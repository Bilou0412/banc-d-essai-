"""Lecture déterministe d'un règlement de la consultation (RC).

Interface : analyser(pages) -> dict ; verifier(dossier, pages) -> dict ; controler(dossier) -> list.
Expressions régulières et bibliothèque standard uniquement.
"""

import copy
import json
import re
import unicodedata

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"
TOUS_LES_LOTS = "tous les lots"

FAITS = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
         "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
         "type_ponderation"]
FAITS_UNIQUES = {"date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                 "variantes", "validite_offres", "mode_remise", "limite_pages", "type_ponderation"}

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}

NOMBRES = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
           "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13,
           "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30,
           "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100, "cents": 100, "et": 0}
MOTS_NOMBRE = (r"zéro|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|"
               r"quatorze|quinze|seize|vingts?|trente|quarante|cinquante|soixante|cents?")
NOMBRE_LETTRES = r"\b(?:" + MOTS_NOMBRE + r")\b(?:(?:\s+|-)(?:" + MOTS_NOMBRE + r")\b)*"


# ---------------------------------------------------------------- utilitaires

def _nettoyer(p):
    p = str(p).replace("\r", "").replace("\x0c", "\n")
    for c in (" ", " ", " "):
        p = p.replace(c, " ")
    return p.replace("’", "'")


def _sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _cle(s):
    return re.sub(r"\s+", " ", str(s).lower()).strip(" ;.,")


def _jk(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _lignes(pages):
    out = []
    for n, p in enumerate(pages, 1):
        for brut in _nettoyer(p).split("\n"):
            t = brut.strip()
            if t:
                out.append((n, brut, t))
    return out


def _nombre_lettres(txt):
    if not txt:
        return None
    centaines, cur, trouve = 0, 0, False
    for m in re.findall(r"[a-z]+", _sans_accents(txt.lower())):
        if m == "et":
            continue
        if m not in NOMBRES:
            return None
        v = NOMBRES[m]
        trouve = True
        if v == 100:
            centaines += (cur or 1) * 100
            cur = 0
        elif v == 20 and 2 <= cur <= 9:
            cur *= 20
        else:
            cur += v
    return centaines + cur if trouve else None


def _nombre_dec(s):
    f = float(s.replace(",", "."))
    return int(f) if f.is_integer() else f


def _date_fr(j, m, a):
    return "%02d/%02d/%04d" % (j, m, a)


RE_DATE_LETTRES = re.compile(
    r"(?<!\w)(\d{1,2}|1er|premier)\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[ée]cembre)\s+(\d{4})(?!\d)", re.I)
RE_DATE_CHIFFRES = re.compile(r"(?<![\d/.\-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d/])")


def _dates(txt):
    trouvees = []
    for m in RE_DATE_LETTRES.finditer(txt):
        j = m.group(1).lower()
        jour = 1 if j in ("1er", "premier") else int(j)
        mois = MOIS[_sans_accents(m.group(2).lower())]
        trouvees.append((m.start(), _date_fr(jour, mois, int(m.group(3)))))
    for m in RE_DATE_CHIFFRES.finditer(txt):
        jour, mois = int(m.group(1)), int(m.group(2))
        an = int(m.group(3))
        if len(m.group(3)) == 2:
            an += 2000
        if 1 <= mois <= 12 and 1 <= jour <= 31:
            trouvees.append((m.start(), _date_fr(jour, mois, an)))
    trouvees.sort()
    return [d for _, d in trouvees]


RE_HEURE_CHIFFRES = re.compile(
    r"(?<![\d/.:])(\d{1,2})\s*[hH](?![a-zA-Zé])\s*(\d{2})?(?!\d)"
    r"|(?<![\d/.:])(\d{1,2}):(\d{2})(?!\d)"
    r"|(?<![\d/.:])(\d{1,2})\s*heures?(?![a-zé])(?:\s*(\d{2})(?!\d))?", re.I)
RE_HEURE_LETTRES = re.compile(
    r"(?<![\w\-])(" + NOMBRE_LETTRES + r")\s+heures?(?![a-zé])(?:\s+(" + NOMBRE_LETTRES + r"))?", re.I)


def _heures(txt):
    res = []
    for m in RE_HEURE_CHIFFRES.finditer(txt):
        if m.group(1) is not None:
            h, mi = m.group(1), m.group(2)
        elif m.group(3) is not None:
            h, mi = m.group(3), m.group(4)
        else:
            h, mi = m.group(5), m.group(6)
        h = int(h)
        mi = int(mi) if mi else 0
        if h <= 23 and mi <= 59:
            res.append((m.start(), "%02d:%02d" % (h, mi)))
    for m in RE_HEURE_LETTRES.finditer(txt):
        h = _nombre_lettres(m.group(1))
        mi = _nombre_lettres(m.group(2)) if m.group(2) else 0
        if h is not None and mi is not None and h <= 23 and mi <= 59:
            res.append((m.start(), "%02d:%02d" % (h, mi)))
    m = re.search(r"\bmidi\b", txt, re.I)
    if m:
        res.append((m.start(), "12:00"))
    res.sort()
    return [v for _, v in res]


VAL_RE = re.compile(r"(?<![\d/.])(?:(\d{1,3})|(" + NOMBRE_LETTRES + r"))\s*(?:\((\d+)\)\s*)?(jours?|mois)(?![a-zé])", re.I)
PAGES_RE = re.compile(r"(?<![\d/.])(?:(\d{1,3})|(" + NOMBRE_LETTRES + r"))\s*(?:\((\d+)\)\s*)?pages?(?![a-zé])", re.I)
DL_KW = re.compile(r"remise|réception|reception|parvenir|plis|offres|limite", re.I)
EXCL_DL = re.compile(r"question|visite|renseignement|envoi", re.I)
Q_KW = re.compile(r"question|renseignement|demande", re.I)
DELAI_RE = re.compile(
    r"((?:\d+|[a-zéèêûôàç]+(?:-[a-zéèêûôàç]+)*)(?:\s*\(\d+\))?\s+jours?\s+avant\s+la\s+date\s+limite[^.;\n]*)", re.I)
V_KW = re.compile(r"visite", re.I)
EXCL_VIS = re.compile(r"remise|réception|limite|question|renseignement|envoi", re.I)
PROCEDURES = ["appel d'offres ouvert", "appel d'offres restreint", "dialogue compétitif",
              "procédure adaptée", "procédure négociée"]
NEG_VAR = re.compile(r"ne sont pas|n'est pas|interdi|aucune variante|non autoris|ne sont pas admis|"
                     r"ne seront pas|ne sera pas|pas admis", re.I)
POS_VAR = re.compile(r"autoris|admis|peuvent (?:presenter|proposer)", re.I)
ELEC_RE = re.compile(r"electronique|dematerialis", re.I)
SENS_RE = re.compile(r"offre|plis|remise|transmis|depos", re.I)
PAP_RE = re.compile(r"papier|pli cachete", re.I)
NEG_PAP = re.compile(r"n'est pas|ne sont pas|ne seront pas|ne sera pas|ne sera accept|ne seront accept|"
                     r"aucune|interdi|refus|exclu|non autoris|pas admis|pas autoris|n'est admis", re.I)


def _balayer(L):
    res = {k: [] for k in ("dl", "hl", "dq", "vis_dates", "proc", "visite", "variantes",
                           "modes", "validites", "limites")}
    for i, (n, brut, t) in enumerate(L):
        suiv = L[i + 1] if i + 1 < len(L) and L[i + 1][0] == n else None
        prec = L[i - 1] if i > 0 and L[i - 1][0] == n else None
        tl = t.lower()
        low = _sans_accents(tl)

        # date et heure limites de remise des offres
        if DL_KW.search(t) and not EXCL_DL.search(t):
            ok_suiv = suiv is not None and not EXCL_DL.search(suiv[2])
            src = t if _dates(t) else (suiv[2] if ok_suiv else "")
            for d in _dates(src):
                res["dl"].append((d, n))
            src = t if _heures(t) else (suiv[2] if ok_suiv else "")
            for h in _heures(src):
                res["hl"].append((h, n))

        # date limite d'envoi des questions, ou délai écrit
        if Q_KW.search(t):
            for d in _dates(t):
                res["dq"].append((d, n))
            for m in DELAI_RE.finditer(t):
                res["dq"].append((m.group(1).strip(), n))

        # dates de visite
        if (V_KW.search(t) and not EXCL_VIS.search(t)) or \
                (prec is not None and V_KW.search(prec[2]) and not EXCL_VIS.search(t)):
            for d in _dates(t):
                res["vis_dates"].append((d, n))

        # procédure
        for p in PROCEDURES:
            if p in tl:
                res["proc"].append((p, n))
        if re.search(r"(?<![\w\-/])mapa(?![\w\-/])", low):
            res["proc"].append(("procédure adaptée", n))

        # visite obligatoire, par phrase
        for s in re.split(r"[.;]", tl):
            if "visite" in s:
                sl = _sans_accents(s)
                if re.search(r"non obligatoire|facultati|pas obligatoire", sl):
                    res["visite"].append(("non", n))
                elif "obligatoire" in sl:
                    res["visite"].append(("oui", n))

        # variantes, par phrase
        for s in re.split(r"[.;]", tl):
            if "variante" in s:
                sl = _sans_accents(s)
                if NEG_VAR.search(sl):
                    res["variantes"].append(("non autorisées", n))
                elif POS_VAR.search(sl):
                    res["variantes"].append(("autorisées", n))

        # mode de remise, par phrase
        for s in re.split(r"[.;]", tl):
            sl = _sans_accents(s)
            if ELEC_RE.search(sl) and SENS_RE.search(sl) and not re.search(r"non electronique|pas electronique", sl):
                res["modes"].append(("électronique", n))
            if PAP_RE.search(sl) and not NEG_PAP.search(sl):
                res["modes"].append(("papier", n))

        # validité des offres, par phrase
        for s in re.split(r"[.;]", t):
            sl = _sans_accents(s.lower())
            if re.search(r"validit|valable", sl) and "offre" in sl:
                for m in VAL_RE.finditer(s):
                    nb = int(m.group(3)) if m.group(3) else (
                        int(m.group(1)) if m.group(1) else _nombre_lettres(m.group(2)))
                    if nb is None:
                        continue
                    unite = "mois" if m.group(4).lower().startswith("mois") else "jours"
                    res["validites"].append(({"nombre": nb, "unite": unite}, n))

        # limite de pages du mémoire technique
        if "memoire" in low:
            for m in PAGES_RE.finditer(t):
                nb = int(m.group(3)) if m.group(3) else (
                    int(m.group(1)) if m.group(1) else _nombre_lettres(m.group(2)))
                if nb is not None:
                    res["limites"].append((nb, n))
    return res

ART_RE = re.compile(r"^\s*(ARTICLE|Article|ANNEXE|Annexe)\b")
LOT_RE = re.compile(r"^\s*[-•*]?\s*lots?\s*(?:n\s*°\s*|n°\s*|n\s*o\s*|numéro\s*)?(\d+)\s*"
                    r"(?:[:\-–—]\s*(.*?))?\s*$", re.I)
LOT_UNIQUE_RE = re.compile(r"lot unique(?:\s*n\s*°\s*(\d+))?|n'est pas alloti|pas alloti\b|non alloti|"
                           r"pas (?:prevu )?de decomposition en lots", re.I)
LOT_UNIQUE_TXT = re.compile(r"lot unique(?:\s*n\s*°\s*\d+)?\s*[:\-–—]\s*(.+)$", re.I)
CTX_RE = re.compile(r"^\s*pour\s+(?:le|les)\s+lots?\s+((?:n\s*°\s*)?(?:\d+|à|et|,|\s)+)", re.I)
CRIT_KW = re.compile(r"critere|notees? sur \d+ points|jugement des offres", re.I)
CLASS_KW = re.compile(r"classes?|classees?|ordre decroissant|ordre d'importance|par ordre", re.I)
TOP_CRIT_N = re.compile(r"^\s*Crit[èe]re\s+n\s*°\s*(\d+)\s*[:—–-]\s*(.*)$", re.I)
TOP_NUM = re.compile(r"^\s*(\d+)\s*[.)\-–]\s+(.*)$")
TOP_PUCE = re.compile(r"^\s*[-•*]\s+(.*)$")
SUB_NUM = re.compile(r"^\s*\d+\.\d+\s+(.*)$")
SUB_LET = re.compile(r"^\s+[A-Za-z][.)]\s+(.*)$")
SUB_PUCE = re.compile(r"^\s+[-•*]\s+(.*)$")
PIECE_KW = re.compile(r"piece|document|au titre de|remett|produira|fournir|envisage d'attribuer", re.I)
PUCE = re.compile(r"^\s*[-•*]\s+")
NUM_PAR = re.compile(r"^\s*\d+\)\s+")


def _poids(txt):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", txt)
    if m:
        return _nombre_dec(m.group(1)), "pourcentage"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*pour\s*cent", txt, re.I)
    if m:
        return _nombre_dec(m.group(1)), "pourcentage"
    m = re.search(r"(" + NOMBRE_LETTRES + r")\s+pour\s+cent", txt, re.I)
    if m and _nombre_lettres(m.group(1)) is not None:
        return _nombre_lettres(m.group(1)), "pourcentage"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:points?|pts?)(?![a-zé])", txt, re.I)
    if m:
        return _nombre_dec(m.group(1)), "points"
    return None


def _libelle(txt):
    return re.split(r"\s*(?:[:(,|]|\s[–—-]\s)", txt, maxsplit=1)[0].strip(" ;.-–—")


def _liste_lots(s):
    toks = re.findall(r"\d+|à", s)
    out = []
    i = 0
    while i < len(toks):
        if toks[i].isdigit():
            if i + 2 < len(toks) and toks[i + 1] == "à" and toks[i + 2].isdigit():
                out.extend(range(int(toks[i]), int(toks[i + 2]) + 1))
                i += 3
                continue
            out.append(int(toks[i]))
        i += 1
    return sorted(set(out))


def _lot_ajoute(lots, ordre, num, texte, n):
    if num not in lots:
        lots[num] = {"intitules": {}, "pages": set()}
        ordre.append(num)
    lots[num]["pages"].add(n)
    texte = texte.strip(" ;.")
    if texte:
        lots[num]["intitules"].setdefault(_cle(texte), (texte, set()))[1].add(n)


def _ajoute_critere(recs, index, lab, n, poids, ctx):
    k = _cle(lab)
    if k not in index:
        index[k] = {"libelle": lab, "pages": set(), "poids": [], "ctx": [], "subs": {}}
        recs.append(index[k])
    c = index[k]
    c["pages"].add(n)
    c["ctx"].append((tuple(ctx) if ctx else None, n))
    if poids is not None:
        for lot in (list(ctx) if ctx else [None]):
            c["poids"].append((poids[0], poids[1], lot, n))
    return c


def _ajoute_sub(c, lab, poids, n):
    k = _cle(lab)
    s = c["subs"].get(k)
    if s is None:
        s = {"libelle": lab, "pages": set(), "poids": []}
        c["subs"][k] = s
    s["pages"].add(n)
    if poids is not None:
        s["poids"].append((poids[0], poids[1], None, n))


def _scan_criteres(L):
    recs, index = [], {}
    lots, lots_ordre = {}, []
    zone, classement, ctx, cur, compteur = False, False, None, None, 0
    for n, brut, t in L:
        tl = t.lower()
        low = _sans_accents(tl)
        if ART_RE.match(t):
            zone = bool(CRIT_KW.search(low))
            classement = False
            ctx, cur, compteur = None, None, 0
            continue
        m = LOT_RE.match(t)
        if m:
            num = int(m.group(1))
            txt = m.group(2) or ""
            _lot_ajoute(lots, lots_ordre, num, txt, n)
            if not txt.strip():
                ctx = [num]
            continue
        mu = LOT_UNIQUE_RE.search(low)
        if mu:
            num = int(mu.group(1)) if mu.group(1) else None
            mt = LOT_UNIQUE_TXT.search(t)
            _lot_ajoute(lots, lots_ordre, num, mt.group(1) if mt else "", n)
        mc = CTX_RE.match(tl)
        if mc:
            lst = _liste_lots(mc.group(1))
            if lst:
                ctx = lst
            continue
        if CRIT_KW.search(low):
            if not zone:
                compteur = 0
            zone = True
            if CLASS_KW.search(low):
                classement = True
        sub = SUB_NUM.match(brut) or SUB_LET.match(brut) or SUB_PUCE.match(brut)
        if cur is not None and sub:
            lab = _libelle(sub.group(1))
            if lab and len(lab) <= 150:
                _ajoute_sub(cur, lab, _poids(sub.group(1)), n)
            continue
        if TOP_CRIT_N.match(t):
            mm = TOP_CRIT_N.match(t)
            txt = mm.group(2)
        elif TOP_NUM.match(t):
            txt = TOP_NUM.match(t).group(2)
        elif TOP_PUCE.match(t):
            txt = TOP_PUCE.match(t).group(1)
        elif "|" in t and zone:
            txt = t
        else:
            continue
        if re.search(r"au titre de|piece", low):
            continue
        lab = _libelle(txt)
        if not lab or len(lab) > 150:
            continue
        if lab.lower() in ("critère", "critères", "criteres"):
            continue
        poids = _poids(txt)
        if not zone and poids is None:
            continue
        compteur += 1
        if poids is None and classement:
            num_rang = TOP_NUM.match(t)
            poids = (int(num_rang.group(1)) if num_rang else compteur, "rang")
        cur = _ajoute_critere(recs, index, lab, n, poids, ctx)
    return recs, lots, lots_ordre


def _scan_pieces(L):
    zone, phase = False, None
    pieces, ordre = {}, []
    for n, brut, t in L:
        low = _sans_accents(t.lower())
        if ART_RE.match(t):
            if PIECE_KW.search(low):
                zone, phase = True, _phase(low)
            else:
                zone, phase = False, None
            continue
        if PUCE.match(brut):
            if zone and not _poids(t):
                nom, obl = _piece_texte(brut)
                _piece_ajoute(pieces, ordre, nom, obl, phase, n)
            continue
        if PIECE_KW.search(low) and len(t) < 200:
            zone, phase = True, _phase(low)
            continue
        if NUM_PAR.match(brut) and zone and not _poids(t):
            nom, obl = _piece_texte(brut)
            _piece_ajoute(pieces, ordre, nom, obl, phase, n)
    return pieces, ordre


def _phase(low):
    if "candidature" in low:
        return "candidature"
    if "attributaire" in low or "attribuer" in low:
        return "attributaire"
    if "offre" in low:
        return "offre"
    return None


def _obligation(s):
    sl = _sans_accents(s.lower())
    if re.search(r"non obligatoire|facultati", sl):
        return "non obligatoire"
    if re.search(r"\bobligatoire\b", sl):
        return "obligatoire"
    return None


def _piece_texte(brut):
    s = re.sub(r"^\s*(?:[-•*]|\d+\))\s+", "", brut).strip()
    obl = _obligation(s)
    nom = re.sub(r"\s*\((?:non\s+)?obligatoire\)|\s*\(facultati(?:f|ve)\)", "", s, flags=re.I)
    nom = re.sub(r",?\s*à titre facultatif", "", nom, flags=re.I)
    return nom.strip(" ;.,"), obl


def _piece_ajoute(pieces, ordre, nom, obl, phase, n):
    if len(nom) < 3:
        return
    k = _cle(nom)
    p = pieces.get(k)
    if p is None:
        p = {"nom": nom, "pages": set(), "phase": [], "obligation": []}
        pieces[k] = p
        ordre.append(k)
    p["pages"].add(n)
    if phase:
        p["phase"].append((phase, n))
    if obl:
        p["obligation"].append((obl, n))

def _fait_fin(valeurs, unique):
    if not valeurs:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    return {"statut": TROUVE, "valeurs": valeurs, "conflit": bool(unique and len(valeurs) > 1)}


def _fait(couples, unique=False):
    """couples : liste de (valeur, pages). Regroupe les pages par valeur."""
    groupes, ordre = {}, []
    for v, pages in couples:
        k = _jk(v)
        if k not in groupes:
            groupes[k] = {"valeur": v, "pages": set()}
            ordre.append(k)
        groupes[k]["pages"].update(pages)
    valeurs = [{"valeur": groupes[k]["valeur"], "pages": sorted(groupes[k]["pages"])} for k in ordre]
    return _fait_fin(valeurs, unique)


def _fait_n(lst, unique=False):
    return _fait([(v, [n]) for v, n in lst], unique)


def _fait_poids(entrees):
    groupes, ordre = {}, []
    for v, u, lot, n in entrees:
        k = _jk([v, u, lot])
        if k not in groupes:
            groupes[k] = {"valeur": v, "unite": u, "lot": lot, "pages": set()}
            ordre.append(k)
        groupes[k]["pages"].add(n)
    valeurs = [{"valeur": groupes[k]["valeur"], "unite": groupes[k]["unite"], "lot": groupes[k]["lot"],
                "pages": sorted(groupes[k]["pages"])} for k in ordre]
    if not valeurs:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    par_lot = {}
    for v in valeurs:
        par_lot.setdefault(_jk(v["lot"]), set()).add(_jk(v["valeur"]))
    conflit = any(len(s) > 1 for s in par_lot.values())
    return {"statut": TROUVE, "valeurs": valeurs, "conflit": conflit}


def _fait_lot(c, declares):
    pages = sorted(c["pages"])
    avec = [(lots, n) for lots, n in c["ctx"] if lots]
    if not avec:
        if len(declares) == 1:
            return _fait([(declares[0], pages)])
        return _fait([(TOUS_LES_LOTS, pages)])
    couvre = set(x for lots, _ in avec for x in lots)
    nums = [d for d in declares if d is not None]
    if nums and set(nums) <= couvre:
        return _fait([(TOUS_LES_LOTS, pages)])
    par = {}
    for lots, n in avec:
        for x in lots:
            par.setdefault(x, []).append(n)
    return _fait([(x, sorted(set(p))) for x, p in par.items()])


def _type(recs):
    couples = []
    unites = {"pourcentage": "pourcentage", "points": "points", "rang": "classement"}
    for c in recs:
        for _v, u, _lot, n in c["poids"]:
            couples.append((unites[u], n))
    return _fait_n(couples, True)


def _criteres_liste(recs, declares):
    out = []
    for c in recs:
        out.append({
            "libelle": c["libelle"],
            "pages": sorted(c["pages"]),
            "lot": _fait_lot(c, declares),
            "ponderation": _fait_poids(c["poids"]),
            "sous_criteres": [{"libelle": s["libelle"], "pages": sorted(s["pages"]),
                               "ponderation": _fait_poids(s["poids"])} for s in c["subs"].values()],
        })
    return out


def _lots_liste(lots, ordre):
    out = []
    for num in ordre:
        l = lots[num]
        ints = [{"valeur": t, "pages": sorted(p)} for t, p in l["intitules"].values()]
        out.append({"numero": num, "intitules": ints, "pages": sorted(l["pages"]),
                    "conflit": len(ints) > 1})
    return out


def _pieces_liste(pieces, ordre):
    out = []
    for k in ordre:
        p = pieces[k]
        out.append({"nom": p["nom"], "pages": sorted(p["pages"]),
                    "phase": _fait_n(p["phase"]),
                    "obligation": _fait_n(p["obligation"], True)})
    return out


def _nature(lib):
    b = _sans_accents(lib.lower())
    if re.search(r"prix|cout", b):
        return "prix"
    if re.search(r"technique|qualite|valeur", b):
        return "technique"
    return None


def _premiere(f):
    return f["valeurs"][0]["valeur"] if f["valeurs"] else None


def _plan(criteres):
    plan = []
    for c in criteres:
        if _nature(c["libelle"]) != "technique":
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                plan.append({"titre": "%s – %s" % (c["libelle"], s["libelle"]),
                             "critere": c["libelle"], "sous_critere": s["libelle"],
                             "ponderation": _premiere(s["ponderation"]),
                             "page_source": s["pages"][0], "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": _premiere(c["ponderation"]),
                         "page_source": c["pages"][0], "contenu": ""})
    return plan


def _sommes_pourcentage(criteres):
    lots = []
    for c in criteres:
        for e in c["ponderation"]["valeurs"]:
            if e["unite"] == "pourcentage" and e["lot"] is not None and e["lot"] not in lots:
                lots.append(e["lot"])
    sommes = []
    for g in (lots or [None]):
        total = 0
        for c in criteres:
            ev = [e for e in c["ponderation"]["valeurs"] if e["unite"] == "pourcentage"
                  and (g is None or e["lot"] is None or e["lot"] == g)]
            if ev:
                total += ev[0]["valeur"]
        sommes.append(total)
    return sommes


def controler(dossier):
    """Alertes du contrôle, calculées sur les critères et le plan du dossier."""
    alertes = []
    plan = dossier.get("plan", [])
    criteres = (dossier.get("criteres") or {}).get("liste", [])
    couverts = set(s.get("critere") for s in plan)
    for c in criteres:
        if _nature(c["libelle"]) == "technique" and c["libelle"] not in couverts:
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in criteres:
        parent = c["ponderation"]["valeurs"]
        subs = [s["ponderation"]["valeurs"][0] for s in c["sous_criteres"] if s["ponderation"]["valeurs"]]
        if parent and subs:
            p = parent[0]
            total = sum(s["valeur"] for s in subs)
            cible = 100 if (subs[0]["unite"] == "pourcentage" and p["unite"] == "points") else p["valeur"]
            if abs(total - cible) > 1e-6:
                alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    tp = (dossier.get("type_ponderation") or {}).get("valeurs", [])
    if len(tp) == 1 and tp[0]["valeur"] == "pourcentage":
        if any(abs(s - 100) > 1e-6 for s in _sommes_pourcentage(criteres)):
            alertes.append({"type": "total différent de 100 %", "objet": "critères"})
    return alertes


def _dossier(faits, lots_liste, pieces_liste, criteres_liste):
    d = {cle: faits[cle] for cle in FAITS}
    d["lots"] = {"statut": TROUVE if lots_liste else NON_TROUVE, "liste": lots_liste}
    d["pieces"] = {"statut": TROUVE if pieces_liste else NON_TROUVE, "liste": pieces_liste}
    d["criteres"] = {"statut": TROUVE if criteres_liste else NON_TROUVE, "liste": criteres_liste}
    d["plan"] = _plan(criteres_liste)
    d["controle"] = {"alertes": []}
    d["controle"]["alertes"] = controler(d)
    return d


def analyser(pages):
    pages = ["" if p is None else str(p) for p in pages]
    L = _lignes(pages)
    r = _balayer(L)
    recs, lots, lots_ordre = _scan_criteres(L)
    pieces, pieces_ordre = _scan_pieces(L)
    declares = list(lots_ordre)
    faits = {
        "date_limite": _fait_n(r["dl"], True),
        "heure_limite": _fait_n(r["hl"], True),
        "date_questions": _fait_n(r["dq"], True),
        "procedure": _fait_n(r["proc"], True),
        "visite_obligatoire": _fait_n(r["visite"], True),
        "dates_visite": _fait_n(r["vis_dates"]),
        "variantes": _fait_n(r["variantes"], True),
        "validite_offres": _fait_n(r["validites"], True),
        "mode_remise": _fait_n(r["modes"], True),
        "limite_pages": _fait_n(r["limites"], True),
        "type_ponderation": _type(recs),
    }
    return _dossier(faits, _lots_liste(lots, lots_ordre), _pieces_liste(pieces, pieces_ordre),
                    _criteres_liste(recs, declares))


def _liste(d, cle):
    x = d.get(cle) if isinstance(d, dict) else None
    if isinstance(x, dict):
        y = x.get("liste", [])
        return y if isinstance(y, list) else []
    return []


def verifier(dossier, pages):
    """Ne garde que ce que le texte des pages retrouve ; le contenu retenu est celui du texte."""
    pages = ["" if p is None else str(p) for p in pages]
    ref = analyser(pages)
    faits = {}
    for cle in FAITS:
        f = dossier.get(cle) if isinstance(dossier, dict) else None
        proposees = f.get("valeurs", []) if isinstance(f, dict) else []
        refmap = {_jk(v["valeur"]): v for v in ref[cle]["valeurs"]}
        gardees, vus = [], set()
        for v in proposees:
            k = _jk(v.get("valeur"))
            if k in refmap and k not in vus:
                vus.add(k)
                gardees.append((refmap[k]["valeur"], refmap[k]["pages"]))
        faits[cle] = _fait(gardees, cle in FAITS_UNIQUES)

    refl = {_jk(l["numero"]): l for l in ref["lots"]["liste"]}
    lots_liste, vus = [], set()
    for l in _liste(dossier, "lots"):
        k = _jk(l.get("numero"))
        if k in refl and k not in vus:
            vus.add(k)
            lots_liste.append(copy.deepcopy(refl[k]))

    refp = {_cle(p["nom"]): p for p in ref["pieces"]["liste"]}
    pieces_liste, vus = [], set()
    for p in _liste(dossier, "pieces"):
        k = _cle(p.get("nom", ""))
        if k in refp and k not in vus:
            vus.add(k)
            pieces_liste.append(copy.deepcopy(refp[k]))

    refc = {_cle(c["libelle"]): c for c in ref["criteres"]["liste"]}
    criteres_liste, vus = [], set()
    for c in _liste(dossier, "criteres"):
        k = _cle(c.get("libelle", ""))
        if k in refc and k not in vus:
            vus.add(k)
            criteres_liste.append(copy.deepcopy(refc[k]))

    return _dossier(faits, lots_liste, pieces_liste, criteres_liste)
