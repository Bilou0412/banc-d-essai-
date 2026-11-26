"""Jeu de gestion de stock — module `app` (couche code, tour 1)."""

import random
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

PRICE_SALE = 1.20
PRICE_COST = 0.80
CRITERION = "SC0x-01"
STREAK_TO_END = 2

MENTOR_EXPLANATION = (
    "Le mentor : la moyenne mobile sur 3 semaines est la moyenne des 3 "
    "dernières semaines de l'historique. Ta prévision doit s'en approcher à 1 % près."
)
FINAL_MESSAGE = (
    "Niveau terminé : deux succès d'affilée. Le critère SC0x-01 est validé."
)

# Une prévision : 0 à 1 décimale, avec un point ou une virgule. Rien d'autre.
FORECAST_RE = re.compile(r"[0-9]+(?:[.,][0-9])?")


class FieldDisabledError(Exception):
    """Le champ demandé est désactivé à cet instant."""


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


class Game:
    def __init__(self, seed=None, history=None):
        self._rng = random.Random(seed)
        self.mean_demand = self._rng.uniform(60, 140)
        self.std_dev = self.mean_demand * self._rng.uniform(0.10, 0.20)
        if history is None:
            history = [self._draw_demand() for _ in range(8)]
        self.history = [int(u) for u in history]

        self.mentor_explanation = None
        self._screen_open = False
        self._explained = False
        self._pending = None  # succès (bool) de la prévision acceptée de la semaine
        self.streak = 0
        self.criteria = {CRITERION: False}
        self.level_over = False
        self.final_message = None

    # ------------------------------------------------------------ draws

    def _draw_demand(self):
        return max(0, round(self._rng.gauss(self.mean_demand, self.std_dev)))

    # ------------------------------------------------------------ fields

    @property
    def forecast_field_enabled(self):
        return (
            self._screen_open
            and self.mentor_explanation is None
            and self._pending is None
            and not self.level_over
        )

    @property
    def order_field_enabled(self):
        return self._pending is not None and not self.level_over

    # ------------------------------------------------------------ screens

    def open_order_screen(self):
        self._screen_open = True
        if not self._explained:
            self._explained = True
            self.mentor_explanation = MENTOR_EXPLANATION

    def dismiss_explanation(self):
        self.mentor_explanation = None

    def table_rows(self):
        return [(week, units) for week, units in enumerate(self.history, start=1)]

    def chart_bars(self):
        return [float(units) for units in self.history]

    # ------------------------------------------------------------ actions

    def submit_forecast(self, text):
        if not self.forecast_field_enabled:
            raise FieldDisabledError("champ de prévision désactivé")
        if not FORECAST_RE.fullmatch(text):
            return ForecastResult(accepted=False)

        value = Fraction(Decimal(text.replace(",", ".")))
        ma = Fraction(sum(self.history[-3:]), 3)
        gap = value - ma
        success = abs(gap) <= abs(ma) / 100
        self._pending = success
        return ForecastResult(
            accepted=True,
            success=success,
            moving_average=float(ma),
            comment=self._comment(text, ma, gap, success),
        )

    def submit_order(self, quantity):
        if not self.order_field_enabled:
            raise FieldDisabledError("champ de commande désactivé")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise ValueError(f"commande invalide : {quantity!r}")

        demand = self._draw_demand()
        sold = min(demand, quantity)
        missed = demand - sold
        wasted = quantity - sold
        revenue = sold * PRICE_SALE
        cost = quantity * PRICE_COST
        profit = revenue - cost

        success = self._pending
        self._pending = None
        self.history.append(demand)

        self.streak = self.streak + 1 if success else 0
        if self.streak == STREAK_TO_END:
            self.criteria[CRITERION] = True
            self.level_over = True
            self.final_message = FINAL_MESSAGE

        return WeekResult(
            demand=demand,
            sold=sold,
            missed=missed,
            wasted=wasted,
            revenue=revenue,
            cost=cost,
            profit=profit,
        )

    # ------------------------------------------------------------ comments

    def _comment(self, text, ma, gap, success):
        if success:
            return (
                f"Bien vu : ta prévision {text} est dans la tolérance de 1 % "
                f"de la moyenne mobile."
            )
        side = "au-dessus" if gap > 0 else "en dessous"
        a, b, c = self.history[-3:]
        total = a + b + c
        return (
            f"Ta prévision {text} est {side} de la moyenne mobile de "
            f"{float(abs(gap)):.2f} unités, au-delà de la tolérance de 1 %. "
            f"Moyenne mobile : {a} + {b} + {c} = {total}, "
            f"soit {total} / 3 = {float(ma):.2f}."
        )


PAGE_HTML = """<!DOCTYPE html>
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
<div id="chart"></div>
<label>Prévision <input id="forecast" type="text" inputmode="decimal"></label>
<label>Commande <input id="order" type="number" min="0" step="1"></label>
<script>
// Branchement sur le moteur : tour suivant.
</script>
</body>
</html>
"""


def page_html():
    return PAGE_HTML
