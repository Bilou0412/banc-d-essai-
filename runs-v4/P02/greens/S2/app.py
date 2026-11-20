"""Carnet de recettes : persistance JSON dans un fichier, relu a chaque operation."""

import base64
import json
import os
import re
import struct
import zlib
from decimal import Decimal, ROUND_HALF_UP, localcontext


class InvalidInput(ValueError):
    pass


def _png_bytes(rgb):
    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgb)))
            + chunk(b"IEND", b""))


DEFAULT_PHOTO = _png_bytes((200, 200, 200))

_NUM = re.compile(r"(\d+(\.\d*)?|\.\d+)")
_WORD = re.compile(r"\w+")


def _valid_png(d):
    if not d.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    pos = 8
    first = True
    while pos + 12 <= len(d):
        (n,) = struct.unpack(">I", d[pos:pos + 4])
        t = d[pos + 4:pos + 8]
        body = d[pos + 8:pos + 8 + n]
        crc = d[pos + 8 + n:pos + 12 + n]
        if len(body) != n or len(crc) != 4:
            return False
        if struct.unpack(">I", crc)[0] != zlib.crc32(t + body) & 0xFFFFFFFF:
            return False
        if first:
            if t != b"IHDR" or n != 13:
                return False
            first = False
        pos += 12 + n
        if t == b"IEND":
            return pos == len(d)
    return False


def _valid_gif(d):
    if not (d[:6] in (b"GIF87a", b"GIF89a") and len(d) >= 14 and d.endswith(b";")):
        return False
    w, h = struct.unpack("<HH", d[6:10])
    return w > 0 and h > 0


def _valid_jpeg(d):
    return len(d) >= 4 and d.startswith(b"\xff\xd8\xff") and d.endswith(b"\xff\xd9")


def _valid_image(d):
    return isinstance(d, (bytes, bytearray)) and (
        _valid_png(bytes(d)) or _valid_gif(bytes(d)) or _valid_jpeg(bytes(d)))


def _parse_qty(v):
    if isinstance(v, bool):
        raise InvalidInput("quantite invalide")
    if isinstance(v, (int, float, Decimal)):
        try:
            d = Decimal(str(v))
        except Exception:
            raise InvalidInput("quantite invalide")
    elif isinstance(v, str):
        s = v.strip().replace(",", ".")
        if not _NUM.fullmatch(s):
            raise InvalidInput("quantite non numerique")
        d = Decimal(s)
    else:
        raise InvalidInput("quantite invalide")
    if not d.is_finite() or d <= 0:
        raise InvalidInput("quantite negative ou nulle")
    return d


def _parse_servings(v):
    if isinstance(v, bool):
        raise InvalidInput("portions invalides")
    if isinstance(v, float):
        if not v.is_integer():
            raise InvalidInput("portions invalides")
        v = int(v)
    elif isinstance(v, str):
        s = v.strip()
        if not re.fullmatch(r"-?\d+", s):
            raise InvalidInput("portions invalides")
        v = int(s)
    elif not isinstance(v, int):
        raise InvalidInput("portions invalides")
    if v < 1:
        raise InvalidInput("portions inferieures a 1")
    return v


def _fmt(d):
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(d.normalize(), "f")


def _scaled(qstr, base, target):
    with localcontext() as ctx:
        ctx.prec = 60
        d = Decimal(qstr) * target / base
        return _fmt(d)


def _tokens(s):
    return _WORD.findall(s.casefold())


class App:
    def __init__(self, path):
        self._path = os.fspath(path)
        self._closed = False

    # ------------------------------------------------------------ stockage
    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"next_id": 1, "recipes": [], "shopping": []}

    def _save(self, st):
        tmp = self._path + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    @staticmethod
    def _find(st, rid):
        for r in st["recipes"]:
            if r["id"] == rid:
                return r
        raise KeyError(rid)

    def close(self):
        self._closed = True

    # ------------------------------------------------------------ recettes
    def save_recipe(self, title, servings=4):
        if not isinstance(title, str) or not title.strip():
            raise InvalidInput("titre vide")
        servings = _parse_servings(servings)
        st = self._load()
        rid = st["next_id"]
        st["next_id"] = rid + 1
        st["recipes"].append({
            "id": rid, "title": title, "servings": servings, "category": None,
            "favorite": False, "note": None, "photo": None, "ingredients": []})
        self._save(st)
        return rid

    def delete_recipe(self, rid):
        st = self._load()
        st["recipes"] = [r for r in st["recipes"] if r["id"] != rid]
        self._save(st)

    def list_recipes(self):
        return [{"id": r["id"], "title": r["title"]} for r in self._load()["recipes"]]

    def recipe(self, rid, servings=None):
        st = self._load()
        r = self._find(st, rid)
        if servings is None:
            target = r["servings"]
        else:
            target = _parse_servings(servings)
        photo = DEFAULT_PHOTO if r["photo"] is None else base64.b64decode(r["photo"])
        return {
            "title": r["title"], "servings": target, "category": r["category"],
            "favorite": r["favorite"], "note": r["note"], "photo": photo,
            "ingredients": [
                {"name": i["name"], "unit": i["unit"],
                 "quantity": _scaled(i["quantity"], r["servings"], target)}
                for i in r["ingredients"]],
        }

    def add_ingredient(self, rid, name, quantity, unit):
        q = _parse_qty(quantity)
        st = self._load()
        r = self._find(st, rid)
        r["ingredients"].append({"name": name, "quantity": str(q), "unit": unit})
        self._save(st)

    def remove_ingredient(self, rid, name):
        st = self._load()
        r = self._find(st, rid)
        r["ingredients"] = [i for i in r["ingredients"]
                            if i["name"].casefold() != name.casefold()]
        self._save(st)

    def _set(self, rid, key, value):
        st = self._load()
        self._find(st, rid)[key] = value
        self._save(st)

    def set_category(self, rid, category):
        self._set(rid, "category", category)

    def set_favorite(self, rid, value):
        self._set(rid, "favorite", bool(value))

    def set_note(self, rid, text):
        if text is None or not text.strip():
            text = None
        self._set(rid, "note", text)

    def set_photo(self, rid, data):
        if not _valid_image(data):
            raise InvalidInput("ce n'est pas une image")
        self._set(rid, "photo", base64.b64encode(bytes(data)).decode("ascii"))

    def remove_photo(self, rid):
        self._set(rid, "photo", None)

    # ------------------------------------------------------------ recherche
    def search(self, query="", category=None, favorites_only=False):
        st = self._load()
        qt = _tokens(query or "")
        out = []
        for r in st["recipes"]:
            if category is not None and r["category"] != category:
                continue
            if favorites_only and not r["favorite"]:
                continue
            if qt:
                title_words = set(_tokens(r["title"]))
                ok = any(w in title_words for w in qt)
                if not ok:
                    for i in r["ingredients"]:
                        it = _tokens(i["name"])
                        n = len(it)
                        if n and any(qt[k:k + n] == it for k in range(len(qt) - n + 1)):
                            ok = True
                            break
                if not ok:
                    continue
            out.append(r["title"])
        return {"results": out, "message": None if out else "Aucun résultat"}

    # ------------------------------------------------------------ courses
    def add_to_shopping_list(self, rid, servings=None):
        st = self._load()
        r = self._find(st, rid)
        target = r["servings"] if servings is None else _parse_servings(servings)
        for i in r["ingredients"]:
            q = Decimal(_scaled(i["quantity"], r["servings"], target))
            key = i["name"].casefold()
            for line in st["shopping"]:
                if line["name"].casefold() == key and line["unit"] == i["unit"]:
                    line["quantity"] = str(Decimal(line["quantity"]) + q)
                    line["checked"] = False
                    break
            else:
                st["shopping"].append({"name": i["name"], "unit": i["unit"],
                                       "quantity": str(q), "checked": False})
        self._save(st)

    def shopping_list(self):
        return [{"name": l["name"], "unit": l["unit"],
                 "quantity": _fmt(Decimal(l["quantity"])), "checked": l["checked"]}
                for l in self._load()["shopping"]]

    def check_item(self, name, unit, checked=True):
        st = self._load()
        for line in st["shopping"]:
            if line["name"].casefold() == name.casefold() and line["unit"] == unit:
                line["checked"] = bool(checked)
        self._save(st)

    def remove_checked(self):
        st = self._load()
        st["shopping"] = [l for l in st["shopping"] if not l["checked"]]
        self._save(st)
