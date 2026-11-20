"""Classeur collaboratif hors ligne — module unique (couche code, tour 1).

Réseau simulé en mémoire, temps simulé, fuseaux via zoneinfo. Chaque personne a sa
copie locale ; la fusion et la détection de conflit se font côté serveur, sur des copies
profondes transmises par le réseau (aucun objet partagé).
"""
import copy
import csv
import io
import re
import sys
import uuid
from collections import deque
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.setrecursionlimit(50000)

W = "écriture"
R = "lecture"
SERVER = "__serveur__"


class Err:
    def __init__(self, code):
        self.code = code

    def __eq__(self, other):
        return isinstance(other, Err) and other.code == self.code

    def __repr__(self):
        return self.code


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
        return f"Alert({self.kind!r}, {self.sheet!r}, {self.cell!r})"


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    def __init__(self, rec, tz):
        self.id = rec["id"]
        self.author = rec["author"]
        self.kind = rec["kind"]
        self.timestamp = rec["ts"].astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- valeurs littérales

DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?$")
ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_RE = re.compile(r"^-?\d+$")
FLOAT_RE = re.compile(r"^-?\d+\.\d+$")


def canon_text(text, tz):
    """Saisie date-heure -> instant avec décalage (fuseau de la personne si absent).
    Le reste est conservé tel quel ; chaîne vide -> pas de contenu."""
    if text == "":
        return None
    if not DT_RE.match(text):
        return text
    s = text.replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.isoformat()


def literal_value(content, literal):
    if literal or content is None:
        return content
    if INT_RE.match(content):
        return int(content)
    if FLOAT_RE.match(content):
        return float(content)
    try:
        if ISO_DT_RE.match(content):
            return datetime.fromisoformat(content)
        if DATE_RE.match(content):
            return date.fromisoformat(content)
    except ValueError:
        pass
    return content


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(n):
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def split_ref(ref):
    m = re.match(r"^([A-Z]+)(\d+)$", ref)
    return col_index(m.group(1)), int(m.group(2))


# ---------------------------------------------------------------- analyseur de formules

class FormulaError(Exception):
    pass


TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<ref>(?:(?P<sheet>[^\W\d]\w*)!)?(?P<col>[A-Za-z]{1,3})(?P<row>\d+)(?!\w))
  | (?P<func>[^\W\d]\w*)(?=\()
  | (?P<op>[-+*/():,])
""", re.X)


def tokenize(src):
    out, pos = [], 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if m is None:
            raise FormulaError(src[pos:])
        pos = m.end()
        if m.group("ws") is not None:
            continue
        if m.group("num") is not None:
            out.append(("num", m.group("num")))
        elif m.group("ref") is not None:
            out.append(("ref", (m.group("sheet"), m.group("col").upper(), int(m.group("row")))))
        elif m.group("func") is not None:
            out.append(("func", m.group("func").upper()))
        else:
            out.append(("op", m.group("op")))
    return out


class Parser:
    """Descente récursive : + - (gauche), * / (gauche), unaire moins, appels, plages."""

    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, text):
        if self.take() != ("op", text):
            raise FormulaError(text)

    def parse(self):
        if not self.t:
            raise FormulaError("vide")
        node = self.expr()
        if self.i != len(self.t):
            raise FormulaError("reste")
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
        return self.primary()

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", float(val) if "." in val else int(val))
        if kind == "ref":
            sheet, col, row = val
            if self.peek() == ("op", ":"):
                self.take()
                k2, v2 = self.take()
                if k2 != "ref":
                    raise FormulaError(":")
                _, col2, row2 = v2
                return ("range", sheet, col, row, col2, row2)
            return ("ref", sheet, col, row)
        if kind == "func":
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
        raise FormulaError("jeton inattendu")


# ---------------------------------------------------------------- évaluation

def is_date_only(x):
    return isinstance(x, date) and not isinstance(x, datetime)


class Evaluator:
    """Évalue les cellules en parcourant le graphe de dépendances. Une arête vers une
    cellule déjà en cours d'évaluation (pile) est une référence circulaire."""

    def __init__(self, doc, now):
        self.doc = doc
        self.now = now
        self.memo = {}
        self.stack = []

    def sheet_id(self, name):
        for sid, sh in self.doc["sheets"].items():
            if sh["name"] == name:
                return sid
        return None

    def cell(self, sheet, ref):
        sid = self.sheet_id(sheet)
        if sid is None:
            return Err("#REF!")
        key = (sid, ref)
        if key in self.memo:
            return self.memo[key]
        if key in self.stack:
            return Err("#CIRC!")
        rec = self.doc["sheets"][sid]["cells"].get(ref)
        if rec is None or rec["c"] is None:
            return None
        if rec["lit"] or not rec["c"].startswith("="):
            return literal_value(rec["c"], rec["lit"])
        self.stack.append(key)
        try:
            result = self.formula(sheet, rec["c"][1:])
        finally:
            self.stack.pop()
        self.memo[key] = result
        return result

    def formula(self, sheet, src):
        try:
            ast = Parser(tokenize(src)).parse()
        except FormulaError:
            return Err("#SYNTAXE!")
        result = self.ev(sheet, ast)
        # Une cellule vide vaut zéro dans une formule (cf. A09) : =A1 avec A1 vide donne 0.
        return 0 if result is None else result

    @staticmethod
    def num(v):
        if isinstance(v, Err):
            return v
        if v is None:
            return 0
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return Err("#TYPE!")
        return v

    def ev(self, sheet, node):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            _, sh, col, row = node
            return self.cell(sh or sheet, f"{col}{row}")
        if k == "range":
            return Err("#TYPE!")
        if k == "neg":
            n = self.num(self.ev(sheet, node[1]))
            return n if isinstance(n, Err) else -n
        if k == "bin":
            return self.binop(node[1], self.ev(sheet, node[2]), self.ev(sheet, node[3]))
        if k == "call":
            return self.call(sheet, node[1], node[2])
        return Err("#SYNTAXE!")

    def binop(self, op, a, b):
        if isinstance(a, Err):
            return a
        if isinstance(b, Err):
            return b
        if op == "-" and isinstance(a, datetime) and isinstance(b, datetime):
            return (a - b).total_seconds() / 86400
        if op == "-" and is_date_only(a) and is_date_only(b):
            return (a - b).days
        x, y = self.num(a), self.num(b)
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

    def range_values(self, sheet, node):
        _, sh, c1, r1, c2, r2 = node
        target = sh or sheet
        a, b = col_index(c1), col_index(c2)
        out = []
        for c in range(min(a, b), max(a, b) + 1):
            for r in range(min(r1, r2), max(r1, r2) + 1):
                out.append(self.cell(target, f"{col_letters(c)}{r}"))
        return out

    def call(self, sheet, name, args):
        if name == "MAINTENANT" and not args:
            return self.now()
        if name == "SOMME":
            total = 0
            for a in args:
                if a[0] == "range":
                    for v in self.range_values(sheet, a):
                        if isinstance(v, Err):
                            return v
                        if v is None:
                            continue
                        if isinstance(v, bool) or not isinstance(v, (int, float)):
                            return Err("#TYPE!")
                        total += v
                else:
                    v = self.num(self.ev(sheet, a))
                    if isinstance(v, Err):
                        return v
                    total += v
            return total
        return Err("#NOM!")


# ---------------------------------------------------------------- document

def new_doc(owner):
    return {"owner": owner, "sheets": {}, "conflicts": {}, "seq": 0}


def sid_of(doc, name):
    if doc is None:
        return None
    for sid, sh in doc["sheets"].items():
        if sh["name"] == name:
            return sid
    return None


def name_taken(doc, name, skip_sid=None):
    """Unicité des noms de feuille, sans distinction de casse (un nom ne différant que par la casse
    est déjà utilisé). La feuille `skip_sid` ne compte pas : elle peut être renommée sur place."""
    key = name.casefold()
    return any(sid != skip_sid and sh["name"].casefold() == key for sid, sh in doc["sheets"].items())


def rec_of(doc, sid, ref):
    sh = doc["sheets"].get(sid) if sid is not None else None
    return sh["cells"].get(ref) if sh is not None else None


def can_write(doc, sid, person):
    if person == doc["owner"]:
        return True
    sh = doc["sheets"].get(sid)
    return sh is not None and sh["rights"].get(person) == W


def _stamp(doc, server):
    if not server:
        return 0
    doc["seq"] += 1
    return doc["seq"]


def _write_cells(doc, sid, sh, items, author, server):
    changed = False
    for ref, content, lit, base in items:
        cur = sh["cells"].get(ref)
        if (server and base is not None and cur is not None and cur["by"] != author
                and cur["seq"] > base and cur["c"] != content):
            doc["conflicts"][(sid, ref)] = (content, author)
            continue
        sh["cells"][ref] = {"c": content, "lit": lit, "seq": _stamp(doc, server), "by": author}
        if server:
            doc["conflicts"].pop((sid, ref), None)
        changed = True
    return changed


def apply(doc, op, author, server):
    """Applique une opération. Renvoie (motif de rejet ou None, modifié ?)."""
    t = op["type"]
    if t in ("cell", "batch"):
        sid = op["sid"]
        sh = doc["sheets"].get(sid)
        if sh is None:
            return "supprimee", False
        if not can_write(doc, sid, author):
            return "droit", False
        if t == "cell":
            items = [(op["ref"], op["content"], op["literal"], op["base"])]
        else:
            items = [(r, c, lit, None) for r, c, lit in op["cells"]]
        return None, _write_cells(doc, sid, sh, items, author, server)

    if t == "add_sheet":
        sid = op["sid"]
        if sid in doc["sheets"]:
            return None, False
        if name_taken(doc, op["name"]):
            return "nom", False
        doc["sheets"][sid] = {"name": op["name"], "cells": {}, "rights": {author: W}}
        return None, True

    if t == "del_sheet":
        sid = op["sid"]
        if sid not in doc["sheets"] or len(doc["sheets"]) <= 1:
            return None, False
        if not can_write(doc, sid, author):
            return "droit", False
        del doc["sheets"][sid]
        for key in [k for k in doc["conflicts"] if k[0] == sid]:
            del doc["conflicts"][key]
        return None, True

    if t == "ren_sheet":
        sid, new = op["sid"], op["new"]
        sh = doc["sheets"].get(sid)
        if sh is None:
            return "supprimee", False
        if not can_write(doc, sid, author):
            return "droit", False
        old = sh["name"]
        if old == new:
            return None, False
        if name_taken(doc, new, sid):
            return "nom", False
        sh["name"] = new
        pat = re.compile(r"(?<!\w)" + re.escape(old) + "!")
        for other in doc["sheets"].values():
            for rec in other["cells"].values():
                if rec["c"] and not rec["lit"] and rec["c"].startswith("="):
                    rec["c"] = pat.sub(lambda m: new + "!", rec["c"])
        return None, True

    if t == "sheet_state":
        sid = op["sid"]
        sh = doc["sheets"].get(sid)
        if sh is None:
            if not op.get("create"):
                return "supprimee", False
            if name_taken(doc, op["name"]):
                return "nom", False
            sh = doc["sheets"][sid] = {"name": op["name"], "cells": {}, "rights": {}}
        else:
            if not can_write(doc, sid, author):
                return "droit", False
            if name_taken(doc, op["name"], sid):
                return "nom", False
            sh["name"] = op["name"]
        sh["cells"] = {}
        _write_cells(doc, sid, sh,
                     [(r, v["c"], v["lit"], None) for r, v in op["cells"].items()], author, server)
        if op.get("rights") is not None:
            sh["rights"] = dict(op["rights"])
        return None, True

    if t == "right":
        if author != doc["owner"]:
            return None, False
        sh = doc["sheets"].get(op["sid"])
        if sh is not None:
            if op["level"] is None:
                sh["rights"].pop(op["person"], None)
            else:
                sh["rights"][op["person"]] = op["level"]
        return None, False

    return None, False


def reject_kind(op, reason):
    if reason == "supprimee":
        return "feuille_supprimee"
    if reason == "nom":
        return "nom_existant"
    if op["type"] in ("cell", "batch"):
        return "modification_rejetee"
    return "droit_insuffisant"


# ---------------------------------------------------------------- réseau simulé

class Network:
    """File FIFO de messages (src, dst, msg). Un nœud coupé n'émet ni ne reçoit."""

    def __init__(self):
        self.nodes = {}
        self.queue = deque()
        self.down = set()
        self.watchers = []

    def register(self, name, node):
        self.nodes[name] = node

    def is_up(self, name):
        return name not in self.down

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def _dispatch(self, item):
        src, dst, msg = item
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.handle(src, msg)

    def deliver_all(self):
        while self.queue:
            self._dispatch(self.queue.popleft())

    def deliver_from(self, name):
        picked = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for m in picked:
            self._dispatch(m)

    def cancel(self, src, op_id):
        """Retire de la file l'opération encore en vol ; faux si elle a déjà été livrée."""
        for m in list(self.queue):
            if m[0] == src and m[2][0] == "op" and m[2][1]["id"] == op_id:
                self.queue.remove(m)
                return True
        return False

    def disconnect(self, name):
        self.down.add(name)
        for w in self.watchers:
            w.on_peer_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        self.nodes[name].on_up()


# ---------------------------------------------------------------- serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.doc = new_doc(owner)
        self.versions = []
        self.presence = {}
        self.processed = {}
        self.clients = set()
        self.nid = 0
        self.doc["sheets"][uuid.uuid4().hex] = {"name": "Feuille1", "cells": {}, "rights": {}}
        net.register(SERVER, self)
        net.watchers.append(self)

    def handle(self, src, msg):
        kind = msg[0]
        if kind == "hello":
            self.clients.add(src)
            self._snap_to(src)
        elif kind == "presence":
            self.presence[src] = (msg[1], msg[2])
            self._broadcast()
        elif kind == "op":
            self._on_op(src, msg[1])

    def on_peer_down(self, name):
        if self.presence.pop(name, None) is not None:
            self._broadcast()

    def _on_op(self, src, op):
        self.clients.add(src)
        done = self.processed.setdefault(src, set())
        if op["id"] in done:
            self._snap_to(src)
            return
        done.add(op["id"])
        if op["type"] == "right":
            apply(self.doc, op, src, True)
            self._broadcast()
            return
        reason, changed = apply(self.doc, op, src, True)
        if changed:
            self.nid += 1
            sid = op.get("sid")
            sh = self.doc["sheets"].get(sid)
            self.versions.append({
                "id": self.nid, "author": src, "ts": op["ts"],
                "kind": op.get("kind", "modification"), "sid": sid,
                "name": sh["name"] if sh is not None else op.get("name"),
                "doc": copy.deepcopy(self.doc),
            })
        if reason is not None:
            self.net.send(SERVER, src, ("reject", op["id"], reject_kind(op, reason),
                                        op.get("name"), op.get("ref")))
        self._broadcast()

    def _snap_to(self, name):
        self.net.send(SERVER, name, ("snap", {
            "doc": copy.deepcopy(self.doc),
            "versions": copy.deepcopy(self.versions),
            "presence": dict(self.presence),
            "acked": list(self.processed.get(name, ())),
        }))

    def _broadcast(self):
        for name in sorted(self.clients):
            if self.net.is_up(name):
                self._snap_to(name)


# ---------------------------------------------------------------- client

class Client:
    """Copie locale : `base` = dernier état confirmé par le serveur, `pending` = modifications
    non encore confirmées. La vue affichée = base + pending rejoués."""

    def __init__(self, net, clock, name, tz="UTC", _state=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        if _state is None:
            self.base = new_doc(None)
            self.versions = []
            self.pending = []
        else:
            self.base, self.versions, self.pending = _state
        self._presence = {}
        self._alerts = []
        self.undo_stack = []
        self.redo_stack = []
        self.active = "Feuille1"
        self.opened = None
        self.view = None
        net.register(name, self)
        self._rebuild()
        if net.is_up(name):
            net.send(name, SERVER, ("hello",))

    # --- réseau et état

    def handle(self, src, msg):
        if msg[0] == "snap":
            p = msg[1]
            self.base = p["doc"]
            self.versions = p["versions"]
            self._presence = p["presence"]
            acked = set(p["acked"])
            self.pending = [op for op in self.pending if op["id"] not in acked]
            self._rebuild()
        elif msg[0] == "reject":
            _, _op_id, kind, sheet, ref = msg
            self._alerts.append(Alert(kind, sheet, ref))

    def on_up(self):
        self.net.send(self.name, SERVER, ("hello",))
        for op in self.pending:
            self.net.send(self.name, SERVER, ("op", op))

    def _rebuild(self):
        view = copy.deepcopy(self.base)
        for op in self.pending:
            apply(view, op, self.name, False)
        self.view = view

    def _send_op(self, op):
        self.pending.append(op)
        if self.net.is_up(self.name):
            self.net.send(self.name, SERVER, ("op", op))
        self._rebuild()

    def _op(self, **kw):
        op = {"id": uuid.uuid4().hex, "ts": self.clock.now()}
        op.update(kw)
        return op

    def _refresh(self, op):
        if op["type"] == "cell":
            op["base"] = self._base_seq(op["sid"], op["ref"])

    def _fresh(self, op):
        new = copy.deepcopy(op)
        new["id"] = uuid.uuid4().hex
        new["ts"] = self.clock.now()
        self._refresh(new)
        return new

    def _base_seq(self, sid, ref):
        rec = rec_of(self.base, sid, ref)
        return rec["seq"] if rec is not None else 0

    def _read_doc(self):
        return self.opened["doc"] if self.opened is not None else self.view

    def _canon(self, text):
        return canon_text(text, self.tz)

    def _version(self, vid):
        for r in self.versions:
            if r["id"] == vid:
                return r
        return None

    # --- saisie

    def _edit(self, sname, changes, batch=False):
        if self.opened is not None or not changes:
            return
        sid = sid_of(self.view, sname)
        if sid is None:
            return
        if not can_write(self.view, sid, self.name):
            self._alerts.append(Alert("droit_insuffisant", sname,
                                      changes[0][0] if len(changes) == 1 else None))
            return
        before = []
        for ref, _c, _l in changes:
            rec = rec_of(self.view, sid, ref)
            before.append((ref, (rec["c"], rec["lit"]) if rec is not None else (None, False)))
        if batch:
            fwd = self._op(type="batch", sid=sid, name=sname, cells=changes)
            inv = self._op(type="batch", sid=sid, name=sname,
                           cells=[(r, c, lit) for r, (c, lit) in before])
            ref = None
        else:
            ref, content, lit = changes[0]
            pc, pl = before[0][1]
            fwd = self._op(type="cell", sid=sid, name=sname, ref=ref, content=content,
                           literal=lit, base=0)
            inv = self._op(type="cell", sid=sid, name=sname, ref=ref, content=pc,
                           literal=pl, base=0)
        self._refresh(fwd)
        self._refresh(inv)
        self._send_op(fwd)
        self.undo_stack.append({"kind": "batch" if batch else "cell", "fwd": fwd, "inv": inv,
                                "sid": sid, "name": sname, "ref": ref})
        self.redo_stack.clear()

    def set_cell(self, ref, text, sheet=None):
        self._edit(sheet or self.active, [(ref.upper(), self._canon(text), False)])

    def clear(self, ref, sheet=None):
        self._edit(sheet or self.active, [(ref.upper(), None, False)])

    def _struct(self, fwd, inv, sid=None, name=None):
        self._send_op(fwd)
        self.undo_stack.append({"kind": "struct", "fwd": fwd, "inv": inv,
                                "sid": sid, "name": name, "ref": None})
        self.redo_stack.clear()

    # --- lecture

    def content(self, ref, sheet=None):
        doc = self._read_doc()
        rec = rec_of(doc, sid_of(doc, sheet or self.active), ref.upper())
        return rec["c"] if rec is not None else None

    def _result(self, ref, sheet):
        ev = Evaluator(self._read_doc(), self.clock.now)
        return ev.cell(sheet or self.active, ref.upper())

    def _show(self, r):
        if isinstance(r, Err):
            return r.code
        if isinstance(r, datetime):
            return r.astimezone(ZoneInfo(self.tz)).strftime("%Y-%m-%d %H:%M")
        if isinstance(r, date):
            return r.isoformat()
        return r

    def value(self, ref, sheet=None):
        return self._show(self._result(ref, sheet))

    def error(self, ref, sheet=None):
        r = self._result(ref, sheet)
        return r.code if isinstance(r, Err) else None

    def set_timezone(self, tz):
        ZoneInfo(tz)
        self.tz = tz

    def sheets(self):
        return [sh["name"] for sh in self.view["sheets"].values()]

    def activate(self, name):
        self.active = name

    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self.net.is_up(self.name) else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    # --- feuilles

    def add_sheet(self, name):
        if self.opened is not None:
            return
        if name_taken(self.view, name):
            self._alerts.append(Alert("nom_existant", name))
            return
        sid = uuid.uuid4().hex
        fwd = self._op(type="add_sheet", sid=sid, name=name)
        inv = self._op(type="del_sheet", sid=sid, name=name)
        self._struct(fwd, inv, sid, name)

    def delete_sheet(self, name):
        if self.opened is not None:
            return
        sid = sid_of(self.view, name)
        if sid is None or len(self.view["sheets"]) <= 1:
            return
        if not can_write(self.view, sid, self.name):
            self._alerts.append(Alert("droit_insuffisant", name))
            return
        sh = copy.deepcopy(self.view["sheets"][sid])
        fwd = self._op(type="del_sheet", sid=sid, name=name)
        inv = self._op(type="sheet_state", sid=sid, name=name, create=True,
                       rights=dict(sh["rights"]),
                       cells={r: {"c": v["c"], "lit": v["lit"]}
                              for r, v in sh["cells"].items() if v["c"] is not None})
        self._struct(fwd, inv, sid, name)

    def rename_sheet(self, old, new):
        if self.opened is not None:
            return
        sid = sid_of(self.view, old)
        if sid is None:
            return
        if not can_write(self.view, sid, self.name):
            self._alerts.append(Alert("droit_insuffisant", old))
            return
        if name_taken(self.view, new, sid):
            self._alerts.append(Alert("nom_existant", new))
            return
        fwd = self._op(type="ren_sheet", sid=sid, name=old, new=new)
        inv = self._op(type="ren_sheet", sid=sid, name=new, new=old)
        if self.active == old:
            self.active = new
        self._struct(fwd, inv, sid, old)

    def right(self, person, sheet):
        if person == self.view["owner"]:
            return W
        sid = sid_of(self.view, sheet)
        if sid is None:
            return None
        return self.view["sheets"][sid]["rights"].get(person)

    def set_right(self, person, sheet, level):
        if self.opened is not None or not self.net.is_up(self.name):
            return
        if self.name != self.view["owner"]:
            return
        sid = sid_of(self.view, sheet)
        if sid is None:
            return
        self.net.send(self.name, SERVER,
                      ("op", self._op(type="right", sid=sid, name=sheet, person=person, level=level)))

    # --- annulation / rétablissement

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _cancel(self, fwd):
        """Retire la dernière opération encore en attente si elle n'a pas encore été livrée."""
        if not self.pending or self.pending[-1]["id"] != fwd["id"]:
            return False
        if self.net.is_up(self.name) and not self.net.cancel(self.name, fwd["id"]):
            return False
        self.pending.pop()
        self._rebuild()
        return True

    def undo(self):
        if not self.undo_stack or self.opened is not None:
            return
        e = self.undo_stack.pop()
        if e["kind"] in ("cell", "batch"):
            if not can_write(self.view, e["sid"], self.name):
                return
            if e["kind"] == "cell":
                rec = rec_of(self.base, e["sid"], e["ref"])
                if rec is not None and rec["by"] != self.name and rec["seq"] > e["fwd"]["base"]:
                    self._alerts.append(Alert("annulation_impossible", e["name"], e["ref"]))
                    return
        if not self._cancel(e["fwd"]):
            self._send_op(self._fresh(e["inv"]))
        self.redo_stack.append(e)

    def redo(self):
        if not self.redo_stack or self.opened is not None:
            return
        e = self.redo_stack.pop()
        e["fwd"] = self._fresh(e["fwd"])
        self._send_op(e["fwd"])
        self.undo_stack.append(e)

    # --- conflits

    def conflict(self, ref, sheet=None):
        sid = sid_of(self.base, sheet or self.active)
        cf = self.base["conflicts"].get((sid, ref.upper())) if sid is not None else None
        return Conflict(cf[0], cf[1]) if cf is not None else None

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.opened is not None:
            return
        sname = sheet or self.active
        ref = ref.upper()
        sid = sid_of(self.base, sname)
        cf = self.base["conflicts"].get((sid, ref)) if sid is not None else None
        if cf is None or not can_write(self.view, sid, self.name):
            return
        if use_discarded:
            content = cf[0]
        else:
            rec = rec_of(self.base, sid, ref)
            content = rec["c"] if rec is not None else None
        self._send_op(self._op(type="cell", sid=sid, name=sname, ref=ref, content=content,
                               literal=False, base=self._base_seq(sid, ref)))

    # --- présence

    def select(self, ref, sheet=None):
        if not self.net.is_up(self.name):
            return
        self.net.send(self.name, SERVER, ("presence", sheet or self.active, ref.upper()))

    def presence(self):
        if not self.net.is_up(self.name):
            return {}
        return {k: v for k, v in self._presence.items() if k != self.name}

    # --- historique

    def history(self, sheet=None):
        recs = [r for r in self.versions if sheet is None or r["name"] == sheet]
        recs.sort(key=lambda r: (r["ts"], r["id"]), reverse=True)
        return [Version(r, self.tz) for r in recs]

    def open_version(self, vid):
        rec = self._version(vid)
        if rec is not None:
            self.opened = rec

    def close_version(self):
        self.opened = None

    def restore_version(self, vid):
        if self.opened is not None:
            return
        rec = self._version(vid)
        sid = rec["sid"] if rec is not None else None
        if sid is None or sid not in self.view["sheets"]:
            return
        if not can_write(self.view, sid, self.name):
            self._alerts.append(Alert("droit_insuffisant", self.view["sheets"][sid]["name"]))
            return
        snap = rec["doc"]["sheets"].get(sid)
        if snap is None:
            return
        cur = self.view["sheets"][sid]
        fwd = self._op(type="sheet_state", sid=sid, name=snap["name"], create=False, rights=None,
                       kind="restauration",
                       cells={r: {"c": v["c"], "lit": v["lit"]}
                              for r, v in snap["cells"].items() if v["c"] is not None})
        inv = self._op(type="sheet_state", sid=sid, name=cur["name"], create=False, rights=None,
                       cells={r: {"c": v["c"], "lit": v["lit"]}
                              for r, v in cur["cells"].items() if v["c"] is not None})
        self._struct(fwd, inv, sid, cur["name"])

    # --- export / import CSV

    def _export_val(self, r):
        if r is None:
            return ""
        if isinstance(r, Err):
            return r.code
        if isinstance(r, datetime):
            return r.astimezone(ZoneInfo(self.tz)).isoformat()
        if isinstance(r, date):
            return r.isoformat()
        if isinstance(r, float) and r.is_integer():
            return str(int(r))
        return str(r)

    def export_csv(self):
        doc = self._read_doc()
        sid = sid_of(doc, self.active)
        if sid is None:
            return b""
        live = [(split_ref(r), r) for r, v in doc["sheets"][sid]["cells"].items() if v["c"] is not None]
        if not live:
            return b""
        rows_used = sorted({rc[1] for rc, _ in live})
        maxcol = max(rc[0] for rc, _ in live)
        ev = Evaluator(doc, self.clock.now)
        out = []
        for row in rows_used:
            fields = []
            for c in range(1, maxcol + 1):
                fields.append(self._export_val(ev.cell(self.active, f"{col_letters(c)}{row}")))
            out.append(fields)
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(out)
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.opened is not None:
            return
        sname = self.active
        sid = sid_of(self.view, sname)
        if sid is None:
            return
        if not can_write(self.view, sid, self.name):
            self._alerts.append(Alert("droit_insuffisant", sname))
            return
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        rows = []
        while True:
            line = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error:
                self._alerts.append(Alert("csv_invalide", sname, None, line))
                return
            rows.append(row)
        changes = []
        for r, row in enumerate(rows):
            for c, field in enumerate(row):
                ref = f"{col_letters(c + 1)}{r + 1}"
                if field == "":
                    changes.append((ref, None, False))
                elif field.startswith("="):
                    changes.append((ref, field, True))
                else:
                    changes.append((ref, self._canon(field), False))
        self._edit(sname, changes, batch=True)

    # --- cycle de vie

    def reopen(self):
        state = (copy.deepcopy(self.base), copy.deepcopy(self.versions), copy.deepcopy(self.pending))
        return Client(self.net, self.clock, self.name, self.tz, _state=state)
