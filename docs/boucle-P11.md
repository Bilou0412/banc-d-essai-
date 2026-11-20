# La boucle de compilation sur P11 (20 novembre 2026)

En une phrase : **la boucle fait compiler la spec du tableur. Le taux « spec » passe de 0,14 à 0,82 en 5 itérations, et les divergences dues à des trous passent de 340 à 14 sur 300 situations. Mais le taux brut reste freiné par les bugs des greens, et 0,9 n'est pas atteint.**

Prédiction figée avant la boucle : `data/predictions/boucle-P11.md`. Outils : `outils/boucle.py`, `outils/taux_spec.py`, `outils/maths.py`. Données : `runs-boucle/P11/`.

## 1. Ce que fait la boucle

```
   spec v_i ──► 4 greens NEUFS (2 haiku, 2 sonnet) ──► 300 situations rejouées (même générateur partout)
      ▲                                                        │
      │                                     premier désaccord à 4 → groupe (action + champs qui diffèrent)
      │                                                        │
      │                                       16 plus gros groupes, chacun jugé par 2 juges indépendants
      │                                                        │
      │           ┌──────────── trou (les 2 juges) ────────────┼──── bug ────── à trancher (désaccord)
      │           ▼                                            ▼                     ▼
      └── assertion stricte + test                      noté (puis test de     liste pour toi
          (comportement de la majorité,                  non-régression)       (tu en as tranché 7)
           sinon le plus simple)
```

## 2. Les courbes

Taux par itération. Le **brut** compte une situation comme accord si les deux codes montrent partout la même chose. Le **spec** compte aussi comme accord une situation dont le premier désaccord est un bug jugé (la spec tranchait). Le **taux par action** est la part des actions où deux codes montrent la même chose.

| Itération | Assertions | Taux brut | Taux spec | 4 d'accord (brut) | 4 d'accord (spec) | Taux par action |
|---|---|---|---|---|---|---|
| 0 (lot A) | 159 | 0,089 | 0,100 | 0,013 | 0,027 | 0,680 |
| 0 (lot B) | 159 | 0,167 | 0,182 | 0,047 | 0,063 | 0,737 |
| 1 | 172 | 0,325 | 0,391 | 0,140 | 0,223 | 0,855 |
| 2 | 187 | 0,449 | 0,576 | 0,233 | 0,427 | 0,885 |
| 3 | 190 | 0,551 | 0,722 | 0,340 | 0,643 | 0,909 |
| 4 | 193 | 0,451 | 0,724 | 0,243 | 0,640 | 0,880 |
| 5 | 196 | **0,631** | **0,822** | 0,433 | 0,767 | **0,935** |
| 6 | 200 + 26 tests de bugs | arrêtée (budget) | | | | |

```
 taux
 1,0 ┤                                                      · · · · · · · · · · · ·  seuil 0,9
 0,9 ┤                                              a ·········· a        (a = par action)
 0,8 ┤                                  a                         S
 0,7 ┤                      a                 S          S
 0,6 ┤        a                                                   B
 0,5 ┤                            S                B
 0,4 ┤                 S                     B          B
 0,3 ┤                            B
 0,2 ┤          S
 0,1 ┤  S B
     └──┬──────────┬──────────┬──────────┬──────────┬──────────┬────▶ itération
        0          1          2          3          4          5
        B = brut     S = spec     a = par action      (it0 : moyenne des lots A et B)
```

Ce qu'on voit : **le taux spec monte à chaque itération** (il est plat entre 3 et 4). Le brut monte aussi, sauf à l'itération 4, où un seul green haiku portait 6 groupes de bugs. Par action, on passe 0,9 dès l'itération 3. Par situation (27 actions en moyenne), le moindre écart fait tout perdre, d'où l'écart entre les courbes.

**Deux biais du taux spec, en sens contraires.** Un bug compté comme accord peut cacher un trou derrière lui, ce qui rend le taux un peu **optimiste**. Une divergence dans un groupe non jugé (au-delà des 16 plus gros) reste comptée comme divergence, ce qui le rend un peu **pessimiste**. Le taux par action est un peu pessimiste lui aussi : après le premier écart, les deux codes ne sont plus dans le même état.

## 3. Trous, bugs, à trancher

Groupes jugés (16 par lot) et premières divergences qu'ils expliquent (sur 300 situations) :

| Itération | Trous | Bugs | À trancher | Invalides | Divergences « trou » | Divergences « bug » | Assertions ajoutées | Accord des 2 juges |
|---|---|---|---|---|---|---|---|---|
| 0 (A + B) | 18 | 2 | 8 | 4 | 340 | 9 | 13 | 75 % / 75 % |
| 1 | 9 | 5 | 2 | 0 | 146 | 25 | 7 (+ 8 nouvelles de toi) | 88 % |
| 2 | 4 | 4 | 8 | 0 | 92 | 58 | 3 | 50 % |
| 3 | 4 | 8 | 4 | 0 | 58 | 91 | 3 | 75 % |
| 4 | 3 | 8 | 3 | 2 | 13 | 119 | 3 | 81 % |
| 5 | 4 | 8 | 4 | 0 | 14 | 100 | 4 | 75 % |

- **Trous** : 41 assertions ajoutées en tout (C01 à C41). 12 viennent de tes décisions : 8 nouvelles (C21 à C28), 2 réécrites (C07, C15) et 2 confirmées (C10, C14). A99 est aussi réécrite. La spec passe de 159 à 200 assertions. La suite de tests passe de 252 à 362 tests.
- **Bugs** : 26 bugs jugés aux itérations 0 à 5 sont devenus 26 tests de non-régression (`test_app_reg6.py`). Leur effet n'a pas pu être mesuré : l'itération 6 a été arrêtée (§8).
- **À trancher** : 33 groupes en tout. Tu en as tranché 7 cas à l'itération 1. La part de désaccord entre juges monte quand il ne reste que des conventions fines (50 % à l'itération 2).
- **Les ajouts créent des trous** (pari 5 de la prédiction : tenu). C15, ajouté à la majorité, contredisait P1. Un test de C17 attendait l'ancien C07. Le red a écarté un ajout qui contredisait C03, et un autre qui contredisait A50.

## 4. Principes contre cas isolés

Un juge a relu les 48 groupes des itérations 0 et 1 et dit lesquels P1 ou P2 tranchent **à eux seuls** :

| | Groupes | Divergences expliquées |
|---|---|---|
| P1 (une action sans effet ne laisse aucune trace) | 6 | 136 |
| P2 (annuler avant ou après confirmation) | 3 | 33 |
| **P1 + P2** | **9 sur 48** | **169 sur 704 (24 %)**, et **82 sur 185 (44 %) à l'itération 1** |
| Cas isolés | 39 sur 48 | 535 |

- **Deux phrases de toi valent 9 groupes de cas isolés, et le quart des divergences.** Les deux plus gros groupes de l'itération 1 (37 et 34 divergences, « effacer une cellule déjà vide ») avaient été tranchés à la majorité des greens dans le sens **contraire** de P1. **La majorité des codes n'est pas un bon arbitre pour une convention** : un principe l'a renversée.
- Sur les 41 assertions ajoutées, 8 portent P1 ou P2 (C07, C15, C21 à C26) et 33 sont des cas isolés.

## 5. Décisions IA contre questions client (H22)

Un juge froid a classé les 41 assertions ajoutées : **convention** (une IA compétente peut trancher seule) ou **client** (deux clients raisonnables voudraient des choses différentes).

| | Convention | Client |
|---|---|---|
| Ajoutées par la boucle (majorité des greens) | 23 | **6** : C04, C18, C29, C30, C33, C36 |
| Tranchées ou réécrites par toi (C07, C10, C14, C15, C21 à C28) | 12 | 0 |
| **Total** | **35 (85 %)** | **6 (15 %)** |

- **85 % des trous sont des conventions.** C'est la part que l'IA peut trancher sans toi.
- **Les 6 questions client ont toutes été tranchées à la majorité des greens, sans te les poser.** Exemples : qui reçoit quels droits sur une feuille ajoutée (C29), le propriétaire qui se retire son propre droit (C33). C'est le défaut le plus net de la boucle. Elle n'a pas de porte qui envoie au client ce qui dépend de lui. Le protocole a déjà cette règle (§4, « qui répond à quoi »), mais la boucle ne l'applique pas.
- **Le juge et toi n'êtes pas d'accord sur un cas.** Tu avais classé le cas 2 (une personne en lecture seule résout un conflit) en « question client (droits) ». Le juge le range en convention, parce que la règle « toute écriture refusée donne la même alerte » se déduit du reste. La frontière entre convention et client est elle-même une question à instrumenter.

## 6. Lecture mathématique (`outils/maths.py`, sans appel de modèle)

### 6.1 Divergence par action : le modèle taux ≈ e^(−λp) tient

λ = 27,1 actions par situation. p estimé = −ln(taux)/λ ; p mesuré = premières divergences ÷ actions jouées jusqu'à la première divergence incluse.

| Itération | −ln(taux brut) | p estimé | p mesuré | Taux prédit par p mesuré | Taux observé | p estimé (spec) |
|---|---|---|---|---|---|---|
| 0 A | 2,42 | 0,089 | 0,088 | 0,092 | 0,089 | 0,085 |
| 0 B | 1,79 | 0,066 | 0,065 | 0,170 | 0,167 | 0,063 |
| 1 | 1,12 | 0,042 | 0,040 | 0,343 | 0,325 | 0,035 |
| 2 | 0,80 | 0,030 | 0,029 | 0,462 | 0,449 | 0,020 |
| 3 | 0,60 | 0,022 | 0,021 | 0,567 | 0,551 | 0,012 |
| 4 | 0,80 | 0,029 | 0,028 | 0,468 | 0,451 | 0,012 |
| 5 | 0,46 | 0,017 | 0,017 | 0,640 | 0,631 | 0,007 |

**Écart entre p estimé et p mesuré : moins de 5 % à chaque itération.** Pour le banc : **le taux par situation n'est qu'un p par action vu à travers la longueur des situations.** Pour atteindre 0,9 sur 27 actions, il faut p ≤ 0,004. On est à 0,017 en brut et à **0,007 en spec**. La partie « spec » de p a été divisée par 12, la partie « bugs » stagne autour de 0,01.

### 6.2 Relaxation de la boucle

Ajustement −ln(taux) = a·e^(−b·i) + c, sur 6 points (itérations 0 à 5, l'itération 0 en moyenne des lots A et B). **C'est peu de points : ordres de grandeur seulement.**

| | a | b | Demi-vie ln2/b | Plancher c | Taux maximal e^(−c) |
|---|---|---|---|---|---|
| Brut | 1,52 | 1,01 | 0,7 itération | 0,58 | **0,56** |
| Spec | 1,78 | 0,88 | 0,8 itération | 0,22 | **0,81** |

- Pour le banc : la boucle relaxe vite, et la moitié du chemin est faite à chaque itération. Mais **elle relaxe vers un plancher**. En brut, ce plancher (0,56) est même dépassé par l'itération 5 (0,63), parce que l'itération 4 tire l'ajustement vers le bas. En spec, le plafond est d'environ 0,8, et l'itération 5 y est déjà.
- **Le plancher brut vient des bugs** : chaque lot neuf fait les siens, et la boucle ne les corrigeait pas. Les tests de bugs (itération 6) devaient le faire baisser. **Ce n'est pas mesuré**, puisque l'itération 6 a été arrêtée.
- Le plancher spec vient de la longue traîne des trous rares (§6.3) et des cas à trancher laissés ouverts.

### 6.3 Trous non vus

Pour chaque trou distinct (38 en tout ; à l'itération 0, un trou vu par A et par B ne compte qu'une fois) : combien de greens le comblent autrement que la majorité.

| Vu par… | 1 green | 2 greens | 3 greens |
|---|---|---|---|
| Trous | 28 | 6 | 4 |

- **Loi bêta-binomiale** (tronquée en zéro, 4 greens) : l'ajustement part à la borne de la grille (α = 0,05, β = 3,5). Il en tire N ≈ 900 trous, **un chiffre que je ne retiens pas**. Avec 3 valeurs et 28 singletons sur 38, la loi n'est pas identifiable. Ce qu'elle dit de solide : la visibilité des trous est très inégale, la plupart ne sont vus que par un green.
- **Chao1** : N ≈ S_obs + f1²/(2·f2) = 38 + 28²/12 ≈ **103 trous au total**. La boucle en a fermé 41.
- **Capture-recapture de l'itération 0** : (11+1)(7+1)/(4+1) − 1 ≈ **18 trous**. C'est une forte sous-estimation, puisque la boucle en a fermé 41. Les trous ne sont pas tous aussi faciles à voir, et la première divergence masque ceux qui sont derrière.
- **Good-Turing**, P(la prochaine observation tombe sur un trou jamais vu) ≈ f1/n, avec les groupes non jugés comptés comme trous candidats :

  | Itération | 0 A | 0 B | 1 | 2 | 3 | 4 | 5 |
  |---|---|---|---|---|---|---|---|
  | f1 / n | 16/292 | 16/241 | 31/233 | 9/172 | 21/107 | 22/91 | 25/70 |
  | ≈ | 0,055 | 0,066 | 0,133 | 0,052 | 0,196 | 0,242 | **0,357** |

  **Il monte au lieu de baisser.** La boucle ferme les gros trous, donc n fond (292, puis 70). Les trous rares vus une seule fois restent, environ 20 à 25 par itération. Par situation (f1/300), on stagne entre 5 et 8 %. Pour le banc : **il reste une longue traîne de trous rares**, et f1/n n'est pas un bon critère d'arrêt tel quel. Une réserve : une partie des singletons non jugés sont sûrement des bugs, ce qui surestime f1.

### 6.4 Corrélation des greens

Pour une paire (a, b), la référence est l'accord des deux autres greens. ρ = φ entre « a s'écarte de la référence » et « b s'en écarte dans le même sens ». Toutes les actions jouées sont comptées, pas seulement celles où quelqu'un s'écarte, ce qui forcerait ρ < 0.

| Paire | ρ |
|---|---|
| haiku-haiku (H1-H2) | 0,33 |
| sonnet-sonnet (S1-S2) | **0,67** |
| haiku-sonnet (4 paires) | **0,10** |

n_eff = n/(1+(n−1)ρ), pour 4 greens : **4 sonnet ≈ 1,3 green indépendant**, 4 haiku ≈ 2,0, **le lot mixte ≈ 2,4** (ρ moyen 0,23). Pour le banc : **deux sonnet se trompent ensemble**, et mélanger les modèles réduit nettement ρ. Pour voir plus de trous, il vaut mieux plus de **familles** de greens que plus de greens.

## 7. Verdicts

- **H20b** (l'union des trous de N greens se répète d'un lot à l'autre) : **réfutée.** Lot A : 11 trous, lot B : 7, 4 en commun, **Jaccard 0,29** pour un critère ≥ 0,5 (j'avais prédit 0,45). La cause est mesurée plus haut : visibilité très inégale (28 trous sur 38 vus par un seul green), et seulement environ 2,4 greens indépendants par lot.
- **H21** (la boucle fait monter le taux à chaque itération) : **confirmée pour la spec, pas pour le brut.**
  - Le taux spec monte 5 fois sur 5 (+0,002 seulement entre 3 et 4) : 0,14, 0,39, 0,58, 0,72, 0,72, 0,82.
  - Les divergences dues aux trous baissent à chaque fois : 340, 146, 92, 58, 13, 14.
  - Le brut baisse une fois (0,55, puis 0,45, à l'itération 4) à cause des bugs d'un green.
  - Ma prédiction figée (0,20, 0,35, 0,50) était trop prudente. Le modèle exp(−M) du complément (0,30, 0,55, 0,74, 0,86) suit le taux spec jusqu'à l'itération 3, puis le dépasse.
  - **0,9 n'est pas atteint** (0,82 en spec, 0,63 en brut). Seul le taux par action le dépasse (0,935).
- **H22** (la plupart des trous sont des conventions que l'IA peut trancher seule) : **retenue, avec un défaut mesuré.** 35 conventions sur 41 (85 %, pour un seuil de 70 % fixé maintenant, donc « non validé »). Mais les 6 questions client ont été tranchées par la majorité des codes sans passer par toi.
- **Juges** : accord moyen de 74 % (prédit ≥ 75 %). Tenu sur 5 lots sur 7, il tombe à 50 % à l'itération 2.

## 8. Coût

| Itération | 0 | 1 | 2 (avec tes décisions) | 3 | 4 | 5 | 6 (arrêtée) | Analyses | **Total** |
|---|---|---|---|---|---|---|---|---|---|
| $ | 10,32 | 8,61 | 12,75 | 8,22 | 10,87 | 9,94 | 7,68 | 0,16 | **68,55** |

Une itération coûte environ **10 $** : 4 greens (environ 5 $), 32 appels de juge (environ 4 $), écriture des ajouts (environ 1 $).

L'itération 6 contient 6 $ **estimés**. Avec 362 tests, le premier tour de trois greens a dépassé le délai de 30 minutes par appel. Un appel coupé ne rend pas son coût, mais il est dépensé. Elle a été arrêtée pour rester sous ta limite de 75,80 $. **Leçon : le délai par appel doit grandir avec la suite de tests.**

## 9. Ce qu'il faut retenir, simplement

1. **Une spec peut se compiler par itérations.** En 5 tours, la part des situations où deux codes font la même chose, quand on retire leurs bugs, passe de 14 % à 82 %. Chaque tour fait la moitié du chemin restant.
2. **Le mur suivant, ce sont les bugs, pas la spec.** Quand la spec est presque fermée, ce qui reste ce sont des erreurs de construction, que la spec tranche déjà mais qu'aucun test ne vérifie. Transformer chaque bug en test est la bonne réponse. Son effet n'est pas encore mesuré.
3. **Un principe vaut dix cas.** P1 et P2 ont tranché 24 % des divergences. Un principe pose la question au bon niveau : le client donne une règle, pas une réponse.
4. **La majorité des codes tranche bien une convention, mais elle peut se tromper (C15), et elle ne doit pas trancher une question client.** 6 de ces questions sont passées sans toi.
5. **Il reste une traîne de trous rares** (Chao1 ≈ 103, pour 41 fermés). Pour la voir, il faut des greens qui se trompent différemment : changer de modèle vaut mieux qu'ajouter des greens du même modèle.

## 10. Ce que je ferais ensuite

- **Mesurer l'effet des tests de bugs**, la question laissée ouverte par l'itération 6 : un seul lot sur v6, délai de 60 minutes par appel, environ 10 $.
- **Ajouter à la boucle la porte « question client »** : avant d'écrire une assertion, un juge classe le trou (convention ou client), et seul « client » remonte au client. C'est le §4 du protocole, appliqué à la boucle.
- **Poser des principes plutôt que des cas** : regrouper les trous à trancher par principe candidat avant de les montrer (piste M3 de `docs/pistes.md`).
- Le plan V5 proprement dit (2 pistes au maximum) est proposé à part.

## Fichiers

- `outils/boucle.py` : la boucle (init, lot, analyser, apparier, ajouter, decider, bugs, iteration, bilan).
- `outils/taux_spec.py` : taux brut, spec et par action → `runs-boucle/P11/taux.json`.
- `outils/maths.py` : la lecture mathématique → `runs-boucle/P11/maths.json`.
- `runs-boucle/P11/it<i>/` : spec.json, tests/, lots/A (greens, groupes.json, accord.json ; traces non versionnées), decisions.json, ajouts.md. Plus `it0/h20b.json` et `it2/arbitre.json` (tes décisions).
- `runs-boucle/P11/principes-P1-P2.json`, `h22.json`, `budget.jsonl`.
