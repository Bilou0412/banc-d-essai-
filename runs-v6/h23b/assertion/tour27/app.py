import json
import os
from typing import Any, Dict, List
import unicodedata
import io
DEFAULT_PHOTO = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\xdac\xf8\xff?\x00\x01\x01\xfe\x00\x00\x00\x00IEND\xaeB`\x82'

class InvalidInput(ValueError):
    pass
    pass
    pass
    pass
    pass
    pass
    pass
    pass
    pass
    pass
    pass
    pass
    pass
    pass

class App:

    def __init__(self, path: str):
        self.path = path
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump([], f)

    def close(self) -> None:
        pass

    def save_recipe(self, title: str, servings: int=4) -> int:
        if not title.strip():
            raise InvalidInput('Le titre ne peut pas être vide')
        if not isinstance(servings, (int, float)) or servings <= 0:
            raise InvalidInput('Le nombre de portions doit être un nombre positif')
        with open(self.path, 'r+') as f:
            data = json.load(f)
            rid = len(data) + 1
            recipe = {'id': rid, 'title': title, 'servings': servings, 'category': None, 'favorite': False, 'note': None, 'photo': DEFAULT_PHOTO.decode('latin-1'), 'ingredients': []}
            data.append(recipe)
            f.seek(0)
            json.dump(data, f)
            return rid

    def delete_recipe(self, rid: int) -> None:
        with open(self.path, 'r+') as f:
            data = json.load(f)
            data = [r for r in data if r['id'] != rid]
            f.seek(0)
            json.dump(data, f)

    def list_recipes(self) -> List[Dict[str, Any]]:
        with open(self.path, 'r') as f:
            return json.load(f)

    def recipe(self, rid: int, servings: int=None) -> Dict[str, Any]:
        recipes = self.list_recipes()
        recipe = next((r for r in recipes if r['id'] == rid), None)
        if not recipe:
            raise ValueError('Recette non trouvée')
        if servings is not None:
            recipe['servings'] = servings
            for i in recipe['ingredients']:
                i['quantity'] = str(round(qty(i['quantity']) / servings, 2))
        return recipe

    def add_ingredient(self, rid: int, name: str, quantity: Any, unit: str) -> None:
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            raise InvalidInput('La quantité doit être un nombre positif')
        recipe = self.recipe(rid)
        recipe['ingredients'].append({'name': name, 'quantity': str(quantity), 'unit': unit})

    def remove_ingredient(self, rid: int, name: str) -> None:
        recipe = self.recipe(rid)
        recipe['ingredients'] = [i for i in recipe['ingredients'] if i['name'] != name]

    def set_category(self, rid: int, category: str) -> None:
        recipe = self.recipe(rid)
        recipe['category'] = category

    def set_favorite(self, rid: int, bool: bool) -> None:
        recipe = self.recipe(rid)
        recipe['favorite'] = bool

    def set_note(self, rid: int, text: str) -> None:
        recipe = self.recipe(rid)
        recipe['note'] = text

    def set_photo(self, rid: int, data: bytes) -> None:
        recipe = self.recipe(rid)
        if not (data.startswith(b'\x89PNG') or data.startswith(b'GIF89a')):
            raise InvalidInput("Le fichier n'est pas une image")
        recipe['photo'] = data

    def remove_photo(self, rid: int) -> None:
        recipe = self.recipe(rid)
        recipe['photo'] = DEFAULT_PHOTO.decode('latin-1')

    def search(self, query: str='', category: str=None, favorites_only: bool=False) -> Dict[str, Any]:
        recipes = self.list_recipes()
        normalized_query = unicodedata.normalize('NFD', query.strip().lower())
        results = [r for r in recipes if (not normalized_query or normalized_query in unicodedata.normalize('NFD', r['title'].lower())) and (category is None or r.get('category') == category) and (not favorites_only or r['favorite'])]
        message = 'Aucun résultat' if not results else None
        return {'results': sorted((r['title'] for r in results)), 'message': message}

    def add_to_shopping_list(self, rid: int, servings: int=None) -> None:
        recipe = self.recipe(rid)
        if servings is not None:
            recipe['servings'] = servings
        for i in recipe['ingredients']:
            item = (i['name'], i['unit'])
            if item in shop(self):
                shop(self)[item]['quantity'] = str(round(qty(shop(self)[item]['quantity']) + qty(i['quantity']), 2))
            else:
                shop(self)[item] = {'name': i['name'], 'quantity': i['quantity'], 'unit': i['unit'], 'checked': False}

    def shopping_list(self) -> List[Dict[str, Any]]:
        return list(shop(self).values())

    def check_item(self, name: str, unit: str, checked: bool=True) -> None:
        item = (name, unit)
        if item in shop(self):
            shop(self)[item]['checked'] = checked

    def remove_checked(self) -> None:
        for item in [i for i in shop(self) if shop(self)[i]['checked']]:
            del shop(self)[item]

def is_valid_quantity(quantity: Any) -> bool:
    return isinstance(quantity, (int, float)) and quantity > 0

def search(self, query: str='', category: str=None, favorites_only: bool=False) -> Dict[str, Any]:
    recipes = self.list_recipes()
    normalized_query = unicodedata.normalize('NFD', query.strip().lower())
    results = [r for r in recipes if (not normalized_query or normalized_query in unicodedata.normalize('NFD', r['title'].lower())) and (category is None or r.get('category') == category) and (not favorites_only or r['favorite'])]
    return {'results': sorted((r['title'] for r in results)), 'message': None}

def set_photo(self, rid: int, data: bytes) -> None:
    recipe = self.recipe(rid)
    if not (data.startswith(b'\x89PNG') or data.startswith(b'GIF89a')):
        raise InvalidInput("Le fichier n'est pas une image")
    recipe['photo'] = data
