"""Lecture déterministe d'un règlement de la consultation (RC)."""

import copy
import json
import re

OUI = "trouvé"
NON = "non trouvé"

# ---------------------------------------------------------------- outils


def _n(s):
    return s.replace("’", "'").replace(" ", " ").replace(" ", " ")


def _norm(s):
    return re.sub(r"\s+", " ", _n(s)).strip().lower()


def _k(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


class _Acc:
    def __init__(self):
        self.d = {}

    def add(self, v, p):
        self.d.setdefault(_k(v), (v, set()))[1].add(p)

    def valeurs(self):
        return [{"valeur": v, "pages": sorted(ps)} for v, ps in self.d.values()]


def _fait(vs, conflit=None):
    if not vs:
        return {"statut": NON, "valeurs": [], "conflit": False}
    return {"statut": OUI, "valeurs": vs,
            "conflit": (len(vs) > 1) if conflit is None else conflit}


# ---------------------------------------------------------------- nombres

_UNITES = {"zéro": 0, "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
           "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
           "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
           "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50,
           "soixante": 60, "cent": 100, "cents": 100}
_W = "|".join(sorted(list(_UNITES) + ["mille"], key=len, reverse=True))
NUMW = rf"(?:{_W})(?:[\s\-]+(?:et[\s\-]+)?(?:{_W}))*"
NUMB = rf"(?<![a-zà-ÿ0-9])(?:{NUMW})(?![a-zà-ÿ])"


def _mot_nombre(s):
    total = 0
    cur = 0
    prev = None
    for tok in re.split(r"[\s\-]+", s.lower().strip()):
        if tok == "et" or not tok:
            continue
        if tok in ("vingt", "vingts") and prev == "quatre":
            cur += 76
        elif tok in ("cent", "cents"):
            cur = (cur or 1) * 100
        elif tok == "mille":
            total += (cur or 1) * 1000
            cur = 0
        elif tok in _UNITES:
            cur += _UNITES[tok]
        else:
            return None
        prev = tok
    return total + cur


def _nombre(s):
    s = s.strip()
    if s.isdigit():
        return int(s)
    return _mot_nombre(s)


# ---------------------------------------------------------------- dates / heures

MOIS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
        "décembre": 12, "decembre": 12}
_MOIS_RE = "|".join(MOIS)
RE_DN = re.compile(r"(?<![\d/.\-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)")
RE_DL = re.compile(rf"(?<!\d)(\d{{1,2}})(?:er|ère)?\s+({_MOIS_RE})\s+(\d{{4}})(?!\d)", re.I)
RE_H = re.compile(rf"(?<![\w/.:\-])(\d{{1,2}}|{NUMW})\s*(?:heures?|h)(?![a-zà-ÿ])"
                  rf"(?:\s*(\d{{2}})(?!\d)|\s+({NUMW})(?![a-zà-ÿ]))?", re.I)
RE_DELAI = re.compile(rf"(?:\d+|{NUMB})\s+jours?\s+(?:calendaires\s+|ouvr[ée]s\s+|ouvrables\s+)?"
                      rf"avant\s+la\s+(?:date|clôture)(?:\s+limite)?"
                      rf"(?:\s+de\s+(?:remise|réception|dépôt)\s+des\s+(?:offres|plis))?", re.I)


def _dates(u):
    res = []
    for m in RE_DN.finditer(u):
        res.append((m.start(), int(m[1]), int(m[2]), int(m[3])))
    for m in RE_DL.finditer(u):
        res.append((m.start(), int(m[1]), MOIS[m[2].lower()], int(m[3])))
    res.sort()
    return [f"{j:02d}/{mo:02d}/{a}" for _, j, mo, a in res if 1 <= j <= 31 and 1 <= mo <= 12]


def _heures(u):
    out = []
    for m in RE_H.finditer(u):
        h = _nombre(m[1])
        if h is None:
            continue
        if m[2]:
            mi = int(m[2])
        elif m[3]:
            mi = _nombre(m[3])
            if mi is None:
                mi = 0
        else:
            mi = 0
        if 0 <= h < 24 and 0 <= mi < 60:
            out.append(f"{h:02d}:{mi:02d}")
    return out


def _nature(u):
    l = u.lower()
    if re.search(r"question|renseignement|éclaircissement", l):
        return "q"
    if "visite" in l:
        return "v"
    if re.search(r"\bavis\b|publication", l):
        return "x"
    if re.search(r"ouverture des|notification|signature|démarrage|début des", l) \
            and not re.search(r"limite|parvenir", l):
        return "x"
    if re.search(r"\blimites?\b|\boffres?\b|\bplis?\b|remise|réception|déposer|dépôt|parvenir", l):
        return "l"
    if re.search(r"\bdate\b", l):
        return "x"
    return None


def _unites_pages(p):
    pn = _n(p)
    sp = r"\n+|;|(?<=[.!?])\s+"
    a = [u for u in re.split(sp, pn) if u.strip()]
    b = [u for u in re.split(sp, p) if u.strip()]
    out = []
    for x, y in zip(a, b):
        lead = len(x) - len(x.lstrip())
        xs = x.strip()
        out.append((xs, y[lead:lead + len(xs)]))
    return out


# ---------------------------------------------------------------- règles textuelles

RE_VALID = re.compile(r"validit[ée]\s+(?:des|de l')\s*offres?|"
                      r"offres?\s+(?:sont|restent|demeurent|reste)\s+(?:valables?|valides?|engag\w+)", re.I)
RE_DUREE = re.compile(rf"(\d+|{NUMB})(?:\s*\((\d+)\))?\s+(jours?|mois)(?![a-zà-ÿ])", re.I)
RE_PAGES = re.compile(rf"(\d+|{NUMB})(?:\s*\((\d+)\))?\s+pages?(?![a-zà-ÿ])", re.I)
RE_ELEC = re.compile(r"électronique|dématérialis|plateforme|profil d'acheteur|profil acheteur", re.I)
RE_PAPIER = re.compile(r"papier|pli cacheté|voie postale|récépissé", re.I)
RE_CTX_MODE = re.compile(r"offres?|\bplis?\b|remise|remis|transmi|dépos|dépôt|candidatures?", re.I)
RE_NEG = re.compile(r"\bpas\b|\bplus\b|aucun|interdit|refus", re.I)


def _procedures(pn):
    out = []
    if re.search(r"\bmapa\b|proc[ée]dure\s+adapt[ée]e", pn, re.I):
        out.append("procédure adaptée")
    if re.search(r"appel\s+d'offres\s+ouvert", pn, re.I):
        out.append("appel d'offres ouvert")
    if re.search(r"appel\s+d'offres\s+restreint", pn, re.I):
        out.append("appel d'offres restreint")
    if re.search(r"dialogue\s+comp[ée]titif", pn, re.I):
        out.append("dialogue compétitif")
    return out


def _variantes(u):
    l = u.lower()
    if "variante" not in l:
        return None
    if re.search(r"(?:ne sont|n'est) pas (?:autoris|admis|accept)|interdit|aucune variante|"
                 r"non[\s-](?:autoris|admis)|refus|exclu|pas de variante", l):
        return "non autorisées"
    if re.search(r"autoris|admis|accept|possible", l):
        return "autorisées"
    return None


def _visite(u):
    l = u.lower()
    if "visite" not in l:
        return None
    if re.search(r"facultati|non[\s-]+obligatoire|pas\s+(?:d')?obligatoire|sans caractère obligatoire", l):
        return "non"
    if re.search(r"obligatoire|imposée", l):
        return "oui"
    return None


# ---------------------------------------------------------------- lignes

def _lignes(p):
    lo = p.split("\n")
    out = []
    for o in lo:
        n = _n(o)
        s = n.strip()
        if not s:
            continue
        lead = len(n) - len(n.lstrip())
        out.append((s, o[lead:lead + len(s)]))
    return out


# ---------------------------------------------------------------- lots

LOT_RE = re.compile(r"^\W*lot\s*(?:n\s*[°º]?\s*|numéro\s*)?0*(\d+)\s*[:\-–—]\s*(.+)$", re.I)
LOT_UNIQUE_RE = re.compile(r"\blot\s+unique\b(?:\s*[:\-–]\s*(.+))?", re.I)
NON_ALLOTI_RE = re.compile(r"n'est pas alloti|non[\s-]alloti|"
                           r"pas (?:prévu |envisagé )?(?:de |d')(?:décomposition|division|découpage|répartition|allotissement)|"
                           r"sans allotissement|n'est pas (?:décomposé|divisé|réparti) en lots", re.I)
BAD_TITLE = re.compile(r"\d\s*(?:%|points?|pour\s*cent)", re.I)


def _lots_page(lignes, p, L):
    for s, o in lignes:
        m = LOT_RE.match(s)
        if m:
            title = o[m.start(2):].strip().rstrip(" ;.,").strip()
            if title and not BAD_TITLE.search(title):
                e = L.setdefault(int(m.group(1)), {"int": {}, "pages": set()})
                e["pages"].add(p)
                e["int"].setdefault(_norm(title), (title, set()))[1].add(p)
            continue
        m = LOT_UNIQUE_RE.search(s)
        if m:
            e = L.setdefault(None, {"int": {}, "pages": set()})
            e["pages"].add(p)
            if m.group(1):
                title = o[m.start(1):].strip().rstrip(" ;.,").strip()
                if title:
                    e["int"].setdefault(_norm(title), (title, set()))[1].add(p)
            continue
        if NON_ALLOTI_RE.search(s):
            e = L.setdefault(None, {"int": {}, "pages": set()})
            e["pages"].add(p)


def _lots_fait(L):
    if any(k is not None for k in L):
        L = {k: v for k, v in L.items() if k is not None}
    liste = []
    for k in sorted(L, key=lambda x: (x is None, x if x is not None else 0)):
        e = L[k]
        ints = [{"valeur": t, "pages": sorted(ps)} for t, ps in e["int"].values()]
        liste.append({"numero": k, "intitules": ints, "pages": sorted(e["pages"]),
                      "conflit": len(ints) > 1})
    return {"statut": OUI if liste else NON, "liste": liste}


# ---------------------------------------------------------------- pièces

PIECE_KW = re.compile(r"pi[èe]ces?|documents?|dossier|remettr|remis|produi|fourni|joindre|joint|"
                      r"contenu|comprend|comport|contiendr|annexer|présenter|présentera", re.I)
BULLET_RE = re.compile(r"^[-•*–—·]\s+(.*)$")


def _phase(s):
    l = s.lower()
    if re.search(r"attributaire|envisagé d'attribuer|pressenti", l):
        return "attributaire"
    if "candidature" in l:
        return "candidature"
    if re.search(r"(?<![a-zà-ÿ])offre(?![a-zà-ÿ])", l):
        return "offre"
    return None


def _pieces_page(lignes, p, P):
    phase = None
    intro = False
    for s, o in lignes:
        mb = BULLET_RE.match(s)
        if mb:
            cn = s[mb.start(1):]
            co = o[mb.start(1):]
            if intro and not WEIGHT_RE.search(cn):
                low = cn.lower()
                if re.search(r"non obligatoire|facultati|optionnel", low):
                    obl = "non obligatoire"
                elif "obligatoire" in low:
                    obl = "obligatoire"
                else:
                    obl = None
                name = re.sub(r"\s*\((?:non\s+)?(?:obligatoire|facultati\w*|optionnel\w*)\)", "", co,
                              flags=re.I)
                name = name.strip().rstrip(";.,").strip()
                if name:
                    e = P.setdefault(_norm(name), {"nom": name, "pages": set(), "phase": _Acc(),
                                                   "obl": _Acc()})
                    e["pages"].add(p)
                    if phase:
                        e["phase"].add(phase, p)
                    if obl:
                        e["obl"].add(obl, p)
            continue
        intro = bool(PIECE_KW.search(s)) and not re.search(r"crit[èe]re", s, re.I)
        ph = _phase(s)
        if ph:
            phase = ph


def _pieces_fait(P):
    liste = []
    for e in P.values():
        liste.append({"nom": e["nom"], "pages": sorted(e["pages"]),
                      "phase": _fait(e["phase"].valeurs(), False),
                      "obligation": _fait(e["obl"].valeurs())})
    return {"statut": OUI if liste else NON, "liste": liste}


# ---------------------------------------------------------------- critères

WEIGHT_RE = re.compile(rf"(?<![\w.,])(?P<n>\d+(?:[.,]\d+)?|{NUMW})\s*(?P<u>%|pour\s*cent|points?|pts)(?![a-zà-ÿ])",
                       re.I)
STRICT_RE = re.compile(rf"[^:()%]{{2,80}}\s*[:(]\s*{WEIGHT_RE.pattern}\s*\)?\s*[.;,]?", re.I)
HEAD_RE = re.compile(r"^(article|annexe|titre|chapitre|section|partie)\b", re.I)
CRIT_WORD = re.compile(r"crit[èe]re", re.I)
CLASS_RE = re.compile(r"class[ée]s?\b|classement|ordre (?:d[ée]croissant|d'importance|de préférence)|"
                      r"par ordre", re.I)
LOTCTX_RE = re.compile(r"^(?:pour\s+(?:le\s+)?)?lot\s*(?:n\s*[°º]?\s*|numéro\s*)?0*(\d+)\s*:?\s*$", re.I)
SUB1_RE = re.compile(r"^(\d+)\.(\d+)\s*[.)]?\s+(.*)$")
SUBL_RE = re.compile(r"^[a-z]\s*\)\s+(.*)$", re.I)
NUM_RE = re.compile(r"^(\d+)\s*[.)]\s+(.*)$")
CRITN_RE = re.compile(r"^crit[èe]re\s*(?:n\s*[°º]?\s*)?(\d+)\s*[:.\-–]\s*(.*)$", re.I)


def _poids(m):
    u = m.group("u").lower()
    unite = "pourcentage" if u.startswith("%") or u.startswith("pour") else "points"
    ns = m.group("n")
    if re.fullmatch(r"\d+(?:[.,]\d+)?", ns):
        v = float(ns.replace(",", "."))
        if v.is_integer():
            v = int(v)
    else:
        v = _mot_nombre(ns)
        if v is None:
            return None
    return v, unite


def _item(cn, co):
    mw = WEIGHT_RE.search(cn)
    cut = len(cn)
    for ch in ":(":
        i = cn.find(ch)
        if i != -1:
            cut = min(cut, i)
    if mw:
        cut = min(cut, mw.start())
    label = co[:cut].strip(" \t-–—,;.:")
    return label, (_poids(mw) if mw else None)


def _crit_page(lignes, p, C):
    mode = False
    classement = False
    lot = None
    cur = None
    rang = 0
    for s, o in lignes:
        if mode:
            ml = LOTCTX_RE.match(s)
            if ml:
                lot = int(ml.group(1))
                continue
        kind = None
        num = None
        start = 0
        m = SUB1_RE.match(s)
        if m:
            kind, start = "sub", m.start(3)
        else:
            m = SUBL_RE.match(s)
            if m:
                kind, start = "sub", m.start(1)
            else:
                m = NUM_RE.match(s)
                if m:
                    kind, num, start = "crit", int(m.group(1)), m.start(2)
                else:
                    m = CRITN_RE.match(s)
                    if m:
                        kind, num, start = "crit", int(m.group(1)), m.start(2)
                    elif mode:
                        m = BULLET_RE.match(s)
                        if m:
                            kind, start = "crit", m.start(1)
        if kind:
            cn = s[start:]
            co = o[start:]
            if not mode and not STRICT_RE.fullmatch(cn):
                kind = None
            elif kind == "crit" and re.match(r"lot\b", cn, re.I):
                continue
        if not kind:
            if CRIT_WORD.search(s):
                if not mode:
                    mode = True
                    classement = False
                    lot = None
                    cur = None
                    rang = 0
            elif HEAD_RE.match(s):
                mode = False
            if mode and CLASS_RE.search(s):
                classement = True
            continue
        label, w = _item(cn, co)
        if not label:
            continue
        if kind == "crit":
            rang += 1
            c = C.setdefault(_norm(label), {"libelle": label, "pages": set(), "lots": [],
                                            "pond": {}, "subs": {}})
            c["pages"].add(p)
            if lot not in c["lots"]:
                c["lots"].append(lot)
            cur = c
            target = c
            if w is None and classement:
                w = (num if num is not None else rang, "rang")
        else:
            if cur is None:
                continue
            target = cur["subs"].setdefault(_norm(label), {"libelle": label, "pages": set(), "pond": {}})
            target["pages"].add(p)
        if w:
            target["pond"].setdefault((w[0], w[1], lot), set()).add(p)


def _conf_p(vs):
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            if vs[i]["lot"] == vs[j]["lot"]:
                return True
    return False


def _fait_p(pond):
    vs = [{"valeur": v, "unite": u, "lot": l, "pages": sorted(ps)} for (v, u, l), ps in pond.items()]
    return _fait(vs, _conf_p(vs))


def _criteres_fait(C, lots):
    known = [l["numero"] for l in lots["liste"]]
    liste = []
    tp = {}
    for c in C.values():
        nums = [x for x in c["lots"] if x is not None]
        if nums:
            if len(nums) == 1:
                lvals = [nums[0]]
            elif set(nums) >= set(known):
                lvals = ["tous les lots"]
            else:
                lvals = nums
        elif len(known) == 1:
            lvals = [known[0]]
        else:
            lvals = ["tous les lots"]
        pg = sorted(c["pages"])
        subs = []
        for s in c["subs"].values():
            subs.append({"libelle": s["libelle"], "pages": sorted(s["pages"]),
                         "ponderation": _fait_p(s["pond"])})
            for (v, u, l), ps in s["pond"].items():
                tp.setdefault(u, set()).update(ps)
        for (v, u, l), ps in c["pond"].items():
            tp.setdefault(u, set()).update(ps)
        liste.append({"libelle": c["libelle"], "pages": pg,
                      "lot": _fait([{"valeur": x, "pages": pg} for x in lvals], False),
                      "ponderation": _fait_p(c["pond"]), "sous_criteres": subs})
    tvals = []
    for u, nom in (("pourcentage", "pourcentage"), ("points", "points"), ("rang", "classement")):
        if u in tp:
            tvals.append({"valeur": nom, "pages": sorted(tp[u])})
    return ({"statut": OUI if liste else NON, "liste": liste}, _fait(tvals))


# ---------------------------------------------------------------- plan et contrôle

def _prix(lbl):
    return bool(re.search(r"\bprix\b|\bcoûts?\b|tarif|financi|montant|économique", _norm(lbl)))


def _w1(f):
    vs = f.get("valeurs") or []
    return vs[0]["valeur"] if vs else None


def _plan(d):
    plan = []
    for c in d["criteres"]["liste"]:
        if _prix(c["libelle"]):
            continue
        pg = min(c["pages"]) if c["pages"] else 1
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                plan.append({"titre": s["libelle"], "critere": c["libelle"],
                             "sous_critere": s["libelle"], "ponderation": _w1(s["ponderation"]),
                             "page_source": pg, "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": _w1(c["ponderation"]), "page_source": pg, "contenu": ""})
    return plan


def _alertes(d):
    al = []
    crits = d["criteres"]["liste"]
    sections = {_norm(s["critere"]) for s in d.get("plan") or []}
    for c in crits:
        if not _prix(c["libelle"]) and _norm(c["libelle"]) not in sections:
            al.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in crits:
        if not c["sous_criteres"]:
            continue
        for pv in c["ponderation"]["valeurs"]:
            if pv["unite"] == "rang":
                continue
            sv = [x["valeur"] for s in c["sous_criteres"] for x in s["ponderation"]["valeurs"]
                  if x["unite"] == pv["unite"] and x["lot"] == pv["lot"]]
            if sv and abs(sum(sv) - pv["valeur"]) > 1e-6:
                al.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
                break
    tvals = [v["valeur"] for v in d["type_ponderation"]["valeurs"]]
    if tvals == ["pourcentage"]:
        groupes = {}
        for c in crits:
            vus = set()
            for pv in c["ponderation"]["valeurs"]:
                if pv["unite"] != "pourcentage" or pv["lot"] in vus:
                    continue
                vus.add(pv["lot"])
                groupes[pv["lot"]] = groupes.get(pv["lot"], 0) + pv["valeur"]
        for lot, tot in groupes.items():
            if abs(tot - 100) > 1e-6:
                al.append({"type": "total différent de 100 %",
                           "objet": "critères" if lot is None else f"lot {lot}"})
    return al


def controler(dossier):
    return _alertes(dossier)


# ---------------------------------------------------------------- extraction

_SIMPLES = ("date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
            "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
            "type_ponderation")


def _extraire(pages):
    pages = [str(p) for p in pages]
    A = {k: _Acc() for k in ("dl", "hl", "dq", "pr", "vo", "dv", "va", "vl", "mr", "lp")}
    L, P, C = {}, {}, {}
    for i, p in enumerate(pages, 1):
        pn = _n(p)
        us = _unites_pages(p)
        nat = [_nature(un) for un, _ in us]
        for j, (un, uo) in enumerate(us):
            na = nat[j] or (nat[j - 1] if j > 0 else None)
            if na == "l":
                for d in _dates(un):
                    A["dl"].add(d, i)
                for h in _heures(un):
                    A["hl"].add(h, i)
            elif na == "q":
                ds = _dates(un)
                for d in ds:
                    A["dq"].add(d, i)
                if not ds:
                    m = RE_DELAI.search(un)
                    if m:
                        A["dq"].add(uo[m.start():m.end()], i)
            elif na == "v":
                for d in _dates(un):
                    A["dv"].add(d, i)
            v = _visite(un)
            if v:
                A["vo"].add(v, i)
            v = _variantes(un)
            if v:
                A["va"].add(v, i)
            mk = RE_VALID.search(un)
            if mk:
                md = RE_DUREE.search(un, mk.end())
                if md:
                    n = int(md.group(2)) if md.group(2) else _nombre(md.group(1))
                    if n is not None:
                        unite = "mois" if md.group(3).lower().startswith("mois") else "jours"
                        A["vl"].add({"nombre": n, "unite": unite}, i)
            if RE_CTX_MODE.search(un):
                if RE_ELEC.search(un) and not RE_NEG.search(un):
                    A["mr"].add("électronique", i)
                if RE_PAPIER.search(un) and not RE_NEG.search(un):
                    A["mr"].add("papier", i)
            if re.search(r"mémoire", un, re.I):
                mp = RE_PAGES.search(un)
                if mp:
                    n = int(mp.group(2)) if mp.group(2) else _nombre(mp.group(1))
                    if n is not None:
                        A["lp"].add(n, i)
        for pr in _procedures(pn):
            A["pr"].add(pr, i)
        lg = _lignes(p)
        _lots_page(lg, i, L)
        _pieces_page(lg, i, P)
        _crit_page(lg, i, C)
    lots = _lots_fait(L)
    crit, tp = _criteres_fait(C, lots)
    d = {
        "lots": lots,
        "date_limite": _fait(A["dl"].valeurs()),
        "heure_limite": _fait(A["hl"].valeurs()),
        "date_questions": _fait(A["dq"].valeurs()),
        "procedure": _fait(A["pr"].valeurs()),
        "visite_obligatoire": _fait(A["vo"].valeurs()),
        "dates_visite": _fait(A["dv"].valeurs(), False),
        "variantes": _fait(A["va"].valeurs()),
        "validite_offres": _fait(A["vl"].valeurs()),
        "mode_remise": _fait(A["mr"].valeurs()),
        "pieces": _pieces_fait(P),
        "limite_pages": _fait(A["lp"].valeurs()),
        "type_ponderation": tp,
        "criteres": crit,
    }
    return d


def _finir(d):
    d["plan"] = _plan(d)
    d["controle"] = {"alertes": _alertes(d)}
    return d


def analyser(pages):
    return _finir(_extraire(pages))


# ---------------------------------------------------------------- vérification

def _cle_val(v):
    return _k(v.get("valeur"))


def _cle_p(v):
    return _k([v.get("valeur"), v.get("unite"), v.get("lot")])


def _garder(prop, frais, cle=_cle_val, conflit=None):
    if not isinstance(prop, dict):
        return _fait([])
    ks = {cle(v) for v in prop.get("valeurs") or [] if isinstance(v, dict)}
    vs = [v for v in frais["valeurs"] if cle(v) in ks]
    return _fait(vs, conflit(vs) if conflit else None)


def _liste(prop):
    if not isinstance(prop, dict):
        return []
    return [x for x in prop.get("liste") or [] if isinstance(x, dict)]


def verifier(dossier, pages):
    frais = _extraire(pages)
    res = {}
    for k in _SIMPLES:
        conf = (lambda vs: False) if k == "dates_visite" else None
        res[k] = _garder(dossier.get(k), frais[k], conflit=conf)

    # lots
    pb = {l.get("numero"): l for l in _liste(dossier.get("lots"))}
    lots = []
    for l in frais["lots"]["liste"]:
        if l["numero"] not in pb:
            continue
        ik = {_k(i.get("valeur")) for i in pb[l["numero"]].get("intitules") or [] if isinstance(i, dict)}
        ints = [i for i in l["intitules"] if _k(i["valeur"]) in ik]
        nl = dict(l)
        nl["intitules"] = ints
        nl["conflit"] = len(ints) > 1
        lots.append(nl)
    res["lots"] = {"statut": OUI if lots else NON, "liste": lots}

    # pièces
    pb = {_norm(str(x.get("nom", ""))): x for x in _liste(dossier.get("pieces"))}
    pieces = []
    for x in frais["pieces"]["liste"]:
        pp = pb.get(_norm(x["nom"]))
        if pp is None:
            continue
        pieces.append({"nom": x["nom"], "pages": x["pages"],
                       "phase": _garder(pp.get("phase"), x["phase"], conflit=lambda vs: False),
                       "obligation": _garder(pp.get("obligation"), x["obligation"])})
    res["pieces"] = {"statut": OUI if pieces else NON, "liste": pieces}

    # critères
    pb = {_norm(str(x.get("libelle", ""))): x for x in _liste(dossier.get("criteres"))}
    crits = []
    for c in frais["criteres"]["liste"]:
        pc = pb.get(_norm(c["libelle"]))
        if pc is None:
            continue
        sb = {_norm(str(s.get("libelle", ""))): s for s in pc.get("sous_criteres") or []
              if isinstance(s, dict)}
        subs = []
        for s in c["sous_criteres"]:
            ps = sb.get(_norm(s["libelle"]))
            if ps is None:
                continue
            subs.append({"libelle": s["libelle"], "pages": s["pages"],
                         "ponderation": _garder(ps.get("ponderation"), s["ponderation"],
                                                cle=_cle_p, conflit=_conf_p)})
        crits.append({"libelle": c["libelle"], "pages": c["pages"],
                      "lot": _garder(pc.get("lot"), c["lot"], conflit=lambda vs: False),
                      "ponderation": _garder(pc.get("ponderation"), c["ponderation"],
                                             cle=_cle_p, conflit=_conf_p),
                      "sous_criteres": subs})
    res["criteres"] = {"statut": OUI if crits else NON, "liste": crits}
    return _finir(res)
