"""Classeur collaboratif hors ligne : formules, copies locales, réseau simulé, fuseaux."""
import copy
import csv
import io
import json
import re
from collections import deque
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"


# ====================================================================== outils

class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


_REF_RE = re.compile(r"^([A-Za-z]{1,3})(\d+)$")


def norm_ref(ref):
    m = _REF_RE.match(str(ref).strip())
    if not m or int(m.group(2)) < 1:
        return None
    return m.group(1).upper() + str(int(m.group(2)))


def split_ref(ref):
    m = _REF_RE.match(ref)
    return m.group(1).upper(), int(m.group(2))


def col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------- cellules

_NUM_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
_INT_RE = re.compile(r"[+-]?\d+")
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def make_cell(text, lit, tz):
    """Cellule = (texte, littéral, instant UTC ISO ou None)."""
    if text is None or text == "":
        return None
    dt = None
    if not lit and not text.startswith("="):
        if _DT_RE.match(text):
            try:
                d = datetime.fromisoformat(text)
                if d.tzinfo is None:
                    d = d.replace(tzinfo=ZoneInfo(tz))
                dt = d.astimezone(UTC).isoformat()
            except ValueError:
                dt = None
    return (text, bool(lit), dt)


def is_formula(cell):
    return cell is not None and not cell[1] and cell[0].startswith("=")


def cell_value(cell):
    raw, lit, dt = cell
    if lit:
        return raw
    if _NUM_RE.fullmatch(raw):
        return int(raw) if _INT_RE.fullmatch(raw) else float(raw)
    if dt:
        return datetime.fromisoformat(dt)
    if _DATE_RE.match(raw):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return raw


def _num(v):
    if isinstance(v, Err):
        return v
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, datetime):
        return v.timestamp() / 86400
    if isinstance(v, date):
        return float(v.toordinal() - 719163)
    return Err("#TYPE!")


# ---------------------------------------------------------------- analyseur de formules

class FormulaSyntax(Exception):
    pass


_TOKENS = [
    ("WS", re.compile(r"\s+")),
    ("SHEET", re.compile(r"(?:'[^']+'|\w+)!")),
    ("NUM", re.compile(r"\d+(?:\.\d+)?|\.\d+")),
    ("RANGE", re.compile(r"[A-Za-z]{1,3}\d+:[A-Za-z]{1,3}\d+(?!\w)")),
    ("REF", re.compile(r"[A-Za-z]{1,3}\d+(?![\w(])")),
    ("FUNC", re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?=\()")),
    ("OP", re.compile(r"[-+*/(),;]")),
]


def tokenize(s):
    toks = []
    pos = 0
    while pos < len(s):
        for kind, rx in _TOKENS:
            m = rx.match(s, pos)
            if m:
                if kind != "WS":
                    toks.append((kind, m.group(0), pos, m.end()))
                pos = m.end()
                break
        else:
            raise FormulaSyntax()
    return toks


def _sheet_name(text):
    nm = text[:-1]
    if nm.startswith("'"):
        nm = nm[1:-1]
    return nm


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def kind(self, j):
        return self.t[j][0] if 0 <= j < len(self.t) else None

    def isop(self, j, chars):
        return self.kind(j) == "OP" and self.t[j][1] in chars

    def parse(self):
        n = self.expr()
        if self.i != len(self.t):
            raise FormulaSyntax()
        return n

    def expr(self):
        n = self.term()
        while self.isop(self.i, "+-"):
            op = self.t[self.i][1]
            self.i += 1
            n = ("bin", op, n, self.term())
        return n

    def term(self):
        n = self.unary()
        while self.isop(self.i, "*/"):
            op = self.t[self.i][1]
            self.i += 1
            n = ("bin", op, n, self.unary())
        return n

    def unary(self):
        if self.isop(self.i, "-"):
            self.i += 1
            return ("neg", self.unary())
        if self.isop(self.i, "+"):
            self.i += 1
            return self.unary()
        return self.primary()

    def arg(self):
        j = self.i
        sheet = None
        if self.kind(j) == "SHEET":
            sheet = _sheet_name(self.t[j][1])
            j += 1
        if self.kind(j) == "RANGE" and self.isop(j + 1, ",;)"):
            a, b = self.t[j][1].upper().split(":")
            self.i = j + 1
            return ("range", sheet, a, b)
        return self.expr()

    def primary(self):
        if self.i >= len(self.t):
            raise FormulaSyntax()
        k, text, _, _ = self.t[self.i]
        if k == "NUM":
            self.i += 1
            return ("num", float(text) if "." in text else int(text))
        if k == "SHEET":
            sheet = _sheet_name(text)
            self.i += 1
            if self.kind(self.i) == "REF":
                ref = self.t[self.i][1].upper()
                self.i += 1
                return ("ref", sheet, ref)
            raise FormulaSyntax()
        if k == "REF":
            self.i += 1
            return ("ref", None, text.upper())
        if k == "FUNC":
            self.i += 1
            if not self.isop(self.i, "("):
                raise FormulaSyntax()
            self.i += 1
            args = []
            if self.isop(self.i, ")"):
                self.i += 1
                return ("call", text, args)
            while True:
                args.append(self.arg())
                if self.isop(self.i, ",;"):
                    self.i += 1
                    continue
                if self.isop(self.i, ")"):
                    self.i += 1
                    break
                raise FormulaSyntax()
            return ("call", text, args)
        if k == "OP" and text == "(":
            self.i += 1
            n = self.expr()
            if not self.isop(self.i, ")"):
                raise FormulaSyntax()
            self.i += 1
            return n
        raise FormulaSyntax()


def _walk(n, items, vol):
    k = n[0]
    if k == "ref":
        items.append(("ref", n[1], n[2]))
    elif k == "range":
        items.append(("range", n[1], n[2], n[3]))
    elif k == "neg":
        _walk(n[1], items, vol)
    elif k == "bin":
        _walk(n[2], items, vol)
        _walk(n[3], items, vol)
    elif k == "call":
        if n[1].upper() in ("MAINTENANT", "NOW"):
            vol[0] = True
        for a in n[2]:
            _walk(a, items, vol)


_PCACHE = {}
_MISSING = object()


def parse_formula(raw):
    r = _PCACHE.get(raw, _MISSING)
    if r is not _MISSING:
        return r
    try:
        ast = _Parser(tokenize(raw[1:])).parse()
        items = []
        vol = [False]
        _walk(ast, items, vol)
        r = (ast, items, vol[0])
    except FormulaSyntax:
        r = None
    _PCACHE[raw] = r
    return r


def _fmt_sheet(name):
    if re.fullmatch(r"\w+", name):
        return name + "!"
    return "'" + name + "'!"


def rewrite_sheet(raw, old, new):
    body = raw[1:]
    try:
        toks = tokenize(body)
    except FormulaSyntax:
        return raw
    out = []
    pos = 0
    for kind, text, s, e in toks:
        if kind == "SHEET" and _sheet_name(text).casefold() == old.casefold():
            out.append(body[pos:s])
            out.append(_fmt_sheet(new))
            pos = e
    out.append(body[pos:])
    return "=" + "".join(out)


# ====================================================================== classeur

class Book:
    def __init__(self, owner=None):
        self.owner = owner
        self.sheets = {"s0": "Feuille1"}
        self.cells = {"s0": {}}
        self.last = {}
        self.conflicts = {}
        self.rights = {"s0": {}}
        self.fdeps = {}
        self.rdeps = {}
        self.values = {}
        self.volatile = set()
        self.now = None

    def copy(self):
        b = Book(self.owner)
        b.sheets = dict(self.sheets)
        b.cells = {s: dict(d) for s, d in self.cells.items()}
        b.last = dict(self.last)
        b.conflicts = dict(self.conflicts)
        b.rights = {s: dict(d) for s, d in self.rights.items()}
        b.fdeps = {k: set(v) for k, v in self.fdeps.items()}
        b.rdeps = {k: set(v) for k, v in self.rdeps.items()}
        b.values = dict(self.values)
        b.volatile = set(self.volatile)
        b.now = self.now
        return b

    # -------- feuilles, droits
    def sid_of(self, name):
        for sid, n in self.sheets.items():
            if n == name:
                return sid
        if isinstance(name, str):
            for sid, n in self.sheets.items():
                if n.casefold() == name.casefold():
                    return sid
        return None

    def name_free(self, name, exclude=None):
        cf = name.casefold()
        return all(n.casefold() != cf for s, n in self.sheets.items() if s != exclude)

    def right(self, person, sid):
        if person is not None and person == self.owner:
            return W
        return self.rights.get(sid, {}).get(person)

    # -------- graphe de dépendances
    def _range_keys(self, tsid, a, b):
        ca, ra = split_ref(a)
        cb, rb = split_ref(b)
        c1, c2 = sorted((col_index(ca), col_index(cb)))
        r1, r2 = sorted((ra, rb))
        return [(tsid, col_name(c) + str(r)) for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)]

    def _target(self, name, sid):
        return sid if name is None else self.sid_of(name)

    def _register(self, key):
        sid, ref = key
        parsed = parse_formula(self.cells[sid][ref][0])
        deps = set()
        if parsed:
            for it in parsed[1]:
                tsid = self._target(it[1], sid)
                if tsid is None:
                    continue
                if it[0] == "ref":
                    deps.add((tsid, it[2]))
                else:
                    deps.update(self._range_keys(tsid, it[2], it[3]))
            if parsed[2]:
                self.volatile.add(key)
        self.fdeps[key] = deps
        for d in deps:
            self.rdeps.setdefault(d, set()).add(key)

    def _unregister(self, key):
        deps = self.fdeps.pop(key, None)
        if deps is not None:
            for d in deps:
                s = self.rdeps.get(d)
                if s is not None:
                    s.discard(key)
                    if not s:
                        del self.rdeps[d]
        self.values.pop(key, None)
        self.volatile.discard(key)

    def _compute(self, keys):
        keys = set(keys)
        indeg = {k: sum(1 for d in self.fdeps[k] if d in keys) for k in keys}
        queue = [k for k in keys if indeg[k] == 0]
        i = 0
        while i < len(queue):
            k = queue[i]
            i += 1
            self.values[k] = self._eval_cell(k)
            for u in self.rdeps.get(k, ()):
                if u in keys:
                    indeg[u] -= 1
                    if indeg[u] == 0:
                        queue.append(u)
        done = set(queue)
        for k in keys:
            if k not in done:
                self.values[k] = Err("#CIRC!")

    def _refresh(self, changed):
        seen = set()
        stack = list(changed)
        for k in changed:
            if k in self.fdeps:
                seen.add(k)
        while stack:
            k = stack.pop()
            for u in self.rdeps.get(k, ()):
                if u not in seen:
                    seen.add(u)
                    stack.append(u)
        if seen:
            self._compute(seen)

    def rebuild(self):
        self.fdeps = {}
        self.rdeps = {}
        self.values = {}
        self.volatile = set()
        keys = []
        for sid, d in self.cells.items():
            for ref, c in d.items():
                if is_formula(c):
                    key = (sid, ref)
                    self._register(key)
                    keys.append(key)
        if keys:
            self._compute(keys)

    # -------- évaluation
    def _peek(self, key):
        if key in self.values:
            return self.values[key]
        c = self.cells.get(key[0], {}).get(key[1])
        return None if c is None else cell_value(c)

    def _read(self, key):
        v = self._peek(key)
        return 0 if v is None else v

    def _eval_cell(self, key):
        sid, ref = key
        parsed = parse_formula(self.cells[sid][ref][0])
        if parsed is None:
            return Err("#SYNTAXE!")
        return self._ev(parsed[0], sid)

    def _ev(self, n, sid):
        k = n[0]
        if k == "num":
            return n[1]
        if k == "ref":
            tsid = self._target(n[1], sid)
            if tsid is None:
                return Err("#REF!")
            return self._read((tsid, n[2]))
        if k == "neg":
            v = _num(self._ev(n[1], sid))
            return v if isinstance(v, Err) else -v
        if k == "bin":
            a = _num(self._ev(n[2], sid))
            if isinstance(a, Err):
                return a
            b = _num(self._ev(n[3], sid))
            if isinstance(b, Err):
                return b
            op = n[1]
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if b == 0:
                return Err("#DIV/0!")
            return a / b
        if k == "call":
            name = n[1].upper()
            if name in ("SOMME", "SUM"):
                total = 0
                for arg in n[2]:
                    if arg[0] == "range":
                        tsid = self._target(arg[1], sid)
                        if tsid is None:
                            return Err("#REF!")
                        for key in self._range_keys(tsid, arg[2], arg[3]):
                            v = self._peek(key)
                            if isinstance(v, Err):
                                return v
                            if isinstance(v, (int, float)):
                                total += v
                    else:
                        v = _num(self._ev(arg, sid))
                        if isinstance(v, Err):
                            return v
                        total += v
                return total
            if name in ("MAINTENANT", "NOW"):
                return self.now or datetime.now(UTC)
            return Err("#NOM?")
        return Err("#SYNTAXE!")

    # -------- application des opérations
    def _put(self, sid, ref, cell):
        key = (sid, ref)
        d = self.cells[sid]
        old = d.get(ref)
        if old is not None and is_formula(old):
            self._unregister(key)
        if cell is None:
            d.pop(ref, None)
        else:
            d[ref] = cell
            if is_formula(cell):
                self._register(key)
        return key

    def _drop_sheet_meta(self, sid):
        for k in [k for k in self.last if k[0] == sid]:
            del self.last[k]
        for k in [k for k in self.conflicts if k[0] == sid]:
            del self.conflicts[k]

    def _rename(self, sid, new):
        old = self.sheets[sid]
        self.sheets[sid] = new
        for s, d in self.cells.items():
            for ref, c in list(d.items()):
                if is_formula(c):
                    nr = rewrite_sheet(c[0], old, new)
                    if nr != c[0]:
                        d[ref] = (nr, c[1], c[2])

    def apply(self, entry):
        op = entry["op"]
        t = op["type"]
        a = op["author"]
        oid = op["id"]
        if t == "set":
            sid = op["sid"]
            if sid not in self.sheets:
                return
            skip = set(entry.get("skip") or ())
            changed = []
            for ref, c in op["cells"].items():
                key = (sid, ref)
                cell = tuple(c) if c else None
                if ref in skip:
                    self.conflicts[key] = (cell, a)
                    continue
                changed.append(self._put(sid, ref, cell))
                self.last[key] = oid
                self.conflicts.pop(key, None)
            self._refresh(changed)
        elif t == "add_sheet":
            sid = op["sid"]
            if sid in self.sheets or not self.name_free(op["name"]):
                return
            self.sheets[sid] = op["name"]
            self.cells[sid] = {}
            self.rights.setdefault(sid, {})[a] = W
            self.rebuild()
        elif t == "delete_sheet":
            sid = op["sid"]
            if sid not in self.sheets:
                return
            del self.sheets[sid]
            del self.cells[sid]
            self._drop_sheet_meta(sid)
            self.rebuild()
        elif t == "rename_sheet":
            sid = op["sid"]
            if sid not in self.sheets or self.sheets[sid] == op["new"]:
                return
            if not self.name_free(op["new"], sid):
                return
            self._rename(sid, op["new"])
            self.rebuild()
        elif t == "restore_sheet":
            sid = op["sid"]
            if sid in self.sheets or not self.name_free(op["name"]):
                return
            self.sheets[sid] = op["name"]
            self.cells[sid] = {ref: tuple(c) for ref, c in op["cells"].items()}
            self.rights.setdefault(sid, {})
            for ref in self.cells[sid]:
                self.last[(sid, ref)] = oid
            self.rebuild()
        elif t == "restore_version":
            sid = op["sid"]
            if sid not in self.sheets:
                return
            old = list(self.cells[sid])
            self._drop_sheet_meta(sid)
            self.cells[sid] = {ref: tuple(c) for ref, c in op["cells"].items()}
            for ref in list(self.cells[sid]) + old:
                self.last[(sid, ref)] = oid
            name = op["name"]
            if name != self.sheets[sid] and self.name_free(name, sid):
                self._rename(sid, name)
            self.rebuild()
        elif t == "set_right":
            d = self.rights.setdefault(op["sid"], {})
            if op["level"] is None:
                d.pop(op["person"], None)
            else:
                d[op["person"]] = op["level"]


# ====================================================================== horloge, réseau

class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Network:
    def __init__(self):
        self.nodes = {}
        self.queue = deque()
        self.down = set()
        self.device_storage = {}

    def register(self, name, node):
        self.nodes[name] = node

    def is_connected(self, name):
        return name not in self.down

    def send(self, src, dst, msg):
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
            self._deliver(self.queue.popleft())

    def deliver_from(self, name):
        mine = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for m in mine:
            self._deliver(m)

    def disconnect(self, name):
        self.down.add(name)
        if name != "server":
            node = self.nodes.get(name)
            if node is not None:
                node.connection_changed(False)
            server = self.nodes.get("server")
            if server is not None:
                server.peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        if name != "server":
            node = self.nodes.get(name)
            if node is not None:
                node.connection_changed(True)


# ====================================================================== serveur

class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.book = Book(owner)
        self.log = []
        self.outcomes = {}
        self.known = []
        self.presence = {}
        net.register("server", self)

    def connection_changed(self, up):
        pass

    def _send(self, dst, msg):
        self.net.send("server", dst, msg)

    def _broadcast(self, msg):
        for c in self.known:
            self._send(c, msg)

    def peer_down(self, name):
        if name in self.presence:
            del self.presence[name]
            self._broadcast({"type": "presence", "map": dict(self.presence)})

    def receive(self, src, msg):
        if src not in self.known:
            self.known.append(src)
        t = msg["type"]
        if t == "hello":
            last = msg["last"]
            self._send(src, {"type": "catchup", "owner": self.owner,
                             "entries": self.log[last:], "presence": dict(self.presence)})
            for op in msg.get("ops", []):
                self._submit(src, op)
            sel = msg.get("sel")
            if sel:
                self.presence[src] = sel
                self._broadcast({"type": "presence", "map": dict(self.presence)})
        elif t == "op":
            self._submit(src, msg["op"])
        elif t == "presence":
            self.presence[src] = msg["sel"]
            self._broadcast({"type": "presence", "map": dict(self.presence)})

    def _submit(self, src, op):
        oid = op["id"]
        if oid in self.outcomes:
            r = self.outcomes[oid]
            if r:
                self._send(src, r)
            return
        if op.get("author") != src:
            return
        res = self._validate(op)
        if isinstance(res, str):
            msg = {"type": "reject", "id": oid, "reason": res}
            self.outcomes[oid] = msg
            self._send(src, msg)
            return
        entry = {"seq": len(self.log) + 1, "op": op, "skip": res}
        self.log.append(entry)
        self.book.now = self.clock.now()
        self.book.apply(entry)
        self.outcomes[oid] = None
        self._broadcast({"type": "entries", "entries": [entry]})

    def _validate(self, op):
        b = self.book
        a = op["author"]
        t = op["type"]

        def can(sid):
            return a == self.owner or b.rights.get(sid, {}).get(a) == W

        if t == "set":
            sid = op["sid"]
            if sid not in b.sheets:
                return "feuille"
            if not can(sid):
                return "droit"
            skip = []
            if not op.get("force"):
                base = op.get("base", {})
                for ref, c in op["cells"].items():
                    if base.get(ref) != b.last.get((sid, ref)):
                        cur = b.cells[sid].get(ref)
                        curc = (cur[0], cur[1]) if cur else (None, False)
                        newc = (c[0], bool(c[1])) if c else (None, False)
                        if curc != newc:
                            skip.append(ref)
            return skip
        if t == "add_sheet":
            if op["sid"] in b.sheets:
                return "doublon"
            if not b.name_free(op["name"]):
                return "nom_existant"
            return []
        if t == "delete_sheet":
            sid = op["sid"]
            if sid not in b.sheets:
                return "feuille"
            if not can(sid):
                return "droit"
            if len(b.sheets) <= 1:
                return "derniere"
            return []
        if t == "rename_sheet":
            sid = op["sid"]
            if sid not in b.sheets:
                return "feuille"
            if not can(sid):
                return "droit"
            if not b.name_free(op["new"], sid):
                return "nom_existant"
            return []
        if t == "restore_sheet":
            sid = op["sid"]
            if sid in b.sheets:
                return "doublon"
            if not can(sid):
                return "droit"
            if not b.name_free(op["name"]):
                return "nom_existant"
            return []
        if t == "restore_version":
            sid = op["sid"]
            if sid not in b.sheets:
                return "feuille"
            if not can(sid):
                return "droit"
            return []
        if t == "set_right":
            if a != self.owner:
                return "droit"
            if op["sid"] not in b.sheets:
                return "feuille"
            return []
        return "invalide"


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


class CsvError(Exception):
    def __init__(self, line):
        super().__init__(line)
        self.line = line


def parse_csv(text):
    rows = []
    row = []
    field = []
    i = 0
    n = len(text)
    line = 1
    inq = False
    qline = 0
    fstart = True
    while i < n:
        ch = text[i]
        if inq:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                inq = False
                i += 1
                continue
            if ch == "\n":
                line += 1
            field.append(ch)
            i += 1
            continue
        if ch == '"' and fstart:
            inq = True
            qline = line
            fstart = False
            i += 1
            continue
        if ch == ",":
            row.append("".join(field))
            field = []
            fstart = True
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row = []
            field = []
            fstart = True
            line += 1
            i += 1
            continue
        field.append(ch)
        fstart = False
        i += 1
    if inq:
        raise CsvError(qline)
    if field or row or not fstart:
        row.append("".join(field))
        rows.append(row)
    return rows


class Client:
    def __init__(self, net, clock, name, tz="UTC", _saved=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.owner = None
        self.confirmed = Book(None)
        self._view = None
        self.log = []
        self.last_seq = 0
        self.pending = []
        self._n = 0
        self._sn = 0
        self._alerts = []
        self.active = "s0"
        self.undo_stack = []
        self.redo_stack = []
        self.presence_map = {}
        self.selection = None
        self.viewing = None
        self.fkey = {}
        if _saved:
            self._load(_saved)
        net.register(name, self)
        if net.is_connected(name):
            self._hello()

    # ------------------------------------------------------------ persistance
    def _save(self):
        return {"owner": self.owner, "log": self.log, "pending": self.pending,
                "n": self._n, "sn": self._sn, "selection": self.selection, "active": self.active}

    def _load(self, s):
        self.owner = s["owner"]
        self.confirmed = Book(self.owner)
        self.confirmed.now = self.clock.now()
        for e in s["log"]:
            self.confirmed.apply(e)
            self.log.append(e)
        self.last_seq = len(self.log)
        self.pending = s["pending"]
        self._n = s["n"]
        self._sn = s["sn"]
        self.selection = s["selection"]
        self.active = s["active"]
        self._rebuild_view()

    def reopen(self):
        saved = json.loads(json.dumps(self._save()))
        self.net.device_storage[self.name] = saved
        return Client(self.net, self.clock, self.name, tz=self.tz, _saved=saved)

    # ------------------------------------------------------------ réseau
    def connected(self):
        return self.net.is_connected(self.name)

    def _hello(self):
        for rec in self.pending:
            rec["sent"] = True
        self.net.send(self.name, "server", {"type": "hello", "last": self.last_seq,
                                            "ops": [r["op"] for r in self.pending],
                                            "sel": self.selection})

    def connection_changed(self, up):
        if up:
            self._hello()

    def receive(self, src, msg):
        t = msg["type"]
        dirty = False
        if t == "catchup":
            self.owner = msg["owner"]
            self.confirmed.owner = self.owner
            if self._view is not None:
                self._view.owner = self.owner
            self.presence_map = msg["presence"]
            dirty = self._apply_entries(msg["entries"])
        elif t == "entries":
            dirty = self._apply_entries(msg["entries"])
        elif t == "reject":
            dirty = self._on_reject(msg)
        elif t == "presence":
            self.presence_map = msg["map"]
        if not self.pending:
            self._view = None
        elif dirty:
            self._rebuild_view()

    def _note_foreign(self, e):
        op = e["op"]
        if op["author"] == self.name:
            return
        sid = op.get("sid")
        if op["type"] == "set":
            skip = set(e.get("skip") or ())
            for ref in op["cells"]:
                if ref not in skip:
                    k = (sid, ref)
                    self.fkey[k] = self.fkey.get(k, 0) + 1
        elif op["type"] == "restore_version":
            refs = set(self.confirmed.cells.get(sid, {})) | set(op["cells"])
            for ref in refs:
                k = (sid, ref)
                self.fkey[k] = self.fkey.get(k, 0) + 1

    def _apply_entries(self, entries):
        dirty = False
        for e in entries:
            seq = e["seq"]
            if seq <= self.last_seq:
                continue
            if seq != self.last_seq + 1:
                self._hello()
                break
            self._fresh(self.confirmed)
            self._note_foreign(e)
            self.confirmed.apply(e)
            self.log.append(e)
            self.last_seq = seq
            oid = e["op"]["id"]
            idx = next((i for i, r in enumerate(self.pending) if r["op"]["id"] == oid), None)
            if idx is not None:
                self.pending.pop(idx)
                if idx != 0 or e.get("skip"):
                    dirty = True
            elif self.pending:
                dirty = True
        return dirty

    def _on_reject(self, msg):
        idx = next((i for i, r in enumerate(self.pending) if r["op"]["id"] == msg["id"]), None)
        if idx is None:
            return False
        rec = self.pending.pop(idx)
        meta = rec["meta"]
        reason = msg["reason"]
        if reason == "droit":
            if rec["op"]["type"] == "set":
                self._alerts.append(Alert("modification_rejetee", meta.get("sheet"), meta.get("cell")))
            else:
                self._alerts.append(Alert("droit_insuffisant", meta.get("sheet")))
        elif reason == "feuille":
            self._alerts.append(Alert("feuille_supprimee", meta.get("sheet"), meta.get("cell")))
        elif reason == "nom_existant":
            self._alerts.append(Alert("nom_existant", meta.get("sheet")))
        return True

    # ------------------------------------------------------------ vues
    def _fresh(self, b):
        now = self.clock.now()
        if b.now != now:
            b.now = now
            if b.volatile:
                b.rebuild()
        return b

    def _cur(self):
        return self._fresh(self._view if self._view is not None else self.confirmed)

    def _book(self):
        if self.viewing is not None:
            return self._fresh(self.viewing)
        return self._cur()

    def _work(self):
        if self._view is None:
            self._view = self.confirmed.copy()
        return self._fresh(self._view)

    def _rebuild_view(self):
        if not self.pending:
            self._view = None
            return
        v = self.confirmed.copy()
        self._fresh(v)
        for rec in self.pending:
            v.apply({"op": rec["op"], "skip": []})
        self._view = v

    def _resolve(self, sheet, b):
        if sheet is None:
            if self.active in b.sheets:
                return self.active
            return next(iter(b.sheets), None)
        return b.sid_of(sheet)

    # ------------------------------------------------------------ émission d'opérations
    def _issue(self, spec, meta):
        self._n += 1
        view = self._work()
        op = dict(spec)
        op["id"] = f"{self.name}:{self._n}"
        op["author"] = self.name
        op["ts"] = self.clock.now().isoformat()
        if op["type"] == "set":
            op["base"] = {ref: view.last.get((op["sid"], ref)) for ref in op["cells"]}
        view.apply({"op": op, "skip": []})
        connected = self.connected()
        self.pending.append({"op": op, "sent": connected, "meta": meta})
        if connected:
            self.net.send(self.name, "server", {"type": "op", "op": op})
        return op["id"]

    def _stamp(self, keys):
        return {k: self.fkey.get(k, 0) for k in keys}

    def _record(self, act):
        self.undo_stack.append(act)
        self.redo_stack.clear()

    def _deny(self, sid, ref=None):
        name = self._cur().sheets.get(sid)
        self._alerts.append(Alert("droit_insuffisant", name, ref))

    def _can_write(self, sid):
        return self._cur().right(self.name, sid) == W

    def _edit(self, sid, cells, force=False, record=True):
        b = self._cur()
        before = {}
        for ref in cells:
            c = b.cells[sid].get(ref)
            before[ref] = list(c) if c else None
        do = {"type": "set", "sid": sid, "force": force,
              "cells": {ref: (list(c) if c else None) for ref, c in cells.items()}}
        undo = {"type": "set", "sid": sid, "force": False, "cells": before}
        refs = list(cells)
        meta = {"sheet": b.sheets[sid], "cell": refs[0] if len(refs) == 1 else None}
        oid = self._issue(do, meta)
        if record:
            keys = [(sid, r) for r in refs]
            self._record({"do": do, "undo": undo, "sid": sid, "keys": keys,
                          "stamp": self._stamp(keys), "opid": oid, "meta": meta})

    # ------------------------------------------------------------ cellules
    def set_cell(self, ref, text, sheet=None):
        if self.viewing is not None:
            return
        ref = norm_ref(ref)
        b = self._cur()
        sid = self._resolve(sheet, b)
        if ref is None or sid is None:
            return
        if not self._can_write(sid):
            self._deny(sid, ref)
            return
        self._edit(sid, {ref: make_cell(text, False, self.tz)})

    def clear(self, ref, sheet=None):
        if self.viewing is not None:
            return
        ref = norm_ref(ref)
        b = self._cur()
        sid = self._resolve(sheet, b)
        if ref is None or sid is None:
            return
        if not self._can_write(sid):
            self._deny(sid, ref)
            return
        if ref not in b.cells[sid]:
            return
        self._edit(sid, {ref: None})

    def content(self, ref, sheet=None):
        b = self._book()
        sid = self._resolve(sheet, b)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        c = b.cells[sid].get(ref)
        return c[0] if c else None

    def _val(self, b, sid, ref):
        cell = b.cells[sid].get(ref)
        if cell is None:
            return None
        if is_formula(cell):
            return b.values.get((sid, ref))
        return cell_value(cell)

    def _display(self, v):
        if isinstance(v, Err):
            return v.code
        if isinstance(v, datetime):
            return v.astimezone(ZoneInfo(self.tz)).strftime("%Y-%m-%d %H:%M")
        if isinstance(v, date):
            return v.isoformat()
        return v

    def value(self, ref, sheet=None):
        b = self._book()
        sid = self._resolve(sheet, b)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        return self._display(self._val(b, sid, ref))

    def error(self, ref, sheet=None):
        b = self._book()
        sid = self._resolve(sheet, b)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        v = self._val(b, sid, ref)
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        self.tz = tz

    # ------------------------------------------------------------ feuilles
    def sheets(self):
        return list(self._book().sheets.values())

    def activate(self, name):
        sid = self._cur().sid_of(name)
        if sid is not None:
            self.active = sid

    def add_sheet(self, name):
        if self.viewing is not None or not name or not name.strip():
            return
        b = self._cur()
        if not b.name_free(name):
            self._alerts.append(Alert("nom_existant", name))
            return
        self._sn += 1
        sid = f"{self.name}-{self._sn}"
        do = {"type": "add_sheet", "sid": sid, "name": name}
        undo = {"type": "delete_sheet", "sid": sid}
        meta = {"sheet": name, "cell": None}
        oid = self._issue(do, meta)
        self._record({"do": do, "undo": undo, "sid": sid, "keys": [], "stamp": {},
                      "opid": oid, "meta": meta})

    def delete_sheet(self, name):
        if self.viewing is not None:
            return
        b = self._cur()
        sid = b.sid_of(name)
        if sid is None:
            return
        if not self._can_write(sid):
            self._deny(sid)
            return
        if len(b.sheets) <= 1:
            return
        snap = {ref: list(c) for ref, c in b.cells[sid].items()}
        sname = b.sheets[sid]
        do = {"type": "delete_sheet", "sid": sid}
        undo = {"type": "restore_sheet", "sid": sid, "name": sname, "cells": snap}
        meta = {"sheet": sname, "cell": None}
        oid = self._issue(do, meta)
        self._record({"do": do, "undo": undo, "sid": sid, "keys": [], "stamp": {},
                      "opid": oid, "meta": meta})

    def rename_sheet(self, old, new):
        if self.viewing is not None:
            return
        b = self._cur()
        sid = b.sid_of(old)
        if sid is None:
            return
        if not self._can_write(sid):
            self._deny(sid)
            return
        oldname = b.sheets[sid]
        if oldname == new or not new or not new.strip():
            return
        if not b.name_free(new, sid):
            self._alerts.append(Alert("nom_existant", new))
            return
        do = {"type": "rename_sheet", "sid": sid, "new": new}
        undo = {"type": "rename_sheet", "sid": sid, "new": oldname}
        meta = {"sheet": new, "cell": None}
        oid = self._issue(do, meta)
        self._record({"do": do, "undo": undo, "sid": sid, "keys": [], "stamp": {},
                      "opid": oid, "meta": meta})

    # ------------------------------------------------------------ droits
    def right(self, person, sheet):
        b = self._cur()
        sid = b.sid_of(sheet)
        if sid is None:
            return None
        return b.right(person, sid)

    def set_right(self, person, sheet, level):
        if self.owner is None or self.name != self.owner or not self.connected():
            return
        b = self._cur()
        sid = b.sid_of(sheet)
        if sid is None or level not in (W, R, None):
            return
        self._n += 1
        op = {"type": "set_right", "sid": sid, "person": person, "level": level,
              "id": f"{self.name}:{self._n}", "author": self.name,
              "ts": self.clock.now().isoformat()}
        self.net.send(self.name, "server", {"type": "op", "op": op})

    # ------------------------------------------------------------ alertes, connexion
    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self.connected() else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    # ------------------------------------------------------------ présence
    def select(self, ref, sheet=None):
        b = self._cur()
        sid = self._resolve(sheet, b)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        self.selection = [sid, ref]
        if self.connected():
            self.net.send(self.name, "server", {"type": "presence", "sel": self.selection})

    def presence(self):
        if not self.connected():
            return {}
        b = self._cur()
        out = {}
        for n, sel in self.presence_map.items():
            if n != self.name and sel[0] in b.sheets:
                out[n] = (b.sheets[sel[0]], sel[1])
        return out

    # ------------------------------------------------------------ conflits
    def conflict(self, ref, sheet=None):
        b = self._cur()
        sid = self._resolve(sheet, b)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        cf = b.conflicts.get((sid, ref))
        if cf is None:
            return None
        cell, by = cf
        return Conflict(cell[0] if cell else None, by)

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.viewing is not None:
            return
        b = self._cur()
        sid = self._resolve(sheet, b)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        if not self._can_write(sid):
            self._deny(sid, ref)
            return
        cf = b.conflicts.get((sid, ref))
        if cf is None:
            return
        cell = cf[0] if use_discarded else b.cells[sid].get(ref)
        self._edit(sid, {ref: cell}, force=True, record=False)

    # ------------------------------------------------------------ annuler / rétablir
    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _stale(self, act):
        return any(self.fkey.get(k, 0) != v for k, v in act["stamp"].items())

    def undo(self):
        if self.viewing is not None or not self.undo_stack:
            return
        act = self.undo_stack[-1]
        if not self._can_write(act["sid"]):
            self._deny(act["sid"])
            return
        self.undo_stack.pop()
        if self._stale(act):
            self._alerts.append(Alert("annulation_impossible", act["meta"].get("sheet")))
            return
        idx = next((i for i, r in enumerate(self.pending)
                    if r["op"]["id"] == act["opid"] and not r["sent"]), None)
        if idx is not None:
            self.pending.pop(idx)
            self._rebuild_view()
        else:
            self._issue(act["undo"], act["meta"])
        act["stamp"] = self._stamp(act["keys"])
        self.redo_stack.append(act)

    def redo(self):
        if self.viewing is not None or not self.redo_stack:
            return
        act = self.redo_stack[-1]
        if not self._can_write(act["sid"]):
            self._deny(act["sid"])
            return
        self.redo_stack.pop()
        if self._stale(act):
            self._alerts.append(Alert("annulation_impossible", act["meta"].get("sheet")))
            return
        act["opid"] = self._issue(act["do"], act["meta"])
        act["stamp"] = self._stamp(act["keys"])
        self.undo_stack.append(act)

    # ------------------------------------------------------------ historique
    def history(self, sheet=None):
        b = self._cur()
        sid = self._resolve(sheet, b)
        tz = ZoneInfo(self.tz)
        out = []
        for e in self.log:
            op = e["op"]
            if op["type"] == "set":
                if op["sid"] != sid or len(e.get("skip") or ()) >= len(op["cells"]):
                    continue
                kind = "modification"
            elif op["type"] == "restore_version":
                if op["sid"] != sid:
                    continue
                kind = "restauration"
            else:
                continue
            ts = datetime.fromisoformat(op["ts"])
            out.append((ts, e["seq"],
                        Version(e["seq"], op["author"], ts.astimezone(tz).strftime("%Y-%m-%d %H:%M"), kind)))
        out.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [v for _, _, v in out]

    def _snapshot(self, seq):
        b = Book(self.owner)
        b.now = self.clock.now()
        for e in self.log[:seq]:
            b.apply(e)
        return b

    def open_version(self, version_id):
        if not isinstance(version_id, int) or not 1 <= version_id <= len(self.log):
            return
        self.viewing = self._snapshot(version_id)

    def close_version(self):
        self.viewing = None

    def restore_version(self, version_id):
        if not isinstance(version_id, int) or not 1 <= version_id <= len(self.log):
            return
        op = self.log[version_id - 1]["op"]
        if op["type"] not in ("set", "restore_version"):
            return
        sid = op["sid"]
        cur = self._cur()
        if sid not in cur.sheets:
            return
        if not self._can_write(sid):
            self._deny(sid)
            return
        snap = self._snapshot(version_id)
        if sid not in snap.sheets:
            return
        do = {"type": "restore_version", "sid": sid, "name": snap.sheets[sid],
              "cells": {r: list(c) for r, c in snap.cells[sid].items()}}
        undo = {"type": "restore_version", "sid": sid, "name": cur.sheets[sid],
                "cells": {r: list(c) for r, c in cur.cells[sid].items()}}
        meta = {"sheet": cur.sheets[sid], "cell": None}
        self.viewing = None
        oid = self._issue(do, meta)
        self._record({"do": do, "undo": undo, "sid": sid, "keys": [], "stamp": {},
                      "opid": oid, "meta": meta})

    # ------------------------------------------------------------ CSV
    def _fmt(self, b, sid, ref):
        v = self._val(b, sid, ref)
        if v is None:
            return ""
        if isinstance(v, Err):
            return v.code
        if isinstance(v, datetime):
            return v.astimezone(ZoneInfo(self.tz)).replace(microsecond=0).isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() else repr(v)
        return str(v)

    def export_csv(self):
        b = self._book()
        sid = self._resolve(None, b)
        cells = b.cells.get(sid, {})
        rows = {}
        maxc = -1
        for ref in cells:
            col, row = split_ref(ref)
            ci = col_index(col)
            rows.setdefault(row, {})[ci] = ref
            maxc = max(maxc, ci)
        buf = io.StringIO()
        wr = csv.writer(buf, lineterminator="\r\n")
        for row in sorted(rows):
            fields = [""] * (maxc + 1)
            for ci, ref in rows[row].items():
                fields[ci] = self._fmt(b, sid, ref)
            wr.writerow(fields)
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.viewing is not None:
            return
        b = self._cur()
        sid = self._resolve(None, b)
        if sid is None:
            return
        if not self._can_write(sid):
            self._deny(sid)
            return
        try:
            text = data.decode("utf-8-sig") if isinstance(data, (bytes, bytearray)) else str(data)
            rows = parse_csv(text)
        except CsvError as e:
            self._alerts.append(Alert("csv_invalide", b.sheets[sid], None, e.line))
            return
        except UnicodeDecodeError:
            self._alerts.append(Alert("csv_invalide", b.sheets[sid], None, 1))
            return
        cells = {}
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                ref = col_name(c) + str(r + 1)
                cells[ref] = make_cell(text, text.startswith("="), self.tz) if text != "" else None
        if not cells:
            return
        self._edit(sid, cells)
