"""Jeu de prévision de commande — code du tour 1.

Interface figée par tests/test_app.py : Refused, Game, WebServer.
"""

import random
import re
from dataclasses import dataclass
from fractions import Fraction

WEEKS_INITIAL = 8
PRICE = 1.20
UNIT_COST = 0.80
TOLERANCE = Fraction(1, 100)
CRITERION = "SC0x-01"
STREAK_TO_FINISH = 2

MENTOR_EXPLANATION = (
    "Le mentor : ta prévision doit suivre la moyenne mobile sur 3 semaines, "
    "c'est-à-dire la moyenne des 3 dernières semaines de l'historique."
)
FINAL_MESSAGE = (
    "Niveau terminé : tu as réussi deux prévisions d'affilée. "
    "Tu sais maintenant utiliser la moyenne mobile."
)

# Une décimale au plus : "100", "100.5", "100,5" acceptées ; "100.55" refusée.
_FORECAST_RE = re.compile(r"\d+(?:[.,]\d)?")


class Refused(Exception):
    """Action du joueur refusée, sans effet sur l'état du jeu."""


@dataclass(frozen=True)
class ForecastResult:
    success: bool
    moving_average: float
    comment: str


@dataclass(frozen=True)
class WeekResult:
    week: int
    demand: int
    sales: int
    missed: int
    wasted: int
    revenue: float
    cost: float
    profit: float


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    body: str


def _fmt(x):
    """Affichage minimal : deux décimales au plus, zéros de fin retirés."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _comment(success, deviation, ma, last3):
    ecart = _fmt(float(deviation))
    moyenne = _fmt(float(ma))
    if success:
        return f"Écart de {ecart} à la moyenne mobile ({moyenne}) : succès."
    a, b, c = (str(u) for u in last3)
    return (
        f"Écart de {ecart} à la moyenne mobile ({moyenne}) : échec. "
        f"Moyenne mobile sur les 3 dernières semaines : "
        f"({a} + {b} + {c}) / 3 = {moyenne}."
    )


class Game:
    def __init__(self, seed=None, history=None):
        self._rng = random.Random(seed)
        self._mean = self._rng.uniform(60, 140)
        self._std = self._mean * self._rng.uniform(0.10, 0.20)
        if history is None:
            history = [
                max(0, round(self._rng.gauss(self._mean, self._std)))
                for _ in range(WEEKS_INITIAL)
            ]
        self._history = list(history)

        self._screen_open = False
        self._explained = False
        self._explanation = None
        self._forecast_pending = False
        self._streak = 0
        self._criteria = {CRITERION: False}
        self._level_finished = False
        self._final_message = None

    # ------------------------------------------------------------ état

    @property
    def history(self):
        return list(self._history)

    @property
    def mean_demand(self):
        return self._mean

    @property
    def std_dev(self):
        return self._std

    @property
    def mentor_explanation(self):
        return self._explanation

    @property
    def forecast_field_enabled(self):
        return (
            self._screen_open
            and self._explanation is None
            and not self._forecast_pending
            and not self._level_finished
        )

    @property
    def order_field_enabled(self):
        return self._forecast_pending and not self._level_finished

    @property
    def streak(self):
        return self._streak

    @property
    def criteria(self):
        return dict(self._criteria)

    @property
    def level_finished(self):
        return self._level_finished

    @property
    def final_message(self):
        return self._final_message

    # ------------------------------------------------------------ écran

    def open_order_screen(self):
        self._screen_open = True
        if not self._explained:
            self._explained = True
            self._explanation = MENTOR_EXPLANATION

    def dismiss_mentor_explanation(self):
        self._explanation = None

    def table(self):
        return [(i + 1, u) for i, u in enumerate(self._history)]

    def chart(self):
        return [float(u) for u in self._history]

    # ------------------------------------------------------------ actions

    def _moving_average(self):
        last = self._history[-3:]
        return Fraction(sum(last), len(last))

    def submit_forecast(self, text):
        if not self.forecast_field_enabled:
            raise Refused("champ de prévision désactivé")
        clean = text.strip()
        if not _FORECAST_RE.fullmatch(clean):
            raise Refused(f"prévision invalide : {text!r}")

        forecast = Fraction(clean.replace(",", "."))
        ma = self._moving_average()
        deviation = abs(forecast - ma)
        success = deviation <= ma * TOLERANCE

        self._forecast_pending = True
        self._streak = self._streak + 1 if success else 0
        return ForecastResult(
            success=success,
            moving_average=float(ma),
            comment=_comment(success, deviation, ma, self._history[-3:]),
        )

    def submit_order(self, quantity):
        if not self.order_field_enabled:
            raise Refused("champ de commande désactivé")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise Refused(f"commande invalide : {quantity!r}")

        week = len(self._history) + 1
        demand = max(0, round(self._rng.gauss(self._mean, self._std)))
        sales = min(demand, quantity)
        missed = demand - sales
        wasted = quantity - sales
        revenue = round(sales * PRICE, 2)
        cost = round(quantity * UNIT_COST, 2)
        profit = round(revenue - cost, 2)

        self._history.append(demand)
        self._forecast_pending = False
        if self._streak >= STREAK_TO_FINISH:
            self._criteria[CRITERION] = True
            self._level_finished = True
            self._final_message = FINAL_MESSAGE

        return WeekResult(
            week=week,
            demand=demand,
            sales=sales,
            missed=missed,
            wasted=wasted,
            revenue=revenue,
            cost=cost,
            profit=profit,
        )


_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jeu de prévision</title>
</head>
<body>
<h1>Jeu de prévision</h1>
<form id="order-screen">
<label>Prévision <input type="text" name="forecast" inputmode="decimal"></label>
</form>
</body>
</html>
"""


class WebServer:
    def get(self, path, headers):
        if path == "/":
            return Response(200, {"Content-Type": "text/html; charset=utf-8"}, _PAGE)
        return Response(404, {"Content-Type": "text/plain; charset=utf-8"}, "Not found")
