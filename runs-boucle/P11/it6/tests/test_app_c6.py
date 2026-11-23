"""Tests rouges — couche code — ajouts C38 à C41 (sonde P11)."""
from datetime import datetime, timedelta, timezone

import app


def _setup(start=None):
    clock = app.Clock(start or datetime(2026, 3, 29, 0, 30, 0, tzinfo=timezone.utc))
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


def test_C38_same_delivery_same_minute_history_ordered_by_local_modification_most_recent_first():
    clock, net, _server, alice, bob, _carol = _setup()
    assert bob.right("bob", "Feuille1") == "écriture", (
        f"pré-condition : bob doit avoir le droit écriture, obtenu {bob.right('bob', 'Feuille1')!r}")
    before = len(alice.history("Feuille1"))
    bob.set_cell("A2", "42", sheet="Feuille1")
    clock.advance(timedelta(seconds=10))
    alice.set_cell("A1", "-50", sheet="Feuille1")
    net.deliver_all()
    alice.set_timezone("Pacific/Kiritimati")
    hist = alice.history("Feuille1")
    new = hist[: len(hist) - before]
    got = [(v.author, v.timestamp, v.kind) for v in new]
    expected = [
        ("alice", "2026-03-29 14:30", "modification"),
        ("bob", "2026-03-29 14:30", "modification"),
    ]
    assert got == expected, (
        f"C38 : attendu les deux versions de la même livraison, la plus récente localement "
        f"(alice) en premier : {expected} ; obtenu {got}")
    assert alice.value("A1", sheet="Feuille1") == -50 and alice.value("A2", sheet="Feuille1") == 42, (
        f"C38 : contenus attendus A1=-50, A2=42 ; obtenu A1={alice.value('A1', sheet='Feuille1')!r}, "
        f"A2={alice.value('A2', sheet='Feuille1')!r}")


def test_C39_presence_selected_during_absence_appears_after_reconnect_without_new_selection():
    _clock, net, _server, _alice, bob, carol = _setup()
    net.disconnect("carol")
    net.deliver_all()
    bob.select("C1", sheet="Feuille1")
    net.deliver_all()
    assert "bob" not in carol.presence(), (
        f"pré-condition A64 : carol hors ligne ne voit aucune présence ; obtenu {carol.presence()!r}")
    net.reconnect("carol")
    net.deliver_all()
    pres = carol.presence()
    assert "bob" in pres, (
        f"C39 : attendu l'indicateur de bob sur Feuille1!C1 après le retour de carol, sans "
        f"nouvelle sélection ; obtenu présence={pres!r}")
    assert tuple(pres["bob"]) == ("Feuille1", "C1"), (
        f"C39 : attendu ('Feuille1', 'C1') ; obtenu {pres['bob']!r}")


def test_C40_redo_while_undo_pending_adds_one_pending_modification_without_removing_undo():
    _clock, net, _server, alice, _bob, _carol = _setup()
    alice.activate("Feuille1")
    alice.import_csv("Café,Noël\n,2026-03-15\n".encode("utf-8"))
    net.deliver_all()
    assert alice.pending_count() == 0, (
        f"pré-condition : import confirmé, attendu 0 en attente ; obtenu {alice.pending_count()}")
    alice.undo()
    assert alice.pending_count() == 1, (
        f"pré-condition C25 : l'annulation d'un import confirmé ajoute 1 ; obtenu {alice.pending_count()}")
    alice.redo()
    assert alice.pending_count() == 2, (
        f"C40 : le rétablissement alors que l'annulation est en attente doit ajouter une "
        f"modification sans retirer l'annulation : attendu 2 ; obtenu {alice.pending_count()}")
    got = (alice.content("A1"), alice.content("B1"), alice.content("A2"), alice.content("B2"))
    assert got == ("Café", "Noël", None, "2026-03-15"), (
        f"C40 : attendu le contenu de l'import rétabli ('Café','Noël',None,'2026-03-15') ; obtenu {got}")
    assert alice.can_undo() is True and alice.can_redo() is False, (
        f"C40 : attendu annuler disponible et rétablir indisponible ; obtenu "
        f"can_undo={alice.can_undo()}, can_redo={alice.can_redo()}")


def test_C41_selection_made_offline_not_shown_to_others_after_reconnect_until_new_selection():
    _clock, net, _server, alice, bob, carol = _setup()
    net.disconnect("alice")
    alice.select("B2", sheet="Feuille1")
    net.deliver_all()
    net.reconnect("alice")
    net.deliver_all()
    for other in (bob, carol):
        assert "alice" not in other.presence(), (
            f"C41 : la sélection faite hors ligne ne doit pas apparaître après le retour ; "
            f"obtenu chez {other!r} présence={other.presence()!r}")
    alice.set_cell("A1", "2.5", sheet="Feuille1")
    net.deliver_all()
    assert bob.value("A1", sheet="Feuille1") == 2.5, (
        f"pré-condition : la saisie d'alice doit être livrée ; obtenu {bob.value('A1', sheet='Feuille1')!r}")
    for other in (bob, carol):
        assert "alice" not in other.presence(), (
            f"C41 : une saisie n'est pas une nouvelle sélection, aucun indicateur d'alice attendu ; "
            f"obtenu présence={other.presence()!r}")
    alice.select("C1", sheet="Feuille1")
    net.deliver_all()
    assert tuple(bob.presence().get("alice", ())) == ("Feuille1", "C1"), (
        f"C41 : après une nouvelle sélection en ligne, attendu ('Feuille1','C1') ; "
        f"obtenu {bob.presence()!r}")
