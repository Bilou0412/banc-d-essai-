"""Tests rouges -- sonde P01 (carnet de contacts), couche code.

Interface publique fixée par ces tests (module `app`) :

    s = app.MemoryStorage()            # « disque » simulé en mémoire
    a = app.App(storage=s)             # une instance = une application lancée
    app.App(storage=s)                 # nouvelle instance sur le même stockage = rechargement

    a.create_contact(name, phone="", email="") -> id | None   (None si refusé)
    a.error            -> str | None    erreur affichée par la dernière action
    a.list_rows()      -> list[dict]    lignes affichées, dans l'ordre :
                                        {"id", "name", "email", "favorite": bool}
    a.list_message     -> str | None    message affiché sous la liste (« Aucun contact »)
    a.card(id)         -> dict          fiche : {"name", "phone", "email",
                                        "tags": list[str], "favorite": bool}

    a.start_edit(id); a.set_edit(name=..., phone=..., email=...)
    a.validate_edit() -> bool ; a.cancel_edit()

    a.request_delete(id); a.confirmation -> str | None
    a.confirm_delete(); a.reject_delete()

    a.set_search(text)                 # "" efface la recherche
    a.set_sort("name_asc" | "name_desc")
    a.add_tag(id, tag); a.remove_tag(id, tag)
    a.set_tag_filter(tag | None)       # None retire le filtre
    a.set_favorite(id, bool)

    a.export_csv() -> str
    a.import_csv(text: str) -> None    # erreurs dans a.error
"""

import csv
import io
import re

import pytest

import app

HEADER = "nom,téléphone,email,étiquettes,favori"


# ---------------------------------------------------------------- helpers

def new_app():
    return app.App(storage=app.MemoryStorage())


def names(a):
    return [r["name"] for r in a.list_rows()]


def row_of(a, cid):
    for r in a.list_rows():
        if r["id"] == cid:
            return r
    raise AssertionError(f"contact {cid!r} absent de la liste affichée : {names(a)}")


def make(a, name, phone="", email=""):
    cid = a.create_contact(name, phone=phone, email=email)
    assert cid is not None, (
        f"création de {name!r} refusée de façon inattendue, erreur : {a.error!r}"
    )
    return cid


def csv_rows(text):
    return list(csv.reader(io.StringIO(text)))


# ---------------------------------------------------------------- création

def test_A01_creation_nom_non_vide_ajoute_a_la_liste():
    a = new_app()
    make(a, "Alice", phone="0601020304", email="alice@x.com")
    assert names(a) == ["Alice"], f"attendu ['Alice'], obtenu {names(a)}"
    assert a.error is None, f"aucune erreur attendue, obtenu {a.error!r}"


def test_A01_creation_deux_contacts_les_deux_dans_la_liste():
    a = new_app()
    make(a, "Alice")
    make(a, "Bruno")
    assert sorted(names(a)) == ["Alice", "Bruno"], f"obtenu {names(a)}"


def test_A02_creation_nom_vide_affiche_erreur():
    a = new_app()
    res = a.create_contact("", phone="0601", email="a@x.com")
    assert res is None, f"création refusée attendue, obtenu id {res!r}"
    assert a.error == "Le nom est obligatoire", f"obtenu {a.error!r}"


def test_A02_trou_nom_uniquement_espaces_est_vide():
    a = new_app()
    a.create_contact("   ")
    assert a.error == "Le nom est obligatoire", (
        f"un nom fait d'espaces doit être traité comme vide, obtenu {a.error!r}"
    )
    assert names(a) == [], f"aucun contact attendu, obtenu {names(a)}"


def test_A03_creation_nom_vide_n_ajoute_aucun_contact():
    a = new_app()
    make(a, "Alice")
    a.create_contact("", email="b@x.com")
    assert names(a) == ["Alice"], f"attendu ['Alice'] seul, obtenu {names(a)}"


def test_A04_email_sans_arobase_affiche_erreur():
    a = new_app()
    res = a.create_contact("Alice", email="alice.x.com")
    assert a.error == "Email invalide", f"obtenu {a.error!r}"
    assert res is None, f"création refusée attendue, obtenu {res!r}"


def test_A04_trou_email_invalide_n_ajoute_pas_le_contact():
    a = new_app()
    a.create_contact("Alice", email="alice.x.com")
    assert names(a) == [], f"aucun contact attendu, obtenu {names(a)}"


def test_A05_telephone_avec_lettres_affiche_erreur():
    a = new_app()
    res = a.create_contact("Alice", phone="06abc12")
    assert a.error == "Téléphone invalide", f"obtenu {a.error!r}"
    assert res is None
    assert names(a) == [], f"aucun contact attendu, obtenu {names(a)}"


def test_A05_trou_telephone_avec_plus_espaces_tirets_accepte():
    a = new_app()
    cid = a.create_contact("Alice", phone="+33 6 12-34-56-78")
    assert a.error is None, f"aucune erreur attendue, obtenu {a.error!r}"
    assert cid is not None
    assert names(a) == ["Alice"]


def test_A06_email_vide_n_affiche_aucune_erreur():
    a = new_app()
    cid = a.create_contact("Alice", phone="0601", email="")
    assert a.error is None, f"aucune erreur attendue, obtenu {a.error!r}"
    assert cid is not None
    assert names(a) == ["Alice"]


def test_A06_trou_erreur_precedente_effacee_apres_creation_valide():
    a = new_app()
    a.create_contact("")
    assert a.error == "Le nom est obligatoire"
    a.create_contact("Alice", email="")
    assert a.error is None, (
        f"l'erreur précédente ne doit plus être affichée, obtenu {a.error!r}"
    )


# ---------------------------------------------------------------- modification

def test_A07_modification_nom_affiche_nouveau_nom_sur_fiche():
    a = new_app()
    cid = make(a, "Alice", email="alice@x.com")
    a.start_edit(cid)
    a.set_edit(name="Alicia")
    assert a.validate_edit() is True
    assert a.card(cid)["name"] == "Alicia", f"obtenu {a.card(cid)['name']!r}"
    assert a.card(cid)["email"] == "alice@x.com", "l'email ne doit pas changer"
    assert names(a) == ["Alicia"], f"liste attendue ['Alicia'], obtenu {names(a)}"


def test_A08_modification_nom_vide_affiche_erreur():
    a = new_app()
    cid = make(a, "Alice")
    a.start_edit(cid)
    a.set_edit(name="")
    assert a.validate_edit() is False
    assert a.error == "Le nom est obligatoire", f"obtenu {a.error!r}"


def test_A08_trou_modification_nom_vide_conserve_ancien_nom():
    a = new_app()
    cid = make(a, "Alice")
    a.start_edit(cid)
    a.set_edit(name="")
    a.validate_edit()
    assert a.card(cid)["name"] == "Alice", f"obtenu {a.card(cid)['name']!r}"
    assert names(a) == ["Alice"]


def test_A09_annuler_modification_garde_ancien_nom():
    a = new_app()
    cid = make(a, "Alice")
    a.start_edit(cid)
    a.set_edit(name="Zoé")
    a.cancel_edit()
    assert a.card(cid)["name"] == "Alice", f"obtenu {a.card(cid)['name']!r}"
    assert names(a) == ["Alice"], f"obtenu {names(a)}"


# ---------------------------------------------------------------- suppression

def test_A10_demande_suppression_affiche_confirmation():
    a = new_app()
    cid = make(a, "Alice")
    assert a.confirmation is None, "aucune confirmation avant la demande"
    a.request_delete(cid)
    assert isinstance(a.confirmation, str) and a.confirmation.strip(), (
        f"une demande de confirmation doit être affichée, obtenu {a.confirmation!r}"
    )
    assert names(a) == ["Alice"], "le contact ne doit pas disparaître avant confirmation"


def test_A11_confirmer_suppression_retire_contact():
    a = new_app()
    cid = make(a, "Alice")
    make(a, "Bruno")
    a.request_delete(cid)
    a.confirm_delete()
    assert names(a) == ["Bruno"], f"obtenu {names(a)}"
    assert a.confirmation is None, "la confirmation doit disparaître"


def test_A12_refuser_confirmation_garde_contact():
    a = new_app()
    cid = make(a, "Alice")
    a.request_delete(cid)
    a.reject_delete()
    assert names(a) == ["Alice"], f"obtenu {names(a)}"
    assert a.confirmation is None, "la confirmation doit disparaître"


# ---------------------------------------------------------------- recherche

def test_A13_recherche_insensible_casse_sur_nom():
    a = new_app()
    make(a, "Alice")
    make(a, "Caroline")
    make(a, "Bruno")
    a.set_search("LI")
    assert sorted(names(a)) == ["Alice", "Caroline"], f"obtenu {names(a)}"


def test_A13_recherche_texte_au_milieu_du_nom():
    a = new_app()
    make(a, "Martin Dupont")
    make(a, "Paul")
    a.set_search("dup")
    assert names(a) == ["Martin Dupont"], f"obtenu {names(a)}"


def test_A14_recherche_dans_email_seulement():
    a = new_app()
    make(a, "Alice", email="contact@acme.fr")
    make(a, "Bruno", email="bruno@x.com")
    a.set_search("ACME")
    assert names(a) == ["Alice"], f"obtenu {names(a)}"


def test_A15_recherche_sans_resultat_liste_vide_et_message():
    a = new_app()
    make(a, "Alice")
    a.set_search("zzz")
    assert names(a) == [], f"liste vide attendue, obtenu {names(a)}"
    assert a.list_message == "Aucun contact", f"obtenu {a.list_message!r}"


def test_A15_trou_message_absent_quand_resultats():
    a = new_app()
    make(a, "Alice")
    a.set_search("ali")
    assert a.list_message is None, f"aucun message attendu, obtenu {a.list_message!r}"


def test_A16_effacer_recherche_affiche_tous():
    a = new_app()
    make(a, "Alice")
    make(a, "Bruno")
    a.set_search("ali")
    assert names(a) == ["Alice"]
    a.set_search("")
    assert sorted(names(a)) == ["Alice", "Bruno"], f"obtenu {names(a)}"
    assert a.list_message is None


# ---------------------------------------------------------------- tri

def test_A17_tri_croissant():
    a = new_app()
    for n in ["Charles", "Alice", "Bruno"]:
        make(a, n)
    a.set_sort("name_asc")
    assert names(a) == ["Alice", "Bruno", "Charles"], f"obtenu {names(a)}"


def test_A17_trou_tri_croissant_insensible_casse():
    a = new_app()
    for n in ["bruno", "Charles", "Alice"]:
        make(a, n)
    a.set_sort("name_asc")
    assert names(a) == ["Alice", "bruno", "Charles"], f"obtenu {names(a)}"


def test_A18_tri_decroissant():
    a = new_app()
    for n in ["Bruno", "Alice", "Charles"]:
        make(a, n)
    a.set_sort("name_desc")
    assert names(a) == ["Charles", "Bruno", "Alice"], f"obtenu {names(a)}"


def test_A19_elodie_entre_denis_et_fabien():
    a = new_app()
    for n in ["Fabien", "élodie", "Denis"]:
        make(a, n)
    a.set_sort("name_asc")
    assert names(a) == ["Denis", "élodie", "Fabien"], f"obtenu {names(a)}"


def test_A19_trou_elodie_entre_fabien_et_denis_en_decroissant():
    a = new_app()
    for n in ["Denis", "Fabien", "élodie"]:
        make(a, n)
    a.set_sort("name_desc")
    assert names(a) == ["Fabien", "élodie", "Denis"], f"obtenu {names(a)}"


def test_A20_creation_placee_selon_tri_croissant():
    a = new_app()
    a.set_sort("name_asc")
    make(a, "Alice")
    make(a, "Charles")
    make(a, "Bruno")
    assert names(a) == ["Alice", "Bruno", "Charles"], f"obtenu {names(a)}"


def test_A20_creation_placee_selon_tri_decroissant():
    a = new_app()
    a.set_sort("name_desc")
    make(a, "Bruno")
    make(a, "Alice")
    make(a, "Charles")
    assert names(a) == ["Charles", "Bruno", "Alice"], f"obtenu {names(a)}"


# ---------------------------------------------------------------- favoris en tête

@pytest.mark.parametrize("sort", ["name_asc", "name_desc"])
def test_A21_favoris_en_tete_quel_que_soit_tri(sort):
    a = new_app()
    ids = {n: make(a, n) for n in ["Alice", "Bruno", "Charles", "Denis"]}
    a.set_favorite(ids["Charles"], True)
    a.set_sort(sort)
    got = names(a)
    assert got[0] == "Charles", f"tri {sort} : favori attendu en tête, obtenu {got}"
    rest = ["Alice", "Bruno", "Denis"]
    expected_rest = rest if sort == "name_asc" else list(reversed(rest))
    assert got[1:] == expected_rest, f"tri {sort} : obtenu {got}"


def test_A21_trou_favoris_entre_eux_suivent_le_tri():
    a = new_app()
    ids = {n: make(a, n) for n in ["Alice", "Bruno", "Charles", "Denis"]}
    a.set_favorite(ids["Denis"], True)
    a.set_favorite(ids["Bruno"], True)
    a.set_sort("name_asc")
    assert names(a) == ["Bruno", "Denis", "Alice", "Charles"], f"obtenu {names(a)}"
    a.set_sort("name_desc")
    assert names(a) == ["Denis", "Bruno", "Charles", "Alice"], f"obtenu {names(a)}"


# ---------------------------------------------------------------- étiquettes

def test_A22_ajouter_etiquette_affichee_sur_fiche():
    a = new_app()
    cid = make(a, "Alice")
    a.add_tag(cid, "travail")
    assert a.card(cid)["tags"] == ["travail"], f"obtenu {a.card(cid)['tags']}"


def test_A23_etiquette_deja_presente_affichee_une_fois():
    a = new_app()
    cid = make(a, "Alice")
    a.add_tag(cid, "travail")
    a.add_tag(cid, "travail")
    assert a.card(cid)["tags"].count("travail") == 1, f"obtenu {a.card(cid)['tags']}"


def test_A24_retirer_etiquette_disparait_de_fiche():
    a = new_app()
    cid = make(a, "Alice")
    a.add_tag(cid, "travail")
    a.add_tag(cid, "famille")
    a.remove_tag(cid, "travail")
    assert a.card(cid)["tags"] == ["famille"], f"obtenu {a.card(cid)['tags']}"


def test_A25_filtre_par_etiquette():
    a = new_app()
    al = make(a, "Alice")
    make(a, "Bruno")
    ch = make(a, "Charles")
    a.add_tag(al, "travail")
    a.add_tag(ch, "travail")
    a.add_tag(ch, "famille")
    a.set_tag_filter("travail")
    assert sorted(names(a)) == ["Alice", "Charles"], f"obtenu {names(a)}"
    a.set_tag_filter("famille")
    assert names(a) == ["Charles"], f"obtenu {names(a)}"


def test_A26_recherche_et_filtre_combines():
    a = new_app()
    al = make(a, "Alice")
    al2 = make(a, "Aline")
    make(a, "Alix")
    br = make(a, "Bruno")
    a.add_tag(al, "travail")
    a.add_tag(br, "travail")
    a.add_tag(al2, "famille")
    a.set_tag_filter("travail")
    a.set_search("ali")
    assert names(a) == ["Alice"], f"obtenu {names(a)}"


# ---------------------------------------------------------------- favoris

def test_A27_marquer_favori_affiche_icone():
    a = new_app()
    cid = make(a, "Alice")
    other = make(a, "Bruno")
    assert row_of(a, cid)["favorite"] is False
    a.set_favorite(cid, True)
    assert row_of(a, cid)["favorite"] is True
    assert a.card(cid)["favorite"] is True
    assert row_of(a, other)["favorite"] is False, "seul le contact marqué porte l'icône"


def test_A28_retirer_favori_fait_disparaitre_icone():
    a = new_app()
    cid = make(a, "Alice")
    a.set_favorite(cid, True)
    a.set_favorite(cid, False)
    assert row_of(a, cid)["favorite"] is False
    assert a.card(cid)["favorite"] is False


# ---------------------------------------------------------------- export CSV

def test_A29_export_premiere_ligne_entete():
    a = new_app()
    make(a, "Alice")
    out = a.export_csv()
    assert out.splitlines()[0] == HEADER, f"obtenu {out.splitlines()[0]!r}"


def test_A29_trou_export_sans_contact_contient_entete():
    a = new_app()
    out = a.export_csv()
    assert out.splitlines() == [HEADER], f"obtenu {out.splitlines()!r}"


def test_A30_export_une_ligne_par_contact_malgre_recherche_et_filtre():
    a = new_app()
    al = make(a, "Alice", email="alice@x.com")
    make(a, "Bruno", email="bruno@x.com")
    make(a, "Charles")
    a.add_tag(al, "travail")
    a.set_tag_filter("travail")
    a.set_search("ali")
    assert names(a) == ["Alice"]
    rows = csv_rows(a.export_csv())
    data = [r for r in rows[1:] if r]
    assert len(data) == 3, f"3 lignes de données attendues, obtenu {data}"
    assert sorted(r[0] for r in data) == ["Alice", "Bruno", "Charles"]


def test_A31_export_nom_avec_virgule_entre_guillemets():
    a = new_app()
    make(a, "Dupont, Jean", email="jd@x.com")
    out = a.export_csv()
    line = out.splitlines()[1]
    assert line.startswith('"Dupont, Jean",'), f"obtenu {line!r}"
    rows = csv_rows(out)
    assert rows[1][0] == "Dupont, Jean" and rows[1][2] == "jd@x.com", f"obtenu {rows[1]}"


def test_A31_trou_export_puis_import_restitue_le_contact():
    a = new_app()
    cid = make(a, "Dupont, Jean", phone="0601", email="jd@x.com")
    a.add_tag(cid, "travail")
    a.add_tag(cid, "famille")
    a.set_favorite(cid, True)
    out = a.export_csv()
    b = new_app()
    b.import_csv(out)
    assert names(b) == ["Dupont, Jean"], f"obtenu {names(b)}"
    card = b.card(b.list_rows()[0]["id"])
    assert card["phone"] == "0601" and card["email"] == "jd@x.com"
    assert sorted(card["tags"]) == ["famille", "travail"], f"obtenu {card['tags']}"
    assert card["favorite"] is True


# ---------------------------------------------------------------- import CSV

def test_A32_import_valide_un_contact_par_ligne():
    a = new_app()
    make(a, "Existant")
    text = (
        HEADER + "\n"
        "Alice,0601,alice@x.com,,non\n"
        "Bruno,0602,bruno@x.com,,non\n"
    )
    a.import_csv(text)
    assert a.error is None, f"aucune erreur attendue, obtenu {a.error!r}"
    assert sorted(names(a)) == ["Alice", "Bruno", "Existant"], f"obtenu {names(a)}"


def test_A32_trou_import_fins_de_ligne_crlf():
    a = new_app()
    text = HEADER + "\r\nAlice,0601,alice@x.com,,non\r\nBruno,0602,bruno@x.com,,non\r\n"
    a.import_csv(text)
    assert a.error is None, f"obtenu {a.error!r}"
    assert sorted(names(a)) == ["Alice", "Bruno"], f"obtenu {names(a)}"
    assert a.card(row_of_name(a, "Bruno"))["email"] == "bruno@x.com"


def row_of_name(a, name):
    for r in a.list_rows():
        if r["name"] == name:
            return r["id"]
    raise AssertionError(f"{name!r} absent : {names(a)}")


def test_A33_ligne_sans_nom_erreur_avec_numero_de_ligne():
    a = new_app()
    text = (
        HEADER + "\n"
        "Alice,0601,alice@x.com,,non\n"
        "Bruno,0602,bruno@x.com,,non\n"
        "Chloé,0603,chloe@x.com,,non\n"
        ",0604,anonyme@x.com,,non\n"
    )
    a.import_csv(text)
    assert a.error is not None, "une erreur doit être affichée"
    # ligne 5 du fichier (l'en-tête est la ligne 1)
    assert re.search(r"(?<!\d)5(?!\d)", a.error), f"numéro 5 attendu dans {a.error!r}"


def test_A34_ligne_sans_nom_non_ajoutee():
    a = new_app()
    text = HEADER + "\n,0604,anonyme@x.com,,non\n"
    a.import_csv(text)
    assert names(a) == [], f"obtenu {names(a)}"
    assert "anonyme@x.com" not in [r["email"] for r in a.list_rows()]


def test_A34_trou_lignes_valides_importees_malgre_ligne_sans_nom():
    a = new_app()
    text = (
        HEADER + "\n"
        "Alice,0601,alice@x.com,,non\n"
        ",0604,anonyme@x.com,,non\n"
        "Bruno,0602,bruno@x.com,,non\n"
    )
    a.import_csv(text)
    assert sorted(names(a)) == ["Alice", "Bruno"], f"obtenu {names(a)}"


def test_A35_sans_entete_format_invalide():
    a = new_app()
    text = "Alice,0601,alice@x.com,,non\nBruno,0602,bruno@x.com,,non\n"
    a.import_csv(text)
    assert a.error == "Format CSV invalide", f"obtenu {a.error!r}"
    assert names(a) == [], f"rien ne doit être importé, obtenu {names(a)}"


def test_A35_trou_fichier_vide_format_invalide():
    a = new_app()
    a.import_csv("")
    assert a.error == "Format CSV invalide", f"obtenu {a.error!r}"
    assert names(a) == []


def test_A36_email_existant_pas_de_doublon():
    a = new_app()
    make(a, "Alice", email="alice@x.com")
    text = (
        HEADER + "\n"
        "Alice Bis,0601,alice@x.com,,non\n"
        "Bruno,0602,bruno@x.com,,non\n"
    )
    a.import_csv(text)
    emails = [r["email"] for r in a.list_rows()]
    assert emails.count("alice@x.com") == 1, f"obtenu {a.list_rows()}"
    assert sorted(names(a)) == ["Alice", "Bruno"], f"obtenu {names(a)}"


def test_A36_trou_email_existant_casse_differente():
    a = new_app()
    make(a, "Alice", email="alice@x.com")
    a.import_csv(HEADER + "\nAlice Bis,0601,ALICE@X.COM,,non\n")
    assert names(a) == ["Alice"], f"obtenu {names(a)}"


def test_A36_trou_emails_vides_ne_sont_pas_des_doublons():
    a = new_app()
    make(a, "Alice", email="")
    a.import_csv(HEADER + "\nBruno,0602,,,non\nCharles,0603,,,non\n")
    assert sorted(names(a)) == ["Alice", "Bruno", "Charles"], f"obtenu {names(a)}"


def test_A36_trou_doublon_interne_au_fichier():
    a = new_app()
    a.import_csv(
        HEADER + "\nAlice,0601,alice@x.com,,non\nAlice2,0602,alice@x.com,,non\n"
    )
    emails = [r["email"] for r in a.list_rows()]
    assert emails.count("alice@x.com") == 1, f"obtenu {a.list_rows()}"


def test_A37_etiquettes_point_virgule():
    a = new_app()
    a.import_csv(HEADER + "\nAlice,0601,alice@x.com,travail;famille,non\n")
    cid = row_of_name(a, "Alice")
    assert sorted(a.card(cid)["tags"]) == ["famille", "travail"], (
        f"obtenu {a.card(cid)['tags']}"
    )


def test_A38_favori_oui():
    a = new_app()
    a.import_csv(HEADER + "\nAlice,0601,alice@x.com,,oui\n")
    cid = row_of_name(a, "Alice")
    assert row_of(a, cid)["favorite"] is True
    assert a.card(cid)["favorite"] is True


def test_A38_trou_favori_non():
    a = new_app()
    a.import_csv(HEADER + "\nAlice,0601,alice@x.com,,non\n")
    cid = row_of_name(a, "Alice")
    assert row_of(a, cid)["favorite"] is False


# ---------------------------------------------------------------- rechargement

def test_A39_recharger_conserve_contacts():
    s = app.MemoryStorage()
    a = app.App(storage=s)
    make(a, "Alice", email="alice@x.com")
    make(a, "Bruno")
    b = app.App(storage=s)
    assert sorted(names(b)) == ["Alice", "Bruno"], f"obtenu {names(b)}"


def test_A39_stockage_distinct_ne_partage_rien():
    s1 = app.MemoryStorage()
    a = app.App(storage=s1)
    make(a, "Alice")
    b = app.App(storage=app.MemoryStorage())
    assert names(b) == [], (
        f"un autre stockage ne doit rien contenir (pas d'état global), obtenu {names(b)}"
    )


def test_A39_trou_suppression_persiste_apres_rechargement():
    s = app.MemoryStorage()
    a = app.App(storage=s)
    cid = make(a, "Alice")
    make(a, "Bruno")
    a.request_delete(cid)
    a.confirm_delete()
    b = app.App(storage=s)
    assert names(b) == ["Bruno"], f"obtenu {names(b)}"


def test_A39_trou_recherche_non_persistee_apres_rechargement():
    s = app.MemoryStorage()
    a = app.App(storage=s)
    make(a, "Alice")
    make(a, "Bruno")
    a.set_search("ali")
    b = app.App(storage=s)
    assert sorted(names(b)) == ["Alice", "Bruno"], f"obtenu {names(b)}"
