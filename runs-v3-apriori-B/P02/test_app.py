"""Tests rouges — couche code — sonde « recettes ».

Interface publique fixée par ces tests (module unique `app`) :

    app.ValidationError                      exception levée pour toute saisie refusée
    app.DEFAULT_IMAGE                        bytes : l'image par défaut affichée sans photo

    a = app.App(path)                        ouvre (ou crée) les données stockées dans le fichier `path`
    a.close()                                ferme l'application (les données sont dans le fichier)

    a.save_recipe(title, servings=4) -> rid  enregistre une recette, renvoie son identifiant (stable après réouverture)
    a.list_recipes() -> list[str]            titres des recettes
    a.delete_recipe(rid)

    a.add_ingredient(rid, name, quantity, unit)   quantity : nombre ou texte saisi
    a.remove_ingredient(rid, name)

    a.open_recipe(rid) -> dict               fiche aux portions d'origine
    a.adjust_servings(rid, n) -> dict        fiche affichée pour n portions (ne modifie pas la recette)
        fiche = {"title", "servings", "category", "favorite", "note", "photo",
                 "ingredients": [{"name", "quantity", "unit"}, ...]}
        "quantity" est un nombre (arrondi à deux décimales), "note" vaut None sans note,
        "photo" vaut les octets de l'image (ou app.DEFAULT_IMAGE).

    a.set_category(rid, category)
    a.set_favorite(rid, bool)
    a.set_note(rid, text)
    a.set_photo(rid, data: bytes)            refuse (ValidationError) des octets qui ne sont pas une image
    a.remove_photo(rid)

    a.search(query="", category=None, favorites=False) -> {"recipes": [titres], "message": None | "Aucun résultat"}

    a.add_to_shopping(rid, servings=None)
    a.shopping_list() -> [{"name", "quantity", "unit", "checked"}, ...]
    a.check_item(name, unit)
    a.remove_checked()
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import app

ROOT = Path(__file__).resolve().parent.parent

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00" + b"\x90wS\xde"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xd9"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
TEXT = "Ceci n'est pas une image.\n".encode("utf-8")


# ---------------------------------------------------------------- fixtures / aides

@pytest.fixture
def db(tmp_path):
    return tmp_path / "recettes.db"


@pytest.fixture
def a(db):
    return app.App(db)


def titles(results):
    return sorted(results["recipes"])


def ing(card, name):
    found = [i for i in card["ingredients"] if i["name"] == name]
    assert len(found) == 1, f"attendu un ingrédient {name!r} sur la fiche, obtenu {card['ingredients']!r}"
    return found[0]


def lines(a, name=None, unit=None):
    out = a.shopping_list()
    if name is not None:
        out = [l for l in out if l["name"].lower() == name.lower()]
    if unit is not None:
        out = [l for l in out if l["unit"] == unit]
    return out


def run_in_fresh_process(path, code):
    """Relit les données dans un AUTRE processus Python : aucune mémoire partagée possible."""
    script = textwrap.dedent(
        f"""
        import sys, json
        sys.path.insert(0, {str(ROOT)!r})
        import app
        a = app.App({str(path)!r})
        """
    ) + textwrap.dedent(code)
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15, cwd=str(ROOT)
    )
    assert proc.returncode == 0, f"le processus neuf a échoué :\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def recipe_with(a, title="Crêpes", servings=4, items=(("farine", 250, "g"), ("lait", 500, "ml"))):
    rid = a.save_recipe(title, servings=servings)
    for n, q, u in items:
        a.add_ingredient(rid, n, q, u)
    return rid


# ---------------------------------------------------------------- A01 / A02 : enregistrer

def test_A01_titre_vide_ne_cree_pas_la_recette(a):
    with pytest.raises(app.ValidationError):
        a.save_recipe("")
    assert a.list_recipes() == [], f"aucune recette attendue, obtenu {a.list_recipes()!r}"


def test_A01_titre_vide_ne_cree_rien_meme_apres_reouverture(db):
    a = app.App(db)
    with pytest.raises(app.ValidationError):
        a.save_recipe("")
    a.close()
    assert app.App(db).list_recipes() == []


def test_A01_trou_titre_espaces(a):
    with pytest.raises(app.ValidationError):
        a.save_recipe("   \t ")
    assert a.list_recipes() == [], f"un titre fait d'espaces ne doit rien créer, obtenu {a.list_recipes()!r}"


def test_A02_titre_non_vide_apparait_dans_la_liste(a):
    a.save_recipe("Tarte aux pommes")
    assert a.list_recipes() == ["Tarte aux pommes"]


def test_A02_titre_non_ascii_apparait_tel_quel(a):
    a.save_recipe("Bœuf bourguignon à l'ancienne")
    assert a.list_recipes() == ["Bœuf bourguignon à l'ancienne"]


def test_A02_plusieurs_recettes_toutes_listees(a):
    a.save_recipe("Crêpes")
    a.save_recipe("Gaufres")
    assert sorted(a.list_recipes()) == ["Crêpes", "Gaufres"]


# ---------------------------------------------------------------- A03 / A04 : ingrédients

def test_A03_ajout_ingredient_apparait_sur_la_fiche(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "farine", 250, "g")
    card = a.open_recipe(rid)
    assert card["ingredients"] == [{"name": "farine", "quantity": 250, "unit": "g"}]


def test_A03_quantite_saisie_en_texte_est_lue_comme_nombre(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "lait", "500", "ml")
    assert ing(a.open_recipe(rid), "lait")["quantity"] == 500


def test_A03_ajout_ne_touche_pas_une_autre_recette(a):
    r1 = a.save_recipe("Crêpes")
    r2 = a.save_recipe("Gaufres")
    a.add_ingredient(r1, "farine", 250, "g")
    assert a.open_recipe(r2)["ingredients"] == []


def test_A04_suppression_ingredient_disparait(a):
    rid = recipe_with(a)
    a.remove_ingredient(rid, "farine")
    names = [i["name"] for i in a.open_recipe(rid)["ingredients"]]
    assert names == ["lait"], f"attendu ['lait'] après suppression de farine, obtenu {names!r}"


def test_A04_suppression_du_seul_ingredient_vide_la_liste(a):
    rid = recipe_with(a, items=(("sel", 1, "pincée"),))
    a.remove_ingredient(rid, "sel")
    assert a.open_recipe(rid)["ingredients"] == []


# ---------------------------------------------------------------- A05 / A06 : quantité

@pytest.mark.parametrize("bad", ["abc", "", "deux", "12abc", "  "])
def test_A05_quantite_non_numerique_refusee(a, bad):
    rid = a.save_recipe("Crêpes")
    with pytest.raises(app.ValidationError):
        a.add_ingredient(rid, "farine", bad, "g")
    assert a.open_recipe(rid)["ingredients"] == [], f"quantité {bad!r} : l'ingrédient ne doit pas être ajouté"


def test_A05_trou_nan_infini(a):
    rid = a.save_recipe("Crêpes")
    for bad in ("nan", "inf", "-inf", float("nan"), float("inf")):
        with pytest.raises(app.ValidationError):
            a.add_ingredient(rid, "farine", bad, "g")
    assert a.open_recipe(rid)["ingredients"] == []


def test_A05_trou_virgule_decimale(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "beurre", "1,5", "cuillère")
    assert ing(a.open_recipe(rid), "beurre")["quantity"] == 1.5


@pytest.mark.parametrize("bad", [0, "0", -1, "-1", -2.5, "-0.01", 0.0])
def test_A06_quantite_negative_ou_nulle_refusee(a, bad):
    rid = a.save_recipe("Crêpes")
    with pytest.raises(app.ValidationError):
        a.add_ingredient(rid, "farine", bad, "g")
    assert a.open_recipe(rid)["ingredients"] == [], f"quantité {bad!r} : l'ingrédient ne doit pas être ajouté"


def test_A06_petite_quantite_positive_acceptee(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "sel", "0.5", "g")
    assert ing(a.open_recipe(rid), "sel")["quantity"] == 0.5


# ---------------------------------------------------------------- A07 – A12 : portions

def test_A07_de_4_a_8_double_chaque_quantite(a):
    rid = recipe_with(a, items=(("farine", 250, "g"), ("lait", 500, "ml"), ("oeufs", 3, "pièce")))
    card = a.adjust_servings(rid, 8)
    got = {i["name"]: i["quantity"] for i in card["ingredients"]}
    assert got == {"farine": 500, "lait": 1000, "oeufs": 6}, f"quantités doublées attendues, obtenu {got!r}"
    assert card["servings"] == 8


def test_A08_de_4_a_2_divise_par_deux(a):
    rid = recipe_with(a, items=(("farine", 250, "g"), ("oeufs", 3, "pièce")))
    card = a.adjust_servings(rid, 2)
    got = {i["name"]: i["quantity"] for i in card["ingredients"]}
    assert got == {"farine": 125, "oeufs": 1.5}, f"quantités divisées par deux attendues, obtenu {got!r}"


def test_A08_ajustements_successifs_partent_de_l_origine(a):
    rid = recipe_with(a, items=(("farine", 250, "g"),))
    a.adjust_servings(rid, 8)
    card = a.adjust_servings(rid, 2)
    assert ing(card, "farine")["quantity"] == 125, (
        f"4→8 puis →2 : attendu 125 (moitié de l'origine), obtenu {ing(card, 'farine')['quantity']!r}"
    )


def test_A09_quantite_non_entiere_arrondie_a_deux_decimales(a):
    rid = recipe_with(a, servings=3, items=(("farine", 100, "g"), ("sucre", 1, "g")))
    card = a.adjust_servings(rid, 4)
    assert ing(card, "farine")["quantity"] == 133.33, f"attendu 133.33, obtenu {ing(card, 'farine')['quantity']!r}"
    assert ing(card, "sucre")["quantity"] == 1.33, f"attendu 1.33, obtenu {ing(card, 'sucre')['quantity']!r}"


def test_A09_arrondi_au_plus_proche_pas_tronque(a):
    rid = recipe_with(a, servings=3, items=(("lait", 1, "l"),))
    card = a.adjust_servings(rid, 2)
    assert ing(card, "lait")["quantity"] == 0.67, f"2/3 attendu arrondi à 0.67, obtenu {ing(card, 'lait')['quantity']!r}"


def test_A10_unite_inchangee_apres_ajustement(a):
    rid = recipe_with(a, items=(("farine", 600, "g"), ("lait", 750, "ml")))
    card = a.adjust_servings(rid, 8)
    assert ing(card, "farine") == {"name": "farine", "quantity": 1200, "unit": "g"}, ing(card, "farine")
    assert ing(card, "lait") == {"name": "lait", "quantity": 1500, "unit": "ml"}, ing(card, "lait")


def test_A10_unite_inchangee_en_reduisant(a):
    rid = recipe_with(a, items=(("beurre", 1, "kg"),))
    card = a.adjust_servings(rid, 1)
    assert ing(card, "beurre") == {"name": "beurre", "quantity": 0.25, "unit": "kg"}, ing(card, "beurre")


@pytest.mark.parametrize("bad", [0, -1, 0.5])
def test_A11_ajustement_inferieur_a_1_refuse(a, bad):
    rid = recipe_with(a)
    with pytest.raises(app.ValidationError):
        a.adjust_servings(rid, bad)
    assert a.open_recipe(rid)["servings"] == 4


def test_A11_une_portion_acceptee(a):
    rid = recipe_with(a, items=(("farine", 200, "g"),))
    card = a.adjust_servings(rid, 1)
    assert card["servings"] == 1 and ing(card, "farine")["quantity"] == 50


@pytest.mark.parametrize("bad", [0, -4])
def test_A11_enregistrement_avec_portions_inferieures_a_1_refuse(a, bad):
    with pytest.raises(app.ValidationError):
        a.save_recipe("Crêpes", servings=bad)
    assert a.list_recipes() == []


def test_A12_reouverture_de_la_fiche_affiche_les_portions_d_origine(a):
    rid = recipe_with(a, items=(("farine", 250, "g"),))
    a.adjust_servings(rid, 8)
    card = a.open_recipe(rid)
    assert card["servings"] == 4, f"portions d'origine 4 attendues, obtenu {card['servings']!r}"
    assert ing(card, "farine")["quantity"] == 250


def test_A12_reouverture_de_l_application_apres_ajustement(db):
    a = app.App(db)
    rid = recipe_with(a, items=(("farine", 250, "g"),))
    a.adjust_servings(rid, 8)
    a.close()
    card = app.App(db).open_recipe(rid)
    assert card["servings"] == 4 and ing(card, "farine")["quantity"] == 250, card


# ---------------------------------------------------------------- A13 / A14 : catégorie

def test_A13_categorie_affichee_sur_la_fiche(a):
    rid = a.save_recipe("Tarte aux pommes")
    a.set_category(rid, "Dessert")
    assert a.open_recipe(rid)["category"] == "Dessert"


def test_A13_recette_sans_categorie(a):
    rid = a.save_recipe("Tarte aux pommes")
    assert a.open_recipe(rid)["category"] is None


def test_A14_filtre_categorie_ne_montre_que_cette_categorie(a):
    r1 = a.save_recipe("Tarte aux pommes")
    r2 = a.save_recipe("Soupe à l'oignon")
    a.save_recipe("Pain")
    r4 = a.save_recipe("Mousse au chocolat")
    a.set_category(r1, "Dessert")
    a.set_category(r2, "Entrée")
    a.set_category(r4, "Dessert")
    assert titles(a.search(category="Dessert")) == ["Mousse au chocolat", "Tarte aux pommes"]


def test_A14_trou_requete_et_categorie(a):
    r1 = a.save_recipe("Tarte aux pommes")
    r2 = a.save_recipe("Tarte à l'oignon")
    a.set_category(r1, "Dessert")
    a.set_category(r2, "Plat")
    assert titles(a.search(query="tarte", category="Dessert")) == ["Tarte aux pommes"]


# ---------------------------------------------------------------- A15 – A19 : recherche

def test_A15_mot_du_titre_fait_apparaitre_la_recette(a):
    a.save_recipe("Tarte aux pommes")
    a.save_recipe("Soupe à l'oignon")
    assert titles(a.search("pommes")) == ["Tarte aux pommes"]


def test_A15_trou_requete_plusieurs_mots(a):
    a.save_recipe("Tarte aux pommes")
    a.save_recipe("Mousse au chocolat")
    a.save_recipe("Soupe à l'oignon")
    assert titles(a.search("tarte chocolat")) == ["Mousse au chocolat", "Tarte aux pommes"]


def test_A16_nom_d_ingredient_fait_apparaitre_les_recettes(a):
    recipe_with(a, "Crêpes", items=(("farine", 250, "g"), ("lait", 500, "ml")))
    recipe_with(a, "Gaufres", items=(("farine", 300, "g"),))
    recipe_with(a, "Omelette", items=(("oeufs", 3, "pièce"),))
    assert titles(a.search("farine")) == ["Crêpes", "Gaufres"]


def test_A16_ingredient_supprime_ne_fait_plus_apparaitre(a):
    rid = recipe_with(a, "Crêpes", items=(("farine", 250, "g"), ("lait", 500, "ml")))
    a.remove_ingredient(rid, "lait")
    assert a.search("lait") == {"recipes": [], "message": "Aucun résultat"}


def test_A17_majuscules_et_minuscules_meme_resultat(a):
    a.save_recipe("Tarte aux pommes")
    recipe_with(a, "Crêpes", items=(("farine", 250, "g"),))
    a.save_recipe("Soupe")
    assert titles(a.search("POMMES")) == titles(a.search("pommes")) == ["Tarte aux pommes"]
    assert titles(a.search("FARINE")) == titles(a.search("farine")) == ["Crêpes"]


def test_A17_majuscules_accentuees(a):
    recipe_with(a, "Gratin", items=(("crème", 20, "cl"),))
    a.save_recipe("Crème brûlée")
    assert titles(a.search("CRÈME")) == titles(a.search("crème")) == ["Crème brûlée", "Gratin"]


def test_A18_requete_vide_affiche_toutes_les_recettes(a):
    for t in ("Crêpes", "Gaufres", "Pain"):
        a.save_recipe(t)
    res = a.search("")
    assert titles(res) == ["Crêpes", "Gaufres", "Pain"]
    assert res["message"] is None


def test_A18_trou_requete_espaces(a):
    for t in ("Crêpes", "Gaufres"):
        a.save_recipe(t)
    assert titles(a.search("   ")) == ["Crêpes", "Gaufres"]


def test_A19_sans_correspondance_message_aucun_resultat(a):
    a.save_recipe("Crêpes")
    assert a.search("couscous") == {"recipes": [], "message": "Aucun résultat"}


def test_A19_avec_correspondance_pas_de_message(a):
    a.save_recipe("Crêpes")
    assert a.search("crêpes")["message"] is None


def test_A19_filtre_categorie_sans_correspondance(a):
    a.save_recipe("Crêpes")
    assert a.search(category="Dessert") == {"recipes": [], "message": "Aucun résultat"}


# ---------------------------------------------------------------- A20 – A22 : favoris

def test_A20_marquer_favori_active_l_icone(a):
    rid = a.save_recipe("Crêpes")
    assert a.open_recipe(rid)["favorite"] is False
    a.set_favorite(rid, True)
    assert a.open_recipe(rid)["favorite"] is True


def test_A21_retirer_favori_desactive_l_icone(a):
    rid = a.save_recipe("Crêpes")
    a.set_favorite(rid, True)
    a.set_favorite(rid, False)
    assert a.open_recipe(rid)["favorite"] is False


def test_A22_filtre_favoris(a):
    r1 = a.save_recipe("Crêpes")
    a.save_recipe("Gaufres")
    r3 = a.save_recipe("Pain")
    r4 = a.save_recipe("Soupe")
    a.set_favorite(r1, True)
    a.set_favorite(r3, True)
    a.set_favorite(r4, True)
    a.set_favorite(r4, False)
    assert titles(a.search(favorites=True)) == ["Crêpes", "Pain"]


# ---------------------------------------------------------------- A23 / A24 : note

def test_A23_note_affichee_sur_la_fiche(a):
    rid = a.save_recipe("Crêpes")
    a.set_note(rid, "Laisser reposer la pâte 1 h — très important !")
    assert a.open_recipe(rid)["note"] == "Laisser reposer la pâte 1 h — très important !"


def test_A23_sans_note(a):
    rid = a.save_recipe("Crêpes")
    assert a.open_recipe(rid)["note"] is None


def test_A24_effacer_le_texte_retire_la_note(a):
    rid = a.save_recipe("Crêpes")
    a.set_note(rid, "Reposer 1 h")
    a.set_note(rid, "")
    assert a.open_recipe(rid)["note"] is None, f"note retirée attendue, obtenu {a.open_recipe(rid)['note']!r}"


def test_A24_trou_note_espaces(a):
    rid = a.save_recipe("Crêpes")
    a.set_note(rid, "Reposer 1 h")
    a.set_note(rid, "  \n ")
    assert a.open_recipe(rid)["note"] is None


# ---------------------------------------------------------------- A25 – A28 : photo

def test_A25_image_png_affichee(a):
    rid = a.save_recipe("Crêpes")
    a.set_photo(rid, PNG)
    assert a.open_recipe(rid)["photo"] == PNG


def test_A25_image_jpeg_affichee(a):
    rid = a.save_recipe("Crêpes")
    a.set_photo(rid, JPEG)
    assert a.open_recipe(rid)["photo"] == JPEG


@pytest.mark.parametrize("bad", [PDF, TEXT, b""])
def test_A26_fichier_non_image_refuse(a, bad):
    rid = a.save_recipe("Crêpes")
    with pytest.raises(app.ValidationError):
        a.set_photo(rid, bad)
    assert a.open_recipe(rid)["photo"] == app.DEFAULT_IMAGE


def test_A26_refus_conserve_la_photo_precedente(a):
    rid = a.save_recipe("Crêpes")
    a.set_photo(rid, PNG)
    with pytest.raises(app.ValidationError):
        a.set_photo(rid, PDF)
    assert a.open_recipe(rid)["photo"] == PNG


def test_A27_sans_photo_image_par_defaut(a):
    assert isinstance(app.DEFAULT_IMAGE, bytes) and len(app.DEFAULT_IMAGE) > 0
    assert app.DEFAULT_IMAGE not in (PNG, JPEG)
    rid = a.save_recipe("Crêpes")
    assert a.open_recipe(rid)["photo"] == app.DEFAULT_IMAGE


def test_A28_suppression_photo_affiche_l_image_par_defaut(a):
    rid = a.save_recipe("Crêpes")
    a.set_photo(rid, PNG)
    a.remove_photo(rid)
    assert a.open_recipe(rid)["photo"] == app.DEFAULT_IMAGE


# ---------------------------------------------------------------- A29 – A34 : courses

def test_A29_chaque_ingredient_dans_la_liste_de_courses(a):
    rid = recipe_with(a, items=(("farine", 250, "g"), ("lait", 500, "ml"), ("oeufs", 3, "pièce")))
    a.add_to_shopping(rid)
    got = sorted((l["name"], l["quantity"], l["unit"]) for l in a.shopping_list())
    assert got == [("farine", 250, "g"), ("lait", 500, "ml"), ("oeufs", 3, "pièce")], got


def test_A29_articles_ajoutes_non_coches(a):
    rid = recipe_with(a)
    a.add_to_shopping(rid)
    assert all(l["checked"] is False for l in a.shopping_list()), a.shopping_list()


def test_A30_portions_ajustees_reportees(a):
    rid = recipe_with(a, items=(("farine", 250, "g"), ("oeufs", 3, "pièce")))
    a.add_to_shopping(rid, servings=8)
    got = sorted((l["name"], l["quantity"], l["unit"]) for l in a.shopping_list())
    assert got == [("farine", 500, "g"), ("oeufs", 6, "pièce")], got


def test_A30_portions_ajustees_non_entieres(a):
    rid = recipe_with(a, servings=3, items=(("farine", 100, "g"),))
    a.add_to_shopping(rid, servings=4)
    assert lines(a, "farine")[0]["quantity"] == 133.33, a.shopping_list()


def test_A30_portions_inferieures_a_1_refusees(a):
    rid = recipe_with(a)
    with pytest.raises(app.ValidationError):
        a.add_to_shopping(rid, servings=0)
    assert a.shopping_list() == []


def test_A31_meme_ingredient_meme_unite_une_ligne_sommee(a):
    r1 = recipe_with(a, "Crêpes", items=(("farine", 250, "g"),))
    r2 = recipe_with(a, "Gaufres", items=(("farine", 300, "g"),))
    a.add_to_shopping(r1)
    a.add_to_shopping(r2)
    got = lines(a, "farine")
    assert len(got) == 1 and got[0]["quantity"] == 550 and got[0]["unit"] == "g", got


def test_A31_somme_avec_portions_ajustees(a):
    r1 = recipe_with(a, "Crêpes", items=(("farine", 250, "g"),))
    r2 = recipe_with(a, "Gaufres", items=(("farine", 300, "g"),))
    a.add_to_shopping(r1, servings=8)
    a.add_to_shopping(r2, servings=2)
    got = lines(a, "farine")
    assert len(got) == 1 and got[0]["quantity"] == 650, got


def test_A31_trou_casse_nom(a):
    r1 = recipe_with(a, "Crêpes", items=(("Farine", 250, "g"),))
    r2 = recipe_with(a, "Gaufres", items=(("farine", 300, "g"),))
    a.add_to_shopping(r1)
    a.add_to_shopping(r2)
    got = lines(a, "farine")
    assert len(got) == 1 and got[0]["quantity"] == 550, got


def test_A32_meme_ingredient_unites_differentes_deux_lignes(a):
    r1 = recipe_with(a, "Crêpes", items=(("farine", 250, "g"),))
    r2 = recipe_with(a, "Pain", items=(("farine", 1, "kg"),))
    a.add_to_shopping(r1)
    a.add_to_shopping(r2)
    got = sorted((l["quantity"], l["unit"]) for l in lines(a, "farine"))
    assert got == [(1, "kg"), (250, "g")], got


def test_A33_cocher_un_article(a):
    rid = recipe_with(a)
    a.add_to_shopping(rid)
    a.check_item("farine", "g")
    state = {l["name"]: l["checked"] for l in a.shopping_list()}
    assert state == {"farine": True, "lait": False}, state


def test_A34_retirer_les_articles_coches(a):
    rid = recipe_with(a, items=(("farine", 250, "g"), ("lait", 500, "ml"), ("sucre", 50, "g")))
    a.add_to_shopping(rid)
    a.check_item("farine", "g")
    a.check_item("sucre", "g")
    a.remove_checked()
    got = [(l["name"], l["quantity"], l["unit"], l["checked"]) for l in a.shopping_list()]
    assert got == [("lait", 500, "ml", False)], got


def test_A34_ne_retire_que_la_bonne_unite(a):
    r1 = recipe_with(a, "Crêpes", items=(("farine", 250, "g"),))
    r2 = recipe_with(a, "Pain", items=(("farine", 1, "kg"),))
    a.add_to_shopping(r1)
    a.add_to_shopping(r2)
    a.check_item("farine", "kg")
    a.remove_checked()
    got = [(l["quantity"], l["unit"]) for l in a.shopping_list()]
    assert got == [(250, "g")], got


# ---------------------------------------------------------------- A35 / A36 : suppression

def test_A35_suppression_disparait_de_la_liste(a):
    rid = a.save_recipe("Crêpes")
    a.save_recipe("Gaufres")
    a.delete_recipe(rid)
    assert a.list_recipes() == ["Gaufres"]


def test_A35_trou_absente_des_resultats(a):
    rid = recipe_with(a, "Crêpes", items=(("farine", 250, "g"),))
    a.delete_recipe(rid)
    assert a.search("") == {"recipes": [], "message": "Aucun résultat"}
    assert a.search("farine")["recipes"] == []


def test_A35_suppression_persiste_apres_reouverture(db):
    a = app.App(db)
    rid = a.save_recipe("Crêpes")
    a.save_recipe("Gaufres")
    a.delete_recipe(rid)
    a.close()
    assert app.App(db).list_recipes() == ["Gaufres"]


def test_A36_suppression_conserve_les_articles_de_courses(a):
    rid = recipe_with(a)
    a.add_to_shopping(rid)
    a.delete_recipe(rid)
    got = sorted((l["name"], l["quantity"], l["unit"]) for l in a.shopping_list())
    assert got == [("farine", 250, "g"), ("lait", 500, "ml")], got


# ---------------------------------------------------------------- A37 – A39 : persistance réelle

def test_A37_recette_presente_apres_reouverture(db):
    a = app.App(db)
    a.save_recipe("Crêpes")
    a.close()
    assert app.App(db).list_recipes() == ["Crêpes"]


def test_A37_les_donnees_sont_dans_le_fichier_donne(db):
    a = app.App(db)
    a.save_recipe("Crêpes")
    a.close()
    assert db.exists() and db.stat().st_size > 0, f"aucune donnée écrite dans {db}"


def test_A37_fichier_copie_ailleurs_relu(db, tmp_path):
    a = app.App(db)
    a.save_recipe("Crêpes")
    a.close()
    other = tmp_path / "ailleurs" / "copie.db"
    other.parent.mkdir()
    shutil.copy(db, other)
    os.remove(db)
    assert app.App(other).list_recipes() == ["Crêpes"], "les données doivent venir du fichier, pas de la mémoire"


def test_A37_fichier_supprime_rien_en_memoire(db):
    a = app.App(db)
    a.save_recipe("Crêpes")
    a.close()
    os.remove(db)
    assert app.App(db).list_recipes() == [], "fichier supprimé : une nouvelle instance ne doit rien retrouver"


def test_A37_autre_chemin_independant(db, tmp_path):
    a = app.App(db)
    a.save_recipe("Crêpes")
    a.close()
    assert app.App(tmp_path / "autre.db").list_recipes() == []


def test_A37_relu_par_un_autre_processus(db):
    a = app.App(db)
    rid = recipe_with(a, items=(("farine", 250, "g"),))
    a.close()
    out = run_in_fresh_process(
        db,
        f"""
        card = a.open_recipe({rid!r})
        print(json.dumps({{"titles": a.list_recipes(), "ing": card["ingredients"]}}))
        """,
    )
    assert out["titles"] == ["Crêpes"], out
    assert out["ing"] == [{"name": "farine", "quantity": 250, "unit": "g"}], out


def test_A37_ecrit_par_un_autre_processus(db):
    run_in_fresh_process(
        db,
        """
        a.save_recipe("Gaufres")
        a.close()
        print(json.dumps(True))
        """,
    )
    assert app.App(db).list_recipes() == ["Gaufres"]


def test_A38_favori_apres_reouverture(db):
    a = app.App(db)
    r1 = a.save_recipe("Crêpes")
    r2 = a.save_recipe("Gaufres")
    a.set_favorite(r1, True)
    a.close()
    b = app.App(db)
    assert b.open_recipe(r1)["favorite"] is True
    assert b.open_recipe(r2)["favorite"] is False
    assert titles(b.search(favorites=True)) == ["Crêpes"]


def test_A38_favori_retire_reste_retire_apres_reouverture(db):
    a = app.App(db)
    rid = a.save_recipe("Crêpes")
    a.set_favorite(rid, True)
    a.set_favorite(rid, False)
    a.close()
    assert app.App(db).open_recipe(rid)["favorite"] is False


def test_A38_favori_relu_par_un_autre_processus(db, tmp_path):
    a = app.App(db)
    rid = a.save_recipe("Crêpes")
    a.set_favorite(rid, True)
    a.close()
    other = tmp_path / "copie.db"
    shutil.copy(db, other)
    out = run_in_fresh_process(other, f"print(json.dumps(a.open_recipe({rid!r})['favorite']))")
    assert out is True


def test_A39_article_coche_apres_reouverture(db):
    a = app.App(db)
    rid = recipe_with(a)
    a.add_to_shopping(rid)
    a.check_item("farine", "g")
    a.close()
    state = {l["name"]: l["checked"] for l in app.App(db).shopping_list()}
    assert state == {"farine": True, "lait": False}, state


def test_A39_article_coche_relu_par_un_autre_processus(db):
    a = app.App(db)
    rid = recipe_with(a)
    a.add_to_shopping(rid)
    a.check_item("lait", "ml")
    a.close()
    out = run_in_fresh_process(
        db, "print(json.dumps({l['name']: l['checked'] for l in a.shopping_list()}))"
    )
    assert out == {"farine": False, "lait": True}, out


def test_A39_retirer_coches_persiste(db):
    a = app.App(db)
    rid = recipe_with(a)
    a.add_to_shopping(rid)
    a.check_item("farine", "g")
    a.remove_checked()
    a.close()
    got = [(l["name"], l["checked"]) for l in app.App(db).shopping_list()]
    assert got == [("lait", False)], got
