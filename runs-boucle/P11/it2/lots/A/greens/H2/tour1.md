test:      test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte
kind:      contradiction
assertion: Le test exige qu'après `alice.set_cell('A1','5')` (une modification en attente) puis `set_right` puis `undo()`, le nombre de modifications en attente passe à 2 (modification + annulation). La règle C07 exige qu'annuler une modification encore en attente la retire des modifications en attente (attente = 0 pour cette seule action) ; la règle C25 ne crée une inverse en attente que pour une modification dont l'envoi est déjà confirmé. Ces deux règles donnent 0 (ou 1 si l'annulation portait sur autre chose), jamais 2.
anchor:    tests/test_app_c2.py::test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte (assert pending_count() == 2 après undo) contre tests/test_app_arbitre2.py::test_C07_online_edit_undone_before_confirmation_pending_back_to_zero et la règle C07 : « annuler une modification en attente la retire : leur nombre revient à zéro » ; règle C25 : seule une modification confirmée produit une inverse en attente.

test:      test_A34_trou_unite_ecart
kind:      gap
assertion: Le test exige que l'écart entre deux date-heures soit exprimé en jours réels écoulés (23/24 pour un passage à l'heure d'été). La règle A34 exige seulement que le résultat soit identique pour des personnes de fuseaux différents ; elle ne fixe ni l'unité de l'écart ni la manière de le compter (jours, heures, jours calendaires).
anchor:    tests/test_app.py::test_A34_trou_unite_ecart (assert abs(v - 23/24) < 1e-9) contre la règle A34 : « Une formule calculant l'écart entre deux cellules date-heure affiche le même résultat pour des personnes de fuseaux différents ».

test:      test_A145_trou_format_iso
kind:      gap
assertion: Le test exige que l'export CSV d'une date-heure soit la chaîne ISO 8601 « 2026-01-15T12:00:00+01:00 » (séparateur T, décalage à deux chiffres). La règle A145 exige que le fichier contienne la date-heure dans le fuseau de la personne avec son décalage horaire ; elle ne fixe ni le format textuel ni le séparateur.
anchor:    tests/test_app.py::test_A145_trou_format_iso (check == "2026-01-15T12:00:00+01:00") contre la règle A145 : « le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire ».

test:      test_A121_trou_ordre_horodatage_hors_ligne
kind:      gap
assertion: Le test exige que l'historique soit trié par horodatage de la modification (alice 11:00 avant bob 10:00), bob ayant été enregistré par le serveur après alice mais horodaté plus tôt. La règle A121 dit « de la plus récente à la plus ancienne » sans préciser si « récente » désigne l'horodatage de la modification ou son ordre d'enregistrement par le serveur ; les deux lectures sont compatibles avec les autres règles et donnent ici des résultats opposés.
anchor:    tests/test_app.py::test_A121_trou_ordre_horodatage_hors_ligne (check des auteurs [("alice","2026-01-15 11:00"),("bob","2026-01-15 10:00")]) contre la règle A121 : « L'historique des versions affiche les entrées de la plus récente à la plus ancienne » ; A124 fixe l'horodatage d'une version hors ligne au moment de la modification locale, sans dire quel ordre l'historique doit suivre.

test:      test_A42_trou_casse_differente
kind:      gap
assertion: Le test exige qu'un renommage vers « FEUILLE2 » soit refusé quand « Feuille2 » existe, c'est-à-dire que l'unicité des noms de feuilles ignore la casse. La règle A42 n'interdit que le renommage vers un nom « déjà utilisé » sans préciser la comparaison ; une lecture stricte (égalité exacte) autoriserait « FEUILLE2 ».
anchor:    tests/test_app.py::test_A42_trou_casse_differente (check ["Feuille1","Feuille2"] après rename_sheet("Feuille1","FEUILLE2")) contre la règle A42 : « Quand une personne renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée ».
