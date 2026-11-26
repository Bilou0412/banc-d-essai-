"""Jeu de prévision par moyenne mobile sur 3 semaines."""

import random
import re
from dataclasses import dataclass
from fractions import Fraction


class FieldDisabledError(Exception):
    pass


@dataclass
class ForecastResult:
    accepted: bool
    success: "bool | None" = None
    moving_average: "float | None" = None
    comment: "str | None" = None


@dataclass
class WeekResult:
    demand: int
    sold: int
    missed: int
    wasted: int
    revenue: float
    cost: float
    profit: float


_FORECAST_RE = re.compile(r"^\d+(?:[.,]\d)?$")

EXPLANATION = (
    "Le mentor explique : la moyenne mobile sur 3 semaines est la moyenne "
    "des ventes des 3 dernières semaines. Utilise-la pour prévoir la semaine suivante."
)


class Game:
    def __init__(self, seed=None, history=None):
        self._rng = random.Random(seed)
        self.mean_demand = self._rng.uniform(60, 140)
        self.std_dev = self.mean_demand * self._rng.uniform(0.10, 0.20)
        drawn = [self._draw() for _ in range(8)]
        self.history = list(history) if history is not None else drawn
        self.mentor_explanation = None
        self._explained = False
        self._opened = False
        self._forecast_done = False
        self._forecast_success = False
        self.streak = 0
        self.criteria = {"SC0x-01": False}
        self.level_over = False
        self.final_message = None

    def _draw(self):
        return max(0, int(round(self._rng.gauss(self.mean_demand, self.std_dev))))

    # --- screen
    def open_order_screen(self):
        self._opened = True
        if not self._explained:
            self._explained = True
            self.mentor_explanation = EXPLANATION

    def dismiss_explanation(self):
        self.mentor_explanation = None

    @property
    def forecast_field_enabled(self):
        return (self._opened and self.mentor_explanation is None
                and not self._forecast_done and not self.level_over)

    @property
    def order_field_enabled(self):
        return self._forecast_done and not self.level_over

    def table_rows(self):
        return [(i + 1, u) for i, u in enumerate(self.history)]

    def chart_bars(self):
        top = max(self.history) if self.history else 0
        if top <= 0:
            return [0.0 for _ in self.history]
        return [u / top for u in self.history]

    # --- forecast
    def submit_forecast(self, text):
        if not self.forecast_field_enabled:
            raise FieldDisabledError("champ de prévision désactivé")
        if not isinstance(text, str) or not _FORECAST_RE.match(text.strip()):
            return ForecastResult(accepted=False)
        value = Fraction(text.strip().replace(",", "."))
        last = self.history[-3:]
        ma = Fraction(sum(last), 3)
        success = abs(value - ma) * 100 <= ma
        self._forecast_done = True
        self._forecast_success = success
        ma_f = float(ma)
        gap = float(value - ma)
        if success:
            comment = (f"Bravo : ta prévision {float(value):.1f} est proche de la "
                       f"moyenne mobile {ma_f:.2f} (écart {gap:+.2f}).")
        else:
            a, b, c = last
            sens = "trop haute" if gap > 0 else "trop basse"
            comment = (f"Ta prévision {float(value):.1f} est {sens} : écart {gap:+.2f} "
                       f"avec la moyenne mobile. Calcul : ({a} + {b} + {c}) / 3 = {ma_f:.2f}.")
        return ForecastResult(True, success, ma_f, comment)

    # --- order
    def submit_order(self, quantity):
        if not self.order_field_enabled:
            raise FieldDisabledError("champ de commande désactivé")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("la commande doit être un entier")
        if quantity < 0:
            raise ValueError("la commande ne peut pas être négative")
        demand = self._draw()
        sold = min(demand, quantity)
        revenue = sold * 1.20
        cost = quantity * 0.80
        result = WeekResult(demand, sold, demand - sold, quantity - sold,
                            revenue, cost, revenue - cost)
        self.history.append(demand)
        self._forecast_done = False
        if self._forecast_success:
            self.streak += 1
        else:
            self.streak = 0
        if self.streak >= 2:
            self.criteria["SC0x-01"] = True
            self.level_over = True
            self.final_message = ("Bravo, niveau terminé : tu maîtrises la "
                                  "moyenne mobile sur 3 semaines !")
        return result


def page_html():
    return """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prévision par moyenne mobile</title>
</head>
<body>
<h1>Prévision par moyenne mobile</h1>
<p id="mentor"></p>
<table id="history"><thead><tr><th>Semaine</th><th>Unités</th></tr></thead><tbody></tbody></table>
<div id="chart"></div>
<label>Prévision <input id="forecast" type="text" inputmode="decimal"></label>
<label>Commande <input id="order" type="number" min="0" step="1" disabled></label>
<script>
var h = [90, 95, 100, 105, 110, 98, 102, 99];
var body = document.querySelector("#history tbody");
h.forEach(function (u, i) {
  var r = body.insertRow();
  r.insertCell().textContent = i + 1;
  r.insertCell().textContent = u;
});
</script>
</body>
</html>
"""
