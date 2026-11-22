"""Le green Bilel comparé à part, sur ses 11 faits (V5).

    python outils/v5/bilel.py --it 0 [--juger 6]

Le code de Bilel (NuExtract + vérification, runs-v5/h23/nuextract/) ne change pas d'une itération à l'autre ;
les greens H et S changent. Pour chaque RC passé par Bilel et chaque fait, on compare la forme canonique
de Bilel à celle de la « majorité » (H et S d'accord sur ce fait). Les faits où H et S divergent ne comptent pas.
Les divergences sont rangées par fait ; les plus fréquentes sont jugées par un juge opus :
trou (la spec v_i ne tranche pas) / bug Bilel / bug majorité.
Écrit runs-v5/boucle/it<i>/bilel.json.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(ICI.parent))
from boucle_v5 import BASE, RACINE, appel, formater, garde, it_dir, noter, spec  # noqa: E402
from h23 import CHAMPS, faits, lotnum, norm, num  # noqa: E402
from situations import situation  # noqa: E402

JUGE = """Un code a lu un règlement de la consultation (RC). Une majorité de codes écrits sur la spécification ci-dessous
rend autre chose pour un fait. Le premier code n'a pas été écrit sur cette spécification : il suit ses propres choix.

Spécification (assertions) :
{assertions}

Le RC (texte page par page) :
{pages}

Fait : {champ}
  Code B (le premier code) rend : {b}
  La majorité rend : {m}

Classe ce désaccord. Un seul choix :
- trou : la spécification ne tranche pas ce cas ; les deux lectures la respectent.
- bug B : la spécification tranche, et le code B la viole.
- bug majorité : la spécification tranche, et la majorité la viole.
Termine par exactement deux lignes :
CLASSE: trou | bug B | bug majorité
CAS: <le cas en une phrase>
N'écris aucun fichier.
"""

PROC = [("adapt", "procedure_adaptee"), ("ouvert", "appel_offres_ouvert"), ("restreint", "appel_offres_restreint"),
        ("negoci", "procedure_negociee"), ("dialogue", "dialogue_competitif")]


def iso(s):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})$", str(s or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else norm(s)


def vals(fait):
    if not isinstance(fait, dict) or fait.get("statut") != "trouvé":
        return []
    return [v.get("valeur") for v in fait.get("valeurs", [])]


def canon_green(d):
    """Dossier d'un green (interface fixée par les tests du duel) → 11 faits canoniques."""
    if not isinstance(d, dict) or "__erreur__" in d:
        return None
    c = {}
    dates, heures = vals(d.get("date_limite")), vals(d.get("heure_limite"))
    c["offer_deadline"] = sorted({(iso(x), heures[0] if len(heures) == 1 else None) for x in dates}, key=repr)
    c["questions_deadline"] = sorted({iso(x) for x in vals(d.get("date_questions"))})
    c["procedure"] = sorted({next((e for k, e in PROC if k in norm(x)), "autre") for x in vals(d.get("procedure"))})
    lots = (d.get("lots") or {}).get("liste") or []
    c["lots"] = sorted({lotnum(l.get("numero")) for l in lots if isinstance(l, dict)}, key=repr)
    c["site_visit"] = sorted({x == "oui" for x in vals(d.get("visite_obligatoire"))})
    c["site_visit_dates"] = sorted({iso(x) for x in vals(d.get("dates_visite"))})
    c["submission_mode"] = sorted({norm(x) for x in vals(d.get("mode_remise"))})
    c["offer_validity"] = sorted({(x.get("nombre"), {"jours": "days", "mois": "months"}.get(x.get("unite")))
                                  for x in vals(d.get("validite_offres")) if isinstance(x, dict)}, key=repr)
    c["variants"] = sorted({x == "autorisées" for x in vals(d.get("variantes"))})
    crit = []
    for k in (d.get("criteres") or {}).get("liste") or []:
        for p in (k.get("ponderation") or {}).get("valeurs") or [{"valeur": {}}]:
            v = p.get("valeur") if isinstance(p.get("valeur"), dict) else p
            u = {"pourcentage": "percent", "points": "points", "rang": "rang"}.get(v.get("unite"))
            crit.append((lotnum(v.get("lot")), norm(k.get("libelle")), None if u == "rang" else num(v.get("valeur")),
                         None if u == "rang" else u, v.get("valeur") if u == "rang" else None))
    c["award_criteria"] = sorted(set(crit), key=repr)
    c["documents_to_return"] = sorted({(norm(p.get("nom"))[:30], (vals(p.get("phase")) or [None])[0])
                                       for p in (d.get("pieces") or {}).get("liste") or []}, key=repr)
    return c


def canon_bilel(sortie):
    f = faits(sortie)
    if not f:
        return None
    c = {}

    def v(field):
        x = f[field]
        return [s["value"] for s in x["values"]] if x["status"] in ("found", "conflict") else []
    od = v("offer_deadline")
    c["offer_deadline"] = sorted({(x["date"], x.get("time")) for x in od}, key=repr)
    c["questions_deadline"] = sorted({x["date"] for x in v("questions_deadline")})
    c["procedure"] = sorted({x["procedure"] for x in v("procedure")})
    c["lots"] = sorted({lotnum(x.get("number")) for x in v("lots")}, key=repr)
    c["site_visit"] = sorted({x["value"] for x in v("site_visit")})
    c["site_visit_dates"] = sorted({x["date"] for x in v("site_visit_dates")})
    t = " ".join(norm(x["text"]) for x in v("submission_mode"))
    c["submission_mode"] = (["electronique"] if re.search(r"electron|dematerial|plateforme|profil|http|www", t)
                            else ["papier"] if t else [])
    c["offer_validity"] = sorted({(x["amount"], x["unit"]) for x in v("offer_validity")}, key=repr)
    c["variants"] = sorted({x["value"] for x in v("variants")})
    c["award_criteria"] = sorted({(lotnum(x.get("lot")), norm(x["wording"]), num((x.get("weight") or {}).get("amount")),
                                   (x.get("weight") or {}).get("unit"), x.get("rank")) for x in v("award_criteria")}, key=repr)
    c["documents_to_return"] = sorted({(norm(x["wording"])[:30], x.get("part")) for x in v("documents_to_return")}, key=repr)
    return c


def comparer(i):
    so = {g: json.loads((it_dir(i) / "sorties" / f"{g}.json").read_text(encoding="utf-8")) for g in ("H", "S")}
    divergences = defaultdict(list)
    compte = Counter()
    for f in sorted((RACINE / "runs-v5" / "h23" / "nuextract").glob("*.json")):
        k = f.stem
        if k not in so["H"] or k not in so["S"]:
            continue
        b = canon_bilel(json.loads(f.read_text(encoding="utf-8")))
        h, s = canon_green(so["H"][k]), canon_green(so["S"][k])
        if not (b and h and s):
            continue
        for c in CHAMPS:
            if h[c] != s[c]:
                compte["majorite_absente"] += 1
                continue
            compte["compares"] += 1
            if b[c] != h[c]:
                divergences[c].append((k, b[c], h[c]))
    return compte, divergences


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--it", type=int, required=True)
    ap.add_argument("--juger", type=int, default=6)
    a = ap.parse_args()
    i = a.it
    compte, div = comparer(i)
    ordre = sorted(div.items(), key=lambda kv: -len(kv[1]))
    res = {"iteration": i, **compte, "divergences": sum(len(v) for v in div.values()),
           "accord": round(1 - sum(len(v) for v in div.values()) / max(compte["compares"], 1), 3),
           "par_fait": {c: len(v) for c, v in ordre}, "jugements": []}
    a_juger = ordre[:a.juger]
    if a_juger:
        garde(0.15 * len(a_juger), f"juge du green Bilel ({len(a_juger)} faits, it{i})")
    for c, lst in a_juger:
        k, b, m = min(lst, key=lambda x: sum(map(len, situation(x[0])["pages"])))
        pages = situation(k)["pages"]
        texte = JUGE.format(assertions=formater(spec(i)), champ=c, b=json.dumps(b, ensure_ascii=False)[:1200],
                            m=json.dumps(m, ensure_ascii=False)[:1200],
                            pages="\n".join(f"──── page {n} ────\n{p}" for n, p in enumerate(pages, 1))[:24000])
        travail = Path(tempfile.mkdtemp(prefix="v5-bilel-"))
        shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
        r, t = appel("judge", texte, "opus", "Write", travail, delai=3600)
        noter(f"it{i}/bilel/{c}", t)
        txt = str(r.get("result", ""))
        cl = (re.search(r"^\**CLASSE\**:\s*(.+)$", txt, re.M) or [None, ""])[1].strip().lower()
        cas = (re.search(r"^\**CAS\**:\s*(.+)$", txt, re.M) or [None, ""])[1].strip()
        cl = "trou" if cl.startswith("trou") else "bug Bilel" if "bug b" in cl else "bug majorité" if "major" in cl else "non classé"
        res["jugements"].append({"fait": c, "divergences": len(lst), "rc": k, "bilel": b, "majorite": m, "classe": cl, "cas": cas})
        print(f"  {c} ({len(lst)}) → {cl} : {cas}", flush=True)
    n = sum(j["divergences"] for j in res["jugements"]) or 1
    res["part_ponderee"] = {cl: round(sum(j["divergences"] for j in res["jugements"] if j["classe"] == cl) / n, 3)
                            for cl in ("trou", "bug Bilel", "bug majorité", "non classé")}
    (it_dir(i) / "bilel.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "jugements"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
