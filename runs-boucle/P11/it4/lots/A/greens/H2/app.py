"""Classeur collaboratif hors ligne — couche code, tour 1 (green).

Tout tient dans ce module : temps simulé, réseau simulé en mémoire, analyseur de
formules, recalcul à la demande suivant le graphe de dépendances (détection de cycle
sur la pile d'évaluation), serveur qui tranche les conflits, copies locales qui
fusionnent les deltas reçus.
"""
import csv
import io
import re
import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

sys.setrecursionlimit(60000)

UTC = timezone.utc
W = "écriture"
R = "lecture"
SERVER = "__serveur__"
# actions qu'une annulation peut retirer d'un envoi encore en attente (sinon : action inverse)
WITHDRAWABLE = ("set", "set_many", "add_sheet", "delete_sheet", "rename")

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?")


@lru_cache(maxsize=None)
def zone(name):
    return ZoneInfo(name)


def fmt_dt(dt, tz):
    return dt.astimezone(zone(tz)).strftime("%Y-%m-%d %H:%M")


def col_name(i):
    s = ""
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def split_ref(ref):
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d+)", ref)
    return col_index(m.group(1)), int(m.group(2))


def make_ref(col, row):
    return f"{col_name(col)}{row}"


# ------------------------------------------------------------------ erreurs et valeurs

class CellErr(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Err:
    def __init__(self, code):
        self.code = code


def typed_value(c, tz):
    """Valeur d'un contenu non formule (texte saisi ou importé)."""
    if NUM_RE.fullmatch(c):
        return float(c) if "." in c else int(c)
    if DATE_RE.fullmatch(c):
        return date.fromisoformat(c)
    if DT_RE.fullmatch(c):
        dt = datetime.fromisoformat(c.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone(tz))
        return dt
    return c


def is_gap(naive, tz):
    """Heure locale inexistante dans le fuseau (passage à l'heure d'été)."""
    aware = naive.replace(tzinfo=zone(tz))
    back = aware.astimezone(zone(tz)).replace(tzinfo=None)
    return back != naive


# ------------------------------------------------------------------ analyseur

TOKEN_RE = re.compile(r"""
 (?P<ws>\s+)
|(?P<num>\d+(?:\.\d+)?)
|(?P<ref>(?:(?P<sh>[^\W\d]\w*)!)?(?P<col>[A-Za-z]{1,3})(?P<row>\d+)(?![\w(]))
|(?P<func>[^\W\d]\w*)(?=\()
|(?P<op>[-+*/(),:])
""", re.X)


def tokenize(src):
    toks = []
    pos = 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise CellErr("#SYNTAXE!")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        if kind == "ref":
            toks.append(("ref", (m.group("sh"), m.group("col").upper(), int(m.group("row")))))
        elif kind == "num":
            toks.append(("num", m.group("num")))
        elif kind == "func":
            toks.append(("func", m.group("func").upper()))
        else:
            toks.append(("op", m.group("op")))
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

    def expect_op(self, val):
        if self.peek() != ("op", val):
            raise CellErr("#SYNTAXE!")
        self.i += 1

    def expr(self):
        n = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            n = ("bin", op, n, self.term())
        return n

    def term(self):
        n = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            n = ("bin", op, n, self.unary())
        return n

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
            sh, col, row = val
            if self.peek() == ("op", ":"):
                self.take()
                k2, v2 = self.take()
                if k2 != "ref":
                    raise CellErr("#SYNTAXE!")
                _, col2, row2 = v2
                return ("range", sh, col_index(col), row, col_index(col2), row2)
            return ("ref", sh, make_ref(col_index(col), row))
        if kind == "func":
            self.expect_op("(")
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            return ("call", val, args)
        if (kind, val) == ("op", "("):
            n = self.expr()
            self.expect_op(")")
            return n
        raise CellErr("#SYNTAXE!")


def parse_formula(src):
    toks = tokenize(src)
    p = _Parser(toks)
    node = p.expr()
    if p.i != len(toks):
        raise CellErr("#SYNTAXE!")
    return node


def _num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        raise CellErr("#TYPE!")
    if isinstance(v, (int, float)):
        return v
    raise CellErr("#TYPE!")


def _arith(op, a, b):
    if op == "-" and isinstance(a, datetime) and isinstance(b, datetime):
        # en UTC : deux datetimes au même objet fuseau se soustraient en heure murale (faux à l'heure d'été)
        return (a.astimezone(UTC) - b.astimezone(UTC)).total_seconds() / 86400
    if op == "-" and isinstance(a, date) and isinstance(b, date) and not isinstance(a, datetime):
        return (a - b).days
    x, y = _num(a), _num(b)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0:
        raise CellErr("#DIV/0!")
    return x / y


class Book:
    """Évaluateur : recalcul à la demande, cycle détecté sur la pile d'évaluation."""

    def __init__(self, sheets, tz, now):
        self.sheets = sheets
        self.tz = tz
        self.now = now
        self.stack = []

    def cell_value(self, sheet, ref):
        key = (sheet, ref)
        if key in self.stack:
            raise CellErr("#CIRC!")
        if sheet not in self.sheets:
            raise CellErr("#REF!")
        rec = self.sheets[sheet].get(ref)
        if rec is None or rec["content"] is None:
            return None
        self.stack.append(key)
        try:
            return self._interpret(rec, sheet)
        except CellErr as e:
            return Err(e.code)
        finally:
            self.stack.pop()

    def top(self, sheet, ref):
        try:
            return self.cell_value(sheet, ref)
        except CellErr as e:
            return Err(e.code)

    def _interpret(self, rec, sheet):
        c = rec["content"]
        if rec["literal"]:
            return c
        if c.startswith("="):
            return self.ev(parse_formula(c[1:]), sheet)
        return typed_value(c, rec["tz"])

    def ref_value(self, sheet, ref):
        v = self.cell_value(sheet, ref)
        if isinstance(v, Err):
            raise CellErr(v.code)
        return 0 if v is None else v

    def _both(self, a, b, sheet):
        vals, errs = [], []
        for side in (a, b):
            try:
                vals.append(self.ev(side, sheet))
            except CellErr as e:
                errs.append(e.code)
        if errs:
            raise CellErr("#CIRC!" if "#CIRC!" in errs else errs[0])
        return vals

    def ev(self, n, sheet):
        k = n[0]
        if k == "num":
            return n[1]
        if k == "ref":
            return self.ref_value(n[1] or sheet, n[2])
        if k == "neg":
            return -_num(self.ev(n[1], sheet))
        if k == "bin":
            a, b = self._both(n[2], n[3], sheet)
            return _arith(n[1], a, b)
        if k == "call":
            if n[1] == "MAINTENANT" and not n[2]:
                return self.now
            if n[1] == "SOMME":
                return self.sum_args(n[2], sheet)
            raise CellErr("#SYNTAXE!")
        raise CellErr("#SYNTAXE!")

    def sum_args(self, args, sheet):
        total = 0
        errs = []
        for a in args:
            if a[0] == "range":
                _, sh, c1, r1, c2, r2 = a
                sh = sh or sheet
                for c in range(min(c1, c2), max(c1, c2) + 1):
                    for r in range(min(r1, r2), max(r1, r2) + 1):
                        try:
                            v = self.cell_value(sh, make_ref(c, r))
                        except CellErr as e:
                            errs.append(e.code)
                            continue
                        if isinstance(v, Err):
                            errs.append(v.code)
                        elif isinstance(v, (int, float)) and not isinstance(v, bool):
                            total += v
            else:
                try:
                    v = self.ev(a, sheet)
                except CellErr as e:
                    errs.append(e.code)
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    total += v
        if errs:
            raise CellErr("#CIRC!" if "#CIRC!" in errs else errs[0])
        return total


def display_value(v, tz):
    if isinstance(v, Err):
        return v.code
    if isinstance(v, datetime):
        return fmt_dt(v, tz)
    if isinstance(v, date):
        return v.isoformat()
    return v


def export_value(v, tz):
    if isinstance(v, Err):
        return v.code
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.astimezone(zone(tz)).isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def rewrite_sheet_refs(content, old, new):
    return re.sub(r"(?<!\w)" + re.escape(old) + "!", new + "!", content)


# ------------------------------------------------------------------ CSV

def csv_unclosed_line(text):
    """Ligne où commence un guillemet jamais fermé, sinon None."""
    line = 1
    in_q = False
    field_start = True
    qline = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_q:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    i += 2
                    continue
                in_q = False
            elif ch == "\n":
                line += 1
        else:
            if ch == '"' and field_start:
                in_q = True
                qline = line
                field_start = False
            elif ch == ",":
                field_start = True
            elif ch == "\n":
                line += 1
                field_start = True
            elif ch == "\r":
                pass
            else:
                field_start = False
        i += 1
    return qline if in_q else None


def csv_parse(data):
    """Retourne (lignes, ligne_invalide). Lignes vides ignorées."""
    text = data.decode("utf-8-sig")
    bad = csv_unclosed_line(text)
    if bad is not None:
        return None, bad
    rows = [r for r in csv.reader(io.StringIO(text, newline="")) if r]
    return rows, None


# ------------------------------------------------------------------ état partagé

def new_state(owner):
    return {"owner": owner, "sheets": {}, "rights": {}, "uids": {}, "history": [], "presence": {}}


def copy_state(st):
    return {
        "owner": st["owner"],
        "sheets": {n: dict(c) for n, c in st["sheets"].items()},
        "rights": {n: dict(r) for n, r in st["rights"].items()},
        "uids": dict(st["uids"]),
        "history": list(st["history"]),
        "presence": dict(st["presence"]),
    }


def apply_changes(st, changes):
    """Applique des deltas. Les enregistrements de cellules ne sont jamais mutés."""
    for ch in changes:
        k = ch[0]
        if k == "cell":
            _, sheet, ref, rec = ch
            if sheet in st["sheets"]:
                st["sheets"][sheet][ref] = rec
        elif k == "sheet_add":
            _, name, rights, uid = ch
            st["sheets"][name] = {}
            st["rights"][name] = dict(rights)
            st["uids"][name] = uid
        elif k == "sheet_del":
            name = ch[1]
            st["sheets"].pop(name, None)
            st["rights"].pop(name, None)
            st["uids"].pop(name, None)
        elif k == "sheet_rename":
            old, new = ch[1], ch[2]
            st["sheets"] = {(new if n == old else n): c for n, c in st["sheets"].items()}
            st["rights"] = {(new if n == old else n): r for n, r in st["rights"].items()}
            st["uids"] = {(new if n == old else n): u for n, u in st["uids"].items()}
        elif k == "right":
            _, sheet, person, level = ch
            if sheet in st["rights"]:
                st["rights"][sheet][person] = level
        elif k == "history":
            st["history"].append(ch[1])
        elif k == "history_del":
            st["history"] = [e for e in st["history"] if e["op"] != ch[1]]
        elif k == "presence":
            _, who, sheet, ref = ch
            if sheet is None:
                st["presence"].pop(who, None)
            else:
                st["presence"][who] = (sheet, ref)


# ------------------------------------------------------------------ temps et réseau

class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Network:
    """Réseau simulé : file FIFO de messages en vol. Un message n'est livré que si
    l'émetteur et le destinataire sont connectés au moment de la livraison."""

    def __init__(self):
        self.queue = []
        self.online = {}
        self.nodes = {}
        self.storage = {}

    def send(self, src, dst, payload):
        self.queue.append((src, dst, payload))

    def _step(self, msg):
        src, dst, payload = msg
        if not self.online.get(src, True) or not self.online.get(dst, True):
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, payload)

    def deliver_all(self):
        while self.queue:
            self._step(self.queue.pop(0))

    def deliver_from(self, name):
        take = [m for m in self.queue if m[0] == name]
        self.queue = [m for m in self.queue if m[0] != name]
        for m in take:
            self._step(m)

    def disconnect(self, name):
        self.online[name] = False
        server = self.nodes.get(SERVER)
        if server is not None and name != SERVER:
            server.peer_left(name)

    def reconnect(self, name):
        self.online[name] = True
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "on_reconnect"):
            node.on_reconnect()


# ------------------------------------------------------------------ serveur

def _ok(status="ok"):
    return {"status": status}


def _rej(reason, sheet=None, cell=None, name=None):
    return {"status": "rejected", "reason": reason, "sheet": sheet, "cell": cell, "name": name}


class Server:
    """Autorité : ordonne les opérations reçues, tranche les conflits, diffuse les deltas."""

    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.state = new_state(owner)
        self.state["sheets"]["Feuille1"] = {}
        self.state["rights"]["Feuille1"] = {owner: W}
        self.state["uids"]["Feuille1"] = "uid-0"
        self.results = {}
        self.applied = {}
        self.vc = 0
        self.hid = 0
        net.nodes[SERVER] = self
        net.online[SERVER] = True

    # -- utilitaires
    def _nextv(self):
        self.vc += 1
        return self.vc

    def _level(self, person, sheet):
        return self.state["rights"].get(sheet, {}).get(person)

    def _snap(self, cells):
        return {r: (c["content"], c["literal"], c["tz"]) for r, c in cells.items() if c["content"] is not None}

    def _entry(self, op, sheet, snap, kind="modification", uid=None):
        self.hid += 1
        if uid is None:
            uid = self.state["uids"].get(sheet)
        return {"id": self.hid, "op": op["id"], "author": op["author"], "ts": op["ts"],
                "kind": kind, "sheet": sheet, "name": sheet, "uid": uid, "snap": snap}

    def _names_lower(self, exclude=None):
        return {n.lower(): n for n in self.state["sheets"] if n != exclude}

    # -- protocole
    def snapshot(self):
        return copy_state(self.state)

    def receive(self, src, payload):
        t = payload["type"]
        if t == "hello":
            acks = {k: v for k, v in self.results.items() if k[0] == src}
            self.net.send(SERVER, src, {"type": "snapshot", "state": self.snapshot(), "acks": acks})
            return
        if t == "presence":
            sheet, ref = payload["sheet"], payload["ref"]
            if sheet in self.state["sheets"]:
                self._commit([("presence", src, sheet, ref)], None, {})
            return
        op = payload["op"]
        changes, res = self._process(op)
        self._commit(changes, src, {op["id"]: res})

    def _commit(self, changes, src, acks):
        if changes:
            apply_changes(self.state, changes)
        for name in list(self.net.nodes):
            if name == SERVER or not self.net.online.get(name, True):
                continue
            if not changes and name != src:
                continue
            self.net.send(SERVER, name, {"type": "delta", "changes": changes,
                                         "acks": acks if name == src else {}})

    def peer_left(self, name):
        if name in self.state["presence"]:
            self._commit([("presence", name, None, None)], None, {})

    def _process(self, op):
        if op["id"] in self.results:
            return [], self.results[op["id"]]
        handler = getattr(self, "_op_" + op["action"])
        changes, res = handler(op)
        self.results[op["id"]] = res
        return changes, res

    # -- opérations de cellules
    def _op_set(self, op):
        sheet, ref = op["sheet"], op["ref"]
        if sheet not in self.state["sheets"]:
            return [], _rej("feuille_supprimee", sheet=sheet, cell=ref)
        if self._level(op["author"], sheet) != W:
            return [], _rej("droit", sheet=sheet, cell=ref)
        cells = self.state["sheets"][sheet]
        cur = cells.get(ref)
        content, literal = op["content"], op["literal"]
        if cur is not None and cur["content"] == content and (content is None or cur["literal"] == literal):
            changes = [("cell", sheet, ref, dict(cur, conflict=None))] if cur["conflict"] else []
            return changes, _ok()
        if cur is not None and cur["version"] > op["base"] and cur["author"] != op["author"]:
            rec = dict(cur, conflict={"content": content, "literal": literal, "tz": op["tz"], "by": op["author"]})
            return [("cell", sheet, ref, rec)], _ok("conflit")
        v = self._nextv()
        rec = {"content": content, "literal": literal, "tz": op["tz"], "author": op["author"],
               "version": v, "conflict": None}
        cells2 = dict(cells)
        cells2[ref] = rec
        self.applied[op["id"]] = [(sheet, ref, cur, v, op["author"])]
        changes = [("cell", sheet, ref, rec), ("history", self._entry(op, sheet, self._snap(cells2)))]
        return changes, _ok()

    def _op_set_many(self, op):
        sheet = op["sheet"]
        if sheet not in self.state["sheets"]:
            return [], _rej("feuille_supprimee", sheet=sheet)
        if self._level(op["author"], sheet) != W:
            return [], _rej("droit", sheet=sheet)
        cells = self.state["sheets"][sheet]
        cells2 = dict(cells)
        changes, applied = [], []
        for ref, content, literal, tz in op["cells"]:
            cur = cells.get(ref)
            curc = cur["content"] if cur else None
            if curc == content and (content is None or (cur and cur["literal"] == literal)):
                continue
            v = self._nextv()
            rec = {"content": content, "literal": literal, "tz": tz, "author": op["author"],
                   "version": v, "conflict": None}
            cells2[ref] = rec
            changes.append(("cell", sheet, ref, rec))
            applied.append((sheet, ref, cur, v, op["author"]))
        if not changes:
            return [], _ok()
        self.applied[op["id"]] = applied
        changes.append(("history", self._entry(op, sheet, self._snap(cells2), kind=op.get("kind", "modification"))))
        return changes, _ok()

    def _op_resolve(self, op):
        sheet, ref = op["sheet"], op["ref"]
        if sheet not in self.state["sheets"]:
            return [], _rej("feuille_supprimee", sheet=sheet, cell=ref)
        if self._level(op["author"], sheet) != W:
            return [], _rej("droit", sheet=sheet, cell=ref)
        cur = self.state["sheets"][sheet].get(ref)
        if cur is None or not cur["conflict"]:
            return [], _ok()
        if op["use_discarded"]:
            c = cur["conflict"]
            return self._op_set(dict(op, action="set", content=c["content"], literal=c["literal"],
                                     tz=c["tz"], base=cur["version"]))
        return [("cell", sheet, ref, dict(cur, conflict=None))], _ok()

    def _op_withdraw(self, op):
        aid = op["op_id"]
        changes = []
        for item in reversed(self.applied.pop(aid, [])):
            kind = item[0]
            if kind == "__sheet__":
                if item[1] in self.state["sheets"]:
                    changes.append(("sheet_del", item[1]))
                continue
            if kind == "__del__":
                _, name, cells, rights, uid = item
                if name not in self.state["sheets"]:
                    changes.append(("sheet_add", name, rights, uid))
                    for ref, rec in cells.items():
                        changes.append(("cell", name, ref, dict(rec, version=self._nextv())))
                continue
            if kind == "__ren__":
                _, old, new, renamed = item
                if new in self.state["sheets"] and old not in self.state["sheets"]:
                    changes.append(("sheet_rename", new, old))
                    for sname, ref, rec in renamed:
                        changes.append(("cell", sname, ref, dict(rec, version=self._nextv())))
                continue
            sheet, ref, prev, v, author = item
            cells = self.state["sheets"].get(sheet)
            if cells is None:
                continue
            cur = cells.get(ref)
            # une cellule déjà reprise par une autre personne n'est pas touchée ; les annulations
            # successives d'une même personne se défont dans l'ordre (la plus récente d'abord)
            if cur is None or cur["author"] != author:
                continue
            nv = self._nextv()
            if prev is None:
                rec = {"content": None, "literal": False, "tz": "UTC", "author": author,
                       "version": nv, "conflict": None}
            else:
                rec = dict(prev, version=nv)
            changes.append(("cell", sheet, ref, rec))
        if any(e["op"] == aid for e in self.state["history"]):
            changes.append(("history_del", aid))
        return changes, _ok()

    # -- feuilles, droits, restauration
    def _op_add_sheet(self, op):
        name = op["name"]
        if name.lower() in self._names_lower():
            return [], _rej("nom", name=name)
        rights = {self.owner: W}
        if op["author"] != self.owner:
            rights[op["author"]] = W
        self.applied[op["id"]] = [("__sheet__", name)]
        return [("sheet_add", name, rights, op["id"])], _ok()

    def _op_create_sheet(self, op):
        name = op["name"]
        if name in self.state["sheets"]:
            return [], _rej("nom", name=name)
        changes = [("sheet_add", name, op["rights"], op["id"])]
        for ref, content, literal, tz in op["cells"]:
            if content is None:
                continue
            rec = {"content": content, "literal": literal, "tz": tz, "author": op["author"],
                   "version": self._nextv(), "conflict": None}
            changes.append(("cell", name, ref, rec))
        return changes, _ok()

    def _op_delete_sheet(self, op):
        name = op["name"]
        if name not in self.state["sheets"]:
            return [], _ok()
        if self._level(op["author"], name) != W:
            return [], _rej("droit", sheet=name)
        if len(self.state["sheets"]) == 1:
            return [], _rej("derniere", sheet=name)
        self.applied[op["id"]] = [("__del__", name, dict(self.state["sheets"][name]),
                                   dict(self.state["rights"].get(name, {})),
                                   self.state["uids"].get(name))]
        return [("sheet_del", name)], _ok()

    def _op_rename(self, op):
        old, new = op["old"], op["new"]
        if old not in self.state["sheets"]:
            return [], _rej("feuille_supprimee", sheet=old)
        if self._level(op["author"], old) != W:
            return [], _rej("droit", sheet=old)
        if new == old:
            return [], _ok()
        if new.lower() in self._names_lower(exclude=old):
            return [], _rej("nom", name=new)
        changes = [("sheet_rename", old, new)]
        changed = []
        for s, cells in self.state["sheets"].items():
            target = new if s == old else s
            for ref, rec in cells.items():
                if rec["literal"] or rec["content"] is None or not rec["content"].startswith("="):
                    continue
                newc = rewrite_sheet_refs(rec["content"], old, new)
                if newc != rec["content"]:
                    changed.append((s, ref, rec))
                    changes.append(("cell", target, ref, dict(rec, content=newc)))
        self.applied[op["id"]] = [("__ren__", old, new, changed)]
        return changes, _ok()

    def _op_set_right(self, op):
        if op["author"] != self.owner:
            return [], _ok()
        sheet, person, level = op["sheet"], op["person"], op["level"]
        if sheet not in self.state["sheets"] or person == self.owner or level not in (W, R):
            return [], _ok()
        return [("right", sheet, person, level)], _ok()

    def _op_restore(self, op):
        entry = next((e for e in self.state["history"] if e["id"] == op["entry"]), None)
        if entry is None:
            return [], _rej("feuille_supprimee")
        target = next((n for n, u in self.state["uids"].items() if u == entry["uid"]), None)
        if target is None:
            return [], _rej("feuille_supprimee")
        if self._level(op["author"], target) != W:
            return [], _rej("droit", sheet=target)
        changes = []
        cur_name = target
        if entry["name"] != target and entry["name"] not in self.state["sheets"]:
            changes.append(("sheet_rename", target, entry["name"]))
            cur_name = entry["name"]
        cells = self.state["sheets"][target]
        cells2 = dict(cells)
        for ref in set(entry["snap"]) | set(cells):
            content, literal, tz = entry["snap"].get(ref, (None, False, "UTC"))
            rec = {"content": content, "literal": literal, "tz": tz, "author": op["author"],
                   "version": self._nextv(), "conflict": None}
            cells2[ref] = rec
            changes.append(("cell", cur_name, ref, rec))
        changes.append(("history", self._entry(op, cur_name, self._snap(cells2), kind="restauration",
                                               uid=entry["uid"])))
        return changes, _ok()


# ------------------------------------------------------------------ objets exposés

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    def __init__(self, e, tz):
        self.id = e["id"]
        self.author = e["author"]
        self.kind = e["kind"]
        self.sheet = e["sheet"]
        self.timestamp = fmt_dt(e["ts"], tz)


NAIVE_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")


# ------------------------------------------------------------------ copie locale

class Client:
    """Copie locale : état reçu du serveur + modifications en attente (rejouées par-dessus)."""

    def __init__(self, net, clock, name, tz="UTC"):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.store = net.storage.setdefault(name, {"outbox": [], "seq": 0, "base": None})
        if self.store["base"] is None:
            self.store["base"] = new_state(None)
        self.active = "Feuille1"
        self._alerts = []
        self.undo_stack = []
        self.redo_stack = []
        self.viewing = None
        net.nodes[name] = self
        net.online.setdefault(name, True)
        if net.online[name]:
            self._sync_out()

    # -- réseau
    def _new_id(self):
        self.store["seq"] += 1
        return (self.name, self.store["seq"])

    def _send_entry(self, entry):
        if self.net.online.get(self.name, True):
            self.net.send(self.name, SERVER, {"type": "op", "op": entry["op"]})

    def _sync_out(self):
        self.net.send(self.name, SERVER, {"type": "hello"})
        for entry in self.store["outbox"]:
            self._send_entry(entry)

    def on_reconnect(self):
        self._sync_out()

    def receive(self, src, payload):
        t = payload["type"]
        if t == "snapshot":
            self.store["base"] = copy_state(payload["state"])
        elif t == "delta":
            apply_changes(self.store["base"], payload["changes"])
        self._acks(payload.get("acks", {}))

    def _acks(self, acks):
        keep = []
        for e in self.store["outbox"]:
            if e["id"] in acks:
                res = acks[e["id"]]
                if e["kind"] == "op" and res.get("status") == "rejected":
                    self._alert_rejected(e["op"], res)
            else:
                keep.append(e)
        self.store["outbox"][:] = keep

    def _alert_rejected(self, op, res):
        a, reason = op["action"], res["reason"]
        if reason == "droit":
            if a in ("set", "set_many", "resolve", "restore"):
                self._alert("modification_rejetee", res.get("sheet") or op.get("sheet"),
                            res.get("cell") or op.get("ref"))
            else:
                self._alert("droit_insuffisant", res.get("sheet") or op.get("name") or op.get("old"))
        elif reason == "feuille_supprimee":
            self._alert("feuille_supprimee", res.get("sheet") or op.get("sheet"), res.get("cell"))
        elif reason == "nom":
            self._alert("nom_existant", res.get("name"))

    # -- état effectif : base + modifications en attente
    def _eff(self):
        base = self.store["base"]
        sheets = {n: dict(c) for n, c in base["sheets"].items()}
        rights = {n: dict(r) for n, r in base["rights"].items()}
        for e in self.store["outbox"]:
            if e["kind"] == "op" and not e["withdrawn"]:
                self._overlay(e["op"], sheets, rights)
        return sheets, rights

    def _put(self, sheets, sheet, cells, author):
        if sheet not in sheets:
            return
        for ref, content, literal, tz in cells:
            sheets[sheet][ref] = {"content": content, "literal": bool(literal) and content is not None,
                                  "tz": tz, "author": author, "version": None, "conflict": None}

    def _overlay(self, op, sheets, rights):
        a = op["action"]
        owner = self.store["base"]["owner"]
        if a == "set" or (a == "resolve" and op["use_discarded"]):
            self._put(sheets, op["sheet"], [(op["ref"], op["content"], op["literal"], op["tz"])], op["author"])
        elif a in ("set_many", "restore"):
            self._put(sheets, op["sheet"], op["cells"], op["author"])
        elif a == "add_sheet":
            n = op["name"]
            sheets[n] = {}
            r = {owner: W}
            if self.name != owner:
                r[self.name] = W
            rights[n] = r
        elif a == "create_sheet":
            n = op["name"]
            sheets[n] = {}
            rights[n] = dict(op["rights"])
            self._put(sheets, n, op["cells"], op["author"])
        elif a == "delete_sheet":
            sheets.pop(op["name"], None)
            rights.pop(op["name"], None)
        elif a == "rename":
            old, new = op["old"], op["new"]
            if old in sheets:
                renamed = {(new if n == old else n): c for n, c in sheets.items()}
                for cells in renamed.values():
                    for ref, rec in list(cells.items()):
                        if rec["literal"] or rec["content"] is None or not rec["content"].startswith("="):
                            continue
                        newc = rewrite_sheet_refs(rec["content"], old, new)
                        if newc != rec["content"]:
                            cells[ref] = dict(rec, content=newc)
                sheets.clear()
                sheets.update(renamed)
                rights[new] = rights.pop(old, {})

    def _view(self):
        sheets, rights = self._eff()
        if self.viewing is not None:
            e = self.viewing
            sheets[e["sheet"]] = {ref: {"content": c, "literal": l, "tz": t, "author": None,
                                        "version": None, "conflict": None}
                                  for ref, (c, l, t) in e["snap"].items()}
        return sheets, rights

    def _book(self, sheets):
        return Book(sheets, self.tz, self.clock.now())

    def _lvl(self, rights, sheet):
        return rights.get(sheet, {}).get(self.name)

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    # -- validation, inverse, soumission
    def _valid(self, a_, sheets, rights):
        a = a_["action"]
        if a == "set":
            s, ref = a_["sheet"], a_["ref"]
            if s not in sheets:
                return False
            if self._lvl(rights, s) != W:
                self._alert("droit_insuffisant", s, ref)
                return False
            prev = sheets[s].get(ref)
            pc = prev["content"] if prev else None
            if pc == a_["content"] and (a_["content"] is None or prev["literal"] == a_["literal"]):
                return False
            return True
        if a in ("set_many", "restore"):
            s = a_["sheet"]
            if s not in sheets:
                return False
            if self._lvl(rights, s) != W:
                self._alert("droit_insuffisant", s)
                return False
            if a == "restore":
                return True
            for ref, c, l, t in a_["cells"]:
                prev = sheets[s].get(ref)
                pc = prev["content"] if prev else None
                if not (pc == c and (c is None or prev["literal"] == l)):
                    return True
            return False
        if a == "resolve":
            s, ref = a_["sheet"], a_["ref"]
            if s not in sheets:
                return False
            if self._lvl(rights, s) != W:
                self._alert("droit_insuffisant", s, ref)
                return False
            return True
        if a == "add_sheet":
            n = a_["name"]
            if n.lower() in {x.lower() for x in sheets}:
                self._alert("nom_existant", n)
                return False
            return True
        if a == "delete_sheet":
            n = a_["name"]
            if n not in sheets:
                return False
            if self._lvl(rights, n) != W:
                self._alert("droit_insuffisant", n)
                return False
            return len(sheets) > 1
        if a == "create_sheet":
            return a_["name"] not in sheets
        if a == "rename":
            old, new = a_["old"], a_["new"]
            if old not in sheets or new == old:
                return False
            if self._lvl(rights, old) != W:
                self._alert("droit_insuffisant", old)
                return False
            if new.lower() in {x.lower() for x in sheets if x != old}:
                self._alert("nom_existant", new)
                return False
            return True
        return False

    def _inverse(self, a_, sheets, rights):
        a = a_["action"]
        if a in ("set", "resolve"):
            if a == "resolve" and not a_["use_discarded"]:
                return None
            s, ref = a_["sheet"], a_["ref"]
            prev = sheets.get(s, {}).get(ref)
            return {"action": "set", "sheet": s, "ref": ref,
                    "content": prev["content"] if prev else None,
                    "literal": prev["literal"] if prev else False,
                    "tz": prev["tz"] if prev else self.tz}
        if a in ("set_many", "restore"):
            s = a_["sheet"]
            cells = []
            for ref, *_ in a_["cells"]:
                prev = sheets.get(s, {}).get(ref)
                cells.append((ref, prev["content"] if prev else None,
                              prev["literal"] if prev else False, prev["tz"] if prev else self.tz))
            return {"action": "set_many", "sheet": s, "cells": cells}
        if a == "add_sheet":
            return {"action": "delete_sheet", "name": a_["name"]}
        if a == "delete_sheet":
            n = a_["name"]
            cells = [(ref, r["content"], r["literal"], r["tz"]) for ref, r in sheets.get(n, {}).items()
                     if r["content"] is not None]
            return {"action": "create_sheet", "name": n, "cells": cells, "rights": dict(rights.get(n, {}))}
        if a == "rename":
            return {"action": "rename", "old": a_["new"], "new": a_["old"]}
        return None

    def _base_version(self, sheet, ref):
        """Version de la cellule telle que la copie l'a reçue du serveur (0 si jamais reçue)."""
        rec = self.store["base"]["sheets"].get(sheet, {}).get(ref)
        if rec is None or rec["version"] is None:
            return 0
        return rec["version"]

    def _submit(self, action, undoable=True, redo=False):
        if self.viewing is not None:
            return None
        if action["action"] == "set":
            action = dict(action, base=self._base_version(action["sheet"], action["ref"]))
        sheets, rights = self._eff()
        if not self._valid(action, sheets, rights):
            return None
        inv = self._inverse(action, sheets, rights)
        op = dict(action, id=self._new_id(), author=self.name, ts=self.clock.now())
        entry = {"id": op["id"], "kind": "op", "op": op, "withdrawn": False}
        self.store["outbox"].append(entry)
        self._send_entry(entry)
        if undoable:
            self.undo_stack.append({"forward": action, "inverse": inv, "op_id": op["id"]})
            if not redo:
                self.redo_stack.clear()
        return op["id"]

    def _pending(self, op_id):
        return any(e["id"] == op_id and e["kind"] == "op" and not e["withdrawn"]
                   for e in self.store["outbox"])

    def _withdraw(self, op_id):
        for e in self.store["outbox"]:
            if e["id"] == op_id:
                e["withdrawn"] = True
        wid = self._new_id()
        entry = {"id": wid, "kind": "wd",
                 "op": {"id": wid, "action": "withdraw", "op_id": op_id, "author": self.name,
                        "ts": self.clock.now()},
                 "withdrawn": False}
        self.store["outbox"].append(entry)
        self._send_entry(entry)

    # -- saisie
    def set_cell(self, ref, text, sheet=None):
        self._submit({"action": "set", "sheet": sheet or self.active, "ref": ref.upper(),
                      "content": str(text), "literal": False, "tz": self.tz})

    def clear(self, ref, sheet=None):
        self._submit({"action": "set", "sheet": sheet or self.active, "ref": ref.upper(),
                      "content": None, "literal": False, "tz": self.tz})

    def content(self, ref, sheet=None):
        sheets, _ = self._view()
        rec = sheets.get(sheet or self.active, {}).get(ref.upper())
        return rec["content"] if rec else None

    def value(self, ref, sheet=None):
        sheet = sheet or self.active
        ref = ref.upper()
        sheets, _ = self._view()
        rec = sheets.get(sheet, {}).get(ref)
        if rec is None or rec["content"] is None:
            return None
        c = rec["content"]
        if not rec["literal"] and not c.startswith("=") and NAIVE_DT_RE.fullmatch(c) \
                and rec["tz"] == self.tz and is_gap(datetime.fromisoformat(c.replace("T", " ")), self.tz):
            return c
        return display_value(self._book(sheets).top(sheet, ref), self.tz)

    def error(self, ref, sheet=None):
        sheet = sheet or self.active
        sheets, _ = self._view()
        v = self._book(sheets).top(sheet, ref.upper())
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        self.tz = tz

    # -- feuilles et droits
    def sheets(self):
        return list(self._eff()[0].keys())

    def activate(self, name):
        if name in self._eff()[0]:
            self.active = name

    def add_sheet(self, name):
        self._submit({"action": "add_sheet", "name": name})

    def delete_sheet(self, name):
        self._submit({"action": "delete_sheet", "name": name})

    def rename_sheet(self, old, new):
        self._submit({"action": "rename", "old": old, "new": new})

    def right(self, person, sheet):
        return self._eff()[1].get(sheet, {}).get(person)

    def set_right(self, person, sheet, level):
        owner = self.store["base"]["owner"]
        if self.viewing is not None or self.name != owner:
            return
        if not self.net.online.get(self.name, True):
            return
        sheets, _ = self._eff()
        if sheet not in sheets or person == owner or level not in (W, R):
            return
        op = {"action": "set_right", "id": self._new_id(), "author": self.name,
              "ts": self.clock.now(), "sheet": sheet, "person": person, "level": level}
        self.net.send(self.name, SERVER, {"type": "op", "op": op})

    # -- alertes, connexion, présence
    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self.net.online.get(self.name, True) else "hors ligne"

    def pending_count(self):
        return sum(1 for e in self.store["outbox"] if e["kind"] == "op" and not e["withdrawn"])

    def select(self, ref, sheet=None):
        if not self.net.online.get(self.name, True):
            return
        self.net.send(self.name, SERVER, {"type": "presence", "who": self.name,
                                          "sheet": sheet or self.active, "ref": ref.upper()})

    def presence(self):
        if not self.net.online.get(self.name, True):
            return {}
        return {k: v for k, v in self.store["base"]["presence"].items() if k != self.name}

    # -- conflits
    def conflict(self, ref, sheet=None):
        rec = self.store["base"]["sheets"].get(sheet or self.active, {}).get(ref.upper())
        if not rec or not rec["conflict"]:
            return None
        return Conflict(rec["conflict"]["content"], rec["conflict"]["by"])

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sheet = sheet or self.active
        ref = ref.upper()
        rec = self.store["base"]["sheets"].get(sheet, {}).get(ref)
        if not rec or not rec["conflict"] or self.viewing is not None:
            return
        if self.right(self.name, sheet) != W:
            self._alert("droit_insuffisant", sheet, ref)
            return
        if use_discarded:
            cf = rec["conflict"]
            self._submit({"action": "resolve", "sheet": sheet, "ref": ref, "use_discarded": True,
                          "content": cf["content"], "literal": cf["literal"], "tz": cf["tz"]})
        else:
            self._submit({"action": "resolve", "sheet": sheet, "ref": ref, "use_discarded": False,
                          "content": None, "literal": False, "tz": self.tz}, undoable=False)

    # -- annulation / rétablissement
    def undo(self):
        if self.viewing is not None or not self.undo_stack:
            return
        e = self.undo_stack.pop()
        if self._pending(e["op_id"]) and e["forward"]["action"] in WITHDRAWABLE:
            self._withdraw(e["op_id"])
            self.redo_stack.append(e)
            return
        fwd = e["forward"]
        if fwd["action"] == "set":
            cur = self.store["base"]["sheets"].get(fwd["sheet"], {}).get(fwd["ref"])
            if cur is not None and cur["author"] != self.name:
                self._alert("annulation_impossible", fwd["sheet"], fwd["ref"])
                return
        if e["inverse"] is None:
            return
        self._submit(e["inverse"], undoable=False)
        self.redo_stack.append(e)

    def redo(self):
        if self.viewing is not None or not self.redo_stack:
            return
        e = self.redo_stack.pop()
        self._submit(e["forward"], undoable=True, redo=True)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz)

    # -- historique
    def history(self, sheet=None):
        sheet = sheet or self.active
        h = [e for e in self.store["base"]["history"] if e["sheet"] == sheet]
        h.sort(key=lambda e: (e["ts"], e["id"]), reverse=True)
        return [Version(e, self.tz) for e in h]

    def _entry_by_id(self, vid):
        return next((e for e in self.store["base"]["history"] if e["id"] == vid), None)

    def open_version(self, vid):
        e = self._entry_by_id(vid)
        if e is not None:
            self.viewing = e

    def close_version(self):
        self.viewing = None

    def restore_version(self, vid):
        e = self._entry_by_id(vid)
        if e is None:
            return
        name = next((n for n, u in self.store["base"]["uids"].items() if u == e["uid"]), None)
        if name is None:
            return
        sheets, _ = self._eff()
        refs = set(e["snap"]) | set(sheets.get(name, {}))
        cells = []
        for ref in sorted(refs):
            c, l, t = e["snap"].get(ref, (None, False, self.tz))
            cells.append((ref, c, l, t))
        self._submit({"action": "restore", "entry": vid, "sheet": name, "cells": cells})

    # -- CSV
    def export_csv(self):
        sheets, _ = self._view()
        cells = sheets.get(self.active, {})
        filled = [ref for ref, r in cells.items() if r["content"] is not None]
        if not filled:
            return b""
        book = self._book(sheets)
        maxc = max(split_ref(r)[0] for r in filled)
        maxr = max(split_ref(r)[1] for r in filled)
        rows = []
        for row in range(1, maxr + 1):
            fields = []
            nonempty = False
            for col in range(1, maxc + 1):
                ref = make_ref(col, row)
                if ref in cells and cells[ref]["content"] is not None:
                    nonempty = True
                fields.append(export_value(book.top(self.active, ref), self.tz))
            if nonempty:
                rows.append(fields)
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(rows)
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.viewing is not None:
            return
        sheet = self.active
        rows, bad = csv_parse(data)
        if bad is not None:
            self._alert("csv_invalide", sheet, None, bad)
            return
        sheets, rights = self._eff()
        if sheet not in sheets:
            return
        if self._lvl(rights, sheet) != W:
            self._alert("droit_insuffisant", sheet)
            return
        cells = []
        for r, row in enumerate(rows, 1):
            for c, field in enumerate(row, 1):
                content = field if field != "" else None
                cells.append((make_ref(c, r), content, field.startswith("="), self.tz))
        self._submit({"action": "set_many", "sheet": sheet, "cells": cells, "kind": "modification"})
