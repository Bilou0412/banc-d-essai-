import json
import os
DEFAULT_PHOTO = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\xdac\xf8\xff?\x00\x01\x01\xfe\x00\x00\x00\x00IEND\xaeB`\x82'

class InvalidInput(ValueError):
    pass
    pass
    pass

class App:

    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump([], f)

    def close(self):
        pass

    def save_recipe(self, title, servings=4):
        if not title.strip():
            raise InvalidInput('Le titre ne peut pas être vide')
        with open(self.path, 'r+') as f:
            data = json.load(f)
            rid = len(data) + 1
            recipe = {'id': rid, 'title': title, 'servings': servings, 'category': None, 'favorite': False, 'note': None, 'photo': DEFAULT_PHOTO, 'ingredients': []}
            data.append(recipe)
            f.seek(0)
            json.dump(data, f)
            return rid

    def delete_recipe(self, rid):
        with open(self.path, 'r+') as f:
            data = json.load(f)
            data = [r for r in data if r['id'] != rid]
            f.seek(0)
            json.dump(data, f)

    def list_recipes(self):
        with open(self.path, 'r') as f:
            return json.load(f)

    def recipe(self, rid, servings=None):
        recipes = self.list_recipes()
        recipe = next((r for r in recipes if r['id'] == rid), None)
        if not recipe:
            raise ValueError('Recette non trouvée')
        if servings is not None:
            recipe['servings'] = servings
        return recipe

    def add_ingredient(self, rid, name, quantity, unit):
        recipe = self.recipe(rid)
        recipe['ingredients'].append({'name': name, 'quantity': str(quantity), 'unit': unit})

    def remove_ingredient(self, rid, name):
        recipe = self.recipe(rid)
        recipe['ingredients'] = [i for i in recipe['ingredients'] if i['name'] != name]

    def set_category(self, rid, category):
        recipe = self.recipe(rid)
        recipe['category'] = category

    def set_favorite(self, rid, bool):
        recipe = self.recipe(rid)
        recipe['favorite'] = bool

    def set_note(self, rid, text):
        recipe = self.recipe(rid)
        recipe['note'] = text

    def set_photo(self, rid, data: bytes):
        recipe = self.recipe(rid)
        recipe['photo'] = DEFAULT_PHOTO

    def remove_photo(self, rid):
        recipe = self.recipe(rid)
        recipe['photo'] = DEFAULT_PHOTO

    def search(self, query='', category=None, favorites_only=False):
        recipes = self.list_recipes()
        results = [r for r in recipes if (not query or query.lower() in r['title'].lower()) and (category is None or r.get('category') == category) and (not favorites_only or r['favorite'])]
        return {'results': sorted((r['title'] for r in results)), 'message': None}

    def add_to_shopping_list(self, rid, servings=None):
        recipe = self.recipe(rid)
        if servings is not None:
            recipe['servings'] = servings
        for i in recipe['ingredients']:
            item = (i['name'], i['unit'])
            if item in shop(self):
                shop(self)[item]['quantity'] = str(qty(shop(self)[item]['quantity']) + qty(i['quantity']))
            else:
                shop(self)[item] = {'name': i['name'], 'quantity': i['quantity'], 'unit': i['unit'], 'checked': False}

    def shopping_list(self):
        return list(shop(self).values())

    def check_item(self, name, unit, checked=True):
        item = (name, unit)
        if item in shop(self):
            shop(self)[item]['checked'] = checked

    def remove_checked(self):
        for item in [i for i in shop(self) if shop(self)[i]['checked']]:
            del shop(self)[item]
