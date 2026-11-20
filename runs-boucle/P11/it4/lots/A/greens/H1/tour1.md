test:      test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte
kind:      gap
assertion: le test exige qu'un changement de droit (set_right du propriétaire) ne soit pas une action annulable : après set_right, puis annuler, la modification de cellule en attente est retirée et le compte revient à 0 ; la spec ne dit pas si un changement de droit entre dans la pile d'annulation, ni s'il en sort.
anchor:    règles A100 à A118 et C03/C07 : elles parlent de « modifications », « actions » et « annuler » sans dire si un changement de droit est annulable ; test_app_c4.py::test_C17_changer_un_droit_apres_modification_non_confirmee_laisse_le_compte, assertion « attendu 0 (modification non confirmée retirée par l annulation) ».
