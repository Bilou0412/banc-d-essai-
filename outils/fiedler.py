"""G2 : valeur de Fiedler λ2 du réseau d'assertions, contre k (H24). Sans appel de modèle.

Usage : python outils/fiedler.py        → tableau, et data/fiedler.json

Choix figés dans data/predictions/G2-H24.md : graphe de mesure.py, laplacien normalisé pondéré,
plus grande composante connexe. Passes v2 (strict-v2) et v2-xl (P11), jamais v1.
"""
import glob
import json
import os
import statistics as st
import sys
from pathlib import Path

import networkx as nx
import numpy as np

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
from mesure import lire_passe  # noqa: E402

DOSSIERS = ["data/passes/strict-v2", "data/passes/strict-v2-xl"]
TOURS = {"P02": 2, "P05": 2, "P06": 3, "P07": 2, "P08": 3, "P10": 4, "P11": 4}  # duels V1, V2, V4 (passes v2)


def graphe(assertions):
    ens = [{o} | c for o, c in assertions]
    etats = set().union(*ens)
    compte = {e: sum(e in a for a in ens) for e in etats}
    champ = max(sorted(compte), key=compte.get)
    G = nx.Graph()
    G.add_nodes_from(range(len(ens)))
    for i in range(len(ens)):
        for j in range(i + 1, len(ens)):
            w = len((ens[i] & ens[j]) - {champ})
            if w:
                G.add_edge(i, j, weight=w)
    return G, st.mean(len(a) for a in ens)


def fiedler(G):
    comp = max(nx.connected_components(G), key=len)
    H = G.subgraph(comp)
    if H.number_of_nodes() < 3:
        return 0.0, len(comp)
    noeuds = list(H)
    W = nx.to_numpy_array(H, nodelist=noeuds, weight="weight")  # numpy seul, sans scipy
    d = W.sum(axis=1)
    Dm = np.diag(1 / np.sqrt(d))
    L = np.eye(len(noeuds)) - Dm @ W @ Dm
    vals = np.sort(np.linalg.eigvalsh(L))
    return float(vals[1]), len(comp)


def spearman(x, y):
    def rangs(v):
        ordre = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[ordre[j + 1]] == v[ordre[i]]:
                j += 1
            for t in range(i, j + 1):
                r[ordre[t]] = (i + j) / 2 + 1
            i = j + 1
        return r
    a, b = rangs(x), rangs(y)
    ma, mb = st.mean(a), st.mean(b)
    num = sum((p - ma) * (q - mb) for p, q in zip(a, b))
    den = (sum((p - ma) ** 2 for p in a) * sum((q - mb) ** 2 for q in b)) ** 0.5
    return num / den if den else 0.0


def ecart_rel(v):
    return (max(v) - min(v)) / st.median(v) if st.median(v) else float("nan")


def main():
    passes = {}
    for d in DOSSIERS:
        for f in sorted(glob.glob(str(RACINE / d / "*.txt"))):
            nom = os.path.basename(f)[:-4]
            A = lire_passe(f)
            G, k = graphe(A)
            l2, taille = fiedler(G)
            passes[nom] = {"k": round(k, 3), "lambda2": round(l2, 4), "n": len(A), "composante": taille,
                           "hors_composante": round(1 - taille / len(A), 3)}
            print(f"{nom:7s} k={k:.2f}  λ2={l2:.4f}  assertions={len(A)}  hors plus grande composante={1 - taille / len(A):.0%}")
    sondes = {}
    for nom, m in passes.items():
        sondes.setdefault(nom.split("_")[0], []).append(m)
    print()
    res = {}
    for s, ms in sorted(sondes.items()):
        ks, ls = [m["k"] for m in ms], [m["lambda2"] for m in ms]
        res[s] = {"k": st.median(ks), "lambda2": st.median(ls), "ecart_rel_k": round(ecart_rel(ks), 3),
                  "ecart_rel_lambda2": round(ecart_rel(ls), 3), "passes": len(ms)}
        print(f"{s}: k {st.median(ks):.2f} (écart rel. {ecart_rel(ks):.1%})   λ2 {st.median(ls):.4f} (écart rel. {ecart_rel(ls):.1%})")
    mk = st.median(r["ecart_rel_k"] for r in res.values())
    ml = st.median(r["ecart_rel_lambda2"] for r in res.values())
    print(f"\nÉcart relatif médian entre passes : k {mk:.1%}, λ2 {ml:.1%}  (rapport {ml / mk:.1f})")
    S = sorted(TOURS)
    rk = spearman([res[s]["k"] for s in S], [TOURS[s] for s in S])
    rl = spearman([res[s]["lambda2"] for s in S], [TOURS[s] for s in S])
    print(f"Tours (7 sondes) : ρ(k) = {rk:+.2f}   ρ(λ2) = {rl:+.2f}   |ρ(λ2)| − |ρ(k)| = {abs(rl) - abs(rk):+.2f}")
    sortie = {"passes": passes, "sondes": res, "ecart_rel_median": {"k": mk, "lambda2": ml},
              "tours": {"sondes": S, "rho_k": round(rk, 3), "rho_lambda2": round(rl, 3)}}
    (RACINE / "data" / "fiedler.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
