"""Classeur collaboratif hors ligne : formules, réseau simulé, fusion, fuseaux, CSV, historique."""
import csv
import io
import pickle
import re
from collections import deque
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = timezone.utc
W = "écriture"
R = "lecture"


@lru_cache(maxsize=None)
def zi(tz):
    return ZoneInfo(tz)


def fmt_dt(dt, tz):
    return dt.astimezone(zi(tz)).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ valeurs, erreurs

class Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


E_TYPE = Err("#TYPE!")
E_DIV = Err("#DIV/0!")
E_SYN = Err("#SYNTAXE!")
E_CIRC = Err("#CIRC!")
E_REF = Err("#REF!")

_INT = re.compile(r'^[+-]?\d+$')
_FLT = re.compile(r'^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$')
_DT_OFF = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$')
_DT_NAIVE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_CELL = re.compile(r'^([A-Za-z]+)(\d+)$')


def col2n(col):
    n = 0
    for ch in col.upper():
        n = n * 26 + ord(ch) - 64
    return n


def n2col(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = _CELL.match(ref)
    return col2n(m.group(1)), int(m.group(2))


def _isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _norm(x):
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        return int(x)
    return x


def parse_literal(text):
    s = text.strip()
    try:
        if _INT.match(s):
            return int(s)
        if _FLT.match(s):
            return float(s)
        if _DT_OFF.match(s):
            return datetime.fromisoformat(s).astimezone(UTC)
        if _DT_NAIVE.match(s):
            return datetime.fromisoformat(s).replace(tzinfo=UTC)
        if _DATE.match(s):
            return date.fromisoformat(s)
    except ValueError:
        pass
    return text


# ------------------------------------------------------------------ analyseur

class SyntaxErr(Exception):
    pass


_TOK = re.compile(
    r'\s*(?:(?P<sheet>\w+)!|(?P<num>\d+\.\d*|\.\d+|\d+)|(?P<func>[A-Za-z]+)(?=\s*\()'
    r'|(?P<ref>[A-Za-z]+\d+)|(?P<op>[-+*/(),;:]))')


def _tokenize(s):
    toks = []
    pos = 0
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m:
            if s[pos:].strip() == "":
                break
            raise SyntaxErr()
        kind = m.lastgroup
        toks.append((kind, m.group(kind)))
        pos = m.end()
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def expr(self):
        n = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.peek()[1]
            self.i += 1
            n = ("bin", op, n, self.term())
        return n

    def term(self):
        n = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.peek()[1]
            self.i += 1
            n = ("bin", op, n, self.unary())
        return n

    def unary(self):
        tok = self.peek()
        if tok == ("op", "-"):
            self.i += 1
            return ("neg", self.unary())
        if tok == ("op", "+"):
            self.i += 1
            return self.unary()
        return self.primary()

    def _refnode(self, sheet, ref):
        c, r = split_ref(ref)
        if self.peek() == ("op", ":"):
            self.i += 1
            t2 = self.peek()
            if not t2 or t2[0] != "ref":
                raise SyntaxErr()
            self.i += 1
            c2, r2 = split_ref(t2[1])
            return ("range", sheet, (c, r), (c2, r2))
        return ("ref", sheet, f"{n2col(c)}{r}")

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise SyntaxErr()
        kind, val = tok
        if kind == "num":
            self.i += 1
            return ("num", float(val) if "." in val else int(val))
        if kind == "sheet":
            self.i += 1
            t2 = self.peek()
            if not t2 or t2[0] != "ref":
                raise SyntaxErr()
            self.i += 1
            return self._refnode(val, t2[1])
        if kind == "ref":
            self.i += 1
            return self._refnode(None, val)
        if kind == "func":
            name = val.upper()
            self.i += 1
            if self.peek() != ("op", "("):
                raise SyntaxErr()
            self.i += 1
            args = []
            if self.peek() == ("op", ")"):
                self.i += 1
            else:
                while True:
                    args.append(self.expr())
                    t = self.peek()
                    if t in (("op", ","), ("op", ";")):
                        self.i += 1
                        continue
                    if t == ("op", ")"):
                        self.i += 1
                        break
                    raise SyntaxErr()
            if name == "MAINTENANT" and not args:
                return ("call", name, args)
            if name == "SOMME" and args:
                return ("call", name, args)
            raise SyntaxErr()
        if kind == "op" and val == "(":
            self.i += 1
            n = self.expr()
            if self.peek() != ("op", ")"):
                raise SyntaxErr()
            self.i += 1
            return n
        raise SyntaxErr()


_SYN = ("syntax",)
_PARSE_CACHE = {}


def parse_formula(text):
    node = _PARSE_CACHE.get(text)
    if node is None:
        try:
            toks = _tokenize(text[1:])
            p = _Parser(toks)
            node = p.expr()
            if p.i != len(toks):
                raise SyntaxErr()
        except SyntaxErr:
            node = _SYN
        _PARSE_CACHE[text] = node
    return node


def is_formula(cell):
    return cell[0].startswith("=") and not cell[1]


def _arith(op, a, b):
    na, nb = _isnum(a), _isnum(b)
    if op in "+-":
        if na and nb:
            return _norm(a + b if op == "+" else a - b)
        da, db = isinstance(a, datetime), isinstance(b, datetime)
        ua = isinstance(a, date) and not da
        ub = isinstance(b, date) and not db
        if da and db and op == "-":
            return _norm((a - b).total_seconds() / 86400)
        if ua and ub and op == "-":
            return _norm((a - b).days)
        if (da or ua) and nb:
            d = timedelta(days=b)
            return a + d if op == "+" else a - d
        if op == "+" and na and (db or ub):
            return b + timedelta(days=a)
        return E_TYPE
    if not (na and nb):
        return E_TYPE
    if op == "*":
        return _norm(a * b)
    if b == 0:
        return E_DIV
    return _norm(a / b)


# ------------------------------------------------------------------ moteur de recalcul

class Engine:
    """Graphe de dépendances entre cellules (sid, ref) et recalcul en ordre topologique."""

    def __init__(self, doc, clock):
        self.doc = doc
        self.clock = clock
        self.now = clock.now()
        self.deps = {}
        self.rdeps = {}
        self.nodes = {}
        self.val = {}
        self.volatile = set()

    def build(self):
        self.deps = {}
        self.rdeps = {}
        self.nodes = {}
        self.val = {}
        self.volatile = set()
        keys = [(sid, ref) for sid in self.doc.order for ref in self.doc.sheets[sid]["cells"]]
        for k in keys:
            self._setup(k)
        self._recalc(keys)

    def update(self, keys):
        ks = [k for k in keys if k[0] in self.doc.sheets]
        for k in ks:
            self._setup(k)
        self._recalc(ks)

    def refresh(self):
        if self.volatile and self.clock.now() != self.now:
            self._recalc(list(self.volatile))

    def get(self, key):
        return self.val.get(key)

    def _resolve(self, name, own):
        return own if name is None else self.doc.sid_of(name)

    def _setup(self, key):
        old = self.deps.pop(key, None)
        if old:
            for d in old:
                s = self.rdeps.get(d)
                if s is not None:
                    s.discard(key)
        self.volatile.discard(key)
        self.nodes.pop(key, None)
        sh = self.doc.sheets.get(key[0])
        cell = sh["cells"].get(key[1]) if sh else None
        deps = set()
        if cell is not None and is_formula(cell):
            node = parse_formula(cell[0])
            self.nodes[key] = node
            if node is not _SYN:
                self._collect(node, key, deps)
        for d in deps:
            self.rdeps.setdefault(d, set()).add(key)
        self.deps[key] = deps

    def _collect(self, n, key, deps):
        k = n[0]
        if k == "ref":
            s = self._resolve(n[1], key[0])
            if s is not None:
                deps.add((s, n[2]))
        elif k == "range":
            s = self._resolve(n[1], key[0])
            if s is not None:
                (c1, r1), (c2, r2) = n[2], n[3]
                for r in range(min(r1, r2), max(r1, r2) + 1):
                    for c in range(min(c1, c2), max(c1, c2) + 1):
                        deps.add((s, f"{n2col(c)}{r}"))
        elif k == "neg":
            self._collect(n[1], key, deps)
        elif k == "bin":
            self._collect(n[2], key, deps)
            self._collect(n[3], key, deps)
        elif k == "call":
            if n[1] == "MAINTENANT":
                self.volatile.add(key)
            for a in n[2]:
                self._collect(a, key, deps)

    def _recalc(self, keys):
        self.now = self.clock.now()
        affected = set()
        stack = list(keys)
        while stack:
            k = stack.pop()
            if k in affected:
                continue
            affected.add(k)
            stack.extend(self.rdeps.get(k, ()))
        indeg = {}
        for k in affected:
            indeg[k] = sum(1 for d in self.deps.get(k, ()) if d in affected)
        ready = [k for k, n in indeg.items() if n == 0]
        while ready:
            k = ready.pop()
            self.val[k] = self._eval_cell(k)
            for d in self.rdeps.get(k, ()):
                if d in indeg:
                    indeg[d] -= 1
                    if indeg[d] == 0:
                        ready.append(d)
        for k, n in indeg.items():
            if n > 0:
                self.val[k] = E_CIRC

    def _eval_cell(self, key):
        sid, ref = key
        sh = self.doc.sheets.get(sid)
        cell = sh["cells"].get(ref) if sh else None
        if cell is None:
            return None
        if is_formula(cell):
            node = self.nodes.get(key)
            if node is None or node is _SYN:
                return E_SYN
            return self._ev(node, sid)
        return parse_literal(cell[0])

    def _ev(self, n, sid):
        k = n[0]
        if k == "num":
            return n[1]
        if k == "ref":
            s = self._resolve(n[1], sid)
            if s is None:
                return E_REF
            v = self.val.get((s, n[2]))
            return 0 if v is None else v
        if k == "range":
            return E_TYPE
        if k == "neg":
            v = self._ev(n[1], sid)
            if isinstance(v, Err):
                return v
            return _norm(-v) if _isnum(v) else E_TYPE
        if k == "bin":
            a = self._ev(n[2], sid)
            if isinstance(a, Err):
                return a
            b = self._ev(n[3], sid)
            if isinstance(b, Err):
                return b
            return _arith(n[1], a, b)
        name, args = n[1], n[2]
        if name == "MAINTENANT":
            return self.now
        total = 0
        for a in args:
            if a[0] == "range":
                s = self._resolve(a[1], sid)
                if s is None:
                    return E_REF
                (c1, r1), (c2, r2) = a[2], a[3]
                for r in range(min(r1, r2), max(r1, r2) + 1):
                    for c in range(min(c1, c2), max(c1, c2) + 1):
                        v = self.val.get((s, f"{n2col(c)}{r}"))
                        if isinstance(v, Err):
                            return v
                        if _isnum(v):
                            total += v
            else:
                v = self._ev(a, sid)
                if isinstance(v, Err):
                    return v
                if not _isnum(v):
                    return E_TYPE
                total += v
        return _norm(total)


# ------------------------------------------------------------------ état répliqué

class Version:
    def __init__(self, id, sid, author, ts, kind, name, cells):
        self.id = id
        self.sid = sid
        self.author = author
        self.ts = ts
        self.kind = kind
        self.name = name
        self.cells = cells


class Doc:
    def __init__(self):
        self.sheets = {}
        self.order = []
        self.rights = {}
        self.conflicts = {}
        self.history = {}
        self.seq = 0
        self.owner = None

    def copy(self):
        d = Doc()
        d.sheets = {s: {"name": v["name"], "cells": dict(v["cells"])} for s, v in self.sheets.items()}
        d.order = list(self.order)
        d.rights = dict(self.rights)
        d.conflicts = dict(self.conflicts)
        d.history = self.history
        d.seq = self.seq
        d.owner = self.owner
        return d

    def sid_of(self, name, exclude=None):
        cf = name.casefold()
        for sid in self.order:
            if sid != exclude and self.sheets[sid]["name"].casefold() == cf:
                return sid
        return None

    def name_taken(self, name, exclude=None):
        return self.sid_of(name, exclude) is not None

    def _rename(self, sid, new):
        old = self.sheets[sid]["name"]
        self.sheets[sid]["name"] = new
        pat = re.compile(r'(?<!\w)' + re.escape(old) + r'(?=!)', re.I)
        for sh in self.sheets.values():
            cells = sh["cells"]
            for ref in list(cells):
                cell = cells[ref]
                if is_formula(cell):
                    t = pat.sub(lambda m: new, cell[0])
                    if t != cell[0]:
                        cells[ref] = (t, cell[1])

    def _drop_conflicts(self, sid):
        for k in [k for k in self.conflicts if k[0] == sid]:
            del self.conflicts[k]

    def _record(self, ev, sid):
        sh = self.sheets[sid]
        self.history.setdefault(sid, []).append(
            Version(ev["seq"], sid, ev["author"], ev["ts"], ev.get("kind", "modification"),
                    sh["name"], dict(sh["cells"])))

    def apply_event(self, ev, record=False):
        """Applique un événement ; rend (structure_modifiée, cellules_modifiées)."""
        t = ev["t"]
        changed = set()
        struct = False
        sid = ev.get("sid")
        if t == "init":
            self.owner = ev["owner"]
        elif t == "addsheet":
            if sid not in self.sheets and not self.name_taken(ev["name"]):
                self.sheets[sid] = {"name": ev["name"], "cells": {}}
                self.order.append(sid)
                self.rights[(ev["creator"], sid)] = W
                struct = True
        elif t == "delsheet":
            if sid in self.sheets:
                del self.sheets[sid]
                self.order.remove(sid)
                self._drop_conflicts(sid)
                struct = True
        elif t == "restoresheet":
            if sid not in self.sheets and not self.name_taken(ev["name"]):
                self.sheets[sid] = {"name": ev["name"], "cells": dict(ev["cells"])}
                self.order.insert(min(ev["index"], len(self.order)), sid)
                struct = True
        elif t == "rename":
            if sid in self.sheets and not self.name_taken(ev["new"], exclude=sid):
                self._rename(sid, ev["new"])
                struct = True
        elif t == "right":
            if ev["level"] is None:
                self.rights.pop((ev["person"], sid), None)
            else:
                self.rights[(ev["person"], sid)] = ev["level"]
        elif t == "cells":
            sh = self.sheets.get(sid)
            if sh is not None:
                cells = sh["cells"]
                for ref, cell in ev["changes"].items():
                    if cell is None:
                        cells.pop(ref, None)
                    else:
                        cells[ref] = cell
                    self.conflicts.pop((sid, ref), None)
                    changed.add((sid, ref))
                for ref, c in ev.get("conflicts", {}).items():
                    self.conflicts[(sid, ref)] = c
                if record and ev["changes"]:
                    self._record(ev, sid)
        elif t == "setsheet":
            sh = self.sheets.get(sid)
            if sh is not None:
                if ev["name"] != sh["name"] and not self.name_taken(ev["name"], exclude=sid):
                    self._rename(sid, ev["name"])
                sh["cells"] = dict(ev["cells"])
                self._drop_conflicts(sid)
                struct = True
                if record:
                    self._record(ev, sid)
        return struct, changed


def op_event(op, author):
    t = op["t"]
    if t == "cells":
        return {"t": "cells", "sid": op["sid"], "changes": op["changes"], "conflicts": {},
                "author": author, "ts": op["ts"], "kind": op.get("kind", "modification")}
    if t == "addsheet":
        return {"t": "addsheet", "sid": op["sid"], "name": op["name"], "creator": author}
    if t == "delsheet":
        return {"t": "delsheet", "sid": op["sid"]}
    if t == "restoresheet":
        return {"t": "restoresheet", "sid": op["sid"], "name": op["name"], "cells": op["cells"],
                "index": op["index"]}
    if t == "rename":
        return {"t": "rename", "sid": op["sid"], "new": op["new"]}
    if t == "setsheet":
        return {"t": "setsheet", "sid": op["sid"], "name": op["name"], "cells": op["cells"],
                "author": author, "ts": op["ts"], "kind": op.get("kind", "modification")}
    return None


# ------------------------------------------------------------------ temps et réseau

class Clock:
    def __init__(self, start):
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


class Network:
    def __init__(self):
        self.nodes = {}
        self.queue = deque()
        self.down = set()

    def register(self, name, node):
        self.nodes[name] = node

    def send(self, src, dst, payload):
        if src in self.down or dst in self.down:
            return
        self.queue.append((src, dst, payload))

    def _deliver(self, m):
        src, dst, payload = m
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, payload)

    def deliver_all(self):
        while self.queue:
            self._deliver(self.queue.popleft())

    def deliver_from(self, name):
        batch = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for m in batch:
            self._deliver(m)

    def disconnect(self, name):
        self.down.add(name)
        self.queue = deque(m for m in self.queue if m[0] != name and m[1] != name)
        srv = self.nodes.get("server")
        if srv is not None and name != "server":
            srv.peer_down(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "net_state"):
            node.net_state(False)

    def reconnect(self, name):
        if name not in self.down:
            return
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None and hasattr(node, "net_state"):
            node.net_state(True)


# ------------------------------------------------------------------ serveur

class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.doc = Doc()
        self.log = []
        self.mods = {}
        self.results = {}
        self.online = set()
        self.presence = {}
        net.register("server", self)
        self._emit({"t": "init", "owner": owner})
        self._emit({"t": "addsheet", "sid": "s0", "name": "Feuille1", "creator": owner})

    def _can_write(self, client, sid):
        return client == self.doc.owner or self.doc.rights.get((client, sid)) == W

    def _bcast_presence(self):
        for c in sorted(self.online):
            m = {n: v for n, v in self.presence.items() if n != c}
            self.net.send("server", c, {"t": "presence", "map": m})

    def peer_down(self, name):
        self.online.discard(name)
        if self.presence.pop(name, None) is not None:
            self._bcast_presence()

    def receive(self, src, msg):
        t = msg["t"]
        if t == "hello":
            self.online.add(src)
            evs = self.log[msg["last_seq"]:]
            if evs:
                self.net.send("server", src, {"t": "events", "evs": list(evs)})
            if msg.get("sel"):
                self.presence[src] = msg["sel"]
            self._bcast_presence()
            for op in msg["pending"]:
                self._process(src, op)
        elif t == "op":
            self._process(src, msg["op"])
        elif t == "presence":
            self.presence[src] = (msg["sid"], msg["ref"])
            self._bcast_presence()

    def _emit(self, ev):
        ev["seq"] = len(self.log) + 1
        d = self.doc
        t = ev["t"]
        sid = ev.get("sid")
        touched = ()
        if t == "cells":
            touched = list(ev["changes"])
        elif t == "setsheet" and sid in d.sheets:
            old = d.sheets[sid]["cells"]
            new = ev["cells"]
            touched = [r for r in set(old) | set(new) if old.get(r) != new.get(r)]
        elif t == "restoresheet":
            touched = list(ev["cells"])
        self.log.append(ev)
        d.apply_event(ev)
        d.seq = ev["seq"]
        author = ev.get("author")
        if author is None and ev.get("src"):
            author = ev["src"][0]
        for ref in touched:
            self.mods.setdefault((sid, ref), []).append((ev["seq"], author))
        for c in sorted(self.online):
            self.net.send("server", c, {"t": "events", "evs": [ev]})

    def _other_mod_after(self, sid, ref, seen, client):
        for seq, a in reversed(self.mods.get((sid, ref), [])):
            if seq <= seen:
                break
            if a != client:
                return True
        return False

    def _process(self, client, op):
        key = (client, op["id"])
        if key in self.results:
            r = self.results[key]
            if r is not None:
                self.net.send("server", client, r)
            return
        nack = self._handle(client, op)
        self.results[key] = nack
        if nack is not None:
            self.net.send("server", client, nack)

    def _handle(self, client, op):
        d = self.doc
        t = op["t"]
        sid = op.get("sid")

        def nack(reason):
            return {"t": "nack", "id": op["id"], "reason": reason, "sname": op.get("sname"),
                    "cells": list(op.get("changes", ()))}

        if t == "addsheet":
            if sid in d.sheets or d.name_taken(op["name"]):
                return nack("nom")
            ev = op_event(op, client)
        elif t == "right":
            if client != d.owner:
                return nack("droit")
            if sid not in d.sheets:
                return nack("supprimee")
            ev = {"t": "right", "person": op["person"], "sid": sid, "level": op["level"]}
        elif t == "restoresheet":
            if sid in d.sheets or d.name_taken(op["name"]):
                return nack("nom")
            if not self._can_write(client, sid):
                return nack("droit")
            ev = op_event(op, client)
        else:
            if sid not in d.sheets:
                return nack("supprimee")
            if not self._can_write(client, sid):
                return nack("droit")
            if t == "delsheet":
                if len(d.order) <= 1:
                    return nack("derniere")
                ev = op_event(op, client)
            elif t == "rename":
                if d.name_taken(op["new"], exclude=sid):
                    return nack("nom")
                ev = op_event(op, client)
            elif t == "setsheet":
                name = op["name"]
                if name != d.sheets[sid]["name"] and d.name_taken(name, exclude=sid):
                    name = d.sheets[sid]["name"]
                ev = op_event(dict(op, name=name), client)
            elif t == "cells":
                cur_cells = d.sheets[sid]["cells"]
                acc, confl = {}, {}
                for ref, cell in op["changes"].items():
                    if (not op.get("force") and cell != cur_cells.get(ref)
                            and self._other_mod_after(sid, ref, op["seen"], client)):
                        confl[ref] = (cell, client)
                    else:
                        acc[ref] = cell
                ev = {"t": "cells", "sid": sid, "changes": acc, "conflicts": confl,
                      "author": client, "ts": op["ts"], "kind": op.get("kind", "modification")}
            else:
                return nack("inconnue")
        ev["src"] = (client, op["id"])
        self._emit(ev)
        return None


# ------------------------------------------------------------------ client

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


class VersionView:
    def __init__(self, id, author, timestamp, kind, sheet):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind
        self.sheet = sheet


def _parse_csv(text):
    """Rend (lignes, None) ou (None, ligne du guillemet jamais fermé)."""
    rows, row, field = [], [], []
    inq = False
    fstart = True
    line = 1
    qline = 0
    i, n = 0, len(text)
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
        elif c == '"' and fstart:
            inq = True
            qline = line
            fstart = False
        elif c == ",":
            row.append("".join(field))
            field = []
            fstart = True
        elif c in "\r\n":
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
            fstart = True
            line += 1
        else:
            field.append(c)
            fstart = False
        i += 1
    if inq:
        return None, qline
    if row or field or not fstart:
        row.append("".join(field))
        rows.append(row)
    return rows, None


class Client:
    def __init__(self, net, clock, name, tz="UTC", _store=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        if _store is None:
            _store = {"base": None, "pending": {}, "opseq": 0, "sidseq": 0}
        self.store = _store
        self.base = pickle.loads(_store["base"]) if _store["base"] else Doc()
        self.pending = _store["pending"]
        self.active = None
        self.viewing = None
        self.vdoc = None
        self.veng = None
        self._alerts = []
        self.undo_stack = []
        self.redo_stack = []
        self.pmap = {}
        self.sel = None
        self.closed = False
        self._rebuild()
        net.register(name, self)
        self.connected = name not in net.down
        if self.connected:
            self._hello()

    # ---------------------------------------------------------- réseau
    def _hello(self):
        ops = []
        for op in self.pending.values():
            op["sent"] = True
            ops.append(dict(op))
        self.net.send(self.name, "server", {"t": "hello", "last_seq": self.base.seq,
                                            "pending": ops, "sel": self.sel})

    def net_state(self, up):
        if self.closed:
            return
        self.connected = up
        if up:
            self._hello()

    def receive(self, src, msg):
        if self.closed:
            return
        t = msg["t"]
        if t == "events":
            self._on_events(msg["evs"])
        elif t == "nack":
            self._on_nack(msg)
        elif t == "presence":
            self.pmap = msg["map"]

    def _on_events(self, evs):
        changed = False
        for ev in evs:
            if ev["seq"] <= self.base.seq:
                continue
            if ev["seq"] != self.base.seq + 1:
                self._hello()
                break
            self.base.apply_event(ev, record=True)
            self.base.seq = ev["seq"]
            src = ev.get("src")
            if src and src[0] == self.name:
                self.pending.pop(src[1], None)
            changed = True
        if changed:
            self.store["base"] = pickle.dumps(self.base)
            self._rebuild()

    def _on_nack(self, msg):
        self.pending.pop(msg["id"], None)
        r = msg["reason"]
        sn = msg.get("sname")
        if r == "droit":
            if msg["cells"]:
                for c in msg["cells"]:
                    self._alert("modification_rejetee", sheet=sn, cell=c)
            else:
                self._alert("droit_insuffisant", sheet=sn)
        elif r == "supprimee":
            self._alert("feuille_supprimee", sheet=sn)
        elif r == "nom":
            self._alert("nom_existant", sheet=sn)
        self._rebuild()

    # ---------------------------------------------------------- état local
    @property
    def view(self):
        return self._view

    def _rebuild(self):
        v = self.base.copy()
        for op in self.pending.values():
            ev = op_event(op, self.name)
            if ev is not None:
                v.apply_event(ev)
        self._view = v
        self.eng = Engine(v, self.clock)
        self.eng.build()

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self._alerts.append(Alert(kind, sheet, cell, line))

    def _next_id(self):
        self.store["opseq"] += 1
        return self.store["opseq"]

    def _new_op(self, t, **kw):
        op = {"id": self._next_id(), "t": t, "ts": self.clock.now(), "sent": False}
        op.update(kw)
        return op

    def _submit(self, op):
        op["sent"] = self.connected
        self.pending[op["id"]] = op
        struct, changed = self._view.apply_event(op_event(op, self.name))
        if struct:
            self.eng.build()
        elif changed:
            self.eng.update(changed)
        if self.connected:
            self.net.send(self.name, "server", {"t": "op", "op": dict(op)})

    def _can_write(self, sid):
        v = self._view
        return self.name == v.owner or v.rights.get((self.name, sid)) == W

    def _active_sid(self):
        v = self._view
        if self.active in v.sheets:
            return self.active
        return v.order[0] if v.order else None

    def _sid(self, sheet=None):
        if sheet is None:
            return self._active_sid()
        return self._view.sid_of(sheet)

    def _ctx(self, sid):
        if self.viewing and self.viewing[0] == sid:
            return self.vdoc, self.veng
        return self._view, self.eng

    def _make_cell(self, text, imp=False):
        if text is None or text == "":
            return None
        if text.startswith("="):
            return (text, imp)
        s = text.strip()
        try:
            if _DT_OFF.match(s):
                return (datetime.fromisoformat(s).astimezone(UTC).isoformat(), False)
            if _DT_NAIVE.match(s):
                dt = datetime.fromisoformat(s).replace(tzinfo=zi(self.tz))
                return (dt.astimezone(UTC).isoformat(), False)
        except ValueError:
            pass
        return (text, False)

    def _ctext(self, cell):
        if cell is None:
            return None
        text, lit = cell
        if not text.startswith("=") and _DT_OFF.match(text):
            try:
                return fmt_dt(datetime.fromisoformat(text), self.tz)
            except ValueError:
                return text
        return text

    def _display(self, v):
        if isinstance(v, Err):
            return v.code
        if isinstance(v, datetime):
            return fmt_dt(v, self.tz)
        if isinstance(v, date):
            return v.isoformat()
        return _norm(v) if isinstance(v, float) else v

    # ---------------------------------------------------------- lecture
    def content(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        doc, _ = self._ctx(sid)
        return self._ctext(doc.sheets[sid]["cells"].get(ref.upper()))

    def value(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        _, eng = self._ctx(sid)
        eng.refresh()
        return self._display(eng.get((sid, ref.upper())))

    def error(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        _, eng = self._ctx(sid)
        eng.refresh()
        v = eng.get((sid, ref.upper()))
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        self.tz = tz

    def sheets(self):
        v = self._view
        return [v.sheets[s]["name"] for s in v.order]

    def activate(self, name):
        sid = self._view.sid_of(name)
        if sid is not None:
            self.active = sid

    def right(self, person, sheet):
        sid = self._view.sid_of(sheet)
        if sid is None:
            return None
        if person == self._view.owner:
            return W
        return self._view.rights.get((person, sid))

    def alerts(self):
        return list(self._alerts)

    def connection_status(self):
        return "en ligne" if self.connected else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def presence(self):
        if not self.connected:
            return {}
        out = {}
        for n, (sid, ref) in self.pmap.items():
            if sid in self._view.sheets:
                out[n] = (self._view.sheets[sid]["name"], ref)
        return out

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return
        self.sel = (sid, ref.upper())
        if self.connected:
            self.net.send(self.name, "server", {"t": "presence", "sid": sid, "ref": ref.upper()})

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        c = self._view.conflicts.get((sid, ref.upper()))
        if c is None:
            return None
        return Conflict(self._ctext(c[0]), c[1])

    # ---------------------------------------------------------- édition
    def _edit(self, sid, changes, force=False):
        if self.viewing or sid is None or sid not in self._view.sheets:
            return
        sh = self._view.sheets[sid]
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sheet=sh["name"], cell=next(iter(changes), None))
            return
        before = {r: sh["cells"].get(r) for r in changes}
        op = self._new_op("cells", sid=sid, sname=sh["name"], changes=dict(changes),
                          seen=self.base.seq, force=force, kind="modification")
        self._submit(op)
        self.undo_stack.append({"kind": "cells", "sid": sid, "before": before,
                                "after": dict(changes), "opid": op["id"]})
        self.redo_stack.clear()

    def set_cell(self, ref, text, sheet=None):
        self._edit(self._sid(sheet), {ref.upper(): self._make_cell(text)})

    def clear(self, ref, sheet=None):
        self._edit(self._sid(sheet), {ref.upper(): None})

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sid = self._sid(sheet)
        if self.viewing or sid is None:
            return
        ref = ref.upper()
        c = self._view.conflicts.get((sid, ref))
        if c is None:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sheet=self._view.sheets[sid]["name"], cell=ref)
            return
        cell = c[0] if use_discarded else self._view.sheets[sid]["cells"].get(ref)
        self._edit(sid, {ref: cell}, force=True)

    def import_csv(self, data):
        sid = self._active_sid()
        if self.viewing or sid is None:
            return
        sh = self._view.sheets[sid]
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sheet=sh["name"])
            return
        rows, bad = _parse_csv(bytes(data).decode("utf-8-sig", errors="replace"))
        if rows is None:
            self._alert("csv_invalide", sheet=sh["name"], line=bad)
            return
        changes = {}
        for r, row in enumerate(rows, 1):
            for c, f in enumerate(row, 1):
                changes[f"{n2col(c)}{r}"] = self._make_cell(f, True)
        if changes:
            self._edit(sid, changes, force=True)

    def export_csv(self):
        sid = self._active_sid()
        if sid is None:
            return b""
        doc, eng = self._ctx(sid)
        eng.refresh()
        cells = doc.sheets[sid]["cells"]
        if not cells:
            return b""
        pos = [split_ref(r) for r in cells]
        rows = sorted({r for _, r in pos})
        width = max(c for c, _ in pos)
        buf = io.StringIO(newline="")
        w = csv.writer(buf, lineterminator="\n")
        for r in rows:
            line = []
            for c in range(1, width + 1):
                v = eng.get((sid, f"{n2col(c)}{r}"))
                if v is None:
                    line.append("")
                elif isinstance(v, Err):
                    line.append(v.code)
                elif isinstance(v, datetime):
                    line.append(v.astimezone(zi(self.tz)).isoformat())
                elif isinstance(v, date):
                    line.append(v.isoformat())
                elif isinstance(v, float):
                    line.append(str(_norm(v)))
                else:
                    line.append(str(v))
            w.writerow(line)
        return buf.getvalue().encode("utf-8")

    # ---------------------------------------------------------- feuilles
    def add_sheet(self, name):
        if self.viewing:
            return
        if self._view.name_taken(name):
            self._alert("nom_existant", sheet=name)
            return
        self.store["sidseq"] += 1
        sid = f"{self.name}-{self.store['sidseq']}"
        self._submit(self._new_op("addsheet", sid=sid, sname=name, name=name))

    def _snap(self, sid):
        sh = self._view.sheets[sid]
        return {"name": sh["name"], "cells": dict(sh["cells"])}

    def delete_sheet(self, name):
        sid = self._view.sid_of(name)
        if self.viewing or sid is None:
            return
        sh = self._view.sheets[sid]
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sheet=sh["name"])
            return
        if len(self._view.order) <= 1:
            return
        snap = {"name": sh["name"], "cells": dict(sh["cells"]), "index": self._view.order.index(sid)}
        op = self._new_op("delsheet", sid=sid, sname=sh["name"])
        self._submit(op)
        self.undo_stack.append({"kind": "sheetdel", "sid": sid, "before": snap, "after": None,
                                "opid": op["id"]})
        self.redo_stack.clear()

    def rename_sheet(self, old, new):
        sid = self._view.sid_of(old)
        if self.viewing or sid is None:
            return
        sh = self._view.sheets[sid]
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sheet=sh["name"])
            return
        if self._view.name_taken(new, exclude=sid):
            self._alert("nom_existant", sheet=new)
            return
        cur = sh["name"]
        if new == cur:
            return
        op = self._new_op("rename", sid=sid, sname=cur, new=new)
        self._submit(op)
        self.undo_stack.append({"kind": "rename", "sid": sid, "before": cur, "after": new,
                                "opid": op["id"]})
        self.redo_stack.clear()

    def right_set(self):
        pass

    def set_right(self, person, sheet, level):
        sid = self._view.sid_of(sheet)
        if sid is None:
            return
        if self.name != self._view.owner:
            self._alert("droit_insuffisant", sheet=self._view.sheets[sid]["name"])
            return
        if not self.connected:
            return
        op = {"id": self._next_id(), "t": "right", "sid": sid, "person": person, "level": level,
              "sname": self._view.sheets[sid]["name"], "ts": self.clock.now()}
        self.net.send(self.name, "server", {"t": "op", "op": op})

    # ---------------------------------------------------------- annuler / rétablir
    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def _transition(self, act, target):
        src = "after" if target == "before" else "before"
        kind, sid = act["kind"], act["sid"]
        v = self._view
        sh = v.sheets.get(sid)
        sname = sh["name"] if sh else None
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sheet=sname)
            return "denied"
        goal = act[target]
        op = None
        if kind == "cells":
            if sh is None or any(sh["cells"].get(r) != c for r, c in act[src].items()):
                return self._impossible(sname)
            op = self._new_op("cells", sid=sid, sname=sname, changes=dict(goal),
                              seen=self.base.seq, force=True, kind="modification")
        elif kind == "sheetdel":
            if target == "before":
                if sh is not None or v.name_taken(goal["name"]):
                    return self._impossible(goal["name"])
                op = self._new_op("restoresheet", sid=sid, sname=goal["name"], name=goal["name"],
                                  cells=dict(goal["cells"]), index=goal["index"])
            else:
                if sh is None or len(v.order) <= 1:
                    return self._impossible(sname)
                act["before"] = {"name": sh["name"], "cells": dict(sh["cells"]),
                                 "index": v.order.index(sid)}
                op = self._new_op("delsheet", sid=sid, sname=sname)
        elif kind == "rename":
            if sh is None or sh["name"].casefold() != act[src].casefold():
                return self._impossible(sname)
            if v.name_taken(goal, exclude=sid):
                return self._impossible(sname)
            op = self._new_op("rename", sid=sid, sname=sname, new=goal)
        elif kind == "setsheet":
            if sh is None or self._snap(sid) != act[src]:
                return self._impossible(sname)
            op = self._new_op("setsheet", sid=sid, sname=sname, name=goal["name"],
                              cells=dict(goal["cells"]), kind="modification")
        opid = act.get("opid")
        p = self.pending.get(opid)
        if p is not None and not p["sent"]:
            del self.pending[opid]
            self._rebuild()
            act["opid"] = None
            self.store["opseq"] = self.store["opseq"]
        else:
            self._submit(op)
            act["opid"] = op["id"]
        return "ok"

    def _impossible(self, sname):
        self._alert("annulation_impossible", sheet=sname)
        return "impossible"

    def undo(self):
        if self.viewing or not self.undo_stack:
            return
        act = self.undo_stack[-1]
        r = self._transition(act, "before")
        if r == "denied":
            return
        self.undo_stack.pop()
        if r == "ok":
            self.redo_stack.append(act)

    def redo(self):
        if self.viewing or not self.redo_stack:
            return
        act = self.redo_stack[-1]
        r = self._transition(act, "after")
        if r == "denied":
            return
        self.redo_stack.pop()
        if r == "ok":
            self.undo_stack.append(act)

    # ---------------------------------------------------------- historique
    def history(self, sheet=None):
        sid = self._sid(sheet)
        vs = sorted(self.base.history.get(sid, []), key=lambda v: (v.ts, v.id), reverse=True)
        return [VersionView(v.id, v.author, fmt_dt(v.ts, self.tz), v.kind, sid) for v in vs]

    def _find_version(self, vid):
        for vs in self.base.history.values():
            for v in vs:
                if v.id == vid:
                    return v
        return None

    def open_version(self, version_id):
        v = self._find_version(version_id)
        if v is None or v.sid not in self._view.sheets:
            return
        d = self._view.copy()
        d.sheets[v.sid]["cells"] = dict(v.cells)
        eng = Engine(d, self.clock)
        eng.build()
        self.viewing = (v.sid, v)
        self.vdoc = d
        self.veng = eng

    def close_version(self):
        self.viewing = None
        self.vdoc = None
        self.veng = None

    def restore_version(self, version_id):
        if self.viewing:
            return
        v = self._find_version(version_id)
        if v is None or v.sid not in self._view.sheets:
            return
        sid = v.sid
        sname = self._view.sheets[sid]["name"]
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sheet=sname)
            return
        before = self._snap(sid)
        op = self._new_op("setsheet", sid=sid, sname=sname, name=v.name, cells=dict(v.cells),
                          kind="restauration")
        self._submit(op)
        self.undo_stack.append({"kind": "setsheet", "sid": sid, "before": before,
                                "after": self._snap(sid), "opid": op["id"]})
        self.redo_stack.clear()

    # ---------------------------------------------------------- appareil
    def reopen(self):
        self.closed = True
        return Client(self.net, self.clock, self.name, tz=self.tz, _store=self.store)
