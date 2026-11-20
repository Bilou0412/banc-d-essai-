# Prédiction figée : la boucle de compilation sur P11 (H20b, H21)

Écrite le 20/11/2026 **avant la 1re itération** (règle 2 du labo). Le commit qui ajoute ce fichier en fait foi. Un écart se note à côté, jamais à la place. Aucun seuil ci-dessous n'est validé (règle 6).

## Ce qu'on mesure

- **Taux moyen** : moyenne des taux de compilation des 6 paires d'un lot de 4 greens (2 haiku, 2 sonnet), sur les mêmes 300 situations (même générateur à toutes les itérations).
- **Accord à 4** : part des situations où les 4 greens montrent partout la même chose.
- **Trous distincts** : groupes de divergences classés « trou » par **les deux** juges, après dédoublonnage (un même trou vu par plusieurs actions compte une fois), soit le nombre d'assertions ajoutées à la spec.
- Point de départ connu (lot A = les 4 greens de V4, spec v0) : taux moyen **0,089**, accord à 4 **1,3 %**.

## Prédiction chiffrée

| Itération | Spec | Taux moyen attendu | Accord à 4 | Trous distincts |
|---|---|---|---|---|
| 0 | v0 (159 assertions) | 0,09 (lot B entre 0,05 et 0,15) | ≤ 3 % | ~15 par lot, ~20 pour l'union A ∪ B |
| 1 | v1 = v0 + trous de l'itération 0 | **0,20** (0,12 à 0,35) | ~5 % | ~14 |
| 2 | v2 | **0,35** | ~12 % | ~9 |
| 3 | v3 | **0,50** | ~25 % | ~6 |

Pourquoi une montée lente : on ne regarde que la **première** divergence de chaque situation. Fermer un trou démasque ceux qui étaient derrière lui dans les mêmes situations. Chaque itération en révèle donc de nouveaux, moins nombreux.

## Paris à trancher

1. **H21** tient si le taux moyen monte à chaque itération ET si les trous distincts baissent. Je prédis qu'elle tient sur les itérations que le budget permet.
2. **Le seuil 0,9 ne sera pas atteint dans le budget de 40 $.** Estimation : environ 12 $ pour l'itération 0 (lot B neuf, deux lots jugés deux fois), puis environ 9 $ par itération. Cela fait 3 itérations au plus.
3. **H20b** : Jaccard des unions de trous lot A / lot B sur v0 ≈ **0,45**. Je prédis donc qu'elle **échoue de peu** au critère ≥ 0,5. Raison : 4 greens ne couvrent qu'une partie des façons de combler chaque trou, et la première divergence masque les autres.
4. **Juges** : les deux juges sont d'accord sur ≥ 75 % des groupes. Le reste part en « à trancher ».
5. **Effet de bord** : des assertions ajoutées créent de nouveaux trous (ce qu'elles disent croise d'autres règles). Je m'attends à en voir au moins 1 par itération.

## Complément (20/11, avant la fin de l'itération 0, aucune donnée de la boucle vue)

Bilel lève la limite de 40 $ et demande combien d'itérations pour atteindre 0,9. Modèle simple : le taux d'une paire ≈ exp(−M), où M est la « masse de trous » qu'une situation rencontre. Au départ, M ≈ 2,4 (taux 0,09). Pour 0,9, il faut M ≈ 0,1, soit 23 fois moins. Si chaque itération enlève environ la moitié de la masse (elle ferme les gros trous, mais en démasque et en crée d'autres) :

| Itération | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| Taux moyen (modèle) | 0,09 | 0,30 | 0,55 | 0,74 | 0,86 | 0,93 |

Ce modèle est plus optimiste que le tableau du haut, qui reste la prédiction figée. Les deux sont notés : la boucle dira lequel est le plus proche. Attendu : **0,9 vers l'itération 5, pour environ 55 à 60 $ en tout**. Si chaque itération n'enlève qu'un tiers de la masse, il faut 8 itérations, soit environ 85 $. La courbe a une forme de S en taux : la montée paraît s'accélérer, puis elle sature près de 1.
