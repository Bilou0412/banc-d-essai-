"""Tests rouges — couche code — compléments C01..C13 (sonde P11)."""
import csv
import io
from datetime import datetime, timezone
import app

def _world(with_rights=True):
    clock = app.Clock(datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc))
    net = app.Network()
    server = app.Server(net, clock, owner='alice')
    alice = app.Client(net, clock, 'alice', tz='Europe/Paris')
    bob = app.Client(net, clock, 'bob', tz='Europe/Paris')
    carol = app.Client(net, clock, 'carol', tz='Europe/Paris')
    net.deliver_all()
    if with_rights:
        alice.set_right('bob', 'Feuille1', 'écriture')
        alice.set_right('carol', 'Feuille1', 'lecture')
        net.deliver_all()
    return (clock, net, server, alice, bob, carol)

def _alerts(client):
    return [(a.kind, a.sheet, a.cell, a.line) for a in client.alerts()]

def _rows(data):
    assert isinstance(data, bytes), f'export_csv doit renvoyer des bytes, obtenu {type(data)!r}'
    return [r for r in csv.reader(io.StringIO(data.decode('utf-8')))]

def test_C01_datetime_without_offset_content_is_exact_typed_text():
    _, net, _, alice, _, _ = _world()
    alice.set_cell('C1', '2026-01-15 12:00', sheet='Feuille1')
    got = alice.content('C1', sheet='Feuille1')
    assert got == '2026-01-15 12:00', f"contenu attendu exactement '2026-01-15 12:00' (texte saisi, sans décalage), obtenu {got!r}"

def test_C02_rename_sheet_keeps_every_persons_right():
    _, net, _, alice, bob, carol = _world()
    before = {p: bob.right(p, 'Feuille1') for p in ('alice', 'bob', 'carol')}
    assert before == {'alice': 'écriture', 'bob': 'écriture', 'carol': 'lecture'}, f'préconditions de droits inattendues : {before!r}'
    bob.rename_sheet('Feuille1', 'Brouillon')
    after = {p: bob.right(p, 'Brouillon') for p in ('alice', 'bob', 'carol')}
    assert after == before, f'droits sur la feuille renommée attendus {before!r}, obtenus {after!r}'

def test_C03_add_sheet_as_first_action_makes_undo_available():
    _, net, _, alice, _, _ = _world(with_rights=False)
    assert alice.can_undo() is False, "précondition : aucune action depuis l'ouverture, annuler doit être indisponible"
    alice.add_sheet('Feuille2')
    assert alice.can_undo() is True, f'après add_sheet, annuler attendu disponible (True), obtenu {alice.can_undo()!r}'

def test_C03_add_sheet_by_non_owner_makes_undo_available():
    _, net, _, alice, bob, _ = _world()
    bob_fresh = bob.reopen()
    assert bob_fresh.can_undo() is False, 'précondition : après réouverture, annuler indisponible'
    bob_fresh.add_sheet('Feuille2')
    assert bob_fresh.can_undo() is True, f'après add_sheet par bob, annuler attendu True, obtenu {bob_fresh.can_undo()!r}'

def test_C04_non_owner_changing_right_raises_no_alert():
    _, net, _, alice, bob, carol = _world()
    carol.set_right('bob', 'Feuille1', 'lecture')
    assert carol.right('bob', 'Feuille1') == 'écriture', f"A51 : droit de bob attendu inchangé 'écriture', obtenu {carol.right('bob', 'Feuille1')!r}"
    assert _alerts(carol) == [], f'aucune alerte attendue, obtenu {_alerts(carol)!r}'

def test_C05_csv_import_adds_exactly_one_pending_modification():
    _, net, _, alice, _, _ = _world()
    before = alice.pending_count()
    assert before == 0, f'précondition : 0 modification en attente, obtenu {before}'
    alice.import_csv('"12,5",x\n'.encode('utf-8'))
    assert alice.content('A1') == '12,5' and alice.content('B1') == 'x', f"précondition d'import : A1/B1 attendus '12,5'/'x', obtenus {alice.content('A1')!r}/{alice.content('B1')!r}"
    got = alice.pending_count()
    assert got == before + 1, f'en attente attendu {before + 1} (un import = une modification), obtenu {got}'

def test_C05_csv_import_many_fields_still_one_pending_modification():
    _, net, _, alice, _, _ = _world()
    before = alice.pending_count()
    alice.import_csv(b'1,2,3\n4,5,6\n7,8,9\n')
    got = alice.pending_count()
    assert got == before + 1, f'9 champs importés : en attente attendu {before + 1}, obtenu {got}'

def test_C06_add_sheet_with_existing_name_alert_cites_the_name():
    _, net, _, alice, _, _ = _world()
    alice.add_sheet('Feuille1')
    assert alice.sheets() == ['Feuille1'], f'liste des feuilles attendue inchangée, obtenu {alice.sheets()!r}'
    got = [(k, s) for k, s, _, _ in _alerts(alice)]
    assert ('nom_existant', 'Feuille1') in got, f"alerte ('nom_existant', 'Feuille1') attendue, obtenu {_alerts(alice)!r}"

def test_C08_invalid_csv_alert_names_active_sheet_and_line():
    _, net, _, alice, bob, _ = _world()
    bob.import_csv(b'a,b\nc,"d\ne,f\n')
    got = _alerts(bob)
    matching = [a for a in got if a[0] == 'csv_invalide']
    assert matching, f'alerte csv_invalide attendue, obtenu {got!r}'
    assert any((s == 'Feuille1' and line == 2 for _, s, _, line in matching)), f"alerte csv_invalide attendue avec sheet='Feuille1' et line=2, obtenu {matching!r}"

def test_C09_export_pads_rows_to_rightmost_non_empty_column():
    _, net, _, alice, _, _ = _world()
    alice.set_cell('A1', 'x')
    alice.set_cell('B2', 'y')
    rows = _rows(alice.export_csv())
    assert rows == [['x', ''], ['', 'y']], f"lignes attendues [['x',''],['','y']], obtenues {rows!r}"

def test_C09_export_pads_rows_with_circular_error_cell():
    _, net, _, alice, _, _ = _world()
    alice.set_cell('A1', '=A1')
    alice.set_cell('B2', '0')
    rows = _rows(alice.export_csv())
    assert rows == [['#CIRC!', ''], ['', '0']], f"lignes attendues [['#CIRC!',''],['','0']], obtenues {rows!r}"

def test_C09_export_every_row_has_same_field_count():
    _, net, _, alice, _, _ = _world()
    alice.set_cell('C1', 'c')
    alice.set_cell('A2', 'a')
    alice.set_cell('B3', 'b')
    rows = _rows(alice.export_csv())
    assert [len(r) for r in rows] == [3, 3, 3], f'3 champs par ligne attendus (dernière colonne non vide = C), obtenu {rows!r}'

def test_C10_sum_over_own_cell_with_text_is_circular_not_type_error():
    _, net, _, alice, _, _ = _world()
    alice.set_cell('A1', 'abc')
    alice.set_cell('A3', '=SOMME(A1:A3)', sheet='Feuille1')
    got = alice.error('A3', sheet='Feuille1')
    assert got == '#CIRC!', f"erreur attendue '#CIRC!' (prioritaire sur '#TYPE!'), obtenu {got!r}"

def test_C11_read_only_delete_sheet_alert_cites_the_sheet():
    _, net, _, alice, _, carol = _world()
    carol.delete_sheet('Feuille1')
    assert carol.sheets() == ['Feuille1'], f'feuille attendue conservée, obtenu {carol.sheets()!r}'
    got = _alerts(carol)
    assert any((k == 'droit_insuffisant' and s == 'Feuille1' for k, s, _, _ in got)), f"alerte ('droit_insuffisant', 'Feuille1') attendue, obtenu {got!r}"

def test_C12_csv_import_adds_single_modification_entry_by_importer():
    _, net, _, alice, bob, carol = _world()
    before = carol.history()
    bob.import_csv(b'1,2\n3,4\n')
    net.deliver_all()
    after = carol.history()
    assert len(after) == len(before) + 1, f"une seule nouvelle entrée attendue pour l'import, {len(after) - len(before)} obtenues"
    newest = after[0]
    assert newest.author == 'bob', f"auteur attendu 'bob', obtenu {newest.author!r}"
    assert newest.kind == 'modification', f"type attendu 'modification', obtenu {newest.kind!r}"

def test_C13_rename_sheet_to_its_own_name_no_alert_no_pending():
    _, net, _, alice, _, _ = _world()
    assert alice.pending_count() == 0, 'précondition : 0 en attente'
    alice.rename_sheet('Feuille1', 'Feuille1')
    assert _alerts(alice) == [], f'aucune alerte attendue, obtenu {_alerts(alice)!r}'
    assert alice.pending_count() == 0, f'en attente attendu 0, obtenu {alice.pending_count()}'
    assert alice.sheets() == ['Feuille1'], f"liste attendue ['Feuille1'], obtenu {alice.sheets()!r}"
