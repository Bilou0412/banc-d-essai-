# V4 : la spec compile-t-elle ? (20 novembre 2026)

En une phrase : **sur une grosse spec, deux codes qui passent tous les mêmes tests ne se comportent pareil que dans 2 à 16 % des situations.** Le taux de compilation est le chiffre le plus parlant du banc à ce jour, mais H20, telle qu'elle est écrite, ne tient pas : deux paires de greens ne voient pas les mêmes trous.

## 1. Ce qui a été enregistré (tes décisions)

- **Cap** en tête de `CLAUDE.md` : « une spec compilable », mesurée par le taux de compilation.
- **Règle 7** : v2 pour k, v3 pour les frontières, deux séries jamais mélangées. Critère frontières : écart de part ≤ 10 points, « non validé ».
- **Règle 8** : les trous du red ne sont plus des données.
- **H20** ajoutée à `docs/theses.md`, section 6.4 bis « Test différentiel » dans `docs/SPEC-banc.md`.

## 2. L'outil : `outils/differentiel.py`

```
   spec ──► red ──► générateur de situations (suites d'actions valides, tirées au hasard)
     │
     ├──► green H1 (haiku) ──┐
     ├──► green H2 (haiku) ──┤   chaque green tourne jusqu'à ce que tous les tests passent
     ├──► green S1 (sonnet) ─┤
     └──► green S2 (sonnet) ─┘
                              ▼
          300 situations rejouées sur chaque code (deux fois : un code non déterministe est écarté)
                              ▼
          même résultat observable ?  oui → « compile »   non → divergence
                              ▼
          divergences groupées par action ; le juge classe un représentant : trou / bug X / bug Y / invalide
```

**Taux de compilation** = situations où les deux codes montrent exactement la même chose ÷ situations jouées.

Un outil de plus, `outils/quatre.py`, regarde les 4 greens ensemble : à la première étape où ils ne sont plus d'accord, qui s'écarte seul, et sur quelle action.

## 3. Réglage sur P02 (recettes, 39 assertions, 104 tests)

Les 4 greens passent 104 tests sur 104 dès le 1er tour.

| Paire | Taux de compilation | Ce que le juge a classé |
|---|---|---|
| H1-S1 | **0,983** | 1 trou |
| S1-S2 | **0,983** | 1 trou |
| H1-S2 | 0,967 | 2 trous |
| H1-H2 | 0,263 | 1 trou, 1 invalide |
| H2-S1 | 0,263 | 1 trou, 1 invalide |
| H2-S2 | 0,253 | 2 trous, 1 invalide |

- Tous les 4 d'accord sur 76 situations sur 300 ; au moins 3 sur 4 d'accord sur 293.
- Quand ils divergent, c'est **toujours 3 contre 1** : H2 seul (219 fois), S2 seul (5 fois).
- 4 trous en tout, chacun porté par un seul green qui s'écarte :
  - H2 refuse de cocher un article absent de la liste (194 divergences). Le juge l'a dit « invalide », c'est discutable : la spec ne dit pas si l'action est permise ;
  - H2 sur un ingrédient ajouté deux fois sous le même nom ;
  - H1 sur l'arrondi quand une recette est ajoutée deux fois aux courses ;
  - S2 sur la casse du nom dans la suppression d'un ingrédient.

Leçon de réglage : **une paire ne voit un trou que si ses deux greens l'ont comblé différemment.** H1-S1 et H2-S2 trouvent 1 et 2 trous, 0 en commun. Ce n'est pas que l'outil est bruité : chaque paire regarde une autre fente.

## 4. La grosse sonde P11 : tableur collaboratif hors ligne

Choisie parce qu'elle mêle les deux difficultés : formules liées, cycles, droits par feuille, annuler par personne, historique, hors ligne avec fusion et conflits, fuseaux horaires, CSV. Prédiction figée **avant** les passes : `data/predictions/P11.md` (commit fbd597c).

### 4.1 Passes, comparées à la prédiction

| | Prédit | Observé | |
|---|---|---|---|
| k (v2-xl) | ≥ 2,2, probablement floue | **1,77 / 1,75 → 1,76, concordante** | ✗ raté |
| Part de frontières (v3-xl) | ≥ 50 % | **36 % / 35 %** (57 sur 158, 54 sur 154) | ✗ raté |
| Écart de part entre passes | ≤ 10 points | **1 point** | ✓ le critère tient |

J'ai surestimé la densité et les frontières. Un tableur, ce sont beaucoup d'assertions simples (une formule, une valeur) autour de quelques mécanismes lourds. Bonne nouvelle pour les instruments : **k et la part de frontières se répètent à 159 assertions**, et le critère « ≤ 10 points », fixé après les données en V3, tient sur la première sonde vue après lui.

### 4.2 Le duel complet (passe A v2-xl, red opus, green haiku, juge opus)

| | P11 | Duels V1-V2 (35 à 40 assertions) |
|---|---|---|
| Assertions / tests à la fin | 159 / 252 | 35-40 / 60-110 |
| Tours | **4** | 2 à 4 |
| Échecs | 3 bugs, 2 trous | 0 à 2 |
| Causes distinctes | 5 | 0 à 1 |
| Tokens découpe | **217 k** | 87 à 172 k |
| Tokens exécution | **1 015 k** | 132 à 565 k |
| Part de découpe | **17,6 %** | 23 à 40 % |

Les 4 assertions qui ont cassé (A26, A27, A34, A135 : références après renommage d'une feuille, formules) **ne sont pas des frontières**. Le champ local par cause vaut 0,00 sur les frontières, 0,03 ailleurs.

### 4.3 Le test différentiel sur P11

Les 4 greens passent les 252 tests (S1 et S2 au 1er tour, H2 au 3e, H1 est le green du duel).

| Paire | Taux de compilation | Classes (12 groupes jugés) |
|---|---|---|
| H2-S1 | **0,163** | 11 trous, 1 bug H2 |
| S1-S2 | 0,143 | 10 trous, 2 bugs S2 |
| H2-S2 | 0,123 | 12 trous |
| H1-S2 | 0,050 | 8 trous, 1 bug H1, 2 bugs S2, 1 invalide |
| H1-S1 | 0,037 | 9 trous, 2 bugs H1, 1 bug S1 |
| H1-H2 | **0,020** | 11 trous, 1 bug H1 |

- **Tous les 4 d'accord : 4 situations sur 300 (1,3 %)**, contre 76 sur 300 (25 %) sur P02. Prédiction 5 (« P11 < P02 ») : ✓, et de loin.
- Même deux sonnet (S1-S2) ne s'accordent que sur 14 % des situations, contre 98 % sur P02.
- Premier désaccord à 4 : 3 contre 1 dans 240 cas, 2 contre 2 dans 24, 2-1-1 dans 32. Celui qui s'écarte seul : H1 (131), H2 (61), S2 (25), S1 (23).
- En regroupant les doublons (un même trou vu par plusieurs actions), **environ 15 trous distincts** sur l'union des 6 paires, et chaque paire en voit 5 à 8. Exemples :
  - quel droit ont les autres sur une feuille qu'on vient d'ajouter (A38) ;
  - « annuler » est-il disponible juste après l'ajout d'une feuille (A104) ;
  - une date-heure saisie garde-t-elle le texte tapé ou devient-elle une date normalisée avec fuseau (A30, A61) ;
  - un import CSV compte-t-il une ou plusieurs modifications en attente ;
  - le renommage d'une feuille entre-t-il dans l'historique (A119) ;
  - à l'export CSV, une ligne courte garde-t-elle ses champs vides (A136).
- **Des bugs que 252 tests n'avaient pas vus.** H1 garde un compteur de modifications en attente à 1 après une résolution de conflit en ligne (A89). Le juge le dit « bug H1 » dans 3 paires sur 3 pour le même cas chez bob. S2 a un défaut voisin sur annuler (A89, 2 paires).
- **Le juge n'est pas parfaitement constant.** La même divergence de H1 sur `alice.resolve_conflict` est classée « bug H1 » une fois et « trou » deux fois.

### 4.4 Deux paires voient-elles les mêmes trous ? (critère de H20)

| Appariement | Trous paire 1 | Trous paire 2 | En commun | Jaccard |
|---|---|---|---|---|
| P02 : H1-S1 / H2-S2 | 1 | 2 | 0 | **0,00** |
| P11 : H1-S1 / H2-S2 | 9 | 12 | 2 (le même trou des dates, vu deux fois) | **0,105** |
| P11 : H1-H2 / S1-S2 | 11 | 10 | 2 | **0,105** |

**Le critère échoue.** Ce n'est pas du bruit au sens du red (deux reds qui voient des choses différentes sur le même texte). C'est structurel : une paire ne voit que les trous où ses deux greens ont fait des choix différents. Deux paires disjointes regardent deux échantillons différents de la même population de trous.

## 5. Verdicts

- **H18b** (frontières → tours) : **tenue au chiffre, pas au mécanisme.** La formule donnait 3 tours, on en observe 4, dans la marge de ±1 fixée d'avance. Mais :
  - la marge est trop large pour être un vrai test : la formule ne donne que 2, 3 ou 4 ;
  - les 4 assertions qui ont coûté des tours ne sont **pas** des frontières ;
  - le pari « la taille ajoute des tours » est le plus probable.
  
  Elle reste **à discuter, affaiblie**.
- **H19** (découpe ≈ coût fixe, la répartition se décide aux tours) : **retenue, précisée.**
  - Découpe : 217 k pour 4 fois plus d'assertions, soit 1,3 à 2,5 fois les petites sondes. Le coût est presque fixe, et la borne prédite (≤ 688 k) est largement tenue.
  - Part de découpe : 17,6 % contre 24 % prédits par la formule avec les 4 tours observés, soit 6,4 points, dans la marge de ±7. Mais c'est sous le plancher de 20 % que j'avais mis.
  - L'exécution grossit avec **la taille × les tours** : 1 015 k, presque 2 fois le maximum vu. Avec 3 tours prédits, la formule donnait 29 %, ce qui est hors marge.
- **H20** (les divergences sont un détecteur de trous plus fiable que le red) : **réfutée telle qu'énoncée.** Le Jaccard entre deux paires vaut 0,00 sur P02 et 0,105 sur P11, deux fois. Ce qui tient en revanche :
  - le différentiel trouve **environ 15 trous et au moins 2 bugs** que le duel, ses 2 attaques du red et ses 252 tests n'avaient pas fermés ;
  - **chaque divergence est un fait, pas un avis** : deux codes conformes aux tests font deux choses différentes, et la situation se rejoue.

  **Reformulation proposée, H20b** : « Avec N greens comparés tous contre tous, l'**union** des trous trouvés se répète d'un lot de N greens à un autre. » Le test : un 2e lot de 4 greens sur P11, environ 10 $. Le critère reste le même, sur l'union et non plus sur une paire.

## 6. Ce qu'il faut retenir, simplement

```
              P02 (39 assertions)        P11 (159 assertions)
              ───────────────────        ────────────────────
  tests       104, tous passent          252, tous passent
  4 codes     d'accord 25 % du temps     d'accord 1 % du temps
  2 sonnet    d'accord 98 %              d'accord 14 %
```

1. **Passer les tests ne veut pas dire « même programme ».** Sur la grosse spec, 252 tests verts laissent les codes libres presque partout. Le taux de compilation mesure exactement ce que le cap demande, et il est mauvais : la spec P11 ne compile pas.
2. **Les trous ne sont pas un défaut de l'un ou l'autre green, ce sont des choix laissés libres.** Chaque green les comble à sa façon. Plus on a de greens, plus on en voit. Deux greens n'en montrent qu'une partie.
3. **Pour répartir des tokens** : la découpe reste un coût presque fixe (H19). L'exécution grossit avec la taille et les tours. Le test différentiel est une 3e dépense, à peu près le prix d'un duel (environ 10 $ sur P11 avec les juges), et c'est celle qui trouve le plus.
4. **La boucle qui en découle** : différentiel, puis trous classés, puis assertions ajoutées à la spec, puis nouveau différentiel. Si le taux de compilation monte d'une boucle à l'autre, on tient la machine qui rend une spec compilable. C'est la suite naturelle du cap.

## 7. Coût de cette étape

| Poste | $ |
|---|---|
| P02 : générateur, 3 greens, 6 paires jugées | ~1,3 |
| P11 : 4 passes xl | 2,4 |
| P11 : duel complet | 3,4 |
| P11 : générateur + 3 greens | 4,5 |
| P11 : 6 paires jugées + 2 appariements | 6,4 |
| **Total** | **~18 $** |

## Fichiers

- `outils/differentiel.py`, `outils/quatre.py`.
- `runs-v4/P02/`, `runs-v4/P11/` : générateur, greens, paires (divergences, verdicts), `accord-H1-H2-S1-S2.json`, appariements. Les traces brutes (`traces/`, ~10 Mo par green) ne sont pas versionnées : `python outils/differentiel.py traces <sonde> --nom <green>` les refait sans appel à un modèle.
- `runs-v4-duel/P11/` : le duel complet.
- `data/predictions/P11.md` : la prédiction figée.
- `data/passes/strict-v2-xl/`, `data/passes/strict-v3-xl/`.
