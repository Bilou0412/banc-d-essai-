"""Classeur collaboratif hors ligne — couche code (green, tour 1). Partie 1 : noyau."""
import csv
import io
import re
import sys
import uuid
from collections import deque
from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

sys.setrecursionlimit(200000)

UTC = timezone.utc
W = "écriture"
R = "lecture"
TYPE, DIV0, SYNTAX, CIRC, REF = "#TYPE!", "#DIV/0!", "#SYNTAXE!", "#CIRC!", "#REF!"
FMT = "%Y-%m-%d %H:%M"


@lru_cache(maxsize=None)
def _zone(name):
    return ZoneInfo(name)


class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


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


class Version:
    def __init__(self, id, author, timestamp, kind):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Date:
    __slots__ = ("d",)

    def __init__(self, d):
        self.d = d


class DT:
    __slots__ = ("instant", "tz", "shown")

    def __init__(self, instant, tz=None, shown=None):
        self.instant = instant
        self.tz = tz
        self.shown = shown


class _Range:
    def __init__(self, values):
        self.values = values


class _Syn(Exception):
    pass


# ---------------------------------------------------------------- colonnes

def _c2n(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _n2c(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------- analyseur

_TOK = re.compile(r"""
    (?P<num>\d+(?:\.\d+)?)
  | (?P<ref>(?:(?P<sheet>[^\W\d]\w*)!)?\$?(?P<col>[A-Z]{1,3})\$?(?P<row>\d+)(?![\w(]))
  | (?P<func>[^\W\d]\w*)(?=\()
  | (?P<op>[-+*/(),:])
""", re.X)


def _tokenize(src):
    toks, pos = [], 0
    while True:
        while pos < len(src) and src[pos].isspace():
            pos += 1
        if pos >= len(src):
            return toks
        m = _TOK.match(src, pos)
        if not m or m.end() == pos:
            raise _Syn()
        if m.group("num"):
            toks.append(("num", m.group("num")))
        elif m.group("ref"):
            toks.append(("ref", m.group("sheet"), m.group("col"), int(m.group("row"))))
        elif m.group("func"):
            toks.append(("func", m.group("func").upper()))
        else:
            toks.append(("op", m.group("op")))
        pos = m.end()


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise _Syn()
        self.i += 1
        return tok

    def is_op(self, v):
        tok = self.peek()
        return tok is not None and tok[0] == "op" and tok[1] == v

    def expect_op(self, v):
        if not self.is_op(v):
            raise _Syn()
        self.i += 1

    def expr(self):
        node = self.term()
        while self.is_op("+") or self.is_op("-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.is_op("*") or self.is_op("/"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.is_op("-"):
            self.take()
            return ("neg", self.unary())
        return self.atom()

    def atom(self):
        tok = self.take()
        if tok[0] == "num":
            return ("num", float(tok[1]) if "." in tok[1] else int(tok[1]))
        if tok[0] == "ref":
            if self.is_op(":"):
                self.take()
                t2 = self.take()
                if t2[0] != "ref" or (t2[1] is not None and t2[1] != tok[1]):
                    raise _Syn()
                return ("range", tok[1], tok[2], tok[3], t2[2], t2[3])
            return ("ref", tok[1], tok[2], tok[3])
        if tok[0] == "func":
            self.expect_op("(")
            args = []
            if not self.is_op(")"):
                args.append(self.expr())
                while self.is_op(","):
                    self.take()
                    args.append(self.expr())
            self.expect_op(")")
            name = tok[1]
            if name == "MAINTENANT" and args:
                raise _Syn()
            if name == "SOMME" and not args:
                raise _Syn()
            if name not in ("SOMME", "MAINTENANT"):
                raise _Syn()
            return ("call", name, args)
        if tok == ("op", "("):
            node = self.expr()
            self.expect_op(")")
            return node
        raise _Syn()


def _parse(content):
    toks = _tokenize(content[1:])
    if not toks:
        raise _Syn()
    p = _Parser(toks)
    node = p.expr()
    if p.i != len(toks):
        raise _Syn()
    return node


_parse_c = lru_cache(maxsize=None)(_parse)

# ---------------------------------------------------------------- valeurs typées

_INT = re.compile(r"-?\d+")
_FLT = re.compile(r"-?\d+\.\d+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DTM = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?")


def _typed(content, tz):
    if _INT.fullmatch(content):
        return int(content)
    if _FLT.fullmatch(content):
        return float(content)
    if _DATE.fullmatch(content):
        return Date(date.fromisoformat(content))
    if _DTM.fullmatch(content):
        naive = datetime.fromisoformat(content)
        if naive.tzinfo is not None:
            return DT(naive.astimezone(UTC))
        z = _zone(tz)
        inst = naive.replace(tzinfo=z).astimezone(UTC)
        exists = inst.astimezone(z).replace(tzinfo=None) == naive
        return DT(inst, tz, None if exists else naive.strftime(FMT))
    return content


def _pick(errs):
    for e in errs:
        if e.code == CIRC:
            return e
    return errs[0]


def _arith(op, a, b):
    errs = [x for x in (a, b) if isinstance(x, Err)]
    if errs:
        return _pick(errs)
    if isinstance(a, _Range) or isinstance(b, _Range):
        return Err(TYPE)
    a = 0 if a is None else a
    b = 0 if b is None else b
    if isinstance(a, (str, DT, Date)) or isinstance(b, (str, DT, Date)):
        if op == "-" and isinstance(a, DT) and isinstance(b, DT):
            return (a.instant - b.instant).total_seconds() / 86400
        if op == "-" and isinstance(a, Date) and isinstance(b, Date):
            return (a.d - b.d).days
        return Err(TYPE)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        return Err(DIV0)
    return a / b


# ---------------------------------------------------------------- évaluation

class _Ev:
    def __init__(self, st, now, tz):
        self.st = st
        self.now = now
        self.tz = tz
        self.memo = {}
        self.stack = set()

    def cell(self, sid, ref):
        key = (sid, ref)
        if key in self.stack:
            return Err(CIRC)
        if key in self.memo:
            return self.memo[key]
        sh = self.st["sheets"].get(sid)
        if sh is None or sh["deleted"]:
            return None
        c = sh["cells"].get(ref)
        if c is None or c[0] is None:
            return None
        content, tz, lit = c[0], c[1], c[2]
        if lit:
            r = content
        elif content.startswith("="):
            try:
                ast = _parse_c(content)
            except _Syn:
                r = Err(SYNTAX)
            else:
                self.stack.add(key)
                try:
                    r = self.ev(ast, sid)
                finally:
                    self.stack.discard(key)
                if r is None:
                    r = 0
        else:
            r = _typed(content, tz)
        self.memo[key] = r
        return r

    def sheet_id(self, name, sid):
        if name is None:
            return sid
        for s in self.st["order"]:
            sh = self.st["sheets"][s]
            if not sh["deleted"] and sh["name"] == name:
                return s
        return Err(REF)

    def ev(self, node, sid):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            s2 = self.sheet_id(node[1], sid)
            if isinstance(s2, Err):
                return s2
            return self.cell(s2, node[2] + str(node[3]))
        if k == "range":
            s2 = self.sheet_id(node[1], sid)
            if isinstance(s2, Err):
                return s2
            c1, c2 = sorted((_c2n(node[2]), _c2n(node[4])))
            r1, r2 = sorted((node[3], node[5]))
            vals = [self.cell(s2, _n2c(c) + str(r)) for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)]
            return _Range(vals)
        if k == "neg":
            v = self.ev(node[1], sid)
            if isinstance(v, Err):
                return v
            if isinstance(v, _Range):
                return Err(TYPE)
            if v is None:
                return 0
            if isinstance(v, (int, float)):
                return -v
            return Err(TYPE)
        if k == "bin":
            return _arith(node[1], self.ev(node[2], sid), self.ev(node[3], sid))
        if k == "call":
            if node[1] == "MAINTENANT":
                return DT(self.now)
            total = 0
            errs = []
            for a in node[2]:
                v = self.ev(a, sid)
                for x in (v.values if isinstance(v, _Range) else [v]):
                    if isinstance(x, Err):
                        errs.append(x)
                    elif isinstance(x, (int, float)):
                        total += x
            if errs:
                return _pick(errs)
            return total
        raise _Syn()


def _show(r, tzname):
    if r is None:
        return None
    if isinstance(r, Err):
        return r.code
    if isinstance(r, DT):
        if r.shown is not None and r.tz == tzname:
            return r.shown
        return r.instant.astimezone(_zone(tzname)).strftime(FMT)
    if isinstance(r, Date):
        return r.d.isoformat()
    return r


def _export(r, tzname):
    if isinstance(r, DT):
        return r.instant.astimezone(_zone(tzname)).isoformat()
    if isinstance(r, float) and r.is_integer():
        return str(int(r))
    v = _show(r, tzname)
    return "" if v is None else str(v)


# ---------------------------------------------------------------- états

def _empty_base():
    return {"owner": None, "order": [], "sheets": {}, "versions": [], "presence": {}}


def _clone_state(st):
    return {
        "owner": st["owner"],
        "order": list(st["order"]),
        "sheets": {
            sid: {"name": s["name"], "deleted": s["deleted"], "rights": dict(s["rights"]),
                  "cells": dict(s["cells"]), "conflicts": dict(s["conflicts"])}
            for sid, s in st["sheets"].items()
        },
    }


def _cell_of(st, sid, ref):
    sh = st["sheets"].get(sid)
    return sh["cells"].get(ref) if sh else None


def _rename_in_state(st, sid, new):
    old = st["sheets"][sid]["name"]
    st["sheets"][sid]["name"] = new
    pat = re.compile(r"(?<!\w)" + re.escape(old) + "!")
    for s in st["sheets"].values():
        for ref, (c, tz, lit, ver) in list(s["cells"].items()):
            if c and not lit and c.startswith("="):
                nc = pat.sub(lambda m: new + "!", c)
                if nc != c:
                    s["cells"][ref] = (nc, tz, lit, ver)


def _apply_local(st, ch, author):
    t = ch["t"]
    if t == "noop":
        return
    if t == "add_sheet":
        if ch["sid"] not in st["sheets"]:
            st["sheets"][ch["sid"]] = {"name": ch["name"], "deleted": False, "rights": {author: W},
                                       "cells": {}, "conflicts": {}}
            st["order"].append(ch["sid"])
        return
    sh = st["sheets"].get(ch["sid"])
    if sh is None:
        return
    if t == "delete_sheet":
        sh["deleted"] = True
    elif t == "undelete_sheet":
        sh["deleted"] = False
    elif t == "rename_sheet":
        _rename_in_state(st, ch["sid"], ch["name"])
    elif t == "cell":
        cur = sh["cells"].get(ch["ref"])
        ver = cur[3] if cur else 0
        sh["cells"][ch["ref"]] = (ch["content"], ch["tz"], ch["lit"], ver)
        sh["conflicts"].pop(ch["ref"], None)
    elif t == "resolve":
        conf = sh["conflicts"].pop(ch["ref"], None)
        if conf and ch["mode"] == "use":
            cur = sh["cells"].get(ch["ref"])
            ver = cur[3] if cur else 0
            sh["cells"][ch["ref"]] = (conf[0], conf[1], False, ver)


# ---------------------------------------------------------------- CSV

class _CsvErr(Exception):
    def __init__(self, line):
        self.line = line


def _parse_csv(text):
    rows, row, field = [], [], []
    i, n, line, rec_line = 0, len(text), 1, 1
    inq = False
    quoted = False
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
        if ch == '"' and not field and not quoted:
            inq = True
            quoted = True
            i += 1
            continue
        if ch == ",":
            row.append("".join(field))
            field = []
            quoted = False
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field, quoted = [], [], False
            line += 1
            rec_line = line
            i += 1
            continue
        field.append(ch)
        i += 1
    if inq:
        raise _CsvErr(rec_line)
    if row or field or quoted:
        row.append("".join(field))
        rows.append(row)
    return rows

class Network:
    def __init__(self):
        self.clients = {}
        self.server = None
        self.offline = set()
        self.queue = deque()

    def register(self, name, endpoint):
        self.clients[name] = endpoint
        if name == "server":
            self.server = endpoint
        elif self.server is not None and name not in self.offline:
            self.server.send_snapshot(name)

    def send(self, src, dst, payload):
        self.queue.append((src, dst, payload))

    def _deliver(self, src, dst, payload):
        if src in self.offline or dst in self.offline:
            return
        ep = self.clients.get(dst)
        if ep is not None:
            ep.receive(src, payload)

    def deliver_all(self):
        for name, ep in list(self.clients.items()):
            if name != "server" and name not in self.offline:
                ep.flush()
        while self.queue:
            self._deliver(*self.queue.popleft())

    def deliver_from(self, name):
        if name not in self.offline and name in self.clients and name != "server":
            self.clients[name].flush()
        items = list(self.queue)
        self.queue.clear()
        for m in items:
            if m[0] == name:
                self._deliver(*m)
            else:
                self.queue.append(m)

    def disconnect(self, name):
        self.offline.add(name)
        if self.server is not None:
            self.server.on_disconnect(name)

    def reconnect(self, name):
        self.offline.discard(name)
        if self.server is not None and name in self.clients:
            self.server.send_snapshot(name)


class Server:
    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        sid = uuid.uuid4().hex
        self.st = {"owner": owner, "order": [sid],
                   "sheets": {sid: {"name": "Feuille1", "deleted": False, "rights": {},
                                    "cells": {}, "conflicts": {}}}}
        self.versions = []
        self.seq = 0
        self.seen = {}
        self.presence = {}
        net.register("server", self)

    def _snapshot(self):
        snap = _clone_state(self.st)
        snap["versions"] = list(self.versions)
        snap["presence"] = dict(self.presence)
        return snap

    def send_snapshot(self, name):
        self.net.send("server", name, ("snapshot", self._snapshot()))

    def _broadcast(self):
        snap = self._snapshot()
        for name in list(self.net.clients):
            if name != "server" and name not in self.net.offline:
                self.net.send("server", name, ("snapshot", snap))

    def on_disconnect(self, name):
        self.presence.pop(name, None)
        self._broadcast()

    def receive(self, src, payload):
        kind = payload[0]
        if kind == "op":
            op = payload[1]
            if op["id"] in self.seen:
                self.net.send("server", src, ("ack", op["id"], self.seen[op["id"]]))
                return
            res = self._apply(op, src)
            self.seen[op["id"]] = res
            self.net.send("server", src, ("ack", op["id"], res))
            self._broadcast()
        elif kind == "right":
            _, sid, person, level = payload
            sh = self.st["sheets"].get(sid)
            if sh is not None and src == self.st["owner"] and person != self.st["owner"]:
                sh["rights"][person] = level
                self._broadcast()
        elif kind == "select":
            _, sheet_name, ref = payload
            self.presence[src] = (sheet_name, ref)
            self._broadcast()

    def _active(self):
        return [s for s in self.st["order"] if not self.st["sheets"][s]["deleted"]]

    def _writable(self, actor, sid):
        sh = self.st["sheets"].get(sid)
        return self.st["owner"] == actor or (sh is not None and sh["rights"].get(actor) == W)

    def _clash(self, name, exclude=None):
        return any(sh["name"].casefold() == name.casefold() and not sh["deleted"] and sid != exclude
                   for sid, sh in self.st["sheets"].items())

    def _apply(self, op, actor):
        st = self.st
        sheets = st["sheets"]

        def fail(kind, sheet=None, cell=None):
            return {"ok": False, "alerts": [(kind, sheet, cell, None)] if kind else []}

        for ch in op["changes"]:
            t = ch["t"]
            if t == "add_sheet":
                if self._clash(ch["name"]):
                    return fail("nom_existant", ch["name"])
                continue
            sh = sheets.get(ch["sid"])
            if sh is None:
                return fail(None)
            if t == "undelete_sheet":
                if not sh["deleted"]:
                    continue
                if not self._writable(actor, ch["sid"]):
                    return fail("modification_rejetee", sh["name"])
                if self._clash(sh["name"], ch["sid"]):
                    return fail("nom_existant", sh["name"])
                continue
            if sh["deleted"]:
                return fail("feuille_supprimee", sh["name"])
            if not self._writable(actor, ch["sid"]):
                return fail("modification_rejetee", sh["name"], ch.get("ref"))
            if t == "rename_sheet" and self._clash(ch["name"], ch["sid"]):
                return fail("nom_existant", ch["name"])
            if t == "delete_sheet" and len(self._active()) <= 1:
                return fail(None)

        changed = False
        first = None
        for ch in op["changes"]:
            t = ch["t"]
            sid = ch.get("sid")
            if t == "add_sheet":
                sheets[sid] = {"name": ch["name"], "deleted": False, "rights": {actor: W},
                               "cells": {}, "conflicts": {}}
                st["order"].append(sid)
            elif t == "delete_sheet":
                sheets[sid]["deleted"] = True
            elif t == "undelete_sheet":
                sheets[sid]["deleted"] = False
            elif t == "rename_sheet":
                _rename_in_state(st, sid, ch["name"])
            elif t == "cell":
                sh = sheets[sid]
                ref = ch["ref"]
                cur = sh["cells"].get(ref)
                cc = cur[0] if cur else None
                cl = cur[2] if cur else False
                ver = cur[3] if cur else 0
                differs = ch["content"] != cc or ch["lit"] != cl
                if ch["base"] < ver:
                    if differs:
                        sh["conflicts"][ref] = (ch["content"], ch["tz"], actor)
                    continue
                sh["conflicts"].pop(ref, None)
                if differs:
                    sh["cells"][ref] = (ch["content"], ch["tz"], ch["lit"], ver + 1)
                    changed = True
                    first = first or sid
            elif t == "resolve":
                sh = sheets[sid]
                conf = sh["conflicts"].pop(ch["ref"], None)
                if conf and ch["mode"] == "use":
                    cur = sh["cells"].get(ch["ref"])
                    ver = cur[3] if cur else 0
                    sh["cells"][ch["ref"]] = (conf[0], conf[1], False, ver + 1)
                    changed = True
                    first = first or sid
        if changed:
            self.seq += 1
            kind = "restauration" if op.get("kind") == "restore" else "modification"
            self.versions.append({"id": self.seq, "sid": first, "author": actor,
                                  "created": op["created"], "kind": kind,
                                  "state": _clone_state(st)})
        return {"ok": True, "alerts": []}

class Client:
    def __init__(self, net, clock, name, tz="UTC"):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self._dev = {"base": None, "outbox": []}
        self._local = _empty_base()
        self._active = None
        self._undo = []
        self._redo = []
        self._alerts = []
        self._viewing = None
        net.register(name, self)

    # ---- état
    def _base(self):
        return self._dev["base"] or _empty_base()

    def _view(self):
        return self._viewing if self._viewing is not None else self._local

    def _rebuild(self):
        st = _clone_state(self._base())
        for op in self._dev["outbox"]:
            for ch in op["changes"]:
                _apply_local(st, ch, op["author"])
        self._local = st

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _expected(self, sid, ref):
        sh = self._base()["sheets"].get(sid)
        cell = sh["cells"].get(ref) if sh else None
        ver = cell[3] if cell else 0
        for op in self._dev["outbox"]:
            for ch in op["changes"]:
                if ch["t"] in ("cell", "resolve") and ch["sid"] == sid and ch["ref"] == ref:
                    ver += 1
        return ver

    def _writable(self, sid):
        st = self._local
        sh = st["sheets"].get(sid)
        if sh is None or sh["deleted"]:
            return False
        return st["owner"] == self.name or sh["rights"].get(self.name) == W

    def _sheet_name(self, sid):
        sh = self._view()["sheets"].get(sid)
        return sh["name"] if sh else None

    def _active_ids(self, st=None):
        st = st or self._view()
        return [s for s in st["order"] if not st["sheets"][s]["deleted"]]

    def _sid(self, sheet=None):
        st = self._view()
        active = self._active_ids(st)
        if sheet is None:
            if self._active in active:
                return self._active
            return active[0] if active else None
        for s in active:
            if st["sheets"][s]["name"] == sheet:
                return s
        return None

    def _clash(self, name, exclude=None):
        return any(sh["name"].casefold() == name.casefold() and not sh["deleted"] and sid != exclude
                   for sid, sh in self._local["sheets"].items())

    def _inverse(self, ch):
        t = ch["t"]
        sid = ch.get("sid")
        if t == "cell":
            c = _cell_of(self._local, sid, ch["ref"])
            return {"t": "cell", "sid": sid, "ref": ch["ref"],
                    "content": c[0] if c else None,
                    "tz": c[1] if c else self.tz,
                    "lit": c[2] if c else False}
        if t == "add_sheet":
            return {"t": "delete_sheet", "sid": sid}
        if t == "delete_sheet":
            return {"t": "undelete_sheet", "sid": sid}
        if t == "undelete_sheet":
            return {"t": "delete_sheet", "sid": sid}
        if t == "rename_sheet":
            return {"t": "rename_sheet", "sid": sid, "name": self._local["sheets"][sid]["name"]}
        return {"t": "noop"}

    def _act(self, changes, undoable=True, user=True, kind="edit"):
        built, inv, after = [], [], {}
        for ch in changes:
            ch = dict(ch)
            if ch["t"] in ("cell", "resolve"):
                ch["base"] = self._expected(ch["sid"], ch["ref"])
                after[(ch["sid"], ch["ref"])] = ch["base"] + 1
            built.append(ch)
            inv.append(self._inverse(ch))
        op = {"id": uuid.uuid4().hex, "author": self.name, "created": self.clock.now(),
              "kind": kind, "changes": built}
        self._dev["outbox"].append(op)
        for ch in built:
            _apply_local(self._local, ch, self.name)
        entry = {"op_id": op["id"], "fwd": [dict(c) for c in changes], "inv": inv, "after": after}
        if undoable:
            self._undo.append(entry)
        if user:
            self._redo.clear()
        return entry

    # ---- réseau
    def receive(self, src, payload):
        kind = payload[0]
        if kind == "snapshot":
            self._dev["base"] = payload[1]
            self._rebuild()
        elif kind == "ack":
            op_id, res = payload[1], payload[2]
            self._dev["outbox"][:] = [op for op in self._dev["outbox"] if op["id"] != op_id]
            for k, s, c, l in res["alerts"]:
                self._alerts.append(Alert(k, s, c, l))
            self._rebuild()

    def flush(self):
        for op in self._dev["outbox"]:
            self.net.send(self.name, "server", ("op", op))

    # ---- lecture
    def content(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        c = _cell_of(self._view(), sid, ref)
        return c[0] if c else None

    def _eval(self, ref, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        ev = _Ev(self._view(), self.clock.now(), self.tz)
        return ev.cell(sid, ref)

    def value(self, ref, sheet=None):
        return _show(self._eval(ref, sheet), self.tz)

    def error(self, ref, sheet=None):
        r = self._eval(ref, sheet)
        return r.code if isinstance(r, Err) else None

    def sheets(self):
        st = self._view()
        return [st["sheets"][s]["name"] for s in self._active_ids(st)]

    def right(self, person, sheet):
        st = self._view()
        sid = self._sid(sheet)
        if sid is None:
            return None
        if person == st["owner"]:
            return W
        return st["sheets"][sid]["rights"].get(person)

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        c = _cell_of(self._view(), sid, ref)
        sh = self._view()["sheets"][sid]
        cf = sh["conflicts"].get(ref)
        return Conflict(cf[0], cf[2]) if cf else None

    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "hors ligne" if self.name in self.net.offline else "en ligne"

    def pending_count(self):
        return len(self._dev["outbox"])

    def presence(self):
        if self.name in self.net.offline:
            return {}
        return {n: tuple(v) for n, v in self._base()["presence"].items() if n != self.name}

    def history(self, sheet=None):
        sid = self._sid(sheet)
        out = [v for v in self._base()["versions"] if v["sid"] == sid]
        out.sort(key=lambda v: (v["created"], v["id"]), reverse=True)
        zone = _zone(self.tz)
        return [Version(v["id"], v["author"], v["created"].astimezone(zone).strftime(FMT), v["kind"])
                for v in out]

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    # ---- écriture
    def set_timezone(self, tz):
        self.tz = tz

    def set_cell(self, ref, text, sheet=None):
        if self._viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if not self._writable(sid):
            self._alert("droit_insuffisant", self._sheet_name(sid), ref)
            return
        cur = _cell_of(self._local, sid, ref)
        cur_c = cur[0] if cur else None
        cur_lit = cur[2] if cur else False
        if text == cur_c and not cur_lit:
            return
        self._act([{"t": "cell", "sid": sid, "ref": ref, "content": text, "tz": self.tz, "lit": False}])

    def clear(self, ref, sheet=None):
        self.set_cell(ref, None, sheet)

    def import_csv(self, data):
        sid = self._sid(None)
        if sid is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", self._sheet_name(sid))
            return
        try:
            rows = _parse_csv(data.decode("utf-8-sig"))
        except _CsvErr as e:
            self._alert("csv_invalide", self._sheet_name(sid), None, e.line)
            return
        changes = []
        for i, row in enumerate(rows):
            for j, f in enumerate(row):
                ref = _n2c(j + 1) + str(i + 1)
                content = f if f != "" else None
                lit = content is not None and content.startswith("=")
                cur = _cell_of(self._local, sid, ref)
                cc = cur[0] if cur else None
                cl = cur[2] if cur else False
                if content == cc and lit == cl:
                    continue
                changes.append({"t": "cell", "sid": sid, "ref": ref, "content": content,
                                "tz": self.tz, "lit": lit})
        if changes:
            self._act(changes)

    def export_csv(self):
        sid = self._sid(None)
        if sid is None:
            return b""
        st = self._view()
        cells = [ref for ref, c in st["sheets"][sid]["cells"].items() if c[0] is not None]
        if not cells:
            return b""
        pos = []
        for ref in cells:
            m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
            pos.append((_c2n(m.group(1)), int(m.group(2))))
        maxc = max(c for c, _ in pos)
        rows = sorted({r for _, r in pos})
        ev = _Ev(st, self.clock.now(), self.tz)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in rows:
            w.writerow([_export(ev.cell(sid, _n2c(c) + str(r)), self.tz) for c in range(1, maxc + 1)])
        return buf.getvalue().encode("utf-8")

    def add_sheet(self, name):
        if self._clash(name):
            self._alert("nom_existant", name)
            return
        self._act([{"t": "add_sheet", "sid": uuid.uuid4().hex, "name": name}])

    def delete_sheet(self, name):
        sid = self._sid(name)
        if sid is None:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", name)
            return
        if len(self._active_ids()) <= 1:
            return
        self._act([{"t": "delete_sheet", "sid": sid}])

    def rename_sheet(self, old, new):
        sid = self._sid(old)
        if sid is None or old == new:
            return
        if not self._writable(sid):
            self._alert("droit_insuffisant", old)
            return
        if self._clash(new, exclude=sid):
            self._alert("nom_existant", new)
            return
        self._act([{"t": "rename_sheet", "sid": sid, "name": new}])

    def activate(self, name):
        sid = self._sid(name)
        if sid is not None:
            self._active = sid

    def set_right(self, person, sheet, level):
        sid = self._sid(sheet)
        if sid is None:
            return
        st = self._local
        if self.name != st["owner"] or person == st["owner"]:
            return
        if self.name in self.net.offline:
            return
        if self.right(person, sheet) == level:
            return
        self.net.send(self.name, "server", ("right", sid, person, level))

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None or self.name in self.net.offline:
            return
        self.net.send(self.name, "server", ("select", self._sheet_name(sid), ref.upper()))

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if not self._writable(sid):
            self._alert("droit_insuffisant", self._sheet_name(sid), ref)
            return
        if ref not in self._local["sheets"][sid]["conflicts"]:
            return
        self._act([{"t": "resolve", "sid": sid, "ref": ref,
                    "mode": "use" if use_discarded else "keep"}], undoable=False)

    # ---- annulation
    def undo(self):
        if not self._undo:
            return
        e = self._undo.pop()
        if any(op["id"] == e["op_id"] for op in self._dev["outbox"]):
            self._dev["outbox"][:] = [op for op in self._dev["outbox"] if op["id"] != e["op_id"]]
            self._rebuild()
            self._redo.append(e["fwd"])
            return
        sids = {c["sid"] for c in e["fwd"] if c.get("sid")}
        for sid in sids:
            if not self._writable(sid):
                self._alert("droit_insuffisant", self._sheet_name(sid))
                return
        for (sid, ref), aft in e["after"].items():
            if self._expected(sid, ref) != aft:
                self._alert("annulation_impossible", self._sheet_name(sid), ref)
                return
        n = self._act(e["inv"], undoable=False, user=False)
        self._redo.append(n["inv"])

    def redo(self):
        if not self._redo:
            return
        changes = self._redo.pop()
        self._act(changes, undoable=True, user=False)

    # ---- versions
    def _find_version(self, vid):
        for v in self._base()["versions"]:
            if v["id"] == vid:
                return v
        return None

    def open_version(self, vid):
        v = self._find_version(vid)
        if v is not None:
            self._viewing = v["state"]

    def close_version(self):
        self._viewing = None

    def restore_version(self, vid):
        v = self._find_version(vid)
        if v is None:
            return
        sid = v["sid"]
        if not self._writable(sid):
            self._alert("droit_insuffisant", self._sheet_name(sid))
            return
        target = v["state"]["sheets"].get(sid)
        if target is None:
            return
        cur = self._local["sheets"][sid]
        changes = []
        if target["name"] != cur["name"]:
            changes.append({"t": "rename_sheet", "sid": sid, "name": target["name"]})
        for ref in set(cur["cells"]) | set(target["cells"]):
            tc = target["cells"].get(ref)
            cc = cur["cells"].get(ref)
            tcont = tc[0] if tc else None
            tlit = tc[2] if tc else False
            ccont = cc[0] if cc else None
            clit = cc[2] if cc else False
            if tcont == ccont and tlit == clit:
                continue
            changes.append({"t": "cell", "sid": sid, "ref": ref, "content": tcont,
                            "tz": tc[1] if tc else self.tz, "lit": tlit})
        if changes:
            self._act(changes, kind="restore")

    def reopen(self):
        c = Client(self.net, self.clock, self.name, self.tz)
        c._dev = self._dev
        c._rebuild()
        return c
