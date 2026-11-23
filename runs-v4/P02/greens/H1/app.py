"""Carnet de recettes -- module unique (sonde P02, couche code, tour 2).

Persistance : fichier SQLite au chemin donne ; chaque instance relit le fichier.
Calculs de quantites en Decimal (a partir de la representation decimale des
flottants), arrondi a deux decimales demi-vers-le-haut.
"""

import math
import re
import sqlite3
import struct
import unicodedata
import zlib
from decimal import Decimal, ROUND_HALF_UP


class InvalidInput(ValueError):
    """Saisie refusee."""


def _png_bytes(rgb):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = b"\x00" + bytes(rgb)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(pixel)) + chunk(b"IEND", b""))


DEFAULT_PHOTO = _png_bytes((0, 0, 255))

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_NUMBER = re.compile(r"[0-9]+(\.[0-9]*)?|\.[0-9]+")
_NO_MATCH = "Aucun résultat"
_CENT = Decimal("0.01")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    servings INTEGER NOT NULL,
    category TEXT,
    favorite INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    photo BLOB
);
CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shopping (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity REAL NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0
);
"""


def _norm(text):
    return unicodedata.normalize("NFC", text).casefold()


def _dec(value):
    """Decimal exact a partir de la representation decimale du flottant."""
    if isinstance(value, Decimal):
        return value
    return Decimal(repr(float(value)))


def _scale(quantity, target, base):
    return _dec(quantity) * target / base


def _fmt(value):
    text = format(_dec(value).quantize(_CENT, rounding=ROUND_HALF_UP), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _parse_quantity(value):
    if isinstance(value, bool):
        raise InvalidInput(f"quantite non numerique : {value!r}")
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not _NUMBER.fullmatch(text):
            raise InvalidInput(f"quantite non numerique : {value!r}")
        number = float(text)
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        raise InvalidInput(f"quantite non numerique : {value!r}")
    if not math.isfinite(number) or number <= 0:
        raise InvalidInput(f"quantite non positive : {value!r}")
    return number


def _check_servings(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidInput(f"portions invalides : {value!r}")
    return value


def _is_png(data):
    if not data.startswith(_PNG_SIGNATURE):
        return False
    pos = len(_PNG_SIGNATURE)
    first = True
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return False
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:end])[0]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            return False
        if first:
            if kind != b"IHDR" or length != 13:
                return False
            first = False
        if kind == b"IEND":
            return end == len(data)
        pos = end
    return False


def _is_gif(data):
    return (data[:6] in (b"GIF87a", b"GIF89a")
            and len(data) >= 13 and data[-1:] == b"\x3b")


def _is_image(data):
    return _is_png(data) or _is_gif(data)


class App:
    def __init__(self, path):
        self._db = sqlite3.connect(str(path))
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None

    # ------------------------------------------------------------ helpers

    def _recipe_row(self, rid):
        row = self._db.execute(
            "SELECT title, servings, category, favorite, note, photo "
            "FROM recipes WHERE id = ?", (rid,)).fetchone()
        if row is None:
            raise KeyError(f"recette inconnue : {rid!r}")
        return row

    def _ingredient_rows(self, rid):
        return self._db.execute(
            "SELECT name, quantity, unit FROM ingredients "
            "WHERE recipe_id = ? ORDER BY id", (rid,)).fetchall()

    # ------------------------------------------------------------ recettes

    def save_recipe(self, title, servings=4):
        if not isinstance(title, str) or not title.strip():
            raise InvalidInput("titre vide")
        _check_servings(servings)
        cur = self._db.execute(
            "INSERT INTO recipes (title, servings) VALUES (?, ?)",
            (title.strip(), servings))
        self._db.commit()
        return cur.lastrowid

    def delete_recipe(self, rid):
        self._db.execute("DELETE FROM ingredients WHERE recipe_id = ?", (rid,))
        self._db.execute("DELETE FROM recipes WHERE id = ?", (rid,))
        self._db.commit()

    def list_recipes(self):
        rows = self._db.execute("SELECT id, title FROM recipes ORDER BY id").fetchall()
        return [{"id": rid, "title": title} for rid, title in rows]

    def recipe(self, rid, servings=None):
        title, base, category, favorite, note, photo = self._recipe_row(rid)
        target = base if servings is None else _check_servings(servings)
        ingredients = [
            {"name": name, "quantity": _fmt(_scale(qty, target, base)), "unit": unit}
            for name, qty, unit in self._ingredient_rows(rid)
        ]
        return {
            "title": title,
            "servings": target,
            "category": category,
            "favorite": bool(favorite),
            "note": note,
            "photo": photo if photo is not None else DEFAULT_PHOTO,
            "ingredients": ingredients,
        }

    # ------------------------------------------------------------ ingredients

    def add_ingredient(self, rid, name, quantity, unit):
        self._recipe_row(rid)
        if not isinstance(name, str) or not name.strip():
            raise InvalidInput("nom d'ingredient vide")
        value = _parse_quantity(quantity)
        self._db.execute(
            "INSERT INTO ingredients (recipe_id, name, quantity, unit) VALUES (?, ?, ?, ?)",
            (rid, name.strip(), value, unit.strip()))
        self._db.commit()

    def remove_ingredient(self, rid, name):
        self._db.execute(
            "DELETE FROM ingredients WHERE recipe_id = ? AND name = ?",
            (rid, name.strip()))
        self._db.commit()

    # ------------------------------------------------------------ fiche

    def set_category(self, rid, category):
        self._recipe_row(rid)
        value = category.strip() if isinstance(category, str) else None
        self._db.execute("UPDATE recipes SET category = ? WHERE id = ?",
                         (value or None, rid))
        self._db.commit()

    def set_favorite(self, rid, flag):
        self._recipe_row(rid)
        self._db.execute("UPDATE recipes SET favorite = ? WHERE id = ?",
                         (1 if flag else 0, rid))
        self._db.commit()

    def set_note(self, rid, text):
        self._recipe_row(rid)
        value = None if text is None or not text.strip() else text
        self._db.execute("UPDATE recipes SET note = ? WHERE id = ?", (value, rid))
        self._db.commit()

    def set_photo(self, rid, data):
        self._recipe_row(rid)
        if not isinstance(data, (bytes, bytearray)) or not _is_image(bytes(data)):
            raise InvalidInput("le fichier n'est pas une image")
        self._db.execute("UPDATE recipes SET photo = ? WHERE id = ?",
                         (bytes(data), rid))
        self._db.commit()

    def remove_photo(self, rid):
        self._recipe_row(rid)
        self._db.execute("UPDATE recipes SET photo = NULL WHERE id = ?", (rid,))
        self._db.commit()

    # ------------------------------------------------------------ recherche

    def search(self, query="", category=None, favorites_only=False):
        q = _norm(query or "")
        terms = q.split()
        ingredient_names = {}
        for rid, name in self._db.execute("SELECT recipe_id, name FROM ingredients"):
            ingredient_names.setdefault(rid, []).append(_norm(name))
        results = []
        for rid, title, cat, fav in self._db.execute(
                "SELECT id, title, category, favorite FROM recipes"):
            if category is not None and cat != category:
                continue
            if favorites_only and not fav:
                continue
            if terms:
                texts = [_norm(title)] + ingredient_names.get(rid, [])
                needles = [q] + terms
                if not any(n in text for text in texts for n in needles):
                    continue
            results.append(title)
        results.sort()
        return {"results": results,
                "message": None if results else _NO_MATCH}

    # ------------------------------------------------------------ courses

    def add_to_shopping_list(self, rid, servings=None):
        base = self._recipe_row(rid)[1]
        target = base if servings is None else _check_servings(servings)
        for name, qty, unit in self._ingredient_rows(rid):
            amount = _scale(qty, target, base)
            key = _norm(name)
            hit = self._db.execute(
                "SELECT id, quantity FROM shopping WHERE name_key = ? AND unit = ?",
                (key, unit)).fetchone()
            if hit is not None:
                total = _dec(hit[1]) + amount
                self._db.execute(
                    "UPDATE shopping SET quantity = ?, checked = 0 WHERE id = ?",
                    (float(total), hit[0]))
            else:
                self._db.execute(
                    "INSERT INTO shopping (name, name_key, unit, quantity, checked) "
                    "VALUES (?, ?, ?, ?, 0)", (name, key, unit, float(amount)))
        self._db.commit()

    def shopping_list(self):
        rows = self._db.execute(
            "SELECT name, quantity, unit, checked FROM shopping ORDER BY id").fetchall()
        return [{"name": name, "quantity": _fmt(qty), "unit": unit,
                 "checked": bool(checked)}
                for name, qty, unit, checked in rows]

    def check_item(self, name, unit, checked=True):
        self._db.execute(
            "UPDATE shopping SET checked = ? WHERE name_key = ? AND unit = ?",
            (1 if checked else 0, _norm(name), unit))
        self._db.commit()

    def remove_checked(self):
        self._db.execute("DELETE FROM shopping WHERE checked = 1")
        self._db.commit()
