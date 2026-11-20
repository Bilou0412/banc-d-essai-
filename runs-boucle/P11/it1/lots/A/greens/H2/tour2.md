test:      test_A34_trou_unite_ecart
kind:      gap
assertion: Le test exige que l'écart entre deux date-heures soit exprimé en jours réels (23/24 pour un passage à l'heure d'été). La spec (A34) demande seulement que l'écart soit identique pour des personnes de fuseaux différents ; elle ne fixe ni l'unité de l'écart ni sa représentation.
anchor:    Règle A34 : « Une formule calculant l'écart entre deux cellules date-heure affiche le même résultat pour des personnes de fuseaux différents ». Le test test_A34_trou_unite_ecart exige abs(v - 23/24) < 1e-9. Implémentation actuelle : écart en jours réels, compatible avec le test, non contredit par la spec.

test:      test_A137_trou_format_nombre
kind:      gap
assertion: Le test exige que la valeur entière calculée 5 soit exportée sous la forme de texte « 5 ». La spec (A137) demande que le fichier contienne la valeur calculée, sans fixer le format textuel d'un nombre (entier, décimal, séparateur).
anchor:    Règle A137 : « Quand une personne exporte en CSV une cellule contenant =A1+A2, le fichier CSV contient la valeur calculée de la cellule ». Le test test_A137_valeur_calculee accepte float(...) == 5.0 ; test_A137_trou_format_nombre exige rows[2][0] == "5". Les deux sont compatibles avec la spec, le second ajoute une exigence de format non écrite.

test:      test_A145_trou_format_iso
kind:      gap
assertion: Le test exige que la date-heure exportée soit au format ISO 8601 exact « 2026-01-15T12:00:00+01:00 ». La spec (A145) demande que la date-heure figure dans le fuseau de la personne avec son décalage horaire ; le format textuel n'est pas spécifié.
anchor:    Règle A145 : « Quand une personne exporte en CSV une cellule date-heure, le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire ». Le test test_A145_date_heure_avec_decalage accepte datetime.fromisoformat(...) avec décalage ; test_A145_trou_format_iso exige une chaîne exacte.

test:      test_N01_trou2_passage_heure_hiver
kind:      gap
assertion: Le test exige que l'écart entre deux date-heures à cheval sur un changement d'heure vaille 25/24 (jours réels). La spec ne fixe pas l'unité de l'écart. La règle citée par le nom du test, « N01 », n'existe pas dans la liste des règles de la spec (A01 à A159, C01 à C13).
anchor:    Liste des règles de la spec : aucune règle N01. Règle A34 : « Une formule calculant l'écart entre deux cellules date-heure affiche le même résultat pour des personnes de fuseaux différents » (unité non fixée). Le test exige abs(v - 25/24) < 1e-9.

test:      test_N01_trou2_dates_seules
kind:      gap
assertion: Le test exige que l'écart entre deux dates seules consécutives (2026-03-28, 2026-03-29) vaille 1. La spec ne fixe ni l'unité ni la nature de l'écart entre deux dates seules. La règle citée par le nom du test, « N01 », n'existe pas dans la liste des règles de la spec.
anchor:    Liste des règles de la spec : aucune règle N01. Règle A33 (date seule : même jour quel que soit le fuseau) : ne dit rien de l'écart. Règle A34 : unité non fixée. Le test exige abs(v - 1) < 1e-9 pour C1 = B1-A1 avec A1 = 2026-03-28, B1 = 2026-03-29.

test:      test_A42_trou_casse_differente
kind:      gap
assertion: Le test exige qu'une feuille ne puisse pas être renommée « FEUILLE2 » quand « Feuille2 » existe déjà : deux noms ne différant que par la casse sont considérés comme le même nom. La spec (A42) dit « un nom déjà utilisé par une autre feuille » sans préciser si la comparaison est sensible à la casse.
anchor:    Règle A42 : « Quand une personne renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée ». Le test test_A42_trou_casse_differente exige que la liste reste ['Feuille1', 'Feuille2']. La spec ne tranche pas la casse ; l'implémentation actuelle compare sans casse, ce qui satisfait le test sans contredire la règle A42.
