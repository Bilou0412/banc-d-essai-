"""Lecture déterministe d'un règlement de la consultation (RC)."""
import copy
import json
import re

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"
I = re.I

# ------------------------------------------------------------------ nombres

_UN = {"zéro": 0, "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
       "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
       "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16}
_DIZ = {"vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}
_NUMW = (r"(?:z[ée]ro|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|"
         r"quinze|seize|vingts?|trente|quarante|cinquante|soixante|cents?|mille)(?![a-zà-ÿ])")
W = rf"{_NUMW}(?:[\s-]+(?:et[\s-]+)?{_NUMW})*"


def mots_en_entier(s):
    toks = [t for t in re.split(r"[\s-]+", s.lower().strip()) if t and t != "et"]
    if not toks:
        return None
    total = cur = 0
    for t in toks:
        if t in _UN:
            cur += _UN[t]
        elif t in _DIZ:
            if t.startswith("vingt") and cur == 4:
                cur = 80
            else:
                cur += _DIZ[t]
        elif t in ("cent", "cents"):
            total += (cur or 1) * 100
            cur = 0
        elif t == "mille":
            total += (cur or 1) * 1000
            cur = 0
        else:
            return None
    return total + cur


def nombre(s):
    s = s.strip()
    if re.fullmatch(r"\d+", s):
        return int(s)
    return mots_en_entier(s)


def num_dec(s):
    s = s.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", s):
        v = float(s.replace(",", "."))
        return int(v) if v == int(v) else v
    return mots_en_entier(s)


# ------------------------------------------------------------------ texte

def prep(page):
    s = str(page or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    for c in (" ", " ", " ", " ", "​"):
        s = s.replace(c, " ")
    s = s.replace("’", "'").replace("‘", "'")
    return s


def norm(s):
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()


HEAD_RE = re.compile(r"^\s*(?:article|annexe|chapitre|titre|section)\b", I)
BULLET_RE = re.compile(r"^\s*[-•*–—·▪]\s+")
MARK_RE = re.compile(r"^(?:[-•*–—·▪]\s+|\d+(?:\.\d+)*\s*[.)]\s+|\d+\s*[-–—]\s+|[A-Za-z][.)]\s+)")
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý])")


def segments(page):
    segs, buf = [], []

    def flush():
        if buf:
            txt = re.sub(r"\s+", " ", " ".join(buf)).strip()
            for part in SENT_RE.split(txt):
                if part.strip():
                    segs.append((part.strip(), False))
            buf.clear()

    for line in page.split("\n"):
        s = line.strip()
        if not s:
            flush()
            continue
        if HEAD_RE.match(s):
            flush()
            segs.append((re.sub(r"\s+", " ", s), True))
        elif MARK_RE.match(s):
            flush()
            buf.append(s)
        else:
            buf.append(s)
    flush()
    return segs


def fait(pairs, unique=True):
    order, data = [], {}
    for v, p in pairs:
        k = json.dumps(v, sort_keys=True, ensure_ascii=False)
        if k not in data:
            data[k] = [v, set()]
            order.append(k)
        data[k][1].add(p)
    vs = [{"valeur": data[k][0], "pages": sorted(data[k][1])} for k in order]
    return {"statut": TROUVE if vs else NON_TROUVE, "valeurs": vs,
            "conflit": bool(unique and len(vs) > 1)}


# ------------------------------------------------------------------ dates et heures

MOIS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
        "décembre": 12, "decembre": 12}
RE_DATE_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?!\d)")
RE_DATE_TXT = re.compile(r"(?<!\d)(\d{1,2})\s*(?:er)?\s+(" + "|".join(MOIS) + r")\s+(\d{4})", I)
RE_H_NUM = re.compile(r"(?<![\d/.:\-])(\d{1,2})\s*(?:h(?![a-zà-ÿ])|heures?\b)\s*(\d{2})?(?!\d)", I)
RE_H_COL = re.compile(r"(?<![\d/.:\-])(\d{1,2}):(\d{2})(?!\d)")
RE_H_WORD = re.compile(r"((?:[a-zàâéèêëîïôûùç-]+\s+){0,2}[a-zàâéèêëîïôûùç-]+)\s+heures?\b"
                       r"(?:\s+(trente|quinze|quarante-cinq|et\s+demie?|et\s+quart|\d{2}))?", I)
RE_MIDI = re.compile(r"\bmidi\b", I)


def tokens(text):
    toks = []
    for m in RE_DATE_NUM.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if y < 100:
            y += 2000
        if 1 <= d <= 31 and 1 <= mo <= 12:
            toks.append((m.start(), m.end(), "d", f"{d:02d}/{mo:02d}/{y}"))
    for m in RE_DATE_TXT.finditer(text):
        d, mo, y = int(m.group(1)), MOIS[m.group(2).lower()], int(m.group(3))
        if 1 <= d <= 31:
            toks.append((m.start(), m.end(), "d", f"{d:02d}/{mo:02d}/{y}"))
    for m in RE_H_NUM.finditer(text):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h < 24 and mi < 60:
            toks.append((m.start(), m.end(), "h", f"{h:02d}:{mi:02d}"))
    for m in RE_H_COL.finditer(text):
        h, mi = int(m.group(1)), int(m.group(2))
        if h < 24 and mi < 60:
            toks.append((m.start(), m.end(), "h", f"{h:02d}:{mi:02d}"))
    for m in RE_MIDI.finditer(text):
        toks.append((m.start(), m.end(), "h", "12:00"))
    for m in RE_H_WORD.finditer(text):
        g1 = m.group(1)
        ts = list(re.finditer(r"\S+", g1))
        for k in range(len(ts), 0, -1):
            h = mots_en_entier(g1[ts[-k].start():])
            if h is not None and h < 24:
                mi = 0
                g2 = (m.group(2) or "").lower()
                if g2:
                    mi = {"trente": 30, "quinze": 15, "quarante-cinq": 45}.get(g2)
                    if mi is None:
                        mi = 30 if "demi" in g2 else 15 if "quart" in g2 else int(g2)
                if mi < 60:
                    toks.append((m.start(1) + ts[-k].start(), m.end(), "h", f"{h:02d}:{mi:02d}"))
                break
    toks.sort(key=lambda t: (t[0], t[2]))
    out, last = [], -1
    for t in toks:
        if t[0] >= last:
            out.append(t)
            last = t[1]
    return out


_C_AUTRE = re.compile(r"publication|pr[ée]sent\s+avis|signature|notification", I)
_C_Q = re.compile(r"question|renseignement|demande", I)
_C_V = re.compile(r"visite", I)
_C_L = re.compile(r"\boffres?\b|\bplis\b|remise|r[ée]ception|limites?\b|parvenir|d[ée]pos[ée]|remis|d[ée]p[ôo]t", I)


def cat_of(text):
    if _C_AUTRE.search(text):
        return "autre"
    if _C_Q.search(text):
        return "questions"
    if _C_V.search(text):
        return "visite"
    if _C_L.search(text):
        return "limite"
    return None


RE_DELAI = re.compile(rf"(?<![\wà-ÿ])(?:\d+|{W})(?:\s*\(\d+\))?\s+jours?(?:\s+calendaires)?\s+avant\s+la\s+date\s+limite"
                      r"\s+(?:de\s+)?(?:remise|r[ée]ception|d[ée]p[ôo]t)\s+des\s+(?:offres|plis)", I)


def scan_dates(segs_pages):
    out = {"dl": [], "hl": [], "dq": [], "dv": []}
    for pi, segs in enumerate(segs_pages, 1):
        run = None
        for text, head in segs:
            if head:
                run = cat_of(text)
                continue
            toks = tokens(text)
            prev = 0
            for s, e, k, v in toks:
                c = cat_of(text[prev:s]) or run
                prev = e
                run = c
                if c == "limite":
                    out["dl" if k == "d" else "hl"].append((v, pi))
                elif c == "questions" and k == "d":
                    out["dq"].append((v, pi))
                elif c == "visite" and k == "d":
                    out["dv"].append((v, pi))
            c = cat_of(text[prev:])
            if c:
                run = c
            if _C_Q.search(text):
                m = RE_DELAI.search(text)
                if m:
                    out["dq"].append((re.sub(r"\s+", " ", m.group(0)), pi))
    return out


# ------------------------------------------------------------------ faits simples

PROCS = [
    (re.compile(r"proc[ée]dure\s+adapt[ée]e", I), lambda m: "procédure adaptée"),
    (re.compile(r"(?<![\w-])MAPA(?![\w-])"), lambda m: "procédure adaptée"),
    (re.compile(r"appel\s+d'offres\s+(ouvert|restreint)", I), lambda m: "appel d'offres " + m.group(1).lower()),
    (re.compile(r"dialogue\s+comp[ée]titif", I), lambda m: "dialogue compétitif"),
    (re.compile(r"proc[ée]dure\s+concurrentielle\s+avec\s+n[ée]gociation", I),
     lambda m: "procédure concurrentielle avec négociation"),
]
_V_NEG = re.compile(r"n'est\s+pas\s+obligatoire|non\s+obligatoire|pas\s+obligatoire|facultati", I)
_V_POS = re.compile(r"obligatoire", I)
_VAR_NEG = re.compile(r"(?:\bne\b|\bn')\s*(?:\w+\s+){0,3}?(?:pas|plus)\b|interdit|\baucune\s+variante|"
                      r"\bnon\s+(?:autoris|admis)|\bsans\s+variante", I)
_VAR_POS = re.compile(r"autoris|admis|accept|permis|peuvent\s+pr[ée]senter|possible", I)
_VKW = re.compile(r"validit[ée]\s+des\s+offres|offres?\s+(?:restent?|reste|demeurent?|sont|resteront)\s+valables?|"
                  r"valables?\s+pendant|engag[ée]s?\s+pendant", I)
_DUR = re.compile(rf"(?<![\wà-ÿ])(?P<n>\d+|{W})(?:\s*\((?P<p>\d+)\))?\s*(?P<u>jours?|mois)\b", I)
_LIM = re.compile(rf"m[ée]moire\b.{{0,100}}?(?<![\wà-ÿ])(?P<n>\d+|{W})(?:\s*\((?P<p>\d+)\))?\s+pages?\b", I)
_ELEC = re.compile(r"[ée]lectronique|d[ée]mat[ée]rialis|profil\s+d'acheteur|plateforme|plate-forme|en\s+ligne|par\s+internet", I)
_PAP = re.compile(r"papier|pli\s+cachet[ée]|support\s+physique", I)
_CTX = re.compile(r"\boffres?\b|\bplis?\b|remise|remis|d[ée]pos|transmi|candidatures?\b", I)
_NEG = re.compile(r"(?:\bne\b|\bn')\s*(?:\w+\s+){0,3}?(?:pas|plus)\b|\baucune?\b|interdit|refus|\bsans\b", I)


def faits_simples(segs_pages):
    dates = scan_dates(segs_pages)
    proc, vis, var, val, mode, lim = [], [], [], [], [], []
    for pi, segs in enumerate(segs_pages, 1):
        for text, head in segs:
            if head:
                continue
            for rx, f in PROCS:
                for m in rx.finditer(text):
                    proc.append((f(m), pi))
            if re.search(r"visite", text, I):
                if _V_NEG.search(text):
                    vis.append(("non", pi))
                elif _V_POS.search(text):
                    vis.append(("oui", pi))
            if re.search(r"variante", text, I):
                if _VAR_NEG.search(text):
                    var.append(("non autorisées", pi))
                elif _VAR_POS.search(text):
                    var.append(("autorisées", pi))
            k = _VKW.search(text)
            if k:
                m = _DUR.search(text, k.end())
                while m:
                    n = int(m.group("p")) if m.group("p") else nombre(m.group("n"))
                    if n is not None:
                        u = "mois" if m.group("u").lower() == "mois" else "jours"
                        val.append(({"nombre": n, "unite": u}, pi))
                        break
                    m = _DUR.search(text, m.end())
            m = _LIM.search(text)
            if m:
                n = int(m.group("p")) if m.group("p") else nombre(m.group("n"))
                if n is not None:
                    lim.append((n, pi))
            for cl in re.split(r"[:;,]", text):
                if _NEG.search(cl) or not _CTX.search(cl):
                    continue
                if _ELEC.search(cl):
                    mode.append(("électronique", pi))
                if _PAP.search(cl):
                    mode.append(("papier", pi))
    return {
        "date_limite": fait(dates["dl"]),
        "heure_limite": fait(dates["hl"]),
        "date_questions": fait(dates["dq"]),
        "procedure": fait(proc),
        "visite_obligatoire": fait(vis),
        "dates_visite": fait(dates["dv"], unique=False),
        "variantes": fait(var),
        "validite_offres": fait(val),
        "mode_remise": fait(mode),
        "limite_pages": fait(lim),
    }


# ------------------------------------------------------------------ lots

_LOT_LINE = re.compile(r"^\s*(?:[-•*–—·]\s*)?lots?(?:\s+unique)?\s*(?:\(s\))?\s*(?:n\s*°|no\b\.?|num[ée]ro)?\s*(\d+)\b(.*)$", I)
_LOT_UNIQUE = re.compile(r"lot\s+unique|n'est\s+pas\s+alloti|non\s+alloti|"
                         r"pas\s+(?:pr[ée]vu|envisag[ée])\s+de\s+(?:d[ée]composition|division|allotissement)|"
                         r"allotissement\s+n'[ée]tant\s+pas", I)


def extraire_lots(pages, segs_pages):
    titres = {}
    for pi, page in enumerate(pages, 1):
        for line in page.split("\n"):
            m = _LOT_LINE.match(line)
            if not m:
                continue
            rest = m.group(2)
            if rest.lstrip().startswith(","):
                continue
            t = re.sub(r"^[\s:\-–—.)]+", "", rest)
            t = re.sub(r"\s+", " ", t).strip(" \t;.,")
            if not t:
                continue
            titres.setdefault(int(m.group(1)), []).append((t, pi))
    lots = []
    if titres:
        for n in sorted(titres):
            pgs = sorted({p for _, p in titres[n]})
            ints = fait(titres[n], unique=False)
            lots.append({"numero": n, "intitules": ints["valeurs"], "pages": pgs,
                         "conflit": len(ints["valeurs"]) > 1})
    else:
        pgs = sorted({pi for pi, segs in enumerate(segs_pages, 1)
                      for text, head in segs if not head and _LOT_UNIQUE.search(text)})
        if pgs:
            lots.append({"numero": None, "intitules": [], "pages": pgs, "conflit": False})
    return {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}


# ------------------------------------------------------------------ pièces

_P_HEAD = re.compile(r"pi[èe]ces?|dossier\s+[àa]\s+remettre|contenu\s+(?:du|des)\s+(?:dossier|plis)|documents?\s+[àa]\s+(?:remettre|fournir)", I)
_P_TRIG = re.compile(r"pi[èe]ces?\b|documents?\s+suivants|dossier\s+[àa]\s+remettre|produira|fournir|remett|comprenant|justificatifs?", I)
_P_ATT = re.compile(r"attributaire|envisag[ée]\s+d'attribuer|attribuer\s+le\s+march|titulaire", I)
_P_CAND = re.compile(r"candidature", I)
_P_OFF = re.compile(r"\boffres?\b", I)
_Q_OBL = re.compile(r"\(\s*obligatoires?\s*\)", I)
_Q_FAC = re.compile(r"\(\s*(?:facultati[fv]e?s?|optionnel(?:le)?s?)\s*\)|,?\s*[àa]\s+titre\s+facultatif", I)


def _phase(text):
    if _P_ATT.search(text):
        return "attributaire"
    c, o = _P_CAND.search(text), _P_OFF.search(text)
    if c and not o:
        return "candidature"
    if o and not c:
        return "offre"
    return None


def extraire_pieces(pages):
    pcs, order = {}, []
    in_p, phase = False, None
    for pi, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = line.strip()
            if not s:
                continue
            if HEAD_RE.match(s):
                in_p = bool(_P_HEAD.search(s))
                phase = _phase(s) if in_p else None
                continue
            b = BULLET_RE.match(line)
            if not b:
                if _P_TRIG.search(s):
                    in_p = True
                if in_p:
                    ph = _phase(s)
                    if ph:
                        phase = ph
                continue
            if not in_p:
                continue
            t = line[b.end():].strip()
            if not t or t.endswith(":"):
                continue
            obl = None
            if re.search(r"non\s+obligatoire|facultati|optionnel|[àa]\s+titre\s+facultatif", t, I):
                obl = "non obligatoire"
            elif re.search(r"obligatoire", t, I):
                obl = "obligatoire"
            name = _Q_FAC.sub("", _Q_OBL.sub("", t))
            name = re.sub(r"\s+", " ", name).strip(" \t;,.")
            if len(name) < 3:
                continue
            k = norm(name)
            if k not in pcs:
                pcs[k] = {"nom": name, "pages": set(), "ph": [], "ob": []}
                order.append(k)
            p = pcs[k]
            p["pages"].add(pi)
            if phase:
                p["ph"].append((phase, pi))
            if obl:
                p["ob"].append((obl, pi))
    liste = [{"nom": pcs[k]["nom"], "pages": sorted(pcs[k]["pages"]),
              "phase": fait(pcs[k]["ph"], unique=False), "obligation": fait(pcs[k]["ob"])} for k in order]
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ------------------------------------------------------------------ critères

_CRIT_HEAD = re.compile(r"crit[èe]res?|jugement\s+des\s+offres|s[ée]lection\s+des\s+offres|"
                        r"notation\s+des\s+offres|choix\s+de\s+l'offre", I)
_CRIT_LINE = re.compile(r"crit[èe]res?\b", I)
_ENTRY = re.compile(r"offres?\s+sont\s+(?:not[ée]es?|jug[ée]es?|[ée]valu[ée]es?)\s+(?:sur|selon|au\s+regard)", I)
_BAREME =re.compile(r"bar[èe]me|formule|notation|note\s+finale|\bla\s+note\b|notes?\s+obtenues", I)
_CLASS = re.compile(r"class[ée]s?\s+par\s+ordre|ordre\s+(?:d[ée]croissant|croissant|d'importance|de\s+priorit[ée])", I)
_DETAIL = re.compile(r"sous-crit|[ée]l[ée]ments\s+suivants|d[ée]tail|d[ée]compos|au\s+regard", I)
_CRIT_N = re.compile(r"^crit[èe]re\s*(?:(?:n\s*°|no\b\.?|num[ée]ro)\s*)?(\d+)\s*[:—–\-.)]*\s*(.*)$", I)
_DOT = re.compile(r"^(\d+(?:\.\d+)+)\s*[.)]?\s+(.*)$")
_NUM = re.compile(r"^(\d+)\s*(?:[.)]|[-–—])\s+(.*)$")
_LET = re.compile(r"^([A-Za-z])\s*[.)]\s+(.*)$")
_WEIGHT = re.compile(rf"(?<![\w.,])(?P<n>\d+(?:[.,]\d+)?|{W})\s*(?P<u>%|pour\s*cent|points?\b|pts?\b)", I)
_LOTCTX = re.compile(r"^(?:pour\s+(?:le|les|chaque)\s+lots?|lots?)\b\s*(?:n\s*°|no\b\.?|num[ée]ros?)?\s*"
                     r"(\d+(?:\s*(?:,|et|à|au|-|–)\s*(?:n\s*°\s*)?\d+)*)(?P<rest>.*)$", I)
_LABEL_TAIL = re.compile(r"[\s:=\-–—(\[,]*(?:pond[ée]ration|pond[ée]r[ée]e?s?|coefficient|poids|not[ée]e?\s+sur|"
                         r"note\s+sur|sur)?[\s:=(\[]*$", I)


def _lw(t):
    m = None
    if "|" in t:
        parts = t.split("|")
        label = parts[0]
        m = _WEIGHT.search("|".join(parts[1:]))
    else:
        m = _WEIGHT.search(t)
        if m:
            label = _LABEL_TAIL.sub("", t[:m.start()])
        else:
            label = t
            if ":" in label:
                label = label.split(":")[0]
    label = re.sub(r"\s+", " ", label).strip(" \t;,.:-–—")
    w = None
    if m:
        v = num_dec(m.group("n"))
        if v is not None:
            u = m.group("u").lower()
            w = (v, "pourcentage" if (u == "%" or u.startswith("pour")) else "points")
    return label, w


def _lots_spec(spec):
    out = set()
    rg = r"(\d+)\s*(?:à|au|-|–)\s*(\d+)"
    for a, b in re.findall(rg, spec):
        out.update(range(int(a), int(b) + 1))
    out.update(int(x) for x in re.findall(r"\d+", re.sub(rg, " ", spec)))
    return tuple(sorted(out))


def _faitp(pond):
    order, data = [], {}
    for v, u, l, p in pond:
        k = (v, u, l)
        if k not in data:
            data[k] = set()
            order.append(k)
        data[k].add(p)
    vals = [{"valeur": v, "unite": u, "lot": l, "pages": sorted(data[(v, u, l)])} for v, u, l in order]
    return {"statut": TROUVE if vals else NON_TROUVE, "valeurs": vals, "conflit": _conflit_p(vals)}


def _conflit_p(vals):
    seen = {}
    for v in vals:
        k = (v["valeur"], v["unite"])
        if v["lot"] in seen and seen[v["lot"]] != k:
            return True
        seen.setdefault(v["lot"], k)
    return False


def _new_crit(lib):
    return {"libelle": lib, "pages": set(), "occ": [], "pond": [], "subs": {}, "ordre": []}


def _lot_fait(occ, pages, lots):
    if len(lots) == 1:
        return fait([(lots[0]["numero"], p) for p in lots[0]["pages"]], unique=False)
    explicit, any_all = set(), False
    for p, ctx in occ:
        if ctx is None:
            any_all = True
        else:
            explicit.update(ctx)
    allnums = {l["numero"] for l in lots if l["numero"] is not None}
    if any_all or not explicit or (allnums and allnums <= explicit):
        pairs = [("tous les lots", p) for p in pages]
    else:
        pairs = [(l, p) for l in sorted(explicit) for p, ctx in occ if ctx and l in ctx]
    return fait(pairs, unique=False)


def extraire_criteres(pages, lots):
    crits, order = {}, []
    st = {"in": False, "class": False, "lot": None, "cur": None, "sub": False, "ind": 0, "seq": 0}

    def bind(s):
        if _DETAIL.search(s):
            ns = norm(s)
            for k in order:
                if k in ns:
                    st["cur"] = crits[k]
                    st["sub"] = True
                    return True
            if st["cur"] is not None:
                st["sub"] = True
        return False

    for pi, page in enumerate(pages, 1):
        for line in page.split("\n"):
            s = line.strip()
            if not s:
                continue
            ex = line.expandtabs(4)
            indent = len(ex) - len(ex.lstrip())
            if HEAD_RE.match(s):
                st.update({"in": bool(_CRIT_HEAD.search(s)), "class": False, "lot": None,
                           "cur": None, "sub": False, "seq": 0})
                if st["in"]:
                    bind(s)
                continue
            if _BAREME.search(s):
                st["in"] = False
                continue
            if not st["in"]:
                if _CRIT_LINE.search(s) or _ENTRY.search(s):
                    st["in"] = True
                else:
                    mm = _CRIT_N.match(s) or _NUM.match(s)
                    if mm and order:
                        lb, ww = _lw(mm.group(2))
                        if ww is not None and norm(lb) in crits:
                            st["in"] = True
                    if not st["in"]:
                        continue
            lm = _LOTCTX.match(s)
            if lm and re.match(r"\s*[:,]?\s*(?:$|les\s)", lm.group("rest")):
                st["lot"] = _lots_spec(lm.group(1))
                st["seq"] = 0
                continue
            if re.search(r"ensemble\s+des\s+lots|tous\s+les\s+lots|chaque\s+lot", s, I):
                st["lot"] = None
            if _CLASS.search(s):
                st["class"] = True
            kind = num = t = None
            m = _CRIT_N.match(s)
            if m:
                kind, num, t = "c0", int(m.group(1)), m.group(2)
            else:
                m = _DOT.match(s)
                if m:
                    kind, t = "c1", m.group(2)
                else:
                    m = _NUM.match(s)
                    if m:
                        kind, num, t = "c0", int(m.group(1)), m.group(2)
                    else:
                        m = _LET.match(s)
                        if m:
                            kind, t = "c1", m.group(2)
                        else:
                            b = BULLET_RE.match(line)
                            if b:
                                kind, t = "b", line[b.end():].strip()
                            elif "|" in s:
                                kind, t = "row", s
            label = w = None
            if kind:
                label, w = _lw(t)
                if not label or len(label) > 150 or (kind == "row" and w is None):
                    kind = None
            if kind is None:
                if _DETAIL.search(s):
                    bind(s)
                elif _CRIT_LINE.search(s):
                    st["cur"] = None
                    st["sub"] = False
                continue
            cur = st["cur"]
            if kind == "c0":
                level0 = True
            elif kind == "c1":
                level0 = cur is None
            elif kind == "b":
                level0 = cur is None or not (st["sub"] or indent > st["ind"])
            else:
                level0 = cur is None or not indent > st["ind"]
            ctx = st["lot"]
            lots_rec = ctx if ctx else (None,)
            if level0:
                key = norm(label)
                if key not in crits:
                    crits[key] = _new_crit(label)
                    order.append(key)
                c = crits[key]
                st["cur"], st["ind"], st["sub"] = c, indent, False
                if num is None:
                    st["seq"] += 1
                if w is None and st["class"]:
                    w = (num if num is not None else st["seq"], "rang")
                c["pages"].add(pi)
                c["occ"].append((pi, ctx))
                if w:
                    for l in lots_rec:
                        c["pond"].append((w[0], w[1], l, pi))
                if _DETAIL.search(s):
                    st["sub"] = True
            else:
                key = norm(label)
                if key not in cur["subs"]:
                    cur["subs"][key] = {"libelle": label, "pages": set(), "pond": []}
                    cur["ordre"].append(key)
                sc = cur["subs"][key]
                sc["pages"].add(pi)
                if w:
                    for l in lots_rec:
                        sc["pond"].append((w[0], w[1], l, pi))
    liste = []
    for k in order:
        c = crits[k]
        pgs = sorted(c["pages"])
        liste.append({
            "libelle": c["libelle"], "pages": pgs,
            "lot": _lot_fait(c["occ"], pgs, lots),
            "ponderation": _faitp(c["pond"]),
            "sous_criteres": [{"libelle": c["subs"][sk]["libelle"], "pages": sorted(c["subs"][sk]["pages"]),
                               "ponderation": _faitp(c["subs"][sk]["pond"])} for sk in c["ordre"]],
        })
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


def type_ponderation(criteres):
    mp = {"pourcentage": "pourcentage", "points": "points", "rang": "classement"}
    pairs = [(mp[v["unite"]], p) for c in criteres for v in c["ponderation"]["valeurs"] for p in v["pages"]]
    if not pairs:
        pairs = [(mp[v["unite"]], p) for c in criteres for s in c["sous_criteres"]
                 for v in s["ponderation"]["valeurs"] for p in v["pages"]]
    return fait(pairs)


# ------------------------------------------------------------------ plan et contrôle

def est_tech(lib):
    n = norm(lib)
    return "techni" in n and not re.search(r"\b(prix|co[uû]t)\b", n)


def _premier(fp):
    return fp["valeurs"][0]["valeur"] if fp["valeurs"] else None


def construire_plan(criteres):
    plan = []
    for c in criteres:
        if not est_tech(c["libelle"]):
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                plan.append({"titre": f"{c['libelle']} – {s['libelle']}", "critere": c["libelle"],
                             "sous_critere": s["libelle"], "ponderation": _premier(s["ponderation"]),
                             "page_source": min(s["pages"]), "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": _premier(c["ponderation"]), "page_source": min(c["pages"]),
                         "contenu": ""})
    return plan


def controler(dossier):
    al = []
    crits = dossier["criteres"]["liste"]
    plan = dossier.get("plan", [])
    for c in crits:
        if est_tech(c["libelle"]) and not any(s["critere"] == c["libelle"] for s in plan):
            al.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in crits:
        if not c["sous_criteres"]:
            continue
        cw = {}
        for v in c["ponderation"]["valeurs"]:
            cw.setdefault(v["lot"], (v["valeur"], v["unite"]))
        bad = False
        for lot, (val, unite) in cw.items():
            if unite == "rang":
                continue
            tot, ok, su = 0, True, None
            for s in c["sous_criteres"]:
                sv = next((v for v in s["ponderation"]["valeurs"] if v["lot"] == lot), None)
                if sv is None:
                    sv = next((v for v in s["ponderation"]["valeurs"] if v["lot"] is None), None)
                if sv is None:
                    ok = False
                    break
                tot += sv["valeur"]
                su = sv["unite"]
            if not ok:
                continue
            attendu = 100 if (unite == "points" and su == "pourcentage") else val
            if abs(tot - attendu) > 0.01:
                bad = True
        if bad:
            al.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    tp = [v["valeur"] for v in dossier["type_ponderation"]["valeurs"]]
    if "pourcentage" in tp:
        rows = []
        for c in crits:
            m = {}
            for v in c["ponderation"]["valeurs"]:
                if v["unite"] == "pourcentage":
                    m.setdefault(v["lot"], v["valeur"])
            if m:
                rows.append(m)
        keys = {l for m in rows for l in m if l is not None} or {None}
        if rows:
            for g in sorted(keys, key=lambda x: (x is None, x or 0)):
                tot = sum(m[g] if g in m else m.get(None, 0) for m in rows)
                if abs(tot - 100) > 0.01:
                    al.append({"type": "total différent de 100 %", "objet": "critères"})
                    break
    return al


def finaliser(d):
    d["plan"] = construire_plan(d["criteres"]["liste"])
    d["controle"] = {"alertes": controler(d)}
    return d


# ------------------------------------------------------------------ points d'entrée

def extraire(pages):
    pages = [prep(p) for p in (pages or [])]
    segs = [segments(p) for p in pages]
    d = faits_simples(segs)
    d["lots"] = extraire_lots(pages, segs)
    d["pieces"] = extraire_pieces(pages)
    d["criteres"] = extraire_criteres(pages, d["lots"]["liste"])
    d["type_ponderation"] = type_ponderation(d["criteres"]["liste"])
    return finaliser(d)


def analyser(pages):
    return extraire(list(pages))


def _jk(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _inter(fr, pr, unique=True):
    keys = {_jk(v["valeur"]) for v in (pr or {}).get("valeurs", [])}
    vs = copy.deepcopy([v for v in fr["valeurs"] if _jk(v["valeur"]) in keys])
    return {"statut": TROUVE if vs else NON_TROUVE, "valeurs": vs, "conflit": bool(unique and len(vs) > 1)}


def _inter_p(fr, pr):
    keys = {(v["valeur"], v["unite"], v["lot"]) for v in (pr or {}).get("valeurs", [])}
    vs = copy.deepcopy([v for v in fr["valeurs"] if (v["valeur"], v["unite"], v["lot"]) in keys])
    return {"statut": TROUVE if vs else NON_TROUVE, "valeurs": vs, "conflit": _conflit_p(vs)}


_SIMPLES = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
            "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
            "type_ponderation"]


def verifier(dossier, pages):
    fr = extraire(list(pages))
    pr = dossier or {}
    out = {}
    for k in _SIMPLES:
        out[k] = _inter(fr[k], pr.get(k), unique=(k != "dates_visite"))
    pl = {l["numero"]: l for l in pr.get("lots", {}).get("liste", [])}
    lots = []
    for l in fr["lots"]["liste"]:
        if l["numero"] in pl:
            keys = {_jk(i["valeur"]) for i in pl[l["numero"]].get("intitules", [])}
            ints = copy.deepcopy([i for i in l["intitules"] if _jk(i["valeur"]) in keys])
            lots.append({"numero": l["numero"], "intitules": ints, "pages": list(l["pages"]),
                         "conflit": len(ints) > 1})
    out["lots"] = {"statut": TROUVE if lots else NON_TROUVE, "liste": lots}
    pm = {norm(p["nom"]): p for p in pr.get("pieces", {}).get("liste", [])}
    pcs = []
    for p in fr["pieces"]["liste"]:
        q = pm.get(norm(p["nom"]))
        if q is not None:
            pcs.append({"nom": p["nom"], "pages": list(p["pages"]),
                        "phase": _inter(p["phase"], q.get("phase"), unique=False),
                        "obligation": _inter(p["obligation"], q.get("obligation"))})
    out["pieces"] = {"statut": TROUVE if pcs else NON_TROUVE, "liste": pcs}
    cm = {norm(c["libelle"]): c for c in pr.get("criteres", {}).get("liste", [])}
    crs = []
    for c in fr["criteres"]["liste"]:
        q = cm.get(norm(c["libelle"]))
        if q is None:
            continue
        sm = {norm(s["libelle"]): s for s in q.get("sous_criteres", [])}
        subs = []
        for s in c["sous_criteres"]:
            sq = sm.get(norm(s["libelle"]))
            if sq is not None:
                subs.append({"libelle": s["libelle"], "pages": list(s["pages"]),
                             "ponderation": _inter_p(s["ponderation"], sq.get("ponderation"))})
        crs.append({"libelle": c["libelle"], "pages": list(c["pages"]),
                    "lot": _inter(c["lot"], q.get("lot"), unique=False),
                    "ponderation": _inter_p(c["ponderation"], q.get("ponderation")),
                    "sous_criteres": subs})
    out["criteres"] = {"statut": TROUVE if crs else NON_TROUVE, "liste": crs}
    return finaliser(out)
