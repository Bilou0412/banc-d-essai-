"""Classeur collaboratif hors ligne — couche code (sonde P11). Partie 1 : moteur de formules."""
import csv
import io
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc

# Une chaîne de dépendances de plusieurs centaines de cellules se calcule par récursion sur le graphe.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 100_000))


# ---------------------------------------------------------------- temps simulé

class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


# ---------------------------------------------------------------- erreurs de formule

class CellError(Exception):
    """Erreur affichable dans une cellule : code = "#TYPE!", "#DIV/0!", "#SYNTAXE!", "#CIRC!", "#REF!"."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- analyse

REF_RE = re.compile(r"(?:([A-Za-zÀ-ÿ_][\wÀ-ÿ ]*)!)?\$?([A-Za-z]+)\$?(\d+)")
TOKEN_RE = re.compile(
    r"\s*(?:(\d+(?:\.\d+)?)"
    r"|((?:[A-Za-zÀ-ÿ_][\wÀ-ÿ]*!)?\$?[A-Za-z]+\$?\d+)"
    r"|([A-Za-zÀ-ÿ_][\wÀ-ÿ]*)"
    r"|(:|\+|-|\*|/|\(|\)|,))"
)


def tokenize(src):
    pos = 0
    tokens = []
    src = src.rstrip()
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m or m.end() == pos:
            raise CellError("#SYNTAXE!")
        pos = m.end()
        if m.group(1) is not None:
            tokens.append(("num", m.group(1)))
        elif m.group(2) is not None:
            tokens.append(("ref", m.group(2)))
        elif m.group(3) is not None:
            tokens.append(("name", m.group(3)))
        else:
            tokens.append(("op", m.group(4)))
    return tokens


def split_ref(text):
    """'Feuille1!A1' -> (sheet or None, 'A1'). Renvoie aussi la colonne/ligne normalisées."""
    if "!" in text:
        sheet, cell = text.rsplit("!", 1)
    else:
        sheet, cell = None, text
    cell = cell.replace("$", "").upper()
    return sheet, cell


class Parser:
    """Descente récursive. Produit un arbre : ('num', x) | ('ref', sheet, cell) | ('range', sheet, a, b)
    | ('bin', op, l, r) | ('neg', e) | ('call', name, args)."""

    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect_op(self, op):
        kind, val = self.take()
        if kind != "op" or val != op:
            raise CellError("#SYNTAXE!")

    def parse(self):
        e = self.expr()
        if self.i != len(self.t):
            raise CellError("#SYNTAXE!")
        return e

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
        return self.primary()

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", float(val) if "." in val else int(val))
        if kind == "ref":
            node = self.reference(val)
            return node
        if kind == "name":
            if self.peek() != ("op", "("):
                raise CellError("#SYNTAXE!")
            self.take()
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            return ("call", val.upper(), args)
        if kind == "op" and val == "(":
            e = self.expr()
            self.expect_op(")")
            return e
        raise CellError("#SYNTAXE!")

    def reference(self, text):
        sheet, cell = split_ref(text)
        if self.peek() == ("op", ":"):
            self.take()
            kind, val = self.take()
            if kind != "ref":
                raise CellError("#SYNTAXE!")
            _, cell2 = split_ref(val)
            return ("range", sheet, cell, cell2)
        return ("ref", sheet, cell)


def parse_formula(src):
    """src : texte sans le « = » initial."""
    return Parser(tokenize(src)).parse()


def cell_coords(ref):
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return col, int(m.group(2))


def cell_name(col, row):
    s = ""
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row}"


def range_cells(a, b):
    c1, r1 = cell_coords(a)
    c2, r2 = cell_coords(b)
    for c in range(min(c1, c2), max(c1, c2) + 1):
        for r in range(min(r1, r2), max(r1, r2) + 1):
            yield cell_name(c, r)


def static_refs(node, home):
    """Ensemble des (feuille, cellule) référencées par l'arbre ; `home` = feuille courante."""
    out = set()
    kind = node[0]
    if kind == "ref":
        out.add((node[1] or home, node[2]))
    elif kind == "range":
        for c in range_cells(node[2], node[3]):
            out.add((node[1] or home, c))
    elif kind == "bin":
        out |= static_refs(node[2], home) | static_refs(node[3], home)
    elif kind == "neg":
        out |= static_refs(node[1], home)
    elif kind == "call":
        for a in node[2]:
            out |= static_refs(a, home)
    return out


# ---------------------------------------------------------------- évaluation

def to_number(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        raise CellError("#TYPE!")
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, datetime):
        raise CellError("#TYPE!")
    raise CellError("#TYPE!")


class DateTime:
    """Instant absolu (UTC). Affiché dans le fuseau de la personne qui regarde."""

    def __init__(self, instant):
        self.instant = instant  # aware, UTC

    def __eq__(self, other):
        return isinstance(other, DateTime) and other.instant == self.instant

    def __hash__(self):
        return hash(self.instant)

    def show(self, tz):
        return self.instant.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")

    def iso(self, tz):
        return self.instant.astimezone(ZoneInfo(tz)).isoformat()


class DateOnly:
    """Date seule, sans fuseau : même jour partout."""

    def __init__(self, text):
        self.text = text

    def __eq__(self, other):
        return isinstance(other, DateOnly) and other.text == self.text

    def __hash__(self):
        return hash(self.text)

    def show(self, tz):
        return self.text


DT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$")
DT_OFF_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_typed(text, tz):
    """Texte tel que saisi -> contenu typé. `tz` : fuseau de la personne qui saisit."""
    if DATE_RE.match(text):
        return DateOnly(text)
    m = DT_OFF_RE.match(text)
    if m:
        off = m.group(5)
        iso = (m.group(1) + "T" + m.group(2) + ":" + m.group(3) + ":" + (m.group(4) or "00")
               + ("+00:00" if off == "Z" else off))
        return DateTime(datetime.fromisoformat(iso).astimezone(UTC))
    m = DT_RE.match(text)
    if m:
        y, mo, d = map(int, m.group(1).split("-"))
        naive = datetime(y, mo, d, int(m.group(2)), int(m.group(3)), int(m.group(4) or 0))
        return DateTime(naive.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC))
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def display(v, tz):
    if v is None:
        return None
    if isinstance(v, (DateTime, DateOnly)):
        return v.show(tz)
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


class Formula:
    """Contenu formule : texte conservé (barre de formule) + arbre analysé, None si syntaxe invalide."""

    def __init__(self, text):
        self.text = text
        try:
            self.tree = parse_formula(text[1:])
        except CellError:
            self.tree = None

    def __eq__(self, other):
        return isinstance(other, Formula) and other.text == self.text

    def __hash__(self):
        return hash(self.text)


def make_content(text, tz):
    """Saisie -> contenu brut. None = sans contenu."""
    if text is None or text == "":
        return None
    if text.startswith("="):
        return Formula(text)
    return parse_typed(text, tz)


def content_text(c, tz):
    """Contenu -> texte de la barre de formule."""
    if c is None:
        return None
    if isinstance(c, Formula):
        return c.text
    if isinstance(c, (DateTime, DateOnly)):
        return c.show(tz)
    return str(c)


def rename_in(wb, old, new):
    """Renomme une feuille dans un classeur et réécrit les références explicites dans les formules."""
    wb.order = [new if n == old else n for n in wb.order]
    wb.sheets[new] = wb.sheets.pop(old)
    pat = re.compile(r"(?<![\wÀ-ÿ])" + re.escape(old) + "!")
    for cells in wb.sheets.values():
        for c, content in list(cells.items()):
            if isinstance(content, Formula):
                cells[c] = Formula(pat.sub(new + "!", content.text))


class Workbook:
    """Contenus bruts par feuille ; valeurs recalculées à la demande en suivant les références.
    Un cycle est détecté par la pile de calcul, qui est le chemin du graphe de dépendances."""

    def __init__(self, clock):
        self.clock = clock
        self.order = []      # ordre des feuilles
        self.sheets = {}     # nom -> {cellule: contenu brut}

    def copy_state(self):
        return ([n for n in self.order], {n: dict(self.sheets[n]) for n in self.order})

    def load_state(self, state):
        self.order = list(state[0])
        self.sheets = {n: dict(state[1][n]) for n in self.order}

    def value(self, sheet, cell, tz):
        try:
            return display(self.compute(sheet, cell, ()), tz)
        except CellError as e:
            return e.code

    def error(self, sheet, cell):
        try:
            self.compute(sheet, cell, ())
            return None
        except CellError as e:
            return e.code

    def compute(self, sheet, cell, stack):
        if (sheet, cell) in stack:
            raise CellError("#CIRC!")
        if sheet not in self.sheets:
            raise CellError("#REF!")
        content = self.sheets[sheet].get(cell)
        if content is None:
            return None
        if isinstance(content, Formula):
            if content.tree is None:
                raise CellError("#SYNTAXE!")
            here = stack + ((sheet, cell),)
            result = evaluate(content.tree, lambda s, c: self.compute(s, c, here), sheet, self.clock)
            # Une formule qui désigne une cellule vide vaut zéro (comme une somme vide).
            return 0 if result is None else result
        return content


def evaluate(node, lookup, home, clock=None):
    """lookup(sheet, cell) -> valeur déjà calculée (peut lever CellError).
    Les références suivent le graphe : la valeur d'une cellule est calculée via lookup,
    et la détection de cycle est faite par le moteur appelant sur ce même graphe."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return lookup(node[1] or home, node[2])
    if kind == "range":
        raise CellError("#TYPE!")
    if kind == "neg":
        return -to_number(evaluate(node[1], lookup, home, clock))
    if kind == "bin":
        op = node[1]
        va = evaluate(node[2], lookup, home, clock)
        vb = evaluate(node[3], lookup, home, clock)
        if op == "-" and isinstance(va, DateTime) and isinstance(vb, DateTime):
            return (va.instant - vb.instant).total_seconds() / 86400
        a = to_number(va)
        b = to_number(vb)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise CellError("#DIV/0!")
            r = a / b
            return int(r) if r == int(r) else r
    if kind == "call":
        name, args = node[1], node[2]
        if name == "MAINTENANT":
            return DateTime(clock.now())
        if name == "SOMME":
            total = 0
            for a in args:
                if a[0] == "range":
                    for c in range_cells(a[2], a[3]):
                        total += to_number(lookup(a[1] or home, c))
                else:
                    total += to_number(evaluate(a, lookup, home, clock))
            return total
        raise CellError("#SYNTAXE!")
    raise CellError("#SYNTAXE!")


# ---------------------------------------------------------------- réseau simulé

W = "écriture"
R = "lecture"


class Network:
    """Messages en vol. Un message dont l'émetteur ou le destinataire est coupé est perdu.
    Les clients envoient leurs modifications au moment où le réseau les livre (flush)."""

    def __init__(self):
        self.nodes = {}
        self.offline = set()
        self.queue = []

    def attach(self, name, node):
        self.nodes[name] = node

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def _deliver(self, item):
        src, dst, msg = item
        if src in self.offline or dst in self.offline:
            return
        self.nodes[dst].receive(src, msg)

    def _flush_clients(self):
        for name, node in list(self.nodes.items()):
            if name != "server" and name not in self.offline:
                node.flush()

    def deliver_all(self):
        while True:
            self._flush_clients()
            if not self.queue:
                break
            self._deliver(self.queue.pop(0))

    def deliver_from(self, name):
        if name not in self.offline:
            self.nodes[name].flush()
        mine = [i for i in self.queue if i[0] == name]
        self.queue = [i for i in self.queue if i[0] != name]
        for item in mine:
            self._deliver(item)

    def disconnect(self, name):
        self.offline.add(name)
        self.queue = [i for i in self.queue if name not in (i[0], i[1])]
        if "server" in self.nodes:
            self.nodes["server"].on_disconnect(name)

    def reconnect(self, name):
        self.offline.discard(name)
        self.nodes[name].on_reconnect()


# ---------------------------------------------------------------- serveur (autorité sur la fusion)

class Conflict:
    def __init__(self, text, by, content):
        self.discarded = text          # valeur écartée, telle que saisie
        self.discarded_by = by         # personne dont la valeur a été écartée
        self.content = content         # contenu typé écarté (pour résolution)


class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.wb = Workbook(clock)
        self.wb.order = ["Feuille1"]
        self.wb.sheets = {"Feuille1": {}}
        self.rights = {(owner, "Feuille1"): W}
        self.rev = {}            # (feuille, cellule) -> numéro de révision
        self.conflicts = {}      # (feuille, cellule) -> Conflict
        self.versions = []       # entrées de l'historique
        self.presence = {}       # nom -> (feuille, cellule)
        self.sids = {"Feuille1": "init"}   # nom -> identité stable de la feuille (survit au renommage)
        self.seen = set()        # (auteur, opid) déjà appliqués
        self.next_id = 1
        net.attach("server", self)

    def right(self, person, sheet):
        return self.rights.get((person, sheet))

    def snapshot(self):
        return {
            "order": list(self.wb.order),
            "sheets": {n: dict(self.wb.sheets[n]) for n in self.wb.order},
            "rights": dict(self.rights),
            "rev": dict(self.rev),
            "conflicts": dict(self.conflicts),
            "versions": list(self.versions),
            "presence": dict(self.presence),
            "owner": self.owner,
            "sids": dict(self.sids),
        }

    def broadcast(self):
        snap = self.snapshot()
        for name in self.net.nodes:
            if name != "server":
                self.net.send("server", name, {"type": "state", "state": snap})

    def on_disconnect(self, name):
        if name in self.presence:
            del self.presence[name]
            self.broadcast()

    def receive(self, src, msg):
        t = msg["type"]
        if t == "hello":
            self.net.send("server", src, {"type": "state", "state": self.snapshot()})
        elif t == "select":
            self.presence[src] = (msg["sheet"], msg["cell"])
            self.broadcast()
        elif t == "right":
            if src == self.owner and msg["sheet"] in self.wb.sheets:
                self.rights[(msg["person"], msg["sheet"])] = msg["level"]
                self.broadcast()
        elif t == "op":
            op = msg["op"]
            key = (src, op["opid"])
            if key in self.seen:
                self.net.send("server", src, {"type": "ack", "opid": op["opid"]})
                return
            self.seen.add(key)
            result = self.apply(src, op)
            self.broadcast()
            if result == "ok":
                self.net.send("server", src, {"type": "ack", "opid": op["opid"]})
            else:
                self.net.send("server", src, {"type": "reject", "opid": op["opid"],
                                              "reason": result, "sheet": op.get("sheet"),
                                              "cell": op.get("cell")})

    # ---- application des opérations

    def _record(self, author, ts, sheet, kind):
        self.versions.append({
            "id": self.next_id, "author": author, "ts": ts, "kind": kind, "sheet": sheet,
            "sid": self.sids.get(sheet),
            "cells": dict(self.wb.sheets[sheet]) if sheet in self.wb.sheets else {},
        })
        self.next_id += 1

    def _set_cell(self, src, sheet, cell, content, base, text=""):
        """Retourne True si le contenu a changé. Base périmée => conflit, la valeur serveur est gardée."""
        key = (sheet, cell)
        cur = self.rev.get(key, 0)
        now = self.wb.sheets[sheet].get(cell)
        if content == now:
            return False
        if base >= cur:
            if content is None:
                self.wb.sheets[sheet].pop(cell, None)
            else:
                self.wb.sheets[sheet][cell] = content
            self.rev[key] = cur + 1
            self.conflicts.pop(key, None)
            return True
        self.conflicts[key] = Conflict(text, src, content)
        return False

    def _rename(self, old, new):
        rename_in(self.wb, old, new)
        for key in [k2 for k2 in self.rights if k2[1] == old]:
            self.rights[(key[0], new)] = self.rights.pop(key)
        self.sids[new] = self.sids.pop(old)

    def apply(self, src, op):
        k = op["kind"]
        if k == "set":
            sheet = op["sheet"]
            if sheet not in self.wb.sheets:
                return "feuille_supprimee"
            if self.right(src, sheet) != W:
                return "droit"
            if self._set_cell(src, sheet, op["cell"], op["content"], op["base"], op.get("text", "")):
                self._record(src, op["ts"], sheet, "modification")
            return "ok"
        if k == "setmany":
            sheet = op["sheet"]
            if sheet not in self.wb.sheets:
                return "feuille_supprimee"
            if self.right(src, sheet) != W:
                return "droit"
            changed = False
            for cell, content in op["cells"].items():
                changed |= self._set_cell(src, sheet, cell, content, self.rev.get((sheet, cell), 0))
            if op.get("restore"):
                self._record(src, op["ts"], sheet, "restauration")
            elif changed:
                self._record(src, op["ts"], sheet, "modification")
            return "ok"
        if k == "addsheet":
            name = op["name"]
            if name in self.wb.sheets:
                return "nom_existant"
            self.wb.order.append(name)
            self.wb.sheets[name] = dict(op.get("contents", {}))
            self.sids[name] = f"{src}:{op['opid']}"
            self.rights[(src, name)] = W
            self._record(src, op["ts"], name, "modification")
            return "ok"
        if k == "delsheet":
            name = op["name"]
            if name not in self.wb.sheets:
                return "ok"
            if self.right(src, name) != W:
                return "droit"
            if len(self.wb.order) == 1:
                return "dernier"
            self.wb.order.remove(name)
            del self.wb.sheets[name]
            for key in [k2 for k2 in self.rights if k2[1] == name]:
                del self.rights[key]
            return "ok"
        if k == "rename":
            old, new = op["old"], op["new"]
            if old not in self.wb.sheets:
                return "feuille_supprimee"
            if self.right(src, old) != W:
                return "droit"
            if new.lower() in {n.lower() for n in self.wb.sheets}:
                return "nom_existant"
            self._rename(old, new)
            return "ok"
        if k == "restore":
            name = next((n for n, s in self.sids.items() if s == op["sid"]), None)
            if name is None:
                return "feuille_supprimee"
            if self.right(src, name) != W:
                return "droit"
            if op["name"] != name:
                if op["name"] in self.wb.sheets:
                    return "nom_existant"
                self._rename(name, op["name"])
                name = op["name"]
            for cell, content in op["cells"].items():
                self._set_cell(src, name, cell, content, self.rev.get((name, cell), 0))
            self._record(src, op["ts"], name, "restauration")
            return "ok"
        if k == "resolve":
            sheet, cell = op["sheet"], op["cell"]
            if sheet not in self.wb.sheets:
                return "feuille_supprimee"
            if self.right(src, sheet) != W:
                return "droit"
            cf = self.conflicts.get((sheet, cell))
            if cf is None:
                return "ok"
            if op["use_discarded"]:
                self._set_cell(src, sheet, cell, cf.content, self.rev.get((sheet, cell), 0), cf.discarded)
                self._record(src, op["ts"], sheet, "modification")
            self.conflicts.pop((sheet, cell), None)
            return "ok"
        return "ok"


# ---------------------------------------------------------------- copie locale (client)

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line


class Version:
    def __init__(self, vid, author, timestamp, kind, sheet, cells):
        self.id = vid
        self.author = author
        self.timestamp = timestamp
        self.kind = kind
        self.sheet = sheet
        self.cells = cells


def _put(cells, cell, content):
    if content is None:
        cells.pop(cell, None)
    else:
        cells[cell] = content


class Client:
    """Copie locale propre. `state` = dernier état confirmé par le serveur ; `outbox` = modifications
    locales non confirmées ; la vue affichée = état confirmé + outbox rejouée."""

    def __init__(self, net, clock, name, tz="UTC"):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.active = "Feuille1"
        self.state = {"order": ["Feuille1"], "sheets": {"Feuille1": {}}, "rights": {}, "rev": {},
                      "conflicts": {}, "versions": [], "presence": {}, "owner": None,
                      "sids": {"Feuille1": "init"}}
        self.outbox = []
        self.undo_stack = []
        self.redo_stack = []
        self.alerts_list = []
        self.opseq = 0
        self.viewing = None
        self._rebuild()
        net.attach(name, self)
        net.send(name, "server", {"type": "hello"})

    # ---- vue locale

    def _rebuild(self):
        wb = Workbook(self.clock)
        wb.order = list(self.state["order"])
        wb.sheets = {n: dict(c) for n, c in self.state["sheets"].items()}
        rights = dict(self.state["rights"])
        for op in self.outbox:
            k = op["kind"]
            if k == "set" and op["sheet"] in wb.sheets:
                _put(wb.sheets[op["sheet"]], op["cell"], op["content"])
            elif k == "setmany" and op["sheet"] in wb.sheets:
                for c, v in op["cells"].items():
                    _put(wb.sheets[op["sheet"]], c, v)
            elif k == "addsheet" and op["name"] not in wb.sheets:
                wb.order.append(op["name"])
                wb.sheets[op["name"]] = dict(op["contents"])
                rights[(self.name, op["name"])] = W
            elif k == "delsheet" and op["name"] in wb.sheets and len(wb.order) > 1:
                wb.order.remove(op["name"])
                del wb.sheets[op["name"]]
            elif k == "rename" and op["old"] in wb.sheets and op["new"] not in wb.sheets:
                rename_in(wb, op["old"], op["new"])
            elif k == "restore":
                name = next((n for n, s in self.state["sids"].items() if s == op["sid"]), None)
                if name is not None and name in wb.sheets:
                    if op["name"] != name and op["name"] not in wb.sheets:
                        rename_in(wb, name, op["name"])
                        name = op["name"]
                    for c, v in op["cells"].items():
                        _put(wb.sheets[name], c, v)
        self.view = wb
        self.rights_view = rights

    def _read(self):
        return self.viewing if self.viewing is not None else self.view

    # ---- réseau

    def flush(self):
        if self.name in self.net.offline:
            return
        for op in self.outbox:
            if not op["sent"]:
                op["sent"] = True
                self.net.send(self.name, "server", {"type": "op", "op": dict(op)})

    def on_reconnect(self):
        for op in self.outbox:
            op["sent"] = False
        self.net.send(self.name, "server", {"type": "hello"})

    def receive(self, src, msg):
        t = msg["type"]
        if t == "state":
            self.state = msg["state"]
            self._rebuild()
        elif t == "ack":
            self.outbox = [o for o in self.outbox if o["opid"] != msg["opid"]]
            self._rebuild()
        elif t == "reject":
            self.outbox = [o for o in self.outbox if o["opid"] != msg["opid"]]
            reason = msg["reason"]
            if reason == "feuille_supprimee":
                self.alerts_list.append(Alert("feuille_supprimee", msg["sheet"], msg["cell"]))
            elif reason == "nom_existant":
                self.alerts_list.append(Alert("nom_existant"))
            elif reason == "droit":
                self.alerts_list.append(Alert("modification_rejetee", msg["sheet"], msg["cell"]))
            self._rebuild()

    def _opid(self):
        self.opseq += 1
        return f"{self.name}-{self.opseq}"

    def _base(self, sheet, cell):
        n = 0
        for o in self.outbox:
            if o["kind"] == "set" and o["sheet"] == sheet and o["cell"] == cell:
                n += 1
            elif o["kind"] == "setmany" and o["sheet"] == sheet and cell in o["cells"]:
                n += 1
        return self.state["rev"].get((sheet, cell), 0) + n

    def _enqueue(self, op):
        op = dict(op)
        op["opid"] = self._opid()
        op["ts"] = self.clock.now()
        op["sent"] = False
        if op["kind"] == "set":
            op["base"] = self._base(op["sheet"], op["cell"])
        self.outbox.append(op)
        self._rebuild()
        return op["opid"]

    # ---- annulation / rétablissement

    def _act(self, fwd, back, check=None):
        opid = self._enqueue(fwd)
        self.undo_stack.append({"fwd": fwd, "back": back, "opid": opid, "check": check})
        self.redo_stack = []

    def _revert(self, e):
        check = e["check"]
        if check is not None:
            sheet, cell, pre, post = check
            if self.view.sheets.get(sheet, {}).get(cell) != pre:
                self.alerts_list.append(Alert("annulation_impossible", sheet, cell))
                return None
        target = e["back"].get("sheet")
        if target is not None and self.rights_view.get((self.name, target)) != W:
            self.alerts_list.append(Alert("droit_insuffisant", target))
            return None
        if e["opid"] is not None and any(o["opid"] == e["opid"] and not o["sent"] for o in self.outbox):
            # l'action n'a pas encore quitté l'appareil : on la retire simplement
            self.outbox = [o for o in self.outbox if o["opid"] != e["opid"]]
            self._rebuild()
            new = None
        else:
            new = self._enqueue(e["back"])
        swapped = None if check is None else (check[0], check[1], check[3], check[2])
        return {"fwd": e["back"], "back": e["fwd"], "opid": new, "check": swapped}

    def undo(self):
        if not self.undo_stack:
            return
        s = self._revert(self.undo_stack.pop())
        if s is not None:
            self.redo_stack.append(s)

    def redo(self):
        if not self.redo_stack:
            return
        s = self._revert(self.redo_stack.pop())
        if s is not None:
            self.undo_stack.append(s)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    # ---- saisie et lecture

    def set_cell(self, ref, text, sheet=None):
        sheet = sheet or self.active
        cell = ref.upper()
        if self.viewing is not None:
            return
        if self.rights_view.get((self.name, sheet)) != W:
            self.alerts_list.append(Alert("droit_insuffisant", sheet, cell))
            return
        before = self.view.sheets.get(sheet, {}).get(cell)
        content = make_content(text, self.tz)
        fwd = {"kind": "set", "sheet": sheet, "cell": cell, "content": content, "text": text}
        back = {"kind": "set", "sheet": sheet, "cell": cell, "content": before,
                "text": content_text(before, self.tz) or ""}
        self._act(fwd, back, check=(sheet, cell, content, before))

    def clear(self, ref, sheet=None):
        self.set_cell(ref, "", sheet)

    def content(self, ref, sheet=None):
        raw = self._read().sheets.get(sheet or self.active, {}).get(ref.upper())
        return content_text(raw, self.tz)

    def value(self, ref, sheet=None):
        return self._read().value(sheet or self.active, ref.upper(), self.tz)

    def error(self, ref, sheet=None):
        return self._read().error(sheet or self.active, ref.upper())

    def set_timezone(self, tz):
        self.tz = tz

    def connection_status(self):
        return "hors ligne" if self.name in self.net.offline else "en ligne"

    def pending_count(self):
        return len(self.outbox)

    def alerts(self):
        return list(self.alerts_list)

    # ---- feuilles et droits

    def sheets(self):
        return list(self.view.order)

    def activate(self, name):
        if name in self.view.sheets:
            self.active = name

    def add_sheet(self, name):
        if name.lower() in {n.lower() for n in self.view.order}:
            self.alerts_list.append(Alert("nom_existant"))
            return
        self._act({"kind": "addsheet", "name": name, "contents": {}},
                  {"kind": "delsheet", "name": name})

    def delete_sheet(self, name):
        if name not in self.view.sheets:
            return
        if self.rights_view.get((self.name, name)) != W:
            self.alerts_list.append(Alert("droit_insuffisant", name))
            return
        if len(self.view.order) == 1:
            return
        contents = dict(self.view.sheets[name])
        self._act({"kind": "delsheet", "name": name},
                  {"kind": "addsheet", "name": name, "contents": contents})

    def rename_sheet(self, old, new):
        if self.rights_view.get((self.name, old)) != W:
            self.alerts_list.append(Alert("droit_insuffisant", old))
            return
        if new.lower() in {n.lower() for n in self.view.order}:
            self.alerts_list.append(Alert("nom_existant"))
            return
        self._act({"kind": "rename", "old": old, "new": new},
                  {"kind": "rename", "old": new, "new": old})

    def right(self, person, sheet):
        return self.rights_view.get((person, sheet))

    def set_right(self, person, sheet, level):
        if self.name in self.net.offline:
            return
        self.net.send(self.name, "server",
                      {"type": "right", "person": person, "sheet": sheet, "level": level})

    # ---- présence et conflits

    def select(self, ref, sheet=None):
        if self.name in self.net.offline:
            return
        self.net.send(self.name, "server",
                      {"type": "select", "sheet": sheet or self.active, "cell": ref.upper()})

    def presence(self):
        if self.name in self.net.offline:
            return {}
        return {k: v for k, v in self.state["presence"].items() if k != self.name}

    def conflict(self, ref, sheet=None):
        return self.state["conflicts"].get((sheet or self.active, ref.upper()))

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sheet = sheet or self.active
        if self.rights_view.get((self.name, sheet)) != W:
            return
        self._enqueue({"kind": "resolve", "sheet": sheet, "cell": ref.upper(),
                       "use_discarded": use_discarded})

    # ---- historique

    def history(self, sheet=None):
        sheet = sheet or self.active
        entries = [v for v in self.state["versions"] if v["sheet"] == sheet]
        entries.sort(key=lambda v: (v["ts"], v["id"]), reverse=True)
        return [Version(v["id"], v["author"],
                        v["ts"].astimezone(ZoneInfo(self.tz)).strftime("%Y-%m-%d %H:%M"),
                        v["kind"], v["sheet"], v["cells"]) for v in entries]

    def open_version(self, vid):
        v = next((x for x in self.state["versions"] if x["id"] == vid), None)
        if v is None:
            return
        wb = Workbook(self.clock)
        wb.order = [v["sheet"]]
        wb.sheets = {v["sheet"]: dict(v["cells"])}
        self.viewing = wb

    def close_version(self):
        self.viewing = None

    def restore_version(self, vid):
        v = next((x for x in self.state["versions"] if x["id"] == vid), None)
        if v is None:
            return
        cur = next((n for n, s in self.state["sids"].items() if s == v["sid"]), None)
        if cur is None or self.rights_view.get((self.name, cur)) != W:
            return
        current = dict(self.view.sheets.get(cur, {}))
        cells = {c: None for c in current}
        cells.update(v["cells"])
        back = {"kind": "restore", "sid": v["sid"], "name": cur, "sheet": cur,
                "cells": {c: current.get(c) for c in cells}}
        fwd = {"kind": "restore", "sid": v["sid"], "name": v["sheet"], "sheet": cur, "cells": cells}
        self._act(fwd, back)

    # ---- CSV

    def _export_text(self, sheet, cell):
        wb = self._read()
        try:
            v = wb.compute(sheet, cell, ())
        except CellError as e:
            return e.code
        if v is None:
            return ""
        if isinstance(v, DateTime):
            return v.iso(self.tz)
        if isinstance(v, DateOnly):
            return v.text
        return str(display(v, self.tz))

    def export_csv(self):
        sheet = self.active
        cells = self._read().sheets.get(sheet, {})
        rows = {}
        for c in cells:
            col, row = cell_coords(c)
            rows.setdefault(row, {})[col] = c
        out = io.StringIO()
        writer = csv.writer(out)
        for row in sorted(rows):
            cols = rows[row]
            width = max(cols)
            writer.writerow([self._export_text(sheet, cols[i]) if i in cols else ""
                             for i in range(1, width + 1)])
        return out.getvalue().encode("utf-8")

    def import_csv(self, data):
        sheet = self.active
        if self.rights_view.get((self.name, sheet)) != W:
            self.alerts_list.append(Alert("droit_insuffisant", sheet))
            return
        lines = data.decode("utf-8-sig").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        records = []
        buf, start = None, 0
        for i, line in enumerate(lines):
            line = line.rstrip("\r")
            if buf is None:
                buf, start = line, i
            else:
                buf = buf + "\n" + line
            if buf.count('"') % 2 == 0:
                records.append((start, buf))
                buf = None
        if buf is not None:
            self.alerts_list.append(Alert("csv_invalide", sheet, None, start + 1))
            return
        cells = {}
        for r, (_, rec) in enumerate(records):
            parsed = list(csv.reader([rec]))
            fields = parsed[0] if parsed else []
            for col, field in enumerate(fields, start=1):
                cell = cell_name(col, r + 1)
                if field == "":
                    cells[cell] = None
                elif field.startswith("="):
                    cells[cell] = field
                else:
                    cells[cell] = parse_typed(field, self.tz)
        before = self.view.sheets.get(sheet, {})
        back = {"kind": "setmany", "sheet": sheet, "cells": {c: before.get(c) for c in cells}}
        self._act({"kind": "setmany", "sheet": sheet, "cells": cells}, back)

    # ---- sessions

    def reopen(self):
        c = Client(self.net, self.clock, self.name, tz=self.tz)
        c.state = self.state
        c.outbox = [dict(o) for o in self.outbox]
        c.active = self.active
        c.opseq = self.opseq
        c._rebuild()
        return c
