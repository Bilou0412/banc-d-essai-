"""Accord entre N greens sur les mêmes situations (H20, version « tous contre tous »).

Usage :
    python outils/quatre.py P11 H1 H2 S1 S2

Pour chaque situation, on cherche la première étape où les greens ne montrent pas
tous la même chose, et on note comment ils se partagent : « 3 contre 1 » désigne un
green qui s'écarte seul (son comportement est minoritaire), « 2 contre 2 » est un
partage sans majorité. Ne lit que les traces en cache (outils/differentiel.py traces).
"""
import json
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def charger(sonde, nom, n=300):
    t1, t2, _ = json.loads((RACINE / "runs-v4" / sonde / "traces" / f"{nom}-{n}.json").read_text(encoding="utf-8"))
    return {int(k): v for k, v in t1.items() if t2.get(k) == v and not isinstance(v, dict)}


def main():
    sonde, noms = sys.argv[1], sys.argv[2:]
    tr = {n: charger(sonde, n) for n in noms}
    graines = sorted(set.intersection(*(set(t) for t in tr.values())))
    tous, majorite, formes, ecarts = 0, 0, Counter(), Counter()
    for g in graines:
        seqs = [tr[n][g] for n in noms]
        if all(s == seqs[0] for s in seqs):
            tous += 1
            continue
        i = 0
        while all(i < len(s) for s in seqs) and all(s[i] == seqs[0][i] for s in seqs):
            i += 1
        obs = [json.dumps(s[i], ensure_ascii=False, sort_keys=True) if i < len(s) else "(fin)" for s in seqs]
        groupes = Counter(obs)
        forme = " contre ".join(str(c) for c in sorted(groupes.values(), reverse=True))
        formes[forme] += 1
        action = str(next((s[i][0] for s in seqs if i < len(s)), "?"))
        action = action.split("(")[0]
        if sorted(groupes.values()) == [1, len(noms) - 1]:
            seul = noms[obs.index(next(o for o, c in groupes.items() if c == 1))]
            ecarts[(seul, action)] += 1
        # accord à la fin : au moins N-1 greens identiques sur toute la situation
        fin = Counter(json.dumps(s, ensure_ascii=False, sort_keys=True) for s in seqs)
        if max(fin.values()) >= len(noms) - 1:
            majorite += 1
    res = {"sonde": sonde, "greens": noms, "situations": len(graines), "tous_identiques": tous,
           "au_moins_n_moins_1": majorite + tous, "formes_premier_ecart": dict(formes),
           "ecart_seul_par_green": dict(Counter(s for s, _ in ecarts.elements())),
           "ecart_seul_par_action": {f"{s} / {a}": c for (s, a), c in ecarts.most_common()}}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    (RACINE / "runs-v4" / sonde / f"accord-{'-'.join(noms)}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
