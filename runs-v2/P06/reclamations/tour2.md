test:      test_A32_trou_duree_modifiee_en_cours_compte_duree_du_demarrage
kind:      gap
assertion: Le test exige que la session terminée compte la durée travail en vigueur au démarrage (2 min) et non celle en vigueur à l'arrivée à zéro (5 min). La spec ne dit pas quelle durée A32 retient lorsque la durée travail change pendant un décompte en cours.
anchor:    A32 (« augmente le total jour de la durée travail », lue à l'arrivée à zéro) et A26 (modifier la durée en cours laisse le temps restant inchangé, sans fixer la durée comptée). Le test asserte minutes == 2 après set_work_duration(5) en cours.

test:      test_A12_trou_reinitialiser_en_pause_courte
kind:      gap
assertion: Le test exige que « réinitialiser » en phase « pause courte » laisse la phase inchangée et remette le temps restant à la durée pause (180 s). La spec ne règle ce comportement que pour la phase « travail ».
anchor:    A12 (conditions : phase = « travail ») ; A11 ne règle que le statut minuteur.

test:      test_A25_trou_arrete_en_pause_courte_temps_restant_inchange
kind:      gap
assertion: Le test exige que, statut « arrêté » en phase « pause courte », modifier la durée travail laisse le temps restant inchangé (60). La spec ne règle la modification de durée sur le temps restant que pour la phase « travail ».
anchor:    A25 (conditions : statut « arrêté » et phase = « travail »).

test:      test_A16_trou_intervalle_zero_refuse
kind:      gap
assertion: Le test exige qu'un intervalle longue de 0 soit refusé (ValueError) et que l'intervalle précédent soit conservé. La spec ne dit rien de la valeur 0 pour l'intervalle longue ; A27 ne traite que la durée travail.
anchor:    A16 et A23 (intervalle longue sans règle de validité) ; A27 (limité à « durée travail de 0 minute »).

test:      test_A27_trou_duree_negative_refusee
kind:      gap
assertion: Le test exige qu'une durée travail négative soit refusée. La spec ne traite que la valeur 0.
anchor:    A27 (« Saisir une durée travail de 0 minute est refusé »), sans mention des valeurs négatives.

test:      test_A23_passer_pause_courte
kind:      gap
assertion: Le test exige que « passer » depuis « travail » avec 0 cycle complété et intervalle longue de 10 donne « pause courte ». La spec ne dit pas quelle pause est choisie lorsque aucun cycle n'est complété ; avec la règle de multiple appliquée aux cycles complétés, 0 serait un multiple de 10.
anchor:    A23 (« selon les cycles complétés ») et A16 (règle du multiple, énoncée après incrément).

test:      test_A40_trou_session_sur_disque_sans_close
kind:      gap
assertion: Le test exige que, après un arrêt brutal du processus sans fermeture (os._exit), la session terminée soit relue à la réouverture. La spec ne demande la persistance qu'après « fermeture puis réouverture ».
anchor:    A40 (« Après fermeture puis réouverture de l'application, l'historique sessions est identique »).
