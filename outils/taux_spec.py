"""Deux taux par itération de la boucle P11 : brut, et « spec » (les divergences classées bug comptent comme un accord).

Usage : python outils/taux_spec.py            → tableau, et runs-boucle/P11/taux.json

Taux brut d'une paire : situations où les deux codes montrent partout la même chose.
Taux spec d'une paire : idem, mais une situation dont la PREMIÈRE divergence entre les deux codes tombe dans
un groupe jugé « bug » d'un des deux (et pas de l'autre) compte comme un accord : la spec, elle, tranchait.
Le groupe est retrouvé comme dans boucle.py (action sans la personne + champs qui diffèrent). Une divergence
dans un groupe non jugé reste une divergence (le taux spec est donc une borne basse).
Accord à 4 « spec » : les 4 codes d'accord, ou première divergence à 4 dans un groupe jugé bug.
"""
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
from boucle import BASE, GREENS, chemins_differents, est_bug  # noqa: E402
from differentiel import nom_action  # noqa: E402


def cle(action, obs):
    base = nom_action(action).split(".")[-1]
    champs = sorted(set(chemins_differents(obs)))
    return f"{base} [{', '.join(champs[:3])}]"


def premiere(seqs):
    k = 0
    while all(k < len(s) for s in seqs) and all(s[k] == seqs[0][k] for s in seqs):
        k += 1
    obs = [s[k][1] if k < len(s) else "(fin de la situation)" for s in seqs]
    action = next((s[k][0] for s in seqs if k < len(s)), "?")
    return action, obs


def un_lot(d):
    tr = {n: {int(k): v for k, v in json.loads((d / "traces" / f"{n}.json").read_text(encoding="utf-8")).items()} for n in GREENS}
    bugs = {}
    for g in json.loads((d / "groupes.json").read_text(encoding="utf-8")):
        f = est_bug(g)
        if f:
            bugs[g["groupe"]] = set(f)
    noms = list(GREENS)
    graines = sorted(set.intersection(*(set(t) for t in tr.values())))
    brut, spec = {}, {}
    for x in range(4):
        for y in range(x + 1, 4):
            a, b = noms[x], noms[y]
            ok = ok_s = 0
            for g in graines:
                if tr[a][g] == tr[b][g]:
                    ok += 1
                    ok_s += 1
                    continue
                action, obs = premiere([tr[a][g], tr[b][g]])
                fautifs = bugs.get(cle(action, obs))
                if fautifs and len(fautifs & {a, b}) == 1:
                    ok_s += 1
            brut[f"{a}-{b}"] = round(ok / len(graines), 3)
            spec[f"{a}-{b}"] = round(ok_s / len(graines), 3)
    # taux par action : part des étapes où deux codes montrent la même chose (moyenne des 6 paires)
    par_action = {}
    for x in range(4):
        for y in range(x + 1, 4):
            a, b = noms[x], noms[y]
            eg = tot = 0
            for g in graines:
                sa, sb = tr[a][g], tr[b][g]
                tot += max(len(sa), len(sb))
                eg += sum(1 for p, q in zip(sa, sb) if p == q)
            par_action[f"{a}-{b}"] = round(eg / tot, 3)
    tous = tous_s = 0
    for g in graines:
        seqs = [tr[n][g] for n in noms]
        if all(s == seqs[0] for s in seqs):
            tous += 1
            tous_s += 1
            continue
        action, obs = premiere(seqs)
        if cle(action, obs) in bugs:
            tous_s += 1
    n = len(graines)
    return {"brut": round(sum(brut.values()) / 6, 3), "spec": round(sum(spec.values()) / 6, 3),
            "accord4_brut": round(tous / n, 3), "accord4_spec": round(tous_s / n, 3), "par_action": round(sum(par_action.values()) / 6, 3), "paires_brut": brut, "paires_spec": spec}


def main():
    res = {}
    for d in sorted(BASE.glob("it*"), key=lambda p: int(p.name[2:])):
        for l in sorted((d / "lots").glob("*")) if (d / "lots").exists() else []:
            if (l / "groupes.json").exists():
                r = un_lot(l)
                res[f"{d.name}-{l.name}"] = r
                print(f"{d.name} lot {l.name} : brut {r['brut']:.3f}  spec {r['spec']:.3f}   "
                      f"accord à 4 brut {r['accord4_brut']:.3f}  spec {r['accord4_spec']:.3f}   par action {r['par_action']:.3f}")
    (BASE / "taux.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
