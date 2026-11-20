test:      test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte
kind:      contradiction
assertion: après alice.set_right(...) puis alice.undo() avec une modification encore en attente, le test attend pending_count() == 2 ; or C07 dit qu'annuler une modification encore en attente la retire des modifications en attente (le nombre revient à zéro), et C17 dit qu'un changement de droit ne change pas ce nombre : aucune de ces règles ne produit 2.
anchor:    règle C07 (« la modification est retirée des modifications en attente : leur nombre revient à zéro (principe P2) ») et règle C17 (« le nombre de modifications en attente reste inchangé ») ; test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte (attend 2 après undo) contre test_C17_changer_un_droit_ne_compte_pas_en_attente (attend 0 après set_right seul) et test_C07 de tests/test_app_arbitre2.py (attend 0 après undo d'une modification en attente).

test:      test_A42_trou_casse_differente
kind:      gap
assertion: le test exige qu'un renommage vers « FEUILLE2 » soit refusé parce que « Feuille2 » existe, c'est-à-dire que deux noms ne différant que par la casse sont le même nom ; la spec dit seulement « un nom déjà utilisé », sans trancher la comparaison insensible à la casse.
anchor:    règle A42 (« renomme une feuille avec un nom déjà utilisé par une autre feuille ») ; test_A42_trou_casse_differente (attend ["Feuille1", "Feuille2"] après rename_sheet("Feuille1", "FEUILLE2")).

test:      test_A34_trou_unite_ecart
kind:      gap
assertion: le test exige que l'écart entre deux date-heures séparées par le passage à l'heure d'été vaille exactement 23/24, c'est-à-dire une unité en jours écoulés réels ; la spec dit seulement que le résultat est identique pour des fuseaux différents, sans fixer l'unité de l'écart.
anchor:    règle A34 (« affiche le même résultat pour des personnes de fuseaux différents ») ; test_A34_trou_unite_ecart (abs(v - 23/24) < 1e-9) contre test_A34_ecart_identique_entre_fuseaux, qui ne précise aucune unité.

test:      test_N01_trou2_passage_heure_hiver
kind:      gap
assertion: le test exige que l'écart entre deux date-heures séparées par le passage à l'heure d'hiver vaille 25/24, soit une unité en jours ; la spec ne fixe pas l'unité de l'écart de date-heure.
anchor:    règle A34 (écart entre deux cellules date-heure, aucune unité indiquée) ; même lacune que test_A34_trou_unite_ecart, appliquée à 25 h réelles.

test:      test_N01_trou2_dates_seules
kind:      gap
assertion: le test exige que l'écart entre deux dates seules consécutives vaille 1, soit une unité en jours ; la spec ne fixe pas l'unité de l'écart entre deux dates.
anchor:    règle A33 (date seule) et règle A34 (écart entre cellules, aucune unité indiquée) ; même lacune que test_A34_trou_unite_ecart.

test:      test_A145_trou_format_iso
kind:      gap
assertion: le test exige la chaîne exacte « 2026-01-15T12:00:00+01:00 » (ISO 8601 avec secondes) dans le CSV ; la spec dit seulement que le fichier contient la date-heure dans le fuseau de la personne avec son décalage horaire, sans fixer le format textuel.
anchor:    règle A145 (« le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire ») ; test_A145_trou_format_iso (check(rows(...)[0][0], "2026-01-15T12:00:00+01:00")) contre test_A145_date_heure_avec_decalage, qui accepte tout format relu par datetime.fromisoformat.

test:      test_A137_trou_format_nombre
kind:      gap
assertion: le test exige que la valeur calculée 5 (de =A1+A2) soit exportée sous la forme exacte « 5 » et non « 5.0 » ; la spec dit seulement que le fichier CSV contient la valeur calculée, sans fixer la mise en forme des nombres.
anchor:    règle A137 (« le fichier CSV contient la valeur calculée de la cellule ») ; test_A137_trou_format_nombre (check(..., "5")) contre test_A137_valeur_calculee, qui accepte float(...) == 5.0.
