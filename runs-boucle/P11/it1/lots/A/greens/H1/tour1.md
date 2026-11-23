test:      test_A34_trou_unite_ecart
kind:      gap
assertion: le test exige que l'écart entre deux date-heures soit exprimé en jours écoulés réels (23/24 de jour, soit 23 h à cause de l'heure d'été). La spec A34 demande seulement que la formule affiche le même résultat pour des fuseaux différents ; elle ne fixe ni l'unité ni la nature du résultat.
anchor:    A34 : « Une formule calculant l'écart entre deux cellules date-heure affiche le même résultat pour des personnes de fuseaux différents » ; le test test_A34_trou_unite_ecart asserte abs(v - 23/24) < 1e-9.

test:      test_A42_trou_casse_differente
kind:      gap
assertion: le test exige qu'un renommage vers « FEUILLE2 » soit refusé parce que « Feuille2 » existe déjà, donc que la comparaison des noms de feuilles ignore la casse. La spec A42 dit « un nom déjà utilisé » sans préciser si la casse compte.
anchor:    A42 : « Quand une personne renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée » ; le test test_A42_trou_casse_differente asserte sheets() == ["Feuille1", "Feuille2"] après rename vers "FEUILLE2".

test:      test_A121_trou_ordre_horodatage_hors_ligne
kind:      gap
assertion: le test exige que l'historique soit trié par horodatage de modification locale (alice 11:00 avant bob 10:00), et non par ordre d'enregistrement serveur (bob est enregistré après alice). La spec A121 demande « de la plus récente à la plus ancienne » sans dire si « récente » désigne l'horodatage local ou l'ordre d'enregistrement ; A124 ne tranche pas non plus cette question.
anchor:    A121 : « L'historique des versions affiche les entrées de la plus récente à la plus ancienne » ; A124 : « Une version issue d'une modification faite hors ligne porte l'horodatage du moment de la modification locale » ; le test asserte [(alice, "2026-01-15 11:00"), (bob, "2026-01-15 10:00")].

test:      test_A137_trou_format_nombre
kind:      gap
assertion: le test exige que la valeur numérique 5 issue de =A1+A2 soit exportée sous la forme « 5 » et non « 5.0 ». La spec A137 indique seulement que le fichier contient la valeur calculée ; elle ne précise pas le format d'écriture des nombres.
anchor:    A137 : « Quand une personne exporte en CSV une cellule contenant =A1+A2, le fichier CSV contient la valeur calculée de la cellule » ; le test test_A137_trou_format_nombre asserte rows(...)[2][0] == "5".

test:      test_A145_trou_format_iso
kind:      gap
assertion: le test exige que la date-heure exportée soit au format ISO 8601 complet « 2026-01-15T12:00:00+01:00 ». La spec A145 demande que la date-heure figure dans le fuseau de la personne « avec son décalage horaire », sans imposer de format.
anchor:    A145 : « Quand une personne exporte en CSV une cellule date-heure, le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire » ; le test test_A145_trou_format_iso asserte rows(...)[0][0] == "2026-01-15T12:00:00+01:00".
