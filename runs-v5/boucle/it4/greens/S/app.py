"""Lecture déterministe d'un règlement de la consultation (RC)."""
import copy
import re

NT = "non trouvé"
TR = "trouvé"

_T = {c: r for c, r in zip("àâäçéèêëîïôöùûüÿœæ", "aaaceeeeiioouuuyoa")}


def fold(s):
    out = []
    for c in s:
        lc = c.lower()
        if len(lc) != 1:
            lc = c
        out.append(_T.get(lc, lc))
    return "".join(out)


def _clean(s):
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    s = re.sub(r"[    ​]", " ", s)
    return s.replace("’", "'")


def _n(s):
    return re.sub(r"\s+", " ", fold(s)).strip()


def _pages(pages):
    out = []
    for p in pages:
        t = _clean(p if isinstance(p, str) else "")
        out.append((t, fold(t)))
    return out


class Acc:
    def __init__(self):
        self.v = []

    def add(self, val, page):
        for x in self.v:
            if x[0] == val:
                x[1].add(page)
                return
        self.v.append([val, {page}])

    def fait(self, single=True):
        if not self.v:
            return {"statut": NT, "valeurs": [], "conflit": False}
        return {"statut": TR,
                "valeurs": [{"valeur": v, "pages": sorted(p)} for v, p in self.v],
                "conflit": bool(single and len(self.v) > 1)}


def _mk(vals, single=True):
    if not vals:
        return {"statut": NT, "valeurs": [], "conflit": False}
    return {"statut": TR, "valeurs": vals, "conflit": bool(single and len(vals) > 1)}


# ------------------------------------------------------------ nombres

_U = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
      "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13,
      "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30,
      "quarante": 40, "cinquante": 50, "soixante": 60}


def words_to_int(s):
    toks = [t for t in re.split(r"[\s\-]+", s.strip()) if t and t != "et"]
    if not toks:
        return None
    cur = 0
    prev = None
    for t in toks:
        if t in ("cent", "cents"):
            cur = cur * 100 if 0 < cur < 10 else cur + 100
        elif t in _U:
            v = _U[t]
            if v == 20 and prev == "quatre":
                cur += 76
            else:
                cur += v
        else:
            return None
        prev = t
    return cur


def qty_before(before):
    b = before.rstrip()
    m = re.search(r"\((\d+)\)\s*$", b)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*$", b)
    if m:
        return int(m.group(1))
    toks = re.findall(r"[a-z]+", b)[-4:]
    for k in range(len(toks), 0, -1):
        n = words_to_int(" ".join(toks[-k:]))
        if n is not None:
            return n
    return None


# ------------------------------------------------------------ dates / heures

_MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
         "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
_DATE_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")
_DATE_TXT = re.compile(r"(?<!\w)(1er|\d{1,2})\s+(" + "|".join(_MOIS) + r")\s+(\d{4})(?!\d)")
_T_DIG = re.compile(r"(?<![\d/.:\-])(\d{1,2})\s*(?:heures?|h)(?![a-z])\s*(\d{2})?(?!\d)")
_T_COL = re.compile(r"(?<![\d/.:\-])(\d{1,2}):(\d{2})(?!\d)")
_T_WORD = re.compile(r"(?<![a-z\-])(?P<h>[a-z]+(?:-[a-z]+){0,2})\s+(?P<hr>heures?)(?![a-z])"
                     r"(?:\s+(?:et\s+)?(?P<m>[a-z]+(?:-[a-z]+)?))?")
_MIDI = re.compile(r"(?<![a-z])midi(?![a-z])")


def _tokens(f):
    toks = []
    for m in _DATE_NUM.finditer(f):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if 1 <= d <= 31 and 1 <= mo <= 12:
            toks.append((m.start(), m.end(), "d", "%02d/%02d/%d" % (d, mo, y)))
    for m in _DATE_TXT.finditer(f):
        d = 1 if m.group(1) == "1er" else int(m.group(1))
        if 1 <= d <= 31:
            toks.append((m.start(), m.end(), "d", "%02d/%02d/%s" % (d, _MOIS[m.group(2)], m.group(3))))
    for m in _T_DIG.finditer(f):
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if h <= 23 and mi <= 59:
            toks.append((m.start(), m.end(), "t", "%02d:%02d" % (h, mi)))
    for m in _T_COL.finditer(f):
        h, mi = int(m.group(1)), int(m.group(2))
        if h <= 23 and mi <= 59:
            toks.append((m.start(), m.end(), "t", "%02d:%02d" % (h, mi)))
    for m in _T_WORD.finditer(f):
        h = words_to_int(m.group("h"))
        if h is None or h > 23:
            continue
        mi = 0
        end = m.end("hr")
        g = m.group("m")
        if g:
            if g in ("demie", "demi"):
                mi = 30
            elif g == "quart":
                mi = 15
            else:
                x = words_to_int(g)
                if x is not None and x <= 59:
                    mi = x
            if mi:
                end = m.end("m")
        toks.append((m.start(), end, "t", "%02d:%02d" % (h, mi)))
    for m in _MIDI.finditer(f):
        toks.append((m.start(), m.end(), "t", "12:00"))
    toks.sort()
    out = []
    last = -1
    for t in toks:
        if t[0] >= last:
            out.append(t)
            last = t[1]
    return out


_FILL = set("a le la les l ou et au aux de du des vers avant apres jusqu jusque lundi mardi mercredi "
            "jeudi vendredi samedi dimanche soit entre en pour sur d h heure heures ainsi que".split())


def _classify(f, toks):
    out = []
    prev_end = 0
    prev = None
    for i, (s, e, k, v) in enumerate(toks):
        lo = max(prev_end, s - 220)
        w = f[lo:s]
        cuts = list(re.finditer(r"[.!?]\s", w))
        if cuts:
            w = w[cuts[-1].end():]
        words = re.findall(r"[a-z]+", w)
        if i > 0 and all(x in _FILL for x in words):
            c = prev
        elif re.search(r"question|renseignement", w):
            c = "Q"
        elif "visite" in w:
            c = "V"
        elif re.search(r"offre|\bpli|remise|reception|depot|depos", w):
            c = "DL"
        else:
            c = None
            if k == "d" and re.search(r"\blieu\b|rendez-vous", w) and "visite" in f[max(0, s - 300):s]:
                c = "V"
            elif k == "d":
                segs = re.split(r"[.!?]\s", f[max(0, s - 300):s])
                rec = " ".join(segs[-2:])
                if "visite" in rec and not re.search(r"offre|remise|question|depot|renseignement", rec):
                    c = "V"
        out.append(c)
        prev_end = e
        prev = c
    return out


def _sents(t):
    out = []
    for line in t.split("\n"):
        for p in re.split(r"(?<=[.!?;])\s+", line.strip()):
            if p:
                out.append((p, fold(p)))
    return out


_DELAI = re.compile(r"(?<![\w(])((?:\d+|[a-z]+(?:-[a-z]+)?)(?:\s*\(\d+\))?\s+jours?\s+avant\s+la\s+date\s+limite"
                    r"\s+de\s+(?:remise|reception)\s+des\s+offres)")


def _facts_dates(pages):
    A = {k: Acc() for k in ("date_limite", "heure_limite", "date_questions", "dates_visite")}
    for i, (t, f) in enumerate(pages, 1):
        toks = _tokens(f)
        for tok, c in zip(toks, _classify(f, toks)):
            if c == "DL":
                A["date_limite" if tok[2] == "d" else "heure_limite"].add(tok[3], i)
            elif c == "Q" and tok[2] == "d":
                A["date_questions"].add(tok[3], i)
            elif c == "V" and tok[2] == "d":
                A["dates_visite"].add(tok[3], i)
        for orig, fs in _sents(t):
            if re.search(r"question|renseignement", fs):
                m = _DELAI.search(fs)
                if m:
                    A["date_questions"].add(re.sub(r"\s+", " ", orig[m.start(1):m.end(1)]), i)
    return {k: (a.fait(False) if k == "dates_visite" else a.fait()) for k, a in A.items()}


# ------------------------------------------------------------ autres faits

_PROC = [(re.compile(r"procedure adaptee"), "procédure adaptée"),
         (re.compile(r"(?<![\w-])mapa(?![\w-])"), "procédure adaptée"),
         (re.compile(r"appel d'offres ouvert"), "appel d'offres ouvert"),
         (re.compile(r"appel d'offres restreint"), "appel d'offres restreint"),
         (re.compile(r"dialogue competitif"), "dialogue compétitif"),
         (re.compile(r"procedure (?:negociee|avec negociation)"), "procédure avec négociation")]
_ANCRE_VALID = re.compile(r"validite des offres|validite de l'offre|offres?\s+(?:sont|restent|demeurent|reste)\s+valables?")


def _facts_autres(pages):
    P, V, VA, VO, M, L = Acc(), Acc(), Acc(), Acc(), Acc(), Acc()
    for i, (t, f) in enumerate(pages, 1):
        found = []
        for rx, val in _PROC:
            for m in rx.finditer(f):
                found.append((m.start(), val))
        for _, val in sorted(found):
            P.add(val, i)
        for orig, s in _sents(t):
            if "visite" in s:
                x = s.replace("attestation de visite", "")
                if "visite" in x:
                    if re.search(r"facultati|pas obligatoire|non obligatoire|non-obligatoire", x):
                        V.add("non", i)
                    elif "obligatoire" in x:
                        V.add("oui", i)
            if "variante" in s:
                if re.search(r"interdit|non autoris|non admis|aucune variante|pas autoris|pas admis|pas accept|"
                             r"pas permis|refus|exclu", s):
                    VA.add("non autorisées", i)
                elif re.search(r"autoris|admis|accept|permis|peuvent presenter|possibilite", s):
                    VA.add("autorisées", i)
            m = _ANCRE_VALID.search(s)
            if m:
                rest = s[m.start():]
                mu = re.search(r"(?:\((\d+)\)\s*)?(jours?|mois)\b", rest)
                if mu:
                    n = int(mu.group(1)) if mu.group(1) else qty_before(rest[:mu.start()])
                    if n is not None:
                        VO.add({"nombre": n, "unite": "jours" if mu.group(2).startswith("jour") else "mois"}, i)
            if (not re.search(r"question|renseignement|\bdce\b|dossier de consultation|mise a disposition", s)
                    and re.search(r"offre|\bpli|remise|depo|transmi|remis", s)):
                elec = re.search(r"electroniq|dematerialis|plateforme|profil d'acheteur", s)
                pap = re.search(r"papier|pli cachete|support physique", s)
                if pap and not re.search(
                        r"aucun\w*[^:;]{0,60}papier|papier[^:;]{0,60}(?:\bpas\b|interdit|refus|\bnon\b|ne sera|n'est)"
                        r"|(?:\bpas\b|interdit\w*)[^:;]{0,60}papier", s):
                    M.add("papier", i)
                if elec and not re.search(r"(?:\bpas\b|aucun\w*|interdit\w*)[^:;]{0,40}(?:electroniq|dematerialis)", s):
                    M.add("électronique", i)
            if "memoire" in s:
                for mp in re.finditer(r"(?:\((\d+)\)\s*)?pages?\b", s):
                    n = int(mp.group(1)) if mp.group(1) else qty_before(s[:mp.start()])
                    if n is not None:
                        L.add(n, i)
                        break
    return {"procedure": P.fait(), "visite_obligatoire": V.fait(), "variantes": VA.fait(),
            "validite_offres": VO.fait(), "mode_remise": M.fait(), "limite_pages": L.fait()}


# ------------------------------------------------------------ lignes

_FOOT = re.compile(r"^\W*(?:rc\s*[–\-]\s*\d+\s*/\s*\d+|page\s+\d+(?:\s+sur\s+\d+)?|\d+)\W*$")
_HEAD = re.compile(r"^\W*(?:article|annexe|titre|chapitre)\b")


def _lines(pages):
    out = []
    for i, (t, f) in enumerate(pages, 1):
        for raw in t.split("\n"):
            raw = raw.expandtabs(4).rstrip()
            if not raw.strip():
                continue
            fl = fold(raw)
            if _FOOT.match(fl.strip()):
                continue
            out.append((i, raw, fl))
    return out


# ------------------------------------------------------------ lots

_LOT = re.compile(r"^[\s\-–—•*·▪]*lots?\s*(?:n\s*[°º])?\s*0*(\d+)\s*(?:[:\-–—)]\s*|\s{2,})(\S.*)$")
_UNIQUE = re.compile(r"\blot unique\b|\bun seul lot\b|\bn'est pas alloti|\bnon alloti|\bpas alloti"
                     r"|pas (?:prevu )?de decomposition en lots?|pas d'allotissement|sans allotissement")


def _lots(pages, lines):
    nums = {}
    for pg, raw, fl in lines:
        m = _LOT.match(fl)
        if not m:
            continue
        n = int(m.group(1))
        intit = raw[m.start(2):].strip().rstrip(" ;.,")
        if not intit:
            continue
        e = nums.setdefault(n, {"i": [], "p": set()})
        e["p"].add(pg)
        for x in e["i"]:
            if _n(x[0]) == _n(intit):
                x[1].add(pg)
                break
        else:
            e["i"].append([intit, {pg}])
    liste = []
    for n in sorted(nums):
        e = nums[n]
        ints = [{"valeur": v, "pages": sorted(p)} for v, p in e["i"]]
        liste.append({"numero": n, "intitules": ints, "pages": sorted(e["p"]), "conflit": len(ints) > 1})
    if not liste:
        up = [i for i, (t, f) in enumerate(pages, 1) if _UNIQUE.search(re.sub(r"\s+", " ", f))]
        if up:
            liste.append({"numero": None, "intitules": [], "pages": up, "conflit": False})
    return {"statut": TR if liste else NT, "liste": liste}


# ------------------------------------------------------------ pièces

_BUL = re.compile(r"^\s*[-–—•*·▪]\s+(\S.*)$")
_PIECE_OPEN = re.compile(r"pieces|documents suivants|dossier (?:a remettre|comprenant)|produira|envisage d'attribuer"
                         r"|contenu des plis|contenu du dossier")
_QUAL = re.compile(r"\s*\((?:obligatoire|facultati[fv]es?|optionnel(?:le)?)\)|,?\s*[àa]\s+titre\s+facultatif", re.I)


def _phase(f):
    if "attributaire" in f or "envisage d'attribuer" in f:
        return "attributaire"
    if re.search(r"(?:pieces?|titre)\b.*\bcandidature\b", f):
        return "candidature"
    if re.search(r"(?:pieces?|titre)\b.*\boffres?\b", f):
        return "offre"
    return None


def _pieces(lines):
    order = []
    data = {}
    zone = False
    phase = None
    for pg, raw, fl in lines:
        if _HEAD.match(fl):
            zone = False
            phase = None
        mb = _BUL.match(raw)
        if mb:
            if not zone:
                continue
            txt = mb.group(1).strip()
            if txt.endswith(":"):
                continue
            ft = fold(txt)
            nom = _QUAL.sub("", txt).strip().rstrip(" ;.,").strip()
            if not nom:
                continue
            key = _n(nom)
            if key not in data:
                data[key] = {"nom": nom, "p": set(), "ph": Acc(), "ob": Acc()}
                order.append(key)
            e = data[key]
            e["p"].add(pg)
            if phase:
                e["ph"].add(phase, pg)
            if re.search(r"facultati|non obligatoire|optionnel", ft):
                e["ob"].add("non obligatoire", pg)
            elif "obligatoire" in ft:
                e["ob"].add("obligatoire", pg)
            continue
        if _PIECE_OPEN.search(fl):
            zone = True
        if zone:
            ph = _phase(fl)
            if ph:
                phase = ph
    liste = []
    for k in order:
        e = data[k]
        liste.append({"nom": e["nom"], "pages": sorted(e["p"]), "phase": e["ph"].fait(False),
                      "obligation": e["ob"].fait()})
    return {"statut": TR if liste else NT, "liste": liste}


# ------------------------------------------------------------ critères

_CRIT_PRE = re.compile(r"crit[eè]res?\s*(?:n\s*[°º]?\s*)?(\d+)\s*[:\-–—.)]?\s*")
_SUBNUM = re.compile(r"(\d+(?:\.\d+)+)\s*[.)\-–—]?\s+")
_TOPNUM = re.compile(r"(\d+)\s*[.)\-–—]\s*(?=\S)")
_LETTER = re.compile(r"([a-z])\s*[.)]\s+")
_BULLET = re.compile(r"[-–—•*·▪]\s+")
_UNIT = re.compile(r"(?<![a-z])(%|pour\s*cent|points?|pts?)(?![a-z])")
_OPEN = re.compile(r"critere|notees? sur|jugees?|jugement des offres|ponderation")
_CLOSE = re.compile(r"^\W*(?:bareme|la note finale|note finale)")
_CLASS = re.compile(r"class\w*\s+par\s+ordre|ordre\s+decroissant\s+d'importance")
_DETAIL = re.compile(r"detail\s+du\s+critere\s+(?P<a>[a-z' \-]+?)\s*:?\s*$|"
                     r"critere\s+(?P<b>[a-z' \-]+?)\s+est\s+(?:decompose|detaille|divise)")


def _num(x):
    return int(x) if x == int(x) else x


def _parse_weight(fs, strict=False):
    for m in _UNIT.finditer(fs):
        if strict and fs[m.end():].strip():
            continue
        before = fs[:m.start()]
        mm = re.search(r"(\d+(?:[.,]\d+)?)\s*$", before)
        if mm:
            val = float(mm.group(1).replace(",", "."))
        else:
            n = None
            toks = re.findall(r"[a-z]+", before)[-3:]
            for k in range(len(toks), 0, -1):
                n = words_to_int(" ".join(toks[-k:]))
                if n is not None:
                    break
            if n is None:
                continue
            val = float(n)
        u = "pourcentage" if m.group(1) == "%" or m.group(1).startswith("pour") else "points"
        return _num(val), u
    return None


def _clean_label(s):
    return s.strip().strip(" :;.,-–—|").strip()


def _label_weight(rest):
    depth = 0
    sep = None
    for i, c in enumerate(rest):
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif c in ":|" and depth == 0:
            sep = i
            break
    for m in re.finditer(r"\(([^()]*)\)", rest):
        if sep is not None and sep < m.start():
            break
        w = _parse_weight(fold(m.group(1)), strict=True)
        if w:
            return _clean_label(rest[:m.start()]), w
    if sep is not None:
        return _clean_label(rest[:sep]), _parse_weight(fold(rest[sep + 1:]))
    return _clean_label(rest), None


def _parse_item(raw, fl):
    indent = len(raw) - len(raw.lstrip())
    body = raw.strip()
    bf = fl.strip()
    kind = None
    num = None
    m = _CRIT_PRE.match(bf)
    if m:
        kind, num = "top", int(m.group(1))
    else:
        m = _SUBNUM.match(bf)
        if m:
            kind = "sub"
        else:
            m = _TOPNUM.match(bf)
            if m:
                kind, num = "top", int(m.group(1))
            else:
                m = _LETTER.match(bf)
                if m:
                    kind = "sub"
                else:
                    m = _BULLET.match(bf)
                    if m:
                        kind = "bullet"
    rest = body[m.end():] if m else body
    label, w = _label_weight(rest)
    if not label or len(label) > 120:
        return None
    if re.match(r"(?:note|bareme|formule)\b", fold(label)):
        return None
    if kind is None and (w is None or not re.search(r"[:|]", rest)):
        return None
    if w is None and len(label.split()) > 14:
        return None
    return {"kind": kind, "indent": indent, "num": num, "label": label, "w": w}


def _ctx_lots(fl):
    s = fl.strip()
    if not re.match(r"^\W*(?:pour\s+(?:le|les|chacun\s+des|tous\s+les)\s+)?lots?\b", s):
        return None
    head = re.split(r"\s*:\s*|,\s*(?=[a-z])", s, 1)
    pre = head[0]
    nums = [int(x) for x in re.findall(r"\d+", pre)]
    if not nums:
        return None
    if not s.startswith("pour"):
        if len(head) > 1 and head[1].strip():
            return None
    if len(nums) == 2 and re.search(r"\d\s*a\s*\d", pre):
        return list(range(nums[0], nums[1] + 1))
    return nums


def _crit_nodes(lines):
    crits = {}
    zone = False
    ctx = None
    classement = False
    rank = 0
    top = None
    top_indent = 0

    def add_weight(ent, w, pg, c):
        for lot in ([None] if c is None else c):
            ent["w"].append((w[0], w[1], lot, pg))

    for pg, raw, fl in lines:
        s = fl.strip()
        if _HEAD.match(fl):
            zone = False
            ctx = None
            classement = False
            top = None
        if _CLOSE.match(fl):
            zone = False
            ctx = None
            top = None
            continue
        dm = _DETAIL.search(s)
        if dm:
            name = (dm.group("a") or dm.group("b") or "").strip()
            for k, e in crits.items():
                if name and (k == name or k.startswith(name) or name.startswith(k) or name in k):
                    top = e
                    top_indent = -1
                    break
        opens = bool(_OPEN.search(s))
        cl = _ctx_lots(fl)
        if cl is not None and (zone or opens):
            zone = True
            ctx = cl
            top = None
            if _CLASS.search(s):
                classement = True
            continue
        item = _parse_item(raw, fl) if (zone or _CRIT_PRE.match(s)) else None
        if item is None and not zone and _TOPNUM.match(s):
            it2 = _parse_item(raw, fl)
            if it2 and it2["w"] is not None and it2["kind"] == "top":
                item = it2
        if item and not zone:
            zone = True
        if item:
            w = item["w"]
            kind = item["kind"]
            is_sub = False
            if kind == "sub":
                if top is None:
                    continue
                is_sub = True
            elif kind == "bullet" and top is not None and item["indent"] > top_indent:
                is_sub = True
            if w is None and not is_sub and classement:
                rank += 1
                w = (item["num"] if item["num"] is not None else rank, "rang")
            key = _n(item["label"])
            if is_sub:
                se = top["subs"].get(key)
                if se is None:
                    se = {"label": item["label"], "p": set(), "w": []}
                    top["subs"][key] = se
                se["p"].add(pg)
                if w:
                    add_weight(se, w, pg, ctx)
            else:
                e = crits.get(key)
                if e is None:
                    e = {"label": item["label"], "p": set(), "w": [], "subs": {}, "all": False, "lots": {}}
                    crits[key] = e
                e["p"].add(pg)
                if ctx is None:
                    e["all"] = True
                else:
                    for lot in ctx:
                        e["lots"].setdefault(lot, set()).add(pg)
                if w:
                    add_weight(e, w, pg, ctx)
                top = e
                top_indent = item["indent"]
            continue
        if opens:
            if not zone:
                zone = True
                ctx = None
                classement = False
                rank = 0
            if _CLASS.search(s):
                classement = True
    return crits


def _conf_p(vals):
    lots = [v["lot"] for v in vals]
    return len(lots) != len(set(lots))


def _faitp(ws):
    out = []
    for val, unite, lot, pg in ws:
        for o in out:
            if o["valeur"] == val and o["unite"] == unite and o["lot"] == lot:
                if pg not in o["pages"]:
                    o["pages"] = sorted(o["pages"] + [pg])
                break
        else:
            out.append({"valeur": val, "unite": unite, "lot": lot, "pages": [pg]})
    return {"statut": TR if out else NT, "valeurs": out, "conflit": _conf_p(out)}


def _criteres(lines, lots_fait):
    crits = _crit_nodes(lines)
    ll = lots_fait["liste"]
    known = {x["numero"] for x in ll if x["numero"] is not None}
    liste = []
    for e in crits.values():
        lotset = set(e["lots"])
        covering = e["all"] or not lotset or (known and known <= lotset)
        if covering:
            if len(ll) == 1:
                lot = {"statut": TR, "valeurs": [{"valeur": ll[0]["numero"], "pages": list(ll[0]["pages"])}],
                       "conflit": False}
            else:
                lot = {"statut": TR, "valeurs": [{"valeur": "tous les lots", "pages": sorted(e["p"])}],
                       "conflit": False}
        else:
            lot = {"statut": TR, "valeurs": [{"valeur": k, "pages": sorted(e["lots"][k])} for k in sorted(lotset)],
                   "conflit": False}
        subs = [{"libelle": s["label"], "pages": sorted(s["p"]), "ponderation": _faitp(s["w"])}
                for s in e["subs"].values()]
        liste.append({"libelle": e["label"], "pages": sorted(e["p"]), "lot": lot,
                      "ponderation": _faitp(e["w"]), "sous_criteres": subs})
    tp = Acc()
    for e in crits.values():
        for val, unite, lot, pg in e["w"]:
            tp.add({"pourcentage": "pourcentage", "points": "points", "rang": "classement"}[unite], pg)
    return {"statut": TR if liste else NT, "liste": liste}, tp.fait()


# ------------------------------------------------------------ plan et contrôle

def _tech(libelle):
    return "technique" in fold(libelle)


def _w(fait):
    vs = fait["valeurs"]
    for v in vs:
        if v["lot"] is None:
            return v
    return vs[0] if vs else None


def _plan(crits):
    plan = []
    for c in crits:
        if not _tech(c["libelle"]):
            continue
        if c["sous_criteres"]:
            for s in c["sous_criteres"]:
                sw = _w(s["ponderation"])
                plan.append({"titre": c["libelle"] + " – " + s["libelle"], "critere": c["libelle"],
                             "sous_critere": s["libelle"], "ponderation": sw["valeur"] if sw else None,
                             "page_source": min(s["pages"]), "contenu": ""})
        else:
            w = _w(c["ponderation"])
            plan.append({"titre": c["libelle"], "critere": c["libelle"], "sous_critere": None,
                         "ponderation": w["valeur"] if w else None,
                         "page_source": min(c["pages"]), "contenu": ""})
    return plan


def controler(dossier):
    crits = dossier["criteres"]["liste"]
    sections = {s["critere"] for s in dossier["plan"]}
    alertes = []
    for c in crits:
        if _tech(c["libelle"]) and c["libelle"] not in sections:
            alertes.append({"type": "critère sans section", "objet": c["libelle"]})
    for c in crits:
        pw = _w(c["ponderation"])
        if not c["sous_criteres"] or pw is None:
            continue
        sws = [_w(s["ponderation"]) for s in c["sous_criteres"]]
        if any(x is None for x in sws):
            continue
        if pw["unite"] == "rang" or any(x["unite"] == "rang" for x in sws):
            continue
        total = sum(x["valeur"] for x in sws)
        cible = pw["valeur"]
        if all(x["unite"] == "pourcentage" for x in sws) and pw["unite"] != "pourcentage":
            cible = 100
        if abs(total - cible) > 1e-6:
            alertes.append({"type": "pondérations incohérentes", "objet": c["libelle"]})
    tp = dossier["type_ponderation"]
    if [v["valeur"] for v in tp["valeurs"]] == ["pourcentage"]:
        par = [[v for v in c["ponderation"]["valeurs"] if v["unite"] == "pourcentage"] for c in crits]
        lots = sorted({v["lot"] for vs in par for v in vs if v["lot"] is not None})
        mauvais = False
        for g in (lots or [None]):
            total = 0
            vu = False
            for vs in par:
                pick = None
                for v in vs:
                    if v["lot"] == g:
                        pick = v
                        break
                if pick is None:
                    for v in vs:
                        if v["lot"] is None:
                            pick = v
                            break
                if pick is not None:
                    total += pick["valeur"]
                    vu = True
            if vu and abs(total - 100) > 1e-6:
                mauvais = True
        if mauvais:
            alertes.append({"type": "total différent de 100 %", "objet": "critères"})
    return alertes


# ------------------------------------------------------------ analyse

def _extraire(pages):
    pg = _pages(pages)
    lines = _lines(pg)
    d = {}
    lots = _lots(pg, lines)
    d["lots"] = lots
    d.update(_facts_dates(pg))
    d.update(_facts_autres(pg))
    d["pieces"] = _pieces(lines)
    crits, tp = _criteres(lines, lots)
    d["criteres"] = crits
    d["type_ponderation"] = tp
    d["plan"] = _plan(crits["liste"])
    d["controle"] = {"alertes": controler(d)}
    return d


def analyser(pages):
    return _extraire(list(pages))


# ------------------------------------------------------------ vérification

def _rf(prop, ext, single=True):
    out = []
    for pv in prop.get("valeurs", []):
        for ev in ext["valeurs"]:
            if pv["valeur"] == ev["valeur"] and not any(o["valeur"] == ev["valeur"] for o in out):
                out.append({"valeur": ev["valeur"], "pages": list(ev["pages"])})
    return _mk(out, single)


def _rfp(prop, ext):
    out = []
    for pv in prop.get("valeurs", []):
        for ev in ext["valeurs"]:
            k = (ev["valeur"], ev["unite"], ev["lot"])
            if (pv["valeur"], pv["unite"], pv["lot"]) == k and not any(
                    (o["valeur"], o["unite"], o["lot"]) == k for o in out):
                out.append(copy.deepcopy(ev))
    return {"statut": TR if out else NT, "valeurs": out, "conflit": _conf_p(out)}


def verifier(dossier, pages):
    ext = _extraire(list(pages))
    r = copy.deepcopy(dossier)
    for k, single in (("date_limite", True), ("heure_limite", True), ("date_questions", True),
                      ("procedure", True), ("visite_obligatoire", True), ("dates_visite", False),
                      ("variantes", True), ("validite_offres", True), ("mode_remise", True),
                      ("limite_pages", True), ("type_ponderation", True)):
        r[k] = _rf(dossier.get(k, {}), ext[k], single)
    liste = []
    for pl in dossier.get("lots", {}).get("liste", []):
        el = next((x for x in ext["lots"]["liste"] if x["numero"] == pl["numero"]), None)
        if el is None or any(x["numero"] == pl["numero"] for x in liste):
            continue
        ints = []
        for pi in pl["intitules"]:
            for ei in el["intitules"]:
                if _n(pi["valeur"]) == _n(ei["valeur"]) and not any(o["valeur"] == ei["valeur"] for o in ints):
                    ints.append(copy.deepcopy(ei))
        liste.append({"numero": el["numero"], "intitules": ints, "pages": list(el["pages"]),
                      "conflit": len(ints) > 1})
    r["lots"] = {"statut": TR if liste else NT, "liste": liste}
    emap = {_n(p["nom"]): p for p in ext["pieces"]["liste"]}
    liste = []
    vus = set()
    for pp in dossier.get("pieces", {}).get("liste", []):
        k = _n(pp["nom"])
        ep = emap.get(k)
        if ep is None or k in vus:
            continue
        vus.add(k)
        liste.append({"nom": ep["nom"], "pages": list(ep["pages"]),
                      "phase": _rf(pp.get("phase", {}), ep["phase"], False),
                      "obligation": _rf(pp.get("obligation", {}), ep["obligation"], True)})
    r["pieces"] = {"statut": TR if liste else NT, "liste": liste}
    emap = {_n(c["libelle"]): c for c in ext["criteres"]["liste"]}
    liste = []
    vus = set()
    for pc in dossier.get("criteres", {}).get("liste", []):
        k = _n(pc["libelle"])
        ec = emap.get(k)
        if ec is None or k in vus:
            continue
        vus.add(k)
        c = copy.deepcopy(ec)
        c["ponderation"] = _rfp(pc.get("ponderation", {}), ec["ponderation"])
        smap = {_n(s["libelle"]): s for s in ec["sous_criteres"]}
        subs = []
        svus = set()
        for ps in pc.get("sous_criteres", []):
            sk = _n(ps["libelle"])
            es = smap.get(sk)
            if es is None or sk in svus:
                continue
            svus.add(sk)
            s = copy.deepcopy(es)
            s["ponderation"] = _rfp(ps.get("ponderation", {}), es["ponderation"])
            subs.append(s)
        c["sous_criteres"] = subs
        liste.append(c)
    r["criteres"] = {"statut": TR if liste else NT, "liste": liste}
    r["plan"] = _plan(liste)
    r["controle"] = {"alertes": controler(r)}
    return r
