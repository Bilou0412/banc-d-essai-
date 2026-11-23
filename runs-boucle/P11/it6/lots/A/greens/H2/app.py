"""Classeur collaboratif hors ligne — implémentation (couche code, tour 1)."""
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
RIGHTS = ("écriture", "lecture")


# ------------------------------------------------------------------ erreurs


class CellError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ------------------------------------------------------------------ temps


class Clock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


# ------------------------------------------------------------------ adresses


def col_to_num(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def num_to_col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


REF_RE = re.compile(r"^([A-Za-z]+)([0-9]+)$")


def parse_ref(ref):
    m = REF_RE.match(ref.strip())
    if not m:
        raise ValueError(ref)
    return (int(m.group(2)), col_to_num(m.group(1)))  # (ligne, colonne)


def ref_of(rc):
    row, col = rc
    return f"{num_to_col(col)}{row}"


def norm_ref(ref):
    return ref_of(parse_ref(ref))


# ------------------------------------------------------------------ analyseur

TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<func>[A-Za-z]+)(?=\s*\()"
    r"|(?P<sheetref>(?:[^\W\d]\w*|'[^']*')!\$?[A-Za-z]+\$?\d+(?::\$?[A-Za-z]+\$?\d+)?)"
    r"|(?P<ref>\$?[A-Za-z]+\$?\d+(?::\$?[A-Za-z]+\$?\d+)?)"
    r"|(?P<op>[-+*/(),]))"
)


def tokenize(text):
    pos, out = 0, []
    text = text.rstrip()
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise CellError("#SYNTAXE!")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


class Parser:
    """expr := terme (('+'|'-') terme)* ; terme := unaire (('*'|'/') unaire)* ;
    unaire := '-' unaire | atome ; atome := nombre | ref | feuille!ref | FONC '(' args ')' | '(' expr ')'."""

    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            raise CellError("#SYNTAXE!")
        node = self.expr()
        if self.i != len(self.t):
            raise CellError("#SYNTAXE!")
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
        return self.atom()

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", float(val) if "." in val else int(val))
        if kind == "ref":
            return self._ref(None, val)
        if kind == "sheetref":
            sheet, ref = val.split("!", 1)
            return self._ref(sheet.strip("'"), ref)
        if kind == "func":
            if self.take() != ("op", "("):
                raise CellError("#SYNTAXE!")
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.expr())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
            if self.take() != ("op", ")"):
                raise CellError("#SYNTAXE!")
            return ("call", val.upper(), args)
        if (kind, val) == ("op", "("):
            node = self.expr()
            if self.take() != ("op", ")"):
                raise CellError("#SYNTAXE!")
            return node
        raise CellError("#SYNTAXE!")

    def _ref(self, sheet, ref):
        if ":" in ref:
            a, b = ref.replace("$", "").split(":")
            return ("range", sheet, norm_ref(a), norm_ref(b))
        return ("ref", sheet, norm_ref(ref.replace("$", "")))


def parse_formula(text):
    """text commence par '=' ; rend l'arbre syntaxique ou lève #SYNTAXE!."""
    return Parser(tokenize(text[1:])).parse()


def refs_of(node, out=None):
    """Ensemble des (feuille|None, ref) dépendances statiques d'un arbre."""
    if out is None:
        out = set()
    k = node[0]
    if k == "ref":
        out.add((node[1], node[2]))
    elif k == "range":
        a = parse_ref(node[2])
        b = parse_ref(node[3])
        for r in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
            for c in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
                out.add((node[1], ref_of((r, c))))
    elif k == "bin":
        refs_of(node[2], out)
        refs_of(node[3], out)
    elif k == "neg":
        refs_of(node[1], out)
    elif k == "call":
        for a in node[2]:
            refs_of(a, out)
    return out


# ------------------------------------------------------------------ valeurs typées


class DateTimeValue:
    """Instant absolu (UTC) issu d'une saisie date-heure ; affiché dans le fuseau du lecteur."""

    def __init__(self, instant):
        self.instant = instant

    def __eq__(self, other):
        return isinstance(other, DateTimeValue) and other.instant == self.instant

    def __hash__(self):
        return hash(self.instant)


class DateValue:
    def __init__(self, d):
        self.d = d

    def __eq__(self, other):
        return isinstance(other, DateValue) and other.d == self.d

    def __hash__(self):
        return hash(self.d)


NUM_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
NAIVE_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
AWARE_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def to_instant_naive(naive, tz_name):
    """Interprète une date-heure sans décalage dans le fuseau donné (zoneinfo, règles réelles)."""
    return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def classify_input(text, tz_name):
    """Rend ('num', n) | ('date', DateValue) | ('dt', DateTimeValue) | ('text', None) pour une saisie brute."""
    s = text.strip()
    if NUM_RE.match(s):
        return ("num", float(s) if "." in s else int(s))
    if DATE_RE.match(s):
        return ("date", DateValue(date.fromisoformat(s)))
    if AWARE_DT_RE.match(s):
        return ("dt", DateTimeValue(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)))
    if NAIVE_DT_RE.match(s):
        naive = datetime.fromisoformat(s.replace("T", " "))
        return ("dt", DateTimeValue(to_instant_naive(naive, tz_name)))
    return ("text", None)


def format_dt(instant, tz_name):
    return instant.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")


def format_iso(instant, tz_name):
    return instant.astimezone(ZoneInfo(tz_name)).isoformat(timespec="seconds")


def display_value(v, tz_name):
    if v is None:
        return None
    if isinstance(v, DateTimeValue):
        return format_dt(v.instant, tz_name)
    if isinstance(v, DateValue):
        return v.d.isoformat()
    return v


sys_limit = None
import sys as _sys
_sys.setrecursionlimit(50000)

PARSE_CACHE = {}


def parse_cached(raw):
    """Rend l'arbre, ou l'exception #SYNTAXE! (mémorisée)."""
    hit = PARSE_CACHE.get(raw)
    if hit is None:
        try:
            hit = parse_formula(raw)
        except CellError as exc:
            hit = exc
        PARSE_CACHE[raw] = hit
    return hit


def make_entry(text, tz_name, literal=False):
    """Classement d'une saisie au moment de la saisie (fuseau de l'auteur fixé ici)."""
    if text is None:
        return None
    if not literal and text.startswith("="):
        return {"k": "f", "raw": text}
    kind, val = classify_input(text, tz_name)
    if kind == "num":
        return {"k": "n", "raw": text, "v": val}
    if kind == "date":
        return {"k": "d", "raw": text, "v": val.d}
    if kind == "dt":
        naive = None
        src = None
        if NAIVE_DT_RE.match(text.strip()):
            naive = text.strip().replace("T", " ")
            src = tz_name
        return {"k": "t", "raw": text, "v": val.instant, "naive": naive, "src": src}
    return {"k": "s", "raw": text}


class Doc:
    """État répliqué : feuilles (identifiées par id stable), cellules, droits, historique."""

    def __init__(self, owner):
        self.owner = owner
        self.order = []
        self.names = {}
        self.cells = {}
        self.rights = {}
        self.history = []
        self.seq = 0

    def copy(self):
        d = Doc(self.owner)
        d.order = list(self.order)
        d.names = dict(self.names)
        d.cells = {sid: dict(c) for sid, c in self.cells.items()}
        d.rights = {sid: dict(r) for sid, r in self.rights.items()}
        d.history = list(self.history)
        d.seq = self.seq
        return d

    def sheet_id(self, name):
        for sid in self.order:
            if self.names[sid] == name:
                return sid
        return None

    def right(self, person, sid):
        if person == self.owner:
            return "écriture"
        return self.rights.get(sid, {}).get(person)

    def rec(self, sid, ref):
        return self.cells.get(sid, {}).get(ref)

    def entry(self, sid, ref):
        r = self.rec(sid, ref)
        return r["e"] if r else None

    def apply(self, ch, meta):
        """Applique un changement déjà décidé. meta : opid, au (auteur), seq."""
        t = ch[0]
        if t == "cell":
            sid, ref, entry = ch[1], ch[2], ch[3]
            row = self.cells.setdefault(sid, {})
            row[ref] = {"e": entry, "op": meta["op"], "au": meta["au"], "rev": meta["seq"],
                        "cf": None}
        elif t == "conflict":
            _, sid, ref, entry, by, opid = ch
            row = self.cells.setdefault(sid, {})
            old = row.get(ref) or {"e": None, "op": None, "au": None, "rev": 0, "cf": None}
            row[ref] = dict(old, cf={"e": entry, "by": by, "op": opid})
        elif t == "resolve":
            sid, ref, use = ch[1], ch[2], ch[3]
            row = self.cells.setdefault(sid, {})
            old = row.get(ref)
            if old and old["cf"]:
                if use:
                    row[ref] = {"e": old["cf"]["e"], "op": meta["op"], "au": meta["au"],
                                "rev": meta["seq"], "cf": None}
                else:
                    row[ref] = dict(old, cf=None)
        elif t == "add":
            sid, name, rights = ch[1], ch[2], ch[3]
            if sid not in self.order:
                self.order.append(sid)
            self.names[sid] = name
            self.rights[sid] = dict(rights)
            self.cells.setdefault(sid, {})
        elif t == "del":
            sid = ch[1]
            if sid in self.order:
                self.order.remove(sid)
        elif t == "rename":
            sid, new = ch[1], ch[2]
            old = self.names.get(sid)
            self.names[sid] = new
            if old and old != new:
                self._rewrite_refs(old, new)
        elif t == "right":
            sid, person, level = ch[1], ch[2], ch[3]
            self.rights.setdefault(sid, {})[person] = level

    def _rewrite_refs(self, old, new):
        pat = re.compile(r"(?<![\w'])" + re.escape(old) + r"!")
        for sid, row in self.cells.items():
            for ref, rec in list(row.items()):
                e = rec["e"]
                if e and e["k"] == "f" and pat.search(e["raw"]):
                    raw = pat.sub(new + "!", e["raw"])
                    row[ref] = dict(rec, e=dict(e, raw=raw))

    def apply_commit(self, commit):
        meta = {"op": commit["op"], "au": commit["au"], "seq": commit["seq"]}
        for ch in commit["changes"]:
            self.apply(ch, meta)
        if commit.get("version"):
            self.history.append(commit["version"])
        self.seq = commit["seq"]


class Evaluator:
    """Calcul paresseux sur le graphe des dépendances ; cycle = composante fortement connexe."""

    def __init__(self, doc, now, viewer_tz, override=None):
        self.doc = doc
        self.now = now
        self.viewer_tz = viewer_tz
        self.override = override  # (sid, dict de cellules) pour consultation d'une version
        self.memo = {}
        self.cyclic = set()

    def cells_of(self, sid):
        if self.override and self.override[0] == sid:
            return self.override[1]
        return self.doc.cells.get(sid, {})

    def entry(self, key):
        r = self.cells_of(key[0]).get(key[1])
        return r["e"] if r else None

    def sheet_key(self, sheet, own_sid):
        if sheet is None:
            return own_sid
        sid = self.doc.sheet_id(sheet)
        if sid is None:
            raise CellError("#REF!")
        return sid

    def deps(self, key):
        e = self.entry(key)
        if not e or e["k"] != "f":
            return []
        tree = parse_cached(e["raw"])
        if isinstance(tree, CellError):
            return []
        out = []
        for sheet, ref in refs_of(tree):
            try:
                sid = self.sheet_key(sheet, key[0])
            except CellError:
                continue
            out.append((sid, ref))
        return out

    def find_cyclic(self, start):
        index = {}
        low = {}
        stack = []
        on = set()
        counter = [0]

        def visit(v):
            index[v] = low[v] = counter[0]
            counter[0] += 1
            stack.append(v)
            on.add(v)
            for w in self.deps(v):
                if w not in index:
                    visit(w)
                    low[v] = min(low[v], low[w])
                elif w in on:
                    low[v] = min(low[v], index[w])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in self.deps(v):
                    self.cyclic.update(comp)

        visit(start)

    def value_of(self, key):
        if key in self.memo:
            res = self.memo[key]
            if isinstance(res, CellError):
                raise res
            return res
        try:
            if key in self.cyclic:
                raise CellError("#CIRC!")
            res = self.evaluate(key)
        except CellError as exc:
            self.memo[key] = exc
            raise
        self.memo[key] = res
        return res

    def evaluate(self, key):
        e = self.entry(key)
        if e is None:
            return None
        k = e["k"]
        if k in ("n", "d", "t"):
            if k == "n":
                return e["v"]
            if k == "d":
                return DateValue(e["v"])
            return DateTimeValue(e["v"])
        if k == "s":
            return e["raw"]
        tree = parse_cached(e["raw"])
        if isinstance(tree, CellError):
            raise CellError("#SYNTAXE!")
        res = self.eval_node(tree, key[0])
        return 0 if res is None else res

    def numeric(self, v):
        if v is None:
            return 0
        if isinstance(v, bool):
            raise CellError("#TYPE!")
        if isinstance(v, (int, float)):
            return v
        raise CellError("#TYPE!")

    def eval_node(self, node, own):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "ref":
            sid = self.sheet_key(node[1], own)
            return self.value_of((sid, node[2]))
        if k == "range":
            raise CellError("#TYPE!")
        if k == "neg":
            return -self.numeric(self.eval_node(node[1], own))
        if k == "bin":
            op = node[1]
            a = self.eval_node(node[2], own)
            b = self.eval_node(node[3], own)
            if op == "-" and isinstance(a, (DateTimeValue, DateValue)) and type(a) is type(b):
                if isinstance(a, DateTimeValue):
                    return (a.instant - b.instant).total_seconds() / 86400.0
                return (a.d - b.d).days * 1.0
            x = self.numeric(a)
            y = self.numeric(b)
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if y == 0:
                raise CellError("#DIV/0!")
            return x / y
        if k == "call":
            name, args = node[1], node[2]
            if name == "MAINTENANT" and not args:
                return DateTimeValue(self.now())
            if name == "SOMME":
                total = 0
                for arg in args:
                    if arg[0] == "range":
                        for key in self.range_keys(arg, own):
                            v = self.value_of(key)
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                total += v
                    else:
                        total += self.numeric(self.eval_node(arg, own))
                return total
            raise CellError("#SYNTAXE!")
        raise CellError("#SYNTAXE!")

    def range_keys(self, node, own):
        sid = self.sheet_key(node[1], own)
        a = parse_ref(node[2])
        b = parse_ref(node[3])
        keys = []
        for r in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
            for c in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
                keys.append((sid, ref_of((r, c))))
        return keys

    def result(self, sid, ref):
        """Rend (valeur, code_erreur) pour une cellule."""
        key = (sid, ref)
        self.find_cyclic(key)
        try:
            return self.value_of(key), None
        except CellError as exc:
            return None, exc.code


def display_for(v, viewer_tz, src_tz=None, naive=None):
    if v is None:
        return None
    if isinstance(v, DateTimeValue):
        if naive and src_tz == viewer_tz:
            local = v.instant.astimezone(ZoneInfo(viewer_tz)).replace(tzinfo=None)
            if local.strftime("%Y-%m-%d %H:%M") != naive[:16]:
                return naive[:16]
        return format_dt(v.instant, viewer_tz)
    if isinstance(v, DateValue):
        return v.d.isoformat()
    return v


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


class Network:
    """Réseau simulé : file de messages en vol ; coupure = perte des messages en vol."""

    def __init__(self):
        self.endpoints = {}
        self.queue = []
        self.down = set()

    def register(self, name, endpoint):
        self.endpoints[name] = endpoint

    def connected(self, name):
        return name not in self.down

    def send(self, src, dst, msg):
        if src != "net" and src in self.down:
            return
        if dst in self.down:
            return
        self.queue.append((src, dst, msg))

    def _deliver(self, item):
        src, dst, msg = item
        if dst in self.down or (src != "net" and src in self.down):
            return
        self.endpoints[dst].handle(src, msg)

    def deliver_all(self):
        while self.queue:
            item = self.queue.pop(0)
            self._deliver(item)

    def deliver_from(self, name):
        mine = [i for i in self.queue if i[0] == name]
        self.queue = [i for i in self.queue if i[0] != name]
        for item in mine:
            self._deliver(item)

    def retract(self, name, opid):
        def is_op(m):
            return isinstance(m, dict) and isinstance(m.get("op"), dict) and m["op"].get("opid") == opid
        self.queue = [i for i in self.queue if not (i[0] == name and is_op(i[2]))]

    def disconnect(self, name):
        if name in self.down:
            return
        self.down.add(name)
        self.queue = [i for i in self.queue if i[0] != name and i[1] != name]
        self.send("net", "server", {"t": "gone", "who": name})

    def reconnect(self, name):
        if name not in self.down:
            return
        self.down.discard(name)
        self.endpoints[name].on_reconnect()


def casefold_names(doc, exclude=None):
    return {doc.names[s].casefold() for s in doc.order if s != exclude}


class Server:
    """Séquenceur : ordre de réception = ordre de commit ; décide droits, refus, conflits."""

    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.doc = Doc(owner)
        self.doc.apply(("add", "S0", "Feuille1", {}), {"op": None, "au": None, "seq": 0})
        self.doc.seq = 0
        self.results = {}
        self.cancelled = set()
        self.presence = {}
        self.clients = set()
        net.register("server", self)

    def _broadcast(self, msg):
        for c in sorted(self.clients):
            self.net.send("server", c, msg)

    def handle(self, src, msg):
        t = msg["t"]
        if t == "hello":
            self.clients.add(src)
            pres = {} if msg.get("fresh") else {k: v for k, v in self.presence.items() if k != src}
            self.net.send("server", src, {"t": "snap", "doc": self.doc.copy(), "seq": self.doc.seq,
                                          "presence": pres})
        elif t == "op":
            self.on_op(src, msg["op"])
        elif t == "retract":
            opid = msg["op"]
            hit = self.results.get(opid)
            if hit and hit[0] is not None and hit[0].get("inv"):
                # déjà livrée : compensation par la modification inverse, sans attente locale
                inv = hit[0]["inv"]
                self.on_op(src, {"opid": opid + "~r", "author": src, "base": self.doc.seq,
                                 "changes": inv, "kind": "modification",
                                 "ts": self.clock.now(), "lseq": 0})
            else:
                self.cancelled.add(opid)
        elif t == "presence":
            self.presence[src] = (msg["sheet"], msg["ref"])
            self._broadcast({"t": "presence", "who": src, "sheet": msg["sheet"], "ref": msg["ref"]})
        elif t == "gone":
            who = msg["who"]
            self.clients.discard(who)
            if self.presence.pop(who, None) is not None:
                self._broadcast({"t": "unpresence", "who": who})

    def on_op(self, src, op):
        opid = op["opid"]
        if opid in self.results:
            commit, ack = self.results[opid]
            if commit is not None:
                self.net.send("server", src, commit)
            self.net.send("server", src, ack)
            return
        if opid in self.cancelled:
            return
        work = self.doc.copy()
        seq = self.doc.seq + 1
        meta = {"op": opid, "au": op["author"], "seq": seq}
        author = op["author"]
        accepted = []
        rejects = []
        inv = []
        wrote = None
        for ch in op["changes"]:
            t = ch[0]
            if t == "cell":
                _, sid, ref, entry, sn = ch
                if sid not in work.order:
                    rejects.append({"k": "feuille_supprimee", "sheet": sn, "cell": None})
                    continue
                if work.right(author, sid) != "écriture":
                    rejects.append({"k": "modification_rejetee", "sheet": sn, "cell": ref})
                    continue
                rec = work.rec(sid, ref)
                cur = rec["e"] if rec else None
                if _raw(cur) == _raw(entry):
                    continue
                base = op["base"]
                if rec and rec["au"] not in (None, author) and rec["rev"] > base:
                    ch2 = ("conflict", sid, ref, entry, author, opid)
                    accepted.append(ch2)
                    work.apply(ch2, meta)
                    continue
                accepted.append(ch)
                inv.append(("cell", sid, ref, cur, sn))
                work.apply(ch, meta)
                wrote = wrote or sid
            elif t == "resolve":
                _, sid, ref, use = ch[:4]
                if work.right(author, sid) != "écriture":
                    rejects.append({"k": "droit_insuffisant", "sheet": ch[4], "cell": ref})
                    continue
                rec = work.rec(sid, ref)
                if not (rec and rec["cf"]):
                    continue
                accepted.append(ch[:4])
                work.apply(ch[:4], meta)
                if use:
                    wrote = wrote or sid
            elif t == "add":
                _, sid, name, rights = ch
                if name.casefold() in casefold_names(work):
                    rejects.append({"k": "nom_existant", "sheet": name, "cell": None})
                    continue
                accepted.append(ch)
                work.apply(ch, meta)
            elif t == "del":
                _, sid, name = ch
                if work.right(author, sid) != "écriture":
                    rejects.append({"k": "droit_insuffisant", "sheet": name, "cell": None})
                    continue
                if sid not in work.order or len(work.order) == 1:
                    continue
                accepted.append(ch[:2])
                work.apply(ch[:2], meta)
            elif t == "rename":
                _, sid, new, old = ch
                if work.right(author, sid) != "écriture":
                    rejects.append({"k": "droit_insuffisant", "sheet": old, "cell": None})
                    continue
                if sid not in work.order:
                    continue
                if new.casefold() in casefold_names(work, exclude=sid):
                    rejects.append({"k": "nom_existant", "sheet": new, "cell": None})
                    continue
                accepted.append(ch[:3])
                work.apply(ch[:3], meta)
            elif t == "right":
                _, sid, person, level = ch
                if author != work.owner or person == work.owner or sid not in work.order:
                    continue
                accepted.append(ch)
                work.apply(ch, meta)
        commit = None
        version = None
        if accepted:
            if wrote is not None and op.get("kind") and wrote in work.names:
                version = {
                    "id": f"v{seq}", "seq": seq, "author": author,
                    "kind": "restauration" if op.get("kind") == "restauration" else "modification",
                    "sid": wrote, "name": work.names[wrote],
                    "ts": op["ts"], "lseq": op["lseq"],
                    "snap": {ref: {"e": rec["e"]} for ref, rec in work.cells.get(wrote, {}).items()
                             if rec["e"] is not None},
                }
            if version is not None:
                work.history.append(version)
            work.seq = seq
            commit = {"t": "commit", "op": opid, "au": author, "seq": seq,
                      "changes": accepted, "version": version, "inv": inv}
        self.doc = work
        ack = {"t": "ack", "op": opid, "rejects": rejects}
        self.results[opid] = (commit, ack)
        if commit is not None:
            self._broadcast(commit)
        self.net.send("server", src, ack)


def _raw(e):
    return None if e is None else e["raw"]


class Version:
    def __init__(self, vid, author, timestamp, kind):
        self.id = vid
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


class CSVError(Exception):
    def __init__(self, line):
        super().__init__(line)
        self.line = line


def parse_csv_text(text):
    """Analyse CSV (guillemets, sauts de ligne dans les champs, CRLF). Guillemet non fermé -> CSVError."""
    rows, row, field = [], [], []
    quoted = False
    qline = 0
    line = 1
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quoted:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                quoted = False
                i += 1
                continue
            if ch == "\n":
                line += 1
            field.append(ch)
            i += 1
            continue
        if ch == '"' and not field:
            quoted = True
            qline = line
            i += 1
            continue
        if ch == ",":
            row.append("".join(field))
            field = []
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
            line += 1
            i += 1
            continue
        field.append(ch)
        i += 1
    if quoted:
        raise CSVError(qline)
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows


class Client:
    """Copie locale d'une personne : état confirmé + modifications en attente, édité sans attendre."""

    def __init__(self, net, clock, name, tz, device=None, fresh=True):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.device = device or {"doc": None, "pending": [], "base": 0, "n": 0}
        if self.device["doc"] is None:
            self.device["doc"] = Doc(None)
        self.doc = self.device["doc"]
        self.active_sid = None
        self.undo_stack = []
        self.redo_stack = []
        self.alerts_list = []
        self.presence_map = {}
        self.synced = False
        self.opened = None
        net.register(name, self)
        net.send(name, "server", {"t": "hello", "fresh": fresh})

    def reopen(self):
        """Ferme puis rouvre l'application : seul le stockage de l'appareil survit (copie, attente, compteurs)."""
        return Client(self.net, self.clock, self.name, self.tz, device=self.device, fresh=True)

    # ---------- réseau

    def on_reconnect(self):
        self.synced = False
        self.presence_map = {}
        self.net.send(self.name, "server", {"t": "hello", "fresh": False})

    def handle(self, src, msg):
        t = msg["t"]
        dev = self.device
        if t == "snap":
            self.doc = msg["doc"].copy()
            dev["doc"] = self.doc
            dev["base"] = msg["seq"]
            self.synced = True
            self.presence_map = dict(msg["presence"])
            for op in dev["pending"]:
                self.net.send(self.name, "server", {"t": "op", "op": op})
        elif t == "commit":
            dev["pending"] = [op for op in dev["pending"] if op["opid"] != msg["op"]]
            if self.synced and msg["seq"] > dev["base"]:
                self.doc.apply_commit(msg)
                dev["base"] = msg["seq"]
        elif t == "ack":
            dev["pending"] = [op for op in dev["pending"] if op["opid"] != msg["op"]]
            for r in msg["rejects"]:
                self.alerts_list.append(Alert(r["k"], r["sheet"], r["cell"]))
        elif t == "presence":
            if msg["who"] != self.name:
                self.presence_map[msg["who"]] = (msg["sheet"], msg["ref"])
        elif t == "unpresence":
            self.presence_map.pop(msg["who"], None)

    # ---------- vue locale

    def view(self):
        v = self.doc.copy()
        base = self.device["base"]
        for op in self.device["pending"]:
            meta = {"op": op["opid"], "au": op["author"], "seq": base}
            for ch in op["changes"]:
                v.apply(ch, meta)
        return v

    def _sid(self, sheet):
        v = self.view()
        if sheet is None:
            if self.active_sid in v.order:
                return self.active_sid
            return v.order[0] if v.order else None
        return v.sheet_id(sheet)

    def _writable(self, sid):
        return sid is not None and self.view().right(self.name, sid) == "écriture"

    def _submit(self, changes, kind="modification", quiet=False, action=None, clear_redo=True):
        dev = self.device
        dev["n"] += 1
        opid = f"{self.name}:{dev['n']}"
        op = {"opid": opid, "author": self.name, "base": dev["base"], "changes": changes,
              "kind": kind, "ts": self.clock.now(), "lseq": dev["n"], "quiet": quiet}
        dev["pending"].append(op)
        if self.synced and self.net.connected(self.name):
            self.net.send(self.name, "server", {"t": "op", "op": op})
        if action is not None:
            self.undo_stack.append(dict(action, opid=opid))
            if clear_redo:
                self.redo_stack.clear()
        return opid

    def _evaluator(self):
        v = self.view()
        override = None
        if self.opened is not None:
            override = (self.opened["sid"], self.opened["snap"])
        return Evaluator(v, self.clock.now, self.tz, override)

    # ---------- cellules

    def _write(self, ref, sheet, text):
        if self.opened is not None:
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        ref = norm_ref(ref)
        v = self.view()
        sn = v.names[sid]
        if not self._writable(sid):
            self.alerts_list.append(Alert("droit_insuffisant", sn, ref))
            return
        cur = v.entry(sid, ref)
        entry = None if text in (None, "") else make_entry(text, self.tz)
        if _raw(cur) == _raw(entry):
            return
        ch = ("cell", sid, ref, entry, sn)
        action = {"items": [{"t": "cell", "sid": sid, "ref": ref, "sn": sn, "before": cur, "after": entry}]}
        self._submit([ch], action=action)

    def set_cell(self, ref, text, sheet=None):
        self._write(ref, sheet, text)

    def clear(self, ref, sheet=None):
        self._write(ref, sheet, None)

    def content(self, ref, sheet=None):
        ref = norm_ref(ref)
        if self.opened is not None:
            e = self.opened["snap"].get(ref, {}).get("e")
            return _raw(e)
        sid = self._sid(sheet)
        return _raw(self.view().entry(sid, ref)) if sid is not None else None

    def _result(self, ref, sheet):
        ref = norm_ref(ref)
        sid = self._sid(sheet)
        if sid is None:
            return None, None, None, None
        ev = self._evaluator()
        val, err = ev.result(sid, ref)
        e = ev.entry((sid, ref))
        return val, err, e, sid

    def value(self, ref, sheet=None):
        val, err, e, _ = self._result(ref, sheet)
        if err is not None:
            return err
        naive = e.get("naive") if e and e["k"] == "t" else None
        src = e.get("src") if e and e["k"] == "t" else None
        return display_for(val, self.tz, src, naive)

    def error(self, ref, sheet=None):
        _, err, _, _ = self._result(ref, sheet)
        return err

    def conflict(self, ref, sheet=None):
        if self.opened is not None:
            return None
        ref = norm_ref(ref)
        sid = self._sid(sheet)
        rec = self.view().rec(sid, ref) if sid is not None else None
        if rec and rec["cf"]:
            return Conflict(_raw(rec["cf"]["e"]), rec["cf"]["by"])
        return None

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        if self.opened is not None:
            return
        ref = norm_ref(ref)
        sid = self._sid(sheet)
        if sid is None:
            return
        sn = self.view().names[sid]
        if not self._writable(sid):
            self.alerts_list.append(Alert("droit_insuffisant", sn, ref))
            return
        rec = self.view().rec(sid, ref)
        if not (rec and rec["cf"]):
            return
        self._submit([("resolve", sid, ref, bool(use_discarded), sn)])

    # ---------- feuilles

    def sheets(self):
        v = self.view()
        return [v.names[s] for s in v.order]

    def activate(self, name):
        sid = self.view().sheet_id(name)
        if sid is not None:
            self.active_sid = sid

    def add_sheet(self, name):
        v = self.view()
        if name.casefold() in casefold_names(v):
            self.alerts_list.append(Alert("nom_existant", name, None))
            return
        self.device["n"] += 1
        sid = f"S{self.name}{self.device['n']}"
        rights = {} if self.name == v.owner else {self.name: "écriture"}
        ch = ("add", sid, name, rights)
        action = {"items": [{"t": "add", "sid": sid, "name": name, "rights": rights}]}
        self._submit([ch], action=action)

    def delete_sheet(self, name):
        v = self.view()
        sid = v.sheet_id(name)
        if sid is None:
            return
        if not self._writable(sid):
            self.alerts_list.append(Alert("droit_insuffisant", name, None))
            return
        if len(v.order) <= 1:
            return
        ch = ("del", sid, name)
        action = {"items": [{"t": "del", "sid": sid, "name": name, "rights": dict(v.rights.get(sid, {}))}]}
        self._submit([ch], action=action)

    def rename_sheet(self, old, new):
        v = self.view()
        sid = v.sheet_id(old)
        if sid is None:
            return
        if not self._writable(sid):
            self.alerts_list.append(Alert("droit_insuffisant", old, None))
            return
        if new == old:
            return
        if new.casefold() in casefold_names(v, exclude=sid):
            self.alerts_list.append(Alert("nom_existant", new, None))
            return
        ch = ("rename", sid, new, old)
        action = {"items": [{"t": "rename", "sid": sid, "old": old, "new": new}]}
        self._submit([ch], action=action)

    def set_right(self, person, sheet, level):
        v = self.view()
        if self.name != v.owner or not self.synced or not self.net.connected(self.name):
            return
        sid = v.sheet_id(sheet)
        if sid is None or person == v.owner:
            return
        if v.right(person, sid) == level:
            return
        self._submit([("right", sid, person, level)], quiet=True)

    def right(self, person, sheet):
        sid = self.view().sheet_id(sheet)
        return self.view().right(person, sid) if sid is not None else None

    # ---------- annulation / rétablissement

    def _changes_for(self, items, redo):
        out = []
        for it in items:
            t = it["t"]
            if t == "cell":
                out.append(("cell", it["sid"], it["ref"], it["after"] if redo else it["before"], it["sn"]))
            elif t == "add":
                out.append(("add", it["sid"], it["name"], it["rights"]) if redo
                           else ("del", it["sid"], it["name"]))
            elif t == "del":
                out.append(("del", it["sid"], it["name"]) if redo
                           else ("add", it["sid"], it["name"], it["rights"]))
            elif t == "rename":
                out.append(("rename", it["sid"], it["new"], it["old"]) if redo
                           else ("rename", it["sid"], it["old"], it["new"]))
        return out

    def _items_writable(self, items):
        v = self.view()
        for it in items:
            if not self._writable(it["sid"]):
                sn = v.names.get(it["sid"]) or it.get("sn") or it.get("name") or it.get("old")
                self.alerts_list.append(Alert("droit_insuffisant", sn, None))
                return False
        return True

    def undo(self):
        if self.opened is not None or not self.undo_stack:
            return
        action = self.undo_stack.pop()
        items = action["items"]
        if not self._items_writable(items):
            return
        dev = self.device
        pending_ids = [op["opid"] for op in dev["pending"]]
        if action["opid"] in pending_ids:
            dev["pending"] = [op for op in dev["pending"] if op["opid"] != action["opid"]]
            self.net.retract(self.name, action["opid"])
            if self.synced and self.net.connected(self.name):
                self.net.send(self.name, "server", {"t": "retract", "op": action["opid"]})
            self.redo_stack.append(action)
            return
        v = self.view()
        for it in items:
            if it["t"] == "cell":
                rec = v.rec(it["sid"], it["ref"])
                if (rec["op"] if rec else None) != action["opid"]:
                    self.alerts_list.append(Alert("annulation_impossible", it["sn"], it["ref"]))
                    return
        inverse = self._changes_for(list(reversed(items)), redo=False)
        self._submit(inverse, action=None)
        self.redo_stack.append(action)

    def redo(self):
        if self.opened is not None or not self.redo_stack:
            return
        action = self.redo_stack.pop()
        if not self._items_writable(action["items"]):
            return
        changes = self._changes_for(action["items"], redo=True)
        self._submit(changes, action={"items": action["items"]}, clear_redo=False)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    # ---------- collaboration / présence / statut

    def select(self, ref, sheet=None):
        if not self.synced or not self.net.connected(self.name):
            return
        sid = self._sid(sheet)
        if sid is None:
            return
        sn = self.view().names[sid]
        self.net.send(self.name, "server", {"t": "presence", "sheet": sn, "ref": norm_ref(ref)})

    def presence(self):
        if not self.net.connected(self.name):
            return {}
        return {k: tuple(v) for k, v in self.presence_map.items() if k != self.name}

    def connection_status(self):
        return "en ligne" if self.net.connected(self.name) else "hors ligne"

    def pending_count(self):
        return sum(1 for op in self.device["pending"] if not op.get("quiet"))

    def alerts(self):
        return list(self.alerts_list)

    def set_timezone(self, tz):
        self.tz = tz

    # ---------- historique

    def history(self, sheet=None):
        sid = self._sid(sheet)
        vs = [v for v in self.doc.history if v["sid"] == sid]
        vs.sort(key=lambda v: (v["ts"], v["lseq"]), reverse=True)
        return [Version(v["id"], v["author"], format_dt(v["ts"], self.tz), v["kind"]) for v in vs]

    def open_version(self, vid):
        for v in self.doc.history:
            if v["id"] == vid:
                self.opened = v
                return

    def close_version(self):
        self.opened = None

    def restore_version(self, vid):
        if self.opened is not None:
            return
        ver = next((v for v in self.doc.history if v["id"] == vid), None)
        if ver is None:
            return
        sid = ver["sid"]
        v = self.view()
        if not self._writable(sid) or sid not in v.order:
            return
        sn = v.names[sid]
        changes, items = [], []
        refs = set(v.cells.get(sid, {})) | set(ver["snap"])
        for ref in sorted(refs):
            cur = v.entry(sid, ref)
            target = ver["snap"].get(ref, {}).get("e")
            if _raw(cur) != _raw(target):
                changes.append(("cell", sid, ref, target, sn))
                items.append({"t": "cell", "sid": sid, "ref": ref, "sn": sn, "before": cur, "after": target})
        if ver["name"] != sn and ver["name"].casefold() not in casefold_names(v, exclude=sid):
            changes.append(("rename", sid, ver["name"], sn))
            items.append({"t": "rename", "sid": sid, "old": sn, "new": ver["name"]})
        if changes:
            self._submit(changes, kind="restauration", action={"items": items})

    # ---------- export / import CSV

    def export_csv(self):
        sid = self._sid(None)
        if sid is None:
            return b""
        v = self.view()
        ev = self._evaluator()
        cells = {ref: rec for ref, rec in v.cells.get(sid, {}).items() if rec["e"] is not None}
        if not cells:
            return b""
        rc = [parse_ref(r) for r in cells]
        max_row = max(r for r, _ in rc)
        max_col = max(c for _, c in rc)
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        for r in range(1, max_row + 1):
            if not any((r, c) in set(rc) for c in range(1, max_col + 1)):
                continue
            fields = []
            for c in range(1, max_col + 1):
                ref = ref_of((r, c))
                if ref not in cells:
                    fields.append("")
                    continue
                val, err = ev.result(sid, ref)
                if err is not None:
                    fields.append(err)
                elif val is None:
                    fields.append("")
                elif isinstance(val, DateTimeValue):
                    fields.append(format_iso(val.instant, self.tz))
                elif isinstance(val, DateValue):
                    fields.append(val.d.isoformat())
                else:
                    fields.append(str(val))
            w.writerow(fields)
        return out.getvalue().encode("utf-8")

    def import_csv(self, data):
        if self.opened is not None:
            return
        sid = self._sid(None)
        if sid is None:
            return
        v = self.view()
        sn = v.names[sid]
        if not self._writable(sid):
            self.alerts_list.append(Alert("droit_insuffisant", sn, None))
            return
        try:
            rows = parse_csv_text(data.decode("utf-8-sig"))
        except CSVError as exc:
            self.alerts_list.append(Alert("csv_invalide", sn, None, exc.line))
            return
        changes, items = [], []
        for r, row in enumerate(rows):
            for c, field in enumerate(row):
                ref = ref_of((r + 1, c + 1))
                entry = None if field == "" else make_entry(field, self.tz, literal=True)
                cur = v.entry(sid, ref)
                if _raw(cur) == _raw(entry):
                    continue
                changes.append(("cell", sid, ref, entry, sn))
                items.append({"t": "cell", "sid": sid, "ref": ref, "sn": sn, "before": cur, "after": entry})
        self._submit(changes, action={"items": items} if items else None)
