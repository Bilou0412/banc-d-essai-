"""Classeur collaboratif hors ligne — couche code.

Noyau : temps simulé, réseau simulé en mémoire, analyseur d'expressions,
évaluateur qui suit le graphe des dépendances (détection de cycle sur le graphe).
Serveur et clients sont dans les parties suivantes du module.
"""
import csv
import io
import re
import sys
import uuid
from collections import deque
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.setrecursionlimit(100000)

UTC = timezone.utc
WRITE = "écriture"
READ = "lecture"
FMT = "%Y-%m-%d %H:%M"


# ---------------------------------------------------------------- temps

class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


# ---------------------------------------------------------------- objets exposés

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line

    def __repr__(self):
        return f"Alert({self.kind!r}, sheet={self.sheet!r}, cell={self.cell!r}, line={self.line!r})"


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    """Entrée de l'historique côté serveur (immuable par convention)."""

    def __init__(self, id, sid, name, author, ts, kind, cells):
        self.id = id
        self.sid = sid
        self.name = name
        self.author = author
        self.ts = ts
        self.kind = kind
        self.cells = cells


class HistEntry:
    def __init__(self, id, author, timestamp, kind):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


class Err:
    def __init__(self, code):
        self.code = code


# ---------------------------------------------------------------- réseau simulé

class Network:
    def __init__(self):
        self.queue = deque()
        self.endpoints = {}
        self.down = set()
        self.storage = {}  # stockage local de l'appareil, par personne

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def _deliver(self, item):
        src, dst, msg = item
        if src in self.down or dst in self.down:
            return
        self.endpoints[dst].receive(msg, src)

    def deliver_all(self):
        while self.queue:
            self._deliver(self.queue.popleft())

    def deliver_from(self, name):
        mine = [it for it in self.queue if it[0] == name]
        self.queue = deque(it for it in self.queue if it[0] != name)
        for it in mine:
            self._deliver(it)

    def disconnect(self, name):
        self.down.add(name)
        srv = self.endpoints.get("server")
        if srv is not None and name != "server":
            srv.client_down(name)

    def reconnect(self, name):
        self.down.discard(name)
        ep = self.endpoints.get(name)
        if ep is not None:
            ep.on_reconnect()

    def is_down(self, name):
        return name in self.down


# ---------------------------------------------------------------- adresses

def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_addr(addr):
    m = re.fullmatch(r"([A-Z]+)(\d+)", addr)
    return col_index(m.group(1)), int(m.group(2))


def split_ref(text):
    """'Feuille2!A1' -> ('Feuille2', 'A1') ; 'A1' -> (None, 'A1')."""
    if "!" in text:
        sheet, addr = text.rsplit("!", 1)
        return sheet, addr
    return None, text


# ---------------------------------------------------------------- analyseur

class SyntaxErr(Exception):
    pass


TOKEN = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<func>[A-Z]+)\("
    r"|(?P<ref>(?:[^\W\d]\w*!)?[A-Z]{1,3}\d+)"
    r"|(?P<op>[-+*/():,])"
)


def tokenize(text):
    toks = []
    pos = 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        m = TOKEN.match(text, pos)
        if not m:
            raise SyntaxErr()
        pos = m.end()
        if m.group("num") is not None:
            toks.append(("num", m.group("num")))
        elif m.group("func") is not None:
            toks.append(("func", m.group("func")))
        elif m.group("ref") is not None:
            toks.append(("ref", m.group("ref")))
        else:
            toks.append(("op", m.group("op")))
    return toks


class Parser:
    """Descente récursive : + et - (gauche), * et / (gauche), unaire -, appels."""

    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect_op(self, s):
        if self.take() != ("op", s):
            raise SyntaxErr()

    def parse(self):
        e = self.expr()
        if self.i != len(self.t):
            raise SyntaxErr()
        return e

    def expr(self):
        left = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            left = ("bin", op, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            left = ("bin", op, left, self.unary())
        return left

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        k, v = self.take()
        if k == "num":
            return ("num", float(v) if "." in v else int(v))
        if k == "ref":
            if self.peek() == ("op", ":"):
                self.take()
                k2, v2 = self.take()
                if k2 != "ref":
                    raise SyntaxErr()
                return ("range", v, v2)
            return ("ref", v)
        if k == "func":
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            if v == "SOMME" and args:
                return ("call", "SOMME", args)
            if v == "MAINTENANT" and not args:
                return ("now",)
            raise SyntaxErr()
        if (k, v) == ("op", "("):
            e = self.expr()
            self.expect_op(")")
            return e
        raise SyntaxErr()


def parse_formula(content):
    return Parser(tokenize(content)).parse()


# ---------------------------------------------------------------- valeurs typées

INT_RE = re.compile(r"-?\d+")
FLOAT_RE = re.compile(r"-?\d+\.\d+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DT_CANON_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")
NAIVE_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")
OFFSET_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})")


def normalize(text, tz):
    """Saisie telle que tapée -> contenu canonique (date-heure ancrée dans le fuseau)."""
    if OFFSET_DT_RE.fullmatch(text):
        return datetime.fromisoformat(text.replace(" ", "T")).isoformat(timespec="seconds")
    if NAIVE_DT_RE.fullmatch(text):
        d = datetime.fromisoformat(text.replace(" ", "T")).replace(tzinfo=ZoneInfo(tz))
        return d.isoformat(timespec="seconds")
    return text


def typed(content):
    if DATE_RE.fullmatch(content):
        return date.fromisoformat(content)
    if DT_CANON_RE.fullmatch(content):
        return datetime.fromisoformat(content)
    if INT_RE.fullmatch(content):
        return int(content)
    if FLOAT_RE.fullmatch(content):
        return float(content)
    return content


# ---------------------------------------------------------------- évaluation

class Ctx:
    def __init__(self, st, clock):
        self.st = st
        self.clock = clock
        self.memo = {}


def sheet_id(st, name):
    if name is None:
        return None
    for sid in st["order"]:
        if st["sheets"][sid]["name"] == name:
            return sid
    return None


def cell_value(ctx, sid, addr, stack):
    key = (sid, addr)
    if key in ctx.memo:
        return ctx.memo[key]
    if key in stack:
        return Err("#CIRC!")
    cell = ctx.st["sheets"][sid]["cells"].get(addr)
    if cell is None:
        return None
    content, literal = cell
    if literal:
        return content
    if content.startswith("="):
        stack.add(key)
        try:
            try:
                ast = parse_formula(content[1:])
            except SyntaxErr:
                v = Err("#SYNTAXE!")
            else:
                v = ev(ctx, ast, sid, stack)
        finally:
            stack.discard(key)
        ctx.memo[key] = v
        return v
    return typed(content)


def ref_target(ctx, text, sid):
    sheet, addr = split_ref(text)
    tsid = sid if sheet is None else sheet_id(ctx.st, sheet)
    return tsid, addr


def num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        return Err("#TYPE!")
    if isinstance(v, (int, float)):
        return v
    return Err("#TYPE!")


def binop(op, l, r):
    if op == "-" and isinstance(l, datetime) and isinstance(r, datetime):
        return (l.astimezone(UTC) - r.astimezone(UTC)).total_seconds() / 86400
    if op == "-" and isinstance(l, date) and isinstance(r, date) and not isinstance(l, datetime):
        return (l - r).days
    a = num(l)
    b = num(r)
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        return Err("#DIV/0!")
    return a / b


def ev(ctx, node, sid, stack):
    t = node[0]
    if t == "num":
        return node[1]
    if t == "now":
        return ctx.clock.now()
    if t == "ref":
        tsid, addr = ref_target(ctx, node[1], sid)
        if tsid is None:
            return Err("#REF!")
        v = cell_value(ctx, tsid, addr, stack)
        return 0 if v is None else v
    if t == "range":
        tsid, a = ref_target(ctx, node[1], sid)
        if tsid is None:
            return Err("#REF!")
        _, b = split_ref(node[2])
        c1, r1 = split_addr(a)
        c2, r2 = split_addr(b)
        out = []
        for c in range(min(c1, c2), max(c1, c2) + 1):
            for r in range(min(r1, r2), max(r1, r2) + 1):
                v = cell_value(ctx, tsid, f"{col_letters(c)}{r}", stack)
                if isinstance(v, Err):
                    return v
                out.append(v)
        return out
    if t == "neg":
        v = ev(ctx, node[1], sid, stack)
        if isinstance(v, Err):
            return v
        n = num(v)
        return n if isinstance(n, Err) else -n
    if t == "bin":
        l = ev(ctx, node[2], sid, stack)
        if isinstance(l, Err):
            return l
        r = ev(ctx, node[3], sid, stack)
        if isinstance(r, Err):
            return r
        return binop(node[1], l, r)
    if t == "call":
        total = 0
        for arg in node[2]:
            v = ev(ctx, arg, sid, stack)
            if isinstance(v, Err):
                return v
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        total += x
            else:
                n = num(v)
                if isinstance(n, Err):
                    return n
                total += n
        return total
    raise ValueError(t)


def display(v, tz):
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(tz)).strftime(FMT)
    if isinstance(v, date):
        return v.isoformat()
    return v


def export_text(v, tz):
    if v is None:
        return ""
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


# ---------------------------------------------------------------- CSV

def parse_csv(text):
    """Analyse CSV (guillemets doublés, sauts de ligne dans un champ, CRLF).

    Rend (enregistrements, None) ou (None, ligne) si un guillemet n'est jamais fermé.
    """
    records = []
    rec = []
    field = []
    i = 0
    n = len(text)
    line = 1
    rec_line = 1
    inq = False
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
        if ch == '"' and not field:
            inq = True
            i += 1
            continue
        if ch == ",":
            rec.append("".join(field))
            field = []
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            rec.append("".join(field))
            records.append(rec)
            rec = []
            field = []
            line += 1
            rec_line = line
            i += 1
            continue
        field.append(ch)
        i += 1
    if inq:
        return None, rec_line
    if rec or field:
        rec.append("".join(field))
        records.append(rec)
    return records, None


# ---------------------------------------------------------------- état du classeur

def empty_state(owner):
    return {
        "sheets": {}, "order": [], "rights": {}, "owner": owner,
        "conflicts": {}, "seq": {}, "writer": {}, "presence": {}, "versions": [],
    }


def copy_state(st):
    return {
        "sheets": {k: {"name": v["name"], "cells": dict(v["cells"])} for k, v in st["sheets"].items()},
        "order": list(st["order"]),
        "rights": dict(st["rights"]),
        "owner": st["owner"],
        "conflicts": dict(st["conflicts"]),
        "seq": dict(st["seq"]),
        "writer": dict(st["writer"]),
        "presence": dict(st["presence"]),
        "versions": list(st["versions"]),
    }


def level_of(st, person, sid):
    if person is not None and person == st["owner"]:
        return WRITE
    return st["rights"].get((sid, person))


def name_taken(st, name, except_sid=None):
    return any(
        sh["name"].casefold() == name.casefold() and sid != except_sid
        for sid, sh in st["sheets"].items()
    )


def rename_sheet_state(st, sid, new):
    old = st["sheets"][sid]["name"]
    st["sheets"][sid]["name"] = new
    pat = re.compile(r"(?<!\w)" + re.escape(old) + "!")
    for sh in st["sheets"].values():
        for addr, (content, literal) in list(sh["cells"].items()):
            if not literal and content.startswith("="):
                nc = pat.sub(new + "!", content)
                if nc != content:
                    sh["cells"][addr] = (nc, literal)


def apply_plain(st, op):
    """Application sans contrôle : sert au serveur (après contrôles) et à la vue optimiste."""
    t = op["type"]
    sid = op.get("sid")
    if t == "set":
        sh = st["sheets"].get(sid)
        if sh is None:
            return
        if op["content"] is None:
            sh["cells"].pop(op["ref"], None)
        else:
            sh["cells"][op["ref"]] = (op["content"], op["literal"])
    elif t == "add":
        st["sheets"][sid] = {"name": op["name"], "cells": dict(op.get("cells") or {})}
        if sid not in st["order"]:
            st["order"].append(sid)
        st["rights"].update(op.get("rights") or {})
        if op["author"] != st["owner"]:
            st["rights"][(sid, op["author"])] = WRITE
    elif t == "delete":
        if sid in st["sheets"]:
            del st["sheets"][sid]
            st["order"].remove(sid)
            for k in [k for k in st["rights"] if k[0] == sid]:
                del st["rights"][k]
    elif t == "rename":
        if sid in st["sheets"]:
            rename_sheet_state(st, sid, op["new"])
    elif t == "restore":
        sh = st["sheets"].get(sid)
        if sh is None:
            return
        if op["name"] != sh["name"]:
            rename_sheet_state(st, sid, op["name"])
        sh["cells"] = dict(op["cells"])


# ---------------------------------------------------------------- serveur

class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.st = empty_state(owner)
        self.seqno = 0
        self.processed = set()
        self.clients = set()
        net.endpoints["server"] = self
        sid = uuid.uuid4().hex
        self.st["sheets"][sid] = {"name": "Feuille1", "cells": {}}
        self.st["order"].append(sid)

    def receive(self, msg, src):
        if msg[0] == "hello":
            self.clients.add(src)
            self.net.send("server", src, ("state", copy_state(self.st), [], []))
        elif msg[0] == "op":
            self._process(msg[1], src)

    def client_down(self, name):
        if self.st["presence"].pop(name, None) is not None:
            self._broadcast(None, None, [])

    def _process(self, op, src):
        self.clients.add(src)
        if op["id"] in self.processed:
            self.net.send("server", src, ("state", copy_state(self.st), [op["id"]], []))
            return
        self.processed.add(op["id"])
        alerts = self._apply(op, src)
        self._broadcast(src, op["id"], alerts)

    def _broadcast(self, origin, op_id, alerts):
        snap = copy_state(self.st)
        for c in sorted(self.clients):
            if c == origin:
                self.net.send("server", c, ("state", snap, [op_id], alerts))
            else:
                self.net.send("server", c, ("state", snap, [], []))

    def _version(self, sid, author, ts, kind, n):
        sh = self.st["sheets"][sid]
        self.st["versions"].append(
            Version(n, sid, sh["name"], author, ts, kind, dict(sh["cells"])))

    def _apply(self, op, author):
        st = self.st
        t = op["type"]
        sid = op.get("sid")
        self.seqno += 1
        n = self.seqno
        if t == "select":
            if sid in st["sheets"]:
                st["presence"][author] = (sid, op["ref"])
            return []
        if t == "right":
            if author != st["owner"] or sid not in st["sheets"]:
                return []
            if op["level"] is None:
                st["rights"].pop((sid, op["person"]), None)
            else:
                st["rights"][(sid, op["person"])] = op["level"]
            return []
        if t == "add":
            if sid in st["sheets"] or name_taken(st, op["name"]):
                return [Alert("nom_existant", sheet=op["name"])]
            apply_plain(st, op)
            return []
        if sid not in st["sheets"]:
            if t == "delete":
                return []
            return [Alert("feuille_supprimee", sheet=op.get("sheet") or op.get("old"))]
        name = st["sheets"][sid]["name"]
        if t == "delete":
            if level_of(st, author, sid) != WRITE or len(st["order"]) <= 1:
                return []
            apply_plain(st, op)
            return []
        if level_of(st, author, sid) != WRITE:
            if t == "set":
                return [Alert("modification_rejetee", sheet=name, cell=op["ref"])]
            if t == "resolve":
                return []
            return [Alert("droit_insuffisant", sheet=name)]
        if t == "rename":
            if name_taken(st, op["new"], except_sid=sid):
                return [Alert("nom_existant", sheet=op["new"])]
            apply_plain(st, op)
            return []
        if t == "restore":
            if op["name"] != name and name_taken(st, op["name"], except_sid=sid):
                return [Alert("nom_existant", sheet=op["name"])]
            sh = st["sheets"][sid]
            old = dict(sh["cells"])
            apply_plain(st, op)
            for ref in set(old) | set(op["cells"]):
                if old.get(ref) != op["cells"].get(ref):
                    key = (sid, ref)
                    st["seq"][key] = n
                    st["writer"][key] = author
                    st["conflicts"].pop(key, None)
            self._version(sid, author, op["ts"], "restauration", n)
            return []
        if t == "resolve":
            key = (sid, op["ref"])
            cf = st["conflicts"].get(key)
            if cf is None:
                return []
            if op["use"]:
                apply_plain(st, {"type": "set", "sid": sid, "ref": op["ref"],
                                 "content": cf.discarded, "literal": False})
                st["seq"][key] = n
                st["writer"][key] = author
                self._version(sid, author, op["ts"], "modification", n)
            st["conflicts"].pop(key, None)
            return []
        if t == "set":
            key = (sid, op["ref"])
            sh = st["sheets"][sid]
            cur = sh["cells"].get(op["ref"])
            cur_c = cur[0] if cur else None
            last = st["writer"].get(key)
            concurrent = (st["seq"].get(key, 0) > op["base"]
                          and last is not None and last != author)
            if concurrent and cur_c != op["content"]:
                st["conflicts"][key] = Conflict(op["content"], author)
                st["seq"][key] = n
                return []
            apply_plain(st, op)
            st["seq"][key] = n
            st["writer"][key] = author
            st["conflicts"].pop(key, None)
            self._version(sid, author, op["ts"], "modification", n)
            return []
        return []


# ---------------------------------------------------------------- client

class Client:
    def __init__(self, net, clock, name, tz="UTC"):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.store = net.storage.setdefault(name, {"pending": [], "srv": None})
        self.pending = self.store["pending"]
        self.srv = self.store["srv"] or empty_state(None)
        self._alerts = []
        self.undo_stack = []
        self.redo_stack = []
        self.active = None
        self.viewing = None
        net.endpoints[name] = self
        if not net.is_down(name):
            self._resync()

    # -- réseau

    def _resync(self):
        for op in self.pending:
            op["sent"] = True
            self.net.send(self.name, "server", ("op", op))
        self.net.send(self.name, "server", ("hello",))

    def on_reconnect(self):
        self._resync()

    def receive(self, msg, src):
        if msg[0] != "state":
            return
        _, snap, done, alerts = msg
        self.srv = snap
        self.store["srv"] = snap
        self.pending[:] = [p for p in self.pending if p["id"] not in done]
        self._alerts.extend(alerts)

    def _new_op(self, **kw):
        op = dict(kw)
        op["id"] = uuid.uuid4().hex
        op["author"] = self.name
        op["ts"] = self.clock.now()
        op["sent"] = False
        return op

    def _transmit(self, op):
        if not self.net.is_down(self.name):
            op["sent"] = True
            self.net.send(self.name, "server", ("op", op))

    def _submit(self, op):
        """Opération en attente : vue optimiste jusqu'à l'accusé du serveur."""
        self.pending.append(op)
        self._transmit(op)
        return op["id"]

    def _send_now(self, op):
        """Opération hors attente (droits, présence) : seulement si en ligne."""
        if not self.net.is_down(self.name):
            self.net.send(self.name, "server", ("op", op))

    # -- vue

    def _view(self):
        st = copy_state(self.srv)
        for op in self.pending:
            apply_plain(st, op)
        if self.viewing is not None:
            v = self.viewing
            if v.sid in st["sheets"]:
                st["sheets"][v.sid] = {"name": v.name, "cells": dict(v.cells)}
        return st

    def _active_name(self, st):
        if self.active is not None and sheet_id(st, self.active) is not None:
            return self.active
        if st["order"]:
            return st["sheets"][st["order"][0]]["name"]
        return None

    def _sheet(self, sheet=None):
        st = self._view()
        name = sheet if sheet is not None else self._active_name(st)
        return st, sheet_id(st, name), name

    def _write(self, st, sid, ref=None, name=None):
        if sid is not None and level_of(st, self.name, sid) == WRITE:
            return True
        self._alerts.append(Alert("droit_insuffisant", sheet=name, cell=ref))
        return False

    # -- cellules

    def _cell_op(self, sid, name, ref, new):
        base = self.srv["seq"].get((sid, ref), 0)
        op = self._new_op(type="set", sid=sid, sheet=name, ref=ref,
                          content=new[0] if new else None,
                          literal=new[1] if new else False, base=base)
        return self._submit(op)

    def _record(self, items):
        self.undo_stack.append(items)
        self.redo_stack.clear()

    def _edit(self, sid, name, changes):
        items = []
        for ref, old, new in changes:
            op_id = self._cell_op(sid, name, ref, new)
            items.append({"kind": "cell", "sid": sid, "name": name, "ref": ref,
                          "old": old, "new": new, "op": op_id})
        if items:
            self._record(items)

    def _set_value(self, ref, text, sheet):
        if self.viewing is not None:
            return
        st, sid, name = self._sheet(sheet)
        if sid is None or not self._write(st, sid, ref, name):
            return
        new = None if text is None else (normalize(text, self.tz), False)
        old = st["sheets"][sid]["cells"].get(ref)
        self._edit(sid, name, [(ref, old, new)])

    def set_cell(self, ref, text, sheet=None):
        self._set_value(ref, text, sheet)

    def clear(self, ref, sheet=None):
        self._set_value(ref, None, sheet)

    def content(self, ref, sheet=None):
        st, sid, _ = self._sheet(sheet)
        if sid is None:
            return None
        cell = st["sheets"][sid]["cells"].get(ref)
        return cell[0] if cell else None

    def value(self, ref, sheet=None):
        st, sid, _ = self._sheet(sheet)
        if sid is None:
            return None
        return display(cell_value(Ctx(st, self.clock), sid, ref, set()), self.tz)

    def error(self, ref, sheet=None):
        st, sid, _ = self._sheet(sheet)
        if sid is None:
            return None
        v = cell_value(Ctx(st, self.clock), sid, ref, set())
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        self.tz = tz

    # -- feuilles

    def sheets(self):
        st = self._view()
        return [st["sheets"][s]["name"] for s in st["order"]]

    def activate(self, name):
        self.active = name

    def add_sheet(self, name):
        st = self._view()
        if name_taken(st, name):
            self._alerts.append(Alert("nom_existant", sheet=name))
            return
        sid = uuid.uuid4().hex
        self._submit(self._new_op(type="add", sid=sid, name=name))
        self._record([{"kind": "add", "sid": sid, "name": name}])

    def delete_sheet(self, name):
        st, sid, _ = self._sheet(name)
        if sid is None or not self._write(st, sid, None, name):
            return
        if len(st["order"]) <= 1:
            return
        cells = dict(st["sheets"][sid]["cells"])
        rights = {k: v for k, v in st["rights"].items() if k[0] == sid}
        self._submit(self._new_op(type="delete", sid=sid, sheet=name))
        self._record([{"kind": "delete", "sid": sid, "name": name,
                       "cells": cells, "rights": rights}])

    def rename_sheet(self, old, new):
        st, sid, _ = self._sheet(old)
        if sid is None or not self._write(st, sid, None, old):
            return
        if name_taken(st, new, except_sid=sid):
            self._alerts.append(Alert("nom_existant", sheet=new))
            return
        self._submit(self._new_op(type="rename", sid=sid, sheet=old, old=old, new=new))
        self._record([{"kind": "rename", "sid": sid, "old": old, "new": new}])

    # -- droits et présence

    def set_right(self, person, sheet, level):
        if self.name != self.srv["owner"]:
            return
        st = self._view()
        sid = sheet_id(st, sheet)
        if sid is None:
            return
        self._send_now(self._new_op(type="right", sid=sid, person=person, level=level))

    def right(self, person, sheet):
        st, sid, _ = self._sheet(sheet)
        if sid is None:
            return None
        return level_of(st, person, sid)

    def select(self, ref, sheet=None):
        st, sid, _ = self._sheet(sheet)
        if sid is None:
            return
        self._send_now(self._new_op(type="select", sid=sid, ref=ref))

    def presence(self):
        if self.net.is_down(self.name):
            return {}
        out = {}
        for person, (sid, ref) in self.srv["presence"].items():
            if person == self.name:
                continue
            sh = self.srv["sheets"].get(sid)
            if sh is not None:
                out[person] = (sh["name"], ref)
        return out

    def connection_status(self):
        return "hors ligne" if self.net.is_down(self.name) else "en ligne"

    def pending_count(self):
        return len(self.pending)

    def alerts(self):
        return list(self._alerts)

    def conflict(self, ref, sheet=None):
        st, sid, _ = self._sheet(sheet)
        if sid is None:
            return None
        return self.srv["conflicts"].get((sid, ref))

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        st, sid, name = self._sheet(sheet)
        if sid is None or not self._write(st, sid, ref, name):
            return
        if (sid, ref) not in self.srv["conflicts"]:
            return
        self._submit(self._new_op(type="resolve", sid=sid, sheet=name, ref=ref,
                                  use=use_discarded))

    # -- annulation / rétablissement

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _rights_ok(self, st, items):
        for it in items:
            sid = it.get("sid")
            if it["kind"] in ("cell", "rename") and sid in st["sheets"]:
                if level_of(st, self.name, sid) != WRITE:
                    self._alerts.append(Alert("droit_insuffisant",
                                              sheet=st["sheets"][sid]["name"]))
                    return False
        return True

    def _blocked(self, st, items):
        for it in items:
            sid = it.get("sid")
            if it["kind"] == "cell":
                if sid not in st["sheets"]:
                    return True
                if st["sheets"][sid]["cells"].get(it["ref"]) != it["new"]:
                    return True
            elif it["kind"] == "rename":
                if sid not in st["sheets"] or st["sheets"][sid]["name"] != it["new"]:
                    return True
        return False

    def undo(self):
        if not self.undo_stack:
            return
        items = self.undo_stack.pop()
        st = self._view()
        if not self._rights_ok(st, items):
            return
        if self._blocked(st, items):
            self._alerts.append(Alert("annulation_impossible"))
            return
        self.redo_stack.append(self._replay(items, undo=True))

    def redo(self):
        if not self.redo_stack:
            return
        items = self.redo_stack.pop()
        st = self._view()
        if not self._rights_ok(st, items):
            return
        self.undo_stack.append(self._replay(items, undo=False))

    def _replay(self, items, undo):
        order = list(reversed(items)) if undo else list(items)
        out = [self._apply_item(it, undo) for it in order]
        return list(reversed(out)) if undo else out

    def _apply_item(self, it, undo):
        k = it["kind"]
        if k == "cell":
            target = it["old"] if undo else it["new"]
            pend = [p for p in self.pending if p["id"] == it["op"]] if it["op"] else []
            if undo and pend and not pend[0]["sent"]:
                # modification encore jamais émise : on la retire de la file
                self.pending.remove(pend[0])
                new_op = None
            else:
                new_op = self._cell_op(it["sid"], it["name"], it["ref"], target)
            return dict(it, op=new_op)
        if k == "rename":
            frm, to = (it["new"], it["old"]) if undo else (it["old"], it["new"])
            self._submit(self._new_op(type="rename", sid=it["sid"], sheet=frm, old=frm, new=to))
            return it
        if k == "add":
            if undo:
                self._submit(self._new_op(type="delete", sid=it["sid"], sheet=it["name"]))
            else:
                self._submit(self._new_op(type="add", sid=it["sid"], name=it["name"]))
            return it
        if k == "delete":
            if undo:
                self._submit(self._new_op(type="add", sid=it["sid"], name=it["name"],
                                          cells=it["cells"], rights=it["rights"]))
            else:
                self._submit(self._new_op(type="delete", sid=it["sid"], sheet=it["name"]))
            return it
        return it

    # -- import / export / versions

    def import_csv(self, data):
        if self.viewing is not None:
            return
        st, sid, name = self._sheet(None)
        if sid is None or not self._write(st, sid, None, name):
            return
        records, err = parse_csv(data.decode("utf-8-sig"))
        if records is None:
            self._alerts.append(Alert("csv_invalide", line=err))
            return
        cells = st["sheets"][sid]["cells"]
        changes = []
        for r, rec in enumerate(records):
            if rec == [""]:
                continue
            for c, field in enumerate(rec):
                ref = f"{col_letters(c + 1)}{r + 1}"
                if field == "":
                    new = None
                elif field.startswith("="):
                    new = (field, True)
                else:
                    new = (normalize(field, self.tz), False)
                old = cells.get(ref)
                if old != new:
                    changes.append((ref, old, new))
        if changes:
            self._edit(sid, name, changes)

    def export_csv(self):
        st, sid, _ = self._sheet(None)
        if sid is None:
            return b""
        cells = st["sheets"][sid]["cells"]
        if not cells:
            return b""
        ctx = Ctx(st, self.clock)
        maxc = 0
        rowset = set()
        for addr in cells:
            c, r = split_addr(addr)
            maxc = max(maxc, c)
            rowset.add(r)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in sorted(rowset):
            line = []
            for c in range(1, maxc + 1):
                addr = f"{col_letters(c)}{r}"
                if addr in cells:
                    line.append(export_text(cell_value(ctx, sid, addr, set()), self.tz))
                else:
                    line.append("")
            w.writerow(line)
        return buf.getvalue().encode("utf-8")

    def history(self, sheet=None):
        st, sid, _ = self._sheet(sheet)
        if sid is None:
            return []
        vs = [v for v in self.srv["versions"] if v.sid == sid]
        vs.sort(key=lambda v: (v.ts, v.id), reverse=True)
        return [HistEntry(v.id, v.author, display(v.ts, self.tz), v.kind) for v in vs]

    def _find_version(self, vid):
        for v in self.srv["versions"]:
            if v.id == vid:
                return v
        return None

    def open_version(self, vid):
        v = self._find_version(vid)
        if v is not None:
            self.viewing = v

    def close_version(self):
        self.viewing = None

    def restore_version(self, vid):
        v = self._find_version(vid)
        if v is None:
            return
        st = self._view()
        if v.sid not in st["sheets"]:
            return
        name = st["sheets"][v.sid]["name"]
        if not self._write(st, v.sid, None, name):
            return
        cur = st["sheets"][v.sid]["cells"]
        changes = []
        for ref in set(cur) | set(v.cells):
            if cur.get(ref) != v.cells.get(ref):
                changes.append({"kind": "cell", "sid": v.sid, "name": name, "ref": ref,
                                "old": cur.get(ref), "new": v.cells.get(ref), "op": None})
        items = []
        if name != v.name:
            items.append({"kind": "rename", "sid": v.sid, "old": name, "new": v.name})
        items.extend(changes)
        self._submit(self._new_op(type="restore", sid=v.sid, name=v.name, cells=dict(v.cells)))
        if items:
            self._record(items)

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz)
