test:      test_A10_trou_table_after_stockout_shows_history_value
kind:      contradiction
assertion: le test exige que la dernière ligne du tableau affiche la demande de la semaine (demand > 0), alors que la règle A10 exige que chaque ligne affiche les unités vendues de la semaine ; avec une commande de 0, les ventes valent 0 alors que la demande est strictement positive, donc les deux exigences ne peuvent pas être satisfaites ensemble.
anchor:    règle A10 (« affiche les unités vendues de la semaine correspondante ») + règle A26 (ventes = min(demande, commande)) contre test_A10_trou_table_after_stockout_shows_history_value (assert g.table_rows()[-1][1] == g.history[-1] == w.demand, avec w.demand > 0 et commande 0). Le test est compatible avec A09 + A32 (ligne = historique = demande), mais A10 lu littéralement ne l'est pas.

test:      test_A28_trou_negative_order_refused
kind:      gap
assertion: le test exige qu'une commande négative lève ValueError et ne résolve pas la semaine ; la spec ne dit rien sur la validité de la commande, ni sur le type d'erreur, ni sur l'absence de résolution.
anchor:    aucune règle A26 à A31 ne traite des commandes négatives ; test_A28_trou_negative_order_refused (pytest.raises(ValueError) sur submit_order(-1), puis len(history) == 8).

test:      test_A01_trou_initial_history_drawn_from_game_law
kind:      gap
assertion: le test exige que les 8 semaines initiales soient tirées autour de la demande moyenne de la partie (moyenne du ratio historique / demande moyenne entre 0,95 et 1,05 sur 300 parties) et qu'elles varient d'une semaine à l'autre (au moins 290 parties sur 300 non constantes) ; la spec ne dit pas comment l'historique initial est tiré.
anchor:    règle A01 (« l'historique contient exactement 8 semaines ») et règle A05 (entiers non négatifs) ne fixent aucune loi pour l'historique initial ; test_A01_trou_initial_history_drawn_from_game_law (assert 0.95 <= avg <= 1.05 et nonconstant >= 290).

test:      test_A14_trou_integer_accepted
kind:      gap
assertion: le test exige qu'une prévision sans décimale (« 100 ») soit acceptée ; la spec ne mentionne que les prévisions à 1 décimale (acceptées, A14) et à 2 décimales (refusées, A15), et ne dit rien du cas sans décimale. D'autres tests non marqués trou utilisent aussi des prévisions entières, ce qui rend le point incontournable.
anchor:    règle A14 (« avec 1 décimale ; elle est acceptée ») et règle A15 (« avec 2 décimales ; elle est refusée ») ; test_A14_trou_integer_accepted (assert submit_forecast("100").accepted is True).

test:      test_A40_trou_page_is_self_contained_mobile_html
kind:      gap
assertion: le test exige un doctype, une balise html, une meta viewport et l'absence de toute ressource externe (src ou href en http/https) ; la spec demande seulement que le jeu se lance dans un navigateur mobile sans installation, sans fixer de structure HTML ni de contrainte sur les ressources externes.
anchor:    règle A40 (« le jeu se lance sans installation ») ; test_A40_trou_page_is_self_contained_mobile_html (assert "<!doctype html" in low, meta viewport, pas de src ou href https?://).
