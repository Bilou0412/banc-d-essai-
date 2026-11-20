"""Classeur collaboratif hors ligne (couche code, tour 1).

Un serveur autoritaire reçoit des opérations par un réseau simulé en mémoire. Chaque
personne a sa copie : le dernier instantané reçu du serveur, plus ses opérations locales
non confirmées rejouées par-dessus. Les valeurs sont calculées sur la copie locale.
"""
import csv
import io
import re
import sys
import uuid
from collections import deque
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.setrecursionlimit(100000)

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
W = "écriture"
R = "lecture"
SERVER = "__serveur__"


# ------------------------------------------------------------------ temps

class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


def fmt_instant(instant, tz):
    return instant.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


def iso_instant(instant, tz):
    return instant.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")


# ------------------------------------------------------------------ valeurs et objets visibles

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind, self.sheet, self.cell, self.line = kind, sheet, cell, line

    def __repr__(self):
        return f"Alert({self.kind!r}, {self.sheet!r}, {self.cell!r}, {self.line!r})"


class Conflict:
    def __init__(self, discarded, discarded_by, cell):
        self.discarded = discarded
        self.discarded_by = discarded_by
        self.cell = cell  # contenu écarté (dict), repris si on choisit la valeur écartée


class Version:
    """Vue d'une version pour une personne : horodatage dans son fuseau."""

    def __init__(self, v, tz):
        self.id = v["id"]
        self.author = v["author"]
        self.kind = v["kind"]
        self.sheet = v["name"]
        self.instant = v["instant"]
        self.timestamp = fmt_instant(v["instant"], tz)


class DT:
    """Date-heure. `tz` : fuseau de saisie si la saisie n'a pas de décalage, sinon None."""

    def __init__(self, instant, tz=None, text=None):
        self.instant, self.tz, self.text = instant, tz, text


class DATE:
    def __init__(self, day):
        self.day = day


class ErrVal:
    def __init__(self, code):
        self.code = code


class XErr(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?")
OFFSET_RE = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


def parse_literal(text, tz):
    """Interprète le texte d'une cellule hors formule : nombre, date, date-heure ou texte."""
    if NUM_RE.fullmatch(text):
        return float(text) if "." in text else int(text)
    if DATE_RE.fullmatch(text):
        return DATE(date.fromisoformat(text))
    if DT_RE.fullmatch(text):
        if OFFSET_RE.search(text):
            return DT(datetime.fromisoformat(text).astimezone(UTC))
        naive = datetime.fromisoformat(text)
        return DT(naive.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC), tz=tz, text=text)
    return text


def display(v, viewer_tz):
    if isinstance(v, DT):
        if v.tz is not None and v.tz == viewer_tz and v.text is not None:
            return v.text
        return fmt_instant(v.instant, viewer_tz)
    if isinstance(v, DATE):
        return v.day.isoformat()
    return v


def export_text(v, viewer_tz):
    if v is None:
        return ""
    if isinstance(v, ErrVal):
        return v.code
    if isinstance(v, DT):
        return iso_instant(v.instant, viewer_tz)
    if isinstance(v, DATE):
        return v.day.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def serial(v):
    if isinstance(v, DT):
        return (v.instant - EPOCH).total_seconds() / 86400
    if isinstance(v, DATE):
        return float((v.day - EPOCH.date()).days)
    return v


def is_formula(cell):
    return cell is not None and not cell.get("literal") and cell["text"].startswith("=")


def _text(cell):
    return None if cell is None else cell["text"]


# ------------------------------------------------------------------ analyse des formules

TOKEN_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<ref>(?:(?P<sheet>[^\W\d]\w*)!)?(?P<col>[A-Za-z]{1,3})(?P<row>\d+))(?!\w)"
    r"|(?P<func>[^\W\d]\w*)(?=\()"
    r"|(?P<op>[-+*/(),:])"
)


class _Syntax(Exception):
    pass


def _tokens(src):
    toks, pos = [], 0
    while True:
        while pos < len(src) and src[pos].isspace():
            pos += 1
        if pos >= len(src):
            return toks
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise _Syntax()
        pos = m.end()
        if m.group("num") is not None:
            toks.append(("num", m.group("num")))
        elif m.group("ref") is not None:
            toks.append(("ref", (m.group("sheet"), m.group("col").upper(), int(m.group("row")))))
        elif m.group("func") is not None:
            toks.append(("func", m.group("func").upper()))
        else:
            toks.append(("op", m.group("op")))


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, op):
        if self.peek() != ("op", op):
            raise _Syntax()
        self.i += 1

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
            if self.peek() == ("op", ":"):
                self.take()
                kind2, val2 = self.take()
                if kind2 != "ref":
                    raise _Syntax()
                return ("range", val, val2)
            return ("ref", val)
        if kind == "func":
            if val not in ("SOMME", "MAINTENANT"):
                raise _Syntax()
            self.expect("(")
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect(")")
            return ("call", val, args)
        if (kind, val) == ("op", "("):
            node = self.expr()
            self.expect(")")
            return node
        raise _Syntax()


_AST_CACHE = {}


def parse_formula(text):
    """Arbre d'une formule (texte commençant par '='), ou None si la syntaxe est invalide."""
    if text in _AST_CACHE:
        return _AST_CACHE[text]
    try:
        toks = _tokens(text[1:])
        p = _Parser(toks)
        node = p.expr()
        if p.i != len(toks):
            raise _Syntax()
    except _Syntax:
        node = None
    _AST_CACHE[text] = node
    return node


def col_letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def key_of(col, row):
    return f"{col_letters(col)}{row}"


def split_key(key):
    m = re.fullmatch(r"([A-Z]+)(\d+)", key)
    return col_index(m.group(1)), int(m.group(2))


class Calc:
    """Calcul sur un jeu de feuilles : graphe de dépendances, cycles, erreurs, valeurs."""

    def __init__(self, sheets, now):
        self.sheets = sheets  # uid -> {"name", "cells"}
        self.now = now
        self._succ = {}

    def _uid(self, name, here):
        if name is None:
            return here
        for uid, sh in self.sheets.items():
            if sh["name"] == name:
                return uid
        return None

    def _targets(self, node, here):
        """(uid, [clés]) désignées par une référence ou une plage ; uid None si feuille absente."""
        if node[0] == "ref":
            sheet, col, row = node[1]
            c1 = c2 = col_index(col)
            r1 = r2 = row
        else:
            sheet, col, row = node[1]
            _, col2, row2 = node[2]
            c1, c2 = sorted((col_index(col), col_index(col2)))
            r1, r2 = sorted((row, row2))
        uid = self._uid(sheet, here)
        keys = [key_of(c, r) for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)]
        return uid, keys

    def _walk(self, node, here, out):
        k = node[0]
        if k in ("ref", "range"):
            uid, keys = self._targets(node, here)
            if uid is not None:
                out.extend((uid, key) for key in keys)
        elif k == "neg":
            self._walk(node[1], here, out)
        elif k == "bin":
            self._walk(node[2], here, out)
            self._walk(node[3], here, out)
        elif k == "call":
            for a in node[2]:
                self._walk(a, here, out)

    def _succ_of(self, nk):
        if nk in self._succ:
            return self._succ[nk]
        uid, key = nk
        out = []
        sh = self.sheets.get(uid)
        cell = sh["cells"].get(key) if sh else None
        if is_formula(cell):
            ast = parse_formula(cell["text"])
            if ast is not None:
                self._walk(ast, uid, out)
        self._succ[nk] = out
        return out

    def reaches_cycle(self, start):
        """Vrai si `start` dépend, directement ou non, d'un cycle du graphe."""
        color = {start: 1}
        stack = [(start, iter(self._succ_of(start)))]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = 2
                stack.pop()
                continue
            c = color.get(nxt, 0)
            if c == 1:
                return True
            if c == 0:
                color[nxt] = 1
                stack.append((nxt, iter(self._succ_of(nxt))))
        return False

    def top(self, uid, key):
        if self.reaches_cycle((uid, key)):
            return ErrVal("#CIRC!")
        try:
            return self._cell(uid, key)
        except XErr as e:
            return ErrVal(e.code)

    def _cell(self, uid, key):
        cell = self.sheets[uid]["cells"].get(key)
        if cell is None:
            return None
        if cell.get("literal"):
            return cell["text"]
        if not cell["text"].startswith("="):
            return parse_literal(cell["text"], cell["tz"])
        ast = parse_formula(cell["text"])
        if ast is None:
            raise XErr("#SYNTAXE!")
        r = self._eval(ast, uid)
        return 0 if r is None else r

    def _range_pairs(self, node, here):
        uid, keys = self._targets(node, here)
        if uid is None:
            raise XErr("#REF!")
        return [(uid, k) for k in keys]

    @staticmethod
    def _num(v):
        if v is None:
            return 0
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, (DT, DATE)):
            return serial(v)
        raise XErr("#TYPE!")

    def _eval(self, node, here):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            uid, keys = self._targets(node, here)
            if uid is None:
                raise XErr("#REF!")
            return self._cell(uid, keys[0])
        if k == "neg":
            return -self._num(self._eval(node[1], here))
        if k == "bin":
            a = self._num(self._eval(node[2], here))
            b = self._num(self._eval(node[3], here))
            op = node[1]
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if b == 0:
                raise XErr("#DIV/0!")
            return a / b
        if k == "call":
            if node[1] == "MAINTENANT":
                return DT(self.now())
            total = 0
            for a in node[2]:
                if a[0] == "range":
                    for uid, key in self._range_pairs(a, here):
                        v = self._cell(uid, key)
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            total += v
                else:
                    v = self._eval(a, here)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        total += v
            return total
        raise XErr("#SYNTAXE!")


# ------------------------------------------------------------------ CSV (parseur maison)

def parse_csv(text):
    """Renvoie (lignes, None), ou (None, ligne) si un guillemet n'est jamais fermé."""
    rows, row, field = [], [], []
    in_q, q_line = False, None
    line = 1
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_q:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_q = False
            else:
                if ch == "\n":
                    line += 1
                field.append(ch)
            i += 1
            continue
        if ch == '"' and not field:
            in_q, q_line = True, line
        elif ch == ",":
            row.append("".join(field))
            field = []
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
            line += 1
        else:
            field.append(ch)
        i += 1
    if in_q:
        return None, q_line
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows, None


# ------------------------------------------------------------------ primitives d'état

def _new_uid():
    return uuid.uuid4().hex[:10]


def _taken(sheets, name, except_uid):
    return any(sh["name"].upper() == name.upper() and uid != except_uid for uid, sh in sheets.items())


def _rename(sheets, uid, new):
    old = sheets[uid]["name"]
    sheets[uid]["name"] = new
    pat = re.compile(r"(?<!\w)" + re.escape(old) + "!")
    for sh in sheets.values():
        cells = sh["cells"]
        for key, cell in list(cells.items()):
            if is_formula(cell) and pat.search(cell["text"]):
                cells[key] = dict(cell, text=pat.sub(lambda m: new + "!", cell["text"]))


def applicable(sheets, p):
    """Une primitive en attente ne s'applique que si sa feuille est connue de la copie.

    Une feuille créée localement dont l'accusé arrive avant le snapshot n'est pas encore
    dans la copie : les primitives qui la visent attendent le snapshot suivant, qui fait foi.
    Une création déjà présente dans le snapshot n'est pas rejouée (elle n'écraserait pas
    le contenu reçu des autres).
    """
    if p["t"] == "sheet_add":
        return p["uid"] not in sheets
    return p["uid"] in sheets


def apply_prim(sheets, conflicts, p):
    t = p["t"]
    if t in ("set", "resolve"):
        cells = sheets[p["uid"]]["cells"]
        if p["cell"] is None:
            cells.pop(p["key"], None)
        else:
            cells[p["key"]] = p["cell"]
        conflicts.pop((p["uid"], p["key"]), None)
    elif t == "sheet_add":
        sheets[p["uid"]] = {"name": p["name"], "cells": dict(p["cells"]), "rights": dict(p["rights"])}
    elif t == "sheet_del":
        sheets.pop(p["uid"], None)
    elif t == "sheet_ren":
        _rename(sheets, p["uid"], p["name"])
    elif t == "sheet_cells":
        sheets[p["uid"]]["cells"] = dict(p["cells"])
    else:
        raise ValueError(t)


# ------------------------------------------------------------------ réseau simulé

class Network:
    """Messages en vol, coupures. Rien n'est livré sans deliver_*."""

    def __init__(self):
        self.endpoints = {}
        self.offline = set()
        self.queue = deque()

    def attach(self, name, endpoint):
        self.endpoints[name] = endpoint

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def is_online(self, name):
        return name not in self.offline

    def disconnect(self, name):
        if name in self.offline:
            return
        self.offline.add(name)
        self.queue = deque(m for m in self.queue if m[0] != name and m[1] != name)
        server = self.endpoints.get(SERVER)
        if server is not None:
            server.on_disconnect(name)

    def reconnect(self, name):
        if name not in self.offline:
            return
        self.offline.discard(name)
        client = self.endpoints.get(name)
        if client is not None and name != SERVER:
            client.on_reconnect()
        server = self.endpoints.get(SERVER)
        if server is not None:
            server.on_connect(name)

    def cancel(self, opid):
        self.queue = deque(
            m for m in self.queue
            if not (m[2].get("type") == "op" and m[2]["op"]["id"] == opid))

    def _deliver(self, src, dst, msg):
        if src in self.offline or dst in self.offline:
            return
        ep = self.endpoints.get(dst)
        if ep is not None:
            ep.receive(src, msg)

    def deliver_all(self):
        while self.queue:
            src, dst, msg = self.queue.popleft()
            self._deliver(src, dst, msg)

    def deliver_from(self, name):
        batch = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for src, dst, msg in batch:
            self._deliver(src, dst, msg)


# ------------------------------------------------------------------ serveur

def _empty_snap():
    return {"owner": None, "sheets": {}, "versions": [], "revs": {}, "conflicts": {}}


class Server:
    def __init__(self, net, clock, owner):
        self.net, self.clock, self.owner = net, clock, owner
        self.sheets = {}
        self.sheets[_new_uid()] = {"name": "Feuille1", "cells": {}, "rights": {owner: W}}
        self.versions = []
        self.revs, self.writers, self.conflicts = {}, {}, {}
        self.presence = {}
        self.applied = set()
        self.next_version = 1
        net.attach(SERVER, self)

    def snapshot(self):
        return {
            "owner": self.owner,
            "sheets": {uid: {"name": sh["name"], "cells": dict(sh["cells"]),
                             "rights": dict(sh["rights"])} for uid, sh in self.sheets.items()},
            "versions": list(self.versions),
            "revs": dict(self.revs),
            "conflicts": dict(self.conflicts),
        }

    def _broadcast(self, msg):
        for name in list(self.net.endpoints):
            if name != SERVER:
                self.net.send(SERVER, name, msg)

    def _broadcast_presence(self):
        self._broadcast({"type": "presence", "presence": dict(self.presence)})

    def receive(self, src, msg):
        t = msg["type"]
        if t == "hello":
            self.net.send(SERVER, src, {"type": "snap", "snap": self.snapshot()})
        elif t == "op":
            self._on_op(src, msg["op"])
        elif t == "right":
            self._on_right(src, msg)
        elif t == "select":
            self.presence[src] = (msg["sheet"], msg["key"])
            self._broadcast_presence()

    def on_connect(self, name):
        self.net.send(SERVER, name, {"type": "snap", "snap": self.snapshot()})
        self.net.send(SERVER, name, {"type": "presence", "presence": dict(self.presence)})

    def on_disconnect(self, name):
        self.presence.pop(name, None)
        self._broadcast_presence()

    def _on_op(self, src, op):
        if op["id"] in self.applied:
            self.net.send(SERVER, src, {"type": "ack", "opid": op["id"], "status": "ok",
                                        "conflict": False, "info": None})
            return
        self.applied.add(op["id"])
        status, info, conflict = self._apply_op(op)
        self.net.send(SERVER, src, {"type": "ack", "opid": op["id"], "status": status,
                                    "conflict": conflict, "info": info})
        self._broadcast({"type": "snap", "snap": self.snapshot()})

    def _refusal(self, author, p):
        t = p["t"]
        if t == "sheet_add":
            if _taken(self.sheets, p["name"], None):
                return {"kind": "nom_existant", "sheet": p["name"]}
            return None
        uid = p["uid"]
        if uid not in self.sheets:
            return {"kind": "feuille_supprimee", "sheet": p["sheet_name"]}
        sh = self.sheets[uid]
        if t == "sheet_ren" and _taken(self.sheets, p["name"], uid):
            return {"kind": "nom_existant", "sheet": p["name"]}
        if t == "sheet_del" and len(self.sheets) <= 1:
            return {"kind": None}
        if sh["rights"].get(author) != W:
            return {"kind": "modification_rejetee", "sheet": sh["name"], "cell": p.get("key")}
        return None

    def _apply_op(self, op):
        author = op["author"]
        for p in op["prims"]:
            bad = self._refusal(author, p)
            if bad is not None:
                return "rejet", bad, False
        conflict = False
        changed = False
        for p in op["prims"]:
            if p["t"] == "set":
                key = (p["uid"], p["key"])
                cur = self.sheets[p["uid"]]["cells"].get(p["key"])
                writer = self.writers.get(key)
                if (writer not in (None, author) and p["base"] < self.revs.get(key, 0)
                        and _text(cur) != _text(p["cell"])):
                    self.conflicts[key] = Conflict(_text(p["cell"]), author, p["cell"])
                    conflict = True
                    continue
            if p["t"] in ("set", "resolve"):
                key = (p["uid"], p["key"])
                self.revs[key] = self.revs.get(key, 0) + 1
                self.writers[key] = author
            apply_prim(self.sheets, self.conflicts, p)
            changed = True
        vuid = op.get("vuid")
        if changed and vuid is not None and vuid in self.sheets:
            self.versions.append({"id": self.next_version, "author": author, "instant": op["time"],
                                  "kind": op["kind"], "uid": vuid,
                                  "name": self.sheets[vuid]["name"],
                                  "cells": dict(self.sheets[vuid]["cells"])})
            self.next_version += 1
        return "ok", None, conflict

    def _on_right(self, src, msg):
        if src != self.owner or msg["person"] == self.owner:
            return
        sh = self.sheets.get(msg["uid"])
        if sh is None:
            return
        if msg["level"] is None:
            sh["rights"].pop(msg["person"], None)
        else:
            sh["rights"][msg["person"]] = msg["level"]
        self._broadcast({"type": "snap", "snap": self.snapshot()})

# ------------------------------------------------------------------ client

class Client:
    def __init__(self, net, clock, name, tz="UTC", store=None):
        self.net, self.clock, self.name, self.tz = net, clock, name, tz
        self.store = store if store is not None else {"outbox": [], "snap": None, "seq": 0}
        self._alerts = []
        self.undo_stack, self.redo_stack = [], []
        self.presence_map = {}
        self.active = None
        self.viewing = None
        self.rep = None
        net.attach(name, self)
        self._rebuild()
        if net.is_online(name):
            net.send(name, SERVER, {"type": "hello"})
            self.on_reconnect()

    # --- réseau -------------------------------------------------------------

    def receive(self, src, msg):
        t = msg["type"]
        if t == "snap":
            self.store["snap"] = msg["snap"]
            self._rebuild()
        elif t == "ack":
            self._on_ack(msg)
        elif t == "presence":
            self.presence_map = dict(msg["presence"])

    def on_reconnect(self):
        if not self.net.is_online(self.name):
            return
        for op in self.store["outbox"]:
            self.net.send(self.name, SERVER, {"type": "op", "op": op})

    def _on_ack(self, msg):
        op = next((o for o in self.store["outbox"] if o["id"] == msg["opid"]), None)
        if op is None:
            return
        self.store["outbox"].remove(op)
        if msg["status"] == "rejet":
            info = msg["info"] or {}
            if info.get("kind"):
                self._alert(info["kind"], info.get("sheet"), info.get("cell"))
        elif msg["conflict"] and op["origin"] == "undo":
            self._alert("annulation_impossible", op["sheet"], op["cell"])
        self._rebuild()

    # --- copie locale ----------------------------------------------------------

    def _snap(self):
        return self.store["snap"] or _empty_snap()

    def _rebuild(self):
        snap = self._snap()
        self.rep = {
            "sheets": {uid: {"name": s["name"], "cells": dict(s["cells"]),
                             "rights": dict(s["rights"])} for uid, s in snap["sheets"].items()},
            "conflicts": dict(snap["conflicts"]),
        }
        for op in self.store["outbox"]:
            for p in op["prims"]:
                if applicable(self.rep["sheets"], p):
                    apply_prim(self.rep["sheets"], self.rep["conflicts"], p)

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _owner(self):
        return self._snap().get("owner")

    def _uid(self, sheet):
        sheets = self.rep["sheets"]
        if sheet is None:
            if self.active in sheets:
                return self.active
            return next(iter(sheets), None)
        for uid, s in sheets.items():
            if s["name"] == sheet:
                return uid
        return None

    def _writable(self, uid):
        sh = self.rep["sheets"].get(uid)
        return sh is not None and sh["rights"].get(self.name) == W

    def _cells(self, uid):
        if self.viewing is not None and self.viewing["uid"] == uid:
            return self.viewing["cells"]
        sh = self.rep["sheets"].get(uid)
        return sh["cells"] if sh else {}

    def _calc(self):
        sheets = self.rep["sheets"]
        if self.viewing is not None:
            sheets = {uid: (dict(s, cells=self.viewing["cells"]) if uid == self.viewing["uid"] else s)
                      for uid, s in sheets.items()}
        return Calc(sheets, self.clock.now)

    def _setp(self, uid, key, cell, t="set"):
        sh = self.rep["sheets"][uid]
        return {"t": t, "uid": uid, "key": key, "cell": cell,
                "base": self._snap()["revs"].get((uid, key), 0), "sheet_name": sh["name"]}

    def _changes(self, p):
        sheets = self.rep["sheets"]
        t = p["t"]
        if t == "resolve":
            return True
        if t == "set":
            return _text(sheets[p["uid"]]["cells"].get(p["key"])) != _text(p["cell"])
        if t == "sheet_add":
            return True
        if t == "sheet_del":
            return p["uid"] in sheets
        if t == "sheet_ren":
            return sheets[p["uid"]]["name"] != p["name"]
        if t == "sheet_cells":
            return sheets[p["uid"]]["cells"] != p["cells"]
        return False

    def _inverse(self, p):
        sheets = self.rep["sheets"]
        t = p["t"]
        if t in ("set", "resolve"):
            prev = sheets[p["uid"]]["cells"].get(p["key"])
            return self._setp(p["uid"], p["key"], prev)
        if t == "sheet_add":
            return {"t": "sheet_del", "uid": p["uid"], "sheet_name": p["name"]}
        if t == "sheet_del":
            s = sheets[p["uid"]]
            return {"t": "sheet_add", "uid": p["uid"], "name": s["name"], "cells": dict(s["cells"]),
                    "rights": dict(s["rights"]), "sheet_name": s["name"]}
        if t == "sheet_ren":
            return {"t": "sheet_ren", "uid": p["uid"], "name": sheets[p["uid"]]["name"],
                    "sheet_name": p["name"]}
        if t == "sheet_cells":
            s = sheets[p["uid"]]
            return {"t": "sheet_cells", "uid": p["uid"], "cells": dict(s["cells"]),
                    "sheet_name": s["name"]}
        raise ValueError(t)

    def _do(self, prims, origin, kind="modification", vuid=None):
        """Exécute une action locale : une opération, envoyée dès que le réseau le permet."""
        if not any(self._changes(p) for p in prims):
            return None
        inv = []
        for p in prims:
            inv.append(self._inverse(p))
            apply_prim(self.rep["sheets"], self.rep["conflicts"], p)
        inv.reverse()
        self.store["seq"] += 1
        op = {"id": f"{self.name}#{self.store['seq']}", "author": self.name, "prims": prims,
              "time": self.clock.now(), "kind": kind, "vuid": vuid, "origin": origin,
              "sheet": prims[0].get("sheet_name"), "cell": prims[0].get("key")}
        self.store["outbox"].append(op)
        if self.net.is_online(self.name):
            self.net.send(self.name, SERVER, {"type": "op", "op": op})
        return {"fwd": prims, "inv": inv, "op": op["id"]}

    def _pending(self, opid):
        return any(o["id"] == opid for o in self.store["outbox"])

    def _cancel(self, opid):
        self.store["outbox"] = [o for o in self.store["outbox"] if o["id"] != opid]
        self.net.cancel(opid)
        self._rebuild()

    def _record(self, action):
        self.undo_stack.append(action)
        self.redo_stack.clear()

    # --- saisie ----------------------------------------------------------------

    def _edit(self, ref, sheet, text):
        uid = self._uid(sheet)
        key = ref.upper()
        if uid is None or self.viewing is not None:
            return
        if not self._writable(uid):
            self._alert("droit_insuffisant", self.rep["sheets"][uid]["name"], key)
            return
        cell = None
        if text:
            cell = {"text": text, "tz": self.tz, "literal": False}
        act = self._do([self._setp(uid, key, cell)], "user", vuid=uid)
        if act is not None:
            self._record(act)

    def set_cell(self, ref, text, sheet=None):
        self._edit(ref, sheet, text)

    def clear(self, ref, sheet=None):
        self._edit(ref, sheet, None)

    def content(self, ref, sheet=None):
        uid = self._uid(sheet)
        cell = self._cells(uid).get(ref.upper()) if uid is not None else None
        return None if cell is None else cell["text"]

    def value(self, ref, sheet=None):
        uid = self._uid(sheet)
        if uid is None:
            return None
        v = self._calc().top(uid, ref.upper())
        if isinstance(v, ErrVal):
            return v.code
        return display(v, self.tz)

    def error(self, ref, sheet=None):
        uid = self._uid(sheet)
        if uid is None:
            return None
        v = self._calc().top(uid, ref.upper())
        return v.code if isinstance(v, ErrVal) else None

    def set_timezone(self, tz):
        self.tz = tz

    def activate(self, name):
        uid = self._uid(name)
        if uid is not None:
            self.active = uid

    # --- feuilles ------------------------------------------------------------------

    def sheets(self):
        return [s["name"] for s in self.rep["sheets"].values()]

    def add_sheet(self, name):
        if self.viewing is not None:
            return
        if _taken(self.rep["sheets"], name, None):
            self._alert("nom_existant", name)
            return
        owner = self._owner()
        rights = {self.name: W}
        if owner is not None:
            rights[owner] = W
        p = {"t": "sheet_add", "uid": _new_uid(), "name": name, "cells": {}, "rights": rights,
             "sheet_name": name}
        act = self._do([p], "user")
        if act is not None:
            self._record(act)

    def delete_sheet(self, name):
        uid = self._uid(name)
        if uid is None or self.viewing is not None:
            return
        if not self._writable(uid):
            self._alert("droit_insuffisant", name)
            return
        if len(self.rep["sheets"]) <= 1:
            return
        p = {"t": "sheet_del", "uid": uid, "sheet_name": name}
        act = self._do([p], "user")
        if act is not None:
            self._record(act)

    def rename_sheet(self, old, new):
        uid = self._uid(old)
        if uid is None or self.viewing is not None or new == old:
            return
        if not self._writable(uid):
            self._alert("droit_insuffisant", old)
            return
        if _taken(self.rep["sheets"], new, uid):
            self._alert("nom_existant", new)
            return
        p = {"t": "sheet_ren", "uid": uid, "name": new, "sheet_name": old}
        act = self._do([p], "user")
        if act is not None:
            self._record(act)

    # --- droits ------------------------------------------------------------------

    def right(self, person, sheet):
        uid = self._uid(sheet)
        if uid is None:
            return None
        return self.rep["sheets"][uid]["rights"].get(person)

    def set_right(self, person, sheet, level):
        if self.name != self._owner() or not self.net.is_online(self.name) or self.viewing is not None:
            return
        uid = self._uid(sheet)
        if uid is None or person == self.name or self.right(person, sheet) == level:
            return
        rights = self.rep["sheets"][uid]["rights"]
        if level is None:
            rights.pop(person, None)
        else:
            rights[person] = level
        self.net.send(self.name, SERVER, {"type": "right", "uid": uid, "person": person, "level": level})

    # --- CSV ---------------------------------------------------------------------

    def import_csv(self, data):
        uid = self._uid(None)
        if uid is None or self.viewing is not None:
            return
        name = self.rep["sheets"][uid]["name"]
        if not self._writable(uid):
            self._alert("droit_insuffisant", name)
            return
        rows, bad = parse_csv(data.decode("utf-8-sig"))
        if bad is not None:
            self._alert("csv_invalide", name, None, bad)
            return
        prims = []
        for r, fields in enumerate(rows, start=1):
            for c, val in enumerate(fields, start=1):
                cell = None
                if val != "":
                    cell = {"text": val, "tz": self.tz, "literal": val.startswith("=")}
                prims.append(self._setp(uid, key_of(c, r), cell))
        if not prims:
            return
        act = self._do(prims, "user", vuid=uid)
        if act is not None:
            self._record(act)

    def export_csv(self):
        uid = self._uid(None)
        if uid is None:
            return b""
        cells = self._cells(uid)
        calc = self._calc()
        rows_map = {}
        for key in cells:
            c, r = split_key(key)
            rows_map.setdefault(r, {})[c] = key
        if not rows_map:
            return b""
        maxc = max(c for r in rows_map.values() for c in r)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in sorted(rows_map):
            line = []
            for c in range(1, maxc + 1):
                key = rows_map[r].get(c)
                line.append("" if key is None else export_text(calc.top(uid, key), self.tz))
            w.writerow(line)
        return buf.getvalue().encode("utf-8")

    # --- annulation / rétablissement ------------------------------------------------

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if not self.undo_stack or self.viewing is not None:
            return
        a = self.undo_stack.pop()
        if self._pending(a["op"]):
            self._cancel(a["op"])
            self.redo_stack.append({"fwd": a["fwd"], "op": None})
            return
        if any(p["t"] != "sheet_add" and not self._writable(p["uid"]) for p in a["inv"]):
            return
        act = self._do(a["inv"], "undo")
        if act is not None:
            self.redo_stack.append({"fwd": a["fwd"], "op": None})

    def redo(self):
        if not self.redo_stack or self.viewing is not None:
            return
        r = self.redo_stack.pop()
        if any(p["t"] != "sheet_add" and not self._writable(p["uid"]) for p in r["fwd"]):
            return
        act = self._do(r["fwd"], "redo", vuid=r["fwd"][0].get("uid") if r["fwd"][0]["t"] == "set" else None)
        if act is not None:
            self.undo_stack.append(act)

    # --- conflits ----------------------------------------------------------------

    def conflict(self, ref, sheet=None):
        uid = self._uid(sheet)
        if uid is None:
            return None
        return self.rep["conflicts"].get((uid, ref.upper()))

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        uid = self._uid(sheet)
        key = ref.upper()
        if uid is None or self.viewing is not None:
            return
        cf = self.rep["conflicts"].get((uid, key))
        if cf is None:
            return
        if not self._writable(uid):
            self._alert("droit_insuffisant", self.rep["sheets"][uid]["name"], key)
            return
        cur = self.rep["sheets"][uid]["cells"].get(key)
        new = dict(cf.cell) if use_discarded else cur
        act = self._do([self._setp(uid, key, new, t="resolve")], "user",
                       vuid=uid if use_discarded else None)
        if act is not None:
            self._record(act)

    # --- présence ---------------------------------------------------------------

    def select(self, ref, sheet=None):
        uid = self._uid(sheet)
        if uid is None or not self.net.is_online(self.name):
            return
        self.net.send(self.name, SERVER, {"type": "select", "sheet": self.rep["sheets"][uid]["name"],
                                          "key": ref.upper()})

    def presence(self):
        if not self.net.is_online(self.name):
            return {}
        return {k: v for k, v in self.presence_map.items() if k != self.name}

    def connection_status(self):
        return "en ligne" if self.net.is_online(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.store["outbox"])

    def alerts(self):
        return list(self._alerts)

    # --- versions ----------------------------------------------------------------

    def history(self, sheet=None):
        vs = self._snap()["versions"]
        if sheet is not None:
            uid = self._uid(sheet)
            vs = [v for v in vs if v["uid"] == uid]
        vs = sorted(vs, key=lambda v: (v["instant"], v["id"]), reverse=True)
        return [Version(v, self.tz) for v in vs]

    def _version(self, vid):
        return next((v for v in self._snap()["versions"] if v["id"] == vid), None)

    def open_version(self, vid):
        v = self._version(vid)
        if v is not None:
            self.viewing = v

    def close_version(self):
        self.viewing = None

    def restore_version(self, vid):
        v = self._version(vid)
        if v is None or self.viewing is not None:
            return
        uid = v["uid"]
        if not self._writable(uid):
            return
        cur = self.rep["sheets"][uid]
        prims = []
        if cur["name"] != v["name"]:
            prims.append({"t": "sheet_ren", "uid": uid, "name": v["name"], "sheet_name": cur["name"]})
        prims.append({"t": "sheet_cells", "uid": uid, "cells": dict(v["cells"]), "sheet_name": v["name"]})
        act = self._do(prims, "user", kind="restauration", vuid=uid)
        if act is not None:
            self._record(act)

    # --- cycle de vie -------------------------------------------------------------

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz, store=self.store)
