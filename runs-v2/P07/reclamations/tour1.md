test:      test_A24_trou_modifications_successives_pas_de_conflit
kind:      contradiction
assertion: le test exige qu'une modification faite hors ligne sur B, après avoir reçu la modification de A, ne soit pas un conflit ; la règle A24 ne fait pas cette distinction et déclenche le conflit dès que la même note est modifiée hors ligne sur A et sur B avec des textes différents.
anchor:    règle A24 (« modifiée hors ligne sur A et sur B avec des textes différents ; les deux appareils retrouvent le réseau : signale un conflit ») contre test_A24_trou_modifications_successives_pas_de_conflit, `assert not w.A.has_conflict(nid)` après la seconde modification hors ligne de B (B a modifié hors ligne, après synchronisation de la version de A).

test:      test_A24_trou_conflit_signale_sur_les_deux_appareils
kind:      gap
assertion: le test exige que chacun des deux appareils signale le conflit ; la règle A24 dit seulement que « l'application signale un conflit », sans préciser sur quel appareil.
anchor:    règle A24 (« l'application signale un conflit sur cette note ») contre test_A24_trou_conflit_signale_sur_les_deux_appareils, `assert w.B.has_conflict(nid), "B ne signale pas le conflit"`.

test:      test_A27_trou_une_seule_copie_identique_sur_les_deux_appareils
kind:      gap
assertion: le test exige exactement une copie de conflit, de même identifiant et de même texte sur les deux appareils, même quand des envois sont dupliqués ; la règle A27 dit seulement qu'une « seconde note » apparaît.
anchor:    règle A27 (« une seconde note « copie de conflit » contenant l'autre version apparaît dans la liste ») contre test_A27_trou_une_seule_copie_identique_sur_les_deux_appareils, `assert len(ca) == 1` et `assert ca[0]["id"] == cb[0]["id"]` après envois dupliqués.

test:      test_A29_trou_conflit_leve_aussi_sur_l_autre_appareil
kind:      gap
assertion: le test exige que le choix fait sur A lève aussi le conflit sur B ; la règle A29 ne parle que de l'appareil qui choisit, et sa condition « aucune » ne dit pas que l'autre appareil est concerné.
anchor:    règle A29 (« l'utilisateur choisit une version : l'application ne signale plus de conflit sur cette note ») contre test_A29_trou_conflit_leve_aussi_sur_l_autre_appareil, `assert not w.B.has_conflict(nid)` après `w.A.resolve_conflict` et run.

test:      test_A11_trou_modification_en_attente_survit_au_redemarrage
kind:      gap
assertion: le test exige que, après redémarrage hors ligne, la note affiche l'indicateur « en attente » ; la règle A11 ne parle que du texte affiché après redémarrage et ne dit rien de l'indicateur.
anchor:    règle A11 (« la note affiche le texte modifié », observé : contenu) contre test_A11_trou_modification_en_attente_survit_au_redemarrage, `assert w.A.note(nid)["indicator"] == PENDING` après close_app/open_app.
