"""Generateur de situations -- sonde P02 (carnet de recettes).

scenario(app, rng, dossier) joue une situation tiree au hasard avec `rng` et rend
une liste de paires (action, observation). Les observations ne contiennent que ce que
l'utilisateur voit : pas d'identifiant opaque, pas d'octets bruts, ordre trie quand
l'ordre n'a pas de sens.
"""

import os
import struct
import zlib


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

IMAGES = [("png", PNG), ("gif", GIF)]
NON_IMAGES = [("vide", b""), ("texte", b"hello world"), ("pdf", b"%PDF-1.4\n%\xe2\xe3"),
              ("gif_tronque", b"GIF"), ("png_signature_seule", b"\x89PNG\r\n\x1a\n"),
              ("png_dechets", b"\x89PNG\r\n\x1a\n" + b"pas une image")]

TITLES = ["Tarte aux pommes", "Crêpes", "Crème brûlée", "Omelette", "Gratin d'aubergines",
          "Pâtes, sauce tomate", "Soupe", "Pain", "Weißwurst", "Flan", "Tarte salée"]
BAD_TITLES = ["", "   ", "\t "]
INGREDIENTS = [("farine", "g"), ("lait", "ml"), ("lait", "l"), ("oeufs", "pièce"),
               ("œufs", "pièce"), ("sucre glace", "g"), ("beurre", "c. à s."),
               ("sel", "g"), ("crème", "cl"), ("Farine", "g"), ("pommes", "pièce")]
GOOD_QTY = [250, 500, 3, 1, 2, "0.5", "1,5", "0.1", 0.35, "200", 5.35, 2.01, 7]
BAD_QTY = ["abc", "", "12abc", "deux", " ", "nan", "inf", 0, -1, "0", "-2", -0.5, "0.0"]
GOOD_SERV = [1, 2, 3, 4, 6, 8, 12]
BAD_SERV = [0, -1, 0.5, -3]
CATEGORIES = ["Dessert", "Plat", "Entrée", "Goûter"]
QUERIES = ["", "   ", "tarte", "TARTE", "farine", "FARINE", "sucre glace", "crème", "CRÈME",
           "brûlée", "chocolat", "aubergines", "pâtes", "weißwurst", "WEISSWURST", "œufs",
           "ŒUFS", "tarte fine", "farine bio", "omelette", "lait"]
NOTES = ["Délicieux", "Cuire 35 min à 180 °C — pâte brisée maison", "servir tiède\nou froid"]
BLANK_NOTES = ["", "  \n "]


def scenario(app, rng, dossier):
    out = []
    path = os.path.join(str(dossier), "recettes.db")
    default_photo = getattr(app, "DEFAULT_PHOTO", None)
    st = {"inst": None, "n": 0}
    table = {}  # mon nom -> identifiant rendu par app
    shop_keys = []  # (nom, unite) deja vus dans la liste de courses

    def open_app():
        st["inst"] = app.App(path)

    def label_of(name):
        return name

    def view_titles():
        return sorted(str(r.get("title")) for r in st["inst"].list_recipes())

    def view_photo(data):
        if default_photo is not None and data == default_photo:
            return "image par défaut"
        if isinstance(data, (bytes, bytearray)):
            return {"image": True, "taille": len(data)}
        return {"image": False}

    def view_recipe(rid, servings=None):
        if servings is None:
            f = st["inst"].recipe(rid)
        else:
            f = st["inst"].recipe(rid, servings=servings)
        ings = sorted(
            ([str(i.get("name")), str(i.get("quantity")), str(i.get("unit"))]
             for i in f.get("ingredients", [])))
        return {"titre": f.get("title"), "portions": f.get("servings"),
                "catégorie": f.get("category"), "favori": f.get("favorite"),
                "note": f.get("note"), "photo": view_photo(f.get("photo")),
                "ingrédients": ings}

    def view_search(**kw):
        r = st["inst"].search(**kw)
        return {"résultats": sorted(str(t) for t in r.get("results", [])),
                "message": r.get("message")}

    def view_shop():
        items = st["inst"].shopping_list()
        for i in items:
            k = (i.get("name"), i.get("unit"))
            if k not in shop_keys:
                shop_keys.append(k)
        return sorted([str(i.get("name")), str(i.get("quantity")), str(i.get("unit")),
                       bool(i.get("checked"))] for i in items)

    def fresh_name(title):
        st["n"] += 1
        return "%s#%d" % (title, st["n"])

    def pick():
        names = sorted(table)
        return rng.choice(names) if names else None

    # ------------------------------------------------------------ actions

    def a_save():
        r = rng.random()
        if r < 0.12:
            title = rng.choice(BAD_TITLES)
            return "save_recipe(%r)" % title, lambda: (st["inst"].save_recipe(title), view_titles())[1]
        if r < 0.22:
            title, serv = rng.choice(TITLES), rng.choice(BAD_SERV)
            return ("save_recipe(%r, %r)" % (title, serv),
                    lambda: (st["inst"].save_recipe(title, servings=serv), view_titles())[1])
        title, serv = rng.choice(TITLES), rng.choice(GOOD_SERV + [4, 4, 4])
        name = fresh_name(title)

        def run():
            table[name] = st["inst"].save_recipe(title, servings=serv)
            return view_titles()
        return "save_recipe(%r, %r) -> %s" % (title, serv, name), run

    def a_add_ing():
        n = pick()
        ing, unit = rng.choice(INGREDIENTS)
        q = rng.choice(BAD_QTY) if rng.random() < 0.25 else rng.choice(GOOD_QTY)
        return ("add_ingredient(%s, %r, %r, %r)" % (n, ing, q, unit),
                lambda: (st["inst"].add_ingredient(table[n], ing, q, unit), view_recipe(table[n]))[1])

    def a_remove_ing():
        n = pick()
        ing = rng.choice(INGREDIENTS)[0]
        return ("remove_ingredient(%s, %r)" % (n, ing),
                lambda: (st["inst"].remove_ingredient(table[n], ing), view_recipe(table[n]))[1])

    def a_view():
        n = pick()
        r = rng.random()
        if r < 0.45:
            return "recipe(%s)" % n, lambda: view_recipe(table[n])
        s = rng.choice(BAD_SERV) if r > 0.85 else rng.choice(GOOD_SERV)
        return "recipe(%s, servings=%r)" % (n, s), lambda: view_recipe(table[n], s)

    def a_category():
        n, c = pick(), rng.choice(CATEGORIES)
        return ("set_category(%s, %r)" % (n, c),
                lambda: (st["inst"].set_category(table[n], c), view_recipe(table[n]))[1])

    def a_favorite():
        n, v = pick(), rng.random() < 0.65
        return ("set_favorite(%s, %r)" % (n, v),
                lambda: (st["inst"].set_favorite(table[n], v), view_recipe(table[n]))[1])

    def a_note():
        n = pick()
        t = rng.choice(BLANK_NOTES) if rng.random() < 0.3 else rng.choice(NOTES)
        return ("set_note(%s, %r)" % (n, t),
                lambda: (st["inst"].set_note(table[n], t), view_recipe(table[n]))[1])

    def a_photo():
        n = pick()
        r = rng.random()
        if r < 0.2:
            return ("remove_photo(%s)" % n,
                    lambda: (st["inst"].remove_photo(table[n]), view_recipe(table[n]))[1])
        if r < 0.5:
            lab, data = rng.choice(NON_IMAGES)
        elif r < 0.6 and default_photo is not None:
            lab, data = "DEFAULT_PHOTO", default_photo
        else:
            lab, data = rng.choice(IMAGES)
        return ("set_photo(%s, <%s>)" % (n, lab),
                lambda: (st["inst"].set_photo(table[n], data), view_recipe(table[n]))[1])

    def a_search():
        q = rng.choice(QUERIES)
        kw = {"query": q}
        txt = "search(%r" % q
        if rng.random() < 0.3:
            kw["category"] = rng.choice(CATEGORIES)
            txt += ", category=%r" % kw["category"]
        if rng.random() < 0.25:
            kw["favorites_only"] = True
            txt += ", favorites_only=True"
        return txt + ")", lambda: view_search(**kw)

    def a_add_shop():
        n = pick()
        r = rng.random()
        if r < 0.5:
            return ("add_to_shopping_list(%s)" % n,
                    lambda: (st["inst"].add_to_shopping_list(table[n]), view_shop())[1])
        s = rng.choice(BAD_SERV) if r > 0.88 else rng.choice(GOOD_SERV)
        return ("add_to_shopping_list(%s, servings=%r)" % (n, s),
                lambda: (st["inst"].add_to_shopping_list(table[n], servings=s), view_shop())[1])

    def a_check():
        if shop_keys and rng.random() < 0.85:
            name, unit = rng.choice(shop_keys)
        else:
            name, unit = rng.choice(INGREDIENTS)
        c = rng.random() < 0.75
        return ("check_item(%r, %r, checked=%r)" % (name, unit, c),
                lambda: (st["inst"].check_item(name, unit, checked=c), view_shop())[1])

    def a_remove_checked():
        return "remove_checked()", lambda: (st["inst"].remove_checked(), view_shop())[1]

    def a_shop():
        return "shopping_list()", view_shop

    def a_delete():
        n = pick()

        def run():
            rid = table.pop(n)
            st["inst"].delete_recipe(rid)
            return {"recettes": view_titles(), "courses": view_shop()}
        return "delete_recipe(%s)" % n, run

    def a_reopen():
        def run():
            try:
                if st["inst"] is not None:
                    st["inst"].close()
            finally:
                st["inst"] = None
                open_app()
            return {"recettes": view_titles(),
                    "favoris": view_search(query="", favorites_only=True)["résultats"],
                    "courses": view_shop()}
        return "fermer puis rouvrir l'application", run

    def a_list():
        return "list_recipes()", view_titles

    needs_recipe = [(a_add_ing, 14), (a_remove_ing, 4), (a_view, 9), (a_category, 5),
                    (a_favorite, 6), (a_note, 4), (a_photo, 5), (a_add_shop, 9),
                    (a_delete, 3)]
    always = [(a_save, 8), (a_search, 9), (a_check, 5), (a_remove_checked, 3),
              (a_shop, 2), (a_reopen, 5), (a_list, 2)]

    def choose():
        pool = list(always) + (list(needs_recipe) if table else [])
        if not table:
            pool = [(a_save, 30)] + pool
        total = sum(w for _, w in pool)
        x = rng.random() * total
        for f, w in pool:
            x -= w
            if x < 0:
                return f
        return pool[-1][0]

    # ------------------------------------------------------------ jeu

    try:
        open_app()
        out.append(("App(dossier/recettes.db)", {"recettes": view_titles()}))
    except Exception:
        out.append(("App(dossier/recettes.db)", "refusé"))

    n_actions = rng.randint(15, 40)
    while len(out) < n_actions:
        try:
            f = choose()
            text, run = f()
        except Exception:
            continue
        try:
            obs = run()
        except Exception:
            obs = "refusé"
        out.append((text, obs))

    try:
        if st["inst"] is not None:
            st["inst"].close()
    except Exception:
        pass
    return out
