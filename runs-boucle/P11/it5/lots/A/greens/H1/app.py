"""Classeur collaboratif hors ligne — module unique (couche code).

Moteur de formules (analyseur réel + graphe de dépendances), littéraux typés,
CSV, réseau simulé en mémoire, serveur, copies locales par personne.
"""
import csv
import io
import itertools
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"
SERVER = "__serveur__"
_IDS = itertools.count(1)


class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __eq__(self, other):
        return isinstance(other, Err) and other.code == self.code

    def __hash__(self):
        return hash(self.code)

    def __repr__(self):
        return self.code


class DT:
    """Instant (UTC). wall/tz : saisie naïve d'origine, pour l'affichage chez son auteur."""
    __slots__ = ("instant", "wall", "tz")

    def __init__(self, instant, wall=None, tz=None):
        self.instant = instant
        self.wall = wall
        self.tz = tz


class DV:
    __slots__ = ("d",)

    def __init__(self, d):
        self.d = d


class SyntaxErr(Exception):
    pass


class CSVError(Exception):
    def __init__(self, line):
        super().__init__(line)
        self.line = line


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


# ------------------------------------------------------------------ références

def colname(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def colindex(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _range_keys(sid, c1, r1, c2, r2):
    a, b = colindex(c1), colindex(c2)
    for c in range(min(a, b), max(a, b) + 1):
        for r in range(min(r1, r2), max(r1, r2) + 1):
            yield (sid, f"{colname(c)}{r}")


# ------------------------------------------------------------------ analyseur

_TOK = re.compile(r"""\s*(?:
    (?P<num>\d+(?:\.\d+)?|\.\d+)
  | (?P<ref>(?:(?P<sheet>[^\W\d]\w*)!)?\$?(?P<col>[A-Za-z]{1,3})\$?(?P<row>\d+)(?!\w))
  | (?P<ident>[^\W\d]\w*)
  | (?P<op>[-+*/(),:])
)""", re.X)


def _tokenize(s):
    toks = []
    pos = 0
    while True:
        m = _TOK.match(s, pos)
        if not m:
            if s[pos:].strip() == "":
                return toks
            raise SyntaxErr(s)
        pos = m.end()
        if m.group("num") is not None:
            toks.append(("num", m.group("num")))
        elif m.group("ref") is not None:
            toks.append(("ref", (m.group("sheet"), m.group("col").upper(), int(m.group("row")))))
        elif m.group("ident") is not None:
            toks.append(("ident", m.group("ident")))
        else:
            toks.append(("op", m.group("op")))


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect_op(self, o):
        k, v = self.take()
        if k != "op" or v != o:
            raise SyntaxErr(o)

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
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        return self.atom()

    def atom(self):
        k, v = self.take()
        if k == "num":
            return ("num", float(v) if "." in v else int(v))
        if k == "ref":
            if self.peek() == ("op", ":"):
                self.take()
                k2, v2 = self.take()
                if k2 != "ref":
                    raise SyntaxErr("plage")
                if v2[0] is not None and v2[0] != v[0]:
                    raise SyntaxErr("plage inter-feuilles")
                return ("range", v[0], v[1], v[2], v2[1], v2[2])
            return ("ref", v[0], v[1], v[2])
        if k == "ident":
            name = v.upper()
            if name not in ("SOMME", "MAINTENANT"):
                raise SyntaxErr(v)
            self.expect_op("(")
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            if name == "MAINTENANT":
                if args:
                    raise SyntaxErr("MAINTENANT")
                return ("now",)
            return ("sum", args)
        if k == "op" and v == "(":
            node = self.expr()
            self.expect_op(")")
            return node
        raise SyntaxErr("atome")


_FORMULAS = {}


def parse_formula(text):
    """text commence par '='. Rend un AST, ou Err('#SYNTAXE!')."""
    if text in _FORMULAS:
        return _FORMULAS[text]
    try:
        p = _Parser(_tokenize(text[1:]))
        node = p.expr()
        if p.i != len(p.t):
            raise SyntaxErr("reste")
        res = node
    except SyntaxErr:
        res = Err("#SYNTAXE!")
    _FORMULAS[text] = res
    return res


# ------------------------------------------------------------------ littéraux

_NUM = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DTNAIVE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?")
_DTOFF = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})")


def parse_literal(text, tz):
    """Valeur brute d'un texte saisi (ou importé) ; tz = fuseau de la personne qui l'a saisi."""
    if _NUM.fullmatch(text):
        return float(text) if "." in text else int(text)
    if _DTOFF.fullmatch(text):
        try:
            dt = datetime.fromisoformat(text.replace(" ", "T"))
            return DT(dt.astimezone(UTC))
        except ValueError:
            return text
    m = _DTNAIVE.fullmatch(text)
    if m:
        y, mo, d, h, mi, s = m.groups()
        try:
            wall = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
        except ValueError:
            return text
        inst = wall.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)
        return DT(inst, wall, tz)
    m = _DATE.fullmatch(text)
    if m:
        try:
            return DV(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return text
    return text


def fmt_dt(instant, tz_name):
    return instant.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")


def display(raw, viewer_tz):
    """Valeur affichée (test value())."""
    if raw is None:
        return None
    if isinstance(raw, Err):
        return raw.code
    if isinstance(raw, DT):
        if raw.wall is not None and raw.tz == viewer_tz:
            return raw.wall.strftime("%Y-%m-%d %H:%M")
        return fmt_dt(raw.instant, viewer_tz)
    if isinstance(raw, DV):
        return raw.d.isoformat()
    return raw


def export_text(raw, viewer_tz):
    if raw is None:
        return ""
    if isinstance(raw, Err):
        return raw.code
    if isinstance(raw, DT):
        return raw.instant.astimezone(ZoneInfo(viewer_tz)).isoformat(timespec="seconds")
    if isinstance(raw, DV):
        return raw.d.isoformat()
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return str(raw)


# ------------------------------------------------------------------ opérations

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def binop(op, a, b):
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    if op == "-" and isinstance(a, DT) and isinstance(b, DT):
        return (a.instant - b.instant).total_seconds() / 86400
    if op == "-" and isinstance(a, DV) and isinstance(b, DV):
        return float((a.d - b.d).days)
    if a is None:
        a = 0
    if b is None:
        b = 0
    if not (_num(a) and _num(b)):
        return Err("#TYPE!")
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        return Err("#DIV/0!")
    return a / b


# ------------------------------------------------------------------ graphe et calcul

def _scc(nodes, edges):
    """Composantes fortement connexes, dépendances d'abord (Tarjan itératif)."""
    index, low, onstack, stack, out = {}, {}, set(), [], []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack.add(root)
        work = [(root, iter(edges.get(root, ())))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(edges.get(w, ()))))
                    advanced = True
                    break
                if w in onstack:
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
                out.append(comp)
    return out


def _resolve(names, sheet, cur):
    if sheet is None:
        return cur
    return names.get(sheet)


def _collect(node, cur, names, out):
    t = node[0]
    if t == "ref":
        sid = _resolve(names, node[1], cur)
        if sid is not None:
            out.append((sid, f"{node[2]}{node[3]}"))
    elif t == "range":
        sid = _resolve(names, node[1], cur)
        if sid is not None:
            out.extend(_range_keys(sid, node[2], node[3], node[4], node[5]))
    elif t == "bin":
        _collect(node[2], cur, names, out)
        _collect(node[3], cur, names, out)
    elif t == "neg":
        _collect(node[1], cur, names, out)
    elif t == "sum":
        for a in node[1]:
            _collect(a, cur, names, out)


class _Ctx:
    def __init__(self, book, names, results, now):
        self.book = book
        self.names = names
        self.results = results
        self.now = now

    def raw(self, sid, ref):
        sh = self.book.get(sid)
        if sh is None:
            return Err("#REF!")
        cell = sh["cells"].get(ref)
        if cell is None or cell[0] is None:
            return None
        text, literal, tz = cell[0], cell[1], cell[2]
        if not literal and text.startswith("="):
            return self.results.get((sid, ref), Err("#CIRC!"))
        return parse_literal(text, tz)

    def ev(self, node, cur):
        t = node[0]
        if t == "num":
            return node[1]
        if t == "ref":
            sid = _resolve(self.names, node[1], cur)
            if sid is None:
                return Err("#REF!")
            return self.raw(sid, f"{node[2]}{node[3]}")
        if t == "range":
            return Err("#TYPE!")
        if t == "bin":
            return binop(node[1], self.ev(node[2], cur), self.ev(node[3], cur))
        if t == "neg":
            a = self.ev(node[1], cur)
            if isinstance(a, Err):
                return a
            if a is None:
                a = 0
            return -a if _num(a) else Err("#TYPE!")
        if t == "now":
            return DT(self.now)
        if t == "sum":
            total = 0
            for arg in node[1]:
                if arg[0] == "range":
                    sid = _resolve(self.names, arg[1], cur)
                    if sid is None:
                        return Err("#REF!")
                    for key in _range_keys(sid, arg[2], arg[3], arg[4], arg[5]):
                        v = self.raw(key[0], key[1])
                        if isinstance(v, Err):
                            return v
                        if _num(v):
                            total += v
                else:
                    v = self.ev(arg, cur)
                    if isinstance(v, Err):
                        return v
                    if _num(v):
                        total += v
            return total
        raise ValueError(t)


def compute(book, now):
    """book : {sid: {'name', 'cells': {ref: (texte, littéral, tz, rev)}}} -> {(sid, ref): brut}."""
    names = {sh["name"]: sid for sid, sh in book.items()}
    nodes = {}
    for sid, sh in book.items():
        for ref, cell in sh["cells"].items():
            text = cell[0]
            if text is not None and not cell[1] and text.startswith("="):
                nodes[(sid, ref)] = parse_formula(text)
    edges = {}
    for key, ast in nodes.items():
        deps = []
        if not isinstance(ast, Err):
            _collect(ast, key[0], names, deps)
        edges[key] = [d for d in deps if d in nodes]
    results = {}
    ctx = _Ctx(book, names, results, now)
    for comp in _scc(list(nodes), edges):
        k = comp[0]
        if len(comp) > 1 or k in edges[k]:
            for c in comp:
                results[c] = Err("#CIRC!")
            continue
        ast = nodes[k]
        if isinstance(ast, Err):
            results[k] = ast
        else:
            r = ctx.ev(ast, k[0])
            results[k] = 0 if r is None else r
    return results


def rewrite_formula(text, old, new):
    return re.sub(r"(?<!\w)" + re.escape(old) + "!", lambda _m: new + "!", text)


# ------------------------------------------------------------------ CSV

def parse_csv(text):
    rows, row, field = [], [], []
    inq = False
    qline = line = 1
    i, n = 0, len(text)
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
        if c == '"' and not field:
            inq = True
            qline = line
            i += 1
            continue
        if c == ",":
            row.append("".join(field))
            field = []
            i += 1
            continue
        if c == "\r":
            i += 1
            continue
        if c == "\n":
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
            line += 1
            i += 1
            continue
        field.append(c)
        i += 1
    if inq:
        raise CSVError(qline)
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows

class Version:
    __slots__ = ("id", "seq", "sid", "author", "at", "kind", "name", "changes")

    def __init__(self, seq, sid, author, at, kind, name, changes):
        self.seq = seq
        self.id = str(seq)
        self.sid = sid
        self.author = author
        self.at = at
        self.kind = kind
        self.name = name
        self.changes = tuple(changes)


class VersionView:
    def __init__(self, v, tz):
        self.id = v.id
        self.seq = v.seq
        self.sid = v.sid
        self.author = v.author
        self.kind = v.kind
        self.timestamp = v.at.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ réseau simulé

class Network:
    def __init__(self):
        self.nodes = {}
        self.connected = set()
        self.queue = []
        self.resync = set()
        self._known = set()

    def register(self, name, node):
        self.nodes[name] = node
        if name not in self._known:
            self._known.add(name)
            self.connected.add(name)

    def is_connected(self, name):
        return name in self.connected

    def disconnect(self, name):
        self.connected.discard(name)

    def reconnect(self, name):
        if name not in self.connected:
            self.connected.add(name)
            self.resync.add(name)

    def send(self, src, dst, payload):
        if src in self.connected:
            self.queue.append((src, dst, payload))

    def withdraw(self, src, op_id):
        before = len(self.queue)
        self.queue = [m for m in self.queue
                      if not (m[0] == src and m[2][0] == "op" and m[2][1]["id"] == op_id)]
        return len(self.queue) != before

    def _deliver(self, m):
        src, dst, payload = m
        if src not in self.connected or dst not in self.connected:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, payload)

    def deliver_all(self):
        while True:
            if self.resync:
                names = sorted(self.resync)
                self.resync.clear()
                for name in names:
                    if name in self.connected and name in self.nodes:
                        self.nodes[name].on_reconnect()
                continue
            if not self.queue:
                return
            self._deliver(self.queue.pop(0))

    def deliver_from(self, name):
        mine = [m for m in self.queue if m[0] == name]
        self.queue = [m for m in self.queue if m[0] != name]
        for m in mine:
            self._deliver(m)


# ------------------------------------------------------------------ serveur

def _new_sheet(sid, name, rights):
    return {"id": sid, "name": name, "cells": {}, "rights": dict(rights), "conflicts": {}}


class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.sheets = [_new_sheet("s1", "Feuille1", {owner: W})]
        self.history = []
        self.seq = 0
        self.replies = {}
        net.register(SERVER, self)

    def snapshot(self):
        return {
            "owner": self.owner,
            "sheets": [{"id": s["id"], "name": s["name"], "cells": dict(s["cells"]),
                        "rights": dict(s["rights"]), "conflicts": dict(s["conflicts"])}
                       for s in self.sheets],
            "history": tuple(self.history),
        }

    def _broadcast(self, payload):
        for name in list(self.net.nodes):
            if name != SERVER:
                self.net.send(SERVER, name, payload)

    def receive(self, src, payload):
        kind = payload[0]
        if kind == "hello":
            self.net.send(SERVER, src, ("snapshot", self.snapshot()))
        elif kind == "op":
            op = payload[1]
            if op["id"] not in self.replies:
                self.replies[op["id"]] = self._apply(op)
            reply = self.replies[op["id"]]
            self.net.send(SERVER, src, reply)
            if reply[0] == "ack":
                self._broadcast(("state", self.snapshot()))
        elif kind == "presence":
            self._broadcast(payload)

    def _apply(self, op):
        k = op["kind"]
        if k == "cells":
            return self._cells(op)
        if k == "create":
            return self._create(op)
        if k == "delete":
            return self._delete(op)
        if k == "rename":
            return self._rename(op)
        if k == "set_right":
            return self._set_right(op)
        if k == "resolve":
            return self._resolve(op)
        return ("reject", op["id"], None, None, None, None)

    def _find(self, sid):
        for s in self.sheets:
            if s["id"] == sid:
                return s
        return None

    def _name_taken(self, name, except_sid=None):
        return any(s["id"] != except_sid and s["name"].casefold() == name.casefold()
                   for s in self.sheets)

    def _log(self, sh, author, at, kind, changes):
        self.seq += 1
        self.history.append(Version(self.seq, sh["id"], author, at, kind, sh["name"], changes))

    def _cells(self, op):
        sh = self._find(op["sheet_id"])
        if sh is None:
            return ("reject", op["id"], "feuille_supprimee", op.get("sheet_name"), None, None)
        first = op["changes"][0][0] if op["changes"] else None
        if sh["rights"].get(op["author"]) != W:
            return ("reject", op["id"], "modification_rejetee", sh["name"], first, None)
        applied = []
        for ref, text, literal, base in op["changes"]:
            cur = sh["cells"].get(ref)
            cur_text = cur[0] if cur else None
            cur_lit = cur[1] if cur else False
            cur_rev = cur[3] if cur else 0
            if base is None or base == cur_rev:
                if (cur_text, cur_lit) == (text, literal) or (cur is None and text is None):
                    continue
                sh["cells"][ref] = (text, literal, op["tz"], cur_rev + 1)
                sh["conflicts"].pop(ref, None)
                applied.append((ref, text, literal, op["tz"]))
            elif cur_text != text:
                sh["conflicts"][ref] = (text, op["author"])
        renamed = False
        new_name = op.get("name")
        if new_name and new_name != sh["name"] and not self._name_taken(new_name, sh["id"]):
            sh["name"] = new_name
            renamed = True
        if applied or renamed:
            self._log(sh, op["author"], op["at"], op.get("hkind", "modification"), applied)
        return ("ack", op["id"])

    def _create(self, op):
        if self._find(op["sheet_id"]) is not None:
            return ("ack", op["id"])
        if self._name_taken(op["name"]):
            return ("reject", op["id"], "nom_existant", op["name"], None, None)
        sh = _new_sheet(op["sheet_id"], op["name"], op["rights"])
        for ref, text, literal, tz in op["cells"]:
            sh["cells"][ref] = (text, literal, tz, 0)
        idx = op.get("index")
        if idx is None or idx > len(self.sheets):
            self.sheets.append(sh)
        else:
            self.sheets.insert(idx, sh)
        return ("ack", op["id"])

    def _delete(self, op):
        sh = self._find(op["sheet_id"])
        if sh is None:
            return ("ack", op["id"])
        if sh["rights"].get(op["author"]) != W:
            return ("reject", op["id"], "droit_insuffisant", sh["name"], None, None)
        if len(self.sheets) <= 1:
            return ("reject", op["id"], None, None, None, None)
        self.sheets.remove(sh)
        return ("ack", op["id"])

    def _rename(self, op):
        sh = self._find(op["sheet_id"])
        if sh is None:
            return ("reject", op["id"], "feuille_supprimee", op["name"], None, None)
        if sh["rights"].get(op["author"]) != W:
            return ("reject", op["id"], "droit_insuffisant", sh["name"], None, None)
        new = op["new"]
        if new == sh["name"]:
            return ("ack", op["id"])
        if self._name_taken(new, sh["id"]):
            return ("reject", op["id"], "nom_existant", new, None, None)
        old = sh["name"]
        sh["name"] = new
        for s in self.sheets:
            for ref, cell in list(s["cells"].items()):
                if cell[0] is not None and not cell[1] and cell[0].startswith("="):
                    s["cells"][ref] = (rewrite_formula(cell[0], old, new), cell[1], cell[2], cell[3])
        return ("ack", op["id"])

    def _set_right(self, op):
        if op["author"] != self.owner:
            return ("reject", op["id"], None, None, None, None)
        sh = self._find(op["sheet_id"])
        if sh is None:
            return ("reject", op["id"], None, None, None, None)
        if op["person"] == self.owner and op["level"] != W:
            return ("reject", op["id"], None, None, None, None)
        sh["rights"][op["person"]] = op["level"]
        return ("ack", op["id"])

    def _resolve(self, op):
        sh = self._find(op["sheet_id"])
        if sh is None:
            return ("reject", op["id"], None, None, None, None)
        if sh["rights"].get(op["author"]) != W:
            return ("reject", op["id"], "droit_insuffisant", sh["name"], op["ref"], None)
        conf = sh["conflicts"].pop(op["ref"], None)
        if conf is None:
            return ("ack", op["id"])
        if op["use"]:
            text = conf[0]
            cur = sh["cells"].get(op["ref"])
            rev = cur[3] if cur else 0
            sh["cells"][op["ref"]] = (text, False, op["tz"], rev + 1)
            self._log(sh, op["author"], op["at"], "modification", [(op["ref"], text, False, op["tz"])])
        return ("ack", op["id"])

EMPTY_SNAP = {"owner": None, "sheets": [], "history": ()}


def _by_id(sheets, sid):
    for s in sheets:
        if s["id"] == sid:
            return s
    return None


def _by_name(sheets, name):
    for s in sheets:
        if s["name"] == name:
            return s
    return None


def _overlay(sheets, op):
    """Applique localement une opération en attente sur la vue (liste de feuilles copiées)."""
    k = op["kind"]
    if k == "cells":
        sh = _by_id(sheets, op["sheet_id"])
        if sh is None:
            return
        for ref, text, literal, _base in op["changes"]:
            cur = sh["cells"].get(ref)
            sh["cells"][ref] = (text, literal, op["tz"], (cur[3] if cur else 0) + 1)
            sh["conflicts"].pop(ref, None)
        new_name = op.get("name")
        if new_name and new_name != sh["name"] and not any(
                s["name"].casefold() == new_name.casefold() for s in sheets if s is not sh):
            sh["name"] = new_name
    elif k == "create":
        if _by_id(sheets, op["sheet_id"]) is not None:
            return
        if any(s["name"].casefold() == op["name"].casefold() for s in sheets):
            return
        cells = {ref: (text, literal, tz, 0) for ref, text, literal, tz in op["cells"]}
        sh = {"id": op["sheet_id"], "name": op["name"], "cells": cells,
              "rights": dict(op["rights"]), "conflicts": {}}
        idx = op.get("index")
        if idx is None or idx > len(sheets):
            sheets.append(sh)
        else:
            sheets.insert(idx, sh)
    elif k == "delete":
        sh = _by_id(sheets, op["sheet_id"])
        if sh is not None and len(sheets) > 1:
            sheets.remove(sh)
    elif k == "rename":
        sh = _by_id(sheets, op["sheet_id"])
        if sh is None or op["new"] == sh["name"]:
            return
        if any(s["name"].casefold() == op["new"].casefold() for s in sheets if s is not sh):
            return
        old, new = sh["name"], op["new"]
        sh["name"] = new
        for s in sheets:
            for ref, cell in list(s["cells"].items()):
                if cell[0] is not None and not cell[1] and cell[0].startswith("="):
                    s["cells"][ref] = (rewrite_formula(cell[0], old, new), cell[1], cell[2], cell[3])
    elif k == "set_right":
        sh = _by_id(sheets, op["sheet_id"])
        if sh is not None:
            sh["rights"][op["person"]] = op["level"]
    elif k == "resolve":
        sh = _by_id(sheets, op["sheet_id"])
        if sh is None:
            return
        conf = sh["conflicts"].pop(op["ref"], None)
        if conf is not None and op["use"]:
            cur = sh["cells"].get(op["ref"])
            sh["cells"][op["ref"]] = (conf[0], False, op["tz"], (cur[3] if cur else 0) + 1)


def _cells_match(sid, items, name=None):
    def ok(view):
        sh = _by_id(view, sid)
        if sh is None:
            return False
        if name is not None and sh["name"] != name:
            return False
        for ref, text, _lit in items:
            c = sh["cells"].get(ref)
            if (c[0] if c else None) != text:
                return False
        return True
    return ok


def _name_is(sid, name):
    def ok(view):
        sh = _by_id(view, sid)
        return sh is not None and sh["name"] == name
    return ok


def _exists(sid):
    def ok(view):
        return _by_id(view, sid) is not None
    return ok


def _absent(sid):
    def ok(view):
        return _by_id(view, sid) is None
    return ok


class Rec:
    """Action annulable. cur_ok : l'état courant ; go : opération qui mène à next_ok ;
    back : opération qui ramène à cur_ok. op_id : opération qui a réalisé l'état courant."""
    __slots__ = ("sid", "sname", "cur_ok", "go", "next_ok", "back", "op_id", "cell")

    def __init__(self, sid, sname, cur_ok, go, next_ok, back, op_id, cell=None):
        self.sid = sid
        self.sname = sname
        self.cur_ok = cur_ok
        self.go = go
        self.next_ok = next_ok
        self.back = back
        self.op_id = op_id
        self.cell = cell


class Device:
    """Stockage de l'appareil : survit à la fermeture de l'application."""

    def __init__(self):
        self.outbox = []
        self.snapshot = None
        self.seq = 0


class Client:
    def __init__(self, net, clock, name, tz="UTC", _device=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.dev = _device if _device is not None else Device()
        self.snap = self.dev.snapshot if self.dev.snapshot is not None else EMPTY_SNAP
        self.view = []
        self.active = None
        self.viewing = None
        self.alerts_list = []
        self.undo_stack = []
        self.redo_stack = []
        self.presence_map = {}
        net.register(name, self)
        self._rebuild()
        self.net.send(self.name, SERVER, ("hello",))

    # -------------------------------------------------- vue locale

    def _rebuild(self):
        sheets = []
        for s in self.snap["sheets"]:
            sheets.append({"id": s["id"], "name": s["name"], "cells": dict(s["cells"]),
                           "rights": dict(s["rights"]), "conflicts": dict(s["conflicts"])})
        for op in self.dev.outbox:
            _overlay(sheets, op)
        self.view = sheets
        if _by_id(sheets, self.active) is None:
            self.active = sheets[0]["id"] if sheets else None

    def _sid(self, sheet):
        if sheet is None:
            return self.active
        sh = _by_name(self.view, sheet)
        return sh["id"] if sh else None

    def _view_rev(self, sh, ref):
        c = sh["cells"].get(ref)
        return c[3] if c else 0

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self.alerts_list.append(Alert(kind, sheet, cell, line))

    def _submit(self, op):
        self.dev.seq += 1
        op["id"] = f"{self.name}-{self.dev.seq}"
        op["author"] = self.name
        op["tz"] = self.tz
        op["at"] = self.clock.now()
        self.dev.outbox.append(op)
        self._rebuild()
        self.net.send(self.name, SERVER, ("op", op))
        return op["id"]

    def _withdraw(self, op_id):
        self.dev.outbox = [o for o in self.dev.outbox if o["id"] != op_id]
        self.net.withdraw(self.name, op_id)
        self._rebuild()

    def _drop_op(self, op_id):
        self.dev.outbox = [o for o in self.dev.outbox if o["id"] != op_id]
        self._rebuild()

    # -------------------------------------------------- réseau

    def receive(self, src, payload):
        k = payload[0]
        if k == "ack":
            self._drop_op(payload[1])
        elif k == "reject":
            _, op_id, akind, sheet, cell, line = payload
            self._drop_op(op_id)
            if akind:
                self._alert(akind, sheet, cell, line)
        elif k in ("state", "snapshot"):
            self.snap = payload[1]
            self.dev.snapshot = self.snap
            self._rebuild()
        elif k == "presence":
            _, person, sheet, ref = payload
            self.presence_map[person] = (sheet, ref)

    def on_reconnect(self):
        self.net.send(self.name, SERVER, ("hello",))
        for op in list(self.dev.outbox):
            self.net.send(self.name, SERVER, ("op", op))

    def connection_status(self):
        return "en ligne" if self.net.is_connected(self.name) else "hors ligne"

    def pending_count(self):
        return sum(1 for o in self.dev.outbox if o["kind"] != "set_right")

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz, _device=self.dev)

    # -------------------------------------------------- lecture

    def set_timezone(self, tz):
        self.tz = tz

    def sheets(self):
        return [s["name"] for s in self.view]

    def activate(self, name):
        sh = _by_name(self.view, name)
        if sh is not None:
            self.active = sh["id"]

    def alerts(self):
        return list(self.alerts_list)

    def right(self, person, sheet=None):
        sh = _by_id(self.view, self._sid(sheet))
        return sh["rights"].get(person) if sh else None

    def history(self, sheet=None):
        sid = self._sid(sheet)
        entries = [v for v in self.snap["history"] if v.sid == sid]
        entries.sort(key=lambda v: (v.at, v.seq), reverse=True)
        return [VersionView(v, self.tz) for v in entries]

    def conflict(self, ref, sheet=None):
        sh = _by_id(self.view, self._sid(sheet))
        if sh is None:
            return None
        c = sh["conflicts"].get(ref.upper())
        return Conflict(c[0], c[1]) if c else None

    def select(self, ref, sheet=None):
        sh = _by_id(self.view, self._sid(sheet))
        if sh is None:
            return
        self.net.send(self.name, SERVER, ("presence", self.name, sh["name"], ref.upper()))

    def presence(self):
        if not self.net.is_connected(self.name):
            return {}
        return {p: v for p, v in self.presence_map.items()
                if p != self.name and self.net.is_connected(p)}

    def _book(self):
        book = {}
        for s in self.view:
            book[s["id"]] = {"name": s["name"], "cells": s["cells"]}
        if self.viewing is not None and self.viewing["sid"] in book:
            sid = self.viewing["sid"]
            book[sid] = {"name": book[sid]["name"], "cells": self.viewing["cells"]}
        return book

    def _raw_cell(self, ref, sheet):
        sid = self._sid(sheet)
        book = self._book()
        if sid not in book:
            return None
        ref = ref.upper()
        c = book[sid]["cells"].get(ref)
        if c is None or c[0] is None:
            return None
        if not c[1] and c[0].startswith("="):
            return compute(book, self.clock.now()).get((sid, ref))
        return parse_literal(c[0], c[2])

    def content(self, ref, sheet=None):
        sid = self._sid(sheet)
        sh = self._book().get(sid)
        if sh is None:
            return None
        c = sh["cells"].get(ref.upper())
        return c[0] if c else None

    def value(self, ref, sheet=None):
        return display(self._raw_cell(ref, sheet), self.tz)

    def error(self, ref, sheet=None):
        raw = self._raw_cell(ref, sheet)
        return raw.code if isinstance(raw, Err) else None

    def export_csv(self):
        sid = self.active
        book = self._book()
        sh = book.get(sid)
        if sh is None:
            return b""
        results = compute(book, self.clock.now())
        occupied = []
        for ref, c in sh["cells"].items():
            if c[0] is None:
                continue
            m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
            occupied.append((colindex(m.group(1)), int(m.group(2)), ref))
        if not occupied:
            return b""
        width = max(c for c, _, _ in occupied)
        rowset = {r for _, r, _ in occupied}
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in sorted(rowset):
            fields = []
            for c in range(1, width + 1):
                ref = f"{colname(c)}{r}"
                cell = sh["cells"].get(ref)
                if cell is None or cell[0] is None:
                    raw = None
                elif not cell[1] and cell[0].startswith("="):
                    raw = results.get((sid, ref))
                else:
                    raw = parse_literal(cell[0], cell[2])
                fields.append(export_text(raw, self.tz))
            w.writerow(fields)
        return buf.getvalue().encode("utf-8")

    # -------------------------------------------------- écritures

    def _record_cells(self, sh, after, before, hkind="modification", name_after=None, name_before=None):
        sid = sh["id"]
        fwd = {"kind": "cells", "sheet_id": sid, "sheet_name": sh["name"], "hkind": hkind,
               "changes": [(ref, t, lit, self._view_rev(sh, ref)) for ref, t, lit in after]}
        if name_after is not None:
            fwd["name"] = name_after
        go = {"kind": "cells", "sheet_id": sid, "sheet_name": sh["name"], "hkind": "modification",
              "changes": [(ref, t, lit, None) for ref, t, lit in before]}
        if name_before is not None:
            go["name"] = name_before
        back = {"kind": "cells", "sheet_id": sid, "sheet_name": sh["name"], "hkind": hkind,
                "changes": [(ref, t, lit, None) for ref, t, lit in after]}
        if name_after is not None:
            back["name"] = name_after
        op_id = self._submit(dict(fwd))
        cell = after[0][0] if after else None
        self.undo_stack.append(Rec(sid, sh["name"],
                                   _cells_match(sid, after, name_after), go,
                                   _cells_match(sid, before, name_before), back, op_id, cell))
        self.redo_stack.clear()

    def set_cell(self, ref, text, sheet=None):
        if self.viewing is not None:
            return
        sh = _by_id(self.view, self._sid(sheet))
        if sh is None:
            return
        ref = ref.upper()
        if text == "":
            text = None
        if sh["rights"].get(self.name) != W:
            self._alert("droit_insuffisant", sh["name"], ref)
            return
        cur = sh["cells"].get(ref)
        cur_text = cur[0] if cur else None
        cur_lit = cur[1] if cur else False
        if text == cur_text and not cur_lit:
            return
        self._record_cells(sh, [(ref, text, False)], [(ref, cur_text, cur_lit)])

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def import_csv(self, data):
        if self.viewing is not None:
            return
        sh = _by_id(self.view, self.active)
        if sh is None:
            return
        if sh["rights"].get(self.name) != W:
            self._alert("droit_insuffisant", sh["name"])
            return
        try:
            rows = parse_csv(data.decode("utf-8-sig"))
        except CSVError as e:
            self._alert("csv_invalide", sh["name"], None, e.line)
            return
        after, before = [], []
        for i, row in enumerate(rows):
            for j, field in enumerate(row):
                ref = f"{colname(j + 1)}{i + 1}"
                newt = field if field != "" else None
                lit = field.startswith("=")
                cur = sh["cells"].get(ref)
                curt = cur[0] if cur else None
                curl = cur[1] if cur else False
                if newt == curt and lit == curl:
                    continue
                after.append((ref, newt, lit))
                before.append((ref, curt, curl))
        if not after:
            return
        self._record_cells(sh, after, before)

    def add_sheet(self, name):
        if self.viewing is not None:
            return
        if any(s["name"].casefold() == name.casefold() for s in self.view):
            self._alert("nom_existant", name)
            return
        sid = f"f{next(_IDS)}"
        owner = self.snap["owner"]
        rights = {self.name: W}
        if owner is not None:
            rights[owner] = W
        create = {"kind": "create", "sheet_id": sid, "sheet_name": name, "name": name,
                  "index": None, "cells": [], "rights": rights}
        delete = {"kind": "delete", "sheet_id": sid, "sheet_name": name, "name": name}
        op_id = self._submit(dict(create))
        self.undo_stack.append(Rec(sid, name, _exists(sid), delete, _absent(sid), dict(create), op_id))
        self.redo_stack.clear()

    def delete_sheet(self, name):
        if self.viewing is not None:
            return
        sh = _by_name(self.view, name)
        if sh is None:
            return
        if sh["rights"].get(self.name) != W:
            self._alert("droit_insuffisant", sh["name"])
            return
        if len(self.view) <= 1:
            return
        idx = self.view.index(sh)
        cells = [(ref, c[0], c[1], c[2]) for ref, c in sh["cells"].items() if c[0] is not None]
        create = {"kind": "create", "sheet_id": sh["id"], "sheet_name": sh["name"], "name": sh["name"],
                  "index": idx, "cells": cells, "rights": dict(sh["rights"])}
        delete = {"kind": "delete", "sheet_id": sh["id"], "sheet_name": sh["name"], "name": sh["name"]}
        op_id = self._submit(dict(delete))
        self.undo_stack.append(Rec(sh["id"], sh["name"], _absent(sh["id"]), create,
                                   _exists(sh["id"]), delete, op_id))
        self.redo_stack.clear()

    def rename_sheet(self, old, new):
        if self.viewing is not None:
            return
        sh = _by_name(self.view, old)
        if sh is None or new == sh["name"]:
            return
        if sh["rights"].get(self.name) != W:
            self._alert("droit_insuffisant", old)
            return
        if any(s["id"] != sh["id"] and s["name"].casefold() == new.casefold() for s in self.view):
            self._alert("nom_existant", new)
            return
        sid = sh["id"]
        fwd = {"kind": "rename", "sheet_id": sid, "sheet_name": old, "name": old, "new": new}
        back = {"kind": "rename", "sheet_id": sid, "sheet_name": new, "name": new, "new": old}
        op_id = self._submit(dict(fwd))
        self.undo_stack.append(Rec(sid, new, _name_is(sid, new), back, _name_is(sid, old), dict(fwd), op_id))
        self.redo_stack.clear()

    def set_right(self, person, sheet, level):
        sh = _by_name(self.view, sheet)
        if sh is None:
            return
        if self.name != self.snap["owner"] or not self.net.is_connected(self.name):
            return
        if person == self.snap["owner"] and level != W:
            return
        if sh["rights"].get(person) == level:
            return
        self._submit({"kind": "set_right", "sheet_id": sh["id"], "sheet_name": sh["name"],
                      "person": person, "level": level})

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sh = _by_id(self.view, self._sid(sheet))
        if sh is None:
            return
        ref = ref.upper()
        if ref not in sh["conflicts"]:
            return
        if sh["rights"].get(self.name) != W:
            self._alert("droit_insuffisant", sh["name"], ref)
            return
        self._submit({"kind": "resolve", "sheet_id": sh["id"], "sheet_name": sh["name"],
                      "ref": ref, "use": bool(use_discarded)})

    # -------------------------------------------------- annulation

    def _step(self, rec, dest):
        if rec.op_id is not None and any(o["id"] == rec.op_id for o in self.dev.outbox):
            self._withdraw(rec.op_id)
            dest.append(Rec(rec.sid, rec.sname, rec.next_ok, rec.back, rec.cur_ok, rec.go, None, rec.cell))
            return
        if not rec.cur_ok(self.view):
            self._alert("annulation_impossible", rec.sname, rec.cell)
            return
        sh = _by_id(self.view, rec.sid)
        if sh is not None and sh["rights"].get(self.name) != W:
            self._alert("droit_insuffisant", sh["name"], rec.cell)
            return
        op_id = self._submit(dict(rec.go))
        dest.append(Rec(rec.sid, rec.sname, rec.next_ok, rec.back, rec.cur_ok, rec.go, op_id, rec.cell))

    def undo(self):
        if self.undo_stack:
            self._step(self.undo_stack.pop(), self.redo_stack)

    def redo(self):
        if self.redo_stack:
            self._step(self.redo_stack.pop(), self.undo_stack)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    # -------------------------------------------------- versions

    def _version(self, vid):
        for v in self.snap["history"]:
            if v.id == vid:
                return v
        return None

    def _version_state(self, v):
        cells, name = {}, None
        for e in self.snap["history"]:
            if e.sid != v.sid:
                continue
            for ref, text, lit, tz in e.changes:
                if text is None:
                    cells.pop(ref, None)
                else:
                    cells[ref] = (text, lit, tz, 0)
            name = e.name
            if e.seq == v.seq:
                break
        return cells, name

    def open_version(self, vid):
        v = self._version(vid)
        if v is None:
            return
        cells, _name = self._version_state(v)
        self.viewing = {"sid": v.sid, "cells": cells}

    def close_version(self):
        self.viewing = None

    def restore_version(self, vid):
        if self.viewing is not None:
            return
        v = self._version(vid)
        if v is None:
            return
        sh = _by_id(self.view, v.sid)
        if sh is None:
            return
        if sh["rights"].get(self.name) != W:
            self._alert("droit_insuffisant", sh["name"])
            return
        cells, name = self._version_state(v)
        after, before = [], []
        for ref in sorted(set(sh["cells"]) | set(cells)):
            cur = sh["cells"].get(ref)
            new = cells.get(ref)
            curt, curl = (cur[0], cur[1]) if cur else (None, False)
            newt, newl = (new[0], new[1]) if new else (None, False)
            if curt == newt and curl == newl:
                continue
            before.append((ref, curt, curl))
            after.append((ref, newt, newl))
        rename = name is not None and name != sh["name"]
        if not after and not rename:
            return
        self._record_cells(sh, after, before, hkind="restauration",
                           name_after=name if rename else None,
                           name_before=sh["name"] if rename else None)

    # -------------------------------------------------- compatibilité d'interface

    def __repr__(self):
        return f"Client({self.name!r})"
