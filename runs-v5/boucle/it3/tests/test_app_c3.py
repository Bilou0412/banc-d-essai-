"""Tests rouges — ajouts C09 à C11 (sonde P12, lecture d'un RC).

Note pour C10 : l'assertion A35 compare la somme des pondérations des
sous-critères à celle du critère parent. Des sous-critères exprimés en
pourcentages *du critère* et totalisant 100 % représentent exactement la
pondération du parent (100 % de 55 points = 55 points) : C10 ne contredit pas A35.
"""
import json
import pytest
import app

def _sections_pour(dossier, mot):
    mot = mot.lower()
    return [s for s in dossier['plan'] if mot in (s.get('critere') or '').lower() or mot in (s.get('titre') or '').lower()]

def _criteres_libelles(dossier):
    return [c['libelle'] for c in dossier['criteres']['liste']]

def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)
PAGE_GARDE = 'RÈGLEMENT DE LA CONSULTATION\nCommune de Saint-Amand – Réhabilitation du groupe scolaire\nProcédure adaptée en application du code de la commande publique.\n'
RC_ENV_POURCENTAGES = [PAGE_GARDE, "Article 7 – Jugement des offres\nLes offres seront jugées selon les critères d'attribution suivants :\n1. Prix des prestations : 50 %\n2. Valeur technique : 40 %\n3. Performances environnementales : 10 %\n"]
RC_ENV_POINTS = [PAGE_GARDE, "ARTICLE 8 : CRITÈRES DE JUGEMENT DES OFFRES\nLe jugement des offres sera effectué selon les critères ci-dessous :\n- Prix : 60 points\n- Valeur technique de l'offre : 30 points\n- Performances en matière de protection de l'environnement : 10 points\n"]

@pytest.mark.parametrize('pages', [RC_ENV_POURCENTAGES, RC_ENV_POINTS], ids=['pourcentages', 'points'])
def test_C09_critere_environnemental_na_pas_de_section(pages):
    d = app.analyser(pages)
    libelles = [l.lower() for l in _criteres_libelles(d)]
    assert any(('environnement' in l for l in libelles)), f"précondition (A21) : le critère environnemental devait figurer dans l'arbre des critères ; obtenu {libelles}"
    env = _sections_pour(d, 'environnement')
    assert env == [], f"C09 : un critère qui n'est ni prix ni valeur technique ne doit avoir aucune section dans le plan ; sections obtenues :\n{_dump(env)}"

@pytest.mark.parametrize('pages', [RC_ENV_POURCENTAGES, RC_ENV_POINTS], ids=['pourcentages', 'points'])
def test_C09_valeur_technique_garde_sa_section_a_cote_du_critere_environnemental(pages):
    d = app.analyser(pages)
    vt = _sections_pour(d, 'valeur technique')
    assert len(vt) == 1, f"C09/A27 : le plan doit contenir exactement une section pour la valeur technique (sans sous-critères) ; plan obtenu :\n{_dump(d['plan'])}"
    assert _sections_pour(d, 'prix') == [], f"A28 : aucune section pour le prix ; plan obtenu :\n{_dump(d['plan'])}"
    assert len(d['plan']) == 1, f"C09 : seule la valeur technique donne une section ; plan obtenu :\n{_dump(d['plan'])}"

@pytest.mark.parametrize('pages', [RC_ENV_POURCENTAGES, RC_ENV_POINTS], ids=['pourcentages', 'points'])
def test_C09_critere_environnemental_sans_section_ne_declenche_pas_d_alerte(pages):
    d = app.analyser(pages)
    alertes = [a for a in d['controle']['alertes'] if a.get('type') == 'critère sans section']
    assert alertes == [], f"C09 : l'absence de section pour un critère non technique n'est pas une anomalie ; alertes « critère sans section » obtenues : {alertes}"
    assert app.controler(d) == d['controle']['alertes'], f"interface : controler(d) doit rendre d['controle']['alertes'] ; obtenu {app.controler(d)} contre {d['controle']['alertes']}"
RC_POINTS_SOUS_POURCENTAGES = [PAGE_GARDE, "Article 6 – Critères d'attribution\nLes offres seront classées selon les critères pondérés suivants :\n1. Valeur technique : 55 points, appréciée au regard des sous-critères suivants :\n   1.1 Méthodologie d'exécution des travaux : 60 %\n   1.2 Moyens humains et matériels affectés au chantier : 40 %\n2. Prix des prestations : 45 points\n"]
RC_POINTS_SOUS_POURCENTAGES_DEUX_PAGES = [PAGE_GARDE, "Article 6 – Critères d'attribution\nLes critères retenus pour le jugement des offres sont :\n- Valeur technique : 55 points\n- Prix : 45 points\n", "Article 6.1 – Détail du critère valeur technique\nLe critère valeur technique est décomposé comme suit :\n- Organisation du chantier et planning : 50 %\n- Qualité des matériaux proposés : 30 %\n- Mesures de sécurité et d'hygiène : 20 %\n"]
PAGE_NON_DOCUMENTS = "Article 2 – Décomposition du marché\n- Décomposition en lots :\nLe marché n'est pas alloti.\n- Décomposition en tranches :\nIl n'est pas prévu de tranches.\nArticle 3 – Présentation des candidatures\n- Il est interdit de présenter plusieurs offres en agissant à la fois en qualité de candidat individuel et de membre d'un groupement.\n- Un même opérateur ne peut être mandataire de plus d'un groupement.\nArticle 4 – Maîtrise d'œuvre\n- Cabinet Durand Architectes\n- 12 rue des Lilas\n- 69003 Lyon\n"
PAGE_PIECES = "Article 5 – Pièces à remettre par le candidat\nLe dossier à remettre par chaque candidat comprendra les pièces suivantes :\n- Lettre de candidature (DC1)\n- Déclaration du candidat (DC2)\n- Mémoire technique\n- Acte d'engagement\n"
MOTS_NON_DOCUMENTS = ['décomposition', 'tranche', 'interdit', 'mandataire', 'durand', 'rue des lilas', '69003', 'lyon']

def _noms_pieces(d):
    return [p['nom'] for p in d['pieces']['liste']]

@pytest.mark.parametrize('mot', MOTS_NON_DOCUMENTS)
def test_C11_enumeration_non_documentaire_absente_des_pieces(mot):
    d = app.analyser([PAGE_GARDE, PAGE_NON_DOCUMENTS, PAGE_PIECES])
    noms = _noms_pieces(d)
    assert any(('dc1' in n.lower() or 'lettre de candidature' in n.lower() for n in noms)), f'précondition (A15) : la lettre de candidature (DC1) doit être listée parmi les pièces ; obtenu {noms}'
    fautifs = [n for n in noms if mot in n.lower()]
    assert fautifs == [], f'C11 : une puce qui ne désigne aucun document (« {mot} ») ne doit pas être listée comme pièce ; pièces obtenues : {noms}'

def test_C11_seules_enumerations_non_documentaires_donnent_pieces_non_trouvees():
    d = app.analyser([PAGE_GARDE, PAGE_NON_DOCUMENTS])
    assert d['pieces']['statut'] == 'non trouvé' and d['pieces']['liste'] == [], f"C11/A119 : sans énumération de pièces à remettre, des puces de rubrique, d'adresse ou d'interdiction ne doivent produire aucune pièce ; obtenu :\n{_dump(d['pieces'])}"
