test:      test_A145_trou_format_iso
kind:      gap
assertion: le test exige le format exact « 2026-01-15T12:00:00+01:00 » pour l'export CSV d'une date-heure ; la règle A145 exige seulement que la date-heure soit exportée « avec son décalage horaire », sans fixer de format de texte.
anchor:    A145 (« le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire ») ; test_A145_trou_format_iso (assert « 2026-01-15T12:00:00+01:00 »).

test:      test_A137_trou_format_nombre
kind:      gap
assertion: le test exige que la valeur 5 soit exportée sous la forme exacte « 5 » ; la règle A137 demande seulement que le fichier contienne la valeur calculée, sans préciser la représentation numérique.
anchor:    A137 (« le fichier CSV contient la valeur calculée de la cellule ») ; test_A137_trou_format_nombre (check « 5 » sur rows(...)[2][0]), alors que test_A137_valeur_calculee accepte float(...) == 5.0.

test:      test_A38_trou2_lecteur_cree_sa_feuille
kind:      gap
assertion: le test exige qu'une personne ayant seulement le droit lecture sur Feuille1 puisse ajouter une feuille et en obtenir le droit écriture ; la règle A36 est conditionnée par « droit », sans dire si ce droit est requis pour ajouter une feuille.
anchor:    A36 (conditions : droit) et A38 (conditions : aucune) ; test_A38_trou2_lecteur_cree_sa_feuille (carol, droit lecture sur Feuille1, add_sheet puis right == écriture).

test:      test_A121_trou_ordre_horodatage_hors_ligne
kind:      gap
assertion: le test exige que l'historique soit trié par horodatage de modification locale (et non par ordre d'enregistrement par le serveur) ; la règle A121 dit « de la plus récente à la plus ancienne » sans préciser si « récente » se mesure à l'horodatage ou à l'arrivée au serveur.
anchor:    A121 (« affiche les entrées de la plus récente à la plus ancienne ») ; A124 (la version porte l'horodatage de la modification locale) ; test_A121_trou_ordre_horodatage_hors_ligne (attendu : alice 11:00 puis bob 10:00, bob enregistré à 12:00).
