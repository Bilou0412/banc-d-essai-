"""Tests rouges -- sonde P02 (carnet de recettes).

Interface publique fixee par ces tests (module `app`) :

    app.InvalidInput                     exception (sous-classe de ValueError) levee pour toute saisie refusee
    app.DEFAULT_PHOTO                    bytes : l'image par defaut affichee sur une fiche sans photo

    a = app.App(path)                    path : str ou os.PathLike ; fichier de donnees (cree au besoin)
    a.close()                            ferme l'application (les donnees doivent etre sur disque)

    rid = a.save_recipe(title, servings=4)   -> identifiant opaque, stable apres reouverture
    a.delete_recipe(rid)
    a.list_recipes()                     -> list[dict] : {"id": rid, "title": str}
    a.recipe(rid, servings=None)         -> dict (la fiche) :
        {"title": str, "servings": int, "category": str|None, "favorite": bool,
         "note": str|None, "photo": bytes,
         "ingredients": [{"name": str, "quantity": str, "unit": str}, ...]}
       `servings` donne : fiche affichee avec portions ajustees (rien n'est enregistre).
       "quantity" est la quantite AFFICHEE, chaine, separateur decimal ".".

    a.add_ingredient(rid, name, quantity, unit)   quantity : str ou nombre
    a.remove_ingredient(rid, name)
    a.set_category(rid, category)
    a.set_favorite(rid, bool)
    a.set_note(rid, text)
    a.set_photo(rid, data: bytes)
    a.remove_photo(rid)

    a.search(query="", category=None, favorites_only=False)
        -> dict {"results": list[str] (titres), "message": str|None}

    a.add_to_shopping_list(rid, servings=None)
    a.shopping_list()                    -> list[dict] {"name", "quantity" (str), "unit", "checked": bool}
    a.check_item(name, unit, checked=True)
    a.remove_checked()
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

import app


# ----------------------------------------------------------------- utilitaires

def _png():
    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


PNG = _png()
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00"
       b"\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")


@pytest.fixture
def db(tmp_path):
    return tmp_path / "recettes.db"


@pytest.fixture
def a(db):
    inst = app.App(db)
    yield inst
    try:
        inst.close()
    except Exception:
        pass


def titles(inst):
    return sorted(r["title"] for r in inst.list_recipes())


def ing(inst, rid, servings=None):
    fiche = inst.recipe(rid) if servings is None else inst.recipe(rid, servings=servings)
    return {i["name"]: i for i in fiche["ingredients"]}


def qty(s):
    return float(s)


def shop(inst):
    return {(i["name"], i["unit"]): i for i in inst.shopping_list()}


def find_id(inst, title):
    ids = [r["id"] for r in inst.list_recipes() if r["title"] == title]
    assert len(ids) == 1, f"attendu une recette '{title}', obtenu {inst.list_recipes()!r}"
    return ids[0]


def run_fresh_process(path, code):
    """Execute `code` dans un AUTRE processus Python : aucune memoire partagee possible."""
    app_dir = os.path.dirname(os.path.abspath(app.__file__))
    env = dict(os.environ)
    env["PYTHONPATH"] = app_dir + os.pathsep + env.get("PYTHONPATH", "")
    script = "import app, json, sys\na = app.App(sys.argv[1])\n" + code
    out = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True,
                         text=True, env=env, timeout=15)
    assert out.returncode == 0, f"processus neuf en echec : {out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


# ----------------------------------------------------------------- A01 / A02

def test_A01_titre_vide_refuse_et_rien_cree(a):
    with pytest.raises(app.InvalidInput):
        a.save_recipe("")
    assert a.list_recipes() == [], f"attendu aucune recette, obtenu {a.list_recipes()!r}"


def test_A01_trou_titre_blanc_refuse(a):
    with pytest.raises(app.InvalidInput):
        a.save_recipe("   \t ")
    assert a.list_recipes() == [], f"titre blanc : attendu aucune recette, obtenu {a.list_recipes()!r}"


def test_A02_titre_non_vide_apparait_dans_la_liste(a):
    a.save_recipe("Tarte aux pommes")
    assert titles(a) == ["Tarte aux pommes"], f"obtenu {titles(a)!r}"


def test_A02_deux_recettes_apparaissent(a):
    a.save_recipe("Crêpes")
    a.save_recipe("Gâteau")
    assert titles(a) == ["Crêpes", "Gâteau"], f"obtenu {titles(a)!r}"


# ----------------------------------------------------------------- A03 / A04

def test_A03_ingredient_ajoute_apparait(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "farine", "250", "g")
    got = ing(a, rid)
    assert set(got) == {"farine"}, f"obtenu {got!r}"
    assert qty(got["farine"]["quantity"]) == 250 and got["farine"]["unit"] == "g", got


def test_A03_ingredient_d_une_recette_n_apparait_pas_dans_une_autre(a):
    r1 = a.save_recipe("Crêpes")
    r2 = a.save_recipe("Omelette")
    a.add_ingredient(r1, "farine", 250, "g")
    assert ing(a, r2) == {}, f"Omelette : attendu aucun ingredient, obtenu {ing(a, r2)!r}"


def test_A04_ingredient_supprime_disparait(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "farine", 250, "g")
    a.add_ingredient(rid, "lait", 500, "ml")
    a.remove_ingredient(rid, "farine")
    assert set(ing(a, rid)) == {"lait"}, f"obtenu {ing(a, rid)!r}"


# ----------------------------------------------------------------- A05 / A06

@pytest.mark.parametrize("bad", ["abc", "", "12abc", "deux", " "])
def test_A05_quantite_non_numerique_refusee(a, bad):
    rid = a.save_recipe("Crêpes")
    with pytest.raises(app.InvalidInput):
        a.add_ingredient(rid, "farine", bad, "g")
    assert ing(a, rid) == {}, f"quantite {bad!r} : ingredient ajoute malgre le refus : {ing(a, rid)!r}"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "NaN"])
def test_A05_trou_nan_inf_refuses(a, bad):
    rid = a.save_recipe("Crêpes")
    with pytest.raises(app.InvalidInput):
        a.add_ingredient(rid, "farine", bad, "g")
    assert ing(a, rid) == {}, f"quantite {bad!r} acceptee : {ing(a, rid)!r}"


def test_A05_trou_virgule_decimale_acceptee(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "beurre", "1,5", "c. à s.")
    assert qty(ing(a, rid)["beurre"]["quantity"]) == 1.5, f"obtenu {ing(a, rid)!r}"


@pytest.mark.parametrize("bad", [0, -1, "0", "-2", -0.5, "0.0"])
def test_A06_quantite_negative_ou_nulle_refusee(a, bad):
    rid = a.save_recipe("Crêpes")
    with pytest.raises(app.InvalidInput):
        a.add_ingredient(rid, "farine", bad, "g")
    assert ing(a, rid) == {}, f"quantite {bad!r} : ingredient ajoute malgre le refus : {ing(a, rid)!r}"


def test_A06_petite_quantite_positive_acceptee(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "sel", "0.5", "g")
    assert qty(ing(a, rid)["sel"]["quantity"]) == 0.5, f"obtenu {ing(a, rid)!r}"


# ----------------------------------------------------------------- A07 .. A12

def _crepes(a):
    rid = a.save_recipe("Crêpes", servings=4)
    a.add_ingredient(rid, "farine", 250, "g")
    a.add_ingredient(rid, "lait", 500, "ml")
    a.add_ingredient(rid, "oeufs", 3, "pièce")
    return rid


def test_A07_4_vers_8_double_chaque_quantite(a):
    rid = _crepes(a)
    got = ing(a, rid, servings=8)
    assert {k: qty(v["quantity"]) for k, v in got.items()} == {"farine": 500, "lait": 1000, "oeufs": 6}, got
    assert a.recipe(rid, servings=8)["servings"] == 8


def test_A08_4_vers_2_divise_par_deux(a):
    rid = _crepes(a)
    got = ing(a, rid, servings=2)
    assert {k: qty(v["quantity"]) for k, v in got.items()} == {"farine": 125, "lait": 250, "oeufs": 1.5}, got


def test_A09_quantite_non_entiere_arrondie_deux_decimales(a):
    rid = a.save_recipe("Sauce", servings=3)
    a.add_ingredient(rid, "beurre", 1, "c. à s.")
    got = ing(a, rid, servings=4)["beurre"]["quantity"]
    assert got == "1.33", f"1*4/3 : attendu '1.33', obtenu {got!r}"


def test_A09_arrondi_et_non_troncature(a):
    rid = a.save_recipe("Sauce", servings=3)
    a.add_ingredient(rid, "beurre", 2, "c. à s.")
    got = ing(a, rid, servings=1)["beurre"]["quantity"]
    assert got == "0.67", f"2/3 : attendu '0.67' (arrondi), obtenu {got!r}"


def test_A10_unite_inchangee_apres_ajustement(a):
    rid = _crepes(a)
    for s in (2, 8, 1):
        got = ing(a, rid, servings=s)
        assert {k: v["unit"] for k, v in got.items()} == {"farine": "g", "lait": "ml", "oeufs": "pièce"}, \
            f"portions {s} : unites modifiees {got!r}"


@pytest.mark.parametrize("bad", [0, -1, 0.5])
def test_A11_portions_inferieures_a_1_refusees_a_l_ajustement(a, bad):
    rid = _crepes(a)
    with pytest.raises(app.InvalidInput):
        a.recipe(rid, servings=bad)
    assert a.recipe(rid)["servings"] == 4


@pytest.mark.parametrize("bad", [0, -3])
def test_A11_portions_inferieures_a_1_refusees_a_l_enregistrement(a, bad):
    with pytest.raises(app.InvalidInput):
        a.save_recipe("Crêpes", servings=bad)
    assert a.list_recipes() == [], f"obtenu {a.list_recipes()!r}"


def test_A11_une_portion_acceptee(a):
    rid = _crepes(a)
    assert qty(ing(a, rid, servings=1)["farine"]["quantity"]) == 62.5


def test_A12_reouverture_apres_ajustement_portions_d_origine(a):
    rid = _crepes(a)
    a.recipe(rid, servings=8)
    fiche = a.recipe(rid)
    assert fiche["servings"] == 4, f"attendu 4 portions, obtenu {fiche['servings']!r}"
    assert qty(ing(a, rid)["farine"]["quantity"]) == 250


def test_A12_ajustements_successifs_ne_se_cumulent_pas(a):
    rid = _crepes(a)
    a.recipe(rid, servings=8)
    got = qty(ing(a, rid, servings=8)["farine"]["quantity"])
    assert got == 500, f"deuxieme ajustement a 8 : attendu 500, obtenu {got} (cumul ?)"


def test_A12_portions_d_origine_apres_reouverture_de_l_application(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.recipe(rid, servings=8)
    a1.add_to_shopping_list(rid, servings=8)
    a1.close()
    a2 = app.App(db)
    assert a2.recipe(rid)["servings"] == 4
    assert qty(ing(a2, rid)["farine"]["quantity"]) == 250
    a2.close()


# ----------------------------------------------------------------- A13 / A14

def test_A13_categorie_affichee_sur_la_fiche(a):
    rid = a.save_recipe("Tarte")
    assert a.recipe(rid)["category"] is None
    a.set_category(rid, "Dessert")
    assert a.recipe(rid)["category"] == "Dessert", f"obtenu {a.recipe(rid)['category']!r}"


def test_A14_filtre_categorie_ne_montre_que_cette_categorie(a):
    r1 = a.save_recipe("Tarte")
    r2 = a.save_recipe("Soupe")
    a.save_recipe("Pain")
    a.set_category(r1, "Dessert")
    a.set_category(r2, "Entrée")
    got = a.search("", category="Dessert")["results"]
    assert got == ["Tarte"], f"filtre Dessert : attendu ['Tarte'], obtenu {got!r}"


def test_A14_changement_de_categorie_suivi_par_le_filtre(a):
    r1 = a.save_recipe("Tarte")
    a.set_category(r1, "Dessert")
    a.set_category(r1, "Goûter")
    assert a.search("", category="Dessert")["results"] == []
    assert a.search("", category="Goûter")["results"] == ["Tarte"]


# ----------------------------------------------------------------- A15 .. A19

def _corpus(a):
    r1 = a.save_recipe("Tarte aux pommes")
    a.add_ingredient(r1, "farine", 200, "g")
    a.add_ingredient(r1, "pommes", 4, "pièce")
    r2 = a.save_recipe("Crème brûlée")
    a.add_ingredient(r2, "crème", 50, "cl")
    a.add_ingredient(r2, "sucre glace", 20, "g")
    r3 = a.save_recipe("Omelette")
    a.add_ingredient(r3, "oeufs", 3, "pièce")
    return r1, r2, r3


def test_A15_mot_du_titre_trouve_la_recette(a):
    _corpus(a)
    assert a.search("Omelette")["results"] == ["Omelette"]
    assert "Tarte aux pommes" in a.search("tarte")["results"]


def test_A15_requete_contenant_un_mot_du_titre_parmi_d_autres(a):
    _corpus(a)
    got = a.search("tarte fine")["results"]
    assert "Tarte aux pommes" in got, f"la requete contient 'tarte' : obtenu {got!r}"


def test_A16_nom_d_ingredient_trouve_les_recettes(a):
    _corpus(a)
    assert a.search("farine")["results"] == ["Tarte aux pommes"]
    assert a.search("sucre glace")["results"] == ["Crème brûlée"]


def test_A16_ingredient_supprime_ne_trouve_plus(a):
    r1, _, _ = _corpus(a)
    a.remove_ingredient(r1, "farine")
    got = a.search("farine")
    assert got["results"] == [], f"obtenu {got!r}"


def test_A17_majuscules_meme_resultat_que_minuscules(a):
    _corpus(a)
    for q in ("omelette", "farine", "crème", "brûlée"):
        lo = sorted(a.search(q)["results"])
        up = sorted(a.search(q.upper())["results"])
        assert lo and lo == up, f"{q!r} -> {lo!r} mais {q.upper()!r} -> {up!r}"


def test_A18_requete_vide_affiche_toutes_les_recettes(a):
    _corpus(a)
    got = a.search("")
    assert sorted(got["results"]) == ["Crème brûlée", "Omelette", "Tarte aux pommes"], got
    assert got["message"] is None, f"requete vide : pas de message attendu, obtenu {got['message']!r}"


def test_A18_trou_requete_blanche_equivaut_a_vide(a):
    _corpus(a)
    got = sorted(a.search("   ")["results"])
    assert got == ["Crème brûlée", "Omelette", "Tarte aux pommes"], f"obtenu {got!r}"


def test_A19_sans_correspondance_message_aucun_resultat(a):
    _corpus(a)
    got = a.search("chocolat")
    assert got["results"] == [] and got["message"] == "Aucun résultat", f"obtenu {got!r}"


def test_A19_avec_correspondance_pas_de_message(a):
    _corpus(a)
    got = a.search("omelette")
    assert got["message"] is None, f"obtenu {got!r}"


def test_A19_trou_filtre_sans_resultat_affiche_aucun_resultat(a):
    _corpus(a)
    got = a.search("", favorites_only=True)
    assert got["results"] == [] and got["message"] == "Aucun résultat", f"obtenu {got!r}"


# ----------------------------------------------------------------- A20 .. A22

def test_A20_marquage_favori_active_l_icone(a):
    rid = a.save_recipe("Tarte")
    assert a.recipe(rid)["favorite"] is False
    a.set_favorite(rid, True)
    assert a.recipe(rid)["favorite"] is True


def test_A21_retrait_des_favoris_desactive_l_icone(a):
    rid = a.save_recipe("Tarte")
    a.set_favorite(rid, True)
    a.set_favorite(rid, False)
    assert a.recipe(rid)["favorite"] is False


def test_A22_filtre_favoris_ne_montre_que_les_favorites(a):
    r1, r2, _ = _corpus(a)
    a.set_favorite(r1, True)
    a.set_favorite(r2, True)
    a.set_favorite(r2, False)
    got = a.search("", favorites_only=True)["results"]
    assert got == ["Tarte aux pommes"], f"obtenu {got!r}"


# ----------------------------------------------------------------- A23 / A24

def test_A23_note_affichee_sur_la_fiche(a):
    rid = a.save_recipe("Tarte")
    assert a.recipe(rid)["note"] is None
    a.set_note(rid, "Cuire 35 min à 180 °C — pâte brisée maison")
    assert a.recipe(rid)["note"] == "Cuire 35 min à 180 °C — pâte brisée maison"


def test_A24_effacement_du_texte_retire_la_note(a):
    rid = a.save_recipe("Tarte")
    a.set_note(rid, "Délicieux")
    a.set_note(rid, "")
    assert a.recipe(rid)["note"] is None, f"obtenu {a.recipe(rid)['note']!r}"


def test_A24_trou_note_blanche_retiree(a):
    rid = a.save_recipe("Tarte")
    a.set_note(rid, "Délicieux")
    a.set_note(rid, "  \n ")
    assert a.recipe(rid)["note"] is None, f"obtenu {a.recipe(rid)['note']!r}"


# ----------------------------------------------------------------- A25 .. A28

@pytest.mark.parametrize("img", [PNG, GIF], ids=["png", "gif"])
def test_A25_image_ajoutee_affichee(a, img):
    rid = a.save_recipe("Tarte")
    a.set_photo(rid, img)
    assert a.recipe(rid)["photo"] == img


@pytest.mark.parametrize("bad", [b"", b"hello world", b"%PDF-1.4\n%\xe2\xe3", b"GIF"],
                         ids=["vide", "texte", "pdf", "tronque"])
def test_A26_fichier_non_image_refuse(a, bad):
    rid = a.save_recipe("Tarte")
    with pytest.raises(app.InvalidInput):
        a.set_photo(rid, bad)
    assert a.recipe(rid)["photo"] == app.DEFAULT_PHOTO


def test_A26_refus_ne_remplace_pas_la_photo_existante(a):
    rid = a.save_recipe("Tarte")
    a.set_photo(rid, PNG)
    with pytest.raises(app.InvalidInput):
        a.set_photo(rid, b"not an image")
    assert a.recipe(rid)["photo"] == PNG


def test_A26_trou_signature_png_suivie_de_dechets_refusee(a):
    rid = a.save_recipe("Tarte")
    with pytest.raises(app.InvalidInput):
        a.set_photo(rid, b"\x89PNG\r\n\x1a\n" + b"ceci n'est pas une image")


def test_A27_sans_photo_image_par_defaut(a):
    rid = a.save_recipe("Tarte")
    assert isinstance(app.DEFAULT_PHOTO, bytes) and app.DEFAULT_PHOTO
    assert a.recipe(rid)["photo"] == app.DEFAULT_PHOTO
    assert app.DEFAULT_PHOTO not in (PNG, GIF)


def test_A28_suppression_photo_image_par_defaut(a):
    rid = a.save_recipe("Tarte")
    a.set_photo(rid, PNG)
    a.remove_photo(rid)
    assert a.recipe(rid)["photo"] == app.DEFAULT_PHOTO


# ----------------------------------------------------------------- A29 .. A34

def test_A29_chaque_ingredient_apparait_dans_la_liste_de_courses(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid)
    got = {k: qty(v["quantity"]) for k, v in shop(a).items()}
    assert got == {("farine", "g"): 250, ("lait", "ml"): 500, ("oeufs", "pièce"): 3}, got


def test_A30_portions_ajustees_reportees(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid, servings=8)
    got = {k: qty(v["quantity"]) for k, v in shop(a).items()}
    assert got == {("farine", "g"): 500, ("lait", "ml"): 1000, ("oeufs", "pièce"): 6}, got


def test_A31_meme_ingredient_meme_unite_une_ligne_sommee(a):
    r1 = a.save_recipe("Crêpes")
    a.add_ingredient(r1, "farine", 200, "g")
    r2 = a.save_recipe("Gâteau")
    a.add_ingredient(r2, "farine", 300, "g")
    a.add_to_shopping_list(r1)
    a.add_to_shopping_list(r2)
    lines = [i for i in a.shopping_list() if i["name"] == "farine"]
    assert len(lines) == 1 and qty(lines[0]["quantity"]) == 500, f"obtenu {lines!r}"


def test_A31_trou_meme_recette_ajoutee_deux_fois_sommee(a):
    r1 = a.save_recipe("Crêpes")
    a.add_ingredient(r1, "farine", 200, "g")
    a.add_to_shopping_list(r1)
    a.add_to_shopping_list(r1)
    lines = [i for i in a.shopping_list() if i["name"] == "farine"]
    assert len(lines) == 1 and qty(lines[0]["quantity"]) == 400, f"obtenu {lines!r}"


def test_A31_trou_noms_differant_par_la_casse_fusionnes(a):
    r1 = a.save_recipe("Crêpes")
    a.add_ingredient(r1, "Farine", 200, "g")
    r2 = a.save_recipe("Gâteau")
    a.add_ingredient(r2, "farine", 300, "g")
    a.add_to_shopping_list(r1)
    a.add_to_shopping_list(r2)
    lines = [i for i in a.shopping_list() if i["name"].lower() == "farine"]
    assert len(lines) == 1 and qty(lines[0]["quantity"]) == 500, f"obtenu {lines!r}"


def test_A31_trou_ligne_cochee_recevant_une_quantite_est_decochee(a):
    r1 = a.save_recipe("Crêpes")
    a.add_ingredient(r1, "farine", 200, "g")
    r2 = a.save_recipe("Gâteau")
    a.add_ingredient(r2, "farine", 300, "g")
    a.add_to_shopping_list(r1)
    a.check_item("farine", "g")
    a.add_to_shopping_list(r2)
    lines = [i for i in a.shopping_list() if i["name"] == "farine"]
    assert len(lines) == 1, f"obtenu {lines!r}"
    assert qty(lines[0]["quantity"]) == 500 and lines[0]["checked"] is False, f"obtenu {lines!r}"


def test_A32_unites_differentes_deux_lignes(a):
    r1 = a.save_recipe("Crêpes")
    a.add_ingredient(r1, "lait", 500, "ml")
    r2 = a.save_recipe("Flan")
    a.add_ingredient(r2, "lait", 1, "l")
    a.add_to_shopping_list(r1)
    a.add_to_shopping_list(r2)
    got = {k: qty(v["quantity"]) for k, v in shop(a).items()}
    assert got == {("lait", "ml"): 500, ("lait", "l"): 1}, got
    assert len(a.shopping_list()) == 2


def test_A33_article_coche_affiche_coche(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid)
    assert all(i["checked"] is False for i in a.shopping_list())
    a.check_item("lait", "ml")
    got = {k: v["checked"] for k, v in shop(a).items()}
    assert got == {("farine", "g"): False, ("lait", "ml"): True, ("oeufs", "pièce"): False}, got


def test_A33_decochage(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid)
    a.check_item("lait", "ml")
    a.check_item("lait", "ml", checked=False)
    assert shop(a)[("lait", "ml")]["checked"] is False


def test_A34_retirer_les_coches(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid)
    a.check_item("lait", "ml")
    a.check_item("oeufs", "pièce")
    a.remove_checked()
    got = sorted(shop(a))
    assert got == [("farine", "g")], f"obtenu {got!r}"


# ----------------------------------------------------------------- A35 / A36

def test_A35_suppression_fait_disparaitre_la_recette(a):
    r1 = a.save_recipe("Crêpes")
    a.save_recipe("Gâteau")
    a.delete_recipe(r1)
    assert titles(a) == ["Gâteau"], f"obtenu {titles(a)!r}"
    assert "Crêpes" not in a.search("")["results"]


def test_A36_suppression_ne_retire_pas_les_articles(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid, servings=8)
    a.check_item("lait", "ml")
    a.delete_recipe(rid)
    got = {k: (qty(v["quantity"]), v["checked"]) for k, v in shop(a).items()}
    assert got == {("farine", "g"): (500, False), ("lait", "ml"): (1000, True),
                   ("oeufs", "pièce"): (6, False)}, got


# ----------------------------------------------------------------- A37 .. A39 (persistance réelle)

def test_A37_recette_presente_apres_reouverture(db):
    a1 = app.App(db)
    rid = a1.save_recipe("Tarte aux pommes")
    a1.close()
    del a1
    a2 = app.App(db)
    assert titles(a2) == ["Tarte aux pommes"], f"obtenu {titles(a2)!r}"
    assert a2.recipe(rid)["title"] == "Tarte aux pommes"
    a2.close()


def test_A37_relue_par_un_autre_processus(db):
    a1 = app.App(db)
    a1.save_recipe("Tarte aux pommes")
    a1.save_recipe("Crème brûlée")
    a1.close()
    got = run_fresh_process(db, "print(json.dumps(sorted(r['title'] for r in a.list_recipes())))")
    assert got == ["Crème brûlée", "Tarte aux pommes"], f"processus neuf : obtenu {got!r}"


def test_A37_le_fichier_porte_les_donnees_copie_lisible(db, tmp_path):
    a1 = app.App(db)
    a1.save_recipe("Tarte aux pommes")
    a1.close()
    assert db.exists() and db.stat().st_size > 0, "aucun fichier de donnees ecrit au chemin donne"
    other = tmp_path / "copie" / "recettes.db"
    other.parent.mkdir()
    shutil.copyfile(db, other)
    a2 = app.App(other)
    assert titles(a2) == ["Tarte aux pommes"], f"copie du fichier : obtenu {titles(a2)!r}"
    a2.close()


def test_A37_fichier_supprime_plus_rien(db):
    a1 = app.App(db)
    a1.save_recipe("Tarte aux pommes")
    a1.close()
    os.remove(db)
    a2 = app.App(db)
    assert a2.list_recipes() == [], f"fichier supprime mais recette encore la : {a2.list_recipes()!r}"
    a2.close()


def test_A37_autre_chemin_ne_voit_rien(db, tmp_path):
    a1 = app.App(db)
    a1.save_recipe("Tarte aux pommes")
    a1.close()
    a2 = app.App(tmp_path / "autre.db")
    assert a2.list_recipes() == [], f"chemin vierge : obtenu {a2.list_recipes()!r}"
    a2.close()


def test_A37_details_et_ingredients_conserves(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.set_category(rid, "Dessert")
    a1.close()
    a2 = app.App(db)
    rid2 = find_id(a2, "Crêpes")
    got = {k: (qty(v["quantity"]), v["unit"]) for k, v in ing(a2, rid2).items()}
    assert got == {"farine": (250, "g"), "lait": (500, "ml"), "oeufs": (3, "pièce")}, got
    assert a2.recipe(rid2)["servings"] == 4
    a2.close()


def test_A38_favori_conserve_apres_reouverture(db):
    a1 = app.App(db)
    r1 = a1.save_recipe("Tarte")
    a1.save_recipe("Soupe")
    a1.set_favorite(r1, True)
    a1.close()
    a2 = app.App(db)
    assert a2.recipe(find_id(a2, "Tarte"))["favorite"] is True
    assert a2.recipe(find_id(a2, "Soupe"))["favorite"] is False
    assert a2.search("", favorites_only=True)["results"] == ["Tarte"]
    a2.close()


def test_A38_favori_relu_par_un_autre_processus(db):
    a1 = app.App(db)
    r1 = a1.save_recipe("Tarte")
    a1.save_recipe("Soupe")
    a1.set_favorite(r1, True)
    a1.close()
    got = run_fresh_process(
        db, "print(json.dumps({r['title']: a.recipe(r['id'])['favorite'] for r in a.list_recipes()}))")
    assert got == {"Tarte": True, "Soupe": False}, f"processus neuf : obtenu {got!r}"


def test_A38_retrait_favori_conserve(db):
    a1 = app.App(db)
    r1 = a1.save_recipe("Tarte")
    a1.set_favorite(r1, True)
    a1.close()
    a2 = app.App(db)
    a2.set_favorite(find_id(a2, "Tarte"), False)
    a2.close()
    a3 = app.App(db)
    assert a3.recipe(find_id(a3, "Tarte"))["favorite"] is False
    a3.close()


def test_A39_article_coche_conserve_apres_reouverture(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.add_to_shopping_list(rid)
    a1.check_item("lait", "ml")
    a1.close()
    a2 = app.App(db)
    got = {k: v["checked"] for k, v in shop(a2).items()}
    assert got == {("farine", "g"): False, ("lait", "ml"): True, ("oeufs", "pièce"): False}, got
    a2.close()


def test_A39_coche_relu_par_un_autre_processus(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.add_to_shopping_list(rid)
    a1.check_item("oeufs", "pièce")
    a1.close()
    got = run_fresh_process(
        db, "print(json.dumps(sorted([i['name'], i['unit'], i['checked']] for i in a.shopping_list())))")
    assert got == [["farine", "g", False], ["lait", "ml", False], ["oeufs", "pièce", True]], \
        f"processus neuf : obtenu {got!r}"
