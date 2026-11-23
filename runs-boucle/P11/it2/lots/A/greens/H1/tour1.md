test:      test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte
kind:      contradiction
assertion: après alice.set_right(...) puis alice.undo() avec une modification encore en attente, le test attend pending_count() == 2 ; or C07 dit qu'annuler une modification encore en attente la retire des modifications en attente (attendu 1 puis 0 selon C07 seul), et la première partie de C17 dit qu'un changement de droit n'est pas compté. Les deux règles donnent donc un nombre que le test ne peut pas satisfaire sans qu'un changement de droit annulé crée une entrée comptée, ce que C17 exclut.
anchor:    règle C07 (« annuler une modification en attente la retire ; leur nombre revient à zéro ») et règle C17 (« changer un droit ne change pas le nombre de modifications en attente ») ; test_C17_changer_un_droit_ne_compte_pas_en_attente (attend 0 après set_right seul) contre test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte (attend 2 après undo).

test:      test_A42_trou_casse_differente
kind:      gap
assertion: le test exige qu'un renommage vers « FEUILLE2 » soit refusé parce que « Feuille2 » existe, c'est-à-dire que deux noms ne différant que par la casse sont considérés comme le même nom ; la spec dit seulement « un nom déjà utilisé », sans trancher la comparaison insensible à la casse.
anchor:    règle A42 (« renomme une feuille avec un nom déjà utilisé par une autre feuille ») et règle A43 ; le test est test_A42_trou_casse_differente (attend ["Feuille1", "Feuille2"] après rename_sheet("Feuille1", "FEUILLE2")).

test:      test_A34_trou_unite_ecart
kind:      gap
assertion: le test exige que l'écart entre deux date-heures séparées par le passage à l'heure d'été soit exactement 23/24 (jours écoulés réels) ; la spec dit seulement que le résultat est identique pour des fuseaux différents (A34), sans fixer l'unité ni la méthode de calcul de l'écart.
anchor:    règle A34 (« affiche le même résultat pour des personnes de fuseaux différents ») ; test_A34_trou_unite_ecart (abs(v - 23/24) < 1e-9) contre test_A34_ecart_identique_entre_fuseaux, qui ne précise aucune unité.

test:      test_A145_trou_format_iso
kind:      gap
assertion: le test exige la chaîne exacte « 2026-01-15T12:00:00+01:00 » (format ISO 8601 avec secondes) dans le CSV ; la spec dit seulement que le fichier contient la date-heure dans le fuseau de la personne avec son décalage horaire (A145), sans fixer le format textuel.
anchor:    règle A145 (« le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire ») ; test_A145_trou_format_iso (check(rows(...)[0][0], "2026-01-15T12:00:00+01:00")) ; le test frère test_A145_date_heure_avec_decalage, lui, accepte n'importe quel format relu par datetime.fromisoformat.
