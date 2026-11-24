"""Lecture déterministe d'un règlement de consultation (RC).

Bibliothèque standard uniquement. Points d'entrée : analyser, verifier, controler.
"""
import copy
import json
import re
import unicodedata

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"


# ------------------------------------------------------------ texte

def _base(c):
    d = unicodedata.normalize("NFD", c)
    return d[0] if len(d) > 1 and d[0].isascii() else c


def _f(s):
    """Repli sans accent, de longueur constante : mêmes indices que s."""
    return "".join(_base(c) for c in s)


def _norm(page):
    t = page.replace("\r\n", "\n").replace("\r", "\n")
    for c in (" ", " ", " "):
        t = t.replace(c, " ")
    return t.replace("’", "'")


def _phrases(s):
    return [x for x in re.split(r"(?<=[.;])\s+", s) if x.strip()]


def _fait(occ, conflit=True):
    """occ : liste de (valeur, page). Rend un Fait de la forme commune."""
    groupes = {}
    for v, p in occ:
        k = json.dumps(v, sort_keys=True, ensure_ascii=False)
        g = groupes.setdefault(k, {"valeur": v, "pages": set()})
        g["pages"].add(p)
    vals = [{"valeur": g["valeur"], "pages": sorted(g["pages"])} for g in groupes.values()]
    if not vals:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    return {"statut": TROUVE, "valeurs": vals, "conflit": bool(conflit and len(vals) > 1)}


# ------------------------------------------------------------ nombres

_UNITES = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
           "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
           "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20,
           "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100}


def _nombre_mots(mots):
    toks = [t for t in re.split(r"[\s\-]+", mots.lower()) if t]
    if not toks:
        return None
    cur, i = 0, 0
    while i < len(toks):
        t = toks[i]
        if t == "quatre" and i + 1 < len(toks) and toks[i + 1] in ("vingt", "vingts"):
            cur += 80
            i += 2
            continue
        if t not in _UNITES:
            return None
        if t == "cent":
            cur = cur * 100 if cur else 100
        else:
            cur += _UNITES[t]
        i += 1
    return cur


def _mots_avant(fs, pos):
    toks = re.findall(r"[a-z]+", fs[:pos].lower())
    out = []
    for t in reversed(toks):
        if t in _UNITES:
            out.insert(0, t)
        else:
            break
    return " ".join(out)


def _nombre_avant(fs, pos):
    """Nombre écrit juste avant pos : « (4) », chiffres ou lettres."""
    pre = fs[:pos].rstrip()
    m = re.search(r"\((\d+)\)$", pre)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)$", pre)
    if m:
        return int(m.group(1))
    return _nombre_mots(_mots_avant(fs, len(pre)))


def _valeur(s):
    v = float(s.replace(",", "."))
    return int(v) if v.is_integer() else v


# ------------------------------------------------------------ dates et heures

_MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
         "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
_DATE_LET = re.compile(r"\b(\d{1,2}|1er|premier)\s+(janvier|fevrier|mars|avril|mai|juin|juillet"
                       r"|aout|septembre|octobre|novembre|decembre)\s+(\d{4})\b", re.I)
_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")


def _dates(s):
    fs = _f(s)
    out = []
    for m in _DATE_LET.finditer(fs):
        j = m.group(1).lower()
        j = 1 if j in ("1er", "premier") else int(j)
        out.append((m.start(), f"{j:02d}/{_MOIS[m.group(2).lower()]:02d}/{m.group(3)}"))
    for m in _DATE_NUM.finditer(fs):
        y = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
        out.append((m.start(), f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{y}"))
    return [v for _, v in sorted(out)]


_HEURE_NUM = re.compile(r"(?<!\d)(\d{1,2})\s*(?:h|:)\s*(\d{2})?(?!\d)", re.I)
_HEURE_LET = re.compile(r"\b(onze|douze|treize|quatorze|quinze|seize|dix-sept|dix-huit|dix-neuf"
                        r"|dix|neuf|huit|sept|six|cinq|quatre|trois|deux|vingt-deux|vingt-trois"
                        r"|vingt)\s+heures?(?:\s+(trente|quinze|quarante-cinq))?\b", re.I)
_MIDI = re.compile(r"\bmidi\b", re.I)


def _heures(s):
    fs = _f(s)
    out = []
    for m in _HEURE_NUM.finditer(fs):
        out.append((m.start(), int(m.group(1)), int(m.group(2) or 0)))
    for m in _HEURE_LET.finditer(fs):
        mi = _nombre_mots(m.group(2)) if m.group(2) else 0
        out.append((m.start(), _nombre_mots(m.group(1)), mi))
    for m in _MIDI.finditer(fs):
        out.append((m.start(), 12, 0))
    out.sort()
    return [f"{h:02d}:{mi:02d}" for _, h, mi in out]


# ------------------------------------------------------------ faits simples

_REMISE = re.compile(r"offre|\bpli|remise|depot|reception", re.I)
_LIMITE = re.compile(r"limite|parvenir|remis|avant|jusqu|attendu|plus tard|heure|date|depos", re.I)
_QUESTION = re.compile(r"question|renseignement", re.I)
_VISITE = re.compile(r"visite|aura lieu|dates suivantes", re.I)
_DELAI_Q = re.compile(r"((?:\d+|[a-z]+)(?:\s*\(\d+\))?\s+jours)\s+avant", re.I)
_NON_VISITE = re.compile(r"non obligatoire|pas obligatoire|n'est pas obligatoire|facultati", re.I)
_NEG_VAR = re.compile(r"ne sont pas autoris|ne sont pas admis|pas autoris|interdit|non autoris"
                      r"|aucune variante|pas admis", re.I)
_POS_VAR = re.compile(r"autorisee|admise|peuvent presenter|peuvent proposer", re.I)
_MODE_CTX = re.compile(r"offre|\bpli|remise|depot|transmi|depose|remis", re.I)
_ELEC = re.compile(r"electronique|dematerialis|profil d'acheteur|marches-securises|plateforme"
                   r"|https?://", re.I)
_PAPIER = re.compile(r"papier|sous pli cachete|recepisse", re.I)
_NEG_PAP = re.compile(r"aucune|n'est pas|ne sera pas|ne seront pas|ne sont pas|pas autoris"
                      r"|non admis|pas admis|pas accept|interdit", re.I)
_PROCS = [(re.compile(r"(?<![\w-])mapa(?![\w-])", re.I), "procédure adaptée"),
          (re.compile(r"procedure adaptee", re.I), "procédure adaptée"),
          (re.compile(r"appel d'offres ouvert", re.I), "appel d'offres ouvert"),
          (re.compile(r"appel d'offres restreint", re.I), "appel d'offres restreint"),
          (re.compile(r"dialogue competitif", re.I), "dialogue compétitif")]


def _fenetres(lignes):
    """Texte de chaque ligne, complété par la ligne suivante si la date ou l'heure est coupée."""
    for i, l in enumerate(lignes):
        t = l
        if (re.search(r"limite|date|heure", _f(l), re.I) and not (_dates(l) or _heures(l))
                and i + 1 < len(lignes)):
            t = l + " " + lignes[i + 1]
        yield t


def _validites(fp):
    if not re.search(r"validite|valable", fp, re.I):
        return []
    out = []
    for m in re.finditer(r"\b(jours?|mois)\b", fp, re.I):
        n = _nombre_avant(fp, m.start())
        if n is not None:
            out.append({"nombre": n, "unite": "mois" if m.group(1).lower() == "mois" else "jours"})
    return out


def _limites(fp):
    if not re.search(r"memoire", fp, re.I):
        return []
    out = []
    for m in re.finditer(r"\bpages?\b", fp, re.I):
        n = _nombre_avant(fp, m.start())
        if n is not None:
            out.append(n)
    return out


def _faits_simples(pages):
    occ = {k: [] for k in ("date_limite", "heure_limite", "date_questions", "procedure", "visite",
                           "dates_visite", "variantes", "validite", "mode", "limite_pages")}
    for p, page in enumerate(pages, 1):
        lignes = _norm(page).split("\n")
        for t in _fenetres(lignes):
            ft = _f(t)
            if _QUESTION.search(ft):
                ds = _dates(t)
                if ds:
                    occ["date_questions"] += [(d, p) for d in ds]
                else:
                    m = _DELAI_Q.search(ft)
                    if m:
                        occ["date_questions"].append((t[m.start(1):m.end(1)], p))
            elif _VISITE.search(ft) and not _REMISE.search(ft):
                occ["dates_visite"] += [(d, p) for d in _dates(t)]
            elif _REMISE.search(ft) and _LIMITE.search(ft):
                occ["date_limite"] += [(d, p) for d in _dates(t)]
                occ["heure_limite"] += [(h, p) for h in _heures(t)]
        for l in lignes:
            for ph in _phrases(l):
                fp = _f(ph)
                if re.search(r"visite", fp, re.I) and not _QUESTION.search(fp):
                    if _NON_VISITE.search(fp):
                        occ["visite"].append(("non", p))
                    elif re.search(r"obligatoire", fp, re.I):
                        occ["visite"].append(("oui", p))
                if re.search(r"variante", fp, re.I):
                    if _NEG_VAR.search(fp):
                        occ["variantes"].append(("non autorisées", p))
                    elif _POS_VAR.search(fp):
                        occ["variantes"].append(("autorisées", p))
                occ["validite"] += [(v, p) for v in _validites(fp)]
                if _MODE_CTX.search(fp) and not _QUESTION.search(fp):
                    if _ELEC.search(fp):
                        occ["mode"].append(("électronique", p))
                    if _PAPIER.search(fp) and not _NEG_PAP.search(fp):
                        occ["mode"].append(("papier", p))
                occ["limite_pages"] += [(n, p) for n in _limites(fp)]
                for rx, val in _PROCS:
                    if rx.search(fp):
                        occ["procedure"].append((val, p))
    return {
        "date_limite": _fait(occ["date_limite"]),
        "heure_limite": _fait(occ["heure_limite"]),
        "date_questions": _fait(occ["date_questions"]),
        "procedure": _fait(occ["procedure"]),
        "visite_obligatoire": _fait(occ["visite"]),
        "dates_visite": _fait(occ["dates_visite"], conflit=False),
        "variantes": _fait(occ["variantes"]),
        "validite_offres": _fait(occ["validite"]),
        "mode_remise": _fait(occ["mode"]),
        "limite_pages": _fait(occ["limite_pages"]),
    }


# ------------------------------------------------------------ structure : lots, critères, pièces

_LOT_BLOC = re.compile(r"^\s*lot\s*n?\s*[°o]?\s*(\d{1,2})\s*:?\s*$", re.I)
_LOT_LIGNE = re.compile(r"^\s*[-•*]?\s*lot\s*n?\s*[°o]?\s*(\d{1,2})\s*(?:[:\-–—]\s*(.+?))?\s*$", re.I)
_LOT_UNIQUE = re.compile(r"lot unique|pas alloti|non alloti|pas prevu de decomposition en lots"
                         r"|pas de decomposition en lots|traite en lot unique|en un lot unique", re.I)
_CTX_OUVRE = re.compile(r"critere|ponderation|jugement|notee|classes? |rappel", re.I)
_ARTICLE = re.compile(r"^\s*(article|annexe)\b", re.I)
_PREF = re.compile(r"^(?P<ws>\s*)(?:(?P<critn>critère\s*n\s*[°o]?\s*\d+\s*[:\-–—]?)\s*"
                   r"|(?P<num>\d+(?:\.\d+)*)(?:\s*[.)]\s*|\s+)"
                   r"|(?P<lettre>[a-z])\)\s*|(?P<puce>[-•*])\s*)", re.I)
_P_PCT = re.compile(r"(\d+(?:[,.]\d+)?)\s*(?:%|pour\s*cent)", re.I)
_P_PTS = re.compile(r"(\d+(?:[,.]\d+)?)\s*(?:points?|pts)\b", re.I)


def _cle(s):
    return re.sub(r"\s+", " ", _f(s)).strip().lower()


def _libelle(t):
    t = re.split(r"\s*[(:|]|,\s|\s[–—-]\s", t, maxsplit=1)[0]
    return t.strip().rstrip(" ;.,–—-").strip()


def _poids(src):
    m = _P_PCT.search(src)
    if m:
        return (_valeur(m.group(1)), "pourcentage")
    m = _P_PTS.search(src)
    if m:
        return (_valeur(m.group(1)), "points")
    fs = _f(src)
    m = re.search(r"pour\s*cent", fs, re.I)
    if m:
        n = _nombre_mots(_mots_avant(fs, m.start()))
        if n is not None:
            return (n, "pourcentage")
    return None


def _item(s):
    first, rest = (s.split("|", 1) if "|" in s else (s, None))
    m = _PREF.match(first)
    if m:
        txt = first[m.end():]
        ind = len(m.group("ws"))
        num = m.group("num")
        crit_n = m.group("critn") is not None
        lettre = m.group("lettre") is not None
        puce = m.group("puce") is not None
    else:
        if rest is None and not re.match(r"^[^:]{2,80}:\s*\d[\d.,]*\s*(%|pour cent|points?|pts)",
                                         _f(s), re.I):
            return None
        txt = first
        ind = 0
        num, crit_n, lettre, puce = None, False, False, False
    src = rest if rest is not None else txt
    poids = _poids(src)
    if not m and rest is not None and poids is None:
        return None
    lib = _libelle(txt)
    if not lib:
        return None
    # Un sous-critère : lettre, numéro à point (1.1), ou puce indentée sous son critère.
    # Un numéro simple (1., 2.) reste un critère, indenté ou non.
    sub = not crit_n and (lettre or (num is not None and "." in num) or (puce and ind > 0))
    rang = int(num) if (num is not None and "." not in num) else None
    return {"lib": lib, "sub": sub, "poids": poids, "rang": rang}


def _phase(s):
    if re.match(r"\s*[-•*]", s):
        return None
    fs = _f(s).lower()
    if not re.search(r"piece|au titre|produira|attributaire|candidature|offre", fs):
        return None
    if "attributaire" in fs or "auquel il est envisage d'attribuer" in fs:
        return "attributaire" if re.search(r"piece|produira|fournir|produire|auquel", fs) else None
    if "candidature" in fs and (re.search(r"piece|au titre|:\s*$", fs) or re.match(r"\s*\d", fs)):
        return "candidature"
    if "offre" in fs and re.search(r"piece|au titre", fs):
        return "offre"
    return None


def _nom_piece(s):
    t = re.sub(r"^\s*[-•*]\s*", "", s).strip()
    t = re.sub(r"\s*\([^()]*(?:obligatoire|facultati)[^()]*\)", "", t, flags=re.I)
    t = re.sub(r",?\s*(?:à|a) titre facultatif", "", t, flags=re.I)
    return t.strip().rstrip(" ;.,").strip()


def _obligation(s):
    fs = _f(s).lower()
    if re.search(r"facultati|non obligatoire", fs):
        return "non obligatoire"
    if re.search(r"obligatoire", fs):
        return "obligatoire"
    return None


def _faitp(ponds):
    """ponds : (valeur, unité, lot, page). conflit seulement si deux valeurs partagent un lot."""
    groupes = {}
    for v, u, lot, p in ponds:
        k = json.dumps([v, u, lot], ensure_ascii=False)
        g = groupes.setdefault(k, {"valeur": v, "unite": u, "lot": lot, "pages": set()})
        g["pages"].add(p)
    valeurs = [{"valeur": g["valeur"], "unite": g["unite"], "lot": g["lot"], "pages": sorted(g["pages"])}
               for g in groupes.values()]
    if not valeurs:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    par_lot = {}
    for x in valeurs:
        par_lot.setdefault(x["lot"], set()).add(x["valeur"])
    conflit = any(len(v) > 1 for v in par_lot.values())
    return {"statut": TROUVE, "valeurs": valeurs, "conflit": conflit}


def _lot_crit(occ_lot, blocs, uniq, numerotes):
    if uniq and not numerotes:
        return _fait([(None, p) for p in uniq])
    if not blocs or any(l is None for l, _ in occ_lot):
        return _fait([("tous les lots", p) for _, p in occ_lot])
    if {l for l, _ in occ_lot} == set(blocs):
        return _fait([("tous les lots", p) for _, p in occ_lot])
    return _fait(list(occ_lot))


def _passe(pages):
    lots_num = {}
    unique = []
    blocs = set()
    tops = {}
    ordre = []
    pieces = {}
    ctx, bloc, phase, parent = False, None, None, None

    def lot_add(n, inti, p):
        e = lots_num.setdefault(n, {"pages": set(), "intitules": []})
        e["pages"].add(p)
        if inti:
            e["intitules"].append((inti, p))

    for p, page in enumerate(pages, 1):
        for l in _norm(page).split("\n"):
            s = l.strip()
            if not s:
                continue
            brut = l.rstrip()  # garde l'indentation : elle distingue sous-critères et critères
            fs = _f(s)
            if _ARTICLE.match(s):
                ctx = bool(_CTX_OUVRE.search(fs))
                bloc, phase, parent = None, None, None
            elif _CTX_OUVRE.search(fs):
                ctx = True
            m = _LOT_BLOC.match(s)
            if m:
                bloc = int(m.group(1))
                blocs.add(bloc)
                ctx = True
                lot_add(bloc, None, p)
                continue
            m = _LOT_LIGNE.match(s)
            if m:
                lot_add(int(m.group(1)), (m.group(2) or "").strip().rstrip(" ;.,") or None, p)
                continue
            if _LOT_UNIQUE.search(fs):
                unique.append(p)
            ph = _phase(s)
            if ph:
                phase = ph
                continue
            if ctx:
                it = _item(brut)
                if it is not None:
                    if it["sub"]:
                        if parent is not None:
                            e = tops[parent]["subs"].setdefault(
                                _cle(it["lib"]), {"lib": it["lib"], "pages": set(), "occ": []})
                            e["pages"].add(p)
                            e["occ"].append({"poids": it["poids"], "lot": bloc, "page": p})
                    else:
                        k = _cle(it["lib"])
                        e = tops.setdefault(k, {"lib": it["lib"], "pages": set(), "occ": [], "subs": {}})
                        if k not in ordre:
                            ordre.append(k)
                        e["pages"].add(p)
                        e["occ"].append({"poids": it["poids"], "rang": it["rang"], "lot": bloc, "page": p})
                        parent = k
                    continue
            elif re.match(r"\s*[-•*]", s):
                nom = _nom_piece(s)
                if nom:
                    e = pieces.setdefault(_cle(nom), {"nom": nom, "pages": set(), "phase": [], "oblig": []})
                    e["pages"].add(p)
                    if phase:
                        e["phase"].append((phase, p))
                    o = _obligation(s)
                    if o:
                        e["oblig"].append((o, p))

    lots = []
    for n in sorted(lots_num):
        e = lots_num[n]
        inti = _fait(e["intitules"])
        lots.append({"numero": n, "intitules": inti["valeurs"], "pages": sorted(e["pages"]),
                     "conflit": len(inti["valeurs"]) > 1})
    if not lots and unique:
        lots = [{"numero": None, "intitules": [], "pages": sorted(set(unique)), "conflit": False}]
    lots_f = {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}
    numerotes = bool(lots_num)

    unites = [(o["poids"][1], o["page"]) for k in ordre for o in tops[k]["occ"] if o["poids"]]
    if unites:
        tp = _fait(unites)
    else:
        rangs = [("classement", o["page"]) for k in ordre for o in tops[k]["occ"] if o["rang"] is not None]
        tp = _fait(rangs)
    classement = bool(tp["valeurs"]) and tp["valeurs"][0]["valeur"] == "classement"

    crits = []
    for k in ordre:
        e = tops[k]
        ponds = []
        for o in e["occ"]:
            if o["poids"]:
                ponds.append((o["poids"][0], o["poids"][1], o["lot"], o["page"]))
            elif classement and o["rang"] is not None:
                ponds.append((o["rang"], "rang", o["lot"], o["page"]))
        occ_lot = [(o["lot"], o["page"]) for o in e["occ"]]
        subs = []
        for se in e["subs"].values():
            subs.append({"libelle": se["lib"], "pages": sorted(se["pages"]),
                         "ponderation": _faitp([(o["poids"][0], o["poids"][1], o["lot"], o["page"])
                                                for o in se["occ"] if o["poids"]])})
        crits.append({"libelle": e["lib"], "pages": sorted(e["pages"]),
                      "lot": _lot_crit(occ_lot, blocs, sorted(set(unique)), numerotes),
                      "ponderation": _faitp(ponds),
                      "sous_criteres": subs})
    criteres_f = {"statut": TROUVE if crits else NON_TROUVE, "liste": crits}

    liste_p = []
    for e in pieces.values():
        liste_p.append({"nom": e["nom"], "pages": sorted(e["pages"]),
                        "phase": _fait(e["phase"], conflit=False),
                        "obligation": _fait(e["oblig"])})
    pieces_f = {"statut": TROUVE if liste_p else NON_TROUVE, "liste": liste_p}
    return {"lots": lots_f, "criteres": criteres_f, "type_ponderation": tp, "pieces": pieces_f}


# ------------------------------------------------------------ plan, contrôle, vérification, entrée

_FAITS_SIMPLES = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                  "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
                  "type_ponderation"]


def _vk(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _technique(lib):
    return re.search(r"technique|qualite", _f(lib), re.I) is not None


def _unique(fp):
    v = fp["valeurs"]
    return v[0]["valeur"] if len(v) == 1 else None


def _plan(criteres):
    plan = []
    for c in criteres:
        if not _technique(c["libelle"]):
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                plan.append({"titre": c["libelle"] + " – " + s["libelle"], "critere": c["libelle"],
                             "sous_critere": s["libelle"], "ponderation": _unique(s["ponderation"]),
                             "page_source": s["pages"][0], "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": _unique(c["ponderation"]), "page_source": c["pages"][0],
                         "contenu": ""})
    return plan


def controler(dossier):
    plan = dossier.get("plan", [])
    criteres = dossier["criteres"]["liste"]
    alertes = []
    for c in criteres:
        if _technique(c["libelle"]) and not any(s["critere"] == c["libelle"] for s in plan):
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in criteres:
        pv = _unique(c["ponderation"])
        subs = [x for x in (_unique(s["ponderation"]) for s in c["sous_criteres"]) if x is not None]
        if pv is not None and subs and abs(sum(subs) - pv) > 1e-9:
            alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    tp = dossier["type_ponderation"]
    if any(v["valeur"] == "pourcentage" for v in tp["valeurs"]):
        totaux = {}
        for c in criteres:
            for v in c["ponderation"]["valeurs"]:
                if v["unite"] == "pourcentage":
                    totaux[v["lot"]] = totaux.get(v["lot"], 0) + v["valeur"]
        if any(abs(round(t, 6) - 100) > 1e-9 for t in totaux.values()):
            alertes.append({"type": "total différent de 100 %", "objet": "critères"})
    return alertes


def _extraire(pages):
    d = _faits_simples(pages)
    st = _passe(pages)
    d.update(st)
    d["plan"] = _plan(d["criteres"]["liste"])
    d["controle"] = {"alertes": controler(d)}
    return d


def _filtre_fait(fait, ref):
    """Garde les valeurs proposées que l'extraction retrouve dans le texte ; pages de la référence."""
    if ref["statut"] != TROUVE:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    refs = {_vk(x["valeur"]): x["pages"] for x in ref["valeurs"]}
    occ = []
    vus = set()
    for x in fait.get("valeurs", []):
        k = _vk(x["valeur"])
        if k in refs and k not in vus:
            vus.add(k)
            occ += [(x["valeur"], p) for p in refs[k]]
    if not occ:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    out = _fait(occ, conflit=ref["conflit"])
    return out


def _filtre_p(fp, ref):
    if ref["statut"] != TROUVE:
        return {"statut": NON_TROUVE, "valeurs": [], "conflit": False}
    refs = {_vk([x["valeur"], x["unite"], x["lot"]]): x["pages"] for x in ref["valeurs"]}
    ponds = []
    vus = set()
    for x in fp.get("valeurs", []):
        k = _vk([x["valeur"], x["unite"], x["lot"]])
        if k in refs and k not in vus:
            vus.add(k)
            ponds += [(x["valeur"], x["unite"], x["lot"], p) for p in refs[k]]
    return _faitp(ponds)


def _filtre_lots(liste, ref_liste):
    refs = {_vk(r["numero"]): r for r in ref_liste}
    out = []
    for x in liste:
        r = refs.get(_vk(x["numero"]))
        if r is None:
            continue
        inti = [v for v in r["intitules"]
                if any(_vk(v["valeur"]) == _vk(i["valeur"]) for i in x["intitules"])]
        out.append({"numero": r["numero"], "intitules": inti, "pages": r["pages"],
                    "conflit": len(inti) > 1 and r["conflit"]})
    return out


def _filtre_pieces(liste, ref_liste):
    refs = {_cle(r["nom"]): r for r in ref_liste}
    out = []
    for x in liste:
        r = refs.get(_cle(x["nom"]))
        if r is None:
            continue
        out.append({"nom": r["nom"], "pages": r["pages"],
                    "phase": _filtre_fait(x["phase"], r["phase"]),
                    "obligation": _filtre_fait(x["obligation"], r["obligation"])})
    return out


def _filtre_criteres(liste, ref_liste):
    refs = {_cle(r["libelle"]): r for r in ref_liste}
    out = []
    for x in liste:
        r = refs.get(_cle(x["libelle"]))
        if r is None:
            continue
        subs_ref = {_cle(s["libelle"]): s for s in r["sous_criteres"]}
        subs, vus = [], set()
        for s in x["sous_criteres"]:
            rs = subs_ref.get(_cle(s["libelle"]))
            if rs is None or _cle(rs["libelle"]) in vus:
                continue
            vus.add(_cle(rs["libelle"]))
            subs.append({"libelle": rs["libelle"], "pages": rs["pages"],
                         "ponderation": _filtre_p(s["ponderation"], rs["ponderation"])})
        out.append({"libelle": r["libelle"], "pages": r["pages"],
                    "lot": _filtre_fait(x["lot"], r["lot"]),
                    "ponderation": _filtre_p(x["ponderation"], r["ponderation"]),
                    "sous_criteres": subs})
    return out


def verifier(dossier, pages):
    """Copie du dossier où toute valeur non retrouvée dans les pages est retirée ; plan et contrôle recalculés."""
    pages = [p if isinstance(p, str) else "" for p in pages]
    ref = _extraire(pages)
    out = copy.deepcopy(dossier)
    for cle in _FAITS_SIMPLES:
        out[cle] = _filtre_fait(dossier[cle], ref[cle])
    lots = _filtre_lots(dossier["lots"]["liste"], ref["lots"]["liste"])
    out["lots"] = {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}
    pcs = _filtre_pieces(dossier["pieces"]["liste"], ref["pieces"]["liste"])
    out["pieces"] = {"statut": TROUVE if pcs else NON_TROUVE, "liste": pcs}
    crs = _filtre_criteres(dossier["criteres"]["liste"], ref["criteres"]["liste"])
    out["criteres"] = {"statut": TROUVE if crs else NON_TROUVE, "liste": crs}
    out["plan"] = _plan(crs)
    out["controle"] = {"alertes": controler(out)}
    return out


def analyser(pages):
    """Point d'entrée unique : dossier sérialisable du règlement de consultation (pages[0] = page 1)."""
    pages = [p if isinstance(p, str) else "" for p in pages]
    return _extraire(pages)
