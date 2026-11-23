"""Classeur collaboratif hors ligne : formules, réseau simulé, fusion serveur, fuseaux."""
import copy
import csv
import io
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"

# ------------------------------------------------------------------ temps / réseau


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
        self.down = set()
        self.queue = []
        self._id = 0

    def register(self, name, node):
        self.nodes[name] = node

    def is_connected(self, name):
        return name not in self.down

    def send(self, src, dst, msg):
        if src in self.down or dst in self.down:
            return None
        self._id += 1
        self.queue.append([self._id, src, dst, copy.deepcopy(msg)])
        return self._id

    def cancel(self, handle):
        for i, m in enumerate(self.queue):
            if m[0] == handle:
                del self.queue[i]
                return True
        return False

    def disconnect(self, name):
        if name in self.down:
            return
        self.down.add(name)
        self.queue = [m for m in self.queue if m[1] != name and m[2] != name]
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_disconnect"):
            node.on_disconnect()
        srv = self.nodes.get("server")
        if srv is not None and name != "server":
            srv.on_client_gone(name)

    def reconnect(self, name):
        if name not in self.down:
            return
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_reconnect"):
            node.on_reconnect()

    def _deliver(self, m):
        node = self.nodes.get(m[2])
        if node is not None:
            node.receive(m[1], m[3])

    def deliver_all(self):
        while self.queue:
            m = self.queue.pop(0)
            self._deliver(m)

    def deliver_from(self, name):
        batch = [m for m in self.queue if m[1] == name]
        for m in batch:
            if m in self.queue:
                self.queue.remove(m)
                self._deliver(m)


# ------------------------------------------------------------------ cellules, dates

_zones = {}


def _zone(name):
    z = _zones.get(name)
    if z is None:
        z = _zones[name] = ZoneInfo(name or "UTC")
    return z


_NUM = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)$")
_DT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:?\d{2})?$")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_REF = re.compile(r"^([A-Z]+)(\d+)$")


class DT:
    def __init__(self, inst, wall, tz):
        self.inst = inst
        self.wall = wall
        self.tz = tz


def _parse_dt(text):
    m = _DT.match(text)
    if not m:
        return None
    y, mo, d, h, mi, s, off = m.groups()
    try:
        wall = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None
    if off is None:
        return wall, None
    if off == "Z":
        return wall, timedelta(0)
    digits = off[1:].replace(":", "")
    hh, mm = int(digits[:2]), int(digits[2:])
    if hh >= 24 or mm >= 60:
        return None
    delta = timedelta(hours=hh, minutes=mm)
    return wall, (delta if off[0] == "+" else -delta)


def make_cell(text, tz, lit=False):
    if text is None or text == "":
        return None
    if lit:
        return (text, True, None)
    zone = None
    if not text.startswith("="):
        p = _parse_dt(text)
        if p is not None and p[1] is None:
            zone = tz
    return (text, False, zone)


def _is_formula(tup):
    return (not tup[1]) and tup[0].startswith("=")


def literal_value(tup):
    text, lit, tz = tup
    if lit:
        return text
    if _NUM.match(text):
        return float(text) if "." in text else int(text)
    p = _parse_dt(text)
    if p is not None:
        wall, off = p
        if off is None:
            inst = wall.replace(tzinfo=_zone(tz)).astimezone(UTC)
            return DT(inst, wall, tz)
        return DT((wall - off).replace(tzinfo=UTC), None, None)
    m = _DATE.match(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return text


def _fmt_dt(dt, tz):
    if dt.wall is not None and dt.tz == tz:
        return dt.wall.strftime("%Y-%m-%d %H:%M")
    return dt.inst.astimezone(_zone(tz)).strftime("%Y-%m-%d %H:%M")


def _colname(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _colnum(s):
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


_coord_cache = {}


def _coords(ref):
    c = _coord_cache.get(ref)
    if c is None:
        m = _REF.match(ref)
        if not m:
            return None
        c = _coord_cache[ref] = (_colnum(m.group(1)), int(m.group(2)))
    return c


def _cellname(col, row):
    return _colname(col) + str(row)


def _norm_ref(ref):
    ref = ref.upper()
    c = _coords(ref)
    if c is None or c[1] < 1:
        return None
    return ref


# ------------------------------------------------------------------ analyseur de formules


class SyntaxErr(Exception):
    pass


class _Err(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


_TOK = re.compile(
    r"(?P<num>\d+\.\d+|\.\d+|\d+)|(?P<id>[^\W\d]\w*)|(?P<q>'[^']*')|(?P<op>[-+*/(),;:!])"
)


def _lex(s):
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
            raise SyntaxErr()
        kind = m.lastgroup
        toks.append((kind, m.group(kind), m.start(kind), m.end(kind)))
        pos = m.end()
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self):
        tok = self.peek()
        if tok is None:
            raise SyntaxErr()
        self.i += 1
        return tok

    def isop(self, o):
        tok = self.peek()
        return tok is not None and tok[0] == "op" and tok[1] == o

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise SyntaxErr()
        return node

    def expr(self):
        node = self.term()
        while self.isop("+") or self.isop("-"):
            op = self.next()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.isop("*") or self.isop("/"):
            op = self.next()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.isop("-"):
            self.next()
            return ("neg", self.unary())
        if self.isop("+"):
            self.next()
            return self.unary()
        return self.atom()

    @staticmethod
    def _ref(val):
        m = _REF.match(val.upper())
        if not m or int(m.group(2)) < 1:
            raise SyntaxErr()
        return _colnum(m.group(1)), int(m.group(2))

    def atom(self):
        kind, val = self.next()[:2]
        if kind == "num":
            return ("num", float(val) if "." in val else int(val))
        if kind == "op" and val == "(":
            node = self.expr()
            if not self.isop(")"):
                raise SyntaxErr()
            self.next()
            return node
        if kind in ("id", "q"):
            sheet = None
            if self.isop("!"):
                self.next()
                sheet = val if kind == "id" else val[1:-1]
                tok = self.next()
                if tok[0] != "id":
                    raise SyntaxErr()
                val = tok[1]
            elif kind == "id" and self.isop("("):
                return self.call(val)
            elif kind == "q":
                raise SyntaxErr()
            col, row = self._ref(val)
            return ("ref", sheet, col, row)
        raise SyntaxErr()

    def call(self, name):
        self.next()  # (
        args = []
        if self.isop(")"):
            self.next()
        else:
            while True:
                args.append(self.arg())
                if self.isop(",") or self.isop(";"):
                    self.next()
                    continue
                if self.isop(")"):
                    self.next()
                    break
                raise SyntaxErr()
        up = name.upper()
        if up == "SOMME":
            if not args:
                raise SyntaxErr()
        elif up == "MAINTENANT":
            if args:
                raise SyntaxErr()
        else:
            raise SyntaxErr()
        return ("call", up, args)

    def arg(self):
        node = self.expr()
        if node[0] == "ref" and self.isop(":"):
            self.next()
            tok = self.next()
            if tok[0] != "id":
                raise SyntaxErr()
            c2, r2 = self._ref(tok[1])
            c1, r1 = node[2], node[3]
            return ("range", node[1], min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2))
        return node


_pcache = {}


def parse_formula(text):
    r = _pcache.get(text)
    if r is None:
        try:
            r = _Parser(_lex(text[1:])).parse()
        except (SyntaxErr, RecursionError):
            r = False
        _pcache[text] = r
    return r


def _refs(ast):
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


def _simple_name(name):
    return re.fullmatch(r"[^\W\d]\w*", name) is not None


def _rewrite(text, old, new):
    body = text[1:]
    try:
        toks = _lex(body)
    except SyntaxErr:
        return text
    out = []
    last = 0
    for i, (kind, val, st, en) in enumerate(toks):
        if kind in ("id", "q") and i + 1 < len(toks) and toks[i + 1][0] == "op" and toks[i + 1][1] == "!":
            nm = val if kind == "id" else val[1:-1]
            if nm.casefold() == old.casefold():
                out.append(body[last:st])
                out.append(new if _simple_name(new) else "'" + new + "'")
                last = en
    out.append(body[last:])
    return "=" + "".join(out)


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _norm(r):
    if isinstance(r, float) and r.is_integer() and abs(r) < 1e15:
        return int(r)
    return r


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
        if isinstance(a, date) and isinstance(b, date):
            return (a - b).days
    raise _Err("#TYPE!")


def _scc(nodes, adj):
    index = {}
    low = {}
    onstack = set()
    stack = []
    res = []
    idx = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = idx
        idx += 1
        stack.append(root)
        onstack.add(root)
        work = [(root, iter(adj[root]))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = idx
                    idx += 1
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(adj[w])))
                    advanced = True
                    break
                elif w in onstack:
                    if index[w] < low[v]:
                        low[v] = index[w]
            if advanced:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                if low[v] < low[u]:
                    low[u] = low[v]
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                res.append(comp)
    return res


def _range_refs(sheet, n):
    c1, r1, c2, r2 = n[2], n[3], n[4], n[5]
    area = (c2 - c1 + 1) * (r2 - r1 + 1)
    out = []
    if area <= len(sheet.cells):
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                ref = _cellname(c, r)
                if ref in sheet.cells:
                    out.append(ref)
    else:
        for ref in sheet.cells:
            co = _coords(ref)
            if co and c1 <= co[0] <= c2 and r1 <= co[1] <= r2:
                out.append(ref)
    return out


class _Ctx:
    def __init__(self, model, res, names, byid, now):
        self.model = model
        self.res = res
        self.names = names
        self.byid = byid
        self.now = now

    def target(self, sid, sheetname):
        if sheetname is None:
            return sid
        t = self.names.get(sheetname.casefold())
        if t is None:
            raise _Err("#REF!")
        return t

    def cell(self, sid, ref):
        key = (sid, ref)
        if key in self.res:
            return self.res[key]
        tup = self.byid[sid].cells.get(ref)
        if tup is None:
            return (None, None)
        return (literal_value(tup), None)

    def ev(self, n, sid):
        k = n[0]
        if k == "num":
            return n[1]
        if k == "ref":
            tsid = self.target(sid, n[1])
            v, e = self.cell(tsid, _cellname(n[2], n[3]))
            if e:
                raise _Err(e)
            return 0 if v is None else v
        if k == "neg":
            v = self.ev(n[1], sid)
            if _isnum(v):
                return _norm(-v)
            raise _Err("#TYPE!")
        if k == "bin":
            a = self.ev(n[2], sid)
            b = self.ev(n[3], sid)
            return _arith(n[1], a, b)
        if k == "call":
            if n[1] == "MAINTENANT":
                return DT(self.now, None, None)
            total = 0
            for arg in n[2]:
                if arg[0] == "range":
                    tsid = self.target(sid, arg[1])
                    for ref in _range_refs(self.byid[tsid], arg):
                        v, e = self.cell(tsid, ref)
                        if e:
                            raise _Err(e)
                        if _isnum(v):
                            total += v
                else:
                    v = self.ev(arg, sid)
                    if _isnum(v):
                        total += v
            return _norm(total)
        raise _Err("#SYNTAXE!")


class Sheet:
    def __init__(self, sid, name, cells=None):
        self.id = sid
        self.name = name
        self.cells = cells if cells is not None else {}


class Model:
    def __init__(self, owner):
        self.owner = owner
        self.sheets = []
        self.rights = {}
        self.conflicts = {}
        self.ver = 0
        self._ev = None

    @classmethod
    def initial(cls, owner):
        m = cls(owner)
        m.sheets.append(Sheet("s0", "Feuille1"))
        m.rights["s0"] = {owner: W} if owner else {}
        return m

    def copy(self):
        m = Model(self.owner)
        m.sheets = [Sheet(s.id, s.name, dict(s.cells)) for s in self.sheets]
        m.rights = {k: dict(v) for k, v in self.rights.items()}
        m.conflicts = dict(self.conflicts)
        return m

    def sheet(self, sid):
        for s in self.sheets:
            if s.id == sid:
                return s
        return None

    def sid_by_name(self, name):
        if name is None:
            return None
        cf = name.casefold()
        for s in self.sheets:
            if s.name.casefold() == cf:
                return s.id
        return None

    def name_taken(self, name, exclude=None):
        cf = name.casefold()
        return any(s.name.casefold() == cf and s.id != exclude for s in self.sheets)

    def level(self, person, sid):
        return self.rights.get(sid, {}).get(person)

    def _rename(self, s, new):
        old = s.name
        s.name = new
        for sh in self.sheets:
            for ref, tup in sh.cells.items():
                if not tup[1] and tup[0].startswith("=") and "!" in tup[0]:
                    t = _rewrite(tup[0], old, new)
                    if t != tup[0]:
                        sh.cells[ref] = (t, False, tup[2])

    def apply(self, op):
        self.ver += 1
        t = op["t"]
        if t == "write":
            s = self.sheet(op["sid"])
            if s is None:
                return
            for ref, tup in op["cells"]:
                if tup is None:
                    s.cells.pop(ref, None)
                else:
                    s.cells[ref] = tup
                self.conflicts.pop((s.id, ref), None)
        elif t == "replace":
            s = self.sheet(op["sid"])
            if s is None:
                return
            s.cells = dict(op["cells"])
            for k in [k for k in self.conflicts if k[0] == s.id]:
                del self.conflicts[k]
            name = op.get("name")
            if name and name != s.name and not self.name_taken(name, s.id):
                self._rename(s, name)
        elif t == "conflict":
            if self.sheet(op["sid"]) is not None:
                self.conflicts[(op["sid"], op["ref"])] = (op["disc"], op["by"])
        elif t == "resolve":
            s = self.sheet(op["sid"])
            c = self.conflicts.get((op["sid"], op["ref"]))
            if s is None or c is None:
                return
            if op["use"]:
                if c[0] is None:
                    s.cells.pop(op["ref"], None)
                else:
                    s.cells[op["ref"]] = c[0]
            del self.conflicts[(op["sid"], op["ref"])]
        elif t == "add_sheet":
            if self.sheet(op["sid"]) is not None or self.name_taken(op["name"]):
                return
            self.sheets.append(Sheet(op["sid"], op["name"]))
            rights = {op["creator"]: W}
            if self.owner:
                rights[self.owner] = W
            self.rights[op["sid"]] = rights
        elif t == "delete_sheet":
            s = self.sheet(op["sid"])
            if s is None or len(self.sheets) <= 1:
                return
            self.sheets.remove(s)
            self.rights.pop(s.id, None)
            for k in [k for k in self.conflicts if k[0] == s.id]:
                del self.conflicts[k]
        elif t == "rename_sheet":
            s = self.sheet(op["sid"])
            if s is None or s.name == op["new"] or self.name_taken(op["new"], s.id):
                return
            self._rename(s, op["new"])
        elif t == "restore_sheet":
            snap = op["snap"]
            if self.sheet(snap["sid"]) is not None or self.name_taken(snap["name"]):
                return
            idx = min(snap["index"], len(self.sheets))
            self.sheets.insert(idx, Sheet(snap["sid"], snap["name"], dict(snap["cells"])))
            self.rights[snap["sid"]] = dict(snap["rights"])
        elif t == "right":
            if self.sheet(op["sid"]) is None:
                return
            r = self.rights.setdefault(op["sid"], {})
            if op["level"] is None:
                r.pop(op["person"], None)
            else:
                r[op["person"]] = op["level"]

    # ---- évaluation
    def results(self, now):
        ev = self._ev
        if ev is not None and ev[0] == self.ver and ev[1] == now:
            return ev[2]
        res = self._evaluate(now)
        self._ev = (self.ver, now, res)
        return res

    def _evaluate(self, now):
        names = {s.name.casefold(): s.id for s in self.sheets}
        byid = {s.id: s for s in self.sheets}
        forms = {}
        for s in self.sheets:
            for ref, tup in s.cells.items():
                if _is_formula(tup):
                    forms[(s.id, ref)] = parse_formula(tup[0])
        adj = {}
        for key, ast in forms.items():
            deps = {}
            if ast is not False:
                for n in _refs(ast):
                    tsid = key[0] if n[1] is None else names.get(n[1].casefold())
                    if tsid is None:
                        continue
                    if n[0] == "ref":
                        k = (tsid, _cellname(n[2], n[3]))
                        if k in forms:
                            deps[k] = True
                    else:
                        for ref in _range_refs(byid[tsid], n):
                            k = (tsid, ref)
                            if k in forms:
                                deps[k] = True
            adj[key] = list(deps)
        res = {}
        ctx = _Ctx(self, res, names, byid, now)
        for comp in _scc(list(forms), adj):
            cyc = len(comp) > 1 or comp[0] in adj[comp[0]]
            for key in comp:
                if cyc:
                    res[key] = (None, "#CIRC!")
                    continue
                ast = forms[key]
                if ast is False:
                    res[key] = (None, "#SYNTAXE!")
                    continue
                try:
                    res[key] = (ctx.ev(ast, key[0]), None)
                except _Err as e:
                    res[key] = (None, e.code)
                except RecursionError:
                    res[key] = (None, "#SYNTAXE!")
        return res

    def cell_result(self, sid, ref, now):
        s = self.sheet(sid)
        if s is None:
            return (None, None)
        tup = s.cells.get(ref)
        if tup is None:
            return (None, None)
        if _is_formula(tup):
            return self.results(now)[(sid, ref)]
        return (literal_value(tup), None)


def replay(owner, log, upto):
    m = Model.initial(owner)
    for e in log:
        if e["seq"] > upto:
            break
        for op in e["ops"]:
            m.apply(op)
    return m


# ------------------------------------------------------------------ serveur


class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.model = Model.initial(owner)
        self.log = []
        self.online = set()
        self.presence = {}
        self.seen = {}
        self.touched = {}
        net.register("server", self)

    def _send(self, dst, msg):
        self.net.send("server", dst, msg)

    def _broadcast(self, msg):
        for c in sorted(self.online):
            self._send(c, msg)

    def on_client_gone(self, name):
        self.online.discard(name)
        if self.presence.pop(name, None) is not None:
            self._broadcast(("presence", name, None))

    def receive(self, src, msg):
        t = msg[0]
        if t == "hello":
            self.online.add(src)
            last = msg[2]
            pres = dict(self.presence) if msg[3] else None
            self._send(src, ("welcome", self.owner, self.log[last:], pres))
        elif t == "op":
            self._on_op(src, msg[1])
        elif t == "right":
            self._on_right(src, msg[1], msg[2], msg[3])
        elif t == "select":
            self.presence[src] = (msg[1], msg[2])
            self._broadcast(("presence", src, (msg[1], msg[2])))

    def _commit(self, author, ops, kind, version, sheets, origin, ts=None):
        e = {
            "seq": len(self.log) + 1,
            "author": author,
            "ts": ts or self.clock.now(),
            "kind": kind,
            "version": version,
            "sheets": sheets,
            "ops": ops,
            "origin": origin,
        }
        self.log.append(e)
        for op in ops:
            self.model.apply(op)
        self._broadcast(("entry", e))
        return e

    def _on_right(self, client, sid, person, level):
        m = self.model
        if client != self.owner or person == self.owner or m.sheet(sid) is None:
            return
        if level not in (W, R, None):
            return
        if m.level(person, sid) == level:
            return
        self._commit(client, [{"t": "right", "sid": sid, "person": person, "level": level}],
                     "droit", False, [sid], None)

    def _on_op(self, client, op):
        key = (client, op["id"])
        if key in self.seen:
            r = self.seen[key]
            if r is not None:
                self._send(client, r)
            return
        status = self._process(client, op)
        msg = None
        if status != "applied":
            msg = ("result", op["id"], status)
            self._send(client, msg)
        self.seen[key] = msg

    def _process(self, client, op):
        m = self.model
        t = op["t"]
        origin = (client, op["id"])
        if t == "add_sheet":
            if m.sheet(op["sid"]) is not None:
                return "noop"
            if m.name_taken(op["name"]):
                return "nom_existant"
            self._commit(client, [{"t": "add_sheet", "sid": op["sid"], "name": op["name"],
                                   "creator": client}], "feuille", False, [op["sid"]], origin)
            return "applied"
        if t == "restore_sheet":
            snap = op["snap"]
            if m.sheet(snap["sid"]) is not None:
                return "noop"
            if m.name_taken(snap["name"]):
                return "nom_existant"
            if snap["rights"].get(client) != W:
                return "droit"
            self._commit(client, [{"t": "restore_sheet", "snap": snap}], "feuille", False,
                         [snap["sid"]], origin)
            return "applied"
        sid = op["sid"]
        s = m.sheet(sid)
        if t == "delete_sheet" and s is None:
            return "noop"
        if s is None:
            return "feuille_supprimee"
        if m.level(client, sid) != W:
            return "droit"
        if t == "write":
            applied = []
            confl = []
            for ref, tup in op["cells"]:
                cur = s.cells.get(ref)
                if cur == tup:
                    continue
                if any(a != client and sq > op["base"] for sq, a in self.touched.get((sid, ref), ())):
                    confl.append({"t": "conflict", "sid": sid, "ref": ref, "disc": tup, "by": client})
                else:
                    applied.append((ref, tup))
            if not applied and not confl:
                return "noop"
            ops = []
            if applied:
                ops.append({"t": "write", "sid": sid, "cells": applied})
            ops.extend(confl)
            e = self._commit(client, ops, op.get("kind", "modification") if applied else "conflit",
                             bool(applied), [sid], origin, op["ts"] if applied else None)
            for ref, _ in applied:
                self.touched.setdefault((sid, ref), []).append((e["seq"], client))
            return "applied"
        if t == "resolve":
            ref = op["ref"]
            c = m.conflicts.get((sid, ref))
            if c is None:
                return "noop"
            changes = bool(op["use"]) and c[0] != s.cells.get(ref)
            e = self._commit(client, [{"t": "resolve", "sid": sid, "ref": ref, "use": op["use"]}],
                             "modification", changes, [sid], origin)
            if changes:
                self.touched.setdefault((sid, ref), []).append((e["seq"], client))
            return "applied"
        if t == "delete_sheet":
            if len(m.sheets) <= 1:
                return "derniere"
            self._commit(client, [{"t": "delete_sheet", "sid": sid}], "feuille", False, [sid], origin)
            return "applied"
        if t == "rename_sheet":
            if s.name == op["new"]:
                return "noop"
            if m.name_taken(op["new"], sid):
                return "nom_existant"
            self._commit(client, [{"t": "rename_sheet", "sid": sid, "new": op["new"]}], "feuille",
                         False, [sid], origin)
            return "applied"
        if t == "replace":
            if s.name == op["name"] and s.cells == dict(op["cells"]):
                return "noop"
            self._commit(client, [{"t": "replace", "sid": sid, "name": op["name"],
                                   "cells": op["cells"]}], op.get("kind", "modification"), True,
                         [sid], origin, op["ts"])
            return "applied"
        return "noop"


# ------------------------------------------------------------------ client


@dataclass
class Alert:
    kind: str
    sheet: object = None
    cell: object = None
    line: object = None


@dataclass
class Version:
    id: int
    author: str
    timestamp: str
    kind: str


@dataclass
class Conflict:
    discarded: object
    discarded_by: str


class _CsvErr(Exception):
    def __init__(self, line):
        Exception.__init__(self, line)
        self.line = line


def _parse_csv(text):
    rows = []
    row = []
    field = []
    quoted = False
    inq = False
    qline = 0
    line = 1
    i = 0
    n = len(text)
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
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
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
        raise _CsvErr(qline)
    if field or row or quoted:
        row.append("".join(field))
        rows.append(row)
    return rows


class Client:
    def __init__(self, net, clock, name, tz="UTC", _storage=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self._storage = _storage if _storage is not None else {}
        st = self._storage.get("state")
        if st:
            st = copy.deepcopy(st)
            self.owner = st["owner"]
            self.base = st["base"].copy()
            self.log = st["log"]
            self.last_seq = st["last_seq"]
            self.pending = st["pending"]
            self._n = st["n"]
        else:
            self.owner = None
            self.base = Model.initial(None)
            self.log = []
            self.last_seq = 0
            self.pending = []
            self._n = 0
        self._view = None
        self._viewing = None
        self.active = None
        self._undo = []
        self._redo = []
        self._alerts = []
        self._presence = {}
        self._handles = {}
        self._buf = {}
        self._dead = False
        net.register(name, self)
        self.online = net.is_connected(name)
        if self.online:
            self._hello(False)

    # ---- réseau
    def _hello(self, snapshot):
        self.net.send(self.name, "server", ("hello", self.name, self.last_seq, snapshot))
        for op in self.pending:
            self._send_op(op)

    def _send_op(self, op):
        if self.online:
            self._handles[op["id"]] = self.net.send(self.name, "server", ("op", op))

    def on_disconnect(self):
        self.online = False
        self._handles = {}

    def on_reconnect(self):
        if self._dead:
            return
        self.online = True
        self._hello(True)

    def receive(self, src, msg):
        if self._dead:
            return
        t = msg[0]
        if t == "welcome":
            owner, entries, pres = msg[1], msg[2], msg[3]
            if self.owner != owner and self.last_seq == 0:
                self.owner = owner
                self.base = Model.initial(owner)
                self._view = None
            if pres is not None:
                self._presence = {k: tuple(v) for k, v in pres.items()}
            for e in entries:
                self._on_entry(e)
        elif t == "entry":
            self._on_entry(msg[1])
        elif t == "result":
            self._on_result(msg[1], msg[2])
        elif t == "presence":
            if msg[2] is None:
                self._presence.pop(msg[1], None)
            else:
                self._presence[msg[1]] = tuple(msg[2])

    def _take_pending(self, opid):
        for i, o in enumerate(self.pending):
            if o["id"] == opid:
                del self.pending[i]
                self._handles.pop(opid, None)
                self._view = None
                return o
        return None

    def _on_entry(self, e):
        if e["seq"] <= self.last_seq:
            return
        if e["seq"] != self.last_seq + 1:
            self._buf[e["seq"]] = e
            return
        self._apply_entry(e)
        while self.last_seq + 1 in self._buf:
            self._apply_entry(self._buf.pop(self.last_seq + 1))

    def _apply_entry(self, e):
        for op in e["ops"]:
            self.base.apply(op)
        self.log.append(e)
        self.last_seq = e["seq"]
        origin = e.get("origin")
        if origin and origin[0] == self.name:
            self._take_pending(origin[1])
        self._view = None

    def _on_result(self, opid, status):
        op = self._take_pending(opid)
        if op is None:
            return
        sname = op.get("sname")
        if status == "droit":
            cell = op["cells"][0][0] if op.get("cells") else op.get("ref")
            self._alert("modification_rejetee", sname, cell)
        elif status == "feuille_supprimee":
            self._alert("feuille_supprimee", sname)
        elif status == "nom_existant":
            self._alert("nom_existant", op.get("name") or op.get("new"))

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def alerts(self):
        return list(self._alerts)

    # ---- modèle
    def _v(self):
        if self._view is None:
            v = self.base.copy()
            for op in self.pending:
                v.apply(op)
            self._view = v
        return self._view

    def _m(self):
        return self._viewing[1] if self._viewing is not None else self._v()

    def _active_in(self, m):
        if self.active is not None and m.sheet(self.active) is not None:
            return self.active
        return m.sheets[0].id

    def _sid_in(self, m, sheet):
        if sheet is None:
            return self._active_in(m)
        return m.sid_by_name(sheet)

    def _submit(self, op):
        self._n += 1
        op = dict(op)
        op["id"] = "%s#%d" % (self.name, self._n)
        op["base"] = self.last_seq
        op["ts"] = self.clock.now()
        self._v().apply(op)
        self.pending.append(op)
        self._send_op(op)
        return op

    def _push_undo(self, item):
        self._undo.append(item)
        self._redo = []

    def _retract(self, opid):
        idx = None
        for i, o in enumerate(self.pending):
            if o["id"] == opid:
                idx = i
        if idx is None:
            return False
        h = self._handles.get(opid)
        if h is not None and not self.net.cancel(h):
            return False
        del self.pending[idx]
        self._handles.pop(opid, None)
        self._view = None
        return True

    # ---- lecture
    def content(self, ref, sheet=None):
        m = self._m()
        sid = self._sid_in(m, sheet)
        if sid is None:
            return None
        tup = m.sheet(sid).cells.get(ref.upper())
        return tup[0] if tup else None

    def _res(self, ref, sheet):
        m = self._m()
        sid = self._sid_in(m, sheet)
        if sid is None:
            return (None, None)
        return m.cell_result(sid, ref.upper(), self.clock.now())

    def _disp(self, v):
        if isinstance(v, DT):
            return _fmt_dt(v, self.tz)
        if isinstance(v, date):
            return v.isoformat()
        return v

    def value(self, ref, sheet=None):
        v, e = self._res(ref, sheet)
        if e:
            return e
        return self._disp(v)

    def error(self, ref, sheet=None):
        return self._res(ref, sheet)[1]

    def set_timezone(self, tz):
        self.tz = tz

    def sheets(self):
        return [s.name for s in self._m().sheets]

    def activate(self, name):
        sid = self._v().sid_by_name(name)
        if sid is not None:
            self.active = sid

    def right(self, person, sheet):
        m = self._m()
        sid = m.sid_by_name(sheet)
        if sid is None:
            return None
        return m.level(person, sid)

    def connection_status(self):
        return "en ligne" if self.online else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def conflict(self, ref, sheet=None):
        m = self._m()
        sid = self._sid_in(m, sheet)
        c = m.conflicts.get((sid, ref.upper()))
        if c is None:
            return None
        return Conflict(c[0][0] if c[0] else None, c[1])

    # ---- présence
    def select(self, ref, sheet=None):
        if not self.online:
            return
        m = self._v()
        sid = self._sid_in(m, sheet)
        s = m.sheet(sid) if sid is not None else None
        name = s.name if s is not None else sheet
        self.net.send(self.name, "server", ("select", name, ref.upper()))

    def presence(self):
        if not self.online:
            return {}
        return {k: v for k, v in self._presence.items() if k != self.name}

    # ---- écriture
    def _writable(self, sheet, cell=None):
        """Retourne (sid, feuille) si l'écriture est permise, sinon None (alerte levée)."""
        if self._viewing is not None:
            return None
        v = self._v()
        sid = self._sid_in(v, sheet)
        if sid is None:
            return None
        s = v.sheet(sid)
        if v.level(self.name, sid) != W:
            self._alert("droit_insuffisant", s.name, cell)
            return None
        return sid, s

    def _write(self, sid, cells, kind="modification"):
        v = self._v()
        s = v.sheet(sid)
        changes = [(r, t) for r, t in cells if s.cells.get(r) != t]
        if not changes:
            return
        old = [(r, s.cells.get(r)) for r, _ in changes]
        fwd = {"t": "write", "sid": sid, "cells": changes, "kind": kind, "sname": s.name}
        inv = {"t": "write", "sid": sid, "cells": old, "kind": kind, "sname": s.name}
        op = self._submit(fwd)
        self._push_undo({"sid": sid, "sname": s.name, "fwd": fwd, "inv": inv, "live": op["id"]})

    def set_cell(self, ref, text, sheet=None):
        r = _norm_ref(ref)
        if r is None:
            return
        got = self._writable(sheet, r)
        if got is None:
            return
        self._write(got[0], [(r, make_cell(text, self.tz))])

    def clear(self, ref, sheet=None):
        r = _norm_ref(ref)
        if r is None:
            return
        got = self._writable(sheet, r)
        if got is None:
            return
        self._write(got[0], [(r, None)])

    def import_csv(self, data):
        got = self._writable(None)
        if got is None:
            return
        sid, s = got
        text = bytes(data).decode("utf-8-sig")
        try:
            rows = _parse_csv(text)
        except _CsvErr as e:
            self._alert("csv_invalide", s.name, None, e.line)
            return
        cells = []
        for ri, row in enumerate(rows):
            for ci, field in enumerate(row):
                cells.append((_cellname(ci + 1, ri + 1),
                              make_cell(field, self.tz, lit=field.startswith("="))))
        self._write(sid, cells)

    def export_csv(self):
        m = self._m()
        s = m.sheet(self._active_in(m))
        now = self.clock.now()
        vals = {}
        maxc = 0
        for ref in s.cells:
            c, r = _coords(ref)
            v, e = m.cell_result(s.id, ref, now)
            vals[(r, c)] = self._export_text(v, e)
            maxc = max(maxc, c)
        out = io.StringIO(newline="")
        w = csv.writer(out, lineterminator="\n")
        for r in sorted({k[0] for k in vals}):
            w.writerow([vals.get((r, c), "") for c in range(1, maxc + 1)])
        return out.getvalue().encode("utf-8")

    def _export_text(self, v, e):
        if e:
            return e
        if v is None:
            return ""
        if isinstance(v, DT):
            return v.inst.astimezone(_zone(self.tz)).isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
        return str(v)

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        r = _norm_ref(ref)
        if r is None:
            return
        got = self._writable(sheet, r)
        if got is None:
            return
        sid, s = got
        if (sid, r) not in self._v().conflicts:
            return
        self._submit({"t": "resolve", "sid": sid, "ref": r, "use": bool(use_discarded),
                      "sname": s.name})

    def set_right(self, person, sheet, level):
        if self._viewing is not None or not self.online:
            return
        v = self._v()
        if self.owner is None or self.name != self.owner or person == self.owner:
            return
        sid = v.sid_by_name(sheet)
        if sid is None or v.level(person, sid) == level:
            return
        self.net.send(self.name, "server", ("right", sid, person, level))

    def add_sheet(self, name):
        if self._viewing is not None or not name:
            return
        v = self._v()
        if v.name_taken(name):
            self._alert("nom_existant", name)
            return
        sid = uuid.uuid4().hex[:8]
        fwd = {"t": "add_sheet", "sid": sid, "name": name, "creator": self.name, "sname": name}
        op = self._submit(fwd)
        self._push_undo({"sid": sid, "sname": name, "fwd": fwd,
                         "inv": {"t": "delete_sheet", "sid": sid, "sname": name}, "live": op["id"]})

    def delete_sheet(self, name):
        if self._viewing is not None:
            return
        v = self._v()
        sid = v.sid_by_name(name)
        if sid is None:
            return
        s = v.sheet(sid)
        if v.level(self.name, sid) != W:
            self._alert("droit_insuffisant", s.name)
            return
        if len(v.sheets) <= 1:
            return
        snap = {"sid": sid, "name": s.name, "cells": list(s.cells.items()),
                "rights": dict(v.rights.get(sid, {})), "index": v.sheets.index(s)}
        fwd = {"t": "delete_sheet", "sid": sid, "sname": s.name}
        op = self._submit(fwd)
        self._push_undo({"sid": sid, "sname": s.name, "fwd": fwd,
                         "inv": {"t": "restore_sheet", "snap": snap, "sname": s.name},
                         "live": op["id"]})

    def rename_sheet(self, old, new):
        if self._viewing is not None:
            return
        v = self._v()
        sid = v.sid_by_name(old)
        if sid is None:
            return
        s = v.sheet(sid)
        if v.level(self.name, sid) != W:
            self._alert("droit_insuffisant", s.name)
            return
        if not new or new == s.name:
            return
        if v.name_taken(new, sid):
            self._alert("nom_existant", new)
            return
        fwd = {"t": "rename_sheet", "sid": sid, "new": new, "sname": s.name}
        inv = {"t": "rename_sheet", "sid": sid, "new": s.name, "sname": new}
        op = self._submit(fwd)
        self._push_undo({"sid": sid, "sname": new, "fwd": fwd, "inv": inv, "live": op["id"]})

    # ---- annulation
    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def _check(self, item):
        v = self._v()
        fwd = item["fwd"]
        t = fwd["t"]
        sid = item["sid"]
        s = v.sheet(sid)
        if t == "delete_sheet":
            if s is not None or v.name_taken(item["inv"]["snap"]["name"]):
                return ("impossible", None)
            return None
        if s is None:
            return ("impossible", None)
        if v.level(self.name, sid) != W:
            return ("droit", None)
        if t == "write":
            for r, tup in fwd["cells"]:
                if s.cells.get(r) != tup:
                    return ("impossible", r)
        elif t == "replace":
            if s.cells != dict(fwd["cells"]):
                return ("impossible", None)
        elif t == "rename_sheet":
            if s.name != fwd["new"] or v.name_taken(item["inv"]["new"], sid):
                return ("impossible", None)
        return None

    def undo(self):
        if self._viewing is not None or not self._undo:
            return
        item = self._undo.pop()
        r = self._check(item)
        if r is not None:
            kind = "droit_insuffisant" if r[0] == "droit" else "annulation_impossible"
            self._alert(kind, item["sname"], r[1])
            return
        if self._retract(item["live"]):
            item["live"] = None
        else:
            self._submit(item["inv"])
        self._redo.append(item)

    def redo(self):
        if self._viewing is not None or not self._redo:
            return
        item = self._redo.pop()
        v = self._v()
        fwd = item["fwd"]
        t = fwd["t"]
        if t == "add_sheet":
            if v.name_taken(fwd["name"]):
                self._alert("nom_existant", fwd["name"])
                return
        else:
            s = v.sheet(item["sid"])
            if s is None:
                return
            if v.level(self.name, item["sid"]) != W:
                self._alert("droit_insuffisant", s.name)
                return
        op = self._submit(fwd)
        item["live"] = op["id"]
        self._undo.append(item)

    # ---- historique
    def history(self, sheet=None):
        v = self._v()
        sid = self._sid_in(v, sheet)
        if sid is None:
            return []
        z = _zone(self.tz)
        es = [e for e in self.log if e["version"] and sid in e["sheets"]]
        es.sort(key=lambda e: (e["ts"], e["seq"]), reverse=True)
        return [Version(e["seq"], e["author"], e["ts"].astimezone(z).strftime("%Y-%m-%d %H:%M"),
                        e["kind"]) for e in es]

    def open_version(self, version_id):
        if not any(e["seq"] == version_id for e in self.log):
            return
        self._viewing = (version_id, replay(self.owner, self.log, version_id))

    def close_version(self):
        self._viewing = None

    def restore_version(self, version_id):
        entry = None
        for e in self.log:
            if e["seq"] == version_id and e["version"]:
                entry = e
        if entry is None:
            return
        self._viewing = None
        v = self._v()
        sid = entry["sheets"][0]
        s = v.sheet(sid)
        if s is None:
            return
        if v.level(self.name, sid) != W:
            self._alert("droit_insuffisant", s.name)
            return
        snap = replay(self.owner, self.log, version_id).sheet(sid)
        if snap is None:
            return
        if snap.name == s.name and snap.cells == s.cells:
            return
        fwd = {"t": "replace", "sid": sid, "name": snap.name, "cells": list(snap.cells.items()),
               "kind": "restauration", "sname": s.name}
        inv = {"t": "replace", "sid": sid, "name": s.name, "cells": list(s.cells.items()),
               "kind": "modification", "sname": snap.name}
        op = self._submit(fwd)
        self._push_undo({"sid": sid, "sname": snap.name, "fwd": fwd, "inv": inv, "live": op["id"]})

    # ---- stockage
    def _save(self):
        self._storage["state"] = copy.deepcopy({
            "owner": self.owner, "base": self.base.copy(), "log": self.log,
            "last_seq": self.last_seq, "pending": self.pending, "n": self._n,
        })

    def reopen(self):
        self._save()
        self._dead = True
        return Client(self.net, self.clock, self.name, tz=self.tz, _storage=self._storage)
