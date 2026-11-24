"""Tests de non-régression — sonde P12, lot 5.

Chaque test reproduit un cas où une implémentation passant les tests existants
s'est trompée, alors que la spec tranchait déjà. Interface utilisée : app.analyser.
"""
import json

import app


def _fait_vide():
    return {"statut": "non trouvé", "valeurs": [], "conflit": False}


# ---------------------------------------------------------------------------
# Cas 1 — A39 / C05 : page valeur du lot critère en lot unique sans numéro
# ---------------------------------------------------------------------------

PAGES_LOT_UNIQUE_SANS_NUMERO = [
    "COMMUNAUTÉ DE COMMUNES DU PAYS DE PONT-DE-MÉRY\n\nMARCHÉ PUBLIC DE TRAVAUX\n\n"
    "RÈGLEMENT DE LA CONSULTATION (R.C.)\n\n"
    "Objet : Construction d'un gymnase de Pont-de-Méry\nRéférence : 2026-MAPA-16\n\n"
    "Date et heure limites de réception des offres : 11 mai 2026 à 10h00\n\n"
    "ARTICLE 1 – OBJET DE LA CONSULTATION\n\n"
    "La présente consultation concerne : Construction d'un gymnase de Pont-de-Méry.\n"
    "Le marché n'est pas alloti : il fait l'objet d'un lot unique.\n\n"
    "ARTICLE 2 – PROCÉDURE\n\n"
    "La présente consultation est passée selon la procédure adaptée en application des "
    "articles L2123-1 et R2123-1 du Code de la commande publique.\n\n"
    "Article 3 : Dispositions relatives aux offres\n\n"
    "Les variantes à l'initiative du candidat sont interdites.\n\n"
    "Article 4 : Critères d'attribution\n\n"
    "L'offre économiquement la plus avantageuse sera appréciée en fonction des critères suivants :\n\n"
    "RC – 1/2\n",
    "\nCritères | Pondération\n"
    "1. Prix | pondération : 40 %\n"
    "2. Valeur technique | pondération : 40 %\n"
    "3. Performances en matière de protection de l'environnement | 10%\n"
    "4. Planning prévisionnel | 10%\n\n\n"
    "Article 5 : Modalités de remise des plis\n\n"
    "La remise des plis se fait exclusivement par voie dématérialisée.\n"
    "Les plis doivent parvenir avant le 11.05.2026 à 10h00.\n\n\nRC – 2/2\n",
]


def test_A39_reg_lot_critere_page_valeur_est_la_page_qui_declare_le_lot_unique():
    d = app.analyser(PAGES_LOT_UNIQUE_SANS_NUMERO)
    criteres = d["criteres"]["liste"]
    assert len(criteres) == 4, (
        f"4 critères attendus, obtenu {[c['libelle'] for c in criteres]}"
    )
    attendu = {"statut": "trouvé", "valeurs": [{"valeur": None, "pages": [1]}], "conflit": False}
    for c in criteres:
        assert c["lot"] == attendu, (
            f"Critère {c['libelle']!r} : le lot unique sans numéro est déclaré en page 1 "
            f"(« Le marché n'est pas alloti »), la page 2 ne parle d'aucun lot ; "
            f"lot critère attendu {attendu}, obtenu {c['lot']}"
        )


# ---------------------------------------------------------------------------
# Cas 2 et 3 — A07 : procédure nommée en toutes lettres (« procédure avec négociation »)
# ---------------------------------------------------------------------------

PAGES_NEGOCIATION = [
    "COMMUNE DE MARSOLLE\n\nMARCHÉ PUBLIC DE TRAVAUX\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\n"
    "Objet : Aménagement de la place du marché de Marsolle\nRéférence : 2025-TX-17\n\n"
    "Date et heure limites de réception des offres : 05.10.2026 à 17 h 30\n\n"
    "ARTICLE 1 – OBJET DE LA CONSULTATION\n\n"
    "Le marché n'est pas alloti : il fait l'objet d'un lot unique.\n\n"
    "Article 2 : Procédure\n\n"
    "La présente consultation est passée selon la procédure avec négociation en application "
    "de l'article R2124-3 du Code de la commande publique.\n\n"
    "Article 3 : Dispositions relatives aux offres\n\n"
    "Les variantes à l'initiative du candidat sont interdites.\n"
    "Délai de validité des offres : 4 mois.\n\nRC – 1/2\n",
    "ARTICLE 4 – JUGEMENT DES OFFRES\n\n"
    "Les critères sont classés par ordre décroissant d'importance :\n"
    "  1. Coût\n  2. Valeur technique\n\n"
    "Article 5 : Conditions d'envoi et de remise des offres\n\n"
    "Les offres sont transmises par voie électronique.\n"
    "Les plis doivent parvenir avant le 05.10.2026 à 17 h 30.\n\n\nRC – 2/2\n",
]


def test_A07_reg_procedure_avec_negociation_en_toutes_lettres_est_trouvee():
    d = app.analyser(PAGES_NEGOCIATION)
    proc = d["procedure"]
    assert proc["statut"] == "trouvé", (
        f"La page 1 nomme « la procédure avec négociation » ; statut attendu 'trouvé', "
        f"obtenu {proc['statut']!r} ({proc})"
    )
    assert proc["valeurs"] == [{"valeur": "procédure avec négociation", "pages": [1]}], (
        f"Valeurs attendues [{{'valeur': 'procédure avec négociation', 'pages': [1]}}], "
        f"obtenu {proc['valeurs']}"
    )
    assert proc["conflit"] is False, f"Aucun conflit attendu, obtenu {proc}"


# ---------------------------------------------------------------------------
# Cas 4, 7, 8 — critères en points, sous-critères A à D, barème en pourcentages,
# critères de sélection des candidatures sur la même page
# ---------------------------------------------------------------------------

PAGE_GARDE = (
    "Pouvoir adjudicateur :\n   Commune de Sainte-Marguerite-sur-Mer\n\n"
    "   REGLEMENT DE CONSULTATION\n\n"
    "   DATE ET HEURE DE REMISE DES OFFRES\n   Le lundi 23 février 2026 à 14h\n\f"
)

PAGE_LOT = (
    "ARTICLE 1 - ETENDUE DE LA CONSULTATION\n\n"
    "Le marché est décomposé en 1 lot unique :\n"
    "   Lot n°1        Maçonnerie\n\f"
)

PAGE_JUGEMENT_AVEC_CANDIDATURES = (
    "ARTICLE 7 - SELECTION DES CANDIDATURES ET JUGEMENT DES OFFRES\n\n"
    "7.1 Sélection des candidatures\n"
    "Les critères de sélection des candidatures sont les suivants :\n"
    "  - Garanties et capacités techniques et financières\n"
    "  - Capacités professionnelles\n\n"
    "7.2 Jugement des offres\n"
    "Les critères de jugement des offres sont les suivants :\n\n"
    "1 - Valeur technique : 60 points\n"
    "   A - Méthodologie d'intervention sur les maçonneries anciennes : 20 points\n"
    "   B - Moyens humains affectés au chantier : 10 points\n"
    "   C - Moyens matériels affectés au chantier : 10 points\n"
    "   D - Planning détaillé d'exécution : 20 points\n"
    "2 - Prix des prestations : 40 points\n\f"
)

PAGE_JUGEMENT_POINTS_BAREME = (
    "ARTICLE 7 - JUGEMENT DES OFFRES\n\n"
    "Les critères de jugement des offres sont les suivants :\n\n"
    "1 - Valeur technique : 60 points\n"
    "   A - Méthodologie d'intervention sur les maçonneries anciennes : 20 points\n"
    "   B - Moyens humains affectés au chantier : 10 points\n"
    "   C - Moyens matériels affectés au chantier : 10 points\n"
    "   D - Planning détaillé d'exécution : 20 points\n"
    "2 - Prix des prestations : 40 points\n\n"
    "Chaque élément de la valeur technique est noté selon le barème suivant :\n"
    "   Très satisfaisant : 100% des points\n"
    "   Satisfaisant, moyen ou passable : 75%, 50% ou 25 % des points\n"
    "   Insuffisant : 0 point\n\f"
)


def test_A28_reg_prix_sans_section_meme_apres_criteres_de_selection_des_candidatures():
    pages = [PAGE_GARDE, PAGE_LOT, PAGE_JUGEMENT_AVEC_CANDIDATURES]
    d = app.analyser(pages)
    fautives = [
        s for s in d["plan"]
        if "prix" in (s["critere"] or "").lower()
        or "prix" in (s["sous_critere"] or "").lower()
        or "prix" in (s["titre"] or "").lower()
    ]
    assert fautives == [], (
        "Le critère « Prix des prestations : 40 points » porte sur le prix : "
        f"aucune section attendue pour lui, obtenu {json.dumps(fautives, ensure_ascii=False)}"
    )


def test_A38_reg_points_coherents_bareme_en_pourcentages_aucune_alerte():
    pages = [PAGE_GARDE, PAGE_LOT, PAGE_JUGEMENT_POINTS_BAREME]
    d = app.analyser(pages)
    alertes = d["controle"]["alertes"]
    assert alertes == [], (
        "Critères en points (60 + 40), sous-critères 20 + 10 + 10 + 20 = 60, la valeur "
        "technique a sa section, les pourcentages ne sont que dans le barème : aucune alerte "
        f"attendue, obtenu {alertes}"
    )


def test_A24_reg_ponderation_en_points_bareme_en_pourcentages_type_points():
    pages = [PAGE_GARDE, PAGE_LOT, PAGE_JUGEMENT_POINTS_BAREME]
    d = app.analyser(pages)
    tp = d["type_ponderation"]
    valeurs = [v["valeur"] for v in tp["valeurs"]]
    assert "pourcentage" not in valeurs, (
        "Les pourcentages (« 100% des points », « 75%, 50% ou 25 % des points ») ne sont "
        f"que le barème de notation ; 'pourcentage' ne doit pas figurer, obtenu {tp}"
    )
    assert valeurs == ["points"], (
        f"Critères pondérés en points : type pondération attendu ['points'], obtenu {tp}"
    )
    assert tp["conflit"] is False, f"Aucun conflit attendu, obtenu {tp}"


# ---------------------------------------------------------------------------
# Cas 5 et 6 — C13 : renvoi à l'heure de la page de garde sans écrire d'heure
# ---------------------------------------------------------------------------

PAGES_RENVOI_HEURE = [
    "         RÈGLEMENT DE LA CONSULTATION\n                 (R.C.)\n\n"
    "   Travaux de restauration du bâti en pierre sèche\n\n"
    "   Lot unique n°01 — Pierres sèches\n\n"
    "   Date et heure limites de réception des offres\n"
    "        Le 28 août 2026 à 8h00\n\n\n                     1\n\f",
    "SOMMAIRE\n"
    "Article 1 — Objet de la consultation ........................ 3\n"
    "Article 7 — Conditions d'envoi et de remise des offres ...... 9\n"
    "   7.1 — Date et heure limites de réception des offres ...... 9\n\f",
    "Article 1 — Objet de la consultation\n\n"
    "Travaux de restauration du bâti en pierre sèche.\n\n                     3\n\f",
    "Article 7 — Conditions d'envoi et de remise des offres\n\n"
    "7.1 — Date et heure limites de réception des offres\n"
    "Les offres doivent parvenir avant la date et l'heure limites indiquées en page de "
    "garde (page 1) du présent règlement.\n"
    "Les offres sont transmises par voie électronique.\n\n                     9\n\f",
]


def test_C13_reg_renvoi_a_la_page_de_garde_ne_cree_ni_heure_ni_conflit():
    d = app.analyser(PAGES_RENVOI_HEURE)
    hl = d["heure_limite"]
    attendu = {"statut": "trouvé", "valeurs": [{"valeur": "08:00", "pages": [1]}], "conflit": False}
    assert hl == attendu, (
        "Seule la page 1 écrit l'heure (« 8h00 ») ; les pages 2 et 4 ne font qu'y renvoyer "
        f"sans écrire d'heure. Attendu {attendu}, obtenu {hl}"
    )


# ---------------------------------------------------------------------------
# Cas 9 — A67 : voie des questions sans date ; délai « X jours avant » sur les
# modifications du dossier par l'acheteur
# ---------------------------------------------------------------------------

PAGES_QUESTIONS_SANS_DATE = [
    "RÈGLEMENT DE LA CONSULTATION\n\nMARCHÉ PUBLIC DE TRAVAUX\n\n"
    "AMENAGEMENT DE CHAUSSEE ET DE TROTTOIRS\n\n"
    "DATE LIMITE OBLIGATOIRE DE RECEPTION DES OFFRES :\n"
    "VENDREDI 13 FEVRIER 2026 A 12H00\n"
    "Plis envoyés uniquement par voie dématérialisée sur https://www.xmarches.fr/\n\f",
    "ARTICLE 3 - MODIFICATIONS DE DETAIL AU DOSSIER DE CONSULTATION\n\n"
    "L'acheteur se réserve le droit d'apporter au plus tard 6 jours avant la date limite de "
    "réception des offres des modifications de détail au dossier de consultation. "
    "Les candidats devront alors répondre sur la base du dossier modifié.\n\n"
    "ARTICLE 4 - RENSEIGNEMENTS COMPLEMENTAIRES\n\n"
    "Pour obtenir tous les renseignements complémentaires, les candidats transmettent leurs "
    "questions exclusivement par l'intermédiaire du profil acheteur https://www.xmarches.fr/.\n\f",
]


def test_A67_reg_questions_sans_date_ni_delai_date_questions_non_trouvee():
    d = app.analyser(PAGES_QUESTIONS_SANS_DATE)
    dq = d["date_questions"]
    assert dq == _fait_vide(), (
        "Le RC dit seulement par quelle voie poser les questions ; le délai « 6 jours avant la "
        "date limite de réception des offres » concerne les modifications du dossier par "
        f"l'acheteur. Attendu {_fait_vide()}, obtenu {dq}"
    )
