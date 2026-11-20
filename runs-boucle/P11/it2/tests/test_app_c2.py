"""Tests rouges — couche code — sonde P11, ajouts C14 à C20."""
from datetime import datetime, timezone
import pytest
import app

@pytest.fixture
def env():
    clock = app.Clock(datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc))
    net = app.Network()
    server = app.Server(net, clock, owner='alice')
    alice = app.Client(net, clock, 'alice', tz='Europe/Paris')
    bob = app.Client(net, clock, 'bob', tz='UTC')
    carol = app.Client(net, clock, 'carol', tz='Europe/Paris')
    net.deliver_all()
    alice.set_right('bob', 'Feuille1', 'écriture')
    alice.set_right('carol', 'Feuille1', 'lecture')
    net.deliver_all()
    return {'clock': clock, 'net': net, 'server': server, 'alice': alice, 'bob': bob, 'carol': carol}

def _new_alerts(client, before):
    return list(client.alerts())[before:]

def test_C14_lecture_resout_conflit_valeur_retenue_alerte_droit_insuffisant(env):
    alice, bob, carol, net = (env['alice'], env['bob'], env['carol'], env['net'])
    alice.set_cell('A1', '1')
    bob.set_cell('A1', '2')
    net.deliver_all()
    before = len(carol.alerts())
    carol.resolve_conflict('A1', use_discarded=False)
    new = _new_alerts(carol, before)
    hits = [a for a in new if a.kind == 'droit_insuffisant' and a.sheet == 'Feuille1' and (a.cell == 'A1')]
    assert hits, f'C14 : attendu une alerte droit_insuffisant (Feuille1, A1) ; obtenu {[(a.kind, a.sheet, a.cell, a.line) for a in new]}'

def test_C14_lecture_resout_conflit_valeur_ecartee_alerte_droit_insuffisant(env):
    alice, bob, carol, net = (env['alice'], env['bob'], env['carol'], env['net'])
    alice.set_cell('A1', '1')
    bob.set_cell('A1', '2')
    net.deliver_all()
    before = len(carol.alerts())
    carol.resolve_conflict('A1', use_discarded=True)
    new = _new_alerts(carol, before)
    hits = [a for a in new if a.kind == 'droit_insuffisant' and a.sheet == 'Feuille1' and (a.cell == 'A1')]
    assert hits, f'C14 : attendu une alerte droit_insuffisant (Feuille1, A1) ; obtenu {[(a.kind, a.sheet, a.cell, a.line) for a in new]}'

def test_C16_auto_reference_avec_dependance_en_erreur_syntaxe_donne_circ(env):
    bob = env['bob']
    bob.set_cell('B1', '=')
    assert bob.error('B1') == '#SYNTAXE!', f"précondition : B1 #SYNTAXE!, obtenu {bob.error('B1')}"
    bob.set_cell('A1', '=B1-A1')
    assert bob.error('A1') == '#CIRC!', f"C16 : attendu #CIRC! en A1, obtenu {bob.error('A1')}"
    assert bob.value('A1') == '#CIRC!', f"C16 : valeur attendue #CIRC!, obtenu {bob.value('A1')!r}"
    assert bob.content('A1') == '=B1-A1'
    assert bob.error('B1') == '#SYNTAXE!', f"B1 doit rester #SYNTAXE!, obtenu {bob.error('B1')}"

def test_C17_changer_un_droit_ne_compte_pas_en_attente(env):
    alice = env['alice']
    assert alice.pending_count() == 0
    alice.set_right('carol', 'Feuille1', 'écriture')
    assert alice.pending_count() == 0, f'C17 : attendu 0 modification en attente, obtenu {alice.pending_count()}'

def test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte(env):
    alice = env['alice']
    alice.set_cell('A1', '5')
    assert alice.pending_count() == 1
    alice.set_right('carol', 'Feuille1', 'écriture')
    assert alice.pending_count() == 1, f'C17 : attendu 1 modification en attente, obtenu {alice.pending_count()}'
    alice.undo()
    assert alice.pending_count() == 2, f'C17+C07 : attendu 2 (modification + annulation), obtenu {alice.pending_count()}'

def test_C18_date_heure_hiver_contenu_identique_chez_autre_fuseau(env):
    alice, bob, net = (env['alice'], env['bob'], env['net'])
    alice.set_cell('A2', '2026-01-15 12:00')
    net.deliver_all()
    assert bob.content('A2') == '2026-01-15 12:00', f"C18 : contenu attendu '2026-01-15 12:00' chez bob, obtenu {bob.content('A2')!r}"
    assert bob.value('A2') == '2026-01-15 11:00', f"C18 : valeur attendue '2026-01-15 11:00' chez bob (UTC), obtenu {bob.value('A2')!r}"
    assert alice.content('A2') == '2026-01-15 12:00'

def test_C18_date_heure_jour_changement_heure_contenu_identique_chez_autre_fuseau(env):
    alice, bob, net = (env['alice'], env['bob'], env['net'])
    bob.set_cell('B2', '2026-03-29 02:30')
    net.deliver_all()
    assert alice.content('B2') == '2026-03-29 02:30', f"C18 : contenu attendu '2026-03-29 02:30' chez alice, obtenu {alice.content('B2')!r}"
    assert alice.value('B2') == '2026-03-29 04:30', f"C18 : valeur attendue '2026-03-29 04:30' (Paris, heure d'été), obtenu {alice.value('B2')!r}"
    assert bob.value('B2') == '2026-03-29 02:30'

def test_C19_lecture_importe_csv_vide_alerte_droit_insuffisant_feuille_active(env):
    carol = env['carol']
    carol.activate('Feuille1')
    before = len(carol.alerts())
    carol.import_csv(b'')
    new = _new_alerts(carol, before)
    hits = [a for a in new if a.kind == 'droit_insuffisant' and a.sheet == 'Feuille1']
    assert hits, f'C19 : attendu une alerte droit_insuffisant citant Feuille1 ; obtenu {[(a.kind, a.sheet, a.cell, a.line) for a in new]}'
    assert carol.content('A1') is None
    assert carol.can_undo() is False

def test_C20_proprietaire_passe_lecture_a_ecriture_sans_alerte(env):
    alice, carol, net = (env['alice'], env['carol'], env['net'])
    assert alice.right('carol', 'Feuille1') == 'lecture'
    before = len(alice.alerts())
    alice.set_right('carol', 'Feuille1', 'écriture')
    net.deliver_all()
    assert alice.right('carol', 'Feuille1') == 'écriture', f"C20 : droit attendu 'écriture', obtenu {alice.right('carol', 'Feuille1')!r}"
    new = _new_alerts(alice, before)
    assert new == [], f'C20 : aucune alerte attendue, obtenu {[(a.kind, a.sheet, a.cell) for a in new]}'
    assert carol.right('carol', 'Feuille1') == 'écriture', f"C20 : chez carol, droit attendu 'écriture', obtenu {carol.right('carol', 'Feuille1')!r}"
