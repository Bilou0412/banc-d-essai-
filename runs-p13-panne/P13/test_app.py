"""Red tests — code layer, first attack.

Public interface fixed by these tests (to be implemented as-is in app.py):

    app.Refused                      exception raised for every refused player action
    app.Game(seed=None, history=None)
        history: optional list of 8 non-negative ints replacing the drawn initial history
        .history                -> list[int]   units per week, oldest first
        .mean_demand            -> float
        .std_dev                -> float
        .open_order_screen()
        .mentor_explanation     -> str | None  (None when not displayed)
        .dismiss_mentor_explanation()
        .forecast_field_enabled -> bool
        .order_field_enabled    -> bool
        .table()                -> list[tuple[int, int]]  (week number, units)
        .chart()                -> list[float]            bar heights, same order as history
        .submit_forecast(text: str) -> ForecastResult(.success: bool,
                                                      .moving_average: float,
                                                      .comment: str)
        .submit_order(quantity: int) -> WeekResult(.week, .demand, .sales, .missed,
                                                   .wasted, .revenue, .cost, .profit)
        .streak                 -> int
        .criteria               -> dict[str, bool]   e.g. {"SC0x-01": False}
        .level_finished         -> bool
        .final_message          -> str | None
    app.WebServer().get(path: str, headers: dict) -> Response(.status, .headers, .body)
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
    """Open the order screen and dismiss the mentor explanation if shown."""
    game.open_order_screen()
    if game.mentor_explanation is not None:
        game.dismiss_mentor_explanation()


def good_forecast(game):
    # deviation <= 0.05, far below 1 % of any average >= 60
    return f"{ma3(game.history):.1f}"


def bad_forecast(game):
    return f"{ma3(game.history) * 2 + 10:.1f}"


def play_week(game, forecast_text, order=100):
    ready(game)
    result = game.submit_forecast(forecast_text)
    week = game.submit_order(order)
    return result, week


def finish_week_if_possible(game, order=100):
    if not game.level_finished and game.order_field_enabled:
        game.submit_order(order)


def contains_number(text, pattern):
    return re.search(pattern, text) is not None


BASE = [100, 100, 100, 100, 100, 100, 100, 100]


# ----------------------------------------------------------------- A01

def test_A01_historique_initial_8_semaines():
    for seed in range(20):
        g = app.Game(seed=seed)
        assert len(g.history) == 8, f"seed {seed}: expected 8 weeks, got {len(g.history)}"


# ----------------------------------------------------------------- A02

def test_A02_demande_moyenne_entre_60_et_140():
    means = [app.Game(seed=s).mean_demand for s in range(300)]
    bad = [m for m in means if not (60 <= m <= 140)]
    assert not bad, f"mean demand outside [60, 140]: {bad[:5]}"


def test_A02_demande_moyenne_reellement_tiree():
    means = [app.Game(seed=s).mean_demand for s in range(300)]
    assert min(means) < 80 and max(means) > 120, (
        f"mean demand must be drawn over [60,140]; observed range "
        f"[{min(means)}, {max(means)}] over 300 games")
    assert len(set(means)) > 100, f"only {len(set(means))} distinct means over 300 games"


# ----------------------------------------------------------------- A03

def test_A03_demande_moyenne_constante_pendant_la_partie():
    g = app.Game(seed=7)
    m0 = g.mean_demand
    for i in range(6):
        play_week(g, bad_forecast(g), order=90)
        assert g.mean_demand == m0, f"week {i + 1}: mean changed from {m0} to {g.mean_demand}"


# ----------------------------------------------------------------- A04

def test_A04_ecart_type_entre_10_et_20_pourcent():
    for s in range(300):
        g = app.Game(seed=s)
        ratio = g.std_dev / g.mean_demand
        assert 0.10 - 1e-12 <= ratio <= 0.20 + 1e-12, (
            f"seed {s}: std/mean expected in [0.10, 0.20], got {ratio}")


def test_A04_ecart_type_reellement_tire():
    ratios = [app.Game(seed=s).std_dev / app.Game(seed=s).mean_demand for s in range(300)]
    assert min(ratios) < 0.12 and max(ratios) > 0.18, (
        f"std ratio must be drawn over [0.10, 0.20]; observed [{min(ratios)}, {max(ratios)}]")


# ----------------------------------------------------------------- A05

def test_A05_historique_entiers_non_negatifs():
    for s in range(200):
        g = app.Game(seed=s)
        for u in g.history:
            assert isinstance(u, int) and not isinstance(u, bool), (
                f"seed {s}: expected int units, got {u!r}")
            assert u >= 0, f"seed {s}: negative units {u}"


def test_A05_trou_historique_tire_selon_la_loi():
    zs = []
    for s in range(300):
        g = app.Game(seed=s)
        zs.extend((u - g.mean_demand) / g.std_dev for u in g.history)
    m = statistics.fmean(zs)
    sd = statistics.pstdev(zs)
    assert abs(m) < 0.15, f"standardized initial history mean expected ~0, got {m}"
    assert 0.85 < sd < 1.15, f"standardized initial history std expected ~1, got {sd}"


# ----------------------------------------------------------------- A06 / A07 / A08

def test_A06_explication_mentor_a_la_premiere_ouverture():
    g = app.Game(seed=1)
    g.open_order_screen()
    text = g.mentor_explanation
    assert text, f"expected mentor explanation at first opening, got {text!r}"
    assert "moyenne mobile" in text.lower(), f"explanation must speak of the moving average: {text!r}"
    assert "3" in text, f"explanation must mention 3 weeks: {text!r}"


def test_A07_pas_d_explication_a_la_reouverture_meme_semaine():
    g = app.Game(seed=1)
    g.open_order_screen()
    g.dismiss_mentor_explanation()
    g.open_order_screen()
    assert g.mentor_explanation is None, f"explanation shown again: {g.mentor_explanation!r}"


def test_A07_pas_d_explication_a_la_semaine_suivante():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "150.0", order=100)
    g.open_order_screen()
    assert g.mentor_explanation is None, f"explanation shown at week 2: {g.mentor_explanation!r}"
    assert g.forecast_field_enabled is True


def test_A08_champ_prevision_desactive_pendant_explication():
    g = app.Game(seed=1)
    g.open_order_screen()
    assert g.mentor_explanation
    assert g.forecast_field_enabled is False, "forecast field must be disabled during explanation"
    g.dismiss_mentor_explanation()
    assert g.forecast_field_enabled is True, "forecast field must be enabled once explanation closed"


def test_A08_trou_soumission_refusee_si_desactive():
    g = app.Game(seed=1, history=list(BASE))
    g.open_order_screen()
    with pytest.raises(app.Refused):
        g.submit_forecast("100.0")
    assert g.order_field_enabled is False


# ----------------------------------------------------------------- A09 / A10 / A11

def test_A09_une_ligne_par_semaine_avec_numero():
    g = app.Game(seed=3)
    rows = g.table()
    assert len(rows) == len(g.history) == 8
    weeks = [w for w, _ in rows]
    assert all(isinstance(w, int) for w in weeks)
    assert weeks == list(range(weeks[0], weeks[0] + 8)), f"week numbers not consecutive: {weeks}"


def test_A09_trou_numerotation_commence_a_1():
    g = app.Game(seed=3)
    assert [w for w, _ in g.table()] == list(range(1, 9))


def test_A10_ligne_affiche_unites_vendues():
    hist = [10, 20, 30, 40, 50, 60, 70, 80]
    g = app.Game(seed=3, history=hist)
    assert [u for _, u in g.table()] == hist


def test_A10_tableau_suit_l_historique_apres_une_semaine():
    g = app.Game(seed=3, history=list(BASE))
    _, week = play_week(g, "150.0", order=100)
    rows = g.table()
    assert len(rows) == 9
    assert rows[-1][1] == week.demand
    assert rows[-1][0] == rows[-2][0] + 1


def test_A11_barres_proportionnelles():
    hist = [10, 20, 30, 40, 55, 60, 75, 80]
    g = app.Game(seed=3, history=hist)
    h = g.chart()
    assert len(h) == 8, f"expected 8 bars, got {len(h)}"
    assert max(h) > 0
    k = h[-1] / hist[-1]
    for u, b in zip(hist, h):
        assert b == pytest.approx(k * u, rel=1e-6), f"bar {b} not proportional to {u} (k={k})"


def test_A11_graphique_suit_l_historique():
    g = app.Game(seed=11)
    play_week(g, bad_forecast(g), order=50)
    h = g.chart()
    assert len(h) == len(g.history) == 9
    nz = [(u, b) for u, b in zip(g.history, h) if u > 0]
    k = nz[0][1] / nz[0][0]
    for u, b in zip(g.history, h):
        assert b == pytest.approx(k * u, rel=1e-6)


# ----------------------------------------------------------------- A12 / A13

def test_A12_commande_desactivee_sans_prevision():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    assert g.order_field_enabled is False


def test_A12_commande_desactivee_a_la_semaine_suivante():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "150.0", order=100)
    ready(g)
    assert g.order_field_enabled is False, "order field must be disabled until this week's forecast"


def test_A12_trou_commande_refusee_sans_prevision():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    n = len(g.history)
    with pytest.raises(app.Refused):
        g.submit_order(100)
    assert len(g.history) == n


def test_A13_commande_activee_apres_prevision():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    g.submit_forecast("150.0")
    assert g.order_field_enabled is True


# ----------------------------------------------------------------- A14 / A15

def test_A14_prevision_une_decimale_acceptee():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    r = g.submit_forecast("100.5")
    assert r.success is True
    assert g.order_field_enabled is True


def test_A14_trou_entier_sans_decimale_accepte():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    r = g.submit_forecast("100")
    assert r.success is True


def test_A14_trou_virgule_decimale_acceptee():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    r = g.submit_forecast("100,5")
    assert r.success is True


@pytest.mark.parametrize("text", ["100.55", "100.05", "99.99"])
def test_A15_prevision_deux_decimales_refusee(text):
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    with pytest.raises(app.Refused):
        g.submit_forecast(text)


def test_A15_trou_refus_sans_effet():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    s = g.streak
    with pytest.raises(app.Refused):
        g.submit_forecast("100.55")
    assert g.streak == s
    assert g.order_field_enabled is False
    assert g.forecast_field_enabled is True
    r = g.submit_forecast("100.5")
    assert r.success is True


# ----------------------------------------------------------------- A16 – A20

def test_A16_moyenne_mobile_des_3_dernieres_semaines():
    g = app.Game(seed=1, history=[10, 10, 10, 10, 10, 80, 90, 130])
    ready(g)
    r = g.submit_forecast("100.0")
    assert r.moving_average == pytest.approx(100.0), f"expected 100.0, got {r.moving_average}"
    assert r.success is True


def test_A16_moyenne_mobile_non_entiere():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 100, 101, 101])
    ready(g)
    r = g.submit_forecast("300.0")
    assert r.moving_average == pytest.approx(302 / 3, abs=1e-9)


def test_A17_ecart_inferieur_a_1_pourcent_succes():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    assert g.submit_forecast("100.9").success is True


def test_A17_ecart_inferieur_par_dessous_succes():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    assert g.submit_forecast("99.1").success is True


def test_A18_ecart_exactement_1_pourcent_succes():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    assert g.submit_forecast("101.0").success is True


def test_A18_ecart_exactement_1_pourcent_par_dessous():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    assert g.submit_forecast("99.0").success is True


def test_A18_ecart_exactement_1_pourcent_sans_erreur_flottante():
    # 90.9 - 90 == 0.9000000000000057 in binary floats: a naive float comparison fails
    g = app.Game(seed=1, history=[90] * 8)
    ready(g)
    r = g.submit_forecast("90.9")
    assert r.success is True, "deviation is exactly 1 % of 90 and must be a success"


def test_A18_ecart_exactement_1_pourcent_sans_erreur_flottante_dessous():
    g = app.Game(seed=1, history=[70] * 8)
    ready(g)
    assert g.submit_forecast("69.3").success is True


def test_A19_ecart_superieur_a_1_pourcent_echec():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    assert g.submit_forecast("101.1").success is False


def test_A19_ecart_superieur_par_dessous_echec():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    assert g.submit_forecast("98.9").success is False


def test_A20_comparaison_a_la_moyenne_non_arrondie():
    g = app.Game(seed=1, history=[100, 100, 100, 100, 100, 100, 101, 101])
    ready(g)
    r = g.submit_forecast("101.7")
    assert r.success is False, "101.7 vs 100.667: deviation 1.033 > 1.00667 -> failure"
    assert r.moving_average == pytest.approx(302 / 3, abs=1e-9)


def test_A20_arrondi_ne_sauve_pas_une_prevision_proche_de_l_arrondi():
    # 101.0 vs 100.667: deviation 0.333 < 1.00667 -> success (both rules agree)
    g = app.Game(seed=1, history=[100, 100, 100, 100, 100, 100, 101, 101])
    ready(g)
    assert g.submit_forecast("101.0").success is True


# ----------------------------------------------------------------- A21 – A24

def test_A21_commentaire_apres_prevision():
    g1 = app.Game(seed=1, history=list(BASE))
    ready(g1)
    ok = g1.submit_forecast("100.5")
    g2 = app.Game(seed=1, history=list(BASE))
    ready(g2)
    ko = g2.submit_forecast("150.0")
    assert isinstance(ok.comment, str) and ok.comment.strip()
    assert isinstance(ko.comment, str) and ko.comment.strip()
    assert ok.comment != ko.comment, "mentor must comment the deviation, not a fixed text"


def test_A21_trou_ecart_chiffre_dans_commentaire():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    r = g.submit_forecast("112.5")
    assert contains_number(r.comment, r"(?<![\d.,])12[.,]5(?!\d)"), (
        f"comment should state the deviation 12.5: {r.comment!r}")


def test_A22_echec_affiche_moyenne_correcte():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 90, 95, 100])
    ready(g)
    r = g.submit_forecast("150.0")
    assert r.success is False
    assert contains_number(r.comment, r"(?<![\d.,])95(?:[.,]0+)?(?![\d])"), (
        f"comment must show the moving average 95: {r.comment!r}")


def test_A22_trou_precision_moyenne_affichee():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 87, 93, 106])
    ready(g)
    r = g.submit_forecast("150.0")
    assert contains_number(r.comment, r"95[.,]3"), (
        f"comment must show 95.33.. with at least one decimal: {r.comment!r}")


def test_A23_echec_affiche_les_3_nombres():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 87, 93, 106])
    ready(g)
    r = g.submit_forecast("150.0")
    for n in ("87", "93", "106"):
        assert re.search(rf"(?<![\d.,]){n}(?![\d])", r.comment), (
            f"comment must show {n}: {r.comment!r}")


def test_A23_echec_affiche_les_3_dernieres_pas_les_premieres():
    g = app.Game(seed=1, history=[11, 12, 13, 14, 15, 87, 93, 106])
    ready(g)
    r = g.submit_forecast("150.0")
    assert "11" not in r.comment and "12" not in r.comment and "13" not in r.comment, (
        f"comment shows weeks not used in the average: {r.comment!r}")


def test_A24_echec_affiche_le_calcul():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 87, 93, 106])
    ready(g)
    r = g.submit_forecast("150.0")
    assert re.search(r"87\s*\+\s*93\s*\+\s*106", r.comment), f"sum not shown: {r.comment!r}"
    assert re.search(r"[/÷]\s*3(?!\d)", r.comment), f"division by 3 not shown: {r.comment!r}"


# ----------------------------------------------------------------- A25 – A31

def _many_weeks(seed, n, order=100):
    g = app.Game(seed=seed)
    weeks = []
    for _ in range(n):
        _, w = play_week(g, bad_forecast(g), order=order)
        weeks.append(w)
    return g, weeks


def test_A25_demande_entiere_non_negative():
    _, weeks = _many_weeks(5, 200)
    for w in weeks:
        assert isinstance(w.demand, int) and not isinstance(w.demand, bool), f"{w.demand!r}"
        assert w.demand >= 0


def test_A25_demande_suit_la_loi_normale_de_la_partie():
    for seed in (2, 9):
        g, weeks = _many_weeks(seed, 400)
        d = [w.demand for w in weeks]
        m = statistics.fmean(d)
        sd = statistics.pstdev(d)
        tol = 4 * g.std_dev / math.sqrt(len(d))
        assert abs(m - g.mean_demand) < tol, (
            f"seed {seed}: sample mean {m} vs game mean {g.mean_demand} (tol {tol})")
        assert 0.8 * g.std_dev < sd < 1.2 * g.std_dev, (
            f"seed {seed}: sample std {sd} vs game std {g.std_dev}")
        within = sum(abs(x - g.mean_demand) <= g.std_dev for x in d) / len(d)
        assert 0.60 < within < 0.77, f"seed {seed}: {within:.2f} within 1 sd, normal gives ~0.68"


def test_A25_demande_differe_entre_parties():
    seen = set()
    for s in range(20):
        g = app.Game(seed=s, history=list(BASE))
        _, w = play_week(g, "150.0", order=100)
        seen.add(w.demand)
    assert len(seen) > 5, f"demand barely varies across games: {seen}"


def test_A26_ventes_minimum_demande_commande():
    for order in (0, 50, 100, 1000):
        _, weeks = _many_weeks(3, 30, order=order)
        for w in weeks:
            assert w.sales == min(w.demand, order), (
                f"order {order}, demand {w.demand}: expected sales {min(w.demand, order)}, got {w.sales}")


def test_A26_trou_commande_negative_refusee():
    g = app.Game(seed=1, history=list(BASE))
    ready(g)
    g.submit_forecast("150.0")
    with pytest.raises(app.Refused):
        g.submit_order(-1)
    assert len(g.history) == 8


def test_A27_manques_demande_moins_ventes():
    for order in (0, 80, 1000):
        _, weeks = _many_weeks(4, 30, order=order)
        for w in weeks:
            assert w.missed == w.demand - w.sales, f"{w}"
    _, weeks = _many_weeks(4, 5, order=0)
    assert all(w.missed == w.demand for w in weeks)


def test_A28_jetes_commande_moins_ventes():
    for order in (0, 80, 1000):
        _, weeks = _many_weeks(6, 30, order=order)
        for w in weeks:
            assert w.wasted == order - w.sales, f"order {order}: {w}"
    _, weeks = _many_weeks(6, 5, order=1000)
    assert all(w.wasted == 1000 - w.demand for w in weeks)


def test_A29_recette_ventes_fois_1_20():
    for order in (0, 77, 1000):
        _, weeks = _many_weeks(8, 20, order=order)
        for w in weeks:
            assert float(w.revenue) == pytest.approx(w.sales * 1.20, abs=0.005), (
                f"sales {w.sales}: expected revenue {w.sales * 1.20}, got {w.revenue}")


def test_A30_cout_commande_fois_0_80():
    for order in (0, 77, 1000):
        _, weeks = _many_weeks(8, 5, order=order)
        for w in weeks:
            assert float(w.cost) == pytest.approx(order * 0.80, abs=0.005), (
                f"order {order}: expected cost {order * 0.80}, got {w.cost}")


def test_A31_benefice_recette_moins_cout():
    for order in (0, 77, 1000):
        _, weeks = _many_weeks(10, 20, order=order)
        for w in weeks:
            assert float(w.profit) == pytest.approx(w.sales * 1.20 - order * 0.80, abs=0.005), f"{w}"
            assert float(w.profit) == pytest.approx(float(w.revenue) - float(w.cost), abs=0.005)


def test_A31_benefice_negatif_si_tout_jete():
    g = app.Game(seed=1, history=list(BASE))
    _, w = play_week(g, "150.0", order=0)
    assert float(w.profit) == pytest.approx(0.0, abs=0.005)


# ----------------------------------------------------------------- A32 / A33

def test_A32_semaine_ajoutee_en_fin_d_historique():
    hist = [10, 20, 30, 40, 50, 60, 70, 80]
    g = app.Game(seed=1, history=list(hist))
    _, w = play_week(g, "500.0", order=10)
    assert g.history == hist + [w.demand], (
        f"expected {hist + [w.demand]}, got {g.history}")


def test_A32_historique_porte_la_demande_pas_les_ventes():
    g = app.Game(seed=1, history=list(BASE))
    _, w = play_week(g, "150.0", order=0)
    assert w.demand > 0
    assert g.history[-1] == w.demand, f"history must record demand {w.demand}, got {g.history[-1]}"


def test_A33_moyenne_mobile_inclut_la_semaine_jouee():
    g = app.Game(seed=1, history=[0, 0, 0, 0, 0, 100, 100, 100])
    _, w = play_week(g, "500.0", order=50)
    ready(g)
    r = g.submit_forecast("500.0")
    assert r.moving_average == pytest.approx((100 + 100 + w.demand) / 3, abs=1e-9), (
        f"expected {(200 + w.demand) / 3}, got {r.moving_average}")


# ----------------------------------------------------------------- A34 – A39

def test_A34_succes_augmente_la_serie():
    g = app.Game(seed=1, history=list(BASE))
    before = g.streak
    play_week(g, "100.0", order=100)
    assert g.streak == before + 1


def test_A35_echec_apres_succes_remet_a_zero():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "100.0", order=100)
    assert g.streak == 1
    play_week(g, bad_forecast(g), order=100)
    assert g.streak == 0


def test_A36_serie_2_valide_le_critere():
    g = app.Game(seed=1, history=list(BASE))
    assert not g.criteria.get("SC0x-01", False)
    play_week(g, "100.0", order=100)
    assert not g.criteria.get("SC0x-01", False), "criterion validated after one success only"
    ready(g)
    assert g.submit_forecast(good_forecast(g)).success is True
    finish_week_if_possible(g)
    assert g.criteria.get("SC0x-01") is True


def test_A36_serie_interrompue_ne_valide_pas():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "100.0")
    play_week(g, bad_forecast(g))
    play_week(g, good_forecast(g))
    assert not g.criteria.get("SC0x-01", False)
    assert g.level_finished is False


def test_A37_serie_2_termine_le_niveau():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "100.0")
    ready(g)
    g.submit_forecast(good_forecast(g))
    finish_week_if_possible(g)
    assert g.level_finished is True


def test_A37_trou_semaine_finale_resolue_par_commande():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "100.0")
    ready(g)
    g.submit_forecast(good_forecast(g))
    assert g.order_field_enabled is True
    w = g.submit_order(100)
    assert g.history[-1] == w.demand
    assert g.level_finished is True


def test_A37_trou_plus_de_prevision_apres_fin():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "100.0")
    ready(g)
    g.submit_forecast(good_forecast(g))
    finish_week_if_possible(g)
    assert g.level_finished is True
    with pytest.raises(app.Refused):
        g.open_order_screen()
        g.submit_forecast(good_forecast(g))


def test_A38_serie_1_le_niveau_continue():
    g = app.Game(seed=1, history=list(BASE))
    play_week(g, "100.0")
    assert g.streak == 1
    assert g.level_finished is False
    ready(g)
    assert g.forecast_field_enabled is True
    r = g.submit_forecast(bad_forecast(g))
    assert r.moving_average == pytest.approx(ma3(g.history))
    assert len(g.history) == 9


def test_A39_message_de_conclusion():
    g = app.Game(seed=1, history=list(BASE))
    assert not g.final_message
    play_week(g, "100.0")
    assert not g.final_message, "final message shown before the end of the level"
    ready(g)
    g.submit_forecast(good_forecast(g))
    finish_week_if_possible(g)
    assert isinstance(g.final_message, str) and g.final_message.strip()


# ----------------------------------------------------------------- A40

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def test_A40_page_servie_au_navigateur_mobile():
    server = app.WebServer()
    resp = server.get("/", headers={"User-Agent": MOBILE_UA})
    assert resp.status == 200, f"expected 200, got {resp.status}"
    ctype = {k.lower(): v for k, v in resp.headers.items()}.get("content-type", "")
    assert ctype.startswith("text/html"), f"expected text/html, got {ctype!r}"
    assert "<html" in resp.body.lower()


def test_A40_trou_page_mobile_jouable_sans_installation():
    server = app.WebServer()
    body = server.get("/", headers={"User-Agent": MOBILE_UA}).body
    low = body.lower()
    assert re.search(r'<meta[^>]+name=["\']viewport["\']', low), "no viewport meta for mobile"
    assert "<input" in low, "the order screen (forecast field) must be in the page"
    for marker in (".apk", "app store", "play store", "télécharger l'application"):
        assert marker not in low, f"page asks for an installation: {marker!r}"
