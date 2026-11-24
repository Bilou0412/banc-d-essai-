"""Analyse déterministe d'un règlement de la consultation (RC).

Point d'entrée : analyser(pages). Rend un dossier sérialisable en JSON.
"""

import copy
import json
import re

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

MOIS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12, "décembre": 12,
}

NOMBRES = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "dix-sept": 17,
    "dix-huit": 18, "dix-neuf": 19, "vingt": 20, "trente": 30, "quarante": 40,
    "cinquante": 50, "soixante": 60, "soixante-dix": 70, "quatre-vingt": 80,
    "quatre-vingt-dix": 90, "cent": 100,
}

_MOT = (r"(?:cent|quatre|vingts|vingt|soixante|dix|onze|douze|treize|quatorze|quinze|seize|sept|huit|neuf|"
        r"cinq|six|deux|trois|un|une|trente|quarante|cinquante|et)")
NOMBRE_RE = r"(?:" + _MOT + r"(?:[- ]" + _MOT + r"){0,4})"


def _norm(s):
    s = s.replace("’", "'").replace(" ", " ").replace(" ", " ")
    s = s.replace("\r", "")
    return re.sub(r"\s+", " ", s).strip()


def _cmp(s):
    return _norm(s).lower()


_UNITES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
           "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
           "quinze": 15, "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50,
           "soixante": 60}


def _nombre_mots(txt):
    """Convertit un nombre écrit en chiffres ou en lettres (« cent vingt », « quatre-vingt-dix ») en entier."""
    t = _cmp(txt)
    if re.fullmatch(r"\d+", t):
        return int(t)
    toks = [p for p in re.split(r"[- ]", t) if p and p != "et"]
    total, i = 0, 0
    while i < len(toks):
        tok = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if tok == "cent":
            total += 100
        elif tok == "quatre" and nxt in ("vingt", "vingts"):
            total += 80
            i += 1
        elif tok in _UNITES:
            total += _UNITES[tok]
        else:
            return None
        i += 1
    return total or None


def _fait(valeurs_pages, unique=False):
    """valeurs_pages : liste ordonnée de (valeur, [pages]). Fusionne les doublons."""
    fusion = []
    for val, pages in valeurs_pages:
        for entree in fusion:
            if entree["valeur"] == val:
                entree["pages"] = sorted(set(entree["pages"]) | set(pages))
                break
        else:
            fusion.append({"valeur": val, "pages": sorted(set(pages))})
    if not fusion:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    conflit = bool(unique) and len(fusion) > 1
    return {"statut": TROUVE, "valeurs": fusion, "conflit": conflit}


def _segments(texte):
    """Phrases, coupées aussi avant chaque libellé de date ou d'heure limite."""
    texte = _norm(texte)
    brut = re.split(r"(?<=[.;!?])\s+", texte)
    out = []
    for phrase in brut:
        morceaux = re.split(r"(?=\b(?:date(?: et heure)? limites?|heure limite|date d'envoi)\b)",
                            phrase, flags=re.IGNORECASE)
        out.extend(m for m in morceaux if m.strip())
    return out


def _lignes(texte):
    return [_norm(l) for l in texte.split("\n") if _norm(l)]


DATE_RE = re.compile(
    r"(?P<j>\d{1,2})(?:er)?\s*(?:[/.\-]\s*(?P<m>\d{1,2})\s*[/.\-]\s*(?P<a>\d{2,4})"
    r"|\s+(?P<mois>[A-Za-zéûèàôîÉÛ]+)\s+(?P<a2>\d{4}))"
    r"|(?:(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+)?(?:le\s+)?"
    r"(?P<j2>\d{1,2}|1er)\s+(?P<mois2>[A-Za-zéûèàôîÉÛ]+)\s+(?P<a3>\d{4})",
    re.IGNORECASE,
)


def _dates(texte):
    """Rend [(jj/mm/aaaa, début, fin)] pour chaque date reconnue dans le texte."""
    res = []
    for m in re.finditer(
            r"(?<!\d)(\d{1,2})(?:er)?\s*(?:/|\.|-)\s*(\d{1,2})\s*(?:/|\.|-)\s*(\d{2}|\d{4})(?!\d)"
            r"|(?<![\w])(?:(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+)?(?:le\s+)?"
            r"(\d{1,2}|1er)\s+([A-Za-zéûèàôîÉÛ]+)\s+(\d{4})(?!\d)",
            texte, flags=re.IGNORECASE):
        if m.group(1) is not None:
            j, mo, a = int(m.group(1)), int(m.group(2)), m.group(3)
        else:
            jour = m.group(4)
            j = 1 if jour.lower() == "1er" else int(jour)
            nom = _cmp(m.group(5))
            if nom not in MOIS:
                continue
            mo, a = MOIS[nom], m.group(6)
        a = int(a)
        if a < 100:
            a += 2000
        if not (1 <= mo <= 12 and 1 <= j <= 31):
            continue
        res.append((f"{j:02d}/{mo:02d}/{a:04d}", m.start(), m.end()))
    return res


def _heure_apres(texte):
    """Heure écrite au début de texte (16h00, 16 h 00, 16 heures, midi, seize heures trente)."""
    m = re.match(r"\s*(?:,\s*)?(?:à|a)?\s*(\d{1,2})\s*(?:h|H|:)\s*(\d{2})?(?![\d])", texte)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h < 24 and mi < 60:
            return f"{h:02d}:{mi:02d}"
    m = re.match(r"\s*(?:,\s*)?(?:à|a)?\s*(\d{1,2})\s+heures?(?:\s+(\d{2}))?", texte, re.IGNORECASE)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h < 24 and mi < 60:
            return f"{h:02d}:{mi:02d}"
    m = re.match(r"\s*(?:,\s*)?(?:à|a)?\s*midi\b", texte, re.IGNORECASE)
    if m:
        return "12:00"
    return None


HEURES_MOTS = {"midi": 12, "onze": 11, "dix": 10, "neuf": 9, "huit": 8, "sept": 7, "six": 6,
               "cinq": 5, "quatre": 4, "trois": 3, "deux": 2, "une": 1, "une heure": 1,
               "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "dix-sept": 17,
               "dix-huit": 18, "dix-neuf": 19, "vingt": 20, "vingt-et-une": 21,
               "vingt-deux": 22, "vingt-trois": 23, "douze": 12}


def _heure_lettres_apres(texte):
    """« dix-sept heures », « seize heures trente » au début de texte."""
    m = re.match(r"\s*(?:,\s*)?(?:à|a)?\s*([a-zéè\-]+)\s+heures?(?:\s+(trente|quinze|quarante-cinq))?\b",
                 texte, re.IGNORECASE)
    if not m:
        return None
    h = HEURES_MOTS.get(_cmp(m.group(1)))
    if h is None:
        return None
    mi = {"trente": 30, "quinze": 15, "quarante-cinq": 45}.get(_cmp(m.group(2) or ""), 0)
    return f"{h:02d}:{mi:02d}"


def _heure_adjacente(texte):
    return _heure_apres(texte) or _heure_lettres_apres(texte)


def _heure_keyword(segment):
    """Heure écrite après le libellé « heure limite » dans le segment."""
    m = re.search(r"heure limite[^:]*?:?\s*(.*)$", segment, re.IGNORECASE)
    if not m:
        return None
    reste = m.group(1)
    h = _heure_apres(" " + reste) or _heure_lettres_apres(" " + reste)
    if h:
        return h
    m2 = re.search(r"(\d{1,2})\s*(?:h|H|:)\s*(\d{2})?", reste)
    if m2 and int(m2.group(1)) < 24:
        return f"{int(m2.group(1)):02d}:{int(m2.group(2) or 0):02d}"
    m3 = re.search(r"(\d{1,2})\s+h\s*(\d{2})", reste)
    if m3:
        return f"{int(m3.group(1)):02d}:{int(m3.group(2)):02d}"
    return None


def _trouver_dates_limites(pages):
    """[(valeur, page, heure ou None)] pour la date limite de remise des offres."""
    res = []
    for n, texte in enumerate(pages, 1):
        for seg in _segments(texte):
            bas = seg.lower()
            if "question" in bas or "renseignement" in bas:
                continue
            if not re.search(r"offre|pli|remise|réception|reception|limite", bas):
                continue
            if re.search(r"date d'envoi|visite", bas):
                continue
            for valeur, debut, fin in _dates(seg):
                heure = _heure_adjacente(seg[fin:])
                res.append((valeur, n, heure))
    return res


def _trouver_heures_limites(pages):
    """[(heure, page)] : heure écrite après le libellé « heure limite », hors questions."""
    res = []
    for n, texte in enumerate(pages, 1):
        for seg in _segments(texte):
            bas = seg.lower()
            if "heure limite" not in bas or "question" in bas or "renseignement" in bas:
                continue
            h = _heure_keyword(seg)
            if h:
                res.append((h, n))
    return res


def _trouver_dates_questions(pages):
    """[(valeur, page)] : date limite d'envoi des questions."""
    res = []
    for n, texte in enumerate(pages, 1):
        for seg in _segments(texte):
            bas = seg.lower()
            if "question" not in bas and "renseignement" not in bas:
                continue
            for valeur, _, _ in _dates(seg):
                res.append((valeur, n))
    return res


DELAI_QUESTIONS_RE = re.compile(
    r"(?:\d+|" + NOMBRE_RE + r")(?:\s*\(\d+\))?\s+jours\s+avant\s+la\s+date\s+limite\s+de\s+remise\s+des\s+offres",
    re.IGNORECASE)


def _trouver_delais_questions(pages):
    res = []
    for n, texte in enumerate(pages, 1):
        for m in DELAI_QUESTIONS_RE.finditer(_norm(texte)):
            if re.search(r"question|renseignement", _norm(texte)[max(0, m.start() - 200):m.start()], re.IGNORECASE):
                res.append((_norm(m.group(0)), n))
    return res


PROC_RE = [
    (re.compile(r"\bMAPA\b"), "procédure adaptée"),
    (re.compile(r"procédure adaptée", re.IGNORECASE), "procédure adaptée"),
    (re.compile(r"appel d'offres ouvert", re.IGNORECASE), "appel d'offres ouvert"),
    (re.compile(r"appel d'offres restreint", re.IGNORECASE), "appel d'offres restreint"),
    (re.compile(r"dialogue compétitif", re.IGNORECASE), "dialogue compétitif"),
]


def _trouver_procedures(pages):
    res = []
    for n, texte in enumerate(pages, 1):
        t = _norm(texte)
        for rx, valeur in PROC_RE:
            if rx.search(t):
                res.append((valeur, n))
    return res


def _trouver_visite(pages):
    """[(oui|non, page)] selon le caractère de la visite du site."""
    res = []
    for n, texte in enumerate(pages, 1):
        for ligne in _lignes(texte):
            bas = ligne.lower()
            if not re.search(r"visite", bas) or re.search(r"pièce|piece", bas):
                continue
            if re.search(r"non obligatoire|facultative|pas obligatoire|n'est pas obligatoire|"
                         r"non\s+obligatoire|conseill", bas):
                res.append(("non", n))
            elif re.search(r"obligatoire", bas):
                res.append(("oui", n))
    return res


def _trouver_dates_visite(pages):
    res = []
    for n, texte in enumerate(pages, 1):
        for ligne in _lignes(texte):
            if "visite" not in ligne.lower():
                continue
            for valeur, _, _ in _dates(ligne):
                res.append((valeur, n))
    return res


def _trouver_variantes(pages):
    res = []
    for n, texte in enumerate(pages, 1):
        for seg in _segments(texte):
            bas = seg.lower()
            if "variante" not in bas:
                continue
            if re.search(r"ne sont pas (?:autoris|admis)|interdi|aucune variante n'est admise|"
                         r"non autoris|ne sont pas admises|pas autoris", bas):
                res.append(("non autorisées", n))
            elif re.search(r"autoris|admis", bas):
                res.append(("autorisées", n))
    return res


def _trouver_validites(pages):
    res = []
    rx = re.compile(r"(?:validit[ée]|valables?|valable)[^.;]*?(\d+|" + NOMBRE_RE + r")(?:\s*\(\d+\))?\s+(jours|mois)"
                    r"|(?:valables?)\s+(\d+|" + NOMBRE_RE + r")(?:\s*\(\d+\))?\s+(jours|mois)",
                    re.IGNORECASE)
    for n, texte in enumerate(pages, 1):
        for seg in _segments(texte):
            if re.search(r"ne sont pas|délai d'exécution|exécution", seg, re.IGNORECASE):
                if not re.search(r"valid", seg, re.IGNORECASE):
                    continue
            for m in rx.finditer(seg):
                nb = m.group(1) or m.group(3)
                unite = m.group(2) or m.group(4)
                if nb is None or unite is None:
                    continue
                if re.search(r"valid|valable", m.group(0), re.IGNORECASE):
                    val = _nombre_mots(nb)
                    if val:
                        res.append(({"nombre": val, "unite": "jours" if unite.lower() == "jours" else "mois"}, n))
    return res


def _trouver_modes(pages):
    res = []
    for n, texte in enumerate(pages, 1):
        for seg in _segments(texte):
            bas = seg.lower()
            if re.search(r"papier", bas) and re.search(r"non autoris|aucune offre papier|n'est pas autoris|ne sera acceptée", bas):
                res.append(("électronique", n))
                continue
            if re.search(r"papier|pli cacheté|récépissé", bas) and "électronique" not in bas:
                res.append(("papier", n))
            elif re.search(r"électronique|électronique|dématérialis", bas):
                res.append(("électronique", n))
    return res


PUCE_RE = re.compile(r"^\s*(?:[-•*·]|o)\s+(.+)$")
LOT_RE = re.compile(r"\blot\s*(?:n\s*°\s*|n°\s*|n\.?\s*|°\s*)?(\d{1,2})\s*[:\-–—]\s*(.+)$", re.IGNORECASE)


def _cle_piece(nom):
    """Identité d'une pièce : libellé sans parenthèses, sans ponctuation finale."""
    s = re.sub(r"\([^)]*\)", " ", nom)
    s = _cmp(s).rstrip(" ;.,:")
    return _norm(s)


def _phase_titre(ligne):
    bas = ligne.lower()
    if "attributaire" in bas:
        return "attributaire"
    if "candidature" in bas:
        return "candidature"
    if re.search(r"\boffre", bas):
        return "offre"
    return None


def _trouver_pieces(pages):
    """[(nom, cle, phase ou None, obligation ou None, page)] dans l'ordre du RC."""
    res = []
    phase = None
    for n, texte in enumerate(pages, 1):
        for ligne in _lignes(texte):
            m = PUCE_RE.match(ligne)
            if not m:
                if re.search(r"pièce|piece|produira|fournir|remettre|documents", ligne, re.IGNORECASE):
                    phase = _phase_titre(ligne) or phase
                continue
            item = m.group(1).strip()
            cle = _cle_piece(item)
            if not cle:
                continue
            bas = item.lower()
            if "non obligatoire" in bas or "facultati" in bas:
                ob = "non obligatoire"
            elif "obligatoire" in bas:
                ob = "obligatoire"
            else:
                ob = None
            nom = _norm(item).rstrip(" ;.,:")
            res.append((nom, cle, phase, ob, n))
    return res


def _trouver_lots(pages):
    """(numéros [(numero, intitule, page)], unique [page]) ; numero None pour un marché à lot unique."""
    res, unique = [], []
    for n, texte in enumerate(pages, 1):
        for ligne in _lignes(texte):
            for seg in re.split(r"(?<=[.])\s+(?=[A-ZÉÈ])", ligne):
                bas = seg.lower()
                if re.search(r"lot unique|n'est pas alloti|pas alloti|marché n'est pas|non alloti|"
                             r"(?:pas|sans) (?:prévu )?(?:de )?décomposition en lots", bas):
                    unique.append(n)
                    continue
                m = LOT_RE.search(seg)
                if m:
                    titre = _norm(m.group(2)).rstrip(" ;.,")
                    res.append((int(m.group(1)), titre, n))
    return res, unique


CTX_RE = re.compile(r"crit[èe]re|jugement|notation|notées|classés|classement|pondér|points", re.IGNORECASE)
TOP_RE = re.compile(r"^(?:Critère\s*n°\s*(\d+)\s*:\s*|(\d+)[.)]\s+|[-•*]\s+)(.*)$", re.IGNORECASE)
SUB_RE = re.compile(r"^(?:(\d+)\.(\d+)\s+|([a-z])\)\s+|[-•*]\s+)(.*)$", re.IGNORECASE)
LOTH_RE = re.compile(r"^lot\s*(?:n\s*°\s*|n°\s*)?(\d+)\s*:?\s*$", re.IGNORECASE)
POND_RE = re.compile(
    r"[:(]?\s*(?:(?P<n>\d+(?:[,.]\d+)?)|(?P<w>" + NOMBRE_RE + r"))\s*"
    r"(?:(?P<pc>%)|(?P<pt>points?|pts)|(?P<pw>pour\s+cent))",
    re.IGNORECASE)


def _valeur_pond(m):
    """(valeur, unité) d'un match POND_RE."""
    if m.group("n"):
        brut = m.group("n").replace(",", ".")
        v = float(brut)
        v = int(v) if v.is_integer() else v
    else:
        v = _nombre_mots(m.group("w"))
    unite = "pourcentage" if (m.group("pc") or m.group("pw")) else "points"
    return v, unite


def _libelle_et_pond(texte):
    """Sépare « Libellé : 60 % » en (libellé, valeur, unité) ; valeur None si absente."""
    m = POND_RE.search(texte)
    if m and m.group("w") is not None and _nombre_mots(m.group("w")) is None:
        m = None
    if m:
        valeur, unite = _valeur_pond(m)
        label = texte[:m.start()]
    else:
        valeur, unite, label = None, None, texte
    label = re.split(r",\s*appr", label)[0]
    label = re.split(r"\s*\(", label)[0]
    label = _norm(label).rstrip(" :(-–").strip()
    return label, valeur, unite


def _analyser_criteres(pages):
    """Rend (criteres_bruts, classement_vu, pages_classement, lots_entetes)."""
    crits = {}
    ordre = []
    cur = None
    cur_lot = None
    ctx = False
    classement_vu = []
    lots_entetes = set()
    for n, texte in enumerate(pages, 1):
        for brut in texte.replace("\r", "").split("\n"):
            ligne = _norm(brut)
            if not ligne:
                continue
            indente = brut[:1] in (" ", "\t", " ")
            if CTX_RE.search(ligne) and re.search(r"classés|ordre décroissant|classement", ligne, re.IGNORECASE):
                classement_vu.append(n)
            mlot = LOTH_RE.match(ligne)
            if mlot:
                cur_lot = int(mlot.group(1))
                lots_entetes.add(cur_lot)
                continue
            if re.match(r"(ARTICLE|Article|ANNEXE)", ligne):
                ctx = bool(CTX_RE.search(ligne))
            elif CTX_RE.search(ligne):
                ctx = True
            sub = SUB_RE.match(ligne) if (indente or re.match(r"^\d+\.\d+\s", ligne)) else None
            if sub and cur is not None:
                label, valeur, unite = _libelle_et_pond(sub.group(4))
                if not label:
                    continue
                c = crits[cur]
                cle = _cmp(label)
                s = c["subs"].setdefault(cle, {"libelle": label, "pages": [], "pond": []})
                s["pages"].append(n)
                if valeur is not None:
                    s["pond"].append((valeur, unite, cur_lot, n))
                continue
            top = TOP_RE.match(ligne)
            if not top:
                continue
            label, valeur, unite = _libelle_et_pond(top.group(3))
            if not label or (valeur is None and not ctx):
                continue
            cle = _cmp(label)
            if cle not in crits:
                crits[cle] = {"libelle": label, "pages": [], "pond": [], "subs": {},
                              "lots": [], "rang": top.group(1) or top.group(2),
                              "ordre": len(ordre)}
                ordre.append(cle)
            cur = cle
            c = crits[cle]
            c["pages"].append(n)
            c["lots"].append(cur_lot)
            if valeur is not None:
                c["pond"].append((valeur, unite, cur_lot, n))
    return [crits[k] for k in ordre], classement_vu, lots_entetes


def _fait_p(entrees):
    """Pondération : entrées (valeur, unité, lot, page). Conflit si deux valeurs pour un même lot."""
    groupes = []
    for valeur, unite, lot, page in entrees:
        for g in groupes:
            if g["valeur"] == valeur and g["unite"] == unite and g["lot"] == lot:
                g["pages"] = sorted(set(g["pages"]) | {page})
                break
        else:
            groupes.append({"valeur": valeur, "unite": unite, "lot": lot, "pages": [page]})
    if not groupes:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    conflit = False
    for g in groupes:
        if sum(1 for h in groupes if h["lot"] == g["lot"]) > 1:
            conflit = True
    return {"statut": TROUVE, "valeurs": groupes, "conflit": conflit}


def _est_technique(libelle):
    c = _cmp(libelle)
    return "technique" in c or "qualité" in c


def _construire_criteres(pages, lots_liste):
    """Liste des critères au format du dossier, type de pondération, pages du type."""
    brut, classement_pages, lots_entetes = _analyser_criteres(pages)
    pond_entrees = [p for c in brut for p in c["pond"]] + [p for c in brut for s in c["subs"].values() for p in s["pond"]]
    if any(p[1] == "pourcentage" for p in pond_entrees):
        type_val = "pourcentage"
    elif any(p[1] == "points" for p in pond_entrees):
        type_val = "points"
    elif classement_pages and brut:
        type_val = "classement"
    else:
        type_val = None
    return brut, type_val, classement_pages, lots_entetes


def _trouver_limite_pages(pages):
    res = []
    rx = re.compile(r"(\d+|" + NOMBRE_RE + r")(?:\s*\(\d+\))?\s+pages?", re.IGNORECASE)
    for n, texte in enumerate(pages, 1):
        for seg in _segments(texte):
            if "mémoire technique" not in seg.lower():
                continue
            if re.search(r"\bpage \d+ sur", seg, re.IGNORECASE):
                continue
            if re.search(r"comporte|règlement|lettre de motivation", seg, re.IGNORECASE):
                continue
            for m in rx.finditer(seg):
                val = _nombre_mots(m.group(1))
                if val:
                    res.append((val, n))
    return res


# ------------------------------------------------------------------ assemblage

def _jsonable(v):
    return v


def _faits_extraits(pages):
    """Valeurs trouvées dans le texte des pages : {clé: [(valeur, [pages])]} pour les faits simples."""
    dates = _trouver_dates_limites(pages)
    heures = [(h, n) for _, n, h in dates if h] + _trouver_heures_limites(pages)
    questions = _trouver_dates_questions(pages) + _trouver_delais_questions(pages)
    return {
        "date_limite": [(v, [n]) for v, n, _ in dates],
        "heure_limite": [(h, [n]) for h, n in heures],
        "date_questions": [(v, [n]) for v, n in questions],
        "procedure": [(v, [n]) for v, n in _trouver_procedures(pages)],
        "visite_obligatoire": [(v, [n]) for v, n in _trouver_visite(pages)],
        "dates_visite": [(v, [n]) for v, n in _trouver_dates_visite(pages)],
        "variantes": [(v, [n]) for v, n in _trouver_variantes(pages)],
        "validite_offres": [(v, [n]) for v, n in _trouver_validites(pages)],
        "mode_remise": [(v, [n]) for v, n in _trouver_modes(pages)],
        "limite_pages": [(v, [n]) for v, n in _trouver_limite_pages(pages)],
    }


UNIQUES = {"date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
           "variantes", "validite_offres", "mode_remise", "limite_pages"}


def _lots(pages):
    entrees, unique_pages = _trouver_lots(pages)
    if unique_pages and not entrees:
        return {"statut": TROUVE, "liste": [{"numero": None, "intitules": [], "pages": sorted(set(unique_pages)),
                                             "conflit": False}]}
    if not entrees:
        return {"statut": NON_TROUVE, "liste": []}
    liste = []
    for numero, titre, n in entrees:
        lot = next((x for x in liste if x["numero"] == numero), None)
        if lot is None:
            lot = {"numero": numero, "intitules": [], "pages": [], "conflit": False}
            liste.append(lot)
        lot["pages"] = sorted(set(lot["pages"]) | {n})
        it = next((i for i in lot["intitules"] if _cmp(i["valeur"]) == _cmp(titre)), None)
        if it is None:
            lot["intitules"].append({"valeur": titre, "pages": [n]})
        else:
            it["pages"] = sorted(set(it["pages"]) | {n})
    liste.sort(key=lambda x: x["numero"])
    for lot in liste:
        lot["conflit"] = len(lot["intitules"]) > 1
    return {"statut": TROUVE, "liste": liste}


def _pieces(pages):
    brut = _trouver_pieces(pages)
    if not brut:
        return {"statut": NON_TROUVE, "liste": []}
    liste = []
    for nom, cle, phase, ob, n in brut:
        p = next((x for x in liste if x["_cle"] == cle), None)
        if p is None:
            p = {"_cle": cle, "nom": nom, "pages": [], "_phases": [], "_obs": []}
            liste.append(p)
        p["pages"] = sorted(set(p["pages"]) | {n})
        if phase:
            p["_phases"].append((phase, [n]))
        if ob:
            p["_obs"].append((ob, [n]))
    sortie = []
    for p in liste:
        sortie.append({"nom": p["nom"], "pages": p["pages"],
                       "phase": _fait([(v, pg) for v, pg in p["_phases"]]),
                       "obligation": _fait([(v, pg) for v, pg in p["_obs"]], unique=True)})
    return {"statut": TROUVE, "liste": sortie}


def _ponderation_fait(entrees):
    return _fait_p(entrees)


def _criteres(pages, lots_liste):
    brut, type_val, classement_pages, lots_entetes = _construire_criteres(pages, lots_liste)
    tous = sorted(lots_entetes)
    liste = []
    for i, c in enumerate(brut):
        entrees = list(c["pond"])
        if type_val == "classement":
            rang = int(c["rang"]) if c["rang"] else c["ordre"] + 1
            entrees = [(rang, "rang", None, n) for n in c["pages"][:1]]
        if tous:
            lots_c = sorted({x for x in c["lots"] if x is not None})
            lot_val = ["tous les lots"] if set(lots_c) == set(tous) or not lots_c else lots_c
            lot_fait = _fait([(v if v == "tous les lots" else v, [c["pages"][0]]) for v in
                              (lot_val if lot_val != ["tous les lots"] else ["tous les lots"])])
        elif len(lots_liste) == 1:
            lot_fait = _fait([(lots_liste[0]["numero"], [c["pages"][0]])])
        else:
            lot_fait = _fait([("tous les lots", [c["pages"][0]])])
        subs = []
        for s in c["subs"].values():
            subs.append({"libelle": s["libelle"], "pages": sorted(set(s["pages"])),
                         "ponderation": _fait_p([(v, u, l, pg) for v, u, l, pg in s["pond"]])})
        liste.append({"libelle": c["libelle"], "pages": sorted(set(c["pages"])),
                      "lot": lot_fait,
                      "ponderation": _fait_p([(v, u, l, pg) for v, u, l, pg in entrees]),
                      "sous_criteres": subs})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}, type_val


def _plan(criteres_liste):
    plan = []
    for c in criteres_liste:
        if not _est_technique(c["libelle"]):
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                pond = s["ponderation"]["valeurs"]
                plan.append({"titre": f"{c['libelle']} – {s['libelle']}", "critere": c["libelle"],
                             "sous_critere": s["libelle"],
                             "ponderation": pond[0]["valeur"] if pond else None,
                             "page_source": s["pages"][0], "contenu": ""})
        else:
            pond = c["ponderation"]["valeurs"]
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": pond[0]["valeur"] if pond else None,
                         "page_source": c["pages"][0], "contenu": ""})
    return plan


def _controle(dossier):
    alertes = []
    criteres_liste = dossier["criteres"]["liste"]
    plan = dossier["plan"]
    type_val = dossier["type_ponderation"]["valeurs"][0]["valeur"] if dossier["type_ponderation"]["valeurs"] else None
    for c in criteres_liste:
        if _est_technique(c["libelle"]) and not any(s["critere"] == c["libelle"] for s in plan):
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    if type_val == "pourcentage":
        totaux = {}
        for c in criteres_liste:
            for v in c["ponderation"]["valeurs"]:
                totaux[v["lot"]] = totaux.get(v["lot"], 0) + v["valeur"]
        for lot, total in totaux.items():
            if abs(total - 100) > 0.01:
                alertes.append({"type": "total différent de 100 %", "objet": "total" if lot is None else f"lot {lot}"})
    if type_val != "classement":
        for c in criteres_liste:
            pond = c["ponderation"]["valeurs"]
            subs = [s["ponderation"]["valeurs"][0]["valeur"] for s in c["sous_criteres"]
                    if s["ponderation"]["valeurs"]]
            if pond and subs and abs(sum(subs) - pond[0]["valeur"]) > 0.01:
                alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    return alertes


def _type_fait(type_val, pages_type):
    if type_val is None:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    return _fait([(type_val, pages_type)], unique=True)


def _assembler(pages, extrait_filtre=None):
    faits = _faits_extraits(pages)
    dossier = {}
    for cle in faits:
        dossier[cle] = _fait(faits[cle], unique=cle in UNIQUES)
    dossier["lots"] = _lots(pages)
    dossier["pieces"] = _pieces(pages)
    dossier["criteres"], type_val = _criteres(pages, dossier["lots"]["liste"])
    dossier["type_ponderation"] = _type_fait(type_val, sorted({n for c in dossier["criteres"]["liste"]
                                                                 for n in c["pages"]} or [])) \
        if type_val else {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    dossier["plan"] = _plan(dossier["criteres"]["liste"])
    dossier["controle"] = {"alertes": _controle(dossier)}
    return dossier


def analyser(pages):
    pages = [p if isinstance(p, str) else "" for p in pages]
    return _assembler(pages)


def controler(dossier):
    return _controle(dossier)


FAITS_SIMPLES = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                 "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages"]


def _filtrer_fait_p(fait, ref):
    """Garde les pondérations proposées retrouvées par l'extraction (même valeur, unité et lot)."""
    retrouvees = {(json.dumps(v["valeur"]), v["unite"], v["lot"]): set(v["pages"]) for v in ref["valeurs"]}
    entrees = []
    for v in fait["valeurs"]:
        cle = (json.dumps(v["valeur"]), v["unite"], v["lot"])
        if cle in retrouvees:
            pg = sorted(set(v["pages"]) & retrouvees[cle]) or sorted(retrouvees[cle])
            entrees.extend((v["valeur"], v["unite"], v["lot"], p) for p in pg)
    return _fait_p(entrees)


def verifier(dossier, pages):
    """Retire toute valeur proposée qui ne se retrouve pas dans le texte des pages, puis recalcule plan et contrôle."""
    pages = [p if isinstance(p, str) else "" for p in pages]
    trouve = _assembler(pages)
    r = copy.deepcopy(dossier)
    for cle in FAITS_SIMPLES:
        ref = {json.dumps(v["valeur"], sort_keys=True): set(v["pages"]) for v in trouve[cle]["valeurs"]}
        garde = []
        for v in r[cle]["valeurs"]:
            cle_v = json.dumps(v["valeur"], sort_keys=True)
            if cle_v in ref:
                pg = sorted(set(v["pages"]) & ref[cle_v]) or sorted(ref[cle_v])
                garde.append({"valeur": v["valeur"], "pages": pg})
        r[cle] = _fait([(v["valeur"], v["pages"]) for v in garde], unique=cle in UNIQUES)
    # lots
    ref_lots = {x["numero"]: {_cmp(i["valeur"]) for i in x["intitules"]} for x in trouve["lots"]["liste"]}
    lots_garde = []
    for lot in r["lots"]["liste"]:
        if lot["numero"] not in ref_lots:
            continue
        ints = [i for i in lot["intitules"] if _cmp(i["valeur"]) in ref_lots[lot["numero"]]]
        lot = dict(lot, intitules=ints, conflit=len(ints) > 1)
        lots_garde.append(lot)
    r["lots"] = {"statut": TROUVE if lots_garde else NON_TROUVE, "liste": lots_garde}
    # pièces
    ref_pieces = {x["nom"] for x in trouve["pieces"]["liste"]}
    refs_cle = {_cle_piece(x["nom"]) for x in trouve["pieces"]["liste"]}
    pieces_garde = [p for p in r["pieces"]["liste"] if _cle_piece(p["nom"]) in refs_cle]
    r["pieces"] = {"statut": TROUVE if pieces_garde else NON_TROUVE, "liste": pieces_garde}
    # critères
    refs = {_cmp(x["libelle"]): x for x in trouve["criteres"]["liste"]}
    crit_garde = []
    for c in r["criteres"]["liste"]:
        ref = refs.get(_cmp(c["libelle"]))
        if ref is None:
            continue
        c["ponderation"] = _filtrer_fait_p(c["ponderation"], ref["ponderation"])
        ref_subs = {_cmp(s["libelle"]): s for s in ref["sous_criteres"]}
        subs = []
        for s in c["sous_criteres"]:
            rs = ref_subs.get(_cmp(s["libelle"]))
            if rs is None:
                continue
            s["ponderation"] = _filtrer_fait_p(s["ponderation"], rs["ponderation"])
            subs.append(s)
        c["sous_criteres"] = subs
        crit_garde.append(c)
    r["criteres"] = {"statut": TROUVE if crit_garde else NON_TROUVE, "liste": crit_garde}
    r["plan"] = _plan(crit_garde)
    r["controle"] = {"alertes": _controle(r)}
    return r
