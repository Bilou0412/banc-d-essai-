test:      test_A01_trou_moderateur_sans_role_auteur
kind:      gap
assertion: exige qu'un utilisateur sans rôle auteur (modérateur seul) qui tente de créer un article soit refusé par une exception ; la spec ne dit pas ce qui arrive à une création par un non-auteur, A01 ne décrit que le cas de l'auteur.
anchor:    A01 : « Un auteur crée un nouvel article : le statut de l'article est « brouillon » » (conditions : rôle) ; test_A01_trou_moderateur_sans_role_auteur qui attend app.Refused.

test:      test_A08_trou_non_proprietaire
kind:      gap
assertion: exige qu'un auteur non propriétaire qui tente de planifier un brouillon soit refusé (exception) et que le statut reste « brouillon » ; la spec ne décrit pas l'issue de cette tentative pour la planification (elle dit seulement « reste » pour A04/A05, sans mécanisme d'exception).
anchor:    A08 : « Un auteur planifie son brouillon avec une date planifiée dans le futur : le statut devient « planifié » » (conditions : propriété, date_planifiée) ; test_A08_trou_non_proprietaire.

test:      test_A09_trou_date_egale_maintenant
kind:      gap
assertion: exige qu'une planification à une date égale à l'instant présent soit refusée ; A08 ne couvre que le futur et A09 que le passé, le cas de l'égalité n'est dit par aucune règle.
anchor:    A08 : « … dans le futur … » ; A09 : « … dans le passé : le statut reste « brouillon » » ; test_A09_trou_date_egale_maintenant (planification à env.clock.now()).

test:      test_A13_trou_non_proprietaire
kind:      gap
assertion: exige qu'un auteur non propriétaire qui tente d'annuler une planification soit refusé (exception) et que le statut reste « planifié » ; la spec ne décrit pas cette tentative.
anchor:    A13 : « Un auteur annule la planification de son article « planifié » : le statut redevient « brouillon » » (conditions : propriété) ; test_A13_trou_non_proprietaire.

test:      test_A14_trou_non_proprietaire
kind:      gap
assertion: exige qu'un modérateur (non propriétaire) qui tente de dépublier un article soit refusé ; A14 ne vise que l'auteur propriétaire, l'issue de la dépublication par un non-propriétaire n'est pas dite.
anchor:    A14 : « Un auteur dépublie son article « publié » : le statut devient « brouillon » » (conditions : propriété) ; test_A14_trou_non_proprietaire (appels avec env.bob et env.mona).

test:      test_A16_trou_moderateur_non_proprietaire
kind:      gap
assertion: exige qu'un modérateur non propriétaire qui tente de modifier un contenu soit refusé ; A16 ne vise que « un auteur », le cas du modérateur non propriétaire n'est pas dit.
anchor:    A16 : « Un auteur tente de modifier le contenu d'un article dont il n'est pas le propriétaire : le contenu reste inchangé » ; test_A16_trou_moderateur_non_proprietaire.

test:      test_A24_trou_non_proprietaire
kind:      gap
assertion: exige qu'un auteur non propriétaire qui tente d'ajouter un tag soit refusé (exception) et que le tag n'apparaisse ni sur l'article ni sur la page du tag ; la spec ne décrit pas cette tentative.
anchor:    A24 : « Un auteur ajoute un tag à son article : le tag figure dans les tags de l'article » (conditions : propriété) ; test_A24_trou_non_proprietaire.

test:      test_A29_trou_commentaire_sur_brouillon
kind:      gap
assertion: exige qu'un visiteur qui tente de commenter un brouillon soit refusé (exception) et qu'aucun commentaire ne soit créé ; A29 ne décrit que le commentaire sur un article « publié ».
anchor:    A29 : « Un visiteur poste un commentaire sur un article « publié » : la modération du commentaire est « en attente » » (conditions : statut) ; test_A29_trou_commentaire_sur_brouillon.

test:      test_A31_trou_approuver_rejete
kind:      gap
assertion: exige qu'un modérateur qui tente d'approuver un commentaire déjà « rejeté » soit refusé et que la modération reste « rejeté » ; A31 ne décrit que l'approbation d'un commentaire « en attente ».
anchor:    A31 : « Un modérateur approuve un commentaire « en attente » : la modération devient « approuvé » » (conditions : rôle) ; test_A31_trou_approuver_rejete.

test:      test_A33_trou_auteur_sans_role_ne_peut_rejeter
kind:      gap
assertion: exige qu'un auteur sans rôle de modérateur qui tente de rejeter un commentaire soit refusé (exception) et que la modération reste « en attente » ; A33 ne décrit que le rejet par un modérateur, et A32 ne couvre que l'approbation.
anchor:    A33 : « Un modérateur rejette un commentaire « en attente » : la modération devient « rejeté » » (conditions : rôle) ; A32 : « Un auteur sans rôle de modérateur tente d'approuver … » ; test_A33_trou_auteur_sans_role_ne_peut_rejeter.

test:      test_A33_trou_rejeter_un_approuve_refuse
kind:      gap
assertion: exige qu'un modérateur qui tente de rejeter un commentaire déjà « approuvé » soit refusé, que la modération reste « approuvé » et que le compteur ne change pas ; A33 ne décrit que le rejet d'un commentaire « en attente ».
anchor:    A33 : « Un modérateur rejette un commentaire « en attente » : la modération devient « rejeté » » (conditions : rôle) ; test_A33_trou_rejeter_un_approuve_refuse.

test:      test_A36_compteur_survit_a_depublication
kind:      gap
assertion: exige que le compteur de commentaires d'un article garde sa valeur pendant une dépublication puis une republication ; A36 ne dit rien du compteur lors d'une dépublication (A36 ne décrit que l'effet d'une approbation).
anchor:    A36 : « Un modérateur approuve un commentaire : le compteur de commentaires de l'article augmente de un » (conditions : modération) ; A14 : « … le statut devient « brouillon » » ; test_A36_compteur_survit_a_depublication.
