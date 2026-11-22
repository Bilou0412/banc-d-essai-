"""Lecture déterministe d'un règlement de la consultation (RC).

Points d'entrée : analyser(pages), verifier(dossier, pages), controler(dossier).
Aucune dépendance en dehors de la bibliothèque standard.
"""

import copy
import datetime
import json
import re
import unicodedata

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

# ---------------------------------------------------------------- outils généraux


def _sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _prep(t):
    if not isinstance(t, str):
        return ""
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    for ch in ("\u00a0", "\u202f", "\u2009", "\u2007"):
        t = t.replace(ch, " ")
    for ch in ("\u200b", "\u00ad"):
        t = t.replace(ch, "")
    return t.replace("\u2019", "'").replace("\u2018", "'")


def _nk(x):
    x = re.sub(r"\s+", " ", str(x)).strip().lower()
    return re.sub(r"^[\s:;,.\-–—|]+|[\s:;,.\-–—|]+$", "", x)


def _cle(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _num(x):
    if isinstance(x, float) and x == int(x):
        return int(x)
    return x


_UNITES = {"zero": 0, "zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
           "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
           "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16}
_DIZAINES = {"vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}


def _fr_num(s):
    toks = [t for t in re.split(r"[\s\-]+", s.lower().strip()) if t and t != "et"]
    if not toks:
        return None
    total = 0
    cur = 0
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "quatre" and i + 1 < len(toks) and toks[i + 1] in ("vingt", "vingts"):
            cur += 80
            i += 2
            continue
        if t in _UNITES:
            cur += _UNITES[t]
        elif t in _DIZAINES:
            cur += _DIZAINES[t]
        elif t in ("cent", "cents"):
            cur = (cur if cur else 1) * 100
        elif t == "mille":
            total += (cur if cur else 1) * 1000
            cur = 0
        else:
            return None
        i += 1
    return total + cur


_W = (r"(?:z[ée]ro|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|"
      r"quinze|seize|vingts?|trente|quarante|cinquante|soixante|cents?|mille)")
_NUMW = r"(?<![a-zà-ÿ])" + _W + r"(?:(?:[\s\-]+et)?[\s\-]+" + _W + r")*(?![a-zà-ÿ])"
_I = re.IGNORECASE


class _Acc:
    def __init__(self):
        self.d = {}

    def add(self, valeur, page):
        k = _cle(valeur)
        if k not in self.d:
            self.d[k] = [valeur, set()]
        self.d[k][1].add(page)

    def valeurs(self):
        return [{"valeur": v, "pages": sorted(p)} for v, p in self.d.values()]


def _fait(valeurs, multi=False):
    vs = list(valeurs)
    return {"statut": TROUVE if vs else NON_TROUVE, "valeurs": vs,
            "conflit": (len(vs) > 1) and not multi}


# ---------------------------------------------------------------- découpage du texte

_FOOTER = re.compile(r"^(?:rc\s*[–\-]\s*\d+\s*/\s*\d+|page\s+\d+(?:\s*(?:sur|/)\s*\d+)?)$", _I)
_HEADING = re.compile(r"^(?:article|annexe|chapitre)\b", _I)


def _unites(t):
    lines = [l.strip() for l in t.split("\n")]
    lines = [l for l in lines if l]
    merged = []
    for l in lines:
        if (merged and not re.search(r"[.;:!?]$", merged[-1])
                and re.match(r"[a-zàâäçéèêëîïôöùûüÿœ(]", l)):
            merged[-1] += " " + l
        else:
            merged.append(l)
    out = []
    for m in merged:
        out.extend(p for p in re.split(r"(?<=[.;!?])\s+", m) if p.strip())
    return out


# ---------------------------------------------------------------- dates, heures

_MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
         "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
_DATE_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?!\d)(?![/.\-]\d)")
_DATE_LET = re.compile(
    r"(?<!\d)(\d{1,2})(?:er)?\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|"
    r"octobre|novembre|d[ée]cembre)\s+(\d{4})(?!\d)", _I)
_TIME_C = re.compile(r"(?<![\d:/.,\-])(\d{1,2}):(\d{2})(?!\d)")
_TIME_H = re.compile(r"(?<![\d:/.,\-])(\d{1,2})\s*(?:heures?|h)(?![a-zà-ÿ])"
                     r"(?:\s*(\d{2})(?!\d)(?![/\-.]\d))?", _I)
_TIME_W = re.compile(r"(?<![a-zà-ÿ])(" + _NUMW + r")\s+heures?(?![a-zà-ÿ])"
                     r"(?:\s+(?:et\s+)?(demie|quart|" + _NUMW + r"))?", _I)
_MIDI = re.compile(r"(?<![a-zà-ÿ])midi(?![a-zà-ÿ])", _I)

_Q = re.compile(r"question|renseignement|compl[ée]ment d'information|demandes? de pr[ée]cision")
_L = re.compile(r"limite|remis|r[ée]ception|d[ée]p[oô]t|d[ée]pos|parvenir|parvenu|au plus tard|"
                r"jusqu|attendu|avant le|date et heure")
_DELAI = re.compile(
    r"((?:\d+|" + _NUMW + r")(?:\s*\(\s*\d+\s*\))?\s+jours?(?:\s+(?:calendaires|ouvr[ée]s|ouvrables|francs))?"
    r"\s+avant\s+la\s+(?:date\s+limite|date\s+de\s+remise|remise)"
    r"(?:\s+(?:de\s+(?:remise|r[ée]ception|d[ée]p[oô]t)|fix[ée]e\s+pour\s+la\s+r[ée]ception)"
    r"\s+des\s+(?:offres|plis))?)", _I)


def _date(j, m, a):
    try:
        datetime.date(a, m, j)
    except ValueError:
        return None
    return "%02d/%02d/%04d" % (j, m, a)


def _heure(h, m):
    if 0 <= h <= 23 and 0 <= m <= 59:
        return "%02d:%02d" % (h, m)
    return None


def _tokens(s):
    toks = []
    for m in _DATE_NUM.finditer(s):
        a = int(m.group(4))
        if len(m.group(4)) == 2:
            a += 2000
        v = _date(int(m.group(1)), int(m.group(3)), a)
        if v:
            toks.append((m.start(), m.end(), "d", v))
    for m in _DATE_LET.finditer(s):
        mois = _MOIS[_sans_accents(m.group(2).lower())]
        v = _date(int(m.group(1)), mois, int(m.group(3)))
        if v:
            toks.append((m.start(), m.end(), "d", v))
    for m in _TIME_C.finditer(s):
        v = _heure(int(m.group(1)), int(m.group(2)))
        if v:
            toks.append((m.start(), m.end(), "t", v))
    for m in _TIME_H.finditer(s):
        v = _heure(int(m.group(1)), int(m.group(2) or 0))
        if v:
            toks.append((m.start(), m.end(), "t", v))
    for m in _TIME_W.finditer(s):
        h = _fr_num(m.group(1))
        mn = 0
        if m.group(2):
            g = m.group(2).lower()
            mn = 30 if g == "demie" else 15 if g == "quart" else _fr_num(g)
        if h is not None and mn is not None:
            v = _heure(h, mn)
            if v:
                toks.append((m.start(), m.end(), "t", v))
    for m in _MIDI.finditer(s):
        toks.append((m.start(), m.end(), "t", "12:00"))
    toks.sort()
    out = []
    fin = -1
    for t in toks:
        if t[0] >= fin:
            out.append(t)
            fin = t[1]
    return out


def _classe(seg):
    l = seg.lower()
    if _Q.search(l):
        return "q"
    if "visite" in l:
        return "v"
    if _L.search(l):
        return "l"
    return None


def _dates_heures(P):
    acc = {"date_limite": _Acc(), "heure_limite": _Acc(), "date_questions": _Acc(),
           "dates_visite": _Acc()}
    for n, _lines, sents in P:
        for idx, s in enumerate(sents):
            toks = _tokens(s)
            classes = []
            fin = 0
            for k, (a, b, kind, val) in enumerate(toks):
                cls = _classe(s[fin:a])
                if cls is None and k > 0:
                    cls = classes[k - 1]
                if cls is None and idx > 0:
                    prec = sents[idx - 1]
                    if not any(t[2] == "d" for t in _tokens(prec)):
                        cls = _classe(prec)
                classes.append(cls)
                fin = b
                if kind == "d":
                    if cls == "q":
                        acc["date_questions"].add(val, n)
                    elif cls == "v":
                        acc["dates_visite"].add(val, n)
                    elif cls == "l":
                        acc["date_limite"].add(val, n)
                elif cls == "l":
                    acc["heure_limite"].add(val, n)
            if _Q.search(s.lower()):
                m = _DELAI.search(s)
                if m:
                    acc["date_questions"].add(re.sub(r"\s+", " ", m.group(1)), n)
    return acc


# ---------------------------------------------------------------- faits textuels

_PROC = re.compile(
    r"proc[ée]dure\s+adapt[ée]e|(?<![\w\-])mapa(?![\w\-])|appel\s+d'offres\s+(ouvert|restreint)|"
    r"dialogue\s+comp[ée]titif|proc[ée]dure\s+concurrentielle\s+avec\s+n[ée]gociation", _I)


def _procedures(P):
    acc = _Acc()
    for n, lines, _s in P:
        flat = " ".join("\n".join(lines).split())
        for m in _PROC.finditer(flat):
            g = _sans_accents(m.group(0).lower())
            if g.startswith("procedure adaptee") or g == "mapa":
                v = "procédure adaptée"
            elif g.startswith("appel"):
                v = "appel d'offres " + m.group(1).lower()
            elif g.startswith("dialogue"):
                v = "dialogue compétitif"
            else:
                v = "procédure concurrentielle avec négociation"
            acc.add(v, n)
    return acc


_ATT_VISITE = re.compile(r"(?:attestations?|certificats?)\s+de\s+visite")
_NON_OBLIG = re.compile(r"facultati|\bnon\s+obligatoire|\bpas\s+(?:\w+\s+)?obligatoire|"
                        r"\bn'est\s+pas\s+exig|\bne\s+(?:\w+\s+)?pas\s+(?:\w+\s+)?obligatoire")
_OBLIG = re.compile(r"obligatoire|exig[ée]e|imp[ée]rative")


def _visite(P):
    acc = _Acc()
    for n, _l, sents in P:
        for s in sents:
            l = _ATT_VISITE.sub("", s.lower())
            if "visite" not in l:
                continue
            if _NON_OBLIG.search(l):
                acc.add("non", n)
            elif _OBLIG.search(l):
                acc.add("oui", n)
    return acc


_NEG = re.compile(r"\bne\s+(?:\w+\s+){0,3}pas\b|\bn'(?:\w+\s+){0,3}pas\b|\baucune?\b|\binterdit|\brefus|"
                  r"\bexclu(?!sivement)|\bnon\s+(?:autoris|admis|accept|recevable)|\bpas\s+(?:autoris|admis|accept)|"
                  r"\bsans\b|\bni\b")
_POS_VAR = re.compile(r"autoris|admis|accept|permis|possible|(?:peuvent|pourront)\s+(?:pr[ée]senter|proposer)|"
                      r"à l'initiative d(?:u|es) candidat")


def _variantes(P):
    acc = _Acc()
    for n, _l, sents in P:
        for s in sents:
            l = s.lower()
            if "variante" not in l:
                continue
            if _NEG.search(l):
                acc.add("non autorisées", n)
            elif _POS_VAR.search(l):
                acc.add("autorisées", n)
    return acc


_KW_VAL = re.compile(r"validit[ée]\s+(?:des|de\s+l')\s*offres?|offres?\b[^.]*\bvalables?\b|"
                     r"\bvalables?\b[^.]*\boffres?\b", _I)
_DUR = re.compile(r"(?:(\d+)|(" + _NUMW + r"))(?:\s*\(\s*(\d+)\s*\))?\s*(jours?|mois)\b", _I)


def _validite(P):
    acc = _Acc()
    for n, _l, sents in P:
        for s in sents:
            k = _KW_VAL.search(s)
            if not k:
                continue
            for m in _DUR.finditer(s, k.start()):
                if m.group(3):
                    nb = int(m.group(3))
                elif m.group(1):
                    nb = int(m.group(1))
                else:
                    nb = _fr_num(m.group(2))
                if nb is None:
                    continue
                unite = "mois" if m.group(4).lower() == "mois" else "jours"
                acc.add({"nombre": nb, "unite": unite}, n)
                break
    return acc


_OBJ_REMISE = re.compile(r"offres?|plis?\b|candidatures?|remise|transmi|d[ée]p[oô]|envoi")
_ELEC = re.compile(r"électronique|dématérialis|plateforme|profil d'acheteur|profil acheteur|en ligne|"
                   r"télétransmission")
_PAPIER = re.compile(r"papier|pli cacheté|contre récépissé|lettre recommandée")


def _mode_remise(P):
    acc = _Acc()
    for n, _l, sents in P:
        for s in sents:
            l = s.lower()
            if _Q.search(l):
                continue
            for c in re.split(r"[:;,]", l):
                if not _OBJ_REMISE.search(c) or _NEG.search(c):
                    continue
                if _ELEC.search(c):
                    acc.add("électronique", n)
                if _PAPIER.search(c):
                    acc.add("papier", n)
    return acc


_PAGES = re.compile(r"(?<![\w])(?:(\d+)|(" + _NUMW + r"))(?:\s*\(\s*(\d+)\s*\))?\s*pages?\b", _I)


def _limite_pages(P):
    acc = _Acc()
    for n, _l, sents in P:
        for s in sents:
            k = re.search(r"m[ée]moire", s, _I)
            if not k:
                continue
            m = _PAGES.search(s, k.start())
            if not m:
                continue
            if m.group(3):
                v = int(m.group(3))
            elif m.group(1):
                v = int(m.group(1))
            else:
                v = _fr_num(m.group(2))
            if v is not None:
                acc.add(v, n)
    return acc


# ---------------------------------------------------------------- lots

_LOT_RE = re.compile(r"^\s*(?:[-–—•·*]\s*)?lot\s*(?:n\s*[°º]|no\.?|num[ée]ro)?\s*0*(\d+)\s*[:\-–—]\s*(\S.*)$", _I)
_LOT_CTX = re.compile(r"^lot\s*(?:n\s*[°º]|no\.?|num[ée]ro)?\s*0*(\d+)\s*[:\-–—]?\s*$", _I)
_UNIQ = re.compile(
    r"lot\s+unique|unique\s+lot|(?:un|1)\s+seul\s+lot|en\s+un\s+lot\b|non\s+allotie?s?\b|"
    r"n'est\s+pas\s+allotie?s?\b|(?:pas|aucune?)\s+(?:de\s+)?(?:d[ée]composition|division|d[ée]coupage|allotissement)|"
    r"pas\s+pr[ée]vu\s+de\s+(?:d[ée]composition|division|d[ée]coupage|allotissement)|"
    r"n'est\s+pas\s+(?:d[ée]compos[ée]|divis[ée])|allotissement\s+n'[ée]tant\s+pas", _I)

_UNIT = r"(%|pour\s*cent|points?|pts?)(?![a-zà-ÿ])"
_W_RE = r"((?:\d+(?:[.,]\d+)?|" + _NUMW + r"))\s*" + _UNIT
_W2 = re.compile(r"\(\s*(?:pond[ée]ration\s*[:=]?\s*)?" + _W_RE + r"\s*\)", _I)
_W1 = re.compile(r"^(.*?)\s*(?:[:|]|\s[–—-]\s)\s*(?:pond[ée]ration\s*[:=]?\s*)?" + _W_RE, _I)


def _lots(P):
    num = {}
    uniq = set()
    for n, lines, _s in P:
        for l in lines:
            m = _LOT_RE.match(l.strip())
            if m:
                intit = re.sub(r"[\s;.,:]+$", "", m.group(2)).strip()
                if not intit or re.fullmatch(_W_RE + r"\s*", intit, _I):
                    continue
                e = num.setdefault(int(m.group(1)), {"intit": {}, "pages": set()})
                e["pages"].add(n)
                e["intit"].setdefault(_nk(intit), [intit, set()])[1].add(n)
        if _UNIQ.search(" ".join("\n".join(lines).split())):
            uniq.add(n)
    liste = []
    if num:
        for numero in sorted(num):
            e = num[numero]
            intit = [{"valeur": d, "pages": sorted(p)} for d, p in e["intit"].values()]
            liste.append({"numero": numero, "intitules": intit, "pages": sorted(e["pages"]),
                          "conflit": len(intit) > 1})
    elif uniq:
        liste.append({"numero": None, "intitules": [], "pages": sorted(uniq), "conflit": False})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ---------------------------------------------------------------- pièces

_BULLET = re.compile(r"^[-–—•·*▪●◦]\s*(\S.*)$")
_PIECES_CTX = re.compile(r"pi[èe]ces?\b|documents?\s+suivants|dossier\s+(?:à|a)\s+remettre|"
                         r"contenu\s+(?:du|des)\s+(?:dossier|plis)|remet(?:tent|tra|tront|tre)\b|"
                         r"produira|fournir|joindre", _I)
_PH_ATTR = re.compile(r"attributaire|envisag[ée]\s+d'attribuer", _I)
_PH_CAND = re.compile(r"(?:pi[èe]ces?|documents?|titre|dossier|contenu|partie|volet|justificatifs?)\b[^\n]*candidature", _I)
_PH_OFFRE = re.compile(r"titre\s+de\s+l'offre|(?:pi[èe]ces?|documents?)\b[^\n]*\boffres?\b|"
                       r"(?:dossier|partie|volet|contenu)\s+(?:de\s+)?l'offre", _I)


def _phase(s):
    if _PH_ATTR.search(s):
        return "attributaire"
    if _PH_CAND.search(s):
        return "candidature"
    if _PH_OFFRE.search(s):
        return "offre"
    return None


def _nom_piece(txt):
    t = re.sub(r"[\s;.,:]+$", "", txt.strip())
    t = re.sub(r"\s*\((?:obligatoires?|facultati(?:f|ve)s?|optionnel(?:le)?s?)\)", "", t, flags=_I)
    t = re.sub(r",?\s*(?:à\s+titre\s+(?:facultatif|optionnel)|facultati(?:f|ve))\s*$", "", t, flags=_I)
    return re.sub(r"[\s;.,:]+$", "", t)


def _pk(nom):
    return _nk(_nom_piece(nom))


def _pieces(P):
    pieces = {}
    phase = None
    inp = False
    for n, lines, _s in P:
        for raw in lines:
            s = raw.strip()
            if not s or _FOOTER.match(s):
                continue
            m = _BULLET.match(s)
            if m:
                if inp:
                    nom = _nom_piece(m.group(1))
                    if len(nom) >= 2:
                        k = _nk(nom)
                        e = pieces.setdefault(k, {"nom": nom, "pages": set(), "phase": _Acc(),
                                                  "obl": _Acc()})
                        e["pages"].add(n)
                        if phase:
                            e["phase"].add(phase, n)
                        l = m.group(1).lower()
                        if re.search(r"facultati|\bnon\s+obligatoire|optionnel|à\s+titre\s+(?:indicatif|facultatif)", l):
                            e["obl"].add("non obligatoire", n)
                        elif "obligatoire" in l:
                            e["obl"].add("obligatoire", n)
                continue
            if _HEADING.match(s):
                phase = None
                inp = False
            ph = _phase(s)
            if ph:
                phase = ph
                inp = True
            elif _PIECES_CTX.search(s):
                inp = True
            elif not _HEADING.match(s):
                inp = False
                phase = None
    liste = []
    for e in pieces.values():
        liste.append({"nom": e["nom"], "pages": sorted(e["pages"]),
                      "phase": _fait(e["phase"].valeurs(), True),
                      "obligation": _fait(e["obl"].valeurs())})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ---------------------------------------------------------------- critères

_HDR = re.compile(r"crit[èe]re|jugement\s+des\s+offres|jug[ée]es?\s+selon|not[ée]es?\s+sur|"
                  r"s[ée]lection\s+des\s+offres", _I)
_RANK = re.compile(r"class[ée]e?s?\s+(?:par\s+)?(?:ordre|selon)|ordre\s+(?:d[ée]croissant|croissant|"
                   r"d'importance|de\s+priorit[ée])|hi[ée]rarchis", _I)
_CRIT_N = re.compile(r"^crit[èe]re\s*(?:n\s*[°º]\s*|no\.?\s*|num[ée]ro\s*)?(\d+)\s*[:.\-–—)]?\s*(.*)$", _I)
_SUB_NUM = re.compile(r"^\d+(?:\.\d+)+\s*[.)\-–]?\s+(.*)$")
_SUB_LET = re.compile(r"^[a-z]\s*\)\s+(.*)$")
_NUM_M = re.compile(r"^\d+\s*[.)]\s+(.*)$")
_EXCL = re.compile(r"^(?:total|somme|note\s+(?:finale|globale|sur))\b", _I)


def _label(x):
    x = x.strip()
    x = re.sub(r"[\s:;,.\-–—|]+$", "", x)
    return re.sub(r"^[\s:;,.\-–—|]+", "", x)


def _parse_item(s):
    m = _CRIT_N.match(s)
    if m:
        return "crit", m.group(2)
    m = _SUB_NUM.match(s)
    if m:
        return "sub", m.group(1)
    m = _SUB_LET.match(s)
    if m:
        return "sub", m.group(1)
    m = _NUM_M.match(s)
    if m:
        return "num", m.group(1)
    m = _BULLET.match(s)
    if m:
        return "bul", m.group(1)
    return "none", s


def _poids(txt):
    m = _W2.search(txt)
    if m:
        label, nb, unit = txt[:m.start()], m.group(1), m.group(2)
    else:
        m = _W1.match(txt)
        if not m:
            return None
        label, nb, unit = m.group(1), m.group(2), m.group(3)
    if re.fullmatch(r"\d+(?:[.,]\d+)?", nb):
        val = float(nb.replace(",", "."))
    else:
        val = _fr_num(nb)
        if val is None:
            return None
    u = unit.lower()
    unite = "pourcentage" if (u == "%" or u.startswith("pour")) else "points"
    return _label(label), _num(val), unite


def _fait_p(vals):
    par_lot = {}
    for v in vals:
        par_lot.setdefault(v["lot"], set()).add((v["valeur"], v["unite"]))
    conflit = any(len(x) > 1 for x in par_lot.values())
    return {"statut": TROUVE if vals else NON_TROUVE, "valeurs": vals, "conflit": conflit}


def _criteres(P, lots_liste):
    C = {}
    block = False
    ranking = False
    rank_n = 0
    lot_ctx = None
    last_top = None
    top_indent = 0
    for n, lines, _s in P:
        for raw in lines:
            s = raw.strip()
            if not s or _FOOTER.match(s):
                continue
            indent = len(raw) - len(raw.lstrip(" \t"))
            if _HEADING.match(s):
                block = False
                ranking = False
                lot_ctx = None
                last_top = None
                if _HDR.search(s):
                    block = True
                continue
            ml = _LOT_CTX.match(s)
            if ml:
                lot_ctx = int(ml.group(1))
                continue
            kind, rest = _parse_item(s)
            pw = _poids(rest)
            label = None
            weighted = False
            if pw is not None:
                lab = pw[0]
                if lab and len(lab) <= 160 and not _EXCL.match(lab):
                    label, weighted = lab, True
            if label is None and block and kind != "none":
                lab = _label(rest)
                if lab and len(lab) <= 160 and not _EXCL.match(lab):
                    label = lab
            if label is None:
                if _HDR.search(s):
                    block = True
                    if _RANK.search(s):
                        ranking = True
                        rank_n = 0
                else:
                    block = False
                    ranking = False
                    last_top = None
                continue
            if kind in ("crit", "num"):
                level = "top"
            elif kind == "sub":
                level = "sub" if last_top is not None else "top"
            else:
                level = "sub" if (last_top is not None and indent > top_indent) else "top"
            if level == "top":
                key = _nk(label)
                tgt = C.get(key)
                if tgt is None:
                    tgt = {"lib": label, "pages": set(), "pond": {}, "lots": set(), "subs": {}}
                    C[key] = tgt
                last_top = key
                top_indent = indent
                if lot_ctx is not None:
                    tgt["lots"].add(lot_ctx)
            else:
                parent = C[last_top]
                skey = _nk(label)
                tgt = parent["subs"].get(skey)
                if tgt is None:
                    tgt = {"lib": label, "pages": set(), "pond": {}}
                    parent["subs"][skey] = tgt
            tgt["pages"].add(n)
            if weighted:
                tgt["pond"].setdefault((pw[1], pw[2], lot_ctx), set()).add(n)
            elif ranking and level == "top":
                rank_n += 1
                tgt["pond"].setdefault((rank_n, "rang", lot_ctx), set()).add(n)

    connus = [l["numero"] for l in lots_liste if l["numero"] is not None]
    liste = []
    for c in C.values():
        pages = sorted(c["pages"])
        if len(lots_liste) == 1:
            lotvals = [lots_liste[0]["numero"]]
        elif not c["lots"]:
            lotvals = ["tous les lots"]
        elif (connus and c["lots"] >= set(connus)) or (not connus and len(c["lots"]) > 1):
            lotvals = ["tous les lots"]
        else:
            lotvals = sorted(c["lots"])
        subs = []
        for sc in c["subs"].values():
            subs.append({"libelle": sc["lib"], "pages": sorted(sc["pages"]),
                         "ponderation": _fait_p(_pond_vals(sc["pond"]))})
        liste.append({"libelle": c["lib"], "pages": pages,
                      "lot": _fait([{"valeur": v, "pages": list(pages)} for v in lotvals], True),
                      "ponderation": _fait_p(_pond_vals(c["pond"])),
                      "sous_criteres": subs})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


def _pond_vals(pond):
    return [{"valeur": v, "unite": u, "lot": l, "pages": sorted(p)} for (v, u, l), p in pond.items()]


def _type_ponderation(criteres):
    acc = _Acc()
    tmap = {"pourcentage": "pourcentage", "points": "points", "rang": "classement"}
    for c in criteres:
        for v in c["ponderation"]["valeurs"]:
            for p in v["pages"]:
                acc.add(tmap[v["unite"]], p)
    return _fait(acc.valeurs())


# ---------------------------------------------------------------- extraction globale

def _extraire(pages):
    pages = [_prep(p) for p in (pages or [])]
    P = []
    for i, t in enumerate(pages, 1):
        P.append((i, t.split("\n"), _unites(t)))
    dh = _dates_heures(P)
    lots = _lots(P)
    criteres = _criteres(P, lots["liste"])
    return {
        "lots": lots,
        "date_limite": _fait(dh["date_limite"].valeurs()),
        "heure_limite": _fait(dh["heure_limite"].valeurs()),
        "date_questions": _fait(dh["date_questions"].valeurs()),
        "procedure": _fait(_procedures(P).valeurs()),
        "visite_obligatoire": _fait(_visite(P).valeurs()),
        "dates_visite": _fait(dh["dates_visite"].valeurs(), True),
        "variantes": _fait(_variantes(P).valeurs()),
        "validite_offres": _fait(_validite(P).valeurs()),
        "mode_remise": _fait(_mode_remise(P).valeurs()),
        "pieces": _pieces(P),
        "limite_pages": _fait(_limite_pages(P).valeurs()),
        "type_ponderation": _type_ponderation(criteres["liste"]),
        "criteres": criteres,
    }


# ---------------------------------------------------------------- plan et contrôle

_TECH = re.compile(r"technique|qualit[ée]|valeur|m[ée]rite|m[ée]thodolog|moyens", _I)


def _premiere_valeur(fait):
    vs = (fait or {}).get("valeurs") or []
    return vs[0]["valeur"] if vs else None


def _plan(criteres):
    plan = []
    for c in criteres:
        lib = c["libelle"]
        if not _TECH.search(lib):
            continue
        pages = c.get("pages") or [0]
        subs = c.get("sous_criteres") or []
        if subs:
            for s in subs:
                plan.append({"titre": lib + " – " + s["libelle"], "critere": lib,
                             "sous_critere": s["libelle"],
                             "ponderation": _premiere_valeur(s.get("ponderation")),
                             "page_source": min(s.get("pages") or pages), "contenu": ""})
        else:
            plan.append({"titre": lib, "critere": lib, "sous_critere": None,
                         "ponderation": _premiere_valeur(c.get("ponderation")),
                         "page_source": min(pages), "contenu": ""})
    return plan


def controler(dossier):
    crits = (dossier.get("criteres") or {}).get("liste") or []
    plan = dossier.get("plan") or []
    alertes = []
    avec_section = {_nk(s.get("critere", "")) for s in plan}
    for c in crits:
        if _TECH.search(c["libelle"]) and _nk(c["libelle"]) not in avec_section:
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in crits:
        subs = c.get("sous_criteres") or []
        pv = _premiere_valeur(c.get("ponderation"))
        if not subs or pv is None:
            continue
        svs = [_premiere_valeur(s.get("ponderation")) for s in subs]
        if any(v is None for v in svs):
            continue
        unites = [(c["ponderation"]["valeurs"][0]["unite"])] + [s["ponderation"]["valeurs"][0]["unite"] for s in subs]
        if "rang" in unites:
            continue
        if abs(sum(svs) - pv) > 1e-6:
            alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    tp = [v["valeur"] for v in ((dossier.get("type_ponderation") or {}).get("valeurs") or [])]
    if tp == ["pourcentage"]:
        groupes = set()
        for c in crits:
            for v in c["ponderation"]["valeurs"]:
                groupes.add(v["lot"])
        if not groupes:
            groupes = {None}
        faux = False
        for g in groupes:
            total = 0
            nb = 0
            for c in crits:
                vs = [v for v in c["ponderation"]["valeurs"] if v["unite"] == "pourcentage"]
                pick = [v for v in vs if v["lot"] == g]
                if not pick and g is not None:
                    pick = [v for v in vs if v["lot"] is None]
                if pick:
                    total += pick[0]["valeur"]
                    nb += 1
            if nb and abs(total - 100) > 1e-6:
                faux = True
        if faux:
            alertes.append({"type": "total différent de 100 %", "objet": "critères"})
    return alertes


# ---------------------------------------------------------------- vérification

_FAITS_UNIQUES = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                  "variantes", "validite_offres", "mode_remise", "limite_pages", "type_ponderation"]


def _filtre_fait(prop, ref, multi=False):
    rm = {_cle(v["valeur"]): v for v in (ref or {}).get("valeurs", [])}
    out = []
    vus = set()
    if isinstance(prop, dict):
        for v in prop.get("valeurs") or []:
            try:
                k = _cle(v["valeur"])
            except (KeyError, TypeError):
                continue
            if k in rm and k not in vus:
                vus.add(k)
                out.append({"valeur": rm[k]["valeur"], "pages": list(rm[k]["pages"])})
    return _fait(out, multi)


def _filtre_pond(prop, ref):
    def cle(v):
        return _cle([v.get("valeur"), v.get("unite"), v.get("lot")])
    rm = {cle(v): v for v in (ref or {}).get("valeurs", [])}
    out = []
    vus = set()
    if isinstance(prop, dict):
        for v in prop.get("valeurs") or []:
            k = cle(v)
            if k in rm and k not in vus:
                vus.add(k)
                r = rm[k]
                out.append({"valeur": r["valeur"], "unite": r["unite"], "lot": r["lot"],
                            "pages": list(r["pages"])})
    return _fait_p(out)


def _filtre_lots(prop, ref):
    rm = {l["numero"]: l for l in ref["liste"]}
    out = []
    vus = set()
    for l in (prop or {}).get("liste") or []:
        num = l.get("numero")
        r = rm.get(num)
        if r is None or num in vus:
            continue
        vus.add(num)
        rim = {_nk(i["valeur"]): i for i in r["intitules"]}
        intit = []
        ks = set()
        for i in l.get("intitules") or []:
            k = _nk(i.get("valeur", ""))
            if k in rim and k not in ks:
                ks.add(k)
                intit.append({"valeur": rim[k]["valeur"], "pages": list(rim[k]["pages"])})
        out.append({"numero": num, "intitules": intit, "pages": list(r["pages"]),
                    "conflit": len(intit) > 1})
    return {"statut": TROUVE if out else NON_TROUVE, "liste": out}


def _filtre_pieces(prop, ref):
    rm = {_pk(p["nom"]): p for p in ref["liste"]}
    out = []
    vus = set()
    for p in (prop or {}).get("liste") or []:
        k = _pk(p.get("nom", ""))
        r = rm.get(k)
        if r is None or k in vus:
            continue
        vus.add(k)
        out.append({"nom": r["nom"], "pages": list(r["pages"]),
                    "phase": _filtre_fait(p.get("phase"), r["phase"], True),
                    "obligation": _filtre_fait(p.get("obligation"), r["obligation"])})
    return {"statut": TROUVE if out else NON_TROUVE, "liste": out}


def _filtre_criteres(prop, ref):
    rm = {_nk(c["libelle"]): c for c in ref["liste"]}
    out = []
    vus = set()
    for c in (prop or {}).get("liste") or []:
        k = _nk(c.get("libelle", ""))
        r = rm.get(k)
        if r is None or k in vus:
            continue
        vus.add(k)
        rsm = {_nk(s["libelle"]): s for s in r["sous_criteres"]}
        subs = []
        svus = set()
        for s in c.get("sous_criteres") or []:
            sk = _nk(s.get("libelle", ""))
            rs = rsm.get(sk)
            if rs is None or sk in svus:
                continue
            svus.add(sk)
            subs.append({"libelle": rs["libelle"], "pages": list(rs["pages"]),
                         "ponderation": _filtre_pond(s.get("ponderation"), rs["ponderation"])})
        out.append({"libelle": r["libelle"], "pages": list(r["pages"]),
                    "lot": _filtre_fait(c.get("lot"), r["lot"], True),
                    "ponderation": _filtre_pond(c.get("ponderation"), r["ponderation"]),
                    "sous_criteres": subs})
    return {"statut": TROUVE if out else NON_TROUVE, "liste": out}


def _verifier(dossier, ref):
    out = copy.deepcopy(dossier) if isinstance(dossier, dict) else {}
    for k in _FAITS_UNIQUES:
        out[k] = _filtre_fait(out.get(k), ref[k])
    out["dates_visite"] = _filtre_fait(out.get("dates_visite"), ref["dates_visite"], True)
    out["lots"] = _filtre_lots(out.get("lots"), ref["lots"])
    out["pieces"] = _filtre_pieces(out.get("pieces"), ref["pieces"])
    out["criteres"] = _filtre_criteres(out.get("criteres"), ref["criteres"])
    out["plan"] = _plan(out["criteres"]["liste"])
    out["controle"] = {"alertes": controler(out)}
    return out


def verifier(dossier, pages):
    return _verifier(dossier, _extraire(pages))


def analyser(pages):
    ref = _extraire(pages)
    return _verifier(ref, ref)
