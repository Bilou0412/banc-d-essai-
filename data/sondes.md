# Sondes

Petits projets créés pour tester la méthode. La description est exactement celle donnée aux décompositeurs aveugles (`{DESCRIPTION}`).

La « prédiction » est celle de Claude, figée avant les passes strictes. Elle portait sur la difficulté en général et s'est révélée fausse pour la densité fonctionnelle (H7 réfutée, 3/10). Pour les nouvelles sondes, la prédiction doit séparer **densité fonctionnelle** et **difficulté technique**.

| ID | Sonde | Description donnée au décompositeur | Prédiction (Claude) | k strict |
|---|---|---|---|---|
| P01 | Carnet de contacts | Une application de carnet de contacts (créer, modifier, supprimer, rechercher, trier, étiquettes, favoris, import/export CSV). | Compressible | 1,76 |
| P02 | Gestionnaire de recettes | Un gestionnaire de recettes (créer des recettes avec ingrédients et quantités, catégories, recherche, ajuster les portions, liste de courses, notes, favoris, photos). | Compressible | 1,57 |
| P03 | Inventaire de matériel | Un inventaire de matériel (articles avec quantité et emplacement, prêts à des emprunteurs avec date de retour, historique, statut hors service, filtres, export). | Compressible | 1,83 |
| P04 | Todo multi-listes | « Todo multi-listes ». Une application de tâches où l'utilisateur organise ses tâches dans plusieurs listes (créer, cocher, déplacer, échéances, filtres, réordonner, etc.). | Compressible | 1,76 |
| P05 | Blog avec commentaires | Un blog avec commentaires (articles en brouillon ou publiés, publication planifiée, rôles auteur/modérateur, commentaires modérés, tags, flux RSS). | Mixte | 2,40 |
| P06 | Pomodoro avec statistiques | Un minuteur Pomodoro avec statistiques (cycles travail/pause, pauses longues, réglages des durées, sessions liées à des tâches, statistiques par jour et par tâche, séries de jours). | Mixte | 1,90 |
| P07 | Note synchronisée hors ligne | « Note synchronisée hors ligne ». Une application de notes utilisable sans connexion, dont les notes se synchronisent entre plusieurs appareils de l'utilisateur quand la connexion revient. | Dense | 1,94 |
| P08 | Éditeur collaboratif temps réel | Un mini éditeur de texte collaboratif en temps réel (plusieurs personnes éditent le même document en même temps, curseurs et présence des autres, annuler, permissions lecture/écriture, historique des versions). | Dense | 1,62 |
| P09 | Réservation de créneaux | Un système de réservation de créneaux (ressources avec capacité, horaires d'ouverture, règles de durée et de délai, quotas par utilisateur, annulation, liste d'attente, fuseaux horaires, récurrence). | Dense | 2,18 (**floue** : 2,05 / 2,35 / 2,18, écart-type 0,15) |
| P10 | Chat chiffré de bout en bout | Une messagerie chiffrée de bout en bout (messages chiffrés, nouvelles clés à chaque message, plusieurs appareils, groupes, vérification des contacts, accusés de remise, messages éphémères). | Dense | 1,80 (**floue** : 1,63 / 1,80 / 2,14, écart-type 0,26 ; une 4e passe, 1,76, avait été lancée avant la règle) |
| P11 | Tableur collaboratif hors ligne (grosse sonde) | Un tableur collaboratif utilisable hors ligne (cellules avec valeurs et formules qui se recalculent quand une cellule dont elles dépendent change, références circulaires signalées, plusieurs feuilles, plusieurs personnes qui éditent en même temps, travail hors connexion avec fusion des modifications au retour de la connexion, conflits sur une même cellule, droits lecture ou écriture par feuille, annuler et rétablir par personne, historique des versions, dates affichées à l'heure locale de chacun, import et export CSV). | Voir `data/predictions/P11.md` | k v2-xl 1,77 / 1,75 → **1,76 concordante** ; frontières v3-xl 36 % / 35 % |

| P12 | Du RC au plan du mémoire vérifié (tranche V5, BuildForge) | Un outil qui lit le règlement de la consultation (RC) d'un marché public de travaux, reçu comme le texte de ses pages, et en tire un dossier structuré : les faits du RC (lots, date et heure limites de remise des offres, date limite des questions, procédure, visite du site obligatoire ou non et ses dates, variantes autorisées ou non, durée de validité des offres, mode de remise), les pièces à remettre (candidature, offre ou attributaire ; obligatoire ou non) et les limites de pages du mémoire technique, l'arbre des critères d'attribution et de leurs sous-critères avec leurs pondérations (pourcentages, points ou simple classement, parfois différents selon le lot), le plan du mémoire technique construit sur cet arbre (une section par critère ou sous-critère noté sur la valeur technique, dans l'ordre du RC, avec son poids et sa page source), et un contrôle de conformité (chaque critère technique a sa section, les poids se recoupent, sinon une alerte nommée). Une valeur n'est gardée que si elle est retrouvée dans le texte d'une page ; sinon elle est déclarée non trouvée. Le mémoire lui-même n'est pas rédigé. | Voir `data/predictions/V5.md` | k v2 2,03 / 2,08 → **2,05 concordante** ; frontières v3 0 % / 0 % |
| P13 | Chaos S&OP, niveau 1 « Semaine 1 » (jeu sérieux, prévision par moyenne mobile) | → `data/sondes/P13.md` (la spec du niveau, telle quelle, après « --- ») | Voir `data/predictions/P13.md` | k v2 2,10 / 2,08 → **2,09 concordante** |

Note : dans `data/passes/strict/P04_*` et `P07_*`, le texte des assertions a été abrégé en « a » lors de la recopie. Seuls l'état observé et les conditions sont exacts.

k strict = médiane des passes (SPEC 6.3). Une sonde **floue** (3 passes, écart-type > 0,10) n'est plus mesurée : on creuse sa spec.

## Consigne v2 (règle 5, assertions frontière)

Passes dans `data/passes/strict-v2/`, jamais comparées aux v1.

| ID | k v2 (médiane) | Statut v2 | Frontières (moyenne, part) |
|---|---|---|---|
| P01 | 1,88 | concordante | 2,5 (6 %) |
| P02 | 1,61 | concordante | 4,0 (10 %) |
| P03 | 1,69 | floue | 2,7 (7 %) |
| P04 | 1,90 | concordante | 2,5 (6 %) |
| P05 | 2,48 | floue | 2,7 (7 %) |
| P06 | 2,10 | concordante | 2,5 (6 %) |
| P07 | 1,85 | concordante | 5,0 (15 %) |
| P08 | 1,83 | concordante | 6,0 (16 %) |
| P09 | 2,56 | floue | 2,7 (7 %) |
| P10 | 1,72 | concordante | 6,0 (16 %) |
