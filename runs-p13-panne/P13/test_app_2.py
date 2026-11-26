"""Red tests — code layer, second attack.

Same public interface as tests/test_app.py (first attack). New names only.
Focus: invariants under repetition, unsaid edge cases (zero, duplicates,
float boundaries, malformed input), rule interactions, isolation between
two games, and anything a shortcut simulation would get wrong.
"""

import math
import re
import statistics

import pytest

import app


# ----------------------------------------------------------------- helpers

def ma3(history):
    return sum(history[-3:]) / 3


def ready(game):
    game.open_order_screen()
    if game.mentor_explanation is not None:
        game.dismiss_mentor_explanation()


def play(game, forecast_text, order=100):
    ready(game)
    r = game.submit_forecast(forecast_text)
    w = game.submit_order(order)
    return r, w


BASE = [100] * 8
FAR = "100000.0"   # always a failure: every moving average here is far below


def _seed_with_smallest_std(n=300):
    best = min(range(n), key=lambda s: app.Game(seed=s).std_dev)
    return best


def _seed_with_largest_ratio(n=300):
    def ratio(s):
        g = app.Game(seed=s)
        return g.std_dev / g.mean_demand
    return max(range(n), key=ratio), min(range(n), key=ratio)


# ----------------------------------------------------------------- A02 / A04 / N01 / A25 : real draws

def test_A02_sans_graine_deux_parties_different():
    means = {app.Game().mean_demand for _ in range(30)}
    assert len(means) > 15, (
        f"without a seed every new game must draw its own mean; got {len(means)} distinct over 30")


def test_A05_historique_initial_non_biaise_par_l_arrondi():
    # floor/int() truncation biases every unit by -0.5; the law of the game has mean mean_demand
    diffs = []
    for s in range(5000):
        g = app.Game(seed=s)
        diffs.extend(u - g.mean_demand for u in g.history)
    m = statistics.fmean(diffs)
    se = statistics.pstdev(diffs) / math.sqrt(len(diffs))
    assert abs(m) < 4 * se, (
        f"initial history units deviate from the game mean by {m:.3f} on average "
        f"(tolerance {4 * se:.3f}): rounding is biased")


def test_A05_historique_initial_semaines_independantes():
    xs, ys = [], []
    for s in range(2000):
        g = app.Game(seed=s)
        z = [(u - g.mean_demand) / g.std_dev for u in g.history]
        xs.extend(z[:-1])
        ys.extend(z[1:])
    r = statistics.correlation(xs, ys)
    assert abs(r) < 0.05, f"consecutive initial weeks must be independent draws, lag-1 corr {r:.3f}"


def test_A25_demande_non_biaisee_par_l_arrondi():
    seed = _seed_with_smallest_std()
    g = app.Game(seed=seed)
    d = []
    for _ in range(20000):
        ready(g)
        g.submit_forecast(FAR)
        d.append(g.submit_order(0).demand)
    m = statistics.fmean(d)
    se = g.std_dev / math.sqrt(len(d))
    assert abs(m - g.mean_demand) < 4 * se + 0.05, (
        f"sample mean {m:.3f} vs game mean {g.mean_demand:.3f} (tolerance {4 * se + 0.05:.3f}): "
        f"demand rounding is biased")
    xs, ys = d[:-1], d[1:]
    r = statistics.correlation(xs, ys)
    assert abs(r) < 0.05, f"weekly demands must be independent, lag-1 corr {r:.3f}"


def test_A25_ecart_type_propre_a_chaque_partie():
    hi, lo = _seed_with_largest_ratio()
    for seed in (hi, lo):
        g = app.Game(seed=seed)
        d = []
        for _ in range(1500):
            ready(g)
            g.submit_forecast(FAR)
            d.append(g.submit_order(0).demand)
        sd = statistics.pstdev(d)
        assert 0.9 * g.std_dev < sd < 1.1 * g.std_dev, (
            f"seed {seed}: sample std {sd:.2f} must match this game's std {g.std_dev:.2f}")


# ----------------------------------------------------------------- A03 : repetition

def test_A03_moyenne_constante_sur_1000_semaines():
    g = app.Game(seed=21)
    m0, s0 = g.mean_demand, g.std_dev
    for _ in range(1000):
        play(g, FAR, order=0)
    assert g.mean_demand == m0, f"mean changed from {m0} to {g.mean_demand}"
    assert g.std_dev == s0, f"std changed from {s0} to {g.std_dev}"
    assert len(g.history) == 1008, f"expected 1008 weeks, got {len(g.history)}"
    weeks = [w for w, _ in g.table()]
    assert weeks == list(range(1, 1009)), "week numbers must stay 1..n after many weeks"


# ----------------------------------------------------------------- A06 / A07 : two games

def test_A06_deux_parties_independantes_pour_l_explication():
    a = app.Game(seed=1)
    a.open_order_screen()
    a.dismiss_mentor_explanation()
    b = app.Game(seed=2)
    b.open_order_screen()
    assert b.mentor_explanation, "a second game must show its own first explanation"
    assert b.forecast_field_enabled is False


def test_A34_deux_parties_ne_partagent_pas_la_serie():
    a = app.Game(seed=1, history=list(BASE))
    play(a, "100.0")
    assert a.streak == 1
    b = app.Game(seed=1, history=list(BASE))
    assert b.streak == 0, f"new game starts with streak {b.streak}"
    assert not b.criteria.get("SC0x-01", False)
    assert len(b.history) == 8


# ----------------------------------------------------------------- A11 : zero

def test_A11_historique_tout_a_zero():
    g = app.Game(seed=1, history=[0] * 8)
    h = g.chart()
    assert len(h) == 8
    assert all(b == 0 for b in h), f"bars of 0 units must have height 0, got {h}"


def test_A11_barre_nulle_pour_semaine_nulle():
    hist = [0, 50, 100, 0, 25, 75, 100, 0]
    g = app.Game(seed=1, history=list(hist))
    h = g.chart()
    k = h[2] / 100
    assert k > 0
    for u, b in zip(hist, h):
        assert b == pytest.approx(k * u, abs=1e-9), f"bar {b} not proportional to {u}"


# ----------------------------------------------------------------- A12 / A13 : one order per forecast

def test_A12_commande_desactivee_juste_apres_la_commande():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    g.submit_forecast("150.0")
    g.submit_order(100)
    assert g.order_field_enabled is False, "order field must be disabled once the week is resolved"


def test_A12_deuxieme_commande_meme_semaine_refusee():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    g.submit_forecast("150.0")
    g.submit_order(100)
    with pytest.raises(app.Refused):
        g.submit_order(100)
    assert len(g.history) == 9, f"a single forecast resolved {len(g.history) - 8} weeks"


def test_A13_trou_deuxieme_prevision_meme_semaine_refusee():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    g.submit_forecast("150.0")
    with pytest.raises(app.Refused):
        g.submit_forecast("100.0")
    assert g.streak == 0, "a failed week must not be rescued by a second forecast"


def test_A34_trou_deux_succes_sans_commande_ne_terminent_pas():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    g.submit_forecast("100.0")
    try:
        g.submit_forecast("100.0")
    except app.Refused:
        pass
    assert g.streak <= 1, f"streak {g.streak} reached within a single week"
    assert g.level_finished is False
    assert not g.criteria.get("SC0x-01", False)


# ----------------------------------------------------------------- A14 / A15 : input forms

@pytest.mark.parametrize("text", ["100.50", "100,55", "100,50", "100.00"])
def test_A15_deux_decimales_meme_zero_final_refusees(text):
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    with pytest.raises(app.Refused):
        g.submit_forecast(text)
    assert g.order_field_enabled is False


@pytest.mark.parametrize("text", ["", "abc", "nan", "inf", "1e2", "100.5.5"])
def test_A14_trou_saisie_non_numerique_refusee(text):
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    with pytest.raises(app.Refused):
        g.submit_forecast(text)
    assert g.order_field_enabled is False
    assert g.streak == 0


def test_A35_prevision_refusee_ne_remet_pas_la_serie_a_zero():
    g = app.Game(seed=1, history=list(BASE))
    play(g, "100.0")
    assert g.streak == 1
    ready(g)
    with pytest.raises(app.Refused):
        g.submit_forecast("100.55")
    assert g.streak == 1, f"refused forecast changed streak to {g.streak}"
    assert g.level_finished is False


# ----------------------------------------------------------------- A16 – A20 : boundaries

def test_A18_moyenne_nulle_prevision_nulle_succes():
    g = app.Game(seed=1, history=[0] * 8)
    ready(g)
    r = g.submit_forecast("0")
    assert r.success is True, "deviation 0 is exactly 1 % of 0 -> success"
    assert r.moving_average == 0


def test_A19_moyenne_nulle_prevision_non_nulle_echec():
    g = app.Game(seed=1, history=[0] * 8)
    ready(g)
    r = g.submit_forecast("0.1")
    assert r.success is False, "deviation 0.1 > 1 % of 0 -> failure"
    assert re.search(r"0\s*\+\s*0\s*\+\s*0", r.comment), f"calculation not shown: {r.comment!r}"


def test_A18_frontiere_exacte_avec_semaines_differentes():
    # 129, 130, 131 -> 130 ; 1 % = 1.3 ; 131.3 - 130 is 1.3000000000000114 in floats
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 129, 130, 131])
    ready(g)
    assert g.submit_forecast("131.3").success is True, "deviation is exactly 1 % of 130"


def test_A18_frontiere_exacte_par_dessous_semaines_differentes():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 131, 130, 129])
    ready(g)
    assert g.submit_forecast("128.7").success is True, "deviation is exactly 1 % of 130"


def test_A19_juste_au_dessus_de_la_frontiere():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 129, 130, 131])
    ready(g)
    assert g.submit_forecast("131.4").success is False


def test_A20_arrondi_vers_le_bas_ne_sauve_pas():
    # 100, 100, 101 -> 100.333 ; 99.3 deviates by 1.0333 > 1.00333 -> failure
    # (against a rounded 100 or 100.3 it would wrongly be a success)
    g = app.Game(seed=1, history=[100, 100, 100, 100, 100, 100, 100, 101])
    ready(g)
    r = g.submit_forecast("99.3")
    assert r.success is False, "99.3 vs 100.333: deviation 1.033 > 1.00333 -> failure"


def test_A17_frontiere_moyenne_non_entiere_succes():
    # 100.333 ; 101.3 deviates by 0.9667 < 1.00333 -> success
    g = app.Game(seed=1, history=[100, 100, 100, 100, 100, 100, 100, 101])
    ready(g)
    assert g.submit_forecast("101.3").success is True


# ----------------------------------------------------------------- A21 – A24 : comment content

def test_A21_commentaire_varie_avec_l_ecart():
    comments = []
    for f in ("130.0", "170.0"):
        g = app.Game(seed=1, history=list(BASE))
        ready(g)
        comments.append(g.submit_forecast(f).comment)
    assert comments[0] != comments[1], "two different deviations got the same comment"
    assert re.search(r"(?<![\d.,])30(?:[.,]0+)?(?!\d)", comments[0]), comments[0]
    assert re.search(r"(?<![\d.,])70(?:[.,]0+)?(?!\d)", comments[1]), comments[1]


def test_A21_commentaire_ecart_sur_un_succes():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    r = g.submit_forecast("100.7")
    assert r.success is True
    assert re.search(r"(?<![\d.,])0[.,]7(?!\d)", r.comment), (
        f"success comment must state the deviation 0.7: {r.comment!r}")


def test_A22_moyenne_non_entiere_affichee_dans_l_echec():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 100, 101, 101])
    ready(g)
    r = g.submit_forecast("150.0")
    assert re.search(r"100[.,]6[67]", r.comment), (
        f"comment must show 100.67/100.7 (not 101): {r.comment!r}")


def test_A23_doublons_affiches_trois_fois():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 57, 57, 57])
    ready(g)
    r = g.submit_forecast("150.0")
    assert re.search(r"57\s*\+\s*57\s*\+\s*57", r.comment), (
        f"all three numbers must be shown even when equal: {r.comment!r}")


def test_A24_calcul_de_la_semaine_suivante_inclut_la_semaine_jouee():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 87, 93, 106])
    _, w = play(g, FAR, order=50)
    ready(g)
    r = g.submit_forecast(FAR)
    assert r.success is False
    assert re.search(rf"93\s*\+\s*106\s*\+\s*{w.demand}(?!\d)", r.comment), (
        f"expected calculation 93 + 106 + {w.demand}: {r.comment!r}")
    assert re.search(r"(?<![\d.,])87(?!\d)", r.comment) is None, (
        f"week 6 (87) is no longer in the window: {r.comment!r}")


# ----------------------------------------------------------------- A26 – A31 / N10

def test_A26_commande_refusee_puis_commande_valide():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    g.submit_forecast("150.0")
    with pytest.raises(app.Refused):
        g.submit_order(-5)
    assert g.order_field_enabled is True, "a refused order must keep the order field enabled"
    w = g.submit_order(30)
    assert w.sales == min(w.demand, 30)
    assert len(g.history) == 9


def test_A27_commande_nulle_tout_manque():
    g = app.Game(seed=4, history=list(BASE))
    _, w = play(g, FAR, order=0)
    assert (w.sales, w.missed, w.wasted) == (0, w.demand, 0), f"{w}"
    assert float(w.revenue) == pytest.approx(0.0, abs=0.005)
    assert float(w.cost) == pytest.approx(0.0, abs=0.005)


def test_A29_montants_au_centime():
    for order in (7, 33, 77, 1001):
        g = app.Game(seed=8, history=list(BASE))
        _, w = play(g, FAR, order=order)
        assert round(float(w.revenue), 2) == round(w.sales * 120 / 100, 2), f"{w}"
        assert round(float(w.cost), 2) == round(order * 80 / 100, 2), f"{w}"
        assert round(float(w.profit), 2) == round((w.sales * 120 - order * 80) / 100, 2), f"{w}"


def test_A31_benefice_negatif_quand_on_jette():
    g = app.Game(seed=1, history=list(BASE))
    _, w = play(g, FAR, order=10000)
    expected = w.demand * 1.20 - 10000 * 0.80
    assert expected < 0
    assert float(w.profit) == pytest.approx(expected, abs=0.005), f"{w}"


# ----------------------------------------------------------------- A32 / A33

def test_A32_trou_historique_fourni_non_modifie():
    hist = [10, 20, 30, 40, 50, 60, 70, 80]
    g = app.Game(seed=1, history=hist)
    play(g, FAR, order=10)
    assert hist == [10, 20, 30, 40, 50, 60, 70, 80], f"caller's list was mutated: {hist}"
    assert len(g.history) == 9


def test_A33_moyenne_apres_deux_semaines():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 0, 0, 100])
    _, w1 = play(g, FAR, order=0)
    _, w2 = play(g, FAR, order=0)
    ready(g)
    r = g.submit_forecast(FAR)
    assert r.moving_average == pytest.approx((100 + w1.demand + w2.demand) / 3, abs=1e-9)
    assert [u for _, u in g.table()][-3:] == [100, w1.demand, w2.demand]


# ----------------------------------------------------------------- A34 – A39 / N11 / N12

def test_A34_echec_apres_echec_serie_reste_a_zero():
    g = app.Game(seed=1, history=list(BASE))
    play(g, FAR)
    play(g, FAR)
    assert g.streak == 0


def test_A37_pas_fini_avant_la_commande_de_la_semaine_finale():
    g = app.Game(seed=1, history=list(BASE))
    play(g, "100.0")
    ready(g)
    r = g.submit_forecast(f"{ma3(g.history):.1f}")
    assert r.success is True
    assert g.level_finished is False, "N12: the final week's order must still be submitted"
    assert g.order_field_enabled is True
    n = len(g.history)
    g.submit_order(100)
    assert len(g.history) == n + 1
    assert g.level_finished is True
    assert g.criteria.get("SC0x-01") is True


def _finished_game():
    g = app.Game(seed=1, history=list(BASE))
    play(g, "100.0")
    ready(g)
    g.submit_forecast(f"{ma3(g.history):.1f}")
    g.submit_order(100)
    assert g.level_finished is True
    return g


def test_A37_apres_la_fin_prevision_directe_refusee():
    g = _finished_game()
    n, s = len(g.history), g.streak
    with pytest.raises(app.Refused):
        g.submit_forecast("100.0")
    assert len(g.history) == n and g.streak == s
    assert g.criteria.get("SC0x-01") is True


def test_A37_apres_la_fin_commande_refusee():
    g = _finished_game()
    n = len(g.history)
    with pytest.raises(app.Refused):
        g.submit_order(100)
    assert len(g.history) == n


def test_A38_pas_de_message_final_a_serie_1():
    g = app.Game(seed=1, history=list(BASE))
    play(g, "100.0")
    assert g.streak == 1
    assert not g.final_message
    assert not g.criteria.get("SC0x-01", False)


def test_A36_succes_puis_echec_puis_deux_succes_valide():
    g = app.Game(seed=1, history=list(BASE))
    play(g, "100.0")
    play(g, FAR)
    assert g.streak == 0
    play(g, f"{ma3(g.history):.1f}")
    assert g.level_finished is False
    play(g, f"{ma3(g.history):.1f}")
    assert g.criteria.get("SC0x-01") is True
    assert g.level_finished is True
    assert g.final_message


# ----------------------------------------------------------------- A40

MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")


def test_A40_trou_page_declare_utf8():
    resp = app.WebServer().get("/", headers={"User-Agent": MOBILE_UA})
    assert resp.status == 200
    ctype = {k.lower(): v for k, v in resp.headers.items()}.get("content-type", "").lower()
    body = resp.body.lower()
    assert "utf-8" in ctype or re.search(r'<meta[^>]+charset=["\']?utf-8', body), (
        f"French text needs a declared UTF-8 charset; content-type {ctype!r}")


def test_A40_android_sans_redirection_vers_un_store():
    resp = app.WebServer().get("/", headers={"User-Agent": MOBILE_UA})
    assert resp.status == 200, f"Android browser must get the game directly, got {resp.status}"
    low = resp.body.lower()
    assert "play.google.com" not in low and "apps.apple.com" not in low
    assert "<input" in low
