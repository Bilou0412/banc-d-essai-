"""Classeur collaboratif hors ligne : formules, copies locales, réseau simulé, fuseaux."""
import copy
import csv
import io
import re
from collections import deque
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"
FMT = "%Y-%m-%d %H:%M"

_Z = {}


def zone(name):
    z = _Z.get(name)
    if z is None:
        z = _Z[name] = ZoneInfo(name)
    return z


# ------------------------------------------------------------------ temps et réseau

class Clock:
    def __init__(self, start):
        self._t = start.astimezone(UTC)

    def now(self):
        return self._t

    def advance(self, delta):
        self._t = self._t + delta


class Msg:
    __slots__ = ("src", "dst", "payload", "state")

    def __init__(self, src, dst, payload):
        self.src = src
        self.dst = dst
        self.payload = payload
        self.state = "flight"


class Network:
    def __init__(self):
        self.q = deque()
        self.nodes = {}
        self.down = set()

    def register(self, name, node):
        self.nodes[name] = node

    def is_up(self, name):
        return name not in self.down

    def send(self, src, dst, payload):
        m = Msg(src, dst, copy.deepcopy(payload))
        if src in self.down or dst in self.down:
            m.state = "dropped"
            return m
        self.q.append(m)
        return m

    def retract(self, m):
        if m.state == "delivered":
            return False
        m.state = "cancelled"
        return True

    def _deliver(self, m):
        if m.state != "flight":
            return
        if m.src in self.down or m.dst in self.down:
            m.state = "dropped"
            return
        m.state = "delivered"
        node = self.nodes.get(m.dst)
        if node is not None:
            node.receive(m.src, m.payload)

    def deliver_all(self):
        while self.q:
            self._deliver(self.q.popleft())

    def deliver_from(self, name):
        mine = [m for m in self.q if m.src == name]
        self.q = deque(m for m in self.q if m.src != name)
        for m in mine:
            self._deliver(m)

    def disconnect(self, name):
        if name in self.down:
            return
        self.down.add(name)
        for node in list(self.nodes.values()):
            node.peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None:
            node.link_up()


# ------------------------------------------------------------------ références, analyseur

_REF = re.compile(r"^([A-Za-z]{1,3})(\d+)$")


def col_num(s):
    n = 0
    for ch in s.upper():
        n = n * 26 + ord(ch) - 64
    return n


def col_name(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def norm_ref(ref):
    if not isinstance(ref, str):
        return None
    m = _REF.match(ref.strip())
    if not m or int(m.group(2)) < 1:
        return None
    return m.group(1).upper() + str(int(m.group(2)))


def split_ref(ref):
    m = _REF.match(ref)
    return col_num(m.group(1)), int(m.group(2))


class SyntaxErr(Exception):
    pass


_TOK = re.compile(r"""\s*(?:
    (?P<num>\d+(?:\.\d+)?)(?![\w.])
  | (?P<ref>(?:(?P<sh>'(?:[^']|'')+'|[^\W\d]\w*)!)?\$?(?P<c1>[A-Za-z]{1,3})\$?(?P<r1>\d+)(?::\$?(?P<c2>[A-Za-z]{1,3})\$?(?P<r2>\d+))?)(?![\w(!])
  | (?P<fn>[^\W\d]\w*)(?=\()
  | (?P<op>[-+*/();,])
)""", re.X)


def tokenize(body):
    toks = []
    pos = 0
    while True:
        m = _TOK.match(body, pos)
        if not m:
            if body[pos:].strip() == "":
                break
            raise SyntaxErr()
        toks.append(m)
        pos = m.end()
    return toks


def _unq(raw):
    if raw.startswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw


def _quote(name):
    if re.fullmatch(r"[^\W\d]\w*", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _parse(text):
    toks = tokenize(text[1:])
    if not toks:
        raise SyntaxErr()
    pos = 0

    def peek_op():
        if pos < len(toks):
            return toks[pos].group("op")
        return None

    def expr():
        nonlocal pos
        node = term()
        while peek_op() in ("+", "-"):
            op = peek_op()
            pos += 1
            node = ("bin", op, node, term())
        return node

    def term():
        nonlocal pos
        node = unary()
        while peek_op() in ("*", "/"):
            op = peek_op()
            pos += 1
            node = ("bin", op, node, unary())
        return node

    def unary():
        nonlocal pos
        o = peek_op()
        if o == "-":
            pos += 1
            return ("neg", unary())
        if o == "+":
            pos += 1
            return unary()
        return primary()

    def primary():
        nonlocal pos
        if pos >= len(toks):
            raise SyntaxErr()
        m = toks[pos]
        if m.group("num") is not None:
            pos += 1
            t = m.group("num")
            return ("num", float(t) if "." in t else int(t))
        if m.group("ref") is not None:
            pos += 1
            sh = m.group("sh")
            sh = _unq(sh) if sh else None
            c1 = col_num(m.group("c1"))
            r1 = int(m.group("r1"))
            if m.group("c2"):
                return ("range", sh, (c1, r1), (col_num(m.group("c2")), int(m.group("r2"))))
            return ("ref", sh, (c1, r1))
        if m.group("fn") is not None:
            name = m.group("fn").upper()
            if name not in ("SOMME", "MAINTENANT"):
                raise SyntaxErr()
            pos += 1
            if peek_op() != "(":
                raise SyntaxErr()
            pos += 1
            args = []
            if peek_op() == ")":
                pos += 1
            else:
                while True:
                    args.append(expr())
                    o = peek_op()
                    if o in (",", ";"):
                        pos += 1
                        continue
                    if o == ")":
                        pos += 1
                        break
                    raise SyntaxErr()
            if name == "MAINTENANT" and args:
                raise SyntaxErr()
            if name == "SOMME" and not args:
                raise SyntaxErr()
            return ("call", name, args)
        if m.group("op") == "(":
            pos += 1
            e = expr()
            if peek_op() != ")":
                raise SyntaxErr()
            pos += 1
            return e
        raise SyntaxErr()

    ast = expr()
    if pos != len(toks):
        raise SyntaxErr()
    return ast


_AST = {}


def parse(text):
    if text in _AST:
        return _AST[text]
    try:
        a = _parse(text)
    except SyntaxErr:
        a = None
    _AST[text] = a
    return a


def rewrite_formula(text, old, new):
    body = text[1:]
    try:
        toks = tokenize(body)
    except SyntaxErr:
        return text
    pieces = []
    pos = 0
    ocf = old.casefold()
    for m in toks:
        if m.group("ref") is not None and m.group("sh"):
            if _unq(m.group("sh")).casefold() == ocf:
                pieces.append(body[pos:m.start("sh")])
                pieces.append(_quote(new))
                pos = m.end("sh")
    pieces.append(body[pos:])
    return "=" + "".join(pieces)


# ------------------------------------------------------------------ valeurs

class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


class EvalErr(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


class DT:
    __slots__ = ("utc", "wall", "tz")

    def __init__(self, utc, wall, tz):
        self.utc = utc
        self.wall = wall
        self.tz = tz

    def fmt(self, tz):
        if self.wall is not None and self.tz == tz:
            return self.wall.strftime(FMT)
        return self.utc.astimezone(zone(tz)).strftime(FMT)


_NUM = re.compile(r"[+-]?\d+(\.\d+)?")
_INT = re.compile(r"[+-]?\d+")
_DT = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:?\d{2})?")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def is_naive_dt(text):
    m = _DT.fullmatch(text)
    return bool(m) and not m.group(7)


def literal_value(cv):
    text, lit, tz = cv
    if _NUM.fullmatch(text):
        return int(text) if _INT.fullmatch(text) else float(text)
    m = _DT.fullmatch(text)
    if m:
        try:
            wall = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
        except ValueError:
            return text
        off = m.group(7)
        if off:
            if off == "Z":
                delta = timedelta(0)
            else:
                mo = re.match(r"([+-])(\d{2}):?(\d{2})", off)
                delta = timedelta(hours=int(mo.group(2)), minutes=int(mo.group(3)))
                if mo.group(1) == "-":
                    delta = -delta
            return DT(wall.replace(tzinfo=timezone(delta)).astimezone(UTC), None, None)
        tzn = tz or "UTC"
        return DT(wall.replace(tzinfo=zone(tzn)).astimezone(UTC), wall, tzn)
    m = _DATE.fullmatch(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return text
    return text


def norm(x):
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        return int(x)
    return x


def num(v):
    if v is None:
        return 0
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EvalErr("#TYPE!")
    return v


# ------------------------------------------------------------------ état du classeur

class Sheet:
    __slots__ = ("id", "name", "cells", "meta", "conf", "rights")

    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.cells = {}
        self.meta = {}
        self.conf = {}
        self.rights = {}

    def copy(self):
        n = Sheet(self.id, self.name)
        n.cells = dict(self.cells)
        n.meta = dict(self.meta)
        n.conf = dict(self.conf)
        n.rights = dict(self.rights)
        return n


class State:
    def __init__(self):
        self.owner = None
        self.sheets = {}
        self.trash = {}

    def copy(self):
        n = State()
        n.owner = self.owner
        n.sheets = {k: v.copy() for k, v in self.sheets.items()}
        n.trash = dict(self.trash)
        return n

    def sid_by_name(self, name):
        if name is None:
            return None
        for sid, sh in self.sheets.items():
            if sh.name == name:
                return sid
        cf = name.casefold()
        for sid, sh in self.sheets.items():
            if sh.name.casefold() == cf:
                return sid
        return None

    def clash(self, name, except_sid):
        cf = name.casefold()
        return any(sh.name.casefold() == cf and sid != except_sid for sid, sh in self.sheets.items())


def can_write(st, person, sh):
    return person == st.owner or sh.rights.get(person) == W


def _rename(st, sid, new):
    sh = st.sheets[sid]
    old = sh.name
    sh.name = new
    for s in st.sheets.values():
        for r, cv in list(s.cells.items()):
            t = cv[0]
            if not cv[1] and t.startswith("="):
                nt = rewrite_formula(t, old, new)
                if nt != t:
                    s.cells[r] = (nt, False, None)


def apply_entry(st, e):
    k = e["kind"]
    if k == "cells":
        sh = st.sheets.get(e["sid"])
        if sh is None:
            return
        seq = e.get("seq", 0)
        au = e.get("author")
        for r, cv in e["set"].items():
            if cv is None:
                sh.cells.pop(r, None)
            else:
                sh.cells[r] = cv
            sh.meta[r] = (seq, au)
        for r, c in e["conf"].items():
            if c is None:
                sh.conf.pop(r, None)
            else:
                sh.conf[r] = c
        if e.get("name"):
            _rename(st, e["sid"], e["name"])
    elif k == "init":
        st.owner = e["owner"]
        sh = Sheet(e["sid"], e["name"])
        sh.rights = {e["owner"]: W}
        st.sheets[e["sid"]] = sh
    elif k == "add_sheet":
        sh = Sheet(e["sid"], e["name"])
        sh.rights = {st.owner: W, e["creator"]: W}
        st.sheets[e["sid"]] = sh
    elif k == "delete_sheet":
        sid = e["sid"]
        if sid in st.sheets:
            idx = list(st.sheets).index(sid)
            st.trash[sid] = (st.sheets.pop(sid), idx)
    elif k == "undelete":
        tr = st.trash.pop(e["sid"], None)
        if tr is not None:
            items = list(st.sheets.items())
            items.insert(min(tr[1], len(items)), (e["sid"], tr[0]))
            st.sheets = dict(items)
    elif k == "rename":
        if e["sid"] in st.sheets:
            _rename(st, e["sid"], e["name"])
    elif k == "rights":
        sh = st.sheets.get(e["sid"])
        if sh is not None:
            if e["level"] is None:
                sh.rights.pop(e["person"], None)
            else:
                sh.rights[e["person"]] = e["level"]


def decide(st, op, author, strict):
    """Décide du sort d'une opération sur un état ; rend une entrée (effets + statut)."""
    k = op["k"]
    e = {"kind": "ack", "status": "ok", "version": False}
    if k == "add":
        name = op["name"]
        if st.clash(name, None):
            e["status"] = "nom_existant"
            e["sname"] = name
            return e
        e.update(kind="add_sheet", sid=op["sid"], name=name, creator=author)
        return e
    sid = op["sid"]
    if k == "rights":
        sh = st.sheets.get(sid)
        if sh is None or author != st.owner or sh.rights.get(op["person"]) == op["level"]:
            return e
        e.update(kind="rights", sid=sid, person=op["person"], level=op["level"])
        return e
    cell = next(iter(op.get("cells") or ()), op.get("ref"))
    if k == "undelete":
        tr = st.trash.get(sid)
        if tr is None:
            e["status"] = "sheet_gone"
            e["sname"] = op.get("sname")
            return e
        sh = tr[0]
        e["sname"] = sh.name
        if not can_write(st, author, sh):
            e["status"] = "droit"
            return e
        if st.clash(sh.name, None):
            e["status"] = "nom_existant"
            return e
        e.update(kind="undelete", sid=sid)
        return e
    sh = st.sheets.get(sid)
    if sh is None:
        tr = st.trash.get(sid)
        e["status"] = "sheet_gone"
        e["sname"] = tr[0].name if tr else op.get("sname")
        return e
    e["sname"] = sh.name
    if not can_write(st, author, sh):
        e["status"] = "droit"
        e["cell"] = cell
        return e
    if k == "delete":
        if len(st.sheets) <= 1:
            e["status"] = "derniere"
            return e
        e.update(kind="delete_sheet", sid=sid)
        return e
    if k == "rename":
        new = op["name"]
        if new == sh.name:
            return e
        if st.clash(new, sid):
            e["status"] = "nom_existant"
            e["sname"] = new
            return e
        e.update(kind="rename", sid=sid, name=new)
        return e
    if k == "resolve":
        ref = op["ref"]
        c = sh.conf.get(ref)
        if c is None:
            return e
        setd = {}
        if op["use"] and sh.cells.get(ref) != c[0]:
            setd[ref] = c[0]
        e.update(kind="cells", sid=sid, set=setd, conf={ref: None}, label="modification",
                 version=bool(setd), cell=ref)
        return e
    if k == "cells":
        setd = {}
        conf = {}
        name = None
        if op.get("full"):
            snap = op["cells"]
            for r in sh.cells:
                if r not in snap:
                    setd[r] = None
            for r, cv in snap.items():
                if sh.cells.get(r) != cv:
                    setd[r] = cv
            conf = {r: None for r in sh.conf}
            nm = op.get("name")
            if nm and nm != sh.name and not st.clash(nm, sid):
                name = nm
        else:
            bases = op.get("bases", {})
            for r, cv in op["cells"].items():
                cur = sh.cells.get(r)
                if cur == cv:
                    continue
                m = sh.meta.get(r)
                if strict and m and m[0] > bases.get(r, 0) and m[1] != author:
                    conf[r] = (cv, author)
                else:
                    setd[r] = cv
                    if r in sh.conf:
                        conf[r] = None
        e.update(kind="cells", sid=sid, set=setd, conf=conf, label=op.get("label", "modification"),
                 version=bool(setd or name), cell=cell)
        if name:
            e["name"] = name
        return e
    return e


# ------------------------------------------------------------------ calcul

class Calc:
    def __init__(self, state, clock):
        self.st = state
        self.clock = clock
        self._reset()

    def _reset(self):
        self.cache = {}
        self.dc = {}
        self.now = self.clock.now()

    def invalidate(self):
        self._reset()

    def get(self, sid, ref):
        if sid not in self.st.sheets:
            return None
        if self.clock.now() != self.now:
            self._reset()
        key = (sid, ref)
        if key not in self.cache:
            self._run(key)
        return self.cache[key]

    # -- graphe
    def _ast_of(self, key):
        cv = self.st.sheets[key[0]].cells.get(key[1])
        if cv is None or cv[1] or not cv[0].startswith("="):
            return None
        return parse(cv[0])

    def _keys(self, node, sid):
        sh = node[1]
        sid2 = sid if sh is None else self.st.sid_by_name(sh)
        if sid2 is None:
            return None
        if node[0] == "ref":
            c, r = node[2]
            return [(sid2, col_name(c) + str(r))]
        (c1, r1), (c2, r2) = node[2], node[3]
        out = []
        for c in range(min(c1, c2), max(c1, c2) + 1):
            cn = col_name(c)
            for r in range(min(r1, r2), max(r1, r2) + 1):
                out.append((sid2, cn + str(r)))
        return out

    def _collect(self, ast, sid, out):
        t = ast[0]
        if t in ("ref", "range"):
            ks = self._keys(ast, sid)
            if ks:
                out.extend(ks)
        elif t == "neg":
            self._collect(ast[1], sid, out)
        elif t == "bin":
            self._collect(ast[2], sid, out)
            self._collect(ast[3], sid, out)
        elif t == "call":
            for a in ast[2]:
                self._collect(a, sid, out)

    def _deps(self, key):
        d = self.dc.get(key)
        if d is None:
            d = []
            ast = self._ast_of(key)
            if ast is not None:
                self._collect(ast, key[0], d)
            self.dc[key] = d
        return d

    def _run(self, root):
        cache = self.cache
        deps = self._deps
        index = {root: 0}
        low = {root: 0}
        cnt = 1
        stack = [root]
        onst = {root}
        work = [(root, iter(deps(root)))]
        while work:
            node, it = work[-1]
            pushed = False
            for d in it:
                if d in cache:
                    continue
                if d not in index:
                    index[d] = low[d] = cnt
                    cnt += 1
                    stack.append(d)
                    onst.add(d)
                    work.append((d, iter(deps(d))))
                    pushed = True
                    break
                if d in onst and index[d] < low[node]:
                    low[node] = index[d]
            if pushed:
                continue
            work.pop()
            if work:
                p = work[-1][0]
                if low[node] < low[p]:
                    low[p] = low[node]
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    onst.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                self._finish(comp)

    def _finish(self, comp):
        if len(comp) > 1 or comp[0] in self._deps(comp[0]):
            for k in comp:
                self.cache[k] = Err("#CIRC!")
        else:
            self.cache[comp[0]] = self._eval_cell(comp[0])

    # -- évaluation
    def _eval_cell(self, key):
        cv = self.st.sheets[key[0]].cells.get(key[1])
        if cv is None:
            return None
        if not cv[1] and cv[0].startswith("="):
            ast = parse(cv[0])
            if ast is None:
                return Err("#SYNTAXE!")
            try:
                return self._ev(ast, key[0])
            except EvalErr as ex:
                return Err(ex.code)
        return literal_value(cv)

    def _ev(self, ast, sid):
        t = ast[0]
        if t == "num":
            return ast[1]
        if t == "ref":
            keys = self._keys(ast, sid)
            if keys is None:
                raise EvalErr("#REF!")
            v = self.cache[keys[0]]
            if isinstance(v, Err):
                raise EvalErr(v.code)
            return 0 if v is None else v
        if t == "range":
            raise EvalErr("#TYPE!")
        if t == "neg":
            return norm(-num(self._ev(ast[1], sid)))
        if t == "bin":
            l = self._ev(ast[2], sid)
            r = self._ev(ast[3], sid)
            op = ast[1]
            if op == "-":
                if isinstance(l, DT) and isinstance(r, DT):
                    return norm((l.utc - r.utc).total_seconds() / 86400)
                if type(l) is date and type(r) is date:
                    return (l - r).days
            a = num(l)
            b = num(r)
            if op == "+":
                return norm(a + b)
            if op == "-":
                return norm(a - b)
            if op == "*":
                return norm(a * b)
            if b == 0:
                raise EvalErr("#DIV/0!")
            return norm(a / b)
        if t == "call":
            if ast[1] == "MAINTENANT":
                return DT(self.now, None, None)
            total = 0
            for a in ast[2]:
                if a[0] in ("ref", "range"):
                    keys = self._keys(a, sid)
                    if keys is None:
                        raise EvalErr("#REF!")
                    for k in keys:
                        v = self.cache[k]
                        if isinstance(v, Err):
                            raise EvalErr(v.code)
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            total += v
                else:
                    total += num(self._ev(a, sid))
            return norm(total)
        raise EvalErr("#TYPE!")


# ------------------------------------------------------------------ CSV

class CsvErr(Exception):
    def __init__(self, line):
        Exception.__init__(self, line)
        self.line = line


def parse_csv(text):
    rows = []
    row = []
    field = []
    quoted = False
    in_q = False
    line = 1
    start = 1
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_q:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_q = False
                i += 1
                continue
            if c == "\n":
                line += 1
            field.append(c)
            i += 1
            continue
        if c == '"' and not field and not quoted:
            in_q = True
            quoted = True
            i += 1
            continue
        if c == ",":
            row.append("".join(field))
            field = []
            quoted = False
            i += 1
            continue
        if c == "\r" or c == "\n":
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if not row and not field and not quoted:
                rows.append([])
            else:
                row.append("".join(field))
                rows.append(row)
            row = []
            field = []
            quoted = False
            line += 1
            start = line
            i += 1
            continue
        field.append(c)
        i += 1
    if in_q:
        raise CsvErr(start)
    if row or field or quoted:
        row.append("".join(field))
        rows.append(row)
    return rows


# ------------------------------------------------------------------ objets rendus

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
    def __init__(self, id, author, timestamp, kind, sheet=None):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind
        self.sheet = sheet


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.state = State()
        self.log = []
        self.seen = set()
        self.sent = {}
        self.pres = {}
        net.register("server", self)
        e = {"kind": "init", "owner": owner, "sid": "sheet-0", "name": "Feuille1", "seq": 1,
             "author": owner, "ts": clock.now(), "ref": None, "status": "ok", "version": False}
        apply_entry(self.state, e)
        self.log.append(e)

    def peer_down(self, name):
        if name in self.pres:
            del self.pres[name]
            self._broadcast_presence(name, None)

    def link_up(self):
        pass

    def _up_clients(self, except_name=None):
        return [c for c in self.sent if c != except_name and self.net.is_up(c)]

    def _broadcast_presence(self, name, sel):
        for c in self._up_clients(name):
            self.net.send("server", c, ("presence", name, sel))

    def _push(self, c):
        if not self.net.is_up(c):
            return
        entries = self.log[self.sent[c]:]
        if entries:
            self.net.send("server", c, ("entries", entries))
            self.sent[c] = entries[-1]["seq"]

    def receive(self, src, p):
        t = p[0]
        if t == "hello":
            self.sent[src] = p[1]
            if p[2]:
                self.pres[src] = p[2]
            self._push(src)
            self.net.send("server", src, ("presence_all", {n: s for n, s in self.pres.items() if n != src}))
            if p[2]:
                self._broadcast_presence(src, p[2])
        elif t == "ops":
            for op in p[1]:
                self._process(src, op)
            for c in list(self.sent):
                self._push(c)
        elif t == "presence":
            self.pres[src] = p[1]
            self._broadcast_presence(src, p[1])

    def _process(self, author, op):
        key = (author, op["id"])
        if key in self.seen:
            return
        self.seen.add(key)
        e = decide(self.state, op, author, True)
        e["seq"] = len(self.log) + 1
        e["author"] = author
        e["ts"] = op["ts"]
        e["ref"] = key
        apply_entry(self.state, e)
        self.log.append(e)


# ------------------------------------------------------------------ client

class Client:
    def __init__(self, net, clock, name, tz="UTC", _dev=None):
        self.net = net
        self.clock = clock
        self.name = name
        dev = _dev if _dev is not None else {}
        self.dev = dev
        self.tz = dev.get("tz", tz)
        dev["tz"] = self.tz
        self.entries = dev.setdefault("entries", [])
        self.pending = dev.setdefault("pending", [])
        self.opn = dev.get("opn", 0)
        self.sel = dev.get("sel")
        self.active = dev.get("active")
        self.conf = State()
        for e in self.entries:
            apply_entry(self.conf, e)
        self.last = self.entries[-1]["seq"] if self.entries else 0
        self.undo_stack = []
        self.redo_stack = []
        self._alerts = []
        self.pmap = {}
        self.vstate = None
        self.vcalc = None
        self._msgs = {}
        self._rebuild()
        net.register(name, self)
        if net.is_up(name):
            self._hello()

    # -- réseau
    def peer_down(self, name):
        pass

    def link_up(self):
        self._hello()

    def _up(self):
        return self.net.is_up(self.name)

    def _hello(self):
        if not self._up():
            return
        self.net.send(self.name, "server", ("hello", self.last, self.sel))
        for op in self.pending:
            self._send_op(op)

    def _send_op(self, op):
        if self._up():
            m = self.net.send(self.name, "server", ("ops", [op]))
            self._msgs.setdefault(op["id"], []).append(m)

    def receive(self, src, p):
        t = p[0]
        if t == "entries":
            self._apply_entries(p[1])
        elif t == "presence":
            if p[2] is None:
                self.pmap.pop(p[1], None)
            else:
                self.pmap[p[1]] = p[2]
        elif t == "presence_all":
            self.pmap = dict(p[1])

    def _apply_entries(self, entries):
        changed = False
        for e in entries:
            if e["seq"] <= self.last:
                continue
            if e["seq"] != self.last + 1:
                self._hello()
                break
            apply_entry(self.conf, e)
            self.entries.append(e)
            self.last = e["seq"]
            changed = True
            if e["ref"] and e["ref"][0] == self.name:
                self._resolve(e)
        if changed:
            self._rebuild()

    def _resolve(self, e):
        opid = e["ref"][1]
        idx = next((i for i, o in enumerate(self.pending) if o["id"] == opid), None)
        if idx is None:
            return
        del self.pending[idx]
        self._msgs.pop(opid, None)
        st = e["status"]
        if st == "ok":
            return
        if st == "droit":
            self._alert("modification_rejetee", e.get("sname"), e.get("cell"))
        elif st == "sheet_gone":
            self._alert("feuille_supprimee", e.get("sname"))
        elif st == "nom_existant":
            self._alert("nom_existant", e.get("sname"))
        else:
            self._alert("modification_rejetee", e.get("sname"))
        self.undo_stack = [r for r in self.undo_stack if r.get("opid") != opid]
        self.redo_stack = [r for r in self.redo_stack if r.get("opid") != opid]

    # -- vue locale = état confirmé + modifications en attente
    def _rebuild(self):
        self.view = self.conf.copy()
        self._pbase = {}
        for op in self.pending:
            self._apply_local(op)
            if op["k"] == "cells" and not op.get("full"):
                for r in op["cells"]:
                    self._pbase.setdefault((op["sid"], r), op["bases"].get(r, 0))
        self.calc = Calc(self.view, self.clock)

    def _apply_local(self, op):
        e = decide(self.view, op, self.name, False)
        if e["kind"] != "ack":
            e["seq"] = 0
            e["author"] = self.name
            apply_entry(self.view, e)

    def _base(self, sid, ref):
        k = (sid, ref)
        if k in self._pbase:
            return self._pbase[k]
        sh = self.conf.sheets.get(sid)
        m = sh.meta.get(ref) if sh else None
        return m[0] if m else 0

    def _next(self):
        self.opn += 1
        self.dev["opn"] = self.opn
        return self.opn

    def _submit(self, tmpl):
        op = dict(tmpl)
        op["id"] = self._next()
        op["ts"] = self.clock.now()
        sid = op.get("sid")
        op["sname"] = self._sname(sid)
        if op["k"] == "cells":
            op["cells"] = dict(op["cells"])
            if not op.get("full"):
                bases = {}
                for r in op["cells"]:
                    b = self._base(sid, r)
                    bases[r] = b
                    self._pbase.setdefault((sid, r), b)
                op["bases"] = bases
        self.pending.append(op)
        self._send_op(op)
        self._apply_local(op)
        self.calc.invalidate()
        return op

    def _cancel(self, opid):
        msgs = self._msgs.pop(opid, [])
        ok = True
        for m in msgs:
            if not self.net.retract(m):
                ok = False
        if not ok:
            self._msgs[opid] = msgs
            return False
        idx = next((i for i, o in enumerate(self.pending) if o["id"] == opid), None)
        if idx is not None:
            del self.pending[idx]
        self._rebuild()
        return True

    # -- utilitaires
    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _sname(self, sid):
        sh = self.view.sheets.get(sid)
        if sh is not None:
            return sh.name
        tr = self.view.trash.get(sid)
        return tr[0].name if tr else None

    def _cur(self):
        if self.vstate is not None:
            return self.vstate, self.vcalc
        return self.view, self.calc

    def _sid(self, sheet, st=None):
        st = st or self.view
        if sheet is None:
            if self.active in st.sheets:
                return self.active
            return next(iter(st.sheets), None)
        return st.sid_by_name(sheet)

    def _writable(self, sid):
        sh = self.view.sheets.get(sid)
        return sh is not None and can_write(self.view, self.name, sh)

    def _push_rec(self, rec):
        self.undo_stack.append(rec)
        self.redo_stack.clear()

    # -- lecture
    def content(self, ref, sheet=None):
        st, _ = self._cur()
        sid = self._sid(sheet, st)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        cv = st.sheets[sid].cells.get(ref)
        return cv[0] if cv else None

    def _val(self, ref, sheet):
        st, calc = self._cur()
        sid = self._sid(sheet, st)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        return calc.get(sid, ref)

    def value(self, ref, sheet=None):
        v = self._val(ref, sheet)
        if isinstance(v, Err):
            return v.code
        if isinstance(v, DT):
            return v.fmt(self.tz)
        if type(v) is date:
            return v.isoformat()
        return v

    def error(self, ref, sheet=None):
        v = self._val(ref, sheet)
        return v.code if isinstance(v, Err) else None

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return None
        c = self.view.sheets[sid].conf.get(ref)
        return Conflict(c[0][0], c[1]) if c else None

    def sheets(self):
        return [sh.name for sh in self.view.sheets.values()]

    def activate(self, name):
        sid = self.view.sid_by_name(name)
        if sid is not None:
            self.active = sid
            self.dev["active"] = sid

    def set_timezone(self, tz):
        zone(tz)
        self.tz = tz
        self.dev["tz"] = tz

    def right(self, person, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        if person == self.view.owner:
            return W
        return self.view.sheets[sid].rights.get(person)

    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self._up() else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        self.sel = (sid, ref)
        self.dev["sel"] = self.sel
        if self._up():
            self.net.send(self.name, "server", ("presence", self.sel))

    def presence(self):
        if not self._up():
            return {}
        out = {}
        for n, (sid, ref) in self.pmap.items():
            if n != self.name:
                out[n] = (self._sname(sid) or sid, ref)
        return out

    # -- écriture
    def _input_cv(self, text):
        if text is None or text == "":
            return None
        return (text, False, self.tz if is_naive_dt(text) else None)

    def set_cell(self, ref, text, sheet=None):
        self._write(ref, self._input_cv(text), sheet)

    def clear(self, ref, sheet=None):
        self._write(ref, None, sheet)

    def _write(self, ref, cv, sheet):
        if self.vstate is not None:
            return
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", self._sname(sid), ref)
            return
        if self.view.sheets[sid].cells.get(ref) == cv:
            return
        self._do_cells(sid, {ref: cv}, "modification")

    def _do_cells(self, sid, after, label):
        sh = self.view.sheets[sid]
        before = {r: sh.cells.get(r) for r in after}
        fwd = {"k": "cells", "sid": sid, "cells": after, "label": label}
        inv = {"k": "cells", "sid": sid, "cells": before, "label": "modification"}
        op = self._submit(fwd)
        self._push_rec({"t": "cells", "sid": sid, "before": before, "after": after, "fwd": fwd,
                        "fwd_cancel": fwd, "inv": inv, "opid": op["id"]})

    def add_sheet(self, name):
        if self.vstate is not None or not name:
            return
        if self.view.clash(name, None):
            self._alert("nom_existant", name)
            return
        sid = f"{self.name}-{self._next()}"
        fwd = {"k": "add", "sid": sid, "name": name}
        op = self._submit(fwd)
        self._push_rec({"t": "add", "sid": sid, "fwd": {"k": "undelete", "sid": sid}, "fwd_cancel": fwd,
                        "inv": {"k": "delete", "sid": sid}, "opid": op["id"]})

    def delete_sheet(self, name):
        if self.vstate is not None:
            return
        sid = self._sid(name)
        if sid is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", self._sname(sid))
            return
        if len(self.view.sheets) <= 1:
            return
        fwd = {"k": "delete", "sid": sid}
        op = self._submit(fwd)
        self._push_rec({"t": "del", "sid": sid, "fwd": fwd, "fwd_cancel": fwd,
                        "inv": {"k": "undelete", "sid": sid}, "opid": op["id"]})

    def rename_sheet(self, old, new):
        if self.vstate is not None or not new:
            return
        sid = self._sid(old)
        if sid is None:
            return
        sh = self.view.sheets[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        if new == sh.name:
            return
        if self.view.clash(new, sid):
            self._alert("nom_existant", new)
            return
        oldname = sh.name
        fwd = {"k": "rename", "sid": sid, "name": new}
        op = self._submit(fwd)
        self._push_rec({"t": "ren", "sid": sid, "new": new, "fwd": fwd, "fwd_cancel": fwd,
                        "inv": {"k": "rename", "sid": sid, "name": oldname}, "opid": op["id"]})

    def set_right(self, person, sheet, level):
        if not self._up() or self.name != self.view.owner:
            return
        sid = self._sid(sheet)
        if sid is None or level not in (W, R, None):
            return
        if self.view.sheets[sid].rights.get(person) == level:
            return
        op = {"k": "rights", "sid": sid, "person": person, "level": level,
              "id": self._next(), "ts": self.clock.now()}
        self.net.send(self.name, "server", ("ops", [op]))

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.vstate is not None:
            return
        sid = self._sid(sheet)
        ref = norm_ref(ref)
        if sid is None or ref is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", self._sname(sid), ref)
            return
        if ref not in self.view.sheets[sid].conf:
            return
        self._submit({"k": "resolve", "sid": sid, "ref": ref, "use": bool(use_discarded)})

    # -- annulation
    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _undo_ok(self, rec):
        st = self.view
        sid = rec["sid"]
        t = rec["t"]
        sh = st.sheets.get(sid)
        if t == "del":
            if sid not in st.trash:
                self._alert("annulation_impossible", None)
                return False
            return True
        if sh is None:
            self._alert("annulation_impossible", None)
            return False
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name)
            return False
        if t == "cells":
            if rec["inv"].get("full"):
                ok = sh.cells == rec["after"]
            else:
                ok = all(sh.cells.get(r) == cv for r, cv in rec["after"].items())
            if not ok:
                self._alert("annulation_impossible", sh.name, next(iter(rec["after"]), None))
                return False
        elif t == "ren":
            if sh.name != rec["new"]:
                self._alert("annulation_impossible", sh.name)
                return False
        return True

    def undo(self):
        if self.vstate is not None or not self.undo_stack:
            return
        rec = self.undo_stack.pop()
        if not self._undo_ok(rec):
            return
        if any(o["id"] == rec["opid"] for o in self.pending) and self._cancel(rec["opid"]):
            rec["cancelled"] = True
        else:
            rec["cancelled"] = False
            rec["opid"] = self._submit(rec["inv"])["id"]
        self.redo_stack.append(rec)

    def redo(self):
        if self.vstate is not None or not self.redo_stack:
            return
        rec = self.redo_stack.pop()
        tmpl = rec["fwd_cancel"] if rec.get("cancelled") else rec["fwd"]
        if rec["t"] == "cells" and not self._writable(rec["sid"]):
            self._alert("droit_insuffisant", self._sname(rec["sid"]))
            return
        rec["cancelled"] = False
        rec["opid"] = self._submit(tmpl)["id"]
        self.undo_stack.append(rec)

    def reopen(self):
        return Client(self.net, self.clock, self.name, self.tz, _dev=self.dev)

    # -- versions
    def history(self, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return []
        es = [e for e in self.entries if e.get("version") and e.get("sid") == sid]
        es.sort(key=lambda e: (e["ts"], e["seq"]), reverse=True)
        z = zone(self.tz)
        return [Version(e["seq"], e["author"], e["ts"].astimezone(z).strftime(FMT), e["label"], sid)
                for e in es]

    def _state_at(self, vid):
        st = State()
        for e in self.entries:
            if e["seq"] > vid:
                break
            apply_entry(st, e)
        return st

    def open_version(self, version_id):
        if not any(e["seq"] == version_id and e.get("version") for e in self.entries):
            return
        self.vstate = self._state_at(version_id)
        self.vcalc = Calc(self.vstate, self.clock)

    def close_version(self):
        self.vstate = None
        self.vcalc = None

    def restore_version(self, version_id):
        entry = next((e for e in self.entries if e["seq"] == version_id and e.get("version")), None)
        if entry is None:
            return
        sid = entry["sid"]
        sh = self.view.sheets.get(sid)
        if sh is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        snap = self._state_at(version_id).sheets.get(sid)
        if snap is None:
            return
        cur = dict(sh.cells)
        if cur == snap.cells and sh.name == snap.name:
            return
        fwd = {"k": "cells", "sid": sid, "cells": dict(snap.cells), "full": True, "name": snap.name,
               "label": "restauration"}
        inv = {"k": "cells", "sid": sid, "cells": cur, "full": True, "name": sh.name,
               "label": "modification"}
        op = self._submit(fwd)
        self._push_rec({"t": "cells", "sid": sid, "before": cur, "after": dict(snap.cells), "fwd": fwd,
                        "fwd_cancel": fwd, "inv": inv, "opid": op["id"]})

    # -- CSV
    def _export_text(self, v):
        if isinstance(v, Err):
            return v.code
        if v is None:
            return ""
        if isinstance(v, DT):
            return v.utc.astimezone(zone(self.tz)).isoformat(timespec="seconds")
        if type(v) is date:
            return v.isoformat()
        return str(v)

    def export_csv(self):
        st, calc = self._cur()
        sid = self._sid(None, st)
        out = io.StringIO()
        if sid is None:
            return b""
        rows = {}
        maxc = 0
        for ref in st.sheets[sid].cells:
            c, r = split_ref(ref)
            rows.setdefault(r, {})[c] = self._export_text(calc.get(sid, ref))
            maxc = max(maxc, c)
        w = csv.writer(out, lineterminator="\r\n")
        for r in sorted(rows):
            w.writerow([rows[r].get(c, "") for c in range(1, maxc + 1)])
        return out.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.vstate is not None:
            return
        sid = self._sid(None)
        if sid is None:
            return
        sname = self._sname(sid)
        if not self._writable(sid):
            self._alert("droit_insuffisant", sname)
            return
        try:
            rows = parse_csv(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            self._alert("csv_invalide", sname, None, 1)
            return
        except CsvErr as ex:
            self._alert("csv_invalide", sname, None, ex.line)
            return
        sh = self.view.sheets[sid]
        changed = {}
        for i, row in enumerate(rows):
            for j, f in enumerate(row):
                ref = col_name(j + 1) + str(i + 1)
                if f == "":
                    cv = None
                else:
                    cv = (f, f.startswith("="), self.tz if is_naive_dt(f) else None)
                if sh.cells.get(ref) != cv:
                    changed[ref] = cv
        if changed:
            self._do_cells(sid, changed, "modification")
