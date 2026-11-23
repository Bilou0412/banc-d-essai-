"""Classeur collaboratif hors ligne : formules, copies locales, réseau simulé, fuseaux."""
import copy
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"


# ====================================================================== valeurs

class Err:
    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return self.code


TYPE, DIV0, SYN, CIRC, REF = (Err("#TYPE!"), Err("#DIV/0!"), Err("#SYNTAXE!"),
                              Err("#CIRC!"), Err("#REF!"))


class Stamp:
    """Instant (UTC). `gap` : texte saisi pour une heure inexistante dans le fuseau `tz`."""

    def __init__(self, utc, gap=None, tz=None):
        self.utc, self.gap, self.tz = utc, gap, tz


@lru_cache(maxsize=None)
def zone(name):
    return ZoneInfo(name)


NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REF_RE = re.compile(r"^([A-Z]+)(\d+)$")


def is_naive_dt(text):
    m = DT_RE.match(text)
    if not m or m.group(2):
        return False
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


@lru_cache(maxsize=None)
def parse_const(text, tz):
    if NUM_RE.match(text):
        return float(text) if "." in text else int(text)
    if DT_RE.match(text):
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return text
        if dt.tzinfo is not None:
            return Stamp(dt.astimezone(UTC))
        z = zone(tz or "UTC")
        local = dt.replace(tzinfo=z)
        utc = local.astimezone(UTC)
        if utc.astimezone(z).replace(tzinfo=None) != dt:
            return Stamp(utc, dt.strftime("%Y-%m-%d %H:%M"), tz or "UTC")
        return Stamp(utc)
    if DATE_RE.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return text
    return text


def is_formula(cell):
    return cell is not None and cell[0].startswith("=") and not cell[2]


def fmt_num(v):
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)
    return str(v)


def norm(v):
    if isinstance(v, float) and v == v and v not in (float("inf"), float("-inf")) and v.is_integer():
        return int(v)
    return v


def fmt_stamp(st, tz):
    if st.gap is not None and st.tz == tz:
        return st.gap
    return st.utc.astimezone(zone(tz)).strftime("%Y-%m-%d %H:%M")


def display_value(v, tz):
    if isinstance(v, Err):
        return v.code
    if isinstance(v, Stamp):
        return fmt_stamp(v, tz)
    if isinstance(v, date):
        return v.isoformat()
    return v


# ====================================================================== analyseur

class SynErr(Exception):
    pass


_TOK = re.compile(r"""\s*(?:
 (?P<ref>(?:(?P<sh>[^\W\d]\w*)!)?(?P<c1>[A-Za-z]+)(?P<r1>\d+)(?::(?P<c2>[A-Za-z]+)(?P<r2>\d+))?(?![\w(]))
|(?P<num>\d+(?:\.\d+)?|\.\d+)
|(?P<fn>[^\W\d]\w*)\s*(?=\()
|(?P<op>[-+*/(),;])
)""", re.X)


def tokenize(s):
    out, pos = [], 0
    while pos < len(s):
        if not s[pos:].strip():
            break
        m = _TOK.match(s, pos)
        if not m:
            raise SynErr()
        pos = m.end()
        if m.group("ref"):
            sh = m.group("sh")
            a = m.group("c1").upper() + m.group("r1")
            if m.group("c2"):
                out.append(("range", sh, a, m.group("c2").upper() + m.group("r2")))
            else:
                out.append(("ref", sh, a))
        elif m.group("num"):
            t = m.group("num")
            out.append(("num", float(t) if "." in t else int(t)))
        elif m.group("fn"):
            out.append(("fn", m.group("fn").upper()))
        else:
            out.append(("op", m.group("op")))
    return out


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def op(self, *ops):
        k = self.peek()
        return k is not None and k[0] == "op" and k[1] in ops

    def expr(self):
        left = self.term()
        while self.op("+", "-"):
            o = self.t[self.i][1]
            self.i += 1
            left = ("bin", o, left, self.term())
        return left

    def term(self):
        left = self.factor()
        while self.op("*", "/"):
            o = self.t[self.i][1]
            self.i += 1
            left = ("bin", o, left, self.factor())
        return left

    def factor(self):
        if self.op("-"):
            self.i += 1
            return ("neg", self.factor())
        if self.op("+"):
            self.i += 1
            return self.factor()
        return self.primary()

    def primary(self):
        k = self.peek()
        if k is None:
            raise SynErr()
        self.i += 1
        if k[0] in ("num", "ref", "range"):
            return k
        if k[0] == "op" and k[1] == "(":
            e = self.expr()
            if not self.op(")"):
                raise SynErr()
            self.i += 1
            return e
        if k[0] == "fn":
            name = k[1]
            if not self.op("("):
                raise SynErr()
            self.i += 1
            args = []
            if not self.op(")"):
                args.append(self.expr())
                while self.op(",", ";"):
                    self.i += 1
                    args.append(self.expr())
            if not self.op(")"):
                raise SynErr()
            self.i += 1
            if name == "SOMME" and args:
                return ("call", name, args)
            if name == "MAINTENANT" and not args:
                return ("call", name, args)
            raise SynErr()
        raise SynErr()


@lru_cache(maxsize=None)
def parse_formula(body):
    try:
        p = Parser(tokenize(body))
        ast = p.expr()
        if p.i != len(p.t):
            raise SynErr()
        return ast
    except SynErr:
        return None


def col_num(c):
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n


def num_col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = REF_RE.match(ref)
    return col_num(m.group(1)), int(m.group(2))


def expand(a, b):
    c1, r1 = split_ref(a)
    c2, r2 = split_ref(b)
    return [num_col(c) + str(r) for r in range(min(r1, r2), max(r1, r2) + 1)
            for c in range(min(c1, c2), max(c1, c2) + 1)]


def ast_cells(ast, out):
    """Collecte (feuille|None, ref) référencés."""
    k = ast[0]
    if k == "ref":
        out.add((ast[1], ast[2]))
    elif k == "range":
        for r in expand(ast[2], ast[3]):
            out.add((ast[1], r))
    elif k == "neg":
        ast_cells(ast[1], out)
    elif k == "bin":
        ast_cells(ast[2], out)
        ast_cells(ast[3], out)
    elif k == "call":
        for a in ast[2]:
            ast_cells(a, out)


def tm(v):
    if isinstance(v, Stamp):
        return v.utc
    return datetime(v.year, v.month, v.day, tzinfo=UTC)


def is_time(v):
    return isinstance(v, (Stamp, date)) and not isinstance(v, datetime)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def arith(o, a, b):
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    if o in "+-" and (is_time(a) or is_time(b)):
        if is_time(a) and is_time(b):
            if o == "-":
                if isinstance(a, date) and isinstance(b, date) and not isinstance(a, Stamp):
                    return (a - b).days
                return (tm(a) - tm(b)).total_seconds() / 86400
            return TYPE
        if is_time(a) and (is_num(b) or b is None):
            d = timedelta(days=(b or 0) if o == "+" else -(b or 0))
            if isinstance(a, Stamp):
                return Stamp(a.utc + d)
            return a + d
        return TYPE
    for v in (a, b):
        if v is not None and not is_num(v):
            return TYPE
    a, b = a or 0, b or 0
    if o == "+":
        return norm(a + b)
    if o == "-":
        return norm(a - b)
    if o == "*":
        return norm(a * b)
    if b == 0:
        return DIV0
    return norm(a / b)


# ====================================================================== classeur

class Sheet:
    def __init__(self, uid, name):
        self.uid, self.name, self.deleted = uid, name, False
        self.cells, self.cellseq, self.cellauth = {}, {}, {}
        self.conflicts, self.rights, self.versions = {}, {}, []

    def copy(self):
        s = Sheet(self.uid, self.name)
        s.deleted = self.deleted
        s.cells, s.cellseq, s.cellauth = dict(self.cells), dict(self.cellseq), dict(self.cellauth)
        s.conflicts, s.rights, s.versions = dict(self.conflicts), dict(self.rights), list(self.versions)
        return s


class Doc:
    def __init__(self, owner):
        self.owner, self.seq = owner, 0
        self.order, self.by = [], {}
        self.ver, self._cache = 0, None

    def copy(self):
        d = Doc(self.owner)
        d.seq = self.seq
        d.order = list(self.order)
        d.by = {u: s.copy() for u, s in self.by.items()}
        return d

    def live(self):
        return [self.by[u] for u in self.order if not self.by[u].deleted]

    def find(self, name):
        for s in self.live():
            if s.name == name:
                return s
        return None

    def name_taken(self, name, except_uid=None):
        low = name.casefold()
        return any(s.name.casefold() == low and s.uid != except_uid for s in self.live())

    def value(self, uid, ref, now):
        s = self.by.get(uid)
        cell = s.cells.get(ref) if s else None
        if cell is None:
            return None
        if is_formula(cell):
            return self._eval_all(now).get((uid, ref))
        return parse_const(cell[0], cell[1])

    def _eval_all(self, now):
        if self._cache is not None and self._cache[0] == (self.ver, now):
            return self._cache[1]
        names = {s.name: s.uid for s in self.live()}
        nodes, asts, home = [], {}, {}
        for s in self.live():
            for ref, cell in s.cells.items():
                if is_formula(cell):
                    n = (s.uid, ref)
                    nodes.append(n)
                    asts[n] = parse_formula(cell[0][1:])
        nodeset = set(nodes)
        edges = {}
        for n in nodes:
            deps = set()
            if asts[n] is not None:
                found = set()
                ast_cells(asts[n], found)
                for sh, ref in found:
                    uid = n[0] if sh is None else names.get(sh)
                    if uid is not None and (uid, ref) in nodeset:
                        deps.add((uid, ref))
            edges[n] = deps
        res = {}

        def lookup(n_home, sh, ref):
            uid = n_home if sh is None else names.get(sh)
            if uid is None:
                return REF
            if (uid, ref) in nodeset:
                return res[(uid, ref)]
            c = self.by[uid].cells.get(ref)
            return None if c is None else parse_const(c[0], c[1])

        def ev(node, h):
            k = node[0]
            if k == "num":
                return node[1]
            if k == "ref":
                return lookup(h, node[1], node[2])
            if k == "range":
                return TYPE
            if k == "neg":
                v = ev(node[1], h)
                if isinstance(v, Err):
                    return v
                if v is None:
                    return 0
                return norm(-v) if is_num(v) else TYPE
            if k == "bin":
                return arith(node[1], ev(node[2], h), ev(node[3], h))
            name, args = node[1], node[2]
            if name == "MAINTENANT":
                return Stamp(now)
            total = 0
            for a in args:
                if a[0] == "range":
                    vals = [lookup(h, a[1], r) for r in expand(a[2], a[3])]
                else:
                    vals = [ev(a, h)]
                for v in vals:
                    if isinstance(v, Err):
                        return v
                    if is_num(v):
                        total += v
            return norm(total)

        for comp in _tarjan(nodes, edges):
            if len(comp) > 1 or comp[0] in edges[comp[0]]:
                for n in comp:
                    res[n] = CIRC
                continue
            n = comp[0]
            if asts[n] is None:
                res[n] = SYN
            else:
                v = ev(asts[n], n[0])
                res[n] = 0 if v is None else v
        self._cache = ((self.ver, now), res)
        return res


def _tarjan(nodes, edges):
    index, low, on, stack, sccs, cnt = {}, {}, set(), [], [], 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = cnt
        cnt += 1
        stack.append(root)
        on.add(root)
        work = [(root, iter(edges[root]))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = cnt
                    cnt += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(edges[w])))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)
    return sccs


def do_rename(doc, s, new):
    old = s.name
    s.name = new
    pat = re.compile(r"(?<![\w!.])" + re.escape(old) + "!")
    for sh in doc.by.values():
        for ref, cell in list(sh.cells.items()):
            if is_formula(cell) and old + "!" in cell[0]:
                sh.cells[ref] = (pat.sub(lambda m: new + "!", cell[0]), cell[1], cell[2])


def apply_op(doc, op, author, seq=None):
    """Applique une opération (effective) à une copie ; `seq` : opération confirmée."""
    doc.ver += 1
    doc._cache = None
    t = op["t"]
    s = doc.by.get(op.get("uid"))
    if t == "add":
        if s:
            s.deleted = False
        else:
            s = Sheet(op["uid"], op["name"])
            if doc.owner:
                s.rights[doc.owner] = W
            s.rights[author] = W
            doc.by[s.uid] = s
            doc.order.append(s.uid)
        return
    if s is None:
        return
    if t == "cells":
        if s.deleted:
            return
        for ref, val in op["cells"].items():
            if val is None:
                s.cells.pop(ref, None)
            else:
                s.cells[ref] = val
            s.conflicts.pop(ref, None)
            if seq is not None:
                s.cellseq[ref], s.cellauth[ref] = seq, author
    elif t == "resolve":
        if s.deleted:
            return
        ref, val = op["ref"], op["cell"]
        if val is None:
            s.cells.pop(ref, None)
        else:
            s.cells[ref] = val
        s.conflicts.pop(ref, None)
        if seq is not None:
            s.cellseq[ref], s.cellauth[ref] = seq, author
    elif t == "delete":
        s.deleted = True
    elif t == "undelete":
        s.deleted = False
    elif t == "rename":
        do_rename(doc, s, op["new"])
    elif t == "restore":
        if s.deleted:
            return
        refs = set(s.cells) | set(op["cells"])
        s.cells = dict(op["cells"])
        s.conflicts = {}
        if seq is not None:
            for r in refs:
                s.cellseq[r], s.cellauth[r] = seq, author
        if op["name"] != s.name:
            do_rename(doc, s, op["name"])
    elif t == "right":
        s.rights[op["person"]] = op["level"]


def apply_entry(doc, e, versions_ready=False):
    apply_op(doc, e["op"], e["author"], e["seq"])
    for c in e["conflicts"]:
        s = doc.by.get(c["uid"])
        if s:
            s.conflicts[c["ref"]] = (c["cell"], c["by"])
    if not versions_ready:
        for uid, v in e["versions"]:
            if uid in doc.by:
                doc.by[uid].versions.append(v)
    doc.seq = e["seq"]


# ====================================================================== temps, réseau

class Clock:
    def __init__(self, start):
        self._t = start.astimezone(UTC)

    def now(self):
        return self._t

    def advance(self, delta):
        self._t = self._t + delta


class Network:
    def __init__(self):
        self.nodes, self.queue, self.down = {}, [], set()

    def register(self, name, node):
        self.nodes[name] = node

    def send(self, src, dst, msg):
        if src in self.down or dst in self.down or dst not in self.nodes:
            return
        self.queue.append((src, dst, copy.deepcopy(msg)))

    def _deliver(self, item):
        src, dst, msg = item
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, msg)

    def deliver_all(self):
        while self.queue:
            self._deliver(self.queue.pop(0))

    def deliver_from(self, name):
        batch = [m for m in self.queue if m[0] == name]
        self.queue = [m for m in self.queue if m[0] != name]
        for m in batch:
            self._deliver(m)

    def disconnect(self, name):
        self.down.add(name)
        self.queue = [m for m in self.queue if m[0] != name and m[1] != name]
        srv = self.nodes.get("server")
        if srv is not None and name != "server":
            srv.peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_reconnect"):
            node.on_reconnect()

    def retract(self, src, opid):
        for i, m in enumerate(self.queue):
            if m[0] == src and m[2][0] == "op" and m[2][1] == opid:
                del self.queue[i]
                return True
        return False


# ====================================================================== serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net, self.clock = net, clock
        self.doc = Doc(owner)
        s = Sheet("s0", "Feuille1")
        s.rights[owner] = W
        self.doc.by["s0"] = s
        self.doc.order.append("s0")
        self.seq = 0
        self.acked, self.rejects, self.presence = set(), {}, {}
        net.register("server", self)

    def _broadcast(self, msg, exclude=None):
        for n in list(self.net.nodes):
            if n != "server" and n != exclude:
                self.net.send("server", n, msg)

    def peer_down(self, name):
        if self.presence.pop(name, None) is not None:
            self._broadcast(("presence", name, None), exclude=name)

    def receive(self, src, msg):
        k = msg[0]
        if k == "hello":
            snap = ("snapshot", self.doc.copy(), set(self.acked),
                    {n: v for n, v in self.presence.items() if n != src})
            self.net.send("server", src, snap)
            for p in msg[1]:
                self._op(src, p["id"], p["op"])
        elif k == "op":
            self._op(src, msg[1], msg[2])
        elif k == "select":
            self.presence[src] = (msg[1], msg[2])
            self._broadcast(("presence", src, (msg[1], msg[2])), exclude=src)

    def _op(self, author, opid, op):
        if opid in self.acked:
            self.net.send("server", author, ("ack", opid))
            return
        if opid in self.rejects:
            self.net.send("server", author, self.rejects[opid])
            return
        r = self._process(author, opid, op)
        if r is None:
            self.acked.add(opid)
            self.net.send("server", author, ("ack", opid))
        elif isinstance(r, tuple):
            self.rejects[opid] = ("reject", opid, r[1], r[2])
            self.net.send("server", author, self.rejects[opid])
        else:
            self.acked.add(opid)
            self._broadcast(("entry", r))

    def _commit(self, author, opid, op, eff, conflicts, vlist):
        self.seq += 1
        seq, doc = self.seq, self.doc
        apply_op(doc, eff, author, seq)
        for c in conflicts:
            doc.by[c["uid"]].conflicts[c["ref"]] = (c["cell"], c["by"])
        versions = []
        for uid, kind in vlist:
            s = doc.by[uid]
            v = {"id": seq, "author": author, "ts": op["ts"], "kind": kind,
                 "name": s.name, "cells": dict(s.cells)}
            s.versions.append(v)
            versions.append((uid, v))
        doc.seq = seq
        return {"seq": seq, "opid": opid, "author": author, "op": eff,
                "conflicts": conflicts, "versions": versions}

    def _process(self, author, opid, op):
        doc, t = self.doc, op["t"]
        uid = op.get("uid")
        s = doc.by.get(uid)

        def rej(reason, **info):
            return ("reject", reason, info)

        if t == "right":
            if (author != doc.owner or s is None or s.deleted or op["person"] == doc.owner
                    or op["level"] not in (W, R)):
                return rej("silencieux")
            if s.rights.get(op["person"]) == op["level"]:
                return None
            return self._commit(author, opid, op, op, [], [])
        if t == "add":
            if s is None:
                if doc.name_taken(op["name"]):
                    return rej("nom_existant", name=op["name"])
                return self._commit(author, opid, op, op, [], [])
            if not s.deleted:
                return None
            op = {"t": "undelete", "uid": uid}
            t = "undelete"
        if s is None:
            return rej("feuille_supprimee", name=None)
        if t == "undelete":
            if not s.deleted:
                return None
            if s.rights.get(author) != W:
                return rej("droit", name=s.name, cells=[])
            if doc.name_taken(s.name, uid):
                return rej("nom_existant", name=s.name)
            return self._commit(author, opid, op, op, [], [])
        if s.deleted:
            return rej("feuille_supprimee", name=s.name)
        if s.rights.get(author) != W:
            refs = list(op["cells"]) if t == "cells" else ([op["ref"]] if t == "resolve" else [])
            return rej("droit", name=s.name, cells=refs)
        if t == "cells":
            applied, conflicts = {}, []
            for ref, val in op["cells"].items():
                if s.cells.get(ref) == val:
                    continue
                if (s.cellseq.get(ref, 0) > op["base"].get(ref, 0)
                        and s.cellauth.get(ref) != author):
                    conflicts.append({"uid": uid, "ref": ref, "cell": val, "by": author})
                else:
                    applied[ref] = val
            if not applied and not conflicts:
                return None
            eff = {"t": "cells", "uid": uid, "cells": applied}
            return self._commit(author, opid, op, eff, conflicts,
                                [(uid, "modification")] if applied else [])
        if t == "resolve":
            if op["ref"] not in s.conflicts:
                return None
            changed = s.cells.get(op["ref"]) != op["cell"]
            return self._commit(author, opid, op, op, [], [(uid, "modification")] if changed else [])
        if t == "delete":
            if len(doc.live()) < 2:
                return rej("derniere")
            return self._commit(author, opid, op, op, [], [])
        if t == "rename":
            if op["new"] == s.name:
                return None
            if doc.name_taken(op["new"], uid):
                return rej("nom_existant", name=op["new"])
            return self._commit(author, opid, op, op, [], [])
        if t == "restore":
            name = op["name"]
            if name != s.name and doc.name_taken(name, uid):
                name = s.name
            eff = {"t": "restore", "uid": uid, "name": name, "cells": op["cells"]}
            return self._commit(author, opid, op, eff, [], [(uid, "restauration")])
        return rej("silencieux")


# ====================================================================== client

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind, self.sheet, self.cell, self.line = kind, sheet, cell, line

    def __repr__(self):
        return f"Alert({self.kind!r}, {self.sheet!r}, {self.cell!r}, {self.line!r})"


class Version:
    def __init__(self, id, author, timestamp, kind):
        self.id, self.author, self.timestamp, self.kind = id, author, timestamp, kind


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded, self.discarded_by = discarded, discarded_by


def parse_csv(text):
    """Renvoie (lignes, ligne_invalide|None)."""
    rows, i, n, line = [], 0, len(text), 1
    while i < n:
        row = []
        while True:
            if i < n and text[i] == '"':
                qline = line
                i += 1
                buf = []
                while True:
                    if i >= n:
                        return rows, qline
                    ch = text[i]
                    if ch == '"':
                        if i + 1 < n and text[i + 1] == '"':
                            buf.append('"')
                            i += 2
                            continue
                        i += 1
                        break
                    if ch == "\n":
                        line += 1
                    buf.append(ch)
                    i += 1
                while i < n and text[i] not in ",\r\n":
                    buf.append(text[i])
                    i += 1
                field = "".join(buf)
            else:
                j = i
                while j < n and text[j] not in ",\r\n":
                    j += 1
                field = text[i:j]
                i = j
            row.append(field)
            if i < n and text[i] == ",":
                i += 1
                continue
            break
        if i < n:
            if text[i] == "\r":
                i += 1
                if i < n and text[i] == "\n":
                    i += 1
            else:
                i += 1
            line += 1
        rows.append(row)
    return rows, None


class Client:
    def __init__(self, net, clock, name, tz="Europe/Paris", _state=None):
        self.net, self.clock, self.name, self.tz = net, clock, name, tz
        self._alerts, self.undo_stack, self.redo_stack = [], [], []
        self.presence_map, self.active = {}, None
        self._view = None
        self._skip_pres = False
        if _state:
            self.confirmed, self.pending = _state["confirmed"], _state["pending"]
            self.counter, self.synced, self._skip_pres = _state["counter"], True, True
        else:
            self.confirmed, self.pending, self.counter, self.synced = Doc(None), [], 0, False
        self._rebuild()
        net.register(name, self)
        self._hello()

    # ---- réseau
    def _hello(self):
        self.net.send(self.name, "server", ("hello", list(self.pending)))

    def on_reconnect(self):
        self._hello()

    def _online(self):
        return self.name not in self.net.down

    def receive(self, src, msg):
        k = msg[0]
        if k == "snapshot":
            _, doc, acked, pres = msg
            self.confirmed, self.synced = doc, True
            self.pending = [p for p in self.pending if p["id"] not in acked]
            if self._skip_pres:
                self.presence_map, self._skip_pres = {}, False
            else:
                self.presence_map = dict(pres)
            self._rebuild()
        elif k == "entry":
            e = msg[1]
            if not self.synced or e["seq"] != self.confirmed.seq + 1:
                return
            apply_entry(self.confirmed, e)
            self.pending = [p for p in self.pending if p["id"] != e["opid"]]
            self._rebuild()
        elif k == "ack":
            self.pending = [p for p in self.pending if p["id"] != msg[1]]
            self._rebuild()
        elif k == "reject":
            _, opid, reason, info = msg
            p = next((p for p in self.pending if p["id"] == opid), None)
            if p is None:
                return
            name = info.get("name")
            if name is None:
                s = self.display.by.get(p["op"].get("uid"))
                name = s.name if s else None
            self.pending = [q for q in self.pending if q["id"] != opid]
            self._rebuild()
            if reason == "droit":
                cells = info.get("cells") or []
                self._alerts.append(Alert("modification_rejetee", name,
                                          cells[0] if len(cells) == 1 else None))
            elif reason == "feuille_supprimee":
                self._alerts.append(Alert("feuille_supprimee", name))
            elif reason == "nom_existant":
                self._alerts.append(Alert("nom_existant", info.get("name")))
        elif k == "presence":
            if msg[2] is None:
                self.presence_map.pop(msg[1], None)
            elif msg[1] != self.name:
                self.presence_map[msg[1]] = msg[2]

    def _rebuild(self):
        d = self.confirmed.copy()
        for p in self.pending:
            apply_op(d, p["op"], self.name)
        self.display = d

    def _newid(self):
        self.counter += 1
        return f"{self.name}:{self.counter}"

    def _submit(self, op):
        opid = self._newid()
        self.pending.append({"id": opid, "op": op})
        apply_op(self.display, op, self.name)
        self.net.send(self.name, "server", ("op", opid, op))
        return opid

    # ---- accès
    def _readdoc(self):
        return self._view if self._view is not None else self.display

    def _active(self, doc):
        live = doc.live()
        for s in live:
            if s.uid == self.active:
                return s
        return live[0] if live else None

    def _sheet(self, sheet, doc=None):
        doc = doc or self.display
        return self._active(doc) if sheet is None else doc.find(sheet)

    def _deny(self, s, cell=None):
        self._alerts.append(Alert("droit_insuffisant", s.name, cell))

    def _can_write(self, s):
        return s.rights.get(self.name) == W

    def _mk(self, text, lit=False):
        if text is None or text == "":
            return None
        return (text, self.tz if is_naive_dt(text) else None, lit and text.startswith("="))

    def _cell_op(self, uid, cells):
        cs = self.confirmed.by.get(uid)
        base = {r: (cs.cellseq.get(r, 0) if cs else 0) for r in cells}
        return {"t": "cells", "uid": uid, "cells": cells, "base": base, "ts": self.clock.now()}

    def _push(self, opid, fwd, inv, check=None):
        self.undo_stack.append({"opid": opid, "fwd": fwd, "inv": inv, "check": check})
        self.redo_stack = []

    def _write(self, s, cells):
        changed = {r: v for r, v in cells.items() if s.cells.get(r) != v}
        if not changed:
            return
        prev = {r: s.cells.get(r) for r in changed}
        op = self._cell_op(s.uid, changed)
        opid = self._submit(op)
        self._push(opid, op, {"t": "cells", "uid": s.uid, "cells": prev}, (s.uid, dict(changed)))

    def _reissue(self, op):
        o = dict(op)
        o["ts"] = self.clock.now()
        if o["t"] == "cells":
            o["base"] = self._cell_op(o["uid"], o["cells"])["base"]
        return o

    # ---- lecture
    def content(self, ref, sheet=None):
        d = self._readdoc()
        s = self._sheet(sheet, d)
        c = s.cells.get(ref.upper()) if s else None
        return c[0] if c else None

    def _raw(self, ref, sheet):
        d = self._readdoc()
        s = self._sheet(sheet, d)
        if s is None:
            return None
        return d.value(s.uid, ref.upper(), self.clock.now())

    def value(self, ref, sheet=None):
        return display_value(self._raw(ref, sheet), self.tz)

    def error(self, ref, sheet=None):
        v = self._raw(ref, sheet)
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        self.tz = tz

    def sheets(self):
        return [s.name for s in self.display.live()]

    def activate(self, name):
        s = self.display.find(name)
        if s:
            self.active = s.uid

    def right(self, person, sheet):
        s = self.display.find(sheet)
        return s.rights.get(person) if s else None

    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self._online() else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def presence(self):
        return dict(self.presence_map) if self._online() else {}

    def conflict(self, ref, sheet=None):
        s = self._sheet(sheet)
        cf = s.conflicts.get(ref.upper()) if s else None
        if cf is None:
            return None
        return Conflict(cf[0][0] if cf[0] else None, cf[1])

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    # ---- écriture
    def select(self, ref, sheet=None):
        s = self._sheet(sheet)
        if s:
            self.net.send(self.name, "server", ("select", s.name, ref.upper()))

    def set_cell(self, ref, text, sheet=None):
        self._edit(ref, self._mk(text), sheet)

    def clear(self, ref, sheet=None):
        self._edit(ref, None, sheet)

    def _edit(self, ref, cell, sheet):
        if self._view is not None:
            return
        s = self._sheet(sheet)
        if s is None:
            return
        ref = ref.upper()
        if not self._can_write(s):
            self._deny(s, ref)
            return
        self._write(s, {ref: cell})

    def add_sheet(self, name):
        if self._view is not None or not name:
            return
        if self.display.name_taken(name):
            self._alerts.append(Alert("nom_existant", name))
            return
        self.counter += 1
        uid = f"{self.name}:s{self.counter}"
        op = {"t": "add", "uid": uid, "name": name}
        opid = self._submit(op)
        self._push(opid, op, {"t": "delete", "uid": uid})

    def delete_sheet(self, name):
        s = self.display.find(name)
        if s is None or self._view is not None:
            return
        if not self._can_write(s):
            self._deny(s)
            return
        if len(self.display.live()) < 2:
            return
        op = {"t": "delete", "uid": s.uid}
        opid = self._submit(op)
        self._push(opid, op, {"t": "undelete", "uid": s.uid})

    def rename_sheet(self, old, new):
        s = self.display.find(old)
        if s is None or self._view is not None or old == new:
            return
        if not self._can_write(s):
            self._deny(s)
            return
        if self.display.name_taken(new, s.uid):
            self._alerts.append(Alert("nom_existant", new))
            return
        op = {"t": "rename", "uid": s.uid, "new": new}
        opid = self._submit(op)
        self._push(opid, op, {"t": "rename", "uid": s.uid, "new": old})

    def set_right(self, person, sheet, level):
        owner = self.confirmed.owner
        if self.name != owner or not self._online() or person == owner or level not in (W, R):
            return
        s = self.display.find(sheet)
        if s is None or s.rights.get(person) == level:
            return
        self.net.send(self.name, "server", ("op", self._newid(),
                      {"t": "right", "uid": s.uid, "person": person, "level": level}))

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self._view is not None:
            return
        s = self._sheet(sheet)
        if s is None:
            return
        ref = ref.upper()
        if not self._can_write(s):
            self._deny(s, ref)
            return
        cf = s.conflicts.get(ref)
        if cf is None:
            return
        cell = cf[0] if use_discarded else s.cells.get(ref)
        self._submit({"t": "resolve", "uid": s.uid, "ref": ref, "cell": cell,
                      "ts": self.clock.now()})

    # ---- annuler / rétablir
    def undo(self):
        if self._view is not None or not self.undo_stack:
            return
        e = self.undo_stack[-1]
        s = self.display.by.get(e["fwd"]["uid"])
        if s is None:
            self.undo_stack.pop()
            return
        if not self._can_write(s):
            self._deny(s)
            return
        if e["check"]:
            for r, v in e["check"][1].items():
                if s.cells.get(r) != v:
                    self._alerts.append(Alert("annulation_impossible", s.name, r))
                    self.undo_stack.pop()
                    return
        self.undo_stack.pop()
        if any(p["id"] == e["opid"] for p in self.pending) and \
                (not self._online() or self.net.retract(self.name, e["opid"])):
            self.pending = [p for p in self.pending if p["id"] != e["opid"]]
            self._rebuild()
        else:
            self._submit(self._reissue(e["inv"]))
        self.redo_stack.append(e)

    def redo(self):
        if self._view is not None or not self.redo_stack:
            return
        e = self.redo_stack[-1]
        s = self.display.by.get(e["fwd"]["uid"])
        if s is None:
            self.redo_stack.pop()
            return
        if not self._can_write(s):
            self._deny(s)
            return
        self.redo_stack.pop()
        fwd = self._reissue(e["fwd"])
        opid = self._submit(fwd)
        self.undo_stack.append({"opid": opid, "fwd": fwd, "inv": e["inv"], "check": e["check"]})

    # ---- historique
    def history(self, sheet=None):
        s = self._sheet(sheet, self.confirmed)
        if s is None:
            return []
        vs = sorted(s.versions, key=lambda v: (v["ts"], v["id"]), reverse=True)
        z = zone(self.tz)
        return [Version(v["id"], v["author"], v["ts"].astimezone(z).strftime("%Y-%m-%d %H:%M"),
                        v["kind"]) for v in vs]

    def _find_version(self, vid):
        for s in self.confirmed.by.values():
            for v in s.versions:
                if v["id"] == vid:
                    return s.uid, v
        return None, None

    def open_version(self, vid):
        uid, v = self._find_version(vid)
        if v is None:
            return
        d = self.display.copy()
        if uid in d.by:
            d.by[uid].cells = dict(v["cells"])
        self._view = d

    def close_version(self):
        self._view = None

    def restore_version(self, vid):
        if self._view is not None:
            return
        uid, v = self._find_version(vid)
        s = self.display.by.get(uid) if v is not None else None
        if s is None:
            return
        if not self._can_write(s):
            self._deny(s)
            return
        op = {"t": "restore", "uid": uid, "name": v["name"], "cells": dict(v["cells"]),
              "ts": self.clock.now()}
        inv = {"t": "restore", "uid": uid, "name": s.name, "cells": dict(s.cells)}
        opid = self._submit(op)
        self._push(opid, op, inv)

    # ---- CSV
    def _csv_text(self, v):
        if isinstance(v, Err):
            return v.code
        if isinstance(v, Stamp):
            return v.utc.astimezone(zone(self.tz)).isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if v is None:
            return ""
        if is_num(v):
            return fmt_num(v)
        return v

    def export_csv(self):
        d = self._readdoc()
        s = self._active(d)
        if s is None:
            return b""
        now = self.clock.now()
        grid = {}
        for ref in s.cells:
            c, r = split_ref(ref)
            grid[(r, c)] = self._csv_text(d.value(s.uid, ref, now))
        if not grid:
            return b""
        maxc = max(c for _, c in grid)
        out = io.StringIO()
        w = csv.writer(out)
        for r in sorted({r for r, _ in grid}):
            w.writerow([grid.get((r, c), "") for c in range(1, maxc + 1)])
        return out.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self._view is not None:
            return
        s = self._active(self.display)
        if s is None:
            return
        if not self._can_write(s):
            self._deny(s)
            return
        text = data.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]
        rows, bad = parse_csv(text)
        if bad is not None:
            self._alerts.append(Alert("csv_invalide", s.name, None, bad))
            return
        cells = {}
        for r, row in enumerate(rows, 1):
            for c, f in enumerate(row, 1):
                cells[num_col(c) + str(r)] = self._mk(f, lit=True)
        self._write(s, cells)

    # ---- appareil
    def reopen(self):
        state = {"confirmed": self.confirmed.copy(), "pending": copy.deepcopy(self.pending),
                 "counter": self.counter}
        return Client(self.net, self.clock, self.name, self.tz, _state=state)
