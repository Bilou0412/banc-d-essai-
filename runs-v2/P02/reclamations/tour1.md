round: 1
author: green
layer: code

test:      test_A01_trou_titre_blanc_refuse
kind:      gap
assertion: Le test exige qu'un titre composé uniquement d'espaces soit refusé et ne crée pas de recette ; la règle A01 ne parle que d'un titre « vide ».
anchor:    A01 : « Avec un titre vide, l'action « enregistrer » ne crée pas la recette » | test_A01_trou_titre_blanc_refuse : `save_recipe("   \t ")` doit lever InvalidInput et `list_recipes()` rester vide.

test:      test_A05_trou_nan_inf_refuses
kind:      gap
assertion: Le test exige que « nan », « inf », « -inf », « NaN » soient refusés comme quantités ; la règle A05 ne dit pas si une chaîne acceptée par une conversion flottante mais non finie est « non numérique ».
anchor:    A05 : « La saisie d'une quantité non numérique est refusée » | test_A05_trou_nan_inf_refuses (quantités « nan », « inf », « -inf », « NaN »).

test:      test_A05_trou_virgule_decimale_acceptee
kind:      gap
assertion: Le test exige que « 1,5 » soit accepté et lu comme 1.5 ; la règle A05 ne dit pas si la virgule décimale est une saisie numérique valide.
anchor:    A05 : « La saisie d'une quantité non numérique est refusée » | test_A05_trou_virgule_decimale_acceptee (`add_ingredient(rid, "beurre", "1,5", ...)` doit donner 1.5).

test:      test_A18_trou_requete_blanche_equivaut_a_vide
kind:      gap
assertion: Le test exige qu'une requête composée uniquement d'espaces soit traitée comme une requête vide (toutes les recettes, pas de message) ; la règle A18 ne parle que de la requête « vide ».
anchor:    A18 : « Une requête vide affiche toutes les recettes dans les résultats » | test_A18_trou_requete_blanche_equivaut_a_vide (`search("   ")`).

test:      test_A19_trou_filtre_sans_resultat_affiche_aucun_resultat
kind:      gap
assertion: Le test exige que le message « Aucun résultat » apparaisse aussi lorsque le filtre « favoris » ne laisse aucune recette ; la règle A19 ne vise que les requêtes sans correspondance.
anchor:    A19 : « Une requête sans correspondance affiche le message « Aucun résultat » » | test_A19_trou_filtre_sans_resultat_affiche_aucun_resultat (`search("", favorites_only=True)` sans favori).

test:      test_A24_trou_note_blanche_retiree
kind:      gap
assertion: Le test exige qu'une note remplacée par des espaces seuls soit retirée de la fiche ; la règle A24 ne traite que l'effacement complet du texte.
anchor:    A24 : « L'effacement du texte d'une note retire la note de la fiche de la recette » | test_A24_trou_note_blanche_retiree (`set_note(rid, "  \n ")`).

test:      test_A26_trou_signature_png_suivie_de_dechets_refusee
kind:      gap
assertion: Le test exige qu'un fichier ayant la signature PNG mais un contenu invalide soit refusé ; la règle A26 ne dit pas ce qui distingue une image d'un fichier qui n'en est pas une.
anchor:    A26 : « L'ajout d'un fichier qui n'est pas une image est refusé » | test_A26_trou_signature_png_suivie_de_dechets_refusee (`set_photo(rid, b"\x89PNG\r\n\x1a\n" + b"ceci n'est pas une image")`).

test:      test_A31_trou_meme_recette_ajoutee_deux_fois_sommee
kind:      gap
assertion: Le test exige que l'ajout deux fois d'une même recette somme les quantités (400 pour 200 g ajoutés deux fois) ; la règle A31 ne parle que de deux recettes distinctes.
anchor:    A31 : « L'ajout de deux recettes contenant le même ingrédient dans la même unité produit une seule ligne avec la somme des quantités » | test_A31_trou_meme_recette_ajoutee_deux_fois_sommee (`add_to_shopping_list(r1)` deux fois, quantité attendue 400).

test:      test_A31_trou_noms_differant_par_la_casse_fusionnes
kind:      gap
assertion: Le test exige que « Farine » et « farine » dans la même unité soient fusionnés en une ligne (500) ; la règle A31 ne dit pas si deux noms qui ne diffèrent que par la casse désignent le même ingrédient.
anchor:    A31 : « ... le même ingrédient dans la même unité ... » | test_A31_trou_noms_differant_par_la_casse_fusionnes (`"Farine"` et `"farine"`, une seule ligne attendue).

test:      test_A31_trou_ligne_cochee_recevant_une_quantite_est_decochee
kind:      gap
assertion: Le test exige qu'une ligne cochée qui reçoit une nouvelle quantité par fusion soit affichée décochée ; ni A31 (somme) ni A33 (cochage affiché) ni A34 (retrait des cochés) ne disent ce qu'il advient de l'état coché lors d'une fusion.
anchor:    A31 : « ... produit une seule ligne avec la somme des quantités » ; A33 : « Le cochage d'un article ... l'affiche comme coché » | test_A31_trou_ligne_cochee_recevant_une_quantite_est_decochee (`check_item("farine", "g")` puis ajout d'une recette, `checked` attendu False).
