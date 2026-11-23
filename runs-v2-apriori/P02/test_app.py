"""Tests rouges — couche code — sonde « recettes ».

Interface publique fixée par ces tests (module `app`) :

    app.ValidationError                      exception levée pour toute saisie refusée
    app.DEFAULT_PHOTO                        bytes de l'image par défaut (une vraie image PNG)
    app.Storage()                            stockage en mémoire qui survit à la fermeture de l'App
    app.App(storage)                         ouvre l'application sur ce stockage
      .close()                               ferme l'application
      .save_recipe(title, servings=4) -> id  enregistre une recette ; titre vide -> ValidationError
      .recipe_list() -> list[str]            titres de la liste des recettes
      .delete_recipe(id)
      .add_ingredient(id, name, quantity, unit)   quantité invalide -> ValidationError
      .remove_ingredient(id, name)
      .open(id) -> dict                      fiche de la recette, aux portions d'origine
      .adjust_servings(id, n) -> dict        fiche affichée avec n portions ; n < 1 -> ValidationError
      .set_category(id, category)
      .set_favorite(id, bool)
      .set_note(id, text)                    texte vide -> la note disparaît (None)
      .set_photo(id, data: bytes)            non-image -> ValidationError
      .remove_photo(id)
      .search(query="", category=None, favorites_only=False) -> dict
            {"titles": list[str], "message": str | None}  ("Aucun résultat" si vide)
      .add_to_shopping_list(id, servings=None)    servings=None -> portions d'origine
      .shopping_list() -> list[dict]         {"name", "quantity", "unit", "checked"}
      .check_item(name, unit)
      .remove_checked()

Fiche (dict) : {"title", "servings", "category", "favorite", "note", "photo",
                "ingredients": [{"name", "quantity", "unit"}]}
"""

import struct
import zlib

import pytest

import app


# ---------------------------------------------------------------- utilitaires

def _png_bytes():
    """Une vraie image PNG 1x1, construite avec la bibliothèque standard."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png_bytes()


@pytest.fixture
def storage():
    return app.Storage()


@pytest.fixture
def a(storage):
    return app.App(storage)


def _ingredient(card, name):
    found = [i for i in card["ingredients"] if i["name"] == name]
    assert len(found) == 1, f"attendu un ingrédient {name!r} sur la fiche, obtenu {card['ingredients']!r}"
    return found[0]


def _lines(a, name, unit=None):
    return [l for l in a.shopping_list()
            if l["name"].lower() == name.lower() and (unit is None or l["unit"] == unit)]


def _crepes(a, servings=4):
    rid = a.save_recipe("Crêpes", servings=servings)
    a.add_ingredient(rid, "farine", 200, "g")
    a.add_ingredient(rid, "oeufs", 3, "pièce")
    return rid


# ---------------------------------------------------------------- A01 / A02

def test_A01_titre_vide_ne_cree_pas_la_recette(a):
    with pytest.raises(app.ValidationError):
        a.save_recipe("")
    assert a.recipe_list() == [], f"attendu aucune recette, obtenu {a.recipe_list()!r}"


def test_A01_titre_vide_ne_change_pas_une_liste_existante(a):
    a.save_recipe("Soupe")
    with pytest.raises(app.ValidationError):
        a.save_recipe("")
    assert a.recipe_list() == ["Soupe"], f"attendu ['Soupe'], obtenu {a.recipe_list()!r}"


def test_A01_trou_titre_blanc(a):
    with pytest.raises(app.ValidationError):
        a.save_recipe("   \t\n")
    assert a.recipe_list() == [], f"un titre fait de blancs ne doit pas créer de recette, obtenu {a.recipe_list()!r}"


def test_A02_titre_non_vide_apparait_dans_la_liste(a):
    a.save_recipe("Tarte aux pommes")
    assert "Tarte aux pommes" in a.recipe_list(), f"obtenu {a.recipe_list()!r}"


def test_A02_deux_recettes_apparaissent(a):
    a.save_recipe("Tarte")
    a.save_recipe("Crème brûlée")
    assert sorted(a.recipe_list()) == ["Crème brûlée", "Tarte"], f"obtenu {a.recipe_list()!r}"


# ---------------------------------------------------------------- A03 / A04

def test_A03_ajout_ingredient_apparait_sur_la_fiche(a):
    rid = a.save_recipe("Pain")
    a.add_ingredient(rid, "farine", 500, "g")
    ing = _ingredient(a.open(rid), "farine")
    assert ing["quantity"] == 500 and ing["unit"] == "g", f"attendu 500 g, obtenu {ing!r}"


def test_A03_ingredient_ne_fuit_pas_vers_une_autre_recette(a):
    r1 = a.save_recipe("Pain")
    r2 = a.save_recipe("Soupe")
    a.add_ingredient(r1, "farine", 500, "g")
    assert a.open(r2)["ingredients"] == [], f"obtenu {a.open(r2)['ingredients']!r}"


def test_A04_suppression_ingredient_le_fait_disparaitre(a):
    rid = _crepes(a)
    a.remove_ingredient(rid, "farine")
    names = [i["name"] for i in a.open(rid)["ingredients"]]
    assert names == ["oeufs"], f"attendu ['oeufs'], obtenu {names!r}"


# ---------------------------------------------------------------- A05 / A06

@pytest.mark.parametrize("bad", ["abc", "", "12abc", None])
def test_A05_quantite_non_numerique_refusee(a, bad):
    rid = a.save_recipe("Pain")
    with pytest.raises(app.ValidationError):
        a.add_ingredient(rid, "farine", bad, "g")
    assert a.open(rid)["ingredients"] == [], f"aucun ingrédient attendu, obtenu {a.open(rid)['ingredients']!r}"


@pytest.mark.parametrize("bad", ["nan", "inf"])
def test_A05_trou_nan_et_infini(a, bad):
    rid = a.save_recipe("Pain")
    with pytest.raises(app.ValidationError):
        a.add_ingredient(rid, "farine", bad, "g")
    assert a.open(rid)["ingredients"] == []


@pytest.mark.parametrize("bad", [0, -1, -0.5, "0", "-3"])
def test_A06_quantite_negative_ou_nulle_refusee(a, bad):
    rid = a.save_recipe("Pain")
    with pytest.raises(app.ValidationError):
        a.add_ingredient(rid, "farine", bad, "g")
    assert a.open(rid)["ingredients"] == [], f"aucun ingrédient attendu, obtenu {a.open(rid)['ingredients']!r}"


# ---------------------------------------------------------------- A07 – A12

def test_A07_quatre_a_huit_double_chaque_quantite(a):
    rid = _crepes(a)
    card = a.adjust_servings(rid, 8)
    assert card["servings"] == 8
    assert _ingredient(card, "farine")["quantity"] == 400
    assert _ingredient(card, "oeufs")["quantity"] == 6


def test_A08_quatre_a_deux_divise_par_deux(a):
    rid = _crepes(a)
    card = a.adjust_servings(rid, 2)
    assert _ingredient(card, "farine")["quantity"] == 100
    assert _ingredient(card, "oeufs")["quantity"] == 1.5, f"obtenu {_ingredient(card, 'oeufs')!r}"


def test_A09_quantite_non_entiere_arrondie_deux_decimales(a):
    rid = a.save_recipe("Sauce", servings=3)
    a.add_ingredient(rid, "sel", 100, "g")
    a.add_ingredient(rid, "poivre", 1, "g")
    card = a.adjust_servings(rid, 2)
    assert _ingredient(card, "sel")["quantity"] == 66.67, f"attendu 66.67 (arrondi, pas tronqué), obtenu {_ingredient(card, 'sel')!r}"
    assert _ingredient(card, "poivre")["quantity"] == 0.67, f"attendu 0.67, obtenu {_ingredient(card, 'poivre')!r}"


def test_A10_ajustement_ne_change_pas_l_unite(a):
    rid = _crepes(a)
    card = a.adjust_servings(rid, 8)
    assert _ingredient(card, "farine")["unit"] == "g"
    assert _ingredient(card, "oeufs")["unit"] == "pièce"


@pytest.mark.parametrize("bad", [0, -1, 0.5])
def test_A11_portions_inferieures_a_un_refusees(a, bad):
    rid = _crepes(a)
    with pytest.raises(app.ValidationError):
        a.adjust_servings(rid, bad)
    card = a.open(rid)
    assert card["servings"] == 4 and _ingredient(card, "farine")["quantity"] == 200


def test_A12_reouverture_affiche_les_portions_d_origine(a):
    rid = _crepes(a)
    a.adjust_servings(rid, 8)
    card = a.open(rid)
    assert card["servings"] == 4, f"attendu 4 portions d'origine, obtenu {card['servings']!r}"
    assert _ingredient(card, "farine")["quantity"] == 200


def test_A12_ajustements_successifs_partent_de_l_origine(a):
    rid = _crepes(a)
    a.adjust_servings(rid, 2)
    a.adjust_servings(rid, 1)
    card = a.adjust_servings(rid, 8)
    assert _ingredient(card, "farine")["quantity"] == 400, f"obtenu {_ingredient(card, 'farine')!r}"


# ---------------------------------------------------------------- A13 / A14

def test_A13_categorie_affichee_sur_la_fiche(a):
    rid = a.save_recipe("Tarte")
    a.set_category(rid, "Dessert")
    assert a.open(rid)["category"] == "Dessert"


def test_A14_filtre_categorie_ne_montre_que_cette_categorie(a):
    t = a.save_recipe("Tarte")
    s = a.save_recipe("Soupe")
    a.save_recipe("Sans catégorie")
    a.set_category(t, "Dessert")
    a.set_category(s, "Entrée")
    res = a.search("", category="Dessert")
    assert res["titles"] == ["Tarte"], f"attendu ['Tarte'], obtenu {res['titles']!r}"


# ---------------------------------------------------------------- A15 – A19

def test_A15_mot_du_titre_trouve_la_recette(a):
    a.save_recipe("Tarte aux pommes")
    a.save_recipe("Soupe")
    assert a.search("pommes")["titles"] == ["Tarte aux pommes"]


def test_A15_trou_requete_de_plusieurs_mots(a):
    a.save_recipe("Tarte aux pommes")
    res = a.search("pommes rapides")
    assert res["titles"] == ["Tarte aux pommes"], (
        f"la requête contient le mot 'pommes' du titre ; obtenu {res['titles']!r}")


def test_A16_nom_d_ingredient_trouve_la_recette(a):
    c = _crepes(a)
    s = a.save_recipe("Soupe")
    a.add_ingredient(s, "poireau", 2, "pièce")
    assert a.search("farine")["titles"] == ["Crêpes"]


def test_A16_ingredient_retire_ne_trouve_plus(a):
    c = _crepes(a)
    a.remove_ingredient(c, "farine")
    assert a.search("farine")["titles"] == []


def test_A17_majuscules_meme_resultat_que_minuscules(a):
    a.save_recipe("Crêpes sucrées")
    a.save_recipe("Soupe")
    low = a.search("crêpes")["titles"]
    up = a.search("CRÊPES")["titles"]
    assert low == up == ["Crêpes sucrées"], f"minuscules {low!r}, majuscules {up!r}"


def test_A17_majuscules_sur_ingredient(a):
    _crepes(a)
    assert a.search("FARINE")["titles"] == a.search("farine")["titles"] == ["Crêpes"]


def test_A18_requete_vide_montre_tout(a):
    a.save_recipe("A")
    a.save_recipe("B")
    a.save_recipe("C")
    res = a.search("")
    assert sorted(res["titles"]) == ["A", "B", "C"]
    assert res["message"] is None


def test_A18_trou_requete_de_blancs(a):
    a.save_recipe("A")
    a.save_recipe("B")
    assert sorted(a.search("   ")["titles"]) == ["A", "B"]


def test_A19_sans_correspondance_message_aucun_resultat(a):
    a.save_recipe("Tarte")
    res = a.search("zzzz")
    assert res["titles"] == []
    assert res["message"] == "Aucun résultat", f"obtenu {res['message']!r}"


def test_A19_avec_correspondance_pas_de_message(a):
    a.save_recipe("Tarte")
    assert a.search("tarte")["message"] != "Aucun résultat"


# ---------------------------------------------------------------- A20 – A22

def test_A20_marquage_favori_active_l_icone(a):
    rid = a.save_recipe("Tarte")
    assert a.open(rid)["favorite"] is False
    a.set_favorite(rid, True)
    assert a.open(rid)["favorite"] is True


def test_A21_retrait_favori_desactive_l_icone(a):
    rid = a.save_recipe("Tarte")
    a.set_favorite(rid, True)
    a.set_favorite(rid, False)
    assert a.open(rid)["favorite"] is False


def test_A22_filtre_favoris(a):
    t = a.save_recipe("Tarte")
    a.save_recipe("Soupe")
    u = a.save_recipe("Ragoût")
    a.set_favorite(t, True)
    a.set_favorite(u, True)
    a.set_favorite(u, False)
    assert a.search("", favorites_only=True)["titles"] == ["Tarte"]


# ---------------------------------------------------------------- A23 / A24

def test_A23_note_affichee(a):
    rid = a.save_recipe("Tarte")
    a.set_note(rid, "Moins de sucre la prochaine fois — ça marche !")
    assert a.open(rid)["note"] == "Moins de sucre la prochaine fois — ça marche !"


def test_A24_effacer_le_texte_retire_la_note(a):
    rid = a.save_recipe("Tarte")
    a.set_note(rid, "Bonne")
    a.set_note(rid, "")
    assert a.open(rid)["note"] is None, f"attendu None, obtenu {a.open(rid)['note']!r}"


def test_A24_trou_note_de_blancs(a):
    rid = a.save_recipe("Tarte")
    a.set_note(rid, "Bonne")
    a.set_note(rid, "  \n ")
    assert a.open(rid)["note"] is None, f"attendu None, obtenu {a.open(rid)['note']!r}"


# ---------------------------------------------------------------- A25 – A28

def test_A25_image_affichee_sur_la_fiche(a):
    rid = a.save_recipe("Tarte")
    a.set_photo(rid, PNG)
    assert a.open(rid)["photo"] == PNG


@pytest.mark.parametrize("bad", [b"bonjour", b"%PDF-1.4\n...", b"", b"\x89PN"])
def test_A26_fichier_non_image_refuse(a, bad):
    rid = a.save_recipe("Tarte")
    with pytest.raises(app.ValidationError):
        a.set_photo(rid, bad)
    assert a.open(rid)["photo"] == app.DEFAULT_PHOTO


def test_A26_refus_ne_remplace_pas_la_photo_existante(a):
    rid = a.save_recipe("Tarte")
    a.set_photo(rid, PNG)
    with pytest.raises(app.ValidationError):
        a.set_photo(rid, b"not an image")
    assert a.open(rid)["photo"] == PNG


def test_A27_sans_photo_image_par_defaut(a):
    rid = a.save_recipe("Tarte")
    photo = a.open(rid)["photo"]
    assert photo == app.DEFAULT_PHOTO
    assert isinstance(photo, bytes) and photo.startswith(b"\x89PNG\r\n\x1a\n"), (
        "l'image par défaut doit être une image (PNG)")
    assert photo != PNG


def test_A28_suppression_photo_affiche_le_defaut(a):
    rid = a.save_recipe("Tarte")
    a.set_photo(rid, PNG)
    a.remove_photo(rid)
    assert a.open(rid)["photo"] == app.DEFAULT_PHOTO


# ---------------------------------------------------------------- A29 – A34

def test_A29_ajout_recette_aux_courses_fait_apparaitre_chaque_ingredient(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid)
    items = {(l["name"], l["unit"]): l["quantity"] for l in a.shopping_list()}
    assert items == {("farine", "g"): 200, ("oeufs", "pièce"): 3}, f"obtenu {items!r}"


def test_A30_portions_ajustees_reportees(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid, servings=8)
    items = {(l["name"], l["unit"]): l["quantity"] for l in a.shopping_list()}
    assert items == {("farine", "g"): 400, ("oeufs", "pièce"): 6}, f"obtenu {items!r}"


def test_A30_portions_ajustees_ne_modifient_pas_la_recette(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid, servings=2)
    assert a.open(rid)["servings"] == 4


def test_A31_meme_ingredient_meme_unite_une_ligne_sommee(a):
    c = _crepes(a)
    p = a.save_recipe("Pain")
    a.add_ingredient(p, "farine", 500, "g")
    a.add_to_shopping_list(c)
    a.add_to_shopping_list(p)
    lines = _lines(a, "farine", "g")
    assert len(lines) == 1, f"attendu une seule ligne farine/g, obtenu {lines!r}"
    assert lines[0]["quantity"] == 700


def test_A31_meme_recette_deux_fois_somme(a):
    c = _crepes(a)
    a.add_to_shopping_list(c)
    a.add_to_shopping_list(c)
    lines = _lines(a, "oeufs", "pièce")
    assert len(lines) == 1 and lines[0]["quantity"] == 6, f"obtenu {lines!r}"


def test_A31_trou_casse_du_nom_ingredient(a):
    c = _crepes(a)
    p = a.save_recipe("Pain")
    a.add_ingredient(p, "Farine", 500, "g")
    a.add_to_shopping_list(c)
    a.add_to_shopping_list(p)
    lines = _lines(a, "farine", "g")
    assert len(lines) == 1 and lines[0]["quantity"] == 700, (
        f"'Farine' et 'farine' sont le même ingrédient ; obtenu {lines!r}")


def test_A31_trou_ajout_sur_article_deja_coche(a):
    c = _crepes(a)
    a.add_to_shopping_list(c)
    a.check_item("farine", "g")
    a.add_to_shopping_list(c)
    lines = _lines(a, "farine", "g")
    assert len(lines) == 1 and lines[0]["quantity"] == 400, f"obtenu {lines!r}"
    assert lines[0]["checked"] is False, "une quantité nouvelle à acheter ne doit pas rester cochée"


def test_A32_meme_ingredient_unites_differentes_deux_lignes(a):
    c = _crepes(a)
    p = a.save_recipe("Gâteau")
    a.add_ingredient(p, "farine", 1, "kg")
    a.add_to_shopping_list(c)
    a.add_to_shopping_list(p)
    lines = {(l["unit"], l["quantity"]) for l in _lines(a, "farine")}
    assert lines == {("g", 200), ("kg", 1)}, f"obtenu {lines!r}"


def test_A33_cochage_affiche_coche(a):
    c = _crepes(a)
    a.add_to_shopping_list(c)
    assert all(l["checked"] is False for l in a.shopping_list())
    a.check_item("farine", "g")
    assert _lines(a, "farine", "g")[0]["checked"] is True
    assert _lines(a, "oeufs", "pièce")[0]["checked"] is False


def test_A34_retirer_les_coches(a):
    c = _crepes(a)
    a.add_to_shopping_list(c)
    a.check_item("farine", "g")
    a.remove_checked()
    names = [l["name"] for l in a.shopping_list()]
    assert names == ["oeufs"], f"attendu ['oeufs'], obtenu {names!r}"


# ---------------------------------------------------------------- A35 / A36

def test_A35_suppression_recette(a):
    t = a.save_recipe("Tarte")
    a.save_recipe("Soupe")
    a.delete_recipe(t)
    assert a.recipe_list() == ["Soupe"]
    assert a.search("tarte")["titles"] == []


def test_A36_suppression_ne_retire_pas_les_courses(a):
    c = _crepes(a)
    a.add_to_shopping_list(c, servings=8)
    a.delete_recipe(c)
    items = {(l["name"], l["unit"]): l["quantity"] for l in a.shopping_list()}
    assert items == {("farine", "g"): 400, ("oeufs", "pièce"): 6}, f"obtenu {items!r}"


# ---------------------------------------------------------------- A37 – A39

def _reopen(a, storage):
    a.close()
    b = app.App(storage)
    assert b is not a
    return b


def test_A37_recette_persiste_apres_reouverture(a, storage):
    rid = _crepes(a)
    b = _reopen(a, storage)
    assert b.recipe_list() == ["Crêpes"]
    card = b.open(rid)
    assert _ingredient(card, "farine")["quantity"] == 200


def test_A37_stockage_neuf_est_vide(a):
    a.save_recipe("Tarte")
    a.close()
    fresh = app.App(app.Storage())
    assert fresh.recipe_list() == [], "un stockage neuf ne doit pas voir les recettes d'un autre stockage"


def test_A37_recette_supprimee_reste_supprimee(a, storage):
    t = a.save_recipe("Tarte")
    a.delete_recipe(t)
    b = _reopen(a, storage)
    assert b.recipe_list() == []


def test_A38_favori_persiste(a, storage):
    t = a.save_recipe("Tarte")
    s = a.save_recipe("Soupe")
    a.set_favorite(t, True)
    b = _reopen(a, storage)
    assert b.open(t)["favorite"] is True
    assert b.open(s)["favorite"] is False


def test_A39_article_coche_persiste(a, storage):
    c = _crepes(a)
    a.add_to_shopping_list(c)
    a.check_item("farine", "g")
    b = _reopen(a, storage)
    assert _lines(b, "farine", "g")[0]["checked"] is True
    assert _lines(b, "oeufs", "pièce")[0]["checked"] is False
