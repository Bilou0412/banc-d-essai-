"""Jeu de gestion de stock : un seul module, sans réseau ni disque."""

import random
import re
from fractions import Fraction

INITIAL_WEEKS = 8
WINDOW = 3
PRICE_SALE = 1.20
PRICE_COST = 0.80
CRITERION = "SC0x-01"
TARGET_STREAK = 2
FORECAST_RE = re.compile(r"[0-9]+(?:[.,][0-9])?")

MENTOR_EXPLANATION = (
    "Avant de commander, prévois la demande avec la moyenne mobile sur 3 semaines : "
    "la moyenne des 3 dernières semaines de demande."
)
FINAL_MESSAGE = (
    "Niveau terminé : deux prévisions réussies d'affilée. "
    "Le mentor te félicite, tu peux passer à la suite."
)


class FieldDisabledError(Exception):
    """Le champ demandé est désactivé à cet instant."""


class ForecastResult:
    def __init__(self, accepted, success=None, moving_average=None, comment=None):
        self.accepted = accepted
        self.success = success
        self.moving_average = moving_average
        self.comment = comment


class WeekResult:
    def __init__(self, demand, sold, missed, wasted, revenue, cost, profit):
        self.demand = demand
        self.sold = sold
        self.missed = missed
        self.wasted = wasted
        self.revenue = revenue
        self.cost = cost
        self.profit = profit


class Game:
    def __init__(self, seed=None, history=None):
        self._rng = random.Random(seed)
        self.mean_demand = self._rng.uniform(60, 140)
        self.std_dev = self.mean_demand * self._rng.uniform(0.10, 0.20)
        drawn = [self._draw_demand() for _ in range(INITIAL_WEEKS)]
        self.history = list(history) if history is not None else drawn
        self.streak = 0
        self.criteria = {CRITERION: False}
        self.level_over = False
        self.final_message = None
        self._opened = False
        self._explanation_shown = False
        self._order_pending = False
        self._pending_success = None

    # ------------------------------------------------------------ state

    @property
    def mentor_explanation(self):
        return MENTOR_EXPLANATION if self._explanation_shown else None

    @property
    def forecast_field_enabled(self):
        return self._opened and not (
            self.level_over or self._explanation_shown or self._order_pending)

    @property
    def order_field_enabled(self):
        return self._order_pending and not self.level_over

    # ------------------------------------------------------------ screens

    def open_order_screen(self):
        if not self._opened:
            self._opened = True
            self._explanation_shown = True

    def dismiss_explanation(self):
        self._explanation_shown = False

    def table_rows(self):
        return [(week, units) for week, units in enumerate(self.history, start=1)]

    def chart_bars(self):
        return [float(units) for units in self.history]

    # ------------------------------------------------------------ actions

    def submit_forecast(self, text):
        if not self.forecast_field_enabled:
            raise FieldDisabledError("forecast field is disabled")
        cleaned = text.strip()
        if not FORECAST_RE.fullmatch(cleaned):
            return ForecastResult(accepted=False)
        # Arithmétique exacte : le seuil de 1 % ne doit pas dépendre des flottants.
        value = Fraction(cleaned.replace(",", "."))
        last = self.history[-WINDOW:]
        average = Fraction(sum(last), WINDOW)
        success = abs(value - average) * 100 <= average
        self._order_pending = True
        self._pending_success = success
        comment = self._comment(value, average, last, success)
        return ForecastResult(True, success, float(average), comment)

    def submit_order(self, quantity):
        if not self.order_field_enabled:
            raise FieldDisabledError("order field is disabled")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise ValueError(f"order must be a non-negative integer, got {quantity!r}")
        demand = self._draw_demand()
        sold = min(demand, quantity)
        missed = demand - sold
        wasted = quantity - sold
        revenue = sold * PRICE_SALE
        cost = quantity * PRICE_COST
        profit = revenue - cost
        self.history.append(demand)
        self._order_pending = False
        self._resolve_streak(self._pending_success)
        return WeekResult(demand, sold, missed, wasted, revenue, cost, profit)

    # ------------------------------------------------------------ helpers

    def _draw_demand(self):
        return max(0, round(self._rng.gauss(self.mean_demand, self.std_dev)))

    def _resolve_streak(self, success):
        self.streak = self.streak + 1 if success else 0
        if self.streak >= TARGET_STREAK:
            self.criteria[CRITERION] = True
            self.level_over = True
            self.final_message = FINAL_MESSAGE

    @staticmethod
    def _comment(value, average, last, success):
        gap = float(value - average)
        if success:
            return (f"Bien joué : ta prévision est dans la marge de 1 % "
                    f"de la moyenne mobile (écart {gap:+.2f}).")
        a, b, c = last
        return (f"Écart de {gap:+.2f} : ta prévision s'éloigne de plus de 1 % "
                f"de la moyenne mobile. Moyenne mobile sur 3 semaines : "
                f"({a} + {b} + {c}) / 3 = {float(average):.2f}.")


def page_html():
    return """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gestion de stock</title>
</head>
<body>
<h1>Gestion de stock</h1>
<table id="history">
<thead><tr><th>Semaine</th><th>Unités vendues</th></tr></thead>
<tbody></tbody>
</table>
<label>Prévision <input id="forecast" type="text" inputmode="decimal"></label>
<label>Commande <input id="order" type="number" min="0" step="1"></label>
<script>
document.getElementById("order").disabled = true;
</script>
</body>
</html>
"""
