"""Classeur collaboratif hors ligne : formules, copies locales, réseau simulé, fuseaux."""
import collections
import csv
import io
import pickle
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import NamedTuple, Optional
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"
FMT = "%Y-%m-%d %H:%M"


# ====================================================================== temps et réseau

class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Message:
    def __init__(self, src, dst, payload):
        self.src = src
        self.dst = dst
        self.payload = payload
        self.delivered = False


class Network:
    def __init__(self):
        self.nodes = {}
        self.queue = collections.deque()
        self.offline = set()

    def register(self, name, node):
        self.nodes[name] = node

    def is_online(self, name):
        return name not in self.offline

    def send(self, src, dst, payload):
        m = Message(src, dst, pickle.dumps(payload))
        if src in self.offline or dst in self.offline:
            return m
        self.queue.append(m)
        return m

    def cancel(self, m):
        try:
            self.queue.remove(m)
        except ValueError:
            pass

    def _deliver(self, m):
        m.delivered = True
        node = self.nodes.get(m.dst)
        if node is not None:
            node.receive(m.src, pickle.loads(m.payload))

    def deliver_all(self):
        while self.queue:
            self._deliver(self.queue.popleft())

    def deliver_from(self, name):
        batch = [m for m in self.queue if m.src == name]
        for m in batch:
            if m in self.queue:
                self.queue.remove(m)
                self._deliver(m)

    def disconnect(self, name):
        self.offline.add(name)
        self.queue = collections.deque(m for m in self.queue if m.src != name and m.dst != name)
        srv = self.nodes.get("server")
        if srv is not None and name != "server":
            srv.peer_disconnected(name)

    def reconnect(self, name):
        self.offline.discard(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_reconnect"):
            node.on_reconnect()


# ====================================================================== modèle

class Cell(NamedTuple):
    raw: str
    lit: bool = False
    tz: Optional[str] = None


class Conflict(NamedTuple):
    discarded: Optional[Cell]
    by: str


class Rec(NamedTuple):
    cell: Optional[Cell]
    ver: int
    last_op: Optional[str]
    conflict: Optional[Conflict]


EMPTY = Rec(None, 0, None, None)


class Version(NamedTuple):
    id: str
    seq: int
    author: str
    ts: datetime
    kind: str
    sheet: str
    name: str
    cells: dict


class Sheet:
    def __init__(self, name, cells=None):
        self.name = name
        self.cells = cells if cells is not None else {}


class Workbook:
    def __init__(self, owner=None):
        self.owner = owner
        self.sheets = {}
        self.order = []
        self.rights = {}

    def clone(self):
        c = Workbook(self.owner)
        c.sheets = {k: Sheet(s.name, dict(s.cells)) for k, s in self.sheets.items()}
        c.order = list(self.order)
        c.rights = dict(self.rights)
        return c

    def find(self, name):
        k = name.casefold()
        for sid in self.order:
            if self.sheets[sid].name.casefold() == k:
                return sid
        return None

    def names(self):
        return [self.sheets[i].name for i in self.order]


def sheet_cells(sh):
    return {ref: r.cell for ref, r in sh.cells.items() if r.cell is not None}


SHEET_Q = re.compile(r"('(?:[^']|'')+'|\w+)!")


def fmt_sheet(name):
    if re.fullmatch(r"\w+", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def is_formula(cell):
    return (not cell.lit) and cell.raw.startswith("=")


def rewrite_all(wb, old, new):
    oldk = old.casefold()

    def rep(m):
        tok = m.group(1)
        name = tok[1:-1].replace("''", "'") if tok.startswith("'") else tok
        if name.casefold() != oldk:
            return m.group(0)
        return fmt_sheet(new) + "!"

    for sh in wb.sheets.values():
        for ref, rec in list(sh.cells.items()):
            c = rec.cell
            if c is not None and is_formula(c):
                nr = SHEET_Q.sub(rep, c.raw)
                if nr != c.raw:
                    sh.cells[ref] = rec._replace(cell=c._replace(raw=nr))


def apply_op(wb, op, seq=None, outcomes=None):
    """Transition déterministe. seq=None : application locale optimiste."""
    k = op["kind"]
    local = seq is None
    if k == "set":
        sh = wb.sheets.get(op["sheet"])
        if sh is None:
            return
        for i, (ref, cell, _root, _prev) in enumerate(op["changes"]):
            out = outcomes[i] if outcomes else "ok"
            rec = sh.cells.get(ref, EMPTY)
            if out == "ok":
                if local:
                    sh.cells[ref] = Rec(cell, rec.ver, rec.last_op, None)
                else:
                    sh.cells[ref] = Rec(cell, seq, op["id"], None)
            elif out == "conflict":
                sh.cells[ref] = rec._replace(conflict=Conflict(cell, op["by"]))
    elif k == "resolve":
        sh = wb.sheets.get(op["sheet"])
        if sh is None:
            return
        if outcomes and outcomes[0] != "ok":
            return
        ref = op["ref"]
        rec = sh.cells.get(ref, EMPTY)
        if rec.conflict is None:
            return
        if op["use_discarded"]:
            sh.cells[ref] = Rec(rec.conflict.discarded, rec.ver if local else seq,
                                rec.last_op if local else op["id"], None)
        else:
            sh.cells[ref] = rec._replace(conflict=None)
    elif k == "add_sheet":
        sid = op["sheet"]
        if sid in wb.sheets:
            return
        wb.sheets[sid] = Sheet(op["name"])
        wb.order.append(sid)
        if wb.owner:
            wb.rights[(wb.owner, sid)] = W
        wb.rights[(op["by"], sid)] = W
    elif k == "undelete":
        snap = op["snap"]
        sid = snap["id"]
        if sid in wb.sheets:
            return
        cells = {ref: Rec(c, 0 if local else seq, None if local else op["id"], None)
                 for ref, c in snap["cells"].items()}
        wb.sheets[sid] = Sheet(snap["name"], cells)
        wb.order.insert(min(snap["index"], len(wb.order)), sid)
        for p, lvl in snap["rights"].items():
            wb.rights[(p, sid)] = lvl
    elif k == "delete_sheet":
        sid = op["sheet"]
        if sid not in wb.sheets:
            return
        del wb.sheets[sid]
        wb.order.remove(sid)
        for key in [key for key in wb.rights if key[1] == sid]:
            del wb.rights[key]
    elif k == "rename":
        sh = wb.sheets.get(op["sheet"])
        if sh is None:
            return
        old, new = sh.name, op["name"]
        sh.name = new
        if old != new:
            rewrite_all(wb, old, new)
    elif k == "replace":
        sh = wb.sheets.get(op["sheet"])
        if sh is None:
            return
        if sh.name != op["name"]:
            old = sh.name
            sh.name = op["name"]
            rewrite_all(wb, old, sh.name)
        cells = op["cells"]
        for ref in set(sh.cells) | set(cells):
            new = cells.get(ref)
            rec = sh.cells.get(ref, EMPTY)
            if new != rec.cell:
                sh.cells[ref] = Rec(new, rec.ver if local else seq, rec.last_op if local else op["id"], None)
            elif rec.conflict is not None:
                sh.cells[ref] = rec._replace(conflict=None)
    elif k == "right":
        if op["sheet"] in wb.sheets:
            wb.rights[(op["person"], op["sheet"])] = op["level"]


class State:
    def __init__(self, wb, hist, seq):
        self.wb = wb
        self.hist = hist
        self.seq = seq

    def apply(self, op, seq, outcomes):
        k = op["kind"]
        apply_op(self.wb, op, seq, outcomes)
        sid = op.get("sheet")
        if k == "add_sheet":
            self.hist.setdefault(sid, [])
        elif k == "undelete":
            self.hist.setdefault(op["snap"]["id"], [])
        elif k == "delete_sheet":
            self.hist.pop(sid, None)
        changed = ((k == "set" and "ok" in outcomes)
                   or (k == "resolve" and op["use_discarded"] and outcomes[0] == "ok")
                   or k == "replace")
        if changed and sid in self.wb.sheets:
            sh = self.wb.sheets[sid]
            self.hist.setdefault(sid, []).append(
                Version(f"v{seq}", seq, op["by"], op["ts"], op.get("label", "modification"),
                        sid, sh.name, sheet_cells(sh)))
        self.seq = seq


# ====================================================================== formules

class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


ERR_TYPE = Err("#TYPE!")
ERR_DIV = Err("#DIV/0!")
ERR_SYN = Err("#SYNTAXE!")
ERR_CIRC = Err("#CIRC!")
ERR_REF = Err("#REF!")


class DT(NamedTuple):
    inst: datetime
    wall: Optional[datetime]
    tzkey: Optional[str]


class FormulaSyntax(Exception):
    pass


_SHEETREF = re.compile(r"(?:('(?:[^']|'')+'|\w+)!)?([A-Za-z]{1,3}\d+)(?![\w(])")
_FUNC = re.compile(r"([^\W\d]\w*)\s*\(")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _tokenize(s):
    toks = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        m = _SHEETREF.match(s, i)
        if m:
            sh = m.group(1)
            if sh and sh.startswith("'"):
                sh = sh[1:-1].replace("''", "'")
            toks.append(("ref", sh, m.group(2).upper()))
            i = m.end()
            continue
        m = _FUNC.match(s, i)
        if m:
            toks.append(("func", m.group(1).upper()))
            i = m.end()
            toks.append(("(",))
            continue
        m = _NUM.match(s, i)
        if m:
            t = m.group(0)
            toks.append(("num", float(t) if "." in t else int(t)))
            i = m.end()
            continue
        if ch in "+-*/():,;":
            toks.append((ch,))
            i += 1
            continue
        raise FormulaSyntax()
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.p = 0

    def peek(self):
        return self.t[self.p] if self.p < len(self.t) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise FormulaSyntax()
        self.p += 1
        return tok

    def expr(self):
        left = self.term()
        while True:
            tok = self.peek()
            if tok is not None and tok[0] in ("+", "-"):
                self.p += 1
                left = ("bin", tok[0], left, self.term())
            else:
                return left

    def term(self):
        left = self.unary()
        while True:
            tok = self.peek()
            if tok is not None and tok[0] in ("*", "/"):
                self.p += 1
                left = ("bin", tok[0], left, self.unary())
            else:
                return left

    def unary(self):
        tok = self.peek()
        if tok is not None and tok[0] in ("+", "-"):
            self.p += 1
            inner = self.unary()
            return ("neg", inner) if tok[0] == "-" else inner
        return self.primary()

    def primary(self):
        tok = self.take()
        k = tok[0]
        if k == "num":
            return ("num", tok[1])
        if k == "ref":
            return ("ref", tok[1], tok[2])
        if k == "(":
            e = self.expr()
            if self.take()[0] != ")":
                raise FormulaSyntax()
            return e
        if k == "func":
            if self.take()[0] != "(":
                raise FormulaSyntax()
            args = []
            nxt = self.peek()
            if nxt is not None and nxt[0] == ")":
                self.p += 1
            else:
                while True:
                    args.append(self.arg())
                    sep = self.take()
                    if sep[0] == ")":
                        break
                    if sep[0] not in (",", ";"):
                        raise FormulaSyntax()
            name = tok[1]
            if name == "SOMME" and len(args) >= 1:
                return ("call", name, args)
            if name == "MAINTENANT" and not args:
                return ("call", name, args)
            raise FormulaSyntax()
        raise FormulaSyntax()

    def arg(self):
        a = self.peek()
        b = self.t[self.p + 1] if self.p + 1 < len(self.t) else None
        if a is not None and a[0] == "ref" and b is not None and b[0] == ":":
            self.p += 2
            c = self.take()
            if c[0] != "ref" or c[1] is not None:
                raise FormulaSyntax()
            return ("range", a[1], a[2], c[2])
        return self.expr()


@lru_cache(maxsize=None)
def parse_formula(raw):
    try:
        p = _Parser(_tokenize(raw[1:]))
        ast = p.expr()
        if p.p != len(p.t):
            return None
        return ast
    except FormulaSyntax:
        return None


@lru_cache(maxsize=None)
def split_ref(ref):
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", ref)
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + ord(ch) - 64
    return col, int(m.group(2))


def col_letters(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def norm_ref(ref):
    if not isinstance(ref, str):
        return None
    ref = ref.strip().upper()
    if re.fullmatch(r"[A-Z]{1,3}[1-9]\d*", ref):
        return ref
    return None


_NUMRAW = re.compile(r"[+-]?\d+(?:\.\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NAIVE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")
_AWARE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})")


def is_naive_dt(text):
    return bool(_NAIVE.fullmatch(text.strip()))


def make_cell(text, tz, literal_eq=False):
    return Cell(text, bool(literal_eq and text.startswith("=")), tz if is_naive_dt(text) else None)


@lru_cache(maxsize=None)
def parse_raw(cell):
    raw = cell.raw
    if cell.lit:
        return raw
    s = raw.strip()
    if _NUMRAW.fullmatch(s):
        return float(s) if "." in s else int(s)
    try:
        if _DATE.fullmatch(s):
            return date.fromisoformat(s)
        if _NAIVE.fullmatch(s):
            naive = datetime.fromisoformat(s.replace(" ", "T"))
            zone = ZoneInfo(cell.tz) if cell.tz else UTC
            return DT(naive.replace(tzinfo=zone).astimezone(UTC), naive, cell.tz)
        if _AWARE.fullmatch(s):
            return DT(datetime.fromisoformat(s.replace(" ", "T")).astimezone(UTC), None, None)
    except ValueError:
        return raw
    return raw


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _arith(op, a, b):
    if op == "-":
        if isinstance(a, DT) and isinstance(b, DT):
            return (a.inst - b.inst).total_seconds() / 86400
        if isinstance(a, date) and isinstance(b, date):
            return (a - b).days
    if not (_is_num(a) and _is_num(b)):
        return ERR_TYPE
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        return ERR_DIV
    if isinstance(a, int) and isinstance(b, int) and a % b == 0:
        return a // b
    return a / b


def _collect(ast):
    out = []
    stack = [ast]
    while stack:
        n = stack.pop()
        t = n[0]
        if t in ("ref", "range"):
            out.append(n)
        elif t == "neg":
            stack.append(n[1])
        elif t == "bin":
            stack.append(n[2])
            stack.append(n[3])
        elif t == "call":
            stack.extend(n[2])
    return out


def evaluate(sheets, now):
    """sheets : {clé_feuille: (nom, {ref: Cell})} -> {(clé, ref): valeur | Err} pour les formules."""
    nodes = {}
    by_sheet = {}
    for skey, (_name, cells) in sheets.items():
        for ref, cell in cells.items():
            if is_formula(cell):
                nodes[(skey, ref)] = parse_formula(cell.raw)
                col, row = split_ref(ref)
                by_sheet.setdefault(skey, []).append((col, row, (skey, ref)))

    def box(a, b):
        c1, r1 = split_ref(a)
        c2, r2 = split_ref(b)
        return min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)

    deps = {}
    for key, ast in nodes.items():
        ds = set()
        if ast is not None:
            for n in _collect(ast):
                skey = (n[1] if n[1] is not None else sheets[key[0]][0]).casefold()
                if n[0] == "ref":
                    k2 = (skey, n[2])
                    if k2 in nodes:
                        ds.add(k2)
                else:
                    c1, r1, c2, r2 = box(n[2], n[3])
                    for col, row, k2 in by_sheet.get(skey, ()):
                        if c1 <= col <= c2 and r1 <= row <= r2:
                            ds.add(k2)
        deps[key] = ds

    index, low = {}, {}
    onstack = set()
    stack = []
    sccs = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack.add(root)
        work = [(root, iter(deps[root]))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(deps[w])))
                    advanced = True
                    break
                elif w in onstack:
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
                sccs.append(comp)

    res = {}

    def lookup(skey, ref):
        if skey not in sheets:
            return ERR_REF
        k = (skey, ref)
        if k in res:
            return res[k]
        cell = sheets[skey][1].get(ref)
        if cell is None:
            return 0
        return parse_raw(cell)

    def ev(n, cur):
        t = n[0]
        if t == "num":
            return n[1]
        if t == "ref":
            return lookup((n[1] if n[1] is not None else sheets[cur][0]).casefold(), n[2])
        if t == "neg":
            v = ev(n[1], cur)
            if isinstance(v, Err):
                return v
            return -v if _is_num(v) else ERR_TYPE
        if t == "bin":
            a = ev(n[2], cur)
            if isinstance(a, Err):
                return a
            b = ev(n[3], cur)
            if isinstance(b, Err):
                return b
            return _arith(n[1], a, b)
        if t == "call":
            if n[1] == "MAINTENANT":
                return DT(now, None, None)
            total = 0
            for a in n[2]:
                if a[0] == "range":
                    skey = (a[1] if a[1] is not None else sheets[cur][0]).casefold()
                    if skey not in sheets:
                        return ERR_REF
                    c1, r1, c2, r2 = box(a[2], a[3])
                    for ref in sheets[skey][1]:
                        col, row = split_ref(ref)
                        if c1 <= col <= c2 and r1 <= row <= r2:
                            v = lookup(skey, ref)
                            if isinstance(v, Err):
                                return v
                            if _is_num(v):
                                total += v
                else:
                    v = ev(a, cur)
                    if isinstance(v, Err):
                        return v
                    if _is_num(v):
                        total += v
            return total
        return ERR_TYPE

    for comp in sccs:
        if len(comp) > 1 or comp[0] in deps[comp[0]]:
            for k in comp:
                res[k] = ERR_CIRC
        else:
            k = comp[0]
            ast = nodes[k]
            res[k] = ERR_SYN if ast is None else ev(ast, k[0])
    return res


# ====================================================================== CSV

def parse_csv(text):
    """Retourne (lignes, None) ou (None, numéro de ligne invalide)."""
    rows = []
    row = []
    field = []
    started = False
    at_start = True
    in_q = False
    qline = 0
    line = 1
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_q:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_q = False
                i += 1
                continue
            if ch == "\n":
                line += 1
            field.append(ch)
            i += 1
            continue
        if ch == '"' and at_start:
            in_q = True
            qline = line
            at_start = False
            started = True
            i += 1
            continue
        if ch == ",":
            row.append("".join(field))
            field = []
            started = True
            at_start = True
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if started or field or row:
                row.append("".join(field))
                rows.append(row)
            else:
                rows.append([])
            row, field, started, at_start = [], [], False, True
            line += 1
            i += 1
            continue
        field.append(ch)
        at_start = False
        started = True
        i += 1
    if in_q:
        return None, qline
    if started or field or row:
        row.append("".join(field))
        rows.append(row)
    return rows, None


# ====================================================================== serveur

class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        wb = Workbook(owner)
        wb.sheets["s0"] = Sheet("Feuille1")
        wb.order.append("s0")
        wb.rights[(owner, "s0")] = W
        self.state = State(wb, {"s0": []}, 0)
        self.results = {}
        self.online = {}
        self.presence = {}
        net.register("server", self)

    def _send(self, dst, payload):
        self.net.send("server", dst, payload)

    def _broadcast(self, payload, exclude=None):
        for c in list(self.online):
            if c != exclude:
                self._send(c, payload)

    def peer_disconnected(self, name):
        self.online.pop(name, None)
        if self.presence.pop(name, None) is not None:
            self._broadcast({"type": "presence", "who": name, "at": None})

    def receive(self, src, msg):
        t = msg["type"]
        if t == "hello":
            self.online[src] = True
            if msg.get("selection"):
                self.presence[src] = tuple(msg["selection"])
                self._broadcast({"type": "presence", "who": src, "at": self.presence[src]}, exclude=src)
            pres = {} if msg.get("fresh") else dict(self.presence)
            self._send(src, {"type": "snapshot", "state": self.state, "presence": pres})
        elif t == "select":
            self.presence[src] = (msg["sheet"], msg["ref"])
            self._broadcast({"type": "presence", "who": src, "at": self.presence[src]}, exclude=src)
        elif t == "op":
            op = msg["op"]
            op["by"] = src
            oid = op["id"]
            if oid in self.results:
                self._send(src, {"type": "result", "op_id": oid, "res": self.results[oid]})
                return
            d = self._decide(src, op)
            if d[0] == "ok":
                outs = d[1]
                seq = self.state.seq + 1
                self.state.apply(op, seq, outs)
                self.results[oid] = ("ok",)
                self._broadcast({"type": "applied", "seq": seq, "op": op, "outs": outs})
            else:
                res = d if d[0] == "reject" else ("noop",)
                self.results[oid] = res
                self._send(src, {"type": "result", "op_id": oid, "res": res})

    def _decide(self, author, op):
        wb = self.state.wb
        k = op["kind"]

        def can_write(sid):
            return wb.rights.get((author, sid)) == W

        def name_taken(name, except_sid=None):
            key = name.casefold()
            return any(s.name.casefold() == key for i, s in wb.sheets.items() if i != except_sid)

        if k == "set":
            sh = wb.sheets.get(op["sheet"])
            if sh is None:
                return ("reject", "sheet_deleted")
            if not can_write(op["sheet"]):
                return ("reject", "droit")
            outs = []
            for ref, cell, root, prev in op["changes"]:
                rec = sh.cells.get(ref, EMPTY)
                if cell == rec.cell:
                    outs.append("noop")
                elif root == rec.ver or (prev is not None and prev == rec.last_op):
                    outs.append("ok")
                else:
                    outs.append("conflict")
            if all(o == "noop" for o in outs):
                return ("noop",)
            return ("ok", outs)
        if k == "resolve":
            sh = wb.sheets.get(op["sheet"])
            if sh is None:
                return ("reject", "sheet_deleted")
            if not can_write(op["sheet"]):
                return ("reject", "droit")
            if sh.cells.get(op["ref"], EMPTY).conflict is None:
                return ("noop",)
            return ("ok", ["ok"])
        if k == "add_sheet":
            if op["sheet"] in wb.sheets:
                return ("noop",)
            if name_taken(op["name"]):
                return ("reject", "nom_existant")
            return ("ok", ["ok"])
        if k == "delete_sheet":
            if op["sheet"] not in wb.sheets:
                return ("noop",)
            if not can_write(op["sheet"]):
                return ("reject", "droit")
            if len(wb.order) <= 1:
                return ("reject", "last")
            return ("ok", ["ok"])
        if k == "undelete":
            snap = op["snap"]
            if snap["id"] in wb.sheets:
                return ("noop",)
            if snap["rights"].get(author) != W and author != wb.owner:
                return ("reject", "droit")
            if name_taken(snap["name"]):
                return ("reject", "nom_existant")
            return ("ok", ["ok"])
        if k == "rename":
            sh = wb.sheets.get(op["sheet"])
            if sh is None:
                return ("reject", "sheet_deleted")
            if not can_write(op["sheet"]):
                return ("reject", "droit")
            if op["name"] == sh.name:
                return ("noop",)
            if name_taken(op["name"], op["sheet"]):
                return ("reject", "nom_existant")
            return ("ok", ["ok"])
        if k == "replace":
            sh = wb.sheets.get(op["sheet"])
            if sh is None:
                return ("reject", "sheet_deleted")
            if not can_write(op["sheet"]):
                return ("reject", "droit")
            if name_taken(op["name"], op["sheet"]):
                return ("reject", "nom_existant")
            if sh.name == op["name"] and sheet_cells(sh) == op["cells"] \
                    and all(r.conflict is None for r in sh.cells.values()):
                return ("noop",)
            return ("ok", ["ok"])
        if k == "right":
            if author != wb.owner:
                return ("reject", "droit")
            if op["sheet"] not in wb.sheets or op["person"] == wb.owner or op["level"] not in (W, R):
                return ("noop",)
            if wb.rights.get((op["person"], op["sheet"])) == op["level"]:
                return ("noop",)
            return ("ok", ["ok"])
        return ("noop",)


# ====================================================================== client

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line

    def __repr__(self):
        return f"Alert({self.kind!r}, {self.sheet!r}, {self.cell!r}, {self.line!r})"


class ConflictView:
    def __init__(self, conflict):
        self.discarded = None if conflict.discarded is None else conflict.discarded.raw
        self.discarded_by = conflict.by


class VersionView:
    def __init__(self, v, zone):
        self.id = v.id
        self.author = v.author
        self.kind = v.kind
        self.timestamp = v.ts.astimezone(zone).strftime(FMT)


class Pend:
    def __init__(self, op):
        self.op = op
        self.msg = None


class Client:
    def __init__(self, net, clock, name, tz="Europe/Paris", _blob=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self._zone = ZoneInfo(tz)
        self.pending = []
        self._opn = 0
        self._alerts = []
        self._undo = []
        self._redo = []
        self._view = None
        self._presence = {}
        self._selection = None
        self.active = "s0"
        self._evc = None
        self._vrev = 0
        fresh = False
        if _blob is not None:
            d = pickle.loads(_blob)
            self.base = d["base"]
            self.pending = [Pend(op) for op in d["ops"]]
            self._opn = d["opn"]
            self.active = d["active"]
            fresh = True
        else:
            wb = Workbook(None)
            wb.sheets["s0"] = Sheet("Feuille1")
            wb.order.append("s0")
            self.base = State(wb, {"s0": []}, 0)
        self._rebuild()
        net.register(name, self)
        if net.is_online(name):
            self._connect(fresh)

    # ---------------------------------------------------------------- réseau
    def _connect(self, fresh=False):
        self.net.send(self.name, "server", {"type": "hello", "fresh": fresh, "selection": self._selection})
        for e in self.pending:
            self._send_op(e)

    def on_reconnect(self):
        self._connect(False)

    def _online(self):
        return self.net.is_online(self.name)

    def _send_op(self, e):
        if self._online():
            e.msg = self.net.send(self.name, "server", {"type": "op", "op": e.op})

    def receive(self, src, msg):
        t = msg["type"]
        if t == "applied":
            seq = msg["seq"]
            if seq != self.base.seq + 1:
                return
            self.base.apply(msg["op"], seq, msg["outs"])
            self._drop(msg["op"]["id"])
            self._rebuild()
        elif t == "result":
            e = self._drop(msg["op_id"])
            if e is not None:
                if msg["res"][0] == "reject":
                    self._reject_alerts(e.op, msg["res"][1])
                self._rebuild()
        elif t == "snapshot":
            self.base = msg["state"]
            self._presence = dict(msg["presence"])
            self._rebuild()
        elif t == "presence":
            if msg["at"] is None:
                self._presence.pop(msg["who"], None)
            else:
                self._presence[msg["who"]] = tuple(msg["at"])

    def _drop(self, oid):
        for e in self.pending:
            if e.op["id"] == oid:
                self.pending.remove(e)
                return e
        return None

    def _reject_alerts(self, op, reason):
        name = op.get("sheet_name")
        if reason == "droit":
            if op["kind"] == "set":
                for ch in op["changes"]:
                    self._alert("modification_rejetee", name, ch[0])
            elif op["kind"] == "resolve":
                self._alert("modification_rejetee", name, op["ref"])
            else:
                self._alert("modification_rejetee", name)
        elif reason == "sheet_deleted":
            self._alert("feuille_supprimee", name)
        elif reason == "nom_existant":
            self._alert("nom_existant", op.get("name") or name)

    # ---------------------------------------------------------------- état local
    def _rebuild(self):
        wb = self.base.wb.clone()
        for e in self.pending:
            apply_op(wb, e.op)
        self.visible = wb
        self._vrev += 1

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def alerts(self):
        return list(self._alerts)

    def _aid(self):
        if self.active in self.visible.sheets:
            return self.active
        return self.visible.order[0]

    def _sid(self, sheet):
        if sheet is None:
            return self._aid()
        return self.visible.find(sheet)

    def _writable(self, sid):
        return self.visible.rights.get((self.name, sid)) == W

    def _new_op(self, kind, **kw):
        self._opn += 1
        op = {"id": f"{self.name}:{self._opn}", "by": self.name, "ts": self.clock.now(), "kind": kind}
        op.update(kw)
        return op

    def _submit(self, op):
        apply_op(self.visible, op)
        self._vrev += 1
        e = Pend(op)
        self.pending.append(e)
        self._send_op(e)
        return e

    def _prev_pending(self, sid, ref):
        for e in reversed(self.pending):
            op = e.op
            k = op["kind"]
            if k == "set" and op["sheet"] == sid and any(c[0] == ref for c in op["changes"]):
                return op["id"]
            if k == "resolve" and op["sheet"] == sid and op["ref"] == ref:
                return op["id"]
            if k == "replace" and op["sheet"] == sid:
                return op["id"]
        return None

    def _edit(self, sid, items):
        sh = self.visible.sheets[sid]
        changes = []
        acts = []
        bsh = self.base.wb.sheets.get(sid)
        for ref, cell in items:
            rec = sh.cells.get(ref, EMPTY)
            if cell == rec.cell:
                continue
            brec = bsh.cells.get(ref, EMPTY) if bsh is not None else EMPTY
            changes.append((ref, cell, brec.ver, self._prev_pending(sid, ref)))
            acts.append((sid, ref, rec.cell, cell))
        if not changes:
            return None
        op = self._new_op("set", sheet=sid, sheet_name=sh.name, changes=changes)
        self._submit(op)
        return op, acts

    def _new_action(self, act):
        self._undo.append(act)
        self._redo = []

    # ---------------------------------------------------------------- cellules
    def _target(self, sheet, ref):
        sid = self._sid(sheet)
        return sid, norm_ref(ref)

    def set_cell(self, ref, text, sheet=None):
        sid, ref = self._target(sheet, ref)
        if sid is None or ref is None or self._view is not None:
            return
        sh = self.visible.sheets[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name, ref)
            return
        cell = make_cell(text, self.tz) if text else None
        res = self._edit(sid, [(ref, cell)])
        if res:
            self._new_action({"t": "cells", "changes": res[1], "ops": [res[0]["id"]]})

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def import_csv(self, data):
        sid = self._aid()
        sh = self.visible.sheets[sid]
        if self._view is not None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        text = bytes(data).decode("utf-8-sig", errors="replace")
        rows, bad = parse_csv(text)
        if rows is None:
            self._alert("csv_invalide", sh.name, None, bad)
            return
        items = []
        for r, row in enumerate(rows, 1):
            for c, f in enumerate(row, 1):
                cell = make_cell(f, self.tz, literal_eq=True) if f != "" else None
                items.append((col_letters(c) + str(r), cell))
        res = self._edit(sid, items)
        if res:
            self._new_action({"t": "cells", "changes": res[1], "ops": [res[0]["id"]]})

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sid, ref = self._target(sheet, ref)
        if sid is None or ref is None or self._view is not None:
            return
        sh = self.visible.sheets[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name, ref)
            return
        if sh.cells.get(ref, EMPTY).conflict is None:
            return
        self._submit(self._new_op("resolve", sheet=sid, sheet_name=sh.name, ref=ref,
                                  use_discarded=bool(use_discarded)))

    # ---------------------------------------------------------------- lecture
    def _cells_of(self, sid):
        if self._view is not None and self._view[0] == sid:
            return self._view[1].cells
        return sheet_cells(self.visible.sheets[sid])

    def _ev(self):
        vk = None if self._view is None else (self._view[0], self._view[1].id)
        key = (self._vrev, self.clock.now(), vk)
        if self._evc is not None and self._evc[0] == key:
            return self._evc[1]
        sheets = {}
        for sid in self.visible.order:
            sh = self.visible.sheets[sid]
            sheets[sh.name.casefold()] = (sh.name, self._cells_of(sid))
        res = evaluate(sheets, self.clock.now())
        self._evc = (key, res)
        return res

    def _lookup(self, ref, sheet):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None, None
        sh = self.visible.sheets[sid]
        cell = self._cells_of(sid).get(ref)
        if cell is None:
            return sh, None
        if is_formula(cell):
            return sh, self._ev().get((sh.name.casefold(), ref))
        return sh, parse_raw(cell)

    def content(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        cell = self._cells_of(sid).get(ref)
        return None if cell is None else cell.raw

    def _dt_local(self, v):
        if v.wall is not None and v.tzkey == self.tz:
            return v.wall.replace(tzinfo=self._zone)
        return v.inst.astimezone(self._zone)

    def value(self, ref, sheet=None):
        _, r = self._lookup(ref, sheet)
        if r is None:
            return None
        if isinstance(r, Err):
            return r.code
        if isinstance(r, DT):
            d = self._dt_local(r)
            return d.strftime(FMT)
        if isinstance(r, date):
            return r.isoformat()
        return r

    def error(self, ref, sheet=None):
        _, r = self._lookup(ref, sheet)
        return r.code if isinstance(r, Err) else None

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        rec = self.visible.sheets[sid].cells.get(ref)
        if rec is None or rec.conflict is None:
            return None
        return ConflictView(rec.conflict)

    # ---------------------------------------------------------------- feuilles
    def sheets(self):
        return self.visible.names()

    def activate(self, name):
        sid = self.visible.find(name)
        if sid is not None:
            self.active = sid

    def _snap(self, sid):
        sh = self.visible.sheets[sid]
        return {"id": sid, "name": sh.name, "index": self.visible.order.index(sid),
                "cells": sheet_cells(sh),
                "rights": {p: lvl for (p, s), lvl in self.visible.rights.items() if s == sid}}

    def add_sheet(self, name):
        if not name:
            return
        if self.visible.find(name) is not None:
            self._alert("nom_existant", name)
            return
        op = self._new_op("add_sheet", name=name, sheet_name=name)
        op["sheet"] = op["id"]
        self._submit(op)
        self._new_action({"t": "add", "sid": op["sheet"], "snap": None, "ops": [op["id"]]})

    def delete_sheet(self, name):
        sid = self.visible.find(name)
        if sid is None:
            return
        sh = self.visible.sheets[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        if len(self.visible.order) <= 1:
            return
        snap = self._snap(sid)
        op = self._new_op("delete_sheet", sheet=sid, sheet_name=sh.name)
        self._submit(op)
        self._new_action({"t": "del", "snap": snap, "ops": [op["id"]]})

    def rename_sheet(self, old, new):
        sid = self.visible.find(old)
        if sid is None:
            return
        sh = self.visible.sheets[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        if not new or new == sh.name:
            return
        other = self.visible.find(new)
        if other is not None and other != sid:
            self._alert("nom_existant", new)
            return
        op = self._new_op("rename", sheet=sid, name=new, sheet_name=sh.name)
        self._submit(op)
        self._new_action({"t": "rename", "sid": sid, "old": sh.name, "new": new, "ops": [op["id"]]})

    # ---------------------------------------------------------------- droits
    def right(self, person, sheet):
        sid = self.visible.find(sheet)
        if sid is None:
            return None
        return self.visible.rights.get((person, sid))

    def set_right(self, person, sheet, level):
        sid = self.visible.find(sheet)
        owner = self.base.wb.owner
        if sid is None or not self._online() or owner != self.name:
            return
        if level not in (W, R) or person == owner:
            return
        if self.visible.rights.get((person, sid)) == level:
            return
        op = self._new_op("right", sheet=sid, person=person, level=level)
        self.net.send(self.name, "server", {"type": "op", "op": op})

    # ---------------------------------------------------------------- connexion, présence
    def connection_status(self):
        return "en ligne" if self._online() else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        at = (self.visible.sheets[sid].name, ref)
        self._selection = at
        if self._online():
            self.net.send(self.name, "server", {"type": "select", "sheet": at[0], "ref": at[1]})

    def presence(self):
        if not self._online():
            return {}
        return {k: v for k, v in self._presence.items() if k != self.name}

    def set_timezone(self, tz):
        self.tz = tz
        self._zone = ZoneInfo(tz)

    def reopen(self):
        blob = pickle.dumps({"base": self.base, "ops": [e.op for e in self.pending],
                             "opn": self._opn, "active": self.active})
        for m in [m for m in self.net.queue if m.src == self.name]:
            self.net.cancel(m)
        return Client(self.net, self.clock, self.name, tz=self.tz, _blob=blob)

    # ---------------------------------------------------------------- annuler / rétablir
    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return
        act = self._undo.pop()
        if self._undo_act(act):
            self._redo.append(act)

    def redo(self):
        if not self._redo:
            return
        act = self._redo.pop()
        if self._redo_act(act):
            self._undo.append(act)

    def _retract(self, act):
        ids = act["ops"]
        if not ids:
            return False
        es = [e for e in self.pending if e.op["id"] in ids]
        if len(es) != len(ids) or any(e.msg is not None and e.msg.delivered for e in es):
            return False
        for e in es:
            if e.msg is not None:
                self.net.cancel(e.msg)
            self.pending.remove(e)
        act["ops"] = []
        self._rebuild()
        return True

    def _impossible(self, sid, ref=None):
        sh = self.visible.sheets.get(sid)
        self._alert("annulation_impossible", sh.name if sh else None, ref)
        return False

    def _denied(self, sid, ref=None):
        self._alert("droit_insuffisant", self.visible.sheets[sid].name, ref)
        return False

    def _cur(self, sid, ref):
        sh = self.visible.sheets.get(sid)
        return None if sh is None else sh.cells.get(ref, EMPTY).cell

    def _undo_act(self, act):
        t = act["t"]
        wb = self.visible
        if t == "cells":
            for sid, ref, _before, after in act["changes"]:
                if sid not in wb.sheets or self._cur(sid, ref) != after:
                    return self._impossible(sid, ref)
            if self._retract(act):
                return True
            sid = act["changes"][0][0]
            if not self._writable(sid):
                return self._denied(sid, act["changes"][0][1])
            res = self._edit(sid, [(ref, before) for _s, ref, before, _a in act["changes"]])
            act["ops"] = [res[0]["id"]] if res else []
            return res is not None
        if t == "add":
            sid = act["sid"]
            if sid not in wb.sheets:
                return self._impossible(sid)
            act["snap"] = self._snap(sid)
            if self._retract(act):
                return True
            if not self._writable(sid):
                return self._denied(sid)
            if len(wb.order) <= 1:
                return self._impossible(sid)
            op = self._new_op("delete_sheet", sheet=sid, sheet_name=wb.sheets[sid].name)
            self._submit(op)
            act["ops"] = [op["id"]]
            return True
        if t == "del":
            snap = act["snap"]
            if snap["id"] in wb.sheets:
                return self._impossible(snap["id"])
            if self._retract(act):
                return True
            return self._undelete(act, snap)
        if t == "rename":
            sid = act["sid"]
            if sid not in wb.sheets or wb.sheets[sid].name != act["new"]:
                return self._impossible(sid)
            if self._retract(act):
                return True
            return self._rename(act, sid, act["old"])
        if t == "replace":
            sid = act["sid"]
            if sid not in wb.sheets or self._state_of(sid) != act["after"]:
                return self._impossible(sid)
            if self._retract(act):
                return True
            return self._replace(act, sid, act["before"], "modification")
        return False

    def _redo_act(self, act):
        t = act["t"]
        wb = self.visible
        if t == "cells":
            sid = act["changes"][0][0]
            if sid not in wb.sheets:
                return self._impossible(sid)
            if not self._writable(sid):
                return self._denied(sid, act["changes"][0][1])
            res = self._edit(sid, [(ref, after) for _s, ref, _b, after in act["changes"]])
            act["ops"] = [res[0]["id"]] if res else []
            return res is not None
        if t == "add":
            snap = act["snap"]
            if snap is None:
                return False
            return self._undelete(act, snap)
        if t == "del":
            sid = act["snap"]["id"]
            if sid not in wb.sheets:
                return self._impossible(sid)
            if not self._writable(sid):
                return self._denied(sid)
            if len(wb.order) <= 1:
                return self._impossible(sid)
            act["snap"] = self._snap(sid)
            op = self._new_op("delete_sheet", sheet=sid, sheet_name=wb.sheets[sid].name)
            self._submit(op)
            act["ops"] = [op["id"]]
            return True
        if t == "rename":
            sid = act["sid"]
            if sid not in wb.sheets:
                return self._impossible(sid)
            return self._rename(act, sid, act["new"])
        if t == "replace":
            sid = act["sid"]
            if sid not in wb.sheets:
                return self._impossible(sid)
            return self._replace(act, sid, act["after"], "modification")
        return False

    def _undelete(self, act, snap):
        wb = self.visible
        if snap["id"] in wb.sheets:
            return self._impossible(snap["id"])
        if wb.find(snap["name"]) is not None:
            self._alert("nom_existant", snap["name"])
            return False
        if snap["rights"].get(self.name) != W and wb.owner != self.name:
            self._alert("droit_insuffisant", snap["name"])
            return False
        op = self._new_op("undelete", snap=snap, sheet=snap["id"], sheet_name=snap["name"])
        self._submit(op)
        act["ops"] = [op["id"]]
        return True

    def _rename(self, act, sid, new):
        wb = self.visible
        sh = wb.sheets[sid]
        if not self._writable(sid):
            return self._denied(sid)
        other = wb.find(new)
        if other is not None and other != sid:
            self._alert("nom_existant", new)
            return False
        op = self._new_op("rename", sheet=sid, name=new, sheet_name=sh.name)
        self._submit(op)
        act["ops"] = [op["id"]]
        return True

    def _state_of(self, sid):
        sh = self.visible.sheets[sid]
        return (sh.name, sheet_cells(sh))

    def _replace(self, act, sid, target, label):
        wb = self.visible
        name, cells = target
        if not self._writable(sid):
            return self._denied(sid)
        other = wb.find(name)
        if other is not None and other != sid:
            self._alert("nom_existant", name)
            return False
        op = self._new_op("replace", sheet=sid, name=name, cells=dict(cells), label=label,
                          sheet_name=wb.sheets[sid].name)
        self._submit(op)
        act["ops"] = [op["id"]]
        return True

    # ---------------------------------------------------------------- historique
    def history(self, sheet=None):
        sid = self._sid(sheet)
        vs = self.base.hist.get(sid, [])
        vs = sorted(vs, key=lambda v: (v.ts, v.seq), reverse=True)
        return [VersionView(v, self._zone) for v in vs]

    def _find_version(self, vid):
        for sid, vs in self.base.hist.items():
            for v in vs:
                if v.id == vid:
                    return sid, v
        return None, None

    def open_version(self, version_id):
        sid, v = self._find_version(version_id)
        if v is not None and sid in self.visible.sheets:
            self._view = (sid, v)

    def close_version(self):
        self._view = None

    def restore_version(self, version_id):
        sid, v = self._find_version(version_id)
        if v is None or sid not in self.visible.sheets:
            return
        self._view = None
        wb = self.visible
        sh = wb.sheets[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        before = self._state_of(sid)
        after = (v.name, dict(v.cells))
        if before == after and all(r.conflict is None for r in sh.cells.values()):
            return
        other = wb.find(v.name)
        if other is not None and other != sid:
            self._alert("nom_existant", v.name)
            return
        act = {"t": "replace", "sid": sid, "before": before, "after": after, "ops": []}
        if self._replace(act, sid, after, "restauration"):
            self._new_action(act)

    # ---------------------------------------------------------------- export
    def _fmt_field(self, r):
        if isinstance(r, Err):
            return r.code
        if isinstance(r, DT):
            return self._dt_local(r).isoformat()
        if isinstance(r, date):
            return r.isoformat()
        if isinstance(r, float) and r.is_integer():
            return str(int(r))
        return str(r)

    def export_csv(self):
        sid = self._aid()
        sh = self.visible.sheets[sid]
        fields = {}
        maxcol = 0
        for ref, cell in self._cells_of(sid).items():
            col, row = split_ref(ref)
            _, r = self._lookup(ref, sh.name)
            fields[(row, col)] = self._fmt_field(r) if r is not None else cell.raw
            maxcol = max(maxcol, col)
        out = io.StringIO()
        w = csv.writer(out)
        for row in sorted({r for r, _c in fields}):
            w.writerow([fields.get((row, c), "") for c in range(1, maxcol + 1)])
        return out.getvalue().encode("utf-8")
