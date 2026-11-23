"""Tests de non-régression — couche code — sonde P11, lot reg6.

Chaque test reproduit un cas où une implémentation passant les tests existants
s'est trompée ; il cite l'assertion de la spec qu'il protège.

Note pour l'arbitre : les cas 4 (C13) et 11 (C27) portent sur la même action
(carol, droit lecture, renomme Feuille1 en Feuille1) avec des attentes
contraires sur l'alerte. Le test C13 ci-dessous ne vérifie donc que ce qui
ne se contredit pas (liste des feuilles, attente) ; le test C27 vérifie l'alerte.
De même pour A62 (cas 12) et C37 : seuls le nom de la personne et la cellule
de l'indicateur de présence sont vérifiés, pas le nom de feuille.
"""
from datetime import datetime, timedelta, timezone

import app


START = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)


def make(tz_alice="Europe/Paris", tz_bob="Europe/Paris", tz_carol="Europe/Paris", start=START):
    clock = app.Clock(start)
    net = app.Network()
    server = app.Server(net, clock, owner="alice")
    alice = app.Client(net, clock, "alice", tz=tz_alice)
    bob = app.Client(net, clock, "bob", tz=tz_bob)
    carol = app.Client(net, clock, "carol", tz=tz_carol)
    net.deliver_all()
    alice.set_right("bob", "Feuille1", "écriture")
    alice.set_right("carol", "Feuille1", "lecture")
    net.deliver_all()
    clock.advance(timedelta(minutes=1))
    return clock, net, server, alice, bob, carol


def has_alert(client, kind, sheet=None, cell=None):
    for a in client.alerts():
        if a.kind != kind:
            continue
        if sheet is not None and a.sheet != sheet:
            continue
        if cell is not None and a.cell != cell:
            continue
        return True
    return False


def alerts_repr(client):
    return [(a.kind, a.sheet, a.cell, a.line) for a in client.alerts()]


# Cas 1 — A147
def test_A147_reg_import_datetime_with_offset_keeps_field_as_content():
    clock, net, server, alice, bob, carol = make()
    alice.import_csv("2026-01-15T12:00:00+00:00\n".encode("utf-8"))
    got = alice.content("A1")
    assert got == "2026-01-15T12:00:00+00:00", (
        f"A147 : le contenu de A1 doit être le champ importé tel quel "
        f"'2026-01-15T12:00:00+00:00', obtenu {got!r}")
    val = alice.value("A1")
    assert val == "2026-01-15 13:00", (
        f"A153 : valeur attendue '2026-01-15 13:00' (Paris), obtenu {val!r}")


# Cas 2 — A61
def test_A61_reg_datetime_from_other_timezone_content_unchanged_after_reconnect():
    clock, net, server, alice, bob, carol = make(tz_bob="UTC")
    net.disconnect("alice")
    bob.set_cell("A1", "2026-07-01 12:00")
    net.deliver_all()
    net.reconnect("alice")
    net.deliver_all()
    got = alice.content("A1")
    assert got == "2026-07-01 12:00", (
        f"A61/C18 : contenu attendu chez alice '2026-07-01 12:00' (texte saisi par bob), obtenu {got!r}")
    val = alice.value("A1")
    assert val == "2026-07-01 14:00", (
        f"A30 : valeur attendue chez alice (Paris, été) '2026-07-01 14:00', obtenu {val!r}")


# Cas 3 — C05
def test_C05_reg_empty_csv_import_with_unconfirmed_change_adds_one_pending():
    clock, net, server, alice, bob, carol = make()
    alice.add_sheet("FEUILLE2")
    before = alice.pending_count()
    alice.import_csv(b"")
    after = alice.pending_count()
    assert after == before + 1, (
        f"C05 : un import CSV (même vide) avant confirmation doit ajouter une modification "
        f"en attente : attendu {before + 1}, obtenu {after}")


# Cas 4 — C13 (partie non contradictoire)
def test_C13_reg_reader_rename_to_same_name_changes_nothing():
    clock, net, server, alice, bob, carol = make()
    carol.rename_sheet("Feuille1", "Feuille1")
    assert carol.pending_count() == 0, (
        f"C13 : nombre de modifications en attente attendu 0, obtenu {carol.pending_count()}")
    assert carol.sheets() == ["Feuille1"], (
        f"C13 : liste des feuilles attendue ['Feuille1'], obtenu {carol.sheets()}")


# Cas 11 — C27
def test_C27_reg_reader_rename_to_same_name_raises_insufficient_right_alert():
    clock, net, server, alice, bob, carol = make()
    carol.rename_sheet("Feuille1", "Feuille1")
    assert has_alert(carol, "droit_insuffisant", sheet="Feuille1"), (
        f"C27 : alerte 'droit_insuffisant' citant Feuille1 attendue, obtenu {alerts_repr(carol)}")
    assert carol.pending_count() == 0, (
        f"C27 : l'écriture est refusée, attente attendue 0, obtenu {carol.pending_count()}")


# Cas 5 — A147
def test_A147_reg_import_after_unconfirmed_rename_fills_active_sheet():
    clock, net, server, alice, bob, carol = make()
    alice.rename_sheet("Feuille1", "Ventes")
    before = alice.pending_count()
    alice.import_csv("Café,Noël\n".encode("utf-8"))
    a1 = alice.content("A1", sheet="Ventes")
    b1 = alice.content("B1", sheet="Ventes")
    assert (a1, b1) == ("Café", "Noël"), (
        f"A147 : A1/B1 de la feuille active Ventes attendus ('Café', 'Noël'), obtenu {(a1, b1)!r}")
    assert alice.content("A1") == "Café", (
        f"A147 : A1 de la feuille active attendu 'Café', obtenu {alice.content('A1')!r}")
    assert alice.pending_count() == before + 1, (
        f"C05 : attente attendue {before + 1}, obtenu {alice.pending_count()}")


# Cas 6 / 10 — C14, C27
def test_C14_reg_reader_resolve_on_cell_without_conflict_alerts():
    clock, net, server, alice, bob, carol = make()
    carol.resolve_conflict("A1", use_discarded=False)
    assert has_alert(carol, "droit_insuffisant", sheet="Feuille1", cell="A1"), (
        f"C14/C27 : alerte 'droit_insuffisant' (Feuille1, A1) attendue, obtenu {alerts_repr(carol)}")
    assert carol.content("A1") is None
    assert carol.pending_count() == 0


def test_C27_reg_reader_resolve_on_cell_without_conflict_use_discarded_alerts():
    clock, net, server, alice, bob, carol = make()
    carol.resolve_conflict("A1", use_discarded=True)
    assert has_alert(carol, "droit_insuffisant", sheet="Feuille1", cell="A1"), (
        f"C14/C27 : alerte 'droit_insuffisant' (Feuille1, A1) attendue, obtenu {alerts_repr(carol)}")


# Cas 7 — C20
def test_C20_reg_owner_raises_reader_to_writer():
    clock, net, server, alice, bob, carol = make()
    assert alice.right("carol", "Feuille1") == "lecture"
    alice.set_right("carol", "Feuille1", "écriture")
    got = alice.right("carol", "Feuille1")
    assert got == "écriture", f"C20 : droit de carol attendu 'écriture', obtenu {got!r}"
    assert alice.alerts() == [], f"C20 : aucune alerte attendue, obtenu {alerts_repr(alice)}"
    net.deliver_all()
    for c in (alice, bob, carol):
        got = c.right("carol", "Feuille1")
        assert got == "écriture", (
            f"C20 : après livraison, droit de carol vu par {c} attendu 'écriture', obtenu {got!r}")


# Cas 8 — A74
def test_A74_reg_new_entry_in_conflicted_cell_clears_conflict_before_confirmation():
    clock, net, server, alice, bob, carol = make()
    alice.set_cell("C1", "10")
    bob.set_cell("C1", "20")
    net.deliver_from("alice")
    net.deliver_all()
    assert bob.conflict("C1") is not None, "précondition : C1 doit être en conflit chez bob"
    clock.advance(timedelta(minutes=1))
    bob.set_cell("C1", "=Feuille1!A1")
    assert bob.conflict("C1") is None, (
        f"A74 : l'indicateur de conflit doit disparaître après une nouvelle saisie, "
        f"obtenu {bob.conflict('C1')!r}")
    assert bob.value("C1") == 0, f"valeur attendue 0, obtenu {bob.value('C1')!r}"


# Cas 9 / 23 — A79
def test_A79_reg_offline_edit_before_online_edit_online_wins():
    clock, net, server, alice, bob, carol = make()
    net.disconnect("bob")
    bob.set_cell("B1", 'dit "oui"')
    clock.advance(timedelta(minutes=1))
    alice.set_cell("B1", "abc")
    net.deliver_all()
    clock.advance(timedelta(minutes=1))
    net.reconnect("bob")
    net.deliver_all()
    for c in (alice, bob):
        got = c.content("B1")
        assert got == "abc", f"A79 : B1 doit garder la valeur de la personne restée en ligne 'abc', obtenu {got!r}"
        conf = c.conflict("B1")
        assert conf is not None, "A80 : un indicateur de conflit doit apparaître sur B1"
        assert conf.discarded == 'dit "oui"' and conf.discarded_by == "bob", (
            f"A69/A70 : valeur écartée attendue ('dit \"oui\"', bob), obtenu {(conf.discarded, conf.discarded_by)!r}")


def test_A79_reg_offline_edit_after_online_edit_online_wins():
    clock, net, server, alice, bob, carol = make()
    net.disconnect("alice")
    bob.set_cell("A2", "=SOMME(A1:A3)")
    net.deliver_all()
    clock.advance(timedelta(minutes=1))
    alice.set_cell("A2", "2.5")
    clock.advance(timedelta(minutes=1))
    net.reconnect("alice")
    net.deliver_all()
    for c in (alice, bob):
        got = c.content("A2")
        assert got == "=SOMME(A1:A3)", (
            f"A79 : A2 doit garder la valeur de la personne restée en ligne '=SOMME(A1:A3)', obtenu {got!r}")
        conf = c.conflict("A2")
        assert conf is not None, "A80 : un indicateur de conflit doit apparaître sur A2"
        assert conf.discarded == "2.5" and conf.discarded_by == "alice", (
            f"A69/A70 : valeur écartée attendue ('2.5', alice), obtenu {(conf.discarded, conf.discarded_by)!r}")


# Cas 12 — A62
def test_A62_reg_presence_survives_rename_by_renamer():
    clock, net, server, alice, bob, carol = make()
    alice.select("A2")
    net.deliver_all()
    bob.rename_sheet("Feuille1", "Feuille2")
    p = bob.presence()
    assert "alice" in p and p["alice"][1] == "A2", (
        f"A62 : indicateur de présence d'alice sur A2 attendu chez bob, obtenu {p!r}")
    net.deliver_all()
    p = bob.presence()
    assert "alice" in p and p["alice"][1] == "A2", (
        f"A62 : après livraison, indicateur d'alice sur A2 attendu chez bob, obtenu {p!r}")


# Cas 15 — A62
def test_A62_reg_presence_kept_when_rename_not_yet_delivered():
    clock, net, server, alice, bob, carol = make()
    alice.set_cell("A1", 'dit "oui"')
    net.deliver_all()
    bob.select("A1")
    net.deliver_all()
    alice.rename_sheet("Feuille1", "Ventes")
    p = alice.presence()
    assert "bob" in p and p["bob"][1] == "A1", (
        f"A62 : indicateur de présence de bob sur A1 attendu chez alice, obtenu {p!r}")


# Cas 13 — A67
def test_A67_reg_csv_import_vs_typing_first_received_wins():
    clock, net, server, alice, bob, carol = make()
    bob.import_csv(b"7\n")
    alice.set_cell("A1", "Été à Noël")
    net.deliver_from("alice")
    net.deliver_all()
    for c, name in ((alice, "alice"), (bob, "bob")):
        got = c.content("A1")
        assert got == "Été à Noël", (
            f"A67 : chez {name}, A1 doit garder la valeur reçue en premier 'Été à Noël', obtenu {got!r}")
        conf = c.conflict("A1")
        assert conf is not None, f"A68 : conflit attendu sur A1 chez {name}"
        assert conf.discarded == "7" and conf.discarded_by == "bob", (
            f"A69/A70 : écartée attendue ('7', bob), obtenu {(conf.discarded, conf.discarded_by)!r}")


# Cas 14 — C21
def test_C21_reg_restore_current_version_leaves_no_trace():
    clock, net, server, alice, bob, carol = make()
    bob.set_cell("A3", "2026-10-25 02:30")
    net.deliver_all()
    h = bob.history()
    assert len(h) == 1
    v1 = h[0].id
    clock.advance(timedelta(minutes=1))
    bob.restore_version(v1)
    net.deliver_all()
    for c, name in ((bob, "bob"), (alice, "alice")):
        h = c.history()
        assert [(v.author, v.kind) for v in h] == [("bob", "modification")], (
            f"C21 : restaurer la version courante ne doit laisser aucune entrée ; historique chez {name} : "
            f"{[(v.author, v.timestamp, v.kind) for v in h]}")
    assert bob.pending_count() == 0
    assert bob.content("A3") == "2026-10-25 02:30"


# Cas 16 — C23
def test_C23_reg_refused_rename_leaves_empty_cells_without_error():
    clock, net, server, alice, bob, carol = make()
    carol.rename_sheet("Feuille1", "Brouillon")
    assert carol.sheets() == ["Feuille1"], f"C23 : feuilles attendues ['Feuille1'], obtenu {carol.sheets()}"
    assert has_alert(carol, "droit_insuffisant", sheet="Feuille1"), (
        f"C27 : alerte droit_insuffisant attendue, obtenu {alerts_repr(carol)}")
    for ref in ("A1", "A2", "A3", "B1", "B2", "C1"):
        got = (carol.content(ref, sheet="Feuille1"), carol.value(ref, sheet="Feuille1"),
               carol.error(ref, sheet="Feuille1"))
        assert got == (None, None, None), (
            f"C23 : {ref} doit rester vide sans valeur ni erreur, obtenu (contenu, valeur, erreur)={got!r}")


# Cas 17 — C28
def test_C28_reg_delivered_rename_of_empty_sheet_no_ref_error():
    clock, net, server, alice, bob, carol = make()
    alice.rename_sheet("Feuille1", "Ventes")
    net.deliver_all()
    for c, name in ((alice, "alice"), (bob, "bob"), (carol, "carol")):
        assert c.sheets() == ["Ventes"], f"chez {name}, feuilles attendues ['Ventes'], obtenu {c.sheets()}"
        for ref in ("A1", "A2", "A3", "B1", "B2", "C1"):
            got = (c.content(ref, sheet="Ventes"), c.value(ref, sheet="Ventes"), c.error(ref, sheet="Ventes"))
            assert got == (None, None, None), (
                f"C28 : chez {name}, {ref} doit rester vide sans erreur, obtenu {got!r}")


# Cas 18 — C27
def test_C27_reg_reader_formula_never_reaches_history():
    clock, net, server, alice, bob, carol = make()
    carol.set_cell("A1", "=1+1")
    h = alice.history()
    assert h == [], f"C27 : écriture refusée, historique d'alice attendu vide, obtenu {[(v.author, v.kind) for v in h]}"
    net.deliver_all()
    h = alice.history()
    assert h == [], f"C27 : après livraison, historique attendu vide, obtenu {[(v.author, v.kind) for v in h]}"
    assert alice.content("A1") is None


# Cas 19 — C07
def test_C07_reg_undo_before_confirmation_then_other_writes_no_conflict():
    clock, net, server, alice, bob, carol = make()
    alice.set_cell("B2", "x")
    alice.undo()
    assert alice.pending_count() == 0, f"C07 : attente attendue 0, obtenu {alice.pending_count()}"
    clock.advance(timedelta(minutes=1))
    bob.set_cell("B2", "Budget")
    net.deliver_all()
    for c, name in ((alice, "alice"), (bob, "bob")):
        assert c.content("B2") == "Budget", f"chez {name}, B2 attendu 'Budget', obtenu {c.content('B2')!r}"
        assert c.conflict("B2") is None, f"chez {name}, aucun conflit attendu sur B2, obtenu {c.conflict('B2')!r}"


# Cas 20 — A61
def test_A61_reg_offline_edit_undone_then_other_text_wins_without_conflict():
    clock, net, server, alice, bob, carol = make()
    net.disconnect("bob")
    bob.set_cell("A1", "5")
    bob.undo()
    clock.advance(timedelta(minutes=1))
    alice.set_cell("A1", "Été à Noël")
    net.deliver_all()
    net.reconnect("bob")
    net.deliver_all()
    for c, name in ((bob, "bob"), (alice, "alice")):
        assert c.content("A1") == "Été à Noël", (
            f"A61 : chez {name}, A1 attendu 'Été à Noël', obtenu {c.content('A1')!r}")
        assert c.conflict("A1") is None, f"chez {name}, aucun conflit attendu, obtenu {c.conflict('A1')!r}"


# Cas 21 / 24 — C34
def test_C34_reg_reopen_shows_no_stale_presence():
    clock, net, server, alice, bob, carol = make()
    bob.select("A1")
    alice.select("A3")
    net.deliver_all()
    carol2 = carol.reopen()
    assert carol2.presence() == {}, f"C34 : aucune présence attendue après réouverture, obtenu {carol2.presence()!r}"
    net.deliver_all()
    assert carol2.presence() == {}, (
        f"C34 : aucune présence attendue tant que personne n'a resélectionné, obtenu {carol2.presence()!r}")


# Cas 22 — A50
def test_A50_reg_downgrade_after_two_noop_actions():
    clock, net, server, alice, bob, carol = make()
    alice.clear("C1")
    alice.rename_sheet("Feuille1", "Feuille1")
    alice.set_right("bob", "Feuille1", "lecture")
    got = alice.right("bob", "Feuille1")
    assert got == "lecture", f"A50 : droit de bob attendu 'lecture', obtenu {got!r}"
    assert alice.alerts() == [], f"aucune alerte attendue, obtenu {alerts_repr(alice)}"


def test_A50_reg_downgrade_after_two_noop_set_right():
    clock, net, server, alice, bob, carol = make()
    alice.set_right("bob", "Feuille1", "écriture")
    alice.set_right("carol", "Feuille1", "lecture")
    alice.set_right("bob", "Feuille1", "lecture")
    got = alice.right("bob", "Feuille1")
    assert got == "lecture", f"A50 : droit de bob attendu 'lecture', obtenu {got!r}"
    net.deliver_all()
    assert bob.right("bob", "Feuille1") == "lecture", (
        f"A50 : après livraison, droit vu par bob attendu 'lecture', obtenu {bob.right('bob', 'Feuille1')!r}")


# Cas 25 — C25
def test_C25_reg_undo_after_delivery_to_server_single_pending_effect():
    clock, net, server, alice, bob, carol = make()
    alice.set_cell("A1", "5")
    net.deliver_from("alice")
    before = alice.pending_count()
    alice.undo()
    after = alice.pending_count()
    expected = 1 if before == 0 else before - 1
    assert after == expected, (
        f"C25 : avant annulation {before} en attente ; attendu {expected} "
        f"(retrait si non confirmée, une seule inverse si confirmée), obtenu {after}")
    assert alice.content("A1") is None
    net.deliver_all()
    for c, name in ((alice, "alice"), (bob, "bob")):
        assert c.content("A1") is None, f"chez {name}, A1 attendu vide, obtenu {c.content('A1')!r}"
    assert alice.pending_count() == 0


# Cas 26 — A112
def test_A112_reg_undo_redone_rename_after_refused_delete_and_other_edit():
    clock, net, server, alice, bob, carol = make()
    bob.rename_sheet("Feuille1", "Brouillon")
    net.deliver_all()
    bob.delete_sheet("Brouillon")
    assert bob.sheets() == ["Brouillon"]
    bob.undo()
    bob.redo()
    net.deliver_all()
    clock.advance(timedelta(minutes=1))
    alice.set_cell("B1", "2.5", sheet="Brouillon")
    net.deliver_all()
    bob.undo()
    assert bob.sheets() == ["Feuille1"], f"A112 : feuilles attendues ['Feuille1'], obtenu {bob.sheets()}"
    got = bob.content("B1", sheet="Feuille1")
    assert got == "2.5", f"B1 écrit par alice doit être conservé ('2.5'), obtenu {got!r}"
    assert bob.right("alice", "Feuille1") == "écriture", (
        f"C02 : droit d'alice attendu 'écriture', obtenu {bob.right('alice', 'Feuille1')!r}")
    net.deliver_all()
    assert alice.sheets() == ["Feuille1"], f"chez alice, feuilles attendues ['Feuille1'], obtenu {alice.sheets()}"
    assert alice.content("B1", sheet="Feuille1") == "2.5"
