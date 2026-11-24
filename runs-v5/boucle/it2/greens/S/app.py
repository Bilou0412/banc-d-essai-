"""Lecture d'un règlement de la consultation (RC) : règles écrites, expressions régulières."""
import copy
import json
import re
import unicodedata

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"

# ------------------------------------------------------------------ outils


def _noaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _prep(t):
    if not isinstance(t, str):
        t = "" if t is None else str(t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    for c in ("\u00a0", "\u202f", "\u2009", "\u2007"):
        t = t.replace(c, " ")
    return t.replace("\u2019", "'").replace("\u2018", "'")


def _norm(s):
    return re.sub(r"\s+", " ", s.replace("\u2019", "'")).strip().lower()


def _key(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


class _Acc:
    def __init__(self):
        self.d = {}

    def add(self, v, p):
        k = _key(v)
        if k not in self.d:
            self.d[k] = [v, set()]
        self.d[k][1].add(p)

    def valeurs(self):
        return [{"valeur": v, "pages": sorted(ps)} for v, ps in self.d.values()]


def _fait(vs, multi=True):
    if isinstance(vs, _Acc):
        vs = vs.valeurs()
    return {"statut": TROUVE if vs else NON_TROUVE, "valeurs": vs,
            "conflit": bool(multi and len(vs) > 1)}


def _faitp(vs):
    par_lot = {}
    for v in vs:
        par_lot.setdefault(v["lot"], set()).add((v["valeur"], v["unite"]))
    conflit = any(len(x) > 1 for x in par_lot.values())
    return {"statut": TROUVE if vs else NON_TROUVE, "valeurs": vs, "conflit": conflit}


# ------------------------------------------------------------------ nombres en lettres

_NW = {"zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
       "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13,
       "quatorze": 14, "quinze": 15, "seize": 16, "trente": 30, "quarante": 40,
       "cinquante": 50, "soixante": 60}
_TOK = (r"(?:un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|"
        r"seize|vingts?|trente|quarante|cinquante|soixante|cents?)(?![\wéèêûô])")
NUMW = r"(?<![\wéèêûô])" + _TOK + r"(?:[\s\-]+(?:et[\s\-]+)?" + _TOK + r")*"


def _parse_fr(s):
    toks = [t for t in re.split(r"[\s\-]+", s.lower().strip()) if t and t != "et"]
    if not toks:
        return None
    cur = 0
    prev = None
    for t in toks:
        if t in ("cent", "cents"):
            cur = (cur or 1) * 100 if cur < 100 else cur + 100
        elif t in ("vingt", "vingts"):
            cur += 76 if prev == "quatre" else 20
        elif t in _NW:
            cur += _NW[t]
        else:
            return None
        prev = t
    return cur


def _num(s):
    s = s.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", s):
        f = float(s.replace(",", "."))
        return int(f) if f == int(f) else f
    return _parse_fr(s)


# ------------------------------------------------------------------ dates et heures

_MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
         "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
_RE_DNUM = re.compile(r"(?<![\d/.\-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")
_RE_DLET = re.compile(r"(?<!\d)(\d{1,2})(?:er)?\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|"
                      r"ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\s+(\d{4})(?!\d)", re.I)


def _fmt_date(j, m, a):
    j, m, a = int(j), int(m), int(a)
    if not (1 <= j <= 31 and 1 <= m <= 12):
        return None
    if a < 100:
        a += 2000
    return f"{j:02d}/{m:02d}/{a:04d}"


def _dates(s):
    out = []
    for m in _RE_DNUM.finditer(s):
        v = _fmt_date(m.group(1), m.group(2), m.group(3))
        if v:
            out.append((m.start(), m.end(), v))
    for m in _RE_DLET.finditer(s):
        v = _fmt_date(m.group(1), _MOIS[_noaccent(m.group(2).lower())], m.group(3))
        if v:
            out.append((m.start(), m.end(), v))
    return sorted(out)


_RE_TNUM = re.compile(r"(?<![\d:/.])(\d{1,2})\s*h(?:eures?)?(?:\s*(\d{2}))?(?!\w)|"
                      r"(?<![\d:/.])(\d{1,2}):(\d{2})(?!\d)", re.I)
_HW = {"une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
       "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
       "seize": 16, "dix-sept": 17, "dix-huit": 18, "dix-neuf": 19, "vingt": 20,
       "vingt-et-une": 21, "vingt-deux": 22, "vingt-trois": 23}
_MW = {"trente": 30, "quinze": 15, "quarante-cinq": 45, "vingt": 20, "dix": 10, "cinq": 5,
       "demi": 30, "demie": 30, "quart": 15}
_RE_TLET = re.compile(r"(?<![\wéèêû])(vingt[\s\-]+et[\s\-]+une|vingt[\s\-]+(?:deux|trois)|"
                      r"dix[\s\-]+(?:sept|huit|neuf)|vingt|une|deux|trois|quatre|cinq|six|sept|huit|"
                      r"neuf|dix|onze|douze|treize|quatorze|quinze|seize)\s+heures?"
                      r"(?:\s+(?:et\s+(demie?|quart)|(trente|quinze|quarante[\s\-]+cinq|vingt|dix|cinq|\d{2})))?"
                      r"(?!\w)", re.I)
_RE_MIDI = re.compile(r"(?<![\w\-])midi(?![\w\-])", re.I)


def _times(s):
    out = []
    for m in _RE_TNUM.finditer(s):
        if m.group(1) is not None:
            h, mi = int(m.group(1)), int(m.group(2) or 0)
        else:
            h, mi = int(m.group(3)), int(m.group(4))
        if h <= 23 and mi <= 59:
            out.append((m.start(), m.end(), f"{h:02d}:{mi:02d}"))
    for m in _RE_TLET.finditer(s):
        h = _HW[re.sub(r"[\s\-]+", "-", m.group(1).lower())]
        extra = (m.group(2) or m.group(3) or "").lower()
        extra = re.sub(r"[\s\-]+", "-", extra)
        mi = int(extra) if extra.isdigit() else _MW.get(extra, 0)
        if mi <= 59:
            out.append((m.start(), m.end(), f"{h:02d}:{mi:02d}"))
    for m in _RE_MIDI.finditer(s):
        out.append((m.start(), m.end(), "12:00"))
    return sorted(out)


def _time_after(line, pos):
    rest = line[pos:]
    for st, _e, v in _times(rest):
        if st > 30:
            return None
        if re.search(r"[.;]\s", rest[:st]):
            return None
        return v
    return None


# ------------------------------------------------------------------ découpage

def _logical_lines(text):
    out = []
    prev_raw = None
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            prev_raw = None
            continue
        if (out and prev_raw is not None and s[0].islower() and not re.match(r"^[a-z]\)", s)
                and not out[-1].rstrip().endswith((".", ";", ":", "!", "?"))):
            out[-1] = out[-1] + " " + s
        else:
            out.append(s)
        prev_raw = s
    return out


def _sentences(line, seps=r"[.;!?]"):
    return [x for x in re.split(r"(?<=" + seps + r")\s+", line) if x.strip()]


# ------------------------------------------------------------------ faits simples

_KW_LIM = re.compile(
    r"limites?\s+(?:de|d')\s*(?:la\s+)?(?:remise|r[ée]ception|d[ée]p[ôo]t)|"
    r"(?:remise|r[ée]ception|d[ée]p[ôo]t)\s+des\s+(?:offres|plis)|"
    r"(?:offres|plis)\s+(?:devront|doivent|pourront|seront|sont\s+attendu)|"
    r"parvenir\s+avant|jusqu'au|heures?\s+limites?|date\s+limite", re.I)
_QUEST = re.compile(r"questions?|renseignements?\s+compl[ée]mentaires|demandes?\s+de\s+renseignements", re.I)
_DELAI = re.compile(r"(?<![\w])(?:\d+|" + NUMW + r")\s*(?:\(\s*\d+\s*\)\s*)?jours?\s+"
                    r"(?:calendaires\s+|ouvr[ée]s\s+|francs\s+)?avant\s+la\s+date\s+limite"
                    r"(?:\s+de\s+(?:remise|r[ée]ception|d[ée]p[ôo]t)\s+des\s+(?:offres|plis))?", re.I)
_NEG = re.compile(r"\b(?:ne|n')\s*(?:\w+[\s']+){0,5}?pas\b|\baucun|\binterdit|"
                  r"\bnon\s+(?:autoris|admis|accept)|\bsans\b|\brefus", re.I)
_ATTEST_VISITE = re.compile(r"attestations?\s+de\s+visite", re.I)
_KW_VAL = re.compile(
    r"validit[ée]\s+des\s+offres|offres?\s+(?:restent?|sont|demeurent?)\s+(?:valables?|valides?|maintenues?)|"
    r"valables?\s+(?:pendant|durant)|(?:d[ée]lai|dur[ée]e)\s+de\s+validit[ée]", re.I)
_DUREE = re.compile(r"(?<![\w])(\d+|" + NUMW + r")\s*(?:\(\s*(\d+)\s*\)\s*)?(jours?|mois)(?![\w])", re.I)
_PAGES = re.compile(r"(?<![\w])(\d+|" + NUMW + r")\s*(?:\(\s*(\d+)\s*\)\s*)?pages?(?![\w])", re.I)
_ELEC = re.compile(r"voie\s+(?:[ée]lectronique|d[ée]mat[ée]rialis[ée]e|num[ée]rique)|d[ée]mat[ée]rialis|"
                   r"[ée]lectroniquement|plateforme|profil\s+d'acheteur", re.I)
_PAPIER = re.compile(r"papier|pli\s+cacheté|récépissé", re.I)
_CTX_REMISE = re.compile(r"offres?|plis?\b|remise|transmi|d[ée]p[ôo]t|d[ée]pos", re.I)


def _simples(pages):
    A = {k: _Acc() for k in ("date_limite", "heure_limite", "date_questions", "procedure",
                              "visite_obligatoire", "dates_visite", "variantes", "validite_offres",
                              "mode_remise", "limite_pages")}
    for pn, texte in enumerate(pages, 1):
        lignes = _logical_lines(texte)
        for idx, ln in enumerate(lignes):
            low = ln.lower()
            nxt = lignes[idx + 1] if idx + 1 < len(lignes) else ""
            prev = lignes[idx - 1] if idx > 0 else ""
            sans_att = _ATTEST_VISITE.sub("", low)
            visite = "visite" in sans_att
            question = bool(_QUEST.search(ln))
            lim = bool(_KW_LIM.search(ln))

            # ---- date / heure limite
            if lim and not question and not visite:
                chunk = ln
                ds = _dates(chunk)
                if (not ds and not _times(chunk) and not re.search(r"\d", chunk)
                        and len(chunk) <= 70 and nxt and not _QUEST.search(nxt)):
                    chunk = nxt
                    ds = _dates(chunk)
                for _s, e, v in ds:
                    A["date_limite"].add(v, pn)
                    t = _time_after(chunk, e)
                    if t:
                        A["heure_limite"].add(t, pn)
                if not ds and re.search(r"heure", ln, re.I):
                    ts = _times(chunk)
                    if ts:
                        A["heure_limite"].add(ts[0][2], pn)

            # ---- date questions
            if question:
                ds = _dates(ln)
                for _s, _e, v in ds:
                    A["date_questions"].add(v, pn)
                if not ds:
                    m = _DELAI.search(ln)
                    if m:
                        A["date_questions"].add(m.group(0), pn)

            # ---- procédure
            if re.search(r"proc[ée]dure\s+adapt[ée]e", ln, re.I) or re.search(r"(?<![\w\-])MAPA(?![\w\-])", ln):
                A["procedure"].add("procédure adaptée", pn)
            for m in re.finditer(r"appel\s+d'offres\s+(ouvert|restreint)", ln, re.I):
                A["procedure"].add("appel d'offres " + m.group(1).lower(), pn)
            if re.search(r"dialogue\s+comp[ée]titif", ln, re.I):
                A["procedure"].add("dialogue compétitif", pn)
            if re.search(r"proc[ée]dure\s+concurrentielle\s+avec\s+n[ée]gociation", ln, re.I):
                A["procedure"].add("procédure concurrentielle avec négociation", pn)

            # ---- visite (caractère)
            for sent in _sentences(sans_att):
                if "visite" not in sent:
                    continue
                if re.search(r"facultati|non[\s\-]+obligatoire|pas\s+obligatoire|optionnel", sent):
                    A["visite_obligatoire"].add("non", pn)
                elif "obligatoire" in sent:
                    A["visite_obligatoire"].add("oui", pn)

            # ---- dates de visite
            if visite:
                ctx = True
            else:
                ctx = ("visite" in _ATTEST_VISITE.sub("", prev.lower())
                       and bool(re.search(r"aura\s+lieu|dates?\b|cr[ée]neau|se\s+d[ée]roul|organis", low))
                       and not lim and not question)
            if ctx:
                for _s, _e, v in _dates(ln):
                    A["dates_visite"].add(v, pn)

            # ---- variantes, validité, limite de pages
            for sent in _sentences(ln):
                sl = sent.lower()
                if "variante" in sl:
                    if _NEG.search(sl):
                        A["variantes"].add("non autorisées", pn)
                    elif re.search(r"autoris|admis|accept|peuvent\s+(?:pr[ée]senter|proposer|remettre)|"
                                   r"possible|permis", sl):
                        A["variantes"].add("autorisées", pn)
                mk = _KW_VAL.search(sent)
                if mk:
                    md = _DUREE.search(sent, mk.end())
                    if md:
                        n = int(md.group(2)) if md.group(2) else _num(md.group(1))
                        if n is not None:
                            u = "mois" if md.group(3).lower() == "mois" else "jours"
                            A["validite_offres"].add({"nombre": n, "unite": u}, pn)
                if re.search(r"m[ée]moire\s+technique", sl):
                    mp = _PAGES.search(sent)
                    if mp:
                        n = int(mp.group(2)) if mp.group(2) else _num(mp.group(1))
                        if n is not None:
                            A["limite_pages"].add(n, pn)

            # ---- mode de remise
            for cl in _sentences(ln, r"[.;:!?]"):
                if _QUEST.search(cl) or not _CTX_REMISE.search(cl) or _NEG.search(cl):
                    continue
                if _ELEC.search(cl):
                    A["mode_remise"].add("électronique", pn)
                if _PAPIER.search(cl):
                    A["mode_remise"].add("papier", pn)
    return A


# ------------------------------------------------------------------ lots

_RE_LOT = re.compile(r"^(?:[-•*–·]\s*)?lot\s*(?:n\s*[°o]\s*|num[ée]ro\s*)?(\d{1,3})\s*[:\-–—.]\s*(\S.*)$", re.I)
_RE_UNIQUE = re.compile(
    r"lot\s+unique|(?:n'est|ne\s+sera)\s+pas\s+(?:allot|pr[ée]vu\s+de\s+(?:d[ée]composition|allotissement)|d[ée]compos)|"
    r"non\s+allot|en\s+un\s+(?:seul\s+)?lot|un\s+seul\s+lot|sans\s+allotissement|"
    r"pas\s+(?:de\s+)?(?:d[ée]composition\s+en\s+lots|d'allotissement)", re.I)


def _lots(pages):
    num = {}
    uniq = set()
    for pn, text in enumerate(pages, 1):
        for raw in text.split("\n"):
            m = _RE_LOT.match(raw.strip())
            if m:
                n = int(m.group(1))
                titre = m.group(2).strip().rstrip(" ;.,").strip()
                e = num.setdefault(n, {"pages": set(), "int": {}})
                e["pages"].add(pn)
                if titre:
                    k = _norm(titre)
                    if k not in e["int"]:
                        e["int"][k] = [titre, set()]
                    e["int"][k][1].add(pn)
        for ln in _logical_lines(text):
            for sent in _sentences(ln):
                if _RE_UNIQUE.search(sent):
                    uniq.add(pn)
    liste = []
    if num:
        for n in sorted(num):
            e = num[n]
            ints = [{"valeur": t, "pages": sorted(ps)} for t, ps in e["int"].values()]
            liste.append({"numero": n, "intitules": ints, "pages": sorted(e["pages"]),
                          "conflit": len(ints) > 1})
    elif uniq:
        liste.append({"numero": None, "intitules": [], "pages": sorted(uniq), "conflit": False})
    return {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}


# ------------------------------------------------------------------ pièces, critères

_RE_BUL = re.compile(r"^(\s*)[-•*–·▪]\s+(\S.*)$")
_RE_CRITN = re.compile(r"^(\s*)crit[èe]re\s*(?:n\s*[°o]?\s*)?(\d+)\s*[:.\-–—)]\s*(\S.*)$", re.I)
_RE_NUMSUB = re.compile(r"^(\s*)(\d+(?:\.\d+)+)\s*[.)]?\s+(\S.*)$")
_RE_LETSUB = re.compile(r"^(\s*)([a-zA-Z])\s*\)\s+(\S.*)$")
_RE_NUMTOP = re.compile(r"^(\s*)(\d+)\s*[.)]\s+(\S.*)$")
_RE_ROW = re.compile(r"^(\s*)([^|\s][^|]*)\|(.+)$")
_RE_POND = re.compile(r"(?<![\w])(\d+(?:[.,]\d+)?|" + NUMW + r")\s*(%|pour\s*cent|points?|pts?)(?![\w])", re.I)
_CRIT_HEAD = re.compile(r"crit[èe]res?\b|jugement\s+des\s+offres|pond[ée]rations?\b|"
                        r"class[ée]s?\s+par\s+ordre|not[ée]es?\s+sur\b", re.I)
_RANK_HEAD = re.compile(r"class[ée]s?\s+par\s+ordre|ordre\s+(?:d[ée]croissant|d'importance)", re.I)
_PIECE_HEAD = re.compile(r"pi[èe]ces?\b|documents?\s+suivants|dossier\s+(?:[àa]\s+remettre|comprenant)|"
                         r"contenu\s+(?:du\s+dossier|des\s+plis)|produira|remettra|remettent", re.I)
_TYPE = {"pourcentage": "pourcentage", "points": "points", "rang": "classement"}


def _phase_of(low):
    if re.search(r"attributaire|envisag[ée]\s+d'attribuer|titulaire\s+pressenti", low):
        return "attributaire"
    c = re.search(r"candidature", low)
    o = re.search(r"\boffre\b", low)
    if c and not o:
        return "candidature"
    if o and not c:
        return "offre"
    return None


def _clean_label(l):
    l = l.split("|")[0].strip()
    prev = None
    while prev != l:
        prev = l
        l = re.sub(r"[\s:(|\-–—,.;]+$", "", l)
        l = re.sub(r"\s*(?:pond[ée]ration|pond[ée]r[ée]e?|not[ée]e?\s+sur|coefficient|note\s+sur)$", "", l,
                   flags=re.I)
    l = re.split(r"\s*[,;]\s*(?:appr[ée]ci|d[ée]compos|d[ée]taill)", l, flags=re.I)[0]
    return l.strip()


def _parse_content(content):
    m = _RE_POND.search(content)
    pond = None
    if m:
        v = _num(m.group(1))
        if v is not None:
            g = m.group(2).lower()
            pond = (v, "pourcentage" if (g.startswith("%") or g.startswith("pour")) else "points")
        label = _clean_label(content[:m.start()])
    else:
        label = _clean_label(content)
    return label, pond


def _item(raw):
    m = _RE_CRITN.match(raw)
    if m:
        return ("top", len(m.group(1)), m.group(2), m.group(3))
    m = _RE_NUMSUB.match(raw)
    if m:
        return ("sub", len(m.group(1)), None, m.group(3))
    m = _RE_LETSUB.match(raw)
    if m:
        return ("sub", len(m.group(1)), None, m.group(3))
    m = _RE_NUMTOP.match(raw)
    if m:
        return ("top", len(m.group(1)), m.group(2), m.group(3))
    m = _RE_BUL.match(raw)
    if m:
        return ("bul", len(m.group(1)), None, m.group(2))
    m = _RE_ROW.match(raw)
    if m:
        return ("row", len(m.group(1)), None, raw.strip())
    return None


def _structure(pages):
    pieces = {}
    crits = {}
    typeacc = _Acc()
    mode = None
    phase = None
    lot_cur = None
    rank = False
    rank_n = 0
    parent = None
    parent_indent = 0
    lotmarks = set()
    for pn, text in enumerate(pages, 1):
        for raw in text.split("\n"):
            s = raw.strip()
            if not s:
                continue
            low = s.lower()
            if re.match(r"(?:article|annexe)\b", low):
                mode = None
                phase = None
                lot_cur = None
                rank = False
                parent = None
            bul = _RE_BUL.match(raw)
            if bul and mode == "pieces":
                item = bul.group(2).strip()
                fac = re.search(r"\(\s*facultati(?:f|ve)s?\s*\)|à\s+titre\s+facultatif|\bfacultati(?:f|ve)\b|"
                                r"optionnel|non[\s\-]+obligatoire", item, re.I)
                obl = re.search(r"\bobligatoires?\b", item, re.I)
                name = re.sub(r"\s*\(\s*(?:obligatoires?|facultati(?:f|ve)s?)\s*\)", "", item, flags=re.I)
                name = re.sub(r",?\s*à\s+titre\s+facultatif", "", name, flags=re.I)
                name = name.strip().rstrip(" ;.,").strip()
                if name:
                    k = _norm(name)
                    p = pieces.setdefault(k, {"nom": name, "pages": set(), "phase": _Acc(), "obl": _Acc()})
                    p["pages"].add(pn)
                    if phase:
                        p["phase"].add(phase, pn)
                    if fac:
                        p["obl"].add("non obligatoire", pn)
                    elif obl:
                        p["obl"].add("obligatoire", pn)
                continue
            if _CRIT_HEAD.search(low):
                if mode != "criteres":
                    parent = None
                mode = "criteres"
                phase = None
                if _RANK_HEAD.search(low):
                    rank = True
                for c in crits.values():
                    if _norm(c["libelle"]) in _norm(s):
                        parent = c
                        parent_indent = 0
            elif _PIECE_HEAD.search(low):
                mode = "pieces"
                phase = _phase_of(low)
                continue
            if mode == "pieces":
                if _phase_of(low) and (s.endswith(":") or len(s) < 90):
                    phase = _phase_of(low)
                continue
            if mode is None and crits:
                it0 = _item(raw)
                if it0 and it0[0] == "top":
                    l0, p0 = _parse_content(it0[3])
                    if l0 and p0 is not None and _norm(l0) in crits:
                        mode = "criteres"
                        parent = None
            if mode != "criteres":
                continue
            ml = re.match(r"lot\s*(?:n\s*[°o]\s*)?(\d+)\s*:?\s*$", low)
            if ml:
                lot_cur = int(ml.group(1))
                lotmarks.add(lot_cur)
                parent = None
                continue
            it = _item(raw)
            if not it:
                continue
            kind, indent, numtxt, content = it
            label, pond = _parse_content(content)
            if not label or len(label) > 120:
                continue
            if kind == "row" and (pond is None or _norm(label) in ("critère", "critères", "critere", "criteres")):
                continue
            if pond is None and _norm(label) in ("critère", "critères", "critere", "criteres"):
                continue
            is_sub = parent is not None and (kind == "sub" or (kind in ("bul", "row") and indent > parent_indent))
            if is_sub:
                k = _norm(label)
                sc = parent["subs"].setdefault(k, {"libelle": label, "pages": set(), "pond": _Acc()})
                sc["pages"].add(pn)
                if pond:
                    sc["pond"].add({"valeur": pond[0], "unite": pond[1], "lot": lot_cur}, pn)
                continue
            k = _norm(label)
            c = crits.setdefault(k, {"libelle": label, "pages": set(), "lots": {}, "pond": _Acc(), "subs": {}})
            c["pages"].add(pn)
            c["lots"].setdefault(lot_cur, set()).add(pn)
            parent = c
            parent_indent = indent
            if pond:
                c["pond"].add({"valeur": pond[0], "unite": pond[1], "lot": lot_cur}, pn)
                typeacc.add(_TYPE[pond[1]], pn)
            elif rank:
                rank_n += 1
                v = int(numtxt) if numtxt and numtxt.isdigit() else rank_n
                c["pond"].add({"valeur": v, "unite": "rang", "lot": lot_cur}, pn)
                typeacc.add("classement", pn)
    return pieces, crits, typeacc, lotmarks


def _pond_vals(acc):
    out = []
    for v, ps in acc.d.values():
        e = dict(v)
        e["pages"] = sorted(ps)
        out.append(e)
    return out


# ------------------------------------------------------------------ assemblage

_FAITS = ("date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
          "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
          "type_ponderation")


def _extraire(pages):
    pages = [_prep(p) for p in pages]
    A = _simples(pages)
    d = {}
    for k, acc in A.items():
        d[k] = _fait(acc, multi=(k != "dates_visite"))
    lots = _lots(pages)
    pieces, crits, typeacc, lotmarks = _structure(pages)
    d["type_ponderation"] = _fait(typeacc)
    d["lots"] = lots
    plist = []
    for p in pieces.values():
        plist.append({"nom": p["nom"], "pages": sorted(p["pages"]),
                      "phase": _fait(p["phase"]), "obligation": _fait(p["obl"])})
    d["pieces"] = {"statut": TROUVE if plist else NON_TROUVE, "liste": plist}

    nums = {x["numero"] for x in lots["liste"] if x["numero"] is not None} | set(lotmarks)
    clist = []
    for c in crits.values():
        lk = {k: v for k, v in c["lots"].items() if k is not None}
        if lk:
            if nums and set(lk) >= nums:
                lot_f = _fait([{"valeur": "tous les lots", "pages": sorted(c["pages"])}])
            else:
                lot_f = _fait([{"valeur": n, "pages": sorted(lk[n])} for n in sorted(lk)])
        elif len(lots["liste"]) == 1:
            lot_f = _fait([{"valeur": lots["liste"][0]["numero"], "pages": lots["liste"][0]["pages"]}])
        elif lots["liste"]:
            lot_f = _fait([{"valeur": "tous les lots", "pages": sorted(c["pages"])}])
        else:
            lot_f = _fait([])
        subs = []
        for s in c["subs"].values():
            subs.append({"libelle": s["libelle"], "pages": sorted(s["pages"]),
                         "ponderation": _faitp(_pond_vals(s["pond"]))})
        clist.append({"libelle": c["libelle"], "pages": sorted(c["pages"]), "lot": lot_f,
                      "ponderation": _faitp(_pond_vals(c["pond"])), "sous_criteres": subs})
    d["criteres"] = {"statut": TROUVE if clist else NON_TROUVE, "liste": clist}
    return d


_TECH = re.compile(r"technique|qualit|m[ée]rite|valeur|m[ée]thodolog|performance|environnement|insertion|"
                   r"d[ée]veloppement\s+durable", re.I)
_PRIX = re.compile(r"prix|co[ûu]t|tarif|financi|montant|redevance", re.I)


def _est_tech(lib):
    return bool(_TECH.search(lib)) and not _PRIX.search(lib)


def _plan(d):
    plan = []
    for c in d["criteres"]["liste"]:
        if not _est_tech(c["libelle"]):
            continue
        pv = c["ponderation"]["valeurs"]
        page_c = min(c["pages"]) if c["pages"] else 1
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                sp = s["ponderation"]["valeurs"]
                plan.append({"titre": c["libelle"] + " – " + s["libelle"], "critere": c["libelle"],
                             "sous_critere": s["libelle"],
                             "ponderation": sp[0]["valeur"] if sp else None,
                             "page_source": min(s["pages"]) if s["pages"] else page_c, "contenu": ""})
        else:
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": pv[0]["valeur"] if pv else None,
                         "page_source": page_c, "contenu": ""})
    return plan


def _alertes(d):
    al = []
    crits = d["criteres"]["liste"]
    avec_section = {s["critere"] for s in d.get("plan", [])}
    for c in crits:
        if _est_tech(c["libelle"]) and c["libelle"] not in avec_section:
            al.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in crits:
        if not c["sous_criteres"]:
            continue
        for pv in c["ponderation"]["valeurs"]:
            tot = 0
            ok = True
            for s in c["sous_criteres"]:
                m = [v for v in s["ponderation"]["valeurs"]
                     if v["lot"] == pv["lot"] and v["unite"] == pv["unite"]]
                if not m:
                    ok = False
                    break
                tot += m[0]["valeur"]
            if ok and abs(tot - pv["valeur"]) > 1e-6:
                al.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
                break
    types = [v["valeur"] for v in d["type_ponderation"]["valeurs"]]
    if "pourcentage" in types:
        groupes = {}
        for c in crits:
            vus = set()
            for v in c["ponderation"]["valeurs"]:
                if v["unite"] != "pourcentage" or v["lot"] in vus:
                    continue
                vus.add(v["lot"])
                groupes[v["lot"]] = groupes.get(v["lot"], 0) + v["valeur"]
        if any(abs(round(t, 6) - 100) > 1e-6 for t in groupes.values()):
            al.append({"type": "total différent de 100 %", "objet": "critères"})
    return al


def _finaliser(d):
    d["plan"] = _plan(d)
    d["controle"] = {"alertes": _alertes(d)}
    return d


def analyser(pages):
    return _finaliser(_extraire(list(pages)))


def controler(dossier):
    return _alertes(dossier)


def verifier(dossier, pages):
    ext = _extraire(list(pages))
    out = copy.deepcopy(ext)
    for k in _FAITS:
        prop = dossier.get(k) or {}
        cles = {_key(v.get("valeur")) for v in prop.get("valeurs", [])}
        vs = [v for v in ext[k]["valeurs"] if _key(v["valeur"]) in cles]
        out[k] = _fait(vs, multi=(k != "dates_visite"))
    prop_lots = {x.get("numero"): x for x in (dossier.get("lots") or {}).get("liste", [])}
    liste = []
    for x in ext["lots"]["liste"]:
        if x["numero"] not in prop_lots:
            continue
        x = copy.deepcopy(x)
        pi = prop_lots[x["numero"]].get("intitules")
        if pi is not None:
            ok = {i.get("valeur") for i in pi}
            x["intitules"] = [i for i in x["intitules"] if i["valeur"] in ok]
        x["conflit"] = len(x["intitules"]) > 1
        liste.append(x)
    out["lots"] = {"statut": TROUVE if liste else NON_TROUVE, "liste": liste}
    cles = {_norm(p.get("nom", "")) for p in (dossier.get("pieces") or {}).get("liste", [])}
    pl = [p for p in ext["pieces"]["liste"] if _norm(p["nom"]) in cles]
    out["pieces"] = {"statut": TROUVE if pl else NON_TROUVE, "liste": pl}
    prop_c = {_norm(c.get("libelle", "")): c for c in (dossier.get("criteres") or {}).get("liste", [])}
    cl = []
    for c in ext["criteres"]["liste"]:
        pc = prop_c.get(_norm(c["libelle"]))
        if pc is None:
            continue
        c = copy.deepcopy(c)
        pk = {(v.get("valeur"), v.get("unite"), v.get("lot"))
              for v in (pc.get("ponderation") or {}).get("valeurs", [])}
        c["ponderation"] = _faitp([v for v in c["ponderation"]["valeurs"]
                                   if (v["valeur"], v["unite"], v["lot"]) in pk])
        ps = {_norm(s.get("libelle", "")): s for s in pc.get("sous_criteres", [])}
        subs = []
        for s in c["sous_criteres"]:
            sp = ps.get(_norm(s["libelle"]))
            if sp is None:
                continue
            sk = {(v.get("valeur"), v.get("unite"), v.get("lot"))
                  for v in (sp.get("ponderation") or {}).get("valeurs", [])}
            s["ponderation"] = _faitp([v for v in s["ponderation"]["valeurs"]
                                       if (v["valeur"], v["unite"], v["lot"]) in sk])
            subs.append(s)
        c["sous_criteres"] = subs
        cl.append(c)
    out["criteres"] = {"statut": TROUVE if cl else NON_TROUVE, "liste": cl}
    return _finaliser(out)
