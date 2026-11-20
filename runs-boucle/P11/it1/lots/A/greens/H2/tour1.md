test:      test_A34_trou_unite_ecart
kind:      gap
assertion: Le test exige que l'écart entre deux date-heures soit exprimé en jours réels (23/24 pour un passage à l'heure d'été). La spec (A34) demande seulement que l'écart soit identique pour des personnes de fuseaux différents ; elle ne fixe ni l'unité de l'écart ni sa représentation.
anchor:    Règle A34 : « Une formule calculant l'écart entre deux cellules date-heure affiche le même résultat pour des personnes de fuseaux différents ». Le test test_A34_trou_unite_ecart exige abs(v - 23/24) < 1e-9.

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
assertion: Les tests portant le préfixe N01 (test_N01_trou2_passage_heure_hiver, test_N01_trou2_dates_seules) citent une règle « N01 » qui n'existe pas dans la liste des règles de la spec (A01 à A159, C01 à C13). Ils exigent en outre que la différence entre deux dates seules consécutives vaille 1 et que la différence de deux date-heures à cheval sur un changement d'heure vaille 25/24 jours : l'unité de l'écart n'est pas fixée par la spec (voir A34).
anchor:    Liste des règles de la spec : aucune règle N01. Règle A34 (écart identique entre fuseaux, unité non fixée). Le test test_N01_trou2_dates_seules exige abs(v - 1) < 1e-9 pour B1-A1 avec A1 = 2026-03-28, B1 = 2026-03-29.
