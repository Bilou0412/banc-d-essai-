test:      test_A16_trou_intervalle_zero_refuse
kind:      gap
assertion: exige que `set_long_interval(0)` lève ValueError et laisse l'intervalle inchangé ; la spec ne dit rien sur les valeurs admissibles de l'intervalle longue.
anchor:    règle A16 (« multiple de l'intervalle longue », sans borne) ; seule A27 fixe un refus, et seulement pour la durée travail à 0 minute.

test:      test_A27_trou_duree_negative_refusee
kind:      gap
assertion: exige que `set_work_duration(-5)` soit refusé ; la spec ne mentionne que la valeur 0.
anchor:    règle A27 : « Saisir une durée travail de 0 minute est refusé et la durée travail reste à sa valeur précédente. » (aucune mention des valeurs négatives).

test:      test_A28_trou_date_de_fin_si_minuit
kind:      gap
assertion: exige que la date d'une session soit la date de fin (00:00:30 le 20 pour une session démarrée à 23:59:30 le 19) ; la spec ne dit pas si la date d'une session est celle du début ou celle de la fin.
anchor:    règle A28 (« ajoute une session à l'historique », sans date) ; A34 et A35 ne définissent la date courante que pour les totaux et la série.

test:      test_A12_trou_reinitialiser_en_pause_courte
kind:      gap
assertion: exige qu'en phase « pause courte », l'action « réinitialiser » remette le temps restant à la durée de la pause (180 s) ; la spec ne fixe ce comportement que pour la phase « travail ».
anchor:    règle A12 (conditions : phase « travail ») ; règle A11 (réinitialiser → statut « arrêté », sans mention du temps restant).

test:      test_A25_trou_arrete_en_pause_courte_temps_restant_inchange
kind:      gap
assertion: exige que modifier la durée travail, statut « arrêté » en phase « pause courte », laisse le temps restant à 60 s ; la spec ne dit rien de cette combinaison.
anchor:    règle A25 (conditions : statut « arrêté » et phase « travail ») ; règle A19 (temps restant fixé au passage en pause courte, sans condition sur la durée travail).

test:      test_A40_trou_session_sur_disque_sans_close
kind:      gap
assertion: exige qu'une session terminée soit relue par une nouvelle instance après interruption du processus, sans appel à close ; la spec ne prescrit la persistance que pour une fermeture suivie d'une réouverture.
anchor:    règle A40 : « Après fermeture puis réouverture de l'application, l'historique sessions est identique à celui d'avant la fermeture. » (aucune mention d'une interruption sans fermeture).
