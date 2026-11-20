test:      test_A145_trou_format_iso
kind:      gap
assertion: exige que la date-heure exportée soit au format ISO 8601 « 2026-01-15T12:00:00+01:00 » ; la spec demande seulement que le fichier contienne la date-heure dans le fuseau de la personne avec son décalage horaire, sans fixer le format textuel.
anchor:    règle A145 : « le fichier CSV contient la date-heure dans le fuseau de la personne avec son décalage horaire » ; test_A145_trou_format_iso : check(rows(...)[0][0], "2026-01-15T12:00:00+01:00", "format ISO 8601").

test:      test_A34_trou_unite_ecart
kind:      gap
assertion: exige que l'écart entre deux date-heures soit exprimé en jours écoulés réels (23/24 pour le passage à l'heure d'été) ; la spec demande seulement que l'écart soit identique pour des personnes de fuseaux différents, sans fixer l'unité ni la manière de compter.
anchor:    règle A34 : « affiche le même résultat pour des personnes de fuseaux différents » ; test_A34_trou_unite_ecart : abs(v - 23 / 24) < 1e-9.

test:      test_A81_trou_conflit_signale
kind:      gap
assertion: exige qu'un indicateur de conflit apparaisse chez alice (valeur écartée « a », auteur « alice ») quand deux personnes hors ligne modifient la même cellule ; la spec ne prévoit un indicateur de conflit que dans le cas d'une modification hors ligne face à une modification faite en ligne entre-temps (A80), et A81 ne mentionne pas de conflit.
anchor:    règle A81 : « la cellule garde la valeur de la personne revenue en ligne la première » (aucune mention d'indicateur) ; règle A80 : « qu'une autre personne a modifiée en ligne entre-temps » ; test_A81_trou_conflit_signale : assert cf is not None.

test:      test_A121_trou_ordre_horodatage_hors_ligne
kind:      gap
assertion: exige que l'ordre « plus récente d'abord » soit l'ordre des horodatages de modification locale (bob 10:00 après alice 11:00 bien que bob soit enregistré en dernier) ; la spec dit « plus récente à la plus ancienne » sans préciser si la récence est l'horodatage de la modification ou l'instant d'enregistrement serveur.
anchor:    règle A121 : « L'historique des versions affiche les entrées de la plus récente à la plus ancienne » ; règle A124 : « porte l'horodatage du moment de la modification locale » ; test_A121_trou_ordre_horodatage_hors_ligne : check([(v.author, v.timestamp) ...], [("alice", "2026-01-15 11:00"), ("bob", "2026-01-15 10:00")]).
