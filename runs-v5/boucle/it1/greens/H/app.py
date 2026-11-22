"""Lecture déterministe d'un règlement de consultation (RC).

Point d'entrée : analyser(pages) -> dict sérialisable.
verifier(dossier, pages) -> dict ; controler(dossier) -> list[dict].
"""

import copy
import json
import re

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

MOIS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}

UNITES_NOMBRES = {
    "zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "dix-sept": 17,
    "dix-huit": 18, "dix-neuf": 19, "vingt": 20, "trente": 30, "quarante": 40,
    "cinquante": 50, "soixante": 60, "soixante-dix": 70, "quatre-vingt": 80,
    "quatre-vingts": 80, "quatre-vingt-dix": 90, "cent": 100,
}

# Nombres composés en lettres : « cent quatre-vingts », « soixante-quinze », etc.
_MOTS_NOMBRE = (
    "quatre-vingt-dix|quatre-vingts|quatre-vingt|soixante-dix|soixante-onze|soixante-quinze"
    "|soixante-et-un|soixante|quarante|cinquante|trente|vingt|dix-neuf|dix-huit|dix-sept"
    "|seize|quinze|quatorze|treize|douze|onze|dix|neuf|huit|sept|six|cinq|quatre|trois"
    "|deux|une|un|cent"
)
_NOMBRE_LETTRES_RE = re.compile(
    r"(?:cent|(?:" + _MOTS_NOMBRE + r"))(?:[\s\-]+(?:et[\s\-]+)?(?:" + _MOTS_NOMBRE + r"))*",
    re.IGNORECASE,
)


def nombre_en_lettres(texte):
    """Valeur entière d'un nombre écrit en lettres (français), ou None."""
    t = texte.lower().replace("-", " ").strip()
    t = re.sub(r"\s+", " ", t).replace("vingts", "vingt")
    if not t:
        return None
    mots = t.split(" ")
    total = 0
    courant = 0
    table = {
        "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
        "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
        "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "dix-sept": 17,
        "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
        "cent": 100, "et": 0,
    }
    # gestion simple : « quatre vingt dix », « soixante quinze », « cent vingt »
    i = 0
    valeur = 0
    while i < len(mots):
        m = mots[i]
        if m == "et":
            i += 1
            continue
        if m == "quatre" and i + 1 < len(mots) and mots[i + 1] == "vingt":
            courant += 80
            i += 2
            if i < len(mots) and mots[i] == "dix":
                courant += 10
                i += 1
            continue
        if m == "soixante" and i + 1 < len(mots) and mots[i + 1] in ("dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", "sept", "huit", "neuf"):
            base = {"dix": 70, "onze": 71, "douze": 72, "treize": 73, "quatorze": 74,
                    "quinze": 75, "seize": 76, "sept": 77, "huit": 78, "neuf": 79}
            courant += base[mots[i + 1]]
            i += 2
            continue
        if m == "vingts":
            m = "vingt"
        if m not in table:
            return None
        v = table[m]
        if v == 100:
            courant = (courant or 1) * 100
        else:
            courant += v
        i += 1
    total += courant + valeur
    return total


def nombre_en_chiffres_ou_lettres(texte):
    """Valeur entière d'un nombre en chiffres ou en lettres ; None sinon."""
    t = texte.strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    return nombre_en_lettres(t)


# ----------------------------------------------------------------- texte


def normaliser_page(texte):
    """Texte d'une page : apostrophes et espaces unifiés, fins de ligne LF, espaces repliés."""
    t = texte.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("’", "'")
    t = re.sub(r"[    ]", " ", t).replace(" ", " ").replace(" ", " ")
    t = t.replace("­", "")
    return t


def norm(s):
    s = normaliser_page(s).replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def lignes(page):
    return [re.sub(r"[ \t]+", " ", l).strip() for l in normaliser_page(page).split("\n")]


def mois_numero(texte):
    t = texte.lower()
    return MOIS.get(t) or MOIS.get(t.replace("é", "e").replace("û", "u"))


# ----------------------------------------------------------------- dates


_RE_DATE_CHIFFRES = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b")
_RE_DATE_LETTRES = re.compile(
    r"\b(\d{1,2}|1er)\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[ée]cembre)\s+(\d{4})\b",
    re.IGNORECASE,
)


def dates_dans(texte):
    """Liste (position, date « jj/mm/aaaa ») des dates reconnues dans un texte."""
    trouvees = []
    for m in _RE_DATE_LETTRES.finditer(texte):
        j = 1 if m.group(1).lower() == "1er" else int(m.group(1))
        mo = mois_numero(m.group(2))
        if mo is None:
            continue
        trouvees.append((m.start(), f"{j:02d}/{mo:02d}/{int(m.group(3)):04d}"))
    for m in _RE_DATE_CHIFFRES.finditer(texte):
        j, mo, a = int(m.group(1)), int(m.group(2)), m.group(3)
        if len(a) == 2:
            a = "20" + a
        if not (1 <= j <= 31 and 1 <= mo <= 12):
            continue
        trouvees.append((m.start(), f"{j:02d}/{mo:02d}/{int(a):04d}"))
    trouvees.sort()
    return trouvees


# ----------------------------------------------------------------- heures


_RE_HEURE_CHIFFRES = re.compile(
    r"\b(\d{1,2})\s?(?:h|H|:)\s?(\d{2})?\b(?!\s*(?:jours|mois|pages|%))"
)
_RE_HEURE_LETTRES = re.compile(
    r"\b((?:" + _MOTS_NOMBRE + r")(?:\s(?:" + _MOTS_NOMBRE + r"))*)\s+heures?"
    r"(?:\s+(trente|quinze|quarante-cinq|quarante\s+cinq))?\b",
    re.IGNORECASE,
)


def heures_dans(texte):
    """Liste (position, « hh:mm ») des heures reconnues dans un texte."""
    trouvees = []
    for m in re.finditer(r"\b(\d{1,2})(?:\s*[hH]\s*(\d{2})?(?![\d])|:(\d{2})\b|\s+heures?\b)", texte):
        h = int(m.group(1))
        brut = m.group(2) or m.group(3)
        mi = int(brut) if brut else 0
        if h > 23 or mi > 59:
            continue
        # « 12 h 00 » et « 12h00 » : on n'accepte pas un nombre suivi d'une unité d'usage
        fin = texte[m.end():m.end() + 12].lower()
        if re.match(r"\s*(jours?|mois|pages?|%|pour|points?|pts)", fin):
            continue
        trouvees.append((m.start(), f"{h:02d}:{mi:02d}"))
    for m in re.finditer(r"\bmidi\b", texte, re.IGNORECASE):
        trouvees.append((m.start(), "12:00"))
    for m in _RE_HEURE_LETTRES.finditer(texte):
        h = nombre_en_lettres(m.group(1))
        if h is None or h > 23:
            continue
        mi = 0
        if m.group(2):
            mi = 30 if "trente" in m.group(2).lower() else (15 if "quinze" in m.group(2).lower() else 45)
        trouvees.append((m.start(), f"{h:02d}:{mi:02d}"))
    trouvees.sort()
    return trouvees


# ----------------------------------------------------------------- lignes


def lignes_page(page):
    """Lignes non vides d'une page, normalisées."""
    return [l for l in lignes(page) if l]


def lignes_indentees(page):
    """Lignes non vides d'une page, indentation conservée (un sous-critère est indenté)."""
    sortie = []
    for l in normaliser_page(page).split("\n"):
        l = re.sub(r"(?<=\S)[ \t]+", " ", l.expandtabs(4)).rstrip()
        if l.strip():
            sortie.append(l)
    return sortie


def textes_logiques(page):
    """Lignes, avec la ligne suivante accolée quand une phrase coupée n'a ni date ni heure."""
    ls = lignes_page(page)
    sortie = []
    for i, t in enumerate(ls):
        if (i + 1 < len(ls) and not dates_dans(t) and not heures_dans(t)
                and not re.search(r"[.;:!?]$", t)):
            sortie.append(t + " " + ls[i + 1])
        sortie.append(t)
    return sortie


# ----------------------------------------------------------------- lots


_RE_LOT = re.compile(
    r"^[\s\-•*]*lots?\s*(?:n\s*°|n°|n\s*o\b|no\b|°)?\s*(\d{1,2})\b\s*[:\-–—]?\s*(.*)$",
    re.IGNORECASE,
)
_RE_LOT_UNIQUE = re.compile(
    r"lot unique|n'est pas alloti|non alloti|pas alloti|pas (?:pr[ée]vu )?de d[ée]composition en lots",
    re.IGNORECASE,
)


def extraire_lots(page):
    """Liste de (numéro, intitulé, texte_trouvé) pour une page."""
    sortie = []
    for t in lignes_page(page):
        m = _RE_LOT.match(t)
        if m:
            titre = re.sub(r"[\s;.,]+$", "", m.group(2)).strip()
            if titre:
                sortie.append((int(m.group(1)), titre, titre))
            continue
        u = _RE_LOT_UNIQUE.search(t)
        if u:
            sortie.append((1, u.group(0), u.group(0)))
    return sortie


# ----------------------------------------------------------------- dates et heures limites


_EXCL_LIMITE = re.compile(r"question|visite|publication|envoi du pr[ée]sent|renseignement|r[ée]ponse|notification", re.I)
_CUE_LIMITE = re.compile(r"remise|r[ée]ception|parvenir|parviennent|d[ée]pos|plis|offres|jusqu'au|limite", re.I)


def extraire_date_limite(page):
    sortie = []
    for t in textes_logiques(page):
        if _EXCL_LIMITE.search(t) or not _CUE_LIMITE.search(t):
            continue
        for _, d in dates_dans(t):
            sortie.append(d)
    return sortie


def extraire_heure_limite(page):
    sortie = []
    for t in textes_logiques(page):
        if re.search(r"visite|question|accueil|ouvert|renseignement", t, re.I):
            continue
        if not re.search(r"limite|remise|r[ée]ception|parvenir|plis|offres", t, re.I):
            continue
        for _, h in heures_dans(t):
            sortie.append(h)
    return sortie


def extraire_date_questions(page):
    """Dates ou délais écrits pour l'envoi des questions (texte recopié tel quel)."""
    sortie = []
    for t in textes_logiques(page):
        if not re.search(r"question|renseignement", t, re.I):
            continue
        for _, d in dates_dans(t):
            sortie.append(d)
        m = re.search(
            r"((?:\d+|[a-zéèàûô\-]+)(?:\s*\(\d+\))?\s+jours?\s+(?:francs\s+)?avant\s+la\s+date\s+limite[^.;\n]*)",
            t, re.I)
        if m:
            sortie.append(m.group(1).strip())
    return sortie


# ----------------------------------------------------------------- procédure


_PROCEDURES = [
    (r"\bmapa\b", "procédure adaptée"),
    (r"proc[ée]dure adapt[ée]e", "procédure adaptée"),
    (r"appel d'offres ouvert", "appel d'offres ouvert"),
    (r"appel d'offres restreint", "appel d'offres restreint"),
    (r"dialogue comp[ée]titif", "dialogue compétitif"),
]


def extraire_procedure(page):
    sortie = []
    for t in lignes_page(page):
        n = norm(t)
        for motif, valeur in _PROCEDURES:
            if re.search(motif, n) and valeur not in sortie:
                sortie.append(valeur)
    return sortie


# ----------------------------------------------------------------- visite


def extraire_visite_obligatoire(page):
    sortie = []
    for t in lignes_page(page):
        n = norm(t)
        if "visite" not in n:
            continue
        if re.search(r"non obligatoire|pas obligatoire|facultati|conseill", n):
            valeur = "non"
        elif "obligatoire" in n:
            valeur = "oui"
        else:
            continue
        sortie.append(valeur)
    return sortie


def extraire_dates_visite(page):
    sortie = []
    for t in lignes_page(page):
        n = norm(t)
        if "visite" not in n or re.search(r"question|limite|offres|plis", n):
            continue
        for _, d in dates_dans(t):
            sortie.append(d)
    return sortie


# ----------------------------------------------------------------- variantes


def extraire_variantes(page):
    sortie = []
    for t in lignes_page(page):
        n = norm(t)
        if "variante" not in n:
            continue
        if re.search(r"non autoris|pas autoris|pas admis|interdi|aucune variante|non admis", n):
            valeur = "non autorisées"
        elif re.search(r"autoris|admis|peuvent pr[ée]senter", n):
            valeur = "autorisées"
        else:
            continue
        sortie.append(valeur)
    return sortie


# ----------------------------------------------------------------- validité des offres


_RE_DUREE = re.compile(
    r"(?:(\d+)\s*(?:\(\d+\))?|\((\d+)\)|([a-zéèêàûôîç\- ]+?))\s*(?:\((\d+)\))?\s*(jours?|mois)\b",
    re.IGNORECASE,
)


def extraire_validite(page):
    sortie = []
    for t in lignes_page(page):
        n = norm(t)
        if not (("offre" in n) and ("validit" in n or "valabl" in n)):
            continue
        for m in _RE_DUREE.finditer(t):
            if m.group(1):
                nb = int(m.group(1))
            elif m.group(4):
                nb = int(m.group(4))
            elif m.group(2):
                nb = int(m.group(2))
            else:
                mots = m.group(3).strip().split()
                nb = None
                for k in range(min(6, len(mots)), 0, -1):
                    nb = nombre_en_lettres(" ".join(mots[-k:]))
                    if nb is not None:
                        break
                if nb is None:
                    continue
            unite = "jours" if m.group(5).lower().startswith("jour") else "mois"
            v = {"nombre": nb, "unite": unite}
            if v not in sortie:
                sortie.append(v)
    return sortie


# ----------------------------------------------------------------- mode de remise


_NEGATION = re.compile(r"\bne\b|\bn'|pas\b|aucune?\b|interdi|non\b", re.IGNORECASE)


def extraire_mode_remise(page):
    sortie = []
    for t in textes_logiques(page):
        for phrase in re.split(r"[.;:]\s", t):
            n = norm(phrase)
            if re.search(r"[ée]lectronique|d[ée]mat[ée]rialis|profil d'acheteur|plateforme", n):
                if "électronique" not in sortie:
                    sortie.append("électronique")
            if re.search(r"papier|sous pli cachet|contre r[ée]c[ée]piss|remis en main propre", n):
                if _NEGATION.search(n):
                    continue
                if "papier" not in sortie:
                    sortie.append("papier")
    return sortie


# ----------------------------------------------------------------- limite de pages


def _nombre_avant_pages(avant):
    """Nombre écrit juste avant le mot « pages » : chiffres, « (20) » ou lettres ; None sinon."""
    avant = avant.rstrip()
    m = re.search(r"\((\d+)\)$", avant) or re.search(r"(\d+)$", avant)
    if m:
        return int(m.group(1))
    mots = re.findall(r"[a-zéèêûôîç\-]+", avant)[-6:]
    for k in range(len(mots), 0, -1):
        nb = nombre_en_lettres(" ".join(mots[-k:]))
        if nb:
            return nb
    return None


def extraire_limite_pages(page):
    sortie = []
    for t in lignes_page(page):
        n = norm(t)
        if "mémoire" not in n:
            continue
        for m in re.finditer(r"\bpages?\b", n):
            nb = _nombre_avant_pages(n[:m.start()])
            if nb is not None and nb not in sortie:
                sortie.append(nb)
    return sortie


# ----------------------------------------------------------------- type de pondération


_RE_CLASSEMENT_DOC = re.compile(r"class[ée]s? par ordre|ordre d[ée]croissant|par ordre d'importance")


def types_pondération_page(page, classement_doc):
    ls = lignes_page(page)
    if any(re.search(r"%|pour ?cent", norm(l)) for l in ls):
        return ["pourcentage"]
    if any(re.search(r"\d+\s*(?:points?|pts)\b", norm(l)) for l in ls):
        return ["points"]
    if classement_doc and any(re.match(r"^\s*\d+\.\s+[^\d%]+$", l) for l in ls):
        return ["classement"]
    return []


# ----------------------------------------------------------------- pièces


_RE_PUCE = re.compile(r"^\s*(?:[-•*–]|\d+[.)]|[a-z][.)])\s+(.+)$")
_RE_QUALIF = re.compile(
    r"\s*(?:,\s*)?(?:à titre\s+)?\(?\s*(?:obligatoire|facultatif|facultative)\s*\)?\s*$",
    re.IGNORECASE,
)


def _entete_piece(n):
    return (re.search(r"pi[eè]ce|document|fournir|produir|remettr|au titre|partie|rubrique", n)
            and re.search(r"candidature|offre|attributaire", n)
            and not re.search(r"crit[èe]re|jugement|avantageuse", n))


def _phase_entete(n):
    if "attributaire" in n:
        return "attributaire"
    if "candidature" in n:
        return "candidature"
    return "offre"


def scanner_pieces(page, phase):
    """Retourne (occurrences, phase_courante) ; la phase se propage d'une page à l'autre."""
    occ = []
    for t in lignes_page(page):
        n = norm(t)
        m = _RE_PUCE.match(t)
        if _entete_piece(n):
            phase = _phase_entete(n)
        elif m:
            if re.search(r"%|\bpoints?\b|\bpts\b|pour cent", n) or _RE_LOT.match(t):
                continue
            brut = re.sub(r"[\s;.,]+$", "", m.group(1)).strip()
            nom = _RE_QUALIF.sub("", brut).strip()
            nom = re.sub(r"[\s;.,]+$", "", nom).strip()
            if not nom:
                continue
            cle = norm(nom)
            occ.append(("piece", cle, nom))
            if phase:
                occ.append(("piece_phase", cle, phase))
            if re.search(r"non obligatoire|facultati", n):
                occ.append(("piece_obl", cle, "non obligatoire"))
            elif "obligatoire" in n:
                occ.append(("piece_obl", cle, "obligatoire"))
    return occ, phase


# ----------------------------------------------------------------- critères


_RE_CTX_CRIT = re.compile(r"crit[èe]re|pond[ée]ration|jugement")
_RE_ARTICLE = re.compile(r"^\s*article\b", re.IGNORECASE)
_RE_TOP_NUM = re.compile(r"^(\d+)[.)]\s+(.*)$")
_RE_TOP_CRIT_N = re.compile(r"^crit[èe]re\s*n\s*°?\s*(\d+)\s*[:.)\-–]\s*(.*)$", re.IGNORECASE)
_RE_DOTTED = re.compile(r"^(\d+\.\d+)\s+(.*)$")
_RE_LETTRE = re.compile(r"^([a-z])\)\s+(.*)$", re.IGNORECASE)
_RE_PUCE_CRIT = re.compile(r"^[-•*–]\s+(.*)$")
_RE_POIDS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|pour\s*cent|points?|pts)(?!\w)", re.IGNORECASE)
_RE_POIDS_LETTRES = re.compile(r"((?:[a-zéèêûôîç\-]+\s+)*?[a-zéèêûôîç\-]+)\s+pour\s+cent", re.IGNORECASE)


def _nombre(s):
    f = float(s.replace(",", "."))
    return int(f) if f == int(f) else f


def _analyser_ligne_critere(t, indent_min_sub=2):
    """Retourne dict {niveau, rang, libelle, valeur, unite} ou None."""
    s = t.strip()
    indent = len(t) - len(t.lstrip())
    niveau = None
    rang = None
    rest = None
    m = _RE_DOTTED.match(s)
    if m:
        niveau, rest = "sub", m.group(2)
    if rest is None:
        m = _RE_TOP_CRIT_N.match(s)
        if m:
            niveau, rang, rest = "top", int(m.group(1)), m.group(2)
    if rest is None:
        m = _RE_TOP_NUM.match(s)
        if m:
            niveau, rang, rest = "top", int(m.group(1)), m.group(2)
    if rest is None:
        m = _RE_LETTRE.match(s)
        if m:
            niveau, rest = "sub", m.group(2)
    if rest is None:
        m = _RE_PUCE_CRIT.match(s)
        if m:
            niveau = "sub" if indent >= indent_min_sub else "top"
            rest = m.group(1)
    if rest is None:
        return None
    valeur = unite = None
    w = _RE_POIDS.search(rest)
    if w:
        valeur = _nombre(w.group(1))
        unite = "points" if w.group(2).lower().startswith(("point", "pts")) else "pourcentage"
        debut = w.start()
    else:
        w2 = _RE_POIDS_LETTRES.search(rest)
        if w2:
            mots = w2.group(1).split()
            for k in range(min(6, len(mots)), 0, -1):
                nb = nombre_en_lettres(" ".join(mots[-k:]))
                if nb is not None:
                    valeur, unite = nb, "pourcentage"
                    break
        debut = w2.start() if (w2 and valeur is not None) else len(rest)
        if valeur is None:
            debut = len(rest)
    libelle = rest[:debut]
    while True:
        nouveau = re.sub(r"\s*(?:\(|:|–|-|\||pond[ée]ration|\s)\s*$", "", libelle, flags=re.IGNORECASE)
        if nouveau == libelle:
            break
        libelle = nouveau
    libelle = libelle.strip(" ;.,")
    if not libelle:
        return None
    return {"niveau": niveau, "rang": rang, "libelle": libelle, "valeur": valeur, "unite": unite}


def scanner_criteres(pages, rang_mode):
    occ = []
    bloc = False
    parent = None
    scope = None
    for p, page in enumerate(pages, 1):
        for t in lignes_indentees(page):
            n = norm(t)
            if _RE_ARTICLE.match(t):
                bloc = False
                scope = None
            if _RE_CTX_CRIT.search(n):
                bloc = True
            lot = _RE_LOT.match(t)
            if lot:
                scope = int(lot.group(1))
                continue
            a = _analyser_ligne_critere(t)
            if a is None:
                continue
            if a["niveau"] == "top":
                if a["valeur"] is None and not bloc:
                    continue
                cle = norm(a["libelle"])
                parent = a["libelle"]
                occ.append((p, "crit", cle, a["libelle"]))
                occ.append((p, "crit_scope", cle, scope))
                if a["valeur"] is not None:
                    occ.append((p, "crit_pond", cle, {"valeur": a["valeur"], "unite": a["unite"], "lot": scope}))
                elif rang_mode and a["rang"] is not None:
                    occ.append((p, "crit_pond", cle, {"valeur": a["rang"], "unite": "rang", "lot": None}))
            else:
                if parent is None:
                    continue
                if a["valeur"] is None and not bloc:
                    continue
                cle = norm(parent) + "|" + norm(a["libelle"])
                occ.append((p, "sub", cle, {"parent": parent, "libelle": a["libelle"]}))
                if a["valeur"] is not None:
                    occ.append((p, "sub_pond", cle, {"valeur": a["valeur"], "unite": a["unite"], "lot": scope}))
    return occ


# ----------------------------------------------------------------- pilote


def _occurrences(pages):
    """Toutes les occurrences (page, fait, clé, valeur) relevées dans les pages."""
    occ = []
    types_doc = set()
    classement_doc = any(_RE_CLASSEMENT_DOC.search(norm(pg)) for pg in pages)
    for p, page in enumerate(pages, 1):
        for cle, fonction in [
            ("date_limite", extraire_date_limite),
            ("heure_limite", extraire_heure_limite),
            ("date_questions", extraire_date_questions),
            ("procedure", extraire_procedure),
            ("visite_obligatoire", extraire_visite_obligatoire),
            ("dates_visite", extraire_dates_visite),
            ("variantes", extraire_variantes),
            ("validite_offres", extraire_validite),
            ("mode_remise", extraire_mode_remise),
            ("limite_pages", extraire_limite_pages),
        ]:
            for v in fonction(page):
                occ.append((p, cle, "", v))
        for v in types_pondération_page(page, classement_doc):
            types_doc.add(v)
            occ.append((p, "type_ponderation", "", v))
        for numero, titre, _ in extraire_lots(page):
            occ.append((p, "lot", str(numero), titre))
    rang_mode = "classement" in types_doc and not ({"pourcentage", "points"} & types_doc)
    phase = None
    for p, page in enumerate(pages, 1):
        ocp, phase = scanner_pieces(page, phase)
        for kind, cle, v in ocp:
            occ.append((p, kind, cle, v))
    for p, kind, cle, v in scanner_criteres(pages, rang_mode):
        occ.append((p, kind, cle, v))
    return occ


def _cle_occ(o):
    return json.dumps(list(o), sort_keys=True, ensure_ascii=False)


# ----------------------------------------------------------------- construction du dossier

FAITS_SIMPLES = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                 "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
                 "type_ponderation"]


def _fait(pv, conflit_possible=True):
    """pv : liste de (page, valeur). Rend un Fait."""
    groupes = {}
    for p, v in pv:
        k = json.dumps(v, sort_keys=True, ensure_ascii=False)
        groupes.setdefault(k, [v, set()])[1].add(p)
    if not groupes:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    ordre = sorted(groupes.values(), key=lambda g: (min(g[1]), json.dumps(g[0], sort_keys=True, ensure_ascii=False)))
    valeurs = [{"valeur": v, "pages": sorted(ps)} for v, ps in ordre]
    return {"statut": TROUVE, "valeurs": valeurs,
            "conflit": bool(conflit_possible and len(valeurs) > 1)}


def _fait_ponderation(pv):
    """pv : liste de (page, {valeur, unite, lot}). Rend un FaitP."""
    groupes = {}
    for p, v in pv:
        k = json.dumps(v, sort_keys=True, ensure_ascii=False)
        groupes.setdefault(k, [v, set()])[1].add(p)
    ordre = sorted(groupes.values(), key=lambda g: (min(g[1]), json.dumps(g[0], sort_keys=True, ensure_ascii=False)))
    valeurs = [{"valeur": v["valeur"], "unite": v["unite"], "lot": v["lot"], "pages": sorted(ps)}
               for v, ps in ordre]
    if not valeurs:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    conflit = False
    for lot_ in {x["lot"] for x in valeurs}:
        if len({x["valeur"] for x in valeurs if x["lot"] == lot_}) > 1:
            conflit = True
    return {"statut": TROUVE, "valeurs": valeurs, "conflit": conflit}


def _premiere(f):
    return f["valeurs"][0]["valeur"] if f.get("valeurs") else None


def _est_technique(libelle):
    n = norm(libelle)
    return "technique" in n and "prix" not in n


def _construire(occ):
    d = {}
    for nom in FAITS_SIMPLES:
        d[nom] = _fait([(p, v) for (p, f, c, v) in occ if f == nom],
                       conflit_possible=(nom != "dates_visite"))

    # lots
    numeros = sorted({int(c) for (p, f, c, v) in occ if f == "lot"})
    liste_lots = []
    for n in numeros:
        pages = set()
        intit = {}
        for (p, f, c, v) in occ:
            if f == "lot" and c == str(n):
                pages.add(p)
                intit.setdefault(norm(v), [v, set()])[1].add(p)
        ints = [{"valeur": v, "pages": sorted(ps)} for v, ps in intit.values()]
        liste_lots.append({"numero": n, "intitules": ints, "pages": sorted(pages),
                           "conflit": len(ints) > 1})
    d["lots"] = {"statut": TROUVE if liste_lots else NON_TROUVE, "liste": liste_lots}

    # pièces
    cles_pieces = []
    for (p, f, c, v) in occ:
        if f == "piece" and c not in cles_pieces:
            cles_pieces.append(c)
    liste_pieces = []
    for c in cles_pieces:
        nom = next(v for (p, f, cc, v) in occ if f == "piece" and cc == c)
        pages = sorted({p for (p, f, cc, v) in occ if f == "piece" and cc == c})
        phase = _fait([(p, v) for (p, f, cc, v) in occ if f == "piece_phase" and cc == c])
        oblig = _fait([(p, v) for (p, f, cc, v) in occ if f == "piece_obl" and cc == c])
        liste_pieces.append({"nom": nom, "pages": pages, "phase": phase, "obligation": oblig})
    d["pieces"] = {"statut": TROUVE if liste_pieces else NON_TROUVE, "liste": liste_pieces}

    # critères
    lots_doc = numeros
    cles_crit = []
    for (p, f, c, v) in occ:
        if f == "crit" and c not in cles_crit:
            cles_crit.append(c)
    liste_crit = []
    for c in cles_crit:
        libelle = next(v for (p, f, cc, v) in occ if f == "crit" and cc == c)
        pages = sorted({p for (p, f, cc, v) in occ if f == "crit" and cc == c})
        scopes = {v for (p, f, cc, v) in occ if f == "crit_scope" and cc == c and v is not None}
        if len(lots_doc) == 1:
            val_lot = lots_doc[0]
        elif len(scopes) == 1:
            val_lot = next(iter(scopes))
        else:
            val_lot = "tous les lots"
        lot_fait = {"statut": TROUVE, "valeurs": [{"valeur": val_lot, "pages": pages}], "conflit": False}
        ponderation = _fait_ponderation([(p, v) for (p, f, cc, v) in occ if f == "crit_pond" and cc == c])
        subs = []
        cles_sub = []
        for (p, f, cc, v) in occ:
            if f == "sub" and cc.split("|", 1)[0] == c and cc not in cles_sub:
                cles_sub.append(cc)
        for cs in cles_sub:
            sv = next(v for (p, f, cc, v) in occ if f == "sub" and cc == cs)
            spages = sorted({p for (p, f, cc, v) in occ if f == "sub" and cc == cs})
            subs.append({"libelle": sv["libelle"], "pages": spages,
                         "ponderation": _fait_ponderation(
                             [(p, v) for (p, f, cc, v) in occ if f == "sub_pond" and cc == cs])})
        liste_crit.append({"libelle": libelle, "pages": pages, "lot": lot_fait,
                           "ponderation": ponderation, "sous_criteres": subs})
    d["criteres"] = {"statut": TROUVE if liste_crit else NON_TROUVE, "liste": liste_crit}

    d["plan"] = _plan(liste_crit)
    d["controle"] = {"alertes": _alertes(d)}
    return d


def _plan(criteres):
    plan = []
    for c in criteres:
        if not _est_technique(c["libelle"]):
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                plan.append({"titre": f"{c['libelle']} – {s['libelle']}", "critere": c["libelle"],
                             "sous_critere": s["libelle"], "ponderation": _premiere(s["ponderation"]),
                             "page_source": min(s["pages"]), "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": _premiere(c["ponderation"]), "page_source": min(c["pages"]),
                         "contenu": ""})
    return plan


def _alertes(d):
    alertes = []
    plan = d.get("plan", [])
    liste = d["criteres"]["liste"]
    for c in liste:
        if _est_technique(c["libelle"]) and not any(s["critere"] == c["libelle"] for s in plan):
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in liste:
        if not c["sous_criteres"]:
            continue
        parent = _premiere(c["ponderation"])
        if parent is None:
            continue
        svals = [_premiere(s["ponderation"]) for s in c["sous_criteres"] if s["ponderation"]["valeurs"]]
        if svals and abs(sum(svals) - parent) > 1e-6:
            alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    if _premiere(d["type_ponderation"]) == "pourcentage":
        par_lot = {}
        for c in liste:
            for v in c["ponderation"]["valeurs"]:
                if v["unite"] == "pourcentage":
                    par_lot[v["lot"]] = par_lot.get(v["lot"], 0) + v["valeur"]
        if any(abs(t - 100) > 1e-6 for t in par_lot.values()):
            alertes.append({"type": "total différent de 100 %", "objet": "critères"})
    return alertes


# ----------------------------------------------------------------- points d'entrée


def analyser(pages):
    return _construire(_occurrences(list(pages)))


def controler(dossier):
    return _alertes(dossier)


def _occurrences_du_dossier(d):
    out = []
    for nom in FAITS_SIMPLES:
        for e in d[nom]["valeurs"]:
            for p in e["pages"]:
                out.append((p, nom, "", e["valeur"]))
    for L in d["lots"]["liste"]:
        for i in L["intitules"]:
            for p in i["pages"]:
                out.append((p, "lot", str(L["numero"]), i["valeur"]))
    for P in d["pieces"]["liste"]:
        c = norm(P["nom"])
        for p in P["pages"]:
            out.append((p, "piece", c, P["nom"]))
        for e in P["phase"]["valeurs"]:
            for p in e["pages"]:
                out.append((p, "piece_phase", c, e["valeur"]))
        for e in P["obligation"]["valeurs"]:
            for p in e["pages"]:
                out.append((p, "piece_obl", c, e["valeur"]))
    for C in d["criteres"]["liste"]:
        c = norm(C["libelle"])
        for p in C["pages"]:
            out.append((p, "crit", c, C["libelle"]))
        for e in C["ponderation"]["valeurs"]:
            for p in e["pages"]:
                out.append((p, "crit_pond", c, {"valeur": e["valeur"], "unite": e["unite"], "lot": e["lot"]}))
        for S in C["sous_criteres"]:
            sc = c + "|" + norm(S["libelle"])
            for p in S["pages"]:
                out.append((p, "sub", sc, {"parent": C["libelle"], "libelle": S["libelle"]}))
            for e in S["ponderation"]["valeurs"]:
                for p in e["pages"]:
                    out.append((p, "sub_pond", sc, {"valeur": e["valeur"], "unite": e["unite"], "lot": e["lot"]}))
    return out


def verifier(dossier, pages):
    pages = list(pages)
    frais = _occurrences(pages)
    pool = {_cle_occ(o) for o in frais}
    garde = {_cle_occ(o) for o in _occurrences_du_dossier(dossier) if _cle_occ(o) in pool}
    noms_gardes = {c for (p, f, c, v) in frais if f == "crit" and _cle_occ((p, f, c, v)) in garde}
    final = [o for o in frais
             if _cle_occ(o) in garde or (o[1] == "crit_scope" and o[2] in noms_gardes)]
    return _construire(final)

