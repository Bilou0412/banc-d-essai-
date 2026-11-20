"""Champ local compté par CAUSE, pas par test (duel V2).

Usage :
    python outils/causes.py runs-v1/P10            # recalcule depuis journal.jsonl + bilan.json
    python outils/causes.py runs-v1/*              # plusieurs duels

Une cause = un message d'erreur (même message = même cause), une fois normalisé :
première ligne, adresses mémoire (0x…) effacées, espaces resserrés.
Le chemin du module de test est effacé aussi : une panne d'import vue depuis
test_app.py et depuis test_app_2.py est la même cause.

Champ local d'une assertion = nombre de causes distinctes rencontrées par ses tests
avant qu'elle passe (0 si elle passe du premier coup). Moyenne par sonde, séparée
pour les assertions frontière et pour les autres. Écrit `causes` dans bilan.json.
"""
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
from mesure import frontieres  # noqa: E402


def cause(message):
    m = (message or "échec sans message").strip()
    m = m.replace("non exécuté : ", "")
    m = re.sub(r"0x[0-9a-f]+", "0x…", m)
    m = re.sub(r"'[^']*/tests/test_app(_2)?\.py'", "'tests'", m)
    lignes = [l for l in m.splitlines() if l.strip()]
    return re.sub(r"\s+", " ", lignes[0] if lignes else m)[:200]


def calculer(journal, ids, frontiere):
    """journal : liste des tours ; ids : identifiants des assertions de la passe."""
    par_assertion = {i: set() for i in ids}
    par_tour = []
    toutes = set()
    for t in journal:
        vues = set()
        for e in t["echecs"]:
            c = cause(e.get("message"))
            vues.add(c)
            if e.get("assertion") in par_assertion:
                par_assertion[e["assertion"]].add(c)
        par_tour.append(len(vues))
        toutes |= vues

    def moyenne(sel):
        v = [len(par_assertion[i]) for i in sel]
        return round(sum(v) / len(v), 2) if v else None

    fr = [i for i in ids if frontiere.get(i)]
    autres = [i for i in ids if not frontiere.get(i)]
    return {
        "causes_distinctes": len(toutes),
        "causes_par_tour": par_tour,
        "champ_local": {"tout": moyenne(ids), "frontiere": moyenne(fr), "autres": moyenne(autres)},
        "par_assertion": {i: len(c) for i, c in par_assertion.items() if c},
        "liste": sorted(toutes),
    }


def recalculer(dossier):
    dossier = Path(dossier)
    bilan = json.loads((dossier / "bilan.json").read_text(encoding="utf-8"))
    journal = [json.loads(l) for l in (dossier / "journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    passe = RACINE / "data" / "passes" / bilan.get("passes", "strict") / f"{bilan['sonde']}_{bilan.get('passe', 'A')}.txt"
    drapeaux = frontieres(passe)
    ids = [f"A{i:02d}" for i in range(1, len(drapeaux) + 1)]
    res = calculer(journal, ids, dict(zip(ids, drapeaux)))
    bilan["causes"] = res
    (dossier / "bilan.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
    return bilan["sonde"], res


if __name__ == "__main__":
    for d in sys.argv[1:]:
        sonde, r = recalculer(d)
        print(f"{d}: {r['causes_distinctes']} cause(s) distincte(s), par tour {r['causes_par_tour']}, "
              f"champ local {r['champ_local']}")
        for c in r["liste"]:
            print(f"    - {c}")
