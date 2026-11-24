"""
Tests rouges — sonde P12, deuxième attaque.

Même interface que tests/test_app.py (analyser, verifier, controler ; mêmes clés du dossier).
Cibles : entrées vides, numérotation des pages par index (pas par pied de page), répétition,
espaces insécables, fins de ligne CRLF, césures, tournures variées, pièges de proximité
(questions contre offres, « obligatoire » d'une pièce contre visite, négations), et un
vérificateur qui ne se contente pas d'une recherche de sous-chaîne.
"""

import copy
import json
import re

import pytest

import app

TROUVE = "trouvé"
NON_TROUVE = "non trouvé"


# ---------------------------------------------------------------- outils

def analyse(pages):
    pages = list(pages)
    d = app.analyser(list(pages))
    assert isinstance(d, dict), f"analyser doit rendre un dict, obtenu {type(d).__name__}"
    rejoue = json.loads(json.dumps(d, ensure_ascii=False))
    assert rejoue == d, "le dossier ne survit pas à un aller-retour JSON"
    assert app.analyser(list(pages)) == d, "analyser rend deux dossiers différents pour les mêmes pages"
    return d


def norm(s):
    s = s.replace("’", "'").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def vals(fait):
    return [v["valeur"] for v in fait["valeurs"]]


def un(fait, nom):
    assert fait["statut"] == TROUVE, f"{nom} : attendu « trouvé », obtenu {fait!r}"
    assert len(fait["valeurs"]) == 1, f"{nom} : attendu une seule valeur, obtenu {vals(fait)!r}"
    return fait["valeurs"][0]


def absent(fait, nom):
    assert fait["statut"] == NON_TROUVE, f"{nom} : attendu « non trouvé », obtenu {fait!r}"
    assert fait["valeurs"] == [], f"{nom} : un fait non trouvé ne porte aucune valeur, obtenu {fait['valeurs']!r}"


def fait_trouve(*couples):
    return {"statut": TROUVE,
            "valeurs": [{"valeur": v, "pages": list(p)} for v, p in couples],
            "conflit": False}


def lots(d):
    return d["lots"]["liste"]


def lot(d, numero):
    l = [x for x in lots(d) if x["numero"] == numero]
    assert len(l) == 1, f"lot {numero} : attendu une entrée, obtenu {lots(d)!r}"
    return l[0]


def intitules(lt):
    return [i["valeur"] for i in lt["intitules"]]


def pieces_avec(d, mot):
    return [x for x in d["pieces"]["liste"] if norm(mot) in norm(x["nom"])]


def piece(d, mot):
    l = pieces_avec(d, mot)
    assert len(l) == 1, (f"pièce « {mot} » : attendu exactement une pièce, obtenu "
                         f"{[x['nom'] for x in d['pieces']['liste']]!r}")
    return l[0]


def criteres(d):
    return d["criteres"]["liste"]


def libelles(d):
    return [c["libelle"] for c in criteres(d)]


def critere(d, debut):
    l = [c for c in criteres(d) if norm(c["libelle"]).startswith(norm(debut))]
    assert len(l) == 1, f"critère « {debut} » : attendu exactement un, obtenu {libelles(d)!r}"
    return l[0]


def sections_de(d, debut):
    return [s for s in d["plan"] if norm(s["critere"]).startswith(norm(debut))]


def types_alertes(d):
    return [a["type"] for a in d["controle"]["alertes"]]


FAITS = ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
         "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
         "type_ponderation"]


# ---------------------------------------------------------------- pages types

COUV = ("RÈGLEMENT DE LA CONSULTATION\n"
        "Pouvoir adjudicateur : Commune de Pontarlier\n"
        "Objet : réhabilitation thermique de l'école élémentaire Victor Hugo\n"
        "Le maître d'œuvre pilote l'opération pour le compte de la commune.\n"
        "Page 1 sur 6\n")

NEUTRE = ("ARTICLE 1 – OBJET DE LA CONSULTATION\n"
          "La présente consultation concerne des travaux d'isolation par l'extérieur, "
          "de remplacement des menuiseries et de mise en place d'une ventilation double flux.\n"
          "Les travaux se dérouleront pendant les vacances scolaires.\n"
          "Page 2 sur 6\n")

LOTS2 = ("ARTICLE 2 – ALLOTISSEMENT\n"
         "La consultation est décomposée en deux lots :\n"
         "Lot n°1 : Gros œuvre – maçonnerie\n"
         "Lot n°2 : Menuiseries extérieures\n"
         "Les candidats peuvent répondre à un ou plusieurs lots.\n")

DL = ("ARTICLE 11 – CONDITIONS DE REMISE DES OFFRES\n"
      "Date limite de réception des offres : 14/03/2025 à 12h00.\n")

VISITE = ("ARTICLE 10 – VISITE DES LIEUX\n"
          "Une visite du site est obligatoire. Deux créneaux sont proposés : "
          "le mardi 18 février 2025 à 10h00 ou le 25/02/2025 à 14h00.\n"
          "Une attestation de visite sera remise au candidat.\n")

PIECES = ("ARTICLE 5 – CONTENU DU DOSSIER À REMETTRE\n"
          "5.1 Pièces relatives à la candidature\n"
          "- Lettre de candidature (formulaire DC1) ou DUME ;\n"
          "- Déclaration du candidat (formulaire DC2) ;\n"
          "- Attestation d'assurance responsabilité civile professionnelle ;\n"
          "- Références de travaux similaires (facultatif).\n"
          "5.2 Pièces relatives à l'offre\n"
          "- Acte d'engagement (AE) complété et signé (obligatoire) ;\n"
          "- Mémoire technique ;\n"
          "- Bordereau des prix unitaires (BPU).\n"
          "5.3 Pièces à produire par le seul attributaire\n"
          "Le candidat auquel il est envisagé d'attribuer le marché produira :\n"
          "- Attestations de régularité fiscale et sociale ;\n"
          "- Extrait K-bis de moins de trois mois.\n")

CRIT_SIMPLE = ("ARTICLE 8 – JUGEMENT DES OFFRES\n"
               "Les offres sont jugées selon les critères suivants :\n"
               "1. Valeur technique : 60 %\n"
               "2. Prix : 40 %\n")

RAPPEL_SIMPLE = ("ANNEXE 2 – RAPPEL DES CRITÈRES D'ATTRIBUTION\n"
                 "1. Valeur technique : 60 %\n"
                 "2. Prix : 40 %\n")

CRIT_PCT = ("ARTICLE 7 - JUGEMENT DES OFFRES\n"
            "Le jugement des offres sera effectué selon les critères pondérés suivants :\n"
            "1. Valeur technique de l'offre : 60 %\n"
            "   1.1 Méthodologie d'exécution des travaux : 30 %\n"
            "   1.2 Moyens humains et matériels affectés au chantier : 20 %\n"
            "   1.3 Planning détaillé d'exécution : 10 %\n"
            "2. Prix des prestations : 40 %\n"
            "La note du critère prix est calculée selon la formule : Note = 40 x (Pmin / P).\n")

CRIT_POINTS = ("Article 9 – Critères d'attribution\n"
               "Les offres sont notées sur 100 points, répartis entre les critères suivants :\n"
               "Critère n°1 : Prix (40 points)\n"
               "Critère n°2 : Valeur technique (60 points), appréciée au regard des sous-critères suivants :\n"
               "  a) Méthodologie proposée (35 points)\n"
               "  b) Moyens affectés à l'opération (25 points)\n")

MODE_ELEC = ("ARTICLE 11 – CONDITIONS DE REMISE DES OFFRES\n"
             "Les offres sont transmises exclusivement par voie électronique sur le profil "
             "d'acheteur https://www.marches-securises.fr.\n")

PROC_ADAPTEE = ("ARTICLE 3 – PROCÉDURE\n"
                "La présente consultation est passée selon la procédure adaptée, en application "
                "de l'article R2123-1 du Code de la commande publique.\n")


def page_remise(texte):
    return "ARTICLE 11 – CONDITIONS DE REMISE DES OFFRES\n" + texte + "\n"


# ================================================================= ENTRÉES VIDES

@pytest.mark.parametrize("pages", [[], [""], ["   \n", "\n\n\t"]])
def test_A03_trou_aucune_page_ou_pages_vides(pages):
    d = analyse(pages)
    for cle in FAITS:
        absent(d[cle], cle)
        assert d[cle]["conflit"] is False, f"{cle} : aucun conflit sur un fait non trouvé"
    for cle in ["lots", "pieces", "criteres"]:
        assert d[cle]["statut"] == NON_TROUVE, f"{cle} : attendu non trouvé, obtenu {d[cle]!r}"
        assert d[cle]["liste"] == [], f"{cle} : obtenu {d[cle]!r}"
    assert d["plan"] == [], f"plan attendu vide, obtenu {d['plan']!r}"
    assert d["controle"]["alertes"] == [], f"aucune alerte attendue, obtenu {d['controle']!r}"


# ================================================================= NUMÉROTATION / RÉPÉTITION

def test_A57_numero_d_index_et_non_pied_de_page():
    d = analyse([COUV, DL + "Page 5 sur 6\n"])
    assert un(d["date_limite"], "date limite")["pages"] == [2], (
        f"la page est l'index dans la liste (2), pas le pied de page « 5 » ; obtenu {d['date_limite']!r}")


def test_A39_permutation_des_pages():
    d1 = analyse([COUV, DL])
    d2 = analyse([DL, COUV])
    assert un(d1["date_limite"], "date limite")["pages"] == [2]
    assert un(d2["date_limite"], "date limite")["pages"] == [1], f"obtenu {d2['date_limite']!r}"
    assert un(d2["heure_limite"], "heure limite")["pages"] == [1]


def test_A53_repetee_sur_cinquante_pages():
    d = analyse([DL] * 50)
    v = un(d["date_limite"], "date limite")
    assert v["valeur"] == "14/03/2025"
    assert v["pages"] == list(range(1, 51)), f"attendu les pages 1 à 50 en ordre croissant, obtenu {v['pages']!r}"
    assert d["date_limite"]["conflit"] is False


def test_A66_page_lointaine():
    d = analyse([NEUTRE] * 200 + [DL])
    assert un(d["heure_limite"], "heure limite")["pages"] == [201], f"obtenu {d['heure_limite']!r}"


# ================================================================= MISE EN PAGE

def test_A02_trou_cesure_de_ligne_dans_le_libelle():
    d = analyse([COUV, "ARTICLE 11\nDate limite de réception des\noffres : 14/03/2025 à 12h00.\n"])
    assert un(d["date_limite"], "date limite")["valeur"] == "14/03/2025", f"obtenu {d['date_limite']!r}"
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00", f"obtenu {d['heure_limite']!r}"


def test_A140_fins_de_ligne_crlf():
    pages = [p.replace("\n", "\r\n") for p in [COUV, DL, CRIT_PCT]]
    d = analyse(pages)
    assert libelles(d) == ["Valeur technique de l'offre", "Prix des prestations"], (
        f"aucun « \\r » ne doit rester dans les libellés ; obtenu {libelles(d)!r}")
    assert un(d["date_limite"], "date limite")["valeur"] == "14/03/2025"
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00"


def test_A52_espaces_insecables():
    page = page_remise("Date limite de réception des offres : vendredi 14 mars 2025 à 12 h 00.")
    d = analyse([COUV, page])
    assert un(d["date_limite"], "date limite")["valeur"] == "14/03/2025", f"obtenu {d['date_limite']!r}"
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00", f"obtenu {d['heure_limite']!r}"


def test_A144_espace_insecable_avant_pourcent():
    page = ("ARTICLE 8\nCritères de jugement :\n"
            "1. Valeur technique : 60 %\n"
            "2. Prix : 40 %\n")
    d = analyse([COUV, page])
    assert [norm(x) for x in libelles(d)] == ["valeur technique", "prix"], f"obtenu {libelles(d)!r}"
    assert un(critere(d, "valeur technique")["ponderation"], "p")["valeur"] == 60
    assert un(critere(d, "prix")["ponderation"], "p")["valeur"] == 40
    assert un(d["type_ponderation"], "type")["valeur"] == "pourcentage"


# ================================================================= DATE / HEURE / QUESTIONS

QO = page_remise("Date limite de réception des questions : 04/03/2025 à 17h00\n"
                 "Date limite de réception des offres : 14/03/2025 à 12h00.")


def test_A02_date_des_questions_n_est_pas_la_date_limite():
    d = analyse([COUV, QO])
    assert vals(d["date_limite"]) == ["14/03/2025"], f"obtenu {d['date_limite']!r}"
    assert d["date_limite"]["conflit"] is False


def test_A04_heure_des_questions_ignoree():
    d = analyse([COUV, QO])
    assert vals(d["heure_limite"]) == ["12:00"], f"obtenu {d['heure_limite']!r}"


def test_A06_date_limite_de_reception_des_questions():
    d = analyse([COUV, QO])
    assert vals(d["date_questions"]) == ["04/03/2025"], f"obtenu {d['date_questions']!r}"


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


@pytest.mark.parametrize("i", range(12))
def test_A51_chaque_mois(i):
    d = analyse([COUV, page_remise(f"Date limite de remise des offres : le 5 {MOIS[i]} 2026 à 12h00.")])
    assert un(d["date_limite"], "date limite")["valeur"] == f"05/{i + 1:02d}/2026"


@pytest.mark.parametrize("ecrit,attendu", [
    ("le 14 aout 2025", "14/08/2025"),
    ("le 3 fevrier 2025", "03/02/2025"),
    ("le 1 decembre 2025", "01/12/2025"),
])
def test_A51_trou_mois_sans_accent(ecrit, attendu):
    d = analyse([COUV, page_remise(f"Date limite de remise des offres : {ecrit} à 12h00.")])
    assert un(d["date_limite"], "date limite")["valeur"] == attendu


def test_A52_trou_annee_sur_deux_chiffres():
    d = analyse([COUV, page_remise("Date limite de remise des offres : 14/03/25 à 12h00.")])
    assert un(d["date_limite"], "date limite")["valeur"] == "14/03/2025", f"obtenu {d['date_limite']!r}"


def test_A02_jusqu_au():
    d = analyse([COUV, page_remise("Les plis pourront être déposés jusqu'au 14 mars 2025, 12h00.")])
    assert un(d["date_limite"], "date limite")["valeur"] == "14/03/2025", f"obtenu {d['date_limite']!r}"
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00", f"obtenu {d['heure_limite']!r}"


@pytest.mark.parametrize("ecrit,attendu", [("9h30", "09:30"), ("8 h 45", "08:45"), ("17h45", "17:45")])
def test_A60_heure_sur_un_ou_deux_chiffres(ecrit, attendu):
    d = analyse([COUV, page_remise(f"Date limite de réception des offres : 14/03/2025 à {ecrit}.")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == attendu


@pytest.mark.parametrize("ecrit", ["12h", "12 h", "12:00"])
def test_A60_trou_autres_notations(ecrit):
    d = analyse([COUV, page_remise(f"Date limite de réception des offres : 14/03/2025 à {ecrit}.")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00", f"obtenu {d['heure_limite']!r}"


def test_A61_midi():
    d = analyse([COUV, page_remise("Date limite de réception des offres : le 14 mars 2025 à midi.")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00", f"obtenu {d['heure_limite']!r}"


def test_A04_heure_sur_la_ligne_suivante():
    d = analyse([COUV, page_remise("Date limite de remise des offres : 14/03/2025\n"
                                   "Heure limite de remise des offres : 12 h 00")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00", f"obtenu {d['heure_limite']!r}"


def test_A70_delai_questions_en_lettres():
    page = page_remise("Date limite de réception des offres : 14/03/2025 à 12h00.\n"
                       "Les demandes de renseignements complémentaires doivent parvenir au plus tard "
                       "six (6) jours avant la date limite de remise des offres.")
    d = analyse([COUV, page])
    v = un(d["date_questions"], "date questions")["valeur"]
    assert isinstance(v, str) and "jours" in norm(v), f"attendu le délai écrit, obtenu {v!r}"
    assert norm(v) in norm(page), f"la valeur doit être recopiée du texte, obtenu {v!r}"
    assert not re.search(r"\d\d/\d\d/\d{4}", v), f"aucune date ne doit être calculée, obtenu {v!r}"
    assert vals(d["date_limite"]) == ["14/03/2025"], f"obtenu {d['date_limite']!r}"


def test_A90_date_limite_n_est_pas_une_date_de_visite():
    page = page_remise("La visite du site est facultative.\n"
                       "Date limite de réception des questions : 04/03/2025\n"
                       "Date limite de réception des offres : 14/03/2025 à 12h00.")
    d = analyse([COUV, page])
    absent(d["dates_visite"], "dates visite")


# ================================================================= LOTS

TITRES = ["Démolition", "Gros œuvre", "Charpente", "Couverture", "Menuiseries extérieures",
          "Plâtrerie", "Électricité", "Plomberie", "Chauffage", "Peinture", "Nettoyage"]


def test_A01_onze_lots():
    page = "ARTICLE 2 – ALLOTISSEMENT\n" + "".join(f"Lot n°{i} : {t}\n" for i, t in enumerate(TITRES, 1))
    d = analyse([COUV, page])
    assert sorted(x["numero"] for x in lots(d)) == list(range(1, 12)), f"obtenu {lots(d)!r}"
    assert intitules(lot(d, 1)) == ["Démolition"], f"obtenu {lot(d, 1)!r}"
    assert intitules(lot(d, 10)) == ["Peinture"], f"obtenu {lot(d, 10)!r}"
    assert intitules(lot(d, 11)) == ["Nettoyage"], f"obtenu {lot(d, 11)!r}"


def test_A01_numeros_non_consecutifs():
    page = ("ARTICLE 2 – LOTS CONCERNÉS\n"
            "LOT N° 3 – Électricité courants forts et faibles\n"
            "LOT N° 5 – Plomberie sanitaire\n")
    d = analyse([COUV, page])
    assert sorted(x["numero"] for x in lots(d)) == [3, 5], f"obtenu {lots(d)!r}"
    assert intitules(lot(d, 3)) == ["Électricité courants forts et faibles"], f"obtenu {lot(d, 3)!r}"


def test_A44_trou_lotissement_n_est_pas_un_lot():
    page = ("ARTICLE 1\nLe chantier est situé dans le lotissement Les Tilleuls ; "
            "le pilotage est assuré par la commune.\n")
    d = analyse([COUV, page])
    assert d["lots"]["statut"] == NON_TROUVE, f"obtenu {d['lots']!r}"
    assert lots(d) == []


def test_A46_numerotations_differentes_meme_lot():
    d = analyse([COUV, LOTS2, "ANNEXE\nLOT 01 - Gros œuvre – maçonnerie\n"])
    assert sorted(x["numero"] for x in lots(d)) == [1, 2], f"obtenu {lots(d)!r}"
    l1 = lot(d, 1)
    assert intitules(l1) == ["Gros œuvre – maçonnerie"], f"obtenu {l1!r}"
    assert l1["pages"] == [2, 3], f"obtenu {l1!r}"
    assert l1["conflit"] is False


def test_A47_trou_ponctuation_finale_meme_intitule():
    d = analyse([COUV, LOTS2, "ANNEXE\nLot n°1 : Gros œuvre – maçonnerie ;\n"])
    assert intitules(lot(d, 1)) == ["Gros œuvre – maçonnerie"], f"obtenu {lot(d, 1)!r}"
    assert lot(d, 1)["conflit"] is False


def test_A48_trou_simple_mention_d_un_lot():
    d = analyse([COUV, LOTS2, "ARTICLE 10\nPour le lot n°1, la visite du site est obligatoire.\n"])
    assert sorted(x["numero"] for x in lots(d)) == [1, 2]
    assert intitules(lot(d, 1)) == ["Gros œuvre – maçonnerie"], (
        f"une mention du lot n'est pas un intitulé ; obtenu {lot(d, 1)!r}")
    assert lot(d, 1)["conflit"] is False


# ================================================================= PROCÉDURE

def test_A07_majuscules():
    d = analyse([COUV, "ARTICLE 3\nMODE DE PASSATION : PROCÉDURE ADAPTÉE\n"])
    assert un(d["procedure"], "procédure")["valeur"] == "procédure adaptée", f"obtenu {d['procedure']!r}"


@pytest.mark.parametrize("texte,attendu", [
    ("La consultation est passée selon une procédure d'appel d'offres restreint.", "appel d'offres restreint"),
    ("Procédure de passation : dialogue compétitif.", "dialogue compétitif"),
])
def test_A07_trou_autres_procedures(texte, attendu):
    d = analyse([COUV, "ARTICLE 3\n" + texte + "\n"])
    assert un(d["procedure"], "procédure")["valeur"] == attendu, f"obtenu {d['procedure']!r}"


# ================================================================= VISITE

@pytest.mark.parametrize("texte", [
    "Visite : non obligatoire",
    "La visite est fortement conseillée mais non obligatoire.",
])
def test_A09_non_obligatoire(texte):
    d = analyse([COUV, "ARTICLE 10 – VISITE DES LIEUX\n" + texte + "\n"])
    assert vals(d["visite_obligatoire"]) == ["non"], f"obtenu {d['visite_obligatoire']!r}"
    assert d["visite_obligatoire"]["conflit"] is False


def test_A84_obligatoire_d_une_piece_n_est_pas_une_visite():
    d = analyse([COUV, PIECES])
    absent(d["visite_obligatoire"], "visite obligatoire")


# ================================================================= VARIANTES

@pytest.mark.parametrize("texte", [
    "Les candidats ne sont pas autorisés à présenter des variantes.",
    "Les variantes ne sont pas admises.",
])
def test_A11_autres_tournures(texte):
    d = analyse([COUV, "ARTICLE 4\n" + texte + "\n"])
    assert vals(d["variantes"]) == ["non autorisées"], f"obtenu {d['variantes']!r}"


def test_A99_autre_chose_autorisee():
    d = analyse([COUV, "ARTICLE 4\nLa sous-traitance est autorisée.\nLa cotraitance est admise.\n"])
    absent(d["variantes"], "variantes")


def test_A11_prestations_supplementaires_autorisees_ne_comptent_pas():
    d = analyse([COUV, "ARTICLE 4\nLes variantes ne sont pas autorisées.\n"
                       "Les prestations supplémentaires éventuelles sont autorisées.\n"])
    assert vals(d["variantes"]) == ["non autorisées"], f"obtenu {d['variantes']!r}"
    assert d["variantes"]["conflit"] is False


# ================================================================= VALIDITÉ

@pytest.mark.parametrize("texte,n", [
    ("Les offres restent valables pendant cent quatre-vingts jours.", 180),
    ("Le délai de validité des offres est de soixante-quinze jours.", 75),
    ("Le délai de validité des offres est de soixante jours.", 60),
])
def test_A108_nombres_composes(texte, n):
    d = analyse([COUV, page_remise(texte)])
    assert un(d["validite_offres"], "validité offres")["valeur"] == {"nombre": n, "unite": "jours"}


def test_A108_lettres_et_chiffres_une_seule_valeur():
    d = analyse([COUV, page_remise("Le délai de validité des offres est de cent vingt (120) jours.")])
    assert vals(d["validite_offres"]) == [{"nombre": 120, "unite": "jours"}], f"obtenu {d['validite_offres']!r}"
    assert d["validite_offres"]["conflit"] is False


def test_A12_autre_duree_sur_la_meme_page():
    d = analyse([COUV, page_remise("Les offres sont valables 120 jours.\n"
                                   "Le délai d'exécution est de 6 mois.")])
    assert vals(d["validite_offres"]) == [{"nombre": 120, "unite": "jours"}], f"obtenu {d['validite_offres']!r}"


# ================================================================= MODE REMISE

@pytest.mark.parametrize("texte", [
    "Les offres sont déposées sur la plateforme de dématérialisation https://www.achatpublic.com. "
    "Aucune offre papier ne sera acceptée.",
    "La transmission des offres sur support papier n'est pas autorisée : les plis sont remis par voie électronique.",
])
def test_A13_papier_refuse(texte):
    d = analyse([COUV, page_remise(texte)])
    assert vals(d["mode_remise"]) == ["électronique"], f"le papier est refusé, obtenu {d['mode_remise']!r}"
    assert d["mode_remise"]["conflit"] is False


def test_A13_dematerialisee():
    d = analyse([COUV, page_remise("La remise des offres est dématérialisée.")])
    assert vals(d["mode_remise"]) == ["électronique"], f"obtenu {d['mode_remise']!r}"


# ================================================================= PIÈCES

def test_A15_puces_variees():
    page = ("ARTICLE 6 – CONTENU DES PLIS\n"
            "Pièces relatives à la candidature :\n"
            "• Formulaire DC1 ;\n"
            "• Formulaire DC2 ;\n"
            "Pièces relatives à l'offre :\n"
            "* Acte d'engagement ;\n"
            "* Cadre de réponse technique.\n")
    d = analyse([COUV, page])
    assert len(d["pieces"]["liste"]) == 4, f"obtenu {[x['nom'] for x in d['pieces']['liste']]!r}"
    assert vals(piece(d, "dc1")["phase"]) == ["candidature"]
    assert vals(piece(d, "cadre de réponse")["phase"]) == ["offre"]


def test_A16_trou_partie_continue_sur_la_page_suivante():
    p2 = ("ARTICLE 5\nPièces relatives à la candidature :\n"
          "- Formulaire DC1 ;\n- Formulaire DC2 ;\n")
    p3 = ("- Attestation d'assurance décennale ;\n"
          "- Certificats de qualification professionnelle.\n"
          "Pièces relatives à l'offre :\n- Acte d'engagement.\n")
    d = analyse([COUV, p2, p3])
    assert vals(piece(d, "assurance")["phase"]) == ["candidature"], f"obtenu {piece(d, 'assurance')!r}"
    assert vals(piece(d, "acte d'engagement")["phase"]) == ["offre"]


def test_A18_a_titre_facultatif():
    page = ("Pièces relatives à l'offre :\n"
            "- Acte d'engagement ;\n"
            "- Références de chantiers similaires, à titre facultatif ;\n"
            "- Mémoire technique.\n")
    d = analyse([COUV, page])
    assert vals(piece(d, "références")["obligation"]) == ["non obligatoire"], f"obtenu {piece(d, 'références')!r}"
    absent(piece(d, "acte d'engagement")["obligation"], "obligation AE")


# ================================================================= LIMITE PAGES

def test_A20_nombre_de_pages_du_reglement():
    page = ("ARTICLE 5\nLe présent règlement de la consultation comporte 12 pages.\n"
            "Le mémoire technique présentera la méthodologie du candidat.\n")
    d = analyse([COUV, page])
    absent(d["limite_pages"], "limite pages")


def test_A19_limite_d_un_autre_document():
    page = ("ARTICLE 5\nLa lettre de motivation ne dépassera pas 2 pages.\n"
            "Le mémoire technique ne dépassera pas 15 pages.\n")
    d = analyse([COUV, page])
    assert vals(d["limite_pages"]) == [15], f"obtenu {d['limite_pages']!r}"


def test_A132_trente():
    d = analyse([COUV, "ARTICLE 5\nLe mémoire technique ne dépassera pas trente pages.\n"])
    assert un(d["limite_pages"], "limite pages")["valeur"] == 30


# ================================================================= CRITÈRES

def test_A22_tirets_sous_criteres_numerotes():
    page = ("ARTICLE 8\nCritères d'attribution :\n"
            "1. Valeur technique : 60 %\n"
            "  - Méthodologie : 40 %\n"
            "  - Moyens humains : 20 %\n"
            "2. Prix : 40 %\n")
    d = analyse([COUV, page])
    assert [norm(x) for x in libelles(d)] == ["valeur technique", "prix"], f"obtenu {libelles(d)!r}"
    vt = critere(d, "valeur technique")
    assert [norm(s["libelle"]) for s in vt["sous_criteres"]] == ["méthodologie", "moyens humains"], (
        f"obtenu {vt['sous_criteres']!r}")
    assert critere(d, "prix")["sous_criteres"] == []


def test_A21_trois_criteres_ordre_quelconque():
    page = ("ARTICLE 8\nCritères de jugement :\n"
            "1. Délai d'exécution : 10 %\n2. Prix : 30 %\n3. Valeur technique : 60 %\n")
    d = analyse([COUV, page])
    assert [norm(x) for x in libelles(d)] == ["délai d'exécution", "prix", "valeur technique"], f"obtenu {libelles(d)!r}"


def test_A140_ponderation_entre_parentheses():
    page = "ARTICLE 8\nCritères de jugement des offres :\n1. Prix (40 %)\n2. Valeur technique (60 %)\n"
    d = analyse([COUV, page])
    assert libelles(d) == ["Prix", "Valeur technique"], f"obtenu {libelles(d)!r}"
    assert un(critere(d, "prix")["ponderation"], "p")["valeur"] == 40
    assert un(critere(d, "valeur technique")["ponderation"], "p")["valeur"] == 60


def test_A140_majuscules():
    page = "ARTICLE 8\nCRITÈRES DE JUGEMENT :\n1. VALEUR TECHNIQUE : 60 %\n2. PRIX : 40 %\n"
    d = analyse([COUV, page])
    assert libelles(d) == ["VALEUR TECHNIQUE", "PRIX"], f"obtenu {libelles(d)!r}"
    assert len(sections_de(d, "valeur technique")) >= 1, f"plan : {d['plan']!r}"
    assert sections_de(d, "prix") == [], f"plan : {d['plan']!r}"


def test_A145_abreviation_pts():
    page = ("ARTICLE 8\nLes offres sont notées sur 100 points :\n"
            "1. Prix : 40 pts\n2. Valeur technique : 60 pts\n")
    d = analyse([COUV, page])
    v = un(critere(d, "valeur technique")["ponderation"], "p")
    assert (v["valeur"], v["unite"]) == (60, "points"), f"obtenu {v!r}"
    assert un(d["type_ponderation"], "type")["valeur"] == "points"


def test_A35_points_incoherents():
    page = CRIT_POINTS.replace("(35 points)", "(30 points)")
    d = analyse([COUV, page])
    assert "pondérations incohérentes" in types_alertes(d), f"30 + 25 ≠ 60, obtenu {types_alertes(d)!r}"


def test_A35_decimales_coherentes():
    page = ("ARTICLE 8\nCritères :\n1. Valeur technique : 60 %\n"
            "  1.1 Méthodologie : 47,5 %\n  1.2 Moyens : 12,5 %\n2. Prix : 40 %\n")
    d = analyse([COUV, page])
    assert d["controle"]["alertes"] == [], f"47,5 + 12,5 = 60 ; obtenu {d['controle']!r}"


def test_A38_trois_tiers_sans_alerte_de_total():
    page = ("ARTICLE 8\nCritères :\n1. Valeur technique : 33,3 %\n"
            "2. Délai d'exécution : 33,3 %\n3. Prix : 33,4 %\n")
    d = analyse([COUV, page])
    assert "total différent de 100 %" not in types_alertes(d), f"33,3 + 33,3 + 33,4 = 100 ; obtenu {types_alertes(d)!r}"


def test_A149_trou_lettres_et_chiffres_meme_ponderation():
    page = ("ARTICLE 8\nCritères de jugement :\n1. Valeur technique : soixante pour cent\n"
            "2. Prix : quarante pour cent\n")
    d = analyse([COUV, page, RAPPEL_SIMPLE])
    p = critere(d, "valeur technique")["ponderation"]
    v = un(p, "pondération")
    assert v["valeur"] == 60 and v["pages"] == [2, 3], f"obtenu {p!r}"
    assert p["conflit"] is False


def test_A28_prix_global_et_forfaitaire():
    page = "ARTICLE 8\nCritères :\n1. Valeur technique : 60 %\n2. Prix global et forfaitaire : 40 %\n"
    d = analyse([COUV, page])
    assert sections_de(d, "prix") == [], f"plan : {d['plan']!r}"


def test_A27_trou_qualite_technique():
    page = "ARTICLE 8\nCritères :\n1. Qualité technique de l'offre : 55 %\n2. Prix : 45 %\n"
    d = analyse([COUV, page])
    assert len(sections_de(d, "qualité technique")) >= 1, f"plan : {d['plan']!r}"


def test_A31_sous_criteres_en_points():
    d = analyse([COUV, CRIT_POINTS])
    attendu = {"méthodologie": 35, "moyens": 25}
    ss = [s for s in d["plan"] if s["sous_critere"]]
    assert len(ss) == 2, f"plan : {d['plan']!r}"
    for s in ss:
        assert s["ponderation"] == attendu[norm(s["sous_critere"]).split()[0]], f"obtenu {s!r}"


# ================================================================= RC COMPLET

RC = [COUV, LOTS2, PROC_ADAPTEE, PIECES, CRIT_PCT, VISITE + DL,
      MODE_ELEC + "Le délai de validité des offres est de 120 jours.\n"
                  "Les variantes ne sont pas autorisées.\n"
                  "Le mémoire technique ne devra pas excéder 10 pages.\n"]


def test_A38_rc_complet_toutes_les_regles_ensemble():
    d = analyse(RC)
    assert sorted(x["numero"] for x in lots(d)) == [1, 2], f"lots : {lots(d)!r}"
    assert vals(d["date_limite"]) == ["14/03/2025"], f"{d['date_limite']!r}"
    assert vals(d["heure_limite"]) == ["12:00"], f"{d['heure_limite']!r}"
    assert vals(d["procedure"]) == ["procédure adaptée"], f"{d['procedure']!r}"
    assert vals(d["visite_obligatoire"]) == ["oui"], f"{d['visite_obligatoire']!r}"
    assert sorted(vals(d["dates_visite"])) == ["18/02/2025", "25/02/2025"], f"{d['dates_visite']!r}"
    assert vals(d["variantes"]) == ["non autorisées"], f"{d['variantes']!r}"
    assert vals(d["validite_offres"]) == [{"nombre": 120, "unite": "jours"}], f"{d['validite_offres']!r}"
    assert vals(d["mode_remise"]) == ["électronique"], f"{d['mode_remise']!r}"
    assert vals(d["limite_pages"]) == [10], f"{d['limite_pages']!r}"
    absent(d["date_questions"], "date questions")
    assert len(d["pieces"]["liste"]) == 9, f"{[x['nom'] for x in d['pieces']['liste']]!r}"
    assert libelles(d) == ["Valeur technique de l'offre", "Prix des prestations"], f"{libelles(d)!r}"
    assert d["controle"]["alertes"] == [], f"{d['controle']!r}"


# ================================================================= VÉRIFICATEUR

def test_A14_verifier_idempotent_sur_rc_complet():
    d = analyse(RC)
    r = app.verifier(copy.deepcopy(d), list(RC))
    assert r == d, "vérifier un dossier sorti d'analyser ne doit rien retirer ni changer"


def test_A56_verifier_contre_d_autres_pages():
    d = copy.deepcopy(analyse([COUV, DL]))
    r = app.verifier(d, [COUV, NEUTRE])
    absent(r["date_limite"], "date limite")
    absent(r["heure_limite"], "heure limite")


def test_A56_verifier_garde_une_date_ecrite_en_lettres():
    pages = [COUV, page_remise("Les offres devront parvenir au plus tard le 14 mars 2025.")]
    d = copy.deepcopy(analyse([COUV, NEUTRE]))
    d["date_limite"] = fait_trouve(("14/03/2025", [2]))
    r = app.verifier(d, pages)
    v = un(r["date_limite"], "date limite")
    assert v["valeur"] == "14/03/2025" and v["pages"] == [2], (
        f"« 14 mars 2025 » est bien écrit page 2 : la date ne doit pas être retirée, obtenu {r['date_limite']!r}")


def test_A65_verifier_garde_une_heure_ecrite_en_lettres():
    pages = [COUV, page_remise("Date limite de réception des offres : le 14 mars 2025 à seize heures.")]
    d = copy.deepcopy(analyse([COUV, NEUTRE]))
    d["heure_limite"] = fait_trouve(("16:00", [2]))
    r = app.verifier(d, pages)
    assert vals(r["heure_limite"]) == ["16:00"], f"obtenu {r['heure_limite']!r}"


def test_A39_trou_verifier_page_annoncee_fausse():
    d = copy.deepcopy(analyse([COUV, NEUTRE]))
    d["date_limite"] = fait_trouve(("14/03/2025", [1]))
    r = app.verifier(d, [COUV, DL])
    for v in r["date_limite"]["valeurs"]:
        assert 1 not in v["pages"], f"la date n'est pas écrite page 1, obtenu {r['date_limite']!r}"


def test_A103_trou_verifier_negation_n_est_pas_une_preuve():
    pages = [COUV, "ARTICLE 4\nLes variantes ne sont pas autorisées.\n"]
    d = copy.deepcopy(analyse(pages))
    d["variantes"]["valeurs"].append({"valeur": "autorisées", "pages": [2]})
    d["variantes"]["conflit"] = True
    r = app.verifier(d, pages)
    assert vals(r["variantes"]) == ["non autorisées"], (
        f"« autorisées » n'est lu que sous la négation : valeur fabriquée, obtenu {r['variantes']!r}")
    assert r["variantes"]["conflit"] is False


def test_A88_trou_verifier_negation_visite():
    pages = [COUV, "ARTICLE 10\nLa visite des lieux n'est pas obligatoire.\n"]
    d = copy.deepcopy(analyse(pages))
    d["visite_obligatoire"] = fait_trouve(("oui", [2]))
    r = app.verifier(d, pages)
    assert "oui" not in vals(r["visite_obligatoire"]), f"obtenu {r['visite_obligatoire']!r}"


def test_A117_trou_verifier_papier_refuse():
    pages = [COUV, page_remise("Les offres sont déposées par voie électronique. Aucune offre papier ne sera acceptée.")]
    d = copy.deepcopy(analyse(pages))
    d["mode_remise"] = fait_trouve(("papier", [2]))
    r = app.verifier(d, pages)
    assert "papier" not in vals(r["mode_remise"]), f"obtenu {r['mode_remise']!r}"


def test_A142_verifier_recalcule_le_plan():
    pages = [COUV, CRIT_SIMPLE]
    d = copy.deepcopy(analyse(pages))
    faux = "Valeur technique et environnementale"
    for c in d["criteres"]["liste"]:
        if norm(c["libelle"]).startswith("valeur technique"):
            c["libelle"] = faux
    for s in d["plan"]:
        if norm(s["critere"]).startswith("valeur technique"):
            s["critere"] = faux
    r = app.verifier(d, pages)
    assert [norm(c["libelle"]) for c in r["criteres"]["liste"]] == ["prix"], f"obtenu {r['criteres']!r}"
    assert [s for s in r["plan"] if s["critere"] == faux] == [], f"le plan doit être recalculé, obtenu {r['plan']!r}"


def test_A49_verifier_intitule_fabrique_sur_un_vrai_lot():
    pages = [COUV, LOTS2]
    d = copy.deepcopy(analyse(pages))
    for l in d["lots"]["liste"]:
        if l["numero"] == 2:
            l["intitules"].append({"valeur": "Plomberie sanitaire", "pages": [2]})
            l["conflit"] = True
    r = app.verifier(d, pages)
    l2 = [l for l in r["lots"]["liste"] if l["numero"] == 2]
    assert len(l2) == 1, f"obtenu {r['lots']!r}"
    assert intitules(l2[0]) == ["Menuiseries extérieures"], f"obtenu {l2[0]!r}"
    assert l2[0]["conflit"] is False
