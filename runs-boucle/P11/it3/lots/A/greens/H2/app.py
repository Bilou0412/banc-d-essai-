"""Classeur collaboratif hors ligne — couche code (tour 2)."""
import csv
import io
import re
from collections import namedtuple
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

ECRITURE = "écriture"
LECTURE = "lecture"
UTC = timezone.utc


class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return f"Err({self.code!r})"


class DT:
    """Instant aware ; `shown` = texte saisi, affiché tel quel dans le fuseau de l'auteur."""
    __slots__ = ("dt", "shown", "shown_tz")

    def __init__(self, dt, shown=None, shown_tz=None):
        self.dt = dt
        self.shown = shown
        self.shown_tz = shown_tz


_NUM = re.compile(r"-?\d+(\.\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NAIVE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?")
_AWARE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})")


def literal_value(text, tz):
    """Valeur d'un contenu qui n'est pas une formule."""
    if _NUM.fullmatch(text):
        return float(text) if "." in text else int(text)
    if _DATE.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return text
    if _NAIVE.fullmatch(text):
        wall = datetime.fromisoformat(text)
        return DT(wall.replace(tzinfo=ZoneInfo(tz)), wall.strftime("%Y-%m-%d %H:%M"), tz)
    if _AWARE.fullmatch(text):
        return DT(datetime.fromisoformat(text.replace("Z", "+00:00")))
    return text


def display(v, tz):
    if isinstance(v, Err):
        return v.code
    if isinstance(v, DT):
        if v.shown is not None and v.shown_tz == tz:
            return v.shown
        return v.dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return v


def export_text(v, tz):
    if isinstance(v, Err):
        return v.code
    if v is None:
        return ""
    if isinstance(v, DT):
        return v.dt.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# ------------------------------------------------------------------ références

_REF = re.compile(r"([A-Z]+)(\d+)")


def split_ref(ref):
    m = _REF.fullmatch(ref)
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return col, int(m.group(2))


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def ref_of(col, row):
    return f"{col_name(col)}{row}"


def expand_range(a, b):
    ca, ra = split_ref(a)
    cb, rb = split_ref(b)
    return [ref_of(c, r) for c in range(min(ca, cb), max(ca, cb) + 1)
            for r in range(min(ra, rb), max(ra, rb) + 1)]


# ------------------------------------------------------------------ analyseur

class SyntaxErr(Exception):
    pass


_NUMRE = re.compile(r"\d+(?:\.\d+)?")
_SHEETREF = re.compile(r"([^\W\d]\w*)!([A-Z]+\d+)")
_REFRE = re.compile(r"[A-Z]+\d+")
_IDRE = re.compile(r"[^\W\d]\w*")


def tokenize(src):
    toks = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c in "+-*/():,":
            toks.append(("op", c))
            i += 1
            continue
        m = _NUMRE.match(src, i)
        if m:
            toks.append(("num", m.group()))
            i = m.end()
            continue
        m = _SHEETREF.match(src, i)
        if m:
            toks.append(("ref", m.group(1), m.group(2)))
            i = m.end()
            continue
        m = _REFRE.match(src, i)
        if m:
            toks.append(("ref", None, m.group()))
            i = m.end()
            continue
        m = _IDRE.match(src, i)
        if m:
            toks.append(("id", m.group()))
            i = m.end()
            continue
        raise SyntaxErr(c)
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise SyntaxErr("fin")
        self.i += 1
        return tok

    def parse(self):
        e = self.expr()
        if self.peek() is not None:
            raise SyntaxErr("reste")
        return e

    def expr(self):
        e = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            e = ("b", op, e, self.term())
        return e

    def term(self):
        e = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            e = ("b", op, e, self.unary())
        return e

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("u", self.unary())
        return self.primary()

    def primary(self):
        tok = self.take()
        if tok[0] == "num":
            return ("n", float(tok[1]) if "." in tok[1] else int(tok[1]))
        if tok[0] == "ref":
            if self.peek() == ("op", ":"):
                self.take()
                t2 = self.take()
                if t2[0] != "ref":
                    raise SyntaxErr("plage")
                return ("rg", tok[1], tok[2], t2[2])
            return ("r", tok[1], tok[2])
        if tok[0] == "id":
            if self.peek() != ("op", "("):
                raise SyntaxErr("id")
            self.take()
            args = []
            if self.peek() == ("op", ")"):
                self.take()
            else:
                while True:
                    args.append(self.expr())
                    t = self.take()
                    if t == ("op", ")"):
                        break
                    if t != ("op", ","):
                        raise SyntaxErr("arg")
            name = tok[1].upper()
            if name not in ("SOMME", "MAINTENANT"):
                raise SyntaxErr("fonction")
            return ("f", name, args)
        if tok == ("op", "("):
            e = self.expr()
            if self.take() != ("op", ")"):
                raise SyntaxErr(")")
            return e
        raise SyntaxErr("jeton")


_PARSE = {}


def parse_formula(text):
    """Arbre de la formule, ou None si la syntaxe est invalide. `text` commence par '='."""
    if text in _PARSE:
        return _PARSE[text]
    try:
        ast = _Parser(tokenize(text[1:])).parse()
    except SyntaxErr:
        ast = None
    _PARSE[text] = ast
    return ast


def collect_refs(node, out):
    k = node[0]
    if k == "r":
        out.append((node[1], node[2]))
    elif k == "rg":
        for r in expand_range(node[2], node[3]):
            out.append((node[1], r))
    elif k == "b":
        collect_refs(node[2], out)
        collect_refs(node[3], out)
    elif k == "u":
        collect_refs(node[1], out)
    elif k == "f":
        for a in node[2]:
            collect_refs(a, out)


# ------------------------------------------------------------------ évaluation

def _num(v):
    if isinstance(v, Err):
        return v
    if v is None:
        return 0
    if isinstance(v, bool):
        return Err("#TYPE!")
    if isinstance(v, (int, float)):
        return v
    return Err("#TYPE!")


def _ev(node, env):
    k = node[0]
    if k == "n":
        return node[1]
    if k == "r":
        return env.ref(node[1], node[2])
    if k == "rg":
        return env.rng(node[1], node[2], node[3])
    if k == "u":
        v = _num(_ev(node[1], env))
        return v if isinstance(v, Err) else -v
    if k == "b":
        a = _ev(node[2], env)
        b = _ev(node[3], env)
        if isinstance(a, Err):
            return a
        if isinstance(b, Err):
            return b
        if isinstance(a, list) or isinstance(b, list):
            return Err("#TYPE!")
        op = node[1]
        if isinstance(a, (DT, date)) or isinstance(b, (DT, date)):
            if op == "-" and isinstance(a, DT) and isinstance(b, DT):
                return (a.dt.astimezone(UTC) - b.dt.astimezone(UTC)).total_seconds() / 86400
            if op == "-" and isinstance(a, date) and isinstance(b, date):
                return float((a - b).days)
            return Err("#TYPE!")
        x = _num(a)
        y = _num(b)
        if isinstance(x, Err):
            return x
        if isinstance(y, Err):
            return y
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if y == 0:
            return Err("#DIV/0!")
        return x / y
    if k == "f":
        if node[1] == "MAINTENANT":
            return DT(env.now.astimezone(UTC))
        total = 0
        for arg in node[2]:
            v = _ev(arg, env)
            vals = v if isinstance(v, list) else [v]
            for x in vals:
                if isinstance(x, Err):
                    return x
                if isinstance(x, bool):
                    continue
                if isinstance(x, (int, float)):
                    total += x
        return total
    raise AssertionError(k)


class _Env:
    def __init__(self, book, sid, memo, now):
        self.book = book
        self.sid = sid
        self.memo = memo
        self.now = now

    def _sid_of(self, sheet):
        if sheet is None:
            return self.sid
        return self.book.sid_by_name(sheet)

    def ref(self, sheet, ref):
        s = self._sid_of(sheet)
        if s is None:
            return Err("#REF!")
        return self.memo.get((s, ref))

    def rng(self, sheet, a, b):
        s = self._sid_of(sheet)
        if s is None:
            return [Err("#REF!")]
        return [self.memo.get((s, r)) for r in expand_range(a, b)]


def _deps(book, key):
    sid, ref = key
    if sid is None:
        return []
    cell = book.cells.get(sid, {}).get(ref)
    if cell is None or cell.text is None or cell.literal or not cell.text.startswith("="):
        return []
    ast = parse_formula(cell.text)
    if ast is None:
        return []
    out = []
    collect_refs(ast, out)
    keys = []
    for sheet, r in out:
        s = sid if sheet is None else book.sid_by_name(sheet)
        keys.append((s, r))
    return keys


def _components(start, deps):
    """Tarjan itératif ; les composantes sortent dépendances d'abord."""
    index = {start: 0}
    low = {start: 0}
    counter = 1
    stack = [start]
    on = {start}
    out = []
    work = [(start, iter(deps(start)))]
    while work:
        v, it = work[-1]
        advanced = False
        for w in it:
            if w not in index:
                index[w] = low[w] = counter
                counter += 1
                stack.append(w)
                on.add(w)
                work.append((w, iter(deps(w))))
                advanced = True
                break
            if w in on:
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
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(comp)
    return out


def _cell_value(book, key, memo, cyc, now):
    sid, ref = key
    if sid is None:
        return Err("#REF!")
    if key in cyc:
        return Err("#CIRC!")
    cell = book.cells.get(sid, {}).get(ref)
    if cell is None or cell.text is None:
        return None
    if cell.literal or not cell.text.startswith("="):
        return literal_value(cell.text, cell.tz)
    ast = parse_formula(cell.text)
    if ast is None:
        return Err("#SYNTAXE!")
    v = _ev(ast, _Env(book, sid, memo, now))
    if isinstance(v, list):
        return Err("#TYPE!")
    return 0 if v is None else v


def evaluate(book, sid, ref, tz, now):
    start = (sid, ref)
    cache = {}

    def deps(k):
        if k not in cache:
            cache[k] = _deps(book, k)
        return cache[k]

    comps = _components(start, deps)
    cyc = set()
    for comp in comps:
        if len(comp) > 1 or comp[0] in deps(comp[0]):
            cyc.update(comp)
    memo = {}
    for comp in comps:
        for key in comp:
            memo[key] = _cell_value(book, key, memo, cyc, now)
    return memo[start]


# ------------------------------------------------------------------ état d'un classeur

Cell = namedtuple("Cell", "text literal tz author seq conflict")
CF = namedtuple("CF", "text literal tz by")
Alert = namedtuple("Alert", "kind sheet cell line")


class Book:
    def __init__(self, owner, order=None, names=None, cells=None, rights=None):
        self.owner = owner
        self.order = list(order or [])
        self.names = dict(names or {})
        self.cells = {s: dict(c) for s, c in (cells or {}).items()}
        self.rights = {s: dict(r) for s, r in (rights or {}).items()}

    @classmethod
    def from_state(cls, st):
        return cls(st["owner"], st["order"], st["names"], st["cells"], st["rights"])

    def state(self):
        return {"owner": self.owner, "order": list(self.order), "names": dict(self.names),
                "cells": {s: dict(c) for s, c in self.cells.items()},
                "rights": {s: dict(r) for s, r in self.rights.items()}}

    def sid_by_name(self, name):
        for s in self.order:
            if self.names[s] == name:
                return s
        return None

    def cell(self, sid, ref):
        return self.cells.get(sid, {}).get(ref)

    def can_write(self, sid, person):
        return self.rights.get(sid, {}).get(person) == ECRITURE

    def dup_name(self, name, except_sid=None):
        f = name.casefold()
        return any(s != except_sid and self.names[s].casefold() == f for s in self.order)


def apply_prim(book, p, author, rev, local=False):
    """Applique une primitive ; renvoie (sid touché ou None, rejet ou None).
    Un rejet est (genre d'alerte, nom de feuille, cellule)."""
    k = p["k"]
    sid = p.get("sid")
    if k == "add":
        if sid in book.names:
            return None, None
        if book.dup_name(p["name"]):
            return None, ("nom_existant", p["name"], None)
        book.order.append(sid)
        book.names[sid] = p["name"]
        book.cells[sid] = {}
        book.rights[sid] = {book.owner: ECRITURE, author: ECRITURE}
        return sid, None
    if k == "restore":
        if sid in book.names:
            return None, None
        book.order.append(sid)
        book.names[sid] = p["name"]
        book.cells[sid] = dict(p["cells"])
        book.rights[sid] = dict(p["rights"])
        return sid, None
    if sid not in book.names:
        if k == "del":
            return None, None
        return None, ("feuille_supprimee", p["sname"], None)
    if k == "del":
        if len(book.order) == 1:
            return None, None
        if not book.can_write(sid, author):
            return None, ("droit_insuffisant", p["sname"], None)
        book.order.remove(sid)
        del book.names[sid]
        del book.cells[sid]
        del book.rights[sid]
        return sid, None
    if k == "rename":
        if not book.can_write(sid, author):
            return None, ("droit_insuffisant", p["sname"], None)
        new = p["name"]
        if book.names[sid] == new:
            return None, None
        if book.dup_name(new, sid):
            return None, ("nom_existant", new, None)
        book.names[sid] = new
        return sid, None
    ref = p["ref"]
    if not book.can_write(sid, author):
        if k == "resolve":
            return None, ("droit_insuffisant", p["sname"], ref)
        return None, ("modification_rejetee", p["sname"], ref)
    cells = book.cells[sid]
    cur = cells.get(ref)
    if k == "resolve":
        if cur is None or cur.conflict is None:
            return None, None
        c = cur.conflict
        if p["use"]:
            cells[ref] = Cell(c.text, c.literal, c.tz, c.by, rev, None)
        else:
            cells[ref] = cur._replace(seq=rev, conflict=None)
        return sid, None
    # k == "set"
    text = p["text"]
    if text is None:
        if cur is None:
            return None, None
        del cells[ref]
        return sid, None
    if (not local and cur is not None and cur.text is not None and cur.seq > p["base"]
            and cur.author != author and cur.text != text):
        cells[ref] = cur._replace(seq=rev, conflict=CF(text, p["literal"], p["tz"], author))
    else:
        cells[ref] = Cell(text, p["literal"], p["tz"], author, rev, None)
    return sid, None


# ------------------------------------------------------------------ CSV

def parse_csv(text):
    """Renvoie (lignes, None) ou (None, ligne du guillemet non fermé)."""
    rows, row, field = [], [], []
    i, n, line = 0, len(text), 1
    inq = False
    qline = None
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
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
            quoted = False
            line += 1
            i += 1
            continue
        field.append(ch)
        i += 1
    if inq:
        return None, qline
    if field or row or quoted:
        row.append("".join(field))
        rows.append(row)
    return rows, None


# ------------------------------------------------------------------ réseau simulé

class Network:
    def __init__(self):
        self.clients = {}
        self.stores = {}
        self.server = None
        self.queue = []
        self.down = set()
        self.reconnecting = set()

    def is_online(self, name):
        return name not in self.down

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def disconnect(self, name):
        if name in self.down:
            return
        self.down.add(name)
        self.reconnecting.discard(name)
        if self.server is not None:
            self.server.drop(name)

    def reconnect(self, name):
        if name in self.down:
            self.down.discard(name)
            self.reconnecting.add(name)

    def cancel(self, name, op_id):
        """Retire de la file les envois encore en vol d'une modification annulée."""
        self.queue = [m for m in self.queue
                      if not (m[0] == name and m[2].get("t") == "op" and m[2]["id"] == op_id)]

    def _resync(self):
        while self.reconnecting:
            name = self.reconnecting.pop()
            c = self.clients.get(name)
            if c is not None and self.is_online(name):
                c._on_reconnect()

    def _deliver(self, item):
        src, dst, msg = item
        if src != "server" and src in self.down:
            return
        if dst != "server" and dst in self.down:
            return
        if dst == "server":
            self.server.handle(src, msg)
            return
        c = self.clients.get(dst)
        if c is not None:
            c._handle(msg)

    def deliver_all(self):
        self._resync()
        while self.queue:
            batch, self.queue = self.queue, []
            for item in batch:
                self._deliver(item)
            self._resync()

    def deliver_from(self, name):
        self._resync()
        mine = [m for m in self.queue if m[0] == name]
        self.queue = [m for m in self.queue if m[0] != name]
        for item in mine:
            self._deliver(item)
        self._resync()


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.book = Book(owner, order=["F1"], names={"F1": "Feuille1"},
                         cells={"F1": {}}, rights={"F1": {owner: ECRITURE}})
        self.rev = 0
        self.done = {}
        self.presence = {}
        self.log = []
        net.server = self

    def _snapshot(self):
        st = self.book.state()
        st["rev"] = self.rev
        st["done"] = dict(self.done)
        st["presence"] = dict(self.presence)
        return st

    def handle(self, src, msg):
        t = msg["t"]
        if t == "hello":
            self.net.send("server", src, {
                "t": "catchup", "state": self._snapshot(),
                "versions": [e for e in self.log if e["versioned"]]})
        elif t == "op":
            self._op(msg)
        elif t == "rights":
            self._rights(src, msg)
        elif t == "select":
            self.rev += 1
            self.presence[src] = (msg["sid"], msg["ref"])
            self._publish(src, self.clock.now(), "présence", None, [], [], [])

    def _op(self, op):
        if op["id"] in self.done:
            self.net.send("server", op["author"], {"t": "state", "state": self._snapshot()})
            return
        self.rev += 1
        rev = self.rev
        touched, rejects = [], []
        for p in op["prims"]:
            sid, rej = apply_prim(self.book, p, op["author"], rev)
            if sid is not None and sid not in touched:
                touched.append(sid)
            if rej is not None:
                rejects.append(rej)
        self.done[op["id"]] = rev
        self._publish(op["author"], op["ts"], op["kind"], op["id"], touched, rejects, None)

    def _rights(self, src, msg):
        if src != self.book.owner:
            return
        sid = msg["sid"]
        if sid not in self.book.names:
            return
        self.rev += 1
        self.book.rights[sid][msg["person"]] = msg["level"]
        self._publish(src, self.clock.now(), "droits", None, [], [], None)

    def drop(self, name):
        if name in self.presence:
            del self.presence[name]
            self.rev += 1
            self._publish(name, self.clock.now(), "présence", None, [], [], None)

    def _publish(self, author, ts, kind, op_id, touched, rejects, _unused):
        entry = {"rev": self.rev, "author": author, "ts": ts, "kind": kind, "op": op_id,
                 "versioned": bool(touched), "touched": list(touched),
                 "rejects": list(rejects), "state": self._snapshot()}
        self.log.append(entry)
        for name in list(self.net.clients):
            self.net.send("server", name, {"t": "entry", "entry": entry})


# ------------------------------------------------------------------ vues publiques

class ConflictInfo:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    def __init__(self, entry, tz):
        self.id = entry["rev"]
        self.author = entry["author"]
        self.kind = entry["kind"]
        self.utc = entry["ts"]
        self.timestamp = entry["ts"].astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ client

class Client:
    def __init__(self, net, clock, name, tz="UTC"):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        st = net.stores.get(name)
        if st is None:
            st = {"pending": [], "synced": None, "rev": -1, "versions": [], "counter": 0}
            net.stores[name] = st
        self.st = st
        self.undo_stack = []
        self.redo_stack = []
        self.alert_log = []
        self.active = "F1"
        self.viewing = None
        self.viewing_book = None
        self.view = None
        net.clients[name] = self
        self._rebuild()
        self._send({"t": "hello"})

    # -- réseau et synchronisation ---------------------------------------
    def _send(self, msg):
        if self.net.is_online(self.name):
            self.net.send(self.name, "server", msg)

    def _on_reconnect(self):
        self._send({"t": "hello"})
        for op in self.st["pending"]:
            self._send(dict(op, t="op"))

    def _handle(self, msg):
        t = msg["t"]
        if t == "catchup":
            self._adopt(msg["state"])
            self.st["versions"] = list(msg["versions"])
        elif t == "state":
            self._adopt(msg["state"])
        elif t == "entry":
            e = msg["entry"]
            if e["rev"] > self.st["rev"]:
                self._adopt(e["state"])
                if e["versioned"]:
                    self.st["versions"].append(e)
                if e["author"] == self.name:
                    for kind, sheet, cell in e["rejects"]:
                        self._alert(kind, sheet, cell)

    def _adopt(self, state):
        if self.st["synced"] is not None and state["rev"] < self.st["rev"]:
            return
        self.st["synced"] = state
        self.st["rev"] = state["rev"]
        self.st["pending"] = [op for op in self.st["pending"] if op["id"] not in state["done"]]
        self._rebuild()

    def _rebuild(self):
        s = self.st["synced"]
        if s is None:
            self.view = Book(None)
            return
        b = Book.from_state(s)
        for op in self.st["pending"]:
            for p in op["prims"]:
                apply_prim(b, p, op["author"], -1, local=True)
        self.view = b

    def _commit(self, prims, op_id, kind="modification"):
        prims = [dict(p) for p in prims]
        for p in prims:
            if p["k"] in ("set", "resolve"):
                p["base"] = self._base(p["sid"], p["ref"])
        op = {"id": op_id, "prims": prims, "ts": self.clock.now(),
              "author": self.name, "kind": kind}
        self.st["pending"].append(op)
        for p in prims:
            apply_prim(self.view, p, self.name, -1, local=True)
        self._send(dict(op, t="op"))
        return op_id

    def _new_id(self):
        n = self.st["counter"] + 1
        self.st["counter"] = n
        return f"{self.name}#{n}"

    def _base(self, sid, ref):
        s = self.st["synced"]
        if s is None:
            return 0
        c = s["cells"].get(sid, {}).get(ref)
        return c.seq if c is not None else 0

    def _record(self, fwd, inv, op_id, fresh=True):
        self.undo_stack.append({"fwd": fwd, "inv": inv, "op": op_id})
        if fresh:
            self.redo_stack.clear()

    # -- helpers --------------------------------------------------------
    def _alert(self, kind, sheet, cell, line=None):
        self.alert_log.append(Alert(kind, sheet, cell, line))

    def _book(self):
        return self.viewing_book if self.viewing is not None else self.view

    def _sid(self, sheet):
        b = self._book()
        if sheet is None:
            return self.active if self.active in b.names else None
        return b.sid_by_name(sheet)

    def _writable(self, sid):
        return self.view.can_write(sid, self.name)

    def _denied(self, prims):
        for p in prims:
            if p["k"] in ("set", "del", "rename") and p["sid"] in self.view.names:
                if not self.view.can_write(p["sid"], self.name):
                    return True
        return False

    def _stale(self, prims, rev):
        s = self.st["synced"]
        for p in prims:
            if p["k"] in ("set", "resolve"):
                c = s["cells"].get(p["sid"], {}).get(p["ref"])
                if c is not None and c.seq > rev:
                    return True
        return False

    def _eval(self, ref, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        return evaluate(self._book(), sid, ref, self.tz, self.clock.now())

    # -- contenu et valeurs ---------------------------------------------
    def content(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        c = self._book().cell(sid, ref)
        return c.text if c is not None else None

    def value(self, ref, sheet=None):
        return display(self._eval(ref, sheet), self.tz)

    def error(self, ref, sheet=None):
        v = self._eval(ref, sheet)
        return v.code if isinstance(v, Err) else None

    def set_cell(self, ref, text, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        sname = self.view.names[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sname, ref)
            return
        text = None if text in (None, "") else text
        cur = self.view.cell(sid, ref)
        if (cur.text if cur is not None else None) == text:
            return
        fwd = [{"k": "set", "sid": sid, "sname": sname, "ref": ref, "text": text,
                "literal": False, "tz": self.tz}]
        inv = [{"k": "set", "sid": sid, "sname": sname, "ref": ref,
                "text": cur.text if cur else None,
                "literal": cur.literal if cur else False,
                "tz": cur.tz if cur else self.tz}]
        op_id = self._new_id()
        self._commit(fwd, op_id)
        self._record(fwd, inv, op_id)

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def import_csv(self, data):
        if self.viewing is not None:
            return
        sid = self._sid(None)
        if sid is None:
            return
        sname = self.view.names[sid]
        if not self._writable(sid):
            self._alert("droit_insuffisant", sname, None)
            return
        rows, bad = parse_csv(data.decode("utf-8-sig"))
        if bad is not None:
            self._alert("csv_invalide", sname, None, bad)
            return
        cur = self.view.cells[sid]
        fwd, inv = [], []
        for r, row in enumerate(rows, start=1):
            for c, field in enumerate(row, start=1):
                ref = ref_of(c, r)
                old = cur.get(ref)
                fwd.append({"k": "set", "sid": sid, "sname": sname, "ref": ref,
                            "text": field if field != "" else None,
                            "literal": True, "tz": self.tz})
                inv.append({"k": "set", "sid": sid, "sname": sname, "ref": ref,
                            "text": old.text if old else None,
                            "literal": old.literal if old else False,
                            "tz": old.tz if old else self.tz})
        if not fwd:
            return
        op_id = self._new_id()
        self._commit(fwd, op_id)
        self._record(fwd, inv, op_id)

    # -- feuilles -------------------------------------------------------
    def sheets(self):
        b = self._book()
        return [b.names[s] for s in b.order]

    def activate(self, name):
        sid = self._book().sid_by_name(name)
        if sid is not None:
            self.active = sid

    def add_sheet(self, name):
        if self.viewing is not None:
            return
        if self.view.dup_name(name):
            self._alert("nom_existant", name, None)
            return
        op_id = self._new_id()
        fwd = [{"k": "add", "sid": op_id, "sname": name, "name": name}]
        inv = [{"k": "del", "sid": op_id, "sname": name}]
        self._commit(fwd, op_id)
        self._record(fwd, inv, op_id)

    def delete_sheet(self, name):
        if self.viewing is not None:
            return
        sid = self.view.sid_by_name(name)
        if sid is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", name, None)
            return
        if len(self.view.order) == 1:
            return
        snap = {"k": "restore", "sid": sid, "sname": name, "name": name,
                "cells": dict(self.view.cells[sid]), "rights": dict(self.view.rights[sid])}
        fwd = [{"k": "del", "sid": sid, "sname": name}]
        op_id = self._new_id()
        self._commit(fwd, op_id)
        self._record(fwd, [snap], op_id)

    def rename_sheet(self, old, new):
        if self.viewing is not None:
            return
        sid = self.view.sid_by_name(old)
        if sid is None or old == new:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", old, None)
            return
        if self.view.dup_name(new, sid):
            self._alert("nom_existant", new, None)
            return
        fwd = [{"k": "rename", "sid": sid, "sname": old, "name": new}]
        inv = [{"k": "rename", "sid": sid, "sname": new, "name": old}]
        pat = re.compile(r"(?<![\w!])" + re.escape(old) + "!")
        for s2 in self.view.order:
            s2name = self.view.names[s2]
            for ref, cell in self.view.cells[s2].items():
                if cell.literal or cell.text is None or not cell.text.startswith("="):
                    continue
                nt = pat.sub(lambda m: new + "!", cell.text)
                if nt == cell.text:
                    continue
                fwd.append({"k": "set", "sid": s2, "sname": s2name, "ref": ref,
                            "text": nt, "literal": False, "tz": self.tz})
                inv.append({"k": "set", "sid": s2, "sname": s2name, "ref": ref,
                            "text": cell.text, "literal": cell.literal, "tz": cell.tz})
        op_id = self._new_id()
        self._commit(fwd, op_id)
        self._record(fwd, inv, op_id)

    # -- droits ---------------------------------------------------------
    def right(self, person, sheet):
        sid = self.view.sid_by_name(sheet)
        if sid is None:
            return None
        return self.view.rights.get(sid, {}).get(person)

    def set_right(self, person, sheet, level):
        if self.viewing is not None or not self.net.is_online(self.name):
            return
        sid = self.view.sid_by_name(sheet)
        if sid is None:
            return
        self._send({"t": "rights", "sid": sid, "person": person, "level": level})

    # -- présence -------------------------------------------------------
    def select(self, ref, sheet=None):
        if self.viewing is not None or not self.net.is_online(self.name):
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        self._send({"t": "select", "sid": sid, "ref": ref})

    def presence(self):
        s = self.st["synced"]
        if s is None or not self.net.is_online(self.name):
            return {}
        out = {}
        for who, (sid, ref) in s["presence"].items():
            if who != self.name and sid in s["names"]:
                out[who] = (s["names"][sid], ref)
        return out

    # -- conflits -------------------------------------------------------
    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        cell = self._book().cell(sid, ref) if sid is not None else None
        if cell is None or cell.conflict is None:
            return None
        return ConflictInfo(cell.conflict.text, cell.conflict.by)

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        cell = self.view.cell(sid, ref)
        if cell is None or cell.conflict is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", self.view.names[sid], ref)
            return
        op_id = self._new_id()
        self._commit([{"k": "resolve", "sid": sid, "sname": self.view.names[sid],
                       "ref": ref, "use": bool(use_discarded)}], op_id)

    # -- annuler / rétablir ---------------------------------------------
    def undo(self):
        if self.viewing is not None or not self.undo_stack:
            return
        e = self.undo_stack.pop()
        if any(op["id"] == e["op"] for op in self.st["pending"]):
            self.st["pending"] = [op for op in self.st["pending"] if op["id"] != e["op"]]
            self.net.cancel(self.name, e["op"])
            self._rebuild()
            self.redo_stack.append({"fwd": e["fwd"], "inv": e["inv"]})
            return
        if self._denied(e["inv"]):
            return
        done_rev = self.st["synced"]["done"].get(e["op"])
        if done_rev is not None and self._stale(e["fwd"], done_rev):
            self._alert("annulation_impossible", None, None)
            return
        op_id = self._new_id()
        self._commit(e["inv"], op_id)
        self.redo_stack.append({"fwd": e["fwd"], "inv": e["inv"]})

    def redo(self):
        if self.viewing is not None or not self.redo_stack:
            return
        e = self.redo_stack.pop()
        if self._denied(e["fwd"]):
            return
        op_id = self._new_id()
        self._commit(e["fwd"], op_id)
        self.undo_stack.append({"fwd": e["fwd"], "inv": e["inv"], "op": op_id})

    def can_undo(self):
        return len(self.undo_stack) > 0

    def can_redo(self):
        return len(self.redo_stack) > 0

    # -- historique -----------------------------------------------------
    def pending_count(self):
        return len(self.st["pending"])

    def connection_status(self):
        return "en ligne" if self.net.is_online(self.name) else "hors ligne"

    def alerts(self):
        return list(self.alert_log)

    def history(self, sheet=None):
        sid = None
        if sheet is not None:
            sid = self._book().sid_by_name(sheet)
            if sid is None:
                return []
        out = [Version(e, self.tz) for e in self.st["versions"]
               if sid is None or sid in e["touched"]]
        out.sort(key=lambda v: (v.utc, v.id), reverse=True)
        return out

    def _entry(self, vid):
        for e in self.st["versions"]:
            if e["rev"] == vid:
                return e
        return None

    def open_version(self, vid):
        e = self._entry(vid)
        if e is None:
            return
        self.viewing = vid
        self.viewing_book = Book.from_state(e["state"])

    def close_version(self):
        self.viewing = None
        self.viewing_book = None

    def restore_version(self, vid):
        if self.viewing is not None:
            return
        e = self._entry(vid)
        if e is None:
            return
        snap = e["state"]
        fwd, inv = [], []
        denied = None
        for sid in e["touched"]:
            if sid not in self.view.names or sid not in snap["names"]:
                continue
            sname = self.view.names[sid]
            if not self.view.can_write(sid, self.name):
                denied = denied or sname
                continue
            if snap["names"][sid] != sname:
                fwd.append({"k": "rename", "sid": sid, "sname": sname, "name": snap["names"][sid]})
                inv.append({"k": "rename", "sid": sid, "sname": snap["names"][sid], "name": sname})
            cur = self.view.cells[sid]
            old = snap["cells"].get(sid, {})
            for ref in set(cur) | set(old):
                c = cur.get(ref)
                o = old.get(ref)
                ct = c.text if c else None
                ot = o.text if o else None
                if ct == ot:
                    continue
                fwd.append({"k": "set", "sid": sid, "sname": sname, "ref": ref, "text": ot,
                            "literal": o.literal if o else False, "tz": o.tz if o else self.tz})
                inv.append({"k": "set", "sid": sid, "sname": sname, "ref": ref, "text": ct,
                            "literal": c.literal if c else False, "tz": c.tz if c else self.tz})
        if denied is not None:
            self._alert("droit_insuffisant", denied, None)
        if not fwd:
            return
        op_id = self._new_id()
        self._commit(fwd, op_id, kind="restauration")
        self._record(fwd, inv, op_id)

    # -- export / reconnexion -------------------------------------------
    def export_csv(self):
        sid = self._sid(None)
        book = self._book()
        cells = book.cells.get(sid, {}) if sid is not None else {}
        occupied = [(split_ref(r), c) for r, c in cells.items() if c.text is not None]
        if not occupied:
            return b""
        maxcol = max(col for (col, _), _ in occupied)
        rows = sorted({row for (_, row), _ in occupied})
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for row in rows:
            line = []
            for col in range(1, maxcol + 1):
                v = evaluate(book, sid, ref_of(col, row), self.tz, self.clock.now())
                line.append(export_text(v, self.tz))
            w.writerow(line)
        return buf.getvalue().encode("utf-8")

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz)

    def set_timezone(self, tz):
        self.tz = tz
# @@SUITE@@
