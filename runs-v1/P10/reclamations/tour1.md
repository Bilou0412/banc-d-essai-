test:      test_A03_trou_autre_appareil_expediteur
kind:      gap
assertion: exige que l'autre appareil de l'expéditeur (laptop) n'affiche pas le message envoyé dans conversation("bob") ; la spec ne dit rien de l'affichage sur les appareils de l'expéditeur lui-même.
anchor:    A03 : « un appareil absent de la liste des appareils liés du destinataire ne peut pas afficher ce message en clair » — ne couvre pas les appareils de l'expéditeur. Cf. lacunes.md, première entrée.

test:      test_A16_trou_confirmation_ne_reverifie_pas
kind:      gap
assertion: exige qu'après confirm_identity le contact reste « non vérifié » ; la spec ne dit pas ce que la confirmation fait à l'état de vérification.
anchor:    A16 : « Quand l'empreinte d'un contact « vérifié » change, le contact repasse à l'état « non vérifié » » — silencieux sur l'effet de la confirmation. A19 mentionne la confirmation sans en définir l'effet sur l'état. Cf. lacunes.md, deuxième entrée.

test:      test_A19_trou_confirmation_libere_message
kind:      gap
assertion: exige qu'après confirmation, le message bloqué passe à « envoyé » et s'affiche chez le destinataire ; la spec ne dit pas si la confirmation libère le message ou s'il doit être renvoyé.
anchor:    A19 : « l'envoi reste bloqué jusqu'à confirmation de l'utilisateur » — ne précise pas le sort du message après confirmation. Cf. lacunes.md, troisième entrée.

test:      test_A19_trou_non_verifie_pas_bloque
kind:      gap
assertion: exige qu'un envoi à un contact « non vérifié » dont l'empreinte a changé ne soit pas bloqué et s'affiche chez le destinataire ; la spec ne dit pas si ce cas est bloqué ou non.
anchor:    A19 : conditions « vérification, empreinte » et « contact précédemment « vérifié » » — le cas non vérifié est hors du champ de la règle, sans être déclaré libre. Cf. lacunes.md, quatrième entrée.

test:      test_A22_trou_un_appareil_en_ligne_suffit
kind:      gap
assertion: exige que l'accusé soit « remis » dès qu'un seul appareil du destinataire est en ligne ; la spec ne fixe que le cas « tous hors ligne » (A22) et le retour en ligne (A23).
anchor:    A22 : « dont tous les appareils sont hors ligne, l'accusé n'indique pas « remis » » — cas complémentaire non fixé. Cf. lacunes.md, cinquième entrée.

test:      test_A24_trou_liste_vue_par_autre_membre
kind:      gap
assertion: exige qu'un ajout au groupe par alice soit visible dans group_members(gid) de bob ; la spec ne dit pas quelle liste de membres doit être cohérente entre membres.
anchor:    A24 : « ce contact apparaît dans la liste des membres » — ne précise pas la liste concernée (celle de l'auteur de l'ajout ou celle des autres membres). Cf. lacunes.md, sixième entrée.

test:      test_A31_trou_participant_hors_ligne_voit_la_minuterie_au_retour
kind:      gap
assertion: exige que la nouvelle minuterie parvienne à un participant hors ligne au moment de la modification, et s'affiche à son retour ; la spec ne tranche pas la propagation vers un participant hors ligne.
anchor:    A31 : « la nouvelle valeur de minuterie s'affiche chez l'autre participant » — sans condition de connexion. Cf. lacunes.md, septième entrée.

test:      test_A32_trou_borne_exacte
kind:      gap
assertion: exige que le message disparaisse à l'instant exact où la durée est écoulée (now = lecture + durée) ; la spec ne fixe pas si la borne est incluse.
anchor:    A32 : « Quand la durée de la minuterie s'est écoulée depuis la lecture d'un message » — l'instant de l'écoulement (strict ou non) n'est pas défini. Cf. lacunes.md, huitième entrée.

test:      test_A33_trou_non_lu_reste_chez_expediteur
kind:      gap
assertion: exige qu'un message éphémère jamais lu par le destinataire reste affiché chez l'expéditeur au-delà de la durée ; la spec ne définit pas l'événement de « lecture » côté expéditeur ni le sort d'un message non lu.
anchor:    A33 : « Quand la durée de la minuterie s'est écoulée depuis la lecture d'un message, ce message disparaît de l'appareil de l'expéditeur » — sans définition de la lecture déclenchante ni cas non lu. Cf. lacunes.md, neuvième entrée.
