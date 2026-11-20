"""Tests rouges — couche code — sonde P11, deuxième attaque.

Même interface publique que tests/test_app.py (voir sa docstring). Ces tests visent ce qu'une
implémentation qui simule le mécanisme ne tiendrait pas : analyseur réel (associativité, unaire,
colonnes à deux lettres), graphe réel (losange, ordre topologique, plage, chaîne profonde), réseau
réel (ordre de réception inversé, coupure avant livraison, rejeu unique), fuseaux réels (heure
d'hiver, demi-heures), CSV réel (CRLF, saut de ligne dans un champ, aller-retour), coordination
de deux acteurs (suppressions et noms concurrents).
"""
import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

import app

UTC = timezone.utc
T0 = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
T_ETE = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
W = "écriture"
R = "lecture"


def check(actual, expected, msg):
    assert actual == expected, f"{msg} : attendu {expected!r}, obtenu {actual!r}"


def kinds(client):
    return [a.kind for a in client.alerts()]


def alerts_of(client, kind):
    return [a for a in client.alerts() if a.kind == kind]


def rows(data):
    assert isinstance(data, (bytes, bytearray)), f"export_csv doit rendre des bytes, obtenu {type(data)!r}"
    return list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))


class World:
    def __init__(self, start=T0):
        self.clock = app.Clock(start)
        self.net = app.Network()
        self.server = app.Server(self.net, self.clock, owner="alice")
        self.alice = app.Client(self.net, self.clock, "alice", tz="Europe/Paris")
        self.bob = app.Client(self.net, self.clock, "bob", tz="UTC")
        self.carol = app.Client(self.net, self.clock, "carol", tz="UTC")
        self.sync()
        self.alice.set_right("bob", "Feuille1", W)
        self.alice.set_right("carol", "Feuille1", R)
        self.sync()

    def sync(self):
        self.net.deliver_all()

    def off(self, *names):
        for n in names:
            self.net.disconnect(n)

    def on(self, name):
        self.net.reconnect(name)
        self.sync()

    def add_sheet(self, name, bob=W, carol=R):
        self.alice.add_sheet(name)
        self.sync()
        if bob:
            self.alice.set_right("bob", name, bob)
        if carol:
            self.alice.set_right("carol", name, carol)
        self.sync()

    def everyone(self):
        return [("alice", self.alice), ("bob", self.bob), ("carol", self.carol)]


@pytest.fixture
def w():
    return World()


# ---------------------------------------------------------------- analyseur

def test_A04_trou2_associativite_gauche(w):
    w.alice.set_cell("A1", "10")
    w.alice.set_cell("B1", "=A1-2-3")
    w.alice.set_cell("B2", "=A1/2/5")
    w.alice.set_cell("B3", "=2*3-4/2")
    check(w.alice.value("B1"), 5, "=10-2-3 (associativité à gauche)")
    check(w.alice.value("B2"), 1, "=10/2/5 (associativité à gauche)")
    check(w.alice.value("B3"), 4, "=2*3-4/2")


def test_A04_trou2_moins_unaire(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("B1", "=-A1+3")
    w.alice.set_cell("B2", "=-(A1+1)")
    check(w.alice.value("B1"), 1, "=-A1+3")
    check(w.alice.value("B2"), -3, "=-(A1+1)")


def test_A04_trou2_espaces_et_decimaux(w):
    w.alice.set_cell("A1", "1.5")
    w.alice.set_cell("B1", "=A1*2")
    w.alice.set_cell("B2", "= A1 + 0.5")
    check(w.alice.value("B1"), 3, "=A1*2 avec A1=1.5")
    check(w.alice.value("B2"), 2, "= A1 + 0.5 (espaces)")


def test_A04_trou2_colonnes_a_deux_lettres(w):
    w.alice.set_cell("AA10", "4")
    w.alice.set_cell("AB2", "6")
    w.alice.set_cell("B1", "=AA10+AB2")
    check(w.alice.value("B1"), 10, "=AA10+AB2")
    w.alice.set_cell("AA10", "5")
    check(w.alice.value("B1"), 11, "recalcul après AA10=5")


def test_A04_trou2_litteraux(w):
    w.alice.set_cell("B1", "=2+3*4")
    check(w.alice.value("B1"), 14, "=2+3*4")


def test_A14_trou2_egal_seul(w):
    w.alice.set_cell("B1", "=")
    check(w.alice.content("B1"), "=", "contenu conservé")
    check(w.alice.error("B1"), "#SYNTAXE!", "erreur de syntaxe pour '='")


# ---------------------------------------------------------------- graphe de dépendances

def test_A08_trou2_ordre_topologique(w):
    # C1 est saisi avant B1 : un recalcul dans l'ordre de saisie lirait B1 périmé
    w.alice.set_cell("C1", "=B1+A1")
    w.alice.set_cell("B1", "=A1+1")
    w.alice.set_cell("A1", "1")
    check(w.alice.value("C1"), 3, "C1 initial")
    w.alice.set_cell("A1", "10")
    check(w.alice.value("C1"), 21, "C1 après A1=10 (B1 doit être recalculé avant C1)")


def test_A08_trou2_losange(w):
    w.alice.set_cell("A1", "1")
    w.alice.set_cell("B1", "=A1*2")
    w.alice.set_cell("C1", "=A1*3")
    w.alice.set_cell("D1", "=B1+C1")
    check(w.alice.value("D1"), 5, "D1 initial")
    w.alice.set_cell("A1", "2")
    check(w.alice.value("D1"), 10, "D1 après A1=2")


def test_A16_trou2_losange_pas_circulaire(w):
    w.alice.set_cell("A1", "1")
    w.alice.set_cell("B1", "=A1*2")
    w.alice.set_cell("C1", "=A1*3")
    w.alice.set_cell("D1", "=B1+C1+A1")
    check(w.alice.error("D1"), None, "un losange n'est pas un cycle")
    check(w.alice.value("D1"), 6, "D1")


def test_A08_trou2_chaine_profonde(w):
    n = 1200
    w.alice.set_cell("A1", "1")
    for i in range(2, n + 1):
        w.alice.set_cell(f"A{i}", f"=A{i-1}+1")
    check(w.alice.value(f"A{n}"), n, "bout de chaîne initial")
    w.alice.set_cell("A1", "100")
    check(w.alice.value(f"A{n}"), n + 99, "bout de chaîne après A1=100")
    check(w.alice.error(f"A{n}"), None, "aucune erreur en bout de chaîne")


def test_A15_trou2_cycle_par_plage(w):
    w.alice.set_cell("A1", "=SOMME(B1:B3)")
    w.alice.set_cell("B2", "=A1+1")
    check(w.alice.error("A1"), "#CIRC!", "A1")
    check(w.alice.error("B2"), "#CIRC!", "B2")


def test_A18_trou2_cycle_rompu_par_effacement(w):
    w.alice.set_cell("B1", "=A1")
    w.alice.set_cell("A1", "=B1")
    w.alice.clear("B1")
    check(w.alice.error("A1"), None, "erreur de A1 après effacement de B1")
    check(w.alice.value("A1"), 0, "valeur de A1 (B1 vide vaut zéro)")


def test_A20_trou2_dependant_retrouve_sa_valeur(w):
    w.alice.set_cell("B1", "=A1")
    w.alice.set_cell("A1", "=B1")
    w.alice.set_cell("C1", "=A1+1")
    assert w.alice.error("C1") is not None, "C1 en erreur pendant le cycle"
    w.alice.set_cell("B1", "7")
    check(w.alice.error("C1"), None, "erreur de C1 après rupture")
    check(w.alice.value("C1"), 8, "valeur de C1 après rupture")


def test_A21_trou2_cycle_entre_feuilles_rompu(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.set_cell("A1", "=Feuille1!A1", sheet="Feuille2")
    w.alice.set_cell("A1", "3", sheet="Feuille2")
    check(w.alice.error("A1", sheet="Feuille1"), None, "Feuille1!A1 après rupture")
    check(w.alice.value("A1", sheet="Feuille1"), 3, "Feuille1!A1 après rupture")


def test_A10_trou2_erreur_type_propagee(w):
    w.alice.set_cell("A1", "abc")
    w.alice.set_cell("B1", "=A1+1")
    w.alice.set_cell("C1", "=B1*2")
    assert w.alice.error("C1") is not None, f"C1 dépend d'une erreur, valeur {w.alice.value('C1')!r}"


def test_A12_trou2_dependant_de_l_erreur_retabli(w):
    w.alice.set_cell("A1", "8")
    w.alice.set_cell("B1", "0")
    w.alice.set_cell("C1", "=A1/B1")
    w.alice.set_cell("D1", "=C1+1")
    assert w.alice.error("D1") is not None, "D1 en erreur tant que C1 l'est"
    w.alice.set_cell("B1", "4")
    check(w.alice.error("D1"), None, "erreur de D1 après B1=4")
    check(w.alice.value("D1"), 3, "valeur de D1 après B1=4")


def test_A09_trou2_somme_de_cellules_vides(w):
    w.alice.set_cell("B1", "=SOMME(A1:A3)")
    check(w.alice.value("B1"), 0, "SOMME de cellules vides")


def test_A28_trou2_plage_rectangulaire(w):
    for ref, v in [("A1", "1"), ("B1", "2"), ("A2", "3"), ("B2", "4")]:
        w.alice.set_cell(ref, v)
    w.alice.set_cell("C5", "=SOMME(A1:B2)")
    check(w.alice.value("C5"), 10, "SOMME(A1:B2)")


def test_A28_trou2_somme_composee(w):
    for ref, v in [("A1", "1"), ("A2", "2"), ("B1", "10"), ("B2", "20")]:
        w.alice.set_cell(ref, v)
    w.alice.set_cell("C1", "=SOMME(A1:A2)*2+SOMME(B1:B2)")
    check(w.alice.value("C1"), 36, "=SOMME(A1:A2)*2+SOMME(B1:B2)")


def test_A29_trou2_cellule_vide_remplie_dans_la_plage(w):
    w.alice.set_cell("A1", "1")
    w.alice.set_cell("B1", "=SOMME(A1:A3)")
    w.alice.set_cell("A3", "5")
    check(w.alice.value("B1"), 6, "SOMME après saisie de A3 jusque-là vide")


def test_A44_trou2_reference_non_qualifiee_reste_dans_sa_feuille(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "1", sheet="Feuille1")
    w.alice.set_cell("A1", "100", sheet="Feuille2")
    w.alice.set_cell("B1", "=A1*2", sheet="Feuille2")
    check(w.alice.value("B1", sheet="Feuille2"), 200, "Feuille2!B1 lit Feuille2!A1")
    w.alice.set_cell("A1", "7", sheet="Feuille1")
    check(w.alice.value("B1", sheet="Feuille2"), 200, "Feuille2!B1 insensible à Feuille1!A1")


def test_A22_trou2_nom_de_feuille_accentue(w):
    w.add_sheet("Dépenses")
    w.alice.set_cell("A1", "8", sheet="Dépenses")
    w.alice.set_cell("B1", "=Dépenses!A1", sheet="Feuille1")
    check(w.alice.value("B1", sheet="Feuille1"), 8, "=Dépenses!A1")


def test_A23_trou2_recalcul_entre_feuilles_chez_un_autre(w):
    w.add_sheet("Feuille2")
    w.bob.set_cell("B1", "=Feuille2!A1*2", sheet="Feuille1")
    w.sync()
    w.alice.set_cell("A1", "4", sheet="Feuille2")
    w.sync()
    check(w.bob.value("B1", sheet="Feuille1"), 8, "Feuille1!B1 chez bob après modification distante")
    check(w.carol.value("B1", sheet="Feuille1"), 8, "Feuille1!B1 chez carol")


# ---------------------------------------------------------------- renommage / suppression

def test_A26_trou2_nom_prefixe_non_reecrit(w):
    w.add_sheet("Feuille2")
    w.add_sheet("Feuille20")
    w.alice.set_cell("A1", "2", sheet="Feuille2")
    w.alice.set_cell("A1", "20", sheet="Feuille20")
    w.alice.set_cell("B1", "=Feuille20!A1", sheet="Feuille1")
    w.alice.set_cell("B2", "=Feuille2!A1", sheet="Feuille1")
    w.alice.rename_sheet("Feuille2", "Ventes")
    check(w.alice.content("B1", sheet="Feuille1"), "=Feuille20!A1", "référence à Feuille20 intacte")
    check(w.alice.content("B2", sheet="Feuille1"), "=Ventes!A1", "référence à Feuille2 réécrite")
    check(w.alice.value("B1", sheet="Feuille1"), 20, "valeur de B1")


def test_A26_trou2_texte_non_reecrit(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("C1", "voir Feuille2!A1", sheet="Feuille1")
    w.alice.rename_sheet("Feuille2", "Ventes")
    check(w.alice.content("C1", sheet="Feuille1"), "voir Feuille2!A1", "un texte n'est pas une formule")


def test_A24_trou2_ancien_nom_apres_renommage(w):
    w.add_sheet("Feuille2")
    w.alice.rename_sheet("Feuille2", "Ventes")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    check(w.alice.error("B1", sheet="Feuille1"), "#REF!", "l'ancien nom n'existe plus")


def test_A112_trou2_annuler_renommage_retablit_formule(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.rename_sheet("Feuille2", "Ventes")
    w.alice.undo()
    w.sync()
    for n, c in w.everyone():
        check(c.content("B1", sheet="Feuille1"), "=Feuille2!A1", f"formule chez {n}")
        check(c.value("B1", sheet="Feuille1"), 8, f"valeur chez {n}")


def test_A110_trou2_annuler_suppression_reprend_formule(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.delete_sheet("Feuille2")
    check(w.alice.error("B1", sheet="Feuille1"), "#REF!", "B1 après suppression")
    w.alice.undo()
    w.sync()
    for n, c in w.everyone():
        check(c.error("B1", sheet="Feuille1"), None, f"erreur de B1 chez {n}")
        check(c.value("B1", sheet="Feuille1"), 8, f"valeur de B1 chez {n}")


def test_A45_trou2_suppressions_concurrentes(w):
    w.add_sheet("Feuille2")
    w.alice.delete_sheet("Feuille2")
    w.bob.delete_sheet("Feuille1")
    w.sync()
    lists = {n: c.sheets() for n, c in w.everyone()}
    for n, s in lists.items():
        assert len(s) >= 1, f"le classeur de {n} n'a plus aucune feuille : {lists!r}"
    check(lists["bob"], lists["alice"], "listes de bob et alice convergentes")
    check(lists["carol"], lists["alice"], "listes de carol et alice convergentes")


def test_A42_trou2_renommage_et_ajout_concurrents(w):
    w.alice.rename_sheet("Feuille1", "Budget")
    w.bob.add_sheet("Budget")
    w.sync()
    lists = {n: c.sheets() for n, c in w.everyone()}
    for n, s in lists.items():
        assert len(s) == len(set(s)), f"noms de feuilles en double chez {n} : {lists!r}"
    check(lists["bob"], lists["alice"], "listes convergentes bob/alice")
    check(lists["carol"], lists["alice"], "listes convergentes carol/alice")


# ---------------------------------------------------------------- droits

def test_A46_trou2_droit_par_feuille(w):
    w.add_sheet("Feuille2", bob=R)
    w.bob.set_cell("A1", "x", sheet="Feuille2")
    w.bob.set_cell("A1", "y", sheet="Feuille1")
    check(w.bob.content("A1", sheet="Feuille2"), None, "Feuille2!A1 chez bob (lecture)")
    check(w.bob.content("A1", sheet="Feuille1"), "y", "Feuille1!A1 chez bob (écriture)")
    w.sync()
    check(w.alice.content("A1", sheet="Feuille2"), None, "Feuille2!A1 chez alice")
    check(w.alice.content("A1", sheet="Feuille1"), "y", "Feuille1!A1 chez alice")


def test_A46_trou2_lecteur_hors_ligne(w):
    w.off("carol")
    w.carol.set_cell("A1", "x")
    check(w.carol.content("A1"), None, "A1 chez carol hors ligne")
    check(w.carol.pending_count(), 0, "rien en attente chez carol")
    w.on("carol")
    check(w.alice.content("A1"), None, "A1 chez alice")


def test_A38_trou2_lecteur_cree_sa_feuille(w):
    w.carol.add_sheet("DeCarol")
    check(w.carol.right("carol", "DeCarol"), W, "droit de carol sur sa feuille")
    w.carol.set_cell("A1", "c", sheet="DeCarol")
    w.carol.set_cell("A1", "pirate", sheet="Feuille1")
    w.sync()
    check(w.alice.content("A1", sheet="DeCarol"), "c", "DeCarol!A1 chez alice")
    check(w.alice.content("A1", sheet="Feuille1"), None, "Feuille1!A1 toujours protégée")


def test_A54_trou2_repromotion(w):
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    w.bob.set_cell("A1", "non")
    w.alice.set_right("bob", "Feuille1", W)
    w.sync()
    w.bob.set_cell("A1", "oui")
    w.sync()
    check(w.alice.content("A1"), "oui", "A1 chez alice après repromotion de bob")


def test_A55_trou2_rejet_limite_a_la_feuille(w):
    w.add_sheet("Feuille2")
    w.off("bob")
    w.bob.set_cell("A1", "r", sheet="Feuille1")
    w.bob.set_cell("A1", "ok", sheet="Feuille2")
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    w.on("bob")
    check(w.alice.content("A1", sheet="Feuille1"), None, "Feuille1!A1 rejeté")
    check(w.alice.content("A1", sheet="Feuille2"), "ok", "Feuille2!A1 appliqué")
    rej = alerts_of(w.bob, "modification_rejetee")
    check(sorted({a.sheet for a in rej}), ["Feuille1"], "feuilles désignées par les rejets")


def test_A119_trou2_rejet_sans_entree(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    before = len(w.alice.history())
    w.carol.set_cell("A1", "pirate")
    w.sync()
    check(len(w.alice.history()), before, "entrées après tentative d'un lecteur")


# ---------------------------------------------------------------- réseau, fusion, conflits

def test_A67_trou2_ordre_de_reception_inverse(w):
    w.alice.set_cell("A1", "1")
    w.bob.set_cell("A1", "2")
    w.net.deliver_from("alice")
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "1", f"A1 chez {n}")
    cf = w.bob.conflict("A1")
    assert cf is not None, "conflit attendu chez bob"
    check((cf.discarded, cf.discarded_by), ("2", "bob"), "valeur et auteur écartés")


def test_A67_trou2_convergence_entrelacee(w):
    w.alice.set_cell("A1", "1")
    w.alice.set_cell("B1", "1")
    w.bob.set_cell("B1", "2")
    w.bob.set_cell("A1", "2")
    w.net.deliver_from("bob")
    w.alice.set_cell("C1", "3")
    w.net.deliver_from("alice")
    w.bob.set_cell("C1", "4")
    w.sync()
    for n, c in w.everyone():
        check([c.content(r) for r in ["A1", "B1", "C1"]], ["2", "2", "3"], f"contenus chez {n}")


def test_A81_trou2_alice_revient_la_premiere(w):
    w.off("alice", "bob")
    w.alice.set_cell("A1", "a")
    w.bob.set_cell("A1", "b")
    w.on("alice")
    w.on("bob")
    for n, c in w.everyone():
        check(c.content("A1"), "a", f"A1 chez {n}")
    cf = w.bob.conflict("A1")
    assert cf is not None, "conflit attendu chez bob"
    check((cf.discarded, cf.discarded_by), ("b", "bob"), "valeur et auteur écartés")


def test_A71_trou2_meme_valeur_hors_ligne(w):
    w.off("alice", "bob")
    w.alice.set_cell("A1", "7")
    w.bob.set_cell("A1", "7")
    w.on("bob")
    w.on("alice")
    for n, c in w.everyone():
        check(c.conflict("A1"), None, f"conflit chez {n}")
        check(c.content("A1"), "7", f"A1 chez {n}")


def test_A78_trou2_cellules_differentes(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.off("bob")
    w.bob.set_cell("B1", "9")
    w.alice.set_cell("A1", "5")
    w.sync()
    w.on("bob")
    for n, c in w.everyone():
        check((c.content("A1"), c.content("B1")), ("5", "9"), f"contenus chez {n}")
        check((c.conflict("A1"), c.conflict("B1")), (None, None), f"conflits chez {n}")


def test_A78_trou2_valeur_vue_avant_coupure(w):
    w.alice.set_cell("A1", "5")
    w.sync()
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.on("bob")
    for n, c in w.everyone():
        check(c.content("A1"), "9", f"A1 chez {n}")
        check(c.conflict("A1"), None, f"conflit chez {n} (bob avait vu 5)")


def test_A80_trou2_modifiee_puis_revenue(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.off("bob")
    w.alice.set_cell("A1", "5")
    w.sync()
    w.alice.set_cell("A1", "1")
    w.sync()
    w.bob.set_cell("A1", "9")
    w.on("bob")
    for n, c in w.everyone():
        check(c.content("A1"), "1", f"A1 chez {n}")
    cf = w.alice.conflict("A1")
    assert cf is not None, "conflit attendu : A1 a été modifiée entre-temps même si sa valeur est revenue"
    check(cf.discarded, "9", "valeur écartée")


def test_A77_trou2_coupure_avant_livraison(w):
    w.bob.set_cell("A1", "9")
    w.off("bob")
    w.sync()
    check(w.alice.content("A1"), None, "A1 chez alice pendant la coupure")
    w.on("bob")
    check(w.alice.content("A1"), "9", "A1 chez alice après retour")
    check(w.bob.pending_count(), 0, "en attente chez bob")
    check(len([v for v in w.alice.history() if v.author == "bob"]), 1, "une seule entrée de bob")


def test_A77_trou2_copie_locale_isolee(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.sync()
    check(w.alice.content("A1"), None, "A1 chez alice avant le retour de bob")
    check(w.carol.content("A1"), None, "A1 chez carol avant le retour de bob")


def test_A119_trou2_pas_de_rejeu_apres_reconnexions(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.on("bob")
    w.off("bob")
    w.on("bob")
    w.off("bob")
    w.on("bob")
    check(len([v for v in w.alice.history() if v.author == "bob"]), 1, "entrées de bob")
    check(w.bob.pending_count(), 0, "en attente chez bob")


def test_A92_trou2_double_reouverture(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.bob.set_cell("A2", "8")
    b3 = w.bob.reopen().reopen()
    check(b3.pending_count(), 2, "en attente après deux réouvertures")
    check((b3.content("A1"), b3.content("A2")), ("9", "8"), "contenus après deux réouvertures")
    w.on("bob")
    check((w.alice.content("A1"), w.alice.content("A2")), ("9", "8"), "chez alice")
    check(len([v for v in w.alice.history() if v.author == "bob"]), 2, "entrées de bob (pas de doublon)")
    check(b3.pending_count(), 0, "en attente après fusion")


def test_A90_trou2_ordre_des_modifications_rejouees(w):
    w.off("bob")
    for v in ["1", "2", "3"]:
        w.bob.set_cell("A1", v)
    w.on("bob")
    for n, c in w.everyone():
        check(c.content("A1"), "3", f"A1 chez {n}")


def test_A88_trou2_repetition(w):
    w.off("bob")
    for i in range(1, 101):
        w.bob.set_cell(f"A{i}", str(i))
    check(w.bob.pending_count(), 100, "en attente après 100 modifications")
    w.on("bob")
    check(w.bob.pending_count(), 0, "en attente après fusion")
    check(w.alice.content("A100"), "100", "A100 chez alice")


def test_A99_trou2_meme_cellule(w):
    w.off("bob")
    w.bob.set_cell("A1", "1")
    w.bob.set_cell("A1", "2")
    check(w.bob.pending_count(), 2, "en attente après deux modifications de A1")
    w.bob.undo()
    check(w.bob.pending_count(), 1, "en attente après annulation")
    check(w.bob.content("A1"), "1", "A1 chez bob")
    w.on("bob")
    check(w.alice.content("A1"), "1", "A1 chez alice")


def test_A95_trou2_formule_hors_ligne_et_modif_distante(w):
    w.off("bob")
    w.bob.set_cell("B1", "=A1*2")
    w.alice.set_cell("A1", "3")
    w.sync()
    w.on("bob")
    check(w.bob.value("B1"), 6, "B1 chez bob après fusion")
    check(w.alice.value("B1"), 6, "B1 chez alice après fusion")


def test_A82_trou2_autres_feuilles_appliquees(w):
    w.add_sheet("Feuille2")
    w.off("bob")
    w.bob.set_cell("A1", "z", sheet="Feuille2")
    w.bob.set_cell("A1", "garde", sheet="Feuille1")
    w.alice.delete_sheet("Feuille2")
    w.sync()
    w.on("bob")
    check(w.alice.content("A1", sheet="Feuille1"), "garde", "Feuille1!A1 chez alice")
    check(w.bob.pending_count(), 0, "en attente chez bob")
    assert "Feuille2" not in w.bob.sheets(), f"chez bob : {w.bob.sheets()!r}"


def test_A148_trou2_texte_egal_chez_les_autres(w):
    w.alice.import_csv(b"5,=A1+1\n")
    w.sync()
    check(w.bob.content("B1"), "=A1+1", "contenu chez bob")
    check(w.bob.value("B1"), "=A1+1", "valeur chez bob : texte, pas 6")
    check(w.bob.error("B1"), None, "erreur chez bob")
    alice2 = w.alice.reopen()
    check(alice2.value("B1"), "=A1+1", "valeur chez alice après réouverture")


# ---------------------------------------------------------------- présence

def test_A62_trou2_selection_deplacee(w):
    w.add_sheet("Feuille2")
    w.bob.select("C3")
    w.sync()
    w.bob.select("D4", sheet="Feuille2")
    w.sync()
    check(w.alice.presence().get("bob"), ("Feuille2", "D4"), "présence de bob après déplacement")


def test_A64_trou2_presence_revient(w):
    w.bob.select("C3")
    w.sync()
    w.off("alice")
    check(w.alice.presence(), {}, "hors ligne")
    w.on("alice")
    check(w.alice.presence().get("bob"), ("Feuille1", "C3"), "présence de bob après retour d'alice")


# ---------------------------------------------------------------- dates et fuseaux

def test_N01_trou2_passage_heure_hiver(w):
    w.alice.set_cell("A1", "2026-10-24 12:00")
    w.alice.set_cell("B1", "2026-10-25 12:00")
    w.alice.set_cell("C1", "=B1-A1")
    v = w.alice.value("C1")
    assert isinstance(v, (int, float)), f"écart numérique attendu, obtenu {v!r}"
    assert abs(v - 25 / 24) < 1e-9, f"25 h réelles : attendu {25/24!r}, obtenu {v!r}"


def test_N01_trou2_dates_seules(w):
    w.alice.set_cell("A1", "2026-03-28")
    w.alice.set_cell("B1", "2026-03-29")
    w.alice.set_cell("C1", "=B1-A1")
    v = w.alice.value("C1")
    assert isinstance(v, (int, float)), f"écart numérique attendu, obtenu {v!r}"
    assert abs(v - 1) < 1e-9, f"deux dates seules consécutives : attendu 1, obtenu {v!r}"


def test_A32_trou2_fuseaux_a_demi_heure(w):
    w.alice.set_cell("A1", "2026-01-15 12:00")
    w.alice.set_timezone("Asia/Kolkata")
    check(w.alice.value("A1"), "2026-01-15 16:30", "vu depuis Kolkata (+05:30)")
    w.alice.set_timezone("Asia/Kathmandu")
    check(w.alice.value("A1"), "2026-01-15 16:45", "vu depuis Katmandou (+05:45)")


def test_A30_trou2_saisie_depuis_new_york(w):
    w.bob.set_timezone("America/New_York")
    w.bob.set_cell("A1", "2026-01-15 07:00")
    check(w.bob.value("A1"), "2026-01-15 07:00", "chez bob (New York)")
    w.sync()
    check(w.alice.value("A1"), "2026-01-15 13:00", "chez alice (Paris)")


def test_A33_trou2_date_saisie_a_l_extreme_est(w):
    w.bob.set_timezone("Pacific/Kiritimati")
    w.bob.set_cell("A1", "2026-03-15")
    w.sync()
    w.alice.set_timezone("Pacific/Pago_Pago")
    check(w.alice.value("A1"), "2026-03-15", "date seule saisie à UTC+14 vue à UTC-11")


def test_A35_trou2_maintenant_passage_heure_ete():
    w = World(datetime(2026, 3, 29, 0, 30, tzinfo=UTC))
    w.alice.set_cell("B1", "=MAINTENANT()")
    check(w.alice.value("B1"), "2026-03-29 01:30", "avant le passage à l'heure d'été")
    w.clock.advance(timedelta(hours=1))
    check(w.alice.value("B1"), "2026-03-29 03:30", "après le passage à l'heure d'été")


def test_A122_trou2_horodatage_hiver_consulte_en_ete(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.clock.advance(timedelta(days=170))
    check(w.alice.history()[0].timestamp, "2026-01-15 11:00", "horodatage d'hiver consulté en été")


def test_A153_trou2_decalage_demi_heure(w):
    w.alice.import_csv(b"2026-01-15T12:00:00+05:30\n")
    check(w.alice.value("A1"), "2026-01-15 07:30", "12:00+05:30 vu à Paris")


# ---------------------------------------------------------------- CSV

def test_A147_trou2_fins_de_ligne_crlf(w):
    w.alice.import_csv(b"1,2\r\nx,y\r\n")
    got = [w.alice.content(r) for r in ["A1", "B1", "A2", "B2"]]
    check(got, ["1", "2", "x", "y"], "contenus importés depuis CRLF")


def test_A147_trou2_guillemets_doubles(w):
    w.alice.import_csv(b'"dit ""oui""",b\n')
    check(w.alice.content("A1"), 'dit "oui"', "guillemets doublés décodés")
    check(w.alice.content("B1"), "b", "B1")


def test_A149_trou2_saut_de_ligne_dans_un_champ(w):
    w.alice.import_csv(b'"a\nb",c\nd\n')
    check(w.alice.content("A1"), "a\nb", "A1")
    check(w.alice.content("B1"), "c", "B1")
    check(w.alice.content("A2"), "d", "A2")


def test_A152_trou2_bom_utf8(w):
    w.alice.import_csv("﻿Café,x\n".encode("utf-8"))
    check(w.alice.content("A1"), "Café", "A1 sans marque d'ordre d'octets")


def test_A150_trou2_nombre_decimal(w):
    w.alice.set_cell("B5", "=A1*2")
    w.alice.import_csv(b"2.5\n")
    check(w.alice.value("B5"), 5, "B5 avec A1 importé 2.5")


def test_A136_trou2_colonnes_preservees(w):
    w.alice.set_cell("A1", "a")
    w.alice.set_cell("C1", "c")
    w.alice.set_cell("B3", "x")
    r = rows(w.alice.export_csv())
    check(len(r), 2, f"nombre de lignes ({r!r})")
    check(r[0][:3], ["a", "", "c"], "colonnes de la première ligne")
    check(r[1][:2], ["", "x"], "colonnes de la seconde ligne")


def test_A147_trou2_aller_retour(w):
    textes = {"A1": "a,b", "B1": 'dit "oui"', "A2": "l1\nl2", "B2": "Été à Noël"}
    for ref, t in textes.items():
        w.alice.set_cell(ref, t, sheet="Feuille1")
    w.alice.activate("Feuille1")
    data = w.alice.export_csv()
    w.add_sheet("Feuille2")
    w.bob.activate("Feuille2")
    w.bob.import_csv(data)
    for ref, t in textes.items():
        check(w.bob.content(ref, sheet="Feuille2"), t, f"Feuille2!{ref} après aller-retour CSV")


# ---------------------------------------------------------------- annulation

def test_A105_trou2_pile_epuisee(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.bob.set_cell("B1", "2")
    w.sync()
    w.alice.undo()
    check(w.alice.can_undo(), False, "annuler chez alice après sa seule action annulée")
    w.alice.undo()
    w.sync()
    for n, c in w.everyone():
        check(c.content("B1"), "2", f"B1 chez {n}")


def test_A115_trou2_annulations_et_retablissements_multiples(w):
    for v in ["1", "2", "3"]:
        w.alice.set_cell("A1", v)
    w.alice.undo()
    w.alice.undo()
    check(w.alice.content("A1"), "1", "après deux annulations")
    w.alice.redo()
    w.alice.redo()
    check(w.alice.content("A1"), "3", "après deux rétablissements")
    check(w.alice.can_redo(), False, "rétablir épuisé")
    w.sync()
    check(w.bob.content("A1"), "3", "A1 chez bob")


def test_A100_trou2_annuler_effacement(w):
    w.alice.set_cell("A1", "5")
    w.alice.set_cell("B1", "=A1*2")
    w.alice.clear("A1")
    w.alice.undo()
    check(w.alice.content("A1"), "5", "A1 après annulation de l'effacement")
    check(w.alice.value("B1"), 10, "B1 recalculé")


def test_A103_trou2_annulations_en_trop(w):
    w.alice.set_cell("A1", "1")
    for _ in range(5):
        w.alice.undo()
    check(w.alice.content("A1"), None, "A1 après annulations répétées")
    check(w.alice.can_undo(), False, "annuler indisponible")


def test_A158_trou2_retablir_l_import(w):
    w.alice.import_csv(b"1,2\n3,4\n")
    w.alice.undo()
    w.alice.redo()
    w.sync()
    for n, c in w.everyone():
        check([c.content(r) for r in ["A1", "B1", "A2", "B2"]], ["1", "2", "3", "4"], f"chez {n}")


# ---------------------------------------------------------------- versions

def test_A125_trou2_cellule_posterieure_absente(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    v1 = w.alice.history()[0].id
    w.clock.advance(timedelta(minutes=1))
    w.alice.set_cell("C1", "nouveau")
    w.sync()
    w.alice.open_version(v1)
    check(w.alice.content("C1"), None, "C1 n'existait pas dans la version")
    check(w.alice.content("A1"), "1", "A1 dans la version")


def test_A129_trou2_autres_feuilles_intactes(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "1", sheet="Feuille1")
    w.sync()
    v1 = w.alice.history(sheet="Feuille1")[0].id
    w.clock.advance(timedelta(minutes=1))
    w.alice.set_cell("A1", "2", sheet="Feuille1")
    w.alice.set_cell("A1", "x", sheet="Feuille2")
    w.sync()
    w.bob.restore_version(v1)
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1", sheet="Feuille1"), "1", f"Feuille1!A1 chez {n}")
        check(c.content("A1", sheet="Feuille2"), "x", f"Feuille2!A1 chez {n}")


def test_A130_trou2_lecteur_sans_entree(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    v1 = w.alice.history()[0].id
    w.alice.set_cell("A1", "2")
    w.sync()
    before = len(w.alice.history())
    w.carol.restore_version(v1)
    w.sync()
    check(len(w.alice.history()), before, "entrées après tentative de restauration par un lecteur")
