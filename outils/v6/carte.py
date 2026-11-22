"""Piste A (V6) : part déterministe d'une spec (H30) et carte des organes, sans aucun appel payant.

    python outils/v6/carte.py        → runs-v6/carte/resultat.json et un tableau

La règle = les 4 greens de P12 à l'itération 4 (runs-v5/boucle/it4/sorties/{H,H2,S,S2}.json), tous déterministes.
Le petit modèle = le pipeline BuildForge avec NuExtract (runs-v5/h23/nuextract/). Le grand = le même pipeline avec sonnet.
Définitions figées dans data/predictions/V6.md (et son complément) :
- la règle a juste sur un fait d'un RC si au moins 3 des 4 greens rendent la vraie valeur ;
- un fait est satisfait sans LLM sur un corpus si la règle a juste sur ≥ 95 % de ses RC ;
- part déterministe = part des 175 assertions (spec it4) dont le fait est satisfait sans LLM ; une assertion
  hors des 11 faits (data/v6/assertion-fait.json, champs « @… ») est jugée sur l'accord : ≥ 3 greens sur 4
  identiques sur ce champ dans ≥ 95 % des RC ;
- carte : règle suffit / petit modèle nécessaire (règle fausse, NuExtract juste) / personne ne sait.
Écarts à H23, imposés par l'interface des greens et écrits dans le rapport : mode de remise jugé « électronique
ou papier » ; date limite des questions jugée sur le jour seul (les greens ne rendent pas d'heure pour les questions).
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent.parent
sys.path.insert(0, str(RACINE / "outils" / "v5"))
from h23 import CHAMPS, faits, juste, lotnum, norm, num  # noqa: E402
from situations import ids, situation  # noqa: E402

IT4 = RACINE / "runs-v5" / "boucle" / "it4"
GREENS = ["H", "H2", "S", "S2"]
SORTIE = RACINE / "runs-v6" / "carte"
PROC = [("adapt", "procedure_adaptee"), ("ouvert", "appel_offres_ouvert"), ("restreint", "appel_offres_restreint"),
        ("negoci", "procedure_negociee"), ("dialogue", "dialogue_competitif")]
UNITE = {"pourcentage": "percent", "points": "points"}


def iso(s):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})$", str(s or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else s


def vals(f):
    if not isinstance(f, dict) or f.get("statut") != "trouvé":
        return []
    return [v.get("valeur") for v in f.get("valeurs", [])]


def statut(f, n):
    if n == 0:
        return "not_found"
    return "conflict" if (isinstance(f, dict) and f.get("conflit")) or n > 1 else "found"


def fait(st, valeurs):
    return {"status": st, "values": [{"value": v} for v in valeurs]}


# ------------------------------------------------------------------ green (dossier fixé par les tests) → Facts

def facts_green(d):
    if not isinstance(d, dict) or "__erreur__" in d:
        return None
    o = {}
    dates, heures = vals(d.get("date_limite")), vals(d.get("heure_limite"))
    ds = sorted(set(iso(x) for x in dates))
    if len(heures) == len(ds):
        od = [{"date": a, "time": b} for a, b in zip(ds, heures)]
    else:
        od = [{"date": a, "time": heures[0] if len(set(heures)) == 1 else None} for a in ds]
    conf = bool((d.get("date_limite") or {}).get("conflit") or (d.get("heure_limite") or {}).get("conflit"))
    o["offer_deadline"] = fait("not_found" if not ds else "conflict" if conf or len(ds) > 1 else "found", od)
    q = sorted(set(iso(x) for x in vals(d.get("date_questions"))))
    o["questions_deadline"] = fait(statut(d.get("date_questions"), len(q)), [{"date": x, "time": None} for x in q])
    p = sorted({next((e for k, e in PROC if k in norm(x)), "autre") for x in vals(d.get("procedure"))})
    o["procedure"] = fait(statut(d.get("procedure"), len(p)), [{"procedure": x} for x in p])
    lots = [l for l in ((d.get("lots") or {}).get("liste") or []) if isinstance(l, dict)]
    nums = [l.get("numero") for l in lots]
    conf = any(l.get("conflit") for l in lots) or (None in nums and len(nums) > 1)
    o["lots"] = fait("not_found" if not lots else "conflict" if conf else "found", [{"number": n} for n in nums])
    v = sorted({x == "oui" for x in vals(d.get("visite_obligatoire"))})
    o["site_visit"] = fait(statut(d.get("visite_obligatoire"), len(v)), [{"value": x} for x in v])
    dv = sorted({iso(x) for x in vals(d.get("dates_visite"))})
    o["site_visit_dates"] = fait("found" if dv else "not_found", [{"date": x} for x in dv])
    m = sorted({norm(x) for x in vals(d.get("mode_remise"))})
    o["submission_mode"] = fait(statut(d.get("mode_remise"), len(m)), [{"text": x} for x in m])
    va = [x for x in vals(d.get("validite_offres")) if isinstance(x, dict)]
    va = sorted({(x.get("nombre"), {"jours": "days", "mois": "months"}.get(x.get("unite"))) for x in va}, key=repr)
    o["offer_validity"] = fait(statut(d.get("validite_offres"), len(va)), [{"amount": a, "unit": u} for a, u in va])
    vr = sorted({x == "autorisées" for x in vals(d.get("variantes"))})
    o["variants"] = fait(statut(d.get("variantes"), len(vr)), [{"value": x} for x in vr])
    crit = []
    for k in ((d.get("criteres") or {}).get("liste") or []):
        subs = []
        for s in k.get("sous_criteres") or []:
            w = (s.get("ponderation") or {}).get("valeurs") or []
            w = w[0] if w else None
            subs.append({"wording": s.get("libelle"), "weight": {"amount": w.get("valeur"), "unit": UNITE.get(w.get("unite"))} if w else None})
        pond = (k.get("ponderation") or {}).get("valeurs") or []
        lots_k = vals(k.get("lot")) or [None]
        if not pond:
            pond = [{"valeur": None, "unite": None, "lot": l} for l in lots_k]
        for p in pond:
            rang = p.get("unite") == "rang"
            crit.append({"lot": p.get("lot"), "wording": k.get("libelle"), "rank": p.get("valeur") if rang else None,
                         "weight": None if rang or p.get("valeur") is None else {"amount": p.get("valeur"), "unit": UNITE.get(p.get("unite"))},
                         "sub_criteria": subs})
    o["award_criteria"] = fait("found" if crit else "not_found", crit)
    pc = [{"wording": p.get("nom"), "part": (vals(p.get("phase")) or [None])[0]} for p in ((d.get("pieces") or {}).get("liste") or [])]
    o["documents_to_return"] = fait("found" if pc else "not_found", pc)
    return o


def facts_bilel(sortie):
    f = faits(sortie)
    return f or None


# ------------------------------------------------------------------ justesse

def mode(f):
    if not f or f["status"] not in ("found", "conflict"):
        return None
    t = " ".join(norm((v.get("value") or v).get("text", "")) for v in f["values"])
    return "electronique" if re.search(r"electron|dematerial|plateforme|profil|http|www|courriel|mail", t) else "papier" if t else None


def juste_synth(field, f, vrai):
    if field == "submission_mode":
        if vrai["statut"] == "not_found":
            return not f or f["status"] == "not_found"
        return mode(f) == "electronique"
    if field == "questions_deadline":
        if vrai["statut"] == "not_found":
            return bool(f) and f["status"] == "not_found"
        if not f or f["status"] != vrai["statut"]:
            return False
        return sorted({(v.get("value") or v)["date"] for v in f["values"]}) == sorted({x["date"] for x in vrai["valeurs"]})
    return juste(field, f, vrai) if f else False


def _crit_canon(vs, lots_rc):
    """Critères → ensemble de (lot, poids, unité, rang, poids des sous-critères), avec repliement : si chaque lot
    du RC a exactement le même jeu, on le ramène à un jeu commun (lot None)."""
    par = defaultdict(list)
    for c in vs:
        c = c.get("value", c)
        w = c.get("weight") or {}
        sw = tuple(sorted(num((s.get("weight") or {}).get("amount")) or 0 for s in c.get("sub_criteria") or []))
        par[lotnum(c.get("lot"))].append((num(w.get("amount")), w.get("unit"), c.get("rank"), sw, norm(c.get("wording"))))
    jeux = {l: sorted((x[:4] for x in v), key=repr) for l, v in par.items()}
    if None not in par and len(par) > 1 and len({repr(j) for j in jeux.values()}) == 1 and set(par) >= set(lots_rc):
        par = {None: next(iter(par.values()))}
    return par


def juste_crit_pub(f, vrai, lots_rc):
    if not f or f["status"] not in ("found", "conflict"):
        return False
    a = _crit_canon(f["values"], lots_rc)
    t = _crit_canon(vrai["valeurs"], lots_rc)
    if set(a) != set(t):
        return False
    for l, tv in t.items():
        av = list(a[l])
        cles = {(x[0], x[1], x[2], x[3]): c["cle"] for c in vrai["valeurs"] if lotnum(c["lot"]) == l
                for x in [(num(c["weight"]["amount"]), c["weight"]["unit"], c["rank"],
                           tuple(sorted(num(s["weight"]["amount"]) for s in c["sub_criteria"])))]}
        if len(av) != len(tv):
            return False
        for x in tv:
            cle = norm(cles[x[:4]])
            m = next((y for y in av if y[:4] == x[:4] and cle in y[4]), None)
            if m is None:
                return False
            av.remove(m)
    return True


def juste_pieces_pub(f, vrai):
    if not f or f["status"] not in ("found", "conflict"):
        return False
    pc = [((v.get("value") or v).get("wording"), (v.get("value") or v).get("part")) for v in f["values"]]
    pc = [(norm(w), p) for w, p in pc]
    for a in vrai["valeurs"]:
        cle = norm(a["cle"])
        parts = {p for w, p in pc if cle in w}
        if parts != {a["part"]}:
            return False
    return True


def juste_pub(field, f, vrai, v_rc):
    if field == "award_criteria":
        return juste_crit_pub(f, vrai, [lotnum(x["number"]) for x in v_rc["lots"]["valeurs"]])
    if field == "documents_to_return":
        return juste_pieces_pub(f, vrai)
    if field == "lots" and "lots_alt" in v_rc:
        return juste("lots", f, vrai) or juste("lots", f, v_rc["lots_alt"]) if f else False
    if field == "procedure" and f and f["status"] != "not_found":
        f = {**f, "values": [{"value": {"procedure": (v.get("value") or v).get("procedure")}} for v in f["values"]]}
    return juste_synth(field, f, vrai)


# ------------------------------------------------------------------ accord sur les champs hors faits

def champ_accord(d, champ):
    if not isinstance(d, dict) or "__erreur__" in d:
        return None
    if champ == "@limite_pages":
        return json.dumps(vals(d.get("limite_pages")), sort_keys=True, ensure_ascii=False)
    if champ == "@type_ponderation":
        return json.dumps(vals(d.get("type_ponderation")), sort_keys=True, ensure_ascii=False)
    if champ == "@controle":
        al = (d.get("controle") or {}).get("alertes") or []
        return json.dumps(sorted(json.dumps(a, sort_keys=True, ensure_ascii=False) for a in al), ensure_ascii=False)
    if champ == "@plan":
        return json.dumps(d.get("plan"), sort_keys=True, ensure_ascii=False)
    if champ == "@obligation":
        return json.dumps(sorted((norm(p.get("nom")), json.dumps(vals(p.get("obligation")), ensure_ascii=False))
                                 for p in ((d.get("pieces") or {}).get("liste") or [])), ensure_ascii=False)
    if champ == "@pages":
        out = []

        def visite(x, chemin):
            if isinstance(x, dict):
                if "pages" in x and "valeur" in x:
                    out.append((chemin, json.dumps(x["valeur"], sort_keys=True, ensure_ascii=False), tuple(x["pages"] or [])))
                for k, y in x.items():
                    if k not in ("plan", "controle"):
                        visite(y, chemin + "/" + k)
            elif isinstance(x, list):
                for y in x:
                    visite(y, chemin)
        visite(d, "")
        return json.dumps(sorted(out), ensure_ascii=False)
    raise ValueError(champ)


def trois_sur_quatre(valeurs):
    c = Counter(v for v in valeurs if v is not None)
    return bool(c) and c.most_common(1)[0][1] >= 3


# ------------------------------------------------------------------ calcul

def main():
    so = {g: json.loads((IT4 / "sorties" / f"{g}.json").read_text(encoding="utf-8")) for g in GREENS}
    verite_pub = json.loads((RACINE / "data" / "v6" / "verite-publics.json").read_text(encoding="utf-8"))["verite"]
    table = json.loads((RACINE / "data" / "v6" / "assertion-fait.json").read_text(encoding="utf-8"))
    nux = RACINE / "runs-v5" / "h23" / "nuextract"
    son = RACINE / "runs-v5" / "h23" / "sonnet"
    synth = [i for i in ids() if i.startswith("S")]
    pub = [f"RC{i}" for i in range(1, 6)]

    def lire(d, i):
        f = d / f"{i}.json"
        return facts_bilel(json.loads(f.read_text(encoding="utf-8"))) if f.exists() else None

    cases = {}  # (rc, fait) → {"greens": [bool]*4, "regle": bool, "nux": bool|None, "son": bool|None}
    for rc in synth + pub:
        if rc.startswith("S"):
            v = situation(rc)["verite"]
            j = lambda f, x, vrai: juste_synth(f, x, vrai)  # noqa: E731
        else:
            v = verite_pub[rc]
            j = lambda f, x, vrai, v=v: juste_pub(f, x, vrai, v)  # noqa: E731
        fg = [facts_green(so[g].get(rc)) for g in GREENS]
        fn, fs = lire(nux, rc), lire(son, rc)
        for c in CHAMPS:
            gj = [bool(f) and j(c, f.get(c), v[c]) for f in fg]
            cases[(rc, c)] = {"greens": gj, "regle": sum(gj) >= 3,
                              "nux": None if fn is None else j(c, fn.get(c), v[c]),
                              "son": None if fs is None else j(c, fs.get(c), v[c])}

    res = {"definitions": "data/predictions/V6.md", "par_fait": {}, "accord": {}, "carte": {}, "part_deterministe": {}}
    for corpus, rcs in (("synthetiques", synth), ("publics", pub)):
        pf = {}
        for c in CHAMPS:
            l = [cases[(r, c)] for r in rcs]
            pf[c] = {"regle": round(sum(x["regle"] for x in l) / len(l), 3),
                     "greens": [round(sum(x["greens"][k] for x in l) / len(l), 3) for k in range(4)],
                     "satisfait": sum(x["regle"] for x in l) / len(l) >= 0.95}
        res["par_fait"][corpus] = pf
        acc = {}
        for ch in sorted({f for f in table.values() if f.startswith("@")}):
            ok = [trois_sur_quatre([champ_accord(so[g].get(r), ch) for g in GREENS]) for r in rcs]
            acc[ch] = {"accord_3_sur_4": round(sum(ok) / len(ok), 3), "satisfait": sum(ok) / len(ok) >= 0.95}
        res["accord"][corpus] = acc
        sat = {a: (acc[f]["satisfait"] if f.startswith("@") else pf[f]["satisfait"]) for a, f in table.items()}
        n_faits = sum(1 for f in table.values() if not f.startswith("@"))
        res["part_deterministe"][corpus] = {
            "assertions": len(sat), "satisfaites": sum(sat.values()), "part": round(sum(sat.values()) / len(sat), 3),
            "part_sur_les_11_faits": round(sum(s for a, s in sat.items() if not table[a].startswith("@")) / n_faits, 3),
            "non_satisfaites_par_champ": dict(Counter(table[a] for a, s in sat.items() if not s))}
        # carte des organes : synthétiques S000-S099 (passés par NuExtract), publics RC1-5
        rcs_c = [r for r in rcs if cases[(r, CHAMPS[0])]["nux"] is not None]
        carte = {"rc": len(rcs_c), "global": Counter(), "par_fait": {}}
        for c in CHAMPS:
            k = Counter()
            for r in rcs_c:
                x = cases[(r, c)]
                cl = "regle suffit" if x["regle"] else "petit modele necessaire" if x["nux"] else "personne ne sait"
                k[cl] += 1
                carte["global"][cl] += 1
                if not x["regle"] and not x["nux"] and x["son"]:
                    k["dont : sonnet sait"] += 1
                    carte["global"]["dont : sonnet sait"] += 1
            carte["par_fait"][c] = dict(k)
        tot = len(rcs_c) * len(CHAMPS)
        carte["global"] = {k: {"n": v, "part": round(v / tot, 3)} for k, v in carte["global"].items()}
        carte["justesse"] = {c: {"regle": round(sum(cases[(r, c)]["regle"] for r in rcs_c) / len(rcs_c), 3),
                                 "nuextract": round(sum(bool(cases[(r, c)]["nux"]) for r in rcs_c) / len(rcs_c), 3),
                                 "sonnet": round(sum(bool(cases[(r, c)]["son"]) for r in rcs_c) / len(rcs_c), 3)}
                             for c in CHAMPS}
        res["carte"][corpus] = carte
    res["cases_publics"] = {f"{r}/{c}": cases[(r, c)] for r in pub for c in CHAMPS}
    SORTIE.mkdir(parents=True, exist_ok=True)
    (SORTIE / "resultat.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for corpus in ("synthetiques", "publics"):
        print(f"\n== {corpus}")
        print("part déterministe :", json.dumps(res["part_deterministe"][corpus], ensure_ascii=False))
        print("carte :", json.dumps(res["carte"][corpus]["global"], ensure_ascii=False))
        for c in CHAMPS:
            print(f"  {c:22s} règle {res['par_fait'][corpus][c]['regle']:.2f}  greens {res['par_fait'][corpus][c]['greens']}  "
                  f"carte {res['carte'][corpus]['par_fait'][c]}  justesse {res['carte'][corpus]['justesse'][c]}")
        print("accord :", json.dumps(res["accord"][corpus], ensure_ascii=False))


if __name__ == "__main__":
    main()
