"""Classeur collaboratif hors ligne : réseau simulé, serveur, clients (copie locale par personne)."""
import csv
import io
import json
import re
from collections import deque
from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

W = "écriture"
R = "lecture"
UTC = timezone.utc


# ------------------------------------------------------------------ temps et réseau

class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Network:
    """Réseau en mémoire : file FIFO de messages sérialisés ; une personne coupée ne reçoit ni n'émet."""

    def __init__(self):
        self.nodes = {}
        self.down = set()
        self.queue = deque()

    def register(self, name, node):
        self.nodes[name] = node

    def is_up(self, name):
        return name not in self.down

    def send(self, src, dst, payload):
        if src in self.down or dst in self.down:
            return
        self.queue.append((src, dst, json.dumps(payload)))

    def disconnect(self, name):
        if name in self.down:
            return
        self.down.add(name)
        self.queue = deque(m for m in self.queue if m[0] != name and m[1] != name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_disconnect"):
            node.on_disconnect()
        self.queue.append(("net", "server", json.dumps({"type": "down", "name": name})))

    def reconnect(self, name):
        if name not in self.down:
            return
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_reconnect"):
            node.on_reconnect()

    def _deliver(self, src, dst, data):
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, json.loads(data))

    def deliver_from(self, name):
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "flush"):
            node.flush()
        mine = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for m in mine:
            self._deliver(*m)

    def deliver_all(self):
        for _ in range(100000):
            for node in list(self.nodes.values()):
                if hasattr(node, "flush"):
                    node.flush()
            if not self.queue:
                return
            while self.queue:
                self._deliver(*self.queue.popleft())


# ------------------------------------------------------------------ cellules, références

_REF_RE = re.compile(r"^([A-Za-z]{1,3})([0-9]+)$")


@lru_cache(maxsize=None)
def parse_ref(ref):
    m = _REF_RE.match(ref)
    if not m:
        return (0, 0)
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return (col, int(m.group(2)))


def col_name(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


_NAIVE_DT = re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?\s*$")
_ANY_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUM = re.compile(r"^[-+]?\d+(\.\d+)?$")


def _same(a, b):
    ac = a.get("c") if a else None
    bc = b.get("c") if b else None
    if ac != bc:
        return False
    if ac is None:
        return True
    if bool(a.get("l")) != bool(b.get("l")):
        return False
    if not a.get("l") and _NAIVE_DT.match(ac):
        return a.get("z") == b.get("z")
    return True


def _spec(cell):
    if cell is None or cell.get("c") is None:
        return {"c": None}
    return {"c": cell["c"], "l": cell.get("l", 0), "z": cell.get("z")}


@lru_cache(maxsize=None)
def _zone(name):
    return ZoneInfo(name)


class DT:
    __slots__ = ("inst", "gap")

    def __init__(self, inst, gap):
        self.inst = inst
        self.gap = gap


class D:
    __slots__ = ("d",)

    def __init__(self, d):
        self.d = d


def _const(cell):
    c = cell["c"]
    if cell.get("l"):
        return c
    s = c.strip()
    if _NUM.match(s):
        return float(s) if "." in s else int(s)
    if _ANY_DT.match(s):
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            return c
        if d.tzinfo is not None:
            return DT(d.astimezone(UTC), None)
        z = cell.get("z") or "UTC"
        zi = _zone(z)
        inst = d.replace(tzinfo=zi).astimezone(UTC)
        back = inst.astimezone(zi).replace(tzinfo=None)
        gap = (z, d.strftime("%Y-%m-%d %H:%M")) if back != d else None
        return DT(inst, gap)
    if _DATE.match(s):
        try:
            return D(date.fromisoformat(s))
        except ValueError:
            return c
    return c


# ------------------------------------------------------------------ analyseur de formules

_TOK = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d*)?|\.\d+)|(?P<q>'(?:[^']|'')*')|(?P<id>[^\W\d]\w*)|(?P<op>[-+*/():,!]))")


class _Syn(Exception):
    pass


class _Err(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def tokenize(s):
    toks = []
    pos = 0
    while s[pos:].strip() != "":
        m = _TOK.match(s, pos)
        if not m:
            raise _Syn()
        kind = m.lastgroup
        toks.append((kind, m.group(kind), m.start(kind), m.end(kind)))
        pos = m.end()
    return toks


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def is_op(self, ch):
        t = self.peek()
        return t is not None and t[0] == "op" and t[1] == ch

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise _Syn()
        return node

    def expr(self):
        left = self.term()
        while self.is_op("+") or self.is_op("-"):
            op = self.take()[1]
            left = ("bin", op, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.is_op("*") or self.is_op("/"):
            op = self.take()[1]
            left = ("bin", op, left, self.unary())
        return left

    def unary(self):
        if self.is_op("-"):
            self.take()
            return ("neg", self.unary())
        if self.is_op("+"):
            self.take()
            return self.unary()
        return self.primary()

    def primary(self):
        t = self.take()
        if t is None:
            raise _Syn()
        kind, val = t[0], t[1]
        if kind == "num":
            return ("num", float(val) if "." in val else int(val))
        if kind == "op" and val == "(":
            e = self.expr()
            if not self.is_op(")"):
                raise _Syn()
            self.take()
            return e
        if kind in ("id", "q"):
            if self.is_op("!"):
                self.take()
                sheet = val if kind == "id" else val[1:-1].replace("''", "'")
                t2 = self.take()
                if t2 is None or t2[0] != "id":
                    raise _Syn()
                return self.cellref(sheet, t2[1])
            if kind == "q":
                raise _Syn()
            if self.is_op("("):
                self.take()
                args = []
                if self.is_op(")"):
                    self.take()
                else:
                    while True:
                        args.append(self.expr())
                        if self.is_op(","):
                            self.take()
                            continue
                        if self.is_op(")"):
                            self.take()
                            break
                        raise _Syn()
                return ("call", val.upper(), args)
            return self.cellref(None, val)
        raise _Syn()

    def cellref(self, sheet, text):
        if not _REF_RE.match(text):
            raise _Syn()
        ref = text.upper()
        if self.is_op(":"):
            self.take()
            t2 = self.take()
            if t2 is None or t2[0] != "id" or not _REF_RE.match(t2[1]):
                raise _Syn()
            return ("range", sheet, ref, t2[1].upper())
        return ("ref", sheet, ref)


def _collect_refs(ast):
    out = []
    stack = [ast]
    while stack:
        n = stack.pop()
        k = n[0]
        if k in ("ref", "range"):
            out.append(n)
        elif k == "neg":
            stack.append(n[1])
        elif k == "bin":
            stack.append(n[2])
            stack.append(n[3])
        elif k == "call":
            stack.extend(n[2])
    return out


@lru_cache(maxsize=None)
def parse_formula(text):
    try:
        ast = _Parser(tokenize(text[1:])).parse()
    except _Syn:
        return None
    return (ast, tuple(_collect_refs(ast)))


def _fmt_sheet_name(n):
    if re.fullmatch(r"[^\W\d]\w*", n):
        return n
    return "'" + n.replace("'", "''") + "'"


def rewrite_sheet(text, old, new):
    try:
        toks = tokenize(text[1:])
    except _Syn:
        return text
    oldc = old.casefold()
    out = text
    for i in range(len(toks) - 1, -1, -1):
        kind, val, s, e = toks[i]
        if kind not in ("id", "q"):
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if nxt is None or nxt[0] != "op" or nxt[1] != "!":
            continue
        name = val if kind == "id" else val[1:-1].replace("''", "'")
        if name.casefold() == oldc:
            out = out[:s + 1] + _fmt_sheet_name(new) + out[e + 1:]
    return out


# ------------------------------------------------------------------ évaluation

def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _norm(x):
    if isinstance(x, float) and x == x and abs(x) < 1e15 and x.is_integer():
        return int(x)
    return x


def _arith(op, a, b):
    if _isnum(a) and _isnum(b):
        if op == "+":
            r = a + b
        elif op == "-":
            r = a - b
        elif op == "*":
            r = a * b
        else:
            if b == 0:
                raise _Err("#DIV/0!")
            r = a / b
        return _norm(r)
    if op == "-":
        if isinstance(a, DT) and isinstance(b, DT):
            return _norm((a.inst - b.inst).total_seconds() / 86400)
        if isinstance(a, D) and isinstance(b, D):
            return (a.d - b.d).days
    raise _Err("#TYPE!")


class _Ctx:
    def __init__(self, wb, formulas, results, now):
        self.sheets = wb["sheets"]
        self.names = {sh["name"].casefold(): sid for sid, sh in self.sheets.items()}
        self.formulas = formulas
        self.results = results
        self.now = now
        self.cur = None
        self.cvals = {}
        self._index = {}

    def sid_of(self, sheet):
        if sheet is None:
            return self.cur
        sid = self.names.get(sheet.casefold())
        if sid is None:
            raise _Err("#REF!")
        return sid

    def index(self, sid):
        idx = self._index.get(sid)
        if idx is None:
            idx = []
            for ref, cell in self.sheets[sid]["cells"].items():
                if cell.get("c") is not None:
                    col, row = parse_ref(ref)
                    idx.append((col, row, ref))
            self._index[sid] = idx
        return idx

    def value_at(self, sid, ref):
        key = (sid, ref)
        r = self.results.get(key)
        if r is not None:
            if r[0] == "e":
                raise _Err(r[1])
            return r[1]
        cell = self.sheets[sid]["cells"].get(ref)
        if cell is None or cell.get("c") is None:
            return 0
        if key in self.formulas:
            raise _Err("#CIRC!")
        v = self.cvals.get(key)
        if v is None:
            v = self.cvals[key] = _const(cell)
        return v

    def range_values(self, sheet, a, b):
        sid = self.sid_of(sheet)
        c1, r1 = parse_ref(a)
        c2, r2 = parse_ref(b)
        c1, c2 = min(c1, c2), max(c1, c2)
        r1, r2 = min(r1, r2), max(r1, r2)
        for col, row, ref in self.index(sid):
            if c1 <= col <= c2 and r1 <= row <= r2:
                yield self.value_at(sid, ref)

    def call(self, name, args):
        if name == "SOMME":
            total = 0
            for a in args:
                if a[0] == "range":
                    for v in self.range_values(a[1], a[2], a[3]):
                        if _isnum(v):
                            total += v
                elif a[0] == "ref":
                    v = self.value_at(self.sid_of(a[1]), a[2])
                    if _isnum(v):
                        total += v
                else:
                    v = self.ev(a)
                    if not _isnum(v):
                        raise _Err("#TYPE!")
                    total += v
            return _norm(total)
        if name == "MAINTENANT":
            if args:
                raise _Err("#SYNTAXE!")
            return DT(self.now, None)
        raise _Err("#NOM?")

    def ev(self, node):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            return self.value_at(self.sid_of(node[1]), node[2])
        if k == "range":
            raise _Err("#TYPE!")
        if k == "neg":
            v = self.ev(node[1])
            if _isnum(v):
                return _norm(-v)
            raise _Err("#TYPE!")
        if k == "bin":
            return _arith(node[1], self.ev(node[2]), self.ev(node[3]))
        return self.call(node[1], node[2])


def _scc(edges):
    """Composantes fortement connexes (Tarjan itératif), émises dépendances d'abord."""
    index = {}
    low = {}
    onstack = set()
    stack = []
    out = []
    counter = 0
    for root in edges:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack.add(root)
        work = [(root, iter(edges[root]))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(edges[w])))
                    advanced = True
                    break
                if w in onstack:
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
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(comp)
    return out


def compute(wb, now):
    sheets = wb["sheets"]
    names = {sh["name"].casefold(): sid for sid, sh in sheets.items()}
    formulas = {}
    fidx = {}
    for sid, sh in sheets.items():
        for ref, cell in sh["cells"].items():
            c = cell.get("c")
            if c is None or cell.get("l") or not c.startswith("="):
                continue
            formulas[(sid, ref)] = parse_formula(c)
            col, row = parse_ref(ref)
            fidx.setdefault(sid, []).append((col, row, ref))
    edges = {}
    for key, p in formulas.items():
        out = []
        if p is not None:
            sid = key[0]
            for item in p[1]:
                tsid = sid if item[1] is None else names.get(item[1].casefold())
                if tsid is None:
                    continue
                if item[0] == "ref":
                    k = (tsid, item[2])
                    if k in formulas:
                        out.append(k)
                else:
                    c1, r1 = parse_ref(item[2])
                    c2, r2 = parse_ref(item[3])
                    c1, c2 = min(c1, c2), max(c1, c2)
                    r1, r2 = min(r1, r2), max(r1, r2)
                    for col, row, ref in fidx.get(tsid, ()):
                        if c1 <= col <= c2 and r1 <= row <= r2:
                            out.append((tsid, ref))
        edges[key] = out
    results = {}
    ctx = _Ctx(wb, formulas, results, now)
    for comp in _scc(edges):
        k = comp[0]
        if len(comp) > 1 or k in edges[k]:
            for x in comp:
                results[x] = ("e", "#CIRC!")
            continue
        p = formulas[k]
        if p is None:
            results[k] = ("e", "#SYNTAXE!")
            continue
        ctx.cur = k[0]
        try:
            results[k] = ("v", ctx.ev(p[0]))
        except _Err as e:
            results[k] = ("e", e.code)
    return results


# ------------------------------------------------------------------ classeur partagé (état répliqué)

def new_wb(owner, server):
    wb = {"owner": owner, "sheets": {}, "order": [], "rights": {}, "conflicts": {}, "trash": {},
          "versions": {}, "_vseq": 0}
    if server:
        wb["sheets"]["s0"] = {"name": "Feuille1", "cells": {}}
        wb["order"].append("s0")
        wb["rights"]["s0"] = {}
        wb["versions"]["s0"] = []
    return wb


def level(wb, person, sid):
    if sid not in wb["sheets"]:
        return None
    if person == wb.get("owner"):
        return W
    return wb["rights"].get(sid, {}).get(person)


def _names_taken(wb, name, except_sid=None):
    cf = name.casefold()
    return any(sh["name"].casefold() == cf for s, sh in wb["sheets"].items() if s != except_sid)


def _rename(wb, sid, new):
    sh = wb["sheets"][sid]
    old = sh["name"]
    sh["name"] = new
    pools = list(wb["sheets"].values()) + [e["sheet"] for e in wb["trash"].values()]
    for s in pools:
        for cell in s["cells"].values():
            c = cell.get("c")
            if c and not cell.get("l") and c.startswith("="):
                cell["c"] = rewrite_sheet(c, old, new)


def _find_version(versions, vid):
    for sid, lst in versions.items():
        for v in lst:
            if v["id"] == vid:
                return sid, v
    return None


def _record(wb, sid, author, ts, kind, versions):
    wb["_vseq"] = wb.get("_vseq", 0) + 1
    sh = wb["sheets"][sid]
    snap = {r: {"c": c["c"], "l": c.get("l", 0), "z": c.get("z")}
            for r, c in sh["cells"].items() if c.get("c") is not None}
    versions.setdefault(sid, []).append(
        {"id": wb["_vseq"], "author": author, "ts": ts, "kind": kind, "name": sh["name"], "cells": snap})


def _restore_cells(sh, ver, op_id):
    snap = ver["cells"]
    changed = False
    for ref in set(sh["cells"]) | set(snap):
        cur = sh["cells"].get(ref)
        tgt = snap.get(ref) or {"c": None}
        if _same(cur, tgt):
            continue
        sh["cells"][ref] = {"c": tgt.get("c"), "l": tgt.get("l", 0), "z": tgt.get("z"), "op": op_id}
        changed = True
    return changed


def apply_op(wb, op, author, server, versions):
    """Applique une opération au classeur. server=True : mode autoritaire (conflits, historique)."""
    t = op["t"]
    sid = op.get("sid")
    ok = {"status": "ok"}
    if t == "add":
        name = op["name"]
        if _names_taken(wb, name):
            return {"status": "rejected", "reason": "nom_existant", "sheet": name}
        if sid in wb["sheets"] or sid in wb["trash"]:
            return ok
        wb["sheets"][sid] = {"name": name, "cells": {}}
        wb["order"].append(sid)
        wb["rights"][sid] = {} if author == wb.get("owner") else {author: W}
        if server:
            versions[sid] = []
        return ok

    if t == "undelete":
        ent = wb["trash"].get(sid)
        if ent is None:
            return ok
        sh = ent["sheet"]
        lvl = W if author == wb.get("owner") else ent["rights"].get(author)
        if lvl != W:
            return {"status": "rejected", "reason": "droit", "sheet": sh["name"]}
        if _names_taken(wb, sh["name"]):
            return {"status": "rejected", "reason": "nom_existant", "sheet": sh["name"]}
        del wb["trash"][sid]
        wb["sheets"][sid] = sh
        wb["order"].insert(min(ent["pos"], len(wb["order"])), sid)
        wb["rights"][sid] = ent["rights"]
        if ent["conflicts"]:
            wb["conflicts"][sid] = ent["conflicts"]
        if server:
            versions[sid] = ent.get("versions", [])
        return ok

    sh = wb["sheets"].get(sid)
    if sh is None and t == "restore":
        f = _find_version(versions, op["version"])
        if f is not None:
            sid = f[0]
            sh = wb["sheets"].get(sid)
    if sh is None:
        if t == "delete":
            return ok
        return {"status": "lost", "sheet": op.get("sname")}
    if level(wb, author, sid) != W:
        res = {"status": "rejected", "reason": "droit", "sheet": sh["name"]}
        if t == "set":
            res["cells"] = list(op["cells"])
        return res

    if t == "set":
        changed = False
        confl = wb["conflicts"]
        for ref, new in op["cells"].items():
            cur = sh["cells"].get(ref)
            if _same(cur, new):
                continue
            if server and (cur.get("op") if cur else None) != op["base"].get(ref):
                confl.setdefault(sid, {})[ref] = {"c": new.get("c"), "l": new.get("l", 0),
                                                  "z": new.get("z"), "by": author}
                continue
            sh["cells"][ref] = {"c": new.get("c"), "l": new.get("l", 0), "z": new.get("z"), "op": op["id"]}
            if sid in confl:
                confl[sid].pop(ref, None)
            changed = True
        renamed = False
        rn = op.get("rename")
        if rn and rn != sh["name"] and not _names_taken(wb, rn, sid):
            _rename(wb, sid, rn)
            renamed = True
        if server and (changed or renamed):
            _record(wb, sid, author, op["ts"], "modification", versions)
        return ok

    if t == "delete":
        if len(wb["order"]) <= 1:
            return {"status": "rejected", "reason": "derniere", "sheet": sh["name"]}
        ent = {"sheet": sh, "rights": wb["rights"].pop(sid, {}), "conflicts": wb["conflicts"].pop(sid, {}),
               "pos": wb["order"].index(sid)}
        if server:
            ent["versions"] = versions.pop(sid, [])
        wb["trash"][sid] = ent
        del wb["sheets"][sid]
        wb["order"].remove(sid)
        return ok

    if t == "rename":
        new = op["new"]
        if new == sh["name"]:
            return ok
        if _names_taken(wb, new, sid):
            return {"status": "rejected", "reason": "nom_existant", "sheet": new}
        _rename(wb, sid, new)
        return ok

    if t == "resolve":
        ref = op["ref"]
        cf = wb["conflicts"].get(sid, {}).get(ref)
        if not cf:
            return ok
        wb["conflicts"][sid].pop(ref)
        if op["use"]:
            new = {"c": cf["c"], "l": cf.get("l", 0), "z": cf.get("z")}
            if not _same(sh["cells"].get(ref), new):
                sh["cells"][ref] = dict(new, op=op["id"])
                if server:
                    _record(wb, sid, author, op["ts"], "modification", versions)
        return ok

    if t == "restore":
        f = _find_version(versions, op["version"])
        if f is None:
            return ok
        ver = f[1]
        changed = _restore_cells(sh, ver, op["id"])
        rn = ver.get("name")
        renamed = False
        if rn and rn != sh["name"] and not _names_taken(wb, rn, sid):
            _rename(wb, sid, rn)
            renamed = True
        if changed:
            wb["conflicts"].pop(sid, None)
        if server and (changed or renamed):
            _record(wb, sid, author, op["ts"], "restauration", versions)
        return ok
    return ok


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.wb = new_wb(owner, True)
        self.seen = {}
        self.members = set()
        self.presence = {}
        self.seq = 0
        net.register("server", self)

    def _process(self, author, op):
        oid = op["id"]
        if oid in self.seen:
            return self.seen[oid]
        res = apply_op(self.wb, op, author, True, self.wb["versions"])
        self.seen[oid] = res
        return res

    def receive(self, src, msg):
        t = msg.get("type")
        results = {}
        if t == "hello":
            self.members.add(src)
            for op in msg["ops"]:
                results[op["id"]] = self._process(src, op)
        elif t == "op":
            results[msg["op"]["id"]] = self._process(src, msg["op"])
        elif t == "right":
            if src != self.owner:
                return
            sid, person, lvl = msg["sid"], msg["person"], msg["level"]
            if sid not in self.wb["sheets"] or person == self.owner or lvl not in (W, R, None):
                return
            rights = self.wb["rights"].setdefault(sid, {})
            if rights.get(person) == lvl:
                return
            if lvl is None:
                rights.pop(person, None)
            else:
                rights[person] = lvl
        elif t == "select":
            if msg["sid"] in self.wb["sheets"]:
                self.presence[src] = [msg["sid"], msg["ref"]]
        elif t == "down":
            self.members.discard(msg["name"])
            self.presence.pop(msg["name"], None)
        else:
            return
        self.seq += 1
        for m in sorted(self.members):
            self.net.send("server", m, {"type": "snap", "seq": self.seq, "wb": self.wb,
                                        "presence": self.presence,
                                        "results": results if m == src else {}})


# ------------------------------------------------------------------ client

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line

    def __repr__(self):
        return f"Alert({self.kind!r}, sheet={self.sheet!r}, cell={self.cell!r}, line={self.line!r})"


class Version:
    def __init__(self, id, author, timestamp, kind):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind

    def __repr__(self):
        return f"Version({self.id!r}, {self.author!r}, {self.timestamp!r}, {self.kind!r})"


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


def _parse_csv(text):
    """Renvoie (lignes, None) ou (None, numéro de la ligne où commence l'enregistrement invalide)."""
    rows = []
    row = []
    buf = []
    i = 0
    n = len(text)
    line = 1
    rec_line = 1
    inq = False
    fstart = True
    started = False
    while i < n:
        ch = text[i]
        if inq:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                inq = False
                i += 1
                continue
            if ch == "\n":
                line += 1
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and fstart:
            inq = True
            fstart = False
            started = True
            i += 1
            continue
        if ch == ",":
            row.append("".join(buf))
            buf = []
            fstart = True
            started = True
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if started:
                row.append("".join(buf))
            rows.append(row)
            row = []
            buf = []
            fstart = True
            started = False
            line += 1
            rec_line = line
            i += 1
            continue
        buf.append(ch)
        fstart = False
        started = True
        i += 1
    if inq:
        return None, rec_line
    if started:
        row.append("".join(buf))
        rows.append(row)
    return rows, None


class Client:
    def __init__(self, net, clock, name, tz="UTC", _disk=None):
        self.net = net
        self.clock = clock
        self.name = name
        _zone(tz)
        self.tz = tz
        self._alerts = []
        self._undo = []
        self._redo = []
        self._viewing = None
        self._active = None
        self._presence = {}
        self._misc = []
        self._gen = 0
        self._rc = None
        self._dc = None
        if _disk is None:
            self.confirmed = new_wb(None, False)
            self.pending = []
            self._ctr = 0
            self._seq = 0
        else:
            d = json.loads(_disk)
            self.confirmed = d["confirmed"]
            self.pending = d["pending"]
            self._ctr = d["ctr"]
            self._seq = d["seq"]
            self._active = d["active"]
        self._hello = True
        self.view = None
        self._rebuild()
        net.register(name, self)

    # ---- réseau
    def on_disconnect(self):
        for p in self.pending:
            p["sent"] = False
        self._misc = []

    def on_reconnect(self):
        self._hello = True

    def flush(self):
        if not self.net.is_up(self.name):
            self._misc = []
            return
        if self._hello:
            self._hello = False
            for p in self.pending:
                p["sent"] = True
            self.net.send(self.name, "server", {"type": "hello", "ops": [p["op"] for p in self.pending]})
        else:
            for p in self.pending:
                if not p["sent"]:
                    p["sent"] = True
                    self.net.send(self.name, "server", {"type": "op", "op": p["op"]})
        misc, self._misc = self._misc, []
        for m in misc:
            self.net.send(self.name, "server", m)

    def receive(self, src, msg):
        if msg.get("type") != "snap" or msg["seq"] < self._seq:
            return
        self._seq = msg["seq"]
        self.confirmed = msg["wb"]
        self._presence = msg["presence"]
        for oid, res in msg.get("results", {}).items():
            self._settle(oid, res)
        self._rebuild()

    def _settle(self, oid, res):
        idx = next((i for i, p in enumerate(self.pending) if p["op"]["id"] == oid), None)
        if idx is None:
            return
        op = self.pending.pop(idx)["op"]
        st = res.get("status")
        if st == "ok":
            return
        self._undo = [e for e in self._undo if e.get("op") != oid]
        self._redo = [e for e in self._redo if e.get("op") != oid]
        sheet = res.get("sheet")
        if st == "lost":
            self._alert("feuille_supprimee", sheet)
        elif st == "rejected":
            reason = res.get("reason")
            if reason == "droit":
                if op["t"] == "set":
                    for ref in res.get("cells", []):
                        self._alert("modification_rejetee", sheet, ref)
                elif op["t"] == "resolve":
                    self._alert("modification_rejetee", sheet, op["ref"])
                else:
                    self._alert("droit_insuffisant", sheet)
            elif reason == "nom_existant":
                self._alert("nom_existant", sheet)

    # ---- état local
    def _rebuild(self):
        base = {k: v for k, v in self.confirmed.items() if k != "versions"}
        wb = json.loads(json.dumps(base))
        for p in self.pending:
            apply_op(wb, p["op"], self.name, False, self.confirmed["versions"])
        self.view = wb
        self._touch()

    def _touch(self):
        self._gen += 1

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _oid(self):
        self._ctr += 1
        return f"{self.name}#{self._ctr}"

    def _now_ts(self):
        return self.clock.now().timestamp()

    def _act(self):
        v = self.view
        if self._active in v["sheets"]:
            return self._active
        return v["order"][0] if v["order"] else None

    def _sid(self, sheet):
        if sheet is None:
            return self._act()
        for sid, sh in self.view["sheets"].items():
            if sh["name"] == sheet:
                return sid
        cf = sheet.casefold()
        for sid, sh in self.view["sheets"].items():
            if sh["name"].casefold() == cf:
                return sid
        return None

    def _sname(self, sid):
        return self.view["sheets"][sid]["name"]

    def _guard(self, sid, cell=None):
        if level(self.view, self.name, sid) == W:
            return True
        self._alert("droit_insuffisant", self._sname(sid), cell)
        return False

    def _submit(self, op):
        self.pending.append({"op": op, "sent": False})
        apply_op(self.view, op, self.name, False, self.confirmed["versions"])
        self._touch()

    def _push(self, op, entry):
        entry["op"] = op["id"]
        self._submit(op)
        self._undo.append(entry)
        self._redo = []

    def _retract(self, oid):
        for i, p in enumerate(self.pending):
            if p["op"]["id"] == oid and not p["sent"]:
                del self.pending[i]
                self._rebuild()
                return True
        return False

    def _write(self, sid, cells):
        sh = self.view["sheets"][sid]
        changes = {}
        new = {}
        base = {}
        for ref, spec in cells.items():
            cur = sh["cells"].get(ref)
            if _same(cur, spec):
                continue
            changes[ref] = [_spec(cur), _spec(spec)]
            new[ref] = _spec(spec)
            base[ref] = cur.get("op") if cur else None
        if not new:
            return
        op = {"id": self._oid(), "t": "set", "sid": sid, "sname": sh["name"], "cells": new, "base": base,
              "ts": self._now_ts()}
        self._push(op, {"kind": "cells", "sid": sid, "changes": changes, "names": None})

    # ---- édition
    def set_cell(self, ref, text, sheet=None):
        if self._viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if not self._guard(sid, ref):
            return
        if text is None or text == "":
            spec = {"c": None}
        else:
            spec = {"c": text, "l": 0, "z": self.tz}
        self._write(sid, {ref: spec})

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def import_csv(self, data):
        if self._viewing is not None:
            return
        sid = self._act()
        if sid is None:
            return
        if not self._guard(sid):
            return
        rows, bad = _parse_csv(bytes(data).decode("utf-8-sig", errors="replace"))
        if rows is None:
            self._alert("csv_invalide", self._sname(sid), None, bad)
            return
        cells = {}
        for ri, row in enumerate(rows, start=1):
            for ci, f in enumerate(row, start=1):
                ref = col_name(ci) + str(ri)
                if f == "":
                    cells[ref] = {"c": None}
                else:
                    cells[ref] = {"c": f, "l": 1 if f.startswith("=") else 0, "z": self.tz}
        self._write(sid, cells)

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if not self._guard(sid, ref):
            return
        if not self.view["conflicts"].get(sid, {}).get(ref):
            return
        cur = self.view["sheets"][sid]["cells"].get(ref)
        op = {"id": self._oid(), "t": "resolve", "sid": sid, "sname": self._sname(sid), "ref": ref,
              "use": bool(use_discarded), "base": {ref: cur.get("op") if cur else None},
              "ts": self._now_ts()}
        self._submit(op)

    # ---- feuilles
    def sheets(self):
        return [self.view["sheets"][s]["name"] for s in self.view["order"]]

    def activate(self, name):
        sid = self._sid(name)
        if sid is not None:
            self._active = sid

    def add_sheet(self, name):
        if not name:
            return
        if _names_taken(self.view, name):
            self._alert("nom_existant", name)
            return
        self._ctr += 1
        sid = f"sh-{self.name}-{self._ctr}"
        op = {"id": self._oid(), "t": "add", "sid": sid, "name": name, "ts": self._now_ts()}
        self._push(op, {"kind": "add", "sid": sid, "name": name})

    def delete_sheet(self, name):
        sid = self._sid(name)
        if sid is None:
            return
        if not self._guard(sid):
            return
        if len(self.view["order"]) <= 1:
            return
        op = {"id": self._oid(), "t": "delete", "sid": sid, "ts": self._now_ts()}
        self._push(op, {"kind": "delete", "sid": sid})

    def rename_sheet(self, old, new):
        sid = self._sid(old)
        if sid is None:
            return
        cur = self._sname(sid)
        if new == cur:
            return
        if not self._guard(sid):
            return
        if not new:
            return
        if _names_taken(self.view, new, sid):
            self._alert("nom_existant", new)
            return
        op = {"id": self._oid(), "t": "rename", "sid": sid, "new": new, "ts": self._now_ts()}
        self._push(op, {"kind": "rename", "sid": sid, "old": cur, "new": new})

    # ---- droits
    def right(self, person, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        return level(self.view, person, sid)

    def set_right(self, person, sheet, lvl):
        if self.name != self.view.get("owner") or not self.net.is_up(self.name):
            return
        sid = self._sid(sheet)
        if sid is None or person == self.view.get("owner"):
            return
        if level(self.view, person, sid) == lvl:
            return
        self._misc.append({"type": "right", "sid": sid, "person": person, "level": lvl})

    # ---- lecture
    def _display(self):
        if self._viewing is None:
            return self.view
        if self._dc is not None and self._dc[0] == self._gen:
            return self._dc[1]
        sid, ver = self._viewing
        wb = dict(self.view)
        if sid in self.view["sheets"]:
            sheets = dict(self.view["sheets"])
            cells = {r: {"c": c["c"], "l": c.get("l", 0), "z": c.get("z")} for r, c in ver["cells"].items()}
            sheets[sid] = {"name": self.view["sheets"][sid]["name"], "cells": cells}
            wb["sheets"] = sheets
        self._dc = (self._gen, wb)
        return wb

    def _results(self):
        now = self.clock.now()
        key = (self._gen, now)
        if self._rc is None or self._rc[0] != key:
            self._rc = (key, compute(self._display(), now))
        return self._rc[1]

    def _val(self, sid, ref):
        cell = self._display()["sheets"][sid]["cells"].get(ref)
        if cell is None or cell.get("c") is None:
            return None
        r = self._results().get((sid, ref))
        if r is not None:
            return r
        return ("v", _const(cell))

    def content(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        cell = self._display()["sheets"][sid]["cells"].get(ref.upper())
        return cell["c"] if cell else None

    def _show(self, v):
        if isinstance(v, DT):
            if v.gap is not None and v.gap[0] == self.tz:
                return v.gap[1]
            return v.inst.astimezone(_zone(self.tz)).strftime("%Y-%m-%d %H:%M")
        if isinstance(v, D):
            return v.d.isoformat()
        return v

    def value(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        r = self._val(sid, ref.upper())
        if r is None:
            return None
        if r[0] == "e":
            return r[1]
        return self._show(r[1])

    def error(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        r = self._val(sid, ref.upper())
        if r is not None and r[0] == "e":
            return r[1]
        return None

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        cf = self.view["conflicts"].get(sid, {}).get(ref.upper())
        if not cf:
            return None
        return Conflict(cf["c"], cf["by"])

    def set_timezone(self, tz):
        _zone(tz)
        self.tz = tz

    # ---- état de connexion, présence
    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self.net.is_up(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None or not self.net.is_up(self.name):
            return
        self._misc.append({"type": "select", "sid": sid, "ref": ref.upper()})

    def presence(self):
        if not self.net.is_up(self.name):
            return {}
        out = {}
        for who, (sid, ref) in self._presence.items():
            if who != self.name and sid in self.view["sheets"]:
                out[who] = (self._sname(sid), ref)
        return out

    # ---- annulation / rétablissement
    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def _impossible(self, stack, sid, cell=None):
        stack.pop()
        name = self._sname(sid) if sid in self.view["sheets"] else None
        self._alert("annulation_impossible", name, cell)

    def _cell_op(self, sh, ref):
        c = sh["cells"].get(ref)
        return c.get("op") if c else None

    def undo(self):
        if not self._undo:
            return
        e = self._undo[-1]
        k = e["kind"]
        sid = e["sid"]
        if k == "cells":
            sh = self.view["sheets"].get(sid)
            if sh is None:
                self._undo.pop()
                return
            if not self._guard(sid, next(iter(e["changes"]), None)):
                return
            for ref, (before, after) in e["changes"].items():
                if not _same(sh["cells"].get(ref), after):
                    return self._impossible(self._undo, sid, ref)
            if e["names"] and sh["name"] != e["names"][1]:
                return self._impossible(self._undo, sid)
            self._undo.pop()
            if not self._retract(e["op"]):
                op = {"id": self._oid(), "t": "set", "sid": sid, "sname": sh["name"],
                      "cells": {r: b for r, (b, a) in e["changes"].items()},
                      "base": {r: self._cell_op(sh, r) for r in e["changes"]}, "ts": self._now_ts()}
                if e["names"]:
                    op["rename"] = e["names"][0]
                self._submit(op)
            self._redo.append(dict(e, op=None))
        elif k == "add":
            if sid not in self.view["sheets"]:
                self._undo.pop()
                return
            if not self._guard(sid):
                return
            if len(self.view["order"]) <= 1:
                return self._impossible(self._undo, sid)
            self._undo.pop()
            if self._retract(e["op"]):
                state = "retracted"
            else:
                self._submit({"id": self._oid(), "t": "delete", "sid": sid, "ts": self._now_ts()})
                state = "deleted"
            self._redo.append({"kind": "add", "sid": sid, "name": e["name"], "state": state, "op": None})
        elif k == "delete":
            if sid not in self.view["trash"]:
                self._undo.pop()
                return
            self._undo.pop()
            if not self._retract(e["op"]):
                self._submit({"id": self._oid(), "t": "undelete", "sid": sid, "ts": self._now_ts()})
            self._redo.append({"kind": "delete", "sid": sid, "op": None})
        elif k == "rename":
            sh = self.view["sheets"].get(sid)
            if sh is None:
                self._undo.pop()
                return
            if not self._guard(sid):
                return
            if sh["name"] != e["new"] or _names_taken(self.view, e["old"], sid):
                return self._impossible(self._undo, sid)
            self._undo.pop()
            if not self._retract(e["op"]):
                self._submit({"id": self._oid(), "t": "rename", "sid": sid, "new": e["old"],
                              "ts": self._now_ts()})
            self._redo.append(dict(e, op=None))

    def redo(self):
        if not self._redo:
            return
        e = self._redo[-1]
        k = e["kind"]
        sid = e["sid"]
        if k == "cells":
            sh = self.view["sheets"].get(sid)
            if sh is None:
                self._redo.pop()
                return
            if not self._guard(sid, next(iter(e["changes"]), None)):
                return
            for ref, (before, after) in e["changes"].items():
                if not _same(sh["cells"].get(ref), before):
                    return self._impossible(self._redo, sid, ref)
            if e["names"] and sh["name"] != e["names"][0]:
                return self._impossible(self._redo, sid)
            self._redo.pop()
            op = {"id": self._oid(), "t": "set", "sid": sid, "sname": sh["name"],
                  "cells": {r: a for r, (b, a) in e["changes"].items()},
                  "base": {r: self._cell_op(sh, r) for r in e["changes"]}, "ts": self._now_ts()}
            if e["names"]:
                op["rename"] = e["names"][1]
            self._submit(op)
            self._undo.append(dict(e, op=op["id"]))
        elif k == "add":
            if _names_taken(self.view, e["name"]):
                self._redo.pop()
                self._alert("nom_existant", e["name"])
                return
            self._redo.pop()
            if e["state"] == "retracted":
                op = {"id": self._oid(), "t": "add", "sid": sid, "name": e["name"], "ts": self._now_ts()}
            else:
                op = {"id": self._oid(), "t": "undelete", "sid": sid, "ts": self._now_ts()}
            self._submit(op)
            self._undo.append({"kind": "add", "sid": sid, "name": e["name"], "op": op["id"]})
        elif k == "delete":
            if sid not in self.view["sheets"]:
                self._redo.pop()
                return
            if not self._guard(sid):
                return
            if len(self.view["order"]) <= 1:
                return self._impossible(self._redo, sid)
            self._redo.pop()
            op = {"id": self._oid(), "t": "delete", "sid": sid, "ts": self._now_ts()}
            self._submit(op)
            self._undo.append({"kind": "delete", "sid": sid, "op": op["id"]})
        elif k == "rename":
            sh = self.view["sheets"].get(sid)
            if sh is None:
                self._redo.pop()
                return
            if not self._guard(sid):
                return
            if sh["name"] != e["old"] or _names_taken(self.view, e["new"], sid):
                return self._impossible(self._redo, sid)
            self._redo.pop()
            op = {"id": self._oid(), "t": "rename", "sid": sid, "new": e["new"], "ts": self._now_ts()}
            self._submit(op)
            self._undo.append(dict(e, op=op["id"]))

    # ---- historique des versions
    def history(self, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return []
        tz = _zone(self.tz)
        vs = sorted(self.confirmed["versions"].get(sid, []), key=lambda v: (v["ts"], v["id"]), reverse=True)
        return [Version(v["id"], v["author"],
                        datetime.fromtimestamp(v["ts"], tz).strftime("%Y-%m-%d %H:%M"), v["kind"])
                for v in vs]

    def open_version(self, version_id):
        f = _find_version(self.confirmed["versions"], version_id)
        if f is None:
            return
        self._viewing = f
        self._touch()

    def close_version(self):
        self._viewing = None
        self._touch()

    def restore_version(self, version_id):
        f = _find_version(self.confirmed["versions"], version_id)
        if f is None:
            return
        sid, ver = f
        sh = self.view["sheets"].get(sid)
        if sh is None:
            return
        if not self._guard(sid):
            return
        changes = {}
        snap = ver["cells"]
        for ref in set(sh["cells"]) | set(snap):
            cur = sh["cells"].get(ref)
            tgt = snap.get(ref) or {"c": None}
            if not _same(cur, tgt):
                changes[ref] = [_spec(cur), _spec(tgt)]
        names = None
        rn = ver.get("name")
        if rn and rn != sh["name"] and not _names_taken(self.view, rn, sid):
            names = [sh["name"], rn]
        if not changes and not names:
            return
        op = {"id": self._oid(), "t": "restore", "sid": sid, "sname": sh["name"], "version": version_id,
              "ts": self._now_ts()}
        self._push(op, {"kind": "cells", "sid": sid, "changes": changes, "names": names})

    # ---- CSV
    def export_csv(self):
        sid = self._act()
        if sid is None:
            return b""
        sh = self._display()["sheets"][sid]
        items = {}
        for ref, cell in sh["cells"].items():
            if cell.get("c") is None:
                continue
            col, row = parse_ref(ref)
            items[(row, col)] = ref
        if not items:
            return b""
        maxcol = max(c for (_, c) in items)
        out = io.StringIO()
        wr = csv.writer(out, lineterminator="\n")
        for r in sorted({r for (r, _) in items}):
            wr.writerow([self._field(sid, items.get((r, c))) for c in range(1, maxcol + 1)])
        return out.getvalue().encode("utf-8")

    def _field(self, sid, ref):
        if ref is None:
            return ""
        r = self._val(sid, ref)
        if r is None:
            return ""
        if r[0] == "e":
            return r[1]
        v = r[1]
        if isinstance(v, DT):
            return v.inst.astimezone(_zone(self.tz)).isoformat()
        if isinstance(v, D):
            return v.d.isoformat()
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
        return str(v)

    # ---- appareil
    def reopen(self):
        disk = json.dumps({"confirmed": self.confirmed,
                           "pending": [{"op": p["op"], "sent": False} for p in self.pending],
                           "ctr": self._ctr, "seq": self._seq, "active": self._active})
        return Client(self.net, self.clock, self.name, tz=self.tz, _disk=disk)
