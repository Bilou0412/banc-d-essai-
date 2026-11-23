"""Classeur collaboratif hors ligne : réseau simulé, serveur autoritaire, copies locales."""
import copy
import csv
import io
import re
from collections import deque
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"


@lru_cache(maxsize=None)
def zi(name):
    return ZoneInfo(name)


# ---------------------------------------------------------------- temps et réseau

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
        self.down = set()
        self.q = deque()

    def register(self, name, node):
        self.nodes[name] = node

    def is_connected(self, name):
        return name not in self.down

    def send(self, src, dst, payload):
        if src in self.down:
            return
        self.q.append((src, dst, payload))

    def disconnect(self, name):
        self.down.add(name)
        self.q = deque(m for m in self.q if m[0] != name and m[1] != name)
        srv = self.nodes.get("server")
        if srv is not None and name != "server":
            srv.on_disconnect(name)

    def reconnect(self, name):
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_reconnect"):
            node.on_reconnect()

    def _deliver(self, m):
        src, dst, payload = m
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, payload)

    def deliver_all(self):
        while self.q:
            self._deliver(self.q.popleft())

    def deliver_from(self, name):
        mine = [m for m in self.q if m[0] == name]
        self.q = deque(m for m in self.q if m[0] != name)
        for m in mine:
            self._deliver(m)

    def retract(self, src, fn):
        items = list(self.q)
        for i, m in enumerate(items):
            if m[0] != src:
                continue
            found, newp = fn(m[2])
            if found:
                if newp is None:
                    del items[i]
                else:
                    items[i] = (m[0], m[1], newp)
                self.q = deque(items)
                return True
        return False


# ---------------------------------------------------------------- références et analyseur

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


_REF = re.compile(r"^([A-Za-z]+)(\d+)$")


def split_ref(ref):
    m = _REF.match(ref)
    return col_num(m.group(1)), int(m.group(2))


def norm_ref(ref):
    c, r = split_ref(ref)
    return col_name(c) + str(r)


class FormulaSyntax(Exception):
    pass


class CellErr(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


_TOK = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<func>[A-Za-z]+)\(|"
    r"(?P<sref>\w+)!(?P<sc>[A-Za-z]+\d+)(?::(?P<sc2>[A-Za-z]+\d+))?|"
    r"(?P<ref>[A-Za-z]+\d+)(?::(?P<rc2>[A-Za-z]+\d+))?|(?P<op>[-+*/(),]))")

FUNCS = {"SOMME", "MAINTENANT"}


def tokenize(s):
    toks = []
    pos = 0
    while True:
        if s[pos:].strip() == "":
            break
        m = _TOK.match(s, pos)
        if not m:
            raise FormulaSyntax()
        pos = m.end()
        if m.group("num") is not None:
            t = m.group("num")
            toks.append(("num", float(t) if "." in t else int(t)))
        elif m.group("func") is not None:
            toks.append(("func", m.group("func").upper()))
        elif m.group("sref") is not None:
            toks.append(("ref", m.group("sref"), m.group("sc"), m.group("sc2")))
        elif m.group("ref") is not None:
            toks.append(("ref", None, m.group("ref"), m.group("rc2")))
        else:
            toks.append(("op", m.group("op")))
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def expr(self):
        n = self.term()
        while True:
            p = self.peek()
            if p is not None and p[0] == "op" and p[1] in "+-":
                self.i += 1
                n = ("bin", p[1], n, self.term())
            else:
                return n

    def term(self):
        n = self.unary()
        while True:
            p = self.peek()
            if p is not None and p[0] == "op" and p[1] in "*/":
                self.i += 1
                n = ("bin", p[1], n, self.unary())
            else:
                return n

    def unary(self):
        p = self.peek()
        if p == ("op", "-"):
            self.i += 1
            return ("neg", self.unary())
        if p == ("op", "+"):
            self.i += 1
            return self.unary()
        return self.prim()

    def prim(self):
        p = self.peek()
        if p is None:
            raise FormulaSyntax()
        self.i += 1
        if p[0] == "num":
            return ("num", p[1])
        if p[0] == "ref":
            c1, r1 = split_ref(p[2])
            if p[3]:
                c2, r2 = split_ref(p[3])
                return ("range", p[1], min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2))
            return ("ref", p[1], col_name(c1) + str(r1))
        if p[0] == "func":
            if p[1] not in FUNCS:
                raise FormulaSyntax()
            args = []
            q = self.peek()
            if q == ("op", ")"):
                self.i += 1
            else:
                while True:
                    args.append(self.expr())
                    q = self.peek()
                    if q == ("op", ","):
                        self.i += 1
                        continue
                    if q == ("op", ")"):
                        self.i += 1
                        break
                    raise FormulaSyntax()
            return ("func", p[1], args)
        if p == ("op", "("):
            n = self.expr()
            if self.peek() != ("op", ")"):
                raise FormulaSyntax()
            self.i += 1
            return n
        raise FormulaSyntax()


_AST = {}


def get_ast(src):
    if src in _AST:
        return _AST[src]
    try:
        p = _Parser(tokenize(src))
        n = p.expr()
        if p.i != len(p.t):
            raise FormulaSyntax()
        res = n
    except FormulaSyntax:
        res = False
    _AST[src] = res
    return res


# ---------------------------------------------------------------- valeurs littérales

_NUM = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$")
_D = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_literal(raw, tz):
    s = raw.strip()
    if _NUM.match(s):
        return float(s) if "." in s else int(s)
    if _D.match(s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass
    if _DT.match(s):
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=zi(tz))
            return dt.astimezone(UTC)
        except ValueError:
            pass
    return raw


def cell_literal(cell):
    if cell[1]:
        return cell[0]
    return parse_literal(cell[0], cell[2])


def ckey(cell):
    return None if cell is None else (cell[0], cell[1])


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _todt(x):
    if isinstance(x, datetime):
        return x
    return datetime(x.year, x.month, x.day, tzinfo=UTC)


def _norm(v):
    if isinstance(v, float):
        try:
            if v == int(v):
                return int(v)
        except (OverflowError, ValueError):
            pass
    return v


# ---------------------------------------------------------------- classeur

class Book:
    def __init__(self, owner=None):
        self.owner = owner
        self.sheets = {}
        self.dead = {}
        self.rights = {}
        self.revs = {}
        self.conflicts = {}
        self.counter = 0
        self.now = None
        self._reset()

    def _reset(self):
        self.vals = {}
        self.deps = {}
        self.rdeps = {}
        self.vol = set()

    def copy(self):
        b = Book(self.owner)
        for src, dst in ((self.sheets, b.sheets), (self.dead, b.dead)):
            for k, v in src.items():
                dst[k] = {"name": v["name"], "order": v["order"], "cells": dict(v["cells"])}
        b.rights = dict(self.rights)
        b.revs = dict(self.revs)
        b.conflicts = dict(self.conflicts)
        b.counter = self.counter
        b.now = self.now
        return b

    # structure
    def live(self):
        return sorted(self.sheets, key=lambda s: self.sheets[s]["order"])

    def sid_by_name(self, name):
        for s, v in self.sheets.items():
            if v["name"] == name:
                return s
        return None

    def name_taken(self, name, exclude=None):
        low = name.lower()
        return any(v["name"].lower() == low for s, v in self.sheets.items() if s != exclude)

    def add_sheet(self, sid, name):
        if sid in self.sheets:
            return False
        if sid in self.dead:
            return self.undelete(sid)
        if self.name_taken(name):
            return False
        self.counter += 1
        self.sheets[sid] = {"name": name, "order": self.counter, "cells": {}}
        return True

    def delete(self, sid):
        if sid not in self.sheets or len(self.sheets) <= 1:
            return False
        self.dead[sid] = self.sheets.pop(sid)
        return True

    def undelete(self, sid):
        if sid not in self.dead or self.name_taken(self.dead[sid]["name"]):
            return False
        self.sheets[sid] = self.dead.pop(sid)
        return True

    def rename(self, sid, new):
        sh = self.sheets.get(sid)
        if sh is None or sh["name"] == new or self.name_taken(new, sid):
            return False
        old = sh["name"]
        sh["name"] = new
        pat = re.compile(r"(?<!\w)" + re.escape(old) + "!")
        for cont in list(self.sheets.values()) + list(self.dead.values()):
            cells = cont["cells"]
            for ref, cell in list(cells.items()):
                if not cell[1] and cell[0].startswith("="):
                    nr = pat.sub(lambda m: new + "!", cell[0])
                    if nr != cell[0]:
                        cells[ref] = (nr, cell[1], cell[2])
        return True

    def cell(self, sid, ref):
        sh = self.sheets.get(sid)
        if sh is None:
            return None
        return sh["cells"].get(ref)

    def put(self, sid, ref, cell):
        sh = self.sheets.get(sid)
        if sh is None:
            return
        if cell is None:
            sh["cells"].pop(ref, None)
        else:
            sh["cells"][ref] = cell

    # calcul
    def _fast(self, cell):
        if cell is None or cell[1] or not cell[0].startswith("="):
            return None
        return get_ast(cell[0][1:])

    def _deps_vol(self, key):
        sid, ref = key
        ast = self._fast(self.cell(sid, ref))
        if not ast:
            return (), False
        out = []
        vol = False
        stack = [ast]
        while stack:
            n = stack.pop()
            t = n[0]
            if t == "ref":
                s = sid if n[1] is None else self.sid_by_name(n[1])
                if s is not None:
                    out.append((s, n[2]))
            elif t == "range":
                s = sid if n[1] is None else self.sid_by_name(n[1])
                if s is not None:
                    for c in range(n[2], n[4] + 1):
                        for r in range(n[3], n[5] + 1):
                            out.append((s, col_name(c) + str(r)))
            elif t == "bin":
                stack.append(n[2])
                stack.append(n[3])
            elif t == "neg":
                stack.append(n[1])
            elif t == "func":
                if n[1] == "MAINTENANT":
                    vol = True
                stack.extend(n[2])
        return tuple(dict.fromkeys(out)), vol

    def _register(self, k):
        d, v = self._deps_vol(k)
        self.deps[k] = d
        for x in d:
            self.rdeps.setdefault(x, set()).add(k)
        if v:
            self.vol.add(k)

    def _unregister(self, k):
        for x in self.deps.pop(k, ()):
            s = self.rdeps.get(x)
            if s:
                s.discard(k)
        self.vol.discard(k)
        self.vals.pop(k, None)

    def recalc_all(self):
        self._reset()
        fkeys = []
        for sid, sh in self.sheets.items():
            for ref, cell in sh["cells"].items():
                if self._fast(cell) is not None:
                    k = (sid, ref)
                    fkeys.append(k)
                    self._register(k)
        self._eval(fkeys)

    def _closure(self, keys):
        seen = set(keys)
        stack = list(keys)
        while stack:
            k = stack.pop()
            for d in self.rdeps.get(k, ()):
                if d not in seen:
                    seen.add(d)
                    stack.append(d)
        return seen

    def recalc_cells(self, keys):
        for k in keys:
            self._unregister(k)
            if self._fast(self.cell(*k)) is not None:
                self._register(k)
        aff = self._closure(keys)
        for k in aff:
            self.vals.pop(k, None)
        self._eval([k for k in aff if k in self.deps])

    def refresh_volatile(self):
        if not self.vol:
            return
        aff = self._closure(list(self.vol))
        for k in aff:
            self.vals.pop(k, None)
        self._eval([k for k in aff if k in self.deps])

    def _eval(self, keys):
        vals = self.vals
        for start in keys:
            if start in vals:
                continue
            stack = [[start, iter(self.deps.get(start, ()))]]
            gray = {start: 0}
            circ = set()
            while stack:
                fr = stack[-1]
                adv = False
                for d in fr[1]:
                    if d in vals:
                        continue
                    if d in gray:
                        for f in stack[gray[d]:]:
                            circ.add(f[0])
                        continue
                    if d not in self.deps:
                        continue
                    gray[d] = len(stack)
                    stack.append([d, iter(self.deps[d])])
                    adv = True
                    break
                if adv:
                    continue
                k = fr[0]
                stack.pop()
                del gray[k]
                vals[k] = ("e", "#CIRC!") if k in circ else self._compute(k)

    def _compute(self, k):
        sid, ref = k
        ast = self._fast(self.cell(sid, ref))
        if ast is False:
            return ("e", "#SYNTAXE!")
        try:
            v = self._ev(ast, sid)
        except CellErr as e:
            return ("e", e.code)
        return ("v", _norm(v))

    def _keyval(self, key):
        cell = self.cell(*key)
        if cell is None:
            return 0
        if self._fast(cell) is not None:
            r = self.vals.get(key)
            if r is None:
                r = ("e", "#CIRC!")
            if r[0] == "e":
                raise CellErr(r[1])
            return r[1]
        return cell_literal(cell)

    def _num(self, v):
        if _isnum(v):
            return v
        raise CellErr("#TYPE!")

    def _arith(self, op, a, b):
        dta = isinstance(a, date)
        dtb = isinstance(b, date)
        if op in "+-" and (dta or dtb):
            if op == "-" and dta and dtb:
                return (_todt(a) - _todt(b)).total_seconds() / 86400
            if isinstance(a, datetime) and _isnum(b):
                d = timedelta(days=b)
                return a + d if op == "+" else a - d
            raise CellErr("#TYPE!")
        a = self._num(a)
        b = self._num(b)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise CellErr("#DIV/0!")
        return a / b

    def _ev(self, n, sid):
        t = n[0]
        if t == "num":
            return n[1]
        if t == "ref":
            s = sid if n[1] is None else self.sid_by_name(n[1])
            if s is None:
                raise CellErr("#REF!")
            return self._keyval((s, n[2]))
        if t == "neg":
            return -self._num(self._ev(n[1], sid))
        if t == "bin":
            a = self._ev(n[2], sid)
            b = self._ev(n[3], sid)
            return self._arith(n[1], a, b)
        if t == "func":
            if n[1] == "MAINTENANT":
                if n[2]:
                    raise CellErr("#SYNTAXE!")
                return self.now() if self.now else datetime.now(UTC)
            tot = 0
            for a in n[2]:
                if a[0] == "range":
                    s = sid if a[1] is None else self.sid_by_name(a[1])
                    if s is None:
                        raise CellErr("#REF!")
                    for c in range(a[2], a[4] + 1):
                        for r in range(a[3], a[5] + 1):
                            key = (s, col_name(c) + str(r))
                            if self.cell(*key) is None:
                                continue
                            v = self._keyval(key)
                            if _isnum(v):
                                tot += v
                else:
                    tot += self._num(self._ev(a, sid))
            return tot
        raise CellErr("#TYPE!")

    def result(self, sid, ref):
        cell = self.cell(sid, ref)
        if cell is None:
            return None
        if self._fast(cell) is not None:
            return self.vals.get((sid, ref)) or ("e", "#CIRC!")
        return ("v", cell_literal(cell))


# ---------------------------------------------------------------- CSV

def parse_csv(text):
    rows = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        row = []
        while True:
            if i < n and text[i] == '"':
                qstart = line
                i += 1
                buf = []
                while True:
                    if i >= n:
                        return None, qstart
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
                field = "".join(buf)
                while i < n and text[i] not in ",\r\n":
                    field += text[i]
                    i += 1
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
        if i < n and text[i] == "\r":
            i += 1
        if i < n and text[i] == "\n":
            i += 1
        line += 1
        rows.append(row)
    return rows, None


# ---------------------------------------------------------------- serveur

class Ver:
    def __init__(self, vid, sid, author, ts, kind, name, delta, replace):
        self.id = vid
        self.sid = sid
        self.author = author
        self.ts = ts
        self.kind = kind
        self.name = name
        self.delta = delta
        self.replace = replace


def snapshot_at(versions, sid, vid):
    cells = {}
    for v in versions:
        if v.sid != sid:
            continue
        if v.replace:
            cells = dict(v.delta)
        else:
            for ref, c in v.delta.items():
                if c is None:
                    cells.pop(ref, None)
                else:
                    cells[ref] = c
        if v.id == vid:
            return v.name, cells
    return None


class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.book = Book(owner)
        self.book.add_sheet("s0", "Feuille1")
        self.versions = []
        self.vid = 0
        self.processed = set()
        self.known = set()
        self.presence = {}
        net.register("server", self)

    def receive(self, src, p):
        t = p["t"]
        acks = {}
        self.known.add(src)
        if t == "hello":
            for op in p["ops"]:
                acks[op["seq"]] = self._process(src, op)
            if p.get("sel"):
                self.presence[src] = tuple(p["sel"])
        elif t == "op":
            op = p["op"]
            acks[op["seq"]] = self._process(src, op)
        elif t == "sel":
            self.presence[src] = tuple(p["sel"])
        self._broadcast(src, acks)

    def on_disconnect(self, name):
        self.presence.pop(name, None)
        self._broadcast(None, {})

    def _broadcast(self, src, acks):
        snap = self.book.copy()
        for c in sorted(self.known):
            if not self.net.is_connected(c):
                continue
            self.net.send("server", c, {
                "t": "state", "book": snap, "versions": list(self.versions),
                "presence": dict(self.presence), "acks": dict(acks) if c == src else {}})

    def _ver(self, vid):
        for v in self.versions:
            if v.id == vid:
                return v
        return None

    def _add_version(self, sid, author, ts, kind, delta, replace):
        self.vid += 1
        self.versions.append(Ver(self.vid, sid, author, ts, kind,
                                 self.book.sheets[sid]["name"], delta, replace))

    def _bump(self, sid, ref, c):
        rev = self.book.revs.get((sid, ref), (0, None))[0]
        self.book.revs[(sid, ref)] = (rev + 1, c)
        self.book.conflicts.pop((sid, ref), None)

    def _replace(self, sid, c, ts, cells, name, kind):
        b = self.book
        old = b.sheets[sid]["cells"]
        for ref in set(old) | set(cells):
            if ckey(old.get(ref)) != ckey(cells.get(ref)):
                self._bump(sid, ref, c)
        b.sheets[sid]["cells"] = dict(cells)
        if name and name != b.sheets[sid]["name"]:
            b.rename(sid, name)
        self._add_version(sid, c, ts, kind, dict(cells), True)

    def _process(self, c, op):
        key = (c, op["seq"])
        if key in self.processed:
            return []
        self.processed.add(key)
        b = self.book
        k = op["kind"]
        sid = op.get("sid")

        def sname():
            sh = b.sheets.get(sid) or b.dead.get(sid)
            return sh["name"] if sh else op.get("sname")

        def can():
            return c == b.owner or b.rights.get((c, sid)) == W

        if k == "add":
            if sid in b.sheets:
                return []
            if sid in b.dead:
                b.undelete(sid)
            elif b.name_taken(op["name"]):
                return [("nom_existant", op["name"], None, None)]
            else:
                b.add_sheet(sid, op["name"])
                b.rights[(c, sid)] = W
            return []
        if k == "del":
            if sid not in b.sheets:
                return []
            if not can():
                return [("droit_insuffisant", sname(), None, None)]
            b.delete(sid)
            return []
        if k == "undel":
            if sid in b.dead:
                if not can():
                    return [("droit_insuffisant", sname(), None, None)]
                b.undelete(sid)
            return []
        if k == "right":
            if c == b.owner and sid in b.sheets:
                if op["level"] is None:
                    b.rights.pop((op["person"], sid), None)
                else:
                    b.rights[(op["person"], sid)] = op["level"]
            return []
        if k == "restore":
            v = self._ver(op["vid"])
            if v is None:
                return []
            sid = v.sid
        if sid not in b.sheets:
            return [("feuille_supprimee", sname(), None, None)]
        if not can():
            if k == "set":
                return [("modification_rejetee", sname(), ref, None) for ref, _, _ in op["cells"]]
            if k == "rename":
                return [("droit_insuffisant", sname(), None, None)]
            return [("droit_insuffisant", sname(), op.get("ref"), None)]
        ts = op["ts"]
        if k == "rename":
            new = op["name"]
            if new != b.sheets[sid]["name"]:
                if b.name_taken(new, sid):
                    return [("nom_existant", new, None, None)]
                b.rename(sid, new)
        elif k == "set":
            changed = {}
            for ref, cell, seen in op["cells"]:
                cur = b.cell(sid, ref)
                if ckey(cur) == ckey(cell):
                    continue
                rev, au = b.revs.get((sid, ref), (0, None))
                if au is not None and au != c and seen != rev:
                    b.conflicts[(sid, ref)] = (cell, c)
                    continue
                b.put(sid, ref, cell)
                self._bump(sid, ref, c)
                changed[ref] = cell
            if changed:
                self._add_version(sid, c, ts, "modification", changed, False)
        elif k == "resolve":
            ref = op["ref"]
            conf = b.conflicts.pop((sid, ref), None)
            if conf is not None and op["use"]:
                cell = conf[0]
                if ckey(b.cell(sid, ref)) != ckey(cell):
                    b.put(sid, ref, cell)
                    self._bump(sid, ref, c)
                    self._add_version(sid, c, ts, "modification", {ref: cell}, False)
        elif k == "replace":
            self._replace(sid, c, ts, dict(op["cells"]), op["name"], "modification")
        elif k == "restore":
            snap = snapshot_at(self.versions, sid, op["vid"])
            if snap is not None:
                self._replace(sid, c, ts, snap[1], snap[0], "restauration")
        return []


# ---------------------------------------------------------------- client

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line


class Conflict:
    def __init__(self, discarded, by):
        self.discarded = discarded
        self.discarded_by = by


class VersionView:
    def __init__(self, vid, author, timestamp, kind):
        self.id = vid
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


class Client:
    def __init__(self, net, clock, name, tz="UTC", _state=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.base = Book()
        self.versions = []
        self.presence_raw = {}
        self.outbox = []
        self.seq = 0
        self.active = None
        self.sel = None
        self._alerts = []
        self.undo_stack = []
        self.redo_stack = []
        self.vview = None
        if _state is not None:
            self.base = _state["base"].copy()
            self.versions = list(_state["versions"])
            self.outbox = copy.deepcopy(_state["outbox"])
            self.seq = _state["seq"]
            self.active = _state["active"]
        self.view = self.base.copy()
        net.register(name, self)
        self._rebuild()
        if net.is_connected(name):
            self._hello()

    # --- réseau
    def _connected(self):
        return self.net.is_connected(self.name)

    def _hello(self):
        for o in self.outbox:
            o["sent"] = True
        self.net.send(self.name, "server", {
            "t": "hello", "ops": copy.deepcopy(self.outbox), "sel": self.sel})

    def on_reconnect(self):
        self._hello()

    def receive(self, src, p):
        if p["t"] != "state":
            return
        self.base = p["book"].copy()
        self.versions = list(p["versions"])
        self.presence_raw = dict(p["presence"])
        acks = p["acks"]
        if acks:
            self.outbox = [o for o in self.outbox if o["seq"] not in acks]
            for al in acks.values():
                for a in al:
                    self._alerts.append(Alert(*a))
        self._rebuild()

    def _emit(self, kind, counted=True, **kw):
        self.seq += 1
        op = {"seq": self.seq, "kind": kind, "ts": self.clock.now(),
              "counted": counted, "sent": False}
        op.update(kw)
        self.outbox.append(op)
        if self._connected():
            self.net.send(self.name, "server", {"t": "op", "op": copy.deepcopy(op)})
            op["sent"] = True
        return op

    # --- copie locale
    def _rebuild(self):
        v = self.base.copy()
        v.now = self.clock.now
        for op in self.outbox:
            self._replay(v, op)
        v.recalc_all()
        self.view = v

    def _replay(self, book, op):
        k = op["kind"]
        sid = op.get("sid")
        if k == "set":
            if sid in book.sheets:
                for ref, cell, _ in op["cells"]:
                    book.put(sid, ref, cell)
                    book.conflicts.pop((sid, ref), None)
        elif k == "add":
            if book.add_sheet(sid, op["name"]):
                book.rights[(self.name, sid)] = W
        elif k == "del":
            book.delete(sid)
        elif k == "undel":
            book.undelete(sid)
        elif k == "rename":
            book.rename(sid, op["name"])
        elif k == "replace":
            if sid in book.sheets:
                book.sheets[sid]["cells"] = dict(op["cells"])
                book.rename(sid, op["name"])
        elif k == "right":
            if self.name == book.owner and sid in book.sheets:
                if op["level"] is None:
                    book.rights.pop((op["person"], sid), None)
                else:
                    book.rights[(op["person"], sid)] = op["level"]
        elif k == "resolve":
            conf = book.conflicts.pop((sid, op["ref"]), None)
            if conf is not None and op["use"]:
                book.put(sid, op["ref"], conf[0])

    # --- aides
    def _rb(self):
        b = self.vview if self.vview is not None else self.view
        b.refresh_volatile()
        return b

    def _sid(self, sheet, book=None):
        b = book or self.view
        if sheet is None:
            if self.active in b.sheets:
                return self.active
            live = b.live()
            return live[0] if live else None
        return b.sid_by_name(sheet)

    def _sname(self, sid):
        sh = self.view.sheets.get(sid) or self.view.dead.get(sid)
        return sh["name"] if sh else None

    def _can_write(self, sid):
        return self.name == self.view.owner or self.view.rights.get((self.name, sid)) == W

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _show(self, v):
        if isinstance(v, datetime):
            return v.astimezone(zi(self.tz)).strftime("%Y-%m-%d %H:%M")
        if isinstance(v, date):
            return v.isoformat()
        return v

    # --- lecture
    def content(self, ref, sheet=None):
        b = self._rb()
        sid = self._sid(sheet, b)
        cell = b.cell(sid, norm_ref(ref))
        return None if cell is None else cell[0]

    def value(self, ref, sheet=None):
        b = self._rb()
        sid = self._sid(sheet, b)
        r = b.result(sid, norm_ref(ref))
        if r is None:
            return None
        if r[0] == "e":
            return r[1]
        return self._show(r[1])

    def error(self, ref, sheet=None):
        b = self._rb()
        sid = self._sid(sheet, b)
        r = b.result(sid, norm_ref(ref))
        if r is not None and r[0] == "e":
            return r[1]
        return None

    def sheets(self):
        return [self.view.sheets[s]["name"] for s in self.view.live()]

    def activate(self, name):
        sid = self.view.sid_by_name(name)
        if sid is not None:
            self.active = sid

    def right(self, person, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        if person == self.view.owner:
            return W
        return self.view.rights.get((person, sid))

    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self._connected() else "hors ligne"

    def pending_count(self):
        return sum(1 for o in self.outbox if o["counted"])

    def set_timezone(self, tz):
        zi(tz)
        self.tz = tz

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return
        self.sel = (sid, norm_ref(ref))
        if self._connected():
            self.net.send(self.name, "server", {"t": "sel", "sel": self.sel})

    def presence(self):
        if not self._connected():
            return {}
        out = {}
        for n, (sid, ref) in self.presence_raw.items():
            if n != self.name and sid in self.view.sheets:
                out[n] = (self.view.sheets[sid]["name"], ref)
        return out

    def conflict(self, ref, sheet=None):
        b = self._rb()
        sid = self._sid(sheet, b)
        conf = b.conflicts.get((sid, norm_ref(ref)))
        if conf is None:
            return None
        return Conflict(conf[0][0] if conf[0] else None, conf[1])

    def history(self, sheet=None):
        sid = self._sid(sheet)
        vs = [v for v in self.versions if v.sid == sid]
        vs.sort(key=lambda v: (v.ts, v.id), reverse=True)
        z = zi(self.tz)
        return [VersionView(v.id, v.author, v.ts.astimezone(z).strftime("%Y-%m-%d %H:%M"), v.kind)
                for v in vs]

    # --- actions avec annulation
    def _spec_sid(self, spec):
        if spec[0] == "restore":
            for v in self.versions:
                if v.id == spec[1]:
                    return v.sid
            return None
        return spec[1]

    def _apply_spec(self, spec):
        k = spec[0]
        if k == "set":
            sid, ch = spec[1], spec[2]
            if sid not in self.view.sheets:
                return []
            cells = [(ref, cell, self.base.revs.get((sid, ref), (0, None))[0]) for ref, cell in ch]
            op = self._emit("set", sid=sid, cells=cells, sname=self._sname(sid))
            for ref, cell, _ in cells:
                self.view.put(sid, ref, cell)
                self.view.conflicts.pop((sid, ref), None)
            self.view.recalc_cells([(sid, ref) for ref, _, _ in cells])
            return [op["seq"]]
        if k == "add":
            op = self._emit("add", sid=spec[1], name=spec[2], sname=spec[2])
        elif k == "del":
            op = self._emit("del", sid=spec[1], sname=self._sname(spec[1]))
        elif k == "undel":
            op = self._emit("undel", sid=spec[1], sname=self._sname(spec[1]))
        elif k == "rename":
            op = self._emit("rename", sid=spec[1], name=spec[2], sname=self._sname(spec[1]))
        elif k == "replace":
            op = self._emit("replace", sid=spec[1], name=spec[2], cells=dict(spec[3]),
                            sname=self._sname(spec[1]))
        else:
            sid = self._spec_sid(spec)
            op = self._emit("restore", sid=sid, vid=spec[1], sname=self._sname(sid))
        self._rebuild()
        return [op["seq"]]

    def _do(self, spec, inv, expect=None):
        seqs = self._apply_spec(spec)
        self.undo_stack.append({"do": spec, "undo": inv, "expect": expect, "seqs": seqs})
        self.redo_stack.clear()

    def _commit(self, sid, items):
        ch = []
        prev = []
        for ref, cell in items:
            cur = self.view.cell(sid, ref)
            if ckey(cur) != ckey(cell):
                ch.append((ref, cell))
                prev.append((ref, cur))
        if not ch:
            return
        self._do(("set", sid, ch), ("set", sid, prev), ("set", sid, ch))

    def _edit(self, sheet, ref, cell):
        if self.vview is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = norm_ref(ref)
        if not self._can_write(sid):
            self._alert("droit_insuffisant", self._sname(sid), ref)
            return
        self._commit(sid, [(ref, cell)])

    def set_cell(self, ref, text, sheet=None):
        cell = None if text == "" else (text, False, self.tz)
        self._edit(sheet, ref, cell)

    def clear(self, ref, sheet=None):
        self._edit(sheet, ref, None)

    def import_csv(self, data):
        if self.vview is not None:
            return
        sid = self._sid(None)
        if sid is None:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", self._sname(sid))
            return
        try:
            text = bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:
            self._alert("csv_invalide", self._sname(sid))
            return
        rows, bad = parse_csv(text)
        if rows is None:
            self._alert("csv_invalide", self._sname(sid), None, bad)
            return
        items = []
        for ri, row in enumerate(rows):
            for ci, f in enumerate(row):
                ref = col_name(ci + 1) + str(ri + 1)
                items.append((ref, None if f == "" else (f, f.startswith("="), self.tz)))
        self._commit(sid, items)

    def add_sheet(self, name):
        if self.vview is not None:
            return
        if self.view.name_taken(name):
            self._alert("nom_existant", name)
            return
        sid = "%s#%d" % (self.name, self.seq + 1)
        self._do(("add", sid, name), ("del", sid), ("add", sid))

    def delete_sheet(self, name):
        if self.vview is not None:
            return
        sid = self.view.sid_by_name(name)
        if sid is None:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", name)
            return
        if len(self.view.sheets) <= 1:
            return
        self._do(("del", sid), ("undel", sid), ("del", sid))

    def rename_sheet(self, old, new):
        if self.vview is not None:
            return
        sid = self.view.sid_by_name(old)
        if sid is None or old == new:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", old)
            return
        if self.view.name_taken(new, sid):
            self._alert("nom_existant", new)
            return
        self._do(("rename", sid, new), ("rename", sid, old), ("rename", sid, new))

    def set_right(self, person, sheet, level):
        if self.name != self.view.owner or not self._connected():
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        if self.view.rights.get((person, sid)) == level:
            return
        self._emit("right", counted=False, sid=sid, person=person, level=level)
        self._rebuild()

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.vview is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = norm_ref(ref)
        if not self._can_write(sid):
            self._alert("droit_insuffisant", self._sname(sid), ref)
            return
        if (sid, ref) not in self.view.conflicts:
            return
        self._emit("resolve", sid=sid, ref=ref, use=bool(use_discarded), sname=self._sname(sid))
        self._rebuild()

    # --- annuler / rétablir
    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _retract(self, e):
        if not self.outbox or len(e["seqs"]) != 1:
            return False
        last = self.outbox[-1]
        seq = last["seq"]
        if last["kind"] == "right" or seq != e["seqs"][0]:
            return False
        if self._connected() and last["sent"]:
            def fn(p):
                if p["t"] == "op" and p["op"]["seq"] == seq:
                    return True, None
                if p["t"] == "hello":
                    for i, o in enumerate(p["ops"]):
                        if o["seq"] == seq:
                            p["ops"].pop(i)
                            return True, p
                return False, p
            if not self.net.retract(self.name, fn):
                return False
        self.outbox.pop()
        self._rebuild()
        return True

    def _expect(self, e):
        ex = e["expect"]
        if ex is None:
            return True
        v = self.view
        if ex[0] == "set":
            return ex[1] in v.sheets and all(ckey(v.cell(ex[1], r)) == ckey(c) for r, c in ex[2])
        if ex[0] == "add":
            return ex[1] in v.sheets
        if ex[0] == "del":
            return ex[1] not in v.sheets
        if ex[0] == "rename":
            return ex[1] in v.sheets and v.sheets[ex[1]]["name"] == ex[2]
        return True

    def undo(self):
        if self.vview is not None or not self.undo_stack:
            return
        e = self.undo_stack[-1]
        sid = e["undo"][1]
        if e["undo"][0] != "del" and not self._can_write(sid):
            self._alert("droit_insuffisant", self._sname(sid))
            return
        self.undo_stack.pop()
        if self._retract(e):
            self.redo_stack.append(e)
            return
        if not self._expect(e):
            self._alert("annulation_impossible", self._sname(sid))
            return
        self._apply_spec(e["undo"])
        self.redo_stack.append(e)

    def redo(self):
        if self.vview is not None or not self.redo_stack:
            return
        e = self.redo_stack[-1]
        spec = e["do"]
        sid = self._spec_sid(spec)
        if spec[0] != "add" and sid is not None and not self._can_write(sid):
            self._alert("droit_insuffisant", self._sname(sid))
            return
        self.redo_stack.pop()
        e = dict(e)
        e["seqs"] = self._apply_spec(spec)
        self.undo_stack.append(e)

    # --- versions
    def open_version(self, vid):
        snap = None
        sid = None
        for v in self.versions:
            if v.id == vid:
                sid = v.sid
                snap = snapshot_at(self.versions, sid, vid)
                break
        if snap is None:
            return
        b = self.view.copy()
        b.now = self.clock.now
        if sid in b.sheets:
            b.sheets[sid]["cells"] = dict(snap[1])
        b.recalc_all()
        self.vview = b

    def close_version(self):
        self.vview = None

    def restore_version(self, vid):
        if self.vview is not None:
            return
        sid = self._spec_sid(("restore", vid))
        if sid is None or sid not in self.view.sheets:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", self._sname(sid))
            return
        if not self._connected():
            return
        sh = self.view.sheets[sid]
        prev = ("replace", sid, sh["name"], dict(sh["cells"]))
        self._do(("restore", vid), prev, None)

    # --- CSV
    def _csv_field(self, b, sid, ref):
        r = b.result(sid, ref)
        if r is None:
            return ""
        if r[0] == "e":
            return r[1]
        v = r[1]
        if isinstance(v, datetime):
            return v.astimezone(zi(self.tz)).replace(microsecond=0).isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, float):
            return repr(v)
        return str(v)

    def export_csv(self):
        b = self._rb()
        sid = self._sid(None, b)
        cells = b.sheets[sid]["cells"] if sid in b.sheets else {}
        grid = set()
        maxc = 0
        for ref in cells:
            c, r = split_ref(ref)
            grid.add((r, c))
            maxc = max(maxc, c)
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        for r in sorted({r for r, _ in grid}):
            w.writerow([self._csv_field(b, sid, col_name(c) + str(r)) if (r, c) in grid else ""
                        for c in range(1, maxc + 1)])
        return out.getvalue().encode("utf-8")

    # --- appareil
    def reopen(self):
        st = {"base": self.base, "versions": self.versions,
              "outbox": copy.deepcopy(self.outbox), "seq": self.seq, "active": self.active}
        return Client(self.net, self.clock, self.name, tz=self.tz, _state=st)
