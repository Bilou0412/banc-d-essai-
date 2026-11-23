"""Classeur collaboratif hors ligne : réseau simulé, serveur, clients à copie locale."""
import csv
import io
import re
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"


# ------------------------------------------------------------------ temps, réseau

class Clock:
    def __init__(self, start):
        self._t = start.astimezone(UTC)

    def now(self):
        return self._t

    def advance(self, delta):
        self._t = self._t + delta


class Network:
    def __init__(self):
        self.nodes = {}
        self.offline = set()
        self.queue = []

    def register(self, name, node):
        self.nodes[name] = node

    def is_offline(self, name):
        return name in self.offline

    def send(self, src, dst, msg):
        token = [src, dst, msg]
        self.queue.append(token)
        return token

    def cancel(self, token):
        for i, t in enumerate(self.queue):
            if t is token:
                del self.queue[i]
                return True
        return False

    def disconnect(self, name):
        if name in self.offline or name == "server":
            return
        self.offline.add(name)
        srv = self.nodes.get("server")
        if srv is not None:
            srv.on_disconnect(name)

    def reconnect(self, name):
        if name not in self.offline:
            return
        self.offline.discard(name)
        node = self.nodes.get(name)
        if node is not None:
            node.on_reconnect()

    def _deliver(self, token):
        src, dst, msg = token
        if src in self.offline or dst in self.offline:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, msg)

    def deliver_all(self):
        n = 0
        while self.queue and n < 1000000:
            token = self.queue.pop(0)
            n += 1
            self._deliver(token)

    def deliver_from(self, name):
        batch = [t for t in self.queue if t[0] == name]
        for t in batch:
            for i, x in enumerate(self.queue):
                if x is t:
                    del self.queue[i]
                    break
            self._deliver(t)


# ------------------------------------------------------------------ contenus

Cell = namedtuple("Cell", "text tz lit")

DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?$")
NAIVE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
REF_RE = re.compile(r"^[A-Za-z]+\d+$")


def make_cell(text, tz, imported=False):
    if text is None or text == "":
        return None
    t = tz if NAIVE_RE.match(text) else None
    return Cell(text, t, bool(imported and text.startswith("=")))


class CalcErr(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def norm(x):
    if isinstance(x, float) and x == x and x not in (float("inf"), float("-inf")) and x.is_integer():
        return int(x)
    return x


def base_value(cell):
    t = cell.text
    if NUM_RE.match(t):
        return norm(float(t)) if "." in t else int(t)
    if DT_RE.match(t):
        try:
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(cell.tz or "UTC"))
            return dt.astimezone(UTC)
        except Exception:
            return t
    if DATE_RE.match(t):
        try:
            return date.fromisoformat(t)
        except Exception:
            return t
    return t


# ------------------------------------------------------------------ analyseur

TOK = re.compile(r"\s*(?:(?P<sref>\w+)!|(?P<num>\d+(?:\.\d+)?)|(?P<id>[^\W\d_]\w*)|(?P<op>[-+*/(),:]))")
FUNCS = ("SOMME", "MAINTENANT")


class SyntaxErr(Exception):
    pass


def tokenize(s):
    pos = 0
    out = []
    while pos < len(s):
        if s[pos:].strip() == "":
            break
        m = TOK.match(s, pos)
        if not m:
            raise SyntaxErr()
        pos = m.end()
        for k in ("sref", "num", "id", "op"):
            if m.group(k) is not None:
                out.append((k, m.group(k)))
                break
    return out


class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.i != len(self.t):
            raise SyntaxErr()
        return node

    def expr(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek() in (("op", "-"), ("op", "+")):
            op = self.take()[1]
            e = self.unary()
            return ("neg", e) if op == "-" else ("pos", e)
        return self.primary()

    def ref(self):
        sheet = None
        k, v = self.take()
        if k == "sref":
            sheet = v
            k, v = self.take()
        if k != "id" or not REF_RE.match(v):
            raise SyntaxErr()
        return sheet, v.upper()

    def primary(self):
        k, v = self.peek()
        if k == "num":
            self.take()
            return ("num", norm(float(v)) if "." in v else int(v))
        if k == "op" and v == "(":
            self.take()
            e = self.expr()
            if self.take() != ("op", ")"):
                raise SyntaxErr()
            return e
        if k == "id" and self.i + 1 < len(self.t) and self.t[self.i + 1] == ("op", "("):
            self.take()
            self.take()
            name = v.upper()
            if name not in FUNCS:
                raise SyntaxErr()
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            if self.take() != ("op", ")"):
                raise SyntaxErr()
            if name == "MAINTENANT" and args:
                raise SyntaxErr()
            return ("call", name, args)
        if k in ("sref", "id"):
            sheet, r = self.ref()
            if self.peek() == ("op", ":"):
                self.take()
                _, r2 = self.ref()
                return ("range", sheet, r, r2)
            return ("ref", sheet, r)
        raise SyntaxErr()


_PARSE_CACHE = {}


def parse_formula(text):
    got = _PARSE_CACHE.get(text)
    if got is None:
        try:
            got = Parser(tokenize(text[1:])).parse()
        except SyntaxErr:
            got = ("syntax",)
        _PARSE_CACHE[text] = got
    return got


def col_to_n(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def n_to_col(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = re.match(r"^([A-Z]+)(\d+)$", ref)
    return col_to_n(m.group(1)), int(m.group(2))


def range_refs(r1, r2):
    c1, w1 = split_ref(r1)
    c2, w2 = split_ref(r2)
    for c in range(min(c1, c2), max(c1, c2) + 1):
        for w in range(min(w1, w2), max(w1, w2) + 1):
            yield n_to_col(c) + str(w)


def walk(node):
    yield node
    if node[0] in ("bin",):
        yield from walk(node[2])
        yield from walk(node[3])
    elif node[0] in ("neg", "pos"):
        yield from walk(node[1])
    elif node[0] == "call":
        for a in node[2]:
            yield from walk(a)


# ------------------------------------------------------------------ calcul

class Calc:
    """Graphe de dépendances et recalcul incrémental (ordre topologique itératif)."""

    def __init__(self, state, clock):
        self.state = state
        self.clock = clock
        self.ast = {}
        self.deps = {}
        self.rdeps = {}
        self.values = {}
        self.volatile = set()
        self.names = {}
        self.fold = {}

    def _names(self):
        self.names = {s.name: sid for sid, s in self.state.sheets.items()}
        self.fold = {s.name.casefold(): sid for sid, s in self.state.sheets.items()}

    def _sid(self, name, cur):
        if name is None:
            return cur
        sid = self.names.get(name)
        if sid is None:
            sid = self.fold.get(name.casefold())
        return sid

    def full(self):
        self._names()
        self.ast, self.deps, self.rdeps, self.values = {}, {}, {}, {}
        self.volatile = set()
        keys = []
        for sid, sh in self.state.sheets.items():
            for ref in sh.cells:
                keys.append((sid, ref))
        for k in keys:
            self._reparse(k)
        self._evaluate(set(keys))

    def update(self, dirty):
        self._names()
        for k in dirty:
            self._reparse(k)
        affected = set(dirty)
        stack = list(dirty)
        while stack:
            k = stack.pop()
            for d in self.rdeps.get(k, ()):
                if d not in affected:
                    affected.add(d)
                    stack.append(d)
        self._evaluate(affected)

    def refresh_volatile(self):
        if self.volatile:
            self._names()
            affected = set(self.volatile)
            stack = list(affected)
            while stack:
                k = stack.pop()
                for d in self.rdeps.get(k, ()):
                    if d not in affected:
                        affected.add(d)
                        stack.append(d)
            self._evaluate(affected)

    def _cell(self, key):
        sh = self.state.sheets.get(key[0])
        return sh.cells.get(key[1]) if sh else None

    def _reparse(self, key):
        for d in self.deps.pop(key, ()):
            s = self.rdeps.get(d)
            if s:
                s.discard(key)
        self.ast.pop(key, None)
        self.volatile.discard(key)
        cell = self._cell(key)
        if cell is None:
            self.values.pop(key, None)
            return
        if cell.lit or not cell.text.startswith("="):
            self.ast[key] = ("lit", base_value(cell))
            self.deps[key] = set()
            return
        node = parse_formula(cell.text)
        self.ast[key] = node
        deps = set()
        if node[0] != "syntax":
            for n in walk(node):
                if n[0] == "ref":
                    sid = self._sid(n[1], key[0])
                    if sid is not None:
                        deps.add((sid, n[2]))
                elif n[0] == "range":
                    sid = self._sid(n[1], key[0])
                    if sid is not None:
                        for r in range_refs(n[2], n[3]):
                            deps.add((sid, r))
                elif n[0] == "call" and n[1] == "MAINTENANT":
                    self.volatile.add(key)
        self.deps[key] = deps
        for d in deps:
            self.rdeps.setdefault(d, set()).add(key)

    def _evaluate(self, affected):
        indeg = {}
        for k in affected:
            indeg[k] = sum(1 for d in self.deps.get(k, ()) if d in affected)
        ready = [k for k, n in indeg.items() if n == 0]
        done = set()
        while ready:
            k = ready.pop()
            done.add(k)
            self._eval_key(k)
            for d in self.rdeps.get(k, ()):
                if d in indeg and d not in done:
                    indeg[d] -= 1
                    if indeg[d] == 0:
                        ready.append(d)
        for k in affected:
            if k not in done and self._cell(k) is not None:
                self.values[k] = CalcErr("#CIRC!")

    def _eval_key(self, k):
        node = self.ast.get(k)
        if node is None:
            self.values.pop(k, None)
            return
        if node[0] == "lit":
            self.values[k] = node[1]
            return
        if node[0] == "syntax":
            self.values[k] = CalcErr("#SYNTAXE!")
            return
        try:
            v = self._ev(node, k[0])
            if v is None:
                v = 0
            self.values[k] = norm(v)
        except CalcErr as e:
            self.values[k] = e

    def _num(self, v):
        if v is None:
            return 0
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CalcErr("#TYPE!")
        return v

    def _ev(self, n, sid):
        t = n[0]
        if t == "num":
            return n[1]
        if t == "ref":
            s = self._sid(n[1], sid)
            if s is None:
                raise CalcErr("#REF!")
            v = self.values.get((s, n[2]))
            if isinstance(v, CalcErr):
                raise v
            return v
        if t == "range":
            raise CalcErr("#TYPE!")
        if t == "neg":
            return -self._num(self._ev(n[1], sid))
        if t == "pos":
            return self._num(self._ev(n[1], sid))
        if t == "bin":
            a = self._ev(n[2], sid)
            b = self._ev(n[3], sid)
            op = n[1]
            if op == "-" and isinstance(a, (date, datetime)) and isinstance(b, (date, datetime)):
                if isinstance(a, datetime) and isinstance(b, datetime):
                    return (a - b).total_seconds() / 86400
                if not isinstance(a, datetime) and not isinstance(b, datetime):
                    return (a - b).days
                raise CalcErr("#TYPE!")
            x = self._num(a)
            y = self._num(b)
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if y == 0:
                raise CalcErr("#DIV/0!")
            return x / y
        if t == "call":
            if n[1] == "MAINTENANT":
                return self.clock.now()
            total = 0
            for a in n[2]:
                if a[0] == "range":
                    s = self._sid(a[1], sid)
                    if s is None:
                        raise CalcErr("#REF!")
                    for r in range_refs(a[2], a[3]):
                        v = self.values.get((s, r))
                        if v is None:
                            continue
                        if isinstance(v, CalcErr):
                            raise v
                        total += self._num(v)
                else:
                    total += self._num(self._ev(a, sid))
            return total
        raise CalcErr("#TYPE!")


# ------------------------------------------------------------------ état répliqué

class Sheet:
    def __init__(self, name, cells=None, rights=None):
        self.name = name
        self.cells = dict(cells or {})
        self.rights = dict(rights or {})


Conflict = namedtuple("Conflict", "cell by")


class ConflictView:
    def __init__(self, c):
        self.discarded = c.cell.text if c.cell else None
        self.discarded_by = c.by
        self.cell = c.cell


class State:
    def __init__(self, owner=None):
        self.owner = owner
        self.sheets = {"s0": Sheet("Feuille1")}
        self.conflicts = {}
        self.known_names = {"s0": "Feuille1"}

    def copy(self):
        st = State(self.owner)
        st.sheets = {k: Sheet(s.name, s.cells, s.rights) for k, s in self.sheets.items()}
        st.conflicts = dict(self.conflicts)
        st.known_names = dict(self.known_names)
        return st

    def right(self, person, sid):
        sh = self.sheets.get(sid)
        if sh is None:
            return None
        if person == self.owner:
            return W
        return sh.rights.get(person)

    def name_taken(self, name, except_sid=None):
        f = name.casefold()
        return any(s.name.casefold() == f for k, s in self.sheets.items() if k != except_sid)


def rewrite_formulas(st, old, new):
    pat = re.compile(r"(?<!\w)" + re.escape(old) + r"(?=!)", re.IGNORECASE)
    for sh in st.sheets.values():
        for ref, c in list(sh.cells.items()):
            if not c.lit and c.text.startswith("="):
                t = pat.sub(lambda m: new, c.text)
                if t != c.text:
                    sh.cells[ref] = c._replace(text=t)


def apply_effect(st, eff):
    """Applique un effet ; rend (cellules modifiées, structurel)."""
    k = eff[0]
    if k == "cells":
        sh = st.sheets.get(eff[1])
        dirty = set()
        if sh is not None:
            for ref, c in eff[2].items():
                if c is None:
                    sh.cells.pop(ref, None)
                else:
                    sh.cells[ref] = c
                st.conflicts.pop((eff[1], ref), None)
                dirty.add((eff[1], ref))
        return dirty, False
    if k == "conflict":
        if eff[1] in st.sheets:
            st.conflicts[(eff[1], eff[2])] = Conflict(eff[3], eff[4])
        return set(), False
    if k == "clear_conflict":
        st.conflicts.pop((eff[1], eff[2]), None)
        return set(), False
    if k == "add":
        sh = Sheet(eff[2])
        sh.rights[eff[3]] = W
        st.sheets[eff[1]] = sh
        st.known_names[eff[1]] = eff[2]
        return set(), True
    if k == "delete":
        st.sheets.pop(eff[1], None)
        for key in [x for x in st.conflicts if x[0] == eff[1]]:
            del st.conflicts[key]
        return set(), True
    if k == "rename":
        sh = st.sheets.get(eff[1])
        if sh is not None:
            old = sh.name
            sh.name = eff[2]
            st.known_names[eff[1]] = eff[2]
            rewrite_formulas(st, old, eff[2])
        return set(), True
    if k == "replace":
        sh = st.sheets.get(eff[1])
        if sh is not None:
            if eff[2] != sh.name and not st.name_taken(eff[2], eff[1]):
                old = sh.name
                sh.name = eff[2]
                st.known_names[eff[1]] = eff[2]
                rewrite_formulas(st, old, eff[2])
            sh.cells = dict(eff[3])
            for key in [x for x in st.conflicts if x[0] == eff[1]]:
                del st.conflicts[key]
        return set(), True
    if k == "undelete":
        st.sheets[eff[1]] = Sheet(eff[2], eff[3], eff[4])
        st.known_names[eff[1]] = eff[2]
        return set(), True
    if k == "right":
        sh = st.sheets.get(eff[2])
        if sh is not None:
            sh.rights[eff[1]] = eff[3]
        return set(), False
    return set(), False


def naive_effects(op, author):
    t = op["type"]
    if t == "cells":
        return [("cells", op["sid"], op["cells"])]
    if t == "resolve":
        return [("cells", op["sid"], {op["ref"]: op["cell"]}), ("clear_conflict", op["sid"], op["ref"])]
    if t == "add":
        return [("add", op["sid"], op["name"], author)]
    if t == "delete":
        return [("delete", op["sid"])]
    if t == "rename":
        return [("rename", op["sid"], op["name"])]
    if t == "replace":
        return [("replace", op["sid"], op["name"], op["cells"])]
    if t == "undelete":
        return [("undelete", op["sid"], op["name"], op["cells"], op["rights"])]
    if t == "right":
        return [("right", op["person"], op["sid"], op["level"])]
    return []


class Version:
    def __init__(self, id, author, timestamp, kind):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


class VersionRec:
    def __init__(self, seq, author, ts, kind, sid, name, cells):
        self.seq, self.author, self.ts, self.kind = seq, author, ts, kind
        self.sid, self.name, self.cells = sid, name, cells


class Replica:
    def __init__(self, owner=None):
        self.state = State(owner)
        self.versions = []
        self.last_seq = 0

    def apply(self, entry):
        for eff in entry["effects"]:
            apply_effect(self.state, eff)
        v = entry["version"]
        if v is not None:
            sh = self.state.sheets.get(v["sid"])
            if sh is not None:
                self.versions.append(VersionRec(entry["seq"], entry["author"], entry["ts"], v["kind"],
                                                v["sid"], sh.name, dict(sh.cells)))
        self.last_seq = entry["seq"]


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.rep = Replica(owner)
        self.log = []
        self.results = {}
        self.clients = set()
        self.presence = {}
        self.last_mod = {}
        net.register("server", self)

    def on_reconnect(self):
        pass

    def on_disconnect(self, name):
        self.clients.discard(name)
        if self.presence.pop(name, None) is not None:
            for c in self.clients:
                self.net.send("server", c, ("presence", name, None))

    def receive(self, src, msg):
        k = msg[0]
        if k == "op":
            self._process(src, msg[1])
            self.net.send("server", src, self.results[msg[1]["id"]])
        elif k == "hello":
            _, name, last_seq, ops, sel = msg
            self.clients.discard(name)
            for op in ops:
                self._process(name, op)
            self.clients.add(name)
            self.net.send("server", name, ("welcome", self.rep.state.owner))
            for e in self.log[last_seq:]:
                self.net.send("server", name, ("entry", e))
            for op in ops:
                self.net.send("server", name, self.results[op["id"]])
            others = {n: p for n, p in self.presence.items() if n != name}
            self.net.send("server", name, ("presence_all", others))
            if sel is not None:
                self._select(name, sel)
        elif k == "select":
            self._select(src, (msg[1], msg[2]))

    def _select(self, name, sel):
        self.presence[name] = sel
        for c in self.clients:
            if c != name:
                self.net.send("server", c, ("presence", name, sel))

    def _can_write(self, who, sid):
        return self.rep.state.right(who, sid) == W

    def _commit(self, author, op, effects, version):
        seq = self.rep.last_seq + 1
        entry = {"seq": seq, "id": op["id"], "author": author, "ts": op["ts"],
                 "effects": effects, "version": version}
        self.rep.apply(entry)
        self.log.append(entry)
        for c in self.clients:
            self.net.send("server", c, ("entry", entry))
        return seq

    def _process(self, author, op):
        oid = op["id"]
        if oid in self.results:
            return
        st = self.rep.state
        t = op["type"]
        sid = op.get("sid")
        res = ("ack", oid)
        effects = []
        version = None
        marks = []

        def reject(reason, s=None, ref=None):
            return ("reject", oid, reason, s, ref)

        if t in ("cells", "resolve", "delete", "rename", "replace"):
            if st.sheets.get(sid) is None:
                res = reject("gone", sid)
            elif not self._can_write(author, sid):
                first = next(iter(op["cells"]), None) if t == "cells" else op.get("ref")
                res = reject("droit", sid, first)
        if res[0] == "ack":
            if t == "cells":
                sh = st.sheets[sid]
                applied, confl = {}, []
                for ref, new in op["cells"].items():
                    if new == sh.cells.get(ref):
                        continue
                    lm = self.last_mod.get((sid, ref))
                    if lm and lm[1] != author and lm[0] > op["base"]:
                        confl.append(("conflict", sid, ref, new, author))
                    else:
                        applied[ref] = new
                if applied:
                    effects.append(("cells", sid, applied))
                    version = {"kind": "modification", "sid": sid}
                    marks = [(sid, r) for r in applied]
                effects += confl
            elif t == "resolve":
                sh = st.sheets[sid]
                ref = op["ref"]
                if (sid, ref) in st.conflicts:
                    if op["cell"] != sh.cells.get(ref):
                        effects.append(("cells", sid, {ref: op["cell"]}))
                        version = {"kind": "modification", "sid": sid}
                        marks = [(sid, ref)]
                    effects.append(("clear_conflict", sid, ref))
            elif t == "add":
                if sid in st.sheets:
                    pass
                elif st.name_taken(op["name"]):
                    res = reject("nom", sid)
                else:
                    effects = naive_effects(op, author)
            elif t == "delete":
                if len(st.sheets) <= 1:
                    res = reject("last", sid)
                else:
                    effects = naive_effects(op, author)
            elif t == "rename":
                sh = st.sheets[sid]
                if op["name"] == sh.name:
                    pass
                elif st.name_taken(op["name"], sid):
                    res = reject("nom", sid)
                else:
                    effects = naive_effects(op, author)
            elif t == "replace":
                sh = st.sheets[sid]
                effects = naive_effects(op, author)
                version = {"kind": op.get("vkind", "modification"), "sid": sid}
                marks = [(sid, r) for r in set(sh.cells) | set(op["cells"])]
            elif t == "undelete":
                if sid in st.sheets or st.name_taken(op["name"]):
                    res = reject("nom", sid)
                else:
                    effects = naive_effects(op, author)
            elif t == "right":
                sh = st.sheets.get(sid)
                if author != st.owner or sh is None or op["level"] not in (W, R):
                    res = reject("noop", sid)
                elif sh.rights.get(op["person"]) != op["level"]:
                    effects = naive_effects(op, author)
        self.results[oid] = res
        if effects:
            seq = self._commit(author, op, effects, version)
            for m in marks:
                self.last_mod[m] = (seq, author)


# ------------------------------------------------------------------ CSV

class CsvErr(Exception):
    def __init__(self, line):
        Exception.__init__(self, line)
        self.line = line


def parse_csv(text):
    rows, row, field = [], [], []
    inq = False
    line = 1
    rec = 1
    i, n = 0, len(text)
    started = False
    while i < n:
        c = text[i]
        if inq:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    inq = False
            else:
                if c == "\n":
                    line += 1
                field.append(c)
        elif c == '"' and not field and not started:
            inq = True
            started = True
        elif c == ",":
            row.append("".join(field))
            field, started = [], False
        elif c in "\r\n":
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field, started = [], [], False
            line += 1
            rec = line
        else:
            field.append(c)
            started = True
        i += 1
    if inq:
        raise CsvErr(rec)
    if field or row or started:
        row.append("".join(field))
        rows.append(row)
    return rows


# ------------------------------------------------------------------ client

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind, self.sheet, self.cell, self.line = kind, sheet, cell, line

    def __repr__(self):
        return f"Alert({self.kind!r}, {self.sheet!r}, {self.cell!r}, {self.line!r})"


class Device:
    """Stockage persistant de l'appareil."""

    def __init__(self, tz):
        self.rep = Replica(None)
        self.outbox = []
        self.op_n = 0
        self.sheet_n = 0
        self.tz = tz


class Client:
    def __init__(self, net, clock, name, tz="Europe/Paris", _dev=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.dev = _dev if _dev is not None else Device(tz)
        self.undo_stack = []
        self.redo_stack = []
        self._alerts = []
        self.active = None
        self.vopen = None
        self.presence_map = {}
        self.sel = None
        net.register(name, self)
        self._rebuild()
        if not net.is_offline(name):
            self._hello()

    @property
    def tz(self):
        return self.dev.tz

    @property
    def outbox(self):
        return self.dev.outbox

    def set_timezone(self, tz):
        self.dev.tz = tz

    def _online(self):
        return not self.net.is_offline(self.name)

    # -- réseau
    def _hello(self):
        ops = [e["op"] for e in self.outbox]
        self.net.send(self.name, "server", ("hello", self.name, self.dev.rep.last_seq, ops, self.sel))
        for e in self.outbox:
            e["msg"] = "hello"

    def on_reconnect(self):
        self._hello()

    def connection_status(self):
        return "hors ligne" if self.net.is_offline(self.name) else "en ligne"

    def receive(self, src, msg):
        k = msg[0]
        rep = self.dev.rep
        if k == "welcome":
            rep.state.owner = msg[1]
            self._rebuild()
        elif k == "entry":
            e = msg[1]
            if e["seq"] == rep.last_seq + 1:
                rep.apply(e)
                self._prune(e["id"])
                self._rebuild()
        elif k == "ack":
            if self._prune(msg[1]):
                self._rebuild()
        elif k == "reject":
            _, oid, reason, sid, ref = msg
            if self._prune(oid):
                name = self.view.known_names.get(sid, sid)
                if reason == "droit":
                    self._alerts.append(Alert("modification_rejetee", name, ref))
                elif reason == "gone":
                    self._alerts.append(Alert("feuille_supprimee", name))
                elif reason == "nom":
                    self._alerts.append(Alert("nom_existant", name))
                self._rebuild()
        elif k == "presence":
            if msg[2] is None:
                self.presence_map.pop(msg[1], None)
            else:
                self.presence_map[msg[1]] = msg[2]
        elif k == "presence_all":
            self.presence_map = dict(msg[1])

    def _prune(self, oid):
        for i, e in enumerate(self.outbox):
            if e["op"]["id"] == oid:
                del self.outbox[i]
                return True
        return False

    # -- vue locale = confirmé + modifications en attente
    def _rebuild(self):
        view = self.dev.rep.state.copy()
        for e in self.outbox:
            for eff in naive_effects(e["op"], self.name):
                apply_effect(view, eff)
        self.view = view
        self.calc = Calc(view, self.clock)
        self.calc.full()

    def _issue(self, spec, record=None, keep_redo=False):
        op = dict(spec)
        op["id"] = f"{self.name}#{self.dev.op_n}"
        self.dev.op_n += 1
        op["base"] = self.dev.rep.last_seq
        op["ts"] = self.clock.now()
        dirty, struct = set(), False
        for eff in naive_effects(op, self.name):
            d, s = apply_effect(self.view, eff)
            dirty |= d
            struct = struct or s
        if struct:
            self.calc.full()
        elif dirty:
            self.calc.update(dirty)
        entry = {"op": op, "counted": op["type"] != "right", "msg": None}
        self.outbox.append(entry)
        if self._online():
            entry["msg"] = self.net.send(self.name, "server", ("op", op))
        if record is not None:
            record["op_id"] = op["id"]
            self.undo_stack.append(record)
            if not keep_redo:
                self.redo_stack.clear()
        return op

    # -- accès
    def _sid(self, sheet):
        if sheet is None:
            if self.active in self.view.sheets:
                return self.active
            return next(iter(self.view.sheets), None)
        for sid, s in self.view.sheets.items():
            if s.name == sheet:
                return sid
        for sid, s in self.view.sheets.items():
            if s.name.casefold() == sheet.casefold():
                return sid
        return None

    def _name(self, sid):
        return self.view.known_names.get(sid, sid)

    def _write_ok(self, sid, cell=None):
        if self.view.right(self.name, sid) == W:
            return True
        self._alerts.append(Alert("droit_insuffisant", self._name(sid), cell))
        return False

    def alerts(self):
        return list(self._alerts)

    def pending_count(self):
        return sum(1 for e in self.outbox if e["counted"])

    def sheets(self):
        return [s.name for s in self.view.sheets.values()]

    def activate(self, name):
        sid = self._sid(name)
        if sid is not None:
            self.active = sid

    def right(self, person, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        return self.view.right(person, sid)

    # -- lecture des cellules
    def _vstate(self, sid):
        if self.vopen is not None and self.vopen[0].sid == sid:
            return self.vopen[1], self.vopen[2]
        return self.view, self.calc

    def content(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        st, _ = self._vstate(sid)
        c = st.sheets[sid].cells.get(ref.upper())
        return c.text if c else None

    def _raw(self, ref, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        st, calc = self._vstate(sid)
        calc.refresh_volatile()
        return calc.values.get((sid, ref.upper()))

    def value(self, ref, sheet=None):
        v = self._raw(ref, sheet)
        if v is None:
            return None
        if isinstance(v, CalcErr):
            return v.code
        if isinstance(v, datetime):
            return v.astimezone(ZoneInfo(self.tz)).strftime("%Y-%m-%d %H:%M")
        if isinstance(v, date):
            return v.isoformat()
        return v

    def error(self, ref, sheet=None):
        v = self._raw(ref, sheet)
        return v.code if isinstance(v, CalcErr) else None

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        c = self.view.conflicts.get((sid, ref.upper()))
        return ConflictView(c) if c is not None else None

    # -- saisie
    def _cell_now(self, sid, ref):
        return self.view.sheets[sid].cells.get(ref)

    def _write_cells(self, sid, changes):
        diff = {r: c for r, c in changes.items() if c != self._cell_now(sid, r)}
        if not diff:
            return
        old = {r: self._cell_now(sid, r) for r in diff}
        fwd = {"type": "cells", "sid": sid, "cells": diff}
        inv = {"type": "cells", "sid": sid, "cells": old}

        def chk():
            return sid in self.view.sheets and all(self._cell_now(sid, r) == c for r, c in diff.items())

        self._issue(fwd, {"fwd": fwd, "inv": inv, "chk": chk})

    def _entry_cells(self, ref, text, sheet):
        if self.vopen is not None:
            return
        sid = self._sid(sheet)
        ref = ref.upper()
        if sid is None or not REF_RE.match(ref):
            return
        if not self._write_ok(sid, ref):
            return
        self._write_cells(sid, {ref: make_cell(text, self.tz)})

    def set_cell(self, ref, text, sheet=None):
        self._entry_cells(ref, text, sheet)

    def clear(self, ref, sheet=None):
        self._entry_cells(ref, None, sheet)

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.vopen is not None:
            return
        sid = self._sid(sheet)
        ref = ref.upper()
        if sid is None or not self._write_ok(sid, ref):
            return
        cf = self.view.conflicts.get((sid, ref))
        if cf is None:
            return
        cell = cf.cell if use_discarded else self._cell_now(sid, ref)
        self._issue({"type": "resolve", "sid": sid, "ref": ref, "cell": cell})

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return
        self.sel = (sid, ref.upper())
        if self._online():
            self.net.send(self.name, "server", ("select", sid, ref.upper()))

    def presence(self):
        if not self._online():
            return {}
        out = {}
        for who, (sid, ref) in self.presence_map.items():
            if sid in self.view.sheets and who != self.name:
                out[who] = (self.view.sheets[sid].name, ref)
        return out

    # -- feuilles
    def add_sheet(self, name):
        if not name:
            return
        if self.view.name_taken(name):
            self._alerts.append(Alert("nom_existant", name))
            return
        self.dev.sheet_n += 1
        sid = f"{self.name}~{self.dev.sheet_n}"
        fwd = {"type": "add", "sid": sid, "name": name}
        inv = {"type": "delete", "sid": sid}
        self._issue(fwd, {"fwd": fwd, "inv": inv, "chk": lambda: sid in self.view.sheets})

    def delete_sheet(self, name):
        sid = self._sid(name)
        if sid is None or not self._write_ok(sid):
            return
        if len(self.view.sheets) <= 1:
            return
        sh = self.view.sheets[sid]
        fwd = {"type": "delete", "sid": sid}
        inv = {"type": "undelete", "sid": sid, "name": sh.name, "cells": dict(sh.cells),
               "rights": dict(sh.rights)}
        self._issue(fwd, {"fwd": fwd, "inv": inv, "chk": lambda: sid not in self.view.sheets})

    def rename_sheet(self, old, new):
        sid = self._sid(old)
        if sid is None or not new or not self._write_ok(sid):
            return
        cur = self.view.sheets[sid].name
        if new == cur:
            return
        if self.view.name_taken(new, sid):
            self._alerts.append(Alert("nom_existant", new))
            return
        fwd = {"type": "rename", "sid": sid, "name": new}
        inv = {"type": "rename", "sid": sid, "name": cur}

        def chk():
            return sid in self.view.sheets and self.view.sheets[sid].name == new

        self._issue(fwd, {"fwd": fwd, "inv": inv, "chk": chk})

    def set_right(self, person, sheet, level):
        if self.view.owner != self.name or not self._online():
            return
        sid = self._sid(sheet)
        if sid is None or level not in (W, R):
            return
        if self.view.right(person, sid) == level:
            return
        self._issue({"type": "right", "person": person, "sid": sid, "level": level})

    # -- annulation / rétablissement
    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if not self.undo_stack:
            return
        rec = self.undo_stack.pop()
        if rec["chk"] is not None and not rec["chk"]():
            self._alerts.append(Alert("annulation_impossible"))
            return
        inv = rec["inv"]
        sid = inv.get("sid")
        if sid in self.view.sheets and not self._write_ok(sid):
            return
        entry = next((e for e in self.outbox if e["op"]["id"] == rec["op_id"]), None)
        retract = False
        if entry is not None and self.outbox[-1] is entry:
            m = entry["msg"]
            if m is None:
                retract = True
            elif m != "hello" and self.net.cancel(m):
                retract = True
        if retract:
            self.outbox.pop()
            self._rebuild()
        else:
            self._issue(inv)
        self.redo_stack.append(rec)

    def redo(self):
        if not self.redo_stack:
            return
        rec = self.redo_stack.pop()
        fwd = rec["fwd"]
        sid = fwd.get("sid")
        if sid in self.view.sheets and not self._write_ok(sid):
            return
        self._issue(fwd, rec, keep_redo=True)

    def reopen(self):
        return Client(self.net, self.clock, self.name, self.dev.tz, _dev=self.dev)

    # -- historique
    def history(self, sheet=None):
        sid = self._sid(sheet)
        z = ZoneInfo(self.tz)
        vs = [v for v in self.dev.rep.versions if v.sid == sid]
        vs.sort(key=lambda v: (v.ts, v.seq), reverse=True)
        return [Version(v.seq, v.author, v.ts.astimezone(z).strftime("%Y-%m-%d %H:%M"), v.kind) for v in vs]

    def _find_version(self, vid):
        for v in self.dev.rep.versions:
            if v.seq == vid:
                return v
        return None

    def open_version(self, version_id):
        v = self._find_version(version_id)
        if v is None or v.sid not in self.view.sheets:
            return
        st = self.view.copy()
        st.sheets[v.sid].cells = dict(v.cells)
        calc = Calc(st, self.clock)
        calc.full()
        self.vopen = (v, st, calc)

    def close_version(self):
        self.vopen = None

    def restore_version(self, version_id):
        v = self._find_version(version_id)
        if v is None or v.sid not in self.view.sheets:
            return
        self.vopen = None
        sid = v.sid
        if not self._write_ok(sid):
            return
        sh = self.view.sheets[sid]
        fwd = {"type": "replace", "sid": sid, "name": v.name, "cells": dict(v.cells), "vkind": "restauration"}
        inv = {"type": "replace", "sid": sid, "name": sh.name, "cells": dict(sh.cells), "vkind": "modification"}
        self._issue(fwd, {"fwd": fwd, "inv": inv, "chk": lambda: sid in self.view.sheets})

    # -- CSV
    def export_csv(self):
        sid = self._sid(None)
        sh = self.view.sheets[sid]
        self.calc.refresh_volatile()
        z = ZoneInfo(self.tz)
        grid = {}
        maxc = 0
        for ref in sh.cells:
            c, r = split_ref(ref)
            v = self.calc.values.get((sid, ref))
            if isinstance(v, CalcErr):
                s = v.code
            elif isinstance(v, datetime):
                s = v.astimezone(z).isoformat(timespec="seconds")
            elif isinstance(v, date):
                s = v.isoformat()
            elif v is None:
                s = ""
            else:
                s = str(v)
            grid.setdefault(r, {})[c] = s
            maxc = max(maxc, c)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in sorted(grid):
            w.writerow([grid[r].get(c, "") for c in range(1, maxc + 1)])
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        sid = self._sid(None)
        if sid is None or not self._write_ok(sid):
            return
        text = bytes(data).decode("utf-8-sig", errors="replace")
        try:
            rows = parse_csv(text)
        except CsvErr as e:
            self._alerts.append(Alert("csv_invalide", self._name(sid), None, e.line))
            return
        changes = {}
        for i, row in enumerate(rows, start=1):
            for j, f in enumerate(row, start=1):
                changes[n_to_col(j) + str(i)] = make_cell(f, self.tz, True)
        self._write_cells(sid, changes)
