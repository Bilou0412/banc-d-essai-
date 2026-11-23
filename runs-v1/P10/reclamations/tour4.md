test:      test_A07_trou_rejeu_ne_duplique_pas
kind:      gap
assertion: le test exige qu'un blob intact rejoué ne fasse pas réapparaître le message ; la spec ne dit rien du rejeu (A07 ne traite que les blobs altérés). Implémenté par déduplication sur l'identifiant du message, sans règle qui le fonde.
anchor:    A07 : « Quand un message chiffré est altéré pendant le transit, il ne s'affiche pas en clair chez le destinataire » — un rejeu n'est pas une altération.

test:      test_A07_trou_substitution_par_blob_d_un_autre_expediteur
kind:      gap
assertion: le test exige qu'un blob authentique de carol, substitué en transit à un message d'alice, ne s'affiche pas dans la conversation avec alice ; la spec ne dit pas où s'affiche un blob authentique d'un autre expéditeur.
anchor:    A07 : « Quand un message chiffré est altéré pendant le transit... » — la substitution n'est pas une altération du blob de carol, qui est intact ; A01 ne détermine pas la conversation d'affichage.

test:      test_A19_trou_plusieurs_bloques_liberes_dans_l_ordre
kind:      gap
assertion: le test exige que plusieurs messages bloqués soient libérés et affichés chez le destinataire dans l'ordre d'envoi ; N03 ne traite que d'un message bloqué et ne dit rien de l'ordre.
anchor:    N03 : « Quand l'utilisateur confirme le changement d'empreinte, le message bloqué passe à « envoyé » et s'affiche en clair chez le destinataire » — règle par message, sans ordre.

test:      test_A21_trou_ordre_des_messages_en_attente
kind:      gap
assertion: le test exige que les messages « en attente » soient transmis et affichés dans l'ordre d'envoi au retour en ligne ; A21 ne dit que le passage à « envoyé ».
anchor:    A21 : « Quand l'appareil de l'expéditeur revient en ligne, l'envoi d'un message « en attente » passe à « envoyé » » — aucune contrainte d'ordre.

test:      test_A24_trou_ajout_en_double
kind:      gap
assertion: le test exige qu'ajouter deux fois le même contact à un groupe le laisse une seule fois dans la liste des membres et ne lui livre chaque message qu'une fois ; la spec ne dit pas ce qu'est un ajout répété.
anchor:    A24 : « Quand un utilisateur ajoute un contact à un groupe, ce contact apparaît dans la liste des membres » — aucune règle sur un second ajout du même contact.

test:      test_A26_trou_membre_a_deux_appareils
kind:      gap
assertion: le test exige qu'un message de groupe s'affiche en clair sur chacun des deux appareils d'un même membre ; A26 dit « chez chaque membre » sans préciser le cas d'un membre à plusieurs appareils, que A02 ne couvre que pour un contact en tête-à-tête.
anchor:    A26 : « ... le message s'affiche en clair chez chaque membre du groupe » ; A02 : « ... un contact qui a deux appareils liés ... » (conversation à deux, pas groupe).

test:      test_A27_trou_non_membre_ne_dechiffre_pas
kind:      gap
assertion: le test exige qu'un contact qui n'a jamais été membre du groupe ne puisse pas déchiffrer ses messages ; A27 ne traite que le membre retiré, et N01/A03 ne traitent que des appareils de destinataires d'un message adressé.
anchor:    A27 : « Quand un utilisateur envoie un message à un groupe, un contact retiré du groupe ne peut pas afficher ce message en clair » — le cas « jamais membre » n'est pas énoncé.

test:      test_A30_trou_minuterie_propre_a_la_conversation
kind:      gap
assertion: le test exige qu'une conversation sans réglage de minuterie ait une minuterie absente (None) par défaut ; la spec ne dit pas quelle est la valeur par défaut de la minuterie.
anchor:    A30 : « Quand un utilisateur règle la minuterie d'une conversation sur une heure, la minuterie affichée vaut une heure » — ne dit rien de la valeur avant tout réglage ; A34 présuppose seulement qu'elle peut être désactivée.
