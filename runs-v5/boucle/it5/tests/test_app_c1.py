"""Tests rouges — compléments C01..C04 (sonde P12, lecture d'un RC).

Interface utilisée : app.analyser(pages) uniquement.
"""
import app
PAGE_POURCENTAGES_ET_POINTS = "ARTICLE 7 - JUGEMENT DES OFFRES\nLes offres seront jugées selon les critères pondérés suivants :\n1. Valeur technique : 60 %\n   1.1 Méthodologie d'intervention : 35 points\n   1.2 Moyens humains et matériels affectés au chantier : 25 points\n2. Prix des prestations : 40 %\n"

def test_C01_pourcentages_criteres_points_sous_criteres_pas_de_conflit_type():
    d = app.analyser(['RÈGLEMENT DE LA CONSULTATION\nTravaux de voirie 2026', PAGE_POURCENTAGES_ET_POINTS])
    tp = d['type_ponderation']
    assert tp['statut'] == 'trouvé', f'C01 : type pondération attendu « trouvé » (critères en %), obtenu {tp!r}'
    assert len(tp['valeurs']) == 1, f"C01 : une seule valeur attendue pour le type pondération quand les sous-critères sont en points sous des critères en %, obtenu {tp['valeurs']!r}"
    assert tp['conflit'] is False, f'C01 : aucun conflit attendu sur le type pondération, obtenu {tp!r}'

def test_C01_variante_mise_en_page_tableau_pas_de_conflit_type():
    page = "Critères de jugement des offres\nCritère | Pondération\nQualité technique de l'offre | 55%\n  - Organisation du chantier | 30 pts\n  - Gestion des déchets | 25 pts\nPrix | 45%\n"
    d = app.analyser([page])
    tp = d['type_ponderation']
    assert tp['statut'] == 'trouvé' and len(tp['valeurs']) == 1 and (tp['conflit'] is False), f'C01 : attendu un type pondération unique sans conflit, obtenu {tp!r}'

def _alertes_total(d):
    return [a for a in d['controle']['alertes'] if a['type'] == 'total différent de 100 %']

def test_C02_total_105_pourcent_alerte_sur_objet_criteres():
    page = "Article 9 – Critères d'attribution\nLe jugement des offres sera effectué selon les critères suivants :\n- Valeur technique : 40 %\n- Prix : 65 %\n"
    d = app.analyser([page])
    obtenu = _alertes_total(d)
    attendu = [{'type': 'total différent de 100 %', 'objet': 'critères'}]
    assert obtenu == attendu, f'C02 : attendu {attendu!r}, obtenu {obtenu!r}'

def test_C02_total_80_pourcent_alerte_sur_objet_criteres():
    page = 'CRITÈRES DE SÉLECTION DES OFFRES\n1) Prix des prestations : 50 pour cent\n2) Valeur technique : 30 %\n'
    d = app.analyser([page])
    obtenu = _alertes_total(d)
    attendu = [{'type': 'total différent de 100 %', 'objet': 'critères'}]
    assert obtenu == attendu, f'C02 : attendu {attendu!r}, obtenu {obtenu!r}'

def test_C03_validite_une_seule_page_pas_de_conflit():
    pages = ['RÈGLEMENT DE LA CONSULTATION\nFourniture de mobilier scolaire', 'Article 5 - Délai de validité des offres\nLe délai de validité des offres est fixé à 4 mois à compter de la date limite de réception des offres.', 'Article 6 - Présentation des offres\nLes documents sont rédigés en français.']
    d = app.analyser(pages)
    v = d['validite_offres']
    attendu = [{'valeur': {'nombre': 4, 'unite': 'mois'}, 'pages': [2]}]
    assert v['statut'] == 'trouvé', f'C03 : validité attendue « trouvé », obtenu {v!r}'
    assert v['valeurs'] == attendu, f"C03 : valeurs attendues {attendu!r}, obtenu {v['valeurs']!r}"
    assert v['conflit'] is False, f'C03 : aucun conflit attendu, obtenu {v!r}'

def test_C04_exclusion_papier_ne_compte_pas_comme_mode_remise():
    pages = ["Article 8 - Modalités de remise des offres\nLes offres sont transmises exclusivement par voie dématérialisée sur le profil d'acheteur.", 'Article 9 - Dispositions diverses\nAucune offre papier ne sera acceptée.']
    d = app.analyser(pages)
    m = d['mode_remise']
    attendu = [{'valeur': 'électronique', 'pages': [1]}]
    assert m['valeurs'] == attendu, f"C04 : attendu {attendu!r} (la page 2 n'exclut qu'un mode), obtenu {m['valeurs']!r}"
    assert m['conflit'] is False, f'C04 : aucun conflit attendu, obtenu {m!r}'

def test_C04_ordre_inverse_exclusion_en_premiere_page():
    pages = ['Les plis transmis sur support papier ne seront pas admis.', "La remise des offres se fait par voie électronique via la plateforme de dématérialisation de l'acheteur."]
    d = app.analyser(pages)
    m = d['mode_remise']
    attendu = [{'valeur': 'électronique', 'pages': [2]}]
    assert m['valeurs'] == attendu, f"C04 : attendu {attendu!r}, obtenu {m['valeurs']!r}"
