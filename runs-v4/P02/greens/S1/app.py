"""Carnet de recettes, persistance JSON sur fichier."""

import base64
import json
import os
import re
import struct
import zlib
from decimal import Decimal, ROUND_HALF_UP


class InvalidInput(ValueError):
    pass


def _png(w, h, rgb):
    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


DEFAULT_PHOTO = _png(2, 2, (200, 200, 200))

_NUM = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")


def _parse_qty(q):
    if isinstance(q, bool):
        raise InvalidInput("quantité invalide")
    s = str(q).strip().replace(",", ".")
    if not _NUM.fullmatch(s):
        raise InvalidInput("quantité non numérique")
    d = Decimal(s)
    if not d.is_finite() or d <= 0:
        raise InvalidInput("quantité négative ou nulle")
    return d


def _parse_servings(s):
    if isinstance(s, bool):
        raise InvalidInput("portions invalides")
    try:
        d = Decimal(str(s).strip())
    except Exception:
        raise InvalidInput("portions invalides")
    if not d.is_finite() or d != d.to_integral_value() or d < 1:
        raise InvalidInput("portions invalides")
    return int(d)


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(d):
    s = format(_round2(d), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _png_ok(b):
    if not b.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    pos, first, end = 8, True, False
    while pos < len(b):
        if end or pos + 12 > len(b):
            return False
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        t = b[pos + 4:pos + 8]
        if pos + 12 + n > len(b):
            return False
        data = b[pos + 8:pos + 8 + n]
        crc = struct.unpack(">I", b[pos + 8 + n:pos + 12 + n])[0]
        if zlib.crc32(t + data) & 0xFFFFFFFF != crc:
            return False
        if first and t != b"IHDR":
            return False
        first = False
        if t == b"IEND":
            end = True
        pos += 12 + n
    return end


def _is_image(b):
    if not isinstance(b, (bytes, bytearray)):
        return False
    b = bytes(b)
    if b.startswith(b"\x89PNG"):
        return _png_ok(b)
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return len(b) >= 14 and b.endswith(b";")
    if b.startswith(b"\xff\xd8\xff"):
        return len(b) >= 6 and b.endswith(b"\xff\xd9")
    return False


def _words(s):
    return re.findall(r"\w+", s.casefold())


class App:
    def __init__(self, path):
        self.path = os.fspath(path)

    # --- stockage
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {"next_id": 1, "recipes": [], "shopping": []}

    def _save(self, st):
        tmp = self.path + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def close(self):
        pass

    @staticmethod
    def _find(st, rid):
        for r in st["recipes"]:
            if r["id"] == rid:
                return r
        raise KeyError(rid)

    # --- recettes
    def save_recipe(self, title, servings=4):
        if not isinstance(title, str) or not title.strip():
            raise InvalidInput("titre vide")
        sv = _parse_servings(servings)
        st = self._load()
        rid = st["next_id"]
        st["next_id"] = rid + 1
        st["recipes"].append({"id": rid, "title": title.strip(), "servings": sv,
                              "category": None, "favorite": False, "note": None,
                              "photo": None, "ingredients": []})
        self._save(st)
        return rid

    def delete_recipe(self, rid):
        st = self._load()
        st["recipes"] = [r for r in st["recipes"] if r["id"] != rid]
        self._save(st)

    def list_recipes(self):
        return [{"id": r["id"], "title": r["title"]} for r in self._load()["recipes"]]

    def _adjusted(self, r, servings):
        if servings is None:
            target = r["servings"]
        else:
            target = _parse_servings(servings)
        out = []
        for i in r["ingredients"]:
            q = Decimal(i["quantity"]) * target / r["servings"]
            out.append({"name": i["name"], "quantity": _fmt(q), "unit": i["unit"]})
        return target, out

    def recipe(self, rid, servings=None):
        r = self._find(self._load(), rid)
        target, ings = self._adjusted(r, servings)
        photo = DEFAULT_PHOTO if r["photo"] is None else base64.b64decode(r["photo"])
        return {"title": r["title"], "servings": target, "category": r["category"],
                "favorite": r["favorite"], "note": r["note"], "photo": photo,
                "ingredients": ings}

    def add_ingredient(self, rid, name, quantity, unit):
        q = _parse_qty(quantity)
        st = self._load()
        r = self._find(st, rid)
        r["ingredients"].append({"name": name, "quantity": str(q), "unit": unit})
        self._save(st)

    def remove_ingredient(self, rid, name):
        st = self._load()
        r = self._find(st, rid)
        r["ingredients"] = [i for i in r["ingredients"] if i["name"] != name]
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
        if not _is_image(data):
            raise InvalidInput("ce n'est pas une image")
        self._set(rid, "photo", base64.b64encode(bytes(data)).decode("ascii"))

    def remove_photo(self, rid):
        self._set(rid, "photo", None)

    # --- recherche
    def search(self, query="", category=None, favorites_only=False):
        st = self._load()
        qw = _words(query or "")
        qtext = " " + " ".join(qw) + " "
        res = []
        for r in st["recipes"]:
            if category is not None and r["category"] != category:
                continue
            if favorites_only and not r["favorite"]:
                continue
            if qw:
                hit = bool(set(_words(r["title"])) & set(qw))
                if not hit:
                    for i in r["ingredients"]:
                        nw = _words(i["name"])
                        if nw and " " + " ".join(nw) + " " in qtext:
                            hit = True
                            break
                if not hit:
                    continue
            res.append(r["title"])
        return {"results": res, "message": None if res else "Aucun résultat"}

    # --- courses
    def add_to_shopping_list(self, rid, servings=None):
        st = self._load()
        r = self._find(st, rid)
        _, ings = self._adjusted(r, servings)
        for i in ings:
            q = Decimal(i["quantity"])
            key = i["name"].casefold()
            for line in st["shopping"]:
                if line["name"].casefold() == key and line["unit"] == i["unit"]:
                    line["quantity"] = str(Decimal(line["quantity"]) + q)
                    line["checked"] = False
                    break
            else:
                st["shopping"].append({"name": i["name"], "quantity": str(q),
                                       "unit": i["unit"], "checked": False})
        self._save(st)

    def shopping_list(self):
        return [{"name": l["name"], "quantity": _fmt(Decimal(l["quantity"])),
                 "unit": l["unit"], "checked": l["checked"]}
                for l in self._load()["shopping"]]

    def check_item(self, name, unit, checked=True):
        st = self._load()
        for l in st["shopping"]:
            if l["name"].casefold() == name.casefold() and l["unit"] == unit:
                l["checked"] = bool(checked)
        self._save(st)

    def remove_checked(self):
        st = self._load()
        st["shopping"] = [l for l in st["shopping"] if not l["checked"]]
        self._save(st)
