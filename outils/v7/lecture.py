"""Piste 1 de V7 (H31) : l'organe de lecture. La règle ne change pas, seule change la lecture des PDF.

    python outils/v7/lecture.py lire       # les 3 lectures + la référence → runs-v7/lecture/<lecture>.json
    python outils/v7/lecture.py rejouer    # les 4 greens it4 sur chaque lecture → runs-v7/lecture/<lecture>/<green>.json
    python outils/v7/lecture.py carte      # cases qui passent / régressent → runs-v7/lecture/resultat.json

Montage figé dans data/predictions/V7.md :
- la règle = les 4 greens de P12 à l'itération 4 (runs-v5/boucle/it4/greens/{H,H2,S,S2}/app.py), appelés tels quels ;
- lectures (sans modèle) : « brut » = pdftotext sans -layout ; « plumber » = pdfplumber, texte de la page puis
  chaque tableau ligne par ligne, cellules séparées par « | » ; « camelot » = pdftotext -layout puis les tableaux
  de Camelot (stream) en fin de page, même forme ; « reference » = pdftotext -layout (la lecture de V6) ;
- vérité = data/v6/verite-publics.json (après la relecture de Bilel) ; une case passe en « règle suffit » si ≥ 3
  greens sur 4 ont juste (mêmes règles de justesse que V6, outils/v6/carte.py).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent.parent
sys.path.insert(0, str(RACINE / "outils" / "v6"))
sys.path.insert(0, str(RACINE / "outils" / "v5"))
from boucle_v5 import REJOUER  # noqa: E402
from carte import CHAMPS, GREENS, facts_bilel, facts_green, juste_pub  # noqa: E402

PDF = Path("/home/user/v5work/rc")
IT4 = RACINE / "runs-v5" / "boucle" / "it4"
SORTIE = RACINE / "runs-v7" / "lecture"
RCS = [f"RC{i}" for i in range(1, 6)]
LECTURES = ["reference", "brut", "plumber", "camelot"]


def pdftotext(pdf, layout):
    out = subprocess.run(["pdftotext", *(["-layout"] if layout else []), str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    pages = out.split("\f")
    pages = pages[:-1] if pages and not pages[-1].strip() else pages
    return [x + "\f" for x in pages]  # comme V5 : chaque page garde son saut de page


def lignes(table):
    return "\n".join(" | ".join(" ".join(str(c or "").split()) for c in ligne) for ligne in table
                     if any(str(c or "").strip() for c in ligne))


def plumber(pdf):
    import pdfplumber
    pages = []
    with pdfplumber.open(str(pdf)) as d:
        for p in d.pages:
            t = p.extract_text() or ""
            tabs = [lignes(x) for x in p.extract_tables()]
            pages.append(t + "".join(f"\n\n[tableau]\n{x}" for x in tabs if x) + "\n\f")
    return pages


def camelot_(pdf):
    import camelot
    pages = pdftotext(pdf, True)
    for i in range(len(pages)):
        try:
            tabs = camelot.read_pdf(str(pdf), pages=str(i + 1), flavor="stream")
        except Exception:  # noqa: BLE001  une page sans tableau lisible garde sa lecture
            continue
        x = [lignes(t.df.values.tolist()) for t in tabs]
        pages[i] = pages[i][:-1] + "".join(f"\n\n[tableau]\n{y}" for y in x if y) + "\n\f"
    return pages


def lire(_):
    SORTIE.mkdir(parents=True, exist_ok=True)
    f = {"reference": lambda p: pdftotext(p, True), "brut": lambda p: pdftotext(p, False),
         "plumber": plumber, "camelot": camelot_}
    for nom in LECTURES:
        sit = {rc: f[nom](PDF / f"{rc}.pdf") for rc in RCS}
        (SORTIE / f"{nom}.json").write_text(json.dumps(sit, ensure_ascii=False, indent=0), encoding="utf-8")
        print(nom, {rc: (len(p), sum(len(x) for x in p), sum(x.count("[tableau]") for x in p)) for rc, p in sit.items()})


def rejouer(_):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "rejouer.py"
        script.write_text(REJOUER, encoding="utf-8")
        for nom in LECTURES:
            (SORTIE / nom).mkdir(parents=True, exist_ok=True)
            for g in GREENS:
                r = subprocess.run([sys.executable, str(script), str(IT4 / "greens" / g / "app.py"), str(SORTIE / f"{nom}.json")],
                                   capture_output=True, text=True, timeout=600, cwd=str(IT4 / "greens" / g))
                out = {x["id"]: x["r"] for x in map(json.loads, r.stdout.splitlines()) if x}
                (SORTIE / nom / f"{g}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        # contrôle : la lecture de référence doit redonner les sorties it4 de V6
        for g in GREENS:
            a = json.loads((SORTIE / "reference" / f"{g}.json").read_text(encoding="utf-8"))
            b = json.loads((IT4 / "sorties" / f"{g}.json").read_text(encoding="utf-8"))
            print(g, "référence = it4 :", all(a[rc] == b.get(rc) for rc in RCS))


def carte(_):
    verite = json.loads((RACINE / "data" / "v6" / "verite-publics.json").read_text(encoding="utf-8"))["verite"]
    nux = RACINE / "runs-v5" / "h23" / "nuextract"
    cases = {}
    for nom in LECTURES:
        so = {g: json.loads((SORTIE / nom / f"{g}.json").read_text(encoding="utf-8")) for g in GREENS}
        for rc in RCS:
            v = verite[rc]
            fg = [facts_green(so[g].get(rc)) for g in GREENS]
            fn = facts_bilel(json.loads((nux / f"{rc}.json").read_text(encoding="utf-8")))
            for c in CHAMPS:
                gj = [bool(f) and juste_pub(c, f.get(c), v[c], v) for f in fg]
                cases[(nom, rc, c)] = {"greens": gj, "regle": sum(gj) >= 3, "nux": juste_pub(c, fn.get(c), v[c], v)}

    def classe(x):
        return "regle suffit" if x["regle"] else "petit modele necessaire" if x["nux"] else "personne ne sait"

    ref = {(rc, c): classe(cases[("reference", rc, c)]) for rc in RCS for c in CHAMPS}
    pns = [k for k, v in ref.items() if v == "personne ne sait"]
    res = {"definitions": "data/predictions/V7.md", "reference": {
        "personne ne sait": len(pns), "regle suffit": sum(v == "regle suffit" for v in ref.values()),
        "cases_personne_ne_sait": [f"{rc}/{c}" for rc, c in pns]}, "lectures": {}}
    for nom in LECTURES[1:]:
        passe = [f"{rc}/{c}" for rc, c in pns if cases[(nom, rc, c)]["regle"]]
        gagne = [f"{rc}/{c}" for (rc, c), v in ref.items() if v != "regle suffit" and cases[(nom, rc, c)]["regle"]]
        perd = [f"{rc}/{c}" for (rc, c), v in ref.items() if v == "regle suffit" and not cases[(nom, rc, c)]["regle"]]
        res["lectures"][nom] = {"passent_de_personne_ne_sait": passe, "gains_toutes_classes": gagne, "regressions": perd,
                                "gain_net": len(gagne) - len(perd),
                                "H31": len(passe) >= 3 and len(gagne) - len(perd) > 0,
                                "regle_suffit": sum(cases[(nom, rc, c)]["regle"] for rc in RCS for c in CHAMPS)}
    res["cases"] = {f"{n}/{rc}/{c}": x for (n, rc, c), x in cases.items()}
    (SORTIE / "resultat.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "cases"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["lire", "rejouer", "carte"])
    a = ap.parse_args()
    {"lire": lire, "rejouer": rejouer, "carte": carte}[a.cmd](a)
