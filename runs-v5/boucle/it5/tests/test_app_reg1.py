"""Tests de non-régression — sonde P12, lecture d'un RC (couche code, auteur : red).

Chaque test reproduit un cas où une implémentation passant les tests existants
s'est trompée, alors que la spec tranchait déjà.
"""

import app


RC_PIECES_UNE_PAGE = ["COMMUNAUTÉ DE COMMUNES DU PAYS DE SAINT-AUBERT-SUR-LOUE\n\nMARCHÉ PUBLIC DE TRAVAUX\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Extension du groupe scolaire de Saint-Aubert-sur-Loue\nRéférence : 2026-T-16\n\nDate et heure limites de réception des offres : vendredi 9 octobre 2026 à 11:00\n\nArticle 1 : Objet de la consultation\n\nLa présente consultation concerne : Extension du groupe scolaire de Saint-Aubert-sur-Loue.\nLes travaux sont traités en lot unique.\n\nARTICLE 2 – PROCÉDURE\n\nLa présente consultation est passée selon la procédure adaptée ouverte.\n\nARTICLE 3 – CONFIDENTIALITÉ ET DONNÉES PERSONNELLES\n\nLes informations transmises par les candidats sont traitées dans le respect du secret des affaires. Les données à caractère personnel recueillies sont utilisées aux seules fins de la passation du marché.\n\nARTICLE 4 – DISPOSITIONS RELATIVES AUX OFFRES\n\nLes variantes sont autorisées.\n\nARTICLE 5 – VISITE DU SITE\n\nLa visite des lieux est facultative.\nElle aura lieu aux dates suivantes : 15/09/2026, mardi 22 septembre 2026.\nLes candidats prennent rendez-vous auprès des services techniques au 01 23 45 43 38.\n\nARTICLE 6 – CONTENU DU DOSSIER À REMETTRE\n\nLes candidats remettent un dossier comprenant les pièces suivantes, datées et signées :\n\n1) Au titre de la candidature :\n  - Déclaration du candidat (formulaire DC2)\n  - Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité\n\n2) Au titre de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Mémoire technique de 15 pages au plus\n  - Attestation de visite\n\nArticle 7 : Jugement des offres\n\nLe jugement des offres sera effectué selon les critères pondérés suivants :\n\nCritère n° 1 : Mérite technique (40%)\nCritère n° 2 : Prix de l'offre (60 %)\n\n\nARTICLE 8 – CONDITIONS D'ENVOI ET DE REMISE DES OFFRES\n\nLa remise des plis se fait exclusivement par voie dématérialisée, sur le site https://www.e-marchespublics.com.\nAucune offre papier ne sera acceptée.\nLes plis doivent parvenir avant le 09.10.2026 à 11:00.\n\nARTICLE 9 – QUESTIONS DES CANDIDATS\n\nLes candidats peuvent poser leurs questions par écrit sur la plateforme au plus tard le 29/09/2026 à 12h00.\nUne réponse sera communiquée à tous les candidats.\n\n\nRC – 1/1\n"]

RC_PONDERATION_ENTRE_PARENTHESES = ["CENTRE HOSPITALIER DE MONTCRESSAC\n\nMARCHÉ PUBLIC DE TRAVAUX\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Rénovation énergétique de la mairie de Montcressac\nRéférence : 2026-TX-34\n\nDate et heure limites de réception des offres : 28/08/2026 à 12h00\n\nArticle 1 : Objet de la consultation\n\nLa présente consultation concerne : Rénovation énergétique de la mairie de Montcressac.\nLes travaux sont répartis en 2 lots :\n  Lot 01 – Isolation thermique par l'extérieur\n  - Lot 02 : Menuiseries\nLes candidats peuvent présenter une offre pour un ou plusieurs lots.\n\nArticle 2 : Procédure\n\nLa présente consultation est passée selon la appel d'offres ouvert.\n\nArticle 3 : Délais d'exécution\n\nLe délai d'exécution des travaux est fixé dans l'acte d'engagement. Il court à compter de la date fixée par l'ordre de service prescrivant le démarrage des travaux. Une période de préparation d'un mois est prévue.\n\nArticle 4 : Variantes et validité des offres\n\nLes variantes sont autorisées.\nDélai de validité des offres : 120 jours.\n\nARTICLE 5 – VISITE DES LIEUX\n\nUne visite du site est obligatoire. Toute offre remise sans attestation de visite sera déclarée irrégulière.\nElle aura lieu aux dates suivantes : 29 juillet 2026, lundi 3 août 2026.\nLes candidats prennent rendez-vous auprès des services techniques au 01 23 45 15 21.\n\nARTICLE 6 – CONTENU DU DOSSIER À REMETTRE\n\nLes candidats remettent un dossier comprenant les pièces suivantes, datées et signées :\n\n1) Au titre de la candidature :\n  - Liste des travaux exécutés au cours des cinq dernières années\n  - Déclaration indiquant les effectifs moyens annuels du candidat\n  - Lettre de candidature (formulaire DC1) ou DUME\n\nPièces de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Détail quantitatif estimatif (DQE)\n  - Décomposition du prix global et forfaitaire (DPGF)\n\nRC – 1/2\n", "  - Attestation de visite\n  - Mémoire technique, limité à 25 pages\n\nLe candidat auquel il est envisagé d'attribuer le marché produira dans un délai de 8 jours :\n  - Attestation URSSAF de vigilance de moins de six mois\n\nArticle 7 : Critères d'attribution\n\nL'offre économiquement la plus avantageuse sera appréciée en fonction des critères suivants :\n\nCritère n° 1 : Prix de l'offre (pondération : 40 %)\nCritère n° 2 : Qualité technique de l'offre (pondération : 50 %)\nCritère n° 3 : Performances en matière d'insertion professionnelle (pondération : 10 %)\n\n\nARTICLE 8 – CONDITIONS D'ENVOI ET DE REMISE DES OFFRES\n\nLes offres sont transmises par voie électronique sur la plateforme AWS-Achat (https://www.marches-publics.info).\nAucune offre papier ne sera acceptée.\nLes plis doivent parvenir avant le 28 août 2026 à 12h00.\n\n\nRC – 2/2\n"]

RC_SOUS_CRITERES_APRES_SAUT = ["OFFICE PUBLIC DE L'HABITAT DE SAINT-AUBERT-SUR-LOUE\n\nMARCHÉ PUBLIC DE TRAVAUX\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Construction d'un gymnase de Saint-Aubert-sur-Loue\nRéférence : 2025-MAPA-56\n\nDate et heure limites de réception des offres : 16.11.2026 à 12h00\n\nArticle 1 : Objet de la consultation\n\nLa présente consultation concerne : Construction d'un gymnase de Saint-Aubert-sur-Loue.\nLe marché n'est pas alloti : il fait l'objet d'un lot unique.\n\nArticle 2 : Procédure\n\nLa présente consultation est passée selon la procédure adaptée (MAPA).\n\nARTICLE 3 – CONFIDENTIALITÉ ET DONNÉES PERSONNELLES\n\nLes informations transmises par les candidats sont traitées dans le respect du secret des affaires. Les données à caractère personnel recueillies sont utilisées aux seules fins de la passation du marché.\n\nARTICLE 4 – DISPOSITIONS RELATIVES AUX OFFRES\n\nAucune variante n'est admise.\n\nArticle 5 : Contenu du dossier à remettre\n\nLes candidats remettent un dossier comprenant les pièces suivantes, datées et signées :\n\n1) Au titre de la candidature :\n  - Liste des travaux exécutés au cours des cinq dernières années\n  - Lettre de candidature (formulaire DC1) ou DUME (facultatif)\n  - Certificats de qualification professionnelle (Qualibat ou équivalent) (facultatif)\n\n2) Au titre de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Détail quantitatif estimatif (DQE)\n  - Planning prévisionnel d'exécution\n  - Décomposition du prix global et forfaitaire (DPGF)\n  - Bordereau des prix unitaires (BPU)\n  - Attestation de visite\n  - Mémoire technique\n\nArticle 6 : Sélection des candidatures et jugement des offres\n\nL'offre économiquement la plus avantageuse sera appréciée en fonction des critères suivants :\n\nCritère n° 1 : Coût (70 %)\nCritère n° 2 : Valeur technique de l'offre (30 %)\n  Ce critère sera apprécié au regard des éléments suivants :\n\nRC – 1/2\n", "  • Gestion des déchets de chantier\n  • Méthodologie et organisation du chantier\n  • Moyens humains affectés au chantier\n\n\nARTICLE 7 – MODALITÉS DE REMISE DES PLIS\n\nLes offres sont transmises par voie électronique sur la plateforme de dématérialisation https://www.marches-saint-au.fr.\nAucune offre papier ne sera acceptée.\nLes plis doivent parvenir avant le 16 novembre 2026 à 12 heures.\n\n\nRC – 2/2\n"]

RC_CLASSEMENT = ["CENTRE HOSPITALIER DE BRÉVAUX\n\nMARCHÉ PUBLIC DE TRAVAUX\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Réhabilitation de l'école élémentaire de Brévaux\nRéférence : 2026-MAPA-71\n\nDate et heure limites de réception des offres : 21.09.2026 à 11 heures\n\nArticle 1 : Objet de la consultation\n\nLa présente consultation concerne : Réhabilitation de l'école élémentaire de Brévaux.\nLes travaux sont traités en lot unique.\n\nArticle 2 : Procédure\n\nLa présente consultation est passée selon la appel d'offres restreint en application des articles R2161-6 à R2161-11 du Code de la commande publique.\n\nARTICLE 3 – NÉGOCIATION\n\nLe pouvoir adjudicateur se réserve la possibilité de négocier avec les candidats ayant présenté une offre. Il peut également attribuer le marché sur la base des offres initiales, sans négociation.\n\nARTICLE 4 – DISPOSITIONS RELATIVES AUX OFFRES\n\nLes variantes ne sont pas autorisées.\n\nArticle 5 : Visite du site\n\nLa visite des lieux est facultative.\n\nARTICLE 6 – PRÉSENTATION DES CANDIDATURES ET DES OFFRES\n\nLes candidats remettent un dossier comprenant les pièces suivantes, datées et signées :\n\n1) Au titre de la candidature :\n  - Pouvoir de la personne habilitée à engager le candidat\n  - Déclaration indiquant les effectifs moyens annuels du candidat\n\n2) Au titre de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Détail quantitatif estimatif (DQE)\n  - Planning prévisionnel d'exécution\n  - Décomposition du prix global et forfaitaire (DPGF)\n  - Mémoire technique\n\nLe candidat auquel il est envisagé d'attribuer le marché produira dans un délai de 8 jours :\n  - Extrait Kbis de moins de trois mois\n\nArticle 7 : Jugement des offres\n\nL'offre économiquement la plus avantageuse sera appréciée en fonction des critères énoncés ci-dessous.\n\nLes critères sont classés par ordre décroissant d'importance :\n\nRC – 1/2\n", "  1. Valeur technique de l'offre\n  2. Prix des prestations\n\nARTICLE 8 – CONDITIONS D'ENVOI ET DE REMISE DES OFFRES\n\nLes offres sont transmises par voie électronique sur la plateforme PLACE (https://www.marches-publics.gouv.fr).\nAucune offre papier ne sera acceptée.\nLes plis doivent parvenir avant le 21.09.2026 à 11h00.\n\nArticle 9 : Modifications de détail au dossier de consultation\n\nLe maître d'ouvrage se réserve le droit d'apporter au plus tard dix jours avant la date limite fixée pour la réception des offres des modifications de détail au dossier de consultation. Les candidats devront alors répondre sur la base du dossier modifié sans pouvoir élever aucune réclamation à ce sujet.\n\n\nRC – 2/2\n"]

RC_SANS_VALIDITE_OFFRES = ["COMMUNAUTÉ DE COMMUNES DU PAYS DE MARSOLLE\n\nMARCHÉ PUBLIC DE TRAVAUX\n\nRÈGLEMENT DE LA CONSULTATION (R.C.)\n\nObjet : Réfection de la voirie communale de Marsolle\nRéférence : 2026-MAPA-32\n\nDate et heure limites de réception des offres : 17.08.2026 à 11:00\n\nARTICLE 1 – OBJET DE LA CONSULTATION\n\nLa présente consultation concerne : Réfection de la voirie communale de Marsolle.\nLe marché est passé en un lot unique, l'allotissement n'étant pas pertinent pour cette opération.\n\nARTICLE 2 – PROCÉDURE\n\nLa présente consultation est passée selon la procédure adaptée (MAPA).\n\nArticle 3 : Confidentialité et données personnelles\n\nLes informations transmises par les candidats sont traitées dans le respect du secret des affaires. Les données à caractère personnel recueillies sont utilisées aux seules fins de la passation du marché.\n\nArticle 4 : Dispositions relatives aux offres\n\nLes candidats peuvent présenter des variantes à l'initiative du candidat.\n\nARTICLE 5 – CONTENU DU DOSSIER À REMETTRE\n\nLes candidats remettent un dossier comprenant les pièces suivantes, datées et signées :\n\n1) Au titre de la candidature :\n  - Pouvoir de la personne habilitée à engager le candidat\n  - Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité\n  - Déclaration du candidat (formulaire DC2)\n  - Liste des travaux exécutés au cours des cinq dernières années\n\n2) Au titre de l'offre :\n  - Acte d'engagement (AE) complété et signé\n  - Mémoire technique\n  - Attestation de visite\n  - Décomposition du prix global et forfaitaire (DPGF)\n  - Planning prévisionnel d'exécution\n\nLe candidat auquel il est envisagé d'attribuer le marché produira dans un délai de 8 jours :\n  - Liste nominative des salariés étrangers\n  - Extrait Kbis de moins de trois mois\n  - Attestations de régularité fiscale et sociale\n\nArticle 6 : Jugement des offres\n\nL'offre économiquement la plus avantageuse sera appréciée en fonction des critères suivants :\n\nCritères | Pondération\n1. Valeur technique | 30 pts\n2. Prix des prestations | 24 pts\n3. Planning prévisionnel | 6 pts\n\nLa note finale est la somme des notes obtenues pour chaque critère.\n\nARTICLE 7 – MODALITÉS DE REMISE DES PLIS\n\nLes offres sont transmises par voie électronique sur le profil d'acheteur https://achats.marsolle-public.fr.\nAucune offre papier ne sera acceptée.\n\nRC – 1/2\n", "Les plis doivent parvenir avant le 17 août 2026 à 11 heures.\n\nARTICLE 8 – RENSEIGNEMENTS COMPLÉMENTAIRES\n\nLes candidats peuvent poser leurs questions par écrit sur la plateforme au plus tard le 7 août 2026.\nUne réponse sera communiquée à tous les candidats.\n\n\nRC – 2/2\n"]


PIECES_ATTENDUES = [
    "Déclaration du candidat (formulaire DC2)",
    "Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité",
    "Acte d'engagement (AE) complété et signé",
    "Mémoire technique de 15 pages au plus",
    "Attestation de visite",
]


# Cas 1 — A15 : cinq pièces sous rubriques candidature / offre, une seule page.
def test_A15_reg_cinq_pieces_sous_rubriques_une_page_toutes_listees():
    d = app.analyser(RC_PIECES_UNE_PAGE)
    liste = d["pieces"]["liste"]
    noms = [p["nom"] for p in liste]
    for nom in PIECES_ATTENDUES:
        assert nom in noms, (
            f"A15 : pièce attendue {nom!r} absente de pieces.liste ; obtenu : {noms!r}"
        )
    assert len(noms) == len(PIECES_ATTENDUES), (
        f"A15 : attendu exactement {len(PIECES_ATTENDUES)} pièces, obtenu {len(noms)} : {noms!r}"
    )
    for p in liste:
        assert p["pages"] == [1], (
            f"A15/A122 : pièce {p['nom']!r} attendue page [1], obtenu {p['pages']!r}"
        )


# Cas 5 — A15 : même RC, le statut des pièces doit être « trouvé ».
def test_A15_reg_cinq_pieces_une_page_statut_trouve():
    d = app.analyser(RC_PIECES_UNE_PAGE)
    assert d["pieces"]["statut"] == "trouvé", (
        f"A15 : pieces.statut attendu 'trouvé', obtenu {d['pieces']['statut']!r} "
        f"(liste : {[p['nom'] for p in d['pieces']['liste']]!r})"
    )


# Cas 2 — A140 : « Libellé (pondération : 50 %) » -> libellé sans la parenthèse.
def test_A140_reg_ponderation_entre_parentheses_hors_du_libelle():
    d = app.analyser(RC_PONDERATION_ENTRE_PARENTHESES)
    libelles = [c["libelle"] for c in d["criteres"]["liste"]]
    assert libelles == [
        "Prix de l'offre",
        "Qualité technique de l'offre",
        "Performances en matière d'insertion professionnelle",
    ], f"A140 : libellés attendus tels qu'écrits sans la pondération, obtenu {libelles!r}"
    sections = [s for s in d["plan"] if s["critere"] == "Qualité technique de l'offre"]
    attendu = {
        "titre": "Qualité technique de l'offre",
        "critere": "Qualité technique de l'offre",
        "sous_critere": None,
        "ponderation": 50,
        "page_source": 2,
        "contenu": "",
    }
    assert sections == [attendu], (
        f"A140 : section attendue {attendu!r}, obtenu {sections!r} (plan complet : {d['plan']!r})"
    )
    for s in d["plan"]:
        assert "pondération" not in s["titre"] and "pondération" not in s["critere"], (
            f"A140 : le titre/critère d'une section ne doit pas contenir la pondération, obtenu {s!r}"
        )


# Cas 3 — A22 : sous-critères listés après un saut de page, sans pondération propre.
def test_A22_reg_sous_criteres_apres_saut_de_page_rattaches_au_parent():
    d = app.analyser(RC_SOUS_CRITERES_APRES_SAUT)
    criteres = {c["libelle"]: c for c in d["criteres"]["liste"]}
    assert "Valeur technique de l'offre" in criteres, (
        f"A22 : critère 'Valeur technique de l'offre' attendu, obtenu {list(criteres)!r}"
    )
    vt = criteres["Valeur technique de l'offre"]
    sc = [(s["libelle"], s["pages"]) for s in vt["sous_criteres"]]
    assert sc == [
        ("Gestion des déchets de chantier", [2]),
        ("Méthodologie et organisation du chantier", [2]),
        ("Moyens humains affectés au chantier", [2]),
    ], f"A22 : sous-critères attendus (page 2) sous 'Valeur technique de l'offre', obtenu {sc!r}"
    assert criteres["Coût"]["sous_criteres"] == [], (
        f"A154 : 'Coût' ne doit avoir aucun sous-critère, obtenu {criteres['Coût']['sous_criteres']!r}"
    )


# Cas 6 — A29 : une section par sous-critère, même sans pondération propre.
def test_A29_reg_une_section_par_sous_critere_non_pondere():
    d = app.analyser(RC_SOUS_CRITERES_APRES_SAUT)
    sous = [
        s for s in d["plan"]
        if s["critere"] == "Valeur technique de l'offre" and s["sous_critere"] is not None
    ]
    attendu = [
        {"titre": "Valeur technique de l'offre – Gestion des déchets de chantier",
         "critere": "Valeur technique de l'offre",
         "sous_critere": "Gestion des déchets de chantier",
         "ponderation": None, "page_source": 2, "contenu": ""},
        {"titre": "Valeur technique de l'offre – Méthodologie et organisation du chantier",
         "critere": "Valeur technique de l'offre",
         "sous_critere": "Méthodologie et organisation du chantier",
         "ponderation": None, "page_source": 2, "contenu": ""},
        {"titre": "Valeur technique de l'offre – Moyens humains affectés au chantier",
         "critere": "Valeur technique de l'offre",
         "sous_critere": "Moyens humains affectés au chantier",
         "ponderation": None, "page_source": 2, "contenu": ""},
    ]
    assert sous == attendu, (
        f"A29 : sections par sous-critère attendues {attendu!r}, obtenu {sous!r} "
        f"(plan complet : {d['plan']!r})"
    )


# Cas 4 — A25 : critères classés par ordre décroissant d'importance, sans chiffre.
def test_A25_reg_criteres_classes_sans_ponderation_type_classement():
    d = app.analyser(RC_CLASSEMENT)
    tp = d["type_ponderation"]
    assert tp["statut"] == "trouvé", f"A25 : type_ponderation attendu 'trouvé', obtenu {tp!r}"
    assert tp["valeurs"] == [{"valeur": "classement", "pages": [2]}], (
        f"A25 : valeurs attendues [{{'valeur': 'classement', 'pages': [2]}}], obtenu {tp['valeurs']!r}"
    )
    assert tp["conflit"] is False, f"A25 : conflit attendu False, obtenu {tp!r}"


# Cas 7 — A105 : « validité » d'une attestation et « délai de 8 jours » ne sont pas
# une durée de validité des offres.
def test_A105_reg_validite_attestation_et_delai_attributaire_pas_validite_offres():
    d = app.analyser(RC_SANS_VALIDITE_OFFRES)
    vo = d["validite_offres"]
    assert vo == {"statut": "non trouvé", "valeurs": [], "conflit": False}, (
        f"A105 : validite_offres attendue non trouvée, obtenu {vo!r}"
    )
