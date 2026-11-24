"""Lecture déterministe d'un règlement de la consultation (RC).

Expressions régulières et règles écrites uniquement. Aucun appel réseau,
aucun hasard : mêmes pages, même dossier.
"""
import copy
import re

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

MOIS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}

UNITES = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
          "six": 6, "sept": 7, "huit": 8, "neuf": 9}
TEENS = {"dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
         "seize": 16, "dix-sept": 17, "dix-huit": 18, "dix-neuf": 19}
DIZAINES = {"vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}


def norm(s):
    s = s.replace("’", "'").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def nombre_en_lettres(s):
    """Nombre écrit en lettres (1 à 999) : 'cent vingt' -> 120, 'quatre-vingt-dix' -> 90.
    Rend None si la chaîne n'est pas un nombre complet."""
    t = norm(s).replace("-", " ")
    t = re.sub(r"\s+et\s+", " ", t).strip()
    if not t:
        return None
    total = 0
    if "cent" in t.split():
        avant, _, apres = t.partition("cent")
        avant = avant.strip()
        centaines = 1 if avant == "" else UNITES.get(avant)
        if centaines is None:
            return None
        total += 100 * centaines
        t = apres.strip()
        if t == "":
            return total
    # quatre-vingt(s) [unité]
    m = re.fullmatch(r"quatre vingts?(?: (.+))?", t)
    if m:
        reste = m.group(1)
        if reste is None:
            return total + 80
        r = _unites_ou_teen(reste)
        return None if r is None else total + 80 + r
    # soixante [dix..dix-neuf | unité]
    m = re.fullmatch(r"soixante(?: (.+))?", t)
    if m:
        reste = m.group(1)
        if reste is None:
            return total + 60
        r = _unites_ou_teen(reste)
        if r is None:
            return None
        if 10 <= r <= 19:
            return total + 60 + r
        return None if r >= 10 else total + 60 + r
    for mot, val in DIZAINES.items():
        if t == mot:
            return total + val
        if t.startswith(mot + " "):
            r = UNITES.get(t[len(mot) + 1:])
            return None if r is None else total + val + r
    r = _unites_ou_teen(t)
    if r is None:
        return None
    return total + r


def _unites_ou_teen(t):
    t = t.strip()
    if t in UNITES:
        return UNITES[t]
    if t in TEENS:
        return TEENS[t]
    # nombre_en_lettres remplace les tirets par des espaces : « dix sept » -> « dix-sept »
    t_tiret = t.replace(" ", "-")
    if t_tiret in TEENS:
        return TEENS[t_tiret]
    return None


def premier_entier(texte):
    """Premier entier écrit en chiffres dans le texte, ou None."""
    m = re.search(r"(?<![\d/.:])(\d{1,4})(?![\d/.:])", texte)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- dates et heures

MOIS_RE = "|".join(sorted(MOIS, key=len, reverse=True))
DATE_CHIFFRES = r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b"
DATE_LETTRES = r"\b(\d{1,2}|1er|premier)\s+(" + MOIS_RE + r")\s+(\d{4})\b"


def _date_chiffres(m):
    jj, mm, aa = int(m.group(1)), int(m.group(2)), m.group(3)
    aa = int(aa) + (2000 if len(aa) == 2 else 0)
    if 1 <= mm <= 12 and 1 <= jj <= 31:
        return "%02d/%02d/%04d" % (jj, mm, aa)
    return None


def _date_lettres(m):
    jour = 1 if m.group(1) in ("1er", "premier") else int(m.group(1))
    return "%02d/%02d/%s" % (jour, MOIS[m.group(2)], m.group(3))


def dates_depuis_texte(texte):
    """Toutes les dates jj/mm/aaaa du texte (chiffres ou lettres), dans l'ordre d'apparition."""
    t = norm(texte)
    trouvees = []
    for m in re.finditer(DATE_CHIFFRES, t):
        d = _date_chiffres(m)
        if d:
            trouvees.append((m.start(), d))
    for m in re.finditer(DATE_LETTRES, t):
        trouvees.append((m.start(), _date_lettres(m)))
    trouvees.sort()
    return [d for _, d in trouvees]


def date_depuis_texte(texte):
    ds = dates_depuis_texte(texte)
    return ds[0] if ds else None


MOTS_HEURE = r"[a-zéè]+(?:-[a-zéè]+)*"


def heures_depuis_texte(texte):
    """Heures hh:mm écrites dans le texte, dans l'ordre d'apparition.
    Formes : 16h00, 16 h 00, 16h, 16:00, 16 heures, midi, seize heures trente."""
    t = norm(texte)
    trouvees = []
    for m in re.finditer(r"\b(\d{1,2})\s*(?:heures?|h|:(?=\d{2}))\s*(\d{2})?\b", t):
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        if hh < 24 and mm < 60:
            trouvees.append((m.start(), "%02d:%02d" % (hh, mm)))
    for m in re.finditer(r"\bmidi\b", t):
        trouvees.append((m.start(), "12:00"))
    for m in re.finditer(r"\b(" + MOTS_HEURE + r")\s+heures?(?:\s+(" + MOTS_HEURE + r"))?\b", t):
        hh = nombre_en_lettres(m.group(1))
        if hh is None or hh > 23:
            continue
        mm = 0
        if m.group(2):
            mm = nombre_en_lettres(m.group(2)) or 0
        if mm < 60:
            trouvees.append((m.start(), "%02d:%02d" % (hh, mm)))
    trouvees.sort()
    return [h for _, h in trouvees]


def heure_depuis_texte(texte):
    hs = heures_depuis_texte(texte)
    return hs[0] if hs else None


# ---------------------------------------------------------------- modèle de lignes

REMISE_RE = re.compile(r"remise|réception|reception|parvenir|déposé|depose|jusqu'au|au plus tard|"
                       r"attendu|date limite|heure limite|limites? de|\bplis\b")
QUESTION_RE = re.compile(r"question|renseignement|demande")
VISITE_RE = re.compile(r"\bvisite")


def lignes(pages):
    """Liste de (n° de page, texte) pour chaque ligne non vide, page 1 en premier."""
    sortie = []
    for n, texte in enumerate(pages, start=1):
        for ligne in nettoyer_page(texte).split("\n"):
            ligne = ligne.strip()
            if ligne:
                sortie.append((n, ligne))
    return sortie


def lignes_brutes(pages):
    """Mêmes lignes que lignes(), dans le même ordre, avec leur retrait d'origine."""
    sortie = []
    for n, texte in enumerate(pages, start=1):
        for ligne in nettoyer_page(texte).split("\n"):
            if ligne.strip():
                sortie.append((n, ligne.rstrip()))
    return sortie


def nettoyer_page(texte):
    if not isinstance(texte, str):
        return ""
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    return texte.replace(" ", " ").replace(" ", " ")


def phrases(ligne):
    """Découpe une ligne en phrases (sur « . » suivi d'un espace, ou « ; »)."""
    return [p.strip() for p in re.split(r"(?<=[.;])\s+", norm(ligne)) if p.strip()]


def fait_vide():
    return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}


def fait(paires, unique=True):
    """paires : liste de (valeur, n° de page). Rend le fait de la forme commune."""
    groupes = {}
    ordre = []
    for valeur, page in paires:
        cle = json_cle(valeur)
        if cle not in groupes:
            groupes[cle] = {"valeur": valeur, "pages": set()}
            ordre.append(cle)
        groupes[cle]["pages"].add(page)
    valeurs = [{"valeur": groupes[c]["valeur"], "pages": sorted(groupes[c]["pages"])} for c in ordre]
    if not valeurs:
        return fait_vide()
    return {"statut": TROUVE, "valeurs": valeurs,
            "conflit": bool(unique and len(valeurs) > 1)}


def json_cle(valeur):
    import json
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False)


def filtrer_fait(propose, reference):
    """Garde les valeurs proposées qui figurent dans la référence, avec les pages de la référence."""
    if not isinstance(propose, dict):
        return fait_vide()
    cles_ok = {json_cle(v["valeur"]): v for v in reference["valeurs"]}
    gardees = []
    for v in propose.get("valeurs", []):
        cle = json_cle(v.get("valeur"))
        if cle in cles_ok:
            gardees.append(cles_ok[cle])
    out = {"statut": TROUVE if gardees else NON_TROUVE,
           "valeurs": [{"valeur": g["valeur"], "pages": list(g["pages"])} for g in gardees],
           "conflit": bool(reference["conflit"] and len(gardees) > 1)}
    if not gardees:
        out = fait_vide()
    return out


# ---------------------------------------------------------------- faits simples

def fait_date_limite(L):
    paires = []
    for i, (n, l) in enumerate(L):
        s = norm(l)
        if not REMISE_RE.search(s) or QUESTION_RE.search(s) or VISITE_RE.search(s):
            continue
        dates = dates_depuis_texte(l)
        if not dates and i + 1 < len(L) and L[i + 1][0] == n:
            sl = L[i + 1][1]
            if not QUESTION_RE.search(norm(sl)) and not VISITE_RE.search(norm(sl)):
                dates = dates_depuis_texte(sl)
        paires += [(d, n) for d in dates]
    return fait(paires)


def fait_heure_limite(L):
    paires = []
    for i, (n, l) in enumerate(L):
        s = norm(l)
        if not REMISE_RE.search(s) or QUESTION_RE.search(s) or VISITE_RE.search(s):
            continue
        heures = heures_depuis_texte(l)
        if not heures and i + 1 < len(L) and L[i + 1][0] == n:
            sl = L[i + 1][1]
            if not QUESTION_RE.search(norm(sl)) and not VISITE_RE.search(norm(sl)):
                heures = heures_depuis_texte(sl)
        paires += [(h, n) for h in heures[:1]]
    return fait(paires)


DELAI_RE = re.compile(r"((?:\d+|[a-zéèêûô]+)(?:\s*\(\d+\))?\s+jours?\s+avant\s+la\s+date\s+limite[^.;\n]*)")


def fait_date_questions(L):
    paires = []
    for i, (n, l) in enumerate(L):
        s = norm(l)
        if not QUESTION_RE.search(s) or VISITE_RE.search(s):
            continue
        dates = dates_depuis_texte(l)
        if not dates and i + 1 < len(L) and L[i + 1][0] == n:
            sl = L[i + 1][1]
            if not REMISE_RE.search(norm(sl)) and not VISITE_RE.search(norm(sl)):
                dates = dates_depuis_texte(sl)
        if dates:
            paires += [(d, n) for d in dates]
        else:
            m = DELAI_RE.search(s)
            if m:
                paires.append((m.group(1).strip(), n))
    return fait(paires)


PROCEDURES = [
    (re.compile(r"proc[ée]dure adapt[ée]e"), "procédure adaptée"),
    (re.compile(r"appel d'offres ouvert"), "appel d'offres ouvert"),
    (re.compile(r"appel d'offres restreint"), "appel d'offres restreint"),
    (re.compile(r"dialogue comp[ée]titif"), "dialogue compétitif"),
    (re.compile(r"(?<![\w\-])mapa(?![\w\-])"), "procédure adaptée"),
]


def fait_procedure(L):
    paires = []
    for n, l in L:
        s = norm(l)
        for motif, valeur in PROCEDURES:
            if motif.search(s):
                paires.append((valeur, n))
    return fait(paires)


def fait_visite_obligatoire(L):
    paires = []
    for n, l in L:
        s = norm(l)
        if not VISITE_RE.search(s):
            continue
        if re.search(r"non obligatoire|pas obligatoire|facultati", s):
            paires.append(("non", n))
        elif re.search(r"\bobligatoire\b", s):
            paires.append(("oui", n))
    return fait(paires)


def fait_dates_visite(L):
    paires = []
    contexte = False
    for n, l in L:
        s = norm(l)
        est_remise = REMISE_RE.search(s) and not VISITE_RE.search(s)
        if VISITE_RE.search(s):
            contexte = True
        elif contexte and re.search(r"aura lieu|dates? suivantes|cr[ée]neau|organis", s):
            pass
        else:
            contexte = False
            continue
        if est_remise or QUESTION_RE.search(s):
            continue
        paires += [(d, n) for d in dates_depuis_texte(l)]
    return fait(paires, unique=False)


def fait_variantes(L):
    paires = []
    for n, l in L:
        for s in phrases(l):
            if "variante" not in s:
                continue
            if re.search(r"\bne sont pas\b|\bn'est\b|\bne seront pas\b|interdit|non autoris|pas autoris|"
                         r"pas admis|pas admise|aucune variante|\bne sont\b", s):
                paires.append(("non autorisées", n))
            elif re.search(r"autoris|admis|admise|peuvent", s):
                paires.append(("autorisées", n))
    return fait(paires)


FILLER = {"des", "offres", "offre", "est", "de", "fixé", "fixée", "fixe", "à", "a", "pendant",
          "sont", "restent", "valables", "valable", "pour", "la", "le", "en", "du", "au", "sur",
          "d", "l", "être", "etre"}


def fait_validite(L):
    paires = []
    for n, l in L:
        for s in phrases(l):
            if not re.search(r"validit|valable|valide", s):
                continue
            if re.search(r"recours|contestation|attestation|r[ée]f[ée]r[ée]|ex[ée]cution|cours de validit", s):
                continue
            m = re.search(r"(?:validit[ée]|valables?|valides?)(.*?)\b(jours|mois)\b", s)
            if not m:
                continue
            milieu = m.group(1)
            chiffre = re.search(r"\((\d+)\)", milieu) or re.search(r"\b(\d+)\b", milieu)
            if chiffre:
                nombre = int(chiffre.group(1))
            else:
                mots = [w.strip(":,") for w in milieu.replace("'", " ").split()]
                reste = " ".join(w for w in mots if w and w not in FILLER)
                nombre = nombre_en_lettres(reste)
            if nombre is None:
                continue
            paires.append(({"nombre": nombre, "unite": m.group(2)}, n))
    return fait(paires)


def fait_mode_remise(L):
    paires = []
    for n, l in L:
        for s in phrases(l):
            if re.search(r"question|renseignement", s):
                continue
            if not re.search(r"offre|\bplis?\b|remi|transmi|déposé|depose|dématérialis", s):
                continue
            neg = re.search(r"\bpas\b|aucune|\bne sera\b|\bne seront\b|\bn'est\b|interdi|refus|exclu|non autoris|\bne sont\b", s)
            if re.search(r"papier", s) and not neg:
                paires.append(("papier", n))
            if re.search(r"électronique|dématérialis|plateforme|profil d'acheteur", s):
                paires.append(("électronique", n))
    return fait(paires)


# ---------------------------------------------------------------- lots

LOT_RE = re.compile(r"\blot\s*(?:n\s*[°o]?\s*)?(\d{1,2})\b(?:\s*[:\-–—]\s*(.*?)|\s+(\S.*?))?\s*$", re.IGNORECASE)
LOT_UNIQUE_RE = re.compile(r"lot unique|pas (?:encore )?alloti|non alloti|pas (?:pr[ée]vu )?de d[ée]composition en lots|"
                           r"n'est pas alloti|n’est pas alloti")


def numero_lot_de_ligne(ligne):
    """(numéro, intitulé éventuel) si la ligne porte « lot n° X [: intitulé] », sinon None."""
    texte = ligne.strip().lstrip("-•*●▪ ").strip()
    m = LOT_RE.search(texte)
    if not m:
        return None
    titre = m.group(2) if m.group(2) is not None else m.group(3)
    titre = (titre or "").strip().rstrip(" ;.,").strip()
    return int(m.group(1)), titre


def fait_lots(L):
    titres = {}
    pages_mention = set()
    unique_pages = set()
    for n, l in L:
        s = norm(l)
        if LOT_UNIQUE_RE.search(s) and "lot unique" in s or re.search(r"pas (?:encore )?alloti|n'est pas alloti|n’est pas alloti|non alloti|pas (?:pr[ée]vu )?de d[ée]composition en lots", s):
            unique_pages.add(n)
            continue
        lot = numero_lot_de_ligne(l)
        if lot is None:
            continue
        numero, titre = lot
        if not titre:
            continue
        cle = (numero, norm(titre))
        if cle not in titres:
            titres[cle] = {"valeur": titre, "pages": set(), "numero": numero}
        titres[cle]["pages"].add(n)
        pages_mention.add(n)
    liste = []
    numeros = sorted({c[0] for c in titres})
    for numero in numeros:
        entrees = [v for c, v in titres.items() if c[0] == numero]
        pages = set()
        intitules = []
        for e in entrees:
            pages |= e["pages"]
            intitules.append({"valeur": e["valeur"], "pages": sorted(e["pages"])})
        liste.append({"numero": numero, "intitules": intitules, "pages": sorted(pages),
                      "conflit": len(intitules) > 1})
    if not liste and unique_pages:
        liste.append({"numero": None, "intitules": [], "pages": sorted(unique_pages), "conflit": False})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ---------------------------------------------------------------- pièces

HEADER_PIECE_RE = re.compile(r"pi[èe]ces?\b|titre de l\S*\s*(?:candidature|offre)|attributaire|produira|remettra|"
                             r"remettront|remettent|comprendra|suivantes?\b|à fournir|à produire|documents suivants",
                             re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*(?:[-•*●▪]|\d+[.)]|[a-z][.)])\s+(.*)$")
ARTICLE_RE = re.compile(r"^\s*article\s+(?:\d|[a-zéè])", re.IGNORECASE)
QUALIF_RE = re.compile(r"\s*\((?:obligatoire|facultati\w*|non obligatoire)\)", re.IGNORECASE)


def phase_de(s):
    if "attributaire" in s or "attribuer" in s:
        return "attributaire"
    if "candidature" in s:
        return "candidature"
    if re.search(r"\boffre\b", s):
        return "offre"
    return None


def obligation_de(s):
    if re.search(r"facultati|non obligatoire", s):
        return "non obligatoire"
    if re.search(r"\bobligatoire\b", s):
        return "obligatoire"
    return None


def fait_pieces(L):
    contexte = False
    phase = None
    pieces = {}
    ordre = []
    for n, l in L:
        s = norm(l)
        if ARTICLE_RE.match(l):
            contexte = False
        est_puce = BULLET_RE.match(l)
        if HEADER_PIECE_RE.search(s) and (not est_puce or l.rstrip().endswith(":")):
            contexte = True
            phase = phase_de(s)
            continue
        if not contexte:
            continue
        if not est_puce:
            contexte = False
            continue
        brut = est_puce.group(1).strip().rstrip(" ;.,").strip()
        nom = QUALIF_RE.sub("", brut).strip()
        if not nom:
            continue
        cle = norm(nom)
        if cle not in pieces:
            pieces[cle] = {"nom": nom, "pages": set(), "phase": [], "obligation": []}
            ordre.append(cle)
        pieces[cle]["pages"].add(n)
        if phase:
            pieces[cle]["phase"].append((phase, n))
        ob = obligation_de(s)
        if ob:
            pieces[cle]["obligation"].append((ob, n))
    liste = []
    for cle in ordre:
        p = pieces[cle]
        liste.append({"nom": p["nom"], "pages": sorted(p["pages"]),
                      "phase": fait(p["phase"], unique=False),
                      "obligation": fait(p["obligation"], unique=True)})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ---------------------------------------------------------------- limite de pages

def fait_limite_pages(L):
    paires = []
    for n, l in L:
        s = norm(l)
        if "mémoire" not in s:
            continue
        for m in re.finditer(r"\bpages?\b", s):
            avant = s[:m.start()].rstrip()
            chiffre = re.search(r"\((\d+)\)$", avant) or re.search(r"(\d+)$", avant)
            if chiffre:
                paires.append((int(chiffre.group(1)), n))
                continue
            mots = re.findall(r"[a-zéè\-]+", avant)
            for k in range(max(0, len(mots) - 3), len(mots)):
                valeur = nombre_en_lettres(" ".join(mots[k:]))
                if valeur is not None:
                    paires.append((valeur, n))
                    break
    return fait(paires)


# ---------------------------------------------------------------- critères

CRIT_ZONE_RE = re.compile(r"crit[èe]res?|jugement des offres|notées? sur|sélection des offres|classés? par ordre|"
                          r"classement|pondérations?|note finale|ordre décroissant|ordre d'importance", re.IGNORECASE)
CLASSEMENT_RE = re.compile(r"classés? par ordre|ordre décroissant|ordre d'importance|classement", re.IGNORECASE)


def _nombre(txt):
    x = float(txt.replace(",", "."))
    return int(x) if x == int(x) else x


def poids_de(texte):
    """(valeur, unité) du poids écrit dans le texte, ou None."""
    s = norm(texte)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:%|pour ?cent)", s)
    if m:
        return (_nombre(m.group(1)), "pourcentage")
    m = re.search(r"((?:[a-zéè\-]+\s+){0,2}[a-zéè\-]+)\s+pour ?cent", s)
    if m:
        mots = m.group(1).split()
        for k in range(len(mots)):
            v = nombre_en_lettres(" ".join(mots[k:]))
            if v is not None:
                return (v, "pourcentage")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:points?|pts)\b", s)
    if m:
        return (_nombre(m.group(1)), "points")
    return None


def libelle_et_poids(texte):
    t = texte.strip()
    m = re.search(r"\(([^()]*)\)", t)
    if m and poids_de(m.group(1)):
        return t[:m.start()].strip(" :;.|,"), poids_de(m.group(1))
    for m in re.finditer(r"[:|]", t):
        p = poids_de(t[m.end():])
        if p:
            return t[:m.start()].strip(" :;.|,"), p
    return t.strip(" :;.|,"), None


def item_de_ligne(l, brut=None):
    """('top' | 'sub', texte) si la ligne ressemble à un critère ou sous-critère, sinon None.
    brut : la ligne telle qu'elle est écrite, avec son retrait (le retrait marque le sous-critère)."""
    brut = l if brut is None else brut
    ind = len(brut) - len(brut.lstrip())
    t = l.strip()
    m = re.match(r"crit[èe]re\s*n\s*[°o]?\s*\d+\s*[:\-–—]\s*(.+)$", t, re.IGNORECASE)
    if m:
        return "top", m.group(1)
    m = re.match(r"\d+\.\d+[.)]?\s+(.+)$", t)
    if m:
        return "sub", m.group(1)
    if ind > 0:
        m = re.match(r"[a-zA-Z][.)]\s+(.+)$", t)
        if m:
            return "sub", m.group(1)
    m = re.match(r"[-•*●▪]\s+(.+)$", t)
    if m:
        return ("sub" if ind > 0 else "top"), m.group(1)
    m = re.match(r"\d+[.)]\s+(.+)$", t)
    if m:
        return "top", m.group(1)
    if "|" in t:
        return ("sub" if ind > 0 else "top"), t
    return None


def extraire_criteres(L, brutes):
    """Rend la liste des critères brute : chaque critère porte ses occurrences.
    L : (n° de page, ligne) ; brutes : mêmes lignes avec leur retrait, dans le même ordre."""
    zone = False
    lot_courant = None
    criteres = []
    index = {}
    cur = None
    for (n, l), (_, brut) in zip(L, brutes):
        s = norm(l)
        if ARTICLE_RE.match(l):
            zone = bool(CRIT_ZONE_RE.search(s))
            lot_courant = None
            continue
        if CRIT_ZONE_RE.search(s):
            if not zone:
                lot_courant = None
            zone = True
        lot = numero_lot_de_ligne(l)
        if lot is not None and (lot[1] or LOT_RE.search(l.strip())):
            lot_courant = lot[0]
            continue
        it = item_de_ligne(l, brut)
        if it is None:
            continue
        kind, texte = it
        if "|" in texte and not poids_de(texte.split("|", 1)[1]):
            continue
        label, poids = libelle_et_poids(texte)
        if not label:
            continue
        if poids is None and not zone:
            continue
        if kind == "top":
            cle = norm(label)
            if cle not in index:
                index[cle] = {"libelle": label, "pages": set(), "occ": [], "poids": [], "subs": [], "subidx": {}}
                criteres.append(index[cle])
            rec = index[cle]
            rec["pages"].add(n)
            rec["occ"].append((lot_courant, n))
            if poids:
                rec["poids"].append((poids[0], poids[1], lot_courant, n))
            cur = rec
        else:
            if cur is None:
                continue
            cle = norm(label)
            if cle not in cur["subidx"]:
                cur["subidx"][cle] = {"libelle": label, "pages": set(), "poids": []}
                cur["subs"].append(cur["subidx"][cle])
            sub = cur["subidx"][cle]
            sub["pages"].add(n)
            if poids:
                sub["poids"].append((poids[0], poids[1], lot_courant, n))
    return criteres


def fait_poids(entrees):
    """entrees : (valeur, unité, lot, page). Fait FaitP : conflit si deux valeurs pour un même lot."""
    groupes = {}
    ordre = []
    for v, u, lot, p in entrees:
        cle = json_cle([v, u, lot])
        if cle not in groupes:
            groupes[cle] = {"valeur": v, "unite": u, "lot": lot, "pages": set()}
            ordre.append(cle)
        groupes[cle]["pages"].add(p)
    valeurs = [{"valeur": groupes[c]["valeur"], "unite": groupes[c]["unite"], "lot": groupes[c]["lot"],
                "pages": sorted(groupes[c]["pages"])} for c in ordre]
    par_lot = {}
    for v in valeurs:
        par_lot.setdefault(json_cle(v["lot"]), set()).add(json_cle(v["valeur"]))
    conflit = any(len(x) > 1 for x in par_lot.values())
    if not valeurs:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    return {"statut": TROUVE, "valeurs": valeurs, "conflit": conflit}


UNITE_TYPE = {"pourcentage": "pourcentage", "points": "points", "rang": "classement"}


def sortie_criteres(brut, lots_liste, classement):
    """Met le brut en forme : critères, lot de chaque critère, pondérations, type de pondération."""
    tous_poids = [p for rec in brut for p in rec["poids"]]
    if not tous_poids and classement and brut:
        for idx, rec in enumerate(brut, start=1):
            for _, p in rec["occ"]:
                rec["poids"].append((idx, "rang", None, p))
        tous_poids = [p for rec in brut for p in rec["poids"]]
    liste = []
    for rec in brut:
        occ_lots = [lot for lot, _ in rec["occ"]]
        nums = {x for x in occ_lots if x is not None}
        if nums and None not in occ_lots and len(nums) == 1:
            valeur_lot = next(iter(nums))
        elif not nums:
            valeur_lot = lots_liste[0]["numero"] if len(lots_liste) == 1 else "tous les lots"
        else:
            valeur_lot = "tous les lots"
        pages = sorted(rec["pages"])
        lot = {"statut": TROUVE, "valeurs": [{"valeur": valeur_lot, "pages": pages}], "conflit": False}
        subs = []
        for s in rec["subs"]:
            subs.append({"libelle": s["libelle"], "pages": sorted(s["pages"]),
                         "ponderation": fait_poids(s["poids"])})
        liste.append({"libelle": rec["libelle"], "pages": pages, "lot": lot,
                      "ponderation": fait_poids(rec["poids"]), "sous_criteres": subs})
    type_fait = fait_vide()
    if tous_poids:
        type_fait = fait([(UNITE_TYPE[u], p) for _, u, _, p in tous_poids], unique=True)
    criteres = {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}
    return criteres, type_fait


def nature(libelle):
    s = norm(libelle)
    if re.search(r"\bprix\b|\bco[uû]t\b", s):
        return "prix"
    if re.search(r"technique|qualit|m[ée]rite|m[ée]thodolog", s):
        return "technique"
    return "autre"


def construire_plan(criteres):
    plan = []
    for c in criteres:
        if nature(c["libelle"]) != "technique":
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                vals = s["ponderation"]["valeurs"]
                plan.append({"titre": c["libelle"] + " – " + s["libelle"], "critere": c["libelle"],
                             "sous_critere": s["libelle"],
                             "ponderation": vals[0]["valeur"] if vals else None,
                             "page_source": s["pages"][0], "contenu": ""})
        else:
            vals = c["ponderation"]["valeurs"]
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": vals[0]["valeur"] if vals else None,
                         "page_source": c["pages"][0], "contenu": ""})
    return plan


def controler(d):
    alertes = []
    plan = d.get("plan") or []
    criteres = (d.get("criteres") or {}).get("liste") or []
    for c in criteres:
        if nature(c["libelle"]) == "technique" and not any(s.get("critere") == c["libelle"] for s in plan):
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
        if c["sous_criteres"]:
            for pv in c["ponderation"]["valeurs"]:
                somme = []
                complet = True
                for sub in c["sous_criteres"]:
                    cands = [v for v in sub["ponderation"]["valeurs"]
                             if v["unite"] == pv["unite"] and json_cle(v["lot"]) == json_cle(pv["lot"])]
                    if not cands:
                        complet = False
                        break
                    somme.append(cands[0]["valeur"])
                if complet and abs(sum(somme) - pv["valeur"]) > 0.01:
                    alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
                    break
    type_p = d.get("type_ponderation") or {}
    if type_p.get("statut") == TROUVE and [v["valeur"] for v in type_p.get("valeurs", [])] == ["pourcentage"]:
        totaux = {}
        for c in criteres:
            vus = set()
            for pv in c["ponderation"]["valeurs"]:
                if pv["unite"] != "pourcentage":
                    continue
                cle = json_cle(pv["lot"])
                if cle in vus:
                    continue
                vus.add(cle)
                totaux[cle] = totaux.get(cle, 0) + pv["valeur"]
        if any(abs(t - 100) > 0.01 for t in totaux.values()):
            alertes.append({"type": "total différent de 100 %", "objet": "critères"})
    return alertes


def extraire(pages):
    """Ce que le RC propose, sans vérification. Les faits sont de la forme commune."""
    L = lignes(pages)
    d = {}
    d["date_limite"] = fait_date_limite(L)
    d["heure_limite"] = fait_heure_limite(L)
    d["date_questions"] = fait_date_questions(L)
    d["procedure"] = fait_procedure(L)
    d["visite_obligatoire"] = fait_visite_obligatoire(L)
    d["dates_visite"] = fait_dates_visite(L)
    d["variantes"] = fait_variantes(L)
    d["validite_offres"] = fait_validite(L)
    d["mode_remise"] = fait_mode_remise(L)
    d["lots"] = fait_lots(L)
    d["pieces"] = fait_pieces(L)
    d["limite_pages"] = fait_limite_pages(L)
    classement = any(CLASSEMENT_RE.search(norm(l)) for _, l in L)
    d["criteres"], d["type_ponderation"] = sortie_criteres(extraire_criteres(L, lignes_brutes(pages)),
                                                          d["lots"]["liste"], classement)
    return d


FAITS_SIMPLES = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                 "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
                 "type_ponderation"]


def verifier(d, pages):
    """Retire de d tout ce qui ne se retrouve pas dans le texte des pages, puis recalcule plan et contrôle."""
    raw = extraire(pages)
    out = {}
    for k in FAITS_SIMPLES:
        out[k] = filtrer_fait(d.get(k), raw[k])
    proposes = d.get("lots") if isinstance(d.get("lots"), dict) else {}
    numeros = [x.get("numero") for x in proposes.get("liste", []) if isinstance(x, dict)]
    lots = [x for x in raw["lots"]["liste"] if x["numero"] in numeros]
    out["lots"] = {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}
    proposes = d.get("criteres") if isinstance(d.get("criteres"), dict) else {}
    libelles = [norm(str(c.get("libelle", ""))) for c in proposes.get("liste", []) if isinstance(c, dict)]
    criteres = [c for c in raw["criteres"]["liste"] if norm(c["libelle"]) in libelles]
    out["criteres"] = {"statut": TROUVE if criteres else NON_TROUVE, "liste": criteres}
    proposes = d.get("pieces") if isinstance(d.get("pieces"), dict) else {}
    noms = [norm(str(p.get("nom", ""))) for p in proposes.get("liste", []) if isinstance(p, dict)]
    pieces = [p for p in raw["pieces"]["liste"] if norm(p["nom"]) in noms]
    out["pieces"] = {"statut": TROUVE if pieces else NON_TROUVE, "liste": pieces}
    out["plan"] = construire_plan(criteres)
    out["controle"] = {"alertes": controler(out)}
    return out


def analyser(pages):
    """Point d'entrée : lit les pages du RC et rend le dossier (sérialisable en JSON)."""
    pages = list(pages)
    return verifier(extraire(pages), pages)
