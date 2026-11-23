"""Classeur collaboratif hors ligne : formules, copies locales, réseau simulé, fuseaux."""
import copy
import csv
import io
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

W = "écriture"
R = "lecture"
UTC = timezone.utc
FMT = "%Y-%m-%d %H:%M"


# ====================================================================== valeurs

class Err:
    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return self.code


E_TYPE = Err("#TYPE!")
E_DIV = Err("#DIV/0!")
E_SYN = Err("#SYNTAXE!")
E_CIRC = Err("#CIRC!")
E_REF = Err("#REF!")


class Fail(Exception):
    def __init__(self, err):
        Exception.__init__(self)
        self.err = err


class DT:
    def __init__(self, instant, wall=None, tz=None):
        self.instant = instant
        self.wall = wall
        self.tz = tz


@dataclass(frozen=True)
class Cell:
    text: str
    tz: object = None
    literal: bool = False


NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")
DT_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})?")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
REF_RE = re.compile(r"([A-Za-z]{1,3})([1-9][0-9]*)")


def make_cell(text, tz, literal=False):
    m = DT_RE.fullmatch(text)
    naive = bool(m) and not m.group(7)
    return Cell(text, tz if naive else None, bool(literal and text.startswith("=")))


def is_formula(cell):
    return cell.text.startswith("=") and not cell.literal


@lru_cache(maxsize=65536)
def classify(cell):
    t = cell.text
    if NUM_RE.fullmatch(t):
        return float(t) if "." in t else int(t)
    m = DT_RE.fullmatch(t)
    if m:
        try:
            y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
            s = int(m.group(6) or 0)
            off = m.group(7)
            if off:
                if off == "Z":
                    tzi = UTC
                else:
                    sign = 1 if off[0] == "+" else -1
                    tzi = timezone(sign * timedelta(hours=int(off[1:3]), minutes=int(off[4:6])))
                return DT(datetime(y, mo, d, h, mi, s, tzinfo=tzi).astimezone(UTC))
            tzname = cell.tz or "UTC"
            local = datetime(y, mo, d, h, mi, s, tzinfo=ZoneInfo(tzname))
            return DT(local.astimezone(UTC), "%04d-%02d-%02d %02d:%02d" % (y, mo, d, h, mi), tzname)
        except Exception:
            return t
    m = DATE_RE.fullmatch(t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return t
    return t


def fmt_dt(dt, tzname):
    if dt.wall is not None and dt.tz == tzname:
        return dt.wall
    return dt.instant.astimezone(ZoneInfo(tzname)).strftime(FMT)


def norm(v):
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    return v


def col_num(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def col_name(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def norm_ref(ref):
    m = REF_RE.fullmatch(ref) if isinstance(ref, str) else None
    return None if not m else m.group(1).upper() + m.group(2)


# ====================================================================== formules

class FormulaSyntax(Exception):
    pass


_WORD = re.compile(r"[^\W\d]\w*")
_NUMTOK = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_QSHEET = re.compile(r"'([^']+)'!")
_REFW = re.compile(r"([A-Za-z]{1,3})([0-9]+)")


def tokenize(s, start=0):
    toks = []
    i = start
    n = len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit() or c == ".":
            m = _NUMTOK.match(s, i)
            if not m:
                raise FormulaSyntax()
            txt = m.group()
            toks.append(("num", float(txt) if "." in txt else int(txt), i, m.end()))
            i = m.end()
            continue
        if c == "'":
            m = _QSHEET.match(s, i)
            if not m:
                raise FormulaSyntax()
            toks.append(("sheet", m.group(1), i, m.end()))
            i = m.end()
            continue
        if c.isalpha() or c == "_":
            m = _WORD.match(s, i)
            w = m.group()
            j = m.end()
            if j < n and s[j] == "!":
                toks.append(("sheet", w, i, j + 1))
                i = j + 1
                continue
            k = j
            while k < n and s[k].isspace():
                k += 1
            if k < n and s[k] == "(":
                toks.append(("func", w.upper(), i, j))
                i = j
                continue
            rm = _REFW.fullmatch(w)
            if rm and int(rm.group(2)) > 0:
                toks.append(("ref", (rm.group(1).upper(), int(rm.group(2))), i, j))
                i = j
                continue
            raise FormulaSyntax()
        if c in "+-*/(),;:":
            toks.append((c, c, i, i + 1))
            i += 1
            continue
        raise FormulaSyntax()
    return toks


class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i][0] if self.i < len(self.t) else None

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.i != len(self.t):
            raise FormulaSyntax()
        return node

    def expr(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.next()[0]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in ("*", "/"):
            op = self.next()[0]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek() in ("-", "+"):
            op = self.next()[0]
            x = self.unary()
            return ("neg", x) if op == "-" else x
        return self.primary()

    def reference(self):
        sheet = None
        if self.peek() == "sheet":
            sheet = self.next()[1]
        if self.peek() != "ref":
            raise FormulaSyntax()
        c, r = self.next()[1]
        if self.peek() == ":":
            self.next()
            if self.peek() == "sheet":
                other = self.next()[1]
                if sheet is None or other.casefold() != sheet.casefold():
                    raise FormulaSyntax()
            if self.peek() != "ref":
                raise FormulaSyntax()
            c2, r2 = self.next()[1]
            a, b = col_num(c), col_num(c2)
            return ("range", sheet, min(a, b), min(r, r2), max(a, b), max(r, r2))
        return ("ref", sheet, c + str(r))

    def primary(self):
        k = self.peek()
        if k is None:
            raise FormulaSyntax()
        if k == "num":
            return ("num", self.next()[1])
        if k == "(":
            self.next()
            node = self.expr()
            if self.peek() != ")":
                raise FormulaSyntax()
            self.next()
            return node
        if k in ("sheet", "ref"):
            node = self.reference()
            if node[0] == "range":
                raise FormulaSyntax()
            return node
        if k == "func":
            name = self.next()[1]
            if name not in ("SOMME", "MAINTENANT"):
                raise FormulaSyntax()
            if self.peek() != "(":
                raise FormulaSyntax()
            self.next()
            args = []
            if self.peek() != ")":
                while True:
                    args.append(self.arg())
                    if self.peek() in (",", ";"):
                        self.next()
                        continue
                    break
            if self.peek() != ")":
                raise FormulaSyntax()
            self.next()
            if name == "MAINTENANT" and args:
                raise FormulaSyntax()
            if name == "SOMME" and not args:
                raise FormulaSyntax()
            return ("func", name, args)
        raise FormulaSyntax()

    def arg(self):
        if self.peek() in ("sheet", "ref"):
            save = self.i
            node = self.reference()
            if node[0] == "range" and self.peek() in (",", ";", ")"):
                return node
            self.i = save
        return self.expr()


def _collect(node, refs, flags):
    k = node[0]
    if k == "ref":
        refs.append((node[1], node[2]))
    elif k == "range":
        _, sheet, c1, r1, c2, r2 = node
        for c in range(c1, c2 + 1):
            for r in range(r1, r2 + 1):
                refs.append((sheet, col_name(c) + str(r)))
    elif k == "neg":
        _collect(node[1], refs, flags)
    elif k == "bin":
        _collect(node[2], refs, flags)
        _collect(node[3], refs, flags)
    elif k == "func":
        if node[1] == "MAINTENANT":
            flags.append(True)
        for a in node[2]:
            _collect(a, refs, flags)


@lru_cache(maxsize=65536)
def parse_formula(text):
    try:
        ast = Parser(tokenize(text, 1)).parse()
    except FormulaSyntax:
        return None
    refs = []
    flags = []
    _collect(ast, refs, flags)
    return ast, tuple(refs), bool(flags)


def _fmt_sheet(name):
    if re.fullmatch(r"[^\W\d]\w*", name):
        return name + "!"
    return "'" + name + "'!"


def rewrite_sheet_refs(text, old, new):
    try:
        toks = tokenize(text, 1)
    except FormulaSyntax:
        return text
    res = text[:1]
    pos = 1
    key = old.casefold()
    for kind, val, a, b in toks:
        if kind == "sheet" and val.casefold() == key:
            res += text[pos:a] + _fmt_sheet(new)
            pos = b
    return res + text[pos:]


class Calc:
    """Valeurs calculées d'un classeur : graphe de dépendances et recalcul incrémental."""

    def __init__(self, doc, clock):
        self.doc = doc
        self.clock = clock
        self.deps = {}
        self.rdeps = {}
        self.results = {}
        self.formulas = set()
        self.volatile = set()
        self.stamp = None
        self._now = None

    def full(self):
        self.deps.clear()
        self.rdeps.clear()
        self.results.clear()
        self.formulas.clear()
        self.volatile.clear()
        now = self.clock.now()
        for sid in self.doc.order:
            for ref in list(self.doc.sheets[sid].cells):
                self._register((sid, ref))
        self._now = now
        self.stamp = now
        self._evaluate(set(self.formulas))

    def _register(self, key):
        for d in self.deps.pop(key, ()):
            s = self.rdeps.get(d)
            if s:
                s.discard(key)
        self.formulas.discard(key)
        self.volatile.discard(key)
        self.results.pop(key, None)
        sid, ref = key
        sh = self.doc.sheets.get(sid)
        cell = sh.cells.get(ref) if sh else None
        if cell is None or not is_formula(cell):
            return
        self.formulas.add(key)
        info = parse_formula(cell.text)
        if info is None:
            self.deps[key] = ()
            return
        _, refs, vol = info
        if vol:
            self.volatile.add(key)
        ds = set()
        for sname, r in refs:
            tsid = sid if sname is None else self.doc.sid_by_name(sname)
            if tsid is not None:
                ds.add((tsid, r))
        self.deps[key] = ds
        for d in ds:
            self.rdeps.setdefault(d, set()).add(key)

    def update(self, changed, reparse=True):
        self._now = self.clock.now()
        if reparse:
            for key in changed:
                self._register(key)
        affected = set()
        stack = list(changed)
        while stack:
            k = stack.pop()
            if k in affected:
                continue
            affected.add(k)
            stack.extend(self.rdeps.get(k, ()))
        self._evaluate(affected & self.formulas)

    def refresh(self):
        if self.volatile:
            now = self.clock.now()
            if now != self.stamp:
                self.stamp = now
                self.update(set(self.volatile), reparse=False)

    def _evaluate(self, nodes):
        index = {}
        low = {}
        onstack = set()
        stack = []
        counter = 0
        for root in nodes:
            if root in index:
                continue
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            onstack.add(root)
            work = [(root, iter(self.deps.get(root, ())))]
            while work:
                node, it = work[-1]
                advanced = False
                for w in it:
                    if w not in nodes:
                        continue
                    if w not in index:
                        index[w] = low[w] = counter
                        counter += 1
                        stack.append(w)
                        onstack.add(w)
                        work.append((w, iter(self.deps.get(w, ()))))
                        advanced = True
                        break
                    elif w in onstack:
                        if index[w] < low[node]:
                            low[node] = index[w]
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    if low[node] < low[parent]:
                        low[parent] = low[node]
                if low[node] == index[node]:
                    comp = []
                    while True:
                        w = stack.pop()
                        onstack.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    self._eval_comp(comp)

    def _eval_comp(self, comp):
        if len(comp) > 1 or comp[0] in self.deps.get(comp[0], ()):
            for k in comp:
                self.results[k] = E_CIRC
            return
        k = comp[0]
        sid, ref = k
        cell = self.doc.sheets[sid].cells[ref]
        info = parse_formula(cell.text)
        if info is None:
            self.results[k] = E_SYN
            return
        try:
            v = self._eval(info[0], sid)
        except Fail as f:
            v = f.err
        if v is None:
            v = 0
        self.results[k] = norm(v)

    def _read(self, sname, ref, cur):
        sid = cur if sname is None else self.doc.sid_by_name(sname)
        if sid is None:
            raise Fail(E_REF)
        key = (sid, ref)
        if key in self.formulas:
            return self.results.get(key)
        cell = self.doc.sheets[sid].cells.get(ref)
        return None if cell is None else classify(cell)

    @staticmethod
    def _chk(v):
        if isinstance(v, Err):
            raise Fail(v)

    def _num(self, v):
        self._chk(v)
        if v is None:
            return 0
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        raise Fail(E_TYPE)

    def _eval(self, node, cur):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            return self._read(node[1], node[2], cur)
        if k == "neg":
            return -self._num(self._eval(node[1], cur))
        if k == "bin":
            a = self._eval(node[2], cur)
            self._chk(a)
            b = self._eval(node[3], cur)
            self._chk(b)
            return self._arith(node[1], a, b)
        if k == "func":
            name, args = node[1], node[2]
            if name == "MAINTENANT":
                return DT(self._now)
            total = 0
            for a in args:
                if a[0] == "range":
                    _, sname, c1, r1, c2, r2 = a
                    for c in range(c1, c2 + 1):
                        for r in range(r1, r2 + 1):
                            v = self._read(sname, col_name(c) + str(r), cur)
                            self._chk(v)
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                total += v
                else:
                    total += self._num(self._eval(a, cur))
            return total
        raise Fail(E_SYN)

    def _arith(self, op, a, b):
        if op == "-":
            if isinstance(a, DT) and isinstance(b, DT):
                return (a.instant - b.instant).total_seconds() / 86400
            if type(a) is date and type(b) is date:
                return (a - b).days
        if op in "+-" and isinstance(a, DT) and isinstance(b, (int, float)):
            return DT(a.instant + timedelta(days=b if op == "+" else -b))
        x = self._num(a)
        y = self._num(b)
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if y == 0:
            raise Fail(E_DIV)
        return x / y


# ====================================================================== classeur

class Sheet:
    def __init__(self, name, cells):
        self.name = name
        self.cells = cells


class Ver:
    def __init__(self, id, sid, author, ts, kind, cells, name):
        self.id = id
        self.sid = sid
        self.author = author
        self.ts = ts
        self.kind = kind
        self.cells = cells
        self.name = name


class Doc:
    def __init__(self, owner=None):
        self.sheets = {}
        self.order = []
        self.rights = {}
        self.conflicts = {}
        self.changes = {}
        self.versions = {}
        self.owner = owner
        self.calc = None
        self._byname = None

    @staticmethod
    def initial(owner):
        d = Doc(owner)
        d.sheets["s0"] = Sheet("Feuille1", {})
        d.order = ["s0"]
        return d

    def clone(self):
        d = Doc(self.owner)
        d.sheets = {k: Sheet(v.name, dict(v.cells)) for k, v in self.sheets.items()}
        d.order = list(self.order)
        d.rights = {k: dict(v) for k, v in self.rights.items()}
        d.conflicts = dict(self.conflicts)
        return d

    def sid_by_name(self, name):
        if self._byname is None:
            self._byname = {sh.name.casefold(): sid for sid, sh in self.sheets.items()}
        return self._byname.get(name.casefold())

    def name_taken(self, name, except_sid=None):
        sid = self.sid_by_name(name)
        return sid is not None and sid != except_sid

    def right(self, person, sid):
        if sid not in self.sheets:
            return None
        if person == self.owner:
            return W
        return self.rights.get(sid, {}).get(person)

    def last_seq(self, sid, ref):
        lst = self.changes.get((sid, ref))
        return lst[-1][0] if lst else 0

    def _version(self, e, sid):
        sh = self.sheets[sid]
        self.versions.setdefault(sid, []).append(
            Ver(e["seq"], sid, e["author"], e["ts"], e.get("kind", "modification"), dict(sh.cells), sh.name))

    def _rename(self, sid, new):
        sh = self.sheets[sid]
        old = sh.name
        if old == new or self.name_taken(new, sid):
            return
        sh.name = new
        self._byname = None
        for s in self.sheets.values():
            for ref, cell in list(s.cells.items()):
                if is_formula(cell):
                    t = rewrite_sheet_refs(cell.text, old, new)
                    if t != cell.text:
                        s.cells[ref] = replace(cell, text=t)

    def apply(self, e):
        """Applique une entrée ; rend l'ensemble des clés modifiées, ou None si la structure change."""
        t = e["type"]
        rec = "seq" in e
        if t == "cells":
            sid = e["sid"]
            sh = self.sheets.get(sid)
            if sh is None:
                return set()
            changed = set()
            for ref, c in e["changes"].items():
                if c is None:
                    sh.cells.pop(ref, None)
                else:
                    sh.cells[ref] = c
                self.conflicts.pop((sid, ref), None)
                changed.add((sid, ref))
                if rec:
                    self.changes.setdefault((sid, ref), []).append((e["seq"], e["author"]))
            for ref in e.get("clear", ()):
                self.conflicts.pop((sid, ref), None)
            for ref, v in e.get("conflicts", {}).items():
                self.conflicts[(sid, ref)] = v
            if rec and e["changes"]:
                self._version(e, sid)
            return changed
        if t == "resolve":
            sid, ref = e["sid"], e["ref"]
            sh = self.sheets.get(sid)
            cf = self.conflicts.pop((sid, ref), None)
            if sh is None or cf is None or not e["take"]:
                return set()
            if cf[0] is None:
                sh.cells.pop(ref, None)
            else:
                sh.cells[ref] = cf[0]
            return {(sid, ref)}
        if t == "add":
            sid = e["sid"]
            if sid in self.sheets:
                return set()
            self.sheets[sid] = Sheet(e["name"], {})
            self.order.append(sid)
            self.rights[sid] = {e["creator"]: W}
            self._byname = None
            return None
        if t == "delete":
            sid = e["sid"]
            if sid in self.sheets:
                del self.sheets[sid]
                self.order.remove(sid)
                self.rights.pop(sid, None)
                for k in [k for k in self.conflicts if k[0] == sid]:
                    del self.conflicts[k]
                self._byname = None
            return None
        if t == "rename":
            if e["sid"] in self.sheets:
                self._rename(e["sid"], e["name"])
            return None
        if t == "restore_sheet":
            sid = e["sid"]
            if sid not in self.sheets:
                self.sheets[sid] = Sheet(e["name"], dict(e["cells"]))
                self.rights[sid] = dict(e["rights"])
                self.order.insert(min(e["index"], len(self.order)), sid)
                self._byname = None
            return None
        if t == "state":
            sid = e["sid"]
            sh = self.sheets.get(sid)
            if sh is None:
                return set()
            old = sh.cells
            new = dict(e["cells"])
            changed = set()
            for r in set(old) | set(new):
                if old.get(r) != new.get(r):
                    changed.add((sid, r))
                    if rec:
                        self.changes.setdefault((sid, r), []).append((e["seq"], e["author"]))
            sh.cells = new
            for k in [k for k in self.conflicts if k[0] == sid]:
                del self.conflicts[k]
            renamed = e.get("name") is not None and e["name"] != sh.name
            if renamed:
                self._rename(sid, e["name"])
            if rec:
                self._version(e, sid)
            return None if renamed else changed
        if t == "right":
            if e["sid"] in self.sheets:
                self.rights.setdefault(e["sid"], {})[e["person"]] = e["level"]
            return set()
        return set()


# ====================================================================== CSV

class CsvError(Exception):
    def __init__(self, line):
        Exception.__init__(self)
        self.line = line


def parse_csv(text):
    rows = []
    row = []
    buf = []
    i = 0
    n = len(text)
    line = 1
    state = 0  # 0 début de champ, 1 champ brut, 2 entre guillemets, 3 après guillemet fermant
    qline = 0
    have = False
    while i < n:
        ch = text[i]
        if state == 2:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                state = 3
                i += 1
                continue
            if ch == "\n":
                line += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ",":
            row.append("".join(buf))
            buf = []
            state = 0
            have = True
            i += 1
            continue
        if ch == "\r" or ch == "\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if have or row or buf:
                row.append("".join(buf))
            rows.append(row)
            row = []
            buf = []
            state = 0
            have = False
            line += 1
            i += 1
            continue
        if ch == '"' and state == 0:
            state = 2
            qline = line
            have = True
            i += 1
            continue
        buf.append(ch)
        if state == 0:
            state = 1
        have = True
        i += 1
    if state == 2:
        raise CsvError(qline)
    if have or row or buf:
        row.append("".join(buf))
        rows.append(row)
    return rows


# ====================================================================== temps et réseau

class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Msg:
    def __init__(self, src, dst, payload):
        self.src = src
        self.dst = dst
        self.payload = payload


class Network:
    def __init__(self):
        self.endpoints = {}
        self.queue = []
        self.down = set()
        self.storage = {}

    def register(self, name, ep):
        self.endpoints[name] = ep

    def is_connected(self, name):
        return name not in self.down

    def send(self, src, dst, payload):
        if src in self.down or dst in self.down:
            return None
        m = Msg(src, dst, copy.deepcopy(payload))
        self.queue.append(m)
        return m

    def cancel(self, handle):
        for i, m in enumerate(self.queue):
            if m is handle:
                del self.queue[i]
                return True
        return False

    def cancel_from(self, name):
        self.queue = [m for m in self.queue if m.src != name]

    def _dispatch(self, m):
        if m.src in self.down or m.dst in self.down:
            return
        ep = self.endpoints.get(m.dst)
        if ep is not None:
            ep.receive(m.src, m.payload)

    def deliver_all(self):
        while self.queue:
            self._dispatch(self.queue.pop(0))

    def deliver_from(self, name):
        mine = [m for m in self.queue if m.src == name]
        self.queue = [m for m in self.queue if m.src != name]
        for m in mine:
            self._dispatch(m)

    def disconnect(self, name):
        self.down.add(name)
        self.queue = [m for m in self.queue if m.src != name and m.dst != name]
        ep = self.endpoints.get(name)
        if ep is not None and hasattr(ep, "on_disconnect"):
            ep.on_disconnect()
        srv = self.endpoints.get("server")
        if srv is not None and name != "server":
            srv.peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        ep = self.endpoints.get(name)
        if ep is not None and hasattr(ep, "on_reconnect"):
            ep.on_reconnect()


# ====================================================================== serveur

class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.doc = Doc.initial(owner)
        self.log = []
        self.seq = 0
        self.clients = set()
        self.presence = {}
        self.outcomes = {}
        net.register("server", self)

    def _send(self, dst, payload):
        self.net.send("server", dst, payload)

    def peer_down(self, name):
        if self.presence.pop(name, None) is not None:
            for c in sorted(self.clients):
                if c != name:
                    self._send(c, ("presence", name, None))

    def receive(self, src, msg):
        k = msg[0]
        if k == "hello":
            _, last_seq, reconnect = msg
            self.clients.add(src)
            self._send(src, ("welcome", self.owner))
            for e in self.log[last_seq:]:
                self._send(src, ("entry", e))
            if reconnect:
                self._send(src, ("presence_all", {n: loc for n, loc in self.presence.items() if n != src}))
        elif k == "op":
            self._op(src, msg[1])
        elif k == "right":
            _, sid, person, level = msg
            d = self.doc
            if src != self.owner or sid not in d.sheets or person == self.owner or level not in (W, R):
                return
            if d.rights.get(sid, {}).get(person) == level:
                return
            self._commit(src, {"type": "right", "sid": sid, "person": person, "level": level}, None)
        elif k == "select":
            _, sid, ref = msg
            self.presence[src] = (sid, ref)
            for c in sorted(self.clients):
                if c != src:
                    self._send(c, ("presence", src, (sid, ref)))

    def _commit(self, who, e, origin):
        self.seq += 1
        e["seq"] = self.seq
        e["author"] = who
        e.setdefault("ts", self.clock.now())
        e["origin"] = origin
        self.doc.apply(e)
        self.log.append(e)
        for c in sorted(self.clients):
            self._send(c, ("entry", e))

    def _op(self, who, op):
        key = (who, op["id"])
        if key in self.outcomes:
            out = self.outcomes[key]
            if out[0] != "applied":
                self._send(who, ("ack", op["id"], out))
            return
        res = self._process(who, op)
        self.outcomes[key] = res
        if res[0] != "applied":
            self._send(who, ("ack", op["id"], res))

    def _can_write(self, who, sid):
        return self.doc.right(who, sid) == W

    def _process(self, who, op):
        d = self.doc
        t = op["type"]
        origin = (who, op["id"])
        ts = op["ts"]
        sid = op.get("sid")
        if t == "add":
            if sid in d.sheets:
                return ("noop",)
            if d.name_taken(op["name"]):
                return ("reject", "nom_existant")
            self._commit(who, {"type": "add", "sid": sid, "name": op["name"], "creator": who, "ts": ts}, origin)
            return ("applied",)
        if t == "restore_sheet":
            if sid in d.sheets:
                return ("noop",)
            if who != self.owner and op["rights"].get(who) != W:
                return ("reject", "droit")
            if d.name_taken(op["name"]):
                return ("reject", "annulation")
            self._commit(who, {"type": "restore_sheet", "sid": sid, "name": op["name"], "cells": op["cells"],
                               "rights": op["rights"], "index": op["index"], "ts": ts}, origin)
            return ("applied",)
        if sid not in d.sheets:
            if t == "delete":
                return ("noop",)
            return ("lost",)
        if not self._can_write(who, sid):
            return ("reject", "droit")
        sh = d.sheets[sid]
        if t == "cells":
            changes = {}
            conflicts = {}
            for ref, new in op["changes"].items():
                if sh.cells.get(ref) == new:
                    continue
                base = op["base"].get(ref, 0)
                clash = False
                for s, a in reversed(d.changes.get((sid, ref), ())):
                    if s <= base:
                        break
                    if a != who:
                        clash = True
                        break
                if clash:
                    conflicts[ref] = (new, who)
                else:
                    changes[ref] = new
            if not changes and not conflicts:
                return ("noop",)
            self._commit(who, {"type": "cells", "sid": sid, "changes": changes, "conflicts": conflicts,
                               "kind": op.get("kind", "modification"), "ts": ts}, origin)
            return ("applied",)
        if t == "resolve":
            cf = d.conflicts.get((sid, op["ref"]))
            if cf is None:
                return ("noop",)
            ref = op["ref"]
            if op["take"]:
                e = {"type": "cells", "sid": sid, "changes": {ref: cf[0]}, "kind": "modification", "ts": ts}
            else:
                e = {"type": "cells", "sid": sid, "changes": {}, "clear": [ref], "kind": "modification", "ts": ts}
            self._commit(who, e, origin)
            return ("applied",)
        if t == "delete":
            if len(d.order) <= 1:
                return ("reject", "derniere")
            self._commit(who, {"type": "delete", "sid": sid, "ts": ts}, origin)
            return ("applied",)
        if t == "rename":
            if sh.name == op["name"]:
                return ("noop",)
            if d.name_taken(op["name"], sid):
                return ("reject", "nom_existant")
            self._commit(who, {"type": "rename", "sid": sid, "name": op["name"], "ts": ts}, origin)
            return ("applied",)
        if t == "state":
            name = op.get("name")
            if name is None or d.name_taken(name, sid):
                name = sh.name
            if sh.cells == op["cells"] and name == sh.name:
                return ("noop",)
            self._commit(who, {"type": "state", "sid": sid, "name": name, "cells": op["cells"],
                               "kind": op.get("kind", "modification"), "ts": ts}, origin)
            return ("applied",)
        return ("noop",)


# ====================================================================== client

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line

    def __repr__(self):
        return "Alert(%r, %r, %r, %r)" % (self.kind, self.sheet, self.cell, self.line)


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

    def __repr__(self):
        return "Version(%r, %r, %r, %r)" % (self.id, self.author, self.timestamp, self.kind)


class Action:
    def __init__(self, kind, sid, fwd, inv):
        self.kind = kind
        self.sid = sid
        self.fwd = fwd
        self.inv = inv
        self.live = None


class Client:
    def __init__(self, net, clock, name, tz="UTC", _snapshot=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.owner = None
        self.confirmed = Doc.initial(None)
        self.seq = 0
        self.buffer = {}
        self.pending = []
        self.op_n = 0
        self.sid_n = 0
        self._alerts = []
        self.undo_stack = []
        self.redo_stack = []
        self.active = "s0"
        self.selection = None
        self.presence_map = {}
        self.version_id = None
        self._vdoc = None
        if _snapshot is not None:
            for k, v in _snapshot.items():
                setattr(self, k, copy.deepcopy(v))
        self.view = None
        self._rebuild()
        net.register(name, self)
        if net.is_connected(name):
            self._connect(False)

    # ------------------------------------------------------------ réseau
    def _connect(self, reconnect):
        self.net.send(self.name, "server", ("hello", self.seq, reconnect))
        for rec in self.pending:
            rec["handle"] = self.net.send(self.name, "server", ("op", rec["op"]))
        if self.selection:
            self.net.send(self.name, "server", ("select", self.selection[0], self.selection[1]))

    def on_reconnect(self):
        self._connect(True)

    def on_disconnect(self):
        for rec in self.pending:
            rec["handle"] = None

    def receive(self, src, msg):
        k = msg[0]
        if k == "entry":
            self._on_entry(msg[1])
        elif k == "ack":
            self._on_ack(msg[1], msg[2])
        elif k == "welcome":
            if self.owner != msg[1]:
                self.owner = msg[1]
                self.confirmed.owner = msg[1]
                self._rebuild()
        elif k == "presence":
            if msg[2] is None:
                self.presence_map.pop(msg[1], None)
            else:
                self.presence_map[msg[1]] = msg[2]
        elif k == "presence_all":
            self.presence_map = dict(msg[1])

    def _on_entry(self, e):
        if e["seq"] <= self.seq:
            return
        self.buffer[e["seq"]] = e
        while self.seq + 1 in self.buffer:
            x = self.buffer.pop(self.seq + 1)
            self.confirmed.apply(x)
            self.seq = x["seq"]
            o = x.get("origin")
            if o and o[0] == self.name:
                self._drop_pending(o[1])
        self._rebuild()

    def _drop_pending(self, opid):
        for i, rec in enumerate(self.pending):
            if rec["op"]["id"] == opid:
                del self.pending[i]
                return rec
        return None

    def _on_ack(self, opid, res):
        rec = self._drop_pending(opid)
        if rec is None:
            return
        op = rec["op"]
        sname = rec["sname"]
        st = res[0]
        if st == "lost":
            self._alert("feuille_supprimee", sname)
        elif st == "reject":
            why = res[1]
            if why == "droit":
                if op["type"] == "cells":
                    for ref in op["changes"]:
                        self._alert("modification_rejetee", sname, ref)
                elif op["type"] == "resolve":
                    self._alert("modification_rejetee", sname, op["ref"])
                else:
                    self._alert("modification_rejetee", sname)
            elif why == "nom_existant":
                self._alert("nom_existant", op.get("name"))
            elif why == "annulation":
                self._alert("annulation_impossible", sname)
        self.undo_stack = [a for a in self.undo_stack if a.live != opid]
        self._rebuild()

    # ------------------------------------------------------------ copie locale
    def _guard(self, doc, op):
        t = op["type"]
        sid = op.get("sid")
        if t == "add":
            return sid not in doc.sheets and not doc.name_taken(op["name"])
        if t == "delete":
            return sid in doc.sheets and len(doc.order) > 1
        if t == "rename":
            return sid in doc.sheets and doc.sheets[sid].name != op["name"] and not doc.name_taken(op["name"], sid)
        if t == "restore_sheet":
            return sid not in doc.sheets and not doc.name_taken(op["name"])
        return True

    def _rebuild(self):
        v = self.confirmed.clone()
        for rec in self.pending:
            if self._guard(v, rec["op"]):
                v.apply(rec["op"])
        v.calc = Calc(v, self.clock)
        v.calc.full()
        self.view = v
        self._vdoc = None
        if self.active not in v.sheets:
            self.active = v.order[0]

    def _apply_local(self, op):
        if not self._guard(self.view, op):
            return
        changed = self.view.apply(op)
        if changed is None:
            self.view.calc.full()
        elif changed:
            self.view.calc.update(changed)
        self._vdoc = None
        if self.active not in self.view.sheets:
            self.active = self.view.order[0]

    def _doc(self):
        if self.version_id is None:
            d = self.view
        else:
            if self._vdoc is None:
                v = self._find_version(self.version_id)
                if v is None:
                    self.version_id = None
                    d = self.view
                    d.calc.refresh()
                    return d
                dd = self.view.clone()
                if v.sid in dd.sheets:
                    dd.sheets[v.sid].cells = dict(v.cells)
                dd.calc = Calc(dd, self.clock)
                dd.calc.full()
                self._vdoc = dd
            d = self._vdoc
        d.calc.refresh()
        return d

    def _find_version(self, vid):
        for lst in self.confirmed.versions.values():
            for v in lst:
                if v.id == vid:
                    return v
        return None

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _sid_arg(self, sheet):
        if sheet is None:
            if self.active not in self.view.sheets:
                self.active = self.view.order[0]
            return self.active
        return self.view.sid_by_name(sheet)

    def _may_write(self, sid, cell=None):
        if self.view.right(self.name, sid) == W:
            return True
        self._alert("droit_insuffisant", self.view.sheets[sid].name, cell)
        return False

    # ------------------------------------------------------------ émission d'opérations
    def _issue(self, tpl):
        op = dict(tpl)
        if "changes" in op:
            op["changes"] = dict(op["changes"])
        if "cells" in op:
            op["cells"] = dict(op["cells"])
        self.op_n += 1
        op["id"] = "%s:%d" % (self.name, self.op_n)
        op["ts"] = self.clock.now()
        if op["type"] == "cells":
            op["base"] = {r: self.confirmed.last_seq(op["sid"], r) for r in op["changes"]}
        sid = op.get("sid")
        sname = self.view.sheets[sid].name if sid in self.view.sheets else op.get("name")
        rec = {"op": op, "handle": None, "sname": sname}
        self.pending.append(rec)
        if self.net.is_connected(self.name):
            rec["handle"] = self.net.send(self.name, "server", ("op", op))
        self._apply_local(op)
        return op

    def _act(self, kind, sid, fwd, inv):
        act = Action(kind, sid, fwd, inv)
        op = self._issue(fwd)
        act.live = op["id"]
        self.undo_stack.append(act)
        self.redo_stack.clear()

    def _write(self, sid, changes, kind="modification"):
        sh = self.view.sheets[sid]
        eff = {r: c for r, c in changes.items() if sh.cells.get(r) != c}
        if not eff:
            return
        prev = {r: sh.cells.get(r) for r in eff}
        fwd = {"type": "cells", "sid": sid, "changes": eff, "kind": kind}
        inv = {"type": "cells", "sid": sid, "changes": prev, "kind": "modification"}
        self._act("cells", sid, fwd, inv)

    def _retract(self, opid):
        for i, rec in enumerate(self.pending):
            if rec["op"]["id"] == opid:
                h = rec["handle"]
                if h is not None and not self.net.cancel(h):
                    return False
                del self.pending[i]
                return True
        return False

    # ------------------------------------------------------------ saisie
    def set_cell(self, ref, text, sheet=None):
        sid = self._sid_arg(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None or self.version_id is not None:
            return
        if not self._may_write(sid, ref):
            return
        cell = None if text is None or text == "" else make_cell(str(text), self.tz)
        self._write(sid, {ref: cell})

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def content(self, ref, sheet=None):
        doc = self._doc()
        sid = self._sid_arg(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        cell = doc.sheets[sid].cells.get(ref)
        return None if cell is None else cell.text

    def _raw(self, doc, sid, ref):
        cell = doc.sheets[sid].cells.get(ref)
        if cell is None:
            return None
        if is_formula(cell):
            return doc.calc.results.get((sid, ref))
        return classify(cell)

    def value(self, ref, sheet=None):
        doc = self._doc()
        sid = self._sid_arg(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        v = self._raw(doc, sid, ref)
        if isinstance(v, Err):
            return v.code
        if isinstance(v, DT):
            return fmt_dt(v, self.tz)
        if isinstance(v, date):
            return v.isoformat()
        return v

    def error(self, ref, sheet=None):
        doc = self._doc()
        sid = self._sid_arg(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        v = self._raw(doc, sid, ref)
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        ZoneInfo(tz)
        self.tz = tz

    # ------------------------------------------------------------ feuilles
    def sheets(self):
        return [self.view.sheets[s].name for s in self.view.order]

    def activate(self, name):
        sid = self.view.sid_by_name(name)
        if sid is not None:
            self.active = sid
            self._vdoc = None

    def add_sheet(self, name):
        if not isinstance(name, str) or not name.strip():
            return
        if self.view.name_taken(name):
            self._alert("nom_existant", name)
            return
        self.sid_n += 1
        sid = "%s-%d" % (self.name, self.sid_n)
        fwd = {"type": "add", "sid": sid, "name": name, "creator": self.name}
        inv = {"type": "delete", "sid": sid}
        self._act("add", sid, fwd, inv)

    def delete_sheet(self, name):
        sid = self.view.sid_by_name(name)
        if sid is None:
            return
        if not self._may_write(sid):
            return
        v = self.view
        if len(v.order) <= 1:
            return
        sh = v.sheets[sid]
        inv = {"type": "restore_sheet", "sid": sid, "name": sh.name, "cells": dict(sh.cells),
               "rights": dict(v.rights.get(sid, {})), "index": v.order.index(sid)}
        self._act("delete", sid, {"type": "delete", "sid": sid}, inv)

    def rename_sheet(self, old, new):
        sid = self.view.sid_by_name(old)
        if sid is None:
            return
        if not self._may_write(sid):
            return
        if not isinstance(new, str) or not new:
            return
        sh = self.view.sheets[sid]
        if sh.name == new:
            return
        if self.view.name_taken(new, sid):
            self._alert("nom_existant", new)
            return
        fwd = {"type": "rename", "sid": sid, "name": new}
        inv = {"type": "rename", "sid": sid, "name": sh.name}
        self._act("rename", sid, fwd, inv)

    # ------------------------------------------------------------ droits
    def right(self, person, sheet):
        sid = self.view.sid_by_name(sheet)
        if sid is None:
            return None
        return self.view.right(person, sid)

    def set_right(self, person, sheet, level):
        sid = self.view.sid_by_name(sheet)
        if sid is None or level not in (W, R):
            return
        if self.owner is not None and self.owner != self.name:
            return
        if not self.net.is_connected(self.name):
            return
        self.net.send(self.name, "server", ("right", sid, person, level))

    def alerts(self):
        return list(self._alerts)

    # ------------------------------------------------------------ connexion
    def connection_status(self):
        return "en ligne" if self.net.is_connected(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def select(self, ref, sheet=None):
        sid = self._sid_arg(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        self.selection = (sid, ref)
        if self.net.is_connected(self.name):
            self.net.send(self.name, "server", ("select", sid, ref))

    def presence(self):
        if not self.net.is_connected(self.name):
            return {}
        out = {}
        for n, (sid, ref) in self.presence_map.items():
            if sid in self.view.sheets:
                out[n] = (self.view.sheets[sid].name, ref)
        return out

    # ------------------------------------------------------------ conflits
    def conflict(self, ref, sheet=None):
        sid = self._sid_arg(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        cf = self.view.conflicts.get((sid, ref))
        if cf is None:
            return None
        return Conflict(cf[0].text if cf[0] is not None else None, cf[1])

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sid = self._sid_arg(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None or self.version_id is not None:
            return
        if not self._may_write(sid, ref):
            return
        if (sid, ref) not in self.view.conflicts:
            return
        self._issue({"type": "resolve", "sid": sid, "ref": ref, "take": bool(use_discarded)})

    # ------------------------------------------------------------ annuler / rétablir
    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _sname(self, act):
        if act.sid in self.view.sheets:
            return self.view.sheets[act.sid].name
        return act.fwd.get("name") or act.inv.get("name")

    def _problem(self, act, undo):
        v = self.view
        sid = act.sid
        k = act.kind
        target = act.fwd if undo else act.inv
        if k in ("cells", "state"):
            if sid not in v.sheets:
                return ("impossible", None)
            if v.right(self.name, sid) != W:
                return ("droit", None)
            sh = v.sheets[sid]
            if k == "cells":
                for r, c in target["changes"].items():
                    if sh.cells.get(r) != c:
                        return ("impossible", r)
            elif sh.cells != target["cells"]:
                return ("impossible", None)
            return None
        if k == "add":
            if undo:
                if sid not in v.sheets or len(v.order) <= 1:
                    return ("impossible", None)
                if v.right(self.name, sid) != W:
                    return ("droit", None)
            elif sid in v.sheets or v.name_taken(act.fwd["name"]):
                return ("impossible", None)
            return None
        if k == "delete":
            if undo:
                snap = act.inv
                if sid in v.sheets or v.name_taken(snap["name"]):
                    return ("impossible", None)
                if self.name != v.owner and snap["rights"].get(self.name) != W:
                    return ("droit", None)
            else:
                if sid not in v.sheets or len(v.order) <= 1:
                    return ("impossible", None)
                if v.right(self.name, sid) != W:
                    return ("droit", None)
            return None
        if k == "rename":
            new = act.fwd["name"]
            old = act.inv["name"]
            src, dst = (new, old) if undo else (old, new)
            if sid not in v.sheets or v.sheets[sid].name != src:
                return ("impossible", None)
            if v.name_taken(dst, sid):
                return ("impossible", None)
            if v.right(self.name, sid) != W:
                return ("droit", None)
            return None
        return None

    def _refuse(self, stack, act, problem):
        kind, ref = problem
        if kind == "droit":
            self._alert("droit_insuffisant", self._sname(act), ref)
            return
        stack.pop()
        self._alert("annulation_impossible", self._sname(act), ref)

    def undo(self):
        if not self.undo_stack:
            return
        act = self.undo_stack[-1]
        problem = self._problem(act, True)
        if problem:
            self._refuse(self.undo_stack, act, problem)
            return
        self.undo_stack.pop()
        if act.live is not None and self._retract(act.live):
            self._rebuild()
        else:
            self._issue(act.inv)
        act.live = None
        self.redo_stack.append(act)

    def redo(self):
        if not self.redo_stack:
            return
        act = self.redo_stack[-1]
        problem = self._problem(act, False)
        if problem:
            self._refuse(self.redo_stack, act, problem)
            return
        self.redo_stack.pop()
        op = self._issue(act.fwd)
        act.live = op["id"]
        self.undo_stack.append(act)

    # ------------------------------------------------------------ réouverture
    def reopen(self):
        snap = {
            "tz": self.tz,
            "owner": self.owner,
            "confirmed": self.confirmed,
            "seq": self.seq,
            "pending": [{"op": r["op"], "handle": None, "sname": r["sname"]} for r in self.pending],
            "op_n": self.op_n,
            "sid_n": self.sid_n,
            "active": self.active,
        }
        snap = copy.deepcopy(snap)
        self.net.storage[self.name] = snap
        self.net.cancel_from(self.name)
        return Client(self.net, self.clock, self.name, tz=self.tz, _snapshot=snap)

    # ------------------------------------------------------------ historique
    def history(self, sheet=None):
        sid = self._sid_arg(sheet)
        if sid is None:
            return []
        tz = ZoneInfo(self.tz)
        vs = sorted(self.confirmed.versions.get(sid, []), key=lambda x: (x.ts, x.id), reverse=True)
        return [Version(v.id, v.author, v.ts.astimezone(tz).strftime(FMT), v.kind) for v in vs]

    def open_version(self, version_id):
        if self._find_version(version_id) is None:
            return
        self.version_id = version_id
        self._vdoc = None

    def close_version(self):
        self.version_id = None
        self._vdoc = None

    def restore_version(self, version_id):
        v = self._find_version(version_id)
        if v is None or v.sid not in self.view.sheets:
            return
        sid = v.sid
        if not self._may_write(sid):
            return
        sh = self.view.sheets[sid]
        name = v.name if not self.view.name_taken(v.name, sid) else sh.name
        cells = dict(v.cells)
        if cells == sh.cells and name == sh.name:
            return
        fwd = {"type": "state", "sid": sid, "name": name, "cells": cells, "kind": "restauration"}
        inv = {"type": "state", "sid": sid, "name": sh.name, "cells": dict(sh.cells), "kind": "modification"}
        self._act("state", sid, fwd, inv)

    # ------------------------------------------------------------ CSV
    def export_csv(self):
        doc = self._doc()
        sid = self._sid_arg(None)
        cells = doc.sheets[sid].cells
        if not cells:
            return b""
        pos = {}
        maxcol = 0
        for ref in cells:
            m = REF_RE.fullmatch(ref)
            c, r = col_num(m.group(1)), int(m.group(2))
            pos[(r, c)] = ref
            maxcol = max(maxcol, c)
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        for r in sorted({r for r, _ in pos}):
            line = []
            for c in range(1, maxcol + 1):
                ref = pos.get((r, c))
                line.append("" if ref is None else self._export_value(doc, sid, ref))
            w.writerow(line)
        return out.getvalue().encode("utf-8")

    def _export_value(self, doc, sid, ref):
        v = self._raw(doc, sid, ref)
        if v is None:
            return ""
        if isinstance(v, Err):
            return v.code
        if isinstance(v, DT):
            return v.instant.astimezone(ZoneInfo(self.tz)).isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
        return str(v)

    def import_csv(self, data):
        if self.version_id is not None:
            return
        sid = self._sid_arg(None)
        if not self._may_write(sid):
            return
        text = bytes(data).decode("utf-8-sig", errors="replace")
        try:
            rows = parse_csv(text)
        except CsvError as e:
            self._alert("csv_invalide", self.view.sheets[sid].name, None, e.line)
            return
        changes = {}
        for r, fields in enumerate(rows, 1):
            for c, f in enumerate(fields, 1):
                changes[col_name(c) + str(r)] = None if f == "" else make_cell(f, self.tz, literal=f.startswith("="))
        self._write(sid, changes)
