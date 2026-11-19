"""Tests rouges -- sonde P02, deuxieme attaque (carnet de recettes).

Meme interface publique que tests/test_app.py (module `app`).
Cibles : arrondis non naifs, sommes flottantes, identifiants recycles, rechargement qui
duplique, persistance des champs binaires, interactions filtres/requete, repetition,
deux instances sur le meme fichier.
"""

import hashlib
import json
import os
import re
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
DISPLAY = re.compile(r"\d+(\.\d{1,2})?")


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


def shop(inst):
    return {(i["name"], i["unit"]): i for i in inst.shopping_list()}


def find_id(inst, title):
    ids = [r["id"] for r in inst.list_recipes() if r["title"] == title]
    assert len(ids) == 1, f"attendu une recette '{title}', obtenu {inst.list_recipes()!r}"
    return ids[0]


def run_fresh_process(path, code):
    app_dir = os.path.dirname(os.path.abspath(app.__file__))
    env = dict(os.environ)
    env["PYTHONPATH"] = app_dir + os.pathsep + env.get("PYTHONPATH", "")
    script = "import app, json, sys, hashlib\na = app.App(sys.argv[1])\n" + code
    out = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True,
                         text=True, env=env, timeout=15)
    assert out.returncode == 0, f"processus neuf en echec : {out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def _crepes(inst):
    rid = inst.save_recipe("Crêpes", servings=4)
    inst.add_ingredient(rid, "farine", 250, "g")
    inst.add_ingredient(rid, "lait", 500, "ml")
    inst.add_ingredient(rid, "oeufs", 3, "pièce")
    return rid


# ----------------------------------------------------------------- A02 / A35 : identifiants

def test_A35_identifiant_non_recycle_apres_suppression(a):
    r1 = a.save_recipe("Crêpes")
    r2 = a.save_recipe("Gâteau")
    a.delete_recipe(r1)
    r3 = a.save_recipe("Flan")
    assert r3 != r2, f"nouvel identifiant {r3!r} identique a celui de 'Gâteau' {r2!r}"
    assert titles(a) == ["Flan", "Gâteau"], f"obtenu {titles(a)!r}"
    assert a.recipe(r2)["title"] == "Gâteau", f"fiche de r2 : {a.recipe(r2)['title']!r}"
    assert a.recipe(r3)["title"] == "Flan", f"fiche de r3 : {a.recipe(r3)['title']!r}"


def test_A35_identifiant_non_recycle_apres_reouverture(db):
    a1 = app.App(db)
    r1 = a1.save_recipe("Crêpes")
    r2 = a1.save_recipe("Gâteau")
    a1.delete_recipe(r1)
    a1.close()
    a2 = app.App(db)
    r3 = a2.save_recipe("Flan")
    a2.add_ingredient(r3, "lait", 1, "l")
    assert r3 != r2, f"identifiant recycle : {r3!r}"
    assert ing(a2, r2) == {}, f"'Gâteau' a recu l'ingredient de 'Flan' : {ing(a2, r2)!r}"
    assert titles(a2) == ["Flan", "Gâteau"], f"obtenu {titles(a2)!r}"
    a2.close()


def test_A35_suppression_conservee_apres_reouverture(db):
    a1 = app.App(db)
    r1 = a1.save_recipe("Crêpes")
    a1.save_recipe("Gâteau")
    a1.set_favorite(r1, True)
    a1.delete_recipe(r1)
    a1.close()
    a2 = app.App(db)
    assert titles(a2) == ["Gâteau"], f"recette supprimee revenue : {titles(a2)!r}"
    assert a2.search("", favorites_only=True)["results"] == []
    a2.close()


def test_A35_recette_supprimee_absente_de_la_recherche_par_ingredient(a):
    rid = _crepes(a)
    a.delete_recipe(rid)
    got = a.search("farine")
    assert got["results"] == [] and got["message"] == "Aucun résultat", f"obtenu {got!r}"


# ----------------------------------------------------------------- A09 : arrondi

@pytest.mark.parametrize("base,q,target", [(3, 0.1, 9), (3, 0.7, 1), (7, 1, 3), (6, 0.35, 5)])
def test_A09_au_plus_deux_decimales_affichees(a, base, q, target):
    rid = a.save_recipe("Sauce", servings=base)
    a.add_ingredient(rid, "beurre", q, "g")
    got = ing(a, rid, servings=target)["beurre"]["quantity"]
    expected = round(q * target / base + 1e-9, 2)
    assert DISPLAY.fullmatch(got), f"{q}*{target}/{base} : affichage {got!r} non arrondi a 2 decimales"
    assert abs(float(got) - expected) < 1e-9, f"attendu {expected}, obtenu {got!r}"


@pytest.mark.parametrize("base,q,target,expected",
                         [(8, 5, 1, "0.63"), (4, 2.01, 2, "1.01"), (4, 5.35, 2, "2.68")])
def test_A09_trou_arrondi_demi_superieur(a, base, q, target, expected):
    rid = a.save_recipe("Sauce", servings=base)
    a.add_ingredient(rid, "beurre", q, "g")
    got = ing(a, rid, servings=target)["beurre"]["quantity"]
    assert float(got) == float(expected), \
        f"{q}*{target}/{base} : valeur a mi-chemin, attendu {expected!r} (demi vers le haut), obtenu {got!r}"


def test_A09_trou_quantite_ajustee_dans_la_liste_de_courses_arrondie(a):
    rid = a.save_recipe("Sauce", servings=3)
    a.add_ingredient(rid, "beurre", 1, "c. à s.")
    a.add_to_shopping_list(rid, servings=4)
    got = shop(a)[("beurre", "c. à s.")]["quantity"]
    assert got == "1.33", f"liste de courses : attendu '1.33', obtenu {got!r}"


# ----------------------------------------------------------------- A31 : sommes

def test_A31_somme_decimale_exacte(a):
    r1 = a.save_recipe("Crêpes")
    a.add_ingredient(r1, "levure", "0.1", "g")
    r2 = a.save_recipe("Gâteau")
    a.add_ingredient(r2, "levure", "0.2", "g")
    a.add_to_shopping_list(r1)
    a.add_to_shopping_list(r2)
    got = shop(a)[("levure", "g")]["quantity"]
    assert DISPLAY.fullmatch(got) and float(got) == 0.3, f"0.1 + 0.2 : attendu 0.3, obtenu {got!r}"


def test_A31_repetition_trente_ajouts_somme_exacte(a):
    rid = a.save_recipe("Crêpes")
    a.add_ingredient(rid, "sel", "0.1", "g")
    for _ in range(30):
        a.add_to_shopping_list(rid)
    lines = [i for i in a.shopping_list() if i["name"] == "sel"]
    assert len(lines) == 1, f"obtenu {lines!r}"
    got = lines[0]["quantity"]
    assert DISPLAY.fullmatch(got) and float(got) == 3, f"30 x 0.1 : attendu 3, obtenu {got!r}"


def test_A31_somme_quantite_ajustee_et_non_ajustee(a):
    r1 = _crepes(a)
    r2 = a.save_recipe("Gâteau")
    a.add_ingredient(r2, "farine", 300, "g")
    a.add_to_shopping_list(r1, servings=8)
    a.add_to_shopping_list(r2)
    lines = [i for i in a.shopping_list() if i["name"] == "farine"]
    assert len(lines) == 1 and float(lines[0]["quantity"]) == 800, f"500 + 300 : obtenu {lines!r}"


def test_A31_somme_a_travers_une_reouverture(db):
    a1 = app.App(db)
    r1 = a1.save_recipe("Crêpes")
    a1.add_ingredient(r1, "farine", 200, "g")
    r2 = a1.save_recipe("Gâteau")
    a1.add_ingredient(r2, "farine", 300, "g")
    a1.add_to_shopping_list(r1)
    a1.close()
    a2 = app.App(db)
    a2.add_to_shopping_list(r2)
    lines = [i for i in a2.shopping_list() if i["name"] == "farine"]
    assert len(lines) == 1 and float(lines[0]["quantity"]) == 500, f"obtenu {lines!r}"
    a2.close()


# ----------------------------------------------------------------- A11 / A12 / A30

def test_A11_portions_nulles_refusees_pour_la_liste_de_courses(a):
    rid = _crepes(a)
    for bad in (0, -2, 0.5):
        with pytest.raises(app.InvalidInput):
            a.add_to_shopping_list(rid, servings=bad)
    assert a.shopping_list() == [], f"refus mais articles ajoutes : {a.shopping_list()!r}"


@pytest.mark.parametrize("bad", [0.5, "0"])
def test_A11_portions_fractionnaires_ou_texte_nul_refusees_a_l_enregistrement(a, bad):
    with pytest.raises(app.InvalidInput):
        a.save_recipe("Crêpes", servings=bad)
    assert a.list_recipes() == [], f"obtenu {a.list_recipes()!r}"


def test_A12_ajustement_n_affecte_pas_un_ajout_ulterieur_aux_courses(a):
    rid = _crepes(a)
    a.recipe(rid, servings=8)
    a.add_to_shopping_list(rid, servings=8)
    a.add_to_shopping_list(rid)
    got = float(shop(a)[("farine", "g")]["quantity"])
    assert got == 750, f"500 (8 portions) + 250 (portions d'origine) : attendu 750, obtenu {got}"
    assert a.recipe(rid)["servings"] == 4


# ----------------------------------------------------------------- A14 / A22 : filtres combines

def test_A14_filtre_categorie_combine_a_une_requete(a):
    r1 = a.save_recipe("Tarte aux pommes")
    r2 = a.save_recipe("Tarte salée")
    a.set_category(r1, "Dessert")
    a.set_category(r2, "Plat")
    got = a.search("tarte", category="Plat")["results"]
    assert got == ["Tarte salée"], f"requete 'tarte' + categorie Plat : obtenu {got!r}"


def test_A22_filtre_favoris_combine_a_une_requete_et_une_categorie(a):
    r1 = a.save_recipe("Tarte aux pommes")
    r2 = a.save_recipe("Tarte salée")
    r3 = a.save_recipe("Tarte au citron")
    for r in (r1, r3):
        a.set_category(r, "Dessert")
    a.set_category(r2, "Dessert")
    a.set_favorite(r1, True)
    a.set_favorite(r2, True)
    got = a.search("tarte", category="Dessert", favorites_only=True)["results"]
    assert sorted(got) == ["Tarte aux pommes", "Tarte salée"], f"obtenu {got!r}"
    a.set_category(r2, "Plat")
    got = a.search("tarte", category="Dessert", favorites_only=True)["results"]
    assert got == ["Tarte aux pommes"], f"obtenu {got!r}"


# ----------------------------------------------------------------- A15 .. A17 : requete

def test_A15_mot_du_titre_apres_une_apostrophe(a):
    a.save_recipe("Gratin d'aubergines")
    got = a.search("aubergines")["results"]
    assert got == ["Gratin d'aubergines"], f"obtenu {got!r}"


def test_A15_mot_du_titre_suivi_d_une_virgule(a):
    a.save_recipe("Pâtes, sauce tomate")
    got = a.search("pâtes")["results"]
    assert got == ["Pâtes, sauce tomate"], f"obtenu {got!r}"


def test_A16_requete_contenant_le_nom_d_un_ingredient_parmi_d_autres_mots(a):
    r1 = a.save_recipe("Crème brûlée")
    a.add_ingredient(r1, "sucre glace", 20, "g")
    r2 = a.save_recipe("Pain")
    a.add_ingredient(r2, "farine", 500, "g")
    assert a.search("farine bio")["results"] == ["Pain"], a.search("farine bio")
    assert a.search("sucre glace vanille")["results"] == ["Crème brûlée"], a.search("sucre glace vanille")


def test_A17_majuscules_eszett(a):
    a.save_recipe("Weißwurst")
    lo = a.search("weißwurst")["results"]
    up = a.search("weißwurst".upper())["results"]
    assert lo == ["Weißwurst"] and up == lo, f"'weißwurst' -> {lo!r}, {'weißwurst'.upper()!r} -> {up!r}"


def test_A17_majuscules_ligature_oe_sur_ingredient(a):
    rid = a.save_recipe("Omelette")
    a.add_ingredient(rid, "œufs", 3, "pièce")
    lo = a.search("œufs")["results"]
    up = a.search("ŒUFS")["results"]
    assert lo == ["Omelette"] and up == lo, f"'œufs' -> {lo!r}, 'ŒUFS' -> {up!r}"


# ----------------------------------------------------------------- A26 / A27 : images

@pytest.mark.parametrize("bad", [
    b"GIF89a" + b"x" * 40,
    b"\xff\xd8\xff\xe0" + b"ceci n'est pas un jpeg" * 3,
    b"\x89PNG\r\n\x1a\n",
], ids=["gif_dechets", "jpeg_dechets", "png_signature_seule"])
def test_A26_signature_d_image_suivie_de_dechets_refusee(a, bad):
    rid = a.save_recipe("Tarte")
    with pytest.raises(app.InvalidInput):
        a.set_photo(rid, bad)
    assert a.recipe(rid)["photo"] == app.DEFAULT_PHOTO


def test_A27_image_par_defaut_est_une_image_acceptee(a):
    rid = a.save_recipe("Tarte")
    try:
        a.set_photo(rid, app.DEFAULT_PHOTO)
    except app.InvalidInput:
        pytest.fail("DEFAULT_PHOTO est refusee par la validation d'image : ce n'est pas une image")
    assert a.recipe(rid)["photo"] == app.DEFAULT_PHOTO


# ----------------------------------------------------------------- A34 / A36 / A39 : liste de courses

def test_A34_retrait_des_coches_conserve_apres_reouverture(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.add_to_shopping_list(rid)
    a1.check_item("lait", "ml")
    a1.remove_checked()
    a1.close()
    a2 = app.App(db)
    assert sorted(shop(a2)) == [("farine", "g"), ("oeufs", "pièce")], f"obtenu {sorted(shop(a2))!r}"
    a2.close()


def test_A34_article_retire_puis_rajoute_repart_non_coche(a):
    rid = _crepes(a)
    a.add_to_shopping_list(rid)
    a.check_item("lait", "ml")
    a.remove_checked()
    a.add_to_shopping_list(rid)
    got = shop(a)
    assert float(got[("lait", "ml")]["quantity"]) == 500 and got[("lait", "ml")]["checked"] is False, got
    assert float(got[("farine", "g")]["quantity"]) == 500, got


def test_A36_articles_orphelins_conserves_apres_reouverture(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.add_to_shopping_list(rid)
    a1.check_item("oeufs", "pièce")
    a1.delete_recipe(rid)
    a1.close()
    a2 = app.App(db)
    got = {k: (float(v["quantity"]), v["checked"]) for k, v in shop(a2).items()}
    assert got == {("farine", "g"): (250, False), ("lait", "ml"): (500, False),
                   ("oeufs", "pièce"): (3, True)}, got
    a2.close()


# ----------------------------------------------------------------- A37 .. A39 : persistance

def test_A37_reouvertures_sans_modification_ne_dupliquent_ni_ne_perdent(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.add_to_shopping_list(rid)
    a1.close()
    for _ in range(5):
        ax = app.App(db)
        ax.close()
    a2 = app.App(db)
    assert titles(a2) == ["Crêpes"], f"apres 5 reouvertures : {titles(a2)!r}"
    assert len(ing(a2, rid)) == 3, f"ingredients : {ing(a2, rid)!r}"
    assert len(a2.shopping_list()) == 3 and float(shop(a2)[("farine", "g")]["quantity"]) == 250, \
        f"liste de courses : {a2.shopping_list()!r}"
    a2.close()


def test_A37_modifications_de_sessions_successives_cumulees(db):
    a1 = app.App(db)
    rid = a1.save_recipe("Crêpes")
    a1.add_ingredient(rid, "farine", 250, "g")
    a1.close()
    a2 = app.App(db)
    a2.add_ingredient(rid, "lait", 500, "ml")
    a2.save_recipe("Gâteau")
    a2.close()
    a3 = app.App(db)
    a3.remove_ingredient(rid, "farine")
    a3.close()
    a4 = app.App(db)
    assert titles(a4) == ["Crêpes", "Gâteau"], f"obtenu {titles(a4)!r}"
    assert set(ing(a4, rid)) == {"lait"}, f"obtenu {ing(a4, rid)!r}"
    a4.close()


def test_A37_trou_photo_note_categorie_conservees(db):
    a1 = app.App(db)
    rid = a1.save_recipe("Tarte")
    a1.set_photo(rid, PNG)
    a1.set_note(rid, "Cuire 35 min — four à 180 °C\nservir tiède")
    a1.set_category(rid, "Dessert")
    a1.close()
    a2 = app.App(db)
    fiche = a2.recipe(rid)
    assert fiche["photo"] == PNG, "photo perdue ou alteree apres reouverture"
    assert fiche["note"] == "Cuire 35 min — four à 180 °C\nservir tiède", f"note : {fiche['note']!r}"
    assert fiche["category"] == "Dessert", f"categorie : {fiche['category']!r}"
    assert a2.search("", category="Dessert")["results"] == ["Tarte"]
    a2.close()


def test_A37_trou_photo_relue_par_un_autre_processus(db):
    a1 = app.App(db)
    rid = a1.save_recipe("Tarte")
    a1.set_photo(rid, PNG)
    a1.close()
    got = run_fresh_process(
        db, "print(json.dumps([hashlib.sha256(a.recipe(r['id'])['photo']).hexdigest()"
            " for r in a.list_recipes()]))")
    assert got == [hashlib.sha256(PNG).hexdigest()], f"processus neuf : empreintes {got!r}"


def test_A37_trou_deux_instances_meme_fichier(db):
    a1 = app.App(db)
    a2 = app.App(db)
    a1.save_recipe("Tarte")
    a1.close()
    a2.save_recipe("Soupe")
    a2.close()
    a3 = app.App(db)
    assert titles(a3) == ["Soupe", "Tarte"], f"une ecriture a ecrase l'autre : {titles(a3)!r}"
    a3.close()


def test_A38_bascules_repetees_etat_final_conserve(db):
    a1 = app.App(db)
    rid = a1.save_recipe("Tarte")
    for i in range(101):
        a1.set_favorite(rid, i % 2 == 0)
    a1.close()
    a2 = app.App(db)
    assert a2.recipe(rid)["favorite"] is True, "101 bascules, la derniere a True"
    a2.close()


def test_A39_decochage_conserve_apres_reouverture(db):
    a1 = app.App(db)
    rid = _crepes(a1)
    a1.add_to_shopping_list(rid)
    a1.check_item("lait", "ml")
    a1.close()
    a2 = app.App(db)
    a2.check_item("lait", "ml", checked=False)
    a2.check_item("farine", "g")
    a2.close()
    a3 = app.App(db)
    got = {k: v["checked"] for k, v in shop(a3).items()}
    assert got == {("farine", "g"): True, ("lait", "ml"): False, ("oeufs", "pièce"): False}, got
    a3.close()
