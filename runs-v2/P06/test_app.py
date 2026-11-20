"""Tests rouges — sonde P06 (minuteur pomodoro, historique, persistance).

Interface publique fixée par ces tests (module `app`) :

    clock = app.Clock(datetime)          # temps simulé
    clock.now() -> datetime
    clock.advance(seconds)               # fait avancer le temps

    a = app.PomodoroApp(path: str, clock)  # path : fichier de données
    a.close()                              # fermeture (les données sont sur disque)

    # état observable
    a.phase        -> "travail" | "pause courte" | "pause longue"
    a.status       -> "arrêté" | "en cours" | "en pause"
    a.cycles       -> int  (cycles complétés)
    a.remaining    -> int  (temps restant, en secondes, calculé d'après clock)
    a.work_duration -> int (minutes)
    a.history      -> list[dict] ; chaque session :
                      {"task": str, "date": datetime.date, "minutes": int}
                      task = nom de la tâche, ou "sans tâche"
    a.today_total  -> int  (minutes, pour la date courante de clock)
    a.task_total(name) -> int (minutes)
    a.streak       -> int  (série jours)
    a.active_task  -> str | None   (None = « aucune »)

    # actions
    a.start(); a.pause(); a.resume(); a.reset(); a.skip()
    a.enter_background(); a.enter_foreground()
    a.set_work_duration(min)   # 0 -> ValueError, valeur inchangée
    a.set_short_break(min); a.set_long_break(min)
    a.set_long_interval(n); a.set_auto_start(bool)
    a.add_task(name); a.set_active_task(name | None); a.delete_task(name)
"""

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import app

ROOT = Path(__file__).resolve().parent.parent
T0 = dt.datetime(2026, 11, 19, 9, 0, 0)
DAY = 86400


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
    """Démarre si arrêté puis laisse le temps restant arriver à zéro."""
    if a.status == "arrêté":
        a.start()
    assert a.status == "en cours", f"attendu statut 'en cours' avant écoulement, obtenu {a.status!r}"
    clock.advance(a.remaining)


def complete_work(a, clock):
    assert a.phase == "travail", f"attendu phase 'travail', obtenu {a.phase!r}"
    run_out(a, clock)


def complete_break(a, clock):
    assert a.phase in ("pause courte", "pause longue"), f"attendu une pause, obtenu {a.phase!r}"
    run_out(a, clock)


def norm(history):
    return [[s["task"], str(s["date"]), s["minutes"]] for s in history]


# --------------------------------------------------------------------------- A01-A04

def test_A01_premier_lancement_phase_travail(tmp_path):
    a, _ = make(tmp_path)
    assert a.phase == "travail", f"attendu 'travail', obtenu {a.phase!r}"


def test_A01_premier_lancement_independant_d_une_autre_instance(tmp_path):
    other, clock = make(tmp_path, "autre.json")
    configure(other)
    complete_work(other, clock)
    assert other.phase == "pause courte"
    a, _ = make(tmp_path, "neuf.json")
    assert a.phase == "travail", f"état partagé entre instances : phase {a.phase!r}"


def test_A02_premier_lancement_statut_arrete(tmp_path):
    a, _ = make(tmp_path)
    assert a.status == "arrêté", f"attendu 'arrêté', obtenu {a.status!r}"


def test_A03_premier_lancement_cycles_zero(tmp_path):
    a, _ = make(tmp_path)
    assert a.cycles == 0, f"attendu 0, obtenu {a.cycles!r}"


def test_A03_premier_lancement_cycles_zero_malgre_autre_instance(tmp_path):
    other, clock = make(tmp_path, "autre.json")
    configure(other)
    complete_work(other, clock)
    assert other.cycles == 1
    a, _ = make(tmp_path, "neuf.json")
    assert a.cycles == 0, f"état partagé entre instances : cycles {a.cycles!r}"


def test_A04_arrete_travail_temps_restant_egal_duree_par_defaut(tmp_path):
    a, _ = make(tmp_path)
    assert a.remaining == a.work_duration * 60, (
        f"attendu {a.work_duration * 60}, obtenu {a.remaining!r}")


def test_A04_arrete_travail_temps_restant_egal_duree_configuree(tmp_path):
    a, _ = make(tmp_path)
    a.set_work_duration(17)
    assert a.status == "arrêté" and a.phase == "travail"
    assert a.remaining == 17 * 60, f"attendu 1020, obtenu {a.remaining!r}"


def test_A04_temps_restant_fige_tant_que_arrete(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    clock.advance(300)
    assert a.remaining == 1500, f"attendu 1500 (arrêté), obtenu {a.remaining!r}"


# --------------------------------------------------------------------------- A05-A10

def test_A05_demarrer_passe_en_cours(tmp_path):
    a, _ = make(tmp_path)
    a.start()
    assert a.status == "en cours", f"attendu 'en cours', obtenu {a.status!r}"


def test_A06_une_seconde_diminue_d_une_seconde(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    r0 = a.remaining
    clock.advance(1)
    assert a.remaining == r0 - 1, f"attendu {r0 - 1}, obtenu {a.remaining!r}"


def test_A06_secondes_successives(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    for i in range(1, 11):
        clock.advance(1)
        assert a.remaining == 1500 - i, f"après {i}s attendu {1500 - i}, obtenu {a.remaining!r}"


def test_A07_en_pause_une_seconde_ne_change_rien(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    clock.advance(10)
    a.pause()
    r0 = a.remaining
    clock.advance(1)
    assert a.remaining == r0, f"attendu {r0}, obtenu {a.remaining!r}"


def test_A07_en_pause_longtemps_ne_change_rien(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    clock.advance(10)
    a.pause()
    clock.advance(3600)
    assert a.remaining == 1490, f"attendu 1490, obtenu {a.remaining!r}"
    assert a.status == "en pause"


def test_A08_pause_passe_en_pause(tmp_path):
    a, _ = make(tmp_path)
    a.start()
    a.pause()
    assert a.status == "en pause", f"attendu 'en pause', obtenu {a.status!r}"


def test_A09_reprendre_passe_en_cours(tmp_path):
    a, _ = make(tmp_path)
    a.start()
    a.pause()
    a.resume()
    assert a.status == "en cours", f"attendu 'en cours', obtenu {a.status!r}"


def test_A09_reprendre_puis_le_temps_recoule(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    clock.advance(5)
    a.pause()
    clock.advance(100)
    a.resume()
    clock.advance(5)
    assert a.remaining == 1490, f"attendu 1490, obtenu {a.remaining!r}"


def test_A10_soixante_secondes_en_arriere_plan(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    r0 = a.remaining
    a.enter_background()
    clock.advance(60)
    a.enter_foreground()
    assert a.remaining == r0 - 60, f"attendu {r0 - 60}, obtenu {a.remaining!r}"
    assert a.status == "en cours"


# --------------------------------------------------------------------------- A11-A13

@pytest.mark.parametrize("etat", ["arrêté", "en cours", "en pause"])
def test_A11_reinitialiser_met_arrete(tmp_path, etat):
    a, clock = make(tmp_path)
    if etat != "arrêté":
        a.start()
        clock.advance(3)
    if etat == "en pause":
        a.pause()
    assert a.status == etat
    a.reset()
    assert a.status == "arrêté", f"depuis {etat!r} attendu 'arrêté', obtenu {a.status!r}"


def test_A12_reinitialiser_travail_remet_duree(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    clock.advance(100)
    a.reset()
    assert a.remaining == 1500, f"attendu 1500, obtenu {a.remaining!r}"
    clock.advance(10)
    assert a.remaining == 1500, f"après reset le temps ne doit plus s'écouler, obtenu {a.remaining!r}"


def test_A12_trou_reinitialiser_en_pause_courte(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1, short=3)
    complete_work(a, clock)
    a.start()
    clock.advance(20)
    a.reset()
    assert a.phase == "pause courte", f"attendu phase inchangée, obtenu {a.phase!r}"
    assert a.remaining == 180, f"attendu 180, obtenu {a.remaining!r}"


def test_A13_reinitialiser_laisse_historique(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1)
    complete_work(a, clock)
    complete_break(a, clock)
    before = norm(a.history)
    assert len(before) == 1
    a.start()
    clock.advance(30)
    a.reset()
    assert norm(a.history) == before, f"attendu {before}, obtenu {norm(a.history)}"


def test_A13_reinitialiser_session_partielle_rien_ajoute(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=1)
    a.start()
    clock.advance(59)
    a.reset()
    clock.advance(120)
    assert a.history == [], f"attendu historique vide, obtenu {a.history!r}"


# --------------------------------------------------------------------------- A14-A22

def test_A14_fin_travail_incremente_cycles(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    assert a.cycles == 1, f"attendu 1, obtenu {a.cycles!r}"


def test_A14_deux_fins_travail(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    complete_break(a, clock)
    complete_work(a, clock)
    assert a.cycles == 2, f"attendu 2, obtenu {a.cycles!r}"


def test_A14_pas_d_increment_avant_zero(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    a.start()
    clock.advance(59)
    assert a.cycles == 0 and a.phase == "travail", f"obtenu cycles={a.cycles}, phase={a.phase!r}"


def test_A15_non_multiple_pause_courte(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=4)
    complete_work(a, clock)
    assert a.phase == "pause courte", f"attendu 'pause courte', obtenu {a.phase!r}"


def test_A16_multiple_pause_longue(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=2)
    complete_work(a, clock)
    assert a.phase == "pause courte"
    complete_break(a, clock)
    complete_work(a, clock)
    assert a.cycles == 2
    assert a.phase == "pause longue", f"attendu 'pause longue', obtenu {a.phase!r}"


def test_A16_intervalle_un_toujours_pause_longue(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=1)
    complete_work(a, clock)
    assert a.phase == "pause longue", f"attendu 'pause longue', obtenu {a.phase!r}"


def test_A17_fin_pause_courte_travail(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    complete_break(a, clock)
    assert a.phase == "travail", f"attendu 'travail', obtenu {a.phase!r}"


def test_A18_fin_pause_longue_travail(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=1)
    complete_work(a, clock)
    assert a.phase == "pause longue"
    complete_break(a, clock)
    assert a.phase == "travail", f"attendu 'travail', obtenu {a.phase!r}"


def test_A19_pause_courte_temps_restant(tmp_path):
    a, clock = make(tmp_path)
    configure(a, short=3)
    complete_work(a, clock)
    assert a.remaining == 180, f"attendu 180, obtenu {a.remaining!r}"


def test_A20_pause_longue_temps_restant(tmp_path):
    a, clock = make(tmp_path)
    configure(a, long=7, interval=1)
    complete_work(a, clock)
    assert a.remaining == 420, f"attendu 420, obtenu {a.remaining!r}"


def test_A21_sans_auto_arrete(tmp_path):
    a, clock = make(tmp_path)
    configure(a, short=3, auto=False)
    complete_work(a, clock)
    assert a.status == "arrêté", f"attendu 'arrêté', obtenu {a.status!r}"
    clock.advance(30)
    assert a.remaining == 180, f"arrêté : attendu 180, obtenu {a.remaining!r}"


def test_A22_avec_auto_reste_en_cours(tmp_path):
    a, clock = make(tmp_path)
    configure(a, short=3, auto=True)
    complete_work(a, clock)
    assert a.status == "en cours", f"attendu 'en cours', obtenu {a.status!r}"
    clock.advance(1)
    assert a.remaining == 179, f"attendu 179, obtenu {a.remaining!r}"


# --------------------------------------------------------------------------- A23-A27

def test_A23_passer_pause_courte(tmp_path):
    a, _ = make(tmp_path)
    configure(a, interval=10)
    a.skip()
    assert a.phase == "pause courte", f"attendu 'pause courte', obtenu {a.phase!r}"


def test_A23_passer_pause_longue(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=1)
    complete_work(a, clock)
    complete_break(a, clock)
    assert a.phase == "travail" and a.cycles == 1
    a.skip()
    assert a.phase == "pause longue", f"attendu 'pause longue', obtenu {a.phase!r}"


def test_A23_trou_passer_cycles_non_multiple(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=2)
    complete_work(a, clock)
    complete_break(a, clock)
    assert a.cycles == 1
    a.skip()
    assert a.phase == "pause courte", f"attendu 'pause courte', obtenu {a.phase!r}"


def test_A24_passer_laisse_cycles(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    complete_break(a, clock)
    a.skip()
    assert a.cycles == 1, f"attendu 1, obtenu {a.cycles!r}"


def test_A24_passer_depuis_zero(tmp_path):
    a, _ = make(tmp_path)
    configure(a)
    a.skip()
    assert a.cycles == 0, f"attendu 0, obtenu {a.cycles!r}"


def test_A25_arrete_modifier_duree(tmp_path):
    a, _ = make(tmp_path)
    a.set_work_duration(25)
    a.set_work_duration(10)
    assert a.remaining == 600, f"attendu 600, obtenu {a.remaining!r}"


def test_A25_trou_en_pause_modifier_duree(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    clock.advance(10)
    a.pause()
    a.set_work_duration(10)
    assert a.remaining == 1490, f"attendu 1490 (inchangé), obtenu {a.remaining!r}"


def test_A26_en_cours_modifier_duree(tmp_path):
    a, clock = make(tmp_path)
    a.set_work_duration(25)
    a.start()
    clock.advance(5)
    r0 = a.remaining
    a.set_work_duration(10)
    assert a.remaining == r0, f"attendu {r0}, obtenu {a.remaining!r}"
    assert a.work_duration == 10


def test_A27_trou_zero_refuse(tmp_path):
    a, _ = make(tmp_path)
    a.set_work_duration(20)
    with pytest.raises(ValueError):
        a.set_work_duration(0)
    assert a.work_duration == 20, f"attendu 20, obtenu {a.work_duration!r}"
    assert a.remaining == 1200, f"attendu 1200, obtenu {a.remaining!r}"


def test_A27_zero_refuse_persiste_pas(tmp_path):
    a, _ = make(tmp_path)
    a.set_work_duration(20)
    try:
        a.set_work_duration(0)
    except ValueError:
        pass
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0))
    assert b.work_duration == 20 or b.work_duration > 0, (
        f"durée 0 persistée : obtenu {b.work_duration!r}")


# --------------------------------------------------------------------------- A28-A33

def test_A28_fin_travail_ajoute_session(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    assert a.history == []
    complete_work(a, clock)
    assert len(a.history) == 1, f"attendu 1 session, obtenu {a.history!r}"
    s = a.history[0]
    assert s["minutes"] == 2 and s["date"] == T0.date(), f"session inattendue {s!r}"


def test_A28_passer_n_ajoute_pas(tmp_path):
    a, _ = make(tmp_path)
    configure(a)
    a.skip()
    assert a.history == [], f"passer ne termine pas une session ; obtenu {a.history!r}"


def test_A28_trou_date_de_fin_si_minuit(tmp_path):
    a, clock = make(tmp_path, start=dt.datetime(2026, 11, 19, 23, 59, 30))
    configure(a, work=1)
    complete_work(a, clock)
    assert a.history[-1]["date"] == dt.date(2026, 11, 20), (
        f"attendu date de fin 2026-11-20, obtenu {a.history[-1]['date']!r}")


def test_A29_fin_pause_courte_historique_inchange(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    before = norm(a.history)
    complete_break(a, clock)
    assert norm(a.history) == before, f"attendu {before}, obtenu {norm(a.history)}"


def test_A29_fin_pause_longue_historique_inchange(tmp_path):
    a, clock = make(tmp_path)
    configure(a, interval=1)
    complete_work(a, clock)
    before = norm(a.history)
    complete_break(a, clock)
    assert norm(a.history) == before, f"attendu {before}, obtenu {norm(a.history)}"


def test_A30_session_rattachee_tache_au_demarrage(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    a.add_task("Rédaction")
    a.add_task("Lecture")
    a.set_active_task("Rédaction")
    a.start()
    clock.advance(10)
    a.set_active_task("Lecture")
    clock.advance(a.remaining)
    assert a.history[-1]["task"] == "Rédaction", f"attendu 'Rédaction', obtenu {a.history[-1]!r}"


def test_A30_tache_simple(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    a.add_task("Révision ✓")
    a.set_active_task("Révision ✓")
    complete_work(a, clock)
    assert a.history[-1]["task"] == "Révision ✓", f"obtenu {a.history[-1]!r}"


def test_A31_sans_tache(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    assert a.active_task is None
    complete_work(a, clock)
    assert a.history[-1]["task"] == "sans tâche", f"attendu 'sans tâche', obtenu {a.history[-1]!r}"


def test_A32_total_jour_augmente(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    assert a.today_total == 0
    complete_work(a, clock)
    assert a.today_total == 2, f"attendu 2, obtenu {a.today_total!r}"
    complete_break(a, clock)
    a.set_work_duration(3)
    complete_work(a, clock)
    assert a.today_total == 5, f"attendu 5, obtenu {a.today_total!r}"


def test_A32_total_jour_pas_sur_reset(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    a.start()
    clock.advance(100)
    a.reset()
    assert a.today_total == 0, f"attendu 0, obtenu {a.today_total!r}"


def test_A33_total_tache_augmente(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    a.add_task("Code")
    a.add_task("Autre")
    a.set_active_task("Code")
    complete_work(a, clock)
    assert a.task_total("Code") == 2, f"attendu 2, obtenu {a.task_total('Code')!r}"
    assert a.task_total("Autre") == 0, f"attendu 0, obtenu {a.task_total('Autre')!r}"


def test_A33_trou_total_tache_au_demarrage(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    a.add_task("Code")
    a.add_task("Autre")
    a.set_active_task("Code")
    a.start()
    clock.advance(10)
    a.set_active_task("Autre")
    clock.advance(a.remaining)
    assert a.task_total("Code") == 2, f"attendu 2, obtenu {a.task_total('Code')!r}"
    assert a.task_total("Autre") == 0, f"attendu 0, obtenu {a.task_total('Autre')!r}"


# --------------------------------------------------------------------------- A34-A38

def test_A34_changement_date_total_jour_zero(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    complete_work(a, clock)
    assert a.today_total == 2
    clock.advance(DAY)
    assert a.today_total == 0, f"attendu 0 le lendemain, obtenu {a.today_total!r}"


def test_A34_total_jour_repart_le_lendemain(tmp_path):
    a, clock = make(tmp_path)
    configure(a, work=2)
    complete_work(a, clock)
    complete_break(a, clock)
    clock.advance(DAY)
    complete_work(a, clock)
    assert a.today_total == 2, f"attendu 2, obtenu {a.today_total!r}"


def test_A35_veille_incremente_serie(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    complete_break(a, clock)
    assert a.streak == 1, f"jour 1 : attendu 1, obtenu {a.streak!r}"
    clock.advance(DAY)
    complete_work(a, clock)
    assert a.streak == 2, f"jour 2 : attendu 2, obtenu {a.streak!r}"


def test_A35_trois_jours(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    for _ in range(3):
        complete_work(a, clock)
        complete_break(a, clock)
        clock.advance(DAY)
    clock.advance(-0) if False else None
    # au 4e jour, sans session encore : la série affichée tient compte de la veille
    complete_work(a, clock)
    assert a.streak == 4, f"attendu 4, obtenu {a.streak!r}"


def test_A36_pas_de_veille_serie_un(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    complete_break(a, clock)
    clock.advance(2 * DAY)
    complete_work(a, clock)
    assert a.streak == 1, f"attendu 1, obtenu {a.streak!r}"


def test_A36_premiere_session_jamais(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    assert a.streak == 1, f"attendu 1, obtenu {a.streak!r}"


def test_A37_deuxieme_session_meme_jour(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    complete_break(a, clock)
    s = a.streak
    complete_work(a, clock)
    assert a.streak == s == 1, f"attendu 1 inchangé, obtenu {s} puis {a.streak!r}"


def test_A38_ni_aujourd_hui_ni_veille_zero(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    complete_break(a, clock)
    assert a.streak == 1
    clock.advance(2 * DAY)
    assert a.streak == 0, f"attendu 0, obtenu {a.streak!r}"


def test_A38_neuf_zero(tmp_path):
    a, _ = make(tmp_path)
    assert a.streak == 0, f"attendu 0, obtenu {a.streak!r}"


# --------------------------------------------------------------------------- A39

def test_A39_supprimer_tache_active(tmp_path):
    a, _ = make(tmp_path)
    a.add_task("Code")
    a.set_active_task("Code")
    a.delete_task("Code")
    assert a.active_task is None, f"attendu None, obtenu {a.active_task!r}"


def test_A39_puis_session_sans_tache(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    a.add_task("Code")
    a.set_active_task("Code")
    a.delete_task("Code")
    complete_work(a, clock)
    assert a.history[-1]["task"] == "sans tâche", f"obtenu {a.history[-1]!r}"


# --------------------------------------------------------------------------- A40 (persistance réelle)

def _fill(a, clock):
    configure(a, work=2)
    a.add_task("Révision ✓")
    a.set_active_task("Révision ✓")
    complete_work(a, clock)
    complete_break(a, clock)
    a.set_active_task(None)
    complete_work(a, clock)
    complete_break(a, clock)
    clock.advance(DAY)
    a.add_task("Code")
    a.set_active_task("Code")
    complete_work(a, clock)


def test_A40_reouverture_historique_identique(tmp_path):
    a, clock = make(tmp_path)
    _fill(a, clock)
    before = norm(a.history)
    assert len(before) == 3
    a.close()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0 + dt.timedelta(days=3)))
    assert norm(b.history) == before, f"attendu {before}, obtenu {norm(b.history)}"
    assert b.history == a.history


def test_A40_fichier_ecrit_sur_disque(tmp_path):
    a, clock = make(tmp_path)
    _fill(a, clock)
    a.close()
    p = tmp_path / "data.json"
    assert p.exists() and p.stat().st_size > 0, "aucune donnée écrite au chemin donné"


def test_A40_relu_par_un_autre_processus(tmp_path):
    a, clock = make(tmp_path)
    _fill(a, clock)
    before = norm(a.history)
    a.close()
    code = (
        "import sys, json, datetime as dt\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import app\n"
        "a = app.PomodoroApp(sys.argv[2], app.Clock(dt.datetime(2026, 11, 25, 12, 0, 0)))\n"
        "print(json.dumps([[s['task'], str(s['date']), s['minutes']] for s in a.history]))\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code, str(ROOT), str(tmp_path / "data.json")],
        capture_output=True, text=True, timeout=15, cwd=str(tmp_path),
    )
    assert r.returncode == 0, f"processus fils en échec : {r.stderr}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got == before, f"attendu {before}, obtenu {got}"


def test_A40_copie_du_fichier_relue(tmp_path):
    a, clock = make(tmp_path)
    _fill(a, clock)
    before = norm(a.history)
    a.close()
    (tmp_path / "ailleurs").mkdir()
    shutil.copy(tmp_path / "data.json", tmp_path / "ailleurs" / "copie.json")
    (tmp_path / "data.json").unlink()
    b = app.PomodoroApp(str(tmp_path / "ailleurs" / "copie.json"), app.Clock(T0))
    assert norm(b.history) == before, f"attendu {before}, obtenu {norm(b.history)}"


def test_A40_fichier_supprime_historique_vide(tmp_path):
    a, clock = make(tmp_path)
    _fill(a, clock)
    a.close()
    (tmp_path / "data.json").unlink()
    b = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0))
    assert b.history == [], f"historique transmis par la mémoire : {b.history!r}"


def test_A40_chemin_distinct_historique_vide(tmp_path):
    a, clock = make(tmp_path)
    _fill(a, clock)
    a.close()
    b = app.PomodoroApp(str(tmp_path / "autre.json"), app.Clock(T0))
    assert b.history == [], f"historique partagé entre chemins : {b.history!r}"


def test_A40_deux_reouvertures_successives(tmp_path):
    a, clock = make(tmp_path)
    configure(a)
    complete_work(a, clock)
    a.close()
    clock2 = app.Clock(T0 + dt.timedelta(hours=1))
    b = app.PomodoroApp(str(tmp_path / "data.json"), clock2)
    configure(b)
    if b.phase != "travail":
        b.skip()
    complete_work(b, clock2)
    before = norm(b.history)
    assert len(before) == 2, f"attendu 2 sessions, obtenu {before}"
    b.close()
    c = app.PomodoroApp(str(tmp_path / "data.json"), app.Clock(T0 + dt.timedelta(hours=2)))
    assert norm(c.history) == before, f"attendu {before}, obtenu {norm(c.history)}"
