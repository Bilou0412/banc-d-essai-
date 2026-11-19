"""Tests rouges de la sonde P04 (listes de tâches).

Interface publique fixée par ces tests (le constructeur l'implémente telle quelle) :

    app.Clock(now: datetime.datetime)
        .now() -> datetime.datetime
        .advance(delta: datetime.timedelta) -> None
        La « date du jour » de l'application est clock.now().date().

    app.Storage()
        Stockage en mémoire, partagé entre deux instances d'App pour simuler
        un rechargement. Deux Storage distincts ne partagent rien.

    app.App(clock: Clock, storage: Storage)
        Une nouvelle App sur un Storage vide n'a aucune liste.
        Toute modification est persistée dans le storage sans action explicite.

      Listes (identifiants opaques) :
        .create_list(name: str) -> id | None     (None si refusée)
        .lists() -> list[id]                     (ordre de création)
        .list_name(list_id) -> str
        .rename_list(list_id, name: str) -> None
        .delete_list(list_id) -> None
        .select_list(list_id) -> None
        .active_list() -> id | None

      Tâches (identifiants opaques) :
        .add_task(title: str) -> id | None       (None si refusée)
        .all_tasks() -> list[id]                 (toutes listes confondues)
        .title(task_id) -> str
        .list_of(task_id) -> id
        .is_done(task_id) -> bool
        .check(task_id) / .uncheck(task_id)
        .rename_task(task_id, title: str)
        .move_task(task_id, list_id)
        .delete_task(task_id)
        .set_due(task_id, date: datetime.date) / .clear_due(task_id)
        .due(task_id) -> datetime.date | None
        .is_overdue(task_id) -> bool

      Affichage :
        .set_filter(f)  f in {"toutes", "actives", "terminees", "en_retard"}
        .set_sort(s)    s in {"manuel", "echeance"}
        .visible() -> list[task_id]   (tâches affichées, dans l'ordre affiché)
        .counter() -> int
        .drag(task_id, position: int) (position 0-based dans la liste de la tâche)
"""

from datetime import date, datetime, timedelta

import pytest

import app

# Date volontairement éloignée de la date réelle : une implémentation qui lit
# l'horloge système au lieu de l'horloge simulée se trompe.
START = datetime(2031, 3, 10, 12, 0)
TODAY = START.date()


def make(now=START):
    clock = app.Clock(now)
    storage = app.Storage()
    a = app.App(clock=clock, storage=storage)
    return a, clock, storage


def make_with_list(name="Courses", now=START):
    a, clock, storage = make(now)
    lid = a.create_list(name)
    assert lid is not None, "create_list('%s') a été refusé sur une app vide" % name
    a.set_filter("toutes")
    a.set_sort("manuel")
    return a, clock, storage, lid


def names(a):
    return [a.list_name(l) for l in a.lists()]


# ---------------------------------------------------------------- A01..A09 listes


def test_A01_creer_liste_nom_non_vide_l_ajoute():
    a, _, _ = make()
    assert a.lists() == [], "app neuve : attendu aucune liste, obtenu %r" % names(a)
    lid = a.create_list("Courses")
    assert lid is not None
    assert a.lists() == [lid], "attendu [%r], obtenu %r" % (lid, a.lists())
    assert a.list_name(lid) == "Courses"


def test_A01_deux_listes_distinctes_coexistent():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    l2 = a.create_list("Travail")
    assert a.lists() == [l1, l2], "attendu deux listes, obtenu %r" % names(a)
    assert names(a) == ["Courses", "Travail"]


@pytest.mark.parametrize("bad", ["", " ", "   ", "\t", " \t \n "])
def test_A02_creer_liste_nom_vide_ou_espaces_n_ajoute_rien(bad):
    a, _, _ = make()
    a.create_list("Existante")
    before = list(a.lists())
    res = a.create_list(bad)
    assert res is None, "create_list(%r) aurait dû être refusé, obtenu %r" % (bad, res)
    assert a.lists() == before, "listes modifiées par create_list(%r) : %r" % (bad, names(a))


def test_A03_creer_liste_nom_deja_pris_n_ajoute_rien():
    a, _, _ = make()
    a.create_list("Courses")
    before = list(a.lists())
    res = a.create_list("Courses")
    assert res is None
    assert a.lists() == before, "doublon accepté : %r" % names(a)


def test_A03_nom_repris_apres_renommage_est_refuse():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    a.rename_list(l1, "Maison")
    before = list(a.lists())
    assert a.create_list("Maison") is None, "nom porté (après renommage) accepté"
    assert a.lists() == before


def test_A03_nom_libere_apres_renommage_est_accepte():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    a.rename_list(l1, "Maison")
    l2 = a.create_list("Courses")
    assert l2 is not None, "l'ancien nom n'est plus porté : la création devait réussir"
    assert len(a.lists()) == 2


def test_A03_trou_nom_identique_aux_espaces_pres():
    a, _, _ = make()
    a.create_list("Courses")
    before = list(a.lists())
    assert a.create_list("  Courses  ") is None, "'  Courses  ' accepté alors que 'Courses' existe"
    assert a.lists() == before


def test_A04_liste_creee_devient_active():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    assert a.active_list() == l1
    l2 = a.create_list("Travail")
    assert a.active_list() == l2, "attendu la liste créée en dernier active, obtenu %r" % a.active_list()


def test_A04_creation_refusee_ne_change_pas_la_liste_active():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    a.create_list("Travail")
    a.select_list(l1)
    a.create_list("")
    a.create_list("Travail")
    assert a.active_list() == l1, "une création refusée a changé la liste active"


def test_A05_renommer_liste_remplace_son_nom():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    l2 = a.create_list("Travail")
    a.rename_list(l1, "Marché")
    assert a.list_name(l1) == "Marché"
    assert a.list_name(l2) == "Travail", "l'autre liste a été renommée"
    assert a.lists() == [l1, l2]


@pytest.mark.parametrize("bad", ["", "   "])
def test_A05_trou_renommer_liste_nom_vide(bad):
    a, _, _ = make()
    l1 = a.create_list("Courses")
    a.rename_list(l1, bad)
    assert a.list_name(l1) == "Courses", "renommage en %r accepté : %r" % (bad, a.list_name(l1))


def test_A05_trou_renommer_liste_nom_deja_pris():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    a.create_list("Travail")
    a.rename_list(l1, "Travail")
    assert a.list_name(l1) == "Courses", "deux listes portent désormais %r" % names(a)


def test_A06_supprimer_liste_la_retire():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    l2 = a.create_list("Travail")
    a.delete_list(l1)
    assert a.lists() == [l2], "attendu [Travail], obtenu %r" % names(a)


def test_A07_supprimer_liste_supprime_ses_taches():
    a, _, _, l1 = make_with_list("Courses")
    t1 = a.add_task("pain")
    t2 = a.add_task("lait")
    l2 = a.create_list("Travail")
    t3 = a.add_task("rapport")
    a.delete_list(l1)
    remaining = a.all_tasks()
    assert t1 not in remaining and t2 not in remaining, "tâches orphelines : %r" % remaining
    assert remaining == [t3], "la tâche de l'autre liste devait rester, obtenu %r" % remaining
    assert a.list_of(t3) == l2


def test_A07_liste_recreee_meme_nom_est_vide():
    a, _, _, l1 = make_with_list("Courses")
    a.add_task("pain")
    a.delete_list(l1)
    l1b = a.create_list("Courses")
    a.select_list(l1b)
    assert a.visible() == [], "les tâches de l'ancienne liste réapparaissent : %r" % a.visible()
    assert a.counter() == 0


def test_A08_supprimer_liste_active_active_une_restante():
    a, _, _ = make()
    l1 = a.create_list("Courses")
    l2 = a.create_list("Travail")
    assert a.active_list() == l2
    a.delete_list(l2)
    assert a.active_list() == l1, "attendu Courses active, obtenu %r" % a.active_list()


def test_A08_active_parmi_restantes_avec_trois_listes():
    a, _, _ = make()
    l1 = a.create_list("A")
    l2 = a.create_list("B")
    l3 = a.create_list("C")
    a.select_list(l2)
    a.delete_list(l2)
    assert a.active_list() in (l1, l3), "liste active %r absente des restantes" % a.active_list()
    assert a.active_list() in a.lists()


def test_A08_supprimer_liste_non_active_ne_change_pas_l_active():
    a, _, _ = make()
    l1 = a.create_list("A")
    l2 = a.create_list("B")
    a.delete_list(l1)
    assert a.active_list() == l2


def test_A08_trou_supprimer_derniere_liste():
    a, _, _ = make()
    l1 = a.create_list("A")
    a.add_task("x")
    a.delete_list(l1)
    assert a.lists() == []
    assert a.active_list() is None, "aucune liste restante, active=%r" % a.active_list()
    assert a.visible() == []
    assert a.counter() == 0


def test_A08_affichage_suit_la_nouvelle_liste_active():
    a, _, _ = make()
    l1 = a.create_list("A")
    t1 = a.add_task("de A")
    a.create_list("B")
    a.add_task("de B")
    a.set_filter("toutes")
    a.set_sort("manuel")
    a.delete_list(a.active_list())
    assert a.active_list() == l1
    assert a.visible() == [t1]
    assert a.counter() == 1


def test_A09_selectionner_liste_la_rend_active():
    a, _, _ = make()
    l1 = a.create_list("A")
    l2 = a.create_list("B")
    a.select_list(l1)
    assert a.active_list() == l1
    a.select_list(l2)
    assert a.active_list() == l2


# ---------------------------------------------------------------- A10..A15 tâches


def test_A10_seules_les_taches_de_la_liste_active_sont_affichees():
    a, _, _, l1 = make_with_list("A")
    t1 = a.add_task("a1")
    t2 = a.add_task("a2")
    l2 = a.create_list("B")
    t3 = a.add_task("b1")
    assert a.visible() == [t3], "liste B active : attendu [b1], obtenu %r" % a.visible()
    a.select_list(l1)
    assert a.visible() == [t1, t2], "liste A active : obtenu %r" % a.visible()


def test_A10_liste_active_vide_affiche_rien():
    a, _, _, _ = make_with_list("A")
    a.add_task("a1")
    a.create_list("B")
    assert a.visible() == []


def test_A11_ajouter_tache_la_rattache_a_la_liste_active():
    a, _, _, l1 = make_with_list("A")
    l2 = a.create_list("B")
    a.select_list(l1)
    t = a.add_task("pain")
    assert t is not None
    assert a.list_of(t) == l1, "attendu liste A, obtenu %r" % a.list_of(t)
    assert a.title(t) == "pain"
    a.select_list(l2)
    u = a.add_task("rapport")
    assert a.list_of(u) == l2
    assert a.list_of(t) == l1


def test_A11_trou_ajouter_tache_sans_liste_active():
    a, _, _ = make()
    res = a.add_task("pain")
    assert res is None, "tâche créée sans liste : %r" % res
    assert a.all_tasks() == []


@pytest.mark.parametrize("bad", ["", " ", "    ", "\t\n"])
def test_A12_titre_vide_ou_espaces_ne_cree_aucune_tache(bad):
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    res = a.add_task(bad)
    assert res is None, "add_task(%r) aurait dû être refusé" % bad
    assert a.all_tasks() == [t]
    assert a.visible() == [t]
    assert a.counter() == 1


def test_A13_tache_ajoutee_est_non_cochee():
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    assert a.is_done(t) is False


def test_A14_tache_ajoutee_sans_echeance():
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    assert a.due(t) is None
    assert a.is_overdue(t) is False


def test_A15_tri_manuel_tache_ajoutee_en_derniere_position():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    assert a.visible() == [t1, t2, t3], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A15_ajout_apres_reordonnancement_reste_dernier():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.drag(t2, 0)
    t3 = a.add_task("3")
    assert a.visible() == [t2, t1, t3], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A15_ajout_apres_suppression_reste_dernier():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    a.delete_task(t2)
    t4 = a.add_task("4")
    assert a.visible() == [t1, t3, t4]


# ---------------------------------------------------------------- A16..A21 statut, compteur, titre


def test_A16_cocher_rend_cochee():
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    a.check(t)
    assert a.is_done(t) is True


def test_A16_cocher_n_affecte_que_la_tache_visee():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.check(t1)
    assert a.is_done(t2) is False


def test_A16_trou_cocher_une_tache_deja_cochee():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    a.add_task("2")
    a.check(t1)
    a.check(t1)
    assert a.is_done(t1) is True, "cocher deux fois a basculé la tâche"
    assert a.counter() == 1, "compteur attendu 1, obtenu %d" % a.counter()


def test_A17_decocher_rend_non_cochee():
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    a.check(t)
    a.uncheck(t)
    assert a.is_done(t) is False


def test_A18_cocher_diminue_compteur_de_un():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    a.add_task("2")
    a.add_task("3")
    assert a.counter() == 3
    a.check(t1)
    assert a.counter() == 2, "attendu 2, obtenu %d" % a.counter()


def test_A18_trou_decocher_augmente_compteur_de_un():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    a.add_task("2")
    a.check(t1)
    a.uncheck(t1)
    assert a.counter() == 2, "attendu 2, obtenu %d" % a.counter()


def test_A19_compteur_taches_non_cochees_liste_active():
    a, _, _, l1 = make_with_list("A")
    t1 = a.add_task("a1")
    a.add_task("a2")
    a.add_task("a3")
    a.check(t1)
    l2 = a.create_list("B")
    a.add_task("b1")
    assert a.counter() == 1, "liste B : attendu 1, obtenu %d" % a.counter()
    a.select_list(l1)
    assert a.counter() == 2, "liste A : attendu 2, obtenu %d" % a.counter()


def test_A19_compteur_ignore_le_filtre():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    a.add_task("2")
    a.check(t1)
    a.set_filter("terminees")
    assert a.counter() == 1, "le filtre ne doit pas changer le compteur, obtenu %d" % a.counter()


def test_A19_compteur_suit_suppression_et_deplacement():
    a, _, _, l1 = make_with_list("A")
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.add_task("3")
    l2 = a.create_list("B")
    a.select_list(l1)
    a.delete_task(t1)
    a.move_task(t2, l2)
    assert a.counter() == 1
    a.select_list(l2)
    assert a.counter() == 1


def test_A19_compteur_inclut_taches_en_retard():
    a, _, _, _ = make_with_list()
    t = a.add_task("1")
    a.set_due(t, TODAY - timedelta(days=3))
    assert a.counter() == 1


def test_A20_modifier_titre_non_vide_le_remplace():
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    a.rename_task(t, "pain complet")
    assert a.title(t) == "pain complet"


@pytest.mark.parametrize("bad", [""])
def test_A21_modifier_titre_vide_laisse_inchange(bad):
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    a.rename_task(t, bad)
    assert a.title(t) == "pain", "obtenu %r" % a.title(t)
    assert t in a.all_tasks()


def test_A21_trou_modifier_titre_espaces_seuls():
    a, _, _, _ = make_with_list()
    t = a.add_task("pain")
    a.rename_task(t, "   ")
    assert a.title(t) == "pain", "titre blanc accepté : %r" % a.title(t)
    assert t in a.all_tasks(), "la tâche a été supprimée par un titre blanc"


# ---------------------------------------------------------------- A22..A27 déplacement, suppression, échéance


def test_A22_deplacer_rattache_a_la_liste_cible():
    a, _, _, l1 = make_with_list("A")
    t = a.add_task("x")
    l2 = a.create_list("B")
    a.move_task(t, l2)
    assert a.list_of(t) == l2
    assert a.visible() == [t], "B active : la tâche déplacée doit y être affichée"
    a.select_list(l1)
    assert a.visible() == []


def test_A22_trou_tache_deplacee_en_derniere_position_cible():
    a, _, _, l1 = make_with_list("A")
    t = a.add_task("x")
    l2 = a.create_list("B")
    b1 = a.add_task("b1")
    b2 = a.add_task("b2")
    a.move_task(t, l2)
    assert a.visible() == [b1, b2, t], "obtenu %r" % [a.title(i) for i in a.visible()]


def test_A23_deplacer_laisse_statut_inchange():
    a, _, _, _ = make_with_list("A")
    t1 = a.add_task("x")
    t2 = a.add_task("y")
    a.check(t1)
    l2 = a.create_list("B")
    a.move_task(t1, l2)
    a.move_task(t2, l2)
    assert a.is_done(t1) is True
    assert a.is_done(t2) is False
    assert a.counter() == 1


def test_A24_deplacer_laisse_echeance_inchangee():
    a, _, _, _ = make_with_list("A")
    t1 = a.add_task("x")
    t2 = a.add_task("y")
    d = date(2031, 4, 2)
    a.set_due(t1, d)
    l2 = a.create_list("B")
    a.move_task(t1, l2)
    a.move_task(t2, l2)
    assert a.due(t1) == d
    assert a.due(t2) is None


def test_A25_supprimer_tache_la_retire():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.delete_task(t1)
    assert a.all_tasks() == [t2]
    assert a.visible() == [t2]


def test_A26_definir_echeance():
    a, _, _, _ = make_with_list()
    t = a.add_task("x")
    d = date(2031, 5, 1)
    a.set_due(t, d)
    assert a.due(t) == d
    d2 = date(2031, 6, 1)
    a.set_due(t, d2)
    assert a.due(t) == d2, "redéfinir l'échéance doit la remplacer"


def test_A27_retirer_echeance():
    a, _, _, _ = make_with_list()
    t = a.add_task("x")
    a.set_due(t, TODAY - timedelta(days=1))
    assert a.is_overdue(t) is True
    a.clear_due(t)
    assert a.due(t) is None
    assert a.is_overdue(t) is False, "sans échéance, la tâche ne peut pas être en retard"


# ---------------------------------------------------------------- A28..A31 retard


def test_A28_non_cochee_echeance_passee_en_retard():
    a, _, _, _ = make_with_list()
    t = a.add_task("x")
    a.set_due(t, TODAY - timedelta(days=1))
    assert a.is_overdue(t) is True


def test_A28_utilise_l_horloge_simulee_pas_l_horloge_systeme():
    # La date simulée (2031) est postérieure à la date réelle : une échéance
    # en 2030 est passée pour l'app, future pour l'horloge système.
    a, _, _, _ = make_with_list()
    t = a.add_task("x")
    a.set_due(t, date(2030, 12, 31))
    assert a.is_overdue(t) is True, "l'app lit-elle l'horloge système ?"


def test_A28_echeance_future_pas_en_retard():
    a, _, _, _ = make_with_list()
    t = a.add_task("x")
    a.set_due(t, TODAY + timedelta(days=1))
    assert a.is_overdue(t) is False


def test_A29_cochee_echeance_passee_pas_en_retard():
    a, _, _, _ = make_with_list()
    t = a.add_task("x")
    a.set_due(t, TODAY - timedelta(days=5))
    a.check(t)
    assert a.is_overdue(t) is False
    a.uncheck(t)
    assert a.is_overdue(t) is True, "décochée, la tâche redevient en retard"


def test_A30_echeance_egale_au_jour_pas_en_retard():
    a, _, _, _ = make_with_list(now=datetime(2031, 3, 10, 23, 59, 59))
    t = a.add_task("x")
    a.set_due(t, date(2031, 3, 10))
    assert a.is_overdue(t) is False


def test_A31_passage_de_minuit_rend_la_tache_en_retard_sans_action():
    a, clock, _, _ = make_with_list(now=datetime(2031, 3, 10, 23, 58))
    t = a.add_task("x")
    a.set_due(t, date(2031, 3, 10))
    a.set_filter("en_retard")
    assert a.is_overdue(t) is False
    assert a.visible() == []
    clock.advance(timedelta(minutes=3))
    assert a.is_overdue(t) is True, "après minuit, attendu en retard"
    assert a.visible() == [t], "le filtre en retard doit montrer la tâche sans action"


def test_A31_avance_sans_franchir_minuit_ne_change_rien():
    a, clock, _, _ = make_with_list(now=datetime(2031, 3, 10, 0, 1))
    t = a.add_task("x")
    a.set_due(t, date(2031, 3, 10))
    clock.advance(timedelta(hours=23, minutes=58))
    assert a.is_overdue(t) is False, "toujours le même jour : pas de retard"


def test_A31_tache_cochee_ne_devient_pas_en_retard():
    a, clock, _, _ = make_with_list()
    t = a.add_task("x")
    a.set_due(t, TODAY)
    a.check(t)
    clock.advance(timedelta(days=2))
    assert a.is_overdue(t) is False


def test_A31_plusieurs_jours_plusieurs_taches():
    a, clock, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.set_due(t1, TODAY + timedelta(days=1))
    a.set_due(t2, TODAY + timedelta(days=3))
    a.set_filter("en_retard")
    clock.advance(timedelta(days=2))
    assert a.visible() == [t1]
    clock.advance(timedelta(days=2))
    assert a.visible() == [t1, t2]


# ---------------------------------------------------------------- A32..A35 filtres


def _mix():
    a, clock, s, l1 = make_with_list()
    t1 = a.add_task("actif")
    t2 = a.add_task("fait")
    t3 = a.add_task("retard")
    t4 = a.add_task("fait_passé")
    a.check(t2)
    a.set_due(t3, TODAY - timedelta(days=1))
    a.set_due(t4, TODAY - timedelta(days=1))
    a.check(t4)
    return a, t1, t2, t3, t4


def test_A32_filtre_actives():
    a, t1, t2, t3, t4 = _mix()
    a.set_filter("actives")
    assert a.visible() == [t1, t3], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A33_filtre_terminees():
    a, t1, t2, t3, t4 = _mix()
    a.set_filter("terminees")
    assert a.visible() == [t2, t4], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A34_filtre_en_retard():
    a, t1, t2, t3, t4 = _mix()
    a.set_filter("en_retard")
    assert a.visible() == [t3], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A34_filtre_respecte_la_liste_active():
    a, t1, t2, t3, t4 = _mix()
    a.create_list("Autre")
    o = a.add_task("autre retard")
    a.set_due(o, TODAY - timedelta(days=2))
    a.set_filter("en_retard")
    assert a.visible() == [o]


def test_A35_filtre_actives_cocher_retire_de_l_affichage():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.set_filter("actives")
    assert a.visible() == [t1, t2]
    a.check(t1)
    assert a.visible() == [t2], "obtenu %r" % a.visible()
    assert t1 in a.all_tasks(), "cocher ne doit pas supprimer la tâche"


def test_A10_filtre_toutes_affiche_tout():
    a, t1, t2, t3, t4 = _mix()
    a.set_filter("toutes")
    assert a.visible() == [t1, t2, t3, t4]


# ---------------------------------------------------------------- A36..A38 tri


def test_A36_glisser_vers_le_debut():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    a.drag(t3, 0)
    assert a.visible() == [t3, t1, t2], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A36_glisser_vers_la_fin():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    a.drag(t1, 2)
    assert a.visible() == [t2, t3, t1], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A36_glisser_au_milieu():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    t4 = a.add_task("4")
    a.drag(t4, 1)
    assert a.visible() == [t1, t4, t2, t3]
    a.drag(t1, 2)
    assert a.visible() == [t4, t2, t1, t3]


def test_A36_glisser_ne_touche_pas_l_autre_liste():
    a, _, _, l1 = make_with_list("A")
    a1 = a.add_task("a1")
    a2 = a.add_task("a2")
    a.create_list("B")
    b1 = a.add_task("b1")
    b2 = a.add_task("b2")
    a.drag(b2, 0)
    assert a.visible() == [b2, b1]
    a.select_list(l1)
    assert a.visible() == [a1, a2]


def test_A37_tri_echeance_glisser_laisse_ordre_inchange():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    a.set_due(t1, TODAY + timedelta(days=3))
    a.set_due(t2, TODAY + timedelta(days=1))
    a.set_due(t3, TODAY + timedelta(days=2))
    a.set_sort("echeance")
    before = a.visible()
    assert before == [t2, t3, t1]
    a.drag(t1, 0)
    assert a.visible() == before, "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A37_trou_retour_tri_manuel_apres_glisser_en_tri_echeance():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    a.set_due(t1, TODAY + timedelta(days=3))
    a.set_due(t2, TODAY + timedelta(days=1))
    a.set_sort("echeance")
    a.drag(t3, 0)
    a.set_sort("manuel")
    assert a.visible() == [t1, t2, t3], "l'ordre manuel a été altéré : %r" % [a.title(t) for t in a.visible()]


def test_A38_tri_echeance_croissante_sans_echeance_apres():
    a, _, _, _ = make_with_list()
    n1 = a.add_task("sans1")
    t1 = a.add_task("loin")
    t2 = a.add_task("passé")
    n2 = a.add_task("sans2")
    t3 = a.add_task("proche")
    a.set_due(t1, date(2031, 12, 1))
    a.set_due(t2, date(2030, 1, 1))
    a.set_due(t3, date(2031, 3, 11))
    a.set_sort("echeance")
    vis = a.visible()
    assert vis[:3] == [t2, t3, t1], "obtenu %r" % [a.title(t) for t in vis]
    assert set(vis[3:]) == {n1, n2}


def test_A38_dates_comparees_chronologiquement_pas_lexicalement():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("a")
    t2 = a.add_task("b")
    a.set_due(t1, date(2031, 10, 1))
    a.set_due(t2, date(2031, 9, 2))
    a.set_sort("echeance")
    assert a.visible() == [t2, t1]


def test_A38_trou_egalite_d_echeance_garde_l_ordre_manuel():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    n1 = a.add_task("n1")
    n2 = a.add_task("n2")
    d = date(2031, 4, 1)
    for t in (t1, t2, t3):
        a.set_due(t, d)
    a.drag(t3, 0)
    a.drag(n2, 0)
    a.set_sort("echeance")
    assert a.visible() == [t3, t1, t2, n2, n1], "obtenu %r" % [a.title(t) for t in a.visible()]


def test_A38_tri_echeance_combine_au_filtre():
    a, _, _, _ = make_with_list()
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    a.set_due(t1, TODAY + timedelta(days=5))
    a.set_due(t2, TODAY + timedelta(days=1))
    a.check(t3)
    a.set_sort("echeance")
    a.set_filter("actives")
    assert a.visible() == [t2, t1]


# ---------------------------------------------------------------- A39..A40 rechargement


def test_A39_rechargement_taches_presentes():
    a, clock, storage, l1 = make_with_list("A")
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.create_list("B")
    t3 = a.add_task("3")
    b = app.App(clock=clock, storage=storage)
    titles = sorted(b.title(t) for t in b.all_tasks())
    assert titles == ["1", "2", "3"], "après rechargement : %r" % titles
    assert sorted(b.list_name(l) for l in b.lists()) == ["A", "B"]


def test_A39_storage_neuf_ne_voit_rien():
    a, clock, _, _ = make_with_list("A")
    a.add_task("1")
    b = app.App(clock=clock, storage=app.Storage())
    assert b.all_tasks() == [], "un storage neuf voit des tâches : état global partagé ?"
    assert b.lists() == []


def test_A39_suppression_persistee():
    a, clock, storage, _ = make_with_list()
    t1 = a.add_task("1")
    a.add_task("2")
    a.delete_task(t1)
    b = app.App(clock=clock, storage=storage)
    assert [b.title(t) for t in b.all_tasks()] == ["2"]


def test_A39_trou_etat_des_taches_persiste():
    a, clock, storage, l1 = make_with_list("A")
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.check(t1)
    a.set_due(t2, date(2031, 1, 1))
    a.rename_task(t2, "deux")
    b = app.App(clock=clock, storage=storage)
    by_title = {b.title(t): t for t in b.all_tasks()}
    assert set(by_title) == {"1", "deux"}
    assert b.is_done(by_title["1"]) is True
    assert b.is_done(by_title["deux"]) is False
    assert b.due(by_title["deux"]) == date(2031, 1, 1)
    assert b.is_overdue(by_title["deux"]) is True
    assert b.list_name(b.list_of(by_title["1"])) == "A"


def test_A39_rechargement_respecte_l_horloge_courante():
    a, clock, storage, _ = make_with_list()
    t = a.add_task("x")
    a.set_due(t, TODAY)
    clock.advance(timedelta(days=1))
    b = app.App(clock=clock, storage=storage)
    (u,) = b.all_tasks()
    assert b.is_overdue(u) is True


def test_A40_rechargement_ordre_manuel_inchange():
    a, clock, storage, l1 = make_with_list("A")
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    t3 = a.add_task("3")
    t4 = a.add_task("4")
    a.drag(t4, 0)
    a.drag(t2, 3)
    expected = [a.title(t) for t in a.visible()]
    assert expected == ["4", "1", "3", "2"]
    b = app.App(clock=clock, storage=storage)
    lid = [l for l in b.lists() if b.list_name(l) == "A"][0]
    b.select_list(lid)
    b.set_filter("toutes")
    b.set_sort("manuel")
    got = [b.title(t) for t in b.visible()]
    assert got == expected, "attendu %r, obtenu %r" % (expected, got)


def test_A40_rechargement_puis_ajout_reste_dernier():
    a, clock, storage, _ = make_with_list("A")
    t1 = a.add_task("1")
    t2 = a.add_task("2")
    a.drag(t2, 0)
    b = app.App(clock=clock, storage=storage)
    b.select_list(b.lists()[0])
    b.set_filter("toutes")
    b.set_sort("manuel")
    b.add_task("3")
    assert [b.title(t) for t in b.visible()] == ["2", "1", "3"]
