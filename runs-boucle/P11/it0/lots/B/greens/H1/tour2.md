test:      test_A42_trou_casse_differente
kind:      gap
assertion: le test exige qu'un nom ne différant de « Feuille2 » que par la casse (« FEUILLE2 ») soit refusé comme nom déjà utilisé ; la règle A42 dit seulement « un nom déjà utilisé par une autre feuille » sans préciser si la casse distingue deux noms.
anchor:    A42 (« renomme une feuille avec un nom déjà utilisé par une autre feuille, la liste des feuilles reste inchangée ») ; test_A42_trou_casse_differente (attendu : ['Feuille1', 'Feuille2'] après rename_sheet('Feuille1', 'FEUILLE2')).
