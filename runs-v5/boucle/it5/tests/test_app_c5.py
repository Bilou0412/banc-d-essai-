"""Tests rouges — compléments C14, C15 (sonde P12, lecture d'un RC)."""
import json

import app


def _piece(dossier, fragment):
    trouvees = [p for p in dossier["pieces"]["liste"] if fragment.lower() in p["nom"].lower()]
    assert len(trouvees) == 1, (
        f"attendu exactement une pièce contenant {fragment!r}, obtenu : "
        f"{[p['nom'] for p in dossier['pieces']['liste']]}"
    )
    return trouvees[0]


PAGE_CANDIDATURE = (
    "ARTICLE 5 - CONTENU DU DOSSIER DE CANDIDATURE\n"
    "Au titre de la candidature, le candidat produit les pièces suivantes :\n"
    "- Lettre de candidature (formulaire DC1) ou DUME (facultatif)\n"
    "- Liste des travaux exécutés au cours des cinq dernières années\n"
    "- Certificats de qualification professionnelle (Qualibat ou équivalent) (obligatoire)\n"
)


def test_C14_mention_facultatif_retiree_du_nom_et_portee_par_obligation():
    d = app.analyser([PAGE_CANDIDATURE])
    p = _piece(d, "DC1")
    assert p["nom"] == "Lettre de candidature (formulaire DC1) ou DUME", (
        f"nom attendu sans la mention « (facultatif) », obtenu {p['nom']!r}"
    )
    assert p["obligation"] == {
        "statut": "trouvé",
        "valeurs": [{"valeur": "non obligatoire", "pages": [1]}],
        "conflit": False,
    }, f"obligation attendue « non obligatoire » p.1, obtenu {p['obligation']!r}"


def test_C14_mention_obligatoire_retiree_mais_parentheses_de_l_intitule_gardees():
    d = app.analyser([PAGE_CANDIDATURE])
    p = _piece(d, "Qualibat")
    assert p["nom"] == "Certificats de qualification professionnelle (Qualibat ou équivalent)", (
        f"nom attendu sans « (obligatoire) » mais avec « (Qualibat ou équivalent) », obtenu {p['nom']!r}"
    )
    assert p["obligation"]["statut"] == "trouvé"
    assert p["obligation"]["valeurs"] == [{"valeur": "obligatoire", "pages": [1]}], (
        f"obligation attendue « obligatoire » p.1, obtenu {p['obligation']!r}"
    )


def test_C14_piece_sans_mention_a_obligation_non_trouvee():
    d = app.analyser([PAGE_CANDIDATURE])
    p = _piece(d, "travaux exécutés")
    assert p["nom"] == "Liste des travaux exécutés au cours des cinq dernières années", p["nom"]
    assert p["obligation"] == {"statut": "non trouvé", "valeurs": [], "conflit": False}, (
        f"aucune mention : obligation attendue non trouvée, obtenu {p['obligation']!r}"
    )


def test_C14_aucun_nom_ne_contient_la_mention():
    d = app.analyser([PAGE_CANDIDATURE])
    noms = [p["nom"] for p in d["pieces"]["liste"]]
    assert len(noms) == 3, f"attendu 3 pièces, obtenu {noms}"
    for n in noms:
        assert "(facultatif)" not in n.lower() and "(obligatoire)" not in n.lower(), (
            f"la mention d'obligation ne doit pas rester dans le nom : {n!r}"
        )


def test_C14_mention_feminine_sur_autre_page_porte_la_page():
    pages = [
        "ARTICLE 1 - OBJET\nLe présent règlement fixe les règles de la consultation.\n",
        "ARTICLE 6 - CONTENU DE L'OFFRE\nAu titre de l'offre, le candidat remet :\n"
        "- Acte d'engagement (obligatoire)\n"
        "- Attestation de visite (facultative)\n",
    ]
    d = app.analyser(pages)
    ae = _piece(d, "Acte d'engagement")
    av = _piece(d, "Attestation de visite")
    assert ae["nom"] == "Acte d'engagement", ae["nom"]
    assert av["nom"] == "Attestation de visite", av["nom"]
    assert ae["obligation"]["valeurs"] == [{"valeur": "obligatoire", "pages": [2]}], ae["obligation"]
    assert av["obligation"]["valeurs"] == [{"valeur": "non obligatoire", "pages": [2]}], av["obligation"]


def _filler(n):
    return f"Page {n}\nDispositions générales relatives à la présente consultation.\n"


def test_C15_signature_papier_meme_page_ne_cree_pas_de_mode_papier():
    pages = [_filler(i) for i in range(1, 9)] + [
        "ARTICLE 9 - CONDITIONS D'ENVOI ET DE REMISE DES OFFRES\n"
        "Les offres sont remises par voie dématérialisée sur le profil d'acheteur.\n"
        "Le marché attribué sera signé à la main sur support papier par l'attributaire.\n"
    ]
    d = app.analyser(pages)
    attendu = {"statut": "trouvé", "valeurs": [{"valeur": "électronique", "pages": [9]}], "conflit": False}
    assert d["mode_remise"] == attendu, (
        f"attendu {json.dumps(attendu, ensure_ascii=False)}, "
        f"obtenu {json.dumps(d['mode_remise'], ensure_ascii=False)}"
    )


def test_C15_signature_papier_autre_page_ne_cree_pas_de_mode_papier():
    pages = [
        "ARTICLE 4 - REMISE DES OFFRES\n"
        "La transmission des offres se fait obligatoirement par voie électronique.\n",
        "ARTICLE 12 - SIGNATURE DU MARCHÉ\n"
        "Le marché sera signé par l'attributaire sous forme papier, signature manuscrite.\n",
    ]
    d = app.analyser(pages)
    assert d["mode_remise"]["statut"] == "trouvé", d["mode_remise"]
    assert d["mode_remise"]["valeurs"] == [{"valeur": "électronique", "pages": [1]}], (
        f"la page 2 ne parle que de la signature du marché ; obtenu {d['mode_remise']['valeurs']!r}"
    )
    assert d["mode_remise"]["conflit"] is False, d["mode_remise"]
