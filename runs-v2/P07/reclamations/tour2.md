test:      test_A24_trou_titre_sur_A_texte_sur_B_pas_de_conflit
kind:      gap
assertion: le test exige qu'une modification du titre faite hors ligne sur A et une modification du texte faite hors ligne sur B se fusionnent (titre et texte visibles sur A et sur B) sans conflit ; la règle A24 ne traite que le cas de « textes différents » et ne dit rien de la fusion titre/texte.
anchor:    règle A24 (« modifiée hors ligne sur A et sur B avec des textes différents : signale un conflit ») contre test_A24_trou_titre_sur_A_texte_sur_B_pas_de_conflit, `assert n["title"] == "Titre par A" and n["text"] == "texte par B"` après les deux retours en ligne.

test:      test_A29_trou_conflit_leve_aussi_sur_l_autre_appareil
kind:      gap
assertion: le test exige que le choix d'une version fait sur A lève aussi le conflit affiché sur B ; la règle A29 ne décrit que l'effet sur l'appareil où l'utilisateur choisit, sans dire ce qu'il advient de l'autre appareil.
anchor:    règle A29 (« l'utilisateur choisit une version : l'application ne signale plus de conflit sur cette note ») contre test_A29_trou_conflit_leve_aussi_sur_l_autre_appareil, `assert not w.B.has_conflict(nid)` après `w.A.resolve_conflict` et `w.net.run()`.

test:      test_A28_trou_horloges_egales_les_appareils_convergent
kind:      gap
assertion: le test exige, quand les deux appareils ont la même heure, que les deux affichent le même texte et que la copie de conflit soit identique sur les deux ; la règle A28 désigne la version la plus récente « selon l'heure des appareils » sans dire comment départager deux heures égales.
anchor:    règle A28 (« la note d'origine affiche la version modifiée en dernier selon l'heure des appareils ») contre test_A28_trou_horloges_egales_les_appareils_convergent, `assert ta == tb and ta in ("version A", "version B")` avec `w.clocks["A"].now() == w.clocks["B"].now()` vérifié juste avant.

test:      test_A27_trou_trois_appareils_aucune_version_perdue
kind:      gap
assertion: le test exige, avec trois appareils A, B, C modifiant la même note hors ligne, que chacun signale le conflit, affiche la même version et voie toutes les autres versions dans des copies identiques ; les règles A24 à A31 ne décrivent que deux appareils, A et B.
anchor:    règle A27 (« une seconde note « copie de conflit » contenant l'autre version apparaît ») contre test_A27_trou_trois_appareils_aucune_version_perdue, `World(names=("A", "B", "C"))` et `assert views[0] == views[1] == views[2]`.
