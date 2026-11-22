"""Lecture déterministe d'un règlement de la consultation (RC)."""

import re
import unicodedata

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
_MOIS_RX = r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre"


def _noacc(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def nettoyer(t):
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("­", "")
    for c in "      ":
        t = t.replace(c, " ")
    return t.replace("\t", "    ")


def cle(s):
    s = s.replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s.strip(" ;.,:")


# ------------------------------------------------------------------ nombres

_UN = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
       "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13,
       "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30,
       "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100, "cents": 100}
_NW = (r"(?:z[ée]ro|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|"
       r"quinze|seize|vingts?|trente|quarante|cinquante|soixante|cents?)")
NUMW = rf"\b{_NW}(?:(?:-|\s+)(?:et(?:-|\s+))?{_NW})*\b"


def fr_nombre(s):
    toks = [t for t in re.split(r"[-\s]+", _noacc(s.lower())) if t and t != "et"]
    cur = 0
    prev = None
    for t in toks:
        v = _UN[t]
        if v == 100:
            cur = (cur or 1) * 100
        elif v == 20 and prev == "quatre":
            cur += 76
        else:
            cur += v
        prev = t
    return cur


def en_nombre(s):
    s = s.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", s):
        x = float(s.replace(",", "."))
        return int(x) if x == int(x) else x
    return fr_nombre(s)


# ------------------------------------------------------------------ faits

def fait(entrees, conflit_multiple=True):
    vals = []
    for v, p in entrees:
        for e in vals:
            if e["valeur"] == v:
                if p not in e["pages"]:
                    e["pages"].append(p)
                break
        else:
            vals.append({"valeur": v, "pages": [p]})
    for e in vals:
        e["pages"].sort()
    return {"statut": TROUVE if vals else NON_TROUVE, "valeurs": vals,
            "conflit": bool(conflit_multiple and len(vals) > 1)}


# ------------------------------------------------------------------ segments

def segments(texte, fusion_titres=False):
    lignes = [l.strip() for l in texte.split("\n")]
    out = []
    n = len(lignes)
    i = 0
    while i < n:
        acc = lignes[i]
        if not acc:
            i += 1
            continue
        while i + 1 < n and lignes[i + 1]:
            nxt = lignes[i + 1]
            maj = acc == acc.upper() and any(c.isalpha() for c in acc)
            cesure = (not re.search(r"[.:;!?)]$", acc)) and nxt[0].islower() \
                and re.search(r"[a-zà-ÿ]$", acc)
            if (fusion_titres and maj) or cesure:
                acc += " " + nxt
                i += 1
            else:
                break
        out.append(acc)
        i += 1
    res = []
    for s in out:
        res.extend(x for x in re.split(
            r"(?:(?<=[a-zà-ÿ)]\.)|(?<=\d\d\.)|(?<=[!?]))\s+(?=\S)", s) if x.strip())
    return res


def segs_pages(pages, fusion=False):
    return [(n, s) for n, t in enumerate(pages, 1) for s in segments(t, fusion)]


RX_AUTRE = re.compile(r"\b(?:avis|publication|signature|accueil)\b", re.I)
RX_QUEST = re.compile(r"question|renseignements?\s+compl[ée]mentaires?|demandes?\s+de\s+renseignements?", re.I)
RX_VISITE = re.compile(r"visite", re.I)
RX_LIMITE = re.compile(r"\boffres?\b|\bplis\b|remise|r[ée]ception|parvenir|d[ée]pos[ée]|\blimites?\b", re.I)


def categorie(seg):
    if RX_AUTRE.search(seg):
        return "autre"
    if RX_QUEST.search(seg):
        return "question"
    if RX_VISITE.search(seg):
        return "visite"
    if RX_LIMITE.search(seg):
        return "limite"
    return None


def segments_classes(pages):
    res = []
    for n, t in enumerate(pages, 1):
        prev = None
        for s in segments(t, True):
            c = categorie(s)
            if c is None and prev == "visite":
                c = "visite"
            res.append((n, s, c))
            prev = c
    return res


# ------------------------------------------------------------------ dates / heures

RX_DATE = re.compile(
    rf"(?<![\d/.\-])(?:(\d{{1,2}})[/.\-](\d{{1,2}})[/.\-](\d{{4}}|\d{{2}})(?!\d)"
    rf"|(\d{{1,2}})(?:er)?\s+({_MOIS_RX})\s+(\d{{4}}))", re.I)


def dates_dans(seg):
    out = []
    for m in RX_DATE.finditer(seg):
        if m.group(1):
            j, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if a < 100:
                a += 2000
        else:
            j, mo, a = int(m.group(4)), MOIS[_noacc(m.group(5).lower())], int(m.group(6))
        if 1 <= j <= 31 and 1 <= mo <= 12:
            out.append(f"{j:02d}/{mo:02d}/{a}")
    return out


RX_HEURE = re.compile(r"(?<![\d/.,:\-])(\d{1,2})(?:\s*(?:h(?![a-zà-ÿ])|heures?\b)\s*(\d{2})?|:(\d{2}))(?!\d)", re.I)
RX_HEURE_MOTS = re.compile(rf"(?P<h>{NUMW})\s+heures?\b(?:\s+(?P<m>{NUMW}|\d{{2}}))?", re.I)
RX_MIDI = re.compile(r"\bmidi\b", re.I)


def heures_dans(seg):
    trouves = []
    for m in RX_HEURE.finditer(seg):
        h = int(m.group(1))
        mg = m.group(2) or m.group(3)
        mi = int(mg) if mg else 0
        trouves.append((m.start(), h, mi))
    for m in RX_HEURE_MOTS.finditer(seg):
        h = fr_nombre(m.group("h"))
        mi = 0
        if m.group("m"):
            mi = int(m.group("m")) if m.group("m").isdigit() else fr_nombre(m.group("m"))
        trouves.append((m.start(), h, mi))
    for m in RX_MIDI.finditer(seg):
        trouves.append((m.start(), 12, 0))
    trouves.sort()
    return [f"{h:02d}:{mi:02d}" for _, h, mi in trouves if 0 <= h <= 23 and 0 <= mi <= 59]


RX_DELAI = re.compile(
    rf"(?<!\w)(?:\d+|{NUMW})(?:\s*\(\s*\d+\s*\))?\s+jours?(?:\s+calendaires)?\s+avant\s+la\s+date\s+limite"
    r"(?:\s+de\s+(?:remise|r[ée]ception|d[ée]p[ôo]t)\s+des\s+(?:offres|plis))?", re.I)


def ex_dates(pages):
    dl, q, vis, hl = [], [], [], []
    for n, s, c in segments_classes(pages):
        if c == "limite":
            dl += [(d, n) for d in dates_dans(s)]
            hl += [(h, n) for h in heures_dans(s)]
        elif c == "question":
            ds = dates_dans(s)
            q += [(d, n) for d in ds]
            if not ds:
                m = RX_DELAI.search(s)
                if m:
                    q.append((m.group(0), n))
        elif c == "visite":
            vis += [(d, n) for d in dates_dans(s)]
    return dl, hl, q, vis


# ------------------------------------------------------------------ procédure

RX_PROC = [
    (re.compile(r"proc[ée]dure\s+adapt[ée]e", re.I), lambda m: "procédure adaptée"),
    (re.compile(r"(?<![\w-])MAPA(?![\w-])", re.I), lambda m: "procédure adaptée"),
    (re.compile(r"appel\s+d['’]offres\s+(ouvert|restreint)", re.I),
     lambda m: "appel d'offres " + m.group(1).lower()),
    (re.compile(r"dialogue\s+comp[ée]titif", re.I), lambda m: "dialogue compétitif"),
    (re.compile(r"proc[ée]dure\s+n[ée]goci[ée]e", re.I), lambda m: "procédure négociée"),
]


def ex_procedure(pages):
    out = []
    for n, t in enumerate(pages, 1):
        T = re.sub(r"\s+", " ", t)
        trouves = []
        for rx, f in RX_PROC:
            for m in rx.finditer(T):
                trouves.append((m.start(), f(m)))
        trouves.sort()
        out += [(v, n) for _, v in trouves]
    return out


# ------------------------------------------------------------------ faits par segment

RX_NONOBL = re.compile(r"facultati|non\s*-?\s*obligatoire|pas\s+obligatoire|n['’]est\s+pas\s+(?:exig|requis)", re.I)


def ex_visite(sp):
    out = []
    for n, s in sp:
        if RX_VISITE.search(s):
            if RX_NONOBL.search(s):
                out.append(("non", n))
            elif re.search(r"obligatoire", s, re.I):
                out.append(("oui", n))
    return out


RX_VAR_NON = re.compile(r"non\s+autoris|interdit|pas\s+(?:autoris|admis|accept)|n['’]est\s+(?:pas\s+)?admis|"
                        r"aucune\s+variante|ne\s+sont\s+pas|ne\s+seront\s+pas|n['’]est\s+pas", re.I)
RX_VAR_OUI = re.compile(r"autoris|admis|accept|peuvent\s+pr[ée]senter|possible", re.I)


def ex_variantes(sp):
    out = []
    for n, s in sp:
        if re.search(r"\bvariantes?\b", s, re.I):
            if RX_VAR_NON.search(s):
                out.append(("non autorisées", n))
            elif RX_VAR_OUI.search(s):
                out.append(("autorisées", n))
    return out


RX_VALID = re.compile(r"validit[ée]\s+des\s+offres|offres?\s+(?:restent?|reste|demeurent?|sont)\s+valables?|"
                      r"valabilit[ée]\s+des\s+offres|offres?\s+valables?", re.I)
RX_DUREE = re.compile(rf"(?P<n>\d+|{NUMW})\s*(?:\(\s*(?P<p>\d+)\s*\))?\s*(?P<u>jours?|mois)\b", re.I)


def ex_validite(sp):
    out = []
    for n, s in sp:
        t = RX_VALID.search(s)
        if not t:
            continue
        m = RX_DUREE.search(s, t.end())
        if m:
            nb = int(m.group("p")) if m.group("p") else en_nombre(m.group("n"))
            out.append(({"nombre": nb, "unite": "mois" if m.group("u").lower() == "mois" else "jours"}, n))
    return out


RX_OFFRE = re.compile(r"\boffres?\b|\bplis?\b|\bremise\b|\btransmi\w*|\bd[ée]pos\w*|\btransmission\b", re.I)
RX_ELEC = re.compile(r"[ée]lectronique|d[ée]mat[ée]rialis|plateforme|profil\s+d['’]acheteur|en\s+ligne", re.I)
RX_PAPIER = re.compile(r"papier|pli\s+cachet[ée]|sous\s+pli", re.I)
RX_NEG = re.compile(r"\bn['’]est\s+pas|\bne\s+(?:sera|seront|sont)\s+pas|\baucune?\b|\binterdit|\brefus|"
                    r"\bn['’]est\s+admis|\bpas\s+(?:autoris|admis|accept)", re.I)


def ex_mode(sp):
    out = []
    for n, s in sp:
        if RX_QUEST.search(s) or re.search(r"\bDCE\b|dossier\s+de\s+consultation", s, re.I):
            continue
        if not RX_OFFRE.search(s):
            continue
        if RX_ELEC.search(s):
            out.append(("électronique", n))
        if RX_PAPIER.search(s) and not RX_NEG.search(s):
            out.append(("papier", n))
    return out


RX_PAGES = re.compile(rf"(?P<n>\d+|{NUMW})\s*(?:\(\s*(?P<p>\d+)\s*\))?\s*pages?\b", re.I)


def ex_limite_pages(sp):
    out = []
    for n, s in sp:
        if re.search(r"m[ée]moire\s+technique", s, re.I):
            for m in RX_PAGES.finditer(s):
                out.append((int(m.group("p")) if m.group("p") else en_nombre(m.group("n")), n))
    return out


# ------------------------------------------------------------------ pièces

RX_FOOTER = re.compile(r"^(?:RC\s*[–-]\s*\d+\s*/\s*\d+|Page\s+\d+(?:\s*(?:sur|/)\s*\d+)?)$", re.I)
RX_BULLET = re.compile(r"^[-•*–·]\s+(.*\S)\s*$")
RX_P_TRIG = re.compile(r"pi[èe]ces?\b|documents?\s+suivants?|dossier\s+[àa]\s+remettre|"
                       r"contenu\s+(?:du|des)\s+(?:dossier|plis)|remett(?:ent|ra|ront|re)\b|"
                       r"produira|produire|fournir|fourniront", re.I)
RX_AU_TITRE = re.compile(r"^(?:\d+[.)]\s*)?au\s+titre\s+d", re.I)
RX_FAC = re.compile(r"facultati|non\s+obligatoire", re.I)
RX_QUAL = re.compile(r"\s*\(\s*(?:facultati\w*|obligatoires?)\s*\)|\s*,?\s*[àa]\s+titre\s+facultatif", re.I)


def _phase_ligne(s):
    ph = set()
    if re.search(r"attributaire|envisag[ée]\s+d['’]attribuer", s, re.I):
        ph.add("attributaire")
    if re.search(r"candidatures?\b", s, re.I):
        ph.add("candidature")
    if re.search(r"\boffres?\b", s, re.I):
        ph.add("offre")
    return ph.pop() if len(ph) == 1 else None


def ex_pieces(pages):
    items = []
    actif = False
    phase = None
    for n, t in enumerate(pages, 1):
        for ligne in t.split("\n"):
            s = ligne.strip()
            if not s or RX_FOOTER.match(s):
                continue
            b = RX_BULLET.match(s)
            if b:
                if actif:
                    txt = b.group(1)
                    if RX_FAC.search(txt):
                        obl = "non obligatoire"
                    elif re.search(r"obligatoire", txt, re.I):
                        obl = "obligatoire"
                    else:
                        obl = None
                    nom = RX_QUAL.sub("", txt)
                    nom = re.sub(r"\s+", " ", nom).strip(" \t;.,")
                    if re.search(r"[A-Za-zÀ-ÿ]", nom):
                        items.append((nom, n, phase, obl))
                continue
            if RX_P_TRIG.search(s) or RX_AU_TITRE.match(s):
                actif = True
                phase = _phase_ligne(s)
            else:
                actif = False
                phase = None
    ordre = []
    par_cle = {}
    for nom, n, phase, obl in items:
        k = cle(nom)
        if k not in par_cle:
            par_cle[k] = {"nom": nom, "pages": set(), "ph": [], "ob": []}
            ordre.append(k)
        e = par_cle[k]
        e["pages"].add(n)
        if phase:
            e["ph"].append((phase, n))
        if obl:
            e["ob"].append((obl, n))
    liste = [{"nom": par_cle[k]["nom"], "pages": sorted(par_cle[k]["pages"]),
              "phase": fait(par_cle[k]["ph"], False), "obligation": fait(par_cle[k]["ob"])}
             for k in ordre]
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ------------------------------------------------------------------ lots

RX_LOT = re.compile(r"^(?:[-•*–·]\s*)?lot\s+(?:n\s*°\s*|n\s*o\s*\.?\s*|num[ée]ro\s+)?0*(\d+)\s*(?:[:\-–—]\s*|\s+)(\S.*)$", re.I)
RX_UNIQUE = re.compile(
    r"\blot\s+unique|\bun\s+seul\s+lot|(?:n['’]est|n['’]étant)\s+pas\s+alloti|\bnon\s+alloti|"
    r"pas\s+(?:pr[ée]vu\w*\s+)?de\s+d[ée]composition\s+en\s+lots?|l['’]allotissement\s+n['’]\w+\s+pas", re.I)


def ex_lots(pages):
    lots = {}
    ordre = []
    uniques = set()
    for n, t in enumerate(pages, 1):
        for ligne in t.split("\n"):
            s = ligne.strip()
            m = RX_LOT.match(s)
            if m:
                titre = re.sub(r"^[:\-–—\s]+", "", m.group(2))
                titre = re.sub(r"\s+", " ", titre).strip(" \t;.,")
                if not re.search(r"[A-Za-zÀ-ÿ]", titre):
                    continue
                num = int(m.group(1))
                if num not in lots:
                    lots[num] = {"pages": set(), "tit": []}
                    ordre.append(num)
                lots[num]["pages"].add(n)
                lots[num]["tit"].append((titre, n))
        for s in segments(t):
            if RX_UNIQUE.search(s):
                uniques.add(n)
    liste = []
    if ordre:
        for num in ordre:
            ent = []
            par = {}
            for titre, n in lots[num]["tit"]:
                k = cle(titre)
                if k not in par:
                    par[k] = {"valeur": titre, "pages": set()}
                    ent.append(k)
                par[k]["pages"].add(n)
            intit = [{"valeur": par[k]["valeur"], "pages": sorted(par[k]["pages"])} for k in ent]
            liste.append({"numero": num, "intitules": intit, "pages": sorted(lots[num]["pages"]),
                          "conflit": len(intit) > 1})
    elif uniques:
        liste.append({"numero": None, "intitules": [], "pages": sorted(uniques), "conflit": False})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ------------------------------------------------------------------ critères

RX_CWORD = re.compile(r"crit[èe]res?\b", re.I)
RX_CRIT_LINE = re.compile(r"^crit[èe]re\s*(?:n\s*°\s*|n\s*o\s*|num[ée]ro\s*)?\d+\s*[:.\-–—]*\s*(.*)$", re.I)
RX_NUM_SUB = re.compile(r"^\d+\.\d+(?:\.\d+)*[.)]?\s+(.*)$")
RX_NUM_TOP = re.compile(r"^\d+[.)]\s+(.*)$")
RX_LET = re.compile(r"^[a-zA-Z][.)]\s+(.*)$")
RX_HDR_ROW = re.compile(r"^crit[èe]res?\s*\|", re.I)
RX_POIDS = re.compile(rf"(?P<n>\d+(?:[.,]\d+)?|{NUMW})\s*(?P<u>%|pour\s*cent\b|points?\b|pts?\b)", re.I)
HEADCLEAN = re.compile(r"[\s:|(\[\-–—]*(?:pond[ée]ration|not[ée]e?\s+sur|sur|coefficient)?[\s:|(\[\-–—]*$", re.I)
RX_LOT_HDR = re.compile(r"^(?:pour\s+(?:le|les)\s+)?lot\s+(?:n\s*°\s*)?0*(\d+)\s*:?\s*$", re.I)
RX_DETAIL1 = re.compile(r"d[ée]tail(?:l[ée])?\s+du\s+crit[èe]re\s+(.+?)\s*:?\s*$", re.I)
RX_DETAIL2 = re.compile(r"crit[èe]re\s+(.+?)\s+(?:est|sera)\s+(?:d[ée]compos|d[ée]taill)", re.I)
RX_RANG = re.compile(r"class[ée]s?\s+par\s+ordre|ordre\s+(?:d[ée]croissant\s+)?d['’]importance|"
                     r"class[ée]s?\s+selon\s+l['’]ordre", re.I)


def parse_item(texte):
    m = RX_POIDS.search(texte)
    if m:
        head = HEADCLEAN.sub("", texte[:m.start()])
        u = "pourcentage" if m.group("u").lower().replace(" ", "").startswith(("%", "pourcent")) else "points"
        poids = (en_nombre(m.group("n")), u)
    else:
        head = re.split(r"[:|]", texte)[0]
        poids = None
    label = re.sub(r"\s+", " ", head).strip(" \t;.,:|-–—")
    return label, poids


def _est_titre(s):
    return bool(re.match(r"^(?:article|annexe|chapitre|titre|section)\b", s, re.I)) or \
        (s.upper() == s and any(c.isalpha() for c in s))


def _trouver_top(tops, nom):
    k = cle(nom)
    cles = [o["cle"] for o in tops]
    if k in cles:
        return k
    for c in cles:
        if c in k or k in c:
            return c
    return None


def ex_criteres_brut(pages):
    tops, subs = [], []
    actif = False
    last_top = None
    top_indent = 0
    lot = None
    rang = 0
    override = None
    for n, t in enumerate(pages, 1):
        for ligne in t.split("\n"):
            s = ligne.strip()
            if not s or RX_FOOTER.match(s):
                continue
            indent = len(ligne) - len(ligne.lstrip())
            kind = None
            rest = None
            mc = RX_CRIT_LINE.match(s)
            if mc:
                kind, rest = "top", mc.group(1)
                actif = True
                override = None
            else:
                b = RX_BULLET.match(s)
                if b:
                    kind, rest = "dash", b.group(1)
                else:
                    for rx, k in ((RX_NUM_SUB, "sub"), (RX_NUM_TOP, "top"), (RX_LET, "sub")):
                        mm = rx.match(s)
                        if mm:
                            kind, rest = k, mm.group(1)
                            break
                    if kind is None and "|" in s and not RX_HDR_ROW.match(s):
                        kind, rest = "row", s
            if kind is None:
                if RX_LOT_HDR.match(s):
                    if actif:
                        lot = int(RX_LOT_HDR.match(s).group(1))
                        last_top = None
                        rang = 0
                    continue
                d = RX_DETAIL1.search(s) or RX_DETAIL2.search(s)
                if d:
                    override = cle(d.group(1))
                    actif = True
                    continue
                if actif and re.match(r"^(?:ce\s+crit[èe]re|sous-crit)", s, re.I):
                    continue
                trig = (RX_CWORD.search(s) or re.search(r"not[ée]e?s?\s+sur|pond[ée]r", s, re.I)) and (
                    s.endswith(":") or re.search(r"suivants|ci-dessous", s, re.I)
                    or RX_HDR_ROW.match(s) or (not s.endswith(".") and len(s) < 90))
                if trig:
                    actif = True
                    last_top = None
                    lot = None
                    rang = 0
                    override = None
                elif RX_P_TRIG.search(s) or _est_titre(s) or \
                        (s.endswith(":") and not re.search(r"crit|\blots?\b|pond", s, re.I)):
                    actif = False
                    override = None
                continue
            label, poids = parse_item(rest)
            if not actif and kind in ("top", "sub") and poids and label \
                    and _trouver_top(tops, label):
                actif = True
                last_top = None
            if not actif:
                continue
            if not label or not re.search(r"[A-Za-zÀ-ÿ]", label) or RX_CWORD.match(label):
                continue
            if override:
                parent = _trouver_top(tops, override)
                if parent is None:
                    continue
                subs.append({"parent": parent, "cle": cle(label), "label": label, "page": n,
                             "poids": poids, "lot": lot})
                continue
            if kind == "top":
                niveau = "top"
            elif kind == "sub":
                niveau = "sub" if last_top else "top"
            else:
                niveau = "top" if (last_top is None or indent <= top_indent) else "sub"
            if niveau == "top":
                rang += 1
                tops.append({"cle": cle(label), "label": label, "page": n, "poids": poids,
                             "lot": lot, "rang": rang})
                last_top = cle(label)
                top_indent = indent
            else:
                subs.append({"parent": last_top, "cle": cle(label), "label": label, "page": n,
                             "poids": poids, "lot": lot})
    return tops, subs


def fait_p(entrees):
    vals = []
    for v, u, l, p in entrees:
        for e in vals:
            if (e["valeur"], e["unite"], e["lot"]) == (v, u, l):
                if p not in e["pages"]:
                    e["pages"].append(p)
                break
        else:
            vals.append({"valeur": v, "unite": u, "lot": l, "pages": [p]})
    for e in vals:
        e["pages"].sort()
    return {"statut": TROUVE if vals else NON_TROUVE, "valeurs": vals, "conflit": conflit_p(vals)}


def conflit_p(vals):
    for i, a in enumerate(vals):
        for b in vals[i + 1:]:
            if a["lot"] == b["lot"] and (a["valeur"], a["unite"]) != (b["valeur"], b["unite"]):
                return True
    return False


def ex_criteres(pages, lots):
    tops, subs = ex_criteres_brut(pages)
    ordre = []
    par = {}
    for o in tops:
        if o["cle"] not in par:
            par[o["cle"]] = {"libelle": o["label"], "occ": []}
            ordre.append(o["cle"])
        par[o["cle"]]["occ"].append(o)
    pondere = any(o["poids"] for o in tops)
    classement = False
    if tops and not pondere:
        texte = " ".join(re.sub(r"\s+", " ", p) for p in pages)
        classement = bool(RX_RANG.search(texte))
    if pondere:
        te = [(o["poids"][1], o["page"]) for o in tops if o["poids"]]
    elif classement:
        te = [("classement", o["page"]) for o in tops]
    else:
        te = []
    type_pond = fait(te)

    connus = [l["numero"] for l in lots["liste"] if l["numero"] is not None]
    tous_lots = set()
    for o in tops:
        if o["poids"] and o["lot"] is not None:
            tous_lots.add(o["lot"])
    ref = set(connus) or tous_lots

    liste = []
    for k in ordre:
        e = par[k]
        pages_c = sorted({o["page"] for o in e["occ"]})
        ent = []
        cl = set()
        for o in e["occ"]:
            if o["poids"]:
                ent.append((o["poids"][0], o["poids"][1], o["lot"], o["page"]))
                if o["lot"] is not None:
                    cl.add(o["lot"])
            elif classement:
                ent.append((o["rang"], "rang", o["lot"], o["page"]))
        if len(lots["liste"]) == 1:
            valeurs_lot = [lots["liste"][0]["numero"]]
        elif cl and cl < ref:
            valeurs_lot = sorted(cl)
        else:
            valeurs_lot = ["tous les lots"]
        lot_fait = fait([(v, p) for v in valeurs_lot for p in pages_c], False)
        ss = []
        ordre_s = []
        pars = {}
        for so in subs:
            if so["parent"] != k:
                continue
            if so["cle"] not in pars:
                pars[so["cle"]] = {"libelle": so["label"], "pages": set(), "ent": []}
                ordre_s.append(so["cle"])
            pars[so["cle"]]["pages"].add(so["page"])
            if so["poids"]:
                pars[so["cle"]]["ent"].append((so["poids"][0], so["poids"][1], so["lot"], so["page"]))
        for sk in ordre_s:
            ss.append({"libelle": pars[sk]["libelle"], "pages": sorted(pars[sk]["pages"]),
                       "ponderation": fait_p(pars[sk]["ent"])})
        liste.append({"libelle": e["libelle"], "pages": pages_c, "lot": lot_fait,
                      "ponderation": fait_p(ent), "sous_criteres": ss})
    return type_pond, {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ------------------------------------------------------------------ plan et contrôle

def nature(libelle):
    k = cle(libelle)
    if re.search(r"techni|m[ée]rite", k):
        return "technique"
    if re.search(r"\b(?:prix|co[uû]t)\b", k):
        return "prix"
    return "autre"


def premiere(fp):
    vs = fp.get("valeurs", [])
    for v in vs:
        if v.get("lot") is None:
            return v
    return vs[0] if vs else None


def construire_plan(crits):
    plan = []
    for c in crits:
        if nature(c["libelle"]) != "technique":
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                p = premiere(s["ponderation"])
                plan.append({"titre": f"{c['libelle']} – {s['libelle']}", "critere": c["libelle"],
                             "sous_critere": s["libelle"], "ponderation": p["valeur"] if p else None,
                             "page_source": min(s["pages"]), "contenu": ""})
        else:
            p = premiere(c["ponderation"])
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": p["valeur"] if p else None,
                         "page_source": min(c["pages"]), "contenu": ""})
    return plan


def controler(d):
    alertes = []
    crits = d["criteres"]["liste"]
    sections = {s["critere"] for s in d.get("plan", [])}
    for c in crits:
        if nature(c["libelle"]) == "technique" and c["libelle"] not in sections:
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in crits:
        subs = c["sous_criteres"]
        if not subs:
            continue
        pw = premiere(c["ponderation"])
        sw = [premiere(s["ponderation"]) for s in subs]
        if pw is None or any(x is None for x in sw) or pw["unite"] == "rang":
            continue
        if all(x["unite"] == pw["unite"] for x in sw):
            cible = pw["valeur"]
        elif pw["unite"] == "points" and all(x["unite"] == "pourcentage" for x in sw):
            cible = 100
        else:
            continue
        if abs(sum(x["valeur"] for x in sw) - cible) > 0.01:
            alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    tp = d.get("type_ponderation", {})
    if [v["valeur"] for v in tp.get("valeurs", [])] == ["pourcentage"]:
        par_crit = []
        lots_cles = set()
        for c in crits:
            vs = [v for v in c["ponderation"]["valeurs"] if v["unite"] == "pourcentage"]
            par_crit.append(vs)
            lots_cles |= {v["lot"] for v in vs if v["lot"] is not None}
        for g in (lots_cles or {None}):
            total = 0
            vu = False
            for vs in par_crit:
                ch = [v for v in vs if v["lot"] == g] or [v for v in vs if v["lot"] is None]
                if ch:
                    total += ch[0]["valeur"]
                    vu = True
            if vu and abs(total - 100) > 0.01:
                alertes.append({"type": "total différent de 100 %", "objet": "critères"})
                break
    return alertes


# ------------------------------------------------------------------ assemblage

def extraire(pages):
    pages = [nettoyer(p) for p in pages]
    sp = segs_pages(pages)
    dl, hl, q, vis = ex_dates(pages)
    lots = ex_lots(pages)
    tp, crits = ex_criteres(pages, lots)
    d = {
        "lots": lots,
        "date_limite": fait(dl),
        "heure_limite": fait(hl),
        "date_questions": fait(q),
        "procedure": fait(ex_procedure(pages)),
        "visite_obligatoire": fait(ex_visite(sp)),
        "dates_visite": fait(vis, False),
        "variantes": fait(ex_variantes(sp)),
        "validite_offres": fait(ex_validite(sp)),
        "mode_remise": fait(ex_mode(sp)),
        "pieces": ex_pieces(pages),
        "limite_pages": fait(ex_limite_pages(sp)),
        "type_ponderation": tp,
        "criteres": crits,
    }
    d["plan"] = construire_plan(crits["liste"])
    d["controle"] = {"alertes": controler(d)}
    return d


def analyser(pages):
    return verifier(extraire(list(pages)), list(pages))


# ------------------------------------------------------------------ vérification

def _restreint(ext, prop, multiple=True):
    if not isinstance(prop, dict):
        return ext
    pv = [v.get("valeur") for v in prop.get("valeurs", [])]
    garde = [e for e in ext["valeurs"] if e["valeur"] in pv]
    return {"statut": TROUVE if garde else NON_TROUVE, "valeurs": garde,
            "conflit": bool(multiple and len(garde) > 1)}


def _restreint_p(ext, prop):
    if not isinstance(prop, dict):
        return ext
    pv = [(v.get("valeur"), v.get("unite"), v.get("lot")) for v in prop.get("valeurs", [])]
    garde = [e for e in ext["valeurs"] if (e["valeur"], e["unite"], e["lot"]) in pv]
    return {"statut": TROUVE if garde else NON_TROUVE, "valeurs": garde, "conflit": conflit_p(garde)}


def verifier(dossier, pages):
    ext = extraire(list(pages))
    r = {}
    for k in ("date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
              "variantes", "validite_offres", "mode_remise", "limite_pages", "type_ponderation"):
        r[k] = _restreint(ext[k], dossier.get(k))
    r["dates_visite"] = _restreint(ext["dates_visite"], dossier.get("dates_visite"), False)

    prop_lots = {l.get("numero"): l for l in dossier.get("lots", {}).get("liste", [])}
    lots = []
    for l in ext["lots"]["liste"]:
        if l["numero"] not in prop_lots:
            continue
        pt = [i.get("valeur") for i in prop_lots[l["numero"]].get("intitules", [])]
        intit = [i for i in l["intitules"] if i["valeur"] in pt] if pt else l["intitules"]
        lots.append({"numero": l["numero"], "intitules": intit, "pages": l["pages"],
                     "conflit": len(intit) > 1})
    r["lots"] = {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}

    prop_p = {cle(p.get("nom", "")): p for p in dossier.get("pieces", {}).get("liste", [])}
    pieces = []
    for p in ext["pieces"]["liste"]:
        pp = prop_p.get(cle(p["nom"]))
        if pp is None:
            continue
        pieces.append({"nom": p["nom"], "pages": p["pages"],
                       "phase": _restreint(p["phase"], pp.get("phase"), False),
                       "obligation": _restreint(p["obligation"], pp.get("obligation"))})
    r["pieces"] = {"statut": TROUVE if pieces else NON_TROUVE, "liste": pieces}

    prop_c = {cle(c.get("libelle", "")): c for c in dossier.get("criteres", {}).get("liste", [])}
    crits = []
    for c in ext["criteres"]["liste"]:
        pc = prop_c.get(cle(c["libelle"]))
        if pc is None:
            continue
        prop_s = {cle(s.get("libelle", "")): s for s in pc.get("sous_criteres", [])}
        ss = []
        for s in c["sous_criteres"]:
            ps = prop_s.get(cle(s["libelle"]))
            if ps is None:
                continue
            ss.append({"libelle": s["libelle"], "pages": s["pages"],
                       "ponderation": _restreint_p(s["ponderation"], ps.get("ponderation"))})
        crits.append({"libelle": c["libelle"], "pages": c["pages"],
                      "lot": _restreint(c["lot"], pc.get("lot"), False),
                      "ponderation": _restreint_p(c["ponderation"], pc.get("ponderation")),
                      "sous_criteres": ss})
    r["criteres"] = {"statut": TROUVE if crits else NON_TROUVE, "liste": crits}
    r["plan"] = construire_plan(crits)
    r["controle"] = {"alertes": controler(r)}
    return r
