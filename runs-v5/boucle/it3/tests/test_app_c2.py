"""Tests rouges — compléments C05..C08 de la sonde P12 (lecture d'un RC).

Chaque test cite l'assertion qu'il protège dans son nom.
"""
import json
import app

def _fait_vide_ou_absent(fait):
    return fait['statut'] == 'non trouvé' and fait['valeurs'] == [] and (fait['conflit'] is False)
PAGES_C05 = ["RÈGLEMENT DE LA CONSULTATION\nObjet : travaux de réfection de la toiture du gymnase municipal.\nAllotissement : le marché est passé en lot unique.\nCritères d'attribution :\n1. Mérite technique : 40 %\n2. Prix de l'offre : 60 %\n"]

def test_C05_lot_unique_sans_numero_lot_critere_vaut_ce_lot_sans_numero():
    d = app.analyser(PAGES_C05)
    criteres = d['criteres']
    assert criteres['statut'] == 'trouvé', f'critères attendus trouvés, obtenu {criteres!r}'
    libelles = [c['libelle'] for c in criteres['liste']]
    assert libelles == ['Mérite technique', "Prix de l'offre"], f"""critères attendus ['Mérite technique', "Prix de l'offre"], obtenu {libelles!r}"""
    for c in criteres['liste']:
        lot = c['lot']
        attendu = {'statut': 'trouvé', 'valeurs': [{'valeur': None, 'pages': [1]}], 'conflit': False}
        assert lot == attendu, f"C05 : lot critère de {c['libelle']!r} attendu {attendu!r} (lot unique sans numéro), obtenu {lot!r}"

def test_C05_lot_unique_sans_numero_aucun_numero_invente_ni_tous_les_lots():
    pages = ['Commune de Saint-Aubin — Règlement de la consultation\nObjet du marché : fourniture de mobilier scolaire.\n', "ARTICLE 2 — DÉCOMPOSITION\nLe présent marché n'est pas alloti.\nARTICLE 7 — JUGEMENT DES OFFRES\nLes offres seront jugées selon les critères suivants :\n- Valeur technique : 55 %\n- Prix : 45 %\n"]
    d = app.analyser(pages)
    assert d['criteres']['statut'] == 'trouvé', f"critères attendus trouvés, obtenu {d['criteres']!r}"
    assert len(d['criteres']['liste']) == 2, f"2 critères attendus, obtenu {d['criteres']['liste']!r}"
    for c in d['criteres']['liste']:
        lot = c['lot']
        assert lot['statut'] == 'trouvé', f"C05 : lot critère attendu trouvé pour {c['libelle']!r}, obtenu {lot!r}"
        valeurs = [v['valeur'] for v in lot['valeurs']]
        assert valeurs == [None], f"C05 : seule valeur attendue None (lot unique sans numéro), ni numéro inventé ni 'tous les lots' ; obtenu {valeurs!r}"
        assert lot['conflit'] is False, f'C05 : aucun conflit attendu, obtenu {lot!r}'
    json.dumps(d)

def test_C06_lot_unique_sans_numero_ni_intitule_un_seul_lot_vide():
    d = app.analyser(PAGES_C05)
    attendu = [{'numero': None, 'intitules': [], 'pages': [1], 'conflit': False}]
    assert d['lots']['statut'] == 'trouvé', f"lots attendus trouvés, obtenu {d['lots']!r}"
    assert d['lots']['liste'] == attendu, f"C06 : attendu {attendu!r}, obtenu {d['lots']['liste']!r}"

def test_C06_lot_unique_declare_page_2_page_valeur_est_2():
    pages = ['DÉPARTEMENT DU CHER\nRÈGLEMENT DE LA CONSULTATION\nObjet : entretien des espaces verts des collèges.\n', 'Article 1.3 — Allotissement\nLe marché est traité en lot unique, les prestations ne pouvant être dissociées.\n']
    d = app.analyser(pages)
    attendu = [{'numero': None, 'intitules': [], 'pages': [2], 'conflit': False}]
    assert d['lots']['statut'] == 'trouvé', f"lots attendus trouvés, obtenu {d['lots']!r}"
    assert d['lots']['liste'] == attendu, f"C06 : un seul lot sans numéro ni intitulé, page 2 ; attendu {attendu!r}, obtenu {d['lots']['liste']!r}"

def test_C07_criteres_points_sous_criteres_pourcentages_deux_pages():
    pages = ["ARTICLE 6 — CRITÈRES D'ATTRIBUTION\n1. Valeur technique : 60 points\n2. Prix : 40 points\n", "Détail du critère Valeur technique :\n1.1 Méthodologie d'intervention : 70 %\n1.2 Moyens humains affectés : 30 %\n"]
    d = app.analyser(pages)
    tp = d['type_ponderation']
    attendu = {'statut': 'trouvé', 'valeurs': [{'valeur': 'points', 'pages': [1]}], 'conflit': False}
    assert tp == attendu, f'C07 : type pondération attendu {attendu!r}, obtenu {tp!r}'

def test_C07_criteres_points_sous_criteres_pourcentages_meme_page_plus_autre_page_en_points():
    pages = ['JUGEMENT DES OFFRES\nCritère n°1 — Valeur technique : 50 points, décomposée comme suit :\n  a) Organisation du chantier : 60 %\n  b) Références similaires : 40 %\nCritère n°2 — Prix des prestations : 30 points\n', "Suite des critères :\nCritère n°3 — Délai d'exécution : 20 points\n"]
    d = app.analyser(pages)
    tp = d['type_ponderation']
    attendu = {'statut': 'trouvé', 'valeurs': [{'valeur': 'points', 'pages': [1, 2]}], 'conflit': False}
    assert tp == attendu, f'C07 : type pondération attendu {attendu!r}, obtenu {tp!r}'

def test_C08_mapa_dans_reference_meme_page_seule_procedure_nommee_sans_conflit():
    pages = ["Référence de la consultation : 2026-MAPA-71\nProcédure de passation : la présente consultation est passée selon la procédure d'appel d'offres restreint, en application du code de la commande publique.\n"]
    d = app.analyser(pages)
    attendu = {'statut': 'trouvé', 'valeurs': [{'valeur': "appel d'offres restreint", 'pages': [1]}], 'conflit': False}
    assert d['procedure'] == attendu, f"C08 : procédure attendue {attendu!r}, obtenu {d['procedure']!r}"
