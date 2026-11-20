test:      test_A42_trou_casse_differente
kind:      gap
assertion: Le test exige qu'un renommage vers « FEUILLE2 » soit refusé parce qu'une feuille « Feuille2 » existe, c'est-à-dire que l'unicité des noms de feuille soit insensible à la casse. La règle A42 dit seulement « un nom déjà utilisé par une autre feuille » et ne précise pas que la casse est ignorée. Implémenté tout de même, car le choix est laissé libre par la spec (comparaison insensible à la casse, avec les autres feuilles seulement).
anchor:    A42 : « Quand une personne renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée » ; test_A42_trou_casse_differente : alice.rename_sheet("Feuille1", "FEUILLE2") doit laisser sheets() == ["Feuille1", "Feuille2"].
