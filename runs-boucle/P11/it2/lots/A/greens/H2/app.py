"""Classeur collaboratif hors ligne — couche code (sonde P11).

Morceau 1 : temps simulé, réseau simulé en mémoire, analyseur de formules.
"""
import csv
import io
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
# chaînes de dépendances profondes : l'évaluation est récursive sur le graphe
sys.setrecursionlimit(20000)


# ------------------------------------------------------------------ temps

class Clock:
    def __init__(self, start):
        assert start.tzinfo is not None
        self._now = start.astimezone(UTC)

    def now(self):
        return self._now

    def advance(self, delta):
        self._now = self._now + delta


# ------------------------------------------------------------------ réseau

class Network:
    """Réseau simulé : messages en vol, livrés dans l'ordre demandé par le test."""

    def __init__(self):
        self._endpoints = {}       # nom -> callback(msg)
        self._objs = {}            # nom -> objet propriétaire (hooks on_reconnect / on_peer_offline)
        self._inflight = []        # liste de (src, dst, msg)
        self._connected = {}       # nom -> bool
        self._seq = 0

    def register(self, name, handler, obj=None):
        self._endpoints[name] = handler
        self._objs[name] = obj
        self._connected.setdefault(name, True)

    def is_connected(self, name):
        return self._connected.get(name, True)

    def send(self, src, dst, msg):
        # un message émis hors ligne n'est jamais mis en vol
        if not self.is_connected(src):
            return False
        self._inflight.append((src, dst, msg))
        return True

    def disconnect(self, name):
        self._connected[name] = False
        # les messages en vol depuis ou vers ce nom sont perdus
        self._inflight = [m for m in self._inflight if m[0] != name and m[1] != name]
        server = self._objs.get("server")
        if server is not None and hasattr(server, "on_peer_offline"):
            server.on_peer_offline(name)

    def reconnect(self, name):
        self._connected[name] = True
        owner = self._objs.get(name)
        if owner is not None and hasattr(owner, "on_reconnect"):
            owner.on_reconnect()

    def recall(self, src, op_id):
        """Retire de la file les envois d'une opération encore en vol (annulation avant envoi)."""
        def mine(m):
            return m[0] == src and m[2][0] == "op" and m[2][1]["id"] == op_id
        self._inflight = [m for m in self._inflight if not mine(m)]

    def _deliver_one(self, item):
        src, dst, msg = item
        if not self.is_connected(src) or not self.is_connected(dst):
            return
        handler = self._endpoints.get(dst)
        if handler is not None:
            handler(src, msg)

    def deliver_all(self):
        # livraison FIFO jusqu'au repos
        guard = 0
        while self._inflight:
            guard += 1
            if guard > 1_000_000:
                raise RuntimeError("réseau non stabilisé")
            item = self._inflight.pop(0)
            self._deliver_one(item)

    def deliver_from(self, name):
        """Livre uniquement les messages en vol émis par `name`, en premier."""
        mine = [m for m in self._inflight if m[0] == name]
        self._inflight = [m for m in self._inflight if m[0] != name]
        for item in mine:
            self._deliver_one(item)


# ------------------------------------------------------------------ erreurs

class CellError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


TYPE_ERR = "#TYPE!"
DIV0_ERR = "#DIV/0!"
SYNTAX_ERR = "#SYNTAXE!"
CIRC_ERR = "#CIRC!"
REF_ERR = "#REF!"


# ------------------------------------------------------------------ analyseur

_REF_RE = re.compile(r"(?:(?P<sheet>[^\W\d]\w*)!)?\$?(?P<col>[A-Za-z]{1,3})\$?(?P<row>\d+)")
_SHEETREF_RE = re.compile(r"(?P<sheet>[^\W\d]\w*)!")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_FUNC_RE = re.compile(r"[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ_0-9]*")


def col_to_index(col):
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def index_to_col(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d+)", ref)
    if not m:
        raise ValueError(f"référence invalide : {ref!r}")
    return m.group(1).upper(), int(m.group(2))


class _Tok:
    def __init__(self, kind, val):
        self.kind = kind
        self.val = val


def tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c in "+-*/(),:":
            toks.append(_Tok(c, c))
            i += 1
            continue
        m = _NUM_RE.match(src, i)
        if m and not (i > 0 and (src[i - 1].isalnum() or src[i - 1] == "_") and src[i - 1] not in "+-*/(,"):
            toks.append(_Tok("num", float(m.group(0)) if "." in m.group(0) else int(m.group(0))))
            i = m.end()
            continue
        # identifiant : nom de feuille, référence, fonction
        m = re.compile(r"(?:([^\W\d]\w*)!)?\$?([A-Za-z]{1,3})\$?(\d+)(?![\w(])").match(src, i)
        if m:
            toks.append(_Tok("ref", (m.group(1), m.group(2).upper(), int(m.group(3)))))
            i = m.end()
            continue
        m = re.compile(r"([^\W\d]\w*)!").match(src, i)
        if m:
            # nom de feuille sans référence complète : erreur de syntaxe
            raise CellError(SYNTAX_ERR)
        m = _FUNC_RE.match(src, i)
        if m:
            toks.append(_Tok("name", m.group(0)))
            i = m.end()
            continue
        raise CellError(SYNTAX_ERR)
    toks.append(_Tok("eof", None))
    return toks


class _Parser:
    """Grammaire : expr := terme (('+'|'-') terme)* ; terme := unaire (('*'|'/') unaire)* ;
    unaire := '-' unaire | atome ; atome := num | ref | ref ':' ref | nom '(' args ')' | '(' expr ')'."""

    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def take(self, kind=None):
        t = self.toks[self.i]
        if kind is not None and t.kind != kind:
            raise CellError(SYNTAX_ERR)
        self.i += 1
        return t

    def parse(self):
        node = self.expr()
        if self.peek().kind != "eof":
            raise CellError(SYNTAX_ERR)
        return node

    def expr(self):
        node = self.term()
        while self.peek().kind in ("+", "-"):
            op = self.take().kind
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek().kind in ("*", "/"):
            op = self.take().kind
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek().kind == "-":
            self.take()
            return ("neg", self.unary())
        return self.atom()

    def atom(self):
        t = self.peek()
        if t.kind == "num":
            self.take()
            return ("num", t.val)
        if t.kind == "ref":
            self.take()
            sheet, col, row = t.val
            if self.peek().kind == ":":
                self.take()
                t2 = self.take("ref")
                s2, c2, r2 = t2.val
                if s2 is not None and sheet is not None and s2 != sheet:
                    raise CellError(REF_ERR)
                return ("range", sheet or s2, col, row, c2, r2)
            return ("ref", sheet, col, row)
        if t.kind == "name":
            self.take()
            self.take("(")
            args = []
            if self.peek().kind != ")":
                args.append(self.expr())
                while self.peek().kind == ",":
                    self.take()
                    args.append(self.expr())
            self.take(")")
            return ("call", t.val.upper(), args)
        if t.kind == "(":
            self.take()
            node = self.expr()
            self.take(")")
            return node
        raise CellError(SYNTAX_ERR)


def parse_formula(text):
    """text commence par '=' ; renvoie l'AST ou lève CellError(SYNTAX_ERR)."""
    return _Parser(tokenize(text[1:])).parse()


def ast_refs(node, out=None):
    """Références (feuille_ou_None, colonne, ligne) ; les plages sont développées en cellules."""
    if out is None:
        out = []
    kind = node[0]
    if kind == "ref":
        out.append((node[1], node[2], node[3]))
    elif kind == "range":
        sheet, c1, r1, c2, r2 = node[1], node[2], node[3], node[4], node[5]
        ci1, ci2 = sorted((col_to_index(c1), col_to_index(c2)))
        ri1, ri2 = sorted((r1, r2))
        for ci in range(ci1, ci2 + 1):
            for ri in range(ri1, ri2 + 1):
                out.append((sheet, index_to_col(ci), ri))
    elif kind == "bin":
        ast_refs(node[2], out)
        ast_refs(node[3], out)
    elif kind == "neg":
        ast_refs(node[1], out)
    elif kind == "call":
        for a in node[2]:
            ast_refs(a, out)
    return out


def rename_refs(node, old, new):
    """Réécrit les références à la feuille `old` vers `new` (nouvel AST)."""
    kind = node[0]
    if kind == "ref":
        return ("ref", new if node[1] == old else node[1], node[2], node[3])
    if kind == "range":
        return ("range", new if node[1] == old else node[1], node[2], node[3], node[4], node[5])
    if kind == "bin":
        return ("bin", node[1], rename_refs(node[2], old, new), rename_refs(node[3], old, new))
    if kind == "neg":
        return ("neg", rename_refs(node[1], old, new))
    if kind == "call":
        return ("call", node[1], [rename_refs(a, old, new) for a in node[2]])
    return node


def ast_to_text(node):
    kind = node[0]
    if kind == "num":
        return str(node[1])
    if kind == "ref":
        pre = f"{node[1]}!" if node[1] else ""
        return f"{pre}{node[2]}{node[3]}"
    if kind == "range":
        pre = f"{node[1]}!" if node[1] else ""
        return f"{pre}{node[2]}{node[3]}:{node[4]}{node[5]}"
    if kind == "bin":
        return f"{ast_to_text(node[2])}{node[1]}{ast_to_text(node[3])}"
    if kind == "neg":
        return f"-{ast_to_text(node[1])}"
    if kind == "call":
        return f"{node[1]}({','.join(ast_to_text(a) for a in node[2])})"
    raise ValueError(kind)


# ------------------------------------------------------------------ contenu littéral

_INT_RE = re.compile(r"-?\d+")
_DEC_RE = re.compile(r"-?\d+\.\d+")
_DT_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})?"
)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_literal(raw, lit, tz_name):
    """Valeur d'un contenu non formule.

    Un contenu saisi sans décalage horaire est interprété dans le fuseau de son auteur (`tz_name`) ;
    le texte lui-même reste inchangé dans la cellule.
    """
    if lit:
        return raw
    if _INT_RE.fullmatch(raw):
        return int(raw)
    if _DEC_RE.fullmatch(raw):
        return float(raw)
    if _DATE_RE.fullmatch(raw):
        return date.fromisoformat(raw)
    m = _DT_RE.fullmatch(raw)
    if m:
        y, mo, d, h, mi, s, off = m.groups()
        naive = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
        if off is None:
            return naive.replace(tzinfo=ZoneInfo(tz_name))
        if off == "Z":
            off = "+00:00"
        return naive.replace(tzinfo=timezone(_parse_offset(off)))
    return raw


def _parse_offset(text):
    sign = -1 if text[0] == "-" else 1
    hh, mm = text[1:].split(":")
    return sign * timedelta(hours=int(hh), minutes=int(mm))


def display_value(v, viewer_tz):
    """Valeur affichée (ou exportée) pour une personne dans son fuseau."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(viewer_tz)).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return v


def export_value(v, viewer_tz):
    """Forme d'export CSV : date-heure avec décalage ISO 8601 dans le fuseau du lecteur."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.astimezone(ZoneInfo(viewer_tz)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    return str(v)


# ------------------------------------------------------------------ évaluation

class Workbook:
    """Contenu d'un classeur : feuilles ordonnées et cellules (raw, lit, tz_auteur)."""

    def __init__(self):
        self.sheets = []           # noms, dans l'ordre d'affichage
        self.cells = {}            # (feuille, col, ligne) -> (raw, lit, tz)

    def has_sheet(self, name):
        return name in self.sheets

    def get(self, sheet, col, row):
        return self.cells.get((sheet, col, row))

    def put(self, sheet, col, row, raw, lit, tz):
        if raw is None or raw == "":
            self.cells.pop((sheet, col, row), None)
        else:
            self.cells[(sheet, col, row)] = (raw, lit, tz)

    def clear_sheet(self, sheet):
        for k in [k for k in self.cells if k[0] == sheet]:
            del self.cells[k]

    def copy(self):
        w = Workbook()
        w.sheets = list(self.sheets)
        w.cells = dict(self.cells)
        return w

    def formula_graph(self):
        """Graphe des dépendances des formules : nœud -> ensemble de cellules référencées."""
        graph = {}
        for (sheet, col, row), (raw, lit, _tz) in self.cells.items():
            if lit or not raw.startswith("="):
                continue
            try:
                ast = parse_formula(raw)
            except CellError:
                continue
            deps = set()
            for s, c, r in ast_refs(ast):
                deps.add((s or sheet, c, r))
            graph[(sheet, col, row)] = deps
        return graph


def cyclic_cells(graph):
    """Cellules appartenant à un cycle (composante fortement connexe de taille > 1 ou boucle).

    Tarjan itératif : les chaînes profondes ne doivent pas épuiser la pile.
    """
    index = {}
    low = {}
    on_stack = set()
    stack = []
    result = set()
    counter = [0]

    for root in graph:
        if root in index:
            continue
        work = [(root, iter(graph.get(root, ())))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in graph:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(graph.get(nxt, ()))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    x = stack.pop()
                    on_stack.discard(x)
                    comp.append(x)
                    if x == node:
                        break
                if len(comp) > 1 or node in graph.get(node, ()):
                    result.update(comp)
    return result


class _Ctx:
    def __init__(self, wb, clock, viewer_tz):
        self.wb = wb
        self.clock = clock
        self.viewer_tz = viewer_tz
        self.cyclic = cyclic_cells(wb.formula_graph())
        self.memo = {}


def _cell(ctx, sheet, col, row):
    key = (sheet, col, row)
    if key in ctx.cyclic:
        raise CellError(CIRC_ERR)
    if key in ctx.memo:
        v = ctx.memo[key]
        if isinstance(v, CellError):
            raise v
        return v
    ent = ctx.wb.get(sheet, col, row)
    if ent is None:
        return None
    raw, lit, tz = ent
    if lit or not raw.startswith("="):
        return parse_literal(raw, lit, tz)
    try:
        v = _eval(ctx, parse_formula(raw), sheet)
    except CellError as e:
        ctx.memo[key] = e
        raise
    ctx.memo[key] = v
    return v


def _num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        raise CellError(TYPE_ERR)
    if isinstance(v, (int, float)):
        return v
    raise CellError(TYPE_ERR)


def _eval(ctx, node, cur):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        sheet = node[1] or cur
        if not ctx.wb.has_sheet(sheet):
            raise CellError(REF_ERR)
        v = _cell(ctx, sheet, node[2], node[3])
        # une cellule vide vaut zéro dans un calcul (cf. A09)
        return 0 if v is None else v
    if kind == "range":
        sheet = node[1] or cur
        if not ctx.wb.has_sheet(sheet):
            raise CellError(REF_ERR)
        return [_cell_or_none(ctx, sheet, c, r) for c, r in _range_cells(node)]
    if kind == "neg":
        return -_num(_eval(ctx, node[1], cur))
    if kind == "bin":
        return _binop(node[1], _eval(ctx, node[2], cur), _eval(ctx, node[3], cur))
    if kind == "call":
        return _call(ctx, node[1], node[2], cur)
    raise CellError(SYNTAX_ERR)


def _cell_or_none(ctx, sheet, col, row):
    return _cell(ctx, sheet, col, row)


def _range_cells(node):
    c1, r1, c2, r2 = node[2], node[3], node[4], node[5]
    ci1, ci2 = sorted((col_to_index(c1), col_to_index(c2)))
    ri1, ri2 = sorted((r1, r2))
    for ci in range(ci1, ci2 + 1):
        for ri in range(ri1, ri2 + 1):
            yield index_to_col(ci), ri


def _binop(op, a, b):
    if op == "-" and isinstance(a, datetime) and isinstance(b, datetime):
        # temps réel écoulé : soustraction en UTC (les deux valeurs peuvent partager un fuseau
        # dont le décalage change entre elles, passage à l'heure d'été ou d'hiver)
        return (a.astimezone(UTC) - b.astimezone(UTC)).total_seconds() / 86400
    if op == "-" and isinstance(a, date) and isinstance(b, date) and not isinstance(a, datetime) \
            and not isinstance(b, datetime):
        return (a - b).days
    a = _num(a)
    b = _num(b)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise CellError(DIV0_ERR)
        return a / b
    raise CellError(SYNTAX_ERR)


def _call(ctx, name, args, cur):
    if name == "MAINTENANT":
        if args:
            raise CellError(SYNTAX_ERR)
        return ctx.clock.now()
    if name == "SOMME":
        total = 0
        for a in args:
            if a[0] == "range":
                for v in _eval(ctx, a, cur):
                    if v is None or isinstance(v, str):
                        continue
                    total = _binop("+", total, _num(v))
            else:
                total = _binop("+", total, _num(_eval(ctx, a, cur)))
        return total
    raise CellError(SYNTAX_ERR)


def evaluate_cell(wb, clock, viewer_tz, sheet, col, row):
    """Valeur affichée d'une cellule pour une personne : (valeur, erreur)."""
    ctx = _Ctx(wb, clock, viewer_tz)
    try:
        v = _cell(ctx, sheet, col, row)
    except CellError as e:
        return None, e.code
    return display_value(v, viewer_tz), None


def raw_value(wb, clock, sheet, col, row):
    """Valeur Python brute (pour export et calculs) : (valeur, erreur)."""
    ctx = _Ctx(wb, clock, "UTC")
    try:
        return _cell(ctx, sheet, col, row), None
    except CellError as e:
        return None, e.code


# ------------------------------------------------------------------ document répliqué

W = "écriture"
R = "lecture"


def same_content(a, b):
    """Même contenu saisi (le fuseau de l'auteur ne compte pas pour la comparaison de texte)."""
    if a is None or b is None:
        return a is b
    return a[0] == b[0] and a[1] == b[1]


def cell_name(c, r):
    return f"{c}{r}"


class Doc:
    """État partagé d'un classeur, tel que le voit une copie (serveur ou personne)."""

    def __init__(self):
        self.owner = None
        self.sheets = []           # [sid, nom], ordre d'affichage
        self.cells = {}            # (sid, col, row) -> (raw, lit, tz)
        self.seq = {}              # (sid, col, row) -> numéro de la dernière écriture acceptée
        self.last = {}             # (sid, col, row) -> auteur de cette dernière écriture
        self.conflicts = {}        # (sid, col, row) -> {"discarded": rec, "by": nom}
        self.rights = {}           # (sid, personne) -> niveau
        self.versions = {}         # sid -> [entrées]
        self.vcount = 0
        self.applied = set()       # identifiants d'opérations déjà traitées
        self.seqnum = 0

    def copy(self):
        d = Doc()
        d.owner = self.owner
        d.sheets = [list(s) for s in self.sheets]
        d.cells = dict(self.cells)
        d.seq = dict(self.seq)
        d.last = dict(self.last)
        d.conflicts = {k: dict(v) for k, v in self.conflicts.items()}
        d.rights = dict(self.rights)
        d.versions = {k: list(v) for k, v in self.versions.items()}
        d.vcount = self.vcount
        d.applied = set(self.applied)
        d.seqnum = self.seqnum
        return d

    def name_of(self, sid):
        for s, n in self.sheets:
            if s == sid:
                return n
        return None

    def sid_of(self, name):
        for s, n in self.sheets:
            if n == name:
                return s
        return None

    def level(self, person, sid):
        if person == self.owner:
            return W
        return self.rights.get((sid, person))

    def is_dup(self, name, exclude=None):
        low = name.casefold()
        return any(s != exclude and n.casefold() == low for s, n in self.sheets)

    def to_workbook(self):
        """Vue par noms de feuilles, pour l'évaluateur."""
        wb = Workbook()
        names = {s: n for s, n in self.sheets}
        wb.sheets = [n for _, n in self.sheets]
        for (sid, c, r), rec in self.cells.items():
            if sid in names:
                wb.cells[(names[sid], c, r)] = rec
        return wb


def apply_effects(doc, effects, seq):
    """Applique des effets à un document. Déterministe : même base + mêmes effets = même résultat."""
    for eff in effects:
        t = eff[0]
        if t == "cell":
            _, key, rec, conflict, touch = eff
            if rec is None:
                doc.cells.pop(key, None)
            else:
                doc.cells[key] = rec
            if conflict is None:
                doc.conflicts.pop(key, None)
            else:
                doc.conflicts[key] = conflict
            if touch and seq is not None:
                doc.seq[key] = seq
                doc.last[key] = touch
        elif t == "sheet_add":
            _, sid, name = eff
            doc.sheets.append([sid, name])
        elif t == "sheet_del":
            sid = eff[1]
            doc.sheets = [s for s in doc.sheets if s[0] != sid]
            for store in (doc.cells, doc.seq, doc.last, doc.conflicts):
                for k in [k for k in store if k[0] == sid]:
                    del store[k]
            for k in [k for k in doc.rights if k[0] == sid]:
                del doc.rights[k]
            doc.versions.pop(sid, None)
        elif t == "sheet_rename":
            _, sid, old, new = eff
            for s in doc.sheets:
                if s[0] == sid:
                    s[1] = new
            for key, (raw, lit, tz) in list(doc.cells.items()):
                if lit or not raw.startswith("="):
                    continue
                try:
                    ast = parse_formula(raw)
                except CellError:
                    continue
                doc.cells[key] = ("=" + ast_to_text(rename_refs(ast, old, new)), lit, tz)
        elif t == "right":
            _, sid, person, level = eff
            if level is None:
                doc.rights.pop((sid, person), None)
            else:
                doc.rights[(sid, person)] = level
        elif t == "version":
            _, sid, author, instant, vkind = eff
            doc.vcount += 1
            name = doc.name_of(sid)
            snap = {(c, r): rec for (s, c, r), rec in doc.cells.items() if s == sid}
            entry = {"id": f"v{doc.vcount}", "n": doc.vcount, "sid": sid, "author": author,
                     "instant": instant, "kind": vkind, "name": name, "cells": snap}
            doc.versions.setdefault(sid, []).append(entry)
        else:
            raise ValueError(t)


def _cellname_of(cells):
    if not cells:
        return None
    c, r, _ = cells[0]
    return cell_name(c, r)


def decide(doc, op, seq):
    """Décision du serveur sur une opération : (effets, rejet). Rejet = (raison, feuille, cellule)."""
    kind = op["kind"]
    author = op["author"]

    if kind == "addsheet":
        if doc.is_dup(op["name"]):
            return [], ("nom", op["name"], None)
        return [("sheet_add", op["sid"], op["name"]), ("right", op["sid"], author, W)], None

    sid = op["sid"]
    cur_name = doc.name_of(sid)

    if kind == "undelete":
        if cur_name is not None:
            return [], None
        eff = [("sheet_add", sid, op["name"])]
        eff += [("right", sid, p, lvl) for p, lvl in op["rights"]]
        eff += [("cell", (sid, c, r), rec, None, False) for c, r, rec in op["cells"]]
        return eff, None

    if kind == "right":
        if author != doc.owner or cur_name is None:
            return [], None
        if doc.rights.get((sid, op["person"])) == op["level"]:
            return [], None
        return [("right", sid, op["person"], op["level"])], None

    if cur_name is None:
        if kind == "delsheet":
            return [], None
        return [], ("feuille_supprimee", op.get("sheet_name"), _cellname_of(op.get("cells", [])))

    if kind == "delsheet":
        if doc.level(author, sid) != W:
            return [], ("droit", cur_name, None)
        if len(doc.sheets) <= 1:
            return [], None
        return [("sheet_del", sid)], None

    if kind == "rename":
        if doc.level(author, sid) != W:
            return [], ("droit", cur_name, None)
        new = op["name"]
        if new == cur_name:
            return [], None
        if doc.is_dup(new, exclude=sid):
            return [], ("nom", new, None)
        return [("sheet_rename", sid, cur_name, new)], None

    if kind == "resolve":
        key = (sid, op["col"], op["row"])
        conf = doc.conflicts.get(key)
        if conf is None:
            return [], None
        cell = cell_name(op["col"], op["row"])
        if doc.level(author, sid) != W:
            return [], ("droit", cur_name, cell)
        cur = doc.cells.get(key)
        new = conf["discarded"] if op["use"] else cur
        eff = [("cell", key, new, None, author)]
        if not same_content(new, cur):
            eff.append(("version", sid, author, op["ts"], "modification"))
        return eff, None

    if kind == "cells":
        cells = op["cells"]
        cell0 = _cellname_of(cells)
        if doc.level(author, sid) != W:
            return [], ("droit", cur_name, cell0)
        eff = []
        new_name = op.get("name")
        if new_name and new_name != cur_name:
            if doc.is_dup(new_name, exclude=sid):
                return [], ("nom", new_name, None)
            eff.append(("sheet_rename", sid, cur_name, new_name))
        changed = False
        for c, r, rec in cells:
            key = (sid, c, r)
            cur = doc.cells.get(key)
            if same_content(cur, rec):
                continue
            # concurrente : écrite par un autre depuis la base de l'opération ;
            # les écritures successives d'une même personne ne se font jamais concurrence
            concurrent = (doc.seq.get(key, 0) > op["base"].get((c, r), 0)
                          and doc.last.get(key) != author)
            if concurrent and op.get("strict"):
                return [], ("annulation", cur_name, cell_name(c, r))
            if concurrent:
                # le serveur garde sa valeur, la valeur reçue est écartée et signalée
                eff.append(("cell", key, cur, {"discarded": rec, "by": author}, False))
            else:
                eff.append(("cell", key, rec, None, author))
                changed = True
        if changed or (new_name and new_name != cur_name and changed):
            eff.append(("version", sid, author, op["ts"], op.get("vkind", "modification")))
        return eff, None

    return [], None


# ------------------------------------------------------------------ serveur

class Server:
    """Copie canonique : tranche les écritures concurrentes et diffuse les décisions."""

    def __init__(self, net, clock, owner):
        self.net = net
        self.clock = clock
        self.doc = Doc()
        self.doc.owner = owner
        self.doc.sheets = [[uuid.uuid4().hex, "Feuille1"]]
        self.subs = set()
        self.presence = {}
        net.register("server", self._on_msg, self)

    def _broadcast(self, msg):
        for name in sorted(self.subs):
            self.net.send("server", name, msg)

    def _on_msg(self, src, msg):
        tag = msg[0]
        if tag == "hello":
            self.subs.add(src)
            self.net.send("server", src, ("snapshot", self.doc.copy(), dict(self.presence)))
        elif tag == "op":
            self._on_op(msg[1])
        elif tag == "right":
            self._on_right(msg[1])
        elif tag == "presence":
            _, sheet, ref = msg
            self.presence[src] = (sheet, ref)
            self._broadcast(("presence", dict(self.presence)))

    def on_peer_offline(self, name):
        if name in self.presence:
            del self.presence[name]
            self._broadcast(("presence", dict(self.presence)))

    def _on_op(self, op):
        if op["id"] in self.doc.applied:
            return
        self.doc.seqnum += 1
        seq = self.doc.seqnum
        effects, reject = decide(self.doc, op, seq)
        apply_effects(self.doc, effects, seq)
        self.doc.applied.add(op["id"])
        ev = {"seq": seq, "id": op["id"], "author": op["author"], "kind": op["kind"],
              "effects": effects, "reject": reject}
        self._broadcast(("event", ev))

    def _on_right(self, op):
        if op["author"] != self.doc.owner:
            return
        effects, _ = decide(self.doc, op, None)
        if not effects:
            return
        apply_effects(self.doc, effects, None)
        ev = {"seq": None, "id": None, "author": op["author"], "kind": "right",
              "effects": effects, "reject": None}
        self._broadcast(("event", ev))


# ------------------------------------------------------------------ objets exposés

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
    def __init__(self, vid, author, timestamp, kind):
        self.id = vid
        self.author = author
        self.timestamp = timestamp
        self.kind = kind


_REJECT_ALERT = {
    "droit": "modification_rejetee",
    "feuille_supprimee": "feuille_supprimee",
    "annulation": "annulation_impossible",
    "nom": "nom_existant",
}


# ------------------------------------------------------------------ client

class Client:
    """Copie locale d'une personne : édite sans attendre, envoie ce qui est en attente."""

    def __init__(self, net, clock, name, tz="UTC", storage=None):
        self.net = net
        self.clock = clock
        self.name = name
        self.tz = tz
        self.storage = storage if storage is not None else {}
        if "base" in self.storage:
            self.base = self.storage["base"].copy()
            self.pending = [dict(p) for p in self.storage.get("pending", [])]
        else:
            self.base = Doc()
            self.pending = []
        self.actions = {}          # id d'opération -> entrée d'annulation
        self.undo_stack = []
        self.redo_stack = []
        self.alerts_list = []
        self.presence_map = {}
        self.active = None
        self.open_snap = None      # (nom, cellules) d'une version consultée
        self.view = None
        self.view_wb = None
        net.register(name, self._on_msg, self)
        self._rebuild()
        self._hello()

    # --- synchronisation -------------------------------------------------

    def _hello(self):
        self.net.send(self.name, "server", ("hello",))
        for op in self.pending:
            self.net.send(self.name, "server", ("op", op))

    def on_reconnect(self):
        self._hello()

    def _persist(self):
        self.storage["base"] = self.base
        self.storage["pending"] = list(self.pending)

    def _rebuild(self):
        v = self.base.copy()
        for op in self.pending:
            apply_effects(v, op["opt"], None)
        self.view = v
        self.view_wb = v.to_workbook()
        self._persist()

    def _on_msg(self, src, msg):
        tag = msg[0]
        if tag == "snapshot":
            self.base = msg[1]
            self.presence_map = dict(msg[2])
            self.pending = [p for p in self.pending if p["id"] not in self.base.applied]
            self._rebuild()
        elif tag == "event":
            self._on_event(msg[1])
        elif tag == "presence":
            self.presence_map = dict(msg[1])

    def _on_event(self, ev):
        apply_effects(self.base, ev["effects"], ev["seq"])
        if ev["author"] == self.name and ev["id"] is not None:
            self.pending = [p for p in self.pending if p["id"] != ev["id"]]
            entry = self.actions.get(ev["id"])
            if ev["reject"] is not None:
                reason, sname, cell = ev["reject"]
                self._alert(_REJECT_ALERT[reason], sname, cell)
            elif entry is not None and ev["seq"] is not None:
                for c, r, _ in entry["fwd"].get("cells", []):
                    entry["result_seq"][(c, r)] = ev["seq"]
        self._rebuild()

    def _alert(self, kind, sheet=None, cell=None, line=None):
        self.alerts_list.append(Alert(kind, sheet, cell, line))

    def _submit(self, op, entry=None):
        op["id"] = uuid.uuid4().hex
        op["author"] = self.name
        op["ts"] = self.clock.now()
        self.pending.append(op)
        if entry is not None:
            entry["op_id"] = op["id"]
            self.actions[op["id"]] = entry
        self._rebuild()
        self.net.send(self.name, "server", ("op", op))

    # --- construction d'opérations ----------------------------------------

    def _make_op(self, fwd, strict=False, inverse_base=None):
        k = fwd["kind"]
        sid = fwd.get("sid")
        op = {"kind": k, "sid": sid, "sheet_name": fwd.get("sheet_name"), "strict": strict}
        if k == "cells":
            cells = fwd["cells"]
            op["cells"] = cells
            op["name"] = fwd.get("name")
            op["vkind"] = fwd.get("vkind", "modification")
            ib = inverse_base or {}
            op["base"] = {(c, r): ib.get((c, r), self.base.seq.get((sid, c, r), 0)) for c, r, _ in cells}
            opt = []
            cur = self.view.name_of(sid)
            if op["name"] and op["name"] != cur:
                opt.append(("sheet_rename", sid, cur, op["name"]))
            opt += [("cell", (sid, c, r), rec, None, False) for c, r, rec in cells]
        elif k == "addsheet":
            op["name"] = fwd["name"]
            opt = [("sheet_add", sid, fwd["name"]), ("right", sid, self.name, W)]
        elif k == "delsheet":
            opt = [("sheet_del", sid)]
        elif k == "rename":
            op["name"] = fwd["name"]
            opt = [("sheet_rename", sid, self.view.name_of(sid), fwd["name"])]
        elif k == "undelete":
            op["name"] = fwd["name"]
            op["cells"] = fwd["cells"]
            op["rights"] = fwd["rights"]
            opt = [("sheet_add", sid, fwd["name"])]
            opt += [("right", sid, p, lvl) for p, lvl in fwd["rights"]]
            opt += [("cell", (sid, c, r), rec, None, False) for c, r, rec in fwd["cells"]]
        else:
            raise ValueError(k)
        op["opt"] = opt
        return op

    def _prev_for(self, fwd):
        k = fwd["kind"]
        sid = fwd.get("sid")
        if k == "cells":
            return {"cells": [(c, r, self.view.cells.get((sid, c, r))) for c, r, _ in fwd["cells"]],
                    "name": self.view.name_of(sid)}
        if k == "delsheet":
            cells = [(c, r, rec) for (s, c, r), rec in self.view.cells.items() if s == sid]
            rights = [(p, lvl) for (s, p), lvl in self.view.rights.items() if s == sid]
            return {"name": self.view.name_of(sid), "cells": cells, "rights": rights}
        if k == "rename":
            return {"name": self.view.name_of(sid)}
        return {}

    def _act(self, fwd, clear_redo=True):
        prev = self._prev_for(fwd)
        op = self._make_op(fwd)
        e = {"fwd": fwd, "prev": prev, "op_id": None, "result_seq": {}}
        self.undo_stack.append(e)
        if clear_redo:
            self.redo_stack.clear()
        self._submit(op, e)

    def _inverse_fwd(self, e):
        f, p = e["fwd"], e["prev"]
        sid = f.get("sid")
        k = f["kind"]
        if k == "cells":
            return {"kind": "cells", "sid": sid,
                    "sheet_name": self.view.name_of(sid) or f.get("sheet_name"),
                    "cells": p["cells"],
                    "name": p["name"] if f.get("name") else None,
                    "vkind": "modification"}, True
        if k == "addsheet":
            return {"kind": "delsheet", "sid": sid, "sheet_name": f["name"]}, False
        if k == "delsheet":
            return {"kind": "undelete", "sid": sid, "sheet_name": p["name"], "name": p["name"],
                    "cells": p["cells"], "rights": p["rights"]}, False
        if k == "rename":
            return {"kind": "rename", "sid": sid, "sheet_name": f["name"], "name": p["name"]}, False
        raise ValueError(k)

    # --- annuler / rétablir -------------------------------------------------

    def undo(self):
        if not self.undo_stack:
            return
        e = self.undo_stack.pop()
        self.redo_stack.append(e)
        if e["op_id"] is not None and any(p["id"] == e["op_id"] for p in self.pending):
            # envoi pas encore confirmé : la modification est retirée, rien n'est envoyé
            self.pending = [p for p in self.pending if p["id"] != e["op_id"]]
            self.net.recall(self.name, e["op_id"])
            self._rebuild()
            return
        inv, strict = self._inverse_fwd(e)
        op = self._make_op(inv, strict=strict, inverse_base=e["result_seq"])
        self._submit(op, None)

    def redo(self):
        if not self.redo_stack:
            return
        e = self.redo_stack.pop()
        self._act(e["fwd"], clear_redo=False)

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    # --- lecture ------------------------------------------------------------

    def _active(self):
        names = self.sheets()
        if self.active in names:
            return self.active
        return names[0] if names else None

    def _wb_and_sheet(self, sheet):
        if self.open_snap is not None:
            name, cells = self.open_snap
            wb = Workbook()
            wb.sheets = [name]
            wb.cells = {(name, c, r): rec for (c, r), rec in cells.items()}
            return wb, name
        return self.view_wb, (sheet or self._active())

    def _eval(self, ref, sheet):
        wb, sname = self._wb_and_sheet(sheet)
        c, r = split_ref(ref)
        return evaluate_cell(wb, self.clock, self.tz, sname, c, r)

    def content(self, ref, sheet=None):
        wb, sname = self._wb_and_sheet(sheet)
        c, r = split_ref(ref)
        rec = wb.get(sname, c, r)
        return None if rec is None else rec[0]

    def value(self, ref, sheet=None):
        v, err = self._eval(ref, sheet)
        return err if err is not None else v

    def error(self, ref, sheet=None):
        return self._eval(ref, sheet)[1]

    def set_timezone(self, tz):
        self.tz = tz

    def alerts(self):
        return list(self.alerts_list)

    def pending_count(self):
        return len(self.pending)

    def connection_status(self):
        return "en ligne" if self.net.is_connected(self.name) else "hors ligne"

    def sheets(self):
        return [n for _, n in self.view.sheets]

    def activate(self, name):
        self.active = name

    def right(self, person, sheet):
        sid = self.view.sid_of(sheet or self._active())
        if sid is None:
            return None
        return self.view.level(person, sid)

    # --- saisie ---------------------------------------------------------------

    def set_cell(self, ref, text, sheet=None):
        self._edit(ref, text, sheet)

    def clear(self, ref, sheet=None):
        self._edit(ref, None, sheet)

    def _edit(self, ref, text, sheet):
        if self.open_snap is not None:
            return
        sname = sheet or self._active()
        sid = self.view.sid_of(sname)
        if sid is None:
            return
        if self.view.level(self.name, sid) != W:
            self._alert("droit_insuffisant", sname, ref)
            return
        c, r = split_ref(ref)
        rec = (text, False, self.tz) if text else None
        if same_content(self.view.cells.get((sid, c, r)), rec):
            return
        self._act({"kind": "cells", "sid": sid, "sheet_name": sname,
                   "cells": [(c, r, rec)], "name": None, "vkind": "modification"})

    def import_csv(self, data):
        if self.open_snap is not None:
            return
        sname = self._active()
        sid = self.view.sid_of(sname)
        if sid is None:
            return
        if self.view.level(self.name, sid) != W:
            self._alert("droit_insuffisant", sname, None)
            return
        text = data.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        it = iter(reader)
        records = []
        while True:
            start = reader.line_num + 1
            try:
                fields = next(it)
            except StopIteration:
                break
            except csv.Error:
                self._alert("csv_invalide", sname, None, line=start)
                return
            records.append(fields)
        changes = []
        for ri, fields in enumerate(records):
            for ci, field in enumerate(fields):
                c, r = index_to_col(ci + 1), ri + 1
                if field == "":
                    rec = None
                elif field.startswith("="):
                    rec = (field, True, self.tz)
                else:
                    rec = (field, False, self.tz)
                if same_content(self.view.cells.get((sid, c, r)), rec):
                    continue
                changes.append((c, r, rec))
        if changes:
            self._act({"kind": "cells", "sid": sid, "sheet_name": sname,
                       "cells": changes, "name": None, "vkind": "modification"})

    def export_csv(self):
        wb, sname = self._wb_and_sheet(None)
        cells = {(c, r) for (n, c, r) in wb.cells if n == sname}
        if not cells:
            return b""
        maxcol = max(col_to_index(c) for c, _ in cells)
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        for r in sorted({r for _, r in cells}):
            fields = []
            for ci in range(1, maxcol + 1):
                c = index_to_col(ci)
                if (c, r) not in cells:
                    fields.append("")
                    continue
                v, err = raw_value(wb, self.clock, sname, c, r)
                fields.append(err if err is not None else export_value(v, self.tz))
            writer.writerow(fields)
        return buf.getvalue().encode("utf-8")

    # --- feuilles ---------------------------------------------------------------

    def add_sheet(self, name):
        if self.view.is_dup(name):
            self._alert("nom_existant", name, None)
            return
        self._act({"kind": "addsheet", "sid": uuid.uuid4().hex, "name": name, "sheet_name": name})

    def delete_sheet(self, name):
        sid = self.view.sid_of(name)
        if sid is None:
            return
        if self.view.level(self.name, sid) != W:
            self._alert("droit_insuffisant", name, None)
            return
        if len(self.view.sheets) <= 1:
            return
        self._act({"kind": "delsheet", "sid": sid, "sheet_name": name})
        if self.active == name:
            self.active = None

    def rename_sheet(self, old, new):
        sid = self.view.sid_of(old)
        if sid is None or new == old:
            return
        if self.view.level(self.name, sid) != W:
            self._alert("droit_insuffisant", old, None)
            return
        if self.view.is_dup(new, exclude=sid):
            self._alert("nom_existant", new, None)
            return
        self._act({"kind": "rename", "sid": sid, "name": new, "sheet_name": old})
        if self.active == old:
            self.active = new

    def set_right(self, person, sheet, level):
        if self.view.owner != self.name or not self.net.is_connected(self.name):
            return
        sid = self.view.sid_of(sheet)
        if sid is None or self.view.rights.get((sid, person)) == level:
            return
        op = {"kind": "right", "sid": sid, "person": person, "level": level,
              "author": self.name, "id": uuid.uuid4().hex, "ts": self.clock.now()}
        self.net.send(self.name, "server", ("right", op))

    # --- conflits -----------------------------------------------------------------

    def conflict(self, ref, sheet=None):
        sid = self.base.sid_of(sheet or self._active())
        if sid is None:
            return None
        c, r = split_ref(ref)
        cf = self.base.conflicts.get((sid, c, r))
        if cf is None:
            return None
        rec = cf["discarded"]
        return Conflict(rec[0] if rec is not None else None, cf["by"])

    def resolve_conflict(self, ref, use_discarded, sheet=None):
        sname = sheet or self._active()
        sid = self.base.sid_of(sname)
        if sid is None:
            return
        c, r = split_ref(ref)
        cf = self.base.conflicts.get((sid, c, r))
        if cf is None:
            return
        if self.view.level(self.name, sid) != W:
            self._alert("droit_insuffisant", sname, ref)
            return
        cur = self.view.cells.get((sid, c, r))
        new = cf["discarded"] if use_discarded else cur
        op = {"kind": "resolve", "sid": sid, "sheet_name": sname, "col": c, "row": r,
              "use": bool(use_discarded)}
        op["opt"] = [("cell", (sid, c, r), new, None, False)]
        self._submit(op)

    # --- versions -------------------------------------------------------------------

    def history(self, sheet=None):
        sid = self.base.sid_of(sheet or self._active())
        if sid is None:
            return []
        entries = sorted(self.base.versions.get(sid, []),
                         key=lambda e: (e["instant"], e["n"]), reverse=True)
        return [Version(e["id"], e["author"], display_value(e["instant"], self.tz), e["kind"])
                for e in entries]

    def _find_version(self, vid):
        for entries in self.base.versions.values():
            for e in entries:
                if e["id"] == vid:
                    return e
        return None

    def open_version(self, vid):
        e = self._find_version(vid)
        if e is not None:
            self.open_snap = (e["name"], dict(e["cells"]))

    def close_version(self):
        self.open_snap = None

    def restore_version(self, vid):
        e = self._find_version(vid)
        if e is None:
            return
        sid = e["sid"]
        cur = self.view.name_of(sid)
        if cur is None:
            return
        if self.view.level(self.name, sid) != W:
            self._alert("droit_insuffisant", cur, None)
            return
        snap = e["cells"]
        keys = {(c, r) for (s, c, r) in self.view.cells if s == sid} | set(snap)
        cells = [(c, r, snap.get((c, r))) for (c, r) in sorted(keys)]
        name = e["name"]
        self._act({"kind": "cells", "sid": sid, "sheet_name": cur, "cells": cells,
                   "name": name if name != cur else None, "vkind": "restauration"})

    # --- présence ---------------------------------------------------------------------

    def select(self, ref, sheet=None):
        sname = sheet or self._active()
        self.net.send(self.name, "server", ("presence", sname, ref))

    def presence(self):
        if not self.net.is_connected(self.name):
            return {}
        return {k: v for k, v in self.presence_map.items() if k != self.name}

    # --- cycle de vie -------------------------------------------------------------------

    def reopen(self):
        return Client(self.net, self.clock, self.name, tz=self.tz, storage=self.storage)
