"""Générateur de situations — jeu de prévision (moyenne mobile sur 3 semaines)."""

import re
from decimal import Decimal, InvalidOperation

REFUSE = "refusé"


def _num(x, nd=4):
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            return str(x)
        return round(x, nd)
    try:
        return round(float(x), nd)
    except Exception:
        return str(x)


def _get(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return REFUSE


def _ints(seq):
    try:
        return [_num(v) for v in list(seq)]
    except Exception:
        return REFUSE


def _state(game):
    """Ce que l'écran montre après chaque action."""
    if game is None:
        return {"partie": None}
    st = {}
    st["historique"] = _ints(_get(game, "history")) if _get(game, "history") != REFUSE else REFUSE
    expl = _get(game, "mentor_explanation")
    st["explication_affichee"] = expl if expl == REFUSE else (expl is not None)
    if isinstance(expl, str):
        low = expl.lower()
        st["explication_parle_moyenne_mobile"] = "moyenne mobile" in low
        st["explication_parle_3"] = "3" in expl
    for key, attr in (("champ_prevision_actif", "forecast_field_enabled"),
                      ("champ_commande_actif", "order_field_enabled"),
                      ("serie", "streak"),
                      ("niveau_termine", "level_over")):
        v = _get(game, attr)
        st[key] = v if isinstance(v, (bool, int, str)) or v is None else str(v)
    crit = _get(game, "criteria")
    if isinstance(crit, dict):
        st["critere_SC0x-01"] = bool(crit.get("SC0x-01", False))
    else:
        st["critere_SC0x-01"] = REFUSE
    fm = _get(game, "final_message")
    st["message_final_affiche"] = fm if fm == REFUSE else (isinstance(fm, str) and bool(fm.strip()))
    return st


def _history(game):
    try:
        return list(game.history)
    except Exception:
        return []


def _ma(history):
    if len(history) < 3:
        return None
    return sum(history[-3:]) / 3


def _ma_strings(ma):
    c = {f"{ma:.2f}", f"{ma:.1f}"}
    c |= {s.replace(".", ",") for s in c}
    if abs(ma - round(ma)) < 1e-9:
        c.add(str(int(round(ma))))
    return c


def _comment_view(comment, last3):
    if comment is None:
        return None
    if not isinstance(comment, str):
        return str(type(comment).__name__)
    view = {"present": bool(comment.strip())}
    if len(last3) == 3:
        a, b, c = last3
        ma = (a + b + c) / 3
        view["montre_moyenne"] = any(s in comment for s in _ma_strings(ma))
        view["montre_3_nombres"] = all(
            re.search(rf"(?<!\d){n}(?!\d)", comment) for n in (a, b, c))
        view["montre_calcul"] = bool(
            re.search(rf"(?<!\d){a}\s*\+\s*{b}\s*\+\s*{c}(?!\d)", comment)
            and re.search(r"[/÷]\s*3(?!\d)", comment))
    return view


def _forecast_text(rng, game):
    hist = _history(game)
    ma = _ma(hist)
    kind = rng.choice(["bon", "bon", "bon", "bon_virgule", "limite_haut", "limite_bas",
                       "juste_au_dela", "entier", "mauvais", "deux_decimales",
                       "malforme", "zero"])
    if ma is None:
        ma = 100.0
    if kind == "bon":
        return f"{ma:.1f}"
    if kind == "bon_virgule":
        return f"{ma:.1f}".replace(".", ",")
    if kind in ("limite_haut", "limite_bas", "juste_au_dela"):
        try:
            m = Decimal(sum(hist[-3:])) / Decimal(3) if len(hist) >= 3 else Decimal(100)
            factor = Decimal("1.01") if kind != "limite_bas" else Decimal("0.99")
            v = (m * factor).quantize(Decimal("0.1"))
            if kind == "juste_au_dela":
                v = v + Decimal("0.2")
            return str(v)
        except (InvalidOperation, Exception):
            return "101.0"
    if kind == "entier":
        return str(int(round(ma)) + rng.choice([-3, -1, 0, 0, 1, 3]))
    if kind == "mauvais":
        return rng.choice(["100000", "0", f"{ma * 1.5:.1f}", f"{ma * 0.5:.1f}"])
    if kind == "deux_decimales":
        return rng.choice([f"{ma:.2f}", f"{ma:.2f}".replace(".", ","), "100.25", "99.90"])
    if kind == "malforme":
        return rng.choice(["", "   ", "abc", "nan", "inf", "1..0", "10.0.0", "100,3,3",
                           "100.333", "-5"])
    return "0"


def _order_qty(rng, game):
    hist = _history(game)
    ma = _ma(hist) or 100
    kind = rng.choice(["proche", "proche", "proche", "zero", "gros", "neg", "frac", "petit"])
    if kind == "proche":
        return int(round(ma)) + rng.randint(-20, 20)
    if kind == "zero":
        return 0
    if kind == "gros":
        return rng.choice([500, 10_000])
    if kind == "neg":
        return rng.choice([-1, -5])
    if kind == "frac":
        return 10.5
    return rng.randint(1, 30)


def _new_game(app, rng):
    seed = rng.randint(0, 10_000)
    mode = rng.choice(["tire", "tire", "constant", "fixe", "zeros"])
    hist = None
    if mode == "constant":
        hist = [rng.choice([10, 50, 100, 150, 200])] * 8
    elif mode == "fixe":
        hist = rng.choice([[90, 95, 100, 105, 110, 98, 102, 99],
                           [90, 95, 100, 105, 110, 100, 101, 101],
                           [10, 20, 30, 40, 50, 87, 93, 104],
                           [10, 20, 30, 40, 50, 100, 100, 100],
                           [10, 20, 30, 40, 50, 0, 0, 5]])
    elif mode == "zeros":
        hist = [0] * 7 + [rng.choice([0, 5])]
    if hist is None:
        label = f"new_game(seed={seed})"
    else:
        label = f"new_game(seed={seed}, history={hist})"
    try:
        game = app.Game(seed=seed, history=list(hist) if hist is not None else None)
    except Exception:
        return label, None, REFUSE
    return label, game, None


def scenario(app, rng, dossier):
    out = []
    game = None

    def record(action, extra, g):
        try:
            obs = {"ecran": _state(g)}
            if extra is not None:
                obs["resultat"] = extra
        except Exception:
            obs = REFUSE
        out.append((action, obs))

    # première action : toujours une nouvelle partie
    label, game, err = _new_game(app, rng)
    if err:
        out.append((label, REFUSE))
    else:
        record(label, {"nb_semaines": len(_history(game))}, game)

    n = rng.randint(15, 40)
    while len(out) < n:
        if game is None:
            label, game, err = _new_game(app, rng)
            if err:
                out.append((label, REFUSE))
            else:
                record(label, {"nb_semaines": len(_history(game))}, game)
            continue

        # choix pondéré selon l'état
        try:
            expl = game.mentor_explanation
        except Exception:
            expl = None
        try:
            order_on = bool(game.order_field_enabled)
        except Exception:
            order_on = False
        weights = [
            ("open_order_screen", 3),
            ("dismiss_explanation", 6 if expl is not None else 1),
            ("submit_forecast", 2 if order_on else 10),
            ("submit_order", 10 if order_on else 1),
            ("table_rows", 1),
            ("chart_bars", 1),
            ("page_html", 1 if rng.random() < 0.3 else 0),
            ("new_game", 1 if rng.random() < 0.15 else 0),
        ]
        total = sum(w for _, w in weights)
        r = rng.uniform(0, total)
        acc = 0
        choice = weights[0][0]
        for name, w in weights:
            acc += w
            if r <= acc and w > 0:
                choice = name
                break

        if choice == "new_game":
            label, g2, err = _new_game(app, rng)
            if err:
                out.append((label, REFUSE))
            else:
                game = g2
                record(label, {"nb_semaines": len(_history(game))}, game)

        elif choice == "open_order_screen":
            try:
                game.open_order_screen()
                record("open_order_screen()", None, game)
            except Exception:
                out.append(("open_order_screen()", REFUSE))

        elif choice == "dismiss_explanation":
            try:
                game.dismiss_explanation()
                record("dismiss_explanation()", None, game)
            except Exception:
                out.append(("dismiss_explanation()", REFUSE))

        elif choice == "submit_forecast":
            text = _forecast_text(rng, game)
            last3 = _history(game)[-3:]
            action = f"submit_forecast({text!r})"
            try:
                res = game.submit_forecast(text)
            except Exception:
                out.append((action, REFUSE))
                continue
            try:
                extra = {
                    "acceptee": _get(res, "accepted"),
                    "succes": _get(res, "success"),
                    "moyenne_mobile": _num(_get(res, "moving_average")),
                    "commentaire": _comment_view(_get(res, "comment"), last3),
                }
            except Exception:
                extra = REFUSE
            record(action, extra, game)

        elif choice == "submit_order":
            q = _order_qty(rng, game)
            action = f"submit_order({q!r})"
            try:
                w = game.submit_order(q)
            except Exception:
                out.append((action, REFUSE))
                continue
            try:
                extra = {
                    "demande": _num(_get(w, "demand")),
                    "vendu": _num(_get(w, "sold")),
                    "manque": _num(_get(w, "missed")),
                    "jete": _num(_get(w, "wasted")),
                    "recette": _num(_get(w, "revenue"), 2),
                    "cout": _num(_get(w, "cost"), 2),
                    "benefice": _num(_get(w, "profit"), 2),
                }
            except Exception:
                extra = REFUSE
            record(action, extra, game)

        elif choice == "table_rows":
            try:
                rows = [[_num(a), _num(b)] for a, b in game.table_rows()]
                record("table_rows()", {"lignes": rows}, game)
            except Exception:
                out.append(("table_rows()", REFUSE))

        elif choice == "chart_bars":
            try:
                bars = [float(h) for h in game.chart_bars()]
                top = max(bars) if bars else 0.0
                rel = [round(h / top, 4) if top > 0 else round(h, 4) for h in bars]
                record("chart_bars()", {"nb_barres": len(bars), "hauteurs_relatives": rel}, game)
            except Exception:
                out.append(("chart_bars()", REFUSE))

        elif choice == "page_html":
            try:
                html = app.page_html()
                low = html.lower() if isinstance(html, str) else ""
                view = {
                    "est_html": "<!doctype html" in low and "<html" in low,
                    "viewport_mobile": bool(re.search(r'<meta[^>]+name=["\']viewport["\']', low)),
                    "utf8": bool(re.search(r'<meta[^>]+charset=["\']?utf-8', low)),
                    "ressource_externe": bool(re.search(r'(src|href)=["\']https?://', low)),
                    "a_script": "<script" in low,
                    "a_tableau": "<table" in low,
                    "nb_champs": len(re.findall(r"<input", low)),
                }
                record("page_html()", view, game)
            except Exception:
                out.append(("page_html()", REFUSE))

    return out[:40]
