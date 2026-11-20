"""Classeur collaboratif hors ligne — couche code, tour 1.

Structure :
- Clock, Network : temps simulé et réseau simulé en mémoire (messages retardables, coupables).
- Analyseur et calcul de formules : graphe de dépendances, cycles détectés par composantes fortement connexes.
- Book : état d'un classeur (feuilles, cellules avec numéro de séquence, droits, versions, présence).
- Server : copie faisant autorité ; applique les opérations reçues et diffuse son état.
- Client : copie locale par personne ; applique ses saisies tout de suite et les garde en attente
  tant que le serveur ne les a pas acquittées.
"""
import csv
import io
import itertools
import re
import sys
from collections import deque
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.setrecursionlimit(100000)

UTC = timezone.utc
W = "écriture"
R = "lecture"

SYN = "#SYNTAXE!"
TYPE_ = "#TYPE!"
DIV = "#DIV/0!"
CIRC = "#CIRC!"
REF = "#REF!"

_ids = itertools.count(1)


def _new_id():
    return next(_ids)


# ------------------------------------------------------------------ temps et réseau

class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line

    def __repr__(self):
        return f"Alert({self.kind!r}, {self.sheet!r}, {self.cell!r}, {self.line!r})"


class Network:
    def __init__(self):
        self.queue = deque()      # (src, dst, msg) en vol, FIFO
        self.down = set()         # personnes coupées du réseau
        self.nodes = {}           # nom -> nœud (serveur "server" ou client)
        self.stores = {}          # stockage de l'appareil, par personne

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def _deliver(self, src, dst, msg):
        # un message est perdu si l'émetteur ou le destinataire est coupé au moment de la livraison
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, msg)

    def deliver_all(self):
        while self.queue:
            src, dst, msg = self.queue.popleft()
            self._deliver(src, dst, msg)

    def deliver_from(self, name):
        matched, rest = [], []
        for item in self.queue:
            (matched if item[0] == name else rest).append(item)
        self.queue.clear()
        for src, dst, msg in matched:
            self._deliver(src, dst, msg)
        new = list(self.queue)
        self.queue.clear()
        self.queue.extend(rest)
        self.queue.extend(new)

    def disconnect(self, name):
        self.down.add(name)
        srv = self.nodes.get("server")
        if srv is not None:
            srv.peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and name != "server":
            node.on_connect()


# ------------------------------------------------------------------ références, littéraux, CSV

_REF_RE = re.compile(r"([A-Z]{1,3})(\d+)")


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def norm_ref(ref):
    r = ref.replace("$", "").upper()
    if _REF_RE.fullmatch(r) is None:
        raise ValueError(f"référence invalide : {ref!r}")
    return r


def split_ref(ref):
    m = _REF_RE.fullmatch(ref)
    return col_index(m.group(1)), int(m.group(2))


_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DT_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})?"
)


def _fixed_offset(off):
    sign = 1 if off[0] == "+" else -1
    hh, mm = int(off[1:3]), int(off[4:6])
    return timezone(sign * timedelta(hours=hh, minutes=mm))


def classify(raw, lit, tz):
    """Retourne (raw, lit, instant). Un instant n'existe que pour une date-heure saisie."""
    if raw is None:
        return None, False, None
    if lit or raw.startswith("="):
        return raw, lit, None
    m = _DT_RE.fullmatch(raw)
    if m is None:
        return raw, False, None
    y, mo, d, h, mi, s, off = m.groups()
    if off:
        tzinfo = UTC if off == "Z" else _fixed_offset(off)
    else:
        tzinfo = ZoneInfo(tz)   # sans décalage : interprété dans le fuseau de l'auteur
    naive = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s) if s else 0)
    inst = naive.replace(tzinfo=tzinfo).astimezone(UTC)
    return raw, False, inst


def literal_value(raw):
    if _INT_RE.fullmatch(raw):
        return int(raw)
    if _FLOAT_RE.fullmatch(raw):
        return float(raw)
    if _DATE_RE.fullmatch(raw):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return raw
    return raw


def fmt_instant(inst, tz):
    return inst.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


def parse_csv(text):
    """Retourne (lignes, None) ou (None, ligne_invalide) si un guillemet n'est jamais fermé."""
    rows, row, field = [], [], []
    i, n, line, rec_line, inq = 0, len(text), 1, 1, False
    while i < n:
        c = text[i]
        if inq:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                inq = False
            else:
                if c == "\n":
                    line += 1
                field.append(c)
            i += 1
            continue
        if c == '"':
            inq = True
        elif c == ",":
            row.append("".join(field))
            field = []
        elif c in "\r\n":
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
            line += 1
            rec_line = line
        else:
            field.append(c)
        i += 1
    if inq:
        return None, rec_line
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows, None


# ------------------------------------------------------------------ formules

class CellError:
    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return f"CellError({self.code!r})"


class FormulaError(Exception):
    pass


_TOK_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<sref>[^\W\d_]\w*!\$?[A-Za-z]{1,3}\$?\d+)"
    r"|(?P<ref>\$?[A-Za-z]{1,3}\$?\d+(?![\w(!]))"
    r"|(?P<func>[^\W\d_]\w*\()"
    r"|(?P<op>[-+*/(),:])"
)


def _tokenize(src):
    toks, pos, n = [], 0, len(src)
    while True:
        while pos < n and src[pos].isspace():
            pos += 1
        if pos >= n:
            return toks
        m = _TOK_RE.match(src, pos)
        if m is None:
            raise FormulaError("caractère inattendu")
        toks.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()


def _split_ref_token(kind, v):
    if kind == "sref":
        sheet, r = v.split("!", 1)
        return sheet, norm_ref(r)
    return None, norm_ref(v)


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def _peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def _take(self):
        tok = self._peek()
        self.i += 1
        return tok

    def _is_op(self, ops):
        k, v = self._peek()
        return k == "op" and v in ops

    def expr(self):
        node = self.term()
        while self._is_op("+-"):
            op = self._take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self._is_op("*/"):
            op = self._take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self._is_op("-"):
            self._take()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        k, v = self._take()
        if k == "num":
            return ("num", float(v) if "." in v else int(v))
        if k in ("ref", "sref"):
            sheet, r = _split_ref_token(k, v)
            if self._is_op(":"):
                self._take()
                k2, v2 = self._take()
                if k2 != "ref":
                    raise FormulaError("plage invalide")
                return ("range", sheet, r, norm_ref(v2))
            return ("ref", sheet, r)
        if k == "func":
            name = v[:-1].upper()
            args = []
            if self._is_op(")"):
                self._take()
            else:
                while True:
                    args.append(self.expr())
                    if self._is_op(","):
                        self._take()
                        continue
                    if self._is_op(")"):
                        self._take()
                        break
                    raise FormulaError("parenthèse manquante")
            return ("call", name, args)
        if k == "op" and v == "(":
            node = self.expr()
            if not self._is_op(")"):
                raise FormulaError("parenthèse fermante manquante")
            self._take()
            return node
        raise FormulaError("expression incomplète")


_AST_CACHE = {}


def parse_formula(raw):
    """raw commence par '='. Retourne l'arbre, ou None si la syntaxe est invalide."""
    if raw in _AST_CACHE:
        return _AST_CACHE[raw]
    node = None
    try:
        toks = _tokenize(raw[1:])
        if toks:
            p = _Parser(toks)
            node = p.expr()
            if p.i != len(toks):
                node = None
    except (FormulaError, ValueError):
        node = None
    _AST_CACHE[raw] = node
    return node


def _range_refs(a, b):
    c1, r1 = split_ref(a)
    c2, r2 = split_ref(b)
    out = []
    for c in range(min(c1, c2), max(c1, c2) + 1):
        for r in range(min(r1, r2), max(r1, r2) + 1):
            out.append(f"{col_letters(c)}{r}")
    return out


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _cyclic_nodes(nodes, edges):
    """Composantes fortement connexes (Tarjan) : renvoie les nœuds placés sur un cycle."""
    index, low, on, stack, out = {}, {}, set(), [], set()
    counter = itertools.count()

    def strong(v):
        index[v] = low[v] = next(counter)
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
            if len(comp) > 1 or v in edges.get(v, ()):
                out.update(comp)

    for v in nodes:
        if v not in index:
            strong(v)
    return out


def _arith(op, a, b):
    if isinstance(a, CellError):
        return a
    if isinstance(b, CellError):
        return b
    if _is_num(a) and _is_num(b):
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            return CellError(DIV)
        return a / b
    if op == "-" and isinstance(a, datetime) and isinstance(b, datetime):
        return (a - b).total_seconds() / 86400
    if (op == "-" and isinstance(a, date) and isinstance(b, date)
            and not isinstance(a, datetime) and not isinstance(b, datetime)):
        return (a - b).days
    return CellError(TYPE_)


def display(v, tz):
    if v is None:
        return None
    if isinstance(v, CellError):
        return v.code
    if isinstance(v, datetime):
        return fmt_instant(v, tz)
    if isinstance(v, date):
        return v.isoformat()
    return v


def plain(v, tz):
    """Texte d'une cellule dans un export CSV."""
    if v is None:
        return ""
    if isinstance(v, CellError):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(tz)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


class Calc:
    """Calcul d'un état de classeur. Les cycles sont trouvés sur le graphe de dépendances."""

    def __init__(self, book, now, tz):
        self.b = book
        self.now = now
        self.tz = tz
        self.memo = {}
        self._cyc = None

    def _refs_of(self, node, sid):
        t = node[0]
        out = []
        if t == "ref":
            tsid = sid if node[1] is None else self.b.sid_by_name(node[1])
            if tsid is not None:
                out.append((tsid, node[2]))
        elif t == "range":
            tsid = sid if node[1] is None else self.b.sid_by_name(node[1])
            if tsid is not None:
                out.extend((tsid, r) for r in _range_refs(node[2], node[3]))
        elif t == "neg":
            out += self._refs_of(node[1], sid)
        elif t == "bin":
            out += self._refs_of(node[2], sid) + self._refs_of(node[3], sid)
        elif t == "call":
            for a in node[2]:
                out += self._refs_of(a, sid)
        return out

    def cyclic(self):
        if self._cyc is None:
            edges = {}
            for (sid, ref), c in self.b.cells.items():
                raw = c["raw"]
                if raw is None or c["lit"] or c["inst"] is not None or not raw.startswith("="):
                    continue
                node = parse_formula(raw)
                if node is None:
                    continue
                edges[(sid, ref)] = self._refs_of(node, sid)
            for k in list(edges):
                edges[k] = [t for t in edges[k] if t in edges]
            self._cyc = _cyclic_nodes(list(edges), edges)
        return self._cyc

    def value(self, sid, ref):
        key = (sid, ref)
        if key in self.memo:
            return self.memo[key]
        if key in self.cyclic():
            res = CellError(CIRC)
        else:
            res = self._compute(sid, ref)
        self.memo[key] = res
        return res

    def _compute(self, sid, ref):
        c = self.b.cells.get((sid, ref))
        if c is None or c["raw"] is None:
            return None
        if c["inst"] is not None:
            return c["inst"]
        raw = c["raw"]
        if c["lit"]:
            return raw
        if raw.startswith("="):
            node = parse_formula(raw)
            if node is None:
                return CellError(SYN)
            return self._ev(node, sid)
        return literal_value(raw)

    def _ev(self, node, sid):
        t = node[0]
        if t == "num":
            return node[1]
        if t == "ref":
            tsid = sid if node[1] is None else self.b.sid_by_name(node[1])
            if tsid is None:
                return CellError(REF)
            v = self.value(tsid, node[2])
            return 0 if v is None else v
        if t == "range":
            return CellError(TYPE_)
        if t == "neg":
            v = self._ev(node[1], sid)
            if isinstance(v, CellError):
                return v
            if _is_num(v):
                return -v
            return CellError(TYPE_)
        if t == "bin":
            a = self._ev(node[2], sid)
            b = self._ev(node[3], sid)
            return _arith(node[1], a, b)
        if t == "call":
            return self._call(node[1], node[2], sid)
        return CellError(SYN)

    def _call(self, name, args, sid):
        if name == "MAINTENANT":
            return self.now if not args else CellError(SYN)
        if name == "SOMME":
            total = 0
            for a in args:
                if a[0] == "range":
                    tsid = sid if a[1] is None else self.b.sid_by_name(a[1])
                    if tsid is None:
                        return CellError(REF)
                    for r in _range_refs(a[2], a[3]):
                        v = self.value(tsid, r)
                        if isinstance(v, CellError):
                            return v
                        if _is_num(v):
                            total += v
                else:
                    v = self._ev(a, sid)
                    if isinstance(v, CellError):
                        return v
                    if not _is_num(v):
                        return CellError(TYPE_)
                    total += v
            return total
        return CellError(SYN)


# ------------------------------------------------------------------ état d'un classeur

def _default_cell():
    return {"raw": None, "lit": False, "inst": None, "seq": 0, "conflict": None}


def bump_set(book, sid, ref, raw, lit, inst):
    c = book.cell(sid, ref)
    c["raw"], c["lit"], c["inst"] = raw, lit, inst
    c["seq"] += 1
    c["conflict"] = None


def rewrite_formulas(book, old, new):
    pat = re.compile(r"(?<!\w)" + re.escape(old) + "!", re.IGNORECASE)
    for c in book.cells.values():
        raw = c["raw"]
        if raw and not c["lit"] and raw.startswith("="):
            c["raw"] = pat.sub(lambda m: new + "!", raw)


def _add_sheet(book, sid, name, author):
    book.names[sid] = name
    if sid not in book.order:
        book.order.append(sid)
    book.rights.setdefault((author, sid), W)


def apply_local(book, op):
    """Applique une opération à un état, sans contrôle de droits ni de conflit."""
    t = op["t"]
    if t == "cell":
        bump_set(book, op["sid"], op["ref"], op["raw"], op["lit"], op["inst"])
    elif t == "cells":
        for ref, raw, lit, inst in op["items"]:
            bump_set(book, op["sid"], ref, raw, lit, inst)
        if op.get("name"):
            book.names[op["sid"]] = op["name"]
    elif t == "add_sheet":
        _add_sheet(book, op["sid"], op["name"], op["author"])
    elif t == "del_sheet":
        if op["sid"] in book.order:
            book.order.remove(op["sid"])
    elif t == "rename":
        book.names[op["sid"]] = op["new"]
        rewrite_formulas(book, op["old"], op["new"])
    elif t == "resolve":
        c = book.cell(op["sid"], op["ref"])
        conf = c["conflict"]
        if conf is not None and op["use"]:
            c["raw"], c["lit"], c["inst"] = conf["raw"], conf["lit"], conf["inst"]
        c["seq"] += 1
        c["conflict"] = None


class Book:
    def __init__(self, owner=None):
        self.owner = owner
        self.names = {}      # sid -> nom (conservé même après suppression)
        self.order = []      # sids des feuilles vivantes, dans l'ordre
        self.cells = {}      # (sid, ref) -> dict
        self.rights = {}     # (personne, sid) -> niveau
        self.versions = []   # entrées immuables partagées entre copies
        self.presence = {}   # personne -> (sid, ref)

    def copy(self):
        b = Book(self.owner)
        b.names = dict(self.names)
        b.order = list(self.order)
        b.cells = {k: dict(v) for k, v in self.cells.items()}
        b.rights = dict(self.rights)
        b.versions = list(self.versions)
        b.presence = dict(self.presence)
        return b

    def sid_by_name(self, name, exclude=None):
        # noms de feuilles comparés sans tenir compte de la casse
        key = name.casefold()
        for sid in self.order:
            if sid != exclude and (self.names.get(sid) or "").casefold() == key:
                return sid
        return None

    def cell(self, sid, ref):
        c = self.cells.get((sid, ref))
        if c is None:
            c = _default_cell()
            self.cells[(sid, ref)] = c
        return c

    def right(self, person, sid):
        if person == self.owner:
            return W
        return self.rights.get((person, sid))


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.book = Book(owner)
        sid = "s0"
        self.book.names[sid] = "Feuille1"
        self.book.order.append(sid)
        self.clients = set()
        self.results = {}
        net.nodes["server"] = self

    def receive(self, src, msg):
        kind = msg[0]
        if kind == "hello":
            self.clients.add(src)
            self.net.send("server", src, ("snap", self.book.copy()))
        elif kind == "op":
            self.clients.add(src)
            op = dict(msg[1])          # copie : ne jamais toucher aux objets du client
            ok, reason = self._handle_op(op, src)
            sid = op.get("sid")
            sheet = self.book.names.get(sid) if sid is not None else op.get("name")
            cell = op.get("ref")
            if cell is None and op.get("items"):
                cell = op["items"][0][0]
            self.net.send("server", src, ("ack", op["id"], ok, reason, sheet, cell))
            self._push()
        elif kind == "right":
            _, person, sid, level = msg
            b = self.book
            if src == b.owner and person != b.owner and sid in b.order and level in (W, R):
                b.rights[(person, sid)] = level
                self._push()
        elif kind == "select":
            _, sid, ref = msg
            self.clients.add(src)
            self.book.presence[src] = (sid, ref)
            self._push()

    def peer_down(self, name):
        self.book.presence.pop(name, None)
        self._push()

    def _push(self):
        snap = self.book.copy()
        for name in sorted(self.clients):
            self.net.send("server", name, ("snap", snap))

    def _handle_op(self, op, src):
        if op["id"] in self.results:
            return self.results[op["id"]]
        op["author"] = src
        res = self._apply(op, src)
        self.results[op["id"]] = res
        return res

    def _apply(self, op, src):
        b = self.book
        t = op["t"]
        sid = op.get("sid")
        if t == "add_sheet":
            if sid in b.order:
                return True, None
            if b.sid_by_name(op["name"]) is not None:
                return False, "nom_existant"
            apply_local(b, op)
            return True, None
        if t == "del_sheet":
            if sid not in b.order:
                return True, None
            if b.right(src, sid) != W:
                return False, "modification_rejetee"
            if len(b.order) <= 1:
                return False, None
            apply_local(b, op)
            return True, None
        if sid not in b.order:
            return False, "feuille_supprimee"
        if b.right(src, sid) != W:
            return False, "modification_rejetee"
        if t == "rename":
            if op["new"] == op["old"]:
                return True, None
            if b.sid_by_name(op["new"], exclude=sid) is not None:
                return False, "nom_existant"
            apply_local(b, op)
            return True, None
        if t == "resolve":
            apply_local(b, op)
            return True, None
        if t == "cell":
            c = b.cell(sid, op["ref"])
            if (op["base"] is not None and c["seq"] != op["base"]
                    and (c["raw"], c["lit"]) != (op["raw"], op["lit"])):
                # modifié entre-temps par un autre : la valeur reçue en premier reste
                c["seq"] += 1
                c["conflict"] = {"raw": op["raw"], "lit": op["lit"], "inst": op["inst"], "by": src}
            else:
                bump_set(b, sid, op["ref"], op["raw"], op["lit"], op["inst"])
            self._record_version(op, "modification")
            return True, None
        if t == "cells":
            apply_local(b, op)
            self._record_version(op, op.get("kind", "modification"))
            return True, None
        return False, None

    def _record_version(self, op, kind):
        sid = op["sid"]
        cells = {}
        for (s, ref), c in self.book.cells.items():
            if s == sid and c["raw"] is not None:
                cells[ref] = (c["raw"], c["lit"], c["inst"])
        self.book.versions.append({
            "id": _new_id(), "sid": sid, "name": self.book.names.get(sid),
            "author": op["author"], "ts": op["ts"], "kind": kind, "cells": cells,
        })


# ------------------------------------------------------------------ client

class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    def __init__(self, e, tz):
        self.id = e["id"]
        self.author = e["author"]
        self.kind = e["kind"]
        self.timestamp = e["ts"].astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


class _Entry:
    def __init__(self, fwd, inv, fwd_id, check, sid):
        self.fwd = fwd
        self.inv = inv
        self.fwd_id = fwd_id
        self.check = check
        self.sid = sid


class Client:
    def __init__(self, net, clock, name, tz="UTC"):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.store = net.stores.setdefault(name, {"snap": None, "pending": []})
        self.alerts_ = []
        self.undo_stack = []
        self.redo_stack = []
        self.active = None
        self.viewing = None
        self.viewbook = None
        net.nodes[name] = self
        self._rebuild()
        if self._connected():
            net.send(name, "server", ("hello",))

    # --- réseau et réplique

    def _connected(self):
        return self.name not in self.net.down

    def receive(self, src, msg):
        if msg[0] == "snap":
            self.store["snap"] = msg[1]
            self._rebuild()
        elif msg[0] == "ack":
            _, op_id, ok, kind, sheet, cell = msg
            self.store["pending"] = [p for p in self.store["pending"] if p["id"] != op_id]
            if not ok and kind:
                self.alerts_.append(Alert(kind, sheet, cell))
            self._rebuild()

    def on_connect(self):
        self.net.send(self.name, "server", ("hello",))
        for op in self.store["pending"]:
            self.net.send(self.name, "server", ("op", op))

    def _rebuild(self):
        snap = self.store["snap"]
        book = snap.copy() if snap is not None else Book()
        for op in self.store["pending"]:
            apply_local(book, op)
        self.replica = book

    def _book(self):
        return self.viewbook if self.viewing is not None else self.replica

    def _active(self, book):
        if self.active in book.order:
            return self.active
        return book.order[0] if book.order else None

    def _sid(self, sheet):
        book = self._book()
        if sheet is None:
            return self._active(book)
        return book.sid_by_name(sheet)

    def _name(self, sid):
        return self.replica.names.get(sid)

    def _can_write(self, sid):
        return sid is not None and self.replica.right(self.name, sid) == W

    def _seq(self, sid, ref):
        c = self.replica.cells.get((sid, ref))
        return c["seq"] if c else 0

    def _cell_tuple(self, sid, ref):
        c = self.replica.cells.get((sid, ref))
        return (c["raw"], c["lit"], c["inst"]) if c else (None, False, None)

    def _materialize(self, spec):
        op = dict(spec)
        op["id"] = f"{self.name}-{_new_id()}"
        op["author"] = self.name
        op["ts"] = self.clock.now()
        if "sid" in op:
            op.setdefault("name", self.replica.names.get(op["sid"]))
        if op["t"] == "cell":
            op["base"] = self._seq(op["sid"], op["ref"])
        return op

    def _submit(self, spec):
        op = self._materialize(spec)
        self.store["pending"].append(op)
        apply_local(self.replica, op)
        if self._connected():
            self.net.send(self.name, "server", ("op", op))
        return op

    def _act(self, fwd, inv, check=None):
        op = self._submit(fwd)
        self.undo_stack.append(_Entry(fwd, inv, op["id"], check, fwd.get("sid")))
        self.redo_stack.clear()

    def _matches(self, check):
        sid, ref, raw, lit = check
        return self._cell_tuple(sid, ref)[:2] == (raw, lit)

    # --- lecture

    def content(self, ref, sheet=None):
        book = self._book()
        sid = self._sid(sheet)
        if sid is None:
            return None
        c = book.cells.get((sid, norm_ref(ref)))
        return c["raw"] if c else None

    def _calc(self):
        return Calc(self._book(), self.clock.now(), self.tz)

    def value(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        return display(self._calc().value(sid, norm_ref(ref)), self.tz)

    def error(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        v = self._calc().value(sid, norm_ref(ref))
        return v.code if isinstance(v, CellError) else None

    def sheets(self):
        book = self._book()
        return [book.names[s] for s in book.order]

    def right(self, person, sheet=None):
        sid = self._sid(sheet)
        return self._book().right(person, sid) if sid is not None else None

    def alerts(self):
        return list(self.alerts_)

    def connection_status(self):
        return "en ligne" if self._connected() else "hors ligne"

    def pending_count(self):
        return len(self.store["pending"])

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        c = self._book().cells.get((sid, norm_ref(ref))) if sid is not None else None
        if c is None or c["conflict"] is None:
            return None
        return Conflict(c["conflict"]["raw"], c["conflict"]["by"])

    def presence(self):
        if not self._connected():
            return {}
        out = {}
        for who, (sid, ref) in self.replica.presence.items():
            if who != self.name and who not in self.net.down:
                out[who] = (self.replica.names.get(sid), ref)
        return out

    def history(self, sheet=None):
        sid = self._sid(sheet)
        ents = [e for e in self.replica.versions if e["sid"] == sid]
        ents.sort(key=lambda e: (e["ts"], e["id"]), reverse=True)
        return [Version(e, self.tz) for e in ents]

    def _version(self, vid):
        for e in self.replica.versions:
            if e["id"] == vid:
                return e
        return None

    # --- saisie

    def set_timezone(self, tz):
        self.tz = tz

    def set_cell(self, ref, text, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = norm_ref(ref)
        if not self._can_write(sid):
            self.alerts_.append(Alert("droit_insuffisant", self._name(sid), ref))
            return
        raw, lit, inst = classify(text, False, self.tz)
        old = self._cell_tuple(sid, ref)
        fwd = {"t": "cell", "sid": sid, "ref": ref, "raw": raw, "lit": lit, "inst": inst}
        inv = {"t": "cell", "sid": sid, "ref": ref, "raw": old[0], "lit": old[1], "inst": old[2]}
        self._act(fwd, inv, check=(sid, ref, raw, lit))

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def import_csv(self, data):
        if self.viewing is not None:
            return
        sid = self._sid(None)
        if sid is None:
            return
        name = self._name(sid)
        if not self._can_write(sid):
            self.alerts_.append(Alert("droit_insuffisant", name, None))
            return
        rows, bad_line = parse_csv(data.decode("utf-8-sig"))
        if rows is None:
            self.alerts_.append(Alert("csv_invalide", name, None, bad_line))
            return
        items = []
        for ri, row in enumerate(rows):
            for ci, field in enumerate(row):
                ref = f"{col_letters(ci + 1)}{ri + 1}"
                if field == "":
                    items.append((ref, None, False, None))
                else:
                    raw, lit, inst = classify(field, field.startswith("="), self.tz)
                    items.append((ref, raw, lit, inst))
        inv_items = [(ref,) + self._cell_tuple(sid, ref) for ref, _, _, _ in items]
        fwd = {"t": "cells", "sid": sid, "items": items, "kind": "modification"}
        inv = {"t": "cells", "sid": sid, "items": inv_items, "kind": "modification"}
        self._act(fwd, inv)

    def export_csv(self):
        book = self._book()
        sid = self._sid(None)
        if sid is None:
            return b""
        occ = [(split_ref(r), (s, r)) for (s, r), c in book.cells.items()
               if s == sid and c["raw"] is not None]
        if not occ:
            return b""
        max_col = max(col for (col, _row), _key in occ)
        by_row = {}
        for (col, row), key in occ:
            by_row.setdefault(row, []).append((col, key))
        calc = self._calc()
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in sorted(by_row):
            line = [""] * max_col
            for col, key in by_row[row]:
                line[col - 1] = plain(calc.value(*key), self.tz)
            writer.writerow(line)
        return buf.getvalue().encode("utf-8")

    # --- feuilles et droits

    def activate(self, name):
        sid = self.replica.sid_by_name(name)
        if sid is not None:
            self.active = sid

    def add_sheet(self, name):
        if self.viewing is not None:
            return
        if self.replica.sid_by_name(name) is not None:
            self.alerts_.append(Alert("nom_existant", name, None))
            return
        sid = f"sh{_new_id()}"
        fwd = {"t": "add_sheet", "sid": sid, "name": name}
        inv = {"t": "del_sheet", "sid": sid}
        self._act(fwd, inv)

    def delete_sheet(self, name):
        if self.viewing is not None:
            return
        sid = self.replica.sid_by_name(name)
        if sid is None:
            return
        if not self._can_write(sid):
            self.alerts_.append(Alert("droit_insuffisant", name, None))
            return
        if len(self.replica.order) <= 1:
            return
        fwd = {"t": "del_sheet", "sid": sid}
        inv = {"t": "add_sheet", "sid": sid, "name": name}
        self._act(fwd, inv)

    def rename_sheet(self, old, new):
        if self.viewing is not None:
            return
        sid = self.replica.sid_by_name(old)
        if sid is None or new == old:
            return
        if not self._can_write(sid):
            self.alerts_.append(Alert("droit_insuffisant", old, None))
            return
        if self.replica.sid_by_name(new, exclude=sid) is not None:
            self.alerts_.append(Alert("nom_existant", new, None))
            return
        fwd = {"t": "rename", "sid": sid, "old": old, "new": new}
        inv = {"t": "rename", "sid": sid, "old": new, "new": old}
        self._act(fwd, inv)

    def set_right(self, person, sheet, level):
        if self.viewing is not None or self.replica.owner != self.name or not self._connected():
            return
        sid = self.replica.sid_by_name(sheet)
        if sid is None or person == self.name:
            return
        self.net.send(self.name, "server", ("right", person, sid, level))

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None or not self._connected() or self.viewing is not None:
            return
        self.net.send(self.name, "server", ("select", sid, norm_ref(ref)))

    # --- conflits

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = norm_ref(ref)
        if not self._can_write(sid):
            self.alerts_.append(Alert("droit_insuffisant", self._name(sid), ref))
            return
        if self.conflict(ref, self._name(sid)) is None:
            return
        self._submit({"t": "resolve", "sid": sid, "ref": ref, "use": bool(use_discarded)})

    # --- annulation

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if self.viewing is not None or not self.undo_stack:
            return
        e = self.undo_stack.pop()
        if e.sid is not None and not self._can_write(e.sid):
            self.alerts_.append(Alert("droit_insuffisant", self._name(e.sid), None))
            return
        if e.check is not None and not self._matches(e.check):
            self.alerts_.append(Alert("annulation_impossible", self._name(e.sid), e.check[1]))
            return
        pending_ids = {p["id"] for p in self.store["pending"]}
        if not self._connected() and e.fwd_id in pending_ids:
            # action encore hors ligne : on la retire de la file, rien n'est envoyé
            self.store["pending"] = [p for p in self.store["pending"] if p["id"] != e.fwd_id]
            self._rebuild()
            e.fwd_id = None
        else:
            self._submit(e.inv)
        self.redo_stack.append(e)

    def redo(self):
        if self.viewing is not None or not self.redo_stack:
            return
        e = self.redo_stack.pop()
        if e.sid is not None and not self._can_write(e.sid):
            self.alerts_.append(Alert("droit_insuffisant", self._name(e.sid), None))
            return
        op = self._submit(e.fwd)
        e.fwd_id = op["id"]
        self.undo_stack.append(e)

    # --- versions

    def open_version(self, vid):
        e = self._version(vid)
        if e is None:
            return
        vb = self.replica.copy()
        sid = e["sid"]
        vb.cells = {k: v for k, v in vb.cells.items() if k[0] != sid}
        for ref, (raw, lit, inst) in e["cells"].items():
            vb.cells[(sid, ref)] = {"raw": raw, "lit": lit, "inst": inst, "seq": 0, "conflict": None}
        if e["name"]:
            vb.names[sid] = e["name"]
        self.viewing = vid
        self.viewbook = vb

    def close_version(self):
        self.viewing = None
        self.viewbook = None

    def restore_version(self, vid):
        if self.viewing is not None:
            return
        e = self._version(vid)
        if e is None:
            return
        sid = e["sid"]
        if not self._can_write(sid):
            self.alerts_.append(Alert("droit_insuffisant", self._name(sid), None))
            return
        refs = set(e["cells"]) | {r for (s, r), c in self.replica.cells.items()
                                  if s == sid and c["raw"] is not None}
        fwd_items, inv_items = [], []
        for r in sorted(refs):
            cur = self._cell_tuple(sid, r)
            inv_items.append((r,) + cur)
            new = e["cells"].get(r, (None, False, None))
            fwd_items.append((r,) + tuple(new))
        fwd = {"t": "cells", "sid": sid, "items": fwd_items, "name": e["name"], "kind": "restauration"}
        inv = {"t": "cells", "sid": sid, "items": inv_items, "name": self._name(sid),
               "kind": "modification"}
        self._act(fwd, inv)

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz)
