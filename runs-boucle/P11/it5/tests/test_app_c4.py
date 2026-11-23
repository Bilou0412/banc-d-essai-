"""Tests rouges — couche code — ajouts C32 à C34 (sonde P11)."""
from datetime import datetime, timezone
import app

def _setup():
    clock = app.Clock(datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc))
    net = app.Network()
    server = app.Server(net, clock, owner='alice')
    alice = app.Client(net, clock, 'alice', tz='Europe/Paris')
    bob = app.Client(net, clock, 'bob', tz='Europe/Paris')
    carol = app.Client(net, clock, 'carol', tz='Europe/Paris')
    net.deliver_all()
    alice.set_right('bob', 'Feuille1', 'écriture')
    alice.set_right('carol', 'Feuille1', 'lecture')
    net.deliver_all()
    return (clock, net, server, alice, bob, carol)

def _hist(client, sheet):
    return [(v.id, v.author, v.timestamp, v.kind) for v in client.history(sheet=sheet)]

def test_C32_ajout_de_feuille_sans_modification_ne_cree_aucune_entree():
    clock, net, server, alice, bob, carol = _setup()
    before = _hist(carol, 'Feuille1')
    bob.add_sheet('Feuille2')
    net.deliver_all()
    after = _hist(carol, 'Feuille1')
    assert after == before, f"C32 : l'ajout de Feuille2 par bob ne doit pas toucher l'historique de Feuille1 ; attendu {before!r}, obtenu {after!r}"

def test_C32_ajouts_en_ligne_et_hors_ligne_laissent_l_historique_des_autres_feuilles_inchange():
    clock, net, server, alice, bob, carol = _setup()
    bob.set_cell('A1', '2026-03-15', sheet='Feuille1')
    net.deliver_all()
    ref = {c.name if hasattr(c, 'name') else i: _hist(c, 'Feuille1') for i, c in enumerate((alice, bob, carol))}
    assert len(_hist(carol, 'Feuille1')) == 1, f"pré-condition : une entrée attendue pour la saisie de bob, obtenu {_hist(carol, 'Feuille1')!r}"
    alice.add_sheet('Feuille2')
    net.deliver_all()
    net.disconnect('bob')
    bob.add_sheet('Feuille3')
    net.reconnect('bob')
    net.deliver_all()
    for i, c in enumerate((alice, bob, carol)):
        key = c.name if hasattr(c, 'name') else i
        got = _hist(c, 'Feuille1')
        assert got == ref[key], f"C32 : chez {key}, l'historique de Feuille1 ne doit gagner aucune entrée après l'ajout de Feuille2 (en ligne) et Feuille3 (hors ligne) ; attendu {ref[key]!r}, obtenu {got!r}"

def test_C33_proprietaire_ne_peut_pas_se_retrograder_en_lecture():
    clock, net, server, alice, bob, carol = _setup()
    alerts_before = len(alice.alerts())
    alice.set_right('alice', 'Feuille1', 'lecture')
    net.deliver_all()
    for who, c in (('alice', alice), ('bob', bob), ('carol', carol)):
        got = c.right('alice', 'Feuille1')
        assert got == 'écriture', f"C33 : chez {who}, le droit d'alice (propriétaire) sur Feuille1 doit rester 'écriture' après sa tentative de rétrogradation ; obtenu {got!r}"
    new_alerts = alice.alerts()[alerts_before:]
    assert new_alerts == [], f'C33 : aucune alerte attendue chez alice, obtenu {[(a.kind, a.sheet, a.cell) for a in new_alerts]!r}'

def test_C33_droit_reste_ecriture_juste_apres_la_tentative_avant_livraison():
    clock, net, server, alice, bob, carol = _setup()
    alerts_before = len(alice.alerts())
    alice.set_right('alice', 'Feuille1', 'lecture')
    got = alice.right('alice', 'Feuille1')
    assert got == 'écriture', f"C33 : avant livraison, le droit affiché pour alice chez elle doit rester 'écriture', obtenu {got!r}"
    assert alice.alerts()[alerts_before:] == [], 'C33 : aucune alerte attendue chez alice'
