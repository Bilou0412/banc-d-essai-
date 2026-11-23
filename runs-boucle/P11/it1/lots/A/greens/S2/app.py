"""Classeur collaboratif hors ligne : module unique.

Architecture : un serveur autoritaire qui ordonne les modifications, des clients qui ont chacun
leur copie (état confirmé + modifications en attente rejouées par-dessus), un réseau simulé en
mémoire. Les formules sont analysées par un vrai analyseur et recalculées en suivant le graphe
des dépendances (ordre topologique, cycles détectés sur le graphe).
"""
import copy
import csv
import io
import re
from collections import deque
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

W = "écriture"
R = "lecture"
UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
EPOCH_D = date(1970, 1, 1)
LIT = "\x00"  # préfixe interne : contenu texte littéral (jamais une formule)

_ZI = {}


def zi(name):
    z = _ZI.get(name)
    if z is None:
        z = _ZI[name] = ZoneInfo(name)
    return z


# ------------------------------------------------------------------ valeurs

class Err(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class DT:
    __slots__ = ("dt",)

    def __init__(self, dt):
        self.dt = dt


class D:
    __slots__ = ("d",)

    def __init__(self, d):
        self.d = d


def norm(x):
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        return int(x)
    return x


def fmt_dt(dt, tz):
    return dt.astimezone(zi(tz)).strftime("%Y-%m-%d %H:%M")


def fmt_num(v):
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return str(v)


_REF = re.compile(r"([A-Z]+)(\d+)")
_SPLIT = {}


def split_ref(ref):
    r = _SPLIT.get(ref)
    if r is None:
        m = _REF.fullmatch(ref)
        if not m:
            r = (0, 0)
        else:
            c = 0
            for ch in m.group(1):
                c = c * 26 + ord(ch) - 64
            r = (c, int(m.group(2)))
        _SPLIT[ref] = r
    return r


def col_name(n):
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


_NUM = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
_DTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DTI = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\s*(Z|[+-]\d{2}:?\d{2}))?")
_LITC = {}


def _parse_literal(c):
    if _NUM.fullmatch(c):
        return float(c) if "." in c else int(c)
    if _DTC.fullmatch(c):
        try:
            return DT(datetime.fromisoformat(c))
        except ValueError:
            return c
    if _DATE.fullmatch(c):
        try:
            return D(date.fromisoformat(c))
        except ValueError:
            return c
    return c


def literal_value(c):
    if c.startswith(LIT):
        return c[1:]
    v = _LITC.get(c)
    if v is None:
        v = _LITC[c] = _parse_literal(c)
    return v


def normalize_input(text, tz, imp=False):
    """Texte saisi -> contenu stocké (partagé entre les copies)."""
    if text is None:
        return None
    text = str(text)
    if text == "":
        return None
    if text.startswith("="):
        return LIT + text if imp else text
    m = _DTI.fullmatch(text)
    if m:
        y, mo, d, h, mi, s, off = m.groups()
        try:
            naive = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
            if off is None:
                aware = naive.replace(tzinfo=zi(tz))
            elif off == "Z":
                aware = naive.replace(tzinfo=UTC)
            else:
                sign = -1 if off[0] == "-" else 1
                delta = timedelta(hours=int(off[1:3]), minutes=int(off[-2:]))
                aware = naive.replace(tzinfo=timezone(sign * delta))
            return aware.astimezone(UTC).isoformat()
        except ValueError:
            return text
    return text


# ------------------------------------------------------------------ analyseur

class _SynErr(Exception):
    pass


_TOK = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?|\.\d+)|(?P<q>'(?:[^']|'')+')|(?P<id>[^\W\d]\w*)|(?P<op>[-+*/(),;:!]))")
_CELL = re.compile(r"[A-Za-z]{1,3}[0-9]+")


def tokenize(s):
    out = []
    pos = 0
    while True:
        m = _TOK.match(s, pos)
        if not m:
            if s[pos:].strip() == "":
                break
            raise _SynErr()
        kind = m.lastgroup
        out.append((kind, m.group(kind), m.start(kind), m.end(kind)))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self):
        tok = self.peek()
        if tok is None:
            raise _SynErr()
        self.i += 1
        return tok

    def isop(self, v):
        tok = self.peek()
        return tok is not None and tok[0] == "op" and tok[1] == v

    def expect(self, v):
        if not self.isop(v):
            raise _SynErr()
        self.i += 1

    def parse(self):
        if not self.t:
            raise _SynErr()
        e = self.expr()
        if self.peek() is not None:
            raise _SynErr()
        return e

    def expr(self):
        left = self.term()
        while self.isop("+") or self.isop("-"):
            o = self.next()[1]
            left = ("bin", o, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.isop("*") or self.isop("/"):
            o = self.next()[1]
            left = ("bin", o, left, self.unary())
        return left

    def unary(self):
        if self.isop("-"):
            self.next()
            return ("neg", self.unary())
        if self.isop("+"):
            self.next()
            return self.unary()
        return self.primary()

    def primary(self):
        k, v, _, _ = self.next()
        if k == "num":
            return ("num", float(v) if "." in v else int(v))
        if k == "op" and v == "(":
            e = self.expr()
            self.expect(")")
            return e
        if k == "q":
            self.expect("!")
            return self.refpart(v[1:-1].replace("''", "'"))
        if k == "id":
            if self.isop("("):
                return self.call(v)
            if self.isop("!"):
                self.next()
                return self.refpart(v)
            return self.refrange(None, v)
        raise _SynErr()

    def refpart(self, sheet):
        k, v, _, _ = self.next()
        if k != "id":
            raise _SynErr()
        return self.refrange(sheet, v)

    def refrange(self, sheet, text):
        if not _CELL.fullmatch(text) or int(re.sub(r"[A-Za-z]", "", text)) == 0:
            raise _SynErr()
        r1 = text.upper()
        if self.isop(":"):
            self.next()
            k, v, _, _ = self.next()
            if k != "id" or not _CELL.fullmatch(v) or int(re.sub(r"[A-Za-z]", "", v)) == 0:
                raise _SynErr()
            return ("range", sheet, r1, v.upper())
        return ("ref", sheet, r1)

    def call(self, name):
        name = name.upper()
        self.expect("(")
        args = []
        if not self.isop(")"):
            while True:
                args.append(self.expr())
                if self.isop(",") or self.isop(";"):
                    self.next()
                    continue
                break
        self.expect(")")
        if name in ("SOMME", "SUM") and len(args) >= 1:
            return ("call", name, args)
        if name in ("MAINTENANT", "NOW") and not args:
            return ("call", name, args)
        raise _SynErr()


_PARSED = {}


def parse_formula(text):
    r = _PARSED.get(text)
    if r is None:
        try:
            r = (_Parser(tokenize(text[1:])).parse(), None)
        except (_SynErr, RecursionError):
            r = (None, "#SYNTAXE!")
        _PARSED[text] = r
    return r


def rewrite_sheet(text, old, new):
    """Réécrit les références à la feuille `old` dans une formule (au niveau des jetons)."""
    body = text[1:]
    try:
        toks = tokenize(body)
    except _SynErr:
        return text
    oldf = old.casefold()
    q = new if re.fullmatch(r"[^\W\d]\w*", new) else "'" + new.replace("'", "''") + "'"
    out = []
    last = 0
    for i, (k, v, s, e) in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if not (nxt is not None and nxt[0] == "op" and nxt[1] == "!"):
            continue
        name = v if k == "id" else (v[1:-1].replace("''", "'") if k == "q" else None)
        if name is not None and name.casefold() == oldf:
            out.append(body[last:s])
            out.append(q)
            last = e
    out.append(body[last:])
    return "=" + "".join(out)


def _num(v):
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, DT):
        return (v.dt - EPOCH).total_seconds() / 86400
    if isinstance(v, D):
        return float((v.d - EPOCH_D).days)
    raise Err("#TYPE!")


def _bin(o, a, b):
    if o == "-" and isinstance(a, DT) and isinstance(b, DT):
        return norm((a.dt - b.dt).total_seconds() / 86400)
    if o == "-" and isinstance(a, D) and isinstance(b, D):
        return (a.d - b.d).days
    x = _num(a)
    y = _num(b)
    if o == "+":
        r = x + y
    elif o == "-":
        r = x - y
    elif o == "*":
        r = x * y
    else:
        if y == 0:
            raise Err("#DIV/0!")
        r = x / y
    return norm(r)


# ------------------------------------------------------------------ classeur

class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}
        self.vers = {}
        self.lastop = {}
        self.conflicts = {}

    def copy(self):
        s = Sheet(self.name)
        s.cells = dict(self.cells)
        s.vers = dict(self.vers)
        s.lastop = dict(self.lastop)
        s.conflicts = dict(self.conflicts)
        return s


class _Ver:
    def __init__(self, vid, author, ts, kind, name, cells):
        self.vid = vid
        self.author = author
        self.ts = ts
        self.kind = kind
        self.name = name
        self.cells = cells


class _F:
    __slots__ = ("ast", "err", "deps", "ranges", "vol")


class Workbook:
    def __init__(self, owner=None, clock=None, initial=True):
        self.owner = owner
        self.clock = clock
        self.sheets = {}
        self.order = []
        self.deadpos = {}
        self.rights = {}
        self.history = {}
        if initial:
            self.sheets["s0"] = Sheet("Feuille1")
            self.order.append("s0")
        self._dirty = True
        self._t = None
        self.F = {}
        self.rdeps = {}
        self.rranges = []
        self.val = {}
        self.names = {}
        self.volatile = set()

    def copy(self, history=False, clock=None):
        w = Workbook(self.owner, clock, initial=False)
        w.sheets = {k: s.copy() for k, s in self.sheets.items()}
        w.order = list(self.order)
        w.deadpos = dict(self.deadpos)
        w.rights = dict(self.rights)
        if history:
            w.history = {k: list(v) for k, v in self.history.items()}
        return w

    # ---- structure
    def right(self, person, sid):
        if sid not in self.sheets:
            return None
        if person is not None and person == self.owner:
            return W
        return self.rights.get((person, sid))

    def sid_by_name(self, name):
        if name is None:
            return None
        n = name.casefold()
        for sid in self.order:
            if self.sheets[sid].name.casefold() == n:
                return sid
        return None

    def name_taken(self, name, except_sid=None):
        sid = self.sid_by_name(name)
        return sid is not None and sid != except_sid

    def _rename(self, sid, new):
        sh = self.sheets[sid]
        old = sh.name
        sh.name = new
        for s2 in self.sheets.values():
            changes = {}
            for ref, c in s2.cells.items():
                if c[0] == "=":
                    nc = rewrite_sheet(c, old, new)
                    if nc != c:
                        changes[ref] = nc
            s2.cells.update(changes)
        self._dirty = True

    def _add_version(self, sid, ev, kind):
        sh = self.sheets[sid]
        self.history.setdefault(sid, []).append(
            _Ver(ev.get("vid"), ev.get("author"), ev.get("ts"), kind, sh.name, dict(sh.cells)))

    def apply_event(self, ev, local=False, record=True):
        t = ev["type"]
        sid = ev.get("sid")
        if t == "setcells":
            sh = self.sheets.get(sid)
            if sh is None or sid not in self.order:
                return
            for ref, content in ev["writes"].items():
                if not local:
                    sh.vers[ref] = sh.vers.get(ref, 0) + 1
                    sh.lastop[ref] = ev.get("opid")
                sh.conflicts.pop(ref, None)
                self._set(sid, ref, content)
            if not local:
                for ref in ev.get("clears", ()):
                    sh.conflicts.pop(ref, None)
                for ref, (disc, by) in ev.get("conflicts", {}).items():
                    sh.conflicts[ref] = (disc, by)
                if record and ev["writes"]:
                    self._add_version(sid, ev, "modification")
        elif t == "resolve":
            sh = self.sheets.get(sid)
            if sh is None or sid not in self.order:
                return
            ref = ev["ref"]
            cf = sh.conflicts.pop(ref, None)
            if cf is not None and ev.get("use_discarded"):
                self._set(sid, ref, cf[0])
        elif t == "add_sheet":
            if sid in self.sheets:
                if sid in self.deadpos:
                    self.apply_event({"type": "undelete", "sid": sid})
                return
            if self.name_taken(ev["name"]):
                return
            self.sheets[sid] = Sheet(ev["name"])
            self.order.append(sid)
            author = ev.get("author")
            if author is not None and author != self.owner:
                self.rights[(author, sid)] = W
            self._dirty = True
        elif t == "delete_sheet":
            if sid not in self.order or len(self.order) <= 1:
                return
            self.deadpos[sid] = self.order.index(sid)
            self.order.remove(sid)
            self._dirty = True
        elif t == "undelete":
            if sid not in self.deadpos or self.name_taken(self.sheets[sid].name):
                return
            pos = self.deadpos.pop(sid)
            self.order.insert(min(pos, len(self.order)), sid)
            self._dirty = True
        elif t == "rename":
            sh = self.sheets.get(sid)
            if sh is None or sid not in self.order:
                return
            new = ev["name"]
            if sh.name == new or self.name_taken(new, sid):
                return
            self._rename(sid, new)
        elif t == "set_right":
            if ev.get("level") is None:
                self.rights.pop((ev["person"], sid), None)
            else:
                self.rights[(ev["person"], sid)] = ev["level"]
        elif t == "replace":
            sh = self.sheets.get(sid)
            if sh is None or sid not in self.order:
                return
            name = ev["name"]
            if name and name != sh.name and not self.name_taken(name, sid):
                self._rename(sid, name)
            newcells = dict(ev["cells"])
            if not local:
                for ref in set(sh.cells) | set(newcells):
                    sh.vers[ref] = sh.vers.get(ref, 0) + 1
                    sh.lastop.pop(ref, None)
            sh.cells = newcells
            sh.conflicts = {}
            self._dirty = True
            if not local and record:
                self._add_version(sid, ev, ev.get("kind", "modification"))

    # ---- calcul
    def _resolve(self, name, sid):
        if name is None:
            return sid
        return self.names.get(name.casefold())

    def _deps(self, ast, sid):
        cells = set()
        ranges = []
        vol = False
        stack = [ast]
        while stack:
            n = stack.pop()
            k = n[0]
            if k == "ref":
                s2 = self._resolve(n[1], sid)
                if s2 is not None:
                    cells.add((s2, n[2]))
            elif k == "range":
                s2 = self._resolve(n[1], sid)
                if s2 is not None:
                    c1, r1 = split_ref(n[2])
                    c2, r2 = split_ref(n[3])
                    ranges.append((s2, min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)))
            elif k == "neg":
                stack.append(n[1])
            elif k == "bin":
                stack.append(n[2])
                stack.append(n[3])
            elif k == "call":
                if n[1] in ("MAINTENANT", "NOW"):
                    vol = True
                stack.extend(n[2])
        return cells, ranges, vol

    def _reg(self, key, content):
        ast, err = parse_formula(content)
        f = _F()
        f.ast = ast
        f.err = err
        if err is None:
            f.deps, f.ranges, f.vol = self._deps(ast, key[0])
        else:
            f.deps, f.ranges, f.vol = set(), [], False
        self.F[key] = f
        for d in f.deps:
            self.rdeps.setdefault(d, set()).add(key)
        for r in f.ranges:
            self.rranges.append((key,) + r)
        if f.vol:
            self.volatile.add(key)

    def _unreg(self, key):
        f = self.F.pop(key, None)
        self.val.pop(key, None)
        self.volatile.discard(key)
        if f is None:
            return
        for d in f.deps:
            s = self.rdeps.get(d)
            if s is not None:
                s.discard(key)
                if not s:
                    del self.rdeps[d]
        if f.ranges:
            self.rranges = [r for r in self.rranges if r[0] != key]

    def _set(self, sid, ref, content):
        sh = self.sheets[sid]
        if content is None:
            sh.cells.pop(ref, None)
        else:
            sh.cells[ref] = content
        if self._dirty:
            return
        key = (sid, ref)
        self._unreg(key)
        if content is not None and content[0] == "=":
            self._reg(key, content)
        self._recalc({key})

    def _dependents(self, key):
        res = set(self.rdeps.get(key, ()))
        sid, ref = key
        c, r = split_ref(ref)
        for (fk, s2, c1, r1, c2, r2) in self.rranges:
            if s2 == sid and c1 <= c <= c2 and r1 <= r <= r2:
                res.add(fk)
        return res

    def _recalc(self, seeds):
        S = set(k for k in seeds if k in self.F)
        seen = set(seeds)
        stack = list(seeds)
        while stack:
            k = stack.pop()
            for f in self._dependents(k):
                if f not in self.F:
                    continue
                S.add(f)
                if f not in seen:
                    seen.add(f)
                    stack.append(f)
        self._eval_set(S)

    def _eval_set(self, S):
        if not S:
            return
        indeg = {f: 0 for f in S}
        outs = {}
        sp = {g: (g[0],) + split_ref(g[1]) for g in S}
        for f in S:
            fi = self.F[f]
            for d in fi.deps:
                if d in indeg:
                    outs.setdefault(d, []).append(f)
                    indeg[f] += 1
            for (s2, c1, r1, c2, r2) in fi.ranges:
                for g, (gs, gc, gr) in sp.items():
                    if gs == s2 and c1 <= gc <= c2 and r1 <= gr <= r2:
                        outs.setdefault(g, []).append(f)
                        indeg[f] += 1
        ready = deque(f for f in S if indeg[f] == 0)
        done = 0
        while ready:
            f = ready.popleft()
            self._compute(f)
            done += 1
            for g in outs.get(f, ()):
                indeg[g] -= 1
                if indeg[g] == 0:
                    ready.append(g)
        if done < len(S):
            for f in S:
                if indeg[f] > 0:
                    self.val[f] = Err("#CIRC!")

    def _compute(self, f):
        fi = self.F[f]
        if fi.err:
            self.val[f] = Err(fi.err)
            return
        try:
            v = self._eval(fi.ast, f[0])
        except Err as e:
            v = Err(e.code)
        except (OverflowError, ValueError):
            v = Err("#NUM!")
        except RecursionError:
            v = Err("#SYNTAXE!")
        self.val[f] = v

    def _valueof(self, sid, ref):
        c = self.sheets[sid].cells.get(ref)
        if c is None:
            return 0
        if c[0] == "=":
            v = self.val.get((sid, ref))
            if v is None:
                return 0
            if isinstance(v, Err):
                raise Err(v.code)
            return v
        return literal_value(c)

    def _eval(self, node, sid):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            s2 = self._resolve(node[1], sid)
            if s2 is None:
                raise Err("#REF!")
            return self._valueof(s2, node[2])
        if k == "range":
            raise Err("#TYPE!")
        if k == "neg":
            return norm(-_num(self._eval(node[1], sid)))
        if k == "bin":
            a = self._eval(node[2], sid)
            b = self._eval(node[3], sid)
            return _bin(node[1], a, b)
        if k == "call":
            name = node[1]
            if name in ("SOMME", "SUM"):
                total = 0
                for arg in node[2]:
                    if arg[0] == "range":
                        s2 = self._resolve(arg[1], sid)
                        if s2 is None:
                            raise Err("#REF!")
                        c1, r1 = split_ref(arg[2])
                        c2, r2 = split_ref(arg[3])
                        c1, c2 = min(c1, c2), max(c1, c2)
                        r1, r2 = min(r1, r2), max(r1, r2)
                        for ref in list(self.sheets[s2].cells):
                            c, r = split_ref(ref)
                            if c1 <= c <= c2 and r1 <= r <= r2:
                                total += _num(self._valueof(s2, ref))
                    else:
                        total += _num(self._eval(arg, sid))
                return norm(total)
            if name in ("MAINTENANT", "NOW"):
                return DT(self.clock.now())
        raise Err("#SYNTAXE!")

    def _full(self):
        self.F = {}
        self.rdeps = {}
        self.rranges = []
        self.val = {}
        self.volatile = set()
        self.names = {self.sheets[s].name.casefold(): s for s in self.order}
        for sid in self.order:
            for ref, c in self.sheets[sid].cells.items():
                if c[0] == "=":
                    self._reg((sid, ref), c)
        self._dirty = False
        self._eval_set(set(self.F))
        self._t = self.clock.now() if self.clock is not None else None

    def ensure(self):
        if self._dirty:
            self._full()
        elif self.volatile and self.clock is not None:
            t = self.clock.now()
            if t != self._t:
                self._t = t
                self._recalc(set(self.volatile))

    def get_value(self, sid, ref):
        self.ensure()
        c = self.sheets[sid].cells.get(ref)
        if c is None:
            return None
        if c[0] == "=":
            return self.val.get((sid, ref))
        return literal_value(c)


# ------------------------------------------------------------------ infrastructure

class Clock:
    def __init__(self, start):
        self._t = start.astimezone(UTC)

    def now(self):
        return self._t

    def advance(self, delta):
        self._t = self._t + delta


class Network:
    def __init__(self):
        self.nodes = {}
        self.down = set()
        self.queue = deque()
        self.storage = {}

    def register(self, name, node):
        self.nodes[name] = node

    def is_up(self, name):
        return name not in self.down

    def send(self, src, dst, payload):
        if src in self.down or dst in self.down:
            return
        self.queue.append((src, dst, copy.deepcopy(payload)))

    def _deliver(self, m):
        src, dst, payload = m
        if src in self.down or dst in self.down:
            return
        node = self.nodes.get(dst)
        if node is not None:
            node.receive(src, payload)

    def deliver_all(self):
        guard = 0
        while self.queue:
            self._deliver(self.queue.popleft())
            guard += 1
            if guard > 5_000_000:
                break

    def deliver_from(self, name):
        batch = [m for m in self.queue if m[0] == name]
        self.queue = deque(m for m in self.queue if m[0] != name)
        for m in batch:
            self._deliver(m)

    def disconnect(self, name):
        if name in self.down or name not in self.nodes or name == "server":
            return
        self.down.add(name)
        self.queue = deque(m for m in self.queue if m[0] != name and m[1] != name)
        self.nodes[name].on_disconnect()
        self.queue.append(("net", "server", ("down", name)))

    def reconnect(self, name):
        if name not in self.down:
            return
        self.down.discard(name)
        node = self.nodes.get(name)
        if node is not None:
            node.on_reconnect()


class Server:
    def __init__(self, net, clock, owner="alice"):
        self.net = net
        self.clock = clock
        self.owner = owner
        self.wb = Workbook(owner)
        self.seq = 0
        self.vseq = 0
        self.online = []
        self.seen = {}
        self.presence = {}
        net.register("server", self)

    def _send(self, dst, msg):
        self.net.send("server", dst, msg)

    def _others(self, name):
        return [c for c in self.online if c != name]

    def receive(self, src, p):
        k = p[0]
        if k == "hello":
            if src not in self.online:
                self.online.append(src)
            sel = p[1].get("selection")
            if sel:
                self.presence[src] = tuple(sel)
                for c in self._others(src):
                    self._send(c, ("presence", src, sel[0], sel[1]))
            snap = {
                "wb": self.wb.copy(history=True),
                "seq": self.seq,
                "seen": set(self.seen.get(src, ())),
                "presence": {n: v for n, v in self.presence.items() if n != src},
            }
            self._send(src, ("snapshot", snap))
        elif k == "down":
            name = p[1]
            if name in self.online:
                self.online.remove(name)
            if self.presence.pop(name, None) is not None:
                for c in self.online:
                    self._send(c, ("presence_off", name))
        elif k == "select":
            self.presence[src] = (p[1], p[2])
            for c in self._others(src):
                self._send(c, ("presence", src, p[1], p[2]))
        elif k == "op":
            self._op(src, p[1])

    def _reject(self, src, oid, alert):
        self._send(src, ("reject", {"opid": oid, "alert": alert}))

    def _emit(self, ev):
        self.seq += 1
        ev["seq"] = self.seq
        self.wb.apply_event(ev, local=False, record=True)
        for c in list(self.online):
            self._send(c, ("event", ev))

    def _vid(self):
        self.vseq += 1
        return "v%d" % self.vseq

    def _op(self, src, op):
        oid = op["opid"]
        seen = self.seen.setdefault(src, set())
        if oid in seen:
            return
        seen.add(oid)
        wb = self.wb
        t = op["type"]
        sid = op.get("sid")
        sh = wb.sheets.get(sid)
        live = sid in wb.order

        def alert(kind, sheet=None, cell=None):
            return {"kind": kind, "sheet": sheet, "cell": cell, "line": None}

        ev = {"type": t, "opid": oid, "author": src, "ts": op["ts"]}

        if t == "set_right":
            if src != self.owner or sh is None or op.get("person") == self.owner \
                    or op.get("level") not in (W, R, None):
                return self._reject(src, oid, None)
            ev.update(sid=sid, person=op["person"], level=op["level"])
            return self._emit(ev)

        if t == "add_sheet":
            name = op["name"]
            if sid in wb.sheets:
                if live:
                    return self._reject(src, oid, None)
                if wb.name_taken(wb.sheets[sid].name):
                    return self._reject(src, oid, alert("nom_existant", wb.sheets[sid].name))
            elif not name or wb.name_taken(name):
                return self._reject(src, oid, alert("nom_existant", name))
            ev.update(sid=sid, name=name)
            return self._emit(ev)

        if t == "undelete":
            if sh is None or sid not in wb.deadpos:
                return self._reject(src, oid, None)
            if wb.right(src, sid) != W:
                return self._reject(src, oid, alert("droit_insuffisant", sh.name))
            if wb.name_taken(sh.name):
                return self._reject(src, oid, alert("nom_existant", sh.name))
            ev.update(sid=sid)
            return self._emit(ev)

        # opérations sur une feuille existante
        if sh is None:
            return self._reject(src, oid, None)
        if not live:
            if t == "delete_sheet":
                return self._reject(src, oid, None)
            return self._reject(src, oid, alert("feuille_supprimee", sh.name))
        if wb.right(src, sid) != W:
            if t == "setcells":
                return self._reject(src, oid, alert("modification_rejetee", sh.name,
                                                    next(iter(op["writes"]), None)))
            return self._reject(src, oid, alert("droit_insuffisant", sh.name))

        if t == "setcells":
            writes = {}
            conflicts = {}
            bases = op.get("bases", {})
            prevs = op.get("prevs", {})
            for ref, content in op["writes"].items():
                cur = sh.cells.get(ref)
                prev = prevs.get(ref)
                fresh = (prev is not None and sh.lastop.get(ref) == prev) \
                    or bases.get(ref, 0) == sh.vers.get(ref, 0)
                if fresh:
                    if content == cur and ref not in sh.conflicts:
                        continue
                    writes[ref] = content
                else:
                    if content == cur:
                        continue
                    conflicts[ref] = (content, src)
            ev.update(sid=sid, writes=writes, conflicts=conflicts, clears=[])
            if writes:
                ev["vid"] = self._vid()
            return self._emit(ev)

        if t == "resolve":
            ref = op["ref"]
            cf = sh.conflicts.get(ref)
            writes = {ref: cf[0]} if cf is not None and op.get("use_discarded") else {}
            ev.update(type="setcells", sid=sid, writes=writes, conflicts={},
                      clears=[ref] if cf is not None else [])
            if writes:
                ev["vid"] = self._vid()
            return self._emit(ev)

        if t == "delete_sheet":
            if len(wb.order) <= 1:
                return self._reject(src, oid, None)
            ev.update(sid=sid)
            return self._emit(ev)

        if t == "rename":
            name = op["name"]
            if name == sh.name:
                return self._reject(src, oid, None)
            if not name or wb.name_taken(name, sid):
                return self._reject(src, oid, alert("nom_existant", name))
            ev.update(sid=sid, name=name)
            return self._emit(ev)

        if t == "replace":
            name = op["name"]
            final = name if name and (name == sh.name or not wb.name_taken(name, sid)) else sh.name
            ev.update(sid=sid, name=final, cells=dict(op["cells"]), kind=op.get("kind", "modification"),
                      vid=self._vid())
            return self._emit(ev)

        return self._reject(src, oid, None)


# ------------------------------------------------------------------ objets publics

class Alert:
    def __init__(self, kind, sheet=None, cell=None, line=None):
        self.kind = kind
        self.sheet = sheet
        self.cell = cell
        self.line = line

    def __repr__(self):
        return "Alert(%r, %r, %r, %r)" % (self.kind, self.sheet, self.cell, self.line)


class Conflict:
    def __init__(self, discarded, discarded_by):
        self.discarded = discarded
        self.discarded_by = discarded_by


class Version:
    def __init__(self, id, author, timestamp, kind, sheet=None):
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.kind = kind
        self.sheet = sheet


def parse_csv(text):
    """-> (lignes, ligne_invalide|None). Une ligne vide donne une ligne sans champ."""
    rows = []
    row = []
    field = []
    inq = False
    qline = 0
    line = 1
    started = False
    fstart = True
    i = 0
    n = len(text)
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
        if ch == '"' and fstart:
            inq = True
            qline = line
            started = True
            fstart = False
            i += 1
            continue
        if ch == ",":
            row.append("".join(field))
            field = []
            started = True
            fstart = True
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if started:
                row.append("".join(field))
                rows.append(row)
            else:
                rows.append([])
            row = []
            field = []
            started = False
            fstart = True
            line += 1
            i += 1
            continue
        field.append(ch)
        started = True
        fstart = False
        i += 1
    if inq:
        return rows, qline
    if started:
        row.append("".join(field))
        rows.append(row)
    return rows, None


class Client:
    def __init__(self, net, clock, name, tz="Europe/Paris"):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.conf = Workbook(None)
        self.pending = []
        self.last_seq = 0
        self.n = 0
        self.active = None
        self.selection = None
        self.presence_map = {}
        self._alerts = []
        self.undo_stack = []
        self.redo_stack = []
        self.viewing = None
        self._view = None
        self._vwb = None
        self.closed = False
        st = net.storage.pop(name, None)
        if st is not None:
            self.tz = st["tz"]
            self.conf = st["conf"]
            self.pending = st["pending"]
            self.last_seq = st["last_seq"]
            self.n = st["n"]
            self.active = st["active"]
            self.selection = st["selection"]
        net.register(name, self)
        if net.is_up(name):
            self._hello()

    # ---- réseau
    @property
    def connected(self):
        return (not self.closed) and self.net.is_up(self.name)

    def _send(self, msg):
        self.net.send(self.name, "server", msg)

    def _hello(self):
        self._send(("hello", {"selection": self.selection}))
        for op in self.pending:
            self._send(("op", op))
            op["sent"] = True

    def on_disconnect(self):
        self.presence_map = {}

    def on_reconnect(self):
        if not self.closed:
            self._hello()

    def receive(self, src, p):
        if self.closed:
            return
        k = p[0]
        if k == "event":
            self._on_event(p[1])
        elif k == "snapshot":
            d = p[1]
            self.conf = d["wb"]
            self.last_seq = d["seq"]
            seen = d["seen"]
            self.pending = [o for o in self.pending if o["opid"] not in seen]
            self.presence_map = dict(d["presence"])
            self._invalidate()
        elif k == "reject":
            r = p[1]
            self.pending = [o for o in self.pending if o["opid"] != r["opid"]]
            if r.get("alert"):
                self._alerts.append(Alert(**r["alert"]))
            self._invalidate()
        elif k == "presence":
            if p[1] != self.name:
                self.presence_map[p[1]] = (p[2], p[3])
        elif k == "presence_off":
            self.presence_map.pop(p[1], None)

    def _on_event(self, ev):
        if ev["seq"] <= self.last_seq:
            return
        self.last_seq = ev["seq"]
        self.conf.apply_event(ev, local=False, record=True)
        if ev.get("author") == self.name:
            self.pending = [o for o in self.pending if o["opid"] != ev.get("opid")]
        self._invalidate()

    def _invalidate(self):
        self._view = None
        self._vwb = None

    # ---- copie locale
    @property
    def view(self):
        if self._view is None:
            v = self.conf.copy(history=False, clock=self.clock)
            for op in self.pending:
                v.apply_event(op, local=True)
            self._view = v
        return self._view

    def _rwb(self):
        v = self.view
        if self.viewing is None:
            return v
        if self._vwb is None:
            w = v.copy(history=False, clock=self.clock)
            sid, cells = self.viewing
            if sid in w.sheets:
                w.sheets[sid].cells = dict(cells)
            self._vwb = w
        return self._vwb

    def _active_sid(self):
        v = self.view
        if self.active in v.order:
            return self.active
        return v.order[0] if v.order else None

    def _sid(self, sheet):
        if sheet is None:
            return self._active_sid()
        return self.view.sid_by_name(sheet)

    def _can_write(self, sid):
        return self.view.right(self.name, sid) == W

    def _alert(self, kind, sid=None, cell=None, line=None, sheetname=None):
        if sheetname is None and sid is not None and sid in self.view.sheets:
            sheetname = self.view.sheets[sid].name
        self._alerts.append(Alert(kind, sheetname, cell, line))

    def alerts(self):
        return list(self._alerts)

    # ---- lecture
    def _disp_content(self, c):
        if c is None:
            return None
        if c.startswith(LIT):
            return c[1:]
        if _DTC.fullmatch(c):
            return fmt_dt(datetime.fromisoformat(c), self.tz)
        return c

    def content(self, ref, sheet=None):
        wb = self._rwb()
        sid = self._sid(sheet)
        if sid is None or sid not in wb.sheets:
            return None
        return self._disp_content(wb.sheets[sid].cells.get(ref.upper()))

    def _disp_value(self, v):
        if isinstance(v, Err):
            return v.code
        if isinstance(v, DT):
            return fmt_dt(v.dt, self.tz)
        if isinstance(v, D):
            return v.d.isoformat()
        return v

    def value(self, ref, sheet=None):
        wb = self._rwb()
        sid = self._sid(sheet)
        if sid is None or sid not in wb.sheets:
            return None
        return self._disp_value(wb.get_value(sid, ref.upper()))

    def error(self, ref, sheet=None):
        wb = self._rwb()
        sid = self._sid(sheet)
        if sid is None or sid not in wb.sheets:
            return None
        v = wb.get_value(sid, ref.upper())
        return v.code if isinstance(v, Err) else None

    def set_timezone(self, tz):
        zi(tz)
        self.tz = tz

    def sheets(self):
        v = self.view
        return [v.sheets[s].name for s in v.order]

    def activate(self, name):
        sid = self.view.sid_by_name(name)
        if sid is not None:
            self.active = sid

    def right(self, person, sheet):
        sid = self._sid(sheet)
        if sid is None:
            return None
        return self.view.right(person, sid)

    def connection_status(self):
        return "en ligne" if self.connected else "hors ligne"

    def pending_count(self):
        return len(self.pending)

    def select(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return
        self.selection = (sid, ref.upper())
        if self.connected:
            self._send(("select", sid, ref.upper()))

    def presence(self):
        if not self.connected:
            return {}
        v = self.view
        out = {}
        for n, (sid, ref) in self.presence_map.items():
            if n != self.name and sid in v.order:
                out[n] = (v.sheets[sid].name, ref)
        return out

    def conflict(self, ref, sheet=None):
        sid = self._sid(sheet)
        if sid is None:
            return None
        cf = self.view.sheets[sid].conflicts.get(ref.upper())
        if cf is None:
            return None
        return Conflict(self._disp_content(cf[0]), cf[1])

    # ---- soumission
    def _submit(self, op):
        self.n += 1
        op["opid"] = "%s#%d" % (self.name, self.n)
        op["author"] = self.name
        op["ts"] = self.clock.now()
        v = self.view
        if op["type"] == "setcells":
            sh = v.sheets[op["sid"]]
            op["bases"] = {r: sh.vers.get(r, 0) for r in op["writes"]}
            prevs = {}
            want = len(op["writes"])
            for p in reversed(self.pending):
                if p["type"] == "setcells" and p["sid"] == op["sid"]:
                    for r in op["writes"]:
                        if r not in prevs and r in p["writes"]:
                            prevs[r] = p["opid"]
                    if len(prevs) == want:
                        break
            op["prevs"] = prevs
        v.apply_event(op, local=True)
        self.pending.append(op)
        if self.connected:
            self._send(("op", op))
            op["sent"] = True
        return op

    def _push(self, entry):
        self.undo_stack.append(entry)
        self.redo_stack = []

    def _edit(self, sid, writes):
        sh = self.view.sheets[sid]
        old = {r: sh.cells.get(r) for r in writes}
        op = self._submit({"type": "setcells", "sid": sid, "writes": dict(writes)})
        self._push({"fwd": {"type": "setcells", "sid": sid, "writes": dict(writes)},
                    "inv": {"type": "setcells", "sid": sid, "writes": old},
                    "opid": op["opid"]})

    # ---- actions
    def set_cell(self, ref, text, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid, ref)
            return
        self._edit(sid, {ref: normalize_input(text, self.tz)})

    def clear(self, ref, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid, ref)
            return
        self._edit(sid, {ref: None})

    def add_sheet(self, name):
        if self.viewing is not None or not name:
            return
        if self.view.name_taken(name):
            self._alert("nom_existant", sheetname=name)
            return
        self.n += 1
        sid = "%s:%d" % (self.name, self.n)
        op = self._submit({"type": "add_sheet", "sid": sid, "name": name})
        self._push({"fwd": {"type": "add_sheet", "sid": sid, "name": name},
                    "inv": {"type": "delete_sheet", "sid": sid},
                    "opid": op["opid"]})

    def delete_sheet(self, name):
        if self.viewing is not None:
            return
        sid = self._sid(name)
        if sid is None:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid)
            return
        if len(self.view.order) <= 1:
            return
        op = self._submit({"type": "delete_sheet", "sid": sid})
        self._push({"fwd": {"type": "delete_sheet", "sid": sid},
                    "inv": {"type": "undelete", "sid": sid},
                    "opid": op["opid"]})

    def rename_sheet(self, old, new):
        if self.viewing is not None:
            return
        sid = self._sid(old)
        if sid is None:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid)
            return
        cur = self.view.sheets[sid].name
        if new == cur or not new:
            return
        if self.view.name_taken(new, sid):
            self._alert("nom_existant", sheetname=new)
            return
        op = self._submit({"type": "rename", "sid": sid, "name": new})
        self._push({"fwd": {"type": "rename", "sid": sid, "name": new},
                    "inv": {"type": "rename", "sid": sid, "name": cur},
                    "opid": op["opid"]})

    def set_right(self, person, sheet, level):
        v = self.view
        if not self.connected or v.owner is None or self.name != v.owner:
            return
        sid = self._sid(sheet)
        if sid is None or level not in (W, R, None):
            return
        self._submit({"type": "set_right", "sid": sid, "person": person, "level": level})

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.viewing is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = ref.upper()
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid, ref)
            return
        if ref not in self.view.sheets[sid].conflicts:
            return
        self._submit({"type": "resolve", "sid": sid, "ref": ref, "use_discarded": bool(use_discarded)})

    # ---- annulation / rétablissement
    def _check(self, spec, entry, undo):
        """True : possible ; False : impossible ; None : refusé (droit), alerte levée."""
        v = self.view
        t = spec["type"]
        sid = spec["sid"]
        if t == "add_sheet":
            return sid not in v.order and not v.name_taken(spec["name"])
        if t == "undelete":
            if sid not in v.deadpos or v.name_taken(v.sheets[sid].name):
                return False
            if not self._can_write(sid):
                self._alert("droit_insuffisant", sid)
                return None
            return True
        if sid not in v.order:
            return False
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid)
            return None
        if t == "setcells":
            if undo:
                sh = v.sheets[sid]
                for ref, c in entry["fwd"]["writes"].items():
                    if sh.cells.get(ref) != c:
                        return False
            return True
        if t == "delete_sheet":
            return len(v.order) > 1
        if t == "rename":
            return not v.name_taken(spec["name"], sid)
        return True

    def undo(self):
        if self.viewing is not None or not self.undo_stack:
            return
        e = self.undo_stack[-1]
        ok = self._check(e["inv"], e, True)
        if ok is None:
            return
        self.undo_stack.pop()
        if not ok:
            self._alert("annulation_impossible", e["inv"].get("sid"))
            return
        pend = None
        for p in self.pending:
            if p["opid"] == e["opid"] and not p.get("sent"):
                pend = p
                break
        if pend is not None:
            self.pending.remove(pend)
            self._invalidate()
        else:
            self._submit(copy.deepcopy(e["inv"]))
        self.redo_stack.append(e)

    def redo(self):
        if self.viewing is not None or not self.redo_stack:
            return
        e = self.redo_stack[-1]
        ok = self._check(e["fwd"], e, False)
        if ok is None:
            return
        self.redo_stack.pop()
        if not ok:
            self._alert("annulation_impossible", e["fwd"].get("sid"))
            return
        op = self._submit(copy.deepcopy(e["fwd"]))
        e["opid"] = op["opid"]
        self.undo_stack.append(e)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    # ---- persistance
    def reopen(self):
        self.net.storage[self.name] = {
            "tz": self.tz,
            "conf": self.conf.copy(history=True),
            "pending": copy.deepcopy(self.pending),
            "last_seq": self.last_seq,
            "n": self.n,
            "active": self.active,
            "selection": self.selection,
        }
        self.closed = True
        return Client(self.net, self.clock, self.name, tz=self.tz)

    # ---- historique
    def history(self, sheet=None):
        sid = self._sid(sheet)
        hl = self.conf.history.get(sid, [])
        idx = sorted(range(len(hl)), key=lambda i: (hl[i].ts, i), reverse=True)
        return [Version(hl[i].vid, hl[i].author, fmt_dt(hl[i].ts, self.tz), hl[i].kind, hl[i].name)
                for i in idx]

    def _find_version(self, vid):
        for sid, hl in self.conf.history.items():
            for ver in hl:
                if ver.vid == vid:
                    return sid, ver
        return None

    def open_version(self, version_id):
        found = self._find_version(version_id)
        if found is None:
            return
        sid, ver = found
        self.viewing = (sid, dict(ver.cells))
        self._vwb = None

    def close_version(self):
        self.viewing = None
        self._vwb = None

    def restore_version(self, version_id):
        found = self._find_version(version_id)
        if found is None:
            return
        sid, ver = found
        v = self.view
        if sid not in v.order:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid)
            return
        sh = v.sheets[sid]
        inv = {"type": "replace", "sid": sid, "name": sh.name, "cells": dict(sh.cells),
               "kind": "modification"}
        fwd = {"type": "replace", "sid": sid, "name": ver.name, "cells": dict(ver.cells),
               "kind": "restauration"}
        op = self._submit(copy.deepcopy(fwd))
        self._push({"fwd": fwd, "inv": inv, "opid": op["opid"]})

    # ---- CSV
    def _export_field(self, wb, sid, ref):
        c = wb.sheets[sid].cells.get(ref)
        if c is None:
            return ""
        if c[0] == "=":
            v = wb.get_value(sid, ref)
        else:
            if c.startswith(LIT):
                return c[1:]
            v = literal_value(c)
            if isinstance(v, (int, float)):
                return c
        if isinstance(v, Err):
            return v.code
        if isinstance(v, DT):
            return v.dt.astimezone(zi(self.tz)).isoformat()
        if isinstance(v, D):
            return v.d.isoformat()
        if isinstance(v, (int, float)):
            return fmt_num(v)
        return "" if v is None else str(v)

    def export_csv(self):
        wb = self._rwb()
        sid = self._active_sid()
        if sid is None or sid not in wb.sheets:
            return b""
        rows = {}
        maxcol = 0
        for ref in wb.sheets[sid].cells:
            c, r = split_ref(ref)
            rows.setdefault(r, {})[c] = self._export_field(wb, sid, ref)
            maxcol = max(maxcol, c)
        buf = io.StringIO(newline="")
        wr = csv.writer(buf, lineterminator="\n")
        for r in sorted(rows):
            wr.writerow([rows[r].get(c, "") for c in range(1, maxcol + 1)])
        return buf.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.viewing is not None:
            return
        sid = self._active_sid()
        if sid is None:
            return
        if not self._can_write(sid):
            self._alert("droit_insuffisant", sid)
            return
        try:
            text = bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:
            self._alert("csv_invalide", sid, line=1)
            return
        rows, bad = parse_csv(text)
        if bad is not None:
            self._alert("csv_invalide", sid, line=bad)
            return
        writes = {}
        for i, row in enumerate(rows, start=1):
            for j, field in enumerate(row, start=1):
                writes[col_name(j) + str(i)] = normalize_input(field, self.tz, imp=True)
        if not writes:
            return
        self._edit(sid, writes)
