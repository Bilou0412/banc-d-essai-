"""Tests rouges — couche code — ajouts C29 à C31 (sonde P11)."""
from datetime import datetime, timezone

import app


def _setup():
    clock = app.Clock(datetime(2026, 3, 28, 9, 0, tzinfo=timezone.utc))
    net = app.Network()
    server = app.Server(net, clock, owner="alice")
    alice = app.Client(net, clock, "alice", tz="Europe/Paris")
    bob = app.Client(net, clock, "bob", tz="Europe/Paris")
    carol = app.Client(net, clock, "carol", tz="Europe/Paris")
    net.deliver_all()
    alice.set_right("bob", "Feuille1", "écriture")
    alice.set_right("carol", "Feuille1", "lecture")
    net.deliver_all()
    return clock, net, server, alice, bob, carol


# ---------------------------------------------------------------- C29

def test_C29_non_owner_adds_sheet_owner_gets_write_others_none():
    _, net, _, alice, bob, carol = _setup()
    bob.add_sheet("Feuille2")
    net.deliver_all()
    for viewer in (alice, bob, carol):
        got = {p: viewer.right(p, "Feuille2") for p in ("alice", "bob", "carol")}
        expected = {"alice": "écriture", "bob": "écriture", "carol": None}
        assert got == expected, (
            f"C29 : vu par {viewer!r}, droits sur Feuille2 ajoutée par bob attendus "
            f"{expected}, obtenus {got}"
        )


def test_C29_non_owner_adds_sheet_owner_right_visible_on_adder_before_delivery():
    _, net, _, alice, bob, carol = _setup()
    bob.add_sheet("Feuille2")
    got = bob.right("alice", "Feuille2")
    assert got == "écriture", (
        f"C29 : chez bob, juste après l'ajout, le droit de la propriétaire alice sur "
        f"Feuille2 doit être 'écriture', obtenu {got!r}"
    )
    got_carol = bob.right("carol", "Feuille2")
    assert got_carol is None, (
        f"C29 : chez bob, carol ne doit avoir aucun droit sur Feuille2, obtenu {got_carol!r}"
    )


# ---------------------------------------------------------------- C30

def test_C30_datetime_in_dst_gap_displayed_as_typed_paris():
    _, net, _, alice, _, _ = _setup()
    alice.set_cell("A1", "2026-03-29 02:30", sheet="Feuille1")
    got = alice.value("A1", sheet="Feuille1")
    assert got == "2026-03-29 02:30", (
        f"C30 : date-heure saisie dans l'heure sautée (Paris) : valeur attendue "
        f"'2026-03-29 02:30' (sans décalage), obtenue {got!r}"
    )
    err = alice.error("A1", sheet="Feuille1")
    assert err is None, f"C30 : aucune erreur attendue, obtenu {err!r}"
    assert alice.alerts() == [], (
        f"C30 : aucune alerte attendue, obtenu {alice.alerts()!r}"
    )
    content = alice.content("A1", sheet="Feuille1")
    assert content == "2026-03-29 02:30", (
        f"C30/C01 : contenu attendu '2026-03-29 02:30', obtenu {content!r}"
    )


def test_C30_datetime_in_dst_gap_still_as_typed_after_delivery():
    _, net, _, alice, _, _ = _setup()
    alice.set_cell("A1", "2026-03-29 02:30", sheet="Feuille1")
    net.deliver_all()
    got = alice.value("A1", sheet="Feuille1")
    assert got == "2026-03-29 02:30", (
        f"C30 : après confirmation par le serveur, valeur attendue chez la saisissante "
        f"'2026-03-29 02:30', obtenue {got!r}"
    )


# ---------------------------------------------------------------- C31

def test_C31_sum_over_text_and_empty_cells_is_zero_without_error():
    _, net, _, _, bob, _ = _setup()
    bob.set_cell("A3", "a,b", sheet="Feuille1")
    bob.set_cell("C1", "=SOMME(A1:A3)", sheet="Feuille1")
    err = bob.error("C1", sheet="Feuille1")
    assert err is None, (
        f"C31 : =SOMME sur A1, A2 vides et A3='a,b' : aucune erreur attendue, obtenu {err!r}"
    )
    got = bob.value("C1", sheet="Feuille1")
    assert got == 0, f"C31 : valeur attendue 0, obtenue {got!r}"


def test_C31_sum_ignores_text_and_adds_numbers():
    _, net, _, _, bob, _ = _setup()
    bob.set_cell("A1", "2", sheet="Feuille1")
    bob.set_cell("A2", "abc", sheet="Feuille1")
    bob.set_cell("A3", "5", sheet="Feuille1")
    bob.set_cell("C1", "=SOMME(A1:A3)", sheet="Feuille1")
    err = bob.error("C1", sheet="Feuille1")
    assert err is None, (
        f"C31 : =SOMME(A1:A3) avec A2='abc' : aucune erreur de type attendue, obtenu {err!r}"
    )
    got = bob.value("C1", sheet="Feuille1")
    assert got == 7, f"C31 : somme des seules cellules numériques attendue 7, obtenue {got!r}"


def test_C31_sum_recomputed_when_text_replaced_by_number():
    _, net, _, _, bob, _ = _setup()
    bob.set_cell("A1", "2", sheet="Feuille1")
    bob.set_cell("A2", "abc", sheet="Feuille1")
    bob.set_cell("C1", "=SOMME(A1:A3)", sheet="Feuille1")
    bob.set_cell("A2", "4", sheet="Feuille1")
    got = bob.value("C1", sheet="Feuille1")
    assert got == 6, (
        f"C31/A29 : après remplacement de 'abc' par 4 dans A2, somme attendue 6, obtenue {got!r}"
    )
