"""Red tests — code layer, first attack.

Public interface fixed by these tests (module `app`):

    app.Game(seed: int | None = None, history: list[int] | None = None)
        A new game. `seed` drives every random draw (random.Random(seed)).
        `history`, if given, replaces the 8 drawn initial weeks (test setup only);
        mean demand and standard deviation are still drawn.

    game.history            -> list[int]   weekly units, oldest first
    game.mean_demand        -> float       drawn once per game
    game.std_dev            -> float       drawn once per game
    game.open_order_screen()   -> None
    game.mentor_explanation    -> str | None  text of the 3-week moving-average
                                              explanation while displayed, else None
    game.dismiss_explanation() -> None
    game.forecast_field_enabled -> bool
    game.order_field_enabled    -> bool
    game.table_rows()  -> list[tuple[int, int]]   (week number, units), one per history week
    game.chart_bars()  -> list[float]             bar heights, one per history week
    game.submit_forecast(text: str) -> ForecastResult
        .accepted: bool, .success: bool | None, .moving_average: float | None,
        .comment: str | None
        raises app.FieldDisabledError when the forecast field is disabled.
    game.submit_order(quantity: int) -> WeekResult
        .demand, .sold, .missed, .wasted: int ; .revenue, .cost, .profit: float (euros)
        raises app.FieldDisabledError when the order field is disabled.
    game.streak       -> int
    game.criteria     -> dict[str, bool]   e.g. {"SC0x-01": False}
    game.level_over   -> bool
    game.final_message -> str | None
    app.page_html()   -> str   the page served at the game's address
"""

import re
import statistics

import pytest

import app


# ---------------------------------------------------------------- helpers

BASE = [90, 95, 100, 105, 110, 98, 102, 99]


def make(history=None, seed=1):
    return app.Game(seed=seed, history=list(history) if history is not None else None)


def ready(game):
    """Open the order screen and dismiss the mentor explanation if shown."""
    game.open_order_screen()
    if game.mentor_explanation is not None:
        game.dismiss_explanation()
    return game


def ma3(history):
    return sum(history[-3:]) / 3


def good_forecast(game):
    return f"{ma3(game.history):.1f}"


BAD_FORECAST = "100000"


def play_week(game, forecast, order):
    f = game.submit_forecast(forecast)
    assert f.accepted, f"forecast {forecast!r} should be accepted, got refused"
    w = game.submit_order(order)
    return f, w


# ---------------------------------------------------------------- A01

@pytest.mark.parametrize("seed", range(30))
def test_A01_initial_history_has_exactly_8_weeks(seed):
    g = app.Game(seed=seed)
    assert len(g.history) == 8, f"expected 8 weeks, got {len(g.history)}: {g.history}"


def test_A01_trou_initial_history_drawn_from_game_law():
    ratios = []
    nonconstant = 0
    for seed in range(300):
        g = app.Game(seed=seed)
        ratios.append(statistics.mean(g.history) / g.mean_demand)
        if len(set(g.history)) > 1:
            nonconstant += 1
    avg = statistics.mean(ratios)
    assert 0.95 <= avg <= 1.05, (
        f"initial weeks should be drawn around the game's mean demand; "
        f"mean(history)/mean_demand averaged {avg:.3f}")
    assert nonconstant >= 290, (
        f"initial history should vary week to week; only {nonconstant}/300 games did")


# ---------------------------------------------------------------- A02

def test_A02_mean_demand_between_60_and_140():
    for seed in range(500):
        m = app.Game(seed=seed).mean_demand
        assert 60 <= m <= 140, f"seed {seed}: mean demand {m} outside [60, 140]"


def test_A02_mean_demand_is_actually_drawn():
    values = [app.Game(seed=s).mean_demand for s in range(300)]
    assert len(set(values)) >= 50, f"only {len(set(values))} distinct mean demands over 300 games"
    assert min(values) < 80 and max(values) > 120, (
        f"draw should cover the range; got min={min(values)}, max={max(values)}")


# ---------------------------------------------------------------- A03

def test_A03_mean_demand_constant_across_weeks():
    g = ready(make(BASE, seed=7))
    m0, s0 = g.mean_demand, g.std_dev
    for _ in range(20):
        play_week(g, BAD_FORECAST, 100)
        assert g.mean_demand == m0, f"mean demand changed from {m0} to {g.mean_demand}"
    assert g.std_dev == s0


# ---------------------------------------------------------------- A04

def test_A04_std_dev_between_10_and_20_percent_of_mean():
    for seed in range(500):
        g = app.Game(seed=seed)
        r = g.std_dev / g.mean_demand
        assert 0.10 - 1e-12 <= r <= 0.20 + 1e-12, (
            f"seed {seed}: std {g.std_dev} / mean {g.mean_demand} = {r:.4f} not in [0.10, 0.20]")


def test_A04_std_ratio_is_actually_drawn():
    ratios = [app.Game(seed=s).std_dev / app.Game(seed=s).mean_demand for s in range(300)]
    assert min(ratios) < 0.12 and max(ratios) > 0.18, (
        f"ratio should be drawn over [0.10, 0.20]; got min={min(ratios):.3f}, max={max(ratios):.3f}")


# ---------------------------------------------------------------- A05

def test_A05_initial_weeks_are_non_negative_integers():
    for seed in range(300):
        for u in app.Game(seed=seed).history:
            assert isinstance(u, int) and not isinstance(u, bool), (
                f"seed {seed}: week value {u!r} is not an int")
            assert u >= 0, f"seed {seed}: negative week value {u}"


# ---------------------------------------------------------------- A06 / A07 / A08

def test_A06_first_opening_shows_moving_average_explanation():
    g = make(BASE)
    assert g.mentor_explanation is None, "explanation shown before the screen was opened"
    g.open_order_screen()
    text = g.mentor_explanation
    assert isinstance(text, str) and text.strip(), f"expected explanation text, got {text!r}"
    assert "moyenne mobile" in text.lower(), f"explanation does not mention 'moyenne mobile': {text!r}"
    assert "3" in text, f"explanation does not mention the 3 weeks: {text!r}"


def test_A07_second_opening_does_not_show_explanation():
    g = make(BASE)
    g.open_order_screen()
    g.dismiss_explanation()
    g.open_order_screen()
    assert g.mentor_explanation is None, f"explanation shown again: {g.mentor_explanation!r}"


def test_A07_explanation_not_shown_after_a_played_week():
    g = ready(make(BASE))
    play_week(g, BAD_FORECAST, 100)
    g.open_order_screen()
    assert g.mentor_explanation is None


def test_A08_forecast_field_disabled_while_explanation_shown():
    g = make(BASE)
    g.open_order_screen()
    assert g.mentor_explanation is not None
    assert g.forecast_field_enabled is False, "forecast field enabled during explanation"
    with pytest.raises(app.FieldDisabledError):
        g.submit_forecast("100.0")
    g.dismiss_explanation()
    assert g.forecast_field_enabled is True, "forecast field still disabled after dismissal"


# ---------------------------------------------------------------- A09 / A10 / A11

def test_A09_table_one_row_per_week_with_number():
    g = make(BASE)
    rows = g.table_rows()
    assert [r[0] for r in rows] == list(range(1, 9)), f"week numbers: {[r[0] for r in rows]}"


def test_A09_table_grows_with_history():
    g = ready(make(BASE))
    play_week(g, BAD_FORECAST, 100)
    rows = g.table_rows()
    assert len(rows) == 9 and rows[-1][0] == 9, f"rows after one week: {rows}"


def test_A10_table_shows_units_of_each_week():
    g = make(BASE)
    assert [r[1] for r in g.table_rows()] == BASE


def test_A10_trou_table_after_stockout_shows_history_value():
    g = ready(make(BASE, seed=3))
    _, w = play_week(g, BAD_FORECAST, 0)
    assert w.demand > 0
    assert g.table_rows()[-1][1] == g.history[-1] == w.demand, (
        f"table last row {g.table_rows()[-1]} vs history {g.history[-1]} vs demand {w.demand}")


def test_A11_chart_bar_per_week_proportional():
    hist = [50, 100, 25, 200, 0, 75, 150, 10]
    g = make(hist)
    bars = g.chart_bars()
    assert len(bars) == 8, f"expected 8 bars, got {len(bars)}"
    k = bars[1] / 100
    assert k > 0
    for u, h in zip(hist, bars):
        assert h == pytest.approx(k * u, rel=1e-6, abs=1e-9), (
            f"bar for {u} units has height {h}, expected {k * u}")


def test_A11_chart_grows_with_history():
    g = ready(make(BASE))
    play_week(g, BAD_FORECAST, 100)
    assert len(g.chart_bars()) == 9


# ---------------------------------------------------------------- A12 / A13

def test_A12_order_field_disabled_before_forecast():
    g = ready(make(BASE))
    assert g.order_field_enabled is False
    with pytest.raises(app.FieldDisabledError):
        g.submit_order(100)


def test_A12_order_field_disabled_again_for_next_week():
    g = ready(make(BASE))
    play_week(g, BAD_FORECAST, 100)
    assert g.order_field_enabled is False, "order field still enabled for the new week"
    with pytest.raises(app.FieldDisabledError):
        g.submit_order(100)


def test_A13_order_field_enabled_after_forecast():
    g = ready(make(BASE))
    g.submit_forecast("100.0")
    assert g.order_field_enabled is True


# ---------------------------------------------------------------- A14 / A15

@pytest.mark.parametrize("text", ["100.3", "99.9"])
def test_A14_one_decimal_accepted(text):
    g = ready(make(BASE))
    assert g.submit_forecast(text).accepted is True


def test_A14_trou_decimal_comma_accepted():
    g = ready(make(BASE))
    assert g.submit_forecast("100,3").accepted is True


def test_A14_trou_integer_accepted():
    g = ready(make(BASE))
    assert g.submit_forecast("100").accepted is True


@pytest.mark.parametrize("text", ["100.33", "99.90", "100,33"])
def test_A15_two_decimals_refused(text):
    g = ready(make(BASE))
    r = g.submit_forecast(text)
    assert r.accepted is False, f"{text!r} accepted"
    assert g.order_field_enabled is False, "refused forecast enabled the order field"


def test_A15_trou_refused_forecast_does_not_touch_streak():
    hist = [100] * 8
    g = ready(make(hist))
    play_week(g, "100.0", 100)  # success -> streak 1
    assert g.streak == 1
    r = g.submit_forecast("100.25")
    assert r.accepted is False
    assert g.streak == 1, f"refused forecast changed streak to {g.streak}"
    assert g.level_over is False


# ---------------------------------------------------------------- A16

def test_A16_moving_average_is_mean_of_last_3_weeks():
    g = ready(make([10, 20, 30, 40, 50, 87, 93, 104]))
    r = g.submit_forecast("50")
    assert r.moving_average == pytest.approx((87 + 93 + 104) / 3, abs=1e-9)


@pytest.mark.parametrize("seed", range(10))
def test_A16_moving_average_on_drawn_history(seed):
    g = ready(app.Game(seed=seed))
    r = g.submit_forecast("50")
    assert r.moving_average == pytest.approx(ma3(g.history), abs=1e-9)


# ---------------------------------------------------------------- A17 / A18 / A19 / A20

def test_A17_deviation_below_1_percent_is_success():
    g = ready(make([100] * 8))
    assert g.submit_forecast("100.5").success is True


def test_A18_deviation_exactly_1_percent_is_success_above():
    g = ready(make([100] * 8))
    assert g.submit_forecast("101.0").success is True


def test_A18_deviation_exactly_1_percent_is_success_below():
    g = ready(make([100] * 8))
    assert g.submit_forecast("99").success is True


def test_A18_deviation_exactly_1_percent_is_success_other_scale():
    g = ready(make([200] * 8))
    assert g.submit_forecast("202").success is True


@pytest.mark.parametrize("text", ["101.1", "98.9", "0", BAD_FORECAST])
def test_A19_deviation_above_1_percent_is_failure(text):
    g = ready(make([100] * 8))
    assert g.submit_forecast(text).success is False


def test_A20_compare_to_unrounded_moving_average():
    g = ready(make([90, 95, 100, 105, 110, 100, 101, 101]))
    r = g.submit_forecast("101.7")
    assert r.success is False, "101.7 compared to rounded 101 instead of 100.667"


def test_A20_unrounded_average_success_side():
    g = ready(make([90, 95, 100, 105, 110, 100, 101, 101]))
    assert g.submit_forecast("101.6").success is True


# ---------------------------------------------------------------- A21 – A24

def test_A21_mentor_comments_after_forecast():
    g1 = ready(make([100] * 8))
    ok = g1.submit_forecast("100.0").comment
    g2 = ready(make([100] * 8))
    ko = g2.submit_forecast("150").comment
    assert isinstance(ok, str) and ok.strip(), f"no comment after success: {ok!r}"
    assert isinstance(ko, str) and ko.strip(), f"no comment after failure: {ko!r}"
    assert ok != ko, "same comment for a success and a failure"


FAIL_HIST = [10, 20, 30, 40, 50, 87, 93, 104]


def test_A22_failure_comment_shows_moving_average():
    g = ready(make(FAIL_HIST))
    c = g.submit_forecast("50").comment
    assert any(v in c for v in ("94.67", "94,67", "94.7", "94,7")), (
        f"comment does not show moving average 94.67: {c!r}")


def test_A23_failure_comment_shows_three_numbers():
    g = ready(make(FAIL_HIST))
    c = g.submit_forecast("50").comment
    for n in ("87", "93", "104"):
        assert re.search(rf"(?<!\d){n}(?!\d)", c), f"comment lacks {n}: {c!r}"


def test_A24_failure_comment_shows_calculation():
    g = ready(make(FAIL_HIST))
    c = g.submit_forecast("50").comment
    assert re.search(r"87\s*\+\s*93\s*\+\s*104", c), f"no sum 87 + 93 + 104 in {c!r}"
    assert re.search(r"[/÷]\s*3(?!\d)", c), f"no division by 3 in {c!r}"


# ---------------------------------------------------------------- A25 – A31

def _many_weeks(seed, n):
    g = ready(app.Game(seed=seed))
    results = []
    orders = []
    for i in range(n):
        order = (i * 37) % 200
        _, w = play_week(g, BAD_FORECAST, order)
        results.append(w)
        orders.append(order)
    return g, results, orders


def test_A25_demand_follows_game_normal_law():
    g, res, _ = _many_weeks(seed=11, n=2000)
    d = [w.demand for w in res]
    for x in d:
        assert isinstance(x, int) and not isinstance(x, bool) and x >= 0, f"bad demand {x!r}"
    m, s = statistics.mean(d), statistics.stdev(d)
    assert abs(m - g.mean_demand) < 4 * g.std_dev / (2000 ** 0.5) + 0.5, (
        f"sample mean {m:.2f} vs game mean {g.mean_demand:.2f}")
    assert s == pytest.approx(g.std_dev, rel=0.12), f"sample std {s:.2f} vs game std {g.std_dev:.2f}"


def test_A25_demand_differs_between_games():
    a = [w.demand for w in _many_weeks(1, 30)[1]]
    b = [w.demand for w in _many_weeks(2, 30)[1]]
    assert a != b


def test_A26_to_A31_week_accounting():
    _, res, orders = _many_weeks(seed=5, n=300)
    stockouts = waste = 0
    for w, o in zip(res, orders):
        assert w.sold == min(w.demand, o), f"A26: sold {w.sold}, demand {w.demand}, order {o}"
        assert w.missed == w.demand - w.sold, f"A27: missed {w.missed}"
        assert w.wasted == o - w.sold, f"A28: wasted {w.wasted}"
        assert w.revenue == pytest.approx(w.sold * 1.20, abs=1e-9), f"A29: revenue {w.revenue}"
        assert w.cost == pytest.approx(o * 0.80, abs=1e-9), f"A30: cost {w.cost}"
        assert w.profit == pytest.approx(w.revenue - w.cost, abs=1e-9), f"A31: profit {w.profit}"
        stockouts += w.missed > 0
        waste += w.wasted > 0
    assert stockouts > 0 and waste > 0


def test_A26_sold_is_min_zero_order():
    g = ready(make(BASE))
    _, w = play_week(g, BAD_FORECAST, 0)
    assert w.sold == 0 and w.missed == w.demand and w.wasted == 0


def test_A27_A28_large_order_no_stockout():
    g = ready(make(BASE))
    _, w = play_week(g, BAD_FORECAST, 10_000)
    assert w.sold == w.demand and w.missed == 0 and w.wasted == 10_000 - w.demand


def test_A29_A30_A31_exact_euros():
    g = ready(make(BASE))
    _, w = play_week(g, BAD_FORECAST, 0)
    assert w.revenue == 0 and w.cost == 0 and w.profit == 0


def test_A28_trou_negative_order_refused():
    g = ready(make(BASE))
    g.submit_forecast(BAD_FORECAST)
    with pytest.raises(ValueError):
        g.submit_order(-1)
    assert len(g.history) == 8, "a refused order resolved the week"


# ---------------------------------------------------------------- A32 / A33

def test_A32_week_appended_with_demand():
    g = ready(make(BASE))
    _, w = play_week(g, BAD_FORECAST, 0)
    assert g.history[:8] == BASE
    assert len(g.history) == 9 and g.history[-1] == w.demand, (
        f"history {g.history}, demand {w.demand}")


def test_A33_next_moving_average_includes_played_week():
    g = ready(make(BASE))
    _, w = play_week(g, BAD_FORECAST, 50)
    r = g.submit_forecast(BAD_FORECAST)
    expected = (BASE[-2] + BASE[-1] + w.demand) / 3
    assert r.moving_average == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------- A34 – A39

def test_A34_success_increments_streak():
    g = ready(make(BASE))
    assert g.streak == 0
    play_week(g, good_forecast(g), 100)
    assert g.streak == 1


def test_A35_failure_after_success_resets_streak():
    g = ready(make(BASE))
    play_week(g, good_forecast(g), 100)
    play_week(g, BAD_FORECAST, 100)
    assert g.streak == 0


def test_A35_failure_from_zero_stays_zero():
    g = ready(make(BASE))
    play_week(g, BAD_FORECAST, 100)
    assert g.streak == 0


def test_A36_criterion_validated_at_streak_2():
    g = ready(make(BASE))
    assert not g.criteria.get("SC0x-01", False)
    play_week(g, good_forecast(g), 100)
    assert not g.criteria.get("SC0x-01", False), "criterion validated at streak 1"
    play_week(g, good_forecast(g), 100)
    assert g.criteria.get("SC0x-01") is True


def test_A36_non_consecutive_successes_do_not_validate():
    g = ready(make(BASE))
    play_week(g, good_forecast(g), 100)
    play_week(g, BAD_FORECAST, 100)
    play_week(g, good_forecast(g), 100)
    assert not g.criteria.get("SC0x-01", False)
    assert g.level_over is False


def test_A37_level_ends_at_streak_2():
    g = ready(make(BASE))
    play_week(g, good_forecast(g), 100)
    play_week(g, good_forecast(g), 100)
    assert g.level_over is True


def test_A38_streak_1_level_continues():
    g = ready(make(BASE))
    play_week(g, good_forecast(g), 100)
    assert g.level_over is False
    assert len(g.history) == 9
    assert g.forecast_field_enabled is True
    assert g.order_field_enabled is False


def test_A39_final_message_at_level_end():
    g = ready(make(BASE))
    assert g.final_message is None
    play_week(g, good_forecast(g), 100)
    assert g.final_message is None
    play_week(g, good_forecast(g), 100)
    assert isinstance(g.final_message, str) and g.final_message.strip()


def test_A37_trou_no_forecast_after_level_end():
    g = ready(make(BASE))
    play_week(g, good_forecast(g), 100)
    play_week(g, good_forecast(g), 100)
    assert g.forecast_field_enabled is False
    with pytest.raises(app.FieldDisabledError):
        g.submit_forecast(good_forecast(g))


# ---------------------------------------------------------------- A40

def test_A40_trou_page_is_self_contained_mobile_html():
    html = app.page_html()
    assert isinstance(html, str)
    low = html.lower()
    assert "<!doctype html" in low and "<html" in low
    assert re.search(r'<meta[^>]+name=["\']viewport["\']', low), "no mobile viewport meta"
    assert not re.search(r'(src|href)=["\']https?://', low), "page depends on external resources"
