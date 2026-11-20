"""Classeur collaboratif hors ligne (couche code, sonde P11).

Mécanismes réels : analyseur d'expressions, graphe de dépendances évalué par
détection de cycles sur la pile d'appels, réseau simulé en mémoire (messages
retardés, coupés, livrés dans un ordre quelconque), copies locales par personne
fusionnées par le serveur, fuseaux via zoneinfo.
"""
import copy
import csv
import io
import itertools
import re
import sys
from collections import deque
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.setrecursionlimit(100000)

W = "écriture"
R = "lecture"
_IDS = itertools.count(1)


class Err:
    def __init__(self, code):
        self.code = code


E_TYPE = Err("#TYPE!")
E_DIV = Err("#DIV/0!")
E_SYNTAX = Err("#SYNTAXE!")
E_CIRC = Err("#CIRC!")
E_REF = Err("#REF!")


# ---------------------------------------------------------------- temps, alertes, réseau

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
    """Réseau en mémoire : un message émis par ou vers une personne coupée est perdu."""

    def __init__(self):
        self.nodes = {}
        self.disconnected = set()
        self.queue = deque()

    def register(self, name, node):
        self.nodes[name] = node

    def is_connected(self, name):
        return name not in self.disconnected

    def send(self, src, dst, msg):
        if src in self.disconnected or dst in self.disconnected:
            return
        self.queue.append((src, dst, msg))

    def _dispatch(self, src, dst, msg):
        node = self.nodes.get(dst)
        if node is not None and dst not in self.disconnected:
            node.receive(src, msg)

    def deliver_all(self):
        while self.queue:
            src, dst, msg = self.queue.popleft()
            self._dispatch(src, dst, msg)

    def deliver_from(self, name):
        items = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for src, dst, msg in items:
            self._dispatch(src, dst, msg)

    def disconnect(self, name):
        self.disconnected.add(name)
        self.queue = deque(m for m in self.queue if name not in (m[0], m[1]))
        srv = self.nodes.get("server")
        if srv is not None:
            srv.on_disconnect(name)

    def reconnect(self, name):
        self.disconnected.discard(name)
        node = self.nodes.get(name)
        if node is not None:
            node.on_connect()


# ---------------------------------------------------------------- références de cellules

def col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


_REF_RE = re.compile(r"([A-Za-z]{1,3})([0-9]+)")


def split_ref(ref):
    m = _REF_RE.fullmatch(ref)
    if m is None:
        return None
    return col_index(m.group(1)), int(m.group(2))


def ref_of(col, row):
    return f"{col_letters(col)}{row}"


def range_refs(a, b):
    c1, r1 = split_ref(a)
    c2, r2 = split_ref(b)
    for r in range(min(r1, r2), max(r1, r2) + 1):
        for c in range(min(c1, c2), max(c1, c2) + 1):
            yield ref_of(c, r)


def find_sid(sheets, name):
    for sid, rec in sheets.items():
        if rec["name"] == name:
            return sid
    return None


def name_taken(sheets, name, exclude=None):
    low = name.lower()
    return any(rec["name"].lower() == low and sid != exclude for sid, rec in sheets.items())


# ---------------------------------------------------------------- valeurs littérales et affichage

_INT_RE = re.compile(r"-?\d+")
_FLT_RE = re.compile(r"-?\d+\.\d+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")


def literal(raw, tz):
    """Valeur d'un texte saisi. Une date-heure sans décalage est lue dans le fuseau `tz` de saisie."""
    if _INT_RE.fullmatch(raw):
        return int(raw)
    if _FLT_RE.fullmatch(raw):
        return float(raw)
    if _DATE_RE.fullmatch(raw):
        return date.fromisoformat(raw)
    if _DT_RE.fullmatch(raw):
        t = raw.replace("Z", "+00:00")
        if re.search(r"[+-]\d{4}$", t):
            t = t[:-2] + ":" + t[-2:]
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        return dt
    return raw


def fmt_dt(dt, tz):
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


def iso_dt(dt, tz):
    return dt.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")


def display(v, tz):
    if v is None:
        return None
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return fmt_dt(v, tz)
    if isinstance(v, date):
        return v.isoformat()
    return v


def csv_text(v, tz):
    if v is None:
        return ""
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return iso_dt(v, tz)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# ---------------------------------------------------------------- CSV (analyse maison)

def parse_csv(text):
    """Renvoie (lignes, ligne_invalide). Un guillemet jamais fermé rend la ligne de son ouverture invalide."""
    rows, row, field = [], [], []
    i, n, line = 0, len(text), 1
    in_q, q_line = False, None
    while i < n:
        c = text[i]
        if in_q:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_q = False
            else:
                if c == "\n":
                    line += 1
                field.append(c)
            i += 1
            continue
        if c == '"' and not field:
            in_q, q_line = True, line
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
        else:
            field.append(c)
        i += 1
    if in_q:
        return rows, q_line
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows, None


# ---------------------------------------------------------------- formules : analyseur

_TOK_NUM = re.compile(r"\d+(?:\.\d+)?")
_TOK_ID = re.compile(r"[^\W\d]\w*")


def tokenize(src):
    toks, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            m = _TOK_NUM.match(src, i)
            txt = m.group(0)
            toks.append(("num", float(txt) if "." in txt else int(txt)))
            i = m.end()
        elif _TOK_ID.match(src, i):
            m = _TOK_ID.match(src, i)
            toks.append(("id", m.group(0)))
            i = m.end()
        elif c in "+-*/(),:!":
            toks.append(("op", c))
            i += 1
        else:
            raise ValueError("caractère inattendu")
    return toks


class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, c):
        if self.peek() != ("op", c):
            raise ValueError("syntaxe")
        self.i += 1

    def parse(self):
        if not self.t:
            raise ValueError("syntaxe")
        e = self.expr()
        if self.i != len(self.t):
            raise ValueError("syntaxe")
        return e

    def expr(self):
        e = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            e = ("bin", op, e, self.term())
        return e

    def term(self):
        e = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            e = ("bin", op, e, self.unary())
        return e

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        kind, val = self.peek()
        if kind == "num":
            self.take()
            return ("num", val)
        if (kind, val) == ("op", "("):
            self.take()
            e = self.expr()
            self.expect(")")
            return e
        if kind != "id":
            raise ValueError("syntaxe")
        nxt = self.peek(1)
        if nxt == ("op", "("):
            name = val.upper()
            if name not in ("SOMME", "MAINTENANT"):
                raise ValueError("syntaxe")
            self.take()
            self.take()
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect(")")
            if name == "MAINTENANT" and args:
                raise ValueError("syntaxe")
            return ("call", name, args)
        if nxt == ("op", "!"):
            sheet = val
            self.take()
            self.take()
            kind, val = self.peek()
            if kind != "id" or split_ref(val) is None:
                raise ValueError("syntaxe")
            self.take()
            return self.ref_tail(sheet, val)
        if split_ref(val) is None:
            raise ValueError("syntaxe")
        self.take()
        return self.ref_tail(None, val)

    def ref_tail(self, sheet, val):
        if self.peek() == ("op", ":"):
            self.take()
            kind, v2 = self.peek()
            if kind != "id" or split_ref(v2) is None:
                raise ValueError("syntaxe")
            self.take()
            return ("range", sheet, val.upper(), v2.upper())
        return ("ref", sheet, val.upper())


_PARSED = {}


def parse_formula(raw):
    ast = _PARSED.get(raw)
    if ast is None:
        ast = Parser(tokenize(raw[1:])).parse()
        _PARSED[raw] = ast
    return ast


# ---------------------------------------------------------------- formules : évaluation

class Ctx:
    def __init__(self, sheets, clock, tz):
        self.sheets = sheets
        self.clock = clock
        self.tz = tz


def isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def cell_value(ctx, sid, ref, stack):
    """Valeur d'une cellule. `stack` est le chemin en cours : y revenir = référence circulaire."""
    key = (sid, ref)
    if key in stack:
        return E_CIRC
    rec = ctx.sheets[sid]["cells"].get(ref)
    if rec is None or rec["raw"] is None:
        return None
    raw = rec["raw"]
    if rec["lit"] or not raw.startswith("="):
        return literal(raw, rec["tz"])
    try:
        ast = parse_formula(raw)
    except ValueError:
        return E_SYNTAX
    stack.append(key)
    try:
        return ev(ctx, sid, ast, stack)
    finally:
        stack.pop()


def ev(ctx, sid, node, stack):
    k = node[0]
    if k == "num":
        return node[1]
    if k == "ref":
        tsid = sid if node[1] is None else find_sid(ctx.sheets, node[1])
        if tsid is None:
            return E_REF
        v = cell_value(ctx, tsid, node[2], stack)
        return 0 if v is None else v
    if k == "range":
        return E_TYPE
    if k == "neg":
        v = ev(ctx, sid, node[1], stack)
        if isinstance(v, Err):
            return v
        return -v if isnum(v) else E_TYPE
    if k == "bin":
        return _binop(ctx, sid, node, stack)
    return _call(ctx, sid, node, stack)


def _binop(ctx, sid, node, stack):
    op = node[1]
    a = ev(ctx, sid, node[2], stack)
    if isinstance(a, Err):
        return a
    b = ev(ctx, sid, node[3], stack)
    if isinstance(b, Err):
        return b
    if op == "-" and isinstance(a, datetime) and isinstance(b, datetime):
        # Soustraction en instants UTC : deux datetimes au même ZoneInfo se soustraient sinon
        # en heures murales, ce qui ignore le passage à l'heure d'été.
        return (a.astimezone(timezone.utc) - b.astimezone(timezone.utc)).total_seconds() / 86400
    if op == "-" and type(a) is date and type(b) is date:
        return (a - b).days
    if not (isnum(a) and isnum(b)):
        return E_TYPE
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        return E_DIV
    return a / b


def _call(ctx, sid, node, stack):
    name, args = node[1], node[2]
    if name == "MAINTENANT":
        return ctx.clock.now()
    vals = []
    for arg in args:
        if arg[0] == "range":
            tsid = sid if arg[1] is None else find_sid(ctx.sheets, arg[1])
            if tsid is None:
                return E_REF
            for ref in range_refs(arg[2], arg[3]):
                vals.append(cell_value(ctx, tsid, ref, stack))
        else:
            vals.append(ev(ctx, sid, arg, stack))
    for v in vals:
        if isinstance(v, Err) and v.code == "#CIRC!":
            return v
    for v in vals:
        if isinstance(v, Err):
            return v
    total = 0
    for v in vals:
        if v is None:
            continue
        if not isnum(v):
            return E_TYPE
        total += v
    return total


# ---------------------------------------------------------------- état répliqué et effets

def new_state(owner):
    return {"owner": owner, "sheets": {}, "conflicts": {}, "versions": [],
            "presence": {}, "applied": set(), "seq": 0}


def _cells_set(st, sid, cells, e):
    rec = st["sheets"].get(sid)
    if rec is None:
        return
    for ref, raw, tz, lit in cells:
        rec["cells"][ref] = {"raw": raw, "tz": tz, "lit": lit, "seq": e.get("seq"),
                             "by": e["by"], "op": e["op"]}
        st["conflicts"].pop((sid, ref), None)


def _rename(st, sid, new):
    rec = st["sheets"].get(sid)
    if rec is None or rec["name"] == new:
        return
    old = rec["name"]
    rec["name"] = new
    pat = re.compile(r"(?<!\w)" + re.escape(old) + "!")
    for sh in st["sheets"].values():
        for cell in sh["cells"].values():
            raw = cell["raw"]
            if raw is not None and not cell["lit"] and raw.startswith("="):
                cell["raw"] = pat.sub(lambda m: new + "!", raw)


def apply_effect(st, e, record=True):
    """Applique un effet à un état. Déterministe : serveur et copies appliquent le même code."""
    k = e["kind"]
    sh = st["sheets"]
    if k == "set":
        _cells_set(st, e["sid"], [(e["ref"], e["raw"], e["tz"], e["lit"])], e)
    elif k == "batch":
        _cells_set(st, e["sid"], e["cells"], e)
    elif k == "unconflict":
        st["conflicts"].pop((e["sid"], e["ref"]), None)
    elif k == "conflict":
        st["conflicts"][(e["sid"], e["ref"])] = {"discarded": e["discarded"], "tz": e["tz"],
                                                 "lit": e["lit"], "by": e["by"]}
    elif k == "add_sheet":
        sh[e["sid"]] = {"name": e["name"], "cells": {}, "rights": {e["creator"]: W}}
    elif k == "restore_sheet":
        sh[e["sid"]] = {"name": e["name"], "cells": copy.deepcopy(e["cells"]),
                        "rights": copy.deepcopy(e["rights"])}
    elif k == "delete_sheet":
        sh.pop(e["sid"], None)
        for key in [x for x in st["conflicts"] if x[0] == e["sid"]]:
            del st["conflicts"][key]
    elif k == "rename":
        _rename(st, e["sid"], e["name"])
    elif k == "set_right":
        rec = sh.get(e["sid"])
        if rec is not None:
            if e["level"] is None:
                rec["rights"].pop(e["person"], None)
            else:
                rec["rights"][e["person"]] = e["level"]
    elif k == "restore":
        rec = sh.get(e["sid"])
        if rec is not None:
            rec["name"] = e["name"]
            rec["cells"] = copy.deepcopy(e["cells"])
    elif k == "presence":
        st["presence"][e["person"]] = (e["sheet"], e["ref"])
    elif k == "drop_presence":
        st["presence"].pop(e["person"], None)
    if record and e.get("ver"):
        st["versions"].append({"id": e["seq"], "sid": e["sid"], "author": e["by"], "at": e["at"],
                               "kind": e["ver"], "state": copy.deepcopy(sh)})


def build_effects(op, seq):
    """Traduit une opération acceptée en effets. `seq` est None pour l'aperçu local."""
    k = op["kind"]
    base = {"seq": seq, "op": op["id"], "by": op["author"], "at": op["at"]}
    if k == "set":
        return [dict(base, kind="set", sid=op["sid"], ref=op["ref"], raw=op["raw"],
                     tz=op["tz"], lit=op["lit"], ver="modification")]
    if k == "batch":
        return [dict(base, kind="batch", sid=op["sid"], cells=op["cells"], ver="modification")]
    if k == "unconflict":
        return [dict(base, kind="unconflict", sid=op["sid"], ref=op["ref"])]
    if k == "add_sheet":
        return [dict(base, kind="add_sheet", sid=op["sid"], name=op["name"], creator=op["author"])]
    if k == "delete_sheet":
        return [dict(base, kind="delete_sheet", sid=op["sid"])]
    if k == "restore_sheet":
        return [dict(base, kind="restore_sheet", sid=op["sid"], name=op["name"],
                     cells=op["cells"], rights=op["rights"])]
    if k == "rename":
        return [dict(base, kind="rename", sid=op["sid"], name=op["name"])]
    if k == "set_right":
        return [dict(base, kind="set_right", sid=op["sid"], person=op["person"], level=op["level"])]
    if k == "restore":
        return [dict(base, kind="restore", sid=op["sid"], name=op["name"], cells=op["cells"],
                     ver="restauration")]
    raise ValueError(k)


# ---------------------------------------------------------------- serveur

class Server:
    """Ordre de réception = ordre de décision. Un conflit est une écriture concurrente
    (base antérieure à la dernière écriture d'une autre personne) sur une valeur différente."""

    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.st = new_state(owner)
        self.st["sheets"]["s0"] = {"name": "Feuille1", "cells": {}, "rights": {}}
        net.register("server", self)

    def receive(self, src, msg):
        t = msg["type"]
        if t == "hello":
            self.net.send("server", src, {"type": "snapshot", "state": copy.deepcopy(self.st)})
        elif t == "op":
            self._op(src, msg["op"])
        elif t == "presence":
            eff = {"kind": "presence", "person": src, "sheet": msg["sheet"], "ref": msg["ref"]}
            apply_effect(self.st, eff)
            self._broadcast(None, [eff])

    def on_disconnect(self, name):
        eff = {"kind": "drop_presence", "person": name}
        apply_effect(self.st, eff)
        self._broadcast(None, [eff])

    def _broadcast(self, op_id, effects):
        msg = {"type": "effects", "op": op_id, "effects": effects}
        for name in list(self.net.nodes):
            if name != "server":
                self.net.send("server", name, msg)

    def _check(self, op):
        """Renvoie (motif_de_rejet, mode) ; mode ∈ apply | noop | conflict."""
        st = self.st
        sh = st["sheets"]
        owner = st["owner"]
        a = op["author"]
        k = op["kind"]
        if k == "set_right":
            if a != owner or op["sid"] not in sh:
                return "silent", None
            return None, "apply"
        if k == "add_sheet":
            return ("nom_existant", None) if name_taken(sh, op["name"]) else (None, "apply")
        if k == "restore_sheet":
            if op["sid"] in sh:
                return "silent", None
            return ("nom_existant", None) if name_taken(sh, op["name"]) else (None, "apply")
        sid = op["sid"]
        if sid not in sh:
            return ("silent", None) if k == "delete_sheet" else ("feuille_supprimee", None)
        right = W if a == owner else sh[sid]["rights"].get(a)
        if right != W:
            return ("droit_insuffisant" if k == "delete_sheet" else "modification_rejetee"), None
        if k == "delete_sheet":
            return ("silent", None) if len(sh) <= 1 else (None, "apply")
        if k == "rename":
            if op["name"] == sh[sid]["name"]:
                return None, "noop"
            return ("nom_existant", None) if name_taken(sh, op["name"], sid) else (None, "apply")
        if k == "set":
            rec = sh[sid]["cells"].get(op["ref"])
            if (rec is not None and rec.get("seq", 0) > op["base"]
                    and rec["by"] != a and rec["raw"] != op["raw"]):
                return None, "conflict"
        return None, "apply"

    def _op(self, src, op):
        if op["id"] in self.st["applied"]:
            self.net.send("server", src, {"type": "effects", "op": op["id"], "effects": []})
            return
        reject, mode = self._check(op)
        if reject is not None:
            self.net.send("server", src, {"type": "reject", "op": op["id"], "kind": reject,
                                          "sheet": op.get("sheet"), "cell": op.get("ref")})
            return
        self.st["seq"] += 1
        seq = self.st["seq"]
        if mode == "noop":
            effects = []
        elif mode == "conflict":
            effects = [{"kind": "conflict", "sid": op["sid"], "ref": op["ref"],
                        "discarded": op["raw"], "tz": op["tz"], "lit": op["lit"],
                        "by": op["author"], "seq": seq, "op": op["id"], "at": op["at"]}]
        else:
            effects = build_effects(op, seq)
        for e in effects:
            apply_effect(self.st, e)
        self.st["applied"].add(op["id"])
        self._broadcast(op["id"], effects)


# ---------------------------------------------------------------- copie locale

class Conflict:
    def __init__(self, c):
        self.discarded = c["discarded"]
        self.discarded_by = c["by"]
        self._tz = c["tz"]
        self._lit = c["lit"]


class Version:
    def __init__(self, entry, tz):
        self.id = entry["id"]
        self.author = entry["author"]
        self.kind = entry["kind"]
        self.timestamp = fmt_dt(entry["at"], tz)


class Client:
    """Copie locale d'une personne. `base` = dernier état reçu du serveur ; `pending` = ses
    opérations non confirmées ; la vue affichée = base + pending rejoués."""

    def __init__(self, net, clock, name, tz="UTC", _restore=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.base = new_state(None)
        self.pending = []
        self.undo_stack = []
        self.redo_stack = []
        self._alerts = []
        self.active = "Feuille1"
        self._open = None
        if _restore is not None:
            self.base, self.pending = _restore
        net.register(name, self)
        self._rebuild()
        if net.is_connected(name):
            self._hello()

    # --- réseau

    def _hello(self):
        self.net.send(self.name, "server", {"type": "hello"})

    def on_connect(self):
        self._hello()

    def receive(self, src, msg):
        t = msg["type"]
        if t == "snapshot":
            self.base = copy.deepcopy(msg["state"])
            done = self.base["applied"]
            self.pending = [p for p in self.pending if p["id"] not in done]
            for p in self.pending:
                self.net.send(self.name, "server", {"type": "op", "op": p})
        elif t == "effects":
            for e in msg["effects"]:
                apply_effect(self.base, e)
            if msg["op"] is not None:
                self.pending = [p for p in self.pending if p["id"] != msg["op"]]
        elif t == "reject":
            self.pending = [p for p in self.pending if p["id"] != msg["op"]]
            if msg["kind"] != "silent":
                self._alert(msg["kind"], msg["sheet"], msg["cell"])
        self._rebuild()

    # --- vue locale

    def _rebuild(self):
        v = copy.deepcopy(self.base)
        for p in self.pending:
            self._apply_local(v, p)
        self._view = v

    def _apply_local(self, v, op):
        for e in build_effects(op, None):
            apply_effect(v, e, record=False)

    @staticmethod
    def _cell(st, sid, ref):
        rec = st["sheets"].get(sid)
        return rec["cells"].get(ref) if rec is not None else None

    def _base_seq(self, sid, ref):
        rec = self._cell(self.base, sid, ref)
        if rec is None or rec.get("seq") is None:
            return 0
        return rec["seq"]

    def _next_id(self):
        return f"{self.name}#{next(_IDS)}"

    def _issue(self, kind, kw, oid=None):
        op = dict(kw)
        op["kind"] = kind
        op["id"] = oid or self._next_id()
        op["author"] = self.name
        op["at"] = self.clock.now()
        if kind == "set":
            op["base"] = self._base_seq(op["sid"], op["ref"])
        self.pending.append(op)
        self._apply_local(self._view, op)
        if self.net.is_connected(self.name):
            self.net.send(self.name, "server", {"type": "op", "op": op})
        return op

    def _record(self, kind, kw, inv, sid, ref=None, oid=None):
        self.redo_stack.clear()
        op = self._issue(kind, kw, oid)
        self.undo_stack.append({"op_id": op["id"], "sid": sid, "ref": ref,
                                "inv": inv, "fwd": (kind, kw)})

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _right(self, person, sid):
        st = self._view
        if sid is None or sid not in st["sheets"]:
            return None
        if person == st["owner"]:
            return W
        return st["sheets"][sid]["rights"].get(person)

    def _src(self):
        return self._open if self._open is not None else self._view["sheets"]

    # --- état et lectures

    def connection_status(self):
        return "en ligne" if self.net.is_connected(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def alerts(self):
        return list(self._alerts)

    def set_timezone(self, tz):
        self.tz = tz

    def sheets(self):
        return [rec["name"] for rec in self._view["sheets"].values()]

    def activate(self, name):
        if find_sid(self._view["sheets"], name) is not None:
            self.active = name

    def right(self, person, sheet):
        return self._right(person, find_sid(self._view["sheets"], sheet))

    def content(self, ref, sheet=None):
        sheets = self._src()
        sid = find_sid(sheets, sheet or self.active)
        if sid is None:
            return None
        rec = sheets[sid]["cells"].get(ref.upper())
        return rec["raw"] if rec is not None else None

    def _eval(self, ref, sheet):
        sheets = self._src()
        sid = find_sid(sheets, sheet or self.active)
        if sid is None:
            return None
        return cell_value(Ctx(sheets, self.clock, self.tz), sid, ref.upper(), [])

    def value(self, ref, sheet=None):
        return display(self._eval(ref, sheet), self.tz)

    def error(self, ref, sheet=None):
        v = self._eval(ref, sheet)
        return v.code if isinstance(v, Err) else None

    # --- saisies

    def set_cell(self, ref, text, sheet=None):
        self._write(ref.upper(), text, False, sheet)

    def clear(self, ref, sheet=None):
        self._write(ref.upper(), None, False, sheet)

    def _write(self, ref, raw, lit, sheet):
        if self._open is not None:
            return
        name = sheet or self.active
        sid = find_sid(self._view["sheets"], name)
        if sid is None:
            return
        if self._right(self.name, sid) != W:
            self._alert("droit_insuffisant", name, ref)
            return
        prev = self._cell(self._view, sid, ref)
        inv = ("set", {"sid": sid, "sheet": name, "ref": ref,
                       "raw": prev["raw"] if prev else None,
                       "tz": prev["tz"] if prev else self.tz,
                       "lit": prev["lit"] if prev else False})
        self._record("set", {"sid": sid, "sheet": name, "ref": ref, "raw": raw,
                             "tz": self.tz, "lit": lit}, inv, sid, ref)

    # --- feuilles et droits

    def add_sheet(self, name):
        if self._open is not None:
            return
        if name_taken(self._view["sheets"], name):
            self._alert("nom_existant", name)
            return
        oid = self._next_id()
        self._record("add_sheet", {"sid": oid, "name": name, "sheet": name},
                     ("delete_sheet", {"sid": oid, "sheet": name}), oid, None, oid)

    def delete_sheet(self, name):
        if self._open is not None:
            return
        sheets = self._view["sheets"]
        sid = find_sid(sheets, name)
        if sid is None:
            return
        if self._right(self.name, sid) != W:
            self._alert("droit_insuffisant", name)
            return
        if len(sheets) <= 1:
            return
        rec = sheets[sid]
        inv = ("restore_sheet", {"sid": sid, "name": rec["name"], "sheet": name,
                                 "cells": copy.deepcopy(rec["cells"]),
                                 "rights": copy.deepcopy(rec["rights"])})
        self._record("delete_sheet", {"sid": sid, "sheet": name}, inv, sid)

    def rename_sheet(self, old, new):
        if self._open is not None:
            return
        sheets = self._view["sheets"]
        sid = find_sid(sheets, old)
        if sid is None:
            return
        if self._right(self.name, sid) != W:
            self._alert("droit_insuffisant", old)
            return
        if new == old:
            return
        if name_taken(sheets, new, sid):
            self._alert("nom_existant", new)
            return
        inv = ("rename", {"sid": sid, "name": old, "sheet": new})
        self._record("rename", {"sid": sid, "name": new, "sheet": old}, inv, sid)

    def set_right(self, person, sheet, level):
        st = self._view
        if self._open is not None or self.name != st["owner"]:
            return
        if not self.net.is_connected(self.name):
            return
        sid = find_sid(st["sheets"], sheet)
        if sid is None:
            return
        self._issue("set_right", {"sid": sid, "person": person, "level": level, "sheet": sheet})

    # --- import, export

    def import_csv(self, data):
        if self._open is not None:
            return
        name = self.active
        sid = find_sid(self._view["sheets"], name)
        if sid is None:
            return
        if self._right(self.name, sid) != W:
            self._alert("droit_insuffisant", name)
            return
        rows, bad = parse_csv(data.decode("utf-8-sig"))
        if bad is not None:
            self._alert("csv_invalide", name, None, bad)
            return
        cells, inv_cells = [], []
        for j, row in enumerate(rows, start=1):
            for i, field in enumerate(row, start=1):
                ref = ref_of(i, j)
                prev = self._cell(self._view, sid, ref)
                if prev is not None:
                    inv_cells.append((ref, prev["raw"], prev["tz"], prev["lit"]))
                else:
                    inv_cells.append((ref, None, self.tz, False))
                if field == "":
                    cells.append((ref, None, self.tz, False))
                else:
                    cells.append((ref, field, self.tz, field.startswith("=")))
        self._record("batch", {"sid": sid, "sheet": name, "cells": cells},
                     ("batch", {"sid": sid, "sheet": name, "cells": inv_cells}), sid)

    def export_csv(self):
        sheets = self._src()
        sid = find_sid(sheets, self.active)
        if sid is None:
            return b""
        cells = sheets[sid]["cells"]
        ctx = Ctx(sheets, self.clock, self.tz)
        maxc = maxr = 0
        for ref, rec in cells.items():
            if rec["raw"] is not None:
                c, r = split_ref(ref)
                maxc = max(maxc, c)
                maxr = max(maxr, r)
        out = []
        for r in range(1, maxr + 1):
            fields = [csv_text(cell_value(ctx, sid, ref_of(c, r), []), self.tz)
                      for c in range(1, maxc + 1)]
            if any(fields):
                out.append(fields)
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(out)
        return buf.getvalue().encode("utf-8")

    # --- annulation, rétablissement

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if not self.undo_stack:
            return
        e = self.undo_stack.pop()
        if (self.pending and self.pending[-1]["id"] == e["op_id"]
                and not self.net.is_connected(self.name)):
            self.pending.pop()
            self._rebuild()
            self.redo_stack.append(e)
            return
        sid = e["sid"]
        if e["ref"] is not None:
            if sid not in self._view["sheets"]:
                return
            cur = self._cell(self._view, sid, e["ref"])
            if cur is None or cur["by"] != self.name:
                self._alert("annulation_impossible", self._view["sheets"][sid]["name"], e["ref"])
                return
        if sid in self._view["sheets"] and self._right(self.name, sid) != W:
            return
        kind, kw = e["inv"]
        self._issue(kind, dict(kw))
        self.redo_stack.append(e)

    def redo(self):
        if not self.redo_stack:
            return
        e = self.redo_stack.pop()
        sid = e["sid"]
        if sid is not None and sid in self._view["sheets"] and self._right(self.name, sid) != W:
            return
        kind, kw = e["fwd"]
        op = self._issue(kind, dict(kw))
        ne = dict(e)
        ne["op_id"] = op["id"]
        self.undo_stack.append(ne)

    # --- versions

    def history(self, sheet=None):
        sid = find_sid(self.base["sheets"], sheet or self.active)
        if sid is None:
            return []
        entries = [v for v in self.base["versions"] if v["sid"] == sid]
        entries.sort(key=lambda v: (v["at"], v["id"]), reverse=True)
        return [Version(v, self.tz) for v in entries]

    def _version(self, vid):
        for v in self.base["versions"]:
            if v["id"] == vid:
                return v
        return None

    def open_version(self, vid):
        v = self._version(vid)
        if v is not None:
            self._open = copy.deepcopy(v["state"])

    def close_version(self):
        self._open = None

    def restore_version(self, vid):
        if self._open is not None:
            return
        v = self._version(vid)
        if v is None or v["sid"] not in self._view["sheets"] or v["sid"] not in v["state"]:
            return
        sid = v["sid"]
        if self._right(self.name, sid) != W:
            return
        src = v["state"][sid]
        cur = self._view["sheets"][sid]
        inv = ("restore", {"sid": sid, "name": cur["name"], "cells": copy.deepcopy(cur["cells"])})
        self._record("restore", {"sid": sid, "name": src["name"], "sheet": src["name"],
                                 "cells": copy.deepcopy(src["cells"])}, inv, sid)

    # --- présence, conflits

    def select(self, ref, sheet=None):
        if not self.net.is_connected(self.name):
            return
        self.net.send(self.name, "server", {"type": "presence", "sheet": sheet or self.active,
                                            "ref": ref.upper()})

    def presence(self):
        if not self.net.is_connected(self.name):
            return {}
        return {p: v for p, v in self.base["presence"].items() if p != self.name}

    def conflict(self, ref, sheet=None):
        sid = find_sid(self.base["sheets"], sheet or self.active)
        c = self.base["conflicts"].get((sid, ref.upper()))
        return Conflict(c) if c is not None else None

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self._open is not None:
            return
        name = sheet or self.active
        sid = find_sid(self._view["sheets"], name)
        c = self.base["conflicts"].get((sid, ref.upper()))
        if sid is None or c is None or self._right(self.name, sid) != W:
            return
        if use_discarded:
            self._issue("set", {"sid": sid, "sheet": name, "ref": ref.upper(),
                                "raw": c["discarded"], "tz": c["tz"], "lit": c["lit"]})
        else:
            self._issue("unconflict", {"sid": sid, "sheet": name, "ref": ref.upper()})

    # --- redémarrage

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz,
                      _restore=(copy.deepcopy(self.base), list(self.pending)))
