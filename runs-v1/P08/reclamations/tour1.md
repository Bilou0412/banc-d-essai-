test:      test_A03_trou_version_non_affichee
kind:      gap
assertion: exige qu'une version de l'historique ne soit pas consultable (ou n'affiche pas son texte) par un participant sans permission ; la règle A03 ne mentionne que « le contenu » du document, sans dire que les versions en font partie.
anchor:    A03 : « Quand un participant sans aucune permission ouvre le lien du document, le contenu ne lui est pas affiché » ; A33 ne traite que de la consultation par un participant ayant accès.

test:      test_A08_trou_delai_detection
kind:      gap
assertion: exige que le nom disparaisse de la présence au plus 60 s après la perte de connexion ; A08 ne fixe aucun délai maximal, seulement la disparition.
anchor:    A08 : « Quand la connexion d'un participant est perdue, son nom disparaît de la présence affichée chez les autres participants » (aucune borne temporelle).

test:      test_A11_trou_insertion_a_la_position_du_curseur
kind:      gap
assertion: exige qu'une insertion faite exactement à la position du curseur (entre le caractère précédent et le caractère suivant) fasse avancer le curseur ; A11 ne dit pas si cette insertion est « avant la position de mon curseur ».
anchor:    A11 : « Quand un autre participant insère du texte avant la position de mon curseur, mon curseur reste devant le même caractère » (la condition « avant » ne tranche pas le cas d'égalité de position).

test:      test_A14_trou_granularite
kind:      gap
assertion: exige qu'une annulation ne retire que la dernière des deux saisies successives (deux appels d'insertion) ; A14 ne définit pas ce qu'est « sa propre saisie » (un appel, une frappe, une séquence de frappes).
anchor:    A14 : « Quand un participant annule juste après sa propre saisie, le texte saisi est retiré du contenu » (granularité de la saisie non définie).

test:      test_A19_trou_saisie_d_autrui
kind:      gap
assertion: exige que la saisie d'un autre participant après mon annulation ne vide pas mon rétablissement ; A19 ne dit pas si la déclencheuse « un participant saisit du texte » est celui qui a annulé ou n'importe quel participant.
anchor:    A19 : « Quand un participant saisit du texte après une annulation, le rétablissement devient vide » (acteur de l'annulation et de la saisie non précisés).

test:      test_A27_trou_contenu_local_rejete
kind:      gap
assertion: exige que, après rejet de ses modifications en attente, le contenu propre du participant redevienne « Hello » et que l'indicateur d'attente disparaisse ; A27 ne dit rien du contenu local ni de l'indicateur après rejet, seulement de l'absence de ces modifications chez les autres.
anchor:    A27 : « ses modifications en attente n'apparaissent pas dans le contenu des autres participants » (aucune règle sur le contenu propre ni sur l'indicateur d'attente).

test:      test_A28_trou_affichee_chez_le_concerne
kind:      gap
assertion: exige que la permission soit affichée comme « read » chez le participant dont elle a changé ; A28 ne précise pas chez quels participants la permission affichée doit changer (propriétaire seul, ou aussi le concerné).
anchor:    A28 : « la permission affichée de ce participant devient lecture » (lieu d'affichage non précisé).

test:      test_A29_trou_auto_promotion
kind:      gap
assertion: exige qu'un participant non propriétaire ne puisse pas modifier sa propre permission ; A29 ne vise que « la permission d'un autre participant ».
anchor:    A29 : « Quand un participant non propriétaire tente de modifier la permission d'un autre participant, cette permission ne change pas » (le cas où l'auteur de la tentative est aussi le concerné n'est pas couvert).

test:      test_A30_trou_historique_partage
kind:      gap
assertion: exige que l'entrée ajoutée à l'historique par un participant apparaisse dans l'historique affiché chez les autres participants connectés ; A30 ne dit pas si l'historique est partagé ou propre à chaque participant.
anchor:    A30 : « une nouvelle entrée apparaît dans l'historique » (portée de l'historique non précisée).

test:      test_A37_trou_auteur_de_la_restauration
kind:      gap
assertion: exige que l'entrée ajoutée à l'historique par une restauration porte le nom de celui qui restaure ; A37 ne précise pas l'auteur de l'entrée, et A32 ne vise que l'enregistrement d'une version.
anchor:    A37 : « une nouvelle entrée apparaît dans l'historique » ; A32 : « l'entrée ajoutée à l'historique porte le nom de ce participant » (conditionnée à « enregistre une version », pas à « restaure »).
