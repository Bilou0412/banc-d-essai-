"""Jeu de gestion de stock : module unique (couche code, tour 1)."""

import random
import re
from dataclasses import dataclass
from fractions import Fraction

CRITERION = "SC0x-01"
PRICE_SELL = 1.20
PRICE_BUY = 0.80
HISTORY_WEEKS = 8
WINDOW = 3
SUCCESS_MARGIN = Fraction(1, 100)
FORECAST_INPUT = re.compile(r"[0-9]+(?:[.,][0-9])?")

MENTOR_EXPLANATION = (
    "Le mentor : la moyenne mobile sur 3 semaines est la moyenne des "
    "3 dernières semaines de l'historique. Calcul : (s1 + s2 + s3) / 3."
)
SUCCESS_COMMENT = "Bien joué : ta prévision est dans la marge de 1 % de la moyenne mobile."
FINAL_MESSAGE = "Niveau terminé : tu as réussi 2 prévisions d'affilée. Critère SC0x-01 validé."

PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gestion de stock</title>
</head>
<body>
<h1>Gestion de stock</h1>
<table>
<thead><tr><th>Semaine</th><th>Unités</th></tr></thead>
<tbody></tbody>
</table>
<form>
<label>Prévision <input name="forecast" type="text" inputmode="decimal"></label>
<label>Commande <input name="order" type="number" min="0" step="1"></label>
</form>
<script>document.documentElement.lang = "fr";</script>
</body>
</html>
"""


class FieldDisabledError(Exception):
    """Un champ désactivé a été utilisé."""


@dataclass
class ForecastResult:
    accepted: bool
    success: bool | None = None
    moving_average: float | None = None
    comment: str | None = None


@dataclass
class WeekResult:
    demand: int
    sold: int
    missed: int
    wasted: int
    revenue: float
    cost: float
    profit: float


def _draw_units(rng, mean, std):
    return max(0, round(rng.gauss(mean, std)))


def _failure_comment(text, forecast, window, ma):
    a, b, c = window
    gap = abs(forecast - ma)
    return (
        f"Écart trop grand : ta prévision {text} s'écarte de {float(gap):.2f} "
        f"de la moyenne mobile, soit plus de 1 %. "
        f"Moyenne mobile = ({a} + {b} + {c}) / 3 = {float(ma):.2f}."
    )


class Game:
    def __init__(self, seed=None, history=None):
        self._rng = random.Random(seed)
        self.mean_demand = self._rng.uniform(60, 140)
        self.std_dev = self.mean_demand * self._rng.uniform(0.10, 0.20)
        drawn = [_draw_units(self._rng, self.mean_demand, self.std_dev)
                 for _ in range(HISTORY_WEEKS)]
        self.history = list(history) if history is not None else drawn
        self.streak = 0
        self.criteria = {CRITERION: False}
        self.level_over = False
        self.final_message = None
        self._screen_opened = False
        self._explanation = None
        self._forecast_done = False
        self._pending_success = None

    # ------------------------------------------------------------ screens

    def open_order_screen(self):
        if not self._screen_opened:
            self._screen_opened = True
            self._explanation = MENTOR_EXPLANATION

    @property
    def mentor_explanation(self):
        return self._explanation

    def dismiss_explanation(self):
        self._explanation = None

    @property
    def forecast_field_enabled(self):
        return (self._screen_opened
                and self._explanation is None
                and not self._forecast_done
                and not self.level_over)

    @property
    def order_field_enabled(self):
        return self._forecast_done and not self.level_over

    def table_rows(self):
        return [(i + 1, units) for i, units in enumerate(self.history)]

    def chart_bars(self):
        return [float(units) for units in self.history]

    # ------------------------------------------------------------ actions

    def submit_forecast(self, text):
        if not self.forecast_field_enabled:
            raise FieldDisabledError("forecast field is disabled")
        if FORECAST_INPUT.fullmatch(text) is None:
            return ForecastResult(accepted=False)

        forecast = Fraction(text.replace(",", "."))
        window = self.history[-WINDOW:]
        ma = Fraction(sum(window), WINDOW)
        success = abs(forecast - ma) <= ma * SUCCESS_MARGIN

        self._forecast_done = True
        self._pending_success = success
        comment = SUCCESS_COMMENT if success else _failure_comment(text, forecast, window, ma)
        return ForecastResult(accepted=True, success=success,
                              moving_average=float(ma), comment=comment)

    def submit_order(self, quantity):
        if not self.order_field_enabled:
            raise FieldDisabledError("order field is disabled")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError(f"order must be a whole number, got {quantity!r}")
        if quantity < 0:
            raise ValueError(f"order must not be negative, got {quantity}")

        demand = _draw_units(self._rng, self.mean_demand, self.std_dev)
        sold = min(demand, quantity)
        missed = demand - sold
        wasted = quantity - sold
        revenue = sold * PRICE_SELL
        cost = quantity * PRICE_BUY
        profit = revenue - cost

        self.history.append(demand)
        self._resolve_streak(self._pending_success)
        self._forecast_done = False
        self._pending_success = None

        return WeekResult(demand=demand, sold=sold, missed=missed, wasted=wasted,
                          revenue=revenue, cost=cost, profit=profit)

    def _resolve_streak(self, success):
        self.streak = self.streak + 1 if success else 0
        if self.streak >= 2:
            self.criteria[CRITERION] = True
            self.level_over = True
            self.final_message = FINAL_MESSAGE


def page_html():
    return PAGE
