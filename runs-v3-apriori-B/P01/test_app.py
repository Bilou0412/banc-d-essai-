"""Tests rouges — gestionnaire de contacts (couche code).

Interface publique fixée par ces tests (module `app`) :

    app.Storage()                      stockage persistant en mémoire (survit au rechargement)
    app.App(storage)                   (re)charge l'application sur ce stockage

    a.create(name, phone="", email="") -> id du contact créé, ou None si refusé
    a.error                            -> message d'erreur affiché (str) ou None
    a.visible_names()                  -> list[str], noms affichés dans la liste, dans l'ordre
    a.empty_message                    -> "Aucun contact" quand la liste affichée est vide, sinon None
    a.card(cid)                        -> dict {"name", "phone", "email", "tags": list[str], "favorite": bool}

    ed = a.begin_edit(cid)             -> formulaire de modification (attributs name, phone, email)
    ed.validate()                      -> True si enregistré, False sinon (a.error renseigné)
    ed.cancel()

    a.request_delete(cid)              -> affiche une demande de confirmation
    a.confirmation                     -> texte de la demande (str) ou None
    a.confirm() / a.refuse()

    a.set_search(text)                 ("" efface la recherche)
    a.set_sort("asc" | "desc")
    a.add_tag(cid, tag) / a.remove_tag(cid, tag)
    a.set_tag_filter(tag | None)
    a.set_favorite(cid, bool)
    a.export_csv()                     -> str (contenu du fichier)
    a.import_csv(text)                 (a.error renseigné en cas d'erreur)
"""

import csv
import io
import re

import app

HEADER = "nom,téléphone,email,étiquettes,favori"


def nouvelle_app(storage=None):
    return app.App(storage if storage is not None else app.Storage())


def creer(a, nom, telephone="", email=""):
    cid = a.create(nom, telephone, email)
    assert cid is not None, f"création de {nom!r} refusée de façon inattendue, erreur affichée : {a.error!r}"
    return cid


def lire_csv(texte):
    return list(csv.reader(io.StringIO(texte.lstrip("﻿"))))


def fichier(*lignes, sep="\n"):
    return sep.join((HEADER,) + lignes) + sep


# ---------------------------------------------------------------- création

def test_A01_nom_non_vide_ajoute_le_contact():
    a = nouvelle_app()
    creer(a, "Alice")
    assert a.visible_names() == ["Alice"], f"attendu ['Alice'], obtenu {a.visible_names()!r}"
    assert a.error is None, f"aucune erreur attendue, obtenu {a.error!r}"


def test_A01_deux_creations_deux_contacts():
    a = nouvelle_app()
    creer(a, "Alice")
    creer(a, "Bob")
    assert sorted(a.visible_names()) == ["Alice", "Bob"], f"obtenu {a.visible_names()!r}"


def test_A01_trou_erreur_effacee_apres_creation_valide():
    a = nouvelle_app()
    assert a.create("", "", "") is None
    creer(a, "Alice")
    assert a.error is None, f"l'erreur précédente devait disparaître, toujours affiché : {a.error!r}"


def test_A02_nom_vide_affiche_erreur():
    a = nouvelle_app()
    cid = a.create("", "0601020304", "a@x.fr")
    assert cid is None, f"la création devait être refusée, id obtenu {cid!r}"
    assert a.error == "Le nom est obligatoire", f"attendu « Le nom est obligatoire », obtenu {a.error!r}"


def test_A02_trou_nom_espaces():
    a = nouvelle_app()
    cid = a.create("   ", "", "")
    assert cid is None, f"un nom fait d'espaces devait être refusé, id obtenu {cid!r}"
    assert a.error == "Le nom est obligatoire", f"obtenu {a.error!r}"


def test_A03_nom_vide_n_ajoute_rien():
    a = nouvelle_app()
    creer(a, "Alice")
    a.create("", "", "")
    assert a.visible_names() == ["Alice"], f"attendu ['Alice'] seul, obtenu {a.visible_names()!r}"


def test_A04_email_sans_arobase():
    a = nouvelle_app()
    a.create("Alice", "", "alice.example.com")
    assert a.error == "Email invalide", f"attendu « Email invalide », obtenu {a.error!r}"


def test_A05_telephone_avec_lettres():
    a = nouvelle_app()
    a.create("Alice", "06AB0203", "")
    assert a.error == "Téléphone invalide", f"attendu « Téléphone invalide », obtenu {a.error!r}"


def test_A05_trou_telephone_ponctuation_accepte():
    a = nouvelle_app()
    cid = a.create("Alice", "+33 6 12-34-56-78", "")
    assert a.error is None, f"un téléphone sans lettre ne doit pas être refusé, erreur : {a.error!r}"
    assert cid is not None


def test_A06_email_vide_sans_erreur():
    a = nouvelle_app()
    cid = a.create("Alice", "0601020304", "")
    assert a.error is None, f"aucune erreur attendue pour un email vide, obtenu {a.error!r}"
    assert cid is not None and a.visible_names() == ["Alice"]


# ---------------------------------------------------------------- modification

def test_A07_modification_du_nom():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    ed = a.begin_edit(cid)
    ed.name = "Alicia"
    assert ed.validate() is True, f"validation refusée : {a.error!r}"
    assert a.card(cid)["name"] == "Alicia", f"attendu 'Alicia', obtenu {a.card(cid)['name']!r}"
    assert a.visible_names() == ["Alicia"], f"obtenu {a.visible_names()!r}"


def test_A08_modification_nom_vide():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    ed = a.begin_edit(cid)
    ed.name = ""
    assert ed.validate() is False
    assert a.error == "Le nom est obligatoire", f"obtenu {a.error!r}"


def test_A08_trou_nom_conserve_apres_echec():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    ed = a.begin_edit(cid)
    ed.name = ""
    ed.validate()
    assert a.card(cid)["name"] == "Alice", f"l'ancien nom devait rester, obtenu {a.card(cid)['name']!r}"


def test_A09_annuler_garde_ancien_nom():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    ed = a.begin_edit(cid)
    ed.name = "Bob"
    ed.cancel()
    assert a.card(cid)["name"] == "Alice", f"attendu 'Alice', obtenu {a.card(cid)['name']!r}"
    assert a.visible_names() == ["Alice"]


# ---------------------------------------------------------------- suppression

def test_A10_demande_de_confirmation():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    assert a.confirmation is None
    a.request_delete(cid)
    assert isinstance(a.confirmation, str) and a.confirmation.strip(), \
        f"une demande de confirmation était attendue, obtenu {a.confirmation!r}"
    assert a.visible_names() == ["Alice"], "le contact ne doit pas disparaître avant confirmation"


def test_A11_confirmer_supprime():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    creer(a, "Bob")
    a.request_delete(cid)
    a.confirm()
    assert a.visible_names() == ["Bob"], f"attendu ['Bob'], obtenu {a.visible_names()!r}"
    assert a.confirmation is None


def test_A12_refuser_garde_le_contact():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    a.request_delete(cid)
    a.refuse()
    assert a.visible_names() == ["Alice"], f"obtenu {a.visible_names()!r}"
    assert a.confirmation is None


# ---------------------------------------------------------------- recherche

def test_A13_recherche_insensible_casse():
    a = nouvelle_app()
    for n in ["Martin", "MARTINE", "Bob", "Amartine"]:
        creer(a, n)
    a.set_search("mArT")
    assert sorted(a.visible_names()) == ["Amartine", "MARTINE", "Martin"], f"obtenu {a.visible_names()!r}"


def test_A13_trou_recherche_insensible_accents():
    a = nouvelle_app()
    creer(a, "Élodie")
    creer(a, "Bob")
    a.set_search("elodie")
    assert a.visible_names() == ["Élodie"], f"obtenu {a.visible_names()!r}"


def test_A14_recherche_dans_email():
    a = nouvelle_app()
    creer(a, "Alice", "", "zorglub@exemple.fr")
    creer(a, "Bob", "", "bob@exemple.fr")
    a.set_search("ZORG")
    assert a.visible_names() == ["Alice"], f"obtenu {a.visible_names()!r}"


def test_A15_aucun_resultat():
    a = nouvelle_app()
    creer(a, "Alice")
    a.set_search("xyz")
    assert a.visible_names() == []
    assert a.empty_message == "Aucun contact", f"obtenu {a.empty_message!r}"


def test_A15_trou_message_absent_si_resultats():
    a = nouvelle_app()
    creer(a, "Alice")
    a.set_search("ali")
    assert a.empty_message is None, f"le message ne doit pas s'afficher, obtenu {a.empty_message!r}"


def test_A16_effacer_recherche():
    a = nouvelle_app()
    for n in ["Alice", "Bob", "Charles"]:
        creer(a, n)
    a.set_search("bob")
    a.set_search("")
    assert sorted(a.visible_names()) == ["Alice", "Bob", "Charles"], f"obtenu {a.visible_names()!r}"
    assert a.empty_message is None


# ---------------------------------------------------------------- tri

def test_A17_tri_croissant():
    a = nouvelle_app()
    for n in ["Charles", "bob", "Alice"]:
        creer(a, n)
    a.set_sort("asc")
    assert a.visible_names() == ["Alice", "bob", "Charles"], f"obtenu {a.visible_names()!r}"


def test_A18_tri_decroissant():
    a = nouvelle_app()
    for n in ["bob", "Alice", "Charles"]:
        creer(a, n)
    a.set_sort("desc")
    assert a.visible_names() == ["Charles", "bob", "Alice"], f"obtenu {a.visible_names()!r}"


def test_A19_elodie_entre_denis_et_fabien():
    a = nouvelle_app()
    for n in ["Zoé", "Fabien", "élodie", "alain", "Denis"]:
        creer(a, n)
    a.set_sort("asc")
    assert a.visible_names() == ["alain", "Denis", "élodie", "Fabien", "Zoé"], f"obtenu {a.visible_names()!r}"


def test_A20_creation_placee_selon_tri():
    a = nouvelle_app()
    a.set_sort("asc")
    creer(a, "Alice")
    creer(a, "Charles")
    creer(a, "Bob")
    assert a.visible_names() == ["Alice", "Bob", "Charles"], f"obtenu {a.visible_names()!r}"
    a.set_sort("desc")
    creer(a, "Berthe")
    assert a.visible_names() == ["Charles", "Bob", "Berthe", "Alice"], f"obtenu {a.visible_names()!r}"


def test_A20_trou_tri_par_defaut_croissant():
    a = nouvelle_app()
    for n in ["Charles", "Alice", "Bob"]:
        creer(a, n)
    assert a.visible_names() == ["Alice", "Bob", "Charles"], f"obtenu {a.visible_names()!r}"


def test_A21_favoris_en_tete():
    a = nouvelle_app()
    ids = {n: creer(a, n) for n in ["Alice", "Bob", "Charles", "Zoé"]}
    a.set_favorite(ids["Zoé"], True)
    a.set_favorite(ids["Bob"], True)
    for ordre in ["asc", "desc"]:
        a.set_sort(ordre)
        noms = a.visible_names()
        assert set(noms[:2]) == {"Bob", "Zoé"}, f"tri {ordre} : favoris attendus en tête, obtenu {noms!r}"


def test_A21_trou_ordre_entre_favoris():
    a = nouvelle_app()
    ids = {n: creer(a, n) for n in ["Alice", "Bob", "Charles", "Zoé"]}
    a.set_favorite(ids["Zoé"], True)
    a.set_favorite(ids["Bob"], True)
    a.set_sort("asc")
    assert a.visible_names() == ["Bob", "Zoé", "Alice", "Charles"], f"obtenu {a.visible_names()!r}"
    a.set_sort("desc")
    assert a.visible_names() == ["Zoé", "Bob", "Charles", "Alice"], f"obtenu {a.visible_names()!r}"


# ---------------------------------------------------------------- étiquettes

def test_A22_ajout_etiquette():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    a.add_tag(cid, "travail")
    assert a.card(cid)["tags"] == ["travail"], f"obtenu {a.card(cid)['tags']!r}"


def test_A23_etiquette_en_double():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    a.add_tag(cid, "travail")
    a.add_tag(cid, "travail")
    assert a.card(cid)["tags"].count("travail") == 1, f"obtenu {a.card(cid)['tags']!r}"


def test_A24_retrait_etiquette():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    a.add_tag(cid, "travail")
    a.add_tag(cid, "famille")
    a.remove_tag(cid, "travail")
    assert a.card(cid)["tags"] == ["famille"], f"obtenu {a.card(cid)['tags']!r}"


def test_A25_filtre_par_etiquette():
    a = nouvelle_app()
    ida = creer(a, "Alice")
    idb = creer(a, "Bob")
    creer(a, "Charles")
    a.add_tag(ida, "travail")
    a.add_tag(idb, "famille")
    a.set_tag_filter("travail")
    assert a.visible_names() == ["Alice"], f"obtenu {a.visible_names()!r}"
    a.set_tag_filter(None)
    assert sorted(a.visible_names()) == ["Alice", "Bob", "Charles"]


def test_A26_filtre_et_recherche():
    a = nouvelle_app()
    ida = creer(a, "Alice")
    idal = creer(a, "Albert")
    idb = creer(a, "Bob")
    for cid in (ida, idb):
        a.add_tag(cid, "travail")
    a.add_tag(idal, "famille")
    a.set_tag_filter("travail")
    a.set_search("al")
    assert a.visible_names() == ["Alice"], f"obtenu {a.visible_names()!r}"


# ---------------------------------------------------------------- favoris

def test_A27_marquer_favori():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    autre = creer(a, "Bob")
    a.set_favorite(cid, True)
    assert a.card(cid)["favorite"] is True
    assert a.card(autre)["favorite"] is False


def test_A28_retirer_favori():
    a = nouvelle_app()
    cid = creer(a, "Alice")
    a.set_favorite(cid, True)
    a.set_favorite(cid, False)
    assert a.card(cid)["favorite"] is False


# ---------------------------------------------------------------- export

def test_A29_entete_export():
    a = nouvelle_app()
    creer(a, "Alice")
    premiere = a.export_csv().lstrip("﻿").splitlines()[0]
    assert premiere == HEADER, f"attendu {HEADER!r}, obtenu {premiere!r}"


def test_A29_trou_format_favori_et_etiquettes():
    a = nouvelle_app()
    cid = creer(a, "Alice", "0601", "a@x.fr")
    a.add_tag(cid, "travail")
    a.add_tag(cid, "famille")
    a.set_favorite(cid, True)
    creer(a, "Bob")
    lignes = {r[0]: r for r in lire_csv(a.export_csv())[1:]}
    alice = lignes["Alice"]
    assert alice[1:3] == ["0601", "a@x.fr"], f"obtenu {alice!r}"
    assert sorted(alice[3].split(";")) == ["famille", "travail"], f"obtenu {alice[3]!r}"
    assert alice[4] == "oui", f"favori attendu « oui », obtenu {alice[4]!r}"
    assert lignes["Bob"][4] == "non", f"non-favori attendu « non », obtenu {lignes['Bob'][4]!r}"


def test_A30_export_ignore_recherche_et_filtre():
    a = nouvelle_app()
    ida = creer(a, "Alice")
    creer(a, "Bob")
    creer(a, "Charles")
    a.add_tag(ida, "travail")
    a.set_tag_filter("travail")
    a.set_search("ali")
    lignes = [r for r in lire_csv(a.export_csv())[1:] if r]
    assert sorted(r[0] for r in lignes) == ["Alice", "Bob", "Charles"], f"obtenu {lignes!r}"


def test_A31_nom_avec_virgule_entre_guillemets():
    a = nouvelle_app()
    creer(a, "Dupont, Jean")
    texte = a.export_csv()
    assert '"Dupont, Jean"' in texte, f"nom entre guillemets attendu, fichier obtenu :\n{texte}"
    lignes = lire_csv(texte)
    assert lignes[1][0] == "Dupont, Jean" and len(lignes[1]) == 5, f"obtenu {lignes[1]!r}"


def test_A31_trou_guillemet_dans_le_nom():
    a = nouvelle_app()
    creer(a, 'Jean "Jojo", Dupont')
    texte = a.export_csv()
    assert '"Jean ""Jojo"", Dupont"' in texte, f"guillemets doublés attendus, fichier :\n{texte}"
    b = nouvelle_app()
    b.import_csv(texte)
    assert b.visible_names() == ['Jean "Jojo", Dupont'], f"aller-retour : obtenu {b.visible_names()!r}"


# ---------------------------------------------------------------- import

def test_A32_import_un_contact_par_ligne():
    a = nouvelle_app()
    creer(a, "Existant")
    a.import_csv(fichier("Alice,0601,a@x.fr,,non", "Bob,,b@x.fr,,non", '"Dupont, Jean",,,,non'))
    assert a.error is None, f"aucune erreur attendue, obtenu {a.error!r}"
    assert sorted(a.visible_names()) == ["Alice", "Bob", "Dupont, Jean", "Existant"], f"obtenu {a.visible_names()!r}"


def test_A32_aller_retour_export_import():
    a = nouvelle_app()
    cid = creer(a, "Dupont, Jean", "0601", "j@x.fr")
    a.add_tag(cid, "travail")
    a.set_favorite(cid, True)
    b = nouvelle_app()
    b.import_csv(a.export_csv())
    assert b.visible_names() == ["Dupont, Jean"], f"obtenu {b.visible_names()!r}"


def test_A33_ligne_sans_nom_numero():
    a = nouvelle_app()
    a.import_csv(fichier("Alice,,a@x.fr,,non", "Bob,,b@x.fr,,non", "Claire,,c@x.fr,,non", ",0600,d@x.fr,,non"))
    assert a.error is not None, "une erreur était attendue"
    # le numéro de la ligne fautive (5 en comptant l'en-tête, 4 en données) doit figurer
    assert re.search(r"\b[45]\b", a.error), f"numéro de ligne attendu dans l'erreur, obtenu {a.error!r}"


def test_A33_trou_numerotation_compte_entete():
    a = nouvelle_app()
    a.import_csv(fichier("Alice,,a@x.fr,,non", ",0600,b@x.fr,,non"))
    assert a.error is not None and re.search(r"\b3\b", a.error) and not re.search(r"\b2\b", a.error), \
        f"ligne 3 du fichier attendue dans l'erreur, obtenu {a.error!r}"


def test_A34_ligne_sans_nom_non_ajoutee():
    a = nouvelle_app()
    a.import_csv(fichier(",0600,b@x.fr,,non"))
    assert a.visible_names() == [], f"obtenu {a.visible_names()!r}"


def test_A34_trou_autres_lignes_importees():
    a = nouvelle_app()
    a.import_csv(fichier("Alice,,a@x.fr,,non", ",0600,b@x.fr,,non", "Charles,,c@x.fr,,non"))
    assert sorted(a.visible_names()) == ["Alice", "Charles"], f"obtenu {a.visible_names()!r}"


def test_A35_sans_entete():
    a = nouvelle_app()
    a.import_csv("Alice,0601,a@x.fr,,non\nBob,,b@x.fr,,non\n")
    assert a.error == "Format CSV invalide", f"obtenu {a.error!r}"


def test_A35_entete_differente():
    a = nouvelle_app()
    a.import_csv("name,phone,email,tags,favorite\nAlice,,a@x.fr,,non\n")
    assert a.error == "Format CSV invalide", f"obtenu {a.error!r}"


def test_A35_trou_fin_de_ligne_crlf_et_bom_acceptes():
    a = nouvelle_app()
    a.import_csv("﻿" + fichier("Alice,,a@x.fr,,non", "Bob,,b@x.fr,,non", sep="\r\n"))
    assert a.error is None, f"aucune erreur attendue, obtenu {a.error!r}"
    assert sorted(a.visible_names()) == ["Alice", "Bob"], f"obtenu {a.visible_names()!r}"


def test_A36_pas_de_doublon_email():
    a = nouvelle_app()
    creer(a, "Alice", "", "a@x.fr")
    a.import_csv(fichier("Alice bis,,a@x.fr,,non", "Bob,,b@x.fr,,non"))
    assert sorted(a.visible_names()) == ["Alice", "Bob"], f"obtenu {a.visible_names()!r}"


def test_A36_trou_email_casse():
    a = nouvelle_app()
    creer(a, "Alice", "", "a@x.fr")
    a.import_csv(fichier("Alice bis,,A@X.FR,,non"))
    assert a.visible_names() == ["Alice"], f"obtenu {a.visible_names()!r}"


def test_A36_trou_email_vide_pas_un_doublon():
    a = nouvelle_app()
    creer(a, "Alice", "", "")
    a.import_csv(fichier("Bob,,,,non", "Charles,,,,non"))
    assert sorted(a.visible_names()) == ["Alice", "Bob", "Charles"], f"obtenu {a.visible_names()!r}"


def test_A36_trou_doublon_dans_le_meme_fichier():
    a = nouvelle_app()
    a.import_csv(fichier("Alice,,a@x.fr,,non", "Alice bis,,a@x.fr,,non"))
    assert a.visible_names() == ["Alice"], f"obtenu {a.visible_names()!r}"


def test_A37_etiquettes_importees():
    a = nouvelle_app()
    a.import_csv(fichier("Alice,,a@x.fr,travail;famille,non"))
    a.set_search("alice")
    cid = None
    # retrouver le contact via le filtre puis la fiche
    a.set_search("")
    a.set_tag_filter("famille")
    assert a.visible_names() == ["Alice"], f"obtenu {a.visible_names()!r}"
    a.set_tag_filter(None)
    b_ids = [c for c in [a.create("Témoin")] if c is not None]
    assert b_ids
    # fiche du contact importé : retrouvée par export croisé
    lignes = {r[0]: r for r in lire_csv(a.export_csv())[1:] if r}
    assert sorted(lignes["Alice"][3].split(";")) == ["famille", "travail"], f"obtenu {lignes['Alice']!r}"


def test_A38_favori_importe():
    a = nouvelle_app()
    a.import_csv(fichier("Bob,,b@x.fr,,non", "Zoé,,z@x.fr,,oui", "Alice,,a@x.fr,,non"))
    a.set_sort("asc")
    assert a.visible_names()[0] == "Zoé", f"le favori importé doit être en tête, obtenu {a.visible_names()!r}"


# ---------------------------------------------------------------- rechargement

def test_A39_rechargement_conserve_les_contacts():
    s = app.Storage()
    a = app.App(s)
    creer(a, "Alice")
    creer(a, "Bob", "0601", "b@x.fr")
    recharge = app.App(s)
    assert sorted(recharge.visible_names()) == ["Alice", "Bob"], f"obtenu {recharge.visible_names()!r}"


def test_A39_stockages_independants():
    s1 = app.Storage()
    creer(app.App(s1), "Alice")
    autre = app.App(app.Storage())
    assert autre.visible_names() == [], f"un nouveau stockage doit être vide, obtenu {autre.visible_names()!r}"


def test_A39_trou_suppression_persistante():
    s = app.Storage()
    a = app.App(s)
    cid = creer(a, "Alice")
    creer(a, "Bob")
    a.request_delete(cid)
    a.confirm()
    assert app.App(s).visible_names() == ["Bob"]


def test_A39_trou_etiquettes_et_favoris_persistants():
    s = app.Storage()
    a = app.App(s)
    creer(a, "Alice")
    cid = creer(a, "Zoé")
    a.add_tag(cid, "travail")
    a.set_favorite(cid, True)
    r = app.App(s)
    assert r.visible_names()[0] == "Zoé", f"favori perdu au rechargement : {r.visible_names()!r}"
    r.set_tag_filter("travail")
    assert r.visible_names() == ["Zoé"], f"étiquette perdue au rechargement : {r.visible_names()!r}"
