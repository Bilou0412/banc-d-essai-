"""Red tests — code layer, second attack.

Same public interface as tests/test_app.py (module `app`); see that file's docstring.
"""

import re
import statistics
from decimal import Decimal

import pytest

import app


# ---------------------------------------------------------------- helpers

BASE = [90, 95, 100, 105, 110, 98, 102, 99]
BAD = "100000"


def make(history=None, seed=1):
    return app.Game(seed=seed, history=list(history) if history is not None else None)


def ready(game):
    game.open_order_screen()
    if game.mentor_explanation is not None:
        game.dismiss_explanation()
    return game


def ma3(history):
    return sum(history[-3:]) / 3


def good(game):
    return f"{ma3(game.history):.1f}"


def play(game, forecast, order):
    f = game.submit_forecast(forecast)
    assert f.accepted, f"forecast {forecast!r} should be accepted, got refused"
    w = game.submit_order(order)
    return f, w


def ma_strings(ma):
    c = {f"{ma:.2f}", f"{ma:.1f}"}
    c |= {s.replace(".", ",") for s in c}
    if abs(ma - round(ma)) < 1e-9:
        c.add(str(int(round(ma))))
    return c


# ---------------------------------------------------------------- A01 / A02 (draws)

def test_A01_trou_initial_history_spread_matches_std():
    z = []
    for seed in range(300):
        g = app.Game(seed=seed)
        z += [(u - g.mean_demand) / g.std_dev for u in g.history]
    s = statistics.pstdev(z)
    assert 0.85 <= s <= 1.15, (
        f"initial weeks should be spread by the game's std dev; pooled std of "
        f"(units - mean)/std is {s:.3f}, expected about 1")


def test_A02_trou_same_seed_same_game_and_demands():
    a, b = app.Game(seed=5), app.Game(seed=5)
    assert (a.history, a.mean_demand, a.std_dev) == (b.history, b.mean_demand, b.std_dev), (
        "same seed produced different games")
    ready(a), ready(b)
    da = [play(a, BAD, 100)[1].demand for _ in range(20)]
    db = [play(b, BAD, 100)[1].demand for _ in range(20)]
    assert da == db, f"same seed, same actions, different demands: {da} vs {db}"


def test_A02_trou_no_seed_draws_vary():
    values = {app.Game().mean_demand for _ in range(20)}
    assert len(values) > 1, f"20 unseeded games all drew mean demand {values}"


# ---------------------------------------------------------------- A08

def test_A08_trou_forecast_disabled_before_screen_opened():
    g = make(BASE)
    assert g.forecast_field_enabled is False, (
        "forecast field enabled before the order screen (and mentor explanation) was shown")
    with pytest.raises(app.FieldDisabledError):
        g.submit_forecast("100.0")


# ---------------------------------------------------------------- A09 / A10 / A11

def test_A09_A10_table_after_three_weeks():
    g = ready(make(BASE))
    demands = [play(g, BAD, 100)[1].demand for _ in range(3)]
    rows = g.table_rows()
    assert [r[0] for r in rows] == list(range(1, 12)), f"week numbers {[r[0] for r in rows]}"
    assert [r[1] for r in rows] == BASE + demands, f"units {[r[1] for r in rows]}"


def test_A11_all_zero_history_chart():
    g = make([0] * 8)
    bars = g.chart_bars()
    assert len(bars) == 8
    assert all(h == pytest.approx(0, abs=1e-12) for h in bars), f"zero weeks give bars {bars}"


def test_A11_single_nonzero_week_chart():
    g = make([0] * 7 + [5])
    bars = g.chart_bars()
    assert all(h == pytest.approx(0, abs=1e-12) for h in bars[:7]), f"bars {bars}"
    assert bars[7] > 0, f"bar for 5 units has height {bars[7]}"


def test_A11_chart_proportional_after_played_weeks():
    g = ready(make(BASE, seed=9))
    for o in (0, 500, 50):
        play(g, BAD, o)
    bars, hist = g.chart_bars(), g.history
    assert len(bars) == len(hist) == 11
    k = bars[0] / hist[0]
    for u, h in zip(hist, bars):
        assert h == pytest.approx(k * u, rel=1e-6, abs=1e-9), (
            f"bar for {u} units has height {h}, expected {k * u} (history {hist}, bars {bars})")


# ---------------------------------------------------------------- A12 / A34 (repetition in a week)

def test_A12_trou_second_forecast_same_week_cannot_rescue_failure():
    g = ready(make([100] * 8))
    r = g.submit_forecast("150")
    assert r.success is False
    try:
        g.submit_forecast("100.0")
    except app.FieldDisabledError:
        pass
    g.submit_order(100)
    assert g.streak == 0, (
        f"after a failed forecast, resubmitting the shown correct value made streak {g.streak}")


def test_A34_trou_repeated_success_same_week_counts_once():
    g = ready(make([100] * 8))
    g.submit_forecast("100.0")
    for _ in range(3):
        try:
            g.submit_forecast("100.0")
        except app.FieldDisabledError:
            pass
    assert g.streak <= 1, f"one week counted as {g.streak} successes"
    assert g.level_over is False, "level ended within a single week"
    assert not g.criteria.get("SC0x-01", False)
    g.submit_order(100)
    assert g.streak == 1, f"streak {g.streak} after a single successful week"
    assert g.level_over is False


# ---------------------------------------------------------------- A14 / A15 (input)

def test_A14_trou_comma_value_is_parsed_as_decimal():
    assert ready(make([100] * 8)).submit_forecast("100,9").success is True, (
        "'100,9' is 100.9, within 1 % of 100")
    assert ready(make([100] * 8)).submit_forecast("101,5").success is False, (
        "'101,5' is 101.5, beyond 1 % of 100")
    assert ready(make([100] * 8)).submit_forecast("98,9").success is False, (
        "'98,9' is 98.9, beyond 1 % of 100")


@pytest.mark.parametrize("text", ["", "   ", "abc", "nan", "inf", "-inf", "1..0",
                                  "10.0.0", "100.333", "100,3,3"])
def test_A15_trou_non_numeric_or_malformed_refused(text):
    g = ready(make(BASE))
    r = g.submit_forecast(text)
    assert r.accepted is False, f"{text!r} accepted"
    assert g.order_field_enabled is False, f"{text!r} enabled the order field"


def test_A15_refused_forecast_has_no_verdict():
    g = ready(make(BASE))
    r = g.submit_forecast("100.25")
    assert r.accepted is False
    assert r.success is None, f"refused forecast judged: success={r.success!r}"


# ---------------------------------------------------------------- A16 / A33

def test_A16_A33_moving_average_after_several_weeks():
    g = ready(make(BASE, seed=4))
    demands = [play(g, BAD, 100)[1].demand for _ in range(5)]
    r = g.submit_forecast(BAD)
    assert r.moving_average == pytest.approx(sum(demands[-3:]) / 3, abs=1e-9), (
        f"moving average {r.moving_average}, last 3 demands {demands[-3:]}")


# ---------------------------------------------------------------- A17 – A20 (boundaries)

def _exact(m, factor):
    return str((Decimal(m) * Decimal(factor)).quantize(Decimal("0.1")))


@pytest.mark.parametrize("m", range(10, 210, 10))
def test_A18_exact_1_percent_is_success_float_safe(m):
    up, down = _exact(m, "1.01"), _exact(m, "0.99")
    ru = ready(make([m] * 8)).submit_forecast(up)
    rd = ready(make([m] * 8)).submit_forecast(down)
    assert ru.success is True, f"moving average {m}: {up} is exactly 1 % above, judged failure"
    assert rd.success is True, f"moving average {m}: {down} is exactly 1 % below, judged failure"


@pytest.mark.parametrize("m", range(10, 210, 10))
def test_A19_just_beyond_1_percent_is_failure(m):
    up = str(Decimal(_exact(m, "1.01")) + Decimal("0.1"))
    down = str(Decimal(_exact(m, "0.99")) - Decimal("0.1"))
    assert ready(make([m] * 8)).submit_forecast(up).success is False, f"{up} vs {m}"
    assert ready(make([m] * 8)).submit_forecast(down).success is False, f"{down} vs {m}"


def test_A18_zero_moving_average_exact_forecast_is_success():
    r = ready(make([0] * 8)).submit_forecast("0")
    assert r.moving_average == 0
    assert r.success is True, "deviation 0 equals 1 % of 0: must be a success"


def test_A19_zero_moving_average_nonzero_forecast_is_failure():
    r = ready(make([0] * 8)).submit_forecast("0.1")
    assert r.success is False, "deviation 0.1 exceeds 1 % of 0"


def test_A20_comma_input_compared_to_unrounded_average():
    g = ready(make([90, 95, 100, 105, 110, 100, 101, 101]))
    assert g.submit_forecast("101,7").success is False


# ---------------------------------------------------------------- A21 – A24

def test_A21_trou_comment_depends_on_gap():
    c1 = ready(make([100] * 8)).submit_forecast("50").comment
    c2 = ready(make([100] * 8)).submit_forecast("150").comment
    assert c1 != c2, f"same comment for forecasts 50 and 150 against 100: {c1!r}"


@pytest.mark.parametrize("seed", range(10))
def test_A22_A23_A24_failure_comment_on_drawn_history(seed):
    g = ready(app.Game(seed=seed))
    a, b, c3 = g.history[-3:]
    c = g.submit_forecast(BAD).comment
    assert any(s in c for s in ma_strings((a + b + c3) / 3)), (
        f"A22: comment lacks moving average {(a + b + c3) / 3:.2f}: {c!r}")
    for n in (a, b, c3):
        assert re.search(rf"(?<!\d){n}(?!\d)", c), f"A23: comment lacks {n}: {c!r}"
    assert re.search(rf"(?<!\d){a}\s*\+\s*{b}\s*\+\s*{c3}(?!\d)", c), (
        f"A24: no sum {a} + {b} + {c3} in {c!r}")


def test_A23_A24_duplicate_values_shown_three_times():
    g = ready(make([10, 20, 30, 40, 50, 100, 100, 100]))
    c = g.submit_forecast("50").comment
    assert re.search(r"(?<!\d)100\s*\+\s*100\s*\+\s*100(?!\d)", c), f"no 100 + 100 + 100 in {c!r}"


def test_A24_calculation_after_a_played_week_uses_new_week():
    g = ready(make(BASE, seed=6))
    _, w = play(g, BAD, 100)
    c = g.submit_forecast(BAD).comment
    a, b = BASE[-2], BASE[-1]
    assert re.search(rf"(?<!\d){a}\s*\+\s*{b}\s*\+\s*{w.demand}(?!\d)", c), (
        f"expected {a} + {b} + {w.demand} in {c!r}")


def test_A24_zero_values_in_calculation():
    g = ready(make([10, 20, 30, 40, 50, 0, 0, 5]))
    c = g.submit_forecast("50").comment
    assert re.search(r"(?<!\d)0\s*\+\s*0\s*\+\s*5(?!\d)", c), f"no 0 + 0 + 5 in {c!r}"


# ---------------------------------------------------------------- A25 (the law, not a shortcut)

def _demands(seed, n, order=100, history=None):
    g = ready(app.Game(seed=seed, history=list(history) if history else None))
    return g, [play(g, BAD, order)[1].demand for _ in range(n)]


def test_A25_demand_independent_of_order():
    _, d0 = _demands(21, 60, order=0, history=BASE)
    _, d1 = _demands(21, 60, order=10_000, history=BASE)
    assert d0 == d1, "the drawn demand depends on the quantity ordered"


def test_A25_demand_shape_is_normal():
    g, d = _demands(11, 4000)
    z = [(x - g.mean_demand) / g.std_dev for x in d]
    w1 = sum(abs(v) <= 1 for v in z) / len(z)
    w2 = sum(abs(v) <= 2 for v in z) / len(z)
    assert 0.64 <= w1 <= 0.73, f"share within 1 sd is {w1:.3f}, normal law gives 0.683"
    assert 0.93 <= w2 <= 0.975, f"share within 2 sd is {w2:.3f}, normal law gives 0.954"
    m = statistics.mean(d)
    m2 = statistics.mean((x - m) ** 2 for x in d)
    m4 = statistics.mean((x - m) ** 4 for x in d)
    k = m4 / m2 ** 2 - 3
    assert abs(k) < 0.5, f"excess kurtosis {k:.2f}, normal law gives 0"


def test_A25_demand_weeks_are_independent():
    _, d = _demands(13, 2000)
    m = statistics.mean(d)
    num = sum((d[i] - m) * (d[i + 1] - m) for i in range(len(d) - 1))
    den = sum((x - m) ** 2 for x in d)
    r = num / den
    assert abs(r) < 0.1, f"lag-1 autocorrelation of demand is {r:.3f}, draws should be independent"


def test_A25_integer_demand_not_biased():
    seed = min(range(200), key=lambda s: app.Game(seed=s).std_dev)
    g, d = _demands(seed, 20000)
    m = statistics.mean(d)
    tol = 4 * g.std_dev / (len(d) ** 0.5) + 0.05
    assert abs(m - g.mean_demand) < tol, (
        f"mean of integer demands {m:.3f} vs game mean {g.mean_demand:.3f} "
        f"(tolerance {tol:.3f}); integerisation biases the law")


# ---------------------------------------------------------------- A26 – A31 (orders)

def test_A28_trou_refused_order_keeps_week_open():
    g = ready(make(BASE))
    g.submit_forecast(BAD)
    with pytest.raises(ValueError):
        g.submit_order(-5)
    assert g.order_field_enabled is True, "refused order closed the order field"
    w = g.submit_order(100)
    assert w.sold == min(w.demand, 100)
    assert len(g.history) == 9


def test_A28_trou_fractional_order_refused():
    g = ready(make(BASE))
    g.submit_forecast(BAD)
    with pytest.raises((ValueError, TypeError)):
        g.submit_order(10.5)
    assert len(g.history) == 8, "a fractional order resolved the week"


def test_A31_profit_negative_when_all_wasted():
    g = ready(make(BASE))
    _, w = play(g, BAD, 10_000)
    expected = round(w.demand * 1.20 - 10_000 * 0.80, 2)
    assert round(w.profit, 2) == expected, f"profit {w.profit}, expected {expected}"
    assert w.profit < 0


# ---------------------------------------------------------------- A32 / isolation

def test_A32_trou_games_do_not_share_state():
    g1, g2 = ready(make(BASE)), ready(make(BASE))
    play(g1, good(g1), 100)
    assert len(g2.history) == 8, f"playing one game changed another's history: {g2.history}"
    assert g2.streak == 0, f"playing one game changed another's streak: {g2.streak}"
    g3 = app.Game(seed=2)
    assert len(g3.history) == 8


# ---------------------------------------------------------------- A34 – A39 (paths)

def test_A37_ends_after_fail_fail_success_success():
    g = ready(make(BASE))
    play(g, BAD, 100)
    play(g, BAD, 100)
    play(g, good(g), 100)
    assert g.level_over is False
    play(g, good(g), 100)
    assert g.level_over is True
    assert g.criteria.get("SC0x-01") is True
    assert isinstance(g.final_message, str) and g.final_message.strip()


def test_A36_success_fail_success_success_validates():
    g = ready(make(BASE))
    play(g, good(g), 100)
    play(g, BAD, 100)
    assert g.streak == 0
    play(g, good(g), 100)
    assert g.streak == 1
    play(g, good(g), 100)
    assert g.criteria.get("SC0x-01") is True


def test_A37_trou_no_order_after_level_end():
    g = ready(make(BASE))
    play(g, good(g), 100)
    play(g, good(g), 100)
    assert g.order_field_enabled is False
    with pytest.raises(app.FieldDisabledError):
        g.submit_order(100)
    assert len(g.history) == 10


def test_A38_long_failure_run_keeps_level_open():
    g = ready(make(BASE))
    for _ in range(100):
        play(g, BAD, 100)
    assert g.streak == 0 and g.level_over is False and g.final_message is None
    assert len(g.history) == 108 and len(g.table_rows()) == 108 and len(g.chart_bars()) == 108


# ---------------------------------------------------------------- A40

def test_A40_trou_page_contains_game_screen():
    low = app.page_html().lower()
    assert len(re.findall(r"<input", low)) >= 2, "page lacks forecast and order fields"
    assert "<table" in low, "page lacks the history table"
    assert "<script" in low, "page has no script: the game cannot run in the browser"


def test_A40_trou_page_declares_utf8():
    low = app.page_html().lower()
    assert re.search(r'<meta[^>]+charset=["\']?utf-8', low), "no utf-8 charset for French text"
