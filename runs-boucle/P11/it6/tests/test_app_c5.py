"""Tests rouges — couche code — ajouts C35..C37 (sonde P11)."""
from datetime import datetime, timezone

import app


def _setup():
    clock = app.Clock(datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc))
    net = app.Network()
    server = app.Server(net, clock, owner="alice")
    alice = app.Client(net, clock, "alice", tz="Europe/Paris")
    bob = app.Client(net, clock, "bob", tz="Europe/Paris")
    carol = app.Client(net, clock, "carol", tz="Europe/Paris")
    net.deliver_all()
    alice.set_right("bob", "Feuille1", "écriture")
    alice.set_right("carol", "Feuille1", "lecture")
    net.deliver_all()
    assert bob.right("bob", "Feuille1") == "écriture", (
        f"préparation : bob devrait avoir écriture sur Feuille1, obtenu {bob.right('bob', 'Feuille1')!r}"
    )
    return clock, net, server, alice, bob, carol


def _alert_tuples(client):
    return [(a.kind, a.sheet, a.cell, a.line) for a in client.alerts()]


# ---------------------------------------------------------------- C35

def test_C35_delete_last_sheet_just_renamed_is_refused_without_trace():
    clock, net, server, alice, bob, carol = _setup()
    # alice modifie une cellule sous l'ancien nom, non livré
    alice.set_cell("A1", "5", sheet="Feuille1")
    bob.rename_sheet("Feuille1", "Dépenses")
    sheets_before = bob.sheets()
    pending_before = bob.pending_count()
    alerts_before = _alert_tuples(bob)
    assert sheets_before == ["Dépenses"], f"après renommage attendu ['Dépenses'], obtenu {sheets_before!r}"

    bob.delete_sheet("Dépenses")

    assert bob.sheets() == ["Dépenses"], (
        f"suppression de la dernière feuille : liste attendue ['Dépenses'], obtenu {bob.sheets()!r}"
    )
    assert bob.pending_count() == pending_before, (
        f"suppression refusée : en attente attendu {pending_before}, obtenu {bob.pending_count()}"
    )
    assert _alert_tuples(bob) == alerts_before, (
        f"suppression refusée : aucune nouvelle alerte attendue, avant {alerts_before!r}, après {_alert_tuples(bob)!r}"
    )
    for ref in ("A1", "A2", "A3", "B1", "B2", "C1"):
        assert bob.content(ref, sheet="Dépenses") is None, (
            f"{ref} : contenu attendu None, obtenu {bob.content(ref, sheet='Dépenses')!r}"
        )
        assert bob.value(ref, sheet="Dépenses") is None, (
            f"{ref} : valeur attendue None, obtenu {bob.value(ref, sheet='Dépenses')!r}"
        )
        assert bob.error(ref, sheet="Dépenses") is None, (
            f"{ref} : erreur attendue None, obtenu {bob.error(ref, sheet='Dépenses')!r}"
        )


def test_C35_refused_delete_of_last_sheet_leaves_sheet_for_everyone_after_delivery():
    clock, net, server, alice, bob, carol = _setup()
    alice.set_cell("A1", "5", sheet="Feuille1")
    bob.rename_sheet("Feuille1", "Dépenses")
    bob.delete_sheet("Dépenses")
    net.deliver_all()
    for c in (alice, bob, carol):
        assert c.sheets() == ["Dépenses"], (
            f"{c!r} après livraison : liste attendue ['Dépenses'], obtenu {c.sheets()!r}"
        )


# ---------------------------------------------------------------- C36

def test_C36_imported_datetime_times_number_is_type_error():
    clock, net, server, alice, bob, carol = _setup()
    alice.import_csv("2026-01-15T12:00:00+00:00\n".encode("utf-8"))
    assert alice.value("A1", sheet="Feuille1") == "2026-01-15 13:00", (
        f"préparation : A1 attendu '2026-01-15 13:00', obtenu {alice.value('A1', sheet='Feuille1')!r}"
    )
    alice.set_cell("C1", "=A1*2", sheet="Feuille1")
    assert alice.error("C1", sheet="Feuille1") == "#TYPE!", (
        f"=A1*2 sur date-heure : erreur attendue '#TYPE!', obtenu {alice.error('C1', sheet='Feuille1')!r}"
    )
    v = alice.value("C1", sheet="Feuille1")
    assert v == "#TYPE!", f"=A1*2 sur date-heure : valeur attendue '#TYPE!', obtenu {v!r}"
    assert not isinstance(v, (int, float)), f"aucune valeur numérique attendue, obtenu {v!r}"


def test_C36_typed_datetime_times_number_is_type_error():
    clock, net, server, alice, bob, carol = _setup()
    alice.set_cell("A1", "2026-01-15 12:00", sheet="Feuille1")
    alice.set_cell("C1", "=A1*2", sheet="Feuille1")
    assert alice.error("C1", sheet="Feuille1") == "#TYPE!", (
        f"=A1*2 sur date-heure saisie : erreur attendue '#TYPE!', obtenu {alice.error('C1', sheet='Feuille1')!r}"
    )
    assert alice.value("C1", sheet="Feuille1") == "#TYPE!", (
        f"=A1*2 sur date-heure saisie : valeur attendue '#TYPE!', obtenu {alice.value('C1', sheet='Feuille1')!r}"
    )


# ---------------------------------------------------------------- C37

def _presence_of(client, name):
    p = client.presence().get(name)
    return None if p is None else tuple(p)


def test_C37_presence_keeps_old_sheet_name_right_after_rename():
    clock, net, server, alice, bob, carol = _setup()
    bob.select("C1", sheet="Feuille1")
    net.deliver_all()
    assert _presence_of(alice, "bob") == ("Feuille1", "C1"), (
        f"préparation : présence attendue ('Feuille1','C1'), obtenu {_presence_of(alice, 'bob')!r}"
    )
    alice.rename_sheet("Feuille1", "Ventes")
    assert _presence_of(alice, "bob") == ("Feuille1", "C1"), (
        f"après renommage : présence attendue ('Feuille1','C1'), obtenu {_presence_of(alice, 'bob')!r}"
    )


def test_C37_presence_keeps_old_sheet_name_after_delivery_until_next_select():
    clock, net, server, alice, bob, carol = _setup()
    bob.select("C1", sheet="Feuille1")
    net.deliver_all()
    alice.rename_sheet("Feuille1", "Ventes")
    net.deliver_all()
    assert _presence_of(alice, "bob") == ("Feuille1", "C1"), (
        f"après livraison du renommage : présence attendue ('Feuille1','C1'), obtenu {_presence_of(alice, 'bob')!r}"
    )
    bob.select("B2", sheet="Ventes")
    net.deliver_all()
    assert _presence_of(alice, "bob") == ("Ventes", "B2"), (
        f"après nouvelle sélection : présence attendue ('Ventes','B2'), obtenu {_presence_of(alice, 'bob')!r}"
    )
