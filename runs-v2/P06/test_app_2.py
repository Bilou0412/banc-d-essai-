"""Tests rouges, deuxième attaque — sonde P06.

Même interface publique que tests/test_app.py (module `app`).
Axes : rattrapage du temps en un seul saut, frontières calendaires (pas de
fenêtre glissante de 24 h), interactions durée/session/tâche, persistance
réelle (fichiers échangés, processus interrompu, noms de tâche hostiles,
volume), et cas non tranchés (préfixe `trou`, listés dans lacunes2.md).
"""

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app

ROOT = Path(__file__).resolve().parent.parent
T0 = dt.datetime(2026, 11, 19, 9, 0, 0)
DAY = 86400
D1 = dt.date(2026, 11, 19)
D2 = dt.date(2026, 11, 20)
D3 = dt.date(2026, 11, 21)


# --------------------------------------------------------------------------- helpers

def make(tmp_path, name="data.json", start=T0):
    clock = app.Clock(start)
    a = app.PomodoroApp(str(tmp_path / name), clock)
    return a, clock


def configure(a, work=1, short=1, long=2, interval=4, auto=False):
    a.set_work_duration(work)
    a.set_short_break(short)
    a.set_long_break(long)
    a.set_long_interval(interval)
    a.set_auto_start(auto)


def run_out(a, clock):
    if a.status == "arrêté":
        a.start()
    assert a.status == "en cours", f"attendu 'en cours' avant écoulement, obtenu {a.status!r}"
    clock.advance(a.remaining)


def complete_work(a, clock):
    assert a.phase == "travail", f"attendu phase 'travail', obtenu {a.phase!r}"
    run_out(a, clock)


def complete_break(a, clock):
    assert a.phase in ("pause courte", "pause longue"), f"attendu une pause, obtenu {a.phase!r}"
    run_out(a, clock)


def advance_to(clock, target):
    clock.advance(int((target - clock.now()).total_seconds()))


def norm(history):
    return [[s["task"], str(s["date"]), s["minutes"]] for s in history]


def snapshot(a):
    return (a.phase, a.status, a.remaining, a.cycles, norm(a.history))


# --------------------------------------------------------------------------- rattrapage en un seul saut

def test_A22_rattrapage_un_saut_traverse_fin_de_travail(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=1, auto=True)
    a.start()
    clock.advance(90)
    got = (a.phase, a.status, a.remaining, a.cycles, len(a.history))
    assert got == ("pause courte", "en cours", 30, 1, 1), (
        "un saut de 90 s (travail 60 s, auto) : attendu "
        f"('pause courte','en cours',30,1,1), obtenu {got}")


def test_A21_rattrapage_un_saut_sans_auto_s_arrete_a_zero(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=1, auto=False)
    a.start()
    clock.advance(1000)
    got = (a.phase, a.status, a.remaining, a.cycles, len(a.history))
    assert got == ("pause courte", "arrêté", 60, 1, 1), (
        "sans auto, un saut de 1000 s ne doit compter qu'une fin de travail : attendu "
        f"('pause courte','arrêté',60,1,1), obtenu {got}")


def test_A22_fin_de_pause_auto_relance_le_travail(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2, short=1, auto=True)
    a.start()
    clock.advance(181)
    got = (a.phase, a.status, a.remaining, a.cycles, len(a.history))
    assert got == ("travail", "en cours", 119, 1, 1), (
        f"attendu ('travail','en cours',119,1,1), obtenu {got}")


def test_A14_rattrapage_deux_cents_sessions_auto(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=1, long=2, interval=4, auto=True)
    a.start()
    clock.advance(27000)  # 50 groupes de (4 travail + 3 courtes + 1 longue) = 50 * 540 s
    assert a.cycles == 200, f"attendu 200 cycles, obtenu {a.cycles!r}"
    assert len(a.history) == 200, f"attendu 200 sessions, obtenu {len(a.history)}"
    assert (a.phase, a.status, a.remaining) == ("travail", "en cours", 60), (
        f"attendu ('travail','en cours',60), obtenu {(a.phase, a.status, a.remaining)}")
    assert a.today_total == 200, f"attendu 200 min, obtenu {a.today_total!r}"


def test_A06_un_grand_saut_egal_mille_petits(tmp_path):
    a, ca = make(tmp_path, "a.json")
    b, cb = make(tmp_path, "b.json")
    for x in (a, b):
        configure(x, work=1, short=1, long=2, interval=3, auto=True)
        x.start()
    ca.advance(5000)
    for _ in range(5000):
        cb.advance(1)
        b.remaining  # lecture à chaque seconde
    expected_head = ("pause longue", "en cours", 40, 36)
    assert snapshot(a)[:4] == expected_head, (
        f"un saut de 5000 s : attendu {expected_head}, obtenu {snapshot(a)[:4]}")
    assert len(a.history) == 36, f"attendu 36 sessions, obtenu {len(a.history)}"
    assert snapshot(b) == snapshot(a), (
        f"5000 x 1 s : obtenu {snapshot(b)[:4]} ; 1 x 5000 s : obtenu {snapshot(a)[:4]}")


def test_A10_arriere_plan_traverse_fin_de_travail(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=2, auto=False)
    a.start()
    clock.advance(30)
    a.enter_background()
    clock.advance(300)
    a.enter_foreground()
    got = (a.phase, a.status, a.remaining, a.cycles, len(a.history))
    assert got == ("pause courte", "arrêté", 120, 1, 1), (
        f"attendu ('pause courte','arrêté',120,1,1), obtenu {got}")


# --------------------------------------------------------------------------- frontières calendaires

def test_A34_minuit_passe_total_jour_zero_une_minute_apres(tmp_path):
    a, clock = make(tmp_path, start=dt.datetime(2026, 11, 19, 23, 58, 0))
    configure(a, work=1, short=1)
    complete_work(a, clock)            # fin 23:59:00 le 19
    assert a.today_total == 1, f"le 19 attendu 1, obtenu {a.today_total!r}"
    complete_break(a, clock)           # fin 00:00:00 le 20
    assert clock.now().date() == D2
    assert a.today_total == 0, (
        f"le 20 à 00:00, aucune session ce jour : attendu 0, obtenu {a.today_total!r}")


def test_A38_avant_hier_moins_de_48h_serie_zero(tmp_path):
    a, clock = make(tmp_path, start=dt.datetime(2026, 11, 19, 23, 58, 0))
    configure(a, work=1)
    complete_work(a, clock)            # session le 19 à 23:59
    assert a.streak == 1
    advance_to(clock, dt.datetime(2026, 11, 21, 0, 0, 30))  # 24 h 01 min 30 plus tard
    assert a.streak == 0, (
        f"le 21 : ni session le 21 ni le 20 -> attendu 0, obtenu {a.streak!r}")


def test_A35_veille_plus_de_24h_serie_incrementee(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1)
    complete_work(a, clock)            # session le 19 à 09:01
    complete_break(a, clock)
    advance_to(clock, dt.datetime(2026, 11, 20, 20, 0, 0))  # ~35 h plus tard
    complete_work(a, clock)
    assert [s["date"] for s in a.history] == [D1, D2]
    assert a.streak == 2, f"session la veille (calendaire) : attendu 2, obtenu {a.streak!r}"


def test_A36_avant_hier_moins_de_48h_serie_un(tmp_path):
    a, clock = make(tmp_path, start=dt.datetime(2026, 11, 19, 23, 58, 0))
    configure(a, work=1, short=1)
    complete_work(a, clock)            # session le 19 à 23:59
    complete_break(a, clock)           # 00:00 le 20, aucune session le 20
    advance_to(clock, dt.datetime(2026, 11, 21, 0, 1, 0))
    complete_work(a, clock)            # session le 21 à 00:02
    assert [s["date"] for s in a.history] == [D1, D3], f"dates {[s['date'] for s in a.history]}"
    assert a.streak == 1, f"aucune session le 20 : attendu 1, obtenu {a.streak!r}"


def test_A35_serie_identique_apres_reouverture(tmp_path):
    """A35-A38 : la série ne dépend que de l'historique et de la date courante."""
    def two_days(x, c):
        configure(x, work=1)
        complete_work(x, c)
        complete_break(x, c)
        c.advance(DAY)
        complete_work(x, c)
        complete_break(x, c)

    x, cx = make(tmp_path, "x.json")
    z, cz = make(tmp_path, "z.json")
    two_days(x, cx)
    two_days(z, cz)
    assert x.streak == z.streak == 2
    x.close()
    y_clock = app.Clock(cx.now() + dt.timedelta(days=1))
    y = app.PomodoroApp(str(tmp_path / "x.json"), y_clock)
    cz.advance(DAY)
    assert norm(y.history) == norm(z.history)
    assert y.streak == z.streak, (
        f"même historique, même date : rouvert {y.streak!r}, jamais fermé {z.streak!r}")
    configure(y, work=1)
    complete_work(y, y_clock)
    complete_work(z, cz)
    assert z.streak == 3, f"jamais fermé : attendu 3, obtenu {z.streak!r}"
    assert y.streak == 3, f"rouvert : attendu 3, obtenu {y.streak!r}"


# --------------------------------------------------------------------------- durées et sessions

def test_A04_duree_changee_pendant_pause_courte_appliquee_au_travail_suivant(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=1)
    complete_work(a, clock)
    a.set_work_duration(3)
    complete_break(a, clock)
    assert (a.phase, a.status) == ("travail", "arrêté")
    assert a.remaining == 180, f"arrêté en travail : attendu 180, obtenu {a.remaining!r}"


def test_A04_duree_changee_en_cours_appliquee_au_travail_suivant(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2, short=1)
    a.start()
    clock.advance(10)
    a.set_work_duration(4)
    clock.advance(a.remaining)
    assert a.phase == "pause courte"
    complete_break(a, clock)
    assert (a.phase, a.status) == ("travail", "arrêté")
    assert a.remaining == 240, f"attendu 240, obtenu {a.remaining!r}"


def test_A25_trou_arrete_en_pause_courte_temps_restant_inchange(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=1)
    complete_work(a, clock)
    assert (a.phase, a.status, a.remaining) == ("pause courte", "arrêté", 60)
    a.set_work_duration(3)
    assert a.remaining == 60, (
        f"la durée travail ne doit pas toucher la pause : attendu 60, obtenu {a.remaining!r}")


def test_A32_trou_duree_modifiee_en_cours_compte_duree_du_demarrage(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    a.start()
    clock.advance(10)
    a.set_work_duration(5)
    assert a.remaining == 110
    clock.advance(a.remaining)
    assert a.history[-1]["minutes"] == 2, f"attendu 2 min travaillées, obtenu {a.history[-1]!r}"
    assert a.today_total == 2, f"attendu 2, obtenu {a.today_total!r}"


def test_A16_trou_intervalle_zero_refuse(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=2)
    with pytest.raises(ValueError):
        a.set_long_interval(0)
    complete_work(a, clock)
    assert a.phase == "pause courte", f"attendu 'pause courte', obtenu {a.phase!r}"
    complete_break(a, clock)
    complete_work(a, clock)
    assert a.phase == "pause longue", f"intervalle 2 conservé : attendu 'pause longue', obtenu {a.phase!r}"


def test_A27_trou_duree_negative_refusee(tmp_path):
    a, _ = make(tmp_path)
    a.set_work_duration(20)
    with pytest.raises(ValueError):
        a.set_work_duration(-5)
    assert a.work_duration == 20, f"attendu 20, obtenu {a.work_duration!r}"
    assert a.remaining == 1200, f"attendu 1200, obtenu {a.remaining!r}"


# --------------------------------------------------------------------------- tâche au démarrage

def test_A30_demarrage_auto_rattache_tache_du_moment(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=1, auto=True)
    for t in ("A", "B", "C"):
        a.add_task(t)
    a.set_active_task("A")
    a.start()                 # t=0 : session 1 démarrée avec A
    clock.advance(60)         # t=60 : fin travail, pause courte (auto)
    a.set_active_task("B")
    clock.advance(70)         # t=120 : session 2 démarrée automatiquement avec B ; t=130
    a.set_active_task("C")
    clock.advance(50)         # t=180 : fin session 2
    tasks = [s["task"] for s in a.history]
    assert tasks == ["A", "B"], f"attendu ['A','B'], obtenu {tasks}"


def test_A30_reprendre_n_est_pas_demarrer(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1)
    a.add_task("A")
    a.add_task("B")
    a.set_active_task("A")
    a.start()
    clock.advance(10)
    a.pause()
    a.set_active_task("B")
    a.resume()
    clock.advance(a.remaining)
    assert a.history[-1]["task"] == "A", f"attendu 'A', obtenu {a.history[-1]!r}"
    assert a.task_total("A") == 1 and a.task_total("B") == 0, (
        f"totaux A={a.task_total('A')!r}, B={a.task_total('B')!r}")


def test_A30_trou_tache_supprimee_en_cours_de_session(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1)
    a.add_task("Code")
    a.set_active_task("Code")
    a.start()
    clock.advance(10)
    a.delete_task("Code")
    assert a.active_task is None
    clock.advance(a.remaining)
    assert a.history[-1]["task"] == "Code", f"attendu 'Code', obtenu {a.history[-1]!r}"


# --------------------------------------------------------------------------- persistance réelle

def test_A40_fichiers_echanges_entre_chemins(tmp_path):
    a, ca = make(tmp_path, "un.json")
    configure(a, work=1)
    a.add_task("Un")
    a.set_active_task("Un")
    complete_work(a, ca)
    b, cb = make(tmp_path, "deux.json")
    configure(b, work=3)
    b.add_task("Deux")
    b.set_active_task("Deux")
    complete_work(b, cb)
    complete_break(b, cb)
    complete_work(b, cb)
    ha, hb = norm(a.history), norm(b.history)
    a.close()
    b.close()
    p1, p2, tmp = tmp_path / "un.json", tmp_path / "deux.json", tmp_path / "x.json"
    os.replace(p1, tmp)
    os.replace(p2, p1)
    os.replace(tmp, p2)
    c = app.PomodoroApp(str(p1), app.Clock(T0))
    d = app.PomodoroApp(str(p2), app.Clock(T0))
    assert norm(c.history) == hb, f"un.json contient l'ancien deux.json : attendu {hb}, obtenu {norm(c.history)}"
    assert norm(d.history) == ha, f"deux.json contient l'ancien un.json : attendu {ha}, obtenu {norm(d.history)}"


def test_A40_noms_de_tache_hostiles(tmp_path):
    names = ['a,b;"c"\n\td\\', "日本語 🍅", "None", "  espaces  "]
    a, clock = make(tmp_path)
    configure(a, work=1)
    for n in names:
        a.add_task(n)
        a.set_active_task(n)
        complete_work(a, clock)
        complete_break(a, clock)
    a.set_active_task(None)
    complete_work(a, clock)
    tasks = [s["task"] for s in a.history]
    assert tasks == names + ["sans tâche"], f"en mémoire : obtenu {tasks!r}"
    before = norm(a.history)
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0))
    assert norm(b.history) == before, f"attendu {before!r}, obtenu {norm(b.history)!r}"


def test_A40_deux_cents_sessions_relues_dans_l_ordre(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=1, long=2, interval=4, auto=True)
    a.add_task("Long")
    a.set_active_task("Long")
    a.start()
    clock.advance(DAY // 2)  # traverse aussi minuit
    a.set_active_task(None)
    clock.advance(DAY // 2)
    before = norm(a.history)
    assert len(before) > 200
    assert len({row[1] for row in before}) == 2, "attendu des sessions sur deux dates"
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0 + dt.timedelta(days=5)))
    got = norm(b.history)
    assert len(got) == len(before), f"attendu {len(before)} sessions, obtenu {len(got)}"
    assert got == before, "historique relu différent (ordre ou contenu)"


def test_A40_historique_vide_ferme_rouvert(tmp_path):
    a, _ = make(tmp_path)
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0))
    assert b.history == [], f"attendu [], obtenu {b.history!r}"


def test_A40_reouverture_sans_rien_faire_ne_perd_rien(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    complete_work(a, clock)
    before = norm(a.history)
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0 + dt.timedelta(hours=1)))
    b.close()
    c = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0 + dt.timedelta(hours=2)))
    assert norm(c.history) == before, f"attendu {before}, obtenu {norm(c.history)}"


def test_A40_trou_session_sur_disque_sans_close(tmp_path):
    path = tmp_path / "data.json"
    code = (
        "import sys, os, datetime as dt\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import app\n"
        "c = app.Clock(dt.datetime(2026, 11, 19, 9, 0, 0))\n"
        "a = app.PomodoroApp(sys.argv[2], c)\n"
        "a.set_work_duration(1); a.set_short_break(1); a.set_long_break(2)\n"
        "a.set_long_interval(4); a.set_auto_start(False)\n"
        "a.start(); c.advance(60)\n"
        "assert len(a.history) == 1, a.history\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code, str(ROOT), str(path)],
        capture_output=True, text=True, timeout=15, cwd=str(tmp_path),
    )
    assert r.returncode == 0, f"processus fils en échec : {r.stderr}"
    b = app.PomodoroApp(str(path), app.Clock(T0 + dt.timedelta(hours=1)))
    assert norm(b.history) == [["sans tâche", "2026-11-19", 1]], (
        f"processus interrompu sans close : obtenu {norm(b.history)}")


def test_A32_trou_total_jour_apres_reouverture_meme_jour(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    complete_work(a, clock)
    complete_break(a, clock)
    complete_work(a, clock)
    assert a.today_total == 4
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(clock.now()))
    assert b.today_total == 4, f"même jour, même historique : attendu 4, obtenu {b.today_total!r}"


def test_A33_trou_total_tache_apres_reouverture(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    a.add_task("Code")
    a.set_active_task("Code")
    complete_work(a, clock)
    complete_break(a, clock)
    complete_work(a, clock)
    assert a.task_total("Code") == 4
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(clock.now()))
    assert b.task_total("Code") == 4, f"attendu 4, obtenu {b.task_total('Code')!r}"
