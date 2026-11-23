"""Lecture mathématique de la boucle P11, sans aucun appel de modèle : traces et verdicts existants seulement.

Usage : python outils/maths.py     → texte sur la sortie, et runs-boucle/P11/maths.json

1. Divergence par action : taux ≈ e^(−λp). λ = longueur moyenne d'une situation (actions), p = probabilité
   qu'une action fasse diverger deux codes jusque-là d'accord. p estimé = −ln(taux)/λ, comparé à p mesuré
   (hasard direct : premières divergences ÷ actions jouées jusqu'à la première divergence incluse).
2. Relaxation : −ln(taux brut) = a·e^(−b·i) + c, ajusté sur les itérations ; demi-vie ln2/b, plancher c,
   taux maximal e^(−c). Ajustement sur 0..5 puis 0..6 (les tests de bugs entrent à l'itération 6).
3. Trous non vus : nombre de greens qui comblent chaque trou autrement que la majorité ; loi bêta-binomiale
   tronquée en zéro, ajustée par vraisemblance ; E[non vus après n] = N·B(α, β+n)/B(α, β) ; Chao1 ;
   capture-recapture de l'itération 0.
4. Corrélation des greens : pour une paire (a, b), la référence est l'accord des deux AUTRES greens ;
   φ entre « a s'écarte de la référence » et « b s'en écarte dans le même sens », par type de paire ; n_eff = n/(1+(n−1)ρ).
Seule la bibliothèque standard est utilisée (pas de numpy ni de scipy dans le banc).
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
from boucle import BASE, GREENS  # noqa: E402

NOMS = list(GREENS)


def lots():
    """(itération, lot, dossier) pour chaque lot jugé, dans l'ordre."""
    out = []
    for d in sorted(BASE.glob("it*"), key=lambda p: int(p.name[2:])):
        for l in sorted((d / "lots").glob("*")) if (d / "lots").exists() else []:
            if (l / "groupes.json").exists() and (l / "traces").exists():
                out.append((int(d.name[2:]), l.name, l))
    return out


def traces(l):
    return {n: {int(k): v for k, v in json.loads((l / "traces" / f"{n}.json").read_text(encoding="utf-8")).items()} for n in NOMS}


def lbeta(a, b):
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


# ── 1. λ et p ─────────────────────────────────────────────────────────────

def divergence(taux):
    res = []
    for i, l, d in lots():
        tr = traces(d)
        graines = sorted(set.intersection(*(set(t) for t in tr.values())))
        lam = sum(len(tr[n][g]) for n in NOMS for g in graines) / (len(NOMS) * len(graines))
        premieres = jouees = 0
        for x in range(4):
            for y in range(x + 1, 4):
                a, b = NOMS[x], NOMS[y]
                for g in graines:
                    sa, sb = tr[a][g], tr[b][g]
                    k = next((k for k, (p, q) in enumerate(zip(sa, sb)) if p != q), None)
                    if k is None and len(sa) != len(sb):
                        k = min(len(sa), len(sb))
                    if k is None:
                        jouees += len(sa)
                    else:
                        premieres += 1
                        jouees += k + 1
        t = taux[f"it{i}-{l}"]
        p_mesure = premieres / jouees
        lp_b, lp_s = -math.log(t["brut"]), -math.log(t["spec"])
        res.append({"it": i, "lot": l, "lambda": round(lam, 2), "lambda_p_brut": round(lp_b, 3), "lambda_p_spec": round(lp_s, 3),
                    "p_estime_brut": round(lp_b / lam, 4), "p_estime_spec": round(lp_s / lam, 4), "p_mesure": round(p_mesure, 4),
                    "taux_predit_par_p_mesure": round(math.exp(-lam * p_mesure), 3), "taux_brut": t["brut"],
                    "part_actions_divergentes": round(1 - t["par_action"], 3)})
    return res


# ── 2. relaxation ─────────────────────────────────────────────────────────

def ajuster(points):
    """Moindres carrés de y = a·e^(−b·i) + c : b par balayage fin, a et c par régression linéaire à b fixé."""
    meilleur = None
    for k in range(1, 4001):
        b = k / 1000
        xs = [math.exp(-b * i) for i, _ in points]
        ys = [y for _, y in points]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx == 0:
            continue
        a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        c = my - a * mx
        r = sum((a * x + c - y) ** 2 for x, y in zip(xs, ys))
        if meilleur is None or r < meilleur[3]:
            meilleur = (a, b, c, r)
    a, b, c, r = meilleur
    return {"a": round(a, 3), "b": round(b, 3), "c": round(c, 3), "demi_vie": round(math.log(2) / b, 2),
            "taux_max": round(math.exp(-c), 3) if c > -50 else None, "residu": round(r, 4), "points": len(points)}


def relaxation(taux):
    pts = {}
    for k, t in taux.items():
        i = int(k.split("-")[0][2:])
        pts.setdefault(i, []).append(-math.log(t["brut"]))
    points = sorted((i, sum(v) / len(v)) for i, v in pts.items())  # itération 0 : moyenne des lots A et B
    out = {"points": [(i, round(y, 3)) for i, y in points]}
    out["sans_it6"] = ajuster([p for p in points if p[0] <= 5])
    if any(i == 6 for i, _ in points):
        out["avec_it6"] = ajuster(points)
    pts_s = {}
    for k, t in taux.items():
        i = int(k.split("-")[0][2:])
        pts_s.setdefault(i, []).append(-math.log(t["spec"]))
    out["spec"] = ajuster(sorted((i, sum(v) / len(v)) for i, v in pts_s.items()))
    return out


# ── 3. trous non vus ──────────────────────────────────────────────────────

def comptes_trous():
    """Pour chaque trou distinct : nombre de greens qui le comblent autrement que la majorité (cumulé sur les lots où il est vu)."""
    h = json.loads((BASE / "it0" / "h20b.json").read_text(encoding="utf-8"))
    vus = {}
    for i, l, d in lots():
        trous = [g for g in json.loads((d / "groupes.json").read_text(encoding="utf-8")) if g["final"] == "trou"]
        for n, g in enumerate(trous, 1):
            tailles = sorted((len(v["greens"]) for v in g["variantes"]), reverse=True)
            k = 4 - tailles[0]
            cle = f"it{i}{l}{n}"
            vus[cle] = vus.get(cle, 0) + k
    # itération 0 : un trou vu par A et par B est un seul trou, vu par les greens des deux lots
    fusion = 0
    for x, y in h["appariement"]:
        a, b = f"it0A{x}", f"it0B{y}"
        if a in vus and b in vus:
            vus[a] += vus.pop(b)
            fusion += 1
    return list(vus.values()), fusion


def betabinomiale(xs, n=4):
    """Bêta-binomiale tronquée en zéro sur n essais, ajustée par vraisemblance (balayage log-grille)."""
    def logp(k, a, b):
        return math.log(math.comb(n, k)) + lbeta(k + a, n - k + b) - lbeta(a, b)
    meilleur = None
    for la in [x / 20 for x in range(-60, 61)]:
        for lb in [x / 20 for x in range(-60, 61)]:
            a, b = math.exp(la), math.exp(lb)
            p0 = math.exp(lbeta(a, b + n) - lbeta(a, b))
            if p0 >= 1:
                continue
            ll = sum(logp(min(k, n), a, b) - math.log(1 - p0) for k in xs)
            if meilleur is None or ll > meilleur[2]:
                meilleur = (a, b, ll, p0)
    return meilleur


def non_vus():
    xs, fusion = comptes_trous()
    s_obs = len(xs)
    a, b, ll, p0 = betabinomiale([min(x, 4) for x in xs])
    n_tot = s_obs / (1 - p0)
    freq = Counter(xs)
    f1, f2 = freq.get(1, 0), freq.get(2, 0)
    chao1 = s_obs + (f1 * f1 / (2 * f2) if f2 else f1 * (f1 - 1) / 2)
    h = json.loads((BASE / "it0" / "h20b.json").read_text(encoding="utf-8"))
    na, nb, m = h["trous_A"], h["trous_B"], h["communs"]
    return {"S_obs": s_obs, "fusions_it0": fusion, "distribution": dict(sorted(freq.items())), "alpha": round(a, 3), "beta": round(b, 3),
            "theta_moyen": round(a / (a + b), 3), "P0_4_greens": round(p0, 3), "N_beta": round(n_tot, 1),
            "non_vus": {n: round(n_tot * math.exp(lbeta(a, b + n) - lbeta(a, b)), 1) for n in (4, 8, 16)},
            "f1": f1, "f2": f2, "chao1": round(chao1, 1),
            "capture_recapture_it0": {"nA": na, "nB": nb, "m": m, "N": round((na + 1) * (nb + 1) / (m + 1) - 1, 1)}}


def good_turing():
    """P(la prochaine situation tombe sur un trou jamais vu) ≈ f1 / n, par lot.
    Une « observation » = une situation dont la première divergence à 4 tombe dans un groupe ; un groupe = un trou
    candidat, sauf s'il a été jugé bug ou invalide. Les groupes non jugés (les plus petits) restent des trous candidats :
    c'est là que sont presque tous les singletons."""
    from boucle import accord
    out = []
    for i, l, d in lots():
        _, divs = accord(i, l, traces(d))
        exclus = {g["groupe"] for g in json.loads((d / "groupes.json").read_text(encoding="utf-8"))
                  if g["final"].startswith("bug") or g["final"] == "invalide"}
        taille = Counter(dv["groupe"] for dv in divs if dv["groupe"] not in exclus)
        n = sum(taille.values())
        f1 = sum(1 for v in taille.values() if v == 1)
        out.append({"it": i, "lot": l, "n": n, "f1": f1, "groupes": len(taille), "p_nouveau": round(f1 / n, 3) if n else None})
    return out


# ── 4. corrélation des greens ─────────────────────────────────────────────

def correlation():
    paires = [(NOMS[x], NOMS[y]) for x in range(4) for y in range(x + 1, 4)]
    cpt = {p: Counter() for p in paires}
    for i, l, d in lots():
        tr = traces(d)
        for g in sorted(set.intersection(*(set(t) for t in tr.values()))):
            seqs = [tr[n][g] for n in NOMS]
            if all(s == seqs[0] for s in seqs):
                continue
            k = 0
            while all(k < len(s) for s in seqs) and all(s[k] == seqs[0][k] for s in seqs):
                k += 1
            obs = [json.dumps(s[k][1] if k < len(s) else "(fin)", sort_keys=True, ensure_ascii=False) for s in seqs]
            for a, b in paires:
                # les k actions d'avant, jouées à l'identique par les 4, comptent comme « personne ne s'écarte »
                # (sans elles, on ne garderait que les actions où quelqu'un s'écarte : corrélation négative forcée)
                cpt[(a, b)][(False, False, False)] += k
                # référence : les deux AUTRES greens, quand ils sont d'accord entre eux (sinon le sens est indéfini)
                c, d2 = [n for n in NOMS if n not in (a, b)]
                ref = obs[NOMS.index(c)]
                if obs[NOMS.index(d2)] != ref:
                    continue
                oa, ob = obs[NOMS.index(a)], obs[NOMS.index(b)]
                da, db = oa != ref, ob != ref
                cpt[(a, b)][(da, db, da and db and oa == ob)] += 1
    out = {}
    for (a, b), c in cpt.items():
        n = sum(c.values())
        pa = sum(v for (da, _, _), v in c.items() if da) / n
        pb = sum(v for (_, db, _), v in c.items() if db) / n
        pab = sum(v for (_, _, e), v in c.items() if e) / n
        phi = (pab - pa * pb) / math.sqrt(pa * (1 - pa) * pb * (1 - pb)) if 0 < pa < 1 and 0 < pb < 1 else None
        out[f"{a}-{b}"] = {"n": n, "p_ecart_a": round(pa, 3), "p_ecart_b": round(pb, 3), "p_ensemble": round(pab, 3),
                           "rho": round(phi, 3) if phi is not None else None}

    def moyenne(cles):
        v = [out[k]["rho"] for k in cles if out[k]["rho"] is not None]
        return round(sum(v) / len(v), 3) if v else None
    hh, ss = moyenne(["H1-H2"]), moyenne(["S1-S2"])
    hs = moyenne(["H1-S1", "H1-S2", "H2-S1", "H2-S2"])
    mix = moyenne(list(out))

    def neff(r, n=4):
        return round(n / (1 + (n - 1) * r), 2) if r is not None else None
    return {"paires": out, "rho_haiku_haiku": hh, "rho_sonnet_sonnet": ss, "rho_haiku_sonnet": hs, "rho_lot_mixte": mix,
            "n_eff_4_haiku": neff(hh), "n_eff_4_sonnet": neff(ss), "n_eff_lot_mixte": neff(mix)}


def main():
    taux = json.loads((BASE / "taux.json").read_text(encoding="utf-8"))
    res = {"divergence": divergence(taux), "relaxation": relaxation(taux), "non_vus": non_vus(), "good_turing": good_turing(), "correlation": correlation()}
    (BASE / "maths.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("1. λ, p")
    for r in res["divergence"]:
        print(f"  it{r['it']}{r['lot']} λ={r['lambda']} −ln(brut)={r['lambda_p_brut']} p_est={r['p_estime_brut']} "
              f"p_mesuré={r['p_mesure']} taux prédit {r['taux_predit_par_p_mesure']} / observé {r['taux_brut']} "
              f"| spec p_est={r['p_estime_spec']} | actions divergentes {r['part_actions_divergentes']}")
    print("2. relaxation", json.dumps(res["relaxation"], ensure_ascii=False))
    print("3. non vus", json.dumps(res["non_vus"], ensure_ascii=False))
    for r in res["good_turing"]:
        print(f"  Good-Turing it{r['it']}{r['lot']} : f1={r['f1']} n={r['n']} groupes={r['groupes']} → P(trou jamais vu) ≈ {r['p_nouveau']}")
    c = res["correlation"]
    print("4. corrélation", json.dumps({k: v for k, v in c.items() if k != "paires"}, ensure_ascii=False))
    for k, v in c["paires"].items():
        print("  ", k, v)


if __name__ == "__main__":
    main()
