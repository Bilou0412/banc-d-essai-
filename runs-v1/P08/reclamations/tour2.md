test:      test_A03_trou_historique_non_divulgue
kind:      gap
assertion: exige qu'une version de l'historique ne soit pas visible (son texte n'apparaît pas) par un participant sans aucune permission ; la règle A03 ne vise que « le contenu » du document, pas l'historique.
anchor:    A03 : « Quand un participant sans aucune permission ouvre le lien du document, le contenu ne lui est pas affiché » ; A30/A33 ne traitent que de l'enregistrement et de la consultation par un participant ayant accès.

test:      test_A06_trou_reapparait_apres_reconnexion
kind:      gap
assertion: exige que le nom d'un participant réapparaisse dans la présence après une perte de connexion puis une reconnexion ; A06 ne vise que l'ouverture du document, et A08 ne dit rien du retour.
anchor:    A06 : « Quand un participant ouvre le document, son nom apparaît dans la présence affichée chez les autres participants » ; A08 : « Quand la connexion d'un participant est perdue, son nom disparaît de la présence affichée chez les autres participants » (aucune règle sur le retour après reconnexion).

test:      test_A06_trou_double_onglet
kind:      gap
assertion: exige que le nom d'un participant reste présent quand il ferme une de ses deux ouvertures du document ; A07 dit que son nom disparaît quand « un participant ferme le document », sans préciser ce qu'est un participant lorsqu'il a plusieurs ouvertures.
anchor:    A07 : « Quand un participant ferme le document, son nom disparaît de la présence affichée chez les autres participants » (identité du participant face à plusieurs ouvertures non définie).

test:      test_A10_trou_fermeture_retire_le_curseur
kind:      gap
assertion: exige que le curseur distant d'un participant disparaisse quand il ferme le document (et non quand sa connexion est perdue) ; A10 ne vise que la perte de connexion.
anchor:    A10 : « Quand la connexion d'un participant est perdue, son curseur distant disparaît chez les autres participants » ; A07 ne parle que du nom dans la présence, pas du curseur.

test:      test_A14_trou_annuler_une_suppression
kind:      gap
assertion: exige qu'annuler juste après une suppression fasse réapparaître le passage supprimé ; A14 ne vise que le retrait du texte de sa propre saisie, et la suppression n'est pas une saisie.
anchor:    A14 : « Quand un participant annule juste après sa propre saisie, le texte saisi est retiré du contenu » ; aucune règle ne définit l'annulation d'une suppression.

test:      test_A14_annulations_successives_une_par_saisie
kind:      gap
assertion: exige que vingt annulations successives retirent chacune une saisie distincte, dont les plus anciennes ; A14 ne vise que l'annulation « juste après sa propre saisie », et la profondeur de la pile d'annulation n'est pas précisée.
anchor:    A14 : « Quand un participant annule juste après sa propre saisie, le texte saisi est retiré du contenu » (une seule annulation décrite) ; A16 : « annuler sans aucune action annulable » ne définit pas la profondeur.

test:      test_A18_retablissements_successifs
kind:      gap
assertion: exige que dix rétablissements successifs réinsèrent chacun une saisie annulée ; A18 ne vise que le rétablissement « juste après une annulation », et la profondeur de la pile de rétablissement n'est pas précisée.
anchor:    A18 : « Quand un participant rétablit juste après une annulation, le texte annulé réapparaît dans le contenu » (un seul rétablissement décrit).

test:      test_A38_trou_deux_annulations
kind:      gap
assertion: exige qu'une seconde annulation, faite après une annulation de restauration, retire une saisie antérieure de l'auteur ; A38 ne vise que l'annulation juste après la restauration, et A14 que l'annulation juste après une saisie.
anchor:    A38 : « Quand un participant annule juste après une restauration, le contenu redevient celui d'avant la restauration » ; A14 : « Quand un participant annule juste après sa propre saisie, le texte saisi est retiré du contenu » (la seconde annulation n'est juste après aucune des deux).
