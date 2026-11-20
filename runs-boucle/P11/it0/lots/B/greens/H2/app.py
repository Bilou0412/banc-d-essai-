"""Classeur collaboratif hors ligne — couche code (sonde P11).

Un seul module : temps simulé, réseau simulé en mémoire, analyseur de formules,
graphe de dépendances (composantes fortement connexes pour les cycles), serveur
qui fusionne les opérations, copies locales par personne.
"""
import csv
import io
import re
import sys
from collections import deque
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.setrecursionlimit(20000)

UTC = timezone.utc
W = "écriture"
R = "lecture"
SERVER = "server"


# ------------------------------------------------------------ temps

class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


# ------------------------------------------------------------ objets publics

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


class Err:
    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return self.code


class Version:
    """Entrée de l'historique côté serveur (partagée, jamais modifiée)."""

    def __init__(self, vid, author, instant, kind, scope, snap):
        self.id = vid
        self.author = author
        self.instant = instant
        self.kind = kind
        self.scope = scope
        self.snap = snap


class VersionView:
    def __init__(self, v, tz):
        self.id = v.id
        self.author = v.author
        self.kind = v.kind
        self.instant = v.instant
        self.timestamp = v.instant.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------ réseau simulé

class Network:
    def __init__(self):
        self.nodes = {}
        self.queue = deque()
        self.down = set()
        self.waking = []

    def register(self, name, node):
        self.nodes[name] = node

    def send(self, src, dst, payload):
        self.queue.append((src, dst, payload))

    def is_online(self, name):
        return name not in self.down

    def disconnect(self, name):
        if name in self.down:
            return
        self.down.add(name)
        srv = self.nodes.get(SERVER)
        if srv is not None and name != SERVER and name in self.nodes:
            srv.peer_left(name)

    def reconnect(self, name):
        if name in self.down:
            self.down.discard(name)
            self.waking.append(name)

    def _deliver(self, src, dst, payload):
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, payload)

    def _wake(self):
        while self.waking:
            name = self.waking.pop(0)
            if name in self.down or name == SERVER:
                continue
            node = self.nodes.get(name)
            if node is not None:
                node.on_connect()

    def deliver_all(self):
        self._wake()
        while self.queue:
            src, dst, payload = self.queue.popleft()
            self._deliver(src, dst, payload)
            self._wake()

    def deliver_from(self, name):
        self._wake()
        mine = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for src, dst, payload in mine:
            self._deliver(src, dst, payload)
            self._wake()


# ------------------------------------------------------------ formules

class _SynErr(Exception):
    pass


class _CsvErr(Exception):
    def __init__(self, line):
        super().__init__(line)
        self.line = line


_TOK = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<id>[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_]*)"
    r"|(?P<op>[-+*/(),:!])|(?P<bad>\S))"
)
_CELLREF = re.compile(r"([A-Z]{1,3})([0-9]+)")
_FUNCS = ("SOMME", "MAINTENANT")


def _tokenize(s):
    toks = []
    pos = 0
    while True:
        m = _TOK.match(s, pos)
        if m is None:
            break
        kind = m.lastgroup
        if kind == "bad":
            raise _SynErr(m.group("bad"))
        toks.append((kind, m.group(kind)))
        pos = m.end()
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
        k, v = self.take()
        if k != "op" or v != ch:
            raise _SynErr(ch)

    def expr(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            node = ("bin", op, node, self.factor())
        return node

    def factor(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.factor())
        return self.atom()

    def atom(self):
        k, v = self.take()
        if k == "num":
            return ("num", float(v) if "." in v else int(v))
        if (k, v) == ("op", "("):
            node = self.expr()
            self.expect_op(")")
            return node
        if k != "id":
            raise _SynErr(v)
        nk, nv = self.peek()
        if (nk, nv) == ("op", "("):
            if v not in _FUNCS:
                raise _SynErr(v)
            self.take()
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            if v == "MAINTENANT":
                if args:
                    raise _SynErr(v)
                return ("now",)
            return ("func", v, args)
        sheet = None
        if (nk, nv) == ("op", "!"):
            self.take()
            sheet = v
            k, v = self.take()
            if k != "id":
                raise _SynErr(v)
        if not _CELLREF.fullmatch(v):
            raise _SynErr(v)
        if self.peek() == ("op", ":"):
            self.take()
            k2, v2 = self.take()
            if k2 != "id" or not _CELLREF.fullmatch(v2):
                raise _SynErr(v2)
            return ("range", sheet, v, v2)
        return ("ref", sheet, v)


def parse_formula(text):
    toks = _tokenize(text[1:])
    p = _Parser(toks)
    node = p.expr()
    if p.i != len(toks):
        raise _SynErr("fin inattendue")
    return node


def _colnum(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _colname(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _range_refs(ref1, ref2):
    c1, r1 = _CELLREF.fullmatch(ref1).groups()
    c2, r2 = _CELLREF.fullmatch(ref2).groups()
    ca, cb = sorted((_colnum(c1), _colnum(c2)))
    ra, rb = sorted((int(r1), int(r2)))
    return [f"{_colname(c)}{r}" for c in range(ca, cb + 1) for r in range(ra, rb + 1)]


def _collect(node, out):
    t = node[0]
    if t == "ref":
        out.append((node[1], [node[2]]))
    elif t == "range":
        out.append((node[1], _range_refs(node[2], node[3])))
    elif t == "neg":
        _collect(node[1], out)
    elif t == "bin":
        _collect(node[2], out)
        _collect(node[3], out)
    elif t == "func":
        for a in node[2]:
            _collect(a, out)
    return out


_INT = re.compile(r"-?\d+")
_FLT = re.compile(r"-?\d+\.\d+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NAIVE_DT = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(:\d{2})?")


def _classify(c, k):
    """Valeur d'un contenu non-formule."""
    if c is None:
        return None
    if _INT.fullmatch(c):
        return int(c)
    if _FLT.fullmatch(c):
        return float(c)
    if _DATE.fullmatch(c):
        try:
            return date.fromisoformat(c)
        except ValueError:
            return c
    try:
        d = datetime.fromisoformat(c)
    except ValueError:
        return c
    return d if d.tzinfo is not None else c


def _normalize_text(text, tz):
    """Une date-heure saisie sans décalage est fixée dans le fuseau de la personne qui saisit."""
    m = _NAIVE_DT.fullmatch(text)
    if not m:
        return text
    try:
        naive = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{m.group(3) or ':00'}")
    except ValueError:
        return text
    return naive.replace(tzinfo=ZoneInfo(tz)).isoformat()


def rename_refs(text, old, new):
    return re.sub(r"(?<![A-Za-z0-9_À-ÿ])" + re.escape(old) + "!", new + "!", text)


_MISSING = object()


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class _Range:
    def __init__(self, vals):
        self.vals = vals


class _Evaluator:
    def __init__(self, sheets, cells, now):
        self.by_name = {name: sid for sid, name in sheets}
        self.cells = cells
        self.now = now
        self.memo = {}

    def resolve(self, sheet, own):
        if sheet is None:
            return own
        return self.by_name.get(sheet, _MISSING)

    def cell_value(self, sid, ref):
        key = (sid, ref)
        if key in self.memo:
            return self.memo[key]
        rec = self.cells.get(sid, {}).get(ref)
        if rec is None:
            return None
        return _classify(rec[0], rec[1])

    def eval(self, node, own):
        t = node[0]
        if t == "num":
            return node[1]
        if t == "now":
            return self.now
        if t == "ref":
            sid = self.resolve(node[1], own)
            if sid is _MISSING:
                return Err("#REF!")
            return self.cell_value(sid, node[2])
        if t == "range":
            sid = self.resolve(node[1], own)
            if sid is _MISSING:
                return Err("#REF!")
            return _Range([self.cell_value(sid, r) for r in _range_refs(node[2], node[3])])
        if t == "neg":
            v = self.eval(node[1], own)
            if isinstance(v, (Err, _Range)):
                return v if isinstance(v, Err) else Err("#TYPE!")
            if v is None:
                return 0
            return -v if _is_num(v) else Err("#TYPE!")
        if t == "func":
            return self._sum(node[2], own)
        a = self.eval(node[2], own)
        b = self.eval(node[3], own)
        for x in (a, b):
            if isinstance(x, Err):
                return x
            if isinstance(x, _Range):
                return Err("#TYPE!")
        op = node[1]
        if op == "-" and a is not None and b is not None:
            if isinstance(a, datetime) and isinstance(b, datetime):
                return (a.astimezone(UTC) - b.astimezone(UTC)).total_seconds() / 86400
            if (isinstance(a, date) and isinstance(b, date)
                    and not isinstance(a, datetime) and not isinstance(b, datetime)):
                return (a - b).days
        a = 0 if a is None else a
        b = 0 if b is None else b
        if not (_is_num(a) and _is_num(b)):
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

    def _sum(self, args, own):
        total = 0
        for arg in args:
            v = self.eval(arg, own)
            items = v.vals if isinstance(v, _Range) else [v]
            for x in items:
                if isinstance(x, Err):
                    return x
                if _is_num(x):
                    total += x
        return total


def _tarjan(nodes, edges):
    index, low, on, stack, out = {}, {}, set(), [], []

    def strong(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        on.add(v)
        for w in edges.get(v, ()):
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
            out.append(comp)

    for v in nodes:
        if v not in index:
            strong(v)
    return out


def evaluate_all(sheets, cells, now):
    """Valeurs de toutes les cellules-formules : {(sid, ref): valeur}.

    Le graphe de dépendances est construit sur les cellules-formules ; une composante
    fortement connexe cyclique (ou une boucle sur soi-même) donne #CIRC! ; l'ordre
    de calcul est l'ordre topologique des composantes.
    """
    ev = _Evaluator(sheets, cells, now)
    formulas = {}
    for sid, cs in cells.items():
        for ref, (c, k) in cs.items():
            if k != "f":
                continue
            try:
                formulas[(sid, ref)] = parse_formula(c)
            except _SynErr:
                ev.memo[(sid, ref)] = Err("#SYNTAXE!")
    edges = {}
    for key, ast in formulas.items():
        sid = key[0]
        deps = []
        for sheet, refs in _collect(ast, []):
            tsid = ev.resolve(sheet, sid)
            if tsid is _MISSING:
                continue
            for r in refs:
                if (tsid, r) in formulas:
                    deps.append((tsid, r))
        edges[key] = deps
    for comp in _tarjan(list(formulas), edges):
        key = comp[0]
        if len(comp) > 1 or key in edges[key]:
            for k2 in comp:
                ev.memo[k2] = Err("#CIRC!")
            continue
        v = ev.eval(formulas[key], key[0])
        if v is None:
            v = 0
        if isinstance(v, _Range):
            v = Err("#TYPE!")
        ev.memo[key] = v
    return ev.memo


def fmt_value(v, tz):
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _csv_text(v, tz):
    if v is None:
        return ""
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# ------------------------------------------------------------ CSV

def _parse_csv(text):
    """Analyseur CSV : guillemets, guillemets doublés, CRLF, sauts de ligne dans un champ.

    Lève _CsvErr(ligne) si un guillemet n'est jamais fermé.
    """
    rows = []
    i, line, n = 0, 1, len(text)
    while i < n:
        start = line
        row = []
        while True:
            field = []
            if i < n and text[i] == '"':
                i += 1
                while True:
                    if i >= n:
                        raise _CsvErr(start)
                    ch = text[i]
                    if ch == '"':
                        if i + 1 < n and text[i + 1] == '"':
                            field.append('"')
                            i += 2
                            continue
                        i += 1
                        break
                    if ch == "\n":
                        line += 1
                    field.append(ch)
                    i += 1
            while i < n and text[i] not in ",\r\n":
                field.append(text[i])
                i += 1
            row.append("".join(field))
            if i >= n:
                break
            if text[i] == ",":
                i += 1
                continue
            if text[i] == "\r":
                i += 1
            if i < n and text[i] == "\n":
                i += 1
            line += 1
            break
        rows.append(row)
    return rows


# ------------------------------------------------------------ serveur

def _rewrite_all(cells, old, new):
    """Réécrit les formules qui visent l'ancien nom (enregistrements à 2 ou 4 champs)."""
    for cs in cells.values():
        for ref, rec in list(cs.items()):
            if rec[1] == "f" and rec[0] is not None:
                nc = rename_refs(rec[0], old, new)
                if nc != rec[0]:
                    cs[ref] = (nc,) + tuple(rec[1:])


def _name_taken(items, sid, new):
    """Nom de feuille déjà pris : comparaison insensible à la casse avec les autres feuilles,
    et identité exacte avec la feuille elle-même (sid, None pour un ajout)."""
    key = new.casefold()
    for s, n in items:
        if s == sid:
            if n == new:
                return True
        elif n.casefold() == key:
            return True
    return False


class Server:
    """Autorité : ordre d'arrivée, conflits par cellule, historique, droits."""

    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.sheets = [("s1", "Feuille1")]
        self.cells = {"s1": {}}          # sid -> {ref: (contenu, genre, derniere_op, conflit)}
        self.rights = {}                 # (sid, personne) -> niveau
        self.versions = []
        self.seen = {}                   # op_id -> alerte (None si acceptee)
        self.presence = {}
        self.clients = set()
        self._seq = 0
        net.register(SERVER, self)

    def snapshot(self):
        return {
            "owner": self.owner,
            "sheets": list(self.sheets),
            "cells": {sid: dict(cs) for sid, cs in self.cells.items()},
            "rights": dict(self.rights),
            "versions": list(self.versions),
            "presence": dict(self.presence),
        }

    def publish(self):
        snap = self.snapshot()
        for c in sorted(self.clients):
            self.net.send(SERVER, c, ("snap", snap))

    def peer_left(self, name):
        self.presence.pop(name, None)
        self.publish()

    def receive(self, src, payload):
        kind = payload[0]
        self.clients.add(src)
        if kind == "sync":
            self.net.send(SERVER, src, ("snap", self.snapshot()))
        elif kind == "op":
            self._op(src, payload[1])
        elif kind == "right":
            _, sid, person, level = payload
            if src == self.owner and any(s == sid for s, _ in self.sheets):
                self.rights[(sid, person)] = level
                self.publish()
        elif kind == "presence":
            _, sheet, ref = payload
            self.presence[src] = (sheet, ref)
            self.publish()

    def _can_write(self, author, sid):
        return author == self.owner or self.rights.get((sid, author)) == W

    def _check(self, op):
        author = op["author"]
        names = dict(self.sheets)
        for a in op["actions"]:
            t, sid = a[0], a[1]
            if t == "add":
                if _name_taken(self.sheets, None, a[2]) or sid in names:
                    return ("nom_existant", a[2], None)
                continue
            sheet = op["names"].get(sid)
            if sid not in names:
                return ("feuille_supprimee", sheet, None)
            if not self._can_write(author, sid):
                return ("modification_rejetee", sheet, a[2] if t == "cell" else None)
            if t == "del" and len(names) <= 1:
                return (None, None, None)
            if t == "rename" and _name_taken(self.sheets, sid, a[2]):
                return ("nom_existant", sheet, None)
        return None

    def _op(self, src, op):
        oid = op["id"]
        if oid in self.seen:
            self.net.send(SERVER, src, ("ack", oid, self.seen[oid]))
            return
        alert = self._check(op)
        if alert is not None:
            self.seen[oid] = alert
            self.net.send(SERVER, src, ("ack", oid, alert))
            return
        author = op["author"]
        scope = set()
        restore = False
        changed = False
        for a in op["actions"]:
            t, sid = a[0], a[1]
            if t == "cell":
                ref, rec, prev = a[2], a[3], a[4]
                cs = self.cells[sid]
                cur = cs.get(ref)
                cur_last = cur[2] if cur else None
                cur_c = (cur[0], cur[1]) if cur else (None, None)
                if prev == cur_last or cur_c == rec:
                    cs[ref] = (rec[0], rec[1], oid, None)
                    scope.add(sid)
                    changed = True
                else:
                    base = cur if cur else (None, None, None, None)
                    cs[ref] = (base[0], base[1], base[2], (rec[0], rec[1], author))
            elif t == "add":
                name, cells = a[2], a[3]
                self.sheets.append((sid, name))
                self.cells[sid] = {r: (c, k, oid, None) for r, (c, k) in cells.items() if c is not None}
                self.rights[(sid, author)] = W
                scope.add(sid)
                changed = True
            elif t == "del":
                self.sheets = [s for s in self.sheets if s[0] != sid]
                self.cells.pop(sid, None)
                for key in [k for k in self.rights if k[0] == sid]:
                    del self.rights[key]
                scope.add(sid)
                changed = True
            elif t == "rename":
                old = dict(self.sheets)[sid]
                new = a[2]
                self.sheets = [(s, new if s == sid else n) for s, n in self.sheets]
                _rewrite_all(self.cells, old, new)
                scope.add(sid)
                changed = True
            elif t == "restore":
                name, cells = a[2], a[3]
                self.sheets = [(s, name if s == sid else n) for s, n in self.sheets]
                self.cells[sid] = {r: (c, k, oid, None) for r, (c, k) in cells.items() if c is not None}
                scope.add(sid)
                restore = True
                changed = True
        self.seen[oid] = None
        if changed:
            self._seq += 1
            names = dict(self.sheets)
            snap = {}
            for sid in scope:
                if sid in self.cells:
                    snap[sid] = (names[sid], {r: (c, k) for r, (c, k, _, _) in self.cells[sid].items()
                                              if c is not None})
            self.versions.append(Version(self._seq, author, op["instant"],
                                         "restauration" if restore else "modification",
                                         frozenset(scope), snap))
        self.publish()
        self.net.send(SERVER, src, ("ack", oid, None))


# ------------------------------------------------------------ copie locale

def _empty_snap():
    return {"owner": None, "sheets": [], "cells": {}, "rights": {}, "versions": [], "presence": {}}


class Client:
    """Copie locale d'une personne : dernière synchro + opérations en attente (overlay)."""

    def __init__(self, net, clock, name, tz="UTC", _disk=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.disk = _disk if _disk is not None else {"base": _empty_snap(), "outbox": [], "seq": 0}
        self.undo_stack = []
        self.redo_stack = []
        self.alert_list = []
        self.active = None
        self.viewing = None
        net.register(name, self)
        net.send(name, SERVER, ("sync",))

    # --- réseau -----------------------------------------------------------

    def receive(self, src, payload):
        kind = payload[0]
        if kind == "snap":
            self.disk["base"] = payload[1]
        elif kind == "ack":
            _, oid, alert = payload
            self.disk["outbox"] = [o for o in self.disk["outbox"] if o["id"] != oid]
            if alert and alert[0]:
                self.alert_list.append(Alert(*alert))

    def on_connect(self):
        self.net.send(self.name, SERVER, ("sync",))
        for op in self.disk["outbox"]:
            op["sent"] = True
            self.net.send(self.name, SERVER, ("op", op))

    # --- état affiché = dernière synchro + opérations en attente ----------

    def _display(self):
        base = self.disk["base"]
        sheets = list(base["sheets"])
        cells = {sid: {r: (rec[0], rec[1]) for r, rec in cs.items() if rec[0] is not None}
                 for sid, cs in base["cells"].items()}
        rights = dict(base["rights"])
        for op in self.disk["outbox"]:
            for a in op["actions"]:
                t, sid = a[0], a[1]
                if t == "cell":
                    rec = a[3]
                    m = cells.setdefault(sid, {})
                    if rec[0] is None:
                        m.pop(a[2], None)
                    else:
                        m[a[2]] = (rec[0], rec[1])
                elif t == "add":
                    sheets.append((sid, a[2]))
                    cells[sid] = {r: (c, k) for r, (c, k) in a[3].items() if c is not None}
                    rights[(sid, op["author"])] = W
                elif t == "del":
                    sheets = [s for s in sheets if s[0] != sid]
                    cells.pop(sid, None)
                elif t == "rename":
                    old = dict(sheets).get(sid)
                    if old is not None:
                        sheets = [(s, a[2] if s == sid else n) for s, n in sheets]
                        _rewrite_all(cells, old, a[2])
                elif t == "restore":
                    if sid in dict(sheets):
                        sheets = [(s, a[2] if s == sid else n) for s, n in sheets]
                        cells[sid] = {r: (c, k) for r, (c, k) in a[3].items() if c is not None}
        return sheets, cells, rights

    def _view_cells(self, cells):
        if self.viewing is None:
            return cells
        v = self._version(self.viewing)
        if v is not None:
            for sid, (_, snapcells) in v.snap.items():
                if sid in cells:
                    cells[sid] = dict(snapcells)
        return cells

    def _version(self, vid):
        for v in self.disk["base"]["versions"]:
            if v.id == vid:
                return v
        return None

    def _lookup(self, sheets, sheet):
        if sheet is not None:
            name = sheet
        elif self.active is not None:
            name = self.active
        else:
            name = sheets[0][1] if sheets else None
        for s, n in sheets:
            if n == name:
                return s, n
        return None, name

    def _writable(self, sid, rights):
        if self.name == self.disk["base"]["owner"]:
            return True
        return rights.get((sid, self.name)) == W

    def _cur(self, sid, ref):
        _, cells, _ = self._display()
        return cells.get(sid, {}).get(ref, (None, None))

    def _holds(self, checks):
        sheets, cells, _ = self._display()
        names = dict(sheets)
        for c in checks:
            if c[0] == "cell":
                if cells.get(c[1], {}).get(c[2], (None, None)) != c[3]:
                    return False
            elif c[0] == "sheet":
                if names.get(c[1]) != c[2]:
                    return False
            elif c[0] == "absent":
                if c[1] in names:
                    return False
        return True

    def _impossible(self, entry):
        sheets, _, _ = self._display()
        names = dict(sheets)
        for c in entry["after"] + entry["before"]:
            if c[0] == "cell":
                self.alert_list.append(Alert("annulation_impossible", names.get(c[1]), c[2]))
                return
        self.alert_list.append(Alert("annulation_impossible"))

    # --- opérations -------------------------------------------------------

    def _prev(self, sid, ref):
        for op in reversed(self.disk["outbox"]):
            if any(a[0] == "cell" and a[1] == sid and a[2] == ref for a in op["actions"]):
                return op["id"]
        rec = self.disk["base"]["cells"].get(sid, {}).get(ref)
        return rec[2] if rec is not None else None

    def _submit(self, actions):
        sheets, _, _ = self._display()
        names = dict(sheets)
        acts = []
        for a in actions:
            if a[0] == "cell":
                acts.append(("cell", a[1], a[2], a[3], self._prev(a[1], a[2])))
            else:
                acts.append(a)
        for a in acts:
            if a[0] == "add":
                names[a[1]] = a[2]
        self.disk["seq"] += 1
        op = {
            "id": f"{self.name}-{self.disk['seq']}",
            "author": self.name,
            "instant": self.clock.now(),
            "actions": acts,
            "names": names,
            "sent": False,
        }
        self.disk["outbox"].append(op)
        if self.net.is_online(self.name):
            op["sent"] = True
            self.net.send(self.name, SERVER, ("op", op))
        return op["id"]

    def _run(self, actions):
        sheets, _, rights = self._display()
        names = dict(sheets)
        for a in actions:
            t, sid = a[0], a[1]
            if t == "add":
                continue
            if sid not in names:
                return None
            if not self._writable(sid, rights):
                self.alert_list.append(Alert("droit_insuffisant", names[sid],
                                             a[2] if t == "cell" else None))
                return None
            if t == "del" and len(names) <= 1:
                return None
        return self._submit(actions)

    def _record(self, fwd, bwd, after, before):
        oid = self._run(fwd)
        if oid is None:
            return False
        self.undo_stack.append({"fwd": fwd, "bwd": bwd, "after": after, "before": before, "op": oid})
        self.redo_stack.clear()
        return True

    def _edit(self, changes):
        _, cells, _ = self._display()
        fwd, bwd, after, before = [], [], [], []
        for sid, ref, rec in changes:
            cur = cells.get(sid, {}).get(ref, (None, None))
            fwd.append(("cell", sid, ref, rec))
            bwd.append(("cell", sid, ref, cur))
            after.append(("cell", sid, ref, rec))
            before.append(("cell", sid, ref, cur))
        return self._record(fwd, bwd, after, before)

    def set_cell(self, ref, text, sheet=None):
        if self.viewing is not None:
            return
        sheets, _, _ = self._display()
        sid, _ = self._lookup(sheets, sheet)
        if sid is None:
            return
        if text.startswith("="):
            rec = (text, "f")
        else:
            rec = (_normalize_text(text, self.tz), "v")
        self._edit([(sid, ref, rec)])

    def clear(self, ref, sheet=None):
        if self.viewing is not None:
            return
        sheets, _, _ = self._display()
        sid, _ = self._lookup(sheets, sheet)
        if sid is None:
            return
        self._edit([(sid, ref, (None, None))])

    def undo(self):
        if self.viewing is not None or not self.undo_stack:
            return
        e = self.undo_stack[-1]
        if not self._holds(e["after"]):
            self.undo_stack.pop()
            self._impossible(e)
            return
        ob = self.disk["outbox"]
        if e.get("op") and ob and ob[-1]["id"] == e["op"] and not ob[-1]["sent"]:
            ob.pop()
        elif self._run(e["bwd"]) is None:
            return
        self.undo_stack.pop()
        e["op"] = None
        self.redo_stack.append(e)

    def redo(self):
        if self.viewing is not None or not self.redo_stack:
            return
        e = self.redo_stack[-1]
        if not self._holds(e["before"]):
            self.redo_stack.pop()
            self._impossible(e)
            return
        oid = self._run(e["fwd"])
        if oid is None:
            return
        self.redo_stack.pop()
        e["op"] = oid
        self.undo_stack.append(e)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def add_sheet(self, name):
        if self.viewing is not None:
            return
        sheets, _, _ = self._display()
        if _name_taken(sheets, None, name):
            self.alert_list.append(Alert("nom_existant", name))
            return
        self.disk["seq"] += 1
        sid = f"{self.name}:{self.disk['seq']}"
        self._record([("add", sid, name, {})], [("del", sid)],
                     [("sheet", sid, name)], [("absent", sid)])

    def delete_sheet(self, name):
        if self.viewing is not None:
            return
        sheets, cells, rights = self._display()
        sid, nm = self._lookup(sheets, name)
        if sid is None:
            return
        if not self._writable(sid, rights):
            self.alert_list.append(Alert("droit_insuffisant", nm))
            return
        if len(sheets) <= 1:
            return
        pre = dict(cells.get(sid, {}))
        self._record([("del", sid)], [("add", sid, nm, pre)],
                     [("absent", sid)], [("sheet", sid, nm)])

    def rename_sheet(self, old, new):
        if self.viewing is not None:
            return
        sheets, _, rights = self._display()
        sid, nm = self._lookup(sheets, old)
        if sid is None:
            return
        if not self._writable(sid, rights):
            self.alert_list.append(Alert("droit_insuffisant", nm))
            return
        if _name_taken(sheets, sid, new):
            self.alert_list.append(Alert("nom_existant", nm))
            return
        self._record([("rename", sid, new)], [("rename", sid, nm)],
                     [("sheet", sid, new)], [("sheet", sid, nm)])

    def sheets(self):
        return [n for _, n in self._display()[0]]

    def activate(self, name):
        self.active = name

    def set_timezone(self, tz):
        self.tz = tz

    def set_right(self, person, sheet, level):
        if self.viewing is not None or self.name != self.disk["base"]["owner"]:
            return
        sheets, _, _ = self._display()
        sid, _ = self._lookup(sheets, sheet)
        if sid is None or not self.net.is_online(self.name):
            return
        self.net.send(self.name, SERVER, ("right", sid, person, level))

    def right(self, person, sheet=None):
        sheets, _, rights = self._display()
        sid, _ = self._lookup(sheets, sheet)
        if sid is None:
            return None
        if person == self.disk["base"]["owner"]:
            return W
        return rights.get((sid, person))

    # --- lecture ----------------------------------------------------------

    def _values(self):
        sheets, cells, _ = self._display()
        cells = self._view_cells(cells)
        return sheets, cells, evaluate_all(sheets, cells, self.clock.now())

    def _result(self, ref, sheet):
        sheets, cells, memo = self._values()
        sid, _ = self._lookup(sheets, sheet)
        if sid is None:
            return None
        rec = cells.get(sid, {}).get(ref)
        if rec is None:
            return None
        if rec[1] == "f":
            return memo.get((sid, ref))
        return _classify(rec[0], rec[1])

    def content(self, ref, sheet=None):
        sheets, cells, _ = self._display()
        sid, _ = self._lookup(sheets, sheet)
        cells = self._view_cells(cells)
        rec = cells.get(sid, {}).get(ref)
        return rec[0] if rec is not None else None

    def value(self, ref, sheet=None):
        v = self._result(ref, sheet)
        if isinstance(v, Err):
            return v.code
        return fmt_value(v, self.tz)

    def error(self, ref, sheet=None):
        v = self._result(ref, sheet)
        return v.code if isinstance(v, Err) else None

    def alerts(self):
        return list(self.alert_list)

    def connection_status(self):
        return "en ligne" if self.net.is_online(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.disk["outbox"])

    def select(self, ref, sheet=None):
        sheets, _, _ = self._display()
        _, nm = self._lookup(sheets, sheet)
        if nm is None or not self.net.is_online(self.name):
            return
        self.net.send(self.name, SERVER, ("presence", nm, ref))

    def presence(self):
        if not self.net.is_online(self.name):
            return {}
        return {n: v for n, v in self.disk["base"]["presence"].items() if n != self.name}

    def conflict(self, ref, sheet=None):
        sheets, _, _ = self._display()
        sid, _ = self._lookup(sheets, sheet)
        rec = self.disk["base"]["cells"].get(sid, {}).get(ref)
        if rec is None or rec[3] is None:
            return None
        return Conflict(rec[3][0], rec[3][2])

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.viewing is not None:
            return
        sheets, _, _ = self._display()
        sid, _ = self._lookup(sheets, sheet)
        rec = self.disk["base"]["cells"].get(sid, {}).get(ref)
        if rec is None or rec[3] is None:
            return
        new = (rec[3][0], rec[3][1]) if use_discarded else (rec[0], rec[1])
        self._edit([(sid, ref, new)])

    # --- historique, versions ---------------------------------------------

    def history(self, sheet=None):
        sheets, _, _ = self._display()
        sid = None
        if sheet is not None:
            sid, _ = self._lookup(sheets, sheet)
        out = []
        for v in self.disk["base"]["versions"]:
            if sheet is not None and sid not in v.scope:
                continue
            out.append(VersionView(v, self.tz))
        out.sort(key=lambda x: (x.instant, x.id), reverse=True)
        return out

    def open_version(self, vid):
        if self._version(vid) is not None:
            self.viewing = vid

    def close_version(self):
        self.viewing = None

    def restore_version(self, vid):
        if self.viewing is not None:
            return
        v = self._version(vid)
        if v is None:
            return
        sheets, cells, _ = self._display()
        names = dict(sheets)
        fwd, bwd, after, before = [], [], [], []
        for sid, (name, snapcells) in v.snap.items():
            if sid not in names:
                continue
            cur = dict(cells.get(sid, {}))
            fwd.append(("restore", sid, name, dict(snapcells)))
            bwd.append(("restore", sid, names[sid], cur))
            after.append(("sheet", sid, name))
            before.append(("sheet", sid, names[sid]))
            for r in set(cur) | set(snapcells):
                after.append(("cell", sid, r, snapcells.get(r, (None, None))))
                before.append(("cell", sid, r, cur.get(r, (None, None))))
        if fwd:
            self._record(fwd, bwd, after, before)

    # --- export / import CSV ----------------------------------------------

    def export_csv(self):
        sheets, cells, memo = self._values()
        sid, _ = self._lookup(sheets, None)
        m = cells.get(sid, {})
        grid = {}
        maxc = 0
        for ref in m:
            mm = _CELLREF.fullmatch(ref)
            if mm is None:
                continue
            c = _colnum(mm.group(1))
            grid.setdefault(int(mm.group(2)), {})[c] = ref
            maxc = max(maxc, c)
        buf = io.StringIO()
        writer = csv.writer(buf)
        for r in sorted(grid):
            row = []
            for c in range(1, maxc + 1):
                ref = grid[r].get(c)
                if ref is None:
                    row.append("")
                    continue
                rec = m[ref]
                v = memo.get((sid, ref)) if rec[1] == "f" else _classify(rec[0], rec[1])
                row.append(_csv_text(v, self.tz))
            if any(x != "" for x in row):
                writer.writerow(row)
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.viewing is not None:
            return
        text = bytes(data).decode("utf-8-sig")
        sheets, _, rights = self._display()
        sid, nm = self._lookup(sheets, None)
        if sid is None:
            return
        if not self._writable(sid, rights):
            self.alert_list.append(Alert("droit_insuffisant", nm))
            return
        try:
            rows = _parse_csv(text)
        except _CsvErr as e:
            self.alert_list.append(Alert("csv_invalide", nm, None, e.line))
            return
        changes = []
        for r, row in enumerate(rows, start=1):
            if row == [""]:
                continue
            for c, field in enumerate(row, start=1):
                ref = f"{_colname(c)}{r}"
                if field == "":
                    rec = (None, None)
                elif field.startswith("="):
                    rec = (field, "v")
                else:
                    rec = (_normalize_text(field, self.tz), "v")
                changes.append((sid, ref, rec))
        if changes:
            self._edit(changes)

    # --- cycle de vie -----------------------------------------------------

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz, _disk=self.disk)

    def set_viewing_none(self):
        self.viewing = None
