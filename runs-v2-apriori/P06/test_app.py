"""Tests rouges de la sonde Pomodoro — couche code.

Interface publique fixée par ces tests (module `app`) :

    app.Clock(start: datetime.datetime)
        .now() -> datetime.datetime
        .advance(seconds: int) -> None          # seul moyen de faire passer le temps

    app.Storage()                               # stockage en mémoire, survit à la fermeture d'une App

    app.App(clock: Clock, storage: Storage)
        # observations (toutes recalculées à partir de l'horloge)
        .phase() -> str          # "travail" | "pause courte" | "pause longue"
        .status() -> str         # "arrêté" | "en cours" | "en pause"
        .remaining() -> int      # secondes
        .cycles() -> int
        .history() -> list[dict] # chaque session : {"task": str, "date": datetime.date, ...}
        .today_total() -> int    # minutes
        .task_total(task_id) -> int  # minutes
        .streak() -> int
        .active_task() -> task_id | None   # None = « aucune »
        # actions
        .start() .pause() .resume() .reset() .skip()
        .go_background() .go_foreground()
        .close()
        # réglages (minutes ; ValueError si refusé)
        .set_work_duration(m) .work_duration() -> int
        .set_short_break_duration(m) .short_break_duration() -> int
        .set_long_break_duration(m) .long_break_duration() -> int
        .set_long_interval(n) .long_interval() -> int
        .set_auto_start(flag: bool) .auto_start() -> bool
        # tâches
        .add_task(name: str) -> task_id
        .set_active_task(task_id | None)
        .delete_task(task_id)
"""

import datetime

import pytest

import app

START = datetime.datetime(2026, 3, 10, 9, 0, 0)
DAY = 86400


def make(start=START):
    clock = app.Clock(start)
    storage = app.Storage()
    a = app.App(clock=clock, storage=storage)
    return a, clock, storage


def make_fast(work=1, short=1, long=1, interval=4, start=START):
    a, clock, storage = make(start)
    a.set_work_duration(work)
    a.set_short_break_duration(short)
    a.set_long_break_duration(long)
    a.set_long_interval(interval)
    a.set_auto_start(False)
    return a, clock, storage


def run_current_phase(a, clock):
    """Démarre la phase courante (minuteur arrêté) et laisse le temps s'écouler jusqu'à zéro."""
    assert a.status() == "arrêté", f"helper: attendu minuteur arrêté, obtenu {a.status()!r}"
    a.start()
    clock.advance(a.remaining())


def complete_work(a, clock):
    """Termine les pauses éventuelles puis une session de travail complète."""
    guard = 0
    while a.phase() != "travail":
        run_current_phase(a, clock)
        guard += 1
        assert guard < 5, "helper: impossible de revenir à la phase travail"
    run_current_phase(a, clock)


# ---------------------------------------------------------------- A01–A03


def test_A01_premier_lancement_phase_travail():
    a, _, _ = make()
    assert a.phase() == "travail", f"attendu 'travail', obtenu {a.phase()!r}"


def test_A02_premier_lancement_minuteur_arrete():
    a, _, _ = make()
    assert a.status() == "arrêté", f"attendu 'arrêté', obtenu {a.status()!r}"


def test_A03_premier_lancement_zero_cycle():
    a, _, _ = make()
    assert a.cycles() == 0, f"attendu 0, obtenu {a.cycles()}"


def test_A03_premier_lancement_independant_dun_autre_stockage():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    assert a.cycles() == 1
    b, _, _ = make()
    assert b.cycles() == 0, f"un nouveau stockage doit démarrer à 0 cycle, obtenu {b.cycles()}"
    assert b.history() == [], f"un nouveau stockage doit avoir un historique vide, obtenu {b.history()!r}"


# ---------------------------------------------------------------- A04–A10


def test_A04_arrete_travail_temps_restant_egal_duree_travail():
    a, _, _ = make()
    assert a.work_duration() > 0
    assert a.remaining() == a.work_duration() * 60, (
        f"attendu {a.work_duration() * 60} s, obtenu {a.remaining()}"
    )


def test_A04_arrete_le_temps_ne_coule_pas():
    a, clock, _ = make()
    before = a.remaining()
    clock.advance(300)
    assert a.remaining() == before == a.work_duration() * 60, (
        f"minuteur arrêté : attendu {a.work_duration() * 60}, obtenu {a.remaining()}"
    )


def test_A05_demarrer_passe_en_cours():
    a, _, _ = make()
    a.start()
    assert a.status() == "en cours", f"attendu 'en cours', obtenu {a.status()!r}"


def test_A06_une_seconde_diminue_dune_seconde():
    a, clock, _ = make_fast(work=25)
    a.start()
    before = a.remaining()
    clock.advance(1)
    assert a.remaining() == before - 1, f"attendu {before - 1}, obtenu {a.remaining()}"


def test_A06_temps_restant_suit_horloge_et_non_les_appels():
    a, clock, _ = make_fast(work=25)
    a.start()
    for _ in range(50):
        a.remaining()
    assert a.remaining() == 1500, f"sans avancer l'horloge, attendu 1500, obtenu {a.remaining()}"
    clock.advance(437)
    assert a.remaining() == 1500 - 437, f"attendu {1500 - 437}, obtenu {a.remaining()}"


def test_A06_secondes_successives():
    a, clock, _ = make_fast(work=25)
    a.start()
    for i in range(1, 11):
        clock.advance(1)
        assert a.remaining() == 1500 - i, f"après {i} s, attendu {1500 - i}, obtenu {a.remaining()}"


def test_A07_en_pause_le_temps_restant_ne_change_pas():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(10)
    a.pause()
    before = a.remaining()
    clock.advance(1)
    assert a.remaining() == before, f"attendu {before}, obtenu {a.remaining()}"
    clock.advance(500)
    assert a.remaining() == before, f"après 500 s en pause, attendu {before}, obtenu {a.remaining()}"


def test_A07_temps_en_pause_non_decompte_apres_reprise():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(10)
    a.pause()
    clock.advance(100)
    a.resume()
    clock.advance(5)
    assert a.remaining() == 1500 - 15, f"attendu {1500 - 15}, obtenu {a.remaining()}"


def test_A08_pause_depuis_en_cours():
    a, _, _ = make()
    a.start()
    a.pause()
    assert a.status() == "en pause", f"attendu 'en pause', obtenu {a.status()!r}"


def test_A09_reprendre_depuis_en_pause():
    a, _, _ = make()
    a.start()
    a.pause()
    a.resume()
    assert a.status() == "en cours", f"attendu 'en cours', obtenu {a.status()!r}"


def test_A10_arriere_plan_60_secondes():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(5)
    before = a.remaining()
    a.go_background()
    clock.advance(60)
    a.go_foreground()
    assert a.remaining() == before - 60, f"attendu {before - 60}, obtenu {a.remaining()}"


def test_A10_arriere_plan_duree_quelconque():
    a, clock, _ = make_fast(work=25)
    a.start()
    before = a.remaining()
    a.go_background()
    clock.advance(37)
    a.go_foreground()
    assert a.remaining() == before - 37, f"attendu {before - 37}, obtenu {a.remaining()}"
    a.go_background()
    clock.advance(600)
    a.go_foreground()
    assert a.remaining() == before - 637, f"attendu {before - 637}, obtenu {a.remaining()}"


def test_A10_trou_zero_atteint_en_arriere_plan():
    a, clock, _ = make_fast(work=1, short=3)
    a.start()
    a.go_background()
    clock.advance(90)
    a.go_foreground()
    assert a.cycles() == 1, f"zéro atteint en arrière-plan : attendu 1 cycle, obtenu {a.cycles()}"
    assert a.phase() == "pause courte", f"attendu 'pause courte', obtenu {a.phase()!r}"
    assert a.status() == "arrêté", f"attendu 'arrêté', obtenu {a.status()!r}"
    assert a.remaining() == 180, f"attendu 180, obtenu {a.remaining()}"
    assert len(a.history()) == 1, f"attendu 1 session, obtenu {len(a.history())}"


# ---------------------------------------------------------------- A11–A13


@pytest.mark.parametrize("prep", ["arrêté", "en cours", "en pause"])
def test_A11_reinitialiser_met_arrete(prep):
    a, clock, _ = make()
    if prep in ("en cours", "en pause"):
        a.start()
        clock.advance(30)
    if prep == "en pause":
        a.pause()
    a.reset()
    assert a.status() == "arrêté", f"depuis {prep!r} : attendu 'arrêté', obtenu {a.status()!r}"


def test_A11_apres_reinitialiser_le_temps_ne_coule_plus():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(30)
    a.reset()
    clock.advance(30)
    assert a.remaining() == 1500, f"attendu 1500, obtenu {a.remaining()}"


def test_A12_reinitialiser_remet_duree_travail():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(123)
    a.reset()
    assert a.remaining() == 1500, f"attendu 1500, obtenu {a.remaining()}"


def test_A12_reinitialiser_en_pause_remet_duree_travail():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(200)
    a.pause()
    a.reset()
    assert a.remaining() == 1500, f"attendu 1500, obtenu {a.remaining()}"


def test_A12_trou_reinitialiser_en_pause_courte():
    a, clock, _ = make_fast(work=1, short=3)
    complete_work(a, clock)
    assert a.phase() == "pause courte"
    a.start()
    clock.advance(50)
    a.reset()
    assert a.phase() == "pause courte", f"attendu 'pause courte', obtenu {a.phase()!r}"
    assert a.remaining() == 180, f"attendu 180, obtenu {a.remaining()}"


def test_A13_reinitialiser_laisse_historique():
    a, clock, _ = make_fast(work=1)
    complete_work(a, clock)
    run_current_phase(a, clock)  # pause courte
    assert a.phase() == "travail"
    before = a.history()
    a.start()
    clock.advance(30)
    a.reset()
    assert a.history() == before, f"attendu {before!r}, obtenu {a.history()!r}"
    clock.advance(120)
    assert a.history() == before, f"après réinitialisation, attendu {before!r}, obtenu {a.history()!r}"


# ---------------------------------------------------------------- A14–A20


def test_A14_zero_en_travail_incremente_cycles():
    a, clock, _ = make_fast(work=1)
    a.start()
    clock.advance(59)
    assert a.cycles() == 0, f"avant zéro, attendu 0, obtenu {a.cycles()}"
    clock.advance(1)
    assert a.cycles() == 1, f"à zéro, attendu 1, obtenu {a.cycles()}"


def test_A14_pas_dincrement_double():
    a, clock, _ = make_fast(work=1)
    a.start()
    clock.advance(60)
    for _ in range(5):
        a.cycles()
    clock.advance(600)
    assert a.cycles() == 1, f"attendu 1, obtenu {a.cycles()}"


def test_A15_cycle_non_multiple_pause_courte():
    a, clock, _ = make_fast(interval=4)
    complete_work(a, clock)
    assert a.cycles() == 1
    assert a.phase() == "pause courte", f"attendu 'pause courte', obtenu {a.phase()!r}"


def test_A16_cycle_multiple_pause_longue():
    a, clock, _ = make_fast(interval=2)
    complete_work(a, clock)
    assert a.phase() == "pause courte"
    complete_work(a, clock)
    assert a.cycles() == 2
    assert a.phase() == "pause longue", f"attendu 'pause longue', obtenu {a.phase()!r}"


def test_A16_quatrieme_cycle_pause_longue_intervalle_4():
    a, clock, _ = make_fast(interval=4)
    phases = []
    for _ in range(4):
        complete_work(a, clock)
        phases.append(a.phase())
    assert phases == ["pause courte", "pause courte", "pause courte", "pause longue"], (
        f"obtenu {phases}"
    )


def test_A17_fin_pause_courte_retour_travail():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    assert a.phase() == "pause courte"
    run_current_phase(a, clock)
    assert a.phase() == "travail", f"attendu 'travail', obtenu {a.phase()!r}"


def test_A18_fin_pause_longue_retour_travail():
    a, clock, _ = make_fast(interval=1)
    complete_work(a, clock)
    assert a.phase() == "pause longue"
    run_current_phase(a, clock)
    assert a.phase() == "travail", f"attendu 'travail', obtenu {a.phase()!r}"


def test_A19_pause_courte_temps_restant_duree_pause():
    a, clock, _ = make_fast(short=3, long=7)
    complete_work(a, clock)
    assert a.phase() == "pause courte"
    assert a.remaining() == 180, f"attendu 180, obtenu {a.remaining()}"


def test_A20_pause_longue_temps_restant_duree_longue():
    a, clock, _ = make_fast(short=3, long=7, interval=1)
    complete_work(a, clock)
    assert a.phase() == "pause longue"
    assert a.remaining() == 420, f"attendu 420, obtenu {a.remaining()}"


# ---------------------------------------------------------------- A21–A22


def test_A21_sans_demarrage_auto_arrete_a_zero():
    a, clock, _ = make_fast()
    a.start()
    clock.advance(60)
    assert a.status() == "arrêté", f"attendu 'arrêté', obtenu {a.status()!r}"
    clock.advance(30)
    assert a.remaining() == 60, f"arrêté en pause courte : attendu 60, obtenu {a.remaining()}"


def test_A22_avec_demarrage_auto_reste_en_cours():
    a, clock, _ = make_fast(short=3)
    a.set_auto_start(True)
    a.start()
    clock.advance(60)
    assert a.status() == "en cours", f"attendu 'en cours', obtenu {a.status()!r}"
    assert a.phase() == "pause courte"
    clock.advance(10)
    assert a.remaining() == 170, f"la pause doit s'écouler : attendu 170, obtenu {a.remaining()}"


def test_A22_trou_debordement_reporte_sur_phase_suivante():
    a, clock, _ = make_fast(short=3)
    a.set_auto_start(True)
    a.start()
    a.go_background()
    clock.advance(90)
    a.go_foreground()
    assert a.phase() == "pause courte", f"attendu 'pause courte', obtenu {a.phase()!r}"
    assert a.status() == "en cours"
    assert a.remaining() == 150, f"attendu 180-30=150, obtenu {a.remaining()}"


# ---------------------------------------------------------------- A23–A24


def test_A23_passer_depuis_travail_va_en_pause():
    a, _, _ = make_fast(interval=4)
    a.skip()
    assert a.phase() in ("pause courte", "pause longue"), f"obtenu {a.phase()!r}"


def test_A23_trou_zero_cycles_pause_courte():
    a, _, _ = make_fast(interval=4)
    assert a.cycles() == 0
    a.skip()
    assert a.phase() == "pause courte", f"attendu 'pause courte', obtenu {a.phase()!r}"


def test_A23_trou_multiple_non_nul_pause_longue():
    a, clock, _ = make_fast(interval=2)
    complete_work(a, clock)
    complete_work(a, clock)
    assert a.cycles() == 2
    run_current_phase(a, clock)  # pause longue
    assert a.phase() == "travail"
    a.skip()
    assert a.phase() == "pause longue", f"attendu 'pause longue', obtenu {a.phase()!r}"


def test_A24_passer_laisse_cycles():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    run_current_phase(a, clock)
    assert a.phase() == "travail"
    a.start()
    clock.advance(10)
    a.skip()
    assert a.cycles() == 1, f"attendu 1, obtenu {a.cycles()}"


def test_A28_trou_passer_najoute_pas_de_session():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(10)
    a.skip()
    clock.advance(5)
    assert a.history() == [], f"attendu historique vide, obtenu {a.history()!r}"
    assert a.today_total() == 0, f"attendu 0, obtenu {a.today_total()}"


# ---------------------------------------------------------------- A25–A27


def test_A25_arrete_travail_modifier_duree_met_temps_restant():
    a, _, _ = make()
    a.set_work_duration(10)
    assert a.remaining() == 600, f"attendu 600, obtenu {a.remaining()}"
    a.set_work_duration(45)
    assert a.remaining() == 2700, f"attendu 2700, obtenu {a.remaining()}"


def test_A25_trou_arrete_en_pause_courte_modifier_duree_travail():
    a, clock, _ = make_fast(work=1, short=3)
    complete_work(a, clock)
    assert a.phase() == "pause courte" and a.status() == "arrêté"
    a.set_work_duration(10)
    assert a.remaining() == 180, f"attendu 180 (pause inchangée), obtenu {a.remaining()}"


def test_A26_en_cours_modifier_duree_laisse_temps_restant():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(20)
    before = a.remaining()
    a.set_work_duration(10)
    assert a.remaining() == before, f"attendu {before}, obtenu {a.remaining()}"
    assert a.work_duration() == 10


def test_A26_trou_en_pause_modifier_duree_laisse_temps_restant():
    a, clock, _ = make_fast(work=25)
    a.start()
    clock.advance(20)
    a.pause()
    a.set_work_duration(10)
    assert a.remaining() == 1480, f"attendu 1480, obtenu {a.remaining()}"


def test_A27_duree_zero_refusee():
    a, _, _ = make()
    a.set_work_duration(25)
    with pytest.raises(ValueError):
        a.set_work_duration(0)
    assert a.work_duration() == 25, f"attendu 25, obtenu {a.work_duration()}"
    assert a.remaining() == 1500, f"attendu 1500, obtenu {a.remaining()}"


def test_A27_trou_duree_negative_refusee():
    a, _, _ = make()
    a.set_work_duration(25)
    with pytest.raises(ValueError):
        a.set_work_duration(-5)
    assert a.work_duration() == 25, f"attendu 25, obtenu {a.work_duration()}"


# ---------------------------------------------------------------- A28–A33


def test_A28_zero_en_travail_ajoute_session():
    a, clock, _ = make_fast()
    assert a.history() == []
    complete_work(a, clock)
    assert len(a.history()) == 1, f"attendu 1 session, obtenu {len(a.history())}"
    complete_work(a, clock)
    assert len(a.history()) == 2, f"attendu 2 sessions, obtenu {len(a.history())}"


def test_A28_pas_de_session_avant_zero():
    a, clock, _ = make_fast()
    a.start()
    clock.advance(59)
    assert a.history() == [], f"attendu vide, obtenu {a.history()!r}"


def test_A29_fin_de_pause_laisse_historique():
    a, clock, _ = make_fast(interval=2)
    complete_work(a, clock)
    before = a.history()
    run_current_phase(a, clock)  # pause courte
    assert a.history() == before, f"pause courte : attendu {before!r}, obtenu {a.history()!r}"
    complete_work(a, clock)
    assert a.phase() == "pause longue"
    before = a.history()
    run_current_phase(a, clock)  # pause longue
    assert a.history() == before, f"pause longue : attendu {before!r}, obtenu {a.history()!r}"


def test_A30_session_rattachee_a_tache_au_demarrage():
    a, clock, _ = make_fast(work=1)
    t1 = a.add_task("Rédiger le résumé")
    t2 = a.add_task("Courriels")
    a.set_active_task(t1)
    a.start()
    clock.advance(30)
    a.set_active_task(t2)
    clock.advance(30)
    hist = a.history()
    assert len(hist) == 1
    assert hist[0]["task"] == "Rédiger le résumé", f"attendu 'Rédiger le résumé', obtenu {hist[0]['task']!r}"


def test_A30_session_simple_tache_active():
    a, clock, _ = make_fast(work=1)
    t = a.add_task("Lire")
    a.set_active_task(t)
    complete_work(a, clock)
    assert a.history()[0]["task"] == "Lire", f"obtenu {a.history()[0]['task']!r}"


def test_A31_aucune_tache_sans_tache():
    a, clock, _ = make_fast()
    assert a.active_task() is None
    complete_work(a, clock)
    assert a.history()[0]["task"] == "sans tâche", f"obtenu {a.history()[0]['task']!r}"


def test_A32_total_jour_augmente_de_duree_travail():
    a, clock, _ = make_fast(work=2)
    assert a.today_total() == 0
    complete_work(a, clock)
    assert a.today_total() == 2, f"attendu 2, obtenu {a.today_total()}"
    complete_work(a, clock)
    assert a.today_total() == 4, f"attendu 4, obtenu {a.today_total()}"


def test_A33_total_tache_augmente_de_duree_travail():
    a, clock, _ = make_fast(work=2)
    t1 = a.add_task("A")
    t2 = a.add_task("B")
    a.set_active_task(t1)
    complete_work(a, clock)
    assert a.task_total(t1) == 2, f"attendu 2, obtenu {a.task_total(t1)}"
    assert a.task_total(t2) == 0, f"attendu 0, obtenu {a.task_total(t2)}"


def test_A33_trou_total_credite_tache_du_demarrage():
    a, clock, _ = make_fast(work=2)
    t1 = a.add_task("A")
    t2 = a.add_task("B")
    a.set_active_task(t1)
    a.start()
    clock.advance(60)
    a.set_active_task(t2)
    clock.advance(60)
    assert a.task_total(t1) == 2, f"attendu 2, obtenu {a.task_total(t1)}"
    assert a.task_total(t2) == 0, f"attendu 0, obtenu {a.task_total(t2)}"


# ---------------------------------------------------------------- A34–A38


def test_A34_changement_de_date_total_jour_zero():
    a, clock, _ = make_fast(work=2)
    complete_work(a, clock)
    assert a.today_total() == 2
    clock.advance(DAY)
    assert a.today_total() == 0, f"nouveau jour : attendu 0, obtenu {a.today_total()}"
    complete_work(a, clock)
    assert a.today_total() == 2, f"nouveau jour + 1 session : attendu 2, obtenu {a.today_total()}"


def test_A34_trou_session_a_cheval_sur_minuit_comptee_le_jour_de_fin():
    a, clock, _ = make_fast(work=20, start=datetime.datetime(2026, 3, 10, 23, 50, 0))
    a.start()
    clock.advance(20 * 60)
    assert clock.now().date() == datetime.date(2026, 3, 11)
    assert a.today_total() == 20, f"attendu 20, obtenu {a.today_total()}"
    assert a.history()[0]["date"] == datetime.date(2026, 3, 11), f"obtenu {a.history()[0]['date']!r}"


def test_A35_session_la_veille_serie_augmente():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    assert a.streak() == 1
    clock.advance(DAY)
    complete_work(a, clock)
    assert a.streak() == 2, f"attendu 2, obtenu {a.streak()}"
    clock.advance(DAY)
    complete_work(a, clock)
    assert a.streak() == 3, f"attendu 3, obtenu {a.streak()}"


def test_A36_premiere_session_serie_1():
    a, clock, _ = make_fast()
    assert a.streak() == 0
    complete_work(a, clock)
    assert a.streak() == 1, f"attendu 1, obtenu {a.streak()}"


def test_A36_trou_dans_les_jours_serie_repart_a_1():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    clock.advance(DAY)
    complete_work(a, clock)
    assert a.streak() == 2
    clock.advance(2 * DAY)
    complete_work(a, clock)
    assert a.streak() == 1, f"attendu 1, obtenu {a.streak()}"


def test_A37_deuxieme_session_du_jour_serie_inchangee():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    clock.advance(DAY)
    complete_work(a, clock)
    assert a.streak() == 2
    complete_work(a, clock)
    assert a.streak() == 2, f"attendu 2, obtenu {a.streak()}"


def test_A38_aucune_session_ni_jour_ni_veille_serie_zero():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    clock.advance(DAY)
    complete_work(a, clock)
    clock.advance(2 * DAY)
    assert a.streak() == 0, f"attendu 0, obtenu {a.streak()}"


def test_A38_trou_serie_affichee_le_lendemain_avant_session():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    clock.advance(DAY)
    assert a.streak() == 1, f"session la veille, aucune aujourd'hui : attendu 1, obtenu {a.streak()}"


# ---------------------------------------------------------------- A39–A40


def test_A39_supprimer_tache_active_met_aucune():
    a, _, _ = make()
    t = a.add_task("A")
    a.set_active_task(t)
    assert a.active_task() == t
    a.delete_task(t)
    assert a.active_task() is None, f"attendu None, obtenu {a.active_task()!r}"


def test_A39_puis_session_sans_tache():
    a, clock, _ = make_fast()
    t = a.add_task("A")
    a.set_active_task(t)
    a.delete_task(t)
    complete_work(a, clock)
    assert a.history()[0]["task"] == "sans tâche", f"obtenu {a.history()[0]['task']!r}"


def test_A40_historique_identique_apres_reouverture():
    a, clock, storage = make_fast()
    t = a.add_task("Écrire")
    a.set_active_task(t)
    complete_work(a, clock)
    a.set_active_task(None)
    complete_work(a, clock)
    before = a.history()
    assert len(before) == 2
    a.close()
    b = app.App(clock=clock, storage=storage)
    assert b.history() == before, f"attendu {before!r}, obtenu {b.history()!r}"


def test_A40_historique_vide_si_autre_stockage():
    a, clock, _ = make_fast()
    complete_work(a, clock)
    a.close()
    b = app.App(clock=clock, storage=app.Storage())
    assert b.history() == [], f"attendu vide, obtenu {b.history()!r}"
