"""Classeur collaboratif hors ligne : couche code, tour 1 (green).

Un seul module : analyseur de formules, graphe de dépendances, réseau simulé,
serveur d'autorité, copies locales des clients, fusion et conflits.
"""
import csv
import io
import re
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.setrecursionlimit(50000)

UTC = timezone.utc
W = "écriture"
R = "lecture"

ERR_TYPE = "#TYPE!"
ERR_DIV = "#DIV/0!"
ERR_SYN = "#SYNTAXE!"
ERR_CIRC = "#CIRC!"
ERR_REF = "#REF!"


class Err(str):
    """Code d'erreur affiché dans une cellule."""


class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


@dataclass
class Alert:
    kind: str
    sheet: object = None
    cell: object = None
    line: object = None


@dataclass
class Conflict:
    discarded: object
    discarded_by: object


@dataclass
class Version:
    id: int
    author: str
    time: datetime
    kind: str
    sheet_id: str
    name: str
    cells: dict
    timestamp: str = ""


class DT:
    """Date-heure : instant réel, plus le texte saisi et son fuseau d'origine si connus."""

    __slots__ = ("inst", "wall", "tz")

    def __init__(self, inst, wall, tz):
        self.inst = inst
        self.wall = wall
        self.tz = tz


_INT = re.compile(r"-?\d+")
_FLT = re.compile(r"-?\d+\.\d+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DT_NAIVE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")
_DT_OFF = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})")


def _literal(rec):
    """Valeur d'un contenu non formule. rec = (contenu, fuseau, nature)."""
    c, tz, kd = rec[0], rec[1], rec[2]
    if c is None:
        return None
    if kd == "text":
        return c
    if _INT.fullmatch(c):
        return int(c)
    if _FLT.fullmatch(c):
        return float(c)
    if _DT_OFF.fullmatch(c):
        d = datetime.fromisoformat(c)
        return DT(d.astimezone(UTC), None, None)
    if _DT_NAIVE.fullmatch(c) and tz:
        wall = datetime.fromisoformat(c)
        return DT(wall.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC), wall, tz)
    if _DATE.fullmatch(c):
        return date.fromisoformat(c)
    return c


def _is_formula(rec):
    return rec[2] != "text" and rec[0] is not None and rec[0].startswith("=")


# ---------------------------------------------------------------- références

_REF_RE = re.compile(r"([A-Za-z]{1,3})(\d+)")


def _col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_letters(n):
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _ref_of(text):
    m = _REF_RE.fullmatch(text)
    if not m:
        return None
    return (_col_index(m.group(1)), int(m.group(2)))


def _ref_key(pos):
    return f"{_col_letters(pos[0])}{pos[1]}"


def _rect(a, b):
    c1, c2 = sorted((a[0], b[0]))
    r1, r2 = sorted((a[1], b[1]))
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            yield _ref_key((c, r))


# ---------------------------------------------------------------- analyseur

class _Syn(Exception):
    pass


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_IDENT_RE = re.compile(r"[^\W\d]\w*")


def _tokenize(src):
    toks = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        m = _NUM_RE.match(src, i)
        if m:
            toks.append(("num", m.group()))
            i = m.end()
            continue
        m = _IDENT_RE.match(src, i)
        if m:
            toks.append(("id", m.group()))
            i = m.end()
            continue
        if ch in "+-*/(),:!":
            toks.append(("op", ch))
            i += 1
            continue
        raise _Syn()
    return toks


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

    def expect_op(self, ch):
        if self.peek() != ("op", ch):
            raise _Syn()
        self.i += 1

    def parse(self):
        node = self.expr()
        if self.i != len(self.t):
            raise _Syn()
        return node

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
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        return self.primary()

    def primary(self):
        kind, val = self.peek()
        if kind == "num":
            self.take()
            return ("num", float(val) if "." in val else int(val))
        if (kind, val) == ("op", "("):
            self.take()
            node = self.expr()
            self.expect_op(")")
            return node
        if kind != "id":
            raise _Syn()
        self.take()
        if self.peek() == ("op", "("):
            name = val.upper()
            self.take()
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            if name not in ("SOMME", "MAINTENANT"):
                raise _Syn()
            return ("call", name, args)
        sheet = None
        if self.peek() == ("op", "!"):
            self.take()
            sheet = val
            k2, val = self.take()
            if k2 != "id":
                raise _Syn()
        pos = _ref_of(val)
        if pos is None:
            raise _Syn()
        if self.peek() == ("op", ":"):
            self.take()
            k3, v3 = self.take()
            pos2 = _ref_of(v3) if k3 == "id" else None
            if pos2 is None:
                raise _Syn()
            return ("range", sheet, pos, pos2)
        return ("ref", sheet, _ref_key(pos))


_PARSE_CACHE = {}


def _parse(text):
    """AST d'une formule (texte commençant par '='), ou None si syntaxe invalide."""
    if text in _PARSE_CACHE:
        return _PARSE_CACHE[text]
    try:
        ast = _Parser(_tokenize(text[1:])).parse()
    except _Syn:
        ast = None
    _PARSE_CACHE[text] = ast
    return ast


# ---------------------------------------------------------------- évaluation

def _num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    return None


def _binop(op, a, b):
    if op == "-":
        if isinstance(a, DT) and isinstance(b, DT):
            return (a.inst - b.inst).total_seconds() / 86400
        if isinstance(a, date) and isinstance(b, date):
            return (a - b).days
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return Err(ERR_TYPE)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0:
        return Err(ERR_DIV)
    return x / y


class _Ev:
    """Évaluation d'un classeur figé : book = {sid: (nom, {ref: rec})}."""

    def __init__(self, book, now):
        self.book = book
        self.now = now
        self.names = {name: sid for sid, (name, _c) in book.items()}
        self.memo = {}
        self.cyc = self._cycles()

    def _sid(self, sheet, sid):
        if sheet is None:
            return sid
        return self.names.get(sheet)

    def _deps(self, node, sid, out):
        k = node[0]
        if k == "ref":
            t = self._sid(node[1], sid)
            if t is not None:
                out.append((t, node[2]))
        elif k == "range":
            t = self._sid(node[1], sid)
            if t is not None:
                for key in _rect(node[2], node[3]):
                    out.append((t, key))
        elif k == "bin":
            self._deps(node[2], sid, out)
            self._deps(node[3], sid, out)
        elif k == "neg":
            self._deps(node[1], sid, out)
        elif k == "call":
            for a in node[2]:
                self._deps(a, sid, out)

    def _cycles(self):
        graph = {}
        for sid, (_n, cells) in self.book.items():
            for ref, rec in cells.items():
                if _is_formula(rec):
                    ast = _parse(rec[0])
                    if ast is not None:
                        out = []
                        self._deps(ast, sid, out)
                        graph[(sid, ref)] = out
        index, low, on, stack, cyc = {}, {}, set(), [], set()
        counter = [0]

        def strong(v):
            index[v] = low[v] = counter[0]
            counter[0] += 1
            stack.append(v)
            on.add(v)
            for w in graph[v]:
                if w not in graph:
                    continue
                if w not in index:
                    strong(w)
                    low[v] = min(low[v], low[w])
                elif w in on:
                    low[v] = min(low[v], index[w])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in graph[v]:
                    cyc.update(comp)

        for v in graph:
            if v not in index:
                strong(v)
        return cyc

    def cell(self, sid, ref):
        key = (sid, ref)
        if key in self.memo:
            return self.memo[key]
        if key in self.cyc:
            return Err(ERR_CIRC)
        rec = self.book[sid][1].get(ref)
        if rec is None:
            return None
        if _is_formula(rec):
            ast = _parse(rec[0])
            v = Err(ERR_SYN) if ast is None else self.ev(ast, sid)
            if v is None:
                v = 0
        else:
            v = _literal(rec)
        self.memo[key] = v
        return v

    def ev(self, n, sid):
        k = n[0]
        if k == "num":
            return n[1]
        if k == "ref":
            t = self._sid(n[1], sid)
            if t is None:
                return Err(ERR_REF)
            return self.cell(t, n[2])
        if k == "range":
            return Err(ERR_TYPE)
        if k == "neg":
            a = self.ev(n[1], sid)
            if isinstance(a, Err):
                return a
            x = _num(a)
            return Err(ERR_TYPE) if x is None else -x
        if k == "bin":
            a = self.ev(n[2], sid)
            if isinstance(a, Err):
                return a
            b = self.ev(n[3], sid)
            if isinstance(b, Err):
                return b
            return _binop(n[1], a, b)
        return self._call(n, sid)

    def _call(self, n, sid):
        name, args = n[1], n[2]
        if name == "MAINTENANT":
            if args:
                return Err(ERR_SYN)
            return DT(self.now, None, None)
        total = 0
        for a in args:
            if a[0] == "range":
                t = self._sid(a[1], sid)
                if t is None:
                    return Err(ERR_REF)
                for key in _rect(a[2], a[3]):
                    v = self.cell(t, key)
                    if isinstance(v, Err):
                        return v
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        total += v
            else:
                v = self.ev(a, sid)
                if isinstance(v, Err):
                    return v
                x = _num(v)
                if x is None:
                    return Err(ERR_TYPE)
                total += x
        return total


def _display(v, tz):
    if v is None:
        return None
    if isinstance(v, Err):
        return str(v)
    if isinstance(v, DT):
        if v.wall is not None and v.tz == tz:
            return v.wall.strftime("%Y-%m-%d %H:%M")
        return v.inst.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _csv_text(v, tz):
    if v is None:
        return ""
    if isinstance(v, Err):
        return str(v)
    if isinstance(v, DT):
        return v.inst.astimezone(ZoneInfo(tz)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _parse_csv(data):
    """Renvoie (lignes, None) ou (None, numéro de la ligne invalide)."""
    text = bytes(data).decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows = []
    start = 1
    try:
        while True:
            start = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            rows.append(row)
    except csv.Error:
        return None, start
    return rows, None


def _same_name(a, b):
    """Deux noms de feuille désignent la même feuille s'ils ne diffèrent que par la casse."""
    return a.casefold() == b.casefold()


def _rewrite_sheet_refs(cells, old, new):
    """Réécrit, dans les formules de `cells`, la référence à la feuille `old` en `new`.
    Renvoie `cells` lui-même si rien ne change, sinon une copie modifiée."""
    pat = re.compile(r"(?<!\w)" + re.escape(old) + "!")
    out = None
    for ref, rec in cells.items():
        if _is_formula(rec):
            nc = pat.sub(lambda m: new + "!", rec[0])
            if nc != rec[0]:
                if out is None:
                    out = dict(cells)
                out[ref] = (nc,) + tuple(rec[1:])
    return cells if out is None else out


class Network:
    """Réseau simulé : file FIFO, messages perdus si l'émetteur ou le destinataire est coupé."""

    def __init__(self):
        self.nodes = {}
        self.queue = []
        self.off = set()

    def register(self, name, node):
        self.nodes[name] = node

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def is_online(self, name):
        return name not in self.off

    def _dispatch(self, item):
        src, dst, msg = item
        if src in self.off or dst in self.off:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, msg)

    def deliver_all(self):
        while self.queue:
            self._dispatch(self.queue.pop(0))

    def deliver_from(self, name):
        mine = [i for i in self.queue if i[0] == name]
        self.queue = [i for i in self.queue if i[0] != name]
        for item in mine:
            self._dispatch(item)

    def cancel(self, name, op_id):
        """Retire de la file l'envoi d'une opération encore en vol."""
        self.queue = [i for i in self.queue
                      if not (i[0] == name and i[2][0] == "op" and i[2][1]["id"] == op_id)]

    def disconnect(self, name):
        self.off.add(name)
        srv = self.nodes.get("server")
        if srv is not None:
            srv.on_disconnect(name)

    def reconnect(self, name):
        self.off.discard(name)
        node = self.nodes.get(name)
        if node is not None:
            node.on_connect()


class Server:
    """Autorité : ordre d'arrivée, conflits, droits, historique. État jamais muté en place."""

    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.s = {
            "owner": owner,
            "sheets": (("s0", "Feuille1"),),
            "cells": {"s0": {}},
            "rights": {"s0": {}},
            "conflicts": {},
            "versions": (),
            "done": frozenset(),
            "seq": 0,
            "vid": 0,
            "presence": {},
        }
        net.register("server", self)

    def _snap(self):
        s = self.s
        return {"owner": s["owner"], "sheets": s["sheets"], "cells": dict(s["cells"]),
                "rights": dict(s["rights"]), "conflicts": s["conflicts"],
                "versions": s["versions"], "done": s["done"],
                "presence": dict(s["presence"])}

    def _broadcast(self):
        snap = self._snap()
        for name in list(self.net.nodes):
            if name != "server":
                self.net.send("server", name, ("state", snap))

    def _alert(self, who, kind, sheet=None, cell=None, line=None):
        self.net.send("server", who, ("alert", Alert(kind, sheet, cell, line)))

    def _sheet_name(self, sid):
        for s_id, name in self.s["sheets"]:
            if s_id == sid:
                return name
        return None

    def _writer(self, who, sid):
        if who == self.s["owner"]:
            return True
        return self.s["rights"].get(sid, {}).get(who) == W

    def _set_cells(self, sid, cells):
        self.s["cells"] = {**self.s["cells"], sid: cells}

    def _version(self, sid, author, time, kind):
        self.s["vid"] += 1
        v = Version(self.s["vid"], author, time, kind, sid,
                    self._sheet_name(sid), self.s["cells"][sid])
        self.s["versions"] = self.s["versions"] + (v,)

    def _drop_conflict(self, sid, ref):
        if (sid, ref) in self.s["conflicts"]:
            c = dict(self.s["conflicts"])
            c.pop((sid, ref))
            self.s["conflicts"] = c

    def _write(self, sid, ref, content, tz, kind, author, base, check):
        cells = self.s["cells"][sid]
        cur = cells.get(ref)
        cur_c = cur[0] if cur else None
        if content == cur_c:
            return False
        if check and cur is not None and cur[3] != author and cur[4] > base:
            self.s["conflicts"] = {**self.s["conflicts"], (sid, ref): (content, tz, kind, author)}
            return False
        new = dict(cells)
        if content is None:
            new.pop(ref, None)
        else:
            self.s["seq"] += 1
            new[ref] = (content, tz, kind, author, self.s["seq"])
        self._set_cells(sid, new)
        self._drop_conflict(sid, ref)
        return True

    def receive(self, src, msg):
        kind = msg[0]
        if kind == "hello":
            self.net.send("server", src, ("state", self._snap()))
        elif kind == "op":
            self._apply(msg[1])
            self._broadcast()
        elif kind == "select":
            p = dict(self.s["presence"])
            p[src] = (msg[1], msg[2])
            self.s["presence"] = p
            self._broadcast()
        elif kind == "right":
            _k, sid, person, level = msg
            if src == self.s["owner"] and sid in self.s["cells"]:
                rights = dict(self.s["rights"])
                rights[sid] = {**rights.get(sid, {}), person: level}
                self.s["rights"] = rights
            self._broadcast()

    def on_disconnect(self, name):
        p = dict(self.s["presence"])
        p.pop(name, None)
        self.s["presence"] = p
        self._broadcast()

    def _apply(self, op):
        if op["id"] in self.s["done"]:
            return
        self.s["done"] = self.s["done"] | {op["id"]}
        k = op["k"]
        if k == "add":
            return self._add(op)
        if k == "del":
            return self._del(op)
        if k == "rename":
            return self._rename(op)
        if k == "restore":
            return self._restore(op)
        sid, who = op["sid"], op["author"]
        if sid not in self.s["cells"]:
            return self._alert(who, "feuille_supprimee", op["sname"])
        if k == "setmany":
            items = [(r, c, tz, kd) for r, (c, tz, kd) in op["items"].items()]
            check = False
        else:
            items = [(op["ref"], op["content"], op["tz"], op["kind"])]
            check = k == "set"
        if not self._writer(who, sid):
            return self._alert(who, "modification_rejetee", op["sname"], items[0][0])
        changed = False
        for ref, c, tz, kd in items:
            if self._write(sid, ref, c, tz, kd, who, op.get("base", 0), check):
                changed = True
        if k == "resolve":
            self._drop_conflict(sid, items[0][0])
        if changed:
            self._version(sid, who, op["time"], "modification")

    def _add(self, op):
        sid, name, who = op["sid"], op["name"], op["author"]
        if sid in self.s["cells"]:
            return
        if any(_same_name(n, name) for _s, n in self.s["sheets"]):
            return self._alert(who, "nom_existant", name)
        self.s["sheets"] = self.s["sheets"] + ((sid, name),)
        cells = {}
        for ref, (c, tz, kd) in op.get("cells", {}).items():
            self.s["seq"] += 1
            cells[ref] = (c, tz, kd, who, self.s["seq"])
        self._set_cells(sid, cells)
        rights = dict(self.s["rights"])
        rights[sid] = dict(op.get("rights", {}))
        self.s["rights"] = rights

    def _del(self, op):
        sid, who = op["sid"], op["author"]
        if sid not in self.s["cells"]:
            return
        if not self._writer(who, sid):
            return self._alert(who, "droit_insuffisant", op["sname"])
        if len(self.s["sheets"]) <= 1:
            return
        self.s["sheets"] = tuple(x for x in self.s["sheets"] if x[0] != sid)
        self.s["cells"] = {k: v for k, v in self.s["cells"].items() if k != sid}
        self.s["rights"] = {k: v for k, v in self.s["rights"].items() if k != sid}
        self.s["conflicts"] = {k: v for k, v in self.s["conflicts"].items() if k[0] != sid}

    def _rename(self, op):
        sid, old, new, who = op["sid"], op["old"], op["new"], op["author"]
        if sid not in self.s["cells"]:
            return
        if not self._writer(who, sid):
            return self._alert(who, "droit_insuffisant", old)
        cur = self._sheet_name(sid)
        if cur == new:
            return
        if any(_same_name(n, new) and s != sid for s, n in self.s["sheets"]):
            return self._alert(who, "nom_existant", new)
        self.s["sheets"] = tuple((s, new if s == sid else n) for s, n in self.s["sheets"])
        all_cells = dict(self.s["cells"])
        for s2, cells in self.s["cells"].items():
            nc = _rewrite_sheet_refs(cells, cur, new)
            if nc is not cells:
                all_cells[s2] = nc
        self.s["cells"] = all_cells

    def _restore(self, op):
        sid, who = op["sid"], op["author"]
        if sid not in self.s["cells"]:
            return
        if not self._writer(who, sid):
            return self._alert(who, "droit_insuffisant", op["sname"])
        cells = {}
        for ref, (c, tz, kd) in op["cells"].items():
            if c is None:
                continue
            self.s["seq"] += 1
            cells[ref] = (c, tz, kd, who, self.s["seq"])
        self._set_cells(sid, cells)
        name = op.get("name")
        if name and not any(_same_name(n, name) and s != sid for s, n in self.s["sheets"]):
            self.s["sheets"] = tuple((s, name if s == sid else n) for s, n in self.s["sheets"])
        self._version(sid, who, op["time"], "restauration")

class Client:
    """Copie locale d'une personne : état serveur connu + opérations en attente (outbox)."""

    def __init__(self, net, clock, name, tz="UTC", _st=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self._st = _st if _st is not None else {"base": None, "outbox": [], "n": 0}
        self._undo = []
        self._redo = []
        self._alerts = []
        self._viewing = None
        self._active = None
        self._sheets = []
        net.register(name, self)
        self._rebuild()
        if net.is_online(name):
            self.on_connect()

    # -- réseau

    def on_connect(self):
        for op in self._st["outbox"]:
            self.net.send(self.name, "server", ("op", op))
        self.net.send(self.name, "server", ("hello",))

    def receive(self, src, msg):
        if msg[0] == "state":
            self._st["base"] = msg[1]
            done = msg[1]["done"]
            self._st["outbox"] = [op for op in self._st["outbox"] if op["id"] not in done]
            self._rebuild()
        elif msg[0] == "alert":
            self._alerts.append(msg[1])

    # -- état local : base serveur + overlay des opérations en attente

    def _owner(self):
        b = self._st["base"]
        return b["owner"] if b else None

    def _rebuild(self):
        b = self._st["base"]
        if b is None:
            self._sheets = []
            return
        sheets = []
        for sid, name in b["sheets"]:
            sheets.append([sid, name, dict(b["cells"].get(sid, {})), dict(b["rights"].get(sid, {}))])
        for op in self._st["outbox"]:
            self._overlay(sheets, op)
        self._sheets = sheets

    def _overlay(self, sheets, op):
        k = op["k"]
        me = self.name

        def entry(sid):
            for e in sheets:
                if e[0] == sid:
                    return e
            return None

        def put(e, ref, c, tz, kd, seq):
            if c is None:
                e[2].pop(ref, None)
            else:
                e[2][ref] = (c, tz, kd, me, seq)

        if k in ("set", "resolve"):
            e = entry(op["sid"])
            if e is not None:
                put(e, op["ref"], op["content"], op["tz"], op["kind"], op.get("base", 0))
        elif k == "setmany":
            e = entry(op["sid"])
            if e is not None:
                for ref, (c, tz, kd) in op["items"].items():
                    put(e, ref, c, tz, kd, 0)
        elif k == "add":
            if entry(op["sid"]) is None and not any(_same_name(e[1], op["name"]) for e in sheets):
                cells = {ref: (c, tz, kd, me, 0) for ref, (c, tz, kd) in op.get("cells", {}).items()}
                sheets.append([op["sid"], op["name"], cells, dict(op.get("rights", {}))])
        elif k == "del":
            sheets[:] = [e for e in sheets if e[0] != op["sid"]]
        elif k == "rename":
            e = entry(op["sid"])
            if e is not None and not any(_same_name(x[1], op["new"]) for x in sheets if x is not e):
                old = e[1]
                e[1] = op["new"]
                for x in sheets:
                    x[2] = _rewrite_sheet_refs(x[2], old, op["new"])
        elif k == "restore":
            e = entry(op["sid"])
            if e is not None:
                e[2] = {}
                for ref, (c, tz, kd) in op["cells"].items():
                    put(e, ref, c, tz, kd, 0)
                if op.get("name") and not any(_same_name(x[1], op["name"]) for x in sheets if x is not e):
                    e[1] = op["name"]

    def _book(self):
        book = {}
        for sid, name, cells, _r in self._sheets:
            if self._viewing is not None and self._viewing[0] == sid:
                cells = self._viewing[1]
            book[sid] = (name, cells)
        return book

    def _entry(self, sid):
        for e in self._sheets:
            if e[0] == sid:
                return e
        return None

    def _sheet(self, name=None):
        if name is None:
            e = self._entry(self._active) if self._active is not None else None
            if e is None and self._sheets:
                e = self._sheets[0]
            return (e[0], e[1]) if e is not None else (None, None)
        for e in self._sheets:
            if e[1] == name:
                return (e[0], e[1])
        return (None, None)

    def _level(self, sid):
        e = self._entry(sid)
        if e is None:
            return None
        if self.name == self._owner():
            return W
        return e[3].get(self.name)

    def _base_seq(self, sid, ref):
        b = self._st["base"]
        if b is None:
            return 0
        rec = b["cells"].get(sid, {}).get(ref)
        return rec[4] if rec else 0

    def _alert_local(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _pending(self, op_id):
        return any(o["id"] == op_id for o in self._st["outbox"])

    # -- lectures

    def content(self, ref, sheet=None):
        sid = self._sheet(sheet)[0]
        if sid is None:
            return None
        rec = self._book()[sid][1].get(ref.upper())
        return rec[0] if rec else None

    def value(self, ref, sheet=None):
        sid = self._sheet(sheet)[0]
        if sid is None:
            return None
        v = _Ev(self._book(), self.clock.now()).cell(sid, ref.upper())
        return _display(v, self.tz)

    def error(self, ref, sheet=None):
        sid = self._sheet(sheet)[0]
        if sid is None:
            return None
        v = _Ev(self._book(), self.clock.now()).cell(sid, ref.upper())
        return str(v) if isinstance(v, Err) else None

    def sheets(self):
        return [e[1] for e in self._sheets]

    def right(self, person, sheet):
        sid = self._sheet(sheet)[0]
        e = self._entry(sid) if sid is not None else None
        if e is None:
            return None
        if person == self._owner():
            return W
        return e[3].get(person)

    def connection_status(self):
        return "en ligne" if self.net.is_online(self.name) else "hors ligne"

    def pending_count(self):
        return len(self._st["outbox"])

    def set_timezone(self, tz):
        self.tz = tz

    def alerts(self):
        return list(self._alerts)

    # -- actions : création d'opérations, annulation, rétablissement

    def _inverse(self, spec):
        k = spec["k"]
        sid = spec["sid"]
        e = self._entry(sid)
        if k in ("set", "resolve"):
            rec = e[2].get(spec["ref"]) if e is not None else None
            return {"k": "set", "sid": sid, "sname": spec["sname"], "ref": spec["ref"],
                    "content": rec[0] if rec else None,
                    "tz": rec[1] if rec else self.tz,
                    "kind": rec[2] if rec else "auto"}
        if k == "setmany":
            items = {}
            for ref in spec["items"]:
                rec = e[2].get(ref) if e is not None else None
                items[ref] = (rec[0], rec[1], rec[2]) if rec else (None, self.tz, "auto")
            return {"k": "setmany", "sid": sid, "sname": spec["sname"], "items": items}
        if k == "add":
            return {"k": "del", "sid": sid, "sname": spec["name"]}
        if k == "del":
            cells = {ref: (r[0], r[1], r[2]) for ref, r in e[2].items()} if e is not None else {}
            rights = dict(e[3]) if e is not None else {}
            return {"k": "add", "sid": sid, "name": spec["sname"], "sname": spec["sname"],
                    "cells": cells, "rights": rights}
        if k == "rename":
            return {"k": "rename", "sid": sid, "sname": spec["new"],
                    "old": spec["new"], "new": spec["old"]}
        if k == "restore":
            cells = {ref: (r[0], r[1], r[2]) for ref, r in e[2].items()} if e is not None else {}
            name = e[1] if e is not None else spec["sname"]
            return {"k": "restore", "sid": sid, "sname": name, "name": name, "cells": cells}
        return None

    def _do(self, spec, track=True, keep_redo=False):
        st = self._st
        st["n"] += 1
        op = dict(spec)
        op["id"] = f"{self.name}#{st['n']}"
        op["author"] = self.name
        op["time"] = self.clock.now()
        if spec["k"] in ("set", "resolve"):
            op["base"] = self._base_seq(spec["sid"], spec["ref"])
        inv = self._inverse(spec)
        st["outbox"].append(op)
        if track:
            self._undo.append({
                "op": op["id"], "inv": inv, "redo": spec, "sid": spec["sid"],
                "ref": spec.get("ref") if spec["k"] == "set" else None,
            })
            if not keep_redo:
                self._redo.clear()
        self._rebuild()
        if self.net.is_online(self.name):
            self.net.send(self.name, "server", ("op", op))
        return op

    def _edit(self, ref, content, sheet, kind="auto"):
        sid, sname = self._sheet(sheet)
        if sid is None or self._viewing is not None:
            return
        ref = ref.upper()
        if self._level(sid) != W:
            self._alert_local("droit_insuffisant", sname, ref)
            return
        rec = self._entry(sid)[2].get(ref)
        if (rec[0] if rec else None) == content:
            return
        self._do({"k": "set", "sid": sid, "sname": sname, "ref": ref,
                  "content": content, "tz": self.tz, "kind": kind})

    def set_cell(self, ref, text, sheet=None):
        self._edit(ref, text, sheet)

    def clear(self, ref, sheet=None):
        self._edit(ref, None, sheet)

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return
        e = self._undo.pop()
        sid = e["sid"]
        ent = self._entry(sid)
        sname = ent[1] if ent is not None else None
        if self._pending(e["op"]):
            self._st["outbox"] = [o for o in self._st["outbox"] if o["id"] != e["op"]]
            self.net.cancel(self.name, e["op"])
            self._redo.append(e["redo"])
            self._rebuild()
            return
        if ent is not None and self._level(sid) != W:
            self._alert_local("droit_insuffisant", sname, e["ref"])
            return
        if e["ref"] is not None and ent is not None:
            rec = ent[2].get(e["ref"])
            if rec is not None and rec[3] != self.name:
                self._alert_local("annulation_impossible", sname, e["ref"])
                return
        self._redo.append(e["redo"])
        if e["inv"] is not None:
            self._do(e["inv"], track=False)

    def redo(self):
        if not self._redo:
            return
        spec = self._redo.pop()
        sid = spec["sid"]
        if self._entry(sid) is not None and self._level(sid) != W:
            self._alert_local("droit_insuffisant", spec.get("sname"))
            return
        self._do(spec, track=True, keep_redo=True)

    # -- feuilles

    def activate(self, name):
        sid, _n = self._sheet(name)
        if sid is not None:
            self._active = sid

    def add_sheet(self, name):
        if any(_same_name(e[1], name) for e in self._sheets):
            self._alert_local("nom_existant", name)
            return
        sid = f"{self.name}-S{self._st['n'] + 1}"
        self._do({"k": "add", "sid": sid, "sname": name, "name": name,
                  "cells": {}, "rights": {self.name: W}})

    def delete_sheet(self, name):
        sid, sname = self._sheet(name)
        if sid is None:
            return
        if self._level(sid) != W:
            self._alert_local("droit_insuffisant", sname)
            return
        if len(self._sheets) <= 1:
            return
        self._do({"k": "del", "sid": sid, "sname": sname})

    def rename_sheet(self, old, new):
        sid, sname = self._sheet(old)
        if sid is None:
            return
        if self._level(sid) != W:
            self._alert_local("droit_insuffisant", sname)
            return
        if old == new:
            return
        if any(e[0] != sid and _same_name(e[1], new) for e in self._sheets):
            self._alert_local("nom_existant", new)
            return
        self._do({"k": "rename", "sid": sid, "sname": old, "old": old, "new": new})

    def set_right(self, person, sheet, level):
        if self.name != self._owner() or not self.net.is_online(self.name):
            return
        sid = self._sheet(sheet)[0]
        if sid is None:
            return
        self.net.send(self.name, "server", ("right", sid, person, level))

    # -- CSV

    def import_csv(self, data):
        sid, sname = self._sheet(None)
        if sid is None:
            return
        if self._level(sid) != W:
            self._alert_local("droit_insuffisant", sname)
            return
        rows, bad = _parse_csv(data)
        if bad is not None:
            self._alert_local("csv_invalide", sname, None, bad)
            return
        items = {}
        for i, row in enumerate(rows):
            for j, field in enumerate(row):
                ref = f"{_col_letters(j + 1)}{i + 1}"
                if field == "":
                    items[ref] = (None, self.tz, "auto")
                elif field.startswith("="):
                    items[ref] = (field, self.tz, "text")
                elif _DT_OFF.fullmatch(field):
                    items[ref] = (field, None, "auto")
                else:
                    items[ref] = (field, self.tz, "auto")
        if items:
            self._do({"k": "setmany", "sid": sid, "sname": sname, "items": items})

    def export_csv(self):
        sid = self._sheet(None)[0]
        if sid is None:
            return b""
        book = self._book()
        cells = book[sid][1]
        if not cells:
            return b""
        ev = _Ev(book, self.clock.now())
        maxc = max(_ref_of(r)[0] for r in cells)
        maxr = max(_ref_of(r)[1] for r in cells)
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        for r in range(1, maxr + 1):
            fields = []
            present = False
            for c in range(1, maxc + 1):
                key = f"{_col_letters(c)}{r}"
                if key in cells:
                    present = True
                fields.append(_csv_text(ev.cell(sid, key), self.tz))
            if present:
                writer.writerow(fields)
        return buf.getvalue().encode("utf-8")

    # -- historique

    def history(self, sheet=None):
        b = self._st["base"]
        sid = self._sheet(sheet)[0]
        if b is None or sid is None:
            return []
        vs = [v for v in b["versions"] if v.sheet_id == sid]
        vs.sort(key=lambda v: (v.time, v.id), reverse=True)
        return [replace(v, timestamp=v.time.astimezone(ZoneInfo(self.tz)).strftime("%Y-%m-%d %H:%M"))
                for v in vs]

    def _version_of(self, vid):
        b = self._st["base"]
        if b is None:
            return None
        for v in b["versions"]:
            if v.id == vid:
                return v
        return None

    def open_version(self, vid):
        v = self._version_of(vid)
        if v is not None:
            self._viewing = (v.sheet_id, dict(v.cells))

    def close_version(self):
        self._viewing = None

    def restore_version(self, vid):
        v = self._version_of(vid)
        if v is None:
            return
        e = self._entry(v.sheet_id)
        if e is None:
            return
        if self._level(v.sheet_id) != W:
            self._alert_local("droit_insuffisant", e[1])
            return
        cells = {ref: (r[0], r[1], r[2]) for ref, r in v.cells.items()}
        self._do({"k": "restore", "sid": v.sheet_id, "sname": e[1], "name": v.name, "cells": cells})

    # -- conflits, présence, droits

    def conflict(self, ref, sheet=None):
        b = self._st["base"]
        sid = self._sheet(sheet)[0]
        if b is None or sid is None:
            return None
        raw = b["conflicts"].get((sid, ref.upper()))
        if raw is None:
            return None
        return Conflict(raw[0], raw[3])

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sid, sname = self._sheet(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if self._level(sid) != W:
            self._alert_local("droit_insuffisant", sname, ref)
            return
        b = self._st["base"]
        raw = b["conflicts"].get((sid, ref))
        if raw is None:
            return
        if use_discarded:
            content, tz, kd = raw[0], raw[1], raw[2]
        else:
            rec = b["cells"].get(sid, {}).get(ref)
            content, tz, kd = (rec[0], rec[1], rec[2]) if rec else (None, self.tz, "auto")
        self._do({"k": "resolve", "sid": sid, "sname": sname, "ref": ref,
                  "content": content, "tz": tz, "kind": kd}, track=False)

    def select(self, ref, sheet=None):
        sid, sname = self._sheet(sheet)
        if sid is None or not self.net.is_online(self.name):
            return
        self.net.send(self.name, "server", ("select", sname, ref.upper()))

    def presence(self):
        b = self._st["base"]
        if b is None or not self.net.is_online(self.name):
            return {}
        return {n: v for n, v in b["presence"].items() if n != self.name}

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz, _st=self._st)
