test:      test_A01_trou_titre_blanc_refuse
kind:      gap
assertion: Le test exige qu'un titre compose uniquement d'espaces soit refuse et ne cree pas de recette ; la regle A01 ne parle que d'un titre « vide ».
anchor:    A01 : « Avec un titre vide, l'action « enregistrer » ne cree pas la recette » | test_A01_trou_titre_blanc_refuse (`save_recipe("   \t ")`).

test:      test_A05_trou_nan_inf_refuses
kind:      gap
assertion: Le test exige que « nan », « inf », « -inf », « NaN » soient refuses comme quantites ; la regle A05 ne dit pas si une chaine convertible en flottant non fini est « non numerique ».
anchor:    A05 : « La saisie d'une quantite non numerique est refusee » | test_A05_trou_nan_inf_refuses.

test:      test_A05_trou_virgule_decimale_acceptee
kind:      gap
assertion: Le test exige que « 1,5 » soit accepte et lu comme 1.5 ; la regle A05 ne dit pas si la virgule decimale est une saisie numerique valide.
anchor:    A05 : « La saisie d'une quantite non numerique est refusee » | test_A05_trou_virgule_decimale_acceptee (`add_ingredient(rid, "beurre", "1,5", ...)`).

test:      test_A09_trou_arrondi_demi_superieur
kind:      gap
assertion: Le test exige un arrondi demi-vers-le-haut sur la valeur decimale exacte (0.625 -> 0.63, 1.005 -> 1.01, 2.675 -> 2.68) ; la regle A09 dit « arrondie a deux decimales » sans preciser le traitement de la moitie.
anchor:    A09 : « Une quantite ajustee non entiere s'affiche arrondie a deux decimales » | test_A09_trou_arrondi_demi_superieur.

test:      test_A09_trou_quantite_ajustee_dans_la_liste_de_courses_arrondie
kind:      gap
assertion: Le test exige que la liste de courses affiche elle aussi la quantite ajustee arrondie a deux decimales (« 1.33 ») ; la regle A09 ne vise que la quantite affichee de la fiche.
anchor:    A09 : « ... quantite ajustee ... s'affiche arrondie a deux decimales » | test_A09_trou_quantite_ajustee_dans_la_liste_de_courses_arrondie (`add_to_shopping_list(rid, servings=4)`).

test:      test_A18_trou_requete_blanche_equivaut_a_vide
kind:      gap
assertion: Le test exige qu'une requete composee uniquement d'espaces soit traitee comme une requete vide (toutes les recettes, pas de message) ; la regle A18 ne parle que de la requete « vide ».
anchor:    A18 : « Une requete vide affiche toutes les recettes dans les resultats » | test_A18_trou_requete_blanche_equivaut_a_vide (`search("   ")`).

test:      test_A19_trou_filtre_sans_resultat_affiche_aucun_resultat
kind:      gap
assertion: Le test exige que le message « Aucun resultat » apparaisse aussi quand le filtre « favoris » ne laisse aucune recette ; la regle A19 ne vise que les requetes sans correspondance.
anchor:    A19 : « Une requete sans correspondance affiche le message « Aucun resultat » » | test_A19_trou_filtre_sans_resultat_affiche_aucun_resultat (`search("", favorites_only=True)`).

test:      test_A24_trou_note_blanche_retiree
kind:      gap
assertion: Le test exige qu'une note remplacee par des espaces seuls soit retiree de la fiche ; la regle A24 ne traite que l'effacement complet du texte.
anchor:    A24 : « L'effacement du texte d'une note retire la note de la fiche de la recette » | test_A24_trou_note_blanche_retiree (`set_note(rid, "  \n ")`).

test:      test_A26_trou_signature_png_suivie_de_dechets_refusee
kind:      gap
assertion: Le test exige qu'un fichier portant la signature PNG mais au contenu invalide soit refuse ; la regle A26 ne definit pas ce qui distingue une image d'un fichier qui n'en est pas une.
anchor:    A26 : « L'ajout d'un fichier qui n'est pas une image est refuse » | test_A26_trou_signature_png_suivie_de_dechets_refusee.

test:      test_A34_article_retire_puis_rajoute_repart_non_coche
kind:      gap
assertion: Le test exige qu'un article retire par « retirer les coches » puis rajoute reparte decoche avec la seule quantite de la nouvelle ajout ; aucune regle ne dit ce qu'il advient d'un article retire puis rajoute.
anchor:    A34 : « L'action « retirer les articles coches » fait disparaitre ... » | test_A34_article_retire_puis_rajoute_repart_non_coche.

test:      test_A31_trou_meme_recette_ajoutee_deux_fois_sommee
kind:      gap
assertion: Le test exige que l'ajout deux fois de la meme recette somme les quantites (400 pour 200 g ajoutes deux fois) ; la regle A31 ne parle que de deux recettes distinctes.
anchor:    A31 : « L'ajout de deux recettes contenant le meme ingredient dans la meme unite produit une seule ligne avec la somme des quantites » | test_A31_trou_meme_recette_ajoutee_deux_fois_sommee.

test:      test_A31_trou_noms_differant_par_la_casse_fusionnes
kind:      gap
assertion: Le test exige que « Farine » et « farine » dans la meme unite soient fusionnes en une ligne (500) ; la regle A31 ne dit pas si deux noms ne differant que par la casse designent le meme ingredient.
anchor:    A31 : « ... le meme ingredient dans la meme unite ... » | test_A31_trou_noms_differant_par_la_casse_fusionnes.

test:      test_A31_trou_ligne_cochee_recevant_une_quantite_est_decochee
kind:      gap
assertion: Le test exige qu'une ligne cochee qui recoit une quantite par fusion soit affichee decochee ; ni A31 (somme) ni A33 (cochage) ni A34 (retrait des coches) ne disent ce qu'il advient de l'etat coche lors d'une fusion.
anchor:    A31 : « ... produit une seule ligne avec la somme des quantites » ; A33 : « Le cochage d'un article ... l'affiche comme coche » | test_A31_trou_ligne_cochee_recevant_une_quantite_est_decochee.

test:      test_A35_identifiant_non_recycle_apres_suppression
kind:      gap
assertion: Le test exige qu'un identifiant de recette supprimee ne soit jamais reattribue ; la spec ne dit rien des identifiants (la regle A35 ne parle que de disparition de la liste).
anchor:    A35 : « La suppression d'une recette la fait disparaitre de la liste des recettes » | test_A35_identifiant_non_recycle_apres_suppression (`r3 != r2`).

test:      test_A35_identifiant_non_recycle_apres_reouverture
kind:      gap
assertion: Le test exige la meme non-reattribution d'identifiants a travers une reouverture ; la spec ne dit rien des identifiants.
anchor:    A35 : « La suppression d'une recette la fait disparaitre de la liste des recettes » | test_A35_identifiant_non_recycle_apres_reouverture (`r3 != r2`).

test:      test_A37_trou_photo_note_categorie_conservees
kind:      gap
assertion: Le test exige que photo, note et categorie d'une recette survivent a la reouverture ; la regle A37 ne cite que la presence de la recette, pas ses champs.
anchor:    A37 : « Apres fermeture et reouverture de l'application, une recette enregistree est toujours presente » | test_A37_trou_photo_note_categorie_conservees.

test:      test_A37_trou_deux_instances_meme_fichier
kind:      gap
assertion: Le test exige que deux instances ouvertes simultanement sur le meme fichier n'ecrasent pas leurs ecritures ; la spec ne dit rien de l'usage concurrent de deux instances.
anchor:    A37 : « Apres fermeture et reouverture de l'application ... » | test_A37_trou_deux_instances_meme_fichier.
