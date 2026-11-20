"""Classeur collaboratif hors ligne : formules, copies locales, réseau simulé, fuseaux."""
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
        self.q = deque()
        self.nodes = {}
        self.down = set()

    def register(self, name, node):
        self.nodes[name] = node

    def is_connected(self, name):
        return name not in self.down

    def send(self, src, dst, payload):
        if src in self.down or dst in self.down:
            return False
        self.q.append((src, dst, copy.deepcopy(payload)))
        return True

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

    def disconnect(self, name):
        if name in self.down:
            return
        self.down.add(name)
        self.q = deque(m for m in self.q if m[0] != name and m[1] != name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_disconnect"):
            node.on_disconnect()
        self.q.append(("__net__", "server", {"k": "down", "who": name}))

    def reconnect(self, name):
        if name not in self.down:
            return
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_connect"):
            node.on_connect()


# ------------------------------------------------------------------ formules

class Err(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


REF_RE = re.compile(r"[A-Za-z]{1,3}\d+")
TOK_RE = re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)|([^\W\d]\w*)|([-+*/(),:!]))")
NUM_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
D_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def tokenize(s):
    toks = []
    pos = 0
    n = len(s)
    while pos < n:
        m = TOK_RE.match(s, pos)
        if not m:
            if s[pos:].strip() == "":
                break
            raise Err("#SYNTAXE!")
        pos = m.end()
        if m.group(1) is not None:
            toks.append(("num", m.group(1)))
        elif m.group(2) is not None:
            toks.append(("id", m.group(2)))
        else:
            toks.append(("op", m.group(3)))
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def expect(self, op):
        if self.peek() != ("op", op):
            raise Err("#SYNTAXE!")
        self.i += 1

    def parse(self):
        e = self.expr()
        if self.i != len(self.t):
            raise Err("#SYNTAXE!")
        return e

    def expr(self):
        left = self.term()
        while True:
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] in ("+", "-"):
                self.i += 1
                left = ("bin", t[1], left, self.term())
            else:
                return left

    def term(self):
        left = self.unary()
        while True:
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] in ("*", "/"):
                self.i += 1
                left = ("bin", t[1], left, self.unary())
            else:
                return left

    def unary(self):
        t = self.peek()
        if t == ("op", "-"):
            self.i += 1
            return ("neg", self.unary())
        if t == ("op", "+"):
            self.i += 1
            return self.unary()
        return self.primary()

    def primary(self):
        t = self.peek()
        if t is None:
            raise Err("#SYNTAXE!")
        if t[0] == "num":
            self.i += 1
            v = t[1]
            return ("num", float(v) if "." in v else int(v))
        if t == ("op", "("):
            self.i += 1
            e = self.expr()
            self.expect(")")
            return e
        if t[0] == "id":
            self.i += 1
            name = t[1]
            nxt = self.peek()
            if nxt == ("op", "!"):
                self.i += 1
                r = self.peek()
                if r is None or r[0] != "id" or not REF_RE.fullmatch(r[1]):
                    raise Err("#SYNTAXE!")
                self.i += 1
                return ("ref", name, r[1].upper())
            if nxt == ("op", "("):
                return self.call(name)
            if REF_RE.fullmatch(name):
                return ("ref", None, name.upper())
        raise Err("#SYNTAXE!")

    def arg(self):
        t = self.peek()
        if t is not None and t[0] == "id":
            sheet = None
            j = 0
            if self.peek(1) == ("op", "!"):
                sheet = t[1]
                j = 2
            a = self.peek(j)
            b = self.peek(j + 1)
            if a is not None and a[0] == "id" and REF_RE.fullmatch(a[1]) and b == ("op", ":"):
                c = self.peek(j + 2)
                if c is not None and c[0] == "id" and REF_RE.fullmatch(c[1]):
                    self.i += j + 3
                    return ("range", sheet, a[1].upper(), c[1].upper())
                raise Err("#SYNTAXE!")
        return self.expr()

    def call(self, name):
        fn = name.upper()
        if fn not in ("SOMME", "MAINTENANT"):
            raise Err("#SYNTAXE!")
        self.i += 1
        args = []
        if self.peek() != ("op", ")"):
            args.append(self.arg())
            while self.peek() == ("op", ","):
                self.i += 1
                args.append(self.arg())
        self.expect(")")
        if (fn == "MAINTENANT" and args) or (fn == "SOMME" and not args):
            raise Err("#SYNTAXE!")
        return ("call", fn, args)


@lru_cache(maxsize=None)
def parse_formula(text):
    try:
        return _Parser(tokenize(text[1:])).parse()
    except Err as e:
        return Err(e.code)


@lru_cache(maxsize=None)
def split_ref(ref):
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", ref)
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return col, int(m.group(2))


def col_name(c):
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def norm_ref(ref):
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d+)", ref or "")
    if not m or int(m.group(2)) < 1:
        return None
    return m.group(1).upper() + str(int(m.group(2)))


@lru_cache(maxsize=None)
def zone(tz):
    return ZoneInfo(tz or "UTC")


def make_cell(text, tz, lit=False):
    m = DT_RE.fullmatch(text)
    if m and not m.group(1) and not lit:
        return (text, lit, tz)
    return (text, lit, None)


def is_formula(cell):
    return (not cell[1]) and cell[0].startswith("=")


@lru_cache(maxsize=None)
def literal(cell):
    text, lit, tz = cell
    if lit:
        return text
    if NUM_RE.fullmatch(text):
        return float(text) if "." in text else int(text)
    if DT_RE.fullmatch(text):
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=zone(tz))
            return dt.astimezone(UTC)
        except ValueError:
            return text
    if D_RE.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return text
    return text


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def norm_num(v):
    if isinstance(v, float) and v == v and v not in (float("inf"), float("-inf")) and v.is_integer():
        return int(v)
    return v


def arith(op, a, b):
    if is_num(a) and is_num(b):
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise Err("#DIV/0!")
        return a / b
    if op == "-" and isinstance(a, datetime) and isinstance(b, datetime):
        return (a - b).total_seconds() / 86400
    if op == "-" and type(a) is date and type(b) is date:
        return (a - b).days
    if op in ("+", "-") and isinstance(a, date) and is_num(b):
        return a + timedelta(days=b) if op == "+" else a - timedelta(days=b)
    if op == "+" and is_num(a) and isinstance(b, date):
        return b + timedelta(days=a)
    raise Err("#TYPE!")


def rewrite(text, old_fold, new):
    def repl(m):
        return new + "!" if m.group(1).casefold() == old_fold else m.group(0)
    return re.sub(r"([^\W\d]\w*)!", repl, text)


def scc_order(nodes, deps):
    index = {}
    low = {}
    onstack = set()
    stack = []
    out = []
    idx = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = idx
                idx += 1
                stack.append(v)
                onstack.add(v)
            ds = deps[v]
            descended = False
            while i < len(ds):
                w = ds[i]
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    descended = True
                    break
                if w in onstack:
                    low[v] = min(low[v], index[w])
            if descended:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(comp)
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    return out


# ------------------------------------------------------------------ document

class Sheet:
    __slots__ = ("name", "cells")

    def __init__(self, name, cells=None):
        self.name = name
        self.cells = cells if cells is not None else {}


class Ver:
    __slots__ = ("id", "author", "ts", "kind", "name", "cells")

    def __init__(self, id, author, ts, kind, name, cells):
        self.id = id
        self.author = author
        self.ts = ts
        self.kind = kind
        self.name = name
        self.cells = cells


class Doc:
    def __init__(self, track=False):
        self.owner = None
        self.sheets = {"s0": Sheet("Feuille1")}
        self.rights = {"s0": {}}
        self.trash = {}
        self.conf = {}
        self.versions = {} if track else None
        self.rev = 0
        self._cache = None

    def clone(self):
        d = Doc(False)
        d.owner = self.owner
        d.sheets = {k: Sheet(s.name, dict(s.cells)) for k, s in self.sheets.items()}
        d.rights = {k: dict(v) for k, v in self.rights.items()}
        d.trash = dict(self.trash)
        d.conf = dict(self.conf)
        return d

    def level(self, person, sid):
        if person == self.owner:
            return W
        return self.rights.get(sid, {}).get(person)

    def cell(self, sid, ref):
        sh = self.sheets.get(sid)
        return sh.cells.get(ref) if sh is not None else None

    def taken(self, name, excl=None):
        f = name.casefold()
        return any(sid != excl and s.name.casefold() == f for sid, s in self.sheets.items())

    def _ver(self, e, sid, sh, kind):
        if self.versions is not None:
            self.versions.setdefault(sid, []).append(
                Ver(e["seq"], e["author"], e["ts"], kind, sh.name, dict(sh.cells)))

    def _rename(self, sid, new):
        sh = self.sheets[sid]
        old = sh.name
        sh.name = new
        of = old.casefold()
        for s in self.sheets.values():
            for ref, cell in list(s.cells.items()):
                if is_formula(cell) and "!" in cell[0]:
                    t = rewrite(cell[0], of, new)
                    if t != cell[0]:
                        s.cells[ref] = (t, cell[1], cell[2])

    def _drop_conf(self, sid):
        for k in [k for k in self.conf if k[0] == sid]:
            del self.conf[k]

    def apply(self, e):
        t = e["t"]
        self.rev += 1
        if t == "cells":
            sid = e["sid"]
            sh = self.sheets.get(sid)
            if sh is None:
                return
            for ref, cell in e["ch"]:
                if cell is None:
                    sh.cells.pop(ref, None)
                else:
                    sh.cells[ref] = cell
                self.conf.pop((sid, ref), None)
            if e["ch"]:
                self._ver(e, sid, sh, "modification")
        elif t == "conflict":
            if e["sid"] in self.sheets:
                self.conf[(e["sid"], e["ref"])] = (e["cell"], e["by"])
        elif t == "resolve":
            sid, ref = e["sid"], e["ref"]
            sh = self.sheets.get(sid)
            c = self.conf.pop((sid, ref), None)
            if sh is not None and c is not None and e["use"]:
                if c[0] is None:
                    sh.cells.pop(ref, None)
                else:
                    sh.cells[ref] = c[0]
                self._ver(e, sid, sh, "modification")
        elif t == "add":
            sid = e["sid"]
            if sid not in self.sheets and not self.taken(e["name"]):
                self.sheets[sid] = Sheet(e["name"])
                self.rights[sid] = {e["author"]: W}
        elif t == "del":
            sh = self.sheets.pop(e["sid"], None)
            if sh is not None:
                self.trash[e["sid"]] = sh
                self._drop_conf(e["sid"])
        elif t == "undel":
            sid = e["sid"]
            if sid not in self.sheets and not self.taken(e["name"]):
                self.sheets[sid] = Sheet(e["name"], dict(e["cells"]))
                self.trash.pop(sid, None)
        elif t == "ren":
            if e["sid"] in self.sheets:
                self._rename(e["sid"], e["new"])
        elif t == "restore":
            sid = e["sid"]
            sh = self.sheets.get(sid)
            if sh is None:
                return
            if sh.name != e["name"]:
                self._rename(sid, e["name"])
            sh.cells = dict(e["cells"])
            self._drop_conf(sid)
            self._ver(e, sid, sh, e.get("vk") or "modification")
        elif t == "right":
            r = self.rights.setdefault(e["sid"], {})
            if e["level"] is None:
                r.pop(e["person"], None)
            else:
                r[e["person"]] = e["level"]

    # ---- valeurs

    def value(self, sid, ref, now):
        cell = self.cell(sid, ref)
        if cell is None:
            return None
        if is_formula(cell):
            return self.compute(now).get((sid, ref))
        return literal(cell)

    def compute(self, now):
        key = (self.rev, now)
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        nodes = {}
        by_sheet = {}
        for sid, sh in self.sheets.items():
            for ref, cell in sh.cells.items():
                if is_formula(cell):
                    nodes[(sid, ref)] = parse_formula(cell[0])
                    by_sheet.setdefault(sid, []).append(ref)
        names = {sh.name.casefold(): sid for sid, sh in self.sheets.items()}
        deps = {}
        for (sid, ref), ast in nodes.items():
            ds = []
            if not isinstance(ast, Err):
                self._collect(ast, sid, names, nodes, by_sheet, ds)
            deps[(sid, ref)] = ds
        vals = {}
        for comp in scc_order(nodes, deps):
            k = comp[0]
            if len(comp) > 1 or k in deps[k]:
                for c in comp:
                    vals[c] = Err("#CIRC!")
                continue
            ast = nodes[k]
            if isinstance(ast, Err):
                vals[k] = Err(ast.code)
                continue
            try:
                vals[k] = norm_num(self._eval(ast, k[0], names, vals, now))
            except Err as e:
                vals[k] = Err(e.code)
        self._cache = (key, vals)
        return vals

    def _target(self, sname, sid, names):
        if sname is None:
            return sid
        return names.get(sname.casefold())

    def _collect(self, ast, sid, names, nodes, by_sheet, ds):
        stack = [ast]
        while stack:
            n = stack.pop()
            t = n[0]
            if t == "ref":
                s = self._target(n[1], sid, names)
                if s is not None and (s, n[2]) in nodes:
                    ds.append((s, n[2]))
            elif t == "range":
                s = self._target(n[1], sid, names)
                if s is not None:
                    c1, r1, c2, r2 = self._rect(n)
                    for ref in by_sheet.get(s, ()):
                        c, r = split_ref(ref)
                        if c1 <= c <= c2 and r1 <= r <= r2:
                            ds.append((s, ref))
            elif t == "neg":
                stack.append(n[1])
            elif t == "bin":
                stack.append(n[2])
                stack.append(n[3])
            elif t == "call":
                stack.extend(n[2])

    @staticmethod
    def _rect(n):
        ca, ra = split_ref(n[2])
        cb, rb = split_ref(n[3])
        return min(ca, cb), min(ra, rb), max(ca, cb), max(ra, rb)

    def _read(self, s, ref, vals):
        k = (s, ref)
        if k in vals:
            v = vals[k]
        else:
            cell = self.sheets[s].cells.get(ref)
            if cell is None:
                return 0
            if is_formula(cell):
                raise Err("#CIRC!")
            v = literal(cell)
        if isinstance(v, Err):
            raise Err(v.code)
        return v

    def _range_values(self, n, sid, names, vals):
        s = self._target(n[1], sid, names)
        if s is None:
            raise Err("#REF!")
        c1, r1, c2, r2 = self._rect(n)
        cells = self.sheets[s].cells
        area = (c2 - c1 + 1) * (r2 - r1 + 1)
        if area <= len(cells):
            refs = [col_name(c) + str(r) for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)
                    if (col_name(c) + str(r)) in cells]
        else:
            refs = []
            for ref in cells:
                c, r = split_ref(ref)
                if c1 <= c <= c2 and r1 <= r <= r2:
                    refs.append(ref)
        return [self._read(s, ref, vals) for ref in refs]

    def _eval(self, n, sid, names, vals, now):
        t = n[0]
        if t == "num":
            return n[1]
        if t == "ref":
            s = self._target(n[1], sid, names)
            if s is None:
                raise Err("#REF!")
            return self._read(s, n[2], vals)
        if t == "neg":
            v = self._eval(n[1], sid, names, vals, now)
            if not is_num(v):
                raise Err("#TYPE!")
            return -v
        if t == "bin":
            a = self._eval(n[2], sid, names, vals, now)
            b = self._eval(n[3], sid, names, vals, now)
            return norm_num(arith(n[1], a, b))
        if t == "call":
            if n[1] == "MAINTENANT":
                return now
            total = 0
            for a in n[2]:
                if a[0] == "range":
                    for v in self._range_values(a, sid, names, vals):
                        if is_num(v):
                            total += v
                else:
                    v = self._eval(a, sid, names, vals, now)
                    if not is_num(v):
                        raise Err("#TYPE!")
                    total += v
            return norm_num(total)
        raise Err("#SYNTAXE!")


# ------------------------------------------------------------------ CSV

class CsvError(Exception):
    def __init__(self, line):
        super().__init__(line)
        self.line = line


def parse_csv(text):
    text = text.replace("\r\n", "\n")
    rows = []
    row = []
    field = []
    i = 0
    n = len(text)
    line = 1
    inq = False
    qline = 0
    quoted = False
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
        if ch == '"' and not field and not quoted:
            inq = True
            quoted = True
            qline = line
            i += 1
            continue
        if ch == ",":
            row.append("".join(field))
            field = []
            quoted = False
            i += 1
            continue
        if ch == "\n":
            row.append("".join(field))
            rows.append(row)
            row = []
            field = []
            quoted = False
            line += 1
            i += 1
            continue
        field.append(ch)
        i += 1
    if inq:
        raise CsvError(qline)
    if field or row or quoted:
        row.append("".join(field))
        rows.append(row)
    return rows


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.doc = Doc(False)
        self.doc.owner = owner
        self.log = []
        self.lastw = {}
        self.done = {}
        self.pres = {}
        self.members = set()
        net.register("server", self)

    def _send(self, dst, payload):
        self.net.send("server", dst, payload)

    def _broadcast(self, payload, exclude=None):
        for n in sorted(self.members):
            if n != exclude:
                self._send(n, payload)

    def receive(self, src, m):
        k = m["k"]
        if k == "down":
            who = m["who"]
            if self.pres.pop(who, None) is not None:
                self._broadcast({"k": "pres", "who": who, "at": None}, exclude=who)
            return
        self.members.add(src)
        if k == "hello":
            self._send(src, {"k": "welcome", "owner": self.owner,
                             "pres": {n: p for n, p in self.pres.items() if n != src}})
            for e in self.log[m["last"]:]:
                self._send(src, {"k": "entry", "e": e})
            for op in m["ops"]:
                self._handle_op(src, op)
        elif k == "op":
            self._handle_op(src, m["op"])
        elif k == "right":
            sid = m["sid"]
            if src == self.owner and sid in self.doc.sheets:
                op = {"t": "right", "sid": sid, "person": m["person"], "level": m["level"],
                      "id": None, "ts": self.clock.now()}
                self._commit(src, op, [dict(op)])
        elif k == "pres":
            self.pres[src] = (m["sid"], m["ref"])
            self._broadcast({"k": "pres", "who": src, "at": (m["sid"], m["ref"])}, exclude=src)

    def _reject(self, src, op, reason, sheet=None, cells=None):
        msg = {"k": "reject", "id": op["id"], "reason": reason, "t": op["t"],
               "sheet": sheet, "cells": cells}
        self.done[(src, op["id"])] = msg
        self._send(src, msg)

    def _track(self, e):
        t = e["t"]
        seq = e["seq"]
        a = e["author"]
        if t == "cells":
            for ref, _ in e["ch"]:
                self.lastw.setdefault((e["sid"], ref), {})[a] = seq
        elif t == "resolve" and e["use"]:
            self.lastw.setdefault((e["sid"], e["ref"]), {})[a] = seq
        elif t == "restore":
            sh = self.doc.sheets.get(e["sid"])
            refs = set(e["cells"])
            if sh is not None:
                refs |= set(sh.cells)
            for ref in refs:
                self.lastw.setdefault((e["sid"], ref), {})[a] = seq

    def _commit(self, src, op, entries):
        for i, e in enumerate(entries):
            e["seq"] = len(self.log) + 1
            e["author"] = src
            e["ts"] = op.get("ts") or self.clock.now()
            e["ack"] = op["id"] if i == len(entries) - 1 else None
            self._track(e)
            self.doc.apply(e)
            self.log.append(e)
            self._broadcast({"k": "entry", "e": e})

    def _handle_op(self, src, op):
        key = (src, op["id"])
        if key in self.done:
            r = self.done[key]
            if r is not None:
                self._send(src, r)
            return
        self.done[key] = None
        t = op["t"]
        d = self.doc
        sid = op.get("sid")
        if t == "add":
            if d.taken(op["name"]) or sid in d.sheets:
                return self._reject(src, op, "name", op["name"])
            return self._commit(src, op, [dict(op)])
        sh = d.sheets.get(sid)
        if t == "undel":
            sh = d.trash.get(sid)
            if sh is None or sid in d.sheets:
                return self._reject(src, op, "noop")
            if d.level(src, sid) != W:
                return self._reject(src, op, "rights", sh.name)
            if d.taken(sh.name):
                return self._reject(src, op, "name", sh.name)
            return self._commit(src, op, [{"t": "undel", "sid": sid, "name": sh.name,
                                           "cells": dict(sh.cells), "id": op["id"], "ts": op["ts"]}])
        if sh is None:
            name = d.trash[sid].name if sid in d.trash else op.get("sn")
            return self._reject(src, op, "gone", name)
        if d.level(src, sid) != W:
            cells = [r for r, _ in op["ch"]] if t == "cells" else None
            return self._reject(src, op, "rights", sh.name, cells)
        if t == "cells":
            entries = []
            ok = []
            for ref, cell in op["ch"]:
                cur = sh.cells.get(ref)
                others = [s for a, s in self.lastw.get((sid, ref), {}).items() if a != src]
                if others and max(others) > op["base"] and cur != cell:
                    entries.append({"t": "conflict", "sid": sid, "ref": ref, "cell": cell,
                                    "by": src, "id": op["id"]})
                else:
                    ok.append((ref, cell))
            if ok:
                entries.append(dict(op, ch=ok))
            if not entries:
                return self._reject(src, op, "noop")
            return self._commit(src, op, entries)
        if t == "del":
            if len(d.sheets) <= 1:
                return self._reject(src, op, "last", sh.name)
            return self._commit(src, op, [dict(op)])
        if t == "ren":
            if op["new"] == sh.name:
                return self._reject(src, op, "noop")
            if d.taken(op["new"], sid):
                return self._reject(src, op, "name", op["new"])
            return self._commit(src, op, [dict(op)])
        if t == "resolve":
            if (sid, op["ref"]) not in d.conf:
                return self._reject(src, op, "noop")
            return self._commit(src, op, [dict(op)])
        if t == "restore":
            if sh.name != op["name"] and d.taken(op["name"], sid):
                return self._reject(src, op, "name", op["name"])
            return self._commit(src, op, [dict(op)])
        return self._reject(src, op, "noop")


# ------------------------------------------------------------------ client

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


class Client:
    def __init__(self, net, clock, name, tz="Europe/Paris", _state=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self._dead = False
        if _state is not None:
            self.conf = _state["conf"]
            self.pending = _state["pending"]
            self.seq = _state["seq"]
            self.n = _state["n"]
            self.tz = _state["tz"]
        else:
            self.conf = Doc(True)
            self.pending = []
            self.seq = 0
            self.n = 0
        self.buf = {}
        self.sent = set()
        self._alerts = []
        self.undo_s = []
        self.redo_s = []
        self.pres = {}
        self.active = "s0"
        self.consult = None
        self._cdoc = None
        self.view = None
        self._rebuild()
        net.register(name, self)
        if net.is_connected(name):
            self.on_connect()

    # ---- réseau

    def _send(self, payload):
        return self.net.send(self.name, "server", payload)

    def on_connect(self):
        self.sent = {o["id"] for o in self.pending}
        self._send({"k": "hello", "last": self.seq, "ops": list(self.pending)})

    def on_disconnect(self):
        self.sent = set()
        self.pres = {}

    def receive(self, src, m):
        if self._dead:
            return
        k = m["k"]
        if k == "entry":
            self._entry(m["e"])
        elif k == "welcome":
            self.conf.owner = m["owner"]
            self.pres = dict(m["pres"])
            self._rebuild()
        elif k == "reject":
            self._reject(m)
        elif k == "pres":
            if m["at"] is None:
                self.pres.pop(m["who"], None)
            else:
                self.pres[m["who"]] = tuple(m["at"])

    def _entry(self, e):
        if e["seq"] <= self.seq:
            return
        self.buf[e["seq"]] = e
        changed = False
        while self.seq + 1 in self.buf:
            e = self.buf.pop(self.seq + 1)
            self.conf.apply(e)
            self.seq = e["seq"]
            changed = True
            ack = e.get("ack")
            if ack and e["author"] == self.name:
                self._settle(ack)
                if e["t"] == "conflict":
                    self._prune(ack)
        if changed:
            self._rebuild()

    def _settle(self, opid):
        self.pending = [o for o in self.pending if o["id"] != opid]
        self.sent.discard(opid)

    def _prune(self, opid):
        self.undo_s = [r for r in self.undo_s if r["opid"] != opid]

    def _reject(self, m):
        opid = m["id"]
        self._settle(opid)
        self._prune(opid)
        r = m["reason"]
        sn = m.get("sheet")
        if r == "rights":
            if m["t"] == "cells" and m.get("cells"):
                for ref in m["cells"]:
                    self._alert("modification_rejetee", sn, ref)
            else:
                self._alert("droit_insuffisant", sn)
        elif r == "gone":
            self._alert("feuille_supprimee", sn)
        elif r == "name":
            self._alert("nom_existant", sn)
        self._rebuild()

    def _rebuild(self):
        v = self.conf.clone()
        for op in self.pending:
            v.apply(op)
        self.view = v

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def alerts(self):
        return list(self._alerts)

    # ---- aides

    def _sid(self, sheet=None):
        d = self.view
        if sheet is None:
            if self.active in d.sheets:
                return self.active
            return next(iter(d.sheets), None)
        f = sheet.casefold()
        for sid, sh in d.sheets.items():
            if sh.name.casefold() == f:
                return sid
        return None

    def _can_write(self, sid):
        return self.view.level(self.name, sid) == W

    def _doc(self):
        if self.consult is None:
            return self.view
        c = self._cdoc
        if c is None or c[0] is not self.view or c[1] != self.view.rev:
            d = self.view.clone()
            sid, ver = self.consult
            if sid in d.sheets:
                d.sheets[sid].cells = dict(ver.cells)
            c = (self.view, self.view.rev, d)
            self._cdoc = c
        return c[2]

    def _submit(self, op):
        self.n += 1
        op.update(id=f"{self.name}:{self.n}", author=self.name, ts=self.clock.now(), base=self.seq)
        self.pending.append(op)
        self.view.apply(op)
        if self._send({"k": "op", "op": op}):
            self.sent.add(op["id"])
        return op["id"]

    def _act(self, do, undo, pre=(), post=()):
        opid = self._submit(dict(do))
        self.undo_s.append({"do": do, "undo": undo, "pre": list(pre), "post": list(post), "opid": opid})
        self.redo_s.clear()

    def _edit_cells(self, sid, changes):
        d = self.view
        sn = d.sheets[sid].name
        pre = [(sid, r, d.cell(sid, r)) for r, _ in changes]
        post = [(sid, r, c) for r, c in changes]
        do = {"t": "cells", "sid": sid, "ch": list(changes), "sn": sn}
        undo = {"t": "cells", "sid": sid, "ch": [(r, c) for _, r, c in pre], "sn": sn}
        self._act(do, undo, pre, post)

    def _writable_sheet(self, ref, sheet):
        if self.consult is not None:
            return None
        sid = self._sid(sheet)
        if sid is None:
            return None
        if ref is not None and norm_ref(ref) is None:
            return None
        if not self._can_write(sid):
            self._alert("droit_insuffisant", self.view.sheets[sid].name,
                        norm_ref(ref) if ref is not None else None)
            return None
        return sid

    # ---- saisie

    def set_cell(self, ref, text, sheet=None):
        sid = self._writable_sheet(ref, sheet)
        if sid is None:
            return
        cell = None if text == "" else make_cell(text, self.tz)
        self._edit_cells(sid, [(norm_ref(ref), cell)])

    def clear(self, ref, sheet=None):
        sid = self._writable_sheet(ref, sheet)
        if sid is None:
            return
        self._edit_cells(sid, [(norm_ref(ref), None)])

    def content(self, ref, sheet=None):
        ref = norm_ref(ref)
        sid = self._sid(sheet)
        if sid is None or ref is None:
            return None
        cell = self._doc().cell(sid, ref)
        return cell[0] if cell is not None else None

    def _raw_value(self, ref, sheet):
        ref = norm_ref(ref)
        sid = self._sid(sheet)
        if sid is None or ref is None:
            return None
        return self._doc().value(sid, ref, self.clock.now())

    def value(self, ref, sheet=None):
        v = self._raw_value(ref, sheet)
        if isinstance(v, Err):
            return v.code
        if isinstance(v, datetime):
            return v.astimezone(zone(self.tz)).strftime("%Y-%m-%d %H:%M")
        if isinstance(v, date):
            return v.isoformat()
        return norm_num(v)

    def error(self, ref, sheet=None):
        v = self._raw_value(ref, sheet)
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        zone(tz)
        self.tz = tz

    # ---- feuilles

    def sheets(self):
        return [s.name for s in self.view.sheets.values()]

    def activate(self, name):
        sid = self._sid(name)
        if sid is not None:
            self.active = sid

    def add_sheet(self, name):
        if self.view.taken(name):
            self._alert("nom_existant", name)
            return
        sid = f"sh:{self.name}:{self.n + 1}"
        do = {"t": "add", "sid": sid, "name": name, "sn": name}
        undo = {"t": "del", "sid": sid, "sn": name}
        self._act(do, undo)

    def delete_sheet(self, name):
        sid = self._sid(name)
        if sid is None:
            return
        sh = self.view.sheets[sid]
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        if len(self.view.sheets) <= 1:
            return
        do = {"t": "del", "sid": sid, "sn": sh.name}
        undo = {"t": "undel", "sid": sid, "name": sh.name, "cells": dict(sh.cells), "sn": sh.name}
        self._act(do, undo)

    def rename_sheet(self, old, new):
        sid = self._sid(old)
        if sid is None:
            return
        sh = self.view.sheets[sid]
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        if self.view.taken(new, sid):
            self._alert("nom_existant", new)
            return
        if new == sh.name:
            return
        do = {"t": "ren", "sid": sid, "old": sh.name, "new": new, "sn": sh.name}
        undo = {"t": "ren", "sid": sid, "old": new, "new": sh.name, "sn": new}
        self._act(do, undo)

    # ---- droits

    def right(self, person, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        return self.view.level(person, sid)

    def set_right(self, person, sheet, level):
        sid = self._sid(sheet)
        if sid is None:
            return
        if self.view.owner != self.name:
            self._alert("droit_insuffisant", self.view.sheets[sid].name)
            return
        self._send({"k": "right", "sid": sid, "person": person, "level": level})

    # ---- connexion

    def connection_status(self):
        return "en ligne" if self.net.is_connected(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        self._send({"k": "pres", "sid": sid, "ref": ref})

    def presence(self):
        if not self.net.is_connected(self.name):
            return {}
        out = {}
        for who, (sid, ref) in self.pres.items():
            if who == self.name:
                continue
            sh = self.view.sheets.get(sid)
            if sh is not None:
                out[who] = (sh.name, ref)
        return out

    # ---- conflits

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        c = self.view.conf.get((sid, ref))
        if c is None:
            return None
        return Conflict(c[0][0] if c[0] is not None else None, c[1])

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None or self.consult is not None:
            return
        if (sid, ref) not in self.view.conf:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", self.view.sheets[sid].name, ref)
            return
        self._submit({"t": "resolve", "sid": sid, "ref": ref, "use": bool(use_discarded),
                      "sn": self.view.sheets[sid].name})

    # ---- annulation

    def _guard(self, exp):
        return all(self.view.cell(sid, ref) == cell for sid, ref, cell in exp)

    def can_undo(self):
        return bool(self.undo_s)

    def can_redo(self):
        return bool(self.redo_s)

    def undo(self):
        if self.consult is not None or not self.undo_s:
            return
        rec = self.undo_s[-1]
        if not self._guard(rec["post"]):
            self.undo_s.pop()
            self._alert("annulation_impossible")
            return
        sid = rec["do"].get("sid")
        if sid is not None and not self._can_write(sid):
            self._alert("droit_insuffisant", rec["do"].get("sn"))
            return
        self.undo_s.pop()
        opid = rec["opid"]
        if opid is not None and opid not in self.sent and any(o["id"] == opid for o in self.pending):
            self._settle(opid)
            self._rebuild()
        else:
            self._submit(dict(rec["undo"]))
        rec["opid"] = None
        self.redo_s.append(rec)

    def redo(self):
        if self.consult is not None or not self.redo_s:
            return
        rec = self.redo_s[-1]
        if not self._guard(rec["pre"]):
            self.redo_s.pop()
            self._alert("annulation_impossible")
            return
        sid = rec["do"].get("sid")
        if sid is not None and not self._can_write(sid):
            self._alert("droit_insuffisant", rec["do"].get("sn"))
            return
        self.redo_s.pop()
        rec["opid"] = self._submit(dict(rec["do"]))
        self.undo_s.append(rec)

    # ---- fermeture / réouverture

    def reopen(self):
        self._dead = True
        state = copy.deepcopy({"conf": self.conf, "pending": self.pending, "seq": self.seq,
                               "n": self.n, "tz": self.tz})
        return Client(self.net, self.clock, self.name, self.tz, _state=state)

    # ---- historique

    def history(self, sheet=None):
        sid = self._sid(sheet)
        vs = self.conf.versions.get(sid, []) if sid is not None else []
        z = zone(self.tz)
        out = sorted(vs, key=lambda v: (v.ts, v.id), reverse=True)
        return [Version(v.id, v.author, v.ts.astimezone(z).strftime("%Y-%m-%d %H:%M"), v.kind)
                for v in out]

    def _find_version(self, vid):
        for sid, vs in self.conf.versions.items():
            for v in vs:
                if v.id == vid:
                    return sid, v
        return None, None

    def open_version(self, version_id):
        sid, v = self._find_version(version_id)
        if v is not None:
            self.consult = (sid, v)
            self._cdoc = None

    def close_version(self):
        self.consult = None
        self._cdoc = None

    def restore_version(self, version_id):
        if self.consult is not None:
            return
        sid, v = self._find_version(version_id)
        if v is None:
            return
        sh = self.view.sheets.get(sid)
        if sh is None:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        if v.name != sh.name and self.view.taken(v.name, sid):
            self._alert("nom_existant", v.name)
            return
        do = {"t": "restore", "sid": sid, "name": v.name, "cells": dict(v.cells),
              "vk": "restauration", "sn": sh.name}
        undo = {"t": "restore", "sid": sid, "name": sh.name, "cells": dict(sh.cells),
                "vk": "modification", "sn": v.name}
        self._act(do, undo)

    # ---- CSV

    def export_csv(self):
        sid = self._sid()
        if sid is None:
            return b""
        d = self._doc()
        sh = d.sheets[sid]
        if not sh.cells:
            return b""
        z = zone(self.tz)
        now = self.clock.now()
        width = max(split_ref(r)[0] for r in sh.cells)
        rows = sorted({split_ref(r)[1] for r in sh.cells})
        buf = io.StringIO()
        w = csv.writer(buf)
        for r in rows:
            fields = []
            for c in range(1, width + 1):
                ref = col_name(c) + str(r)
                if ref not in sh.cells:
                    fields.append("")
                    continue
                v = d.value(sid, ref, now)
                if isinstance(v, Err):
                    fields.append(v.code)
                elif isinstance(v, datetime):
                    fields.append(v.astimezone(z).isoformat())
                elif isinstance(v, date):
                    fields.append(v.isoformat())
                else:
                    fields.append(str(norm_num(v)))
            w.writerow(fields)
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        sid = self._writable_sheet(None, None)
        if sid is None:
            return
        text = bytes(data).decode("utf-8", errors="replace")
        if text.startswith("﻿"):
            text = text[1:]
        sn = self.view.sheets[sid].name
        try:
            rows = parse_csv(text)
        except CsvError as e:
            self._alert("csv_invalide", sn, None, e.line)
            return
        changes = []
        for r, row in enumerate(rows, start=1):
            for c, field in enumerate(row, start=1):
                ref = col_name(c) + str(r)
                if field == "":
                    changes.append((ref, None))
                else:
                    changes.append((ref, make_cell(field, self.tz, field.startswith("="))))
        if changes:
            self._edit_cells(sid, changes)
