"""Classeur collaboratif hors ligne : formules, réseau simulé, fusion serveur, fuseaux, CSV."""
import csv
import io
import pickle
import re
import sys
from collections import deque
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

sys.setrecursionlimit(20000)

UTC = timezone.utc
W = "écriture"
R = "lecture"


# ====================================================================== temps

class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


# ====================================================================== formules

class Err:
    def __init__(self, code):
        self.code = code


E_TYPE = Err("#TYPE!")
E_DIV = Err("#DIV/0!")
E_SYN = Err("#SYNTAXE!")
E_CIRC = Err("#CIRC!")
E_REF = Err("#REF!")


class _Syntax(Exception):
    pass


_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<sref>(?P<sname>\w+)!(?P<scell>[A-Za-z]+\d+)(?::(?P<scell2>[A-Za-z]+\d+))?(?![\w(]))
  | (?P<func>[^\W\d_]\w*)(?=\()
  | (?P<ref>(?P<c1>[A-Za-z]+\d+)(?::(?P<c2>[A-Za-z]+\d+))?(?![\w(]))
  | (?P<num>\d+(?:\.\d+)?)(?![\w.])
  | (?P<op>[-+*/(),])
""", re.X)


def _scan(text, pos=0):
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if m is None:
            raise _Syntax()
        pos = m.end()
        if m.group("ws") is not None:
            continue
        if m.group("sref") is not None:
            yield "sref", m
        elif m.group("func") is not None:
            yield "func", m
        elif m.group("ref") is not None:
            yield "ref", m
        elif m.group("num") is not None:
            yield "num", m
        else:
            yield "op", m


def _tokenize(body):
    toks = []
    for kind, m in _scan(body):
        if kind == "sref":
            c2 = m.group("scell2")
            toks.append(("ref", m.group("sname"), m.group("scell").upper(), c2.upper() if c2 else None))
        elif kind == "ref":
            c2 = m.group("c2")
            toks.append(("ref", None, m.group("c1").upper(), c2.upper() if c2 else None))
        elif kind == "func":
            toks.append(("func", m.group("func").upper()))
        elif kind == "num":
            s = m.group("num")
            toks.append(("num", float(s) if "." in s else int(s)))
        else:
            toks.append(("op", m.group("op")))
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def is_op(self, chars):
        t = self.peek()
        return t is not None and t[0] == "op" and t[1] in chars

    def expect(self, ch):
        if not self.is_op(ch):
            raise _Syntax()
        self.i += 1

    def expr(self):
        left = self.term()
        while self.is_op("+-"):
            op = self.t[self.i][1]
            self.i += 1
            left = ("bin", op, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.is_op("*/"):
            op = self.t[self.i][1]
            self.i += 1
            left = ("bin", op, left, self.unary())
        return left

    def unary(self):
        if self.is_op("+-"):
            op = self.t[self.i][1]
            self.i += 1
            operand = self.unary()
            return ("neg", operand) if op == "-" else operand
        return self.primary()

    def primary(self):
        t = self.peek()
        if t is None:
            raise _Syntax()
        k = t[0]
        if k == "num":
            self.i += 1
            return ("num", t[1])
        if k == "ref":
            self.i += 1
            if t[3]:
                return ("range", t[1], t[2], t[3])
            return ("ref", t[1], t[2])
        if k == "func":
            name = t[1]
            self.i += 1
            self.expect("(")
            args = []
            if self.is_op(")"):
                self.i += 1
            else:
                while True:
                    args.append(self.expr())
                    if self.is_op(","):
                        self.i += 1
                        continue
                    self.expect(")")
                    break
            if name == "SOMME" and len(args) >= 1:
                return ("call", name, args)
            if name == "MAINTENANT" and not args:
                return ("call", name, args)
            raise _Syntax()
        if k == "op" and t[1] == "(":
            self.i += 1
            e = self.expr()
            self.expect(")")
            return e
        raise _Syntax()


@lru_cache(maxsize=8192)
def parse_formula(text):
    """Rend l'arbre de la formule (texte commençant par '='), ou None si la syntaxe est invalide."""
    try:
        toks = _tokenize(text[1:])
        p = _Parser(toks)
        node = p.expr()
        if p.i != len(toks):
            return None
        return node
    except _Syntax:
        return None


def rewrite_sheet_name(text, old, new):
    if not text.startswith("="):
        return text
    try:
        scanned = list(_scan(text, 1))
    except _Syntax:
        return text
    oldf = old.casefold()
    out = []
    last = 0
    for kind, m in scanned:
        if kind == "sref" and m.group("sname").casefold() == oldf:
            out.append(text[last:m.start("sname")])
            out.append(new)
            last = m.end("sname")
    out.append(text[last:])
    return "".join(out)


@lru_cache(maxsize=65536)
def coords(ref):
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return col, int(m.group(2))


def col_name(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _norm_ref(ref):
    r = ref.strip().upper()
    return r if re.fullmatch(r"[A-Z]+\d+", r) else None


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_temporal(v):
    return isinstance(v, date)


def _norm(x):
    if isinstance(x, float) and x == x and abs(x) < 1e15 and x.is_integer():
        return int(x)
    return x


def _arith(op, a, b):
    if a is None:
        a = 0
    if b is None:
        b = 0
    ta = _is_temporal(a)
    tb = _is_temporal(b)
    if ta or tb:
        if op == "-" and ta and tb:
            if isinstance(a, datetime) and isinstance(b, datetime):
                return _norm((a - b).total_seconds() / 86400)
            if not isinstance(a, datetime) and not isinstance(b, datetime):
                return (a - b).days
            return E_TYPE
        if op in "+-":
            if ta and _is_num(b):
                d = timedelta(days=b)
                return a + d if op == "+" else a - d
            if tb and _is_num(a) and op == "+":
                return b + timedelta(days=a)
        return E_TYPE
    if not (_is_num(a) and _is_num(b)):
        return E_TYPE
    if op == "+":
        return _norm(a + b)
    if op == "-":
        return _norm(a - b)
    if op == "*":
        return _norm(a * b)
    if b == 0:
        return E_DIV
    return _norm(a / b)


class Evaluator:
    """Recalcul qui suit le graphe des dépendances (ordre topologique, cycles détectés sur le graphe)."""

    def __init__(self, state, now):
        self.state = state
        self.now = now
        self.memo = {}
        self.by_name = {s.name.casefold(): s for s in state.sheets}

    def _target(self, sh, name):
        if name is None:
            return sh
        return self.by_name.get(name.casefold())

    def _range_refs(self, sh, r1, r2):
        c1, w1 = coords(r1)
        c2, w2 = coords(r2)
        lo_c, hi_c = min(c1, c2), max(c1, c2)
        lo_r, hi_r = min(w1, w2), max(w1, w2)
        out = []
        for ref, c in sh.cells.items():
            if c[0] is None:
                continue
            col, row = coords(ref)
            if lo_c <= col <= hi_c and lo_r <= row <= hi_r:
                out.append(ref)
        return out

    def _deps(self, sh, ast):
        out = []
        stack = [ast]
        while stack:
            n = stack.pop()
            t = n[0]
            if t == "ref":
                target = self._target(sh, n[1])
                if target is not None:
                    out.append((target, n[2]))
            elif t == "range":
                target = self._target(sh, n[1])
                if target is not None:
                    for r in self._range_refs(target, n[2], n[3]):
                        out.append((target, r))
            elif t == "neg":
                stack.append(n[1])
            elif t == "bin":
                stack.append(n[2])
                stack.append(n[3])
            elif t == "call":
                stack.extend(n[2])
        return out

    @staticmethod
    def _plain(c):
        k = c[0]
        p = c[1]
        if k == "n":
            return _norm(float(p) if "." in p else int(p))
        if k == "d":
            return date.fromisoformat(p)
        if k == "dt":
            return datetime.fromisoformat(p)
        return p

    def get(self, sh, ref):
        key = (sh.id, ref)
        if key not in self.memo:
            self._compute(sh, ref)
        return self.memo[key]

    def _compute(self, sh0, ref0):
        memo = self.memo
        nodes = {}
        stack = [(sh0, ref0)]
        while stack:
            sh, ref = stack.pop()
            key = (sh.id, ref)
            if key in memo or key in nodes:
                continue
            c = sh.cells.get(ref)
            if c is None or c[0] is None:
                memo[key] = None
                continue
            if c[0] != "f":
                memo[key] = self._plain(c)
                continue
            ast = parse_formula(c[1])
            if ast is None:
                memo[key] = E_SYN
                continue
            deps = self._deps(sh, ast)
            nodes[key] = (sh, ast, deps)
            for dsh, dref in deps:
                dk = (dsh.id, dref)
                if dk not in memo and dk not in nodes:
                    stack.append((dsh, dref))
        waiting = {}
        dependents = {}
        for key, (sh, ast, deps) in nodes.items():
            pend = set()
            for dsh, dref in deps:
                dk = (dsh.id, dref)
                if dk in nodes:
                    pend.add(dk)
            waiting[key] = pend
            for dk in pend:
                dependents.setdefault(dk, []).append(key)
        ready = [k for k, p in waiting.items() if not p]
        while ready:
            k = ready.pop()
            sh, ast, _ = nodes[k]
            v = self._ev(sh, ast)
            memo[k] = 0 if v is None else v
            for d in dependents.get(k, ()):
                w = waiting[d]
                w.discard(k)
                if not w:
                    ready.append(d)
        for key in nodes:
            if key not in memo:
                memo[key] = E_CIRC

    def _ev(self, sh, node):
        t = node[0]
        if t == "num":
            return node[1]
        if t == "ref":
            target = self._target(sh, node[1])
            if target is None:
                return E_REF
            return self.memo.get((target.id, node[2]))
        if t == "range":
            target = self._target(sh, node[1])
            if target is None:
                return E_REF
            return E_TYPE
        if t == "neg":
            v = self._ev(sh, node[1])
            if isinstance(v, Err):
                return v
            if v is None:
                return 0
            if _is_num(v):
                return _norm(-v)
            return E_TYPE
        if t == "bin":
            a = self._ev(sh, node[2])
            if isinstance(a, Err):
                return a
            b = self._ev(sh, node[3])
            if isinstance(b, Err):
                return b
            return _arith(node[1], a, b)
        # appel de fonction
        name, args = node[1], node[2]
        if name == "MAINTENANT":
            return self.now
        total = 0
        for a in args:
            if a[0] == "range":
                target = self._target(sh, a[1])
                if target is None:
                    return E_REF
                for ref in self._range_refs(target, a[2], a[3]):
                    v = self.memo.get((target.id, ref))
                    if isinstance(v, Err):
                        return v
                    if _is_num(v):
                        total += v
            else:
                v = self._ev(sh, a)
                if isinstance(v, Err):
                    return v
                if _is_num(v):
                    total += v
        return _norm(total)


# ====================================================================== modèle

class Sheet:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.cells = {}       # ref -> (kind, payload, rev, author) ; kind None = effacée
        self.rights = {}
        self.conflicts = {}   # ref -> (cellule écartée | None, auteur)
        self.versions = []    # (id, auteur, ts, nature, nom, changements)

    def copy(self):
        s = Sheet(self.id, self.name)
        s.cells = dict(self.cells)
        s.rights = dict(self.rights)
        s.conflicts = dict(self.conflicts)
        s.versions = list(self.versions)
        return s


class State:
    def __init__(self, owner, sheets):
        self.owner = owner
        self.sheets = sheets

    def find(self, sid):
        for s in self.sheets:
            if s.id == sid:
                return s
        return None

    def name_taken(self, name, exclude=None):
        f = name.casefold()
        return any(s is not exclude and s.name.casefold() == f for s in self.sheets)

    def copy(self):
        return State(self.owner, [s.copy() for s in self.sheets])


def _key(c):
    if c is None or c[0] is None:
        return None
    return (c[0], c[1])


def _put(sh, ref, cell, author, rev):
    if cell is None:
        sh.cells[ref] = (None, None, rev, author)
    else:
        sh.cells[ref] = (cell[0], cell[1], rev, author)
    sh.conflicts.pop(ref, None)


def rename_in(state, sh, new):
    old = sh.name
    sh.name = new
    for s in state.sheets:
        for ref, c in list(s.cells.items()):
            if c[0] == "f":
                nt = rewrite_sheet_name(c[1], old, new)
                if nt != c[1]:
                    s.cells[ref] = ("f", nt, c[2], c[3])


def apply_local(state, op, me):
    """Effet optimiste d'une opération sur une copie locale."""
    t = op["t"]
    if t == "add":
        if not state.name_taken(op["name"]):
            s = Sheet(op["id"], op["name"])
            s.rights[me] = W
            state.sheets.append(s)
        return
    if t == "undelete":
        rec = op["record"]
        if state.find(op["sheet"]) is None and not state.name_taken(rec.name):
            state.sheets.insert(min(op["index"], len(state.sheets)), rec.copy())
        return
    sh = state.find(op["sheet"])
    if sh is None:
        return
    if t == "set":
        _put(sh, op["ref"], op["cell"], me, 0)
    elif t == "batch":
        for ref, cell in op["changes"]:
            _put(sh, ref, cell, me, 0)
        new = op.get("rename")
        if new and not state.name_taken(new, sh):
            rename_in(state, sh, new)
    elif t == "resolve":
        c = sh.conflicts.get(op["ref"])
        if c is not None:
            if op["use_discarded"]:
                _put(sh, op["ref"], c[0], me, 0)
            sh.conflicts.pop(op["ref"], None)
    elif t == "delete":
        if len(state.sheets) > 1:
            state.sheets.remove(sh)
    elif t == "rename":
        if not state.name_taken(op["name"], sh):
            rename_in(state, sh, op["name"])


def snapshot_at(sheet, vid):
    cells = {}
    name = sheet.name
    for v in sheet.versions:
        for ref, cell in v[5].items():
            if cell is None:
                cells.pop(ref, None)
            else:
                cells[ref] = cell
        name = v[4]
        if v[0] == vid:
            break
    return cells, name


# ====================================================================== saisie

_N_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_D_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$")


def parse_input(text, tz, formulas=True):
    if text is None or text == "":
        return None
    if formulas and text.startswith("="):
        return ("f", text)
    s = text.strip()
    if _N_RE.match(s):
        return ("n", s)
    if _D_RE.match(s):
        try:
            return ("d", date.fromisoformat(s).isoformat())
        except ValueError:
            pass
    elif _DT_RE.match(s):
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(tz))
            return ("dt", dt.astimezone(UTC).isoformat())
        except ValueError:
            pass
    return ("t", text)


# ====================================================================== réseau

class Network:
    def __init__(self):
        self.endpoints = {}
        self.queue = deque()
        self.down = set()
        self.resync = []
        self.devices = {}

    def register(self, name, endpoint):
        self.endpoints[name] = endpoint

    def is_connected(self, name):
        return name not in self.down

    def send(self, src, dst, msg):
        if src in self.down or dst in self.down:
            return
        self.queue.append((src, dst, pickle.dumps(msg, -1)))

    def disconnect(self, name):
        self.down.add(name)
        self.queue = deque(m for m in self.queue if m[0] != name and m[1] != name)
        if name in self.resync:
            self.resync.remove(name)
        srv = self.endpoints.get("server")
        if srv is not None and name != "server":
            srv.peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        if name not in self.resync:
            self.resync.append(name)

    def _deliver(self, src, dst, blob):
        if src in self.down or dst in self.down:
            return
        ep = self.endpoints.get(dst)
        if ep is not None:
            ep.receive(pickle.loads(blob))

    def _flush(self):
        srv = self.endpoints.get("server")
        if srv is not None:
            srv.flush()

    def deliver_all(self):
        pending = self.resync
        self.resync = []
        for name in pending:
            ep = self.endpoints.get(name)
            if ep is not None and name not in self.down:
                ep.on_reconnect()
        while True:
            while self.queue:
                src, dst, blob = self.queue.popleft()
                self._deliver(src, dst, blob)
            self._flush()
            if not self.queue:
                break

    def deliver_from(self, name):
        batch = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for src, dst, blob in batch:
            self._deliver(src, dst, blob)
        self._flush()


# ====================================================================== serveur

class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.state = State(owner, [Sheet("s0", "Feuille1")])
        self.counter = 0
        self.results = {}
        self.outbox = {}
        self.members = []
        self.presence = {}
        self.trash = {}
        self.dirty = False
        self.msg_seq = 0
        net.register("server", self)

    def _next(self):
        self.counter += 1
        return self.counter

    def _level(self, sh, who):
        if who == self.state.owner:
            return W
        return sh.rights.get(who)

    def peer_down(self, name):
        if self.presence.pop(name, None) is not None:
            pass
        self.dirty = True

    def receive(self, msg):
        kind = msg[0]
        if kind == "hello":
            _, name, ops, sel = msg
            if name not in self.members:
                self.members.append(name)
            for op in ops:
                self._handle(name, op)
            if sel is not None:
                self.presence[name] = sel
        elif kind == "ops":
            _, name, ops = msg
            if name not in self.members:
                self.members.append(name)
            for op in ops:
                self._handle(name, op)
        elif kind == "select":
            _, name, sid, ref = msg
            self.presence[name] = (sid, ref)
        elif kind == "right":
            _, name, person, sid, level = msg
            sh = self.state.find(sid)
            if name == self.state.owner and sh is not None and level in (W, R, None):
                if level is None:
                    sh.rights.pop(person, None)
                else:
                    sh.rights[person] = level
        self.dirty = True

    def flush(self):
        if not self.dirty:
            return
        self.dirty = False
        self.msg_seq += 1
        for name in list(self.members):
            acks = self.outbox.pop(name, [])
            if self.net.is_connected(name):
                self.net.send("server", name,
                              ("state", self.msg_seq, self.state, acks, dict(self.presence)))

    def _handle(self, name, op):
        key = (name, op["seq"])
        ack = self.results.get(key)
        if ack is None:
            ack = self._execute(name, op)
            self.results[key] = ack
        self.outbox.setdefault(name, []).append(ack)

    def _write(self, sh, who, ts, kind, changes):
        rev = self._next()
        for ref, cell in changes:
            _put(sh, ref, cell, who, rev)
        sh.versions.append((rev, who, ts, kind, sh.name, {ref: cell for ref, cell in changes}))

    def _execute(self, who, op):
        t = op["t"]
        seq = op["seq"]
        st = self.state

        def ok():
            return {"seq": seq, "ok": True, "kind": None, "sheet": None, "cell": None}

        def no(kind, sheet=None, cell=None):
            return {"seq": seq, "ok": False, "kind": kind,
                    "sheet": sheet if sheet is not None else op.get("sname"), "cell": cell}

        if t == "add":
            if st.name_taken(op["name"]):
                return no("nom_existant", op["name"])
            s = Sheet(op["id"], op["name"])
            s.rights[who] = W
            st.sheets.append(s)
            return ok()
        if t == "undelete":
            item = self.trash.get(op["sheet"])
            if item is None:
                return no(None)
            idx, sh = item
            if self._level(sh, who) != W:
                return no("droit_insuffisant")
            if st.name_taken(sh.name):
                return no("nom_existant", sh.name)
            del self.trash[op["sheet"]]
            st.sheets.insert(min(idx, len(st.sheets)), sh)
            return ok()
        sh = st.find(op["sheet"])
        if sh is None:
            if t == "delete":
                return ok()
            return no("feuille_supprimee")
        lvl = self._level(sh, who)
        if t == "set":
            ref = op["ref"]
            if lvl != W:
                return no("modification_rejetee", cell=ref)
            cell = op["cell"]
            cur = sh.cells.get(ref)
            cur_rev = cur[2] if cur else 0
            cur_by = cur[3] if cur else None
            if cur_rev > op["base"] and cur_by != who:
                if _key(cur) != cell:
                    sh.conflicts[ref] = (cell, who)
                return ok()
            self._write(sh, who, op["ts"], "modification", [(ref, cell)])
            return ok()
        if t == "batch":
            changes = op["changes"]
            if lvl != W:
                return no("modification_rejetee", cell=changes[0][0] if changes else None)
            renamed = False
            new = op.get("rename")
            if new and not st.name_taken(new, sh):
                rename_in(st, sh, new)
                renamed = True
            if changes or renamed:
                self._write(sh, who, op["ts"], op["kind"], changes)
            return ok()
        if t == "resolve":
            if lvl != W:
                return no("droit_insuffisant", cell=op["ref"])
            c = sh.conflicts.get(op["ref"])
            if c is None:
                return ok()
            sh.conflicts.pop(op["ref"], None)
            if op["use_discarded"]:
                self._write(sh, who, op["ts"], "modification", [(op["ref"], c[0])])
            return ok()
        if t == "delete":
            if lvl != W:
                return no("droit_insuffisant")
            if len(st.sheets) <= 1:
                return no(None)
            idx = st.sheets.index(sh)
            st.sheets.remove(sh)
            self.trash[sh.id] = (idx, sh)
            return ok()
        if t == "rename":
            if lvl != W:
                return no("droit_insuffisant")
            if st.name_taken(op["name"], sh):
                return no("nom_existant", op["name"])
            rename_in(st, sh, op["name"])
            return ok()
        return no(None)


# ====================================================================== client

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line

    def __repr__(self):
        return f"Alert({self.kind!r}, {self.sheet!r}, {self.cell!r}, {self.line!r})"


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    def __init__(self, id, author, timestamp, kind):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


_IMPOSSIBLE = "annulation_impossible"


class Client:
    def __init__(self, net, clock, name, tz="Europe/Paris", _device=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.confirmed = State(None, [Sheet("s0", "Feuille1")])
        self.pending = {}
        self._sent = set()
        self._next = 1
        self.active = "s0"
        self.selection = None
        self._undo = []
        self._redo = []
        self._alerts = []
        self._presence = {}
        self._mseq = 0
        self._view = None
        self._gen = 0
        self._ver = None
        self._vkey = None
        self._vstate = None
        self._ekey = None
        self._ev = None
        if _device is not None:
            self.confirmed = _device["confirmed"]
            self.pending = _device["pending"]
            self._sent = set(self.pending)
            self._next = _device["next"]
            self.tz = _device["tz"]
            self.active = _device["active"]
            self.selection = _device["selection"]
        self._dev = {}
        self._save()
        net.devices[name] = self._dev
        net.register(name, self)
        if net.is_connected(name):
            self._hello()

    # -- persistance (stockage de l'appareil)
    def _save(self):
        d = self._dev
        d["confirmed"] = self.confirmed
        d["pending"] = self.pending
        d["next"] = self._next
        d["tz"] = self.tz
        d["active"] = self.active
        d["selection"] = self.selection

    def reopen(self):
        dev = pickle.loads(pickle.dumps(self._dev, -1))
        return Client(self.net, self.clock, self.name, tz=dev["tz"], _device=dev)

    # -- réseau
    def _hello(self):
        ops = list(self.pending.values())
        self._sent.update(self.pending)
        self.net.send(self.name, "server", ("hello", self.name, ops, self.selection))

    def on_reconnect(self):
        self._hello()

    def receive(self, msg):
        if msg[0] != "state":
            return
        _, mseq, state, acks, presence = msg
        if mseq <= self._mseq:
            return
        self._mseq = mseq
        self.confirmed = state
        self._presence = presence
        for ack in acks:
            op = self.pending.pop(ack["seq"], None)
            if op is None:
                continue
            self._sent.discard(ack["seq"])
            if ack["kind"]:
                self._alerts.append(Alert(ack["kind"], ack["sheet"], ack["cell"]))
        self._invalidate()
        self._save()

    # -- vue locale = copie confirmée + modifications en attente
    def _invalidate(self):
        self._view = None
        self._gen += 1

    def _touch(self):
        self._gen += 1

    def _get_view(self):
        if self._view is None:
            if self.pending:
                v = self.confirmed.copy()
                for op in self.pending.values():
                    apply_local(v, op, self.name)
                self._view = v
            else:
                self._view = self.confirmed
        return self._view

    def _mut_view(self):
        v = self._get_view()
        if v is self.confirmed:
            v = self.confirmed.copy()
            self._view = v
        return v

    def _shown(self):
        v = self._get_view()
        if self._ver is None:
            return v
        key = (self._gen, self._ver)
        if self._vkey != key:
            st = v.copy()
            found = self._find_version(self._ver)
            if found is not None:
                s, cells, _name = found
                target = st.find(s.id)
                if target is not None:
                    target.cells = {r: (c[0], c[1], 0, "") for r, c in cells.items()}
                    target.conflicts = {}
            self._vstate = st
            self._vkey = key
        return self._vstate

    def _find_version(self, vid):
        for s in self.confirmed.sheets:
            for v in s.versions:
                if v[0] == vid:
                    cells, name = snapshot_at(s, vid)
                    return s, cells, name
        return None

    def _evaluator(self):
        st = self._shown()
        key = (self._gen, self._ver, self.clock.now())
        if self._ekey != key:
            self._ev = Evaluator(st, self.clock.now())
            self._ekey = key
        return self._ev

    def _sheet(self, name=None):
        st = self._shown()
        if name is None:
            s = st.find(self.active)
            if s is None and st.sheets:
                s = st.sheets[0]
            return s
        for s in st.sheets:
            if s.name == name:
                return s
        f = name.casefold()
        for s in st.sheets:
            if s.name.casefold() == f:
                return s
        return None

    def _level(self, sh, who=None):
        who = self.name if who is None else who
        if who == self.confirmed.owner:
            return W
        return sh.rights.get(who)

    def _can_write(self, sh):
        return self._level(sh) == W

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    # -- émission d'opérations
    def _issue(self, tpl):
        op = dict(tpl)
        op["seq"] = self._next
        self._next += 1
        op["ts"] = self.clock.now()
        if op["t"] in ("set", "resolve"):
            csh = self.confirmed.find(op["sheet"])
            cur = csh.cells.get(op["ref"]) if csh is not None else None
            op["base"] = cur[2] if cur else 0
        v = self._mut_view()
        apply_local(v, op, self.name)
        self._touch()
        self.pending[op["seq"]] = op
        if self.net.is_connected(self.name):
            self.net.send(self.name, "server", ("ops", self.name, [op]))
            self._sent.add(op["seq"])
        self._save()
        return op["seq"]

    def _perform(self, fwd, inv):
        seq = self._issue(fwd)
        self._undo.append({"fwd": fwd, "inv": inv, "seqs": [seq]})
        self._redo.clear()

    # -- saisie
    def set_cell(self, ref, text, sheet=None):
        self._edit(ref, parse_input(text, self.tz), sheet)

    def clear(self, ref, sheet=None):
        self._edit(ref, None, sheet)

    def _edit(self, ref, cell, sheet):
        if self._ver is not None:
            return
        sh = self._sheet(sheet)
        r = _norm_ref(ref)
        if sh is None or r is None:
            return
        if not self._can_write(sh):
            self._alert("droit_insuffisant", sh.name, r)
            return
        before = _key(sh.cells.get(r))
        base = {"t": "set", "sheet": sh.id, "sname": sh.name, "ref": r}
        self._perform(dict(base, cell=cell), dict(base, cell=before))

    # -- lecture
    def _text(self, c):
        if c is None or c[0] is None:
            return None
        if c[0] == "dt":
            return self._fmt_dt(datetime.fromisoformat(c[1]))
        return c[1]

    def _fmt_dt(self, dt):
        return dt.astimezone(ZoneInfo(self.tz)).strftime("%Y-%m-%d %H:%M")

    def content(self, ref, sheet=None):
        s = self._sheet(sheet)
        r = _norm_ref(ref)
        if s is None or r is None:
            return None
        return self._text(s.cells.get(r))

    def _raw(self, ref, sheet):
        s = self._sheet(sheet)
        r = _norm_ref(ref)
        if s is None or r is None:
            return None
        return self._evaluator().get(s, r)

    def value(self, ref, sheet=None):
        v = self._raw(ref, sheet)
        if v is None:
            return None
        if isinstance(v, Err):
            return v.code
        if isinstance(v, datetime):
            return self._fmt_dt(v)
        if isinstance(v, date):
            return v.isoformat()
        return v

    def error(self, ref, sheet=None):
        v = self._raw(ref, sheet)
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        self.tz = tz
        self._save()

    # -- feuilles
    def sheets(self):
        return [s.name for s in self._shown().sheets]

    def activate(self, name):
        s = self._sheet(name)
        if s is not None:
            self.active = s.id
            self._save()

    def add_sheet(self, name):
        if self._ver is not None:
            return
        if self._get_view().name_taken(name):
            self._alert("nom_existant", name)
            return
        self._issue({"t": "add", "id": f"{self.name}:{self._next}", "name": name, "sname": name})
        self._redo.clear()

    def delete_sheet(self, name):
        if self._ver is not None:
            return
        sh = self._sheet(name)
        if sh is None:
            return
        if not self._can_write(sh):
            self._alert("droit_insuffisant", sh.name)
            return
        st = self._get_view()
        if len(st.sheets) <= 1:
            return
        idx = st.sheets.index(sh)
        fwd = {"t": "delete", "sheet": sh.id, "sname": sh.name}
        inv = {"t": "undelete", "sheet": sh.id, "sname": sh.name, "record": sh.copy(), "index": idx}
        self._perform(fwd, inv)

    def rename_sheet(self, old, new):
        if self._ver is not None:
            return
        sh = self._sheet(old)
        if sh is None:
            return
        if not self._can_write(sh):
            self._alert("droit_insuffisant", sh.name)
            return
        if new == sh.name:
            return
        if self._get_view().name_taken(new, sh):
            self._alert("nom_existant", new)
            return
        fwd = {"t": "rename", "sheet": sh.id, "sname": sh.name, "name": new}
        inv = {"t": "rename", "sheet": sh.id, "sname": new, "name": sh.name}
        self._perform(fwd, inv)

    # -- droits
    def right(self, person, sheet):
        s = self._sheet(sheet)
        if s is None:
            return None
        return self._level(s, person)

    def set_right(self, person, sheet, level):
        if self.confirmed.owner != self.name:
            self._alert("droit_insuffisant", sheet)
            return
        if not self.net.is_connected(self.name):
            return
        s = self._sheet(sheet)
        if s is None:
            return
        self.net.send(self.name, "server", ("right", self.name, person, s.id, level))

    # -- alertes / connexion
    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self.net.is_connected(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    # -- présence
    def select(self, ref, sheet=None):
        s = self._sheet(sheet)
        r = _norm_ref(ref)
        if s is None or r is None:
            return
        self.selection = (s.id, r)
        self._save()
        if self.net.is_connected(self.name):
            self.net.send(self.name, "server", ("select", self.name, s.id, r))

    def presence(self):
        if not self.net.is_connected(self.name):
            return {}
        out = {}
        for who, (sid, ref) in self._presence.items():
            if who == self.name:
                continue
            s = self.confirmed.find(sid)
            if s is not None:
                out[who] = (s.name, ref)
        return out

    # -- conflits
    def conflict(self, ref, sheet=None):
        s = self._sheet(sheet)
        r = _norm_ref(ref)
        if s is None or r is None:
            return None
        c = s.conflicts.get(r)
        if c is None:
            return None
        return Conflict(self._text(c[0]) if c[0] is not None else None, c[1])

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self._ver is not None:
            return
        s = self._sheet(sheet)
        r = _norm_ref(ref)
        if s is None or r is None:
            return
        if not self._can_write(s):
            self._alert("droit_insuffisant", s.name, r)
            return
        if r not in s.conflicts:
            return
        self._issue({"t": "resolve", "sheet": s.id, "sname": s.name, "ref": r,
                     "use_discarded": bool(use_discarded)})

    # -- annulation / rétablissement
    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def _check(self, tpl):
        """None si l'état courant reflète bien `tpl` appliquée ; sinon la nature de l'alerte."""
        t = tpl["t"]
        st = self._get_view()
        if t == "delete":
            return None if st.find(tpl["sheet"]) is None else _IMPOSSIBLE
        if t == "undelete":
            return None if st.find(tpl["sheet"]) is not None else _IMPOSSIBLE
        sh = st.find(tpl["sheet"])
        if sh is None:
            return _IMPOSSIBLE
        if not self._can_write(sh):
            return "droit_insuffisant"
        if t == "set":
            return None if _key(sh.cells.get(tpl["ref"])) == tpl["cell"] else _IMPOSSIBLE
        if t == "batch":
            for ref, cell in tpl["changes"]:
                if _key(sh.cells.get(ref)) != cell:
                    return _IMPOSSIBLE
            if tpl.get("rename") and sh.name != tpl["rename"]:
                return _IMPOSSIBLE
            return None
        if t == "rename":
            return None if sh.name == tpl["name"] else _IMPOSSIBLE
        return _IMPOSSIBLE

    def undo(self):
        if self._ver is not None or not self._undo:
            return
        e = self._undo[-1]
        verdict = self._check(e["fwd"])
        if verdict == "droit_insuffisant":
            sh = self._get_view().find(e["fwd"]["sheet"])
            self._alert(verdict, sh.name if sh else None)
            return
        if verdict:
            self._alert(verdict, e["fwd"].get("sname"), e["fwd"].get("ref"))
            self._undo.pop()
            return
        self._undo.pop()
        seqs = e["seqs"]
        if seqs and all(s in self.pending and s not in self._sent for s in seqs):
            for s in seqs:
                del self.pending[s]
            self._invalidate()
            self._save()
        else:
            self._issue(e["inv"])
        self._redo.append(e)

    def redo(self):
        if self._ver is not None or not self._redo:
            return
        e = self._redo[-1]
        verdict = self._check(e["inv"])
        if verdict == "droit_insuffisant":
            sh = self._get_view().find(e["inv"]["sheet"])
            self._alert(verdict, sh.name if sh else None)
            return
        if verdict:
            self._alert(verdict, e["inv"].get("sname"), e["inv"].get("ref"))
            self._redo.pop()
            return
        self._redo.pop()
        e["seqs"] = [self._issue(e["fwd"])]
        self._undo.append(e)

    # -- historique des versions
    def history(self, sheet=None):
        s = self._sheet(sheet)
        if s is None:
            return []
        cs = self.confirmed.find(s.id)
        if cs is None:
            return []
        zone = ZoneInfo(self.tz)
        ordered = sorted(cs.versions, key=lambda v: (v[2], v[0]), reverse=True)
        return [Version(v[0], v[1], v[2].astimezone(zone).strftime("%Y-%m-%d %H:%M"), v[3])
                for v in ordered]

    def open_version(self, version_id):
        if self._find_version(version_id) is None:
            return
        self._ver = version_id
        self._touch()

    def close_version(self):
        if self._ver is not None:
            self._ver = None
            self._touch()

    def restore_version(self, version_id):
        found = self._find_version(version_id)
        if found is None:
            return
        csheet, snap, vname = found
        st = self._get_view()
        sh = st.find(csheet.id)
        if sh is None:
            return
        if not self._can_write(sh):
            self._alert("droit_insuffisant", sh.name)
            return
        changes = []
        undo_changes = []
        for ref in sorted(set(snap) | {r for r, c in sh.cells.items() if c[0] is not None}):
            cur = _key(sh.cells.get(ref))
            target = snap.get(ref)
            target = (target[0], target[1]) if target is not None else None
            if cur != target:
                changes.append((ref, target))
                undo_changes.append((ref, cur))
        rename = vname if vname != sh.name and not st.name_taken(vname, sh) else None
        if not changes and rename is None:
            return
        fwd = {"t": "batch", "sheet": sh.id, "sname": sh.name, "changes": changes,
               "kind": "restauration", "rename": rename}
        inv = {"t": "batch", "sheet": sh.id, "sname": rename or sh.name, "changes": undo_changes,
               "kind": "modification", "rename": sh.name if rename else None}
        self._perform(fwd, inv)

    # -- CSV
    def _csv_value(self, v):
        if v is None:
            return ""
        if isinstance(v, Err):
            return v.code
        if isinstance(v, datetime):
            return v.astimezone(ZoneInfo(self.tz)).isoformat()
        if isinstance(v, date):
            return v.isoformat()
        return str(v)

    def export_csv(self):
        s = self._sheet(None)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        if s is not None:
            ev = self._evaluator()
            rows = {}
            for ref, c in s.cells.items():
                if c[0] is None:
                    continue
                col, row = coords(ref)
                rows.setdefault(row, {})[col] = ref
            for row in sorted(rows):
                cols = rows[row]
                line = [""] * max(cols)
                for col, ref in cols.items():
                    line[col - 1] = self._csv_value(ev.get(s, ref))
                w.writerow(line)
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self._ver is not None:
            return
        sh = self._sheet(None)
        if sh is None:
            return
        if not self._can_write(sh):
            self._alert("droit_insuffisant", sh.name)
            return
        try:
            text = bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:
            self._alert("csv_invalide", sh.name, None, 1)
            return
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows = []
        while True:
            start = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error:
                self._alert("csv_invalide", sh.name, None, start)
                return
            rows.append(row)
        changes = []
        undo_changes = []
        for r, row in enumerate(rows, start=1):
            for c, field in enumerate(row, start=1):
                ref = f"{col_name(c)}{r}"
                cell = parse_input(field, self.tz, formulas=False)
                cur = _key(sh.cells.get(ref))
                if cell != cur:
                    changes.append((ref, cell))
                    undo_changes.append((ref, cur))
        if not changes:
            return
        base = {"t": "batch", "sheet": sh.id, "sname": sh.name, "rename": None}
        self._perform(dict(base, changes=changes, kind="import"),
                      dict(base, changes=undo_changes, kind="modification"))
