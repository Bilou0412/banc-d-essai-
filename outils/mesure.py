"""Mesure statique des passes (règle stricte).

Usage :
    python outils/mesure.py data/passes/strict            # toutes les sondes d'un dossier
    python outils/mesure.py data/passes/strict/P05_A.txt  # une seule passe

Format attendu, une assertion par ligne :
    - texte | observé: etat | conditions: etat1, etat2   (ou "conditions: aucune")

Fichiers nommés <SONDE>_<PASSE>.txt (ex. P05_A.txt) pour regrouper les passes d'une même sonde.
Dépendance : networkx (pip install networkx).
"""
import glob
import itertools
import os
import statistics as st
import sys

import networkx as nx

ECART_MAX = 0.15  # 2 passes : écart max − min toléré (SPEC 6.3)
ECART_TYPE_MAX = 0.10  # 3 passes ou plus : écart-type (d'échantillon) toléré (SPEC 6.3)
PASSES_MAX = 3  # au-delà, la sonde est « floue » : on ne la mesure plus, on creuse sa spec


def concordance(ks):
    """SPEC 6.3. Rend (k retenu = médiane, statut). Statuts : une seule passe,
    concordante, non concordante (lancer une 3e passe), floue."""
    if len(ks) < 2:
        return (ks[0] if ks else None), "une seule passe"
    k = st.median(ks)
    if len(ks) == 2:
        return k, "concordante" if max(ks) - min(ks) <= ECART_MAX else "non concordante : lancer une 3e passe"
    return k, "concordante" if st.stdev(ks) <= ECART_TYPE_MAX else "floue"


def lire_passe(chemin):
    assertions = []
    for ligne in open(chemin, encoding="utf-8"):
        ligne = ligne.strip()
        if not ligne.startswith("- ") or "observé:" not in ligne:
            continue
        morceaux = [m.strip() for m in ligne[2:].split("|")]
        obs = next(m for m in morceaux if m.startswith("observé:")).split(":", 1)[1].strip().lower()
        cond_txt = next((m for m in morceaux if m.startswith("conditions:")), "conditions: aucune").split(":", 1)[1]
        cond = {c.strip().lower() for c in cond_txt.split(",") if c.strip() and c.strip().lower() != "aucune"}
        assertions.append((obs, cond - {obs}))
    return assertions


def frontieres(chemin):
    """Liste de booléens, une par assertion lue : marquée « | frontière: oui » (consigne v2)."""
    out = []
    for ligne in open(chemin, encoding="utf-8"):
        ligne = ligne.strip()
        if not ligne.startswith("- ") or "observé:" not in ligne:
            continue
        morceaux = [m.strip().lower() for m in ligne[2:].split("|")]
        out.append(any(m.startswith("frontière:") and m.split(":", 1)[1].strip() == "oui" for m in morceaux))
    return out


def mesurer(assertions):
    n = len(assertions)
    ensembles = [{o} | c for o, c in assertions]
    etats = set().union(*ensembles)
    compte = {e: sum(e in a for a in ensembles) for e in etats}
    champ = max(sorted(compte), key=compte.get)  # ordre fixe : à égalité, le choix ne dépend plus du hasard du hachage
    G = nx.Graph()
    G.add_nodes_from(range(n))
    for i, j in itertools.combinations(range(n), 2):
        poids = len((ensembles[i] & ensembles[j]) - {champ})
        if poids:
            G.add_edge(i, j, weight=poids)
    coeur = G.subgraph([v for v in G if G.degree(v) > 0])
    blocs = nx.community.greedy_modularity_communities(coeur, weight="weight") if coeur.number_of_edges() else []
    Q = nx.community.modularity(coeur, blocs, weight="weight") if blocs else 0.0
    return {
        "assertions": n,
        "etats": len(etats),
        "k": st.mean(len(a) for a in ensembles),
        "champ": champ,
        "part_champ": compte[champ] / n,
        "densite": nx.density(G),
        "modularite": Q,
        "isolees": n - coeur.number_of_nodes(),
    }


def main(cible):
    fichiers = sorted(glob.glob(os.path.join(cible, "*.txt"))) if os.path.isdir(cible) else [cible]
    par_sonde = {}
    for f in fichiers:
        nom = os.path.basename(f)[:-4]
        sonde = nom.split("_")[0]
        A = lire_passe(f)
        if len(A) < 5:
            print(f"! {nom} : illisible ou presque vide ({len(A)} assertions)")
            continue
        m = mesurer(A)
        fr = frontieres(f)
        m["frontieres"] = sum(fr)
        par_sonde.setdefault(sonde, []).append(m)
        print(f"{nom:10s} k={m['k']:.2f}  densité={m['densite']:.2f}  modularité={m['modularite']:.2f}  "
              f"assertions={m['assertions']}  états={m['etats']}  champ={m['champ']} ({m['part_champ']:.0%})"
              + (f"  frontières={m['frontieres']} ({m['frontieres'] / m['assertions']:.0%})" if m["frontieres"] else ""))
    print()
    for sonde, ms in sorted(par_sonde.items()):
        ks = [m["k"] for m in ms]
        k, etat = concordance(ks)
        dispersion = f"écart-type {st.stdev(ks):.2f}" if len(ks) > 2 else f"écart {max(ks) - min(ks):.2f}"
        fr = sum(m["frontieres"] for m in ms) / len(ms)
        print(f"{sonde}: k retenu (médiane) = {k:.2f}, {len(ks)} passes, {dispersion}  ({etat})"
              + (f"  frontières moy. = {fr:.1f}" if fr else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/passes/strict")
