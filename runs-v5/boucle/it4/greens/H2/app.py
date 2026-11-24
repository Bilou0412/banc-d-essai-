"""Lecture déterministe d'un règlement de consultation (RC).

Expressions régulières et règles écrites ; bibliothèque standard uniquement.
Point d'entrée : analyser(pages) -> dossier sérialisable en JSON.
"""
import json
import re
import unicodedata

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
NB = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
      "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13,
      "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30,
      "quarante": 40, "cinquante": 50, "soixante": 60, "midi": 12}


# ----------------------------------------------------------------- texte

def _texte(page):
    """Texte d'une page : fins de ligne normalisées, espaces insécables et apostrophes unifiés."""
    s = page.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").replace(" ", " ")
    return s.replace("’", "'")


def _pliec(c):
    base = "".join(x for x in unicodedata.normalize("NFD", c) if unicodedata.category(x) != "Mn")
    return base.lower() if len(base) == 1 else c


def _plie(s):
    """Version repliée (minuscules, sans accents), de même longueur que s."""
    return "".join(_pliec(c) for c in s)


def _lignes_pages(pages):
    """Pour chaque page (numéro à partir de 1) : liste (original, replié) des lignes non vides."""
    out = []
    for n, page in enumerate(pages, 1):
        lignes = []
        for ligne in _texte(page).split("\n"):
            if ligne.strip():
                texte_ligne = ligne.rstrip()
                lignes.append((texte_ligne, _plie(texte_ligne)))
        out.append((n, lignes))
    return out


def _entier(mots):
    """Entier écrit en lettres (« quatre-vingt-dix »), ou None."""
    cur, ok = 0, False
    for t in re.split(r"[\s\-]+", mots.strip()):
        if not t or t == "et":
            continue
        if t in ("cent", "cents"):
            cur = (cur or 1) * 100 if cur < 10 else cur + 100
        elif t in ("vingt", "vingts") and ok and cur % 100 in range(2, 10):
            cur = cur - cur % 100 + (cur % 100) * 20
        elif t in NB:
            cur += NB[t]
        else:
            return None
        ok = True
    return cur if ok else None


def _nombre(s):
    """Nombre décimal écrit à la française (47,5) -> 47.5 ; entier si possible."""
    x = float(s.replace(",", "."))
    return int(x) if x == int(x) else x


# ----------------------------------------------------------------- dates et heures

RE_DATE_L = re.compile(r"\b(\d{1,2}|1er|premier)\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
                       r"septembre|octobre|novembre|decembre)\s+(\d{4})\b")
RE_DATE_N = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b")
RE_HEURE_N = re.compile(r"\b(\d{1,2})(?:\s*h\s*(\d{2})?|:(\d{2}))\b|\b(\d{1,2})\s+heures?(?:\s+(\d{2}))?\b")
RE_HEURE_MOT = re.compile(r"((?:[a-z\-]+\s+){0,2}[a-z\-]+)\s+heures?(?:\s+([a-z\-]+))?\b")


def _date_valide(j, m, a):
    if 1 <= m <= 12 and 1 <= j <= 31 and 2000 <= a <= 2099:
        return f"{j:02d}/{m:02d}/{a:04d}"
    return None


def _dates(f):
    """Dates jj/mm/aaaa d'un texte replié, dans l'ordre d'apparition."""
    trouvees = []
    for m in RE_DATE_L.finditer(f):
        j = 1 if m.group(1) in ("1er", "premier") else int(m.group(1))
        d = _date_valide(j, MOIS[m.group(2)], int(m.group(3)))
        if d:
            trouvees.append((m.start(), d))
    for m in RE_DATE_N.finditer(f):
        a = int(m.group(3))
        a = a + 2000 if a < 100 else a
        d = _date_valide(int(m.group(1)), int(m.group(2)), a)
        if d:
            trouvees.append((m.start(), d))
    return [d for _, d in sorted(trouvees)]


def _heures(f):
    """Heures hh:mm d'un texte replié (chiffres, lettres, « midi »), dans l'ordre d'apparition."""
    trouvees = []
    for m in RE_HEURE_N.finditer(f):
        if m.group(1):
            h, mi = int(m.group(1)), int(m.group(2) or m.group(3) or 0)
        elif m.group(4):
            h, mi = int(m.group(4)), int(m.group(5) or 0)
        else:
            continue
        if h < 24 and mi < 60:
            trouvees.append((m.start(), f"{h:02d}:{mi:02d}"))
    for m in re.finditer(r"\bmidi\b", f):
        trouvees.append((m.start(), "12:00"))
    for m in RE_HEURE_MOT.finditer(f):
        mots = m.group(1).split()
        h = None
        for debut in range(len(mots)):
            v = _entier(" ".join(mots[debut:]))
            if v is not None and v <= 23:
                h = v
                break
        if h is None:
            continue
        mi = _entier(m.group(2)) if m.group(2) else None
        if mi is None or mi >= 60:
            mi = 0
        trouvees.append((m.start(), f"{h:02d}:{mi:02d}"))
    return [v for _, v in sorted(trouvees)]


# ----------------------------------------------------------------- faits

def _fait(paires, conflit_si_plusieurs=True):
    """Fait à partir de couples (valeur, page). Une valeur n'apparaît qu'une fois, pages triées."""
    acc = {}
    for valeur, page in paires:
        cle = json.dumps(valeur, sort_keys=True, ensure_ascii=False)
        acc.setdefault(cle, {"valeur": valeur, "pages": set()})["pages"].add(page)
    if not acc:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    valeurs = [{"valeur": e["valeur"], "pages": sorted(e["pages"])} for e in acc.values()]
    return {"statut": TROUVE, "valeurs": valeurs,
            "conflit": bool(conflit_si_plusieurs and len(valeurs) > 1)}


def _fait_poids(paires):
    """Pondération : valeurs (valeur, unité, lot, page). Conflit seulement si deux valeurs diffèrent pour un même lot."""
    acc = {}
    for valeur, unite, lot, page in paires:
        cle = json.dumps([valeur, unite, lot], sort_keys=True)
        acc.setdefault(cle, {"valeur": valeur, "unite": unite, "lot": lot, "pages": set()})["pages"].add(page)
    if not acc:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    valeurs = [{"valeur": e["valeur"], "unite": e["unite"], "lot": e["lot"], "pages": sorted(e["pages"])}
               for e in acc.values()]
    par_lot = {}
    for v in valeurs:
        par_lot.setdefault(v["lot"], set()).add(v["valeur"])
    conflit = any(len(x) > 1 for x in par_lot.values())
    return {"statut": TROUVE, "valeurs": valeurs, "conflit": conflit}


# ----------------------------------------------------------------- date limite, heure limite, questions

EXCL_REMISE = ("question", "renseignement", "visite", "rendez-vous", "modification", "recours",
               "validite", "negociation", "avis")
ACCROCHE_LIMITE = ("limite", "au plus tard", "parvenir", "jusqu'au")


def _est_remise(f):
    return (any(x in f for x in ("offre", "pli", "remise", "candidature"))
            and any(x in f for x in ACCROCHE_LIMITE)
            and not any(x in f for x in EXCL_REMISE))


def _est_questions(f):
    return (any(x in f for x in ("question", "renseignement", "demande"))
            and any(x in f for x in ("limite", "au plus tard", "parvenir", "jusqu'au", "envoi")))


def _valeurs_ligne(plis, i, extraire, pred):
    """Valeurs de la ligne i ; à défaut, de la ligne suivante si elle ne contredit pas le prédicat."""
    v = extraire(plis[i])
    if not v and i + 1 < len(plis) and pred(plis[i + 1]) and not _est_remise(plis[i + 1]) \
            and not any(x in plis[i + 1] for x in ("question", "visite", "renseignement")):
        v = extraire(plis[i + 1])
    return v


def _sur_remise(pages, extraire):
    out = []
    for n, lignes in _lignes_pages(pages):
        plis = [f for _, f in lignes]
        for i, f in enumerate(plis):
            if _est_remise(f):
                out += [(v, n) for v in _valeurs_ligne(plis, i, extraire, lambda g: True)]
            elif i + 1 < len(plis) and _est_remise(f + " " + plis[i + 1]):
                # libellé coupé sur deux lignes (« Date limite de réception des » / « offres : ... »)
                out += [(v, n) for v in extraire(f + " " + plis[i + 1])]
    return out


def _sur_questions(pages, extraire):
    out = []
    for n, lignes in _lignes_pages(pages):
        plis = [f for _, f in lignes]
        for i, f in enumerate(plis):
            if _est_questions(f):
                out += [(v, n) for v in _valeurs_ligne(plis, i, extraire, lambda g: "offre" not in g)]
    return out


def _date_limite(pages):
    return _fait(_sur_remise(pages, _dates))


def _heure_limite(pages):
    return _fait(_sur_remise(pages, _heures))


def _date_questions(pages):
    paires = _sur_questions(pages, _dates)
    for n, page in enumerate(pages, 1):
        f = _plie(_texte(page))
        for m in RE_DELAI_QUESTIONS.finditer(f):
            paires.append((re.sub(r"\s+", " ", _texte(page)[m.start():m.end()]), n))
    return _fait(paires)


RE_DELAI_QUESTIONS = re.compile(
    r"[\w\-]+(?: \(\d+\))?\s+jours\s+avant\s+la\s+date\s+limite\s+de\s+remise\s+des\s+offres")


# ----------------------------------------------------------------- faits simples

PROCEDURES = [
    (r"(?<![\w\-])mapa(?![\w\-])", "procédure adaptée"),
    (r"procedure adaptee", "procédure adaptée"),
    (r"appel d'offres ouvert", "appel d'offres ouvert"),
    (r"appel d'offres restreint", "appel d'offres restreint"),
    (r"dialogue competitif", "dialogue compétitif"),
]


def _procedure(pages):
    paires = []
    for n, lignes in _lignes_pages(pages):
        for _, f in lignes:
            for motif, valeur in PROCEDURES:
                if re.search(motif, f):
                    paires.append((valeur, n))
    return _fait(paires)


RE_NON_OBLIG = re.compile(r"non obligatoire|pas obligatoire|facultati|n'est pas obligatoire")


def _visite_obligatoire(pages):
    paires = []
    for n, lignes in _lignes_pages(pages):
        for _, f in lignes:
            if "visite" not in f:
                continue
            if RE_NON_OBLIG.search(f):
                paires.append(("non", n))
            elif "obligatoire" in f:
                paires.append(("oui", n))
    return _fait(paires)


def _dates_visite(pages):
    paires = []
    for n, lignes in _lignes_pages(pages):
        plis = [f for _, f in lignes]
        for i, f in enumerate(plis):
            prec = plis[i - 1] if i else ""
            if "visite" not in f and not ("visite" in prec and ("elle" in f or _dates(f))):
                continue
            if any(x in f for x in ("offre", "pli", "limite", "question", "remise", "renseignement")):
                continue
            paires += [(d, n) for d in _dates(f)]
    return _fait(paires, conflit_si_plusieurs=False)


NEG_VARIANTE = re.compile(r"aucune|ne sont pas|sont interdit|non autoris|pas autoris|pas admis|"
                          r"n'est admise|n'est pas admise|interdit|ne sont pas admis")


def _variantes(pages):
    paires = []
    for n, lignes in _lignes_pages(pages):
        for _, f in lignes:
            if "variante" not in f:
                continue
            if NEG_VARIANTE.search(f):
                paires.append(("non autorisées", n))
            elif re.search(r"autoris|admis", f):
                paires.append(("autorisées", n))
    return _fait(paires)


MOTS_DUREE = re.compile(r"((?:[a-z\-]+\s+){0,4})([a-z\-]+)\s+(jours?|mois)\b")


def _duree_premiere(f):
    """Première durée (nombre, unité) d'une ligne repliée : chiffres ou lettres."""
    cands = []
    for m in re.finditer(r"(?<![\w(])(\d+)\s*(?:\(\d+\)\s*)?(jours?|mois)\b|\((\d+)\)\s*(jours?|mois)\b", f):
        nombre = int(m.group(1) or m.group(3))
        unite = m.group(2) or m.group(4)
        cands.append((m.start(), nombre, unite))
    for m in MOTS_DUREE.finditer(f):
        mots = (m.group(1) + m.group(2)).split()
        for debut in range(len(mots)):
            v = _entier(" ".join(mots[debut:]))
            if v is not None:
                cands.append((m.start(), v, m.group(3)))
                break
    if not cands:
        return None
    _, nombre, unite = min(cands)
    return {"nombre": nombre, "unite": "jours" if unite.startswith("jour") else "mois"}


def _validite_offres(pages):
    paires = []
    for n, lignes in _lignes_pages(pages):
        for _, f in lignes:
            if not re.search(r"validite des offres|validite de l'offre|offres? (sont |restent )?valables?", f):
                continue
            v = _duree_premiere(f)
            if v:
                paires.append((v, n))
    return _fait(paires)


def _mode_remise(pages):
    paires = []
    for n, lignes in _lignes_pages(pages):
        for _, f in lignes:
            if not any(x in f for x in ("offre", "pli")):
                continue
            if re.search(r"electronique|dematerialis|profil d'acheteur|plateforme|https?://", f):
                paires.append(("électronique", n))
            if "papier" in f and not re.search(
                    r"aucune offre papier|ne sera pas accept|ne seront pas accept|ne seront pas admis|"
                    r"ne sera pas admis|n'est pas autoris|non autoris|pas autoris|ne sera acceptee|"
                    r"refus|pas admis|pas accept|ne sont pas", f):
                paires.append(("papier", n))
    return _fait(paires)


MOTS_DUREE_PAGES = re.compile(r"((?:[a-z\-]+\s+){0,2})([a-z\-]+)\s+pages?\b")


def _limite_pages(pages):
    paires = []
    for n, lignes in _lignes_pages(pages):
        for _, f in lignes:
            if "memoire" not in f:
                continue
            m = re.search(r"(\d+)\s+pages?\b|\((\d+)\)\s*pages?\b", f)
            if m:
                paires.append((int(m.group(1) or m.group(2)), n))
                continue
            m = MOTS_DUREE_PAGES.search(f)
            if m:
                mots = (m.group(1) + m.group(2)).split()
                for debut in range(len(mots)):
                    v = _entier(" ".join(mots[debut:]))
                    if v is not None:
                        paires.append((v, n))
                        break
    return _fait(paires)


# ----------------------------------------------------------------- lots

RE_LOT_LIGNE = re.compile(r"^\s*(?:[-•*]\s*)?lots?\s*(?:n\s*°?\s*|no\s*|numero\s*)?(\d+)\b(.*)$")
RE_LOT_UNIQUE = re.compile(r"lot unique|n'est pas alloti|non alloti|pas alloti|"
                           r"pas prevu de decomposition en lots|pas de decomposition en lots|"
                           r"traite en lot unique|traitee en lot unique|en un lot unique")


def _titre_lot(orig, debut):
    reste = orig[debut:]
    reste = re.sub(r"^\s*[:\-–—]\s*", "", reste)
    return reste.strip(" ;.,")


def _lots(pages):
    donnees = {}
    uniques = []
    for n, lignes in _lignes_pages(pages):
        for orig, f in lignes:
            m = RE_LOT_LIGNE.match(f)
            if m:
                num = int(m.group(1))
                d = donnees.setdefault(num, {"intitules": {}, "pages": set()})
                d["pages"].add(n)
                titre = _titre_lot(orig, m.start(2))
                if titre:
                    d["intitules"].setdefault(titre, set()).add(n)
                continue
            if RE_LOT_UNIQUE.search(f) and not re.match(r"^\s*(?:[-•*]\s*)?pour", f):
                titre = ""
                if ":" in orig:
                    apres = orig.split(":", 1)[1].strip(" ;.,")
                    # après les deux-points, la déclaration « lot unique » n'est pas un intitulé
                    if apres and not RE_LOT_UNIQUE.search(_plie(apres)):
                        titre = apres
                uniques.append((titre, n))
    if not donnees and uniques:
        d = {"intitules": {}, "pages": set()}
        for titre, n in uniques:
            d["pages"].add(n)
            if titre:
                d["intitules"].setdefault(titre, set()).add(n)
        donnees[None] = d
    liste = []
    for num, d in donnees.items():
        intitules = [{"valeur": t, "pages": sorted(p)} for t, p in d["intitules"].items()]
        liste.append({"numero": num, "intitules": intitules, "pages": sorted(d["pages"]),
                      "conflit": len(intitules) > 1})
    if not liste:
        return {"statut": NON_TROUVE, "liste": []}
    return {"statut": TROUVE, "liste": liste}


# ----------------------------------------------------------------- pièces

def _ouvre_pieces(f):
    if any(x in f for x in ("critere", "jugement", "note", "ponder")):
        return False
    if "piece" in f or ("dossier" in f and "remettre" in f):
        return True
    return f.endswith(":") and any(x in f for x in ("suivant", "candidature", "offre", "attribu", "document"))


def _ferme_pieces(f):
    return any(x in f for x in ("article", "critere", "jugement", "bareme", "negociation", "visite",
                                "variante", "procedure", "renseignement", "question", "modalit",
                                "annexe", "lot "))


def _phase_titre(f):
    if any(x in f for x in ("article", "critere", "jugement")):
        return None
    if "attribu" in f and ("piece" in f or "fournir" in f or "produira" in f or f.endswith(":")):
        return "attributaire"
    if "candidature" in f and ("piece" in f or "titre de" in f or f.endswith(":")):
        return "candidature"
    if "offre" in f and ("piece" in f or "titre de" in f or f.endswith(":")):
        return "offre"
    return None


def _nom_piece(texte):
    nom = re.sub(r"\s*\((?:obligatoire|facultatif|facultative)\)", "", texte)
    return nom.strip(" ;.,")


def _pieces(pages):
    ouvert = False
    phase = None
    entrees = {}
    for n, lignes in _lignes_pages(pages):
        for orig, f in lignes:
            m = re.match(r"^\s*[-•*]\s+(.*)$", orig)
            if m:
                if not ouvert:
                    continue
                nom = _nom_piece(m.group(1))
                if not nom:
                    continue
                e = entrees.setdefault(_plie(nom), {"nom": nom, "pages": set(), "phases": {}, "oblig": {}})
                e["pages"].add(n)
                if phase:
                    e["phases"].setdefault(phase, set()).add(n)
                if "facultati" in f:
                    e["oblig"].setdefault("non obligatoire", set()).add(n)
                elif "obligatoire" in f:
                    e["oblig"].setdefault("obligatoire", set()).add(n)
                continue
            if _ouvre_pieces(f):
                ouvert = True
            elif _ferme_pieces(f):
                ouvert = False
            ph = _phase_titre(f)
            if ph:
                phase = ph
    liste = []
    for e in entrees.values():
        phases = [(v, p) for v, ps in e["phases"].items() for p in ps]
        oblig = [(v, p) for v, ps in e["oblig"].items() for p in ps]
        liste.append({"nom": e["nom"], "pages": sorted(e["pages"]),
                      "phase": _fait(phases, conflit_si_plusieurs=False),
                      "obligation": _fait(oblig)})
    if not liste:
        return {"statut": NON_TROUVE, "liste": []}
    return {"statut": TROUVE, "liste": liste}

# ----------------------------------------------------------------- critères

RE_CANDIDAT = re.compile(r"^\s*(?:critere\s*n\s*°?\s*\d+|\d+(?:\.\d+)+\s|\d+\s*[.)]\s|\d+\s+[-–]\s"
                         r"|[a-z][.)]\s|[-•*]\s)|\|")
RE_PREFIXE = re.compile(r"^\s*(?:critere\s*n\s*°?\s*\d+\s*[:\-–—]\s*|\d+\.\d+\s+|\d+\s*[.)]\s+|\d+\s+[-–]\s+"
                        r"|[a-z][.)]\s+|[-•*]\s+)?")
RE_POIDS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|pour cent|points?|pts)")
RE_POIDS_MOT = re.compile(r"((?:[a-z\-]+\s+)?[a-z\-]+)\s+pour cent")
RE_LOTS_TITRE = re.compile(r"^\s*(?:pour (?:le|les) )?lots?\b")
MOTS_OPEN_CRIT = ("critere", "jugement", "classe", "ponder", "notee", "notes ")
MOTS_FERME_CRIT = ("article", "bareme", "annexe", "negociation", "modalit", "visite", "variante",
                   "procedure", "remise", "question", "renseignement", "piece", "attribution")


def _numeros_lots(f):
    """Numéros de lots d'une ligne repliée (« lots 1 à 3 », « n° 1, 02, 3 »)."""
    f = f.split(":")[0]
    nums = []
    for a, b in re.findall(r"(\d+)\s+a\s+(\d+)", f):
        nums += list(range(int(a), int(b) + 1))
    reste = re.sub(r"(\d+)\s+a\s+(\d+)", " ", f)
    nums += [int(x) for x in re.findall(r"\d+", reste)]
    return sorted(set(nums))


def _ouvre_criteres(f):
    if RE_CANDIDAT.match(f) or RE_LOTS_TITRE.match(f):
        return False
    titre = f.strip().startswith(("critere", "article", "annexe")) and len(f) < 90
    return any(x in f for x in MOTS_OPEN_CRIT) and (
        f.endswith(":") or "suivant" in f or "ci-dessous" in f or titre)


def _nature(libelle):
    f = _plie(libelle)
    if "prix" in f or "cout" in f:
        return "prix"
    if any(x in f for x in ("technique", "valeur", "qualite", "merite")):
        return "technique"
    return "autre"


def _connu(f, tops):
    """Ligne numérotée dont le libellé reprend un critère déjà relevé (rappel hors bloc de critères)."""
    corps = f[RE_PREFIXE.match(f).end():]
    return any(corps.startswith(cle) for cle in tops)


def _criteres(pages):
    ctx = False
    lots_courants = []
    classement = False
    tops = {}
    ordre = []
    courant = [None]
    for n, lignes in _lignes_pages(pages):
        for orig, f in lignes:
            ligne_de_lot = False
            if RE_LOTS_TITRE.match(f) and not RE_CANDIDAT.match(f):
                lots_courants = _numeros_lots(f)
                ligne_de_lot = True
                if not _ouvre_criteres(f):
                    continue
            if "classe" in f and (ctx or _ouvre_criteres(f)):
                classement = True
            if not ctx and RE_CANDIDAT.match(f) and _connu(f, tops):
                ctx = True
            if RE_CANDIDAT.match(f) or re.match(r"^\s*critere\s*n", f) or (ctx and "|" in f):
                if not ctx and not re.match(r"^\s*critere\s*n", f):
                    continue
                ctx = True
                _ligne_critere(orig, f, n, lots_courants, tops, ordre, courant)
                continue
            if _ouvre_criteres(f):
                if not ligne_de_lot:
                    lots_courants = []
                ctx = True
                continue
            if ctx and any(x in f for x in MOTS_FERME_CRIT):
                ctx = False
                lots_courants = []
    return classement, tops, ordre


def _nettoie_libelle(libelle):
    """Retire la mention de pondération qui suit le libellé (« (pondération : », « noté sur »)."""
    libelle = libelle.rstrip(" :;,.-–—(").strip()
    fl = _plie(libelle)
    m = re.search(r"\(?\s*ponderation\s*:?\s*$", fl)
    if m:
        libelle = libelle[:m.start()]
        fl = _plie(libelle)
    m = re.search(r"\(?\s*note sur\s*$", fl)
    if m:
        libelle = libelle[:m.start()]
    return libelle.rstrip(" :;,.-–—(").strip()


def _ligne_critere(orig, f, n, lots_courants, tops, ordre, courant):
    if "|" in orig:
        cellules = [c.strip() for c in orig.split("|")]
        if _plie(cellules[0]).startswith("critere") and "ponder" in _plie(" ".join(cellules[1:])):
            return
        m = RE_PREFIXE.match(_plie(cellules[0]))
        libelle = _nettoie_libelle(cellules[0][m.end():])
        partie = " ".join(cellules[1:])
        sub = bool(re.match(r"^\s+[-•*]\s", orig))
    else:
        m = RE_PREFIXE.match(f)
        corps, corps_f = orig[m.end():], f[m.end():]
        sub = bool(re.match(r"^\s*\d+\.\d+\s", orig) or re.match(r"^\s*[a-zA-Z][.)]\s", orig)
                   or re.match(r"^\s+[-•*]\s", orig))
        debut = None
        mp = RE_POIDS.search(corps_f)
        if mp:
            debut = mp.start()
        dm = _debut_poids_mot(corps_f)
        if dm is not None and (debut is None or dm < debut):
            debut = dm
        if debut is not None:
            libelle, partie = _nettoie_libelle(corps[:debut]), corps_f[debut:]
        else:
            libelle, partie = _nettoie_libelle(corps), corps_f
    if not libelle:
        return
    _range_critere(libelle, sub, _poids_de(partie), n, lots_courants, tops, ordre, courant)


def _debut_poids_mot(f):
    """Position du nombre écrit en lettres précédant « pour cent » (« soixante pour cent »), ou None."""
    for m in RE_POIDS_MOT.finditer(f):
        mots = list(re.finditer(r"[a-z\-]+", m.group(1)))
        for k in range(len(mots)):
            if _entier(" ".join(x.group() for x in mots[k:])) is not None:
                return m.start(1) + mots[k].start()
    return None


def _poids_de(texte):
    """Liste (valeur, unité) d'un texte (repliés) : pourcentages, points ou mots suivis de « pour cent »."""
    out = []
    for m in RE_POIDS.finditer(_plie(texte)):
        unite = "pourcentage" if m.group(2) in ("%", "pour cent") else "points"
        out.append((_nombre(m.group(1)), unite))
        break
    if not out:
        mm = RE_POIDS_MOT.search(_plie(texte))
        if mm:
            for debut in range(len(mm.group(1).split())):
                v = _entier(" ".join(mm.group(1).split()[debut:]))
                if v is not None:
                    out.append((v, "pourcentage"))
                    break
    return out


def _range_critere(libelle, sub, poids, n, lots_courants, tops, ordre, courant):
    lots = lots_courants or [None]
    cle = _plie(libelle)
    if not sub:
        t = tops.get(cle)
        if t is None:
            t = {"libelle": libelle, "pages": set(), "poids": [], "subs": {}, "lots": set(), "ordre_subs": []}
            tops[cle] = t
            ordre.append(cle)
        courant[0] = cle
        t["pages"].add(n)
        t["lots"].update(lots_courants)
        for valeur, unite in poids:
            for lot in lots:
                t["poids"].append((valeur, unite, lot, n))
        return
    if courant[0] is None:
        return
    parent = tops[courant[0]]
    sc = _plie(libelle)
    s = parent["subs"].get(sc)
    if s is None:
        s = {"libelle": libelle, "pages": set(), "poids": []}
        parent["subs"][sc] = s
        parent["ordre_subs"].append(sc)
    s["pages"].add(n)
    for valeur, unite in poids:
        s["poids"].append((valeur, unite, None, n))

def _lot_critere(t, lots_doc):
    """Lot d'un critère : « tous les lots », le numéro du lot unique, ou les lots où il est réservé."""
    numeros = [x["numero"] for x in lots_doc["liste"]] if lots_doc["statut"] == TROUVE else []
    pages = sorted(t["pages"])
    if len(numeros) == 1:
        return _fait([(numeros[0], p) for p in pages])
    attendus = {x for x in numeros if x is not None}
    if not t["lots"] or (attendus and attendus <= t["lots"]):
        return _fait([("tous les lots", p) for p in pages])
    return _fait([(lot, p) for lot in sorted(t["lots"]) for p in pages])


def _construire_criteres(classement, tops, ordre, lots_doc):
    liste = []
    for cle in ordre:
        t = tops[cle]
        sous = []
        for sc in t["ordre_subs"]:
            s = t["subs"][sc]
            sous.append({"libelle": s["libelle"], "pages": sorted(s["pages"]),
                         "ponderation": _fait_poids(s["poids"])})
        liste.append({"libelle": t["libelle"], "pages": sorted(t["pages"]),
                      "lot": _lot_critere(t, lots_doc), "ponderation": _fait_poids(t["poids"]),
                      "sous_criteres": sous})
    if classement and liste and not any(c["ponderation"]["statut"] == TROUVE for c in liste):
        for i, c in enumerate(liste, 1):
            c["ponderation"] = _fait_poids([(i, "rang", None, c["pages"][0])])
    return liste


def _type_ponderation(criteres, classement):
    paires = []
    for c in criteres:
        for v in c["ponderation"]["valeurs"]:
            paires += [(v["unite"], p) for p in v["pages"] if v["unite"] != "rang"]
    if paires:
        return _fait(paires)
    if classement and criteres:
        return _fait([("classement", p) for c in criteres for p in c["pages"]])
    return _fait([])


# ----------------------------------------------------------------- plan et contrôle

def _valeur_unique(fait):
    if fait["statut"] == TROUVE and len(fait["valeurs"]) == 1:
        return fait["valeurs"][0]["valeur"]
    return None


def _plan(criteres):
    plan = []
    for c in criteres:
        if _nature(c["libelle"]) != "technique":
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                plan.append({"titre": f"{c['libelle']} – {s['libelle']}", "critere": c["libelle"],
                             "sous_critere": s["libelle"],
                             "ponderation": _valeur_unique(s["ponderation"]),
                             "page_source": s["pages"][0], "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": _valeur_unique(c["ponderation"]),
                         "page_source": c["pages"][0], "contenu": ""})
    return plan


def controler(dossier):
    """Alertes du contrôle, calculées sur le plan et les critères du dossier tel quel."""
    criteres = dossier["criteres"]["liste"]
    plan = dossier["plan"]
    tp = _valeur_unique(dossier["type_ponderation"])
    alertes = []
    for c in criteres:
        if _nature(c["libelle"]) == "technique" and not any(s["critere"] == c["libelle"] for s in plan):
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in criteres:
        pv = c["ponderation"]
        if pv["statut"] != TROUVE or len(pv["valeurs"]) != 1 or not c["sous_criteres"]:
            continue
        if any(s["ponderation"]["statut"] != TROUVE or len(s["ponderation"]["valeurs"]) != 1
               for s in c["sous_criteres"]):
            continue
        sous = [s["ponderation"]["valeurs"][0] for s in c["sous_criteres"]]
        unites = {v["unite"] for v in sous}
        if len(unites) != 1:
            continue
        unite = unites.pop()
        total = sum(v["valeur"] for v in sous)
        parent = pv["valeurs"][0]
        if unite == parent["unite"]:
            incoherent = abs(total - parent["valeur"]) > 0.01
        elif unite == "pourcentage" and parent["unite"] == "points":
            incoherent = abs(total - 100) > 0.01
        else:
            incoherent = False
        if incoherent:
            alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    if tp == "pourcentage":
        totaux = {}
        for c in criteres:
            for v in c["ponderation"]["valeurs"]:
                if v["unite"] == "pourcentage":
                    totaux[v["lot"]] = totaux.get(v["lot"], 0) + v["valeur"]
        if any(abs(t - 100) > 0.01 for t in totaux.values()):
            alertes.append({"type": "total différent de 100 %", "objet": "critères"})
    return alertes


# ----------------------------------------------------------------- assemblage

def _extraire(pages):
    pages = list(pages)
    lots = _lots(pages)
    classement, tops, ordre = _criteres(pages)
    liste = _construire_criteres(classement, tops, ordre, lots)
    criteres = {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}
    return {
        "lots": lots,
        "date_limite": _date_limite(pages),
        "heure_limite": _heure_limite(pages),
        "date_questions": _date_questions(pages),
        "procedure": _procedure(pages),
        "visite_obligatoire": _visite_obligatoire(pages),
        "dates_visite": _dates_visite(pages),
        "variantes": _variantes(pages),
        "validite_offres": _validite_offres(pages),
        "mode_remise": _mode_remise(pages),
        "pieces": _pieces(pages),
        "limite_pages": _limite_pages(pages),
        "type_ponderation": _type_ponderation(liste, classement),
        "criteres": criteres,
    }


def analyser(pages):
    d = _extraire(pages)
    d["plan"] = _plan(d["criteres"]["liste"])
    d["controle"] = {"alertes": controler(d)}
    return d


# ----------------------------------------------------------------- vérification

FAITS_SIMPLES = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                 "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
                 "type_ponderation"]


def _meme(a, b):
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def _filtre_fait(fait, ref, conflit_si_plusieurs=True):
    """Ne garde que les valeurs proposées retrouvées dans l'extraction, sur leurs pages."""
    paires = []
    for v in fait.get("valeurs", []):
        for rv in ref["valeurs"]:
            if _meme(v["valeur"], rv["valeur"]):
                for p in sorted(set(v["pages"]) & set(rv["pages"])):
                    paires.append((rv["valeur"], p))
    return _fait(paires, conflit_si_plusieurs)


def _filtre_poids(fait, ref):
    paires = []
    for v in fait.get("valeurs", []):
        for rv in ref["valeurs"]:
            if _meme([v["valeur"], v["unite"], v["lot"]], [rv["valeur"], rv["unite"], rv["lot"]]):
                for p in sorted(set(v["pages"]) & set(rv["pages"])):
                    paires.append((rv["valeur"], rv["unite"], rv["lot"], p))
    return _fait_poids(paires)


def verifier(dossier, pages):
    ref = _extraire(pages)
    r = json.loads(json.dumps(dossier, ensure_ascii=False))
    for cle in FAITS_SIMPLES:
        r[cle] = _filtre_fait(r[cle], ref[cle], conflit_si_plusieurs=cle != "dates_visite")

    lots = []
    for lot in r["lots"]["liste"]:
        rl = [x for x in ref["lots"]["liste"] if x["numero"] == lot["numero"]]
        if not rl:
            continue
        rl = rl[0]
        paires = []
        for it in lot["intitules"]:
            for ri in rl["intitules"]:
                if it["valeur"] == ri["valeur"]:
                    paires += [(ri["valeur"], p) for p in sorted(set(it["pages"]) & set(ri["pages"]))]
        pages_lot = sorted(set(lot["pages"]) & set(rl["pages"]))
        if pages_lot:
            intitules = _fait(paires)["valeurs"] if paires else []
            lots.append({"numero": lot["numero"], "intitules": intitules, "pages": pages_lot,
                         "conflit": len(intitules) > 1})
    r["lots"] = {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}

    pieces = []
    for p in r["pieces"]["liste"]:
        rp = [x for x in ref["pieces"]["liste"] if x["nom"] == p["nom"]]
        if not rp:
            continue
        rp = rp[0]
        pages_p = sorted(set(p["pages"]) & set(rp["pages"]))
        if pages_p:
            pieces.append({"nom": p["nom"], "pages": pages_p,
                           "phase": _filtre_fait(p["phase"], rp["phase"], False),
                           "obligation": _filtre_fait(p["obligation"], rp["obligation"])})
    r["pieces"] = {"statut": TROUVE if pieces else NON_TROUVE, "liste": pieces}

    criteres = []
    for c in r["criteres"]["liste"]:
        rc = [x for x in ref["criteres"]["liste"] if x["libelle"] == c["libelle"]]
        if not rc:
            continue
        rc = rc[0]
        pages_c = sorted(set(c["pages"]) & set(rc["pages"]))
        if not pages_c:
            continue
        sous = []
        for s in c["sous_criteres"]:
            rs = [x for x in rc["sous_criteres"] if x["libelle"] == s["libelle"]]
            if not rs:
                continue
            pages_s = sorted(set(s["pages"]) & set(rs[0]["pages"]))
            if pages_s:
                sous.append({"libelle": s["libelle"], "pages": pages_s,
                             "ponderation": _filtre_poids(s["ponderation"], rs[0]["ponderation"])})
        criteres.append({"libelle": c["libelle"], "pages": pages_c,
                         "lot": _filtre_fait(c["lot"], rc["lot"]),
                         "ponderation": _filtre_poids(c["ponderation"], rc["ponderation"]),
                         "sous_criteres": sous})
    r["criteres"] = {"statut": TROUVE if criteres else NON_TROUVE, "liste": criteres}
    r["plan"] = _plan(criteres)
    r["controle"] = {"alertes": controler(r)}
    return r
