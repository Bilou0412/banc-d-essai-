test:      test_A10_tableau_suit_l_historique_apres_une_semaine
kind:      contradiction
assertion: le test exige que la ligne ajoutée pour la semaine jouée affiche la demande (rows[-1][1] == week.demand), alors que A10 exige que chaque ligne affiche les unités vendues de la semaine.
anchor:    A10 : « Chaque ligne du tableau affiche les unités vendues de la semaine correspondante » est incompatible avec le test, car A26 pose que les unités vendues valent min(demande, commande), donc diffèrent de la demande dès que la commande est inférieure à la demande (le test joue avec une commande de 100, et la demande de la semaine peut dépasser 100). A32 précise en outre que l'historique porte la demande, pas les ventes (test_A32_historique_porte_la_demande_pas_les_ventes). La spec ne dit donc pas quelle valeur la ligne doit afficher pour une semaine jouée.

---

```
claim:     test_A10_tableau_suit_l_historique_apres_une_semaine — contradiction : le test exige que la ligne ajoutée pour la semaine jouée affiche la demande (rows[-1][1] == week.demand), alors que A10 exige que chaque ligne affiche les unités vendues de la semaine.
ruling:    upheld
because:   Les citations sont exactes. A10 dit « Chaque ligne du tableau affiche les unités vendues de la semaine correspondante ». A26 dit « Les unités vendues de la semaine valent le minimum entre la demande et la commande ». La commande est de 100 et A02 fixe la demande moyenne entre 60 et 140 : la demande de la semaine peut donc dépasser 100. Une ligne qui suit A10 à la lettre afficherait alors 100, et le test, qui exige `week.demand` sans condition, échouerait. Le test tranche à la place de la spec entre A10 (ventes) et A32 (« ajoutée à la fin de l'historique avec sa demande »).
certainty: close
```

C'est serré pour une raison précise. Dans le vocabulaire de la spec, les semaines de l'historique initial sont des tirages de demande (N01), mais A10 les présente comme des « unités vendues ». A10 a aussi pour condition « historique ». On peut donc lire A10 comme « la ligne affiche la valeur portée par l'historique », et sous cette lecture le test serait conforme. Le texte d'A10, lui, renvoie à la grandeur définie par A26. Seule l'intention de l'arbitre peut dire laquelle des deux il veut voir pour une semaine jouée : afficher la demande ou les ventes. C'est à lui de lever l'ambiguïté, pas au chercheur. En attendant, le test impose un choix que la spec ne fait pas.

Le test n'a pas été exécuté (app.py ne s'importe pas), donc ce verdict repose sur la lecture du texte seul. Le résultat d'exécution ne départage rien ici.

VERDICT: maintenue
NOUVELLE_ASSERTION: aucune