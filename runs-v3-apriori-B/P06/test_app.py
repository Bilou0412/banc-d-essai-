"""Tests rouges de la sonde P06 (minuteur pomodoro).

Interface publique fixée par ces tests (module `app`) :

    app.Horloge(debut: datetime.datetime)
        .maintenant -> datetime.datetime
        .avancer(secondes: int | float) -> None

    app.App(chemin: str, horloge: app.Horloge)
        # état observable
        .phase            -> "travail" | "pause courte" | "pause longue"
        .statut           -> "arrêté" | "en cours" | "en pause"
        .cycles           -> int   (cycles complétés)
        .temps_restant    -> int   (secondes)
        .duree_travail    -> int   (minutes)
        .duree_pause      -> int   (minutes)
        .duree_longue     -> int   (minutes)
        .intervalle_longue -> int
        .demarrage_auto   -> bool
        .tache_active     -> str | None   (None = « aucune »)
        .historique       -> list[Session]  (Session: .tache: str, .date: datetime.date, .duree: int minutes)
        .total_jour       -> int   (minutes)
        .serie_jours      -> int
        .total_tache(nom: str) -> int (minutes)
        # actions
        .demarrer() .pause() .reprendre() .reinitialiser() .passer()
        .arriere_plan() .premier_plan()
        .regler_duree_travail(minutes)   # ValueError si refusé
        .regler_duree_pause(minutes)
        .regler_duree_longue(minutes)
        .regler_intervalle_longue(n)
        .regler_demarrage_auto(actif: bool)
        .ajouter_tache(nom) .supprimer_tache(nom) .choisir_tache(nom | None)
        .fermer()

L'application lit l'horloge à chaque observation : avancer l'horloge puis lire
l'état suffit à faire progresser le minuteur (y compris les passages à zéro).
Les sessions sont datées à la date de leur ajout (arrivée à zéro).
"""

import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app

RACINE = Path(__file__).resolve().parent.parent
DEBUT = datetime.datetime(2026, 11, 19, 9, 0, 0)
JOUR = 24 * 3600


def nouvelle(tmp_path, horloge=None, nom="pomodoro.dat"):
    h = horloge if horloge is not None else app.Horloge(DEBUT)
    a = app.App(str(tmp_path / nom), h)
    return a, h


def finir_phase(a, h):
    """Démarre si nécessaire et laisse le temps restant arriver exactement à zéro."""
    if a.statut == "arrêté":
        a.demarrer()
    elif a.statut == "en pause":
        a.reprendre()
    h.avancer(a.temps_restant)


def finir_travail(a, h):
    assert a.phase == "travail", f"attendu phase travail avant de finir un travail, obtenu {a.phase!r}"
    finir_phase(a, h)


def sessions(a):
    return [(s.tache, s.date, s.duree) for s in a.historique]


# ---------------------------------------------------------------- A01-A03

def test_A01_phase_initiale_travail(tmp_path):
    a, _ = nouvelle(tmp_path)
    assert a.phase == "travail", f"attendu 'travail' au premier lancement, obtenu {a.phase!r}"


def test_A02_statut_initial_arrete(tmp_path):
    a, _ = nouvelle(tmp_path)
    assert a.statut == "arrêté", f"attendu 'arrêté' au premier lancement, obtenu {a.statut!r}"


def test_A03_cycles_initiaux_zero(tmp_path):
    a, _ = nouvelle(tmp_path)
    assert a.cycles == 0, f"attendu 0 cycle au premier lancement, obtenu {a.cycles!r}"


def test_A03_premier_lancement_sur_nouveau_chemin_ignore_une_autre_instance(tmp_path):
    a, h = nouvelle(tmp_path, nom="autre.dat")
    finir_travail(a, h)
    assert a.cycles == 1
    a.fermer()
    b, _ = nouvelle(tmp_path, nom="vierge.dat")
    assert b.cycles == 0, f"un nouveau chemin doit être un premier lancement : attendu 0 cycle, obtenu {b.cycles!r}"
    assert b.phase == "travail", f"attendu 'travail', obtenu {b.phase!r}"
    assert b.historique == [] or len(b.historique) == 0, f"attendu historique vide, obtenu {sessions(b)!r}"


# ---------------------------------------------------------------- A04-A10

def test_A04_temps_restant_arrete_egal_duree_travail(tmp_path):
    a, _ = nouvelle(tmp_path)
    assert a.temps_restant == a.duree_travail * 60, (
        f"attendu {a.duree_travail * 60} s, obtenu {a.temps_restant!r}")


def test_A04_arrete_le_temps_qui_passe_ne_decompte_pas(tmp_path):
    a, h = nouvelle(tmp_path)
    h.avancer(300)
    assert a.temps_restant == a.duree_travail * 60, (
        f"minuteur arrêté : attendu {a.duree_travail * 60} s après 300 s, obtenu {a.temps_restant!r}")


def test_A05_demarrer_passe_en_cours(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.demarrer()
    assert a.statut == "en cours", f"attendu 'en cours', obtenu {a.statut!r}"


def test_A06_une_seconde_diminue_d_une_seconde(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    avant = a.temps_restant
    h.avancer(1)
    assert a.temps_restant == avant - 1, f"attendu {avant - 1}, obtenu {a.temps_restant!r}"


def test_A06_cent_secondes_une_par_une(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    depart = a.temps_restant
    for i in range(1, 101):
        h.avancer(1)
        assert a.temps_restant == depart - i, f"après {i} s attendu {depart - i}, obtenu {a.temps_restant!r}"


def test_A07_en_pause_le_temps_ne_decompte_pas(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(10)
    a.pause()
    avant = a.temps_restant
    h.avancer(1)
    assert a.temps_restant == avant, f"en pause : attendu {avant}, obtenu {a.temps_restant!r}"
    h.avancer(3600)
    assert a.temps_restant == avant, f"en pause 1 h : attendu {avant}, obtenu {a.temps_restant!r}"


def test_A07_reprise_repart_du_temps_fige(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(10)
    a.pause()
    fige = a.temps_restant
    h.avancer(500)
    a.reprendre()
    h.avancer(5)
    assert a.temps_restant == fige - 5, f"attendu {fige - 5}, obtenu {a.temps_restant!r}"


def test_A08_pause_passe_en_pause(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.demarrer()
    a.pause()
    assert a.statut == "en pause", f"attendu 'en pause', obtenu {a.statut!r}"


def test_A09_reprendre_passe_en_cours(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.demarrer()
    a.pause()
    a.reprendre()
    assert a.statut == "en cours", f"attendu 'en cours', obtenu {a.statut!r}"


def test_A10_arriere_plan_60_secondes(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    avant = a.temps_restant
    a.arriere_plan()
    h.avancer(60)
    a.premier_plan()
    assert a.temps_restant == avant - 60, f"attendu {avant - 60} au retour, obtenu {a.temps_restant!r}"


def test_A14_arriere_plan_traverse_le_zero(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    a.arriere_plan()
    h.avancer(a.duree_travail * 60)
    a.premier_plan()
    assert a.cycles == 1, f"zéro atteint en arrière-plan : attendu 1 cycle, obtenu {a.cycles!r}"


# ---------------------------------------------------------------- A11-A13

def test_A11_reinitialiser_depuis_en_cours(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(5)
    a.reinitialiser()
    assert a.statut == "arrêté", f"attendu 'arrêté', obtenu {a.statut!r}"


def test_A11_reinitialiser_depuis_en_pause(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    a.pause()
    a.reinitialiser()
    assert a.statut == "arrêté", f"attendu 'arrêté', obtenu {a.statut!r}"


def test_A11_reinitialiser_puis_le_temps_ne_decompte_plus(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(5)
    a.reinitialiser()
    h.avancer(100)
    assert a.temps_restant == a.duree_travail * 60, (
        f"après réinitialiser, attendu {a.duree_travail * 60}, obtenu {a.temps_restant!r}")


def test_A12_reinitialiser_remet_duree_travail(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(100)
    a.reinitialiser()
    assert a.temps_restant == a.duree_travail * 60, (
        f"attendu {a.duree_travail * 60}, obtenu {a.temps_restant!r}")


def test_A13_reinitialiser_laisse_historique(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    finir_phase(a, h)  # pause courte -> travail
    assert a.phase == "travail"
    avant = sessions(a)
    a.demarrer()
    h.avancer(a.duree_travail * 60 - 1)
    a.reinitialiser()
    assert sessions(a) == avant, f"attendu historique {avant!r}, obtenu {sessions(a)!r}"


# ---------------------------------------------------------------- A14-A22

def test_A14_zero_augmente_cycles_de_un(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(a.duree_travail * 60 - 1)
    assert a.cycles == 0, f"une seconde avant zéro : attendu 0, obtenu {a.cycles!r}"
    h.avancer(1)
    assert a.cycles == 1, f"à zéro : attendu 1, obtenu {a.cycles!r}"


def test_A14_deux_travaux_deux_cycles(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(4)
    finir_travail(a, h)
    finir_phase(a, h)
    finir_travail(a, h)
    assert a.cycles == 2, f"attendu 2, obtenu {a.cycles!r}"


def test_A15_non_multiple_pause_courte(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(4)
    finir_travail(a, h)
    assert a.phase == "pause courte", f"cycles=1, intervalle=4 : attendu 'pause courte', obtenu {a.phase!r}"


def test_A16_multiple_pause_longue(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(2)
    finir_travail(a, h)
    assert a.phase == "pause courte", f"cycles=1 : attendu 'pause courte', obtenu {a.phase!r}"
    finir_phase(a, h)
    finir_travail(a, h)
    assert a.cycles == 2
    assert a.phase == "pause longue", f"cycles=2, intervalle=2 : attendu 'pause longue', obtenu {a.phase!r}"


def test_A16_intervalle_un_toujours_pause_longue(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(1)
    finir_travail(a, h)
    assert a.phase == "pause longue", f"intervalle=1 : attendu 'pause longue', obtenu {a.phase!r}"


def test_A17_fin_pause_courte_vers_travail(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(4)
    finir_travail(a, h)
    assert a.phase == "pause courte"
    finir_phase(a, h)
    assert a.phase == "travail", f"attendu 'travail', obtenu {a.phase!r}"


def test_A18_fin_pause_longue_vers_travail(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(1)
    finir_travail(a, h)
    assert a.phase == "pause longue"
    finir_phase(a, h)
    assert a.phase == "travail", f"attendu 'travail', obtenu {a.phase!r}"


def test_A19_pause_courte_temps_egal_duree_pause(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(4)
    a.regler_duree_pause(7)
    finir_travail(a, h)
    assert a.temps_restant == 7 * 60, f"attendu {7 * 60}, obtenu {a.temps_restant!r}"


def test_A19_trou_arrete_ne_decompte_pas(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_demarrage_auto(False)
    a.regler_intervalle_longue(4)
    a.regler_duree_pause(7)
    finir_travail(a, h)
    h.avancer(120)
    assert a.temps_restant == 7 * 60, (
        f"pause courte arrêtée : attendu {7 * 60} après 120 s, obtenu {a.temps_restant!r}")


def test_A20_pause_longue_temps_egal_duree_longue(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(1)
    a.regler_duree_longue(20)
    finir_travail(a, h)
    assert a.temps_restant == 20 * 60, f"attendu {20 * 60}, obtenu {a.temps_restant!r}"


def test_A21_auto_desactive_arrete(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_demarrage_auto(False)
    finir_travail(a, h)
    assert a.statut == "arrêté", f"attendu 'arrêté', obtenu {a.statut!r}"


def test_A21_auto_desactive_fin_de_pause_arrete(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_demarrage_auto(False)
    a.regler_intervalle_longue(4)
    finir_travail(a, h)
    finir_phase(a, h)
    assert a.statut == "arrêté", f"attendu 'arrêté', obtenu {a.statut!r}"
    assert a.temps_restant == a.duree_travail * 60


def test_A22_auto_active_reste_en_cours(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_demarrage_auto(True)
    a.regler_intervalle_longue(4)
    finir_travail(a, h)
    assert a.statut == "en cours", f"attendu 'en cours', obtenu {a.statut!r}"
    assert a.phase == "pause courte", f"attendu 'pause courte', obtenu {a.phase!r}"
    h.avancer(1)
    assert a.temps_restant == a.duree_pause * 60 - 1, (
        f"la pause doit décompter : attendu {a.duree_pause * 60 - 1}, obtenu {a.temps_restant!r}")


def test_A22_trou_debordement(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_demarrage_auto(True)
    a.regler_intervalle_longue(4)
    a.demarrer()
    a.arriere_plan()
    h.avancer(a.duree_travail * 60 + 30)
    a.premier_plan()
    assert a.phase == "pause courte", f"attendu 'pause courte', obtenu {a.phase!r}"
    assert a.temps_restant == a.duree_pause * 60 - 30, (
        f"les 30 s de débordement comptent sur la pause : attendu {a.duree_pause * 60 - 30}, "
        f"obtenu {a.temps_restant!r}")


# ---------------------------------------------------------------- A23-A24

def test_A23_passer_pause_courte(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(4)
    finir_travail(a, h)
    finir_phase(a, h)
    assert a.cycles == 1 and a.phase == "travail"
    a.passer()
    assert a.phase == "pause courte", f"cycles=1, intervalle=4 : attendu 'pause courte', obtenu {a.phase!r}"


def test_A23_trou_cycle_a_venir(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(2)
    finir_travail(a, h)
    finir_phase(a, h)
    assert a.cycles == 1 and a.phase == "travail"
    a.passer()
    assert a.phase == "pause longue", (
        f"cycles=1, intervalle=2 : le cycle passé serait le 2e -> attendu 'pause longue', obtenu {a.phase!r}")


def test_A24_passer_laisse_cycles(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(10)
    a.passer()
    assert a.cycles == 0, f"attendu 0, obtenu {a.cycles!r}"


def test_A24_passer_n_ajoute_pas_de_session(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    a.passer()
    assert sessions(a) == [], f"attendu historique vide, obtenu {sessions(a)!r}"


# ---------------------------------------------------------------- A25-A27

def test_A25_arrete_modifier_duree_travail(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.regler_duree_travail(10)
    assert a.duree_travail == 10
    assert a.temps_restant == 600, f"attendu 600, obtenu {a.temps_restant!r}"


def test_A26_en_cours_modifier_duree_travail(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(20)
    avant = a.temps_restant
    a.regler_duree_travail(a.duree_travail + 5)
    assert a.temps_restant == avant, f"attendu {avant}, obtenu {a.temps_restant!r}"


def test_A26_trou_en_pause(tmp_path):
    a, h = nouvelle(tmp_path)
    a.demarrer()
    h.avancer(20)
    a.pause()
    avant = a.temps_restant
    a.regler_duree_travail(a.duree_travail + 5)
    assert a.temps_restant == avant, f"en pause : attendu {avant}, obtenu {a.temps_restant!r}"


def test_A27_zero_minute_refuse(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.regler_duree_travail(12)
    with pytest.raises(ValueError):
        a.regler_duree_travail(0)
    assert a.duree_travail == 12, f"attendu 12, obtenu {a.duree_travail!r}"
    assert a.temps_restant == 12 * 60, f"attendu {12 * 60}, obtenu {a.temps_restant!r}"


def test_A27_trou_negative(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.regler_duree_travail(12)
    with pytest.raises(ValueError):
        a.regler_duree_travail(-5)
    assert a.duree_travail == 12, f"attendu 12, obtenu {a.duree_travail!r}"


# ---------------------------------------------------------------- A28-A33

def test_A28_zero_travail_ajoute_une_session(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    assert len(a.historique) == 1, f"attendu 1 session, obtenu {sessions(a)!r}"
    s = a.historique[0]
    assert s.date == DEBUT.date(), f"attendu date {DEBUT.date()}, obtenu {s.date!r}"
    assert s.duree == a.duree_travail, f"attendu durée {a.duree_travail}, obtenu {s.duree!r}"


def test_A29_fin_pause_courte_historique_inchange(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(4)
    finir_travail(a, h)
    avant = sessions(a)
    finir_phase(a, h)
    assert sessions(a) == avant, f"attendu {avant!r}, obtenu {sessions(a)!r}"


def test_A29_fin_pause_longue_historique_inchange(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_intervalle_longue(1)
    finir_travail(a, h)
    assert a.phase == "pause longue"
    avant = sessions(a)
    finir_phase(a, h)
    assert sessions(a) == avant, f"attendu {avant!r}, obtenu {sessions(a)!r}"


def test_A30_session_rattachee_a_la_tache_au_demarrage(tmp_path):
    a, h = nouvelle(tmp_path)
    a.ajouter_tache("Rapport")
    a.ajouter_tache("Courriel")
    a.choisir_tache("Rapport")
    a.demarrer()
    h.avancer(30)
    a.choisir_tache("Courriel")
    h.avancer(a.temps_restant)
    assert [s.tache for s in a.historique] == ["Rapport"], (
        f"attendu ['Rapport'], obtenu {[s.tache for s in a.historique]!r}")


def test_A30_tache_non_ascii(tmp_path):
    a, h = nouvelle(tmp_path)
    a.ajouter_tache("Révision — 日本語")
    a.choisir_tache("Révision — 日本語")
    finir_travail(a, h)
    assert a.historique[0].tache == "Révision — 日本語", f"obtenu {a.historique[0].tache!r}"


def test_A31_sans_tache(tmp_path):
    a, h = nouvelle(tmp_path)
    assert a.tache_active is None, f"attendu aucune tâche active (None), obtenu {a.tache_active!r}"
    finir_travail(a, h)
    assert [s.tache for s in a.historique] == ["sans tâche"], (
        f"attendu ['sans tâche'], obtenu {[s.tache for s in a.historique]!r}")


def test_A32_total_jour_augmente_de_duree_travail(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_duree_travail(10)
    assert a.total_jour == 0
    finir_travail(a, h)
    assert a.total_jour == 10, f"attendu 10 min, obtenu {a.total_jour!r}"
    finir_phase(a, h)
    finir_travail(a, h)
    assert a.total_jour == 20, f"attendu 20 min, obtenu {a.total_jour!r}"


def test_A33_total_tache_augmente(tmp_path):
    a, h = nouvelle(tmp_path)
    a.regler_duree_travail(10)
    a.ajouter_tache("Rapport")
    a.ajouter_tache("Courriel")
    a.choisir_tache("Rapport")
    finir_travail(a, h)
    assert a.total_tache("Rapport") == 10, f"attendu 10, obtenu {a.total_tache('Rapport')!r}"
    assert a.total_tache("Courriel") == 0, f"attendu 0, obtenu {a.total_tache('Courriel')!r}"


# ---------------------------------------------------------------- A34-A38

def test_A34_changement_de_date_total_jour_zero(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    assert a.total_jour > 0
    a.reinitialiser()
    h.avancer(JOUR)
    assert a.total_jour == 0, f"nouveau jour : attendu 0, obtenu {a.total_jour!r}"


def test_A35_veille_serie_plus_un(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    assert a.serie_jours == 1, f"premier jour : attendu 1, obtenu {a.serie_jours!r}"
    a.reinitialiser()
    h.avancer(JOUR)
    if a.phase != "travail":
        a.passer()
    a.reinitialiser()
    finir_travail(a, h)
    assert a.serie_jours == 2, f"lendemain : attendu 2, obtenu {a.serie_jours!r}"


def test_A35_trou_minuit(tmp_path):
    h = app.Horloge(datetime.datetime(2026, 11, 19, 9, 0, 0))
    a, _ = nouvelle(tmp_path, horloge=h)
    finir_travail(a, h)  # session le 19
    a.reinitialiser()
    if a.phase != "travail":
        a.passer()
    a.reinitialiser()
    # avancer jusqu'au 19 à 23:50
    cible = datetime.datetime(2026, 11, 19, 23, 50, 0)
    h.avancer((cible - h.maintenant).total_seconds())
    a.regler_duree_travail(25)
    finir_travail(a, h)  # se termine le 20 à 00:15
    assert a.historique[-1].date == datetime.date(2026, 11, 20), (
        f"session datée de son ajout : attendu 2026-11-20, obtenu {a.historique[-1].date!r}")
    assert a.serie_jours == 2, f"attendu 2, obtenu {a.serie_jours!r}"


def test_A36_pas_de_veille_serie_a_un(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    a.reinitialiser()
    if a.phase != "travail":
        a.passer()
    a.reinitialiser()
    h.avancer(2 * JOUR)
    finir_travail(a, h)
    assert a.serie_jours == 1, f"trou d'un jour : attendu 1, obtenu {a.serie_jours!r}"


def test_A37_deuxieme_session_du_jour_serie_inchangee(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    serie = a.serie_jours
    finir_phase(a, h)
    finir_travail(a, h)
    assert len(a.historique) == 2
    assert a.serie_jours == serie, f"attendu {serie}, obtenu {a.serie_jours!r}"


def test_A38_ni_aujourd_hui_ni_veille_serie_zero(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    assert a.serie_jours == 1
    a.reinitialiser()
    h.avancer(2 * JOUR)
    assert a.serie_jours == 0, f"aucune session ni aujourd'hui ni hier : attendu 0, obtenu {a.serie_jours!r}"


def test_A38_historique_vide_serie_zero(tmp_path):
    a, _ = nouvelle(tmp_path)
    assert a.serie_jours == 0, f"attendu 0, obtenu {a.serie_jours!r}"


# ---------------------------------------------------------------- A39

def test_A39_supprimer_tache_active(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.ajouter_tache("Rapport")
    a.choisir_tache("Rapport")
    a.supprimer_tache("Rapport")
    assert a.tache_active is None, f"attendu None (aucune), obtenu {a.tache_active!r}"


def test_A39_supprimer_autre_tache_garde_active(tmp_path):
    a, _ = nouvelle(tmp_path)
    a.ajouter_tache("Rapport")
    a.ajouter_tache("Courriel")
    a.choisir_tache("Rapport")
    a.supprimer_tache("Courriel")
    assert a.tache_active == "Rapport", f"attendu 'Rapport', obtenu {a.tache_active!r}"


# ---------------------------------------------------------------- A40 (persistance réelle)

def _remplir(a, h):
    a.regler_intervalle_longue(4)
    a.ajouter_tache("Rapport")
    a.choisir_tache("Rapport")
    finir_travail(a, h)
    finir_phase(a, h)
    a.choisir_tache(None)
    finir_travail(a, h)
    a.reinitialiser()
    h.avancer(JOUR)
    if a.phase != "travail":
        a.passer()
    a.reinitialiser()
    a.ajouter_tache("Été ✓")
    a.choisir_tache("Été ✓")
    finir_travail(a, h)


def test_A40_reouverture_meme_historique(tmp_path):
    a, h = nouvelle(tmp_path)
    _remplir(a, h)
    avant = sessions(a)
    assert len(avant) == 3
    a.fermer()
    b, _ = nouvelle(tmp_path, horloge=app.Horloge(h.maintenant))
    assert sessions(b) == avant, f"attendu {avant!r}, obtenu {sessions(b)!r}"


def test_A40_fichier_ecrit_sur_disque(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    a.fermer()
    chemin = tmp_path / "pomodoro.dat"
    assert chemin.exists(), f"attendu un fichier à {chemin}, absent"
    assert chemin.stat().st_size > 0, "attendu un fichier non vide"


def test_A40_fichier_supprime_historique_vide(tmp_path):
    a, h = nouvelle(tmp_path)
    finir_travail(a, h)
    a.fermer()
    os.remove(tmp_path / "pomodoro.dat")
    b, _ = nouvelle(tmp_path, horloge=app.Horloge(h.maintenant))
    assert sessions(b) == [], f"sans fichier, rien ne doit survivre en mémoire ; obtenu {sessions(b)!r}"


def test_A40_relu_par_un_autre_processus(tmp_path):
    a, h = nouvelle(tmp_path)
    _remplir(a, h)
    avant = [(t, d.isoformat(), du) for (t, d, du) in sessions(a)]
    a.fermer()
    chemin = str(tmp_path / "pomodoro.dat")
    code = (
        "import sys, datetime\n"
        f"sys.path.insert(0, {str(RACINE)!r})\n"
        "import app\n"
        f"a = app.App({chemin!r}, app.Horloge(datetime.datetime(2026, 11, 25, 9, 0, 0)))\n"
        "print(repr([(s.tache, s.date.isoformat(), s.duree) for s in a.historique]))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(RACINE),
                       capture_output=True, text=True, timeout=15,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, f"le processus neuf a échoué : {r.stderr}"
    obtenu = eval(r.stdout.strip())
    assert obtenu == avant, f"processus neuf : attendu {avant!r}, obtenu {obtenu!r}"


def test_A40_deux_chemins_independants(tmp_path):
    a, h = nouvelle(tmp_path, nom="un.dat")
    finir_travail(a, h)
    a.fermer()
    b, _ = nouvelle(tmp_path, horloge=app.Horloge(h.maintenant), nom="deux.dat")
    assert sessions(b) == [], f"attendu historique vide sur un autre chemin, obtenu {sessions(b)!r}"
