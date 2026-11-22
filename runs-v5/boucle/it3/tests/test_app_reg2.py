"""Tests de non-régression — sonde P12, deuxième lot.

Chaque test reproduit un cas où des implémentations passant les tests existants
se sont trompées, alors que la spécification tranchait déjà.
"""

import app


# ---------------------------------------------------------------------------
# Cas 1 et 2 (A10) : deux dates de visite, l'une en chiffres, l'autre en lettres
# ---------------------------------------------------------------------------

RC_VISITE_DEUX_DATES = [
    "COMMUNAUTÉ DE COMMUNES DU PAYS DE SAINT-AUBERT-SUR-LOUE\n\nMARCHÉ PUBLIC DE TRAVAUX\n\n"
    "RÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Extension du groupe scolaire de Saint-Aubert-sur-Loue\n"
    "Référence : 2026-T-16\n\nDate et heure limites de réception des offres : vendredi 9 octobre 2026 à 11:00\n\n"
    "Article 1 : Objet de la consultation\n\nLa présente consultation concerne : Extension du groupe scolaire de "
    "Saint-Aubert-sur-Loue.\nLes travaux sont traités en lot unique.\n\nARTICLE 2 – PROCÉDURE\n\n"
    "La présente consultation est passée selon la procédure adaptée ouverte.\n\n"
    "ARTICLE 3 – CONFIDENTIALITÉ ET DONNÉES PERSONNELLES\n\nLes informations transmises par les candidats sont "
    "traitées dans le respect du secret des affaires. Les données à caractère personnel recueillies sont utilisées "
    "aux seules fins de la passation du marché.\n\nARTICLE 4 – DISPOSITIONS RELATIVES AUX OFFRES\n\n"
    "Les variantes sont autorisées.\n\nARTICLE 5 – VISITE DU SITE\n\nLa visite des lieux est facultative.\n"
    "Elle aura lieu aux dates suivantes : 15/09/2026, mardi 22 septembre 2026.\n"
    "Les candidats prennent rendez-vous auprès des services techniques au 01 23 45 43 38.\n\n"
    "ARTICLE 6 – CONTENU DU DOSSIER À REMETTRE\n\nLes candidats remettent un dossier comprenant les pièces "
    "suivantes, datées et signées :\n\n1) Au titre de la candidature :\n  - Déclaration du candidat (formulaire DC2)\n"
    "  - Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité\n\n"
    "2) Au titre de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Mémoire technique de 15 pages au plus\n"
    "  - Attestation de visite\n\nArticle 7 : Jugement des offres\n\nLe jugement des offres sera effectué selon les "
    "critères pondérés suivants :\n\nCritère n° 1 : Mérite technique (40%)\nCritère n° 2 : Prix de l'offre (60 %)\n\n\n"
    "ARTICLE 8 – CONDITIONS D'ENVOI ET DE REMISE DES OFFRES\n\nLa remise des plis se fait exclusivement par voie "
    "dématérialisée, sur le site https://www.e-marchespublics.com.\nAucune offre papier ne sera acceptée.\n"
    "Les plis doivent parvenir avant le 09.10.2026 à 11:00.\n\nARTICLE 9 – QUESTIONS DES CANDIDATS\n\n"
    "Les candidats peuvent poser leurs questions par écrit sur la plateforme au plus tard le 29/09/2026 à 12h00.\n"
    "Une réponse sera communiquée à tous les candidats.\n\n\nRC – 1/1\n"
]


def test_A10_reg_dates_visite_chiffres_et_lettres_sur_une_ligne():
    d = app.analyser(RC_VISITE_DEUX_DATES)
    dv = d["dates_visite"]
    assert dv["statut"] == "trouvé", (
        f"A10 : la page 1 indique deux dates de visite (15/09/2026 et mardi 22 septembre 2026) ; "
        f"statut attendu « trouvé », obtenu {dv['statut']!r}"
    )
    attendu = [
        {"valeur": "15/09/2026", "pages": [1]},
        {"valeur": "22/09/2026", "pages": [1]},
    ]
    assert dv["valeurs"] == attendu, (
        f"A10 : dates visite attendues {attendu}, obtenues {dv['valeurs']}"
    )


# ---------------------------------------------------------------------------
# Cas 3 (A31) : cellule de tableau « noté sur 7 points »
# ---------------------------------------------------------------------------

RC_NOTE_SUR_7_POINTS = [
    "OFFICE PUBLIC DE L'HABITAT DE LAVERGNE-LES-PINS\n\nMARCHÉ PUBLIC DE TRAVAUX\n\n"
    "RÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Restauration de l'église Saint-Martin de Lavergne-les-Pins\n"
    "Référence : 2025-MAPA-60\n\nDate et heure limites de réception des offres : 23/11/2026 à 10 heures\n\n"
    "Article 1 : Objet de la consultation\n\nLa présente consultation concerne : Restauration de l'église "
    "Saint-Martin de Lavergne-les-Pins.\nLe marché est passé en un lot unique, l'allotissement n'étant pas "
    "pertinent pour cette opération.\n\nArticle 2 : Procédure\n\nLa présente consultation est passée selon la "
    "procédure adaptée (MAPA).\n\nARTICLE 3 – RECOURS\n\nLe tribunal administratif territorialement compétent peut "
    "être saisi d'un référé précontractuel avant la signature du marché, ou d'un recours en contestation de "
    "validité dans un délai de deux mois à compter de la publicité de l'attribution.\n\n"
    "ARTICLE 4 – DISPOSITIONS RELATIVES AUX OFFRES\n\nLes offres restent valables pendant 90 jours à compter de la "
    "date limite de remise.\n\nARTICLE 5 – CONTENU DU DOSSIER À REMETTRE\n\nLes candidats remettent un dossier "
    "comprenant les pièces suivantes, datées et signées :\n\n1) Au titre de la candidature :\n"
    "  - Pouvoir de la personne habilitée à engager le candidat\n"
    "  - Déclaration indiquant les effectifs moyens annuels du candidat\n"
    "  - Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité\n\n"
    "2) Au titre de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Attestation de visite\n"
    "  - Décomposition du prix global et forfaitaire (DPGF)\n  - Bordereau des prix unitaires (BPU)\n"
    "  - Mémoire technique\n\nLe candidat auquel il est envisagé d'attribuer le marché produira dans un délai de "
    "8 jours :\n  - Attestations de régularité fiscale et sociale\n\nArticle 6 : Critères d'attribution\n\n"
    "L'offre économiquement la plus avantageuse sera appréciée en fonction des critères suivants :\n\nRC – 1/2\n",
    "\nCritères | Pondération\n1. Valeur technique de l'offre | noté sur 7 points\n2. Prix de l'offre | 3 points\n\n"
    "La note finale est la somme des notes obtenues pour chaque critère.\n\n"
    "ARTICLE 7 – CONDITIONS D'ENVOI ET DE REMISE DES OFFRES\n\nLes offres sont transmises par voie électronique "
    "sur la plateforme PLACE (https://www.marches-publics.gouv.fr).\nAucune offre papier ne sera acceptée.\n"
    "Les plis doivent parvenir avant le 23/11/2026 à 10 heures.\n\nARTICLE 8 – RENSEIGNEMENTS COMPLÉMENTAIRES\n\n"
    "Les candidats peuvent poser leurs questions par écrit sur la plateforme au plus tard le dimanche 8 novembre "
    "2026.\nUne réponse sera communiquée à tous les candidats.\n\n\nRC – 2/2\n",
]


def test_A31_reg_ponderation_note_sur_N_points_dans_un_tableau():
    d = app.analyser(RC_NOTE_SUR_7_POINTS)
    sections = [s for s in d["plan"] if s["critere"].startswith("Valeur technique")]
    assert len(sections) == 1, (
        f"A27/A31 : une section attendue pour le critère « Valeur technique de l'offre », "
        f"obtenu plan = {d['plan']}"
    )
    s = sections[0]
    assert s["ponderation"] == 7, (
        f"A31 : la cellule « noté sur 7 points » fixe la pondération du critère technique à 7 ; "
        f"pondération de section attendue 7, obtenue {s['ponderation']!r} (section {s})"
    )
    assert s["sous_critere"] is None and s["page_source"] == 2 and s["contenu"] == "", (
        f"A31/A32/A33 : section attendue sans sous-critère, page_source 2, contenu vide ; obtenu {s}"
    )


# ---------------------------------------------------------------------------
# Cas 4 (A118) : la page 2 parle d'une plateforme pour les questions seulement
# ---------------------------------------------------------------------------

RC_MODE_REMISE_PAGE_1 = [
    "COMMUNAUTÉ DE COMMUNES DU PAYS DE MARSOLLE\n\nMARCHÉ PUBLIC DE TRAVAUX\n\n"
    "RÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Réfection de la voirie communale de Marsolle\n"
    "Référence : 2026-MAPA-32\n\nDate et heure limites de réception des offres : 17.08.2026 à 11:00\n\n"
    "ARTICLE 1 – OBJET DE LA CONSULTATION\n\nLa présente consultation concerne : Réfection de la voirie communale "
    "de Marsolle.\nLe marché est passé en un lot unique, l'allotissement n'étant pas pertinent pour cette "
    "opération.\n\nARTICLE 2 – PROCÉDURE\n\nLa présente consultation est passée selon la procédure adaptée (MAPA).\n\n"
    "Article 3 : Confidentialité et données personnelles\n\nLes informations transmises par les candidats sont "
    "traitées dans le respect du secret des affaires. Les données à caractère personnel recueillies sont utilisées "
    "aux seules fins de la passation du marché.\n\nArticle 4 : Dispositions relatives aux offres\n\n"
    "Les candidats peuvent présenter des variantes à l'initiative du candidat.\n\n"
    "ARTICLE 5 – CONTENU DU DOSSIER À REMETTRE\n\nLes candidats remettent un dossier comprenant les pièces "
    "suivantes, datées et signées :\n\n1) Au titre de la candidature :\n"
    "  - Pouvoir de la personne habilitée à engager le candidat\n"
    "  - Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité\n"
    "  - Déclaration du candidat (formulaire DC2)\n  - Liste des travaux exécutés au cours des cinq dernières années\n\n"
    "2) Au titre de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Mémoire technique\n"
    "  - Attestation de visite\n  - Décomposition du prix global et forfaitaire (DPGF)\n"
    "  - Planning prévisionnel d'exécution\n\nLe candidat auquel il est envisagé d'attribuer le marché produira "
    "dans un délai de 8 jours :\n  - Liste nominative des salariés étrangers\n  - Extrait Kbis de moins de trois mois\n"
    "  - Attestations de régularité fiscale et sociale\n\nArticle 6 : Jugement des offres\n\nL'offre économiquement "
    "la plus avantageuse sera appréciée en fonction des critères suivants :\n\nCritères | Pondération\n"
    "1. Valeur technique | 30 pts\n2. Prix des prestations | 24 pts\n3. Planning prévisionnel | 6 pts\n\n"
    "La note finale est la somme des notes obtenues pour chaque critère.\n\nARTICLE 7 – MODALITÉS DE REMISE DES PLIS\n\n"
    "Les offres sont transmises par voie électronique sur le profil d'acheteur https://achats.marsolle-public.fr.\n"
    "Aucune offre papier ne sera acceptée.\n\nRC – 1/2\n",
    "Les plis doivent parvenir avant le 17 août 2026 à 11 heures.\n\nARTICLE 8 – RENSEIGNEMENTS COMPLÉMENTAIRES\n\n"
    "Les candidats peuvent poser leurs questions par écrit sur la plateforme au plus tard le 7 août 2026.\n"
    "Une réponse sera communiquée à tous les candidats.\n\n\nRC – 2/2\n",
]


def test_A118_reg_plateforme_des_questions_n_est_pas_un_mode_de_remise():
    d = app.analyser(RC_MODE_REMISE_PAGE_1)
    attendu = [{"valeur": "électronique", "pages": [1]}]
    assert d["mode_remise"]["valeurs"] == attendu, (
        f"A118 : seule la page 1 nomme le mode de remise (la page 2 ne parle de plateforme que pour les "
        f"questions) ; attendu {attendu}, obtenu {d['mode_remise']['valeurs']}"
    )


# ---------------------------------------------------------------------------
# Cas 5 (A29) : critère technique « noté sur 27 points » avec trois sous-critères
# ---------------------------------------------------------------------------

RC_SOUS_CRITERES_SANS_PONDERATION = [
    "COMMUNAUTÉ DE COMMUNES DU PAYS DE BRÉVAUX\n\nMARCHÉ PUBLIC DE TRAVAUX\n\n"
    "RÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Extension du groupe scolaire de Brévaux\n"
    "Référence : 2025-AO-37\n\nDate et heure limites de réception des offres : jeudi 12 février 2026 à 12 heures\n\n"
    "ARTICLE 1 – OBJET DE LA CONSULTATION\n\nLa présente consultation concerne : Extension du groupe scolaire de "
    "Brévaux.\nLes travaux sont répartis en 2 lots :\n  - Lot 1 : Gros œuvre\n  Lot n° 2 : Charpente bois\n"
    "Les candidats peuvent présenter une offre pour un ou plusieurs lots.\n\nArticle 2 : Procédure\n\n"
    "La présente consultation est passée selon la procédure adaptée (MAPA).\n\n"
    "Article 3 : Modifications de détail au dossier de consultation\n\nLe maître d'ouvrage se réserve le droit "
    "d'apporter au plus tard dix jours avant la date limite fixée pour la réception des offres des modifications "
    "de détail au dossier de consultation. Les candidats devront alors répondre sur la base du dossier modifié sans "
    "pouvoir élever aucune réclamation à ce sujet.\n\nARTICLE 4 – VARIANTES ET VALIDITÉ DES OFFRES\n\n"
    "Délai de validité des offres : 4 mois.\n\nArticle 5 : Contenu du dossier à remettre\n\n"
    "Les candidats remettent un dossier comprenant les pièces suivantes, datées et signées :\n\n"
    "1) Au titre de la candidature :\n  - Certificats de qualification professionnelle (Qualibat ou équivalent)\n"
    "  - Pouvoir de la personne habilitée à engager le candidat\n"
    "  - Liste des travaux exécutés au cours des cinq dernières années\n"
    "  - Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité\n"
    "  - Déclaration du candidat (formulaire DC2)\n  - Déclaration indiquant les effectifs moyens annuels du candidat\n\n"
    "Pièces de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Mémoire technique de 25 pages au plus\n"
    "  - Décomposition du prix global et forfaitaire (DPGF)\n  - Cadre de réponse technique complété\n\n"
    "Le candidat auquel il est envisagé d'attribuer le marché produira dans un délai de 8 jours :\n"
    "  - Attestations de régularité fiscale et sociale\n  - Extrait Kbis de moins de trois mois\n\n"
    "ARTICLE 6 – SÉLECTION DES CANDIDATURES ET JUGEMENT DES OFFRES\n\nLe jugement des offres sera effectué selon "
    "les critères pondérés suivants :\n\nCritères | Pondération\n1. Valeur technique | noté sur 27 points\n"
    "   - Gestion des déchets de chantier\n   - Moyens matériels affectés au chantier\n"
    "   - Planning détaillé des travaux\n2. Coût | 21 points\n3. Délai d'exécution | 6 pts\n"
    "4. Planning prévisionnel | 6 pts\n\nLa note finale est la somme des notes obtenues pour chaque critère.\n\n"
    "ARTICLE 7 – MODALITÉS DE REMISE DES PLIS\n\nLes offres sont transmises par voie électronique sur la plateforme "
    "AWS-Achat (https://www.marches-publics.info).\nAucune offre papier ne sera acceptée.\n"
    "Les plis doivent parvenir avant le 12/02/2026 à 12h00.\n\nArticle 8 : Renseignements complémentaires\n\n"
    "RC – 1/2\n",
]


def test_A29_reg_sous_criteres_d_un_critere_note_sur_N_points():
    d = app.analyser(RC_SOUS_CRITERES_SANS_PONDERATION)
    sections = [s for s in d["plan"] if s["critere"].startswith("Valeur technique")]
    attendus = [
        "Gestion des déchets de chantier",
        "Moyens matériels affectés au chantier",
        "Planning détaillé des travaux",
    ]
    obtenus = [s["sous_critere"] for s in sections]
    assert obtenus == attendus, (
        f"A29 : le critère « Valeur technique » détaillé en trois sous-critères doit donner une section par "
        f"sous-critère, dans l'ordre du RC ; sous-critères attendus {attendus}, obtenus {obtenus} "
        f"(sections {sections})"
    )
    for s in sections:
        assert s["page_source"] == 1 and s["contenu"] == "", (
            f"A32/A33 : section attendue avec page_source 1 et contenu vide ; obtenu {s}"
        )
        assert s["ponderation"] is None, (
            f"A31 : le sous-critère « {s['sous_critere']} » n'a pas de pondération propre ; "
            f"pondération de section attendue None, obtenue {s['ponderation']!r}"
        )
