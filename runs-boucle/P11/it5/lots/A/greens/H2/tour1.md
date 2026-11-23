test:      test_A34_trou_unite_ecart
kind:      gap
assertion: exige que l'écart entre deux date-heures soit exprimé en jours écoulés réels (23/24 pour un passage à l'heure d'été), ce que la règle A34 ne précise pas (A34 demande seulement un résultat identique entre fuseaux).
anchor:    règle A34 : « Une formule calculant l'écart entre deux cellules date-heure affiche le même résultat pour des personnes de fuseaux différents ». Le test attend abs(v - 23/24) < 1e-9 ; l'unité n'est fixée par aucune règle.

test:      test_A145_trou_format_iso
kind:      gap
assertion: exige que l'export CSV d'une date-heure soit au format ISO 8601 (« 2026-01-15T12:00:00+01:00 »), format non prescrit par la règle.
anchor:    règle A145 : « le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire ». Le format de sérialisation n'est pas spécifié ; le test attend une chaîne exacte.

test:      test_A137_trou_format_nombre
kind:      gap
assertion: exige que la valeur 5 (résultat de =A1+A2) soit exportée sous la forme textuelle « 5 » et non « 5.0 », règle de formatage numérique absente de la spec.
anchor:    règle A137 : « le fichier CSV contient la valeur calculée de la cellule ». Aucune règle ne fixe le formatage des nombres ; le test attend rows[2][0] == "5".

test:      test_A42_trou_casse_differente
kind:      gap
assertion: exige que deux noms de feuille ne différant que par la casse soient considérés comme identiques (« FEUILLE2 » refusé face à « Feuille2 »), comparaison insensible à la casse non prescrite.
anchor:    règle A42 : « Quand une personne renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée ». La notion de « nom déjà utilisé » ne précise pas la sensibilité à la casse ; le test tranche sans règle.

test:      test_A121_trou_ordre_horodatage_hors_ligne
kind:      gap
assertion: exige que l'historique soit trié par horodatage de modification locale (et non par ordre d'enregistrement par le serveur) lorsqu'une modification hors ligne est enregistrée après une modification plus récente, ordre non décrit par la règle.
anchor:    règle A121 : « L'historique des versions affiche les entrées de la plus récente à la plus ancienne ». « Plus récente » n'est pas défini : ordre d'enregistrement ou horodatage de la modification ? Le test (horodatage) et la lecture la plus simple de A124 (« porte l'horodatage du moment de la modification locale ») divergent de l'ordre d'arrivée ; la spec ne tranche pas.
