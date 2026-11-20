"""Classeur collaboratif hors ligne — couche code (sonde P11).

Un seul module. Le temps est simulé (Clock), le réseau est simulé en mémoire (Network).
Chaque Client a sa propre copie ; le Server est l'autorité d'ordre (journal numéroté).
"""
import csv
import io
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

sys.setrecursionlimit(50000)

UTC = timezone.utc
W = "écriture"
R = "lecture"

CIRC = "#CIRC!"
TYPE = "#TYPE!"
DIV = "#DIV/0!"
SYNTAX = "#SYNTAXE!"
REF = "#REF!"


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


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    def __init__(self, id, author, timestamp, kind):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


# ---------------------------------------------------------------- valeurs littérales

_NUM = re.compile(r"-?\d+(?:\.\d+)?\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DT_NAIVE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}\Z")
_DT_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)\Z")


def literal(text, tz):
    """Valeur d'un contenu non formule. Une date-heure sans décalage est lue dans le fuseau `tz`."""
    if _NUM.match(text):
        return float(text) if "." in text else int(text)
    if _DATE.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return text
    if _DT_NAIVE.match(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))
        except ValueError:
            return text
    if _DT_ISO.match(text):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return d if d.tzinfo is not None else text
        except ValueError:
            return text
    return text


def col_index(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------- analyseur de formules

class FormulaSyntaxError(Exception):
    pass


_TOKEN = re.compile(r"""
  (?P<ws>\s+)
| (?P<num>\d+(?:\.\d+)?)
| (?P<ref>(?:(?P<sheet>[^\W\d]\w*)!)?\$?(?P<col>[A-Za-z]{1,3})\$?(?P<row>\d+))
| (?P<func>[^\W\d]\w*)(?=\s*\()
| (?P<op>[-+*/(),:])
""", re.VERBOSE)

FUNCS = {"SOMME", "MAINTENANT"}


def _tokenize(src):
    out = []
    pos = 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise FormulaSyntaxError(src[pos:])
        pos = m.end()
        if m.group("ws") is not None:
            continue
        if m.group("num") is not None:
            out.append(("num", m.group("num")))
        elif m.group("ref") is not None:
            out.append(("ref", m.group("sheet"), m.group("col").upper(), int(m.group("row"))))
        elif m.group("func") is not None:
            if m.group("func").upper() not in FUNCS:
                raise FormulaSyntaxError(m.group("func"))
            out.append(("func", m.group("func").upper()))
        else:
            out.append(("op", m.group("op")))
    return out


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect_op(self, v):
        if self.take() != ("op", v):
            raise FormulaSyntaxError(v)

    def parse(self):
        if not self.t:
            raise FormulaSyntaxError("vide")
        e = self.expr()
        if self.peek() is not None:
            raise FormulaSyntaxError("reste")
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
        tok = self.take()
        if tok is None:
            raise FormulaSyntaxError("fin")
        if tok[0] == "num":
            txt = tok[1]
            return ("num", float(txt) if "." in txt else int(txt))
        if tok[0] == "ref":
            _, sheet, col, row = tok
            if self.peek() == ("op", ":"):
                self.take()
                t2 = self.take()
                if t2 is None or t2[0] != "ref" or t2[1] is not None:
                    raise FormulaSyntaxError(":")
                return ("range", sheet, col, row, t2[2], t2[3])
            return ("ref", sheet, col, row)
        if tok[0] == "func":
            self.expect_op("(")
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            return ("call", tok[1], args)
        if tok == ("op", "("):
            e = self.expr()
            self.expect_op(")")
            return e
        raise FormulaSyntaxError(str(tok))


@lru_cache(maxsize=None)
def parse_formula(text):
    """`text` commence par '='. Lève FormulaSyntaxError."""
    return _Parser(_tokenize(text[1:])).parse()


# ---------------------------------------------------------------- évaluation

class Err:
    """Valeur d'erreur affichée dans une cellule."""
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return self.code


def _pick_err(errs):
    for e in errs:
        if e.code == CIRC:
            return e
    return errs[0]


def _is_dt(x):
    return isinstance(x, datetime)


def _is_date(x):
    return isinstance(x, date) and not isinstance(x, datetime)


def _to_num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        return Err(TYPE)
    if isinstance(v, (int, float)):
        return v
    return Err(TYPE)


def _binop(op, a, b):
    errs = [x for x in (a, b) if isinstance(x, Err)]
    if errs:
        return _pick_err(errs)
    if op == "-" and _is_dt(a) and _is_dt(b):
        # durée réelle : deux fuseaux ZoneInfo identiques ignoreraient le décalage à la soustraction
        return (a.astimezone(UTC) - b.astimezone(UTC)).total_seconds() / 86400
    if op == "-" and _is_date(a) and _is_date(b):
        return (a - b).days
    if _is_dt(a) or _is_dt(b) or _is_date(a) or _is_date(b):
        return Err(TYPE)
    x = _to_num(a)
    y = _to_num(b)
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
        return Err(DIV)
    return x / y


class Evaluator:
    """Calcul paresseux suivant le graphe de dépendances ; un cycle rencontré sur la pile
    de résolution donne #CIRC!. Le mémo est propre à une lecture."""

    def __init__(self, wb, now):
        self.wb = wb
        self.now = now
        self.memo = {}
        self.active = set()

    def resolve_sheet(self, sid, name):
        if name is None:
            return sid
        for s in self.wb.sheets.values():
            if s.name == name:
                return s.id
        return None

    def cell_value(self, sid, ref):
        key = (sid, ref)
        if key in self.active:
            return Err(CIRC)
        if key in self.memo:
            return self.memo[key]
        sh = self.wb.sheets.get(sid)
        if sh is None:
            return Err(REF)
        cell = sh.cells.get(ref)            # (contenu, fuseau, littéral ?, révision, auteur)
        content = None if cell is None else cell[0]
        if content is None:
            res = None
        elif cell[2]:
            res = content
        elif content.startswith("="):
            self.active.add(key)
            try:
                try:
                    ast = parse_formula(content)
                except FormulaSyntaxError:
                    res = Err(SYNTAX)
                else:
                    res = self.ev(ast, sid)
            finally:
                self.active.discard(key)
        else:
            res = literal(content, cell[1])
        self.memo[key] = res
        return res

    def ev(self, node, sid):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            target = self.resolve_sheet(sid, node[1])
            if target is None:
                return Err(REF)
            v = self.cell_value(target, f"{node[2]}{node[3]}")
            return 0 if v is None else v        # une cellule vide vaut zéro (cf. A09)
        if k == "range":
            return Err(TYPE)
        if k == "neg":
            v = self.ev(node[1], sid)
            if isinstance(v, Err):
                return v
            x = _to_num(v)
            return x if isinstance(x, Err) else -x
        if k == "bin":
            return _binop(node[1], self.ev(node[2], sid), self.ev(node[3], sid))
        if k == "call":
            name, args = node[1], node[2]
            if name == "MAINTENANT":
                return self.now
            return self.somme(args, sid)
        return Err(SYNTAX)

    def somme(self, args, sid):
        total = 0
        errs = []
        for arg in args:
            if arg[0] == "range":
                _, sheet, c1, r1, c2, r2 = arg
                target = self.resolve_sheet(sid, sheet)
                if target is None:
                    errs.append(Err(REF))
                    continue
                for c in range(col_index(c1), col_index(c2) + 1):
                    for r in range(min(r1, r2), max(r1, r2) + 1):
                        v = self.cell_value(target, f"{col_name(c)}{r}")
                        if isinstance(v, Err):
                            errs.append(v)
                        elif isinstance(v, (int, float)) and not isinstance(v, bool):
                            total += v
            else:
                v = self.ev(arg, sid)
                if isinstance(v, Err):
                    errs.append(v)
                elif v is None:
                    pass
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    total += v
                else:
                    errs.append(Err(TYPE))
        if errs:
            return _pick_err(errs)
        return total


def show(v, tz):
    """Valeur telle qu'affichée (date-heure dans le fuseau `tz`)."""
    if v is None:
        return None
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return v


def export_text(v, tz):
    if v is None:
        return ""
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(tz)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)

# ---------------------------------------------------------------- état du classeur

EMPTY = (None, None, False, 0, None)   # (contenu, fuseau, littéral ?, révision, auteur)


class Sheet:
    def __init__(self, sid, name, rights=None):
        self.id = sid
        self.name = name
        self.cells = {}
        self.rights = dict(rights or {})


class Workbook:
    def __init__(self):
        self.sheets = {}
        self.order = []
        self.conflicts = {}

    def copy(self):
        wb = Workbook()
        for sid, sh in self.sheets.items():
            n = Sheet(sid, sh.name, sh.rights)
            n.cells = dict(sh.cells)
            wb.sheets[sid] = n
        wb.order = list(self.order)
        wb.conflicts = dict(self.conflicts)
        return wb

    def names(self):
        return [self.sheets[s].name for s in self.order]

    def by_name(self, name):
        for sid in self.order:
            if self.sheets[sid].name == name:
                return self.sheets[sid]
        return None

    def name_taken(self, name, except_sid=None):
        low = name.lower()
        return any(s.name.lower() == low and s.id != except_sid for s in self.sheets.values())


def _rewrite_formulas(wb, old, new):
    pat = re.compile(r"(?<![\w.])" + re.escape(old) + "!")
    for sh in wb.sheets.values():
        for ref, (content, tz, lit, rev, author) in list(sh.cells.items()):
            if content and not lit and content.startswith("="):
                nc = pat.sub(new + "!", content)
                if nc != content:
                    sh.cells[ref] = (nc, tz, lit, rev, author)


def apply_body(wb, body):
    """Transition d'état déterministe, appliquée à l'identique par le serveur et par chaque copie."""
    k = body["k"]
    if k in ("set", "imp", "del", "ren", "right") and body["sid"] not in wb.sheets:
        return
    if k in ("set", "imp", "restore"):
        if k == "restore":
            sid = body["sid"]
            if sid not in wb.sheets:
                wb.sheets[sid] = Sheet(sid, body["name"], body.get("rights"))
                wb.order.append(sid)
            sh = wb.sheets[sid]
            if sh.name != body["name"]:
                old = sh.name
                sh.name = body["name"]
                _rewrite_formulas(wb, old, sh.name)
            snap = body["cells"]
            items = []
            for ref in set(sh.cells) | set(snap):
                c, tz, lit = snap.get(ref, (None, None, False))
                items.append((ref, c, tz, lit))
        elif k == "set":
            items = [(body["ref"], body["content"], body["tz"], body["lit"])]
            sh = wb.sheets[body["sid"]]
        else:
            items = body["items"]
            sh = wb.sheets[body["sid"]]
        for ref, content, tz, lit in items:
            old = sh.cells.get(ref, EMPTY)
            sh.cells[ref] = (content, tz, lit, old[3] + 1, body["author"])
            wb.conflicts.pop((sh.id, ref), None)
        return
    if k == "add":
        wb.sheets[body["sid"]] = Sheet(body["sid"], body["name"], {body["creator"]: W})
        wb.order.append(body["sid"])
        return
    if k == "del":
        sid = body["sid"]
        wb.sheets.pop(sid, None)
        if sid in wb.order:
            wb.order.remove(sid)
        for key in [key for key in wb.conflicts if key[0] == sid]:
            wb.conflicts.pop(key)
        return
    if k == "ren":
        sh = wb.sheets[body["sid"]]
        old = sh.name
        sh.name = body["name"]
        _rewrite_formulas(wb, old, sh.name)
        return
    if k == "right":
        wb.sheets[body["sid"]].rights[body["person"]] = body["level"]
        return
    if k == "conf":
        wb.conflicts[(body["sid"], body["ref"])] = Conflict(body["discarded"], body["by"])
        return
    raise ValueError(k)


# ---------------------------------------------------------------- réseau simulé

SERVER = "__serveur__"


class Network:
    """File de messages en mémoire. Les messages déjà émis restent en vol ; un message destiné
    à une personne déconnectée est perdu à la livraison (la resynchronisation la rattrape)."""

    def __init__(self):
        self.clients = {}
        self.server = None
        self.owner = None
        self.initial = None
        self.queue = []
        self.down = set()

    def send(self, src, dst, msg):
        self.queue.append((src, dst, msg))

    def connected(self, name):
        return name not in self.down

    def disconnect(self, name):
        self.down.add(name)
        if self.server is not None:
            self.server.on_disconnect(name)

    def reconnect(self, name):
        self.down.discard(name)
        self.clients[name]._on_connect()

    def _flush_all(self):
        for name, c in list(self.clients.items()):
            if self.connected(name):
                c.flush()

    def _deliver(self, src, dst, msg):
        if dst == SERVER:
            self.server.receive(src, msg)
        elif self.connected(dst):
            self.clients[dst].receive(msg)

    def deliver_all(self):
        while True:
            self._flush_all()
            if not self.queue:
                break
            batch, self.queue = self.queue, []
            for src, dst, msg in batch:
                self._deliver(src, dst, msg)

    def deliver_from(self, name):
        if self.connected(name):
            self.clients[name].flush()
        mine = [m for m in self.queue if m[0] == name]
        self.queue = [m for m in self.queue if m[0] != name]
        for src, dst, msg in mine:
            self._deliver(src, dst, msg)


class Server:
    """Autorité d'ordre : valide chaque opération reçue, lui attribue un numéro de journal
    et la diffuse. Les rejets et conflits sont aussi journalisés (sinon une personne
    hors ligne ne saurait jamais ce qui a été refusé)."""

    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.owner = owner
        net.owner = owner
        net.server = self
        self.wb = Workbook()
        self.wb.sheets["S0"] = Sheet("S0", "Feuille1", {owner: W})
        self.wb.order.append("S0")
        net.initial = self.wb.copy()
        self.log = []
        self.done = set()
        self.presence = {}

    def _broadcast(self, msg):
        for name in self.net.clients:
            self.net.send(SERVER, name, msg)

    def _broadcast_presence(self):
        self._broadcast(("presence", dict(self.presence)))

    def on_disconnect(self, name):
        if self.presence.pop(name, None) is not None:
            self._broadcast_presence()

    def receive(self, src, msg):
        kind = msg[0]
        if kind == "op":
            self._op(src, msg[1])
        elif kind == "hello":
            for e in self.log[msg[1]:]:
                self.net.send(SERVER, src, ("entry", e))
            self.net.send(SERVER, src, ("presence", dict(self.presence)))
        elif kind == "presence":
            self.presence[src] = (msg[1], msg[2])
            self._broadcast_presence()

    def _reject_or_check(self, body):
        """Renvoie (raison_de_rejet, None) ou (None, None) si la conduite est acceptée."""
        k = body["k"]
        author = body["author"]
        wb = self.wb
        if k == "right":
            if author != self.owner:
                return "role", None
            if body["sid"] not in wb.sheets:
                return "feuille", None
            return None, None
        if k == "add":
            if wb.name_taken(body["name"]):
                return "nom", None
            return None, None
        sid = body.get("sid")
        if k == "restore" and sid not in wb.sheets:
            if (body.get("rights") or {}).get(author) == W:
                return None, None
            return "feuille", None
        sh = wb.sheets.get(sid)
        if sh is None:
            return "feuille", None
        if sh.rights.get(author) != W:
            return "droit", None
        if k == "del" and len(wb.order) <= 1:
            return "ultime", None
        if k == "ren" and wb.name_taken(body["name"], except_sid=sid):
            return "nom", None
        if k == "set":
            cur = sh.cells.get(body["ref"], EMPTY)
            if cur[3] != body["base"]:
                if cur[0] == body["content"] and cur[2] == body["lit"]:
                    return "sans_effet", None
                return None, "conflit"
        return None, None

    def _op(self, src, msg):
        op_id = msg["op_id"]
        if op_id in self.done:
            return
        self.done.add(op_id)
        body = msg["body"]
        reason, conflict = self._reject_or_check(body)
        base = {"seq": len(self.log) + 1, "op_id": op_id, "author": body["author"],
                "t": body.get("t"), "name": body.get("name"), "ref": body.get("ref")}
        if reason is not None:
            entry = dict(base, kind="rejet", reason=reason, k=body["k"])
        elif conflict is not None:
            conf = {"k": "conf", "sid": body["sid"], "ref": body["ref"],
                    "discarded": body["content"], "by": body["author"]}
            apply_body(self.wb, conf)
            entry = dict(base, kind="conflit", body=conf)
        else:
            apply_body(self.wb, body)
            entry = dict(base, kind="op", body=body)
        self.log.append(entry)
        self._broadcast(("entry", entry))

# ---------------------------------------------------------------- copie locale

HISTORY_KINDS = ("set", "imp", "restore", "add", "del", "ren")


class _Disk:
    """Stockage de l'appareil : survit à la fermeture de l'application."""

    def __init__(self, replica):
        self.replica = replica
        self.pending = []
        self.log = []
        self.last_seq = 0
        self.counter = 0


class Client:
    def __init__(self, net, clock, name, tz="UTC", _disk=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.disk = _disk if _disk is not None else _Disk(net.initial.copy())
        self.active_sid = next(iter(self.disk.replica.order), None)
        self.alerts_list = []
        self.presence_map = {}
        self.undo_stack = []
        self.redo_stack = []
        self.version_wb = None
        self.need_hello = True
        net.clients[name] = self
        self.view = None
        self._rebuild()

    # -- réseau

    def _on_connect(self):
        self.need_hello = True
        for p in self.disk.pending:
            p["sent"] = False

    def flush(self):
        if not self.net.connected(self.name):
            return
        if self.need_hello:
            self.need_hello = False
            self.net.send(self.name, SERVER, ("hello", self.disk.last_seq))
        for p in self.disk.pending:
            if not p["sent"]:
                p["sent"] = True
                self.net.send(self.name, SERVER, ("op", {"op_id": p["op_id"], "body": p["body"]}))

    def receive(self, msg):
        if msg[0] == "entry":
            self._entry(msg[1])
        elif msg[0] == "presence":
            self.presence_map = {n: v for n, v in msg[1].items() if n != self.name}

    def _entry(self, e):
        disk = self.disk
        if e["seq"] != disk.last_seq + 1:
            return
        disk.last_seq = e["seq"]
        disk.log.append(e)
        disk.pending = [p for p in disk.pending if p["op_id"] != e["op_id"]]
        if e["kind"] in ("op", "conflit"):
            apply_body(disk.replica, e["body"])
        elif e["kind"] == "rejet" and e["author"] == self.name:
            self._alert_rejet(e)
        self._rebuild()

    def _alert_rejet(self, e):
        k, reason = e["k"], e["reason"]
        if k in ("set", "imp") and reason == "droit":
            self.alerts_list.append(Alert("modification_rejetee", e["name"], e["ref"]))
        elif k in ("set", "imp") and reason == "feuille":
            self.alerts_list.append(Alert("feuille_supprimee", e["name"]))
        elif k in ("add", "ren") and reason == "nom":
            self.alerts_list.append(Alert("nom_existant", e["name"]))

    # -- vue locale = copie confirmée + modifications en attente

    def _rebuild(self):
        v = self.disk.replica.copy()
        for p in self.disk.pending:
            apply_body(v, p["body"])
        self.view = v

    def _submit(self, spec, counted=True):
        disk = self.disk
        disk.counter += 1
        op_id = f"{self.name}-{disk.counter}"
        body = dict(spec, author=self.name, t=self.clock.now())
        disk.pending.append({"op_id": op_id, "body": body, "counted": counted, "sent": False})
        apply_body(self.view, body)
        return op_id

    def _do(self, spec, inv, push=True, clear_redo=True):
        body = dict(spec)
        if body["k"] == "set":
            body["base"] = self.view.sheets[body["sid"]].cells.get(body["ref"], EMPTY)[3]
        op_id = self._submit(body, counted=body["k"] != "right")
        guard = None
        if body["k"] == "set":
            guard = (body["sid"], body["ref"],
                     self.view.sheets[body["sid"]].cells.get(body["ref"], EMPTY)[3])
        if push:
            self.undo_stack.append({"fwd": spec, "inv": inv, "op_id": op_id, "guard": guard})
            if clear_redo:
                self.redo_stack.clear()
        return op_id

    # -- lectures

    def _rd(self):
        return self.version_wb if self.version_wb is not None else self.view

    def _sid(self, sheet, wb=None):
        wb = wb or self._rd()
        if sheet is None:
            return self.active_sid if self.active_sid in wb.sheets else None
        s = wb.by_name(sheet)
        return s.id if s is not None else None

    def _writer(self, sid):
        sh = self.view.sheets.get(sid)
        return sh is not None and sh.rights.get(self.name) == W

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self.alerts_list.append(Alert(kind, sheet, cell, line))

    def _cell(self, ref, sheet=None):
        rd = self._rd()
        sid = self._sid(sheet, rd)
        if sid is None:
            return None, None
        return sid, rd.sheets[sid].cells.get(ref, EMPTY)

    def _evaluate(self, ref, sheet=None):
        rd = self._rd()
        sid = self._sid(sheet, rd)
        if sid is None:
            return None
        if rd.sheets[sid].cells.get(ref, EMPTY)[0] is None:
            return None
        return Evaluator(rd, self.clock.now()).cell_value(sid, ref)

    # -- saisie

    def set_cell(self, ref, text, sheet=None):
        if self.version_wb is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        sh = self.view.sheets[sid]
        if not self._writer(sid):
            self._alert("droit_insuffisant", sh.name, ref)
            return
        content = None if text in (None, "") else text
        cur = sh.cells.get(ref, EMPTY)
        if cur[0] == content:
            return
        spec = {"k": "set", "sid": sid, "name": sh.name, "ref": ref, "content": content,
                "tz": self.tz, "lit": False}
        inv = {"k": "set", "sid": sid, "name": sh.name, "ref": ref, "content": cur[0],
               "tz": cur[1], "lit": cur[2]}
        self._do(spec, inv)

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def content(self, ref, sheet=None):
        _, cell = self._cell(ref, sheet)
        return None if cell is None else cell[0]

    def value(self, ref, sheet=None):
        v = self._evaluate(ref, sheet)
        return show(v, self.tz)

    def error(self, ref, sheet=None):
        v = self._evaluate(ref, sheet)
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        self.tz = tz

    # -- feuilles

    def sheets(self):
        return self._rd().names()

    def activate(self, name):
        sid = self._sid(name)
        if sid is not None:
            self.active_sid = sid

    def add_sheet(self, name):
        if self.view.name_taken(name):
            self._alert("nom_existant", name)
            return
        self.disk.counter += 1
        sid = f"{self.name}-S{self.disk.counter}"
        self._do({"k": "add", "sid": sid, "name": name, "creator": self.name},
                 {"k": "del", "sid": sid, "name": name})

    def delete_sheet(self, name):
        sid = self._sid(name)
        if sid is None:
            return
        sh = self.view.sheets[sid]
        if not self._writer(sid):
            self._alert("droit_insuffisant", name)
            return
        if len(self.view.order) <= 1:
            return
        snap = {ref: (c, tz, lit) for ref, (c, tz, lit, _r, _a) in sh.cells.items() if c is not None}
        self._do({"k": "del", "sid": sid, "name": name},
                 {"k": "restore", "sid": sid, "name": name, "cells": snap, "rights": dict(sh.rights)})

    def rename_sheet(self, old, new):
        sid = self._sid(old)
        if sid is None or new == old:
            return
        if self.view.name_taken(new, except_sid=sid):
            self._alert("nom_existant", new)
            return
        if not self._writer(sid):
            self._alert("droit_insuffisant", old)
            return
        self._do({"k": "ren", "sid": sid, "name": new}, {"k": "ren", "sid": sid, "name": old})

    # -- droits

    def right(self, person, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        return self._rd().sheets[sid].rights.get(person)

    def set_right(self, person, sheet, level):
        if self.version_wb is not None or self.name != self.net.owner:
            return
        if not self.net.connected(self.name):
            return
        sid = self._sid(sheet)
        if sid is None or self.view.sheets[sid].rights.get(person) == level:
            return
        self._submit({"k": "right", "sid": sid, "name": sheet, "person": person, "level": level},
                     counted=False)

    # -- état

    def alerts(self):
        return list(self.alerts_list)

    def connection_status(self):
        return "en ligne" if self.net.connected(self.name) else "hors ligne"

    def pending_count(self):
        return sum(1 for p in self.disk.pending if p["counted"])

    def select(self, ref, sheet=None):
        if not self.net.connected(self.name):
            return
        sid = self._sid(sheet)
        name = self.view.sheets[sid].name if sid is not None else None
        self.net.send(self.name, SERVER, ("presence", name, ref))

    def presence(self):
        if not self.net.connected(self.name):
            return {}
        return dict(self.presence_map)

    # -- conflits

    def conflict(self, ref, sheet=None):
        rd = self._rd()
        sid = self._sid(sheet, rd)
        if sid is None:
            return None
        return rd.conflicts.get((sid, ref))

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.version_wb is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        sh = self.view.sheets[sid]
        if not self._writer(sid):
            self._alert("droit_insuffisant", sh.name, ref)
            return
        cf = self.view.conflicts.get((sid, ref))
        if cf is None:
            return
        cur = sh.cells.get(ref, EMPTY)
        content = cf.discarded if use_discarded else cur[0]
        spec = {"k": "set", "sid": sid, "name": sh.name, "ref": ref, "content": content,
                "tz": self.tz, "lit": False}
        inv = {"k": "set", "sid": sid, "name": sh.name, "ref": ref, "content": cur[0],
               "tz": cur[1], "lit": cur[2]}
        self._do(spec, inv)

    # -- annuler / rétablir

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _pending_index(self, op_id):
        for i, p in enumerate(self.disk.pending):
            if p["op_id"] == op_id:
                return i
        return None

    def undo(self):
        if self.version_wb is not None or not self.undo_stack:
            return
        rec = self.undo_stack[-1]
        i = self._pending_index(rec["op_id"])
        if i is not None:
            # modification encore en attente : elle est retirée, rien n'est envoyé
            del self.disk.pending[i]
            self.undo_stack.pop()
            self._rebuild()
            self.redo_stack.append(rec)
            return
        g = rec["guard"]
        if g is not None:
            sid, ref, rev = g
            sh = self.view.sheets.get(sid)
            if sh is None or sh.cells.get(ref, EMPTY)[3] != rev:
                self._alert("annulation_impossible", sh.name if sh else None, ref)
                return
        target = rec["inv"].get("sid")
        if target in self.view.sheets and not self._writer(target):
            return
        self.undo_stack.pop()
        self._do(rec["inv"], rec["fwd"], push=False)
        self.redo_stack.append(rec)

    def redo(self):
        if self.version_wb is not None or not self.redo_stack:
            return
        rec = self.redo_stack.pop()
        target = rec["fwd"].get("sid")
        if target in self.view.sheets and not self._writer(target):
            return
        self._do(rec["fwd"], rec["inv"], push=True, clear_redo=False)

    # -- réouverture

    def reopen(self):
        return Client(self.net, self.clock, self.name, self.tz, _disk=self.disk)

    # -- historique

    def _replay(self, upto):
        wb = self.net.initial.copy()
        for e in self.disk.log:
            if e["seq"] > upto:
                break
            if e["kind"] in ("op", "conflit"):
                apply_body(wb, e["body"])
        return wb

    def history(self, sheet=None):
        sid = None
        if sheet is not None:
            sid = self._sid(sheet)
            if sid is None:
                return []
        out = []
        for e in self.disk.log:
            if e["kind"] != "op" or e["body"]["k"] not in HISTORY_KINDS:
                continue
            if sid is not None and e["body"].get("sid") != sid:
                continue
            out.append(e)
        out.sort(key=lambda e: (e["t"], e["seq"]), reverse=True)
        return [Version(e["seq"], e["author"], show(e["t"], self.tz),
                        "restauration" if e["body"]["k"] == "restore" else "modification")
                for e in out]

    def open_version(self, vid):
        self.version_wb = self._replay(vid)

    def close_version(self):
        self.version_wb = None

    def restore_version(self, vid):
        if self.version_wb is not None:
            return
        entry = next((e for e in self.disk.log if e["seq"] == vid), None)
        if entry is None or "sid" not in entry["body"]:
            return
        sid = entry["body"]["sid"]
        if sid not in self.view.sheets or not self._writer(sid):
            return
        past = self._replay(vid)
        if sid not in past.sheets:
            return
        ps = past.sheets[sid]
        cur = self.view.sheets[sid]
        snap = {ref: (c, tz, lit) for ref, (c, tz, lit, _r, _a) in ps.cells.items() if c is not None}
        now = {ref: (c, tz, lit) for ref, (c, tz, lit, _r, _a) in cur.cells.items() if c is not None}
        self._do({"k": "restore", "sid": sid, "name": ps.name, "cells": snap},
                 {"k": "restore", "sid": sid, "name": cur.name, "cells": now})

    # -- CSV

    def export_csv(self):
        rd = self._rd()
        sid = self._sid(None, rd)
        sh = rd.sheets[sid]
        ev = Evaluator(rd, self.clock.now())
        pos = []
        for ref, cell in sh.cells.items():
            if cell[0] is None:
                continue
            m = re.match(r"([A-Z]+)(\d+)\Z", ref)
            pos.append((int(m.group(2)), col_index(m.group(1))))
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        if pos:
            maxcol = max(c for _, c in pos)
            for r in sorted({r for r, _ in pos}):
                row = [export_text(ev.cell_value(sid, f"{col_name(c)}{r}"), self.tz)
                       for c in range(1, maxcol + 1)]
                writer.writerow(row)
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        sid = self._sid(None)
        if sid is None:
            return
        sh = self.view.sheets[sid]
        if not self._writer(sid):
            self._alert("droit_insuffisant", sh.name)
            return
        text = data.decode("utf-8-sig")
        rows = []
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        while True:
            start = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error:
                self._alert("csv_invalide", sh.name, None, start)
                return
            rows.append(row)
        items = []
        prev = []
        for ri, row in enumerate(rows):
            for ci, field in enumerate(row):
                ref = f"{col_name(ci + 1)}{ri + 1}"
                cur = sh.cells.get(ref, EMPTY)
                items.append((ref, field if field != "" else None, self.tz, field.startswith("=")))
                prev.append((ref, cur[0], cur[1], cur[2]))
        if not items:
            return
        self._do({"k": "imp", "sid": sid, "name": sh.name, "items": items},
                 {"k": "imp", "sid": sid, "name": sh.name, "items": prev})

