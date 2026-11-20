"""Carnet de recettes -- module unique.

Persistance : un fichier JSON, relu a chaque operation et reecrit atomiquement
a chaque modification. Rien n'est garde en memoire entre deux appels : deux
instances ouvertes sur le meme fichier se voient mutuellement.
"""

import base64
import json
import os
import re
import struct
import unicodedata
import zlib
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


DEFAULT_SERVINGS = 4
NO_RESULT = "Aucun résultat"
_CENT = Decimal("0.01")
_NUMBER = re.compile(r"[0-9]+(\.[0-9]*)?|\.[0-9]+")
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


class InvalidInput(ValueError):
    """Saisie refusee."""


def _png_bytes(gray):
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = bytes([0, gray, gray, gray])
    return (_PNG_SIG + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


DEFAULT_PHOTO = _png_bytes(0x80)


# ----------------------------------------------------------------- images

def _is_png(data):
    if not data.startswith(_PNG_SIG):
        return False
    pos = len(_PNG_SIG)
    kinds = []
    while True:
        if pos + 12 > len(data):
            return False
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body_end = pos + 8 + length
        if body_end + 4 > len(data):
            return False
        body = data[pos + 8:body_end]
        (crc,) = struct.unpack(">I", data[body_end:body_end + 4])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            return False
        kinds.append(kind)
        pos = body_end + 4
        if kind == b"IEND":
            break
    return pos == len(data) and kinds[0] == b"IHDR" and b"IDAT" in kinds


def _skip_blocks(data, pos):
    """Saute une suite de sous-blocs GIF ; renvoie la position suivante ou None."""
    while True:
        if pos >= len(data):
            return None
        size = data[pos]
        pos += 1
        if size == 0:
            return pos
        pos += size
        if pos > len(data):
            return None


def _is_gif(data):
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return False
    pos = 13
    if data[10] & 0x80:
        pos += 3 * 2 ** ((data[10] & 0x07) + 1)
    while pos < len(data):
        block = data[pos]
        if block == 0x3B:
            return pos == len(data) - 1
        if block == 0x21:
            pos = _skip_blocks(data, pos + 2)
        elif block == 0x2C:
            if pos + 10 > len(data):
                return False
            flags = data[pos + 9]
            pos += 10
            if flags & 0x80:
                pos += 3 * 2 ** ((flags & 0x07) + 1)
            pos = _skip_blocks(data, pos + 1)
        else:
            return False
        if pos is None:
            return False
    return False


# ----------------------------------------------------------------- validation

def _text(value, what):
    if not isinstance(value, str):
        raise InvalidInput(f"{what} : texte attendu")
    return value.strip()


def _check_servings(n):
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise InvalidInput(f"nombre de portions invalide : {n!r}")
    return n


def _parse_quantity(value):
    if isinstance(value, bool):
        raise InvalidInput("quantite invalide")
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not _NUMBER.fullmatch(text):
            raise InvalidInput(f"quantite non numerique : {value!r}")
    elif isinstance(value, (int, float)):
        text = repr(value)
    else:
        raise InvalidInput("quantite invalide")
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise InvalidInput(f"quantite invalide : {value!r}")
    if not d.is_finite() or d <= 0:
        raise InvalidInput(f"quantite negative ou nulle : {value!r}")
    return d


# ----------------------------------------------------------------- calculs

def _scale(quantity, new, base):
    return quantity * Decimal(new) / Decimal(base)


def _fmt(d):
    """Affichage : arrondi a deux decimales (demi vers le haut), zeros inutiles retires."""
    s = format(d.quantize(_CENT, rounding=ROUND_HALF_UP), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _tokens(text):
    return set(re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold()))


def _photo_of(r):
    if r["photo"] is None:
        return DEFAULT_PHOTO
    return base64.b64decode(r["photo"])


def _resolve_servings(r, servings):
    if servings is None:
        return r["servings"]
    return _check_servings(servings)


def _add_line(shopping, name, unit, quantity):
    key = (name.casefold(), unit)
    for line in shopping:
        if (line["name"].casefold(), line["unit"]) == key:
            line["quantity"] = str(Decimal(line["quantity"]) + quantity)
            line["checked"] = False
            return
    shopping.append({"name": name, "unit": unit, "quantity": str(quantity), "checked": False})


def _find_line(shopping, name, unit):
    key = (name.casefold(), unit)
    for line in shopping:
        if (line["name"].casefold(), line["unit"]) == key:
            return line
    raise KeyError((name, unit))


def _empty():
    return {"next_id": 1, "recipes": [], "shopping": []}


# ----------------------------------------------------------------- application

class App:
    def __init__(self, path):
        self._path = os.fspath(path)

    def close(self):
        pass

    # persistance ------------------------------------------------------

    def _load(self):
        if not os.path.exists(self._path):
            return _empty()
        with open(self._path, encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            return _empty()
        return json.loads(text)

    def _save(self, state):
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, self._path)

    @staticmethod
    def _recipe(state, rid):
        for r in state["recipes"]:
            if r["id"] == rid:
                return r
        raise KeyError(rid)

    # recettes ---------------------------------------------------------

    def save_recipe(self, title, servings=DEFAULT_SERVINGS):
        title = _text(title, "titre")
        if not title:
            raise InvalidInput("titre vide")
        servings = _check_servings(servings)
        state = self._load()
        rid = state["next_id"]
        state["next_id"] = rid + 1
        state["recipes"].append({
            "id": rid, "title": title, "servings": servings, "category": None,
            "favorite": False, "note": None, "photo": None, "ingredients": [],
        })
        self._save(state)
        return rid

    def delete_recipe(self, rid):
        state = self._load()
        state["recipes"].remove(self._recipe(state, rid))
        self._save(state)

    def list_recipes(self):
        return [{"id": r["id"], "title": r["title"]} for r in self._load()["recipes"]]

    def recipe(self, rid, servings=None):
        r = self._recipe(self._load(), rid)
        new = _resolve_servings(r, servings)
        base = r["servings"]
        return {
            "title": r["title"],
            "servings": new,
            "category": r["category"],
            "favorite": r["favorite"],
            "note": r["note"],
            "photo": _photo_of(r),
            "ingredients": [
                {"name": i["name"],
                 "quantity": _fmt(_scale(Decimal(i["quantity"]), new, base)),
                 "unit": i["unit"]}
                for i in r["ingredients"]
            ],
        }

    # ingredients ------------------------------------------------------

    def add_ingredient(self, rid, name, quantity, unit):
        name = _text(name, "ingredient")
        if not name:
            raise InvalidInput("ingredient sans nom")
        unit = _text(unit, "unite")
        qty = _parse_quantity(quantity)
        state = self._load()
        r = self._recipe(state, rid)
        r["ingredients"] = [i for i in r["ingredients"] if i["name"] != name]
        r["ingredients"].append({"name": name, "quantity": str(qty), "unit": unit})
        self._save(state)

    def remove_ingredient(self, rid, name):
        state = self._load()
        r = self._recipe(state, rid)
        r["ingredients"] = [i for i in r["ingredients"] if i["name"] != name]
        self._save(state)

    # attributs --------------------------------------------------------

    def set_category(self, rid, category):
        category = _text(category, "categorie") or None
        state = self._load()
        self._recipe(state, rid)["category"] = category
        self._save(state)

    def set_favorite(self, rid, value):
        state = self._load()
        self._recipe(state, rid)["favorite"] = bool(value)
        self._save(state)

    def set_note(self, rid, text):
        if text is not None and not isinstance(text, str):
            raise InvalidInput("note : texte attendu")
        note = None if text is None or text.strip() == "" else text
        state = self._load()
        self._recipe(state, rid)["note"] = note
        self._save(state)

    def set_photo(self, rid, data):
        if not isinstance(data, (bytes, bytearray)):
            raise InvalidInput("photo : octets attendus")
        data = bytes(data)
        if not (_is_png(data) or _is_gif(data)):
            raise InvalidInput("le fichier n'est pas une image acceptee")
        state = self._load()
        self._recipe(state, rid)["photo"] = base64.b64encode(data).decode("ascii")
        self._save(state)

    def remove_photo(self, rid):
        state = self._load()
        self._recipe(state, rid)["photo"] = None
        self._save(state)

    # recherche --------------------------------------------------------

    def search(self, query="", category=None, favorites_only=False):
        q_tokens = _tokens(query or "")
        results = []
        for r in self._load()["recipes"]:
            if q_tokens:
                words = _tokens(r["title"])
                for i in r["ingredients"]:
                    words |= _tokens(i["name"])
                if not (q_tokens & words):
                    continue
            if category is not None and r["category"] != category:
                continue
            if favorites_only and not r["favorite"]:
                continue
            results.append(r["title"])
        return {"results": results, "message": None if results else NO_RESULT}

    # liste de courses -------------------------------------------------

    def add_to_shopping_list(self, rid, servings=None):
        state = self._load()
        r = self._recipe(state, rid)
        new = _resolve_servings(r, servings)
        base = r["servings"]
        for i in r["ingredients"]:
            _add_line(state["shopping"], i["name"], i["unit"],
                      _scale(Decimal(i["quantity"]), new, base))
        self._save(state)

    def shopping_list(self):
        return [
            {"name": line["name"],
             "quantity": _fmt(Decimal(line["quantity"])),
             "unit": line["unit"],
             "checked": line["checked"]}
            for line in self._load()["shopping"]
        ]

    def check_item(self, name, unit, checked=True):
        state = self._load()
        _find_line(state["shopping"], name, unit)["checked"] = bool(checked)
        self._save(state)

    def remove_checked(self):
        state = self._load()
        state["shopping"] = [line for line in state["shopping"] if not line["checked"]]
        self._save(state)
