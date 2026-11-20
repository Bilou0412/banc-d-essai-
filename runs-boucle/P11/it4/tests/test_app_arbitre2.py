"""Tests rouges — couche code — règles tranchées par l'arbitre (C07, C15, C21-C28).

Écrits sans voir l'implémentation, uniquement à partir de la spécification et de
l'interface publique de `app`.

Conventions supposées (tirées de l'interface publique) :
- un envoi est « confirmé » une fois que `net.deliver_all()` a livré le message au
  serveur et l'accusé de retour au client ; avant cela il est « en attente » ;
- `alerts()` ne fait qu'ajouter des alertes : les nouvelles alertes sont la fin de la liste.

Lacunes relevées (non testées, à trancher par l'arbitre) :
- C27 / ajout de feuille : les droits sont par feuille, la « feuille en cause » d'un ajout
  refusé n'est pas définie (feuille demandée ? feuille active ?). Le test accepte l'une
  ou l'autre.
- C21 contre C12 : importer un CSV identique au contenu actuel ne change rien (P1 : aucune
  entrée d'historique) mais C12 dit que tout import gagne une entrée. Les deux règles
  donnent deux réponses ; aucun test n'est écrit tant que l'arbitre n'a pas tranché.
"""
from datetime import datetime, timezone
import app
START = datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc)

def make_world(*names, tz='Europe/Paris'):
    clock = app.Clock(START)
    net = app.Network()
    server = app.Server(net, clock, owner='alice')
    clients = {n: app.Client(net, clock, n, tz=tz) for n in names}
    net.deliver_all()
    return (clock, net, server, clients)

def grant(owner, net, person, level, sheet='Feuille1'):
    owner.set_right(person, sheet, level)
    net.deliver_all()
    assert owner.right(person, sheet) == level, f'précondition : droit de {person} sur {sheet} attendu {level!r}, obtenu {owner.right(person, sheet)!r}'

def history_ids(c, sheet=None):
    return [v.id for v in c.history(sheet)]

def new_alerts(c, before):
    return c.alerts()[before:]

def make_conflict(net, first, first_name, second, ref='A1', v1='10', v2='20'):
    """first et second saisissent en même temps ; le serveur reçoit first d'abord."""
    first.set_cell(ref, v1)
    second.set_cell(ref, v2)
    net.deliver_from(first_name)
    net.deliver_all()

def test_C07_online_edit_undone_before_confirmation_pending_back_to_zero():
    _, net, _, cs = make_world('alice', 'bob')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    assert alice.pending_count() == 1, f'précondition : envoi non confirmé, attendu 1 en attente, obtenu {alice.pending_count()}'
    alice.undo()
    assert alice.pending_count() == 0, f'C07 : annuler une modification en attente doit la retirer : attendu 0, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert alice.pending_count() == 0, f'C07 : après livraison, attendu 0 en attente, obtenu {alice.pending_count()}'
    assert cs['bob'].content('A1') is None, f"C07 : la modification retirée ne doit jamais atteindre bob, contenu attendu None, obtenu {cs['bob'].content('A1')!r}"

def test_C07_undo_removes_only_the_last_pending_edit():
    _, _, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    alice.set_cell('A2', '6')
    assert alice.pending_count() == 2, f'précondition : attendu 2, obtenu {alice.pending_count()}'
    alice.undo()
    assert alice.pending_count() == 1, f'C07 : une annulation retire une seule modification en attente : attendu 1, obtenu {alice.pending_count()}'
    alice.undo()
    assert alice.pending_count() == 0, f'C07 : après deux annulations, attendu 0 en attente, obtenu {alice.pending_count()}'

def test_C15_clear_empty_cell_on_fresh_client_leaves_no_trace():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    before_hist = history_ids(alice)
    assert alice.can_undo() is False, "précondition : annuler indisponible à l'ouverture"
    alice.clear('A1')
    assert alice.pending_count() == 0, f'C15 : effacer une cellule vide ne doit rien mettre en attente, obtenu {alice.pending_count()}'
    assert alice.can_undo() is False, 'C15 : effacer une cellule vide ne doit pas rendre la commande annuler disponible'
    net.deliver_all()
    assert history_ids(alice) == before_hist, f"C15 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(alice)}"

def test_C15_clear_cell_already_cleared_and_confirmed_leaves_no_trace():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    alice.clear('A1')
    net.deliver_all()
    before_hist = history_ids(alice)
    alice.clear('A1')
    assert alice.pending_count() == 0, f"C15 : second effacement d'une cellule déjà vide, attendu 0 en attente, obtenu {alice.pending_count()}"
    net.deliver_all()
    assert history_ids(alice) == before_hist, f'C15 : aucune nouvelle entrée attendue ; avant {before_hist}, après {history_ids(alice)}'

def test_C15_clear_empty_cell_offline_does_not_increase_pending():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    net.disconnect('alice')
    alice.set_cell('A2', '3')
    assert alice.pending_count() == 1, f'précondition : attendu 1, obtenu {alice.pending_count()}'
    alice.clear('A1')
    assert alice.pending_count() == 1, f"C15 : effacer une cellule vide hors ligne ne doit pas ajouter d'attente : attendu 1, obtenu {alice.pending_count()}"

def test_C21_retyping_same_number_leaves_no_trace():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '42')
    alice.set_cell('B1', '=A1*2')
    net.deliver_all()
    before_hist = history_ids(alice)
    alice.set_cell('A1', '42')
    assert alice.pending_count() == 0, f'C21 : ressaisir le même contenu ne doit rien mettre en attente, obtenu {alice.pending_count()}'
    assert alice.value('A1') == 42 and alice.value('B1') == 84, f"C21 : aucune valeur ne change ; attendu A1=42, B1=84, obtenu A1={alice.value('A1')!r}, B1={alice.value('B1')!r}"
    net.deliver_all()
    assert history_ids(alice) == before_hist, f"C21 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(alice)}"

def test_C21_retyping_same_formula_leaves_no_trace():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '3')
    alice.set_cell('B1', '=A1*2')
    net.deliver_all()
    before_hist = history_ids(alice)
    alice.set_cell('B1', '=A1*2')
    assert alice.pending_count() == 0, f'C21 : ressaisir la même formule, attendu 0 en attente, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert history_ids(alice) == before_hist, f"C21 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(alice)}"
    assert alice.value('B1') == 6, f"C21 : B1 attendu 6, obtenu {alice.value('B1')!r}"

def test_C21_retyping_same_content_while_first_still_pending_counts_once():
    _, _, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    alice.set_cell('A1', '5')
    assert alice.pending_count() == 1, f'C21 : la seconde saisie identique ne change rien : attendu 1 en attente, obtenu {alice.pending_count()}'

def test_C21_retyping_same_content_offline_does_not_increase_pending():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    net.disconnect('alice')
    alice.set_cell('A1', '5')
    assert alice.pending_count() == 0, f'C21 : saisie identique hors ligne, attendu 0 en attente, obtenu {alice.pending_count()}'

def test_C21_refused_write_by_reader_leaves_no_trace():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.set_cell('A1', '5')
    alice.set_cell('B1', '=A1*2')
    net.deliver_all()
    grant(alice, net, 'bob', 'lecture')
    before_hist = history_ids(alice)
    bob_pending = bob.pending_count()
    bob.set_cell('A1', '99')
    assert bob.pending_count() == bob_pending, f'C21 : écriture refusée, attente inchangée attendue ({bob_pending}), obtenu {bob.pending_count()}'
    assert bob.value('B1') == 10, f"C21 : B1 doit rester 10 chez bob, obtenu {bob.value('B1')!r}"
    net.deliver_all()
    assert history_ids(alice) == before_hist, f"C21 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(alice)}"
    assert alice.value('B1') == 10, f"C21 : B1 doit rester 10 chez alice, obtenu {alice.value('B1')!r}"

def test_C21_setting_right_to_current_level_leaves_no_trace():
    _, net, _, cs = make_world('alice', 'bob')
    alice = cs['alice']
    grant(alice, net, 'bob', 'lecture')
    before_hist = history_ids(alice)
    before_pending = alice.pending_count()
    alice.set_right('bob', 'Feuille1', 'lecture')
    assert alice.pending_count() == before_pending, f'C21 : droit identique, attente attendue {before_pending}, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert history_ids(alice) == before_hist, f"C21 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(alice)}"
    assert alice.right('bob', 'Feuille1') == 'lecture'

def test_C21_undo_with_nothing_to_undo_leaves_no_trace():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.set_cell('A1', '5')
    net.deliver_all()
    before_hist = history_ids(bob)
    bob.undo()
    assert bob.pending_count() == 0, f'C21 : annuler sans rien à annuler, attendu 0 en attente, obtenu {bob.pending_count()}'
    net.deliver_all()
    assert history_ids(bob) == before_hist, f"C21 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(bob)}"
    assert bob.value('A1') == 5, f"C21 : A1 doit rester 5, obtenu {bob.value('A1')!r}"

def test_C21_redo_with_nothing_to_redo_leaves_no_trace():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    before_hist = history_ids(alice)
    alice.redo()
    assert alice.pending_count() == 0, f'C21 : rétablir sans rien à rétablir, attendu 0 en attente, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert history_ids(alice) == before_hist, f"C21 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(alice)}"
    assert alice.value('A1') == 5

def test_C21_refused_delete_of_last_sheet_leaves_no_trace():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    before_hist = history_ids(alice)
    alice.delete_sheet('Feuille1')
    assert alice.sheets() == ['Feuille1'], f'précondition A45 : obtenu {alice.sheets()}'
    assert alice.pending_count() == 0, f'C21 : suppression refusée, attendu 0 en attente, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert history_ids(alice) == before_hist, f"C21 : aucune entrée d'historique attendue ; avant {before_hist}, après {history_ids(alice)}"
    assert alice.value('A1') == 5

def test_C21_rename_to_same_name_offline_does_not_increase_pending():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    net.disconnect('alice')
    alice.rename_sheet('Feuille1', 'Feuille1')
    assert alice.pending_count() == 0, f'C21 : renommage identique hors ligne, attendu 0 en attente, obtenu {alice.pending_count()}'

def test_C21_selecting_a_cell_leaves_no_trace():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    before_hist = history_ids(alice)
    alice.select('B2')
    assert alice.pending_count() == 0, f"C21 : une sélection n'est pas une modification, obtenu {alice.pending_count()} en attente"
    net.deliver_all()
    assert history_ids(alice) == before_hist

def test_C22_resolve_on_cell_without_conflict_use_discarded_true_changes_nothing():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.set_cell('A1', '5')
    net.deliver_all()
    assert alice.conflict('A1') is None, 'précondition : aucun conflit sur A1'
    alice.resolve_conflict('A1', True)
    assert alice.content('A1') == '5', f"C22 : contenu attendu '5', obtenu {alice.content('A1')!r}"
    assert alice.pending_count() == 0, f'C22 : attendu 0 en attente, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert bob.content('A1') == '5', f"C22 : chez bob attendu '5', obtenu {bob.content('A1')!r}"

def test_C22_resolve_on_cell_without_conflict_use_discarded_false_changes_nothing():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    alice.resolve_conflict('A1', False)
    assert alice.content('A1') == '5', f"C22 : attendu '5', obtenu {alice.content('A1')!r}"
    assert alice.pending_count() == 0, f'C22 : attendu 0, obtenu {alice.pending_count()}'

def test_C22_resolve_on_empty_cell_without_conflict_changes_nothing():
    _, _, _, cs = make_world('alice')
    alice = cs['alice']
    for choice in (True, False):
        alice.resolve_conflict('B7', choice)
        assert alice.content('B7') is None, f"C22 (use_discarded={choice}) : contenu attendu None, obtenu {alice.content('B7')!r}"
        assert alice.pending_count() == 0, f'C22 (use_discarded={choice}) : attendu 0, obtenu {alice.pending_count()}'

def test_C22_resolve_without_conflict_offline_keeps_pending_count():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    net.disconnect('alice')
    alice.set_cell('A2', '1')
    assert alice.pending_count() == 1
    alice.resolve_conflict('A1', True)
    assert alice.pending_count() == 1, f'C22 : hors ligne, attente attendue 1, obtenu {alice.pending_count()}'
    assert alice.content('A1') == '5', f"C22 : attendu '5', obtenu {alice.content('A1')!r}"

def test_C22_second_resolve_after_conflict_resolved_changes_nothing():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    grant(alice, net, 'bob', 'écriture')
    make_conflict(net, alice, 'alice', bob, 'A1', '10', '20')
    assert alice.conflict('A1') is not None, 'précondition A68 : conflit attendu sur A1 chez alice'
    alice.resolve_conflict('A1', True)
    net.deliver_all()
    assert alice.content('A1') == '20', f"précondition A72 : attendu '20', obtenu {alice.content('A1')!r}"
    assert alice.conflict('A1') is None, 'précondition A73 : conflit résolu'
    for choice in (True, False):
        alice.resolve_conflict('A1', choice)
        assert alice.content('A1') == '20', f"C22 (use_discarded={choice}) : la cellule ne montre plus de conflit, contenu attendu '20', obtenu {alice.content('A1')!r}"
        assert alice.pending_count() == 0, f'C22 (use_discarded={choice}) : attendu 0, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert bob.content('A1') == '20', f"C22 : chez bob attendu '20', obtenu {bob.content('A1')!r}"

def test_C23_rename_refused_for_reader_keeps_sheets_and_empty_cells_empty():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    grant(alice, net, 'bob', 'lecture')
    bob.rename_sheet('Feuille1', 'Ventes')
    for who, c in (('bob', bob), ('alice', alice)):
        if who == 'alice':
            net.deliver_all()
        assert c.sheets() == ['Feuille1'], f"C23 ({who}) : attendu ['Feuille1'], obtenu {c.sheets()}"
        for ref in ('A1', 'B2', 'Z99'):
            assert c.content(ref, sheet='Feuille1') is None, f"C23 ({who}) : {ref} doit rester sans contenu, obtenu {c.content(ref, sheet='Feuille1')!r}"
            assert c.value(ref, sheet='Feuille1') is None, f"C23 ({who}) : {ref} doit rester sans valeur, obtenu {c.value(ref, sheet='Feuille1')!r}"
            assert c.error(ref, sheet='Feuille1') is None, f"C23 ({who}) : {ref} ne doit afficher aucune erreur, obtenu {c.error(ref, sheet='Feuille1')!r}"

def test_C23_rename_refused_for_duplicate_name_keeps_sheets_and_cells():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.add_sheet('Ventes')
    alice.set_cell('A1', '8', sheet='Ventes')
    alice.set_cell('B1', '=Feuille1!A1', sheet='Ventes')
    net.deliver_all()
    before = alice.sheets()
    alice.rename_sheet('Feuille1', 'Ventes')
    assert alice.sheets() == before, f'C23 : attendu {before}, obtenu {alice.sheets()}'
    for ref in ('A1', 'C3'):
        assert alice.value(ref, sheet='Feuille1') is None and alice.error(ref, sheet='Feuille1') is None, f"C23 : Feuille1!{ref} doit rester vide sans erreur, obtenu valeur={alice.value(ref, sheet='Feuille1')!r}, erreur={alice.error(ref, sheet='Feuille1')!r}"
    assert alice.content('B1', sheet='Ventes') == '=Feuille1!A1', f"C23 : la formule citant Feuille1 ne change pas, obtenu {alice.content('B1', sheet='Ventes')!r}"
    assert alice.error('B1', sheet='Ventes') is None, f"C23 : aucune erreur attendue sur Ventes!B1, obtenu {alice.error('B1', sheet='Ventes')!r}"
    assert alice.value('A1', sheet='Ventes') == 8

def test_C24_online_import_undone_before_confirmation_pending_back_to_zero():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.import_csv('1,2,3\n4,5,6\n'.encode('utf-8'))
    assert alice.pending_count() == 1, f'précondition C05 : attendu 1, obtenu {alice.pending_count()}'
    alice.undo()
    assert alice.pending_count() == 0, f'C24 : import annulé avant confirmation, attendu 0, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert alice.pending_count() == 0, f'C24 : après livraison attendu 0, obtenu {alice.pending_count()}'
    for ref in ('A1', 'C2'):
        assert bob.content(ref) is None, f"C24 : l'import retiré ne doit pas atteindre bob ; {ref} obtenu {bob.content(ref)!r}"

def test_C24_import_undone_after_earlier_pending_edit_leaves_earlier_edit_pending():
    _, _, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('Z1', '7')
    alice.import_csv('1,2\n'.encode('utf-8'))
    assert alice.pending_count() == 2, f'précondition : attendu 2, obtenu {alice.pending_count()}'
    alice.undo()
    assert alice.pending_count() == 1, f"C24 : l'annulation de l'import retire l'import seul, attendu 1, obtenu {alice.pending_count()}"
    assert alice.content('Z1') == '7'

def test_C25_undo_of_confirmed_edit_online_adds_one_pending_inverse():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.set_cell('A1', '5')
    net.deliver_all()
    assert alice.pending_count() == 0, 'précondition : envoi confirmé'
    alice.undo()
    assert alice.pending_count() == 1, f"C25 : annuler une modification confirmée crée l'inverse en attente : attendu 1, obtenu {alice.pending_count()}"
    assert alice.content('A1') is None, f"C25 : A1 attendu None, obtenu {alice.content('A1')!r}"
    net.deliver_all()
    assert alice.pending_count() == 0, f'C25 : après livraison attendu 0, obtenu {alice.pending_count()}'
    assert bob.content('A1') is None, f"C25 : la modification inverse doit atteindre bob, obtenu {bob.content('A1')!r}"

def test_C25_mixed_confirmed_then_pending_edits_undone_in_order():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    alice.set_cell('A1', '7')
    assert alice.pending_count() == 1
    alice.undo()
    assert alice.pending_count() == 0, f'C25 : la modification encore en attente est retirée, attendu 0, obtenu {alice.pending_count()}'
    assert alice.content('A1') == '5', f"C25 : A1 attendu '5', obtenu {alice.content('A1')!r}"
    alice.undo()
    assert alice.pending_count() == 1, f'C25 : la modification confirmée est défaite par une inverse en attente, attendu 1, obtenu {alice.pending_count()}'
    assert alice.content('A1') is None, f"C25 : A1 attendu None, obtenu {alice.content('A1')!r}"

def test_C25_undo_of_confirmed_formula_input_recomputes_dependents_elsewhere():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.set_cell('A1', '2')
    alice.set_cell('B1', '=A1*2')
    net.deliver_all()
    alice.set_cell('A1', '10')
    net.deliver_all()
    alice.undo()
    assert alice.pending_count() == 1, f'C25 : attendu 1, obtenu {alice.pending_count()}'
    net.deliver_all()
    assert bob.content('A1') == '2' and bob.value('B1') == 4, f"C25 : chez bob attendu A1='2', B1=4 ; obtenu A1={bob.content('A1')!r}, B1={bob.value('B1')!r}"

def test_C26_offline_undo_of_edit_confirmed_before_cut_adds_one_pending():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    assert alice.pending_count() == 0
    net.disconnect('alice')
    alice.undo()
    assert alice.pending_count() == 1, f'C26 : attendu 1 en attente, obtenu {alice.pending_count()}'
    assert alice.content('A1') is None, f"C26 : A1 attendu None, obtenu {alice.content('A1')!r}"

def test_C26_offline_undo_inverse_reaches_others_after_reconnection():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.set_cell('A1', '5')
    net.deliver_all()
    net.disconnect('alice')
    alice.undo()
    assert alice.pending_count() == 1
    net.deliver_all()
    assert bob.content('A1') == '5', "C26 : tant qu'alice est hors ligne, bob garde '5'"
    net.reconnect('alice')
    net.deliver_all()
    assert alice.pending_count() == 0, f'C26 : après fusion attendu 0, obtenu {alice.pending_count()}'
    assert bob.content('A1') is None, f"C26 : l'inverse doit être appliquée chez bob, obtenu {bob.content('A1')!r}"

def test_C26_offline_undo_survives_reopen_as_pending():
    _, net, _, cs = make_world('alice')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    net.disconnect('alice')
    alice.undo()
    alice2 = alice.reopen()
    assert alice2.pending_count() == 1, f"C26/A92 : l'inverse en attente est conservée à la réouverture, obtenu {alice2.pending_count()}"

def _reader_world():
    _, net, _, cs = make_world('alice', 'bob', 'carol')
    alice = cs['alice']
    alice.set_cell('A1', '5')
    net.deliver_all()
    grant(alice, net, 'bob', 'lecture')
    return (net, cs)

def _assert_refused_alert(c, before, sheet, what):
    got = new_alerts(c, before)
    matching = [a for a in got if a.kind == 'droit_insuffisant']
    assert matching, f"C27 ({what}) : alerte 'droit_insuffisant' attendue, obtenu {[(a.kind, a.sheet, a.cell) for a in got]}"
    assert any((a.sheet == sheet for a in matching)), f"C27 ({what}) : l'alerte doit citer la feuille {sheet!r}, obtenu {[a.sheet for a in matching]}"

def test_C27_reader_set_cell_refused_with_alert():
    net, cs = _reader_world()
    bob = cs['bob']
    n = len(bob.alerts())
    bob.set_cell('A1', '99')
    assert bob.content('A1') == '5', f"C27 : contenu attendu '5', obtenu {bob.content('A1')!r}"
    _assert_refused_alert(bob, n, 'Feuille1', 'saisie')

def test_C27_reader_clear_refused_with_alert():
    net, cs = _reader_world()
    bob = cs['bob']
    n = len(bob.alerts())
    bob.clear('A1')
    assert bob.content('A1') == '5', f"C27 : contenu attendu '5', obtenu {bob.content('A1')!r}"
    net.deliver_all()
    assert cs['alice'].content('A1') == '5'
    _assert_refused_alert(bob, n, 'Feuille1', 'effacement')

def test_C27_reader_import_refused_with_alert():
    net, cs = _reader_world()
    bob = cs['bob']
    n = len(bob.alerts())
    bob.import_csv('9,9\n'.encode('utf-8'))
    assert bob.content('A1') == '5' and bob.content('B1') is None, f"C27 : contenus inchangés attendus, obtenu A1={bob.content('A1')!r}, B1={bob.content('B1')!r}"
    _assert_refused_alert(bob, n, 'Feuille1', 'import')

def test_C27_reader_rename_refused_with_alert_citing_old_name():
    net, cs = _reader_world()
    bob = cs['bob']
    n = len(bob.alerts())
    bob.rename_sheet('Feuille1', 'Ventes')
    assert bob.sheets() == ['Feuille1'], f"C27 : attendu ['Feuille1'], obtenu {bob.sheets()}"
    _assert_refused_alert(bob, n, 'Feuille1', 'renommage')

def test_C27_reader_delete_sheet_refused_with_alert():
    _, net, _, cs = make_world('alice', 'bob')
    alice, bob = (cs['alice'], cs['bob'])
    alice.add_sheet('Feuille2')
    net.deliver_all()
    grant(alice, net, 'bob', 'lecture', 'Feuille1')
    grant(alice, net, 'bob', 'lecture', 'Feuille2')
    n = len(bob.alerts())
    bob.delete_sheet('Feuille2')
    assert 'Feuille2' in bob.sheets(), f'C27 : Feuille2 doit rester, obtenu {bob.sheets()}'
    net.deliver_all()
    assert 'Feuille2' in alice.sheets(), f'C27 : Feuille2 doit rester chez alice, obtenu {alice.sheets()}'
    _assert_refused_alert(bob, n, 'Feuille2', 'suppression de feuille')

def test_C27_reader_resolve_conflict_refused_with_alert_both_choices():
    _, net, _, cs = make_world('alice', 'bob', 'carol')
    alice, bob, carol = (cs['alice'], cs['bob'], cs['carol'])
    grant(alice, net, 'carol', 'écriture')
    grant(alice, net, 'bob', 'lecture')
    make_conflict(net, alice, 'alice', carol, 'A1', '10', '20')
    assert bob.conflict('A1') is not None, 'précondition A68/A75 : bob voit le conflit sur A1'
    for choice in (True, False):
        n = len(bob.alerts())
        bob.resolve_conflict('A1', choice)
        assert bob.content('A1') == '10', f"C27 (use_discarded={choice}) : contenu attendu '10', obtenu {bob.content('A1')!r}"
        assert bob.conflict('A1') is not None, f'C27 (use_discarded={choice}) : le conflit doit rester affiché'
        _assert_refused_alert(bob, n, 'Feuille1', f'résolution de conflit use_discarded={choice}')
    net.deliver_all()
    assert alice.content('A1') == '10' and alice.conflict('A1') is not None

def _rename_world():
    _, net, _, cs = make_world('alice', 'bob', 'carol')
    alice = cs['alice']
    grant(alice, net, 'bob', 'écriture')
    grant(alice, net, 'carol', 'écriture')
    alice.add_sheet('Feuille2')
    alice.set_cell('A1', '8', sheet='Feuille2')
    alice.set_cell('B1', '=Feuille2!A1', sheet='Feuille1')
    net.deliver_all()
    return (net, cs)

def _check_renamed(cs, extra=()):
    for who, c in cs.items():
        assert 'Ventes' in c.sheets() and 'Feuille2' not in c.sheets(), f"C28 ({who}) : feuilles attendues avec 'Ventes' sans 'Feuille2', obtenu {c.sheets()}"
        cells = [('B1', '=Ventes!A1', 8)] + list(extra)
        for ref, content, value in cells:
            assert c.content(ref, sheet='Feuille1') == content, f"C28 ({who}) : Feuille1!{ref} attendu {content!r}, obtenu {c.content(ref, sheet='Feuille1')!r}"
            assert c.error(ref, sheet='Feuille1') is None, f"C28 ({who}) : Feuille1!{ref} sans erreur attendu, obtenu {c.error(ref, sheet='Feuille1')!r}"
            assert c.value(ref, sheet='Feuille1') == value, f"C28 ({who}) : Feuille1!{ref} valeur attendue {value!r}, obtenu {c.value(ref, sheet='Feuille1')!r}"
        for sheet, ref in (('Feuille1', 'D9'), ('Ventes', 'B2'), ('Ventes', 'A2')):
            assert c.content(ref, sheet=sheet) is None and c.value(ref, sheet=sheet) is None and (c.error(ref, sheet=sheet) is None), f'C28 ({who}) : {sheet}!{ref} doit rester vide ; obtenu contenu={c.content(ref, sheet=sheet)!r}, valeur={c.value(ref, sheet=sheet)!r}, erreur={c.error(ref, sheet=sheet)!r}'

def test_C28_rename_delivered_to_all_online_updates_formulas_everywhere():
    net, cs = _rename_world()
    cs['alice'].rename_sheet('Feuille2', 'Ventes')
    net.deliver_all()
    _check_renamed(cs)
