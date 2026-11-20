test:      test_A42_trou_casse_differente
kind:      gap
assertion: exige qu'un renommage vers « FEUILLE2 » soit refusé quand « Feuille2 » existe, c'est-à-dire une unicité des noms insensible à la casse ; la spec dit seulement « un nom déjà utilisé » (A42) et ne fixe pas la comparaison des noms.
anchor:    règle A42 : « Quand une personne renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée ». Le test test_A42_trou_casse_differente exige l'insensibilité à la casse, non écrite dans A42.

test:      test_A34_trou_unite_ecart
kind:      gap
assertion: exige que l'écart entre deux date-heures soit exprimé en jours réels (23/24 pour un passage à l'heure d'été), unité et calcul de l'écart non fixés par la spec.
anchor:    règle A34 : « Une formule calculant l'écart entre deux cellules date-heure affiche le même résultat pour des personnes de fuseaux différents ». Le test exige une unité précise (jours décimaux), que A34 ne fixe pas.

test:      test_A137_trou_format_nombre
kind:      gap
assertion: exige que la valeur calculée 5 soit exportée sous la chaîne exacte « 5 » (pas « 5.0 »), format d'export des nombres non fixé par la spec.
anchor:    règle A137 : « Quand une personne exporte en CSV une cellule contenant =A1+A2, le fichier CSV contient la valeur calculée de la cellule ». Le format textuel du nombre n'est pas précisé ; test_A137_valeur_calculee accepte un flottant, test_A137_trou_format_nombre exige une chaîne entière : les deux ne sont pas fixés par la spec.

test:      test_A145_trou_format_iso
kind:      gap
assertion: exige le format exact « 2026-01-15T12:00:00+01:00 » pour une date-heure exportée en CSV ; la spec demande le décalage horaire mais pas le format de sérialisation.
anchor:    règle A145 : « Quand une personne exporte en CSV une cellule date-heure, le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire ». Le format ISO 8601 exact et la précision à la seconde ne sont pas dans la règle.
