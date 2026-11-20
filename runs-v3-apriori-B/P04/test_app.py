"""Tests rouges — sonde P04 (listes de tâches).

Interface publique fixée par ces tests (module `app`) :

    h = app.Horloge(datetime)            # horloge que les tests font avancer
    h.avancer(timedelta)
    h.maintenant() -> datetime
    s = app.Stockage()                   # stockage en mémoire, survit au rechargement
    a = app.Application(stockage=s, horloge=h)   # « ouvrir / recharger » l'application

    Listes :
    a.creer_liste(nom) -> id_liste | None
    a.listes() -> list[id_liste]
    a.nom_liste(id_liste) -> str
    a.renommer_liste(id_liste, nom)
    a.supprimer_liste(id_liste)
    a.selectionner_liste(id_liste)
    a.liste_active() -> id_liste | None

    Tâches :
    a.ajouter_tache(titre) -> id_tache | None     (dans la liste active)
    a.taches() -> list[id_tache]                  (toutes listes confondues)
    a.affichage() -> list[id_tache]               (liste active, filtre, tri appliqués)
    a.liste_de(id_tache) -> id_liste
    a.titre(id_tache) -> str
    a.modifier_titre(id_tache, texte)
    a.est_cochee(id_tache) -> bool
    a.cocher(id_tache) / a.decocher(id_tache)
    a.compteur() -> int
    a.deplacer(id_tache, id_liste)
    a.supprimer_tache(id_tache)
    a.echeance(id_tache) -> datetime.date | None
    a.definir_echeance(id_tache, date) / a.retirer_echeance(id_tache)
    a.en_retard(id_tache) -> bool
    a.definir_filtre("toutes" | "actives" | "terminees" | "en_retard")
    a.definir_tri("manuel" | "echeance")
    a.glisser(id_tache, position)   # position 0-based dans l'affichage
"""
from datetime import date, datetime, timedelta

import app


DEBUT = datetime(2026, 3, 10, 12, 0, 0)


def ouvrir(stockage=None, horloge=None):
    if stockage is None:
        stockage = app.Stockage()
    if horloge is None:
        horloge = app.Horloge(DEBUT)
    return app.Application(stockage=stockage, horloge=horloge), stockage, horloge


def app_avec_liste(nom="Courses"):
    a, s, h = ouvrir()
    lid = a.creer_liste(nom)
    assert lid is not None, f"creer_liste({nom!r}) devait réussir, obtenu None"
    a.definir_filtre("toutes")
    a.definir_tri("manuel")
    return a, s, h, lid


def titres(a, ids):
    return [a.titre(t) for t in ids]


def liste_par_nom(a, nom):
    trouvees = [l for l in a.listes() if a.nom_liste(l) == nom]
    assert len(trouvees) == 1, f"attendu une liste nommée {nom!r}, obtenu {len(trouvees)}"
    return trouvees[0]


# ---------------------------------------------------------------- A01-A04

def test_A01_creer_liste_nom_non_vide_ajoute_liste():
    a, _, _ = ouvrir()
    avant = list(a.listes())
    lid = a.creer_liste("Courses")
    apres = a.listes()
    assert len(apres) == len(avant) + 1, f"attendu {len(avant)+1} listes, obtenu {len(apres)}"
    assert lid in apres
    assert a.nom_liste(lid) == "Courses"


def test_A01_deux_listes_distinctes_coexistent():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    l2 = a.creer_liste("Travail")
    assert l1 != l2
    assert set([l1, l2]) <= set(a.listes())


def test_A02_nom_vide_ou_espaces_n_ajoute_aucune_liste():
    a, _, _ = ouvrir()
    avant = list(a.listes())
    for nom in ["", " ", "   ", "\t", " \n "]:
        r = a.creer_liste(nom)
        assert r is None, f"creer_liste({nom!r}) devait renvoyer None, obtenu {r!r}"
    assert a.listes() == avant, f"attendu {avant}, obtenu {a.listes()}"


def test_A03_nom_deja_porte_n_ajoute_aucune_liste():
    a, _, _ = ouvrir()
    a.creer_liste("Courses")
    avant = list(a.listes())
    r = a.creer_liste("Courses")
    assert r is None, f"doublon devait renvoyer None, obtenu {r!r}"
    assert a.listes() == avant


def test_A03_nom_libere_apres_suppression_est_reutilisable():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    a.creer_liste("Autre")
    a.supprimer_liste(l1)
    assert a.creer_liste("Courses") is not None, "le nom d'une liste supprimée doit redevenir libre"


def test_A04_liste_creee_devient_active():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    assert a.liste_active() == l1
    l2 = a.creer_liste("Travail")
    assert a.liste_active() == l2, f"attendu {l2}, obtenu {a.liste_active()}"


def test_A04_creation_refusee_ne_change_pas_liste_active():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    a.creer_liste("Courses")
    a.creer_liste("  ")
    assert a.liste_active() == l1


# ---------------------------------------------------------------- A05-A09

def test_A05_renommer_remplace_nom():
    a, _, _, lid = app_avec_liste("Courses")
    a.renommer_liste(lid, "Marché")
    assert a.nom_liste(lid) == "Marché", f"obtenu {a.nom_liste(lid)!r}"
    assert lid in a.listes()


def test_A05_trou_nom_vide():
    a, _, _, lid = app_avec_liste("Courses")
    a.renommer_liste(lid, "")
    a.renommer_liste(lid, "   ")
    assert a.nom_liste(lid) == "Courses", f"obtenu {a.nom_liste(lid)!r}"


def test_A05_trou_nom_duplique():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    l2 = a.creer_liste("Travail")
    a.renommer_liste(l2, "Courses")
    assert a.nom_liste(l2) == "Travail", f"obtenu {a.nom_liste(l2)!r}"
    assert a.nom_liste(l1) == "Courses"


def test_A06_supprimer_liste_la_retire():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    l2 = a.creer_liste("Travail")
    a.supprimer_liste(l1)
    assert l1 not in a.listes()
    assert l2 in a.listes()


def test_A07_supprimer_liste_supprime_ses_taches():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    t1 = a.ajouter_tache("Pain")
    t2 = a.ajouter_tache("Lait")
    a.creer_liste("Travail")
    t3 = a.ajouter_tache("Rapport")
    a.supprimer_liste(l1)
    restantes = a.taches()
    assert t1 not in restantes and t2 not in restantes, f"obtenu {restantes}"
    assert t3 in restantes, "les tâches des autres listes doivent rester"


def test_A08_supprimer_active_rend_active_une_autre():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    l2 = a.creer_liste("Travail")
    l3 = a.creer_liste("Maison")
    assert a.liste_active() == l3
    a.supprimer_liste(l3)
    assert a.liste_active() in (l1, l2), f"obtenu {a.liste_active()}"


def test_A08_trou_derniere_liste():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    a.supprimer_liste(l1)
    assert a.listes() == []
    assert a.liste_active() is None, f"obtenu {a.liste_active()}"


def test_A08_supprimer_non_active_laisse_active():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    l2 = a.creer_liste("Travail")
    a.supprimer_liste(l1)
    assert a.liste_active() == l2


def test_A09_selectionner_rend_active():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    a.creer_liste("Travail")
    a.selectionner_liste(l1)
    assert a.liste_active() == l1


# ---------------------------------------------------------------- A10-A15

def test_A10_seules_taches_de_liste_active_affichees():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    a.definir_filtre("toutes")
    a.definir_tri("manuel")
    t1 = a.ajouter_tache("Pain")
    l2 = a.creer_liste("Travail")
    t2 = a.ajouter_tache("Rapport")
    assert a.affichage() == [t2], f"attendu [{t2}], obtenu {a.affichage()}"
    a.selectionner_liste(l1)
    assert a.affichage() == [t1], f"attendu [{t1}], obtenu {a.affichage()}"
    a.selectionner_liste(l2)
    assert a.affichage() == [t2]


def test_A11_ajouter_tache_rattachee_liste_active():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    l2 = a.creer_liste("Travail")
    a.selectionner_liste(l1)
    t = a.ajouter_tache("Pain")
    assert t is not None
    assert a.liste_de(t) == l1, f"attendu {l1}, obtenu {a.liste_de(t)}"
    assert a.titre(t) == "Pain"
    assert t in a.taches()


def test_A11_trou_sans_liste_active():
    a, _, _ = ouvrir()
    r = a.ajouter_tache("Pain")
    assert r is None, f"sans liste active, attendu None, obtenu {r!r}"
    assert a.taches() == []


def test_A12_titre_vide_ou_espaces_ne_cree_rien():
    a, _, _, _ = app_avec_liste()
    for titre in ["", " ", "   ", "\t\n"]:
        r = a.ajouter_tache(titre)
        assert r is None, f"ajouter_tache({titre!r}) devait renvoyer None, obtenu {r!r}"
    assert a.taches() == [], f"obtenu {a.taches()}"
    assert a.affichage() == []


def test_A13_tache_ajoutee_non_cochee():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("Pain")
    assert a.est_cochee(t) is False


def test_A14_tache_ajoutee_sans_echeance():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("Pain")
    assert a.echeance(t) is None


def test_A15_tri_manuel_tache_ajoutee_en_derniere_position():
    a, _, _, _ = app_avec_liste()
    t1 = a.ajouter_tache("A")
    t2 = a.ajouter_tache("B")
    t3 = a.ajouter_tache("C")
    assert a.affichage() == [t1, t2, t3], f"obtenu {titres(a, a.affichage())}"
    a.glisser(t3, 0)
    t4 = a.ajouter_tache("D")
    assert a.affichage()[-1] == t4, f"obtenu {titres(a, a.affichage())}"


# ---------------------------------------------------------------- A16-A21

def test_A16_cocher_rend_cochee():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("Pain")
    a.cocher(t)
    assert a.est_cochee(t) is True


def test_A17_decocher_rend_non_cochee():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("Pain")
    a.cocher(t)
    a.decocher(t)
    assert a.est_cochee(t) is False


def test_A18_cocher_diminue_compteur_de_un():
    a, _, _, _ = app_avec_liste()
    t1 = a.ajouter_tache("A")
    a.ajouter_tache("B")
    a.ajouter_tache("C")
    avant = a.compteur()
    a.cocher(t1)
    assert a.compteur() == avant - 1, f"attendu {avant-1}, obtenu {a.compteur()}"


def test_A18_trou_cocher_deja_cochee():
    a, _, _, _ = app_avec_liste()
    t1 = a.ajouter_tache("A")
    a.ajouter_tache("B")
    a.cocher(t1)
    avant = a.compteur()
    a.cocher(t1)
    assert a.compteur() == avant, f"attendu {avant}, obtenu {a.compteur()}"
    assert a.est_cochee(t1) is True


def test_A19_compteur_non_cochees_liste_active():
    a, _, _ = ouvrir()
    l1 = a.creer_liste("Courses")
    a1 = a.ajouter_tache("A1")
    a.ajouter_tache("A2")
    a.ajouter_tache("A3")
    a.cocher(a1)
    l2 = a.creer_liste("Travail")
    a.ajouter_tache("B1")
    assert a.compteur() == 1, f"liste Travail : attendu 1, obtenu {a.compteur()}"
    a.selectionner_liste(l1)
    assert a.compteur() == 2, f"liste Courses : attendu 2, obtenu {a.compteur()}"
    a.decocher(a1)
    assert a.compteur() == 3


def test_A19_compteur_independant_du_filtre():
    a, _, _, _ = app_avec_liste()
    t1 = a.ajouter_tache("A")
    a.ajouter_tache("B")
    a.cocher(t1)
    a.definir_filtre("terminees")
    assert a.compteur() == 1, f"obtenu {a.compteur()}"


def test_A20_modifier_titre_remplace():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("Pain")
    a.modifier_titre(t, "Pain complet")
    assert a.titre(t) == "Pain complet"


def test_A21_titre_vide_laisse_inchange():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("Pain")
    a.modifier_titre(t, "")
    assert a.titre(t) == "Pain", f"obtenu {a.titre(t)!r}"


def test_A21_trou_espaces():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("Pain")
    a.modifier_titre(t, "   ")
    assert a.titre(t) == "Pain", f"obtenu {a.titre(t)!r}"


# ---------------------------------------------------------------- A22-A27

def _deux_listes_avec_tache():
    a, s, h = ouvrir()
    l1 = a.creer_liste("Courses")
    a.definir_filtre("toutes")
    a.definir_tri("manuel")
    t = a.ajouter_tache("Pain")
    l2 = a.creer_liste("Travail")
    a.selectionner_liste(l1)
    return a, l1, l2, t


def test_A22_deplacer_rattache_liste_cible():
    a, l1, l2, t = _deux_listes_avec_tache()
    a.deplacer(t, l2)
    assert a.liste_de(t) == l2
    assert t not in a.affichage(), "la tâche ne doit plus apparaître dans la liste source"
    a.selectionner_liste(l2)
    assert t in a.affichage()


def test_A22_trou_position_dans_cible():
    a, l1, l2, t = _deux_listes_avec_tache()
    a.selectionner_liste(l2)
    x = a.ajouter_tache("X")
    y = a.ajouter_tache("Y")
    a.selectionner_liste(l1)
    a.deplacer(t, l2)
    a.selectionner_liste(l2)
    assert a.affichage() == [x, y, t], f"obtenu {titres(a, a.affichage())}"


def test_A23_deplacer_laisse_statut():
    a, l1, l2, t = _deux_listes_avec_tache()
    a.cocher(t)
    a.deplacer(t, l2)
    assert a.est_cochee(t) is True
    a2, _, l2b, t2 = _deux_listes_avec_tache()
    a2.deplacer(t2, l2b)
    assert a2.est_cochee(t2) is False


def test_A24_deplacer_laisse_echeance():
    a, l1, l2, t = _deux_listes_avec_tache()
    a.definir_echeance(t, date(2026, 4, 1))
    a.deplacer(t, l2)
    assert a.echeance(t) == date(2026, 4, 1), f"obtenu {a.echeance(t)}"


def test_A25_supprimer_tache_la_retire():
    a, _, _, _ = app_avec_liste()
    t1 = a.ajouter_tache("A")
    t2 = a.ajouter_tache("B")
    a.supprimer_tache(t1)
    assert t1 not in a.taches()
    assert t1 not in a.affichage()
    assert t2 in a.taches()


def test_A25_supprimer_tache_non_cochee_met_a_jour_compteur():
    a, _, _, _ = app_avec_liste()
    t1 = a.ajouter_tache("A")
    a.ajouter_tache("B")
    a.supprimer_tache(t1)
    assert a.compteur() == 1, f"obtenu {a.compteur()}"


def test_A26_definir_echeance():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 5, 2))
    assert a.echeance(t) == date(2026, 5, 2)
    a.definir_echeance(t, date(2026, 6, 3))
    assert a.echeance(t) == date(2026, 6, 3)


def test_A27_retirer_echeance():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 5, 2))
    a.retirer_echeance(t)
    assert a.echeance(t) is None


# ---------------------------------------------------------------- A28-A31

def test_A28_non_cochee_echeance_passee_en_retard():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 3, 9))
    assert a.en_retard(t) is True
    t2 = a.ajouter_tache("B")
    a.definir_echeance(t2, date(2025, 1, 1))
    assert a.en_retard(t2) is True


def test_A28_echeance_future_pas_en_retard_et_sans_echeance_non_plus():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    assert a.en_retard(t) is False
    a.definir_echeance(t, date(2026, 3, 11))
    assert a.en_retard(t) is False


def test_A28_decocher_tache_echue_la_remet_en_retard():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 3, 1))
    a.cocher(t)
    a.decocher(t)
    assert a.en_retard(t) is True


def test_A29_cochee_echeance_passee_pas_en_retard():
    a, _, _, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 3, 1))
    a.cocher(t)
    assert a.en_retard(t) is False


def test_A30_echeance_aujourd_hui_pas_en_retard():
    a, _, h, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 3, 10))
    assert a.en_retard(t) is False
    h.avancer(timedelta(hours=11, minutes=59))  # 23:59 le même jour
    assert a.en_retard(t) is False, "23:59 le jour de l'échéance : pas encore en retard"


def test_A31_passage_de_minuit_rend_en_retard_sans_action():
    a, _, h, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 3, 10))
    assert a.en_retard(t) is False
    h.avancer(timedelta(hours=12, minutes=1))  # 00:01 le lendemain
    assert a.en_retard(t) is True, f"après minuit ({h.maintenant()}), attendu en retard"


def test_A31_filtre_en_retard_suit_l_horloge():
    a, _, h, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 3, 12))
    a.definir_filtre("en_retard")
    assert a.affichage() == []
    h.avancer(timedelta(days=1))
    assert a.affichage() == [], "le 11, échéance le 12 : pas en retard"
    h.avancer(timedelta(days=2))
    assert a.affichage() == [t], f"le 13 : attendu [{t}], obtenu {a.affichage()}"


def test_A31_horloge_independante_entre_instances():
    a, _, h, _ = app_avec_liste()
    t = a.ajouter_tache("A")
    a.definir_echeance(t, date(2026, 3, 9))
    assert a.en_retard(t) is True
    b, _, _ = ouvrir(horloge=app.Horloge(datetime(2026, 3, 1, 9, 0)))
    b.creer_liste("X")
    u = b.ajouter_tache("U")
    b.definir_echeance(u, date(2026, 3, 9))
    assert b.en_retard(u) is False, "la date du jour doit venir de l'horloge injectée"


# ---------------------------------------------------------------- A32-A35

def _melange():
    a, s, h, lid = app_avec_liste()
    actif = a.ajouter_tache("actif")
    fini = a.ajouter_tache("fini")
    retard = a.ajouter_tache("retard")
    fini_echu = a.ajouter_tache("fini_echu")
    a.cocher(fini)
    a.definir_echeance(retard, date(2026, 3, 1))
    a.definir_echeance(fini_echu, date(2026, 3, 1))
    a.cocher(fini_echu)
    return a, actif, fini, retard, fini_echu


def test_A32_filtre_actives():
    a, actif, fini, retard, fini_echu = _melange()
    a.definir_filtre("actives")
    assert a.affichage() == [actif, retard], f"obtenu {titres(a, a.affichage())}"


def test_A33_filtre_terminees():
    a, actif, fini, retard, fini_echu = _melange()
    a.definir_filtre("terminees")
    assert a.affichage() == [fini, fini_echu], f"obtenu {titres(a, a.affichage())}"


def test_A34_filtre_en_retard():
    a, actif, fini, retard, fini_echu = _melange()
    a.definir_filtre("en_retard")
    assert a.affichage() == [retard], f"obtenu {titres(a, a.affichage())}"


def test_A32_filtre_toutes_affiche_tout():
    a, actif, fini, retard, fini_echu = _melange()
    a.definir_filtre("toutes")
    assert a.affichage() == [actif, fini, retard, fini_echu]


def test_A32_filtre_respecte_liste_active():
    a, actif, fini, retard, fini_echu = _melange()
    a.creer_liste("Autre")
    autre = a.ajouter_tache("autre")
    a.definir_filtre("actives")
    assert a.affichage() == [autre], f"obtenu {titres(a, a.affichage())}"


def test_A35_filtre_actives_cocher_retire_de_l_affichage():
    a, _, _, _ = app_avec_liste()
    t1 = a.ajouter_tache("A")
    t2 = a.ajouter_tache("B")
    a.definir_filtre("actives")
    assert a.affichage() == [t1, t2]
    a.cocher(t1)
    assert a.affichage() == [t2], f"obtenu {titres(a, a.affichage())}"
    assert t1 in a.taches(), "cocher ne doit pas supprimer la tâche"


# ---------------------------------------------------------------- A36-A38

def _quatre():
    a, s, h, lid = app_avec_liste()
    ts = [a.ajouter_tache(x) for x in "ABCD"]
    return a, s, h, ts


def test_A36_glisser_vers_le_debut():
    a, _, _, (ta, tb, tc, td) = _quatre()
    a.glisser(td, 0)
    assert a.affichage() == [td, ta, tb, tc], f"obtenu {titres(a, a.affichage())}"


def test_A36_glisser_vers_la_fin_et_milieu():
    a, _, _, (ta, tb, tc, td) = _quatre()
    a.glisser(ta, 3)
    assert a.affichage() == [tb, tc, td, ta], f"obtenu {titres(a, a.affichage())}"
    a.glisser(ta, 1)
    assert a.affichage() == [tb, ta, tc, td], f"obtenu {titres(a, a.affichage())}"


def test_A36_glisser_n_affecte_pas_autre_liste():
    a, _, _, (ta, tb, tc, td) = _quatre()
    l1 = a.liste_active()
    a.creer_liste("Autre")
    x = a.ajouter_tache("X")
    y = a.ajouter_tache("Y")
    a.glisser(y, 0)
    assert a.affichage() == [y, x]
    a.selectionner_liste(l1)
    assert a.affichage() == [ta, tb, tc, td]


def test_A37_tri_echeance_glisser_laisse_ordre():
    a, _, _, (ta, tb, tc, td) = _quatre()
    a.definir_echeance(ta, date(2026, 4, 4))
    a.definir_echeance(tb, date(2026, 4, 1))
    a.definir_echeance(tc, date(2026, 4, 3))
    a.definir_echeance(td, date(2026, 4, 2))
    a.definir_tri("echeance")
    avant = a.affichage()
    a.glisser(ta, 0)
    assert a.affichage() == avant, f"attendu {titres(a, avant)}, obtenu {titres(a, a.affichage())}"


def test_A37_trou_retour_manuel():
    a, _, _, (ta, tb, tc, td) = _quatre()
    a.definir_echeance(ta, date(2026, 4, 4))
    a.definir_echeance(td, date(2026, 4, 1))
    a.definir_tri("echeance")
    a.glisser(ta, 0)
    a.definir_tri("manuel")
    assert a.affichage() == [ta, tb, tc, td], f"obtenu {titres(a, a.affichage())}"


def test_A38_tri_echeance_croissante_sans_echeance_apres():
    a, _, _, (ta, tb, tc, td) = _quatre()
    a.definir_echeance(ta, date(2026, 5, 3))
    # tb sans échéance
    a.definir_echeance(tc, date(2026, 5, 1))
    a.definir_echeance(td, date(2026, 5, 2))
    a.definir_tri("echeance")
    assert a.affichage() == [tc, td, ta, tb], f"obtenu {titres(a, a.affichage())}"


def test_A38_tri_echeance_annees_et_mois_differents():
    a, _, _, (ta, tb, tc, td) = _quatre()
    a.definir_echeance(ta, date(2027, 1, 1))
    a.definir_echeance(tb, date(2026, 12, 31))
    a.definir_echeance(tc, date(2026, 2, 10))
    a.definir_tri("echeance")
    assert a.affichage() == [tc, tb, ta, td], f"obtenu {titres(a, a.affichage())}"


def test_A38_trou_egalite():
    a, _, _, (ta, tb, tc, td) = _quatre()
    a.glisser(tc, 0)  # manuel : C A B D
    for t in (ta, tb, tc, td):
        a.definir_echeance(t, date(2026, 5, 1))
    a.definir_tri("echeance")
    assert a.affichage() == [tc, ta, tb, td], f"obtenu {titres(a, a.affichage())}"


# ---------------------------------------------------------------- A39-A40

def test_A39_rechargement_conserve_taches():
    a, s, h = ouvrir()
    a.creer_liste("Courses")
    a.ajouter_tache("Pain")
    a.ajouter_tache("Lait")
    a.creer_liste("Travail")
    a.ajouter_tache("Rapport")
    b = app.Application(stockage=s, horloge=h)
    assert sorted(b.titre(t) for t in b.taches()) == ["Lait", "Pain", "Rapport"], \
        f"obtenu {[b.titre(t) for t in b.taches()]}"


def test_A39_rechargement_conserve_modifications_ulterieures():
    a, s, h = ouvrir()
    a.creer_liste("Courses")
    t1 = a.ajouter_tache("Pain")
    t2 = a.ajouter_tache("Lait")
    a.modifier_titre(t1, "Pain complet")
    a.cocher(t1)
    a.definir_echeance(t2, date(2026, 3, 1))
    a.supprimer_tache(a.ajouter_tache("Jetable"))
    b = app.Application(stockage=s, horloge=h)
    par_titre = {b.titre(t): t for t in b.taches()}
    assert set(par_titre) == {"Pain complet", "Lait"}, f"obtenu {set(par_titre)}"
    assert b.est_cochee(par_titre["Pain complet"]) is True
    assert b.echeance(par_titre["Lait"]) == date(2026, 3, 1)
    assert b.en_retard(par_titre["Lait"]) is True


def test_A39_stockage_neuf_est_vide():
    a, s, h = ouvrir()
    a.creer_liste("Courses")
    a.ajouter_tache("Pain")
    b, _, _ = ouvrir()
    assert b.taches() == [], "un stockage neuf ne doit rien contenir (pas d'état global au module)"
    assert b.listes() == []


def test_A39_trou_listes_persistees():
    a, s, h = ouvrir()
    a.creer_liste("Courses")
    a.ajouter_tache("Pain")
    a.creer_liste("Travail")
    a.ajouter_tache("Rapport")
    b = app.Application(stockage=s, horloge=h)
    courses = liste_par_nom(b, "Courses")
    travail = liste_par_nom(b, "Travail")
    par_titre = {b.titre(t): t for t in b.taches()}
    assert b.liste_de(par_titre["Pain"]) == courses
    assert b.liste_de(par_titre["Rapport"]) == travail


def test_A40_rechargement_conserve_ordre_manuel():
    a, s, h = ouvrir()
    a.creer_liste("Courses")
    a.definir_tri("manuel")
    a.definir_filtre("toutes")
    ts = [a.ajouter_tache(x) for x in "ABCD"]
    a.glisser(ts[3], 0)
    a.glisser(ts[0], 3)  # D B C A
    assert titres(a, a.affichage()) == ["D", "B", "C", "A"]
    b = app.Application(stockage=s, horloge=h)
    b.selectionner_liste(liste_par_nom(b, "Courses"))
    b.definir_tri("manuel")
    b.definir_filtre("toutes")
    assert titres(b, b.affichage()) == ["D", "B", "C", "A"], f"obtenu {titres(b, b.affichage())}"
