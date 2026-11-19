# V2 : la répartition découpe / exécution (19 novembre 2026)

En une phrase : **la part de découpe ne suit pas k, elle suit le nombre de tours d'exécution.** La moitié « frontières » de H18 va dans le bon sens, la moitié « k » non.

## 1. Champ local compté par cause (`outils/causes.py`)

Une cause = un message d'erreur, une fois normalisé : première ligne, adresses mémoire effacées. Même message = même cause. Le champ local d'une assertion devient le nombre de causes distinctes rencontrées avant qu'elle passe (0 si elle passe du premier coup).

Recalcul de `runs-v1` :

| Sonde | Avant (tours cassés + 1) | Après (causes) | Causes distinctes |
|---|---|---|---|
| P05 Blog | 1,00 | **0,00** | 0 |
| P08 Éditeur | 1,03 | **0,03** (frontière 0,00 / autres 0,03) | 1 : permissions livrées dans le désordre |
| P10 Chat | 3,00 | **1,00** (frontière 1,00 / autres 1,00) | 1 : `collection failure` (l'import de la bibliothèque crypto) |

Le « 3,00 » du chat était donc **une seule panne vue deux fois sur 62 tests**. Avec les causes, le chat reste devant, mais à 1 et non plus à 3.

Le duel renvoie maintenant au green la vraie erreur, et non plus « collection failure ». Le compte par cause est fait à la fin de chaque duel.

## 2. Passes v2 pour toutes les sondes

| Sonde | k des passes v2 | k retenu (médiane) | Statut | Frontières par passe | Moy. | Part |
|---|---|---|---|---|---|---|
| P01 Contacts | 1,82 / 1,95 | 1,88 | concordante | 3 / 2 | 2,5 | 6 % |
| P02 Recettes | 1,54 / 1,68 | 1,61 | concordante | 3 / 5 | 4,0 | 10 % |
| P03 Inventaire | 1,63 / 1,92 / 1,69 | 1,69 | **floue** (écart-type 0,15) | 3 / 2 / 3 | 2,7 | 7 % |
| P04 Todo | 1,90 / 1,90 | 1,90 | concordante | 3 / 2 | 2,5 | 6 % |
| P05 Blog | 2,18 / 2,56 / 2,48 | 2,48 | **floue** (0,20) | 3 / 3 / 2 | 2,7 | 7 % |
| P06 Pomodoro | 2,10 / 2,10 | 2,10 | concordante | 2 / 3 | 2,5 | 6 % |
| P07 Notes hors ligne | 1,80 / 1,91 | 1,85 | concordante | 3 / 7 | 5,0 | 15 % |
| P08 Éditeur | 1,87 / 1,79 | 1,83 | concordante | 6 / 6 | 6,0 | 16 % |
| P09 Réservation | 2,33 / 2,56 / 3,11 | 2,56 | **floue** (0,40) | 3 / 3 / 2 | 2,7 | 7 % |
| P10 Chat | 1,72 / 1,68 / 1,81 | 1,72 | concordante | 6 / 5 / 7 | 6,0 | 16 % |

7 sondes concordantes, 3 floues. P09 reste floue, et encore plus qu'en v1 (écart-type 0,40 contre 0,15) : une passe à 3,11 est la plus haute jamais mesurée.

**À noter :** le **nombre de frontières n'est pas toujours reproductible**. P07 en a 3 dans une passe et 7 dans l'autre, P02 3 et 5. Il l'est sur P08 (6 / 6) et P10 (6 / 5 / 7).

## 3. H15 en grand : trous a priori sans exécution

Seulement l'attaque 1 du red (opus), sans green, sur la passe A v2. Même consigne que l'attaque 1 du V1, dont les valeurs sont reprises pour P08 et P10.

| Sonde concordante | k | Trous a priori | Assertions | Par assertion | Rang k | Rang trous |
|---|---|---|---|---|---|---|
| P02 Recettes | 1,61 | 7 | 39 | 0,18 | 1 | 1 |
| P10 Chat | 1,72 | 9 | 36 | 0,25 | 2 | 3 |
| P08 Éditeur | 1,83 | 13 | 38 | 0,34 | 3 | 6 |
| P07 Notes | 1,85 | 8 | 35 | 0,23 | 4 | 2 |
| P01 Contacts | 1,88 | 21 | 39 | **0,54** | 5 | 7 |
| P04 Todo | 1,90 | 12 | 40 | 0,30 | 6 | 4 |
| P06 Pomodoro | 2,10 | 13 | 40 | 0,33 | 7 | 5 |

**Spearman ρ = +0,54 sur 7 points**, avec p ≈ 0,12 en unilatéral (test exact par permutation). Le sens est positif, mais pas significatif. P01 (contacts) est le point qui casse l'ordre : 21 trous pour un k moyen.

Avec les 3 sondes floues ajoutées (P03 0,37, P05 0,37, P09 0,21), on tombe à ρ = +0,12 sur 10 points. Les sondes floues brouillent le lien : c'est logique, puisque leur k n'est pas fiable.

Limite : chaque compte vient d'**une seule** attaque du red. On ne sait pas encore si deux reds trouvent le même nombre de trous, comme on l'a vérifié pour k avec H13.

## 4. Les trois duels complets (H18)

Même réglage que le V1 : red opus avec deux attaques, green haiku, juge opus, mécanismes frontière réels, causes comptées, vraie erreur renvoyée au green. P09 étant floue, la sonde à k haut est **P06**, la plus haute concordante.

| Sonde | k | Frontières (passe A) | Tours | Causes | Trous a priori (2 attaques) | Tokens découpe | Tokens exécution | **Part découpe** |
|---|---|---|---|---|---|---|---|---|
| P02 Recettes (k bas) | 1,61 | 3 | 2 | 0 | 15 | 100 k | 192 k | **34 %** |
| P07 Notes (moyenne) | 1,85 | 3 | 2 | 0 | 25 | 125 k | 337 k | **27 %** |
| P06 Pomodoro (k haut) | 2,10 | 2 | 3 | 1 trou | 14 | 109 k | 303 k | **27 %** |

Avec les trois duels du V1, même réglage à l'erreur renvoyée près :

| Sonde | k | Frontières | Tours | Part découpe |
|---|---|---|---|---|
| P05 Blog (floue) | 2,48 | 3 | 2 | 40 % |
| P08 Éditeur | 1,83 | 6 | 3 | 23 % |
| P10 Chat | 1,72 | 6 | 4 | 24 % |

Corrélations de rang :

| Part de découpe face à… | 6 duels | 5 concordants (sans le blog) |
|---|---|---|
| k | +0,31 | **−0,20** |
| frontières | **−0,56** | **−0,63** |
| nombre de tours | **−0,83** | |

## 5. La carte

k en hauteur, frontières (moyenne des passes v2) en largeur. Chaque sonde porte sa part de découpe quand elle a eu un duel, et `·` sinon. Les floues sont entre crochets.

```
  k
 2,6 ┤ [P09 ·]
 2,5 ┤ [P05 40 %]
 2,4 ┤
 2,3 ┤
 2,2 ┤
 2,1 ┤  P06 27 %
 2,0 ┤
 1,9 ┤  P04 ·  P01 ·
 1,8 ┤                              P07 27 %        P08 23 %
 1,7 ┤ [P03 ·]                                       P10 24 %
 1,6 ┤                  P02 34 %
     └──┬───────────────┬───────────┬───────────────┬──────▶ frontières
       2,5             4,0         5,0             6,0
```

Ce qu'on voit : **la découpe pèse plus à gauche (peu de frontières) qu'à droite (beaucoup)**. En hauteur, il n'y a pas de pente nette : P02, la sonde la plus basse, a une part de 34 %, et P06, la plus haute des concordantes, 27 %.

## 6. H16 : une sonde floue face à une concordante de k proche

| Paire | k | Statut | Trous a priori / assertion |
|---|---|---|---|
| **P03** Inventaire | 1,69 | floue | **0,37** |
| **P10** Chat | 1,72 | concordante | 0,25 |
| (P02 Recettes) | 1,61 | concordante | 0,18 |

C'est **une paire valable** (écart de k 0,03) : la sonde floue a 1,5 fois plus de trous a priori que sa voisine concordante, comme le prédit H16. Ce n'est qu'une paire, donc une anecdote, pas un résultat.

Les deux autres floues, P05 (2,48) et P09 (2,56), n'ont pas de concordante proche : la plus haute est P06 à 2,10.

## 7. Verdicts

- **H15** (trous a priori suivent k) : **ρ = +0,54 sur 7 sondes concordantes, p ≈ 0,12.** Le sens tient pour la 3e fois, mais ce n'est pas significatif. Elle reste à discuter, et il faut mesurer la reproductibilité du compte du red.
- **H16** (floue → spec ambiguë) : une seule paire de k proche, **P03 floue 0,37 contre P10 concordante 0,25 trou par assertion**. Dans le sens prédit, sur un point.
- **H17** (frontières → difficulté technique) : 6 duels, 2 causes en tout, et une seule sur une sonde riche en frontières (le chat). Le champ local par cause vaut 0 à 0,03 partout sauf sur le chat (1,00). Elle **ne tient pas comme loi** : l'éditeur (6 frontières) a 0,03, comme P06 (2 frontières).
- **H18** (part de découpe ↑ avec k, ↓ avec les frontières) : **moitié tenue, moitié non.**
  - Frontières : ρ = −0,56 sur 6 duels et −0,63 sur 5 concordants, **dans le sens prédit**.
  - k : ρ = +0,31 sur 6, mais **−0,20 sur les 5 concordants**. Le +0,31 tient au seul blog, qui est flou. Sans lui, le signe s'inverse.
  - Le facteur le plus fort n'était pas dans la thèse : le **nombre de tours** (ρ = −0,83). Chaque tour d'exécution ajoute des tokens au green, alors que la découpe est payée une fois.

## 8. Ce qu'il faut retenir, simplement

1. **Ce qui décide la répartition, c'est le nombre d'allers-retours avec le code, pas la densité des règles.** La découpe est un coût presque fixe (87 à 172 k tokens pour deux attaques). L'exécution grossit à chaque tour raté.
2. **Les frontières annoncent ces allers-retours, en partie.** Les deux sondes à 6 frontières ont 3 et 4 tours et les plus petites parts de découpe. Mais P06, avec 2 frontières, a aussi 3 tours : le lien est loin d'être net. C'est la piste la plus prometteuse pour la règle de répartition : « beaucoup de frontières → réserver du budget pour l'exécution ».
3. **k sert à autre chose.** Il suit (faiblement) les trous trouvés avant le code, pas le coût total. On pourrait reformuler H18 : k dit combien coûte la découpe, les frontières disent combien coûte l'exécution.
4. **Les échecs restent trop rares** : 2 causes sur 6 duels. Tant que haiku réussit presque tout du premier coup, le champ local ne peut rien dire.

## 9. Coûts de cette étape

16 passes v2 (~3,70 $), 7 attaques a priori seules (~4,20 $), 3 duels (P02 1,34 $, P07 1,86 $, P06 1,49 $). **Total ~12,60 $.** Les tokens d'opus et de haiku ne coûtent pas la même chose : on compare les tokens, pas les dollars.

## Fichiers

- `data/passes/strict-v2/` : toutes les passes v2.
- `runs-v2-apriori/<sonde>/` : attaque 1 seule (tests, lacunes, bilan).
- `runs-v2/<sonde>/` : duels complets P02, P06, P07.
- `outils/causes.py` : comptage par cause, rejouable sur n'importe quel duel.
