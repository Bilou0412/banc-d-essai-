test:      test_A42_trou_casse_differente
kind:      gap
assertion: le test exige qu'un renommage vers « FEUILLE2 » soit refusé quand la feuille « Feuille2 » existe : l'unicité des noms de feuille est donc insensible à la casse. La règle A42 dit seulement « un nom déjà utilisé par une autre feuille » ; elle ne dit pas si la comparaison ignore la casse.
anchor:    règle A42 (« Quand une personne renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée ») ; test_app.py::test_A42_trou_casse_differente attend ["Feuille1", "Feuille2"] après rename_sheet("Feuille1", "FEUILLE2").

test:      test_C27_reg_reader_rename_to_same_name_raises_insufficient_right_alert
kind:      contradiction
assertion: le test exige qu'un lecteur qui renomme une feuille avec son nom actuel reçoive une alerte « droit insuffisant ». La règle C13 dit qu'une personne en ligne qui renomme avec le nom qu'elle porte déjà ne voit aucune alerte, sans condition de droit ; le lecteur est une personne en ligne. Les deux règles sont incompatibles sur ce cas précis.
anchor:    règle C13 (« Quand une personne en ligne renomme une feuille avec le nom qu'elle porte déjà, aucune alerte n'apparaît et le nombre de modifications en attente reste à zéro ») face à règle C27 (« ... l'écriture est refusée et une alerte « droit insuffisant » cite la feuille en cause ») ; test_app_reg6.py::test_C27_reg_reader_rename_to_same_name_raises_insufficient_right_alert asserte l'alerte, test_app_reg6.py::test_C13_reg_reader_rename_to_same_name_changes_nothing n'assère que la liste et l'attente, ce qui ne se contredit pas.
