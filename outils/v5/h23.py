"""H23 : justesse (synthétiques) et accord (publics) de A (NuExtract + vérification) et B (sonnet + même vérification).

    python outils/v5/h23.py            → tableau, et runs-v5/h23/resultat.json

Les sorties viennent de outils/v5/h23_passer.py (le Facts de BuildForge, tel quel).
On ne compte que les RC passés par les DEUX modèles. Une sortie en erreur compte comme fausse partout.

Règles de justesse, fait par fait (la vérité vient du générateur) :
  - fait absent du RC : juste si « not_found » ;
  - fait présent : juste si le statut est le bon (found, ou conflict quand le RC se contredit)
    ET les valeurs gardées sont exactement les vraies (comparées après normalisation) ;
  - dates : jour (et heure quand le RC la donne) ; lots : numéros sans zéros de tête ; mode de remise :
    l'adresse de la plateforme apparaît dans le texte gardé ; critères : même ensemble de
    (lot, libellé, poids, unité, rang, sous-critères avec leurs poids) ; pièces : chaque pièce vraie
    retrouvée une fois (libellé), dans la bonne partie, sans pièce en trop.
Familles : « simples » = les 9 faits hors critères et pièces.
« Confirmés par l'algorithme seul » : faits présents dans le RC pour lesquels le pipeline garde au moins
une valeur (proposée par le modèle ET retrouvée dans la page).
« Faux affichés comme trouvés » : faits rendus found/conflict mais faux, sur tous les faits rendus found/conflict.
"""
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from situations import RACINE, situation  # noqa: E402

H23 = RACINE / "runs-v5" / "h23"
CHAMPS = ["offer_deadline", "questions_deadline", "procedure", "lots", "site_visit", "site_visit_dates",
          "submission_mode", "offer_validity", "variants", "award_criteria", "documents_to_return"]
SIMPLES = CHAMPS[:9]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("œ", "oe")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except ValueError:
        return None


def lotnum(n):
    return None if n is None else (str(n).lstrip("0") or "0")


def canon(field, values):
    """Valeurs d'un fait → un objet comparable (ensemble trié)."""
    out = []
    for v in values:
        v = v.get("value", v)
        if field in ("offer_deadline", "questions_deadline"):
            out.append((v.get("date"), v.get("time")))
        elif field == "site_visit_dates":
            out.append(v.get("date"))
        elif field == "procedure":
            out.append(v.get("procedure"))
        elif field == "lots":
            out.append(lotnum(v.get("number")))
        elif field in ("site_visit", "variants"):
            out.append(v.get("value"))
        elif field == "offer_validity":
            out.append((v.get("amount"), v.get("unit")))
        elif field == "submission_mode":
            out.append(norm(v.get("text")))
        elif field == "award_criteria":
            w = v.get("weight") or {}
            subs = tuple(sorted((norm(s.get("wording")), num((s.get("weight") or {}).get("amount")), (s.get("weight") or {}).get("unit"))
                                for s in v.get("sub_criteria", [])))
            out.append((lotnum(v.get("lot")), norm(v.get("wording")), num(w.get("amount")), w.get("unit"), v.get("rank"), subs))
        elif field == "documents_to_return":
            out.append((norm(v.get("wording")), v.get("part")))
    return sorted(set(out), key=repr)


def juste(field, fait, vrai):
    statut = fait["status"] if fait else "erreur"
    if vrai["statut"] == "not_found":
        return statut == "not_found"
    if statut != vrai["statut"]:
        return False
    vals = fait["values"]
    if field in ("offer_deadline", "questions_deadline"):
        t = sorted({(x["date"], x["time"]) for x in vrai["valeurs"]}, key=repr)
        return canon(field, vals) == t
    if field == "site_visit_dates":
        return canon(field, vals) == sorted(set(vrai["valeurs"]))
    if field == "procedure":
        return canon(field, vals) == vrai["valeurs"]
    if field == "lots":
        return canon(field, vals) == sorted({lotnum(x.get("number")) for x in vrai["valeurs"]}, key=repr)
    if field in ("site_visit", "variants"):
        return canon(field, vals) == vrai["valeurs"]
    if field == "offer_validity":
        return canon(field, vals) == [(x["amount"], x["unit"]) for x in vrai["valeurs"]]
    if field == "submission_mode":
        url = norm(vrai["valeurs"][0].split("//")[-1])
        return len(vals) == 1 and url in canon(field, vals)[0]
    if field == "award_criteria":
        a = canon(field, vals)
        t = sorted({(lotnum(c["lot"]), norm(c["wording"]), num((c["weight"] or {}).get("amount")), (c["weight"] or {}).get("unit"), c["rank"],
                     tuple(sorted((norm(s["wording"]), num((s["weight"] or {}).get("amount")), (s["weight"] or {}).get("unit")) for s in c["sub_criteria"])))
                    for c in vrai["valeurs"]}, key=repr)
        return a == t
    if field == "documents_to_return":
        a = canon(field, vals)
        reste = list(a)
        for d in vrai["valeurs"]:
            cle = norm(d["wording"])[:30]
            m = next((x for x in reste if cle in x[0] and x[1] == d["part"]), None)
            if m is None:
                return False
            reste.remove(m)
        return not reste
    return False


def faits(sortie):
    if not sortie or "facts" not in sortie:
        return {}
    return {f["field"]: f for f in sortie["facts"]}


def lire(modele, i):
    f = H23 / modele / f"{i}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def main():
    ida = {p.stem for p in (H23 / "nuextract").glob("*.json")}
    idb = {p.stem for p in (H23 / "sonnet").glob("*.json")}
    communs = sorted(ida & idb)
    synth = [i for i in communs if i.startswith("S")]
    publics = [i for i in communs if i.startswith("RC")]
    res = {"rc_synthetiques": len(synth), "rc_publics": len(publics)}
    par = {m: defaultdict(lambda: [0, 0]) for m in ("A", "B")}
    confirme = {m: [0, 0] for m in ("A", "B")}
    faux_trouves = {m: [0, 0] for m in ("A", "B")}
    par_trait = {m: defaultdict(lambda: [0, 0]) for m in ("A", "B")}
    echecs_A = defaultdict(int)
    secondes = defaultdict(list)
    for i in synth:
        s = situation(i)
        for m, mod in (("A", "nuextract"), ("B", "sonnet")):
            out = lire(mod, i)
            secondes[m].append(out.get("secondes", 0) if out else 0)
            fa = faits(out)
            for c in CHAMPS:
                v = s["verite"][c]
                ok = juste(c, fa.get(c), v)
                par[m][c][0] += ok
                par[m][c][1] += 1
                for t in s["traits"]:
                    if c == "award_criteria" or (c == "documents_to_return" and t == "pieces-sur-plusieurs-pages"):
                        par_trait[m][f"{c} | {t}"][0] += ok
                        par_trait[m][f"{c} | {t}"][1] += 1
                st = fa.get(c, {}).get("status")
                if v["statut"] != "not_found":
                    confirme[m][0] += st in ("found", "conflict")
                    confirme[m][1] += 1
                if st in ("found", "conflict"):
                    faux_trouves[m][0] += not ok
                    faux_trouves[m][1] += 1
                if m == "A" and not ok:
                    echecs_A[c] += 1

    def taux(m, champs):
        j = sum(par[m][c][0] for c in champs)
        n = sum(par[m][c][1] for c in champs)
        return round(j / n, 3) if n else None
    for m in ("A", "B"):
        res[m] = {"justesse": taux(m, CHAMPS), "simples": taux(m, SIMPLES), "criteres": taux(m, ["award_criteria"]),
                  "pieces": taux(m, ["documents_to_return"]),
                  "par_fait": {c: round(par[m][c][0] / par[m][c][1], 3) for c in CHAMPS if par[m][c][1]},
                  "confirmes_algorithme": round(confirme[m][0] / confirme[m][1], 3) if confirme[m][1] else None,
                  "faux_affiches_trouves": round(faux_trouves[m][0] / faux_trouves[m][1], 3) if faux_trouves[m][1] else None,
                  "secondes_mediane": sorted(secondes[m])[len(secondes[m]) // 2] if secondes[m] else None,
                  "par_trait": {k: f"{v[0]}/{v[1]}" for k, v in sorted(par_trait[m].items())}}
    if res["A"]["justesse"] is not None:
        res["ecart"] = round(res["B"]["justesse"] - res["A"]["justesse"], 3)
        res["ecart_simples"] = round(res["B"]["simples"] - res["A"]["simples"], 3)
        res["H23"] = "confirmée" if res["ecart"] <= 0.10 else "réfutée"
    # accord A-B sur les publics, et part confirmée sur les publics
    acc = [0, 0]
    conf_pub = {m: [0, 0] for m in ("A", "B")}
    for i in publics:
        fa, fb = faits(lire("nuextract", i)), faits(lire("sonnet", i))
        for c in CHAMPS:
            a, b = fa.get(c), fb.get(c)
            same = bool(a and b) and a["status"] == b["status"] and canon(c, a["values"]) == canon(c, b["values"])
            acc[0] += same
            acc[1] += 1
            for m, f in (("A", a), ("B", b)):
                if f and f["status"] != "not_found":
                    conf_pub[m][0] += f["status"] in ("found", "conflict")
                conf_pub[m][1] += 1
    res["accord_publics"] = round(acc[0] / acc[1], 3) if acc[1] else None
    res["echecs_A_par_fait"] = dict(sorted(echecs_A.items(), key=lambda kv: -kv[1]))
    (H23 / "resultat.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("A", "B")}, ensure_ascii=False))
    for m in ("A", "B"):
        print(m, json.dumps({k: v for k, v in res[m].items() if k != "par_trait"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
