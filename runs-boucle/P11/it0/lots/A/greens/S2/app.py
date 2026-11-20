"""Classeur collaboratif hors ligne : formules, réseau simulé, fusion, fuseaux, CSV, annulation, versions."""
import csv
import io
import pickle
import re
from collections import deque, namedtuple
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"
SERVER = "server"
S0 = "sheet0"
FMT = "%Y-%m-%d %H:%M"


# ------------------------------------------------------------------ temps et réseau

class Clock:
    def __init__(self, start):
        self.t = start.astimezone(UTC)

    def now(self):
        return self.t

    def advance(self, delta):
        self.t = self.t + delta


class Network:
    def __init__(self):
        self.nodes = {}
        self.queue = deque()
        self.down = set()

    def register(self, name, node):
        self.nodes[name] = node

    def is_connected(self, name):
        return name not in self.down

    def send(self, src, dst, msg):
        if src in self.down:
            return
        self.queue.append((src, dst, msg))

    def _deliver(self, item):
        src, dst, msg = item
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, msg)

    def deliver_all(self):
        while self.queue:
            self._deliver(self.queue.popleft())

    def deliver_from(self, name):
        mine = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for m in mine:
            self._deliver(m)

    def disconnect(self, name):
        self.down.add(name)
        srv = self.nodes.get(SERVER)
        if srv is not None and name != SERVER:
            srv.peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and name != SERVER:
            node.link_up()


# ------------------------------------------------------------------ cellules et formules

class CellError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _Syn(Exception):
    pass


_NUM_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_REF_RE = re.compile(r"([A-Za-z]+)(\d+)")


def make_cell(text, tz, literal=False):
    if text is None or text == "":
        return None
    if text.startswith("="):
        return ("L", text) if literal else ("t", text)
    if _DT_RE.fullmatch(text):
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return ("t", text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        return ("D", dt.astimezone(UTC).isoformat())
    if _DATE_RE.fullmatch(text):
        try:
            date.fromisoformat(text)
        except ValueError:
            return ("t", text)
        return ("d", text)
    return ("t", text)


def is_formula(cell):
    return cell[0] == "t" and cell[1].startswith("=")


def plain_value(cell):
    k, t = cell
    if k == "t":
        if _NUM_RE.fullmatch(t):
            return float(t) if "." in t else int(t)
        return t
    if k == "L":
        return t
    if k == "D":
        return datetime.fromisoformat(t)
    return date.fromisoformat(t)


def cell_text(cell, zi):
    if cell is None:
        return None
    if cell[0] == "D":
        return datetime.fromisoformat(cell[1]).astimezone(zi).strftime(FMT)
    return cell[1]


def fmt_value(v, zi):
    if isinstance(v, datetime):
        return v.astimezone(zi).strftime(FMT)
    if isinstance(v, date):
        return v.isoformat()
    return v


def export_text(v, zi):
    if v is None:
        return ""
    if isinstance(v, CellError):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(zi).isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _col_num(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_name(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _split_ref(ref):
    m = _REF_RE.fullmatch(ref)
    return _col_num(m.group(1)), int(m.group(2))


def _nref(ref):
    ref = ref.strip().upper()
    return ref if _REF_RE.fullmatch(ref) else None


def _expand(sid, r1, r2):
    c1, w1 = _split_ref(r1)
    c2, w2 = _split_ref(r2)
    for r in range(min(w1, w2), max(w1, w2) + 1):
        for c in range(min(c1, c2), max(c1, c2) + 1):
            yield (sid, f"{_col_name(c)}{r}")


_TOK = re.compile(r"""
    (?P<range>(?:(?:'[^']+'|\w+)!)?[A-Za-z]+\d+:[A-Za-z]+\d+)
   |(?P<ref>(?:(?:'[^']+'|\w+)!)?[A-Za-z]+\d+)
   |(?P<num>\d+(?:\.\d+)?)
   |(?P<func>[^\W\d]\w*)\(
   |(?P<op>[-+*/(),;])
""", re.X)


def _split_sheet(tok):
    if "!" in tok:
        sh, rest = tok.rsplit("!", 1)
        if len(sh) >= 2 and sh.startswith("'") and sh.endswith("'"):
            sh = sh[1:-1]
        return sh, rest
    return None, tok


def _tokenize(s):
    toks = []
    pos = 0
    n = len(s)
    while True:
        while pos < n and s[pos].isspace():
            pos += 1
        if pos >= n:
            break
        m = _TOK.match(s, pos)
        if not m:
            raise _Syn()
        pos = m.end()
        g = m.lastgroup
        v = m.group(g)
        if g == "num":
            toks.append(("num", float(v) if "." in v else int(v)))
        elif g == "ref":
            sh, rest = _split_sheet(v)
            toks.append(("ref", sh, rest.upper()))
        elif g == "range":
            sh, rest = _split_sheet(v)
            a, b = rest.split(":")
            toks.append(("range", sh, a.upper(), b.upper()))
        elif g == "func":
            toks.append(("func", v.upper()))
        else:
            toks.append(("op", v))
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def isop(self, c):
        p = self.peek()
        return p is not None and p[0] == "op" and p[1] == c

    def expr(self):
        n = self.term()
        while self.isop("+") or self.isop("-"):
            op = self.t[self.i][1]
            self.i += 1
            n = ("bin", op, n, self.term())
        return n

    def term(self):
        n = self.unary()
        while self.isop("*") or self.isop("/"):
            op = self.t[self.i][1]
            self.i += 1
            n = ("bin", op, n, self.unary())
        return n

    def unary(self):
        if self.isop("-"):
            self.i += 1
            return ("neg", self.unary())
        if self.isop("+"):
            self.i += 1
            return self.unary()
        return self.primary()

    def arg(self):
        p = self.peek()
        if p is not None and p[0] == "range":
            self.i += 1
            return ("range", p[1], p[2], p[3])
        return self.expr()

    def primary(self):
        p = self.peek()
        if p is None:
            raise _Syn()
        k = p[0]
        if k == "num":
            self.i += 1
            return ("num", p[1])
        if k == "ref":
            self.i += 1
            return ("ref", p[1], p[2])
        if k == "func":
            self.i += 1
            args = []
            if self.isop(")"):
                self.i += 1
            else:
                while True:
                    args.append(self.arg())
                    if self.isop(",") or self.isop(";"):
                        self.i += 1
                        continue
                    if self.isop(")"):
                        self.i += 1
                        break
                    raise _Syn()
            name = p[1]
            if name == "SOMME" and len(args) >= 1:
                pass
            elif name == "MAINTENANT" and not args:
                pass
            else:
                raise _Syn()
            return ("call", name, args)
        if k == "op" and p[1] == "(":
            self.i += 1
            n = self.expr()
            if not self.isop(")"):
                raise _Syn()
            self.i += 1
            return n
        raise _Syn()


def _parse(text):
    toks = _tokenize(text[1:])
    p = _Parser(toks)
    n = p.expr()
    if p.i != len(toks):
        raise _Syn()
    return n


_PCACHE = {}


def parse_cached(text):
    r = _PCACHE.get(text)
    if r is None:
        try:
            r = (_parse(text), None)
        except (_Syn, RecursionError):
            r = (None, "#SYNTAXE!")
        _PCACHE[text] = r
    return r


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _norm(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _arith(op, a, b):
    if op == "-" and isinstance(a, datetime) and isinstance(b, datetime):
        return (a - b).total_seconds() / 86400
    if (op == "-" and isinstance(a, date) and isinstance(b, date)
            and not isinstance(a, datetime) and not isinstance(b, datetime)):
        return (a - b).days
    if not (_isnum(a) and _isnum(b)):
        raise CellError("#TYPE!")
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        raise CellError("#DIV/0!")
    return a / b


class Calc:
    """Valeurs calculées d'un classeur, avec graphe de dépendances et recalcul topologique."""

    def __init__(self, doc, now_fn):
        self.doc = doc
        self.now_fn = now_fn
        self.now = now_fn()
        self.values = {}
        self.deps = {}
        self.rev = {}
        self.parsed = {}
        self.volatile = set()
        self.n2s = {sh.name: sid for sid, sh in doc.sheets.items()}
        self.recalc({(sid, ref) for sid, sh in doc.sheets.items() for ref in sh.cells})

    def _sheet(self, name, sid):
        if name is None:
            return sid
        return self.n2s.get(name)

    def _collect(self, n, sid, out):
        t = n[0]
        vol = False
        if t == "ref":
            s = self._sheet(n[1], sid)
            if s is not None:
                out.add((s, n[2]))
        elif t == "neg":
            vol = self._collect(n[1], sid, out)
        elif t == "bin":
            v1 = self._collect(n[2], sid, out)
            v2 = self._collect(n[3], sid, out)
            vol = v1 or v2
        elif t == "call":
            if n[1] == "MAINTENANT":
                vol = True
            for a in n[2]:
                if a[0] == "range":
                    s = self._sheet(a[1], sid)
                    if s is not None:
                        out.update(_expand(s, a[2], a[3]))
                else:
                    if self._collect(a, sid, out):
                        vol = True
        return vol

    def _setup(self, a):
        sid, ref = a
        for d in self.deps.pop(a, ()):
            s = self.rev.get(d)
            if s:
                s.discard(a)
        self.volatile.discard(a)
        self.parsed.pop(a, None)
        sh = self.doc.sheets.get(sid)
        cell = sh.cells.get(ref) if sh else None
        if cell is not None and is_formula(cell):
            ast, code = parse_cached(cell[1])
            if ast is None:
                self.parsed[a] = ("err", code)
            else:
                ds = set()
                vol = self._collect(ast, sid, ds)
                self.parsed[a] = ("ok", ast)
                if ds:
                    self.deps[a] = ds
                    for d in ds:
                        self.rev.setdefault(d, set()).add(a)
                if vol:
                    self.volatile.add(a)

    def _get(self, a):
        v = self.values.get(a)
        if isinstance(v, CellError):
            raise CellError(v.code)
        return v

    def _ev(self, n, sid):
        t = n[0]
        if t == "num":
            return n[1]
        if t == "ref":
            s = self._sheet(n[1], sid)
            if s is None:
                raise CellError("#REF!")
            v = self._get((s, n[2]))
            return 0 if v is None else v
        if t == "neg":
            v = self._ev(n[1], sid)
            if _isnum(v):
                return -v
            raise CellError("#TYPE!")
        if t == "bin":
            a = self._ev(n[2], sid)
            b = self._ev(n[3], sid)
            return _arith(n[1], a, b)
        # appel de fonction
        if n[1] == "MAINTENANT":
            return self.now
        total = 0
        for a in n[2]:
            if a[0] == "range":
                s = self._sheet(a[1], sid)
                if s is None:
                    raise CellError("#REF!")
                for addr in _expand(s, a[2], a[3]):
                    v = self._get(addr)
                    if _isnum(v):
                        total += v
            else:
                v = self._ev(a, sid)
                if not _isnum(v):
                    raise CellError("#TYPE!")
                total += v
        return total

    def _compute(self, a):
        sid, ref = a
        sh = self.doc.sheets.get(sid)
        cell = sh.cells.get(ref) if sh else None
        if cell is None:
            self.values.pop(a, None)
            return
        if is_formula(cell):
            kind, x = self.parsed[a]
            if kind == "err":
                self.values[a] = CellError(x)
                return
            try:
                v = _norm(self._ev(x, sid))
            except CellError as e:
                v = e
            self.values[a] = v
        else:
            self.values[a] = plain_value(cell)

    def recalc(self, changed):
        for a in changed:
            self._setup(a)
        affected = set()
        stack = list(changed)
        rev = self.rev
        while stack:
            a = stack.pop()
            if a in affected:
                continue
            affected.add(a)
            r = rev.get(a)
            if r:
                stack.extend(r)
        indeg = {}
        for a in affected:
            ds = self.deps.get(a)
            indeg[a] = sum(1 for d in ds if d in affected) if ds else 0
        ready = [a for a, k in indeg.items() if k == 0]
        while ready:
            a = ready.pop()
            self._compute(a)
            r = rev.get(a)
            if r:
                for b in r:
                    if b in indeg:
                        indeg[b] -= 1
                        if indeg[b] == 0:
                            ready.append(b)
        for a, k in indeg.items():
            if k > 0:
                self.values[a] = CellError("#CIRC!")

    def refresh(self):
        if self.volatile:
            now = self.now_fn()
            if now != self.now:
                self.now = now
                self.recalc(set(self.volatile))


# ------------------------------------------------------------------ document répliqué

class Sheet:
    __slots__ = ("name", "cells", "ver", "last", "conflicts")

    def __init__(self, name):
        self.name = name
        self.cells = {}
        self.ver = {}
        self.last = {}
        self.conflicts = {}


Entry = namedtuple("Entry", "id author ts kind name cells")


class Doc:
    def __init__(self, owner):
        self.owner = owner
        self.order = []
        self.sheets = {}
        self.rights = {}
        self.history = {}

    @staticmethod
    def initial(owner):
        d = Doc(owner)
        d.sheets[S0] = Sheet("Feuille1")
        d.order.append(S0)
        return d

    def clone(self, full=False):
        d = Doc(self.owner)
        d.order = list(self.order)
        for sid, sh in self.sheets.items():
            n = Sheet(sh.name)
            n.cells = dict(sh.cells)
            n.conflicts = dict(sh.conflicts)
            if full:
                n.ver = dict(sh.ver)
                n.last = dict(sh.last)
            d.sheets[sid] = n
        d.rights = {sid: dict(r) for sid, r in self.rights.items()}
        if full:
            d.history = {sid: list(h) for sid, h in self.history.items()}
        return d


def can_write(doc, person, sid):
    if sid not in doc.sheets:
        return False
    return person == doc.owner or doc.rights.get(sid, {}).get(person) == W


def name_taken(doc, name, except_sid=None):
    low = name.casefold()
    return any(sid != except_sid and sh.name.casefold() == low for sid, sh in doc.sheets.items())


def _rewrite(text, old, new):
    q = new if re.fullmatch(r"\w+", new) else "'" + new + "'"

    def rep(m):
        name = m.group(1) if m.group(1) is not None else m.group(2)
        return q + "!" if name == old else m.group(0)

    return re.sub(r"(?<![\w'])(?:'([^']+)'|(\w+))!(?=[A-Za-z]+\d+)", rep, text)


def rename_in_doc(doc, sid, new):
    sh = doc.sheets[sid]
    old = sh.name
    if old == new:
        return
    sh.name = new
    for s in doc.sheets.values():
        for ref, cell in list(s.cells.items()):
            if cell[0] == "t" and cell[1].startswith("=") and "!" in cell[1]:
                nt = _rewrite(cell[1], old, new)
                if nt != cell[1]:
                    s.cells[ref] = ("t", nt)


def _put(sh, ref, cell):
    if cell is None:
        sh.cells.pop(ref, None)
    else:
        sh.cells[ref] = cell


def apply_replace(doc, body, oid):
    sid = body["sid"]
    cells = body["cells"]
    sh = doc.sheets.get(sid)
    if body["create"]:
        if sh is not None:
            return None
        sh = Sheet(body["name"])
        doc.sheets[sid] = sh
        doc.order.insert(min(body["pos"], len(doc.order)), sid)
        doc.rights[sid] = dict(body["rights"] or {})
        refs = set(cells)
    else:
        if sh is None:
            return None
        refs = set(sh.cells) | set(cells)
        if sh.name != body["name"]:
            rename_in_doc(doc, sid, body["name"])
    sh.cells = dict(cells)
    for ref in refs:
        sh.ver[ref] = sh.ver.get(ref, 0) + 1
        sh.last[ref] = oid
    sh.conflicts = {}
    return sh


def _entry(doc, ev, sid, kind):
    sh = doc.sheets[sid]
    doc.history.setdefault(sid, []).append(
        Entry(ev["seq"], ev["author"], ev["ts"], kind, sh.name, dict(sh.cells)))


def apply_event(doc, ev):
    k = ev["kind"]
    sid = ev.get("sid")
    if k == "set":
        sh = doc.sheets.get(sid)
        if sh is None:
            return
        any_applied = False
        for ref, cell, ver, conflict, applied in ev["changes"]:
            _put(sh, ref, cell)
            sh.ver[ref] = ver
            if applied:
                sh.last[ref] = ev["id"]
                any_applied = True
            if conflict:
                sh.conflicts[ref] = conflict
            else:
                sh.conflicts.pop(ref, None)
        if any_applied:
            _entry(doc, ev, sid, "modification")
    elif k == "add_sheet":
        if sid in doc.sheets:
            return
        doc.sheets[sid] = Sheet(ev["name"])
        doc.order.append(sid)
        doc.rights[sid] = {ev["author"]: W}
    elif k == "delete":
        if sid in doc.sheets:
            del doc.sheets[sid]
            doc.order.remove(sid)
            doc.rights.pop(sid, None)
    elif k == "rename":
        if sid in doc.sheets:
            rename_in_doc(doc, sid, ev["name"])
            _entry(doc, ev, sid, "renommage")
    elif k == "replace":
        sh = apply_replace(doc, ev, ev["id"])
        if sh is not None and not ev["create"]:
            _entry(doc, ev, sid, ev["label"])
    elif k == "set_right":
        r = doc.rights.setdefault(sid, {})
        if ev["level"] is None:
            r.pop(ev["person"], None)
        else:
            r[ev["person"]] = ev["level"]


def apply_local(doc, op):
    k = op["kind"]
    sid = op.get("sid")
    if k == "set":
        sh = doc.sheets.get(sid)
        if sh is not None:
            for ref, cell, _b, _f in op["changes"]:
                _put(sh, ref, cell)
                sh.conflicts.pop(ref, None)
    elif k == "resolve":
        sh = doc.sheets.get(sid)
        if sh is not None:
            conf = sh.conflicts.pop(op["ref"], None)
            if conf is not None and op["use"]:
                _put(sh, op["ref"], conf[0])
    elif k == "add_sheet":
        if sid not in doc.sheets and not name_taken(doc, op["name"]):
            doc.sheets[sid] = Sheet(op["name"])
            doc.order.append(sid)
            doc.rights[sid] = {op["author"]: W}
    elif k == "delete_sheet":
        if sid in doc.sheets and len(doc.order) > 1:
            del doc.sheets[sid]
            doc.order.remove(sid)
            doc.rights.pop(sid, None)
    elif k == "rename":
        if sid in doc.sheets and not name_taken(doc, op["name"], sid):
            rename_in_doc(doc, sid, op["name"])
    elif k == "replace":
        if op["create"]:
            if sid not in doc.sheets and not name_taken(doc, op["name"]):
                apply_replace(doc, op, op["id"])
        elif sid in doc.sheets:
            name = op["name"]
            if name_taken(doc, name, sid):
                name = doc.sheets[sid].name
            body = dict(op)
            body["name"] = name
            apply_replace(doc, body, op["id"])
    elif k == "set_right":
        r = doc.rights.setdefault(sid, {})
        if op["level"] is None:
            r.pop(op["person"], None)
        else:
            r[op["person"]] = op["level"]


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.doc = Doc.initial(owner)
        self.seq = 0
        self.clients = []
        self.processed = {}
        self.status = {}
        self.presence = {}
        net.register(SERVER, self)

    def _broadcast_presence(self):
        for c in self.clients:
            self.net.send(SERVER, c, {"t": "presence", "map": dict(self.presence)})

    def peer_down(self, name):
        if name in self.presence:
            del self.presence[name]
            self._broadcast_presence()

    def receive(self, src, msg):
        t = msg["t"]
        if src not in self.clients:
            self.clients.append(src)
        if t == "hello":
            results = {}
            for op in msg["ops"]:
                res, _fresh = self._process(op)
                results[op["id"]] = res
            self.net.send(SERVER, src, {
                "t": "snapshot", "seq": self.seq, "doc": self.doc.clone(True),
                "presence": dict(self.presence), "results": results})
        elif t == "op":
            op = msg["op"]
            res, fresh = self._process(op)
            if fresh and res["status"] == "rejected":
                self.net.send(SERVER, src, {"t": "reject", "id": op["id"], "res": res})
        elif t == "presence":
            self.presence[src] = (msg["sheet"], msg["ref"])
            self._broadcast_presence()

    def _process(self, op):
        oid = op["id"]
        if oid in self.processed:
            return self.processed[oid], False
        res, body = self._decide(op)
        self.processed[oid] = res
        if body is not None:
            self.seq += 1
            ev = dict(body)
            ev.update({"t": "event", "seq": self.seq, "id": oid,
                       "author": op["author"], "ts": op["ts"]})
            apply_event(self.doc, ev)
            for c in self.clients:
                self.net.send(SERVER, c, ev)
        return res, True

    def _decide(self, op):
        d = self.doc
        kind = op["kind"]
        author = op["author"]
        oid = op["id"]
        sid = op.get("sid")
        ok = ({"status": "applied"})

        def rej(reason, sheet=None, cells=()):
            return {"status": "rejected", "reason": reason, "sheet": sheet,
                    "cells": list(cells), "kind": kind}, None

        if kind == "set":
            refs = [c[0] for c in op["changes"]]
            sh = d.sheets.get(sid)
            if sh is None:
                return rej("sheet_gone", op.get("sname"), refs)
            if not can_write(d, author, sid):
                return rej("rights", sh.name, refs)
            changes = []
            for ref, cell, base, follows in op["changes"]:
                cur = sh.cells.get(ref)
                ver = sh.ver.get(ref, 0)
                fst = self.status.get((follows, sid, ref)) if follows else None
                if fst == "applied":
                    good = sh.last.get(ref) == follows
                elif fst == "conflict":
                    good = False
                else:
                    good = ver == base
                if good or cur == cell:
                    changes.append((ref, cell, ver + 1, None, True))
                    self.status[(oid, sid, ref)] = "applied"
                else:
                    changes.append((ref, cur, ver, (cell, author), False))
                    self.status[(oid, sid, ref)] = "conflict"
            return ok, {"kind": "set", "sid": sid, "changes": changes}
        if kind == "resolve":
            sh = d.sheets.get(sid)
            if sh is None:
                return rej("sheet_gone", op.get("sname"), [op["ref"]])
            if not can_write(d, author, sid):
                return rej("rights", sh.name, [op["ref"]])
            ref = op["ref"]
            conf = sh.conflicts.get(ref)
            if conf is None:
                return rej("noconflict")
            ver = sh.ver.get(ref, 0)
            if op["use"]:
                self.status[(oid, sid, ref)] = "applied"
                ch = (ref, conf[0], ver + 1, None, True)
            else:
                ch = (ref, sh.cells.get(ref), ver, None, False)
            return ok, {"kind": "set", "sid": sid, "changes": [ch]}
        if kind == "add_sheet":
            if sid in d.sheets or name_taken(d, op["name"]):
                return rej("name", op["name"])
            return ok, {"kind": "add_sheet", "sid": sid, "name": op["name"]}
        if kind == "delete_sheet":
            sh = d.sheets.get(sid)
            if sh is None:
                return rej("sheet_gone", op.get("sname"))
            if not can_write(d, author, sid):
                return rej("rights", sh.name)
            if len(d.order) <= 1:
                return rej("last", sh.name)
            return ok, {"kind": "delete", "sid": sid}
        if kind == "rename":
            sh = d.sheets.get(sid)
            if sh is None:
                return rej("sheet_gone", op.get("sname"))
            if not can_write(d, author, sid):
                return rej("rights", sh.name)
            if name_taken(d, op["name"], sid):
                return rej("name", op["name"])
            return ok, {"kind": "rename", "sid": sid, "name": op["name"]}
        if kind == "replace":
            sh = d.sheets.get(sid)
            if op["create"]:
                if sh is not None:
                    return rej("exists")
                if name_taken(d, op["name"]):
                    return rej("name", op["name"])
                if not (author == d.owner or (op["rights"] or {}).get(author) == W):
                    return rej("rights", op["name"])
                refs = set(op["cells"])
                name = op["name"]
            else:
                if sh is None:
                    return rej("sheet_gone", op.get("sname"))
                if not can_write(d, author, sid):
                    return rej("rights", sh.name)
                name = op["name"]
                if name_taken(d, name, sid):
                    name = sh.name
                refs = set(sh.cells) | set(op["cells"])
            for ref in refs:
                self.status[(oid, sid, ref)] = "applied"
            return ok, {"kind": "replace", "sid": sid, "name": name, "cells": dict(op["cells"]),
                        "label": op["label"], "create": op["create"],
                        "rights": op["rights"], "pos": op["pos"]}
        if kind == "set_right":
            if author != d.owner:
                return rej("owner")
            if sid not in d.sheets or op["level"] not in (W, R, None):
                return rej("invalid")
            return ok, {"kind": "set_right", "sid": sid, "person": op["person"], "level": op["level"]}
        return rej("unknown")


# ------------------------------------------------------------------ client

@dataclass
class Alert:
    kind: str
    sheet: str = None
    cell: str = None
    line: int = None


@dataclass
class Version:
    id: int
    author: str
    timestamp: str
    kind: str


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class _CsvError(Exception):
    def __init__(self, line):
        super().__init__(line)
        self.line = line


def parse_csv(text):
    rows = []
    row = []
    field = []
    i = 0
    n = len(text)
    inq = False
    fstart = True
    line = 1
    rowstart = 1
    while i < n:
        c = text[i]
        if inq:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                inq = False
                i += 1
                continue
            if c == "\n":
                line += 1
            field.append(c)
            i += 1
            continue
        if c == '"' and fstart:
            inq = True
            fstart = False
            i += 1
            continue
        if c == ",":
            row.append("".join(field))
            field = []
            fstart = True
            i += 1
            continue
        if c == "\r" or c == "\n":
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row = []
            field = []
            fstart = True
            line += 1
            rowstart = line
            i += 1
            continue
        field.append(c)
        fstart = False
        i += 1
    if inq:
        raise _CsvError(rowstart)
    if field or row or not fstart:
        row.append("".join(field))
        rows.append(row)
    return rows


class Client:
    def __init__(self, net, clock, name, tz="Europe/Paris", _store=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self._zi = ZoneInfo(tz)
        self._store = _store if _store is not None else {}
        self.conf = Doc.initial(None)
        self.applied = 0
        self.pending = []
        self.n = 0
        blob = self._store.get("blob")
        if blob:
            st = pickle.loads(blob)
            self.conf = st["conf"]
            self.pending = st["pending"]
            self.applied = st["applied"]
            self.n = st["n"]
        self.sent = set()
        self.undo_stack = []
        self.redo_stack = []
        self._alerts = []
        self.presence_map = {}
        self.active = None
        self.viewing = None
        self._closed = False
        self.view = None
        self.calc = None
        net.register(name, self)
        self._rebuild()
        if self._connected():
            self._hello()

    # ---- infrastructure
    def _connected(self):
        return self.net.is_connected(self.name)

    def _next(self):
        self.n += 1
        return self.n

    def _mk(self, kind, **kw):
        op = {"id": f"{self.name}-{self._next()}", "kind": kind, "author": self.name,
              "ts": self.clock.now().isoformat()}
        op.update(kw)
        return op

    def _rebuild(self):
        doc = self.conf.clone()
        for op in self.pending:
            apply_local(doc, op)
        self.view = doc
        self.calc = Calc(doc, self.clock.now)

    def _hello(self):
        ops = list(self.pending)
        self.sent.update(o["id"] for o in ops)
        self.net.send(self.name, SERVER, {"t": "hello", "ops": ops})

    def link_up(self):
        if not self._closed:
            self._hello()

    def _issue(self, op):
        self.pending.append(op)
        if self._connected():
            self.net.send(self.name, SERVER, {"t": "op", "op": op})
            self.sent.add(op["id"])

    def _drop_pending(self, oid):
        self.pending = [o for o in self.pending if o["id"] != oid]
        self.sent.discard(oid)

    def _sid(self, sheet=None, doc=None):
        doc = doc or self.view
        if sheet is None:
            if self.active in doc.sheets:
                return self.active
            return doc.order[0] if doc.order else None
        for sid, sh in doc.sheets.items():
            if sh.name == sheet:
                return sid
        return None

    def _alert(self, kind, sid=None, cell=None, line=None, sheet=None):
        if sheet is None and sid is not None and sid in self.view.sheets:
            sheet = self.view.sheets[sid].name
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _alert_from(self, res):
        reason = res.get("reason")
        if reason == "rights":
            if res["kind"] == "set":
                for c in res["cells"]:
                    self._alerts.append(Alert("modification_rejetee", res["sheet"], c))
            else:
                self._alerts.append(Alert("droit_insuffisant", res["sheet"]))
        elif reason == "sheet_gone":
            self._alerts.append(Alert("feuille_supprimee", res["sheet"]))
        elif reason == "name":
            self._alerts.append(Alert("nom_existant", res["sheet"]))

    def _cur(self):
        if self.viewing is not None:
            doc, calc = self.viewing
        else:
            doc, calc = self.view, self.calc
        calc.refresh()
        return doc, calc

    def _writable(self, sid):
        return can_write(self.view, self.name, sid)

    # ---- réception
    def receive(self, src, msg):
        if self._closed:
            return
        t = msg["t"]
        if t == "event":
            seq = msg["seq"]
            if seq != self.applied + 1:
                return
            apply_event(self.conf, msg)
            self.applied = seq
            if msg["author"] == self.name:
                self._drop_pending(msg["id"])
            self._rebuild()
        elif t == "snapshot":
            if msg["seq"] < self.applied:
                return
            self.conf = msg["doc"]
            self.applied = msg["seq"]
            self.presence_map = msg["presence"]
            results = msg["results"]
            keep = []
            for op in self.pending:
                res = results.get(op["id"])
                if res is None:
                    keep.append(op)
                    continue
                self.sent.discard(op["id"])
                if res["status"] == "rejected":
                    self._alert_from(res)
            self.pending = keep
            self._rebuild()
        elif t == "reject":
            if any(o["id"] == msg["id"] for o in self.pending):
                self._drop_pending(msg["id"])
                self._alert_from(msg["res"])
                self._rebuild()
        elif t == "presence":
            self.presence_map = msg["map"]

    # ---- lecture
    def content(self, ref, sheet=None):
        doc, _calc = self._cur()
        sid = self._sid(sheet, doc)
        ref = _nref(ref)
        if sid is None or ref is None:
            return None
        return cell_text(doc.sheets[sid].cells.get(ref), self._zi)

    def value(self, ref, sheet=None):
        doc, calc = self._cur()
        sid = self._sid(sheet, doc)
        ref = _nref(ref)
        if sid is None or ref is None:
            return None
        v = calc.values.get((sid, ref))
        if isinstance(v, CellError):
            return v.code
        return fmt_value(v, self._zi)

    def error(self, ref, sheet=None):
        doc, calc = self._cur()
        sid = self._sid(sheet, doc)
        ref = _nref(ref)
        if sid is None or ref is None:
            return None
        v = calc.values.get((sid, ref))
        return v.code if isinstance(v, CellError) else None

    def set_timezone(self, tz):
        self._zi = ZoneInfo(tz)
        self.tz = tz

    def sheets(self):
        return [self.view.sheets[s].name for s in self.view.order]

    def activate(self, name):
        sid = self._sid(name)
        if sid is not None:
            self.active = sid

    def right(self, person, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        if person == self.view.owner:
            return W
        return self.view.rights.get(sid, {}).get(person)

    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self._connected() else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = _nref(ref)
        if sid is None or ref is None:
            return
        if self._connected():
            self.net.send(self.name, SERVER, {"t": "presence", "sheet": self.view.sheets[sid].name,
                                              "ref": ref})

    def presence(self):
        if not self._connected():
            return {}
        return {k: v for k, v in self.presence_map.items() if k != self.name}

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = _nref(ref)
        if sid is None or ref is None:
            return None
        c = self.view.sheets[sid].conflicts.get(ref)
        if not c:
            return None
        return Conflict(cell_text(c[0], self._zi), c[1])

    # ---- édition
    def _follows(self, sid, ref):
        for op in reversed(self.pending):
            k = op["kind"]
            if k == "set" and op["sid"] == sid and any(c[0] == ref for c in op["changes"]):
                return op["id"]
            if k == "resolve" and op["sid"] == sid and op["ref"] == ref:
                return op["id"]
            if k == "replace" and op["sid"] == sid:
                return op["id"]
        return None

    def _edit(self, sid, pairs, record=True, keep_redo=False):
        sh = self.view.sheets[sid]
        csh = self.conf.sheets.get(sid)
        changes = []
        undo = []
        for ref, cell in pairs:
            base = csh.ver.get(ref, 0) if csh else 0
            changes.append((ref, cell, base, self._follows(sid, ref)))
            undo.append((ref, sh.cells.get(ref), cell))
        op = self._mk("set", sid=sid, sname=sh.name, changes=tuple(changes))
        self._issue(op)
        apply_local(self.view, op)
        self.calc.recalc({(sid, ref) for ref, _c in pairs})
        if record:
            self.undo_stack.append({"kind": "set", "sid": sid, "changes": undo, "op": op["id"]})
            if not keep_redo:
                self.redo_stack.clear()
        return op

    def set_cell(self, ref, text, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        ref = _nref(ref)
        if sid is None or ref is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sid, ref)
            return
        self._edit(sid, [(ref, make_cell(text, self.tz))])

    def clear(self, ref, sheet=None):
        self.set_cell(ref, "", sheet)

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        ref = _nref(ref)
        if sid is None or ref is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sid, ref)
            return
        if ref not in self.view.sheets[sid].conflicts:
            return
        op = self._mk("resolve", sid=sid, sname=self.view.sheets[sid].name, ref=ref,
                      use=bool(use_discarded))
        self._issue(op)
        apply_local(self.view, op)
        self.calc.recalc({(sid, ref)})

    # ---- droits
    def set_right(self, person, sheet, level):
        sid = self._sid(sheet)
        if sid is None or self.view.owner != self.name or not self._connected():
            return
        op = self._mk("set_right", sid=sid, person=person, level=level)
        self._issue(op)
        self._rebuild()

    # ---- feuilles
    def add_sheet(self, name):
        if name_taken(self.view, name):
            self._alert("nom_existant", sheet=name)
            return
        sid = f"{self.name}~{self._next()}"
        op = self._mk("add_sheet", sid=sid, name=name)
        self._issue(op)
        self._rebuild()

    def _do_delete(self, sid, record=True, keep_redo=False):
        sh = self.view.sheets[sid]
        act = {"kind": "delete", "sid": sid, "name": sh.name, "cells": dict(sh.cells),
               "rights": dict(self.view.rights.get(sid, {})), "pos": self.view.order.index(sid)}
        op = self._mk("delete_sheet", sid=sid, sname=sh.name)
        self._issue(op)
        self._rebuild()
        if record:
            self.undo_stack.append(act)
            if not keep_redo:
                self.redo_stack.clear()

    def delete_sheet(self, name):
        sid = self._sid(name)
        if sid is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sid)
            return
        if len(self.view.order) <= 1:
            return
        self._do_delete(sid)

    def _do_rename(self, sid, new, record=True, keep_redo=False):
        old = self.view.sheets[sid].name
        if name_taken(self.view, new, sid):
            self._alert("nom_existant", sheet=new)
            return False
        op = self._mk("rename", sid=sid, name=new, sname=old)
        self._issue(op)
        self._rebuild()
        if record:
            self.undo_stack.append({"kind": "rename", "sid": sid, "old": old, "new": new})
            if not keep_redo:
                self.redo_stack.clear()
        return True

    def rename_sheet(self, old, new):
        sid = self._sid(old)
        if sid is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sid)
            return
        self._do_rename(sid, new)

    def _do_replace(self, sid, name, cells, label, record=True, keep_redo=False):
        sh = self.view.sheets[sid]
        before = (sh.name, dict(sh.cells))
        op = self._mk("replace", sid=sid, name=name, cells=dict(cells), label=label,
                      create=False, rights=None, pos=0, sname=sh.name)
        self._issue(op)
        self._rebuild()
        if record:
            self.undo_stack.append({"kind": "replace", "sid": sid, "before": before,
                                    "after": (name, dict(cells))})
            if not keep_redo:
                self.redo_stack.clear()

    # ---- annulation
    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if self.viewing is not None or not self.undo_stack:
            return
        act = self.undo_stack.pop()
        if self._reverse(act):
            self.redo_stack.append(act)

    def redo(self):
        if self.viewing is not None or not self.redo_stack:
            return
        act = self.redo_stack.pop()
        self._forward(act)

    def _reverse(self, act):
        k = act["kind"]
        sid = act["sid"]
        if k == "set":
            sh = self.view.sheets.get(sid)
            if sh is None:
                self._alert("annulation_impossible", sheet=None)
                return False
            if not self._writable(sid):
                self._alert("droit_insuffisant", sid)
                return False
            oid = act["op"]
            if oid not in self.sent and any(o["id"] == oid for o in self.pending):
                self._drop_pending(oid)
                self._rebuild()
                return True
            for ref, _old, new in act["changes"]:
                if sh.cells.get(ref) != new:
                    self._alert("annulation_impossible", sid, ref)
                    return False
            self._edit(sid, [(ref, old) for ref, old, _new in act["changes"]], record=False)
            return True
        if k == "delete":
            if sid in self.view.sheets:
                self._alert("annulation_impossible", sid)
                return False
            op = self._mk("replace", sid=sid, name=act["name"], cells=dict(act["cells"]),
                          label="modification", create=True, rights=dict(act["rights"]),
                          pos=act["pos"], sname=act["name"])
            self._issue(op)
            self._rebuild()
            return True
        if k == "rename":
            if sid not in self.view.sheets or self.view.sheets[sid].name != act["new"]:
                self._alert("annulation_impossible", sid)
                return False
            if not self._writable(sid):
                self._alert("droit_insuffisant", sid)
                return False
            return self._do_rename(sid, act["old"], record=False)
        if k == "replace":
            if sid not in self.view.sheets:
                self._alert("annulation_impossible")
                return False
            if not self._writable(sid):
                self._alert("droit_insuffisant", sid)
                return False
            name, cells = act["before"]
            self._do_replace(sid, name, cells, "modification", record=False)
            return True
        return False

    def _forward(self, act):
        k = act["kind"]
        sid = act["sid"]
        if sid not in self.view.sheets:
            self._alert("annulation_impossible")
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sid)
            return
        if k == "set":
            self._edit(sid, [(ref, new) for ref, _old, new in act["changes"]], keep_redo=True)
        elif k == "delete":
            if len(self.view.order) > 1:
                self._do_delete(sid, keep_redo=True)
        elif k == "rename":
            self._do_rename(sid, act["new"], keep_redo=True)
        elif k == "replace":
            name, cells = act["after"]
            self._do_replace(sid, name, cells, "restauration", keep_redo=True)

    # ---- versions
    def history(self, sheet=None):
        sid = self._sid(sheet)
        ents = self.conf.history.get(sid, [])
        ents = sorted(ents, key=lambda e: (datetime.fromisoformat(e.ts), e.id), reverse=True)
        return [Version(e.id, e.author,
                        datetime.fromisoformat(e.ts).astimezone(self._zi).strftime(FMT), e.kind)
                for e in ents]

    def _find_version(self, vid):
        for sid, ents in self.conf.history.items():
            for e in ents:
                if e.id == vid:
                    return sid, e
        return None, None

    def open_version(self, version_id):
        sid, e = self._find_version(version_id)
        if sid is None or sid not in self.view.sheets:
            return
        doc = self.view.clone()
        doc.sheets[sid].cells = dict(e.cells)
        doc.sheets[sid].conflicts = {}
        self.viewing = (doc, Calc(doc, self.clock.now))

    def close_version(self):
        self.viewing = None

    def restore_version(self, version_id):
        if self.viewing is not None:
            return
        sid, e = self._find_version(version_id)
        if sid is None or sid not in self.view.sheets:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sid)
            return
        self._do_replace(sid, e.name, e.cells, "restauration")

    # ---- CSV
    def export_csv(self):
        doc, calc = self._cur()
        sid = self._sid(None, doc)
        sh = doc.sheets[sid]
        byrow = {}
        for ref in sh.cells:
            col, row = _split_ref(ref)
            byrow.setdefault(row, {})[col] = ref
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        for row in sorted(byrow):
            cols = byrow[row]
            mx = max(cols)
            w.writerow([export_text(calc.values.get((sid, cols[c])) if c in cols else None, self._zi)
                        for c in range(1, mx + 1)])
        return out.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.viewing is not None:
            return
        sid = self._sid(None)
        if sid is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sid)
            return
        try:
            rows = parse_csv(bytes(data).decode("utf-8-sig"))
        except UnicodeDecodeError:
            self._alert("csv_invalide", sid, line=1)
            return
        except _CsvError as e:
            self._alert("csv_invalide", sid, line=e.line)
            return
        pairs = []
        for i, row in enumerate(rows):
            for j, f in enumerate(row):
                pairs.append((f"{_col_name(j + 1)}{i + 1}", make_cell(f, self.tz, literal=True)))
        if pairs:
            self._edit(sid, pairs)

    # ---- appareil
    def reopen(self):
        self._store["blob"] = pickle.dumps({"conf": self.conf, "pending": self.pending,
                                            "applied": self.applied, "n": self.n})
        self._closed = True
        return Client(self.net, self.clock, self.name, tz=self.tz, _store=self._store)
