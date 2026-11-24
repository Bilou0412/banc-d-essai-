"""
Tests rouges — sonde P12 : lecture d'un règlement de la consultation (RC).

Interface publique fixée par ces tests (à implémenter telle quelle dans app.py) :

  app.analyser(pages: list[str]) -> dict
      pages[0] est la page 1. Rend un dossier sérialisable en JSON, identique pour
      les mêmes pages.

  app.verifier(dossier: dict, pages: list[str]) -> dict
      Rend une copie du dossier où toute valeur proposée qui ne se retrouve dans le
      texte d'aucune page est retirée (un fait vidé passe à « non trouvé », un élément
      de liste fabriqué disparaît), puis recalcule plan et contrôle.
      analyser(pages) applique cette vérification à ce que son extraction propose.

  app.controler(dossier: dict) -> list[dict]
      Rend les alertes du contrôle calculées sur ce dossier, avec son plan tel quel.
      Pour un dossier sorti d'analyser : controler(d) == d["controle"]["alertes"].

Fait (forme commune) :
  {"statut": "trouvé" | "non trouvé",
   "valeurs": [{"valeur": <valeur>, "pages": [<n° de page, 1 = première>, ...]}, ...],
   "conflit": bool}
  - « non trouvé » => valeurs == [] et conflit False ;
  - une même valeur n'apparaît qu'une fois, avec toutes ses pages en ordre croissant ;
  - fait à valeur unique : conflit True dès que deux valeurs différentes coexistent.

Clés du dossier :
  "lots":               {"statut", "liste": [Lot]}
      Lot = {"numero": int | None, "intitules": [{"valeur": str, "pages": [...]}],
             "pages": [...], "conflit": bool}
  "date_limite":        Fait, valeur "jj/mm/aaaa"
  "heure_limite":       Fait, valeur "hh:mm"
  "date_questions":     Fait, valeur "jj/mm/aaaa", ou le délai tel qu'il est écrit
  "procedure":          Fait, valeur en minuscules ("procédure adaptée", "appel d'offres ouvert", ...)
  "visite_obligatoire": Fait, valeur "oui" | "non"
  "dates_visite":       Fait, valeurs "jj/mm/aaaa", conflit toujours False
  "variantes":          Fait, valeur "autorisées" | "non autorisées"
  "validite_offres":    Fait, valeur {"nombre": int, "unite": "jours" | "mois"}
  "mode_remise":        Fait, valeur "électronique" | "papier"
  "pieces":             {"statut", "liste": [Piece]}
      Piece = {"nom": str, "pages": [...],
               "phase": Fait ("candidature" | "offre" | "attributaire"),
               "obligation": Fait ("obligatoire" | "non obligatoire")}
  "limite_pages":       Fait, valeur int
  "type_ponderation":   Fait, valeur "pourcentage" | "points" | "classement"
  "criteres":           {"statut", "liste": [Critere]}, dans l'ordre du RC
      Critere = {"libelle": str, "pages": [...],
                 "lot": Fait ("tous les lots" | numéro du lot),
                 "ponderation": FaitP, "sous_criteres": [SousCritere]}
      SousCritere = {"libelle": str, "pages": [...], "ponderation": FaitP}
      FaitP = Fait dont chaque valeur est
              {"valeur": nombre, "unite": "pourcentage" | "points" | "rang",
               "lot": int | None, "pages": [...]}
              conflit True seulement si deux valeurs différentes portent le même lot.
  "plan":               [Section], dans l'ordre des critères du RC
      Section = {"titre": str, "critere": str (libellé du critère),
                 "sous_critere": str | None (libellé du sous-critère),
                 "ponderation": nombre | None, "page_source": int, "contenu": ""}
  "controle":           {"alertes": [{"type": str, "objet": str}]}
      types : "critère sans section", "pondérations incohérentes",
              "total différent de 100 %"
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
    assert rejoue == d, "le dossier ne survit pas à un aller-retour JSON (tuple, clé non chaîne, objet ?)"
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


def pages_de(fait, valeur):
    for v in fait["valeurs"]:
        if v["valeur"] == valeur:
            return v["pages"]
    raise AssertionError(f"valeur {valeur!r} absente de {vals(fait)!r}")


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


def sous(c, debut):
    l = [s for s in c["sous_criteres"] if norm(s["libelle"]).startswith(norm(debut))]
    assert len(l) == 1, (f"sous-critère « {debut} » de « {c['libelle']} » : attendu exactement un, "
                         f"obtenu {[s['libelle'] for s in c['sous_criteres']]!r}")
    return l[0]


def pond(c):
    return sorted((v["valeur"], v["lot"]) for v in c["ponderation"]["valeurs"])


def sections_de(d, debut):
    return [s for s in d["plan"] if norm(s["critere"]).startswith(norm(debut))]


def types_alertes(d):
    return [a["type"] for a in d["controle"]["alertes"]]


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

CRIT_CLASSEMENT = ("ARTICLE 6 – SÉLECTION DES OFFRES\n"
                   "L'offre économiquement la plus avantageuse sera appréciée en fonction des "
                   "critères ci-dessous, classés par ordre décroissant d'importance :\n"
                   "1. Valeur technique\n"
                   "2. Prix\n")

CRIT_PAR_LOT = ("ARTICLE 8 – CRITÈRES DE JUGEMENT DES OFFRES\n"
                "Les pondérations diffèrent selon les lots.\n"
                "Lot n°1 :\n"
                "- Valeur technique : 60 %\n"
                "- Prix : 40 %\n"
                "Lot n°2 :\n"
                "- Valeur technique : 30 %\n"
                "- Prix : 70 %\n")

CRIT_RESERVE = ("ARTICLE 8 – CRITÈRES DE JUGEMENT DES OFFRES\n"
                "Lot n°1 :\n"
                "- Valeur technique : 60 %\n"
                "- Prix : 40 %\n"
                "Lot n°2 :\n"
                "- Prix : 100 %\n")


def page_remise(texte):
    return "ARTICLE 11 – CONDITIONS DE REMISE DES OFFRES\n" + texte + "\n"


# ================================================================= LOTS

def test_A01_deux_lots_numerotes():
    d = analyse([COUV, LOTS2])
    assert d["lots"]["statut"] == TROUVE, f"lots attendus trouvés, obtenu {d['lots']!r}"
    assert sorted(x["numero"] for x in lots(d)) == [1, 2], f"attendu les lots 1 et 2, obtenu {lots(d)!r}"
    assert intitules(lot(d, 1)) == ["Gros œuvre – maçonnerie"]
    assert intitules(lot(d, 2)) == ["Menuiseries extérieures"]


def test_A01_deux_lots_autre_mise_en_forme():
    page = ("DÉCOMPOSITION DE LA CONSULTATION\n"
            "LOT 01 - TERRASSEMENT VRD\n"
            "LOT 02 - ESPACES VERTS ET PLANTATIONS\n")
    d = analyse([COUV, page])
    assert sorted(x["numero"] for x in lots(d)) == [1, 2], f"attendu les lots 1 et 2, obtenu {lots(d)!r}"
    assert intitules(lot(d, 2)) == ["ESPACES VERTS ET PLANTATIONS"], f"obtenu {lot(d, 2)!r}"


def test_A43_lot_unique():
    page = ("ARTICLE 2 – DÉCOMPOSITION\n"
            "Le marché comporte un lot unique : fourniture et livraison de repas en liaison froide.\n")
    d = analyse([COUV, page])
    assert d["lots"]["statut"] == TROUVE
    assert len(lots(d)) == 1, f"attendu exactement un lot, obtenu {lots(d)!r}"


def test_A44_aucun_lot_non_trouve():
    d = analyse([COUV, NEUTRE])
    assert d["lots"]["statut"] == NON_TROUVE, f"attendu lots non trouvés (« pilote » n'est pas un lot), obtenu {d['lots']!r}"
    assert d["lots"]["liste"] == []


@pytest.mark.parametrize("phrase", [
    "Le présent marché n'est pas alloti.",
    "Il n'est pas prévu de décomposition en lots : la nature des prestations ne le permet pas.",
])
def test_A45_marche_non_alloti_un_lot(phrase):
    d = analyse([COUV, "ARTICLE 2 – ALLOTISSEMENT\n" + phrase + "\n"])
    assert d["lots"]["statut"] == TROUVE, f"obtenu {d['lots']!r}"
    assert len(lots(d)) == 1, f"attendu exactement un lot, obtenu {lots(d)!r}"


def test_A46_meme_lot_deux_pages_une_fois():
    rappel = "ANNEXE – RAPPEL DE L'ALLOTISSEMENT\nLot n°1 : Gros œuvre – maçonnerie\n"
    d = analyse([COUV, LOTS2, rappel])
    assert sorted(x["numero"] for x in lots(d)) == [1, 2], f"obtenu {lots(d)!r}"
    assert intitules(lot(d, 1)) == ["Gros œuvre – maçonnerie"]


PRECISION_LOT2 = "ARTICLE 12 – PRÉCISIONS\nLot n°2 : Menuiseries extérieures et occultations\n"


def test_A47_deux_intitules_pour_un_numero():
    d = analyse([COUV, LOTS2, PRECISION_LOT2])
    assert sorted(intitules(lot(d, 2))) == ["Menuiseries extérieures",
                                            "Menuiseries extérieures et occultations"], f"obtenu {lot(d, 2)!r}"


def test_A48_deux_intitules_conflit_signale():
    d = analyse([COUV, LOTS2, PRECISION_LOT2])
    assert lot(d, 2)["conflit"] is True, f"attendu conflit sur le lot 2, obtenu {lot(d, 2)!r}"
    assert lot(d, 1)["conflit"] is False, f"aucun conflit attendu sur le lot 1, obtenu {lot(d, 1)!r}"


def test_A49_trou_verifier_lot_fabrique():
    pages = [COUV, LOTS2]
    d = copy.deepcopy(analyse(pages))
    d["lots"]["liste"].append({"numero": 7, "intitules": [{"valeur": "Plomberie sanitaire", "pages": [2]}],
                               "pages": [2], "conflit": False})
    r = app.verifier(d, pages)
    assert sorted(x["numero"] for x in r["lots"]["liste"]) == [1, 2], f"le lot 7 fabriqué doit disparaître, obtenu {r['lots']!r}"


def test_A50_page_du_lot():
    d = analyse([COUV, NEUTRE, LOTS2])
    assert lot(d, 1)["pages"] == [3], f"attendu [3], obtenu {lot(d, 1)!r}"
    assert lot(d, 2)["intitules"][0]["pages"] == [3]


def test_A46_meme_lot_deux_pages_pages_cumulees():
    rappel = "ANNEXE – RAPPEL DE L'ALLOTISSEMENT\nLot n°1 : Gros œuvre – maçonnerie\n"
    d = analyse([COUV, LOTS2, rappel])
    assert sorted(lot(d, 1)["pages"]) == [2, 3], f"obtenu {lot(d, 1)!r}"
    assert lot(d, 1)["conflit"] is False


# ================================================================= DATE LIMITE

@pytest.mark.parametrize("texte,attendu", [
    ("Date limite de réception des offres : 14/03/2025 à 12h00.", "14/03/2025"),
    ("Les offres devront parvenir au plus tard le vendredi 14 mars 2025 à 12 heures.", "14/03/2025"),
    ("DATE ET HEURE LIMITES DE REMISE DES PLIS\nLe 28 novembre 2025 à 16h00", "28/11/2025"),
])
def test_A02_date_limite_affichee(texte, attendu):
    d = analyse([COUV, page_remise(texte)])
    assert un(d["date_limite"], "date limite")["valeur"] == attendu


def test_A03_aucune_date_limite_non_trouvee():
    page = ("ARTICLE 10 – CALENDRIER\n"
            "Visite du site le 18/02/2025 à 10h00.\n"
            "Les questions doivent parvenir au plus tard le 04/03/2025.\n"
            "Date d'envoi du présent avis à la publication : 10/02/2025.\n")
    d = analyse([COUV, page])
    absent(d["date_limite"], "date limite")


@pytest.mark.parametrize("ecrit,attendu", [
    ("le 1er avril 2025", "01/04/2025"),
    ("le lundi 3 février 2025", "03/02/2025"),
    ("le 29 août 2025", "29/08/2025"),
    ("le 15 DÉCEMBRE 2025", "15/12/2025"),
])
def test_A51_date_limite_en_lettres(ecrit, attendu):
    d = analyse([COUV, page_remise(f"Date limite de remise des offres : {ecrit} à 12h00.")])
    assert un(d["date_limite"], "date limite")["valeur"] == attendu


@pytest.mark.parametrize("ecrit", ["07/02/2025", "07.02.2025", "07-02-2025", "7/2/2025"])
def test_A52_date_limite_en_chiffres(ecrit):
    d = analyse([COUV, page_remise(f"Date limite de remise des offres : {ecrit} à 12h00.")])
    assert un(d["date_limite"], "date limite")["valeur"] == "07/02/2025"


def test_A53_meme_date_limite_deux_pages_une_fois():
    d = analyse([COUV, DL, "ANNEXE – CALENDRIER\nDate limite de réception des offres : 14/03/2025 à 12h00.\n"])
    v = un(d["date_limite"], "date limite")
    assert v["valeur"] == "14/03/2025"
    assert sorted(v["pages"]) == [2, 3], f"obtenu {v!r}"


def test_A53_trou_notations_differentes():
    d = analyse([COUV, DL, "ANNEXE – CALENDRIER\nLes offres sont attendues au plus tard le 14 mars 2025.\n"])
    v = un(d["date_limite"], "date limite")
    assert v["valeur"] == "14/03/2025"
    assert sorted(v["pages"]) == [2, 3], f"obtenu {v!r}"
    assert d["date_limite"]["conflit"] is False


DL_AUTRE = "ANNEXE – CALENDRIER\nDate limite de remise des offres : 21/03/2025 à 12h00.\n"


def test_A54_deux_dates_limites_differentes():
    d = analyse([COUV, DL, NEUTRE, DL_AUTRE])
    assert sorted(vals(d["date_limite"])) == ["14/03/2025", "21/03/2025"], f"obtenu {d['date_limite']!r}"


def test_A55_deux_dates_limites_conflit():
    d = analyse([COUV, DL, NEUTRE, DL_AUTRE])
    assert d["date_limite"]["conflit"] is True, f"obtenu {d['date_limite']!r}"


def test_A56_trou_verifier_date_limite_fabriquee():
    pages = [COUV, DL]
    d = copy.deepcopy(analyse(pages))
    d["date_limite"]["valeurs"].append({"valeur": "21/03/2025", "pages": [2]})
    d["date_limite"]["conflit"] = True
    r = app.verifier(d, pages)
    assert vals(r["date_limite"]) == ["14/03/2025"], f"la date fabriquée doit disparaître, obtenu {r['date_limite']!r}"
    assert r["date_limite"]["conflit"] is False


def test_A56_trou_verifier_date_limite_seule_fabriquee():
    pages = [COUV, NEUTRE]
    d = copy.deepcopy(analyse(pages))
    d["date_limite"] = fait_trouve(("21/03/2025", [2]))
    r = app.verifier(d, pages)
    absent(r["date_limite"], "date limite")


def test_A57_page_de_la_date_limite():
    d = analyse([COUV, NEUTRE, DL])
    assert un(d["date_limite"], "date limite")["pages"] == [3]


# ================================================================= HEURE LIMITE

def test_A04_heure_limite_affichee():
    d = analyse([COUV, page_remise("Date limite de réception des offres : 14/03/2025 à 11h30.")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == "11:30"


def test_A04_heure_de_visite_ignoree():
    d = analyse([COUV, VISITE + DL])
    assert un(d["heure_limite"], "heure limite")["valeur"] == "12:00", f"obtenu {d['heure_limite']!r}"


def test_A05_date_sans_heure():
    d = analyse([COUV, page_remise("Date limite de réception des offres : le 14 mars 2025.")])
    assert un(d["date_limite"], "date limite")["valeur"] == "14/03/2025"
    absent(d["heure_limite"], "heure limite")


def test_A58_aucune_heure_limite_malgre_autres_heures():
    page = page_remise("Date limite de réception des offres : le 14 mars 2025.\n"
                       "Visite du site le 18/02/2025 à 10h00.\n"
                       "L'accueil de la mairie est ouvert de 9h à 17h.")
    d = analyse([COUV, page])
    absent(d["heure_limite"], "heure limite")


def test_A59_forme_16_heures():
    d = analyse([COUV, page_remise("Date limite de réception des offres : 14/03/2025 à 16 heures.")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == "16:00"


@pytest.mark.parametrize("ecrit,attendu", [
    ("16h00", "16:00"), ("16 h 00", "16:00"), ("16H00", "16:00"), ("16h30", "16:30"),
])
def test_A60_forme_16h00(ecrit, attendu):
    d = analyse([COUV, page_remise(f"Date limite de réception des offres : 14/03/2025 à {ecrit}.")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == attendu


@pytest.mark.parametrize("ecrit,attendu", [
    ("dix-sept heures", "17:00"), ("douze heures", "12:00"), ("seize heures trente", "16:30"),
])
def test_A61_heure_en_lettres(ecrit, attendu):
    d = analyse([COUV, page_remise(f"Date limite de réception des offres : le 14 mars 2025 à {ecrit}.")])
    assert un(d["heure_limite"], "heure limite")["valeur"] == attendu


def test_A62_meme_heure_deux_pages_une_fois():
    d = analyse([COUV, DL, "ANNEXE – CALENDRIER\nDate limite de réception des offres : 14/03/2025 à 12h00.\n"])
    v = un(d["heure_limite"], "heure limite")
    assert v["valeur"] == "12:00"
    assert sorted(v["pages"]) == [2, 3]


HEURE_AUTRE = "ANNEXE – CALENDRIER\nDate limite de réception des offres : 14/03/2025 à 16h00.\n"


def test_A63_deux_heures_differentes():
    d = analyse([COUV, DL, HEURE_AUTRE])
    assert sorted(vals(d["heure_limite"])) == ["12:00", "16:00"], f"obtenu {d['heure_limite']!r}"


def test_A64_deux_heures_conflit():
    d = analyse([COUV, DL, HEURE_AUTRE])
    assert d["heure_limite"]["conflit"] is True
    assert d["date_limite"]["conflit"] is False, "la date est la même : pas de conflit sur la date"


def test_A65_trou_verifier_heure_fabriquee():
    pages = [COUV, page_remise("Date limite de réception des offres : le 14 mars 2025.")]
    d = copy.deepcopy(analyse(pages))
    d["heure_limite"] = fait_trouve(("17:00", [2]))
    r = app.verifier(d, pages)
    absent(r["heure_limite"], "heure limite")


def test_A66_page_de_l_heure():
    d = analyse([COUV, NEUTRE, NEUTRE, DL])
    assert un(d["heure_limite"], "heure limite")["pages"] == [4]


# ================================================================= DATE QUESTIONS

def test_A06_date_questions_distincte_de_la_date_limite():
    page = page_remise("Date limite de réception des offres : 14/03/2025 à 12h00.\n"
                       "Les demandes de renseignements complémentaires devront parvenir au plus tard le 04/03/2025.")
    d = analyse([COUV, page])
    assert un(d["date_questions"], "date questions")["valeur"] == "04/03/2025"
    assert un(d["date_limite"], "date limite")["valeur"] == "14/03/2025"


def test_A67_aucune_date_questions():
    d = analyse([COUV, DL])
    absent(d["date_questions"], "date questions")


def test_A68_date_questions_en_lettres():
    page = page_remise("Les questions des candidats doivent être posées sur la plateforme au plus tard le 4 mars 2025.")
    d = analyse([COUV, page])
    assert un(d["date_questions"], "date questions")["valeur"] == "04/03/2025"


def test_A69_date_questions_en_chiffres():
    d = analyse([COUV, page_remise("Date limite d'envoi des questions : 04.03.2025")])
    assert un(d["date_questions"], "date questions")["valeur"] == "04/03/2025"


def test_A70_delai_questions_tel_qu_ecrit():
    texte = ("Les candidats pourront poser leurs questions au plus tard 10 jours avant "
             "la date limite de remise des offres.")
    page = page_remise(texte)
    d = analyse([COUV, page])
    v = un(d["date_questions"], "date questions")["valeur"]
    assert isinstance(v, str), f"attendu le délai écrit, obtenu {v!r}"
    assert "10 jours" in norm(v), f"le délai « 10 jours » doit figurer dans la valeur, obtenu {v!r}"
    assert norm(v) in norm(page), f"la valeur doit être recopiée du texte, obtenu {v!r}"
    assert not re.fullmatch(r"\d\d/\d\d/\d{4}", v), f"aucune date ne doit être calculée, obtenu {v!r}"


def test_A71_meme_date_questions_deux_pages():
    q = "Date limite d'envoi des questions : 04/03/2025\n"
    d = analyse([COUV, page_remise(q), "ANNEXE – CALENDRIER\n" + q])
    v = un(d["date_questions"], "date questions")
    assert v["valeur"] == "04/03/2025"
    assert sorted(v["pages"]) == [2, 3]


Q1 = page_remise("Date limite d'envoi des questions : 04/03/2025")
Q2 = "ANNEXE – CALENDRIER\nDate limite d'envoi des questions : 07/03/2025\n"


def test_A72_deux_dates_questions():
    d = analyse([COUV, Q1, Q2])
    assert sorted(vals(d["date_questions"])) == ["04/03/2025", "07/03/2025"]


def test_A73_deux_dates_questions_conflit():
    d = analyse([COUV, Q1, Q2])
    assert d["date_questions"]["conflit"] is True


def test_A74_trou_verifier_date_questions_fabriquee():
    pages = [COUV, DL]
    d = copy.deepcopy(analyse(pages))
    d["date_questions"] = fait_trouve(("28/02/2025", [2]))
    r = app.verifier(d, pages)
    absent(r["date_questions"], "date questions")


def test_A75_page_de_la_date_questions():
    d = analyse([COUV, NEUTRE, Q1])
    assert un(d["date_questions"], "date questions")["pages"] == [3]


# ================================================================= PROCÉDURE

PROC_ADAPTEE = ("ARTICLE 3 – PROCÉDURE\n"
                "La présente consultation est passée selon la procédure adaptée, en application "
                "de l'article R2123-1 du Code de la commande publique.\n")
PROC_AOO = "ARTICLE 3 – PROCÉDURE\nProcédure de passation : appel d'offres ouvert\n"


def test_A07_procedure_adaptee():
    d = analyse([COUV, PROC_ADAPTEE])
    assert un(d["procedure"], "procédure")["valeur"] == "procédure adaptée"


def test_A76_aucune_procedure():
    d = analyse([COUV, NEUTRE])
    absent(d["procedure"], "procédure")


@pytest.mark.parametrize("texte", ["Mode de passation : MAPA", "Consultation n° 2025-014 (MAPA)"])
def test_A77_sigle_mapa(texte):
    d = analyse([COUV, "ARTICLE 3\n" + texte + "\n"])
    assert un(d["procedure"], "procédure")["valeur"] == "procédure adaptée"


@pytest.mark.parametrize("texte", [
    "Procédure de passation : appel d'offres ouvert",
    "La consultation est lancée par APPEL D’OFFRES OUVERT conformément aux articles R2124-2 et R2161-2.",
])
def test_A78_appel_d_offres_ouvert(texte):
    d = analyse([COUV, "ARTICLE 3\n" + texte + "\n"])
    assert un(d["procedure"], "procédure")["valeur"] == "appel d'offres ouvert"


def test_A79_meme_procedure_deux_pages():
    d = analyse([COUV, PROC_ADAPTEE, "ANNEXE\nRappel : procédure adaptée.\n"])
    v = un(d["procedure"], "procédure")
    assert v["valeur"] == "procédure adaptée"
    assert sorted(v["pages"]) == [2, 3]


def test_A79_sigle_et_expression_meme_procedure():
    d = analyse([COUV, PROC_ADAPTEE, NEUTRE, "Consultation passée en MAPA.\n"])
    v = un(d["procedure"], "procédure")
    assert sorted(v["pages"]) == [2, 4], f"obtenu {v!r}"


def test_A80_deux_procedures():
    d = analyse([COUV, PROC_ADAPTEE, PROC_AOO])
    assert sorted(vals(d["procedure"])) == ["appel d'offres ouvert", "procédure adaptée"]


def test_A81_deux_procedures_conflit():
    d = analyse([COUV, PROC_ADAPTEE, PROC_AOO])
    assert d["procedure"]["conflit"] is True


def test_A82_trou_verifier_procedure_fabriquee():
    pages = [COUV, PROC_ADAPTEE]
    d = copy.deepcopy(analyse(pages))
    d["procedure"]["valeurs"].append({"valeur": "appel d'offres restreint", "pages": [2]})
    r = app.verifier(d, pages)
    assert vals(r["procedure"]) == ["procédure adaptée"], f"obtenu {r['procedure']!r}"
    d2 = copy.deepcopy(analyse([COUV, NEUTRE]))
    d2["procedure"] = fait_trouve(("appel d'offres restreint", [2]))
    absent(app.verifier(d2, [COUV, NEUTRE])["procedure"], "procédure")


def test_A83_page_de_la_procedure():
    d = analyse([COUV, NEUTRE, PROC_AOO])
    assert un(d["procedure"], "procédure")["pages"] == [3]


# ================================================================= VISITE

@pytest.mark.parametrize("texte", [
    "Une visite des lieux est obligatoire avant la remise des offres.",
    "Visite de site : OBLIGATOIRE",
    "La visite du site est obligatoire ; toute offre remise sans attestation de visite sera déclarée irrégulière.",
])
def test_A08_visite_obligatoire_oui(texte):
    d = analyse([COUV, "ARTICLE 10 – VISITE\n" + texte + "\n"])
    assert un(d["visite_obligatoire"], "visite obligatoire")["valeur"] == "oui"


@pytest.mark.parametrize("texte", [
    "La visite du site est facultative.",
    "La visite des lieux n'est pas obligatoire mais elle est vivement conseillée.",
    "Une visite facultative peut être organisée sur demande.",
])
def test_A09_visite_facultative_non(texte):
    d = analyse([COUV, "ARTICLE 10 – VISITE\n" + texte + "\n"])
    assert un(d["visite_obligatoire"], "visite obligatoire")["valeur"] == "non"


def test_A84_aucune_visite():
    d = analyse([COUV, NEUTRE])
    absent(d["visite_obligatoire"], "visite obligatoire")


VIS_OBL = "ARTICLE 10 – VISITE\nLa visite du site est obligatoire.\n"
VIS_FAC = "ANNEXE\nLa visite du site est facultative.\n"


def test_A85_deux_pages_obligatoire():
    d = analyse([COUV, VIS_OBL, "ANNEXE\nVisite de site : obligatoire\n"])
    v = un(d["visite_obligatoire"], "visite obligatoire")
    assert v["valeur"] == "oui"
    assert sorted(v["pages"]) == [2, 3]
    assert d["visite_obligatoire"]["conflit"] is False


def test_A86_obligatoire_et_facultative():
    d = analyse([COUV, VIS_OBL, VIS_FAC])
    assert sorted(vals(d["visite_obligatoire"])) == ["non", "oui"]


def test_A87_obligatoire_et_facultative_conflit():
    d = analyse([COUV, VIS_OBL, VIS_FAC])
    assert d["visite_obligatoire"]["conflit"] is True


def test_A88_trou_verifier_visite_fabriquee():
    pages = [COUV, NEUTRE]
    d = copy.deepcopy(analyse(pages))
    d["visite_obligatoire"] = fait_trouve(("oui", [2]))
    absent(app.verifier(d, pages)["visite_obligatoire"], "visite obligatoire")


def test_A89_page_de_la_visite():
    d = analyse([COUV, NEUTRE, VIS_OBL])
    assert un(d["visite_obligatoire"], "visite obligatoire")["pages"] == [3]


# ================================================================= DATES VISITE

def test_A10_dates_visite_listees_sans_la_date_limite():
    d = analyse([COUV, VISITE + DL])
    assert d["dates_visite"]["statut"] == TROUVE
    assert sorted(vals(d["dates_visite"])) == ["18/02/2025", "25/02/2025"], f"obtenu {d['dates_visite']!r}"


def test_A90_aucune_date_visite():
    d = analyse([COUV, "La visite du site est facultative.\n" + DL])
    absent(d["dates_visite"], "dates visite")


def test_A91_date_visite_en_lettres():
    d = analyse([COUV, "Une visite obligatoire aura lieu le jeudi 20 février 2025 à 9h30.\n"])
    assert vals(d["dates_visite"]) == ["20/02/2025"]


def test_A92_date_visite_en_chiffres():
    d = analyse([COUV, "Visite des lieux organisée le 20/02/2025 à 9h30.\n"])
    assert vals(d["dates_visite"]) == ["20/02/2025"]


def test_A93_meme_date_visite_deux_pages():
    d = analyse([COUV, "Visite des lieux organisée le 20/02/2025 à 9h30.\n",
                 "ANNEXE\nRappel : visite du site le 20 février 2025.\n"])
    v = un(d["dates_visite"], "dates visite")
    assert v["valeur"] == "20/02/2025"
    assert sorted(v["pages"]) == [2, 3]


V1 = "Visite des lieux organisée le 20/02/2025 à 9h30.\n"
V2 = "ANNEXE\nUne seconde visite du site est organisée le 27/02/2025 à 14h00.\n"


def test_A94_deux_dates_visite():
    d = analyse([COUV, V1, V2])
    assert sorted(vals(d["dates_visite"])) == ["20/02/2025", "27/02/2025"]


def test_A95_deux_dates_visite_sans_conflit():
    d = analyse([COUV, V1, V2])
    assert d["dates_visite"]["conflit"] is False


def test_A96_trou_verifier_date_visite_fabriquee():
    pages = [COUV, V1]
    d = copy.deepcopy(analyse(pages))
    d["dates_visite"]["valeurs"].append({"valeur": "03/03/2025", "pages": [2]})
    r = app.verifier(d, pages)
    assert vals(r["dates_visite"]) == ["20/02/2025"], f"obtenu {r['dates_visite']!r}"


def test_A97_page_de_la_date_visite():
    d = analyse([COUV, NEUTRE, V1])
    assert pages_de(d["dates_visite"], "20/02/2025") == [3]


# ================================================================= VARIANTES

@pytest.mark.parametrize("texte", [
    "Les variantes ne sont pas autorisées.",
    "Les variantes sont interdites.",
    "Aucune variante n'est admise.",
    "Variantes : non autorisées",
])
def test_A11_variantes_interdites(texte):
    d = analyse([COUV, "ARTICLE 4 – VARIANTES\n" + texte + "\n"])
    assert un(d["variantes"], "variantes")["valeur"] == "non autorisées"


@pytest.mark.parametrize("texte", [
    "Les variantes sont autorisées.",
    "Les variantes sont admises dans les conditions de l'article 4.2.",
])
def test_A98_variantes_autorisees(texte):
    d = analyse([COUV, "ARTICLE 4 – VARIANTES\n" + texte + "\n"])
    assert un(d["variantes"], "variantes")["valeur"] == "autorisées"


def test_A99_aucune_mention_variantes():
    d = analyse([COUV, NEUTRE])
    absent(d["variantes"], "variantes")


VAR_NON = "ARTICLE 4\nLes variantes ne sont pas autorisées.\n"
VAR_OUI = "ANNEXE\nLes variantes sont autorisées.\n"


def test_A100_deux_pages_interdisent():
    d = analyse([COUV, VAR_NON, "ANNEXE\nAucune variante n'est admise.\n"])
    v = un(d["variantes"], "variantes")
    assert v["valeur"] == "non autorisées"
    assert sorted(v["pages"]) == [2, 3]


def test_A101_autorisees_et_interdites():
    d = analyse([COUV, VAR_NON, VAR_OUI])
    assert sorted(vals(d["variantes"])) == ["autorisées", "non autorisées"]


def test_A102_autorisees_et_interdites_conflit():
    d = analyse([COUV, VAR_NON, VAR_OUI])
    assert d["variantes"]["conflit"] is True


def test_A103_trou_verifier_variantes_fabriquees():
    pages = [COUV, NEUTRE]
    d = copy.deepcopy(analyse(pages))
    d["variantes"] = fait_trouve(("autorisées", [2]))
    absent(app.verifier(d, pages)["variantes"], "variantes")


def test_A104_page_des_variantes():
    d = analyse([COUV, NEUTRE, VAR_NON])
    assert un(d["variantes"], "variantes")["pages"] == [3]


# ================================================================= VALIDITÉ

def test_A12_validite_offres():
    d = analyse([COUV, page_remise("Le délai de validité des offres est fixé à 120 jours à compter "
                                   "de la date limite de réception des offres.")])
    assert un(d["validite_offres"], "validité offres")["valeur"] == {"nombre": 120, "unite": "jours"}


def test_A105_aucune_validite_malgre_autre_duree():
    d = analyse([COUV, page_remise("Le délai d'exécution des travaux est de 90 jours.\n"
                                   "Date limite de réception des offres : 14/03/2025 à 12h00.")])
    absent(d["validite_offres"], "validité offres")


@pytest.mark.parametrize("texte,n", [
    ("Les offres sont valables 150 jours.", 150),
    ("Durée de validité des offres : 90 jours à compter de la date limite de remise.", 90),
])
def test_A106_validite_en_jours(texte, n):
    d = analyse([COUV, page_remise(texte)])
    assert un(d["validite_offres"], "validité offres")["valeur"] == {"nombre": n, "unite": "jours"}


@pytest.mark.parametrize("texte,n", [
    ("Le délai de validité des offres est de 6 mois.", 6),
    ("Durée de validité des offres : quatre (4) mois.", 4),
])
def test_A107_validite_en_mois(texte, n):
    d = analyse([COUV, page_remise(texte)])
    assert un(d["validite_offres"], "validité offres")["valeur"] == {"nombre": n, "unite": "mois"}


@pytest.mark.parametrize("texte,n", [
    ("Le délai de validité des offres est de cent vingt jours.", 120),
    ("Délai de validité des offres : quatre-vingt-dix jours.", 90),
])
def test_A108_validite_en_lettres(texte, n):
    d = analyse([COUV, page_remise(texte)])
    assert un(d["validite_offres"], "validité offres")["valeur"] == {"nombre": n, "unite": "jours"}


VAL120 = page_remise("Le délai de validité des offres est de 120 jours.")
VAL180 = "ANNEXE\nDurée de validité des offres : 180 jours.\n"


def test_A109_meme_validite_deux_pages():
    d = analyse([COUV, VAL120, "ANNEXE\nDurée de validité des offres : 120 jours.\n"])
    v = un(d["validite_offres"], "validité offres")
    assert sorted(v["pages"]) == [2, 3]


def test_A110_deux_validites():
    d = analyse([COUV, VAL120, VAL180])
    assert sorted(x["nombre"] for x in vals(d["validite_offres"])) == [120, 180]


def test_A111_deux_validites_conflit():
    d = analyse([COUV, VAL120, VAL180])
    assert d["validite_offres"]["conflit"] is True


def test_A112_page_de_la_validite():
    d = analyse([COUV, NEUTRE, VAL120])
    assert un(d["validite_offres"], "validité offres")["pages"] == [3]


def test_A14_trou_verifier_validite_fabriquee():
    pages = [COUV, NEUTRE]
    d = copy.deepcopy(analyse(pages))
    d["validite_offres"] = fait_trouve(({"nombre": 180, "unite": "jours"}, [2]))
    absent(app.verifier(d, pages)["validite_offres"], "validité offres")


def test_A14_trou_verifier_garde_la_vraie_validite():
    pages = [COUV, VAL120]
    d = copy.deepcopy(analyse(pages))
    d["validite_offres"]["valeurs"].append({"valeur": {"nombre": 180, "unite": "jours"}, "pages": [2]})
    r = app.verifier(d, pages)
    assert vals(r["validite_offres"]) == [{"nombre": 120, "unite": "jours"}], f"obtenu {r['validite_offres']!r}"


def test_A14_validite_renvoyee_ailleurs_non_inventee():
    d = analyse([COUV, page_remise("Le délai de validité des offres est indiqué dans l'acte d'engagement.")])
    absent(d["validite_offres"], "validité offres")


# ================================================================= MODE REMISE

MODE_ELEC = page_remise("Les offres sont transmises exclusivement par voie électronique sur le profil "
                        "d'acheteur https://www.marches-securises.fr.")
MODE_PAPIER = ("ANNEXE\nLes plis pourront également être remis sur support papier, sous pli cacheté, "
               "contre récépissé à l'accueil de la mairie.\n")


def test_A13_mode_remise_electronique():
    d = analyse([COUV, MODE_ELEC])
    assert un(d["mode_remise"], "mode remise")["valeur"] == "électronique"


def test_A13_trou_mode_remise_papier():
    d = analyse([COUV, MODE_PAPIER])
    assert un(d["mode_remise"], "mode remise")["valeur"] == "papier"


def test_A113_aucun_mode_remise():
    d = analyse([COUV, NEUTRE])
    absent(d["mode_remise"], "mode remise")


def test_A114_meme_mode_deux_pages():
    d = analyse([COUV, MODE_ELEC, "ANNEXE\nRemise des plis par voie électronique uniquement.\n"])
    v = un(d["mode_remise"], "mode remise")
    assert sorted(v["pages"]) == [2, 3]


def test_A115_deux_modes():
    d = analyse([COUV, MODE_ELEC, MODE_PAPIER])
    assert sorted(vals(d["mode_remise"])) == ["papier", "électronique"]


def test_A116_deux_modes_conflit():
    d = analyse([COUV, MODE_ELEC, MODE_PAPIER])
    assert d["mode_remise"]["conflit"] is True


def test_A117_trou_verifier_mode_fabrique():
    pages = [COUV, MODE_ELEC]
    d = copy.deepcopy(analyse(pages))
    d["mode_remise"]["valeurs"].append({"valeur": "papier", "pages": [2]})
    r = app.verifier(d, pages)
    assert vals(r["mode_remise"]) == ["électronique"], f"obtenu {r['mode_remise']!r}"


def test_A118_page_du_mode():
    d = analyse([COUV, NEUTRE, MODE_ELEC])
    assert un(d["mode_remise"], "mode remise")["pages"] == [3]


# ================================================================= PIÈCES

MOTS_PIECES = ["dc1", "dc2", "assurance", "références", "acte d'engagement",
               "mémoire technique", "bordereau", "régularité", "k-bis"]


def test_A15_chaque_piece_listee():
    d = analyse([COUV, PIECES])
    assert d["pieces"]["statut"] == TROUVE
    for mot in MOTS_PIECES:
        piece(d, mot)
    assert len(d["pieces"]["liste"]) == 9, f"attendu 9 pièces, obtenu {[x['nom'] for x in d['pieces']['liste']]!r}"


def test_A16_phase_candidature():
    d = analyse([COUV, PIECES])
    for mot in ["dc1", "dc2", "assurance"]:
        assert vals(piece(d, mot)["phase"]) == ["candidature"], f"{mot} : obtenu {piece(d, mot)['phase']!r}"


def test_A17_phase_attributaire():
    d = analyse([COUV, PIECES])
    for mot in ["régularité", "k-bis"]:
        assert vals(piece(d, mot)["phase"]) == ["attributaire"], f"{mot} : obtenu {piece(d, mot)['phase']!r}"


def test_A123_phase_offre():
    d = analyse([COUV, PIECES])
    for mot in ["acte d'engagement", "mémoire technique", "bordereau"]:
        assert vals(piece(d, mot)["phase"]) == ["offre"], f"{mot} : obtenu {piece(d, mot)['phase']!r}"


def test_A124_piece_sans_partie():
    page = ("ARTICLE 4 – PRÉSENTATION DES PROPOSITIONS\n"
            "Chaque soumissionnaire remettra les documents suivants :\n"
            "- un mémoire justificatif ;\n"
            "- un planning prévisionnel.\n")
    d = analyse([COUV, page])
    absent(piece(d, "mémoire justificatif")["phase"], "phase pièce")
    absent(piece(d, "planning")["phase"], "phase pièce")


def test_A18_piece_facultative():
    d = analyse([COUV, PIECES])
    assert un(piece(d, "références")["obligation"], "obligation")["valeur"] == "non obligatoire"


def test_A127_piece_obligatoire():
    d = analyse([COUV, PIECES])
    assert un(piece(d, "acte d'engagement")["obligation"], "obligation")["valeur"] == "obligatoire"


def test_A128_piece_ni_obligatoire_ni_facultative():
    d = analyse([COUV, PIECES])
    absent(piece(d, "mémoire technique")["obligation"], "obligation pièce")


def test_A119_aucune_piece():
    d = analyse([COUV, NEUTRE])
    assert d["pieces"]["statut"] == NON_TROUVE
    assert d["pieces"]["liste"] == []


ANNEXE_AE = ("ANNEXE – PIÈCES DE L'OFFRE\n"
             "- Acte d'engagement (AE) complété et signé (obligatoire) ;\n")


def test_A120_meme_piece_deux_pages():
    d = analyse([COUV, PIECES, NEUTRE, ANNEXE_AE])
    p = piece(d, "acte d'engagement")
    assert sorted(p["pages"]) == [2, 4], f"obtenu {p!r}"


def test_A125_meme_partie_une_fois():
    d = analyse([COUV, PIECES, NEUTRE, ANNEXE_AE])
    assert vals(piece(d, "acte d'engagement")["phase"]) == ["offre"]


def test_A129_obligatoire_deux_fois():
    d = analyse([COUV, PIECES, NEUTRE, ANNEXE_AE])
    o = piece(d, "acte d'engagement")["obligation"]
    assert vals(o) == ["obligatoire"]
    assert o["conflit"] is False


def test_A126_deux_parties():
    attrib = ("ARTICLE 13 – ATTRIBUTION\nPièces à fournir par l'attributaire :\n"
              "- Attestation d'assurance responsabilité civile professionnelle ;\n")
    d = analyse([COUV, PIECES, attrib])
    assert sorted(vals(piece(d, "assurance")["phase"])) == ["attributaire", "candidature"]


ASS_OBL = ("Pièces relatives à la candidature\n"
           "- Attestation d'assurance responsabilité civile (obligatoire) ;\n")
ASS_FAC = ("ANNEXE – Pièces relatives à la candidature\n"
           "- Attestation d'assurance responsabilité civile (facultative) ;\n")


def test_A130_obligatoire_et_facultative():
    d = analyse([COUV, ASS_OBL, ASS_FAC])
    assert sorted(vals(piece(d, "assurance")["obligation"])) == ["non obligatoire", "obligatoire"]


def test_A131_obligatoire_et_facultative_conflit():
    d = analyse([COUV, ASS_OBL, ASS_FAC])
    assert piece(d, "assurance")["obligation"]["conflit"] is True


def test_A121_trou_verifier_piece_fabriquee():
    pages = [COUV, PIECES]
    d = copy.deepcopy(analyse(pages))
    d["pieces"]["liste"].append({"nom": "Certificat de qualification Qualibat", "pages": [2],
                                 "phase": fait_trouve(("candidature", [2])),
                                 "obligation": fait_trouve(("obligatoire", [2]))})
    r = app.verifier(d, pages)
    assert pieces_avec(r, "qualibat") == [], "la pièce fabriquée doit disparaître"
    assert len(r["pieces"]["liste"]) == 9


def test_A122_page_de_la_piece():
    d = analyse([COUV, NEUTRE, PIECES])
    assert piece(d, "dc1")["pages"] == [3]


# ================================================================= LIMITE PAGES

@pytest.mark.parametrize("texte,n", [
    ("Le mémoire technique ne devra pas excéder 10 pages (format A4, police Arial 11).", 10),
    ("Mémoire technique : 25 pages maximum, annexes non comprises.", 25),
])
def test_A19_limite_pages(texte, n):
    d = analyse([COUV, "ARTICLE 5\n" + texte + "\n"])
    assert un(d["limite_pages"], "limite pages")["valeur"] == n


def test_A20_aucune_limite_malgre_pieds_de_page():
    page = ("ARTICLE 5\nLe mémoire technique présentera la méthodologie du candidat. "
            "Il sera rédigé en police 11.\nPage 3 sur 6\n")
    d = analyse([COUV, page])
    absent(d["limite_pages"], "limite pages")


@pytest.mark.parametrize("texte,n", [
    ("Le mémoire technique est limité à quinze pages.", 15),
    ("Le mémoire technique ne dépassera pas vingt (20) pages.", 20),
])
def test_A132_limite_en_lettres(texte, n):
    d = analyse([COUV, "ARTICLE 5\n" + texte + "\n"])
    assert un(d["limite_pages"], "limite pages")["valeur"] == n


def test_A133_limite_en_chiffres():
    d = analyse([COUV, "ARTICLE 5\nLe mémoire technique est limité à 12 pages recto.\n"])
    assert un(d["limite_pages"], "limite pages")["valeur"] == 12


LIM10 = "ARTICLE 5\nLe mémoire technique ne devra pas excéder 10 pages.\n"


def test_A134_meme_limite_deux_pages():
    d = analyse([COUV, LIM10, "ANNEXE\nMémoire technique : 10 pages maximum.\n"])
    v = un(d["limite_pages"], "limite pages")
    assert sorted(v["pages"]) == [2, 3]


LIM15 = "ANNEXE\nMémoire technique : 15 pages maximum.\n"


def test_A135_deux_limites():
    d = analyse([COUV, LIM10, LIM15])
    assert sorted(vals(d["limite_pages"])) == [10, 15]


def test_A136_deux_limites_conflit():
    d = analyse([COUV, LIM10, LIM15])
    assert d["limite_pages"]["conflit"] is True


def test_A137_trou_verifier_limite_fabriquee():
    pages = [COUV, NEUTRE]
    d = copy.deepcopy(analyse(pages))
    d["limite_pages"] = fait_trouve((30, [2]))
    absent(app.verifier(d, pages)["limite_pages"], "limite pages")


def test_A138_page_de_la_limite():
    d = analyse([COUV, NEUTRE, LIM10])
    assert un(d["limite_pages"], "limite pages")["pages"] == [3]


# ================================================================= CRITÈRES

def test_A21_ordre_des_criteres():
    d = analyse([COUV, CRIT_PCT])
    assert [norm(x) for x in libelles(d)] == ["valeur technique de l'offre", "prix des prestations"]
    d = analyse([COUV, CRIT_POINTS])
    assert [norm(x) for x in libelles(d)] == ["prix", "valeur technique"], f"obtenu {libelles(d)!r}"


def test_A140_libelle_tel_qu_ecrit():
    d = analyse([COUV, CRIT_PCT])
    assert libelles(d) == ["Valeur technique de l'offre", "Prix des prestations"], f"obtenu {libelles(d)!r}"


def test_A139_aucun_critere():
    page = ("ARTICLE 5\nLe mémoire technique ne devra pas excéder 10 pages.\n"
            "Le prix est ferme et actualisable.\n")
    d = analyse([COUV, page])
    assert d["criteres"]["statut"] == NON_TROUVE
    assert d["criteres"]["liste"] == []
    assert d["plan"] == []


def test_A141_meme_critere_deux_pages():
    d = analyse([COUV, CRIT_SIMPLE, NEUTRE, NEUTRE, RAPPEL_SIMPLE])
    assert [norm(x) for x in libelles(d)] == ["valeur technique", "prix"], f"obtenu {libelles(d)!r}"
    assert sorted(critere(d, "valeur technique")["pages"]) == [2, 5]


def test_A142_trou_verifier_critere_fabrique():
    pages = [COUV, CRIT_SIMPLE]
    d = copy.deepcopy(analyse(pages))
    d["criteres"]["liste"].append({
        "libelle": "Performance environnementale", "pages": [2],
        "lot": fait_trouve(("tous les lots", [2])),
        "ponderation": {"statut": TROUVE, "valeurs": [{"valeur": 10, "unite": "pourcentage", "lot": None, "pages": [2]}],
                        "conflit": False},
        "sous_criteres": []})
    r = app.verifier(d, pages)
    assert [norm(c["libelle"]) for c in r["criteres"]["liste"]] == ["valeur technique", "prix"]


def test_A143_page_du_critere():
    d = analyse([COUV, NEUTRE, CRIT_SIMPLE])
    assert critere(d, "prix")["pages"] == [3]


def test_A22_sous_criteres_rattaches():
    d = analyse([COUV, CRIT_PCT])
    vt = critere(d, "valeur technique")
    assert [norm(s["libelle"]) for s in vt["sous_criteres"]] == [
        "méthodologie d'exécution des travaux",
        "moyens humains et matériels affectés au chantier",
        "planning détaillé d'exécution"], f"obtenu {vt['sous_criteres']!r}"


def test_A22_sous_criteres_lettres():
    d = analyse([COUV, CRIT_POINTS])
    vt = critere(d, "valeur technique")
    assert [norm(s["libelle"]) for s in vt["sous_criteres"]] == [
        "méthodologie proposée", "moyens affectés à l'opération"], f"obtenu {vt['sous_criteres']!r}"
    assert len(criteres(d)) == 2, "les sous-critères ne sont pas des critères"


def test_A154_critere_sans_sous_critere():
    d = analyse([COUV, CRIT_PCT])
    assert critere(d, "prix")["sous_criteres"] == []


def test_A155_ponderation_sous_critere():
    d = analyse([COUV, CRIT_PCT])
    m = sous(critere(d, "valeur technique"), "méthodologie")
    v = un(m["ponderation"], "pondération sous-critère")
    assert (v["valeur"], v["unite"]) == (30, "pourcentage")
    d = analyse([COUV, CRIT_POINTS])
    m = sous(critere(d, "valeur technique"), "moyens")
    v = un(m["ponderation"], "pondération sous-critère")
    assert (v["valeur"], v["unite"]) == (25, "points")


def test_A156_meme_sous_critere_deux_pages():
    rappel = ("ANNEXE – RAPPEL\n1. Valeur technique de l'offre : 60 %\n"
              "   1.1 Méthodologie d'exécution des travaux : 30 %\n")
    d = analyse([COUV, CRIT_PCT, NEUTRE, rappel])
    vt = critere(d, "valeur technique")
    assert len(vt["sous_criteres"]) == 3, f"obtenu {vt['sous_criteres']!r}"
    assert sorted(sous(vt, "méthodologie")["pages"]) == [2, 4]


def test_A157_trou_verifier_sous_critere_fabrique():
    pages = [COUV, CRIT_PCT]
    d = copy.deepcopy(analyse(pages))
    vt = [c for c in d["criteres"]["liste"] if norm(c["libelle"]).startswith("valeur technique")][0]
    vt["sous_criteres"].append({"libelle": "Démarche qualité", "pages": [2],
                                "ponderation": {"statut": TROUVE, "valeurs": [
                                    {"valeur": 5, "unite": "pourcentage", "lot": None, "pages": [2]}], "conflit": False}})
    r = app.verifier(d, pages)
    vt2 = critere(r, "valeur technique")
    assert [norm(s["libelle"]) for s in vt2["sous_criteres"]].count("démarche qualité") == 0
    assert len(vt2["sous_criteres"]) == 3


def test_A158_page_du_sous_critere():
    d = analyse([COUV, NEUTRE, CRIT_PCT])
    assert sous(critere(d, "valeur technique"), "planning")["pages"] == [3]


# ---------------------------------------------------------------- pondérations

def test_A23_type_pourcentage():
    d = analyse([COUV, CRIT_PCT])
    assert un(d["type_ponderation"], "type pondération")["valeur"] == "pourcentage"


def test_A24_type_points():
    d = analyse([COUV, CRIT_POINTS])
    assert un(d["type_ponderation"], "type pondération")["valeur"] == "points"


def test_A25_type_classement():
    d = analyse([COUV, CRIT_CLASSEMENT])
    assert un(d["type_ponderation"], "type pondération")["valeur"] == "classement"


def test_A25_trou_liste_sans_ordre_ni_valeur():
    page = ("ARTICLE 8\nLes offres seront jugées sur les critères suivants :\n"
            "- Valeur technique\n- Prix\n")
    d = analyse([COUV, page])
    absent(d["type_ponderation"], "type pondération")
    absent(critere(d, "valeur technique")["ponderation"], "pondération")


def test_A144_ponderation_en_pourcentage():
    d = analyse([COUV, CRIT_PCT])
    v = un(critere(d, "valeur technique")["ponderation"], "pondération")
    assert (v["valeur"], v["unite"], v["lot"]) == (60, "pourcentage", None)


@pytest.mark.parametrize("vt,px,a,b", [
    ("47,5 %", "52,5%", 47.5, 52.5),
    ("55 %", "45 pour cent", 55, 45),
])
def test_A144_pourcentages_formats(vt, px, a, b):
    page = f"ARTICLE 8\nCritères de jugement :\n- Valeur technique : {vt}\n- Prix : {px}\n"
    d = analyse([COUV, page])
    assert un(critere(d, "valeur technique")["ponderation"], "p")["valeur"] == a
    assert un(critere(d, "prix")["ponderation"], "p")["valeur"] == b


def test_A145_ponderation_en_points():
    d = analyse([COUV, CRIT_POINTS])
    v = un(critere(d, "prix")["ponderation"], "pondération")
    assert (v["valeur"], v["unite"]) == (40, "points")
    v = un(critere(d, "valeur technique")["ponderation"], "pondération")
    assert (v["valeur"], v["unite"]) == (60, "points")


def test_A146_rang_comme_ponderation():
    d = analyse([COUV, CRIT_CLASSEMENT])
    v = un(critere(d, "valeur technique")["ponderation"], "pondération")
    assert (v["valeur"], v["unite"]) == (1, "rang")
    v = un(critere(d, "prix")["ponderation"], "pondération")
    assert (v["valeur"], v["unite"]) == (2, "rang")


def test_A147_ponderation_en_lettres():
    page = ("ARTICLE 8\nCritères de jugement :\n1. Valeur technique : soixante pour cent\n"
            "2. Prix : quarante pour cent\n")
    d = analyse([COUV, page])
    assert un(critere(d, "valeur technique")["ponderation"], "p")["valeur"] == 60
    assert un(critere(d, "prix")["ponderation"], "p")["valeur"] == 40


def test_A148_critere_sans_ponderation():
    page = ("ARTICLE 8\nCritères de jugement :\n1. Valeur technique : 60 %\n2. Prix : 40 %\n"
            "3. Délai d'exécution\n")
    d = analyse([COUV, page])
    absent(critere(d, "délai")["ponderation"], "pondération du délai")
    assert un(critere(d, "prix")["ponderation"], "p")["valeur"] == 40


def test_A149_meme_ponderation_deux_pages():
    d = analyse([COUV, CRIT_SIMPLE, NEUTRE, NEUTRE, RAPPEL_SIMPLE])
    v = un(critere(d, "valeur technique")["ponderation"], "pondération")
    assert v["valeur"] == 60
    assert sorted(v["pages"]) == [2, 5]


RAPPEL_70 = ("ANNEXE 2 – RAPPEL DES CRITÈRES D'ATTRIBUTION\n"
             "1. Valeur technique : 70 %\n2. Prix : 30 %\n")


def test_A150_deux_ponderations_meme_lot():
    d = analyse([COUV, CRIT_SIMPLE, NEUTRE, RAPPEL_70])
    assert sorted(vals(critere(d, "valeur technique")["ponderation"])) == [60, 70]


def test_A151_deux_ponderations_meme_lot_conflit():
    d = analyse([COUV, CRIT_SIMPLE, NEUTRE, RAPPEL_70])
    assert critere(d, "valeur technique")["ponderation"]["conflit"] is True
    assert critere(d, "prix")["ponderation"]["conflit"] is True


def test_A152_trou_verifier_ponderation_fabriquee():
    page = ("ARTICLE 8\nCritères de jugement :\n1. Valeur technique : 60 %\n2. Prix : 40 %\n"
            "3. Délai d'exécution\n")
    pages = [COUV, page]
    d = copy.deepcopy(analyse(pages))
    dl = [c for c in d["criteres"]["liste"] if norm(c["libelle"]).startswith("délai")][0]
    dl["ponderation"] = {"statut": TROUVE, "conflit": False,
                         "valeurs": [{"valeur": 25, "unite": "pourcentage", "lot": None, "pages": [2]}]}
    r = app.verifier(d, pages)
    absent(critere(r, "délai")["ponderation"], "pondération fabriquée")


def test_A153_page_de_la_ponderation():
    d = analyse([COUV, NEUTRE, CRIT_SIMPLE])
    assert un(critere(d, "valeur technique")["ponderation"], "p")["pages"] == [3]


def test_A26_ponderation_par_lot():
    d = analyse([COUV, LOTS2, CRIT_PAR_LOT])
    assert len([c for c in criteres(d) if norm(c["libelle"]) == "valeur technique"]) == 1
    assert pond(critere(d, "valeur technique")) == [(30, 2), (60, 1)]
    assert pond(critere(d, "prix")) == [(40, 1), (70, 2)]


def test_A162_ponderations_par_lot_sans_conflit():
    d = analyse([COUV, LOTS2, CRIT_PAR_LOT])
    assert critere(d, "valeur technique")["ponderation"]["conflit"] is False
    assert critere(d, "prix")["ponderation"]["conflit"] is False


# ---------------------------------------------------------------- lot critère

def test_A159_memes_criteres_tous_lots():
    page = ("ARTICLE 8 – JUGEMENT DES OFFRES\n"
            "Les critères ci-dessous s'appliquent à l'ensemble des lots :\n"
            "1. Valeur technique : 60 %\n2. Prix : 40 %\n")
    d = analyse([COUV, LOTS2, page])
    for c in criteres(d):
        assert vals(c["lot"]) == ["tous les lots"], f"{c['libelle']} : obtenu {c['lot']!r}"


def test_A159_trou_ponderation_par_lot_tous_les_lots():
    d = analyse([COUV, LOTS2, CRIT_PAR_LOT])
    assert vals(critere(d, "valeur technique")["lot"]) == ["tous les lots"]


def test_A160_critere_reserve_a_un_lot():
    d = analyse([COUV, LOTS2, CRIT_RESERVE])
    assert vals(critere(d, "valeur technique")["lot"]) == [1], f"obtenu {critere(d, 'valeur technique')['lot']!r}"


def test_A161_lot_unique():
    d = analyse([COUV, "Le marché comporte un lot unique : réhabilitation thermique de l'école.\n", CRIT_SIMPLE])
    assert len(lots(d)) == 1
    n = lots(d)[0]["numero"]
    for c in criteres(d):
        assert vals(c["lot"]) == [n], f"{c['libelle']} : attendu le lot unique {n!r}, obtenu {c['lot']!r}"


# ================================================================= PLAN

def test_A27_section_valeur_technique():
    d = analyse([COUV, CRIT_SIMPLE])
    assert len(sections_de(d, "valeur technique")) >= 1, f"plan : {d['plan']!r}"


def test_A28_aucune_section_prix():
    d = analyse([COUV, CRIT_SIMPLE])
    assert sections_de(d, "prix") == [], f"plan : {d['plan']!r}"
    d = analyse([COUV, CRIT_PCT])
    assert sections_de(d, "prix") == [], f"plan : {d['plan']!r}"


def test_A29_section_par_sous_critere():
    d = analyse([COUV, CRIT_PCT])
    vt = critere(d, "valeur technique")
    ss = [s for s in d["plan"] if s["sous_critere"] is not None]
    assert sorted(s["sous_critere"] for s in ss) == sorted(x["libelle"] for x in vt["sous_criteres"]), f"plan : {d['plan']!r}"
    for s in ss:
        assert s["critere"] == vt["libelle"]


def test_A30_ordre_des_sections():
    page = ("ARTICLE 8\nCritères :\n1. Valeur technique : 60 %\n"
            "   a) Planning d'intervention : 10 %\n"
            "   b) Méthodologie d'exécution : 30 %\n"
            "   c) Moyens affectés : 20 %\n"
            "2. Prix : 40 %\n")
    d = analyse([COUV, page])
    ordre = [norm(s["sous_critere"]).split()[0] for s in d["plan"] if s["sous_critere"]]
    assert ordre == ["planning", "méthodologie", "moyens"], f"obtenu {ordre!r}"


def test_A31_ponderation_section():
    d = analyse([COUV, CRIT_SIMPLE])
    for s in sections_de(d, "valeur technique"):
        assert s["ponderation"] == 60, f"obtenu {s!r}"


def test_A31_trou_section_sous_critere_ponderation_propre():
    d = analyse([COUV, CRIT_PCT])
    attendu = {"méthodologie": 30, "moyens": 20, "planning": 10}
    for s in d["plan"]:
        if s["sous_critere"]:
            assert s["ponderation"] == attendu[norm(s["sous_critere"]).split()[0]], f"obtenu {s!r}"


def test_A32_page_source():
    d = analyse([COUV, NEUTRE, CRIT_SIMPLE])
    ss = sections_de(d, "valeur technique")
    assert ss and all(s["page_source"] == 3 for s in ss), f"obtenu {ss!r}"


def test_A33_sections_sans_texte_redige():
    d = analyse([COUV, CRIT_PCT])
    assert d["plan"], "plan vide"
    for s in d["plan"]:
        assert s["contenu"] == "", f"une section ne contient aucun texte rédigé, obtenu {s!r}"


# ================================================================= CONTRÔLE

def test_A34_trou_controler_section_retiree():
    d = analyse([COUV, CRIT_SIMPLE])
    assert "critère sans section" not in [a["type"] for a in app.controler(d)]
    d2 = copy.deepcopy(d)
    d2["plan"] = [s for s in d2["plan"] if not norm(s["critere"]).startswith("valeur technique")]
    types = [a["type"] for a in app.controler(d2)]
    assert "critère sans section" in types, f"obtenu {types!r}"


def test_A35_ponderations_incoherentes():
    page = ("ARTICLE 8\nCritères :\n1. Valeur technique : 60 %\n"
            "  1.1 Méthodologie : 30 %\n  1.2 Moyens humains : 20 %\n2. Prix : 40 %\n")
    d = analyse([COUV, page])
    assert "pondérations incohérentes" in types_alertes(d), f"obtenu {types_alertes(d)!r}"
    assert "total différent de 100 %" not in types_alertes(d)


def test_A36_total_different_de_100():
    page = "ARTICLE 8\nCritères :\n1. Valeur technique : 60 %\n2. Prix : 30 %\n"
    d = analyse([COUV, page])
    assert "total différent de 100 %" in types_alertes(d), f"obtenu {types_alertes(d)!r}"


def test_A36_trou_somme_par_lot():
    d = analyse([COUV, LOTS2, CRIT_PAR_LOT])
    assert "total différent de 100 %" not in types_alertes(d), f"obtenu {types_alertes(d)!r}"


def test_A37_classement_sans_alerte_de_somme():
    d = analyse([COUV, CRIT_CLASSEMENT])
    t = types_alertes(d)
    assert "total différent de 100 %" not in t and "pondérations incohérentes" not in t, f"obtenu {t!r}"


def test_A38_aucune_alerte():
    d = analyse([COUV, CRIT_PCT])
    assert d["controle"]["alertes"] == [], f"obtenu {d['controle']!r}"
    assert app.controler(d) == []
    d = analyse([COUV, CRIT_POINTS])
    assert d["controle"]["alertes"] == [], f"obtenu {d['controle']!r}"


# ================================================================= PAGE VALEUR / CONFLITS

def test_A39_page_valeur():
    d = analyse([COUV, DL, PROC_ADAPTEE])
    assert un(d["date_limite"], "date limite")["pages"] == [2]
    assert un(d["procedure"], "procédure")["pages"] == [3]


def test_A40_valeur_sur_deux_pages():
    d = analyse([PROC_ADAPTEE, NEUTRE, "ANNEXE\nRappel : procédure adaptée.\n"])
    assert sorted(un(d["procedure"], "procédure")["pages"]) == [1, 3]


def test_A40_trou_pages_ordre_croissant():
    d = analyse([PROC_ADAPTEE, NEUTRE, "ANNEXE\nRappel : procédure adaptée.\n"])
    assert un(d["procedure"], "procédure")["pages"] == [1, 3]


def test_A41_non_trouve_sans_page():
    d = analyse([COUV, NEUTRE])
    for cle in ["date_limite", "heure_limite", "date_questions", "procedure", "visite_obligatoire",
                "dates_visite", "variantes", "validite_offres", "mode_remise", "limite_pages",
                "type_ponderation"]:
        absent(d[cle], cle)
        assert d[cle]["conflit"] is False, f"{cle} : aucun conflit sur un fait non trouvé"


def test_A42_meme_valeur_deux_pages_sans_conflit():
    d = analyse([COUV, DL, PROC_ADAPTEE, "ANNEXE\nDate limite de réception des offres : 14/03/2025 à 12h00.\n"
                 "Rappel : procédure adaptée.\n"])
    assert d["date_limite"]["conflit"] is False
    assert d["heure_limite"]["conflit"] is False
    assert d["procedure"]["conflit"] is False
