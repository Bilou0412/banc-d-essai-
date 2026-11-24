"""Tests rouges — ajouts C12, C13 (sonde P12, lecture d'un RC)."""
import json
import app
PAGE_LOTS = 'RÈGLEMENT DE LA CONSULTATION\nMarché public de travaux — Procédure adaptée\nARTICLE 2 – ALLOTISSEMENT\nLes travaux sont répartis en 4 lots :\nLot 1 : Gros œuvre\nLot 2 : Charpente\nLot 3 : Couverture\nLot 4 : Électricité\n'

def _pages_c12(lot4_lignes):
    page_criteres = 'ARTICLE 8 – JUGEMENT DES OFFRES\nPour les lots 1 à 3, les offres seront jugées selon les critères pondérés suivants :\n1. Valeur technique : 60 %\n2. Prix des prestations : 40 %\n\nPour le lot 4, les offres seront jugées selon les critères pondérés suivants :\n' + lot4_lignes
    return [PAGE_LOTS, page_criteres]
LOT4_OK = "1. Prix des prestations : 50 %\n2. Valeur technique : 30 %\n3. Délai d'exécution : 20 %\n"
LOT4_KO = "1. Prix des prestations : 50 %\n2. Valeur technique : 30 %\n3. Délai d'exécution : 10 %\n"

def _alertes_total(dossier):
    return [a for a in dossier['controle']['alertes'] if a.get('type') == 'total différent de 100 %']

def test_C12_un_lot_a_90_pourcent_declenche_encore_l_alerte_total():
    d = app.analyser(_pages_c12(LOT4_KO))
    alertes = _alertes_total(d)
    assert len(alertes) >= 1, f"C12/A36 : le jeu de critères du lot 4 totalise 90 %, l'alerte « total différent de 100 % » est attendue ; alertes obtenues : {d['controle']['alertes']}"
PAGES_C13 = ['RÈGLEMENT DE LA CONSULTATION\nFourniture de mobilier scolaire\nDate et heure limites de réception des offres : le 15 mars 2027 à 8h00\n', "ARTICLE 5 – CONDITIONS D'ENVOI DES OFFRES\nLes offres sont transmises par voie électronique sur le profil d'acheteur.\nElles devront parvenir avant les date et heure limites indiquées en page de garde.\nLes plis reçus après ces date et heure ne seront pas ouverts.\n"]

def test_C13_renvoi_sans_heure_ne_cree_ni_valeur_ni_page_ni_conflit():
    d = app.analyser(PAGES_C13)
    h = d['heure_limite']
    attendu = {'statut': 'trouvé', 'valeurs': [{'valeur': '08:00', 'pages': [1]}], 'conflit': False}
    assert h == attendu, f"C13 : heure limite attendue {attendu} (seule la page 1 écrit l'heure, la page 2 ne fait qu'y renvoyer), obtenue {h}"

def test_C13_renvoi_place_avant_la_page_qui_ecrit_l_heure():
    pages = [PAGES_C13[1], PAGES_C13[0]]
    d = app.analyser(pages)
    h = d['heure_limite']
    attendu = {'statut': 'trouvé', 'valeurs': [{'valeur': '08:00', 'pages': [2]}], 'conflit': False}
    assert h == attendu, f"C13 : heure limite attendue {attendu} (le renvoi en page 1 n'écrit pas d'heure), obtenue {h}"
