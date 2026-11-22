"""Tests de non-régression — sonde P12, lot 4.

Chaque test reproduit un cas où une implémentation passant les tests existants
s'est trompée, et vérifie le comportement exigé par l'assertion citée.
"""
import app

def _valeurs(fait):
    return [v['valeur'] for v in fait['valeurs']]

def _piece(dossier, prefixe):
    trouvees = [p for p in dossier['pieces']['liste'] if p['nom'].startswith(prefixe)]
    assert trouvees, f"pièce commençant par {prefixe!r} attendue ; pièces obtenues : {[p['nom'] for p in dossier['pieces']['liste']]}"
    return trouvees[0]

def _critere(dossier, libelle):
    trouves = [c for c in dossier['criteres']['liste'] if c['libelle'] == libelle]
    assert trouves, f"critère {libelle!r} attendu ; critères obtenus : {[c['libelle'] for c in dossier['criteres']['liste']]}"
    return trouves[0]
PAGES_CAS1 = ["CENTRE HOSPITALIER DE MONTCRESSAC\n\nMARCHÉ PUBLIC DE TRAVAUX\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Rénovation énergétique de la mairie de Montcressac\nRéférence : 2026-TX-34\n\nDate et heure limites de réception des offres : 28/08/2026 à 12h00\n\nArticle 1 : Objet de la consultation\n\nLa présente consultation concerne : Rénovation énergétique de la mairie de Montcressac.\nLes travaux sont répartis en 2 lots :\n  Lot 01 – Isolation thermique par l'extérieur\n  - Lot 02 : Menuiseries\nLes candidats peuvent présenter une offre pour un ou plusieurs lots.\n\nArticle 2 : Procédure\n\nLa présente consultation est passée selon la appel d'offres ouvert.\n\nArticle 4 : Variantes et validité des offres\n\nLes variantes sont autorisées.\nDélai de validité des offres : 120 jours.\n\nARTICLE 6 – CONTENU DU DOSSIER À REMETTRE\n\nLes candidats remettent un dossier comprenant les pièces suivantes, datées et signées :\n\n1) Au titre de la candidature :\n  - Liste des travaux exécutés au cours des cinq dernières années\n  - Déclaration indiquant les effectifs moyens annuels du candidat\n  - Lettre de candidature (formulaire DC1) ou DUME\n\nPièces de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Détail quantitatif estimatif (DQE)\n  - Décomposition du prix global et forfaitaire (DPGF)\n\nRC – 1/2\n", "  - Attestation de visite\n  - Mémoire technique, limité à 25 pages\n\nLe candidat auquel il est envisagé d'attribuer le marché produira dans un délai de 8 jours :\n  - Attestation URSSAF de vigilance de moins de six mois\n\nArticle 7 : Critères d'attribution\n\nCritère n° 1 : Prix de l'offre (pondération : 40 %)\nCritère n° 2 : Qualité technique de l'offre (pondération : 50 %)\nCritère n° 3 : Performances en matière d'insertion professionnelle (pondération : 10 %)\n\nARTICLE 8 – CONDITIONS D'ENVOI ET DE REMISE DES OFFRES\n\nLes offres sont transmises par voie électronique.\n\nRC – 2/2\n"]

def test_A15_reg_liste_de_pieces_continuee_en_haut_de_page_suivante():
    d = app.analyser(PAGES_CAS1)
    for prefixe in ('Attestation de visite', 'Mémoire technique'):
        p = _piece(d, prefixe)
        assert p['pages'] == [2], f"{prefixe}: pages attendues [2], obtenu {p['pages']}"
        assert _valeurs(p['phase']) == ['offre'], f"{prefixe}: la liste de l'offre continue page 2 sans nouveau titre, phase attendue ['offre'], obtenu {p['phase']}"
    for prefixe in ("Acte d'engagement", 'Détail quantitatif estimatif', 'Décomposition du prix global'):
        assert _valeurs(_piece(d, prefixe)['phase']) == ['offre']
    urssaf = _piece(d, 'Attestation URSSAF')
    assert _valeurs(urssaf['phase']) == ['attributaire'], f"URSSAF: phase attendue ['attributaire'], obtenu {urssaf['phase']}"
PAGES_CAS2 = ["CENTRE HOSPITALIER DE HAUTE-RIVE\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Construction d'un gymnase de Haute-Rive\n\nDate et heure limites de réception des offres : jeudi 15 octobre 2026 à 12h00\n\nArticle 1 : Objet de la consultation\n\nLes travaux sont répartis en 4 lots :\n  Lot n° 1 : Terrassement - VRD\n  Lot n° 02 : Gros œuvre\n  Lot 3 – Charpente métallique\n  Lot n° 4 : Étanchéité\nLes candidats peuvent présenter une offre pour un ou plusieurs lots.\n\nArticle 2 : Procédure\n\nLa présente consultation est passée selon la procédure adaptée.\n\nARTICLE 6 – CRITÈRES D'ATTRIBUTION\n\nLe jugement des offres sera effectué selon les critères pondérés suivants :\n\nPour les lots n° 1, 02, 3 :\nCritère n° 1 : Qualité technique de l'offre (50%)\nCritère n° 2 : Prix (50%)\n\nPour le lot n° 4 :\nCritères | Pondération\n1. Mérite technique | pondération : 60 %\n2. Prix de l'offre | pondération : 30 %\n3. Délai d'exécution | pondération : 10 %\n\n\nARTICLE 7 – MODALITÉS DE REMISE DES PLIS\n\nLes offres sont transmises par voie électronique.\n\nRC – 1/1\n"]

def test_A160_reg_criteres_reserves_au_lot_4_ont_lot_critere_4():
    d = app.analyser(PAGES_CAS2)
    for libelle, poids in (('Mérite technique', 60), ("Prix de l'offre", 30), ("Délai d'exécution", 10)):
        c = _critere(d, libelle)
        assert c['lot']['statut'] == 'trouvé', f"{libelle}: lot critère attendu trouvé, obtenu {c['lot']}"
        assert _valeurs(c['lot']) == [4], f"{libelle}: critère réservé au lot n° 4, lot critère attendu [4], obtenu {_valeurs(c['lot'])}"
        assert [v['valeur'] for v in c['ponderation']['valeurs']] == [poids], f"{libelle}: pondération attendue [{poids}], obtenu {c['ponderation']}"
    for libelle in ("Qualité technique de l'offre", 'Prix'):
        assert 4 not in _valeurs(_critere(d, libelle)['lot']), f'{libelle}: ne concerne pas le lot 4'
PAGE_GARDE_LLASSERES = "         RÈGLEMENT DE LA CONSULTATION\n                                     (R.C.)\n\n\n             Travaux de restauration du bâti en pierre sèche\n              et de valorisation du site pastoral de Llasseres\n                 dans le cadre du projet POCTEFA PETRA.\n\n\n\n                       Lot unique n°01 — Pierres sèches\n          Communes de Taurinya et Clara-Villerach (Pyrénées-Orientales)\n\n\n\n\nMaîtrise d'ouvrage : Syndicat mixte du Parc naturel régional des Pyrénées catalanes\n\n\n\n                Date et heure limites de réception des offres\n                             Le 28 août 2026 à 8h00\n\n\n\n\n                                         1\n\x0c"
PAGE_SOMMAIRE_LLASSERES = 'SOMMAIRE\nArticle 1 — Objet et étendue de la consultation ........................ 3\n   1.3 — Décomposition de la consultation .............................. 3\nArticle 6 — Modifications de détail au dossier de consultation ......... 4\nArticle 8 — Demande de renseignements ................................. 4\n                                         2\n\x0c'
PAGE_LOT_LLASSERES = 'Article 1 — Objet et étendue de la consultation\n\n1.3 — Décomposition de la consultation\nLa consultation est traitée en lot unique :\nLot n°01 — Pierres sèches\n\n                                         3\n\x0c'
PAGE_MODIFS_LLASSERES = "Article 6 — Modifications de détail au dossier de consultation\n\nLe maître d'ouvrage se réserve le droit d'apporter, au plus tard 10 jours avant la date limite fixée pour la réception des offres, des modifications de détail au dossier de consultation.\n\n                                         4\n\x0c"

def test_A70_reg_delai_questions_en_jours_avant_remise():
    page_questions = 'Article 8 — Demande de renseignements\n\n8.1 — Renseignements complémentaires\nPour obtenir tous les renseignements complémentaires qui leur seraient nécessaires, les candidats devront faire parvenir une demande écrite sur la plateforme au plus tard 6 jours avant la date limite de remise des offres.\n\n                                         5\n\x0c'
    pages = [PAGE_GARDE_LLASSERES, PAGE_SOMMAIRE_LLASSERES, PAGE_LOT_LLASSERES, PAGE_MODIFS_LLASSERES, page_questions]
    d = app.analyser(pages)
    fq = d['date_questions']
    assert fq['statut'] == 'trouvé', f'date questions attendue trouvée, obtenu {fq}'
    assert fq['valeurs'] == [{'valeur': '6 jours avant la date limite de remise des offres', 'pages': [5]}], f"délai attendu tel qu'écrit, page 5 ; obtenu {fq['valeurs']}"
    assert fq['conflit'] is False

def test_A67_reg_titre_au_sommaire_et_delai_de_modification_ne_sont_pas_une_date_questions():
    pages = [PAGE_GARDE_LLASSERES, PAGE_SOMMAIRE_LLASSERES, PAGE_LOT_LLASSERES, PAGE_MODIFS_LLASSERES]
    d = app.analyser(pages)
    fq = d['date_questions']
    assert fq == {'statut': 'non trouvé', 'valeurs': [], 'conflit': False}, f"aucune page n'indique de limite d'envoi des questions ; obtenu {fq}"

def test_A60_reg_heure_8h00_sur_page_de_garde_sur_deux_lignes():
    pages = [PAGE_GARDE_LLASSERES, PAGE_SOMMAIRE_LLASSERES, PAGE_LOT_LLASSERES]
    d = app.analyser(pages)
    fh = d['heure_limite']
    assert fh['statut'] == 'trouvé', f'heure limite attendue trouvée, obtenu {fh}'
    assert {'valeur': '08:00', 'pages': [1]} in fh['valeurs'], f"heure « 8h00 » page 1 attendue au format 08:00 ; obtenu {fh['valeurs']}"
    assert _valeurs(d['date_limite']) == ['28/08/2026'], f"date limite attendue ['28/08/2026'], obtenu {d['date_limite']}"
PAGE_GARDE_SM = 'Pouvoir adjudicateur :\n         Commune de Sainte-Marguerite-sur-Mer\n\n\n             Dossier de Consultation des Entreprises\n\n      Assainissement des façades de l’église Sainte-Marguerite\n\n                 REGLEMENT DE CONSULTATION\n\n\n                        DATE ET HEURE DE REMISE DES OFFRES\n                             Le lundi 23 février 2026 à 14h\n\x0c'
PAGE_LOT_SM = 'ARTICLE 3 - ETENDUE DE LA CONSULTATION\n\nLe marché est décomposé en 1 lot unique :\n\n                          Lot(s)                                              Désignation\n                         Lot n°1                           Maçonnerie\n\x0c'
PAGE_CRITERES_POINTS_SM = "ARTICLE 6 - JUGEMENT DES OFFRES\n\nLes critères retenus pour le jugement des offres sont pondérés de la manière suivante :\n\n1 - Valeur technique : 60 points\n   - Méthodologie d'intervention : 30 points\n   - Moyens humains et matériels affectés au chantier : 30 points\n2 - Prix des prestations : 40 points\n\nBarème d'attribution des points de la valeur technique :\n   Très satisfaisant : 100 % des points\n   Satisfaisant : 75 % des points\n   Peu satisfaisant : 50 % des points\n   Insuffisant : 0 % des points\n\x0c"
PAGE_CLASSEMENT_SM = 'ARTICLE 7 - ATTRIBUTION\n\nAprès analyse des offres, le pouvoir adjudicateur procède au classement des candidats. Le candidat classé en premier sera invité à produire les certificats demandés.\n\x0c'

def test_A24_reg_mention_du_classement_des_candidats_n_est_pas_un_type_ponderation():
    pages = [PAGE_GARDE_SM, PAGE_LOT_SM, PAGE_CRITERES_POINTS_SM, PAGE_CLASSEMENT_SM]
    d = app.analyser(pages)
    tp = d['type_ponderation']
    assert 'classement' not in _valeurs(tp), f'la page 4 ne parle que du classement des candidats ; obtenu {tp}'
    assert tp['statut'] == 'trouvé' and _valeurs(tp) == ['points'], f"type pondération attendu ['points'], obtenu {tp}"
    assert tp['valeurs'][0]['pages'] == [3], f"page valeur attendue [3], obtenu {tp['valeurs']}"
    assert tp['conflit'] is False

def test_A24_reg_pourcentages_du_bareme_de_notation_ne_masquent_pas_les_points():
    pages = [PAGE_GARDE_SM, PAGE_LOT_SM, PAGE_CRITERES_POINTS_SM]
    d = app.analyser(pages)
    tp = d['type_ponderation']
    assert tp['statut'] == 'trouvé', f'critères pondérés en 60/40 points : type pondération attendu trouvé, obtenu {tp}'
    assert tp['valeurs'] == [{'valeur': 'points', 'pages': [3]}], f"type pondération attendu points page 3 seul, obtenu {tp['valeurs']}"
    assert tp['conflit'] is False

def test_A10_reg_date_de_visite_en_lettres_sous_rubrique_visite_obligatoire():
    page_visite = 'ARTICLE 5 - VISITE\n\nVisite obligatoire\nLe lundi 02 février 2026 à 10h\nRendez-vous devant le portail de l’église.\n\x0c'
    pages = [PAGE_GARDE_SM, PAGE_LOT_SM, page_visite]
    d = app.analyser(pages)
    dv = d['dates_visite']
    assert dv['statut'] == 'trouvé', f'date de visite attendue trouvée, obtenu {dv}'
    assert {'valeur': '02/02/2026', 'pages': [3]} in dv['valeurs'], f"date de visite 02/02/2026 page 3 attendue, obtenu {dv['valeurs']}"
    assert '23/02/2026' not in _valeurs(dv), f"la date limite de remise n'est pas une date de visite ; obtenu {dv['valeurs']}"
    assert dv['conflit'] is False
