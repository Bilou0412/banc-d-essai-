"""Lecture déterministe d'un règlement de la consultation (RC).

Points d'entrée : analyser(pages), verifier(dossier, pages), controler(dossier).
"""

import datetime
import json
import re

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

# ---------------------------------------------------------------- nombres en lettres

_UNITES = {"zero": 0, "zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
           "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
           "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16}
_DIZAINES = {"vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50,
             "soixante": 60}
_MOTS = sorted(list(_UNITES) + list(_DIZAINES) + ["cent", "cents"], key=len, reverse=True)
_W = r"\b(?:%s)\b" % "|".join(_MOTS)
_NBRE = r"%s(?:[-\s]+(?:et[-\s]+)?%s)*" % (_W, _W)


def _parse_mots(s):
    total = 0
    prev = None
    for t in re.split(r"[-\s]+", s.lower()):
        if not t or t == "et":
            continue
        if t in _UNITES:
            total += _UNITES[t]
        elif t in _DIZAINES:
            if t.startswith("vingt") and prev == "quatre":
                total += 76
            else:
                total += _DIZAINES[t]
        elif t in ("cent", "cents"):
            total = (total if total else 1) * 100
        prev = t
    return total


def _intify(x):
    return int(x) if float(x).is_integer() else float(x)


def _val_num(g):
    g = g.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", g):
        return _intify(g.replace(",", "."))
    return _parse_mots(g)


# ---------------------------------------------------------------- texte

def _prep(t):
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[^\S\n]", " ", t)
    return t.replace("’", "'").replace("‘", "'")


def _k(s):
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()


_RX_Q = re.compile(r"questions?|renseignements?\s+compl[ée]mentaires|demandes?\s+de\s+renseignements?", re.I)
_RX_V = re.compile(r"visite", re.I)
_RX_O1 = re.compile(r"\boffres?\b|\bplis?\b|candidatures?", re.I)
_RX_O2 = re.compile(r"limite|plus\s+tard|jusqu|parvenir|remise|r[ée]ception|d[ée]p[ôo]|attendu|remis|transmi", re.I)


def _cat(s):
    if _RX_Q.search(s):
        return "q"
    if _RX_V.search(s):
        return "v"
    if _RX_O1.search(s) and _RX_O2.search(s):
        return "o"
    return None


def _unites(texte):
    """Phrases de la page avec leur catégorie (q, v, o ou None)."""
    t = re.sub(r"(?<![.;:!?])\n[ ]*(?=[a-zà-ÿ])", " ", texte)
    res = []
    prev_cat = None
    prev_header = False
    for ligne in t.split("\n"):
        ligne = ligne.strip()
        if not ligne:
            continue
        phrases = [s for s in re.split(r"(?<=[.!?])\s+", ligne) if s]
        for i, s in enumerate(phrases):
            c = _cat(s)
            if c is None and (i > 0 or prev_header):
                c = prev_cat
            res.append((s, c))
            prev_cat = c
        prev_header = not re.search(r"[.!?;]$", ligne)
    return res


def _phrases(texte):
    return [s for s, _ in _unites(texte)]


# ---------------------------------------------------------------- dates et heures

_MOIS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
         "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
         "décembre": 12, "decembre": 12}
_RX_DATE_L = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:er|ère)?\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[ée]cembre)\s+(\d{4})(?!\d)", re.I)
_RX_DATE_N = re.compile(r"(?<![\d/.\-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")


def _date(j, m, a):
    a = int(a)
    if a < 100:
        a += 2000
    try:
        datetime.date(a, int(m), int(j))
    except ValueError:
        return None
    return "%02d/%02d/%04d" % (int(j), int(m), a)


def _dates(s):
    r = []
    for m in _RX_DATE_L.finditer(s):
        d = _date(m.group(1), _MOIS[m.group(2).lower()], m.group(3))
        if d:
            r.append((m.start(), d))
    for m in _RX_DATE_N.finditer(s):
        d = _date(m.group(1), m.group(2), m.group(3))
        if d:
            r.append((m.start(), d))
    return [d for _, d in sorted(r)]


_RX_H = re.compile(r"(?<![\d/.:])(\d{1,2})\s*h(?:\s*(\d{2}))?(?![a-zà-ÿ\d])", re.I)
_RX_HEURES = re.compile(r"(?<![\d/.:])(\d{1,2})\s*heures?(?:\s*(\d{2})(?!\d))?", re.I)
_RX_COLON = re.compile(r"(?<![\d/.:])(\d{1,2}):(\d{2})(?!\d)")
_RX_HW = re.compile(r"(?P<h>%s)\s+heures?(?:\s+(?:et\s+(?P<f>demie|quart)|(?P<m>%s)))?" % (_NBRE, _NBRE), re.I)
_RX_MIDI = re.compile(r"\bmidi\b", re.I)


def _heures(s):
    r = []
    for m in _RX_H.finditer(s):
        r.append((m.start(), int(m.group(1)), int(m.group(2) or 0)))
    for m in _RX_HEURES.finditer(s):
        r.append((m.start(), int(m.group(1)), int(m.group(2) or 0)))
    for m in _RX_COLON.finditer(s):
        r.append((m.start(), int(m.group(1)), int(m.group(2))))
    for m in _RX_HW.finditer(s):
        mn = 0
        if m.group("f"):
            mn = 30 if m.group("f").lower() == "demie" else 15
        elif m.group("m"):
            mn = _parse_mots(m.group("m"))
        r.append((m.start(), _parse_mots(m.group("h")), mn))
    for m in _RX_MIDI.finditer(s):
        r.append((m.start(), 12, 0))
    return ["%02d:%02d" % (h, mn) for _, h, mn in sorted(r) if h < 24 and mn < 60]


_RX_DELAI = re.compile(
    r"(?<![\d,.])(?:\d+|%s)(?:\s*\(\s*\d+\s*\))?\s+jours?(?:\s+(?:calendaires|ouvr[ée]s|ouvrables|francs))?"
    r"\s+(?:avant|pr[ée]c[ée]dant)\s+la\s+date\s+limite"
    r"(?:\s+de\s+(?:remise|r[ée]ception|d[ée]p[ôo]t)\s+des\s+(?:offres|plis))?" % _NBRE, re.I)


# ---------------------------------------------------------------- faits

def _fait(occ, conflit=True):
    vals = []
    idx = {}
    for v, p in occ:
        k = json.dumps(v, sort_keys=True, ensure_ascii=False)
        if k not in idx:
            idx[k] = {"valeur": v, "pages": []}
            vals.append(idx[k])
        if p not in idx[k]["pages"]:
            idx[k]["pages"].append(p)
    for x in vals:
        x["pages"].sort()
    return {"statut": TROUVE if vals else NON_TROUVE, "valeurs": vals,
            "conflit": bool(conflit and len(vals) > 1)}


# ---------------------------------------------------------------- procédure, visite, variantes...

_PROCS = [
    (re.compile(r"\bMAPA\b"), "procédure adaptée"),
    (re.compile(r"proc[ée]dure\s+adapt[ée]e", re.I), "procédure adaptée"),
    (re.compile(r"appel\s+d'offres\s+ouvert", re.I), "appel d'offres ouvert"),
    (re.compile(r"appel\s+d'offres\s+restreint", re.I), "appel d'offres restreint"),
    (re.compile(r"dialogue\s+comp[ée]titif", re.I), "dialogue compétitif"),
    (re.compile(r"proc[ée]dure\s+concurrentielle\s+avec\s+n[ée]gociation", re.I),
     "procédure concurrentielle avec négociation"),
]

_RX_NEG_V = re.compile(r"non\s+obligatoire|(?:n'est|ne\s+sont)\s+pas\s+(?:obligatoire|exig|requise|imp)|"
                       r"facultati|pas\s+obligatoire|optionnel", re.I)
_RX_POS_V = re.compile(r"obligatoire|exig[ée]e|imp[ée]rative", re.I)

_RX_VAR = re.compile(r"variantes?", re.I)
_RX_NEG_VAR = re.compile(r"aucune\s+variante|interdit|\bnon\s+(?:autoris|admis|accept|permis)|"
                         r"pas\s+(?:autoris|admis|accept|permis|possible)|refus|exclu|ne\s+seront\s+pas", re.I)
_RX_POS_VAR = re.compile(r"autoris|admis|accept|permis|possible", re.I)

_RX_VALID = re.compile(r"validit[ée]|valables?", re.I)
_RX_DUREE = re.compile(r"(?<![\d,.])(?P<n>\d+|%s)(?:\s*\(\s*(?P<p>\d+)\s*\))?\s+(?P<u>jours?|mois)\b" % _NBRE, re.I)

_RX_REMISE = re.compile(r"offres?\b|\bplis?\b|remise|remis|d[ée]p[ôo]|transmi|envoi", re.I)
_RX_ELEC = re.compile(r"[ée]lectroni|d[ée]mat[ée]rialis|plateforme|profil\s+d'acheteur|t[ée]l[ée]transmi", re.I)
_RX_PAP = re.compile(r"papier|pli\s+cachet", re.I)
_RX_NEG_P = re.compile(r"\b(?:aucune?|pas|non|interdit\w*|refus\w*|sans)\b", re.I)

_RX_LIM = re.compile(r"(?<![\d,.])(?P<n>\d+|%s)(?:\s*\(\s*(?P<p>\d+)\s*\))?\s+pages?\b" % _NBRE, re.I)
_RX_MEM = re.compile(r"m[ée]moire", re.I)


def _nb(m):
    if m.group("p"):
        return int(m.group("p"))
    return _val_num(m.group("n"))


# ---------------------------------------------------------------- lots

_RX_LOT = re.compile(r"^(?:[-•*–·]\s*)?lot\s*(?:n\s*[°ºo]\s*\.?|num[ée]ro)?\s*0*(\d+)\s*[:\-–—]\s*(\S.*)$", re.I)
_RX_LOT_CTX = re.compile(r"^(?:pour\s+(?:le\s+)?)?lot\s*(?:n\s*[°ºo]\s*\.?)?\s*0*(\d+)\s*:?\s*$", re.I)
_RX_UNIQ = re.compile(
    r"lot\s+unique|n'est\s+pas\s+alloti|non\s+alloti|"
    r"pas\s+(?:de\s+)?(?:d[ée]composition\s+en\s+lots|allotissement)|"
    r"pas\s+pr[ée]vu\s+de\s+(?:d[ée]composition\s+en\s+lots|allotissement)|"
    r"sans\s+allotissement|ne\s+comporte\s+pas\s+de\s+lots?", re.I)
_RX_UNIQ_T = re.compile(r"lot\s+unique\s*:\s*([^.;]+)", re.I)


def _lots(P):
    lots = {}
    ordre = []
    for pn, txt in enumerate(P, 1):
        for ligne in txt.split("\n"):
            m = _RX_LOT.match(ligne.strip())
            if not m:
                continue
            num = int(m.group(1))
            titre = re.sub(r"[\s;.,:]+$", "", m.group(2)).strip()
            if not titre:
                continue
            if num not in lots:
                lots[num] = {"ints": {}, "ordre": []}
                ordre.append(num)
            L = lots[num]
            k = _k(titre)
            if k not in L["ints"]:
                L["ints"][k] = {"valeur": titre, "pages": []}
                L["ordre"].append(k)
            if pn not in L["ints"][k]["pages"]:
                L["ints"][k]["pages"].append(pn)
    liste = []
    if ordre:
        for num in ordre:
            L = lots[num]
            ints = [{"valeur": L["ints"][k]["valeur"], "pages": sorted(L["ints"][k]["pages"])} for k in L["ordre"]]
            pages = sorted({p for i in ints for p in i["pages"]})
            liste.append({"numero": num, "intitules": ints, "pages": pages, "conflit": len(ints) > 1})
    else:
        # un lot unique n'est retenu que si aucun lot numéroté n'est écrit dans le texte
        flat_all = [(pn, re.sub(r"\s+", " ", t)) for pn, t in enumerate(P, 1)]
        pages = [pn for pn, f in flat_all if _RX_UNIQ.search(f)]
        if pages:
            f = _fait(uniq_titres_to_occ(flat_all))
            ints = f["valeurs"]
            liste.append({"numero": None, "intitules": ints, "pages": pages, "conflit": len(ints) > 1})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


def uniq_titres_to_occ(flat_all):
    occ = []
    for pn, f in flat_all:
        if _RX_UNIQ.search(f):
            m = _RX_UNIQ_T.search(f)
            if m and m.group(1).strip():
                occ.append((m.group(1).strip(), pn))
    return occ


# ---------------------------------------------------------------- pièces

_RX_BULLET = re.compile(r"^(\s*)[-•*–·▪●]\s+(.+)$")
_RX_FOOTER = re.compile(r"^page\s+\d+(?:\s*(?:sur|/)\s*\d+)?$", re.I)
_RX_INTRO = re.compile(r"pi[èe]ces?|documents?|dossier|remettr|produi|fourni|contenu|\bplis\b|joindre|comprend|constitu", re.I)
_RX_ANYPOIDS = re.compile(r"%|\bpoints?\b|\bpts?\b|pour\s+cent", re.I)
_RX_ATTR = re.compile(r"attributaire|envisag[ée]\s+d'attribuer|titulaire\s+pressenti", re.I)
_RX_NEG_OBL = re.compile(r"facultati|non\s+obligatoire|optionnel|à\s+titre\s+(?:facultatif|indicatif)", re.I)
_RX_POS_OBL = re.compile(r"obligatoire", re.I)


def _phase(s):
    if _RX_ATTR.search(s):
        return "attributaire"
    if re.search(r"candidature", s, re.I):
        return "candidature"
    if re.search(r"offres?\b", s, re.I):
        return "offre"
    return None


def _nom_piece(t):
    t = re.sub(r"[\s;.,:]+$", "", t.strip())
    t = re.sub(r"\s*\(\s*(?:obligatoires?|facultati(?:f|ve)s?|optionnel(?:le)?s?)\s*\)", "", t, flags=re.I)
    t = re.sub(r",?\s*à\s+titre\s+(?:facultatif|optionnel)", "", t, flags=re.I)
    return re.sub(r"[\s;.,:]+$", "", t).strip()


def _pieces(P):
    pieces = {}
    ordre = []
    in_p = False
    phase = None
    for pn, txt in enumerate(P, 1):
        for ligne in txt.split("\n"):
            s = ligne.strip()
            if not s or _RX_FOOTER.match(s):
                continue
            m = _RX_BULLET.match(ligne)
            if m:
                if in_p:
                    nom = _nom_piece(m.group(2))
                    if not nom:
                        continue
                    k = _k(nom)
                    if k not in pieces:
                        pieces[k] = {"nom": nom, "pages": [], "phase": [], "obl": []}
                        ordre.append(k)
                    p = pieces[k]
                    if pn not in p["pages"]:
                        p["pages"].append(pn)
                    if phase:
                        p["phase"].append((phase, pn))
                    if _RX_NEG_OBL.search(m.group(2)):
                        p["obl"].append(("non obligatoire", pn))
                    elif _RX_POS_OBL.search(m.group(2)):
                        p["obl"].append(("obligatoire", pn))
                continue
            if _RX_INTRO.search(s) and not _RX_ANYPOIDS.search(s):
                if not in_p:
                    phase = None
                in_p = True
                ph = _phase(s)
                if ph:
                    phase = ph
            else:
                in_p = False
                phase = None
    liste = []
    for k in ordre:
        p = pieces[k]
        liste.append({"nom": p["nom"], "pages": sorted(p["pages"]),
                      "phase": _fait(p["phase"], conflit=False),
                      "obligation": _fait(p["obl"])})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ---------------------------------------------------------------- critères

_RX_START = re.compile(r"crit[èe]res?|pond[ée]r|\bnot[ée]e?s?\b|jug[ée]e?s?\b|jugement|class[ée]e?s?\b|"
                       r"classement|appr[ée]ci", re.I)
_RX_END = re.compile(r"^\s*(?:article|annexe|chapitre|titre|section)\b", re.I)
_RX_CLASS = re.compile(r"class[ée]e?s?\s+par\s+ordre|ordre\s+(?:d[ée]croissant|croissant|d'importance|"
                       r"de\s+(?:priorit|pr[ée]f[ée]rence))|classement", re.I)

_RX_IT_CRIT = re.compile(r"^(\s*)crit[èe]re\s+n\s*[°ºo]?\s*(\d+)\s*[:.\-–]\s*(.+)$", re.I)
_RX_IT_SUB = re.compile(r"^(\s*)(\d+\.\d+)(?:\.\d+)*[.)]?\s+(.+)$")
_RX_IT_NUM = re.compile(r"^(\s*)(\d+)[.)]\s+(.+)$")
_RX_IT_ALPHA = re.compile(r"^(\s*)([a-z])\)\s+(.+)$", re.I)
_RX_IT_DASH = re.compile(r"^(\s*)[-•*–·▪●]\s+(.+)$")

_RX_POIDS = [
    (re.compile(r"(?<![\d,.])(?P<n>\d+(?:[.,]\d+)?)\s*(?:%|pour\s*cent)", re.I), "pourcentage"),
    (re.compile(r"(?P<n>%s)\s+pour\s+cent" % _NBRE, re.I), "pourcentage"),
    (re.compile(r"(?<![\d,.])(?P<n>\d+(?:[.,]\d+)?)\s*(?:points?|pts?)\b", re.I), "points"),
    (re.compile(r"(?P<n>%s)\s+points?\b" % _NBRE, re.I), "points"),
]


def _label(t):
    t = re.sub(r"[\s:;,.(\-–—]+$", "", t)
    return re.sub(r"^[\s:;\-–—]+", "", t).strip()


def _poids(text):
    best = None
    for rx, u in _RX_POIDS:
        m = rx.search(text)
        if m and (best is None or m.start() < best[0].start()):
            best = (m, u)
    if best is None:
        return _label(text), None
    m, u = best
    return _label(text[:m.start()]), (_val_num(m.group("n")), u)


def _parse_item(line):
    m = _RX_IT_CRIT.match(line)
    if m:
        return "crit", len(m.group(1)), m.group(2), m.group(3)
    m = _RX_IT_SUB.match(line)
    if m:
        return "sub", len(m.group(1)), m.group(2), m.group(3)
    m = _RX_IT_NUM.match(line)
    if m:
        return "num", len(m.group(1)), m.group(2), m.group(3)
    m = _RX_IT_ALPHA.match(line)
    if m:
        return "alpha", len(m.group(1)), m.group(2), m.group(3)
    m = _RX_IT_DASH.match(line)
    if m:
        return "dash", len(m.group(1)), None, m.group(2)
    return None


def _ajout_poids(entree, key, pn):
    pg = entree["poids"].setdefault(key, [])
    if pn not in pg:
        pg.append(pn)


def _criteres_extraire(P):
    crits = {}
    ordre = []
    for pn, txt in enumerate(P, 1):
        in_crit = False
        lot = None
        classement = False
        last_top = None
        last_style = None
        last_indent = 0
        ntop = 0
        for ligne in txt.split("\n"):
            s = ligne.strip()
            if not s:
                continue
            item = _parse_item(ligne)
            if _RX_START.search(s) and not in_crit:
                in_crit = True
                lot = None
                classement = False
                last_top = None
                ntop = 0
            elif (not in_crit and item and item[0] in ("crit", "num")
                  and _poids(item[3])[1] is not None):
                in_crit = True
                lot = None
                classement = False
                last_top = None
                ntop = 0
            elif in_crit and _RX_END.match(s) and not _RX_START.search(s):
                in_crit = False
                lot = None
                last_top = None
                continue
            if not in_crit:
                continue
            if _RX_CLASS.search(s):
                classement = True
            ml = _RX_LOT_CTX.match(s)
            if ml:
                lot = int(ml.group(1))
                last_top = None
                continue
            if not item:
                continue
            kind, indent, num, text = item
            label, poids = _poids(text)
            if not label:
                continue
            niveau = "top"
            if kind in ("sub", "alpha"):
                niveau = "sub"
            elif kind == "dash" and last_top is not None and last_style in ("num", "crit") and indent > last_indent:
                niveau = "sub"
            if niveau == "sub":
                if last_top is None:
                    continue
                c = last_top
                k = _k(label)
                if k not in c["subidx"]:
                    c["subidx"][k] = {"libelle": label, "pages": [], "poids": {}}
                    c["subs"].append(c["subidx"][k])
                sc = c["subidx"][k]
                if pn not in sc["pages"]:
                    sc["pages"].append(pn)
                if poids:
                    _ajout_poids(sc, (poids[0], poids[1], lot), pn)
                continue
            ntop += 1
            k = _k(label)
            if k not in crits:
                crits[k] = {"libelle": label, "pages": [], "poids": {}, "lots": [], "subs": [], "subidx": {}}
                ordre.append(k)
            c = crits[k]
            if pn not in c["pages"]:
                c["pages"].append(pn)
            if lot is not None and lot not in c["lots"]:
                c["lots"].append(lot)
            if poids is None and classement:
                rang = int(num) if num and num.isdigit() else ntop
                poids = (rang, "rang")
            if poids:
                _ajout_poids(c, (poids[0], poids[1], lot), pn)
            last_top = c
            last_style = "dash" if kind == "dash" else "num"
            last_indent = indent
    return [crits[k] for k in ordre]


def _conflit_pond(valeurs):
    par_lot = {}
    for v in valeurs:
        par_lot.setdefault(v["lot"], set()).add((v["valeur"], v["unite"]))
    return any(len(x) > 1 for x in par_lot.values())


def _fait_pond(poids):
    valeurs = [{"valeur": k[0], "unite": k[1], "lot": k[2], "pages": sorted(pg)} for k, pg in poids.items()]
    return {"statut": TROUVE if valeurs else NON_TROUVE, "valeurs": valeurs,
            "conflit": _conflit_pond(valeurs)}


def _lot_critere(lots_where, lots_liste):
    numeros = [l["numero"] for l in lots_liste if l["numero"] is not None]
    if not lots_where:
        if len(lots_liste) == 1:
            return [lots_liste[0]["numero"]]
        return ["tous les lots"]
    ws = set(lots_where)
    if (len(numeros) >= 2 and set(numeros) <= ws) or (not numeros and len(ws) >= 2):
        return ["tous les lots"]
    return sorted(ws)


_TYPE_POIDS = {"pourcentage": "pourcentage", "points": "points", "rang": "classement"}


def _criteres(P, lots_liste):
    crits = _criteres_extraire(P)
    liste = []
    types = []
    for c in crits:
        subs = []
        for sc in c["subs"]:
            subs.append({"libelle": sc["libelle"], "pages": sorted(sc["pages"]), "ponderation": _fait_pond(sc["poids"])})
            for k, pg in sc["poids"].items():
                types.extend((_TYPE_POIDS[k[1]], p) for p in pg)
        for k, pg in c["poids"].items():
            types.extend((_TYPE_POIDS[k[1]], p) for p in pg)
        pages = sorted(c["pages"])
        lots_val = _lot_critere(c["lots"], lots_liste)
        liste.append({"libelle": c["libelle"], "pages": pages,
                      "lot": {"statut": TROUVE, "valeurs": [{"valeur": v, "pages": list(pages)} for v in lots_val],
                              "conflit": False},
                      "ponderation": _fait_pond(c["poids"]),
                      "sous_criteres": subs})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}, _fait(types)


# ---------------------------------------------------------------- plan et contrôle

def _nature(lib):
    l = lib.lower()
    if re.search(r"\bprix\b|co[ûu]t|tarif|montant|financ|redevance", l) and not re.search(r"techni|qualit", l):
        return "prix"
    if re.search(r"techni|qualit[ée]|m[ée]thod|valeur", l):
        return "technique"
    return "autre"


def _pond_plan(fait):
    vs = [v["valeur"] for v in fait["valeurs"]]
    return vs[0] if vs else None


def _plan(liste):
    plan = []
    for c in liste:
        if _nature(c["libelle"]) != "technique":
            continue
        pg = c["pages"][0] if c["pages"] else 1
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                plan.append({"titre": s["libelle"], "critere": c["libelle"], "sous_critere": s["libelle"],
                             "ponderation": _pond_plan(s["ponderation"]),
                             "page_source": s["pages"][0] if s["pages"] else pg, "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": _pond_plan(c["ponderation"]), "page_source": pg, "contenu": ""})
    return plan


def _premiere(fait, lot):
    for v in fait["valeurs"]:
        if v["lot"] == lot and v["unite"] != "rang":
            return v["valeur"]
    return None


def controler(dossier):
    alertes = []
    plan = dossier.get("plan", [])
    crits = dossier["criteres"]["liste"]
    for c in crits:
        if _nature(c["libelle"]) == "technique" and not any(s["critere"] == c["libelle"] for s in plan):
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in crits:
        if not c["sous_criteres"]:
            continue
        lots = []
        for v in c["ponderation"]["valeurs"]:
            if v["unite"] != "rang" and v["lot"] not in lots:
                lots.append(v["lot"])
        for lot in lots:
            parent = _premiere(c["ponderation"], lot)
            somme = [_premiere(s["ponderation"], lot) for s in c["sous_criteres"]]
            somme = [x for x in somme if x is not None]
            if somme and parent is not None and abs(sum(somme) - parent) > 1e-6:
                a = {"type": "pondérations incohérentes", "objet": c["libelle"]}
                if a not in alertes:
                    alertes.append(a)
    types = {v["valeur"] for v in dossier["type_ponderation"]["valeurs"]}
    if types == {"pourcentage"}:
        cles = []
        for c in crits:
            for v in c["ponderation"]["valeurs"]:
                if v["lot"] not in cles:
                    cles.append(v["lot"])
        if any(k is not None for k in cles):
            cles = [k for k in cles if k is not None]
        for lot in cles:
            vals = []
            for c in crits:
                v = _premiere(c["ponderation"], lot)
                if v is None and lot is not None:
                    v = _premiere(c["ponderation"], None)
                if v is not None:
                    vals.append(v)
            if vals and abs(sum(vals) - 100) > 1e-6:
                alertes.append({"type": "total différent de 100 %",
                                "objet": "critères" if lot is None else "lot %s" % lot})
    return alertes


# ---------------------------------------------------------------- extraction

def _extraire(pages):
    P = [_prep(p if isinstance(p, str) else "") for p in pages]
    occ = {k: [] for k in ("date_limite", "heure_limite", "date_questions", "procedure",
                           "visite_obligatoire", "dates_visite", "variantes", "validite_offres",
                           "mode_remise", "limite_pages")}
    for pn, txt in enumerate(P, 1):
        flat = re.sub(r"\s+", " ", txt)
        for rx, val in _PROCS:
            if rx.search(flat):
                occ["procedure"].append((val, pn))
        for s, c in _unites(txt):
            if c == "o":
                occ["date_limite"].extend((d, pn) for d in _dates(s))
                occ["heure_limite"].extend((h, pn) for h in _heures(s))
            elif c == "q":
                occ["date_questions"].extend((d, pn) for d in _dates(s))
                m = _RX_DELAI.search(s)
                if m:
                    occ["date_questions"].append((re.sub(r"\s+", " ", m.group(0)), pn))
            elif c == "v":
                occ["dates_visite"].extend((d, pn) for d in _dates(s))
            if _RX_V.search(s):
                if _RX_NEG_V.search(s):
                    occ["visite_obligatoire"].append(("non", pn))
                elif _RX_POS_V.search(s):
                    occ["visite_obligatoire"].append(("oui", pn))
            if _RX_VAR.search(s):
                if _RX_NEG_VAR.search(s):
                    occ["variantes"].append(("non autorisées", pn))
                elif _RX_POS_VAR.search(s):
                    occ["variantes"].append(("autorisées", pn))
            mv = _RX_VALID.search(s)
            if mv:
                md = _RX_DUREE.search(s, mv.start()) or _RX_DUREE.search(s)
                if md:
                    n = _nb(md)
                    u = "jours" if md.group("u").lower().startswith("jour") else "mois"
                    occ["validite_offres"].append(({"nombre": n, "unite": u}, pn))
            if _RX_REMISE.search(s):
                if _RX_PAP.search(s) and not _RX_NEG_P.search(s):
                    occ["mode_remise"].append(("papier", pn))
                if _RX_ELEC.search(s):
                    occ["mode_remise"].append(("électronique", pn))
            if _RX_MEM.search(s):
                ml = _RX_LIM.search(s)
                if ml:
                    occ["limite_pages"].append((_nb(ml), pn))
    lots = _lots(P)
    criteres, type_pond = _criteres(P, lots["liste"])
    d = {"lots": lots}
    for cle in ("date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire"):
        d[cle] = _fait(occ[cle])
    d["dates_visite"] = _fait(occ["dates_visite"], conflit=False)
    for cle in ("variantes", "validite_offres", "mode_remise"):
        d[cle] = _fait(occ[cle])
    d["pieces"] = _pieces(P)
    d["limite_pages"] = _fait(occ["limite_pages"])
    d["type_ponderation"] = type_pond
    d["criteres"] = criteres
    d["plan"] = _plan(criteres["liste"])
    d["controle"] = {"alertes": controler(d)}
    return d


# ---------------------------------------------------------------- vérification

def _inter_fait(d, e, conflit=True):
    dv = [v.get("valeur") for v in (d or {}).get("valeurs", [])]
    vals = [{"valeur": v["valeur"], "pages": list(v["pages"])} for v in e["valeurs"] if v["valeur"] in dv]
    return {"statut": TROUVE if vals else NON_TROUVE, "valeurs": vals,
            "conflit": bool(conflit and len(vals) > 1)}


def _inter_pond(d, e):
    dk = [(v.get("valeur"), v.get("unite"), v.get("lot")) for v in (d or {}).get("valeurs", [])]
    vals = [dict(v, pages=list(v["pages"])) for v in e["valeurs"] if (v["valeur"], v["unite"], v["lot"]) in dk]
    return {"statut": TROUVE if vals else NON_TROUVE, "valeurs": vals, "conflit": _conflit_pond(vals)}


def verifier(dossier, pages):
    e = _extraire(pages)
    dossier = dossier or {}
    out = {}
    # lots
    dl = {l.get("numero"): l for l in dossier.get("lots", {}).get("liste", [])}
    lots = []
    for el in e["lots"]["liste"]:
        if el["numero"] not in dl:
            continue
        di = [i.get("valeur") for i in dl[el["numero"]].get("intitules", [])]
        ints = [{"valeur": i["valeur"], "pages": list(i["pages"])} for i in el["intitules"] if i["valeur"] in di]
        if el["intitules"] and not ints:
            continue
        pages_l = sorted({p for i in ints for p in i["pages"]}) if ints else list(el["pages"])
        lots.append({"numero": el["numero"], "intitules": ints, "pages": pages_l, "conflit": len(ints) > 1})
    out["lots"] = {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}
    for cle in ("date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                "variantes", "validite_offres", "mode_remise", "limite_pages", "type_ponderation"):
        out[cle] = _inter_fait(dossier.get(cle), e[cle])
    out["dates_visite"] = _inter_fait(dossier.get("dates_visite"), e["dates_visite"], conflit=False)
    # pièces
    dp = {_k(p.get("nom", "")): p for p in dossier.get("pieces", {}).get("liste", [])}
    pieces = []
    for ep in e["pieces"]["liste"]:
        dpi = dp.get(_k(ep["nom"]))
        if dpi is None:
            continue
        pieces.append({"nom": ep["nom"], "pages": list(ep["pages"]),
                       "phase": _inter_fait(dpi.get("phase"), ep["phase"], conflit=False),
                       "obligation": _inter_fait(dpi.get("obligation"), ep["obligation"])})
    out["pieces"] = {"statut": TROUVE if pieces else NON_TROUVE, "liste": pieces}
    # critères
    dc = {_k(c.get("libelle", "")): c for c in dossier.get("criteres", {}).get("liste", [])}
    crits = []
    for ec in e["criteres"]["liste"]:
        c = dc.get(_k(ec["libelle"]))
        if c is None:
            continue
        ds = {_k(s.get("libelle", "")): s for s in c.get("sous_criteres", [])}
        subs = []
        for es in ec["sous_criteres"]:
            s = ds.get(_k(es["libelle"]))
            if s is None:
                continue
            subs.append({"libelle": es["libelle"], "pages": list(es["pages"]),
                         "ponderation": _inter_pond(s.get("ponderation"), es["ponderation"])})
        crits.append({"libelle": ec["libelle"], "pages": list(ec["pages"]),
                      "lot": _inter_fait(c.get("lot"), ec["lot"], conflit=False),
                      "ponderation": _inter_pond(c.get("ponderation"), ec["ponderation"]),
                      "sous_criteres": subs})
    out["criteres"] = {"statut": TROUVE if crits else NON_TROUVE, "liste": crits}
    out["plan"] = _plan(crits)
    out["controle"] = {"alertes": controler(out)}
    return out


def analyser(pages):
    pages = list(pages)
    return verifier(_extraire(pages), pages)
