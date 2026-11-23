"""Tests rouges — couche code — sonde P11 (classeur collaboratif hors ligne).

Interface publique de `app` fixée par ces tests (le constructeur l'implémente telle quelle) :

    clock = app.Clock(start: datetime aware)        # temps simulé
        clock.now() -> datetime aware (UTC)
        clock.advance(delta: timedelta)
    net = app.Network()                              # réseau simulé en mémoire
        net.deliver_all()          # livre tous les messages jusqu'au repos (FIFO)
        net.deliver_from(name)     # livre uniquement les messages actuellement en vol émis par `name`
        net.disconnect(name)       # coupe `name` du réseau (ses messages ne passent plus)
        net.reconnect(name)        # rétablit `name` ; la resynchronisation se fait au deliver_all suivant
    server = app.Server(net, clock, owner="alice")   # classeur initial : une feuille "Feuille1"
    c = app.Client(net, clock, name, tz="Europe/Paris")   # copie locale propre à la personne

Client :
    set_cell(ref, text, sheet=None)      # saisie (texte tel que tapé : "42", "Budget", "=A1+A2", "2026-01-15 12:00", "2026-03-15")
    clear(ref, sheet=None)
    content(ref, sheet=None) -> str | None          # barre de formule ; None = sans contenu
    value(ref, sheet=None) -> int|float|str|None     # valeur affichée ; date-heure : "AAAA-MM-JJ HH:MM" dans le fuseau du client ;
                                                     # date seule : "AAAA-MM-JJ" ; en erreur : le code d'erreur
    error(ref, sheet=None) -> str | None             # "#TYPE!", "#DIV/0!", "#SYNTAXE!", "#CIRC!", "#REF!"
    set_timezone(tz)
    sheets() -> list[str]; activate(name); add_sheet(name); delete_sheet(name); rename_sheet(old, new)
    right(person, sheet) -> "écriture" | "lecture" | None ; set_right(person, sheet, level)
    alerts() -> list[Alert]  (Alert : .kind, .sheet, .cell, .line ; absent = None)
        kinds : "droit_insuffisant", "nom_existant", "modification_rejetee", "feuille_supprimee",
                "annulation_impossible", "csv_invalide"
    connection_status() -> "en ligne" | "hors ligne"
    pending_count() -> int
    select(ref, sheet=None); presence() -> dict[name, (sheet, ref)]  (sans soi-même)
    conflict(ref, sheet=None) -> None | Conflict (.discarded : contenu écarté, .discarded_by : nom)
    resolve_conflict(ref, use_discarded: bool, sheet=None)
    undo(); redo(); can_undo() -> bool; can_redo() -> bool
    reopen() -> Client     # ferme l'application puis la rouvre depuis le stockage de l'appareil
    history(sheet=None) -> list[Version] (plus récente d'abord ; Version : .id, .author, .timestamp "AAAA-MM-JJ HH:MM" fuseau du client, .kind)
        .kind == "restauration" pour une restauration
    open_version(version_id); close_version(); restore_version(version_id)
    export_csv() -> bytes (UTF-8, feuille active) ; import_csv(data: bytes) (UTF-8, à partir de A1 de la feuille active)
"""
import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

import app

UTC = timezone.utc
T0 = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)       # hiver : Paris = UTC+1
T_ETE = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)     # été : Paris = UTC+2
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


# ---------------------------------------------------------------- saisie, valeurs

def test_A01_saisie_nombre_contenu_par_personne_en_ecriture(w):
    w.bob.set_cell("C3", "42")
    check(w.bob.content("C3"), "42", "contenu de C3 après saisie de 42 par bob (droit écriture)")


def test_A02_saisie_nombre_valeur_numerique(w):
    w.bob.set_cell("C3", "42")
    v = w.bob.value("C3")
    assert isinstance(v, (int, float)) and not isinstance(v, bool), f"valeur numérique attendue, obtenu {v!r}"
    check(v, 42, "valeur de C3")


def test_A03_saisie_texte(w):
    w.alice.set_cell("A1", "Budget")
    check(w.alice.value("A1"), "Budget", "valeur de A1")


def test_A04_formule_addition(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("A2", "3")
    w.alice.set_cell("A3", "=A1+A2")
    check(w.alice.value("A3"), 5, "valeur de =A1+A2")


def test_A04_trou_priorite_operateurs(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("A2", "3")
    w.alice.set_cell("B1", "=A1+A2*2")
    w.alice.set_cell("B2", "=(A1+A2)*2")
    check(w.alice.value("B1"), 8, "=A1+A2*2 (priorité de * sur +)")
    check(w.alice.value("B2"), 10, "=(A1+A2)*2 (parenthèses)")


def test_A05_contenu_formule_barre(w):
    w.alice.set_cell("A3", "=A1+A2")
    check(w.alice.content("A3"), "=A1+A2", "contenu de la barre de formule")


def test_A06_recalcul_apres_remplacement(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("B1", "=A1*2")
    w.alice.set_cell("A1", "10")
    check(w.alice.value("B1"), 20, "B1 après A1=10")


def test_A07_cellule_non_dependante_inchangee(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("B1", "=A1*2")
    w.alice.set_cell("C5", "100")
    check(w.alice.value("B1"), 4, "B1 après modification de C5")


def test_A08_recalcul_en_chaine(w):
    w.alice.set_cell("A1", "1")
    w.alice.set_cell("B1", "=A1+1")
    w.alice.set_cell("C1", "=B1+1")
    check(w.alice.value("C1"), 3, "C1 initial")
    w.alice.set_cell("A1", "10")
    check(w.alice.value("C1"), 12, "C1 après A1=10")


def test_A08_recalcul_chaine_saisie_dans_le_desordre(w):
    w.alice.set_cell("C1", "=B1+1")
    w.alice.set_cell("B1", "=A1+1")
    w.alice.set_cell("A1", "5")
    check(w.alice.value("C1"), 7, "C1 saisi avant ses dépendances")


def test_A09_effacer_vaut_zero(w):
    w.alice.set_cell("A1", "3")
    w.alice.set_cell("B1", "=A1+5")
    check(w.alice.value("B1"), 8, "B1 avant effacement")
    w.alice.clear("A1")
    check(w.alice.content("A1"), None, "contenu de A1 effacé")
    check(w.alice.value("B1"), 5, "B1 après effacement de A1")


def test_A10_erreur_type(w):
    w.alice.set_cell("A1", "abc")
    w.alice.set_cell("B1", "=A1+1")
    check(w.alice.error("B1"), "#TYPE!", "erreur de B1")


def test_A11_division_par_zero(w):
    w.alice.set_cell("A1", "8")
    w.alice.set_cell("B1", "0")
    w.alice.set_cell("C1", "=A1/B1")
    check(w.alice.error("C1"), "#DIV/0!", "erreur de C1")


def test_A12_erreur_division_disparait(w):
    w.alice.set_cell("A1", "8")
    w.alice.set_cell("B1", "0")
    w.alice.set_cell("C1", "=A1/B1")
    w.alice.set_cell("B1", "4")
    check(w.alice.error("C1"), None, "erreur de C1 après B1=4")
    check(w.alice.value("C1"), 2, "valeur de C1 après B1=4")


def test_A13_formule_incomplete_erreur_syntaxe(w):
    w.alice.set_cell("B1", "=A1+")
    check(w.alice.error("B1"), "#SYNTAXE!", "erreur de =A1+")


@pytest.mark.parametrize("texte", ["=A1+", "=(A1+2", "=A1+*2", "=SOMME(A1:A3", "=A1 A2", "=A1)"])
def test_A14_syntaxe_invalide_contenu_conserve(w, texte):
    w.alice.set_cell("B1", texte)
    check(w.alice.content("B1"), texte, "contenu conservé après formule invalide")
    check(w.alice.error("B1"), "#SYNTAXE!", f"erreur de syntaxe pour {texte}")


def test_A15_auto_reference(w):
    w.alice.set_cell("A1", "=A1+1")
    check(w.alice.error("A1"), "#CIRC!", "erreur de A1")


def test_A15_trou_somme_incluant_soi(w):
    w.alice.set_cell("A1", "1")
    w.alice.set_cell("A3", "3")
    w.alice.set_cell("A2", "=SOMME(A1:A3)")
    check(w.alice.error("A2"), "#CIRC!", "SOMME dont la plage contient la cellule")


def test_A16_cycle_deux_cellules_A1(w):
    w.alice.set_cell("B1", "=A1")
    w.alice.set_cell("A1", "=B1")
    check(w.alice.error("A1"), "#CIRC!", "erreur de A1")


def test_A16_trou_cycle_long(w):
    w.alice.set_cell("B1", "=C1+1")
    w.alice.set_cell("C1", "=D1+1")
    w.alice.set_cell("D1", "=E1+1")
    w.alice.set_cell("E1", "=A1+1")
    w.alice.set_cell("A1", "=B1+1")
    for ref in ["A1", "B1", "C1", "D1", "E1"]:
        check(w.alice.error(ref), "#CIRC!", f"erreur de {ref} dans un cycle de 5")


def test_A17_cycle_deux_cellules_B1(w):
    w.alice.set_cell("B1", "=A1")
    w.alice.set_cell("A1", "=B1")
    check(w.alice.error("B1"), "#CIRC!", "erreur de B1")


def test_A18_cycle_rompu_erreur_disparait(w):
    w.alice.set_cell("B1", "=A1")
    w.alice.set_cell("A1", "=B1")
    w.alice.set_cell("B1", "7")
    check(w.alice.error("A1"), None, "erreur de A1 après rupture du cycle")


def test_A19_cycle_rompu_valeur(w):
    w.alice.set_cell("B1", "=A1")
    w.alice.set_cell("A1", "=B1")
    w.alice.set_cell("B1", "7")
    check(w.alice.value("A1"), 7, "valeur de A1 après rupture du cycle")


def test_A20_dependant_d_un_cycle(w):
    w.alice.set_cell("B1", "=A1")
    w.alice.set_cell("A1", "=B1")
    w.alice.set_cell("C1", "=A1")
    assert w.alice.error("C1") is not None, f"C1 devrait être en erreur, valeur {w.alice.value('C1')!r}"


def test_A21_cycle_entre_feuilles(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.set_cell("A1", "=Feuille1!A1", sheet="Feuille2")
    check(w.alice.error("A1", sheet="Feuille1"), "#CIRC!", "Feuille1!A1")
    check(w.alice.error("A1", sheet="Feuille2"), "#CIRC!", "Feuille2!A1")


def test_A22_reference_autre_feuille(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    check(w.alice.value("B1", sheet="Feuille1"), 8, "Feuille1!B1")


def test_A23_recalcul_entre_feuilles(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.set_cell("A1", "11", sheet="Feuille2")
    check(w.alice.value("B1", sheet="Feuille1"), 11, "Feuille1!B1 après modification")


def test_A24_feuille_inexistante(w):
    w.alice.set_cell("B1", "=Inexistante!A1")
    check(w.alice.error("B1"), "#REF!", "erreur de B1")


def test_A25_feuille_supprimee(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.delete_sheet("Feuille2")
    check(w.alice.error("B1", sheet="Feuille1"), "#REF!", "B1 après suppression de Feuille2")


def test_A26_renommage_reecrit_formule(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.rename_sheet("Feuille2", "Ventes")
    check(w.alice.content("B1", sheet="Feuille1"), "=Ventes!A1", "contenu de B1 chez alice")
    w.sync()
    check(w.bob.content("B1", sheet="Feuille1"), "=Ventes!A1", "contenu de B1 chez bob")


def test_A27_renommage_garde_valeur(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.rename_sheet("Feuille2", "Ventes")
    check(w.alice.value("B1", sheet="Feuille1"), 8, "valeur de B1")
    check(w.alice.error("B1", sheet="Feuille1"), None, "erreur de B1")


def test_A28_somme(w):
    for ref, v in [("A1", "1"), ("A2", "2"), ("A3", "3")]:
        w.alice.set_cell(ref, v)
    w.alice.set_cell("B1", "=SOMME(A1:A3)")
    check(w.alice.value("B1"), 6, "SOMME(A1:A3)")


def test_A29_somme_recalculee(w):
    for ref, v in [("A1", "1"), ("A2", "2"), ("A3", "3")]:
        w.alice.set_cell(ref, v)
    w.alice.set_cell("B1", "=SOMME(A1:A3)")
    w.alice.set_cell("A2", "20")
    check(w.alice.value("B1"), 24, "SOMME après A2=20")


# ---------------------------------------------------------------- dates et fuseaux

def test_A30_date_heure_dans_fuseau_de_la_personne(w):
    w.alice.set_cell("A1", "2026-07-01 12:00")
    check(w.alice.value("A1"), "2026-07-01 12:00", "date-heure chez alice (Paris)")


def test_A30_date_heure_ete_vue_depuis_utc(w):
    w.alice.set_cell("A1", "2026-07-01 12:00")
    w.sync()
    check(w.bob.value("A1"), "2026-07-01 10:00", "12:00 Paris en été (UTC+2) vu en UTC")


def test_A31_paris_hiver_vu_en_utc(w):
    w.alice.set_cell("A1", "2026-01-15 12:00")
    w.sync()
    check(w.bob.value("A1"), "2026-01-15 11:00", "12:00 Paris en hiver vu en UTC")


def test_A32_changement_de_fuseau(w):
    w.alice.set_cell("A1", "2026-07-01 12:00")
    w.alice.set_timezone("America/New_York")
    check(w.alice.value("A1"), "2026-07-01 06:00", "après passage à New York")


def test_A33_date_seule_meme_jour(w):
    w.alice.set_cell("A1", "2026-03-15")
    w.sync()
    for tz in ["UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"]:
        w.bob.set_timezone(tz)
        check(w.bob.value("A1"), "2026-03-15", f"date seule vue depuis {tz}")


def test_A34_ecart_identique_entre_fuseaux(w):
    w.alice.set_cell("A1", "2026-03-28 12:00")
    w.alice.set_cell("B1", "2026-03-29 12:00")
    w.alice.set_cell("C1", "=B1-A1")
    w.sync()
    w.bob.set_timezone("America/New_York")
    check(w.bob.value("C1"), w.alice.value("C1"), "écart vu par bob vs alice")


def test_A34_trou_unite_ecart(w):
    w.alice.set_cell("A1", "2026-03-28 12:00")
    w.alice.set_cell("B1", "2026-03-29 12:00")
    w.alice.set_cell("C1", "=B1-A1")
    v = w.alice.value("C1")
    assert isinstance(v, (int, float)), f"écart numérique attendu, obtenu {v!r}"
    assert abs(v - 23 / 24) < 1e-9, f"écart en jours écoulés réels (23 h à cause de l'heure d'été) : attendu {23/24!r}, obtenu {v!r}"


def test_A35_maintenant_dans_fuseau_du_lecteur():
    w = World(T_ETE)
    w.alice.set_cell("B1", "=MAINTENANT()")
    w.sync()
    check(w.alice.value("B1"), "2026-07-01 12:00", "MAINTENANT chez alice (Paris été)")
    check(w.bob.value("B1"), "2026-07-01 10:00", "MAINTENANT chez bob (UTC)")
    w.clock.advance(timedelta(hours=1))
    check(w.alice.value("B1"), "2026-07-01 13:00", "MAINTENANT après une heure")


# ---------------------------------------------------------------- feuilles

def test_A36_ajout_feuille(w):
    w.alice.add_sheet("Feuille2")
    assert "Feuille2" in w.alice.sheets(), f"Feuille2 absente de {w.alice.sheets()!r}"


def test_A37_nouvelle_feuille_vide(w):
    w.alice.set_cell("A1", "x", sheet="Feuille1")
    w.alice.add_sheet("Feuille2")
    for ref in ["A1", "B2", "Z99"]:
        check(w.alice.content(ref, sheet="Feuille2"), None, f"Feuille2!{ref}")


def test_A38_createur_obtient_ecriture(w):
    w.bob.add_sheet("DeBob")
    check(w.bob.right("bob", "DeBob"), W, "droit de bob sur sa feuille")
    w.bob.set_cell("A1", "1", sheet="DeBob")
    w.sync()
    check(w.alice.content("A1", sheet="DeBob"), "1", "saisie de bob dans sa feuille, vue par alice")


def test_A39_suppression_par_ecrivain(w):
    w.add_sheet("Feuille2")
    w.bob.delete_sheet("Feuille2")
    assert "Feuille2" not in w.bob.sheets(), f"listes chez bob : {w.bob.sheets()!r}"
    w.sync()
    assert "Feuille2" not in w.alice.sheets(), f"listes chez alice : {w.alice.sheets()!r}"


def test_A40_suppression_par_lecteur_refusee(w):
    w.add_sheet("Feuille2")
    w.carol.delete_sheet("Feuille2")
    w.sync()
    assert "Feuille2" in w.carol.sheets(), f"chez carol : {w.carol.sheets()!r}"
    assert "Feuille2" in w.alice.sheets(), f"chez alice : {w.alice.sheets()!r}"


def test_A41_renommage(w):
    w.bob.rename_sheet("Feuille1", "Ventes")
    check(w.bob.sheets(), ["Ventes"], "liste chez bob")
    w.sync()
    check(w.alice.sheets(), ["Ventes"], "liste chez alice")


def test_A42_renommage_nom_existant(w):
    w.add_sheet("Feuille2")
    w.alice.rename_sheet("Feuille1", "Feuille2")
    w.sync()
    check(w.alice.sheets(), ["Feuille1", "Feuille2"], "liste après renommage refusé")


def test_A42_trou_casse_differente(w):
    w.add_sheet("Feuille2")
    w.alice.rename_sheet("Feuille1", "FEUILLE2")
    w.sync()
    check(w.alice.sheets(), ["Feuille1", "Feuille2"], "nom ne différant que par la casse")


def test_A43_alerte_nom_existant(w):
    w.add_sheet("Feuille2")
    w.alice.rename_sheet("Feuille1", "Feuille2")
    assert "nom_existant" in kinds(w.alice), f"alertes : {kinds(w.alice)!r}"


def test_A44_feuilles_independantes(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "f2", sheet="Feuille2")
    w.alice.set_cell("A1", "f1", sheet="Feuille1")
    check(w.alice.content("A1", sheet="Feuille2"), "f2", "Feuille2!A1")


def test_A45_derniere_feuille(w):
    w.alice.delete_sheet("Feuille1")
    w.sync()
    check(w.alice.sheets(), ["Feuille1"], "liste après tentative de suppression de la dernière feuille")


# ---------------------------------------------------------------- droits

def test_A46_lecteur_ne_modifie_pas(w):
    w.alice.set_cell("A1", "orig")
    w.sync()
    w.carol.set_cell("A1", "pirate")
    check(w.carol.content("A1"), "orig", "contenu chez carol")
    w.sync()
    check(w.alice.content("A1"), "orig", "contenu chez alice")


def test_A47_alerte_droit_lecture(w):
    w.carol.set_cell("A1", "pirate")
    found = alerts_of(w.carol, "droit_insuffisant")
    assert found, f"alerte droit_insuffisant attendue, alertes : {kinds(w.carol)!r}"


def test_A48_lecteur_voit_valeurs(w):
    w.alice.set_cell("A1", "3")
    w.alice.set_cell("B1", "=A1*2")
    w.sync()
    check(w.carol.value("B1"), 6, "B1 chez carol")


def test_A49_lecteur_voit_recalcul(w):
    w.alice.set_cell("A1", "3")
    w.alice.set_cell("B1", "=A1*2")
    w.sync()
    w.bob.set_cell("A1", "10")
    w.sync()
    check(w.carol.value("B1"), 20, "B1 chez carol après modification de bob")


def test_A50_proprietaire_retrograde(w):
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    check(w.alice.right("bob", "Feuille1"), R, "droit vu par alice")
    check(w.bob.right("bob", "Feuille1"), R, "droit vu par bob")


def test_A51_non_proprietaire_ne_change_pas_les_droits(w):
    w.bob.set_right("carol", "Feuille1", W)
    w.sync()
    check(w.alice.right("carol", "Feuille1"), R, "droit de carol vu par alice")
    w.carol.set_cell("A1", "x")
    w.sync()
    check(w.alice.content("A1"), None, "carol ne doit pas pouvoir écrire")


def test_A52_proprietaire_hors_ligne(w):
    w.off("alice")
    w.alice.set_right("bob", "Feuille1", R)
    check(w.alice.right("bob", "Feuille1"), W, "droit vu par alice hors ligne")


def test_A52_trou_pas_applique_au_retour(w):
    w.off("alice")
    w.alice.set_right("bob", "Feuille1", R)
    w.on("alice")
    check(w.bob.right("bob", "Feuille1"), W, "droit de bob après retour d'alice")
    w.bob.set_cell("A1", "ok")
    w.sync()
    check(w.alice.content("A1"), "ok", "bob écrit toujours")


def test_A53_formule_vers_feuille_en_lecture(w):
    w.add_sheet("Feuille2", bob=R)
    w.alice.set_cell("A1", "8", sheet="Feuille2")
    w.sync()
    w.bob.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    check(w.bob.value("B1", sheet="Feuille1"), 8, "B1 chez bob")


def test_A54_retrogradation_en_ligne(w):
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    w.bob.set_cell("A1", "x")
    check(w.bob.content("A1"), None, "contenu chez bob")
    w.sync()
    check(w.alice.content("A1"), None, "contenu chez alice")


def test_A55_modif_hors_ligne_rejetee(w):
    w.alice.set_cell("A1", "orig")
    w.sync()
    w.off("bob")
    w.bob.set_cell("A1", "hors")
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    w.on("bob")
    check(w.alice.content("A1"), "orig", "A1 chez alice")
    check(w.carol.content("A1"), "orig", "A1 chez carol")


def test_A55_trou_copie_locale_revient(w):
    w.alice.set_cell("A1", "orig")
    w.sync()
    w.off("bob")
    w.bob.set_cell("A1", "hors")
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    w.on("bob")
    check(w.bob.content("A1"), "orig", "copie de bob après rejet")
    check(w.bob.pending_count(), 0, "modifications en attente de bob après rejet")


def test_A56_alerte_cellule_rejetee(w):
    w.off("bob")
    w.bob.set_cell("A1", "hors")
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    w.on("bob")
    found = alerts_of(w.bob, "modification_rejetee")
    assert found, f"alerte modification_rejetee attendue, alertes : {kinds(w.bob)!r}"
    assert any(a.cell == "A1" and a.sheet == "Feuille1" for a in found), \
        f"l'alerte doit désigner Feuille1!A1, obtenu {[(a.sheet, a.cell) for a in found]!r}"


def test_A57_import_par_lecteur(w):
    w.alice.set_cell("A1", "orig")
    w.sync()
    w.carol.import_csv(b"x,y\n")
    check(w.carol.content("A1"), "orig", "A1 chez carol")
    check(w.carol.content("B1"), None, "B1 chez carol")
    w.sync()
    check(w.alice.content("A1"), "orig", "A1 chez alice")


def test_A58_lecteur_voit_historique(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    h = w.carol.history()
    assert h, "historique vide chez carol"
    check(h[0].author, "alice", "auteur de la dernière version")


# ---------------------------------------------------------------- collaboration

def test_A59_mise_a_jour_en_ligne(w):
    w.alice.set_cell("A1", "5")
    w.sync()
    check(w.bob.content("A1"), "5", "A1 chez bob")


def test_A60_hors_ligne_garde_ancien(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.off("bob")
    w.alice.set_cell("A1", "5")
    w.sync()
    check(w.bob.content("A1"), "1", "A1 chez bob hors ligne")


def test_A61_retour_en_ligne(w):
    w.off("bob")
    w.alice.set_cell("A1", "5")
    w.sync()
    w.on("bob")
    check(w.bob.content("A1"), "5", "A1 chez bob revenu")


def test_A62_presence(w):
    w.bob.select("C3")
    w.sync()
    check(w.alice.presence().get("bob"), ("Feuille1", "C3"), "présence de bob chez alice")


def test_A63_presence_disparait(w):
    w.bob.select("C3")
    w.sync()
    w.off("bob")
    w.sync()
    assert "bob" not in w.alice.presence(), f"présences : {w.alice.presence()!r}"


def test_A64_hors_ligne_sans_presence(w):
    w.bob.select("C3")
    w.carol.select("D4")
    w.sync()
    w.off("alice")
    check(w.alice.presence(), {}, "présences chez alice hors ligne")


def test_A65_premiere_garde_sa_modification(w):
    w.alice.set_cell("A1", "x")
    w.bob.set_cell("B1", "y")
    w.net.deliver_from("bob")
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "x", f"A1 chez {n}")


def test_A66_seconde_garde_sa_modification(w):
    w.alice.set_cell("A1", "x")
    w.bob.set_cell("B1", "y")
    w.sync()
    for n, c in w.everyone():
        check(c.content("B1"), "y", f"B1 chez {n}")


def test_A67_premiere_recue_par_serveur(w):
    w.alice.set_cell("A1", "1")
    w.bob.set_cell("A1", "2")
    w.net.deliver_from("bob")   # bob arrive au serveur en premier, bien qu'alice ait saisi avant
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "2", f"A1 chez {n}")


def _conflict(w, preset_b1=False):
    if preset_b1:
        w.alice.set_cell("B1", "=A1*2")
        w.sync()
    w.alice.set_cell("A1", "1")
    w.bob.set_cell("A1", "2")
    w.net.deliver_from("bob")
    w.sync()


def test_A68_indicateur_conflit(w):
    _conflict(w)
    assert w.alice.conflict("A1") is not None, "conflit attendu sur A1 chez alice"


def test_A68_trou_visible_chez_tous(w):
    _conflict(w)
    for n, c in w.everyone():
        assert c.conflict("A1") is not None, f"conflit attendu sur A1 chez {n}"


def test_A69_valeur_ecartee(w):
    _conflict(w)
    check(w.alice.conflict("A1").discarded, "1", "valeur écartée proposée")


def test_A70_nom_ecarte(w):
    _conflict(w)
    check(w.bob.conflict("A1").discarded_by, "alice", "personne écartée")


def test_A71_meme_valeur_pas_de_conflit(w):
    w.alice.set_cell("A1", "7")
    w.bob.set_cell("A1", "7")
    w.sync()
    for n, c in w.everyone():
        check(c.conflict("A1"), None, f"conflit chez {n}")


def test_A72_choisir_valeur_ecartee(w):
    _conflict(w)
    w.bob.resolve_conflict("A1", use_discarded=True)
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "1", f"A1 chez {n}")


def test_A73_choix_fait_disparaitre_conflit(w):
    _conflict(w)
    w.bob.resolve_conflict("A1", use_discarded=False)
    w.sync()
    for n, c in w.everyone():
        check(c.conflict("A1"), None, f"conflit chez {n}")
        check(c.content("A1"), "2", f"A1 chez {n}")


def test_A74_nouvelle_saisie_fait_disparaitre_conflit(w):
    _conflict(w)
    w.alice.set_cell("A1", "3")
    w.sync()
    for n, c in w.everyone():
        check(c.conflict("A1"), None, f"conflit chez {n}")


def test_A75_lecteur_ne_resout_pas(w):
    _conflict(w)
    w.carol.resolve_conflict("A1", use_discarded=True)
    w.sync()
    assert w.alice.conflict("A1") is not None, "conflit toujours attendu chez alice"
    assert w.carol.conflict("A1") is not None, "conflit toujours attendu chez carol"
    check(w.alice.content("A1"), "2", "A1 chez alice")


def test_A76_resolution_recalcule(w):
    _conflict(w, preset_b1=True)
    check(w.alice.value("B1"), 4, "B1 avant résolution")
    w.alice.resolve_conflict("A1", use_discarded=True)
    w.sync()
    check(w.alice.value("B1"), 2, "B1 chez alice")
    check(w.carol.value("B1"), 2, "B1 chez carol")


def test_A77_modif_hors_ligne_appliquee(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.on("bob")
    for n, c in w.everyone():
        check(c.content("A1"), "9", f"A1 chez {n}")


def test_A78_modif_hors_ligne_sans_conflit(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.on("bob")
    for n, c in w.everyone():
        check(c.conflict("A1"), None, f"conflit chez {n}")


def _offline_vs_online(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.alice.set_cell("A1", "5")
    w.sync()
    w.on("bob")


def test_A79_en_ligne_l_emporte(w):
    _offline_vs_online(w)
    for n, c in w.everyone():
        check(c.content("A1"), "5", f"A1 chez {n}")


def test_A80_conflit_au_retour(w):
    _offline_vs_online(w)
    for n, c in [("alice", w.alice), ("bob", w.bob)]:
        cf = c.conflict("A1")
        assert cf is not None, f"conflit attendu chez {n}"
        check(cf.discarded, "9", f"valeur écartée chez {n}")
        check(cf.discarded_by, "bob", f"auteur écarté chez {n}")


def _two_offline(w):
    w.off("alice", "bob")
    w.alice.set_cell("A1", "a")
    w.bob.set_cell("A1", "b")
    w.on("bob")
    w.on("alice")


def test_A81_premier_revenu_l_emporte(w):
    _two_offline(w)
    for n, c in w.everyone():
        check(c.content("A1"), "b", f"A1 chez {n}")


def test_A81_trou_conflit_signale(w):
    _two_offline(w)
    cf = w.alice.conflict("A1")
    assert cf is not None, "conflit attendu chez alice"
    check(cf.discarded, "a", "valeur écartée")
    check(cf.discarded_by, "alice", "auteur écarté")


def _offline_on_deleted_sheet(w):
    w.add_sheet("Feuille2")
    w.off("bob")
    w.bob.set_cell("A1", "z", sheet="Feuille2")
    w.alice.delete_sheet("Feuille2")
    w.sync()
    w.on("bob")


def test_A82_feuille_non_recreee(w):
    _offline_on_deleted_sheet(w)
    for n, c in w.everyone():
        assert "Feuille2" not in c.sheets(), f"Feuille2 recréée chez {n} : {c.sheets()!r}"


def test_A83_alerte_modifications_perdues(w):
    _offline_on_deleted_sheet(w)
    found = alerts_of(w.bob, "feuille_supprimee")
    assert found, f"alerte feuille_supprimee attendue, alertes : {kinds(w.bob)!r}"
    assert any(a.sheet == "Feuille2" for a in found), f"feuilles : {[a.sheet for a in found]!r}"


def test_A84_fusion_recalcule(w):
    w.alice.set_cell("A1", "1")
    w.alice.set_cell("B1", "=A1*2")
    w.sync()
    w.off("bob")
    w.bob.set_cell("A1", "7")
    w.on("bob")
    check(w.alice.value("B1"), 14, "B1 chez alice après fusion")


def test_A85_indicateur_hors_ligne(w):
    w.off("bob")
    check(w.bob.connection_status(), "hors ligne", "indicateur de bob")


def test_A86_indicateur_en_ligne(w):
    w.off("bob")
    w.on("bob")
    check(w.bob.connection_status(), "en ligne", "indicateur de bob")


def test_A87_ecriture_hors_ligne(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    check(w.bob.content("A1"), "9", "A1 chez bob hors ligne")


def test_A88_attente_augmente(w):
    w.off("bob")
    before = w.bob.pending_count()
    w.bob.set_cell("A1", "9")
    check(w.bob.pending_count(), before + 1, "en attente après une modification")
    w.bob.set_cell("A2", "8")
    check(w.bob.pending_count(), before + 2, "en attente après deux modifications")


def test_A89_attente_zero_en_ligne(w):
    w.bob.set_cell("A1", "9")
    w.sync()
    check(w.bob.pending_count(), 0, "en attente après confirmation")


def test_A90_attente_zero_apres_fusion(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.bob.set_cell("A2", "8")
    w.on("bob")
    check(w.bob.pending_count(), 0, "en attente après fusion")


def test_A91_reouverture_hors_ligne_contenu(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    bob2 = w.bob.reopen()
    check(bob2.content("A1"), "9", "A1 après réouverture hors ligne")


def test_A92_reouverture_hors_ligne_attente(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.bob.set_cell("A2", "8")
    bob2 = w.bob.reopen()
    check(bob2.pending_count(), 2, "en attente après réouverture")
    w.on("bob")
    check(w.alice.content("A2"), "8", "modification en attente livrée après réouverture")


def test_A93_ajout_feuille_hors_ligne_local(w):
    w.off("bob")
    w.bob.add_sheet("Brouillon")
    assert "Brouillon" in w.bob.sheets(), f"chez bob : {w.bob.sheets()!r}"


def test_A94_ajout_feuille_hors_ligne_invisible(w):
    w.off("bob")
    w.bob.add_sheet("Brouillon")
    w.sync()
    assert "Brouillon" not in w.alice.sheets(), f"chez alice : {w.alice.sheets()!r}"
    w.on("bob")
    assert "Brouillon" in w.alice.sheets(), f"chez alice après retour : {w.alice.sheets()!r}"


def test_A95_recalcul_hors_ligne(w):
    w.alice.set_cell("B1", "=A1*2")
    w.sync()
    w.off("bob")
    w.bob.set_cell("A1", "6")
    check(w.bob.value("B1"), 12, "B1 chez bob hors ligne")


def test_A96_historique_hors_ligne_fige(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.off("bob")
    ids = [v.id for v in w.bob.history()]
    w.alice.set_cell("A1", "2")
    w.sync()
    check([v.id for v in w.bob.history()], ids, "historique chez bob hors ligne")


def test_A97_modifs_hors_ligne_absentes_de_l_historique(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    bob_ids = [v.id for v in w.bob.history()]
    alice_ids = [v.id for v in w.alice.history()]
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.sync()
    check([v.id for v in w.bob.history()], bob_ids, "historique de bob avant retour")
    check([v.id for v in w.alice.history()], alice_ids, "historique d'alice avant retour de bob")
    w.on("bob")
    assert any(v.author == "bob" for v in w.alice.history()), "entrée de bob attendue après retour"


def test_A98_annulation_hors_ligne(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.bob.undo()
    w.on("bob")
    for n, c in w.everyone():
        check(c.content("A1"), "1", f"A1 chez {n}")


def test_A99_annulation_hors_ligne_attente(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.bob.set_cell("A2", "8")
    n = w.bob.pending_count()
    w.bob.undo()
    check(w.bob.pending_count(), n - 1, "en attente après annulation")


# ---------------------------------------------------------------- annulation / rétablissement

def test_A100_annuler(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("A1", "10")
    w.alice.undo()
    check(w.alice.content("A1"), "2", "A1 chez alice")
    w.sync()
    check(w.bob.content("A1"), "2", "A1 chez bob")


def test_A101_annuler_recalcule(w):
    w.alice.set_cell("B1", "=A1*2")
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("A1", "10")
    w.alice.undo()
    check(w.alice.value("B1"), 4, "B1 après annulation")


def test_A102_annuler_n_affecte_pas_autrui(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.bob.set_cell("B1", "2")
    w.sync()
    w.alice.undo()
    w.sync()
    check(w.alice.content("A1"), None, "A1 annulé")
    for n, c in w.everyone():
        check(c.content("B1"), "2", f"B1 chez {n}")


def test_A103_annuler_sans_modification(w):
    w.alice.set_cell("A1", "3")
    w.sync()
    w.bob.undo()
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "3", f"A1 chez {n}")


def test_A104_annuler_indisponible_au_depart(w):
    check(w.bob.can_undo(), False, "annuler disponible chez bob sans modification")


def test_A105_modif_d_autrui_non_annulable(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    check(w.bob.can_undo(), False, "annuler chez bob")


def test_A106_annuler_cellule_modifiee_par_autrui(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.bob.set_cell("A1", "2")
    w.sync()
    w.alice.undo()
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "2", f"A1 chez {n}")


def test_A107_alerte_annulation_impossible(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.bob.set_cell("A1", "2")
    w.sync()
    w.alice.undo()
    w.sync()
    assert "annulation_impossible" in kinds(w.alice), f"alertes : {kinds(w.alice)!r}"


def test_A108_annuler_apres_retrogradation(w):
    w.bob.set_cell("A1", "1")
    w.sync()
    w.alice.set_right("bob", "Feuille1", R)
    w.sync()
    w.bob.undo()
    w.sync()
    check(w.bob.content("A1"), "1", "A1 chez bob")
    check(w.alice.content("A1"), "1", "A1 chez alice")


def test_A109_annuler_sur_autre_feuille(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "old", sheet="Feuille2")
    w.alice.set_cell("A1", "new", sheet="Feuille2")
    w.alice.activate("Feuille1")
    w.alice.undo()
    check(w.alice.content("A1", sheet="Feuille2"), "old", "Feuille2!A1")


def test_A110_annuler_suppression_feuille(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "x", sheet="Feuille2")
    w.alice.delete_sheet("Feuille2")
    w.alice.undo()
    w.sync()
    assert "Feuille2" in w.alice.sheets(), f"chez alice : {w.alice.sheets()!r}"
    assert "Feuille2" in w.bob.sheets(), f"chez bob : {w.bob.sheets()!r}"


def test_A111_annuler_suppression_restaure_cellules(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "x", sheet="Feuille2")
    w.alice.set_cell("B2", "=A1", sheet="Feuille2")
    w.alice.delete_sheet("Feuille2")
    w.alice.undo()
    w.sync()
    check(w.bob.content("A1", sheet="Feuille2"), "x", "Feuille2!A1 chez bob")
    check(w.bob.content("B2", sheet="Feuille2"), "=A1", "Feuille2!B2 chez bob")


def test_A112_annuler_renommage(w):
    w.alice.rename_sheet("Feuille1", "Ventes")
    w.alice.undo()
    w.sync()
    check(w.alice.sheets(), ["Feuille1"], "liste chez alice")
    check(w.bob.sheets(), ["Feuille1"], "liste chez bob")


def test_A113_annuler_import(w):
    w.alice.set_cell("A1", "avant")
    w.alice.import_csv(b"x,y\n")
    w.alice.undo()
    check(w.alice.content("A1"), "avant", "A1 après annulation de l'import")
    check(w.alice.content("B1"), None, "B1 après annulation de l'import")


def test_A114_annulee_devient_retablissable(w):
    w.alice.set_cell("A1", "1")
    w.alice.undo()
    check(w.alice.can_redo(), True, "rétablir disponible")


def test_A115_retablir(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("A1", "10")
    w.alice.undo()
    w.alice.redo()
    check(w.alice.content("A1"), "10", "A1 après rétablissement")
    w.sync()
    check(w.bob.content("A1"), "10", "A1 chez bob")


def test_A116_nouvelle_modif_vide_retablir(w):
    w.alice.set_cell("A1", "1")
    w.alice.undo()
    w.alice.set_cell("B1", "2")
    check(w.alice.can_redo(), False, "rétablir après nouvelle modification")


def test_A117_modif_d_autrui_garde_retablir(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.alice.undo()
    w.sync()
    w.bob.set_cell("B1", "2")
    w.sync()
    check(w.alice.can_redo(), True, "rétablir après modification de bob")


def test_A118_reouverture_vide_annuler(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    alice2 = w.alice.reopen()
    check(alice2.can_undo(), False, "annuler après réouverture")


# ---------------------------------------------------------------- historique des versions

def test_A119_nouvelle_entree(w):
    before = len(w.bob.history())
    w.alice.set_cell("A1", "1")
    w.sync()
    check(len(w.bob.history()), before + 1, "nombre d'entrées chez bob")


def test_A120_auteur(w):
    w.bob.set_cell("A1", "1")
    w.sync()
    check(w.alice.history()[0].author, "bob", "auteur de la dernière entrée")


def test_A121_ordre_plus_recente_d_abord(w):
    w.alice.set_cell("A1", "1")
    w.sync()
    w.clock.advance(timedelta(minutes=5))
    w.bob.set_cell("A2", "2")
    w.sync()
    h = w.carol.history()
    check([v.author for v in h[:2]], ["bob", "alice"], "ordre des auteurs")
    assert h[0].timestamp > h[1].timestamp, f"horodatages non décroissants : {[v.timestamp for v in h[:2]]!r}"


def test_A121_trou_ordre_horodatage_hors_ligne(w):
    w.off("bob")
    w.bob.set_cell("A2", "b")               # 10:00 UTC, local
    w.clock.advance(timedelta(hours=1))
    w.alice.set_cell("A1", "a")             # 11:00 UTC, enregistré tout de suite
    w.sync()
    w.clock.advance(timedelta(hours=1))
    w.on("bob")                             # enregistré à 12:00, horodaté 10:00
    h = w.carol.history()
    check([(v.author, v.timestamp) for v in h[:2]],
          [("alice", "2026-01-15 11:00"), ("bob", "2026-01-15 10:00")],
          "historique trié par horodatage affiché")


def test_A122_horodatage_heure_locale():
    w = World(T_ETE)
    w.bob.set_cell("A1", "1")
    w.sync()
    check(w.alice.history()[0].timestamp, "2026-07-01 12:00", "horodatage chez alice (Paris été)")


def test_A123_horodatages_differents_selon_fuseau():
    w = World(T_ETE)
    w.alice.set_cell("A1", "1")
    w.sync()
    a = w.alice.history()[0]
    b = w.bob.history()[0]
    check(a.id, b.id, "même version")
    check((a.timestamp, b.timestamp), ("2026-07-01 12:00", "2026-07-01 10:00"), "horodatages alice / bob")


def test_A124_horodatage_modif_hors_ligne(w):
    w.off("bob")
    w.bob.set_cell("A1", "9")
    w.clock.advance(timedelta(hours=2))
    w.on("bob")
    entries = [v for v in w.bob.history() if v.author == "bob"]
    assert entries, "entrée de bob attendue"
    check(entries[0].timestamp, "2026-01-15 10:00", "horodatage chez bob (UTC)")
    entries_a = [v for v in w.alice.history() if v.author == "bob"]
    check(entries_a[0].timestamp, "2026-01-15 11:00", "horodatage chez alice (Paris)")


def _versions(w):
    w.alice.set_cell("B1", "=A1*10")
    w.alice.set_cell("A1", "1")
    w.sync()
    v1 = w.alice.history()[0].id
    w.clock.advance(timedelta(minutes=1))
    w.alice.set_cell("A1", "2")
    w.sync()
    return v1


def test_A125_ouvrir_ancienne_version(w):
    v1 = _versions(w)
    w.alice.open_version(v1)
    check(w.alice.content("A1"), "1", "A1 dans la version ouverte")
    w.alice.close_version()
    check(w.alice.content("A1"), "2", "A1 après fermeture de la version")


def test_A126_valeurs_de_l_ancienne_version(w):
    v1 = _versions(w)
    w.alice.open_version(v1)
    check(w.alice.value("B1"), 10, "B1 dans la version ouverte")


def test_A127_consultation_lecture_seule(w):
    v1 = _versions(w)
    w.alice.open_version(v1)
    w.alice.set_cell("A1", "99")
    check(w.alice.content("A1"), "1", "A1 dans la version consultée")
    w.alice.close_version()
    w.sync()
    check(w.alice.content("A1"), "2", "A1 courant chez alice")
    check(w.bob.content("A1"), "2", "A1 courant chez bob")


def test_A128_autres_voient_courant(w):
    v1 = _versions(w)
    w.alice.open_version(v1)
    w.sync()
    check(w.bob.content("A1"), "2", "A1 chez bob")
    check(w.bob.value("B1"), 20, "B1 chez bob")


def test_A129_restaurer(w):
    v1 = _versions(w)
    w.bob.restore_version(v1)
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "1", f"A1 chez {n}")


def test_A130_lecteur_ne_restaure_pas(w):
    v1 = _versions(w)
    w.carol.restore_version(v1)
    w.sync()
    for n, c in w.everyone():
        check(c.content("A1"), "2", f"A1 chez {n}")


def test_A131_entree_de_restauration(w):
    v1 = _versions(w)
    before = len(w.alice.history())
    w.alice.restore_version(v1)
    w.sync()
    h = w.carol.history()
    check(len(h), before + 1, "nombre d'entrées après restauration")
    check(h[0].kind, "restauration", "nature de la dernière entrée")


def test_A132_entrees_posterieures_conservees(w):
    v1 = _versions(w)
    ids = [v.id for v in w.alice.history()]
    w.alice.restore_version(v1)
    w.sync()
    after = [v.id for v in w.alice.history()]
    missing = [i for i in ids if i not in after]
    check(missing, [], "entrées disparues après restauration")


def test_A133_restauration_recalcule_autres_feuilles(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("B1", "=Feuille2!A1", sheet="Feuille1")
    w.alice.set_cell("A1", "1", sheet="Feuille2")
    w.sync()
    v1 = w.alice.history(sheet="Feuille2")[0].id
    w.alice.set_cell("A1", "2", sheet="Feuille2")
    w.sync()
    w.alice.restore_version(v1)
    w.sync()
    check(w.alice.value("B1", sheet="Feuille1"), 1, "Feuille1!B1 chez alice")
    check(w.carol.value("B1", sheet="Feuille1"), 1, "Feuille1!B1 chez carol")


def test_A134_restauration_annulable(w):
    v1 = _versions(w)
    w.alice.restore_version(v1)
    w.sync()
    check(w.alice.can_undo(), True, "annuler après restauration")
    w.alice.undo()
    w.sync()
    check(w.bob.content("A1"), "2", "A1 après annulation de la restauration")


def test_A135_restauration_reprend_le_nom(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "1", sheet="Feuille2")
    w.sync()
    v1 = w.alice.history(sheet="Feuille2")[0].id
    w.alice.rename_sheet("Feuille2", "Ventes")
    w.sync()
    w.alice.restore_version(v1)
    w.sync()
    names = w.bob.sheets()
    assert "Feuille2" in names and "Ventes" not in names, f"liste après restauration : {names!r}"


# ---------------------------------------------------------------- export CSV

def test_A136_une_ligne_par_ligne_non_vide(w):
    w.alice.set_cell("A1", "a")
    w.alice.set_cell("B1", "b")
    w.alice.set_cell("A3", "c")
    r = rows(w.alice.export_csv())
    check(len(r), 2, f"nombre de lignes ({r!r})")
    check(r[0][:2], ["a", "b"], "première ligne")
    check(r[1][0], "c", "seconde ligne")


def test_A137_valeur_calculee(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("A2", "3")
    w.alice.set_cell("A3", "=A1+A2")
    data = w.alice.export_csv()
    assert b"=A1+A2" not in data, f"formule exportée : {data!r}"
    check(float(rows(data)[2][0]), 5.0, "valeur exportée de A3")


def test_A137_trou_format_nombre(w):
    w.alice.set_cell("A1", "2")
    w.alice.set_cell("A2", "3")
    w.alice.set_cell("A3", "=A1+A2")
    check(rows(w.alice.export_csv())[2][0], "5", "nombre entier exporté sans décimale")


def test_A138_erreur_circulaire(w):
    w.alice.set_cell("A1", "=A1+1")
    check(rows(w.alice.export_csv())[0][0], "#CIRC!", "code exporté")


def test_A139_virgule_entre_guillemets(w):
    w.alice.set_cell("A1", "a,b")
    data = w.alice.export_csv()
    assert b'"a,b"' in data, f"champ attendu entre guillemets : {data!r}"
    check(rows(data)[0][0], "a,b", "champ relu")


def test_A140_guillemet_double(w):
    w.alice.set_cell("A1", 'dit "oui"')
    data = w.alice.export_csv()
    assert b'"dit ""oui"""' in data, f"guillemets doublés attendus : {data!r}"


def test_A141_feuille_active_seulement(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("A1", "secret", sheet="Feuille2")
    w.alice.set_cell("A1", "public", sheet="Feuille1")
    w.alice.activate("Feuille1")
    data = w.alice.export_csv()
    assert b"secret" not in data and b"public" in data, f"export : {data!r}"


def test_A142_export_par_lecteur(w):
    w.alice.set_cell("A1", "lu")
    w.sync()
    check(rows(w.carol.export_csv())[0][0], "lu", "export de carol")


def test_A143_export_hors_ligne(w):
    w.off("bob")
    w.bob.set_cell("A1", "local")
    check(rows(w.bob.export_csv())[0][0], "local", "export de bob hors ligne")


def test_A144_export_cellule_en_conflit(w):
    _conflict(w)
    check(rows(w.alice.export_csv())[0][0], "2", "valeur retenue exportée")


def test_A145_date_heure_avec_decalage(w):
    w.alice.set_cell("A1", "2026-01-15 12:00")
    w.alice.set_cell("A2", "2026-07-01 12:00")
    r = rows(w.alice.export_csv())
    d1 = datetime.fromisoformat(r[0][0])
    d2 = datetime.fromisoformat(r[1][0])
    check(d1.utcoffset(), timedelta(hours=1), "décalage hiver")
    check(d2.utcoffset(), timedelta(hours=2), "décalage été")
    check(d1, datetime(2026, 1, 15, 11, 0, tzinfo=UTC), "instant hiver")
    check(d2, datetime(2026, 7, 1, 10, 0, tzinfo=UTC), "instant été")


def test_A145_trou_format_iso(w):
    w.alice.set_cell("A1", "2026-01-15 12:00")
    check(rows(w.alice.export_csv())[0][0], "2026-01-15T12:00:00+01:00", "format ISO 8601")


def test_A146_accents_conserves(w):
    w.alice.set_cell("A1", "Été à Noël")
    data = w.alice.export_csv()
    check(rows(data)[0][0], "Été à Noël", "champ accentué")


# ---------------------------------------------------------------- import CSV

def test_A147_import(w):
    w.bob.import_csv(b"1,2\nx,y\n")
    got = [w.bob.content(r) for r in ["A1", "B1", "A2", "B2"]]
    check(got, ["1", "2", "x", "y"], "contenus importés")
    w.sync()
    check([w.alice.content(r) for r in ["A1", "B1", "A2", "B2"]], ["1", "2", "x", "y"], "chez alice")


def test_A148_champ_egal_sans_formule(w):
    w.alice.import_csv(b"5,=A1+1\n")
    check(w.alice.content("B1"), "=A1+1", "contenu de B1")
    check(w.alice.error("B1"), None, "B1 ne doit pas être évalué")


def test_A148_trou_valeur_texte(w):
    w.alice.import_csv(b"5,=A1+1\n")
    check(w.alice.value("B1"), "=A1+1", "valeur affichée = texte littéral, pas 6")
    w.alice.set_cell("A1", "100")
    check(w.alice.value("B1"), "=A1+1", "texte importé insensible à A1")


def test_A149_champ_guillemets_virgule(w):
    w.alice.import_csv(b'"12,5",x\n')
    check(w.alice.content("A1"), "12,5", "A1")
    check(w.alice.content("B1"), "x", "B1")
    check(w.alice.content("C1"), None, "C1")


def test_A150_nombre_importe(w):
    w.alice.set_cell("B5", "=A1*2")
    w.alice.import_csv(b"25\n")
    check(w.alice.value("B5"), 50, "B5")


def test_A151_champ_vide(w):
    w.alice.set_cell("B1", "ancien")
    w.alice.import_csv(b"1,,3\n")
    check(w.alice.content("B1"), None, "B1 vide")
    check(w.alice.content("C1"), "3", "C1")


def test_A152_accents_utf8(w):
    w.alice.import_csv("Café,Noël\n".encode("utf-8"))
    check((w.alice.value("A1"), w.alice.value("B1")), ("Café", "Noël"), "valeurs accentuées")


def test_A153_date_avec_decalage(w):
    w.alice.import_csv(b"2026-01-15T12:00:00+00:00\n2026-07-01T10:00:00+00:00\n")
    check(w.alice.value("A1"), "2026-01-15 13:00", "hiver converti à Paris")
    check(w.alice.value("A2"), "2026-07-01 12:00", "été converti à Paris")


def test_A154_date_sans_decalage(w):
    w.alice.import_csv(b"2026-07-01 12:00\n2026-01-15 12:00\n")
    w.sync()
    check(w.bob.value("A1"), "2026-07-01 10:00", "naïf été interprété à Paris, vu en UTC")
    check(w.bob.value("A2"), "2026-01-15 11:00", "naïf hiver interprété à Paris, vu en UTC")


def test_A155_guillemet_non_ferme(w):
    w.alice.set_cell("A1", "orig")
    w.alice.import_csv(b'a,b\nc,"d\ne,f\n')
    check(w.alice.content("A1"), "orig", "A1")
    check(w.alice.content("A2"), None, "A2")
    check(w.alice.content("B1"), None, "B1")


def test_A156_alerte_ligne_invalide(w):
    w.alice.import_csv(b'a,b\nc,"d\ne,f\n')
    found = alerts_of(w.alice, "csv_invalide")
    assert found, f"alerte csv_invalide attendue, alertes : {kinds(w.alice)!r}"
    check(found[-1].line, 2, "ligne invalide")


def test_A157_import_recalcule_autres_feuilles(w):
    w.add_sheet("Feuille2")
    w.alice.set_cell("B1", "=Feuille1!A1", sheet="Feuille2")
    w.alice.activate("Feuille1")
    w.alice.import_csv(b"7\n")
    check(w.alice.value("B1", sheet="Feuille2"), 7, "Feuille2!B1")


def test_A158_une_annulation_pour_tout_l_import(w):
    w.alice.set_cell("A5", "garde")
    w.alice.import_csv(b"1,2\n3,4\n")
    w.alice.undo()
    got = [w.alice.content(r) for r in ["A1", "B1", "A2", "B2"]]
    check(got, [None, None, None, None], "cellules après une annulation")
    check(w.alice.content("A5"), "garde", "modification antérieure intacte")


def test_A159_import_hors_ligne(w):
    w.off("bob")
    w.bob.import_csv(b"h,l\n")
    check((w.bob.content("A1"), w.bob.content("B1")), ("h", "l"), "contenus chez bob hors ligne")
