test:      test_A27_trou_zero_refuse
kind:      gap
assertion: exige qu'une durée travail de 0 lève ValueError ; la spec dit seulement que la saisie est « refusée », sans fixer la forme du refus.
anchor:    règle A27 « Saisir une durée travail de 0 minute est refusé et la durée travail reste à sa valeur précédente. » (lacunes.md, ligne 1)

test:      test_A23_passer_pause_courte
kind:      gap
assertion: exige que « passer » depuis zéro cycle complété (intervalle 10) donne « pause courte ». La spec ne dit pas si zéro cycle compte comme multiple de l'intervalle longue ; le test tranche pour « non ».
anchor:    règle A23 « selon les cycles complétés » ; règle A16 « sont un multiple de l'intervalle longue » ; lacunes.md, ligne 2.

test:      test_A12_trou_reinitialiser_en_pause_courte
kind:      gap
assertion: exige que « réinitialiser » pendant une pause courte laisse la phase « pause courte » et remette le temps restant à la durée pause (180 s). La règle A12 ne couvre que la phase « travail ».
anchor:    règle A12 « Lorsque la phase est « travail », l'action « réinitialiser » remet le temps restant à la durée travail. » ; lacunes.md, ligne 4.

test:      test_A25_trou_en_pause_modifier_duree
kind:      gap
assertion: exige que modifier la durée travail pendant « en pause » laisse le temps restant inchangé. A25 traite l'état « arrêté » et A26 l'état « en cours » ; « en pause » n'est tranché par aucune des deux.
anchor:    règles A25 (« arrêté ») et A26 (« en cours ») ; lacunes.md, ligne 3.

test:      test_A28_trou_date_de_fin_si_minuit
kind:      gap
assertion: exige que la date d'une session qui chevauche minuit soit la date de fin (2026-11-20). La spec ne dit pas si la session porte la date de démarrage ou de fin ; ce choix change total jour et série jours.
anchor:    règle A28 « ajoute une session à l'historique sessions » (aucune règle de date) ; lacunes.md, ligne 5.

test:      test_A33_trou_total_tache_au_demarrage
kind:      gap
assertion: exige que le total tâche soit crédité à la tâche active au démarrage de la session, même si la tâche active a changé avant l'arrivée à zéro. A33 dit seulement « la tâche active » sans préciser l'instant ; le rattachement au démarrage n'est fixé que pour l'historique par A30.
anchor:    règle A33 « augmente le total tâche de la tâche active » ; règle A30 « au moment où la session a été démarrée » ; lacunes.md, ligne 6.
