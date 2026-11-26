import random
import re
from dataclasses import dataclass
from fractions import Fraction


class FieldDisabledError(Exception):
    pass


@dataclass
class ForecastResult:
    accepted: bool
    success: object = None
    moving_average: object = None
    comment: object = None


@dataclass
class WeekResult:
    demand: int
    sold: int
    missed: int
    wasted: int
    revenue: float
    cost: float
    profit: float


_FORECAST_RE = re.compile(r"\d+(?:[.,]\d)?")

EXPLANATION = (
    "Mentor : la moyenne mobile sur 3 semaines est la moyenne des ventes "
    "des 3 dernières semaines. Utilise-la pour faire ta prévision."
)


class Game:
    def __init__(self, seed=None, history=None):
        self._rng = random.Random(seed)
        self.mean_demand = self._rng.uniform(60, 140)
        self.std_dev = self.mean_demand * self._rng.uniform(0.10, 0.20)
        drawn = [self._draw() for _ in range(8)]
        self.history = list(history) if history is not None else drawn
        self.streak = 0
        self.criteria = {"SC0x-01": False}
        self.level_over = False
        self.final_message = None
        self.mentor_explanation = None
        self._opened = False
        self._screen_ready = False
        self._forecast_done = False
        self._success = None

    def _draw(self):
        return max(0, int(round(self._rng.gauss(self.mean_demand, self.std_dev))))

    # --- screen
    def open_order_screen(self):
        if not self._opened:
            self._opened = True
            self.mentor_explanation = EXPLANATION
        # explanation stays displayed until dismissed

    def dismiss_explanation(self):
        self.mentor_explanation = None
        if self._opened:
            self._screen_ready = True

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
        top = max(max(self.history, default=0), 1)
        return [100.0 * u / top for u in self.history]

    # --- forecast
    def submit_forecast(self, text):
        if not self.forecast_field_enabled:
            raise FieldDisabledError("forecast field disabled")
        s = text.strip() if isinstance(text, str) else ""
        if not _FORECAST_RE.fullmatch(s):
            return ForecastResult(False)
        value = Fraction(s.replace(",", "."))
        last = self.history[-3:]
        total = sum(last)
        ma = Fraction(total, 3)
        gap = abs(value - ma)
        success = gap <= ma / 100
        ma_f = float(ma)
        if success:
            comment = (f"Bravo ! Ta prévision {s} est proche de la moyenne mobile "
                       f"{ma_f:.2f} (écart {float(gap):.2f}).")
        else:
            nums = " + ".join(str(n) for n in last)
            comment = (f"Ta prévision {s} s'écarte de la moyenne mobile de "
                       f"{float(gap):.2f}. La moyenne mobile vaut {ma_f:.2f} : "
                       f"({nums}) / 3 = {ma_f:.2f}.")
        self._forecast_done = True
        self._success = success
        return ForecastResult(True, success, ma_f, comment)

    # --- order
    def submit_order(self, quantity):
        if not self.order_field_enabled:
            raise FieldDisabledError("order field disabled")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("order must be an integer")
        if quantity < 0:
            raise ValueError("order must not be negative")
        demand = self._draw()
        sold = min(demand, quantity)
        revenue = sold * 1.20
        cost = quantity * 0.80
        result = WeekResult(demand, sold, demand - sold, quantity - sold,
                            revenue, cost, revenue - cost)
        self.history.append(demand)
        if self._success:
            self.streak += 1
        else:
            self.streak = 0
        self._forecast_done = False
        self._success = None
        if self.streak >= 2:
            self.criteria["SC0x-01"] = True
            self.level_over = True
            self.final_message = ("Mentor : niveau terminé ! Tu sais maintenant "
                                  "calculer la moyenne mobile sur 3 semaines.")
        return result


def page_html():
    return """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prévision de la demande</title>
</head>
<body>
<h1>Prévision de la demande</h1>
<p id="mentor"></p>
<label>Prévision <input id="forecast" type="text" inputmode="decimal"></label>
<button id="fbtn">Valider la prévision</button>
<label>Commande <input id="order" type="number" min="0" step="1" disabled></label>
<button id="obtn">Commander</button>
<table id="history"><thead><tr><th>Semaine</th><th>Unités</th></tr></thead><tbody></tbody></table>
<div id="chart"></div>
<script>
(function () {
  var hist = [], mean = 60 + Math.random() * 80, sd = mean * (0.1 + Math.random() * 0.1);
  function gauss() { var u = 1 - Math.random(), v = Math.random();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
  function draw() { return Math.max(0, Math.round(mean + sd * gauss())); }
  for (var i = 0; i < 8; i++) hist.push(draw());
  var streak = 0, success = false;
  function render() {
    var tb = document.querySelector("#history tbody"), ch = document.getElementById("chart");
    var top = Math.max.apply(null, hist.concat([1]));
    tb.innerHTML = ""; ch.innerHTML = "";
    hist.forEach(function (u, i) {
      tb.innerHTML += "<tr><td>" + (i + 1) + "</td><td>" + u + "</td></tr>";
      ch.innerHTML += '<div style="display:inline-block;width:8px;background:#36c;height:' + (100 * u / top) + 'px"></div>';
    });
  }
  document.getElementById("mentor").textContent =
    "Mentor : la moyenne mobile sur 3 semaines est la moyenne des 3 dernières semaines.";
  document.getElementById("fbtn").onclick = function () {
    var s = document.getElementById("forecast").value.trim();
    if (!/^\\d+([.,]\\d)?$/.test(s)) return;
    var v = parseFloat(s.replace(",", "."));
    var l = hist.slice(-3), ma = (l[0] + l[1] + l[2]) / 3;
    success = Math.abs(v - ma) <= ma / 100 + 1e-9;
    document.getElementById("mentor").textContent = success ? "Bravo !" :
      "Moyenne mobile : (" + l.join(" + ") + ") / 3 = " + ma.toFixed(2);
    document.getElementById("order").disabled = false;
  };
  document.getElementById("obtn").onclick = function () {
    var q = parseInt(document.getElementById("order").value, 10);
    if (isNaN(q) || q < 0) return;
    hist.push(draw());
    streak = success ? streak + 1 : 0;
    document.getElementById("order").disabled = true;
    if (streak >= 2) document.getElementById("mentor").textContent = "Niveau terminé !";
    render();
  };
  render();
})();
</script>
</body>
</html>
"""
