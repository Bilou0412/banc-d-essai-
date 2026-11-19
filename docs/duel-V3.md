# V3 : fiabiliser les instruments (19 novembre 2026)

En une phrase : **le compte de trous du red n'est pas un instrument fiable, et la règle 5 précisée (v3) stabilise une partie des frontières mais déstabilise k.** On a appris ce qu'on ne peut pas mesurer avant de changer d'échelle.

La sonde à taille réelle (point 4) attend ta réponse sur le projet client. Elle sera ajoutée à ce rapport, avec sa prédiction figée avant le duel.

## 1. Thèses reformulées

- **H15 fusionnée dans H18a** : « k annonce le nombre de trous trouvés en découpe ».
- **H18b** : « les frontières annoncent le nombre de tours d'exécution, donc la part d'exécution ».
- **H19, retenue** : « la découpe est un coût presque fixe ; la répartition se décide par le nombre de tours ». Chiffres du V2 : découpe de 87 à 172 k tokens, exécution de 132 à 565 k, ρ(part de découpe, tours) = −0,83.

## 2. Reproductibilité du red (comme H13 pour k)

Pour les 7 sondes concordantes en v2 : un red neuf refait l'attaque 1 a priori sur la même passe A, sans voir la première.

| Sonde | k v2 | Red A (trous / assertion) | Red B | Écart | Moyenne |
|---|---|---|---|---|---|
| P02 Recettes | 1,61 | 0,18 | 0,23 | 0,05 | 0,21 |
| P10 Chat | 1,72 | 0,25 | 0,28 | 0,03 | 0,26 |
| P08 Éditeur | 1,83 | 0,34 | 0,18 | **0,16** | 0,26 |
| P07 Notes | 1,85 | 0,23 | 0,29 | 0,06 | 0,26 |
| P01 Contacts | 1,88 | 0,54 | 0,46 | 0,08 | **0,50** |
| P04 Todo | 1,90 | 0,30 | 0,25 | 0,05 | 0,28 |
| P06 Pomodoro | 2,10 | 0,33 | 0,15 | **0,18** | 0,24 |

- Écart moyen entre les deux reds : **0,085** trou par assertion.
- Écart entre sondes (étendue des moyennes) : 0,295, mais **0,07 sans P01**.
- Corrélation de rang entre red A et red B : **ρ = 0,00**. Les deux reds ne classent pas les sondes dans le même ordre.

**Verdict, avec ton critère.** Le bruit entre deux reds (0,085) est **plus grand** que l'écart entre sondes, sauf pour une seule : P01, où les deux reds trouvent beaucoup de trous (0,54 et 0,46). Le compte de trous a priori ne sépare donc que P01 du reste. **On arrête de s'appuyer dessus** pour classer les sondes. Comparé à H13, où le demi-écart entre auteurs (±0,05) était 30 fois plus petit que l'étendue des k (1,57 à 2,40), ce n'est pas le même monde.

Conséquence directe sur **H18a** : avec le red B seul, ρ(k, trous) = −0,11 ; avec la moyenne des deux, +0,29. Le **+0,54 du V2 était du bruit**.

## 3. Reproductibilité des frontières

### Pourquoi P07 donnait 3 et 7

En v2, la passe A de P07 ne marquait que deux choses : une transmission coupée en plein envoi, et un conflit tranché par l'horloge. La passe B marquait **tout résultat obtenu après une reconnexion** : copie de conflit, versions conservées, suppression contre modification, date de synchronisation. La règle v2 disait « un mécanisme que l'utilisateur ne voit pas », sans dire si **la synchronisation elle-même** en est un. Chaque auteur a tranché à sa façon.

### La règle 5 précisée (`prompts/decompositeur-strict-v3.md`)

Une assertion est frontière **si et seulement si** son résultat dépend d'au moins un de ces six mécanismes : (a) transmission entre appareils ou utilisateurs, (b) chiffrement, signature ou vérification de clé, (c) conservation après fermeture, (d) deux actions au même moment, (e) écoulement réel du temps, horloge, date ou fuseau, (f) calcul par un service extérieur.

S'y ajoute un test d'exclusion : si l'assertion reste vraie dans une version où tout tient dans une seule mémoire, sur un seul appareil, pour un seul utilisateur, une action après l'autre, sans fermeture et sans que le temps passe, elle n'est pas frontière.

### Résultat (2 passes, puis une 3e quand k divergeait)

| Sonde | Frontières v2 | Frontières v3 (A / B / C) | Écart A-B | Écart sur 3 | Part v3 | k v3 | Statut k v3 |
|---|---|---|---|---|---|---|---|
| P02 Recettes | 3 / 5 | 5 / 4 / 5 | **1 ✓** | **1 ✓** | 10-13 % | 1,45 / 1,62 / 1,56 | concordante (0,09) |
| P07 Notes | 3 / 7 | 20 / 19 / 24 | **1 ✓** | 5 ✗ | 53-63 % | 2,00 / 1,75 / 1,92 | **floue** (0,13) |
| P08 Éditeur | 6 / 6 | 18 / 22 / 17 | 4 ✗ | 5 ✗ | 45-59 % | 1,77 / 1,46 / 1,61 | **floue** (0,15) |
| P10 Chat | 6 / 5 / 7 | 31 / 30 | **1 ✓** | — | 79 % | 1,72 / 1,58 | concordante (0,14) |

Ce qu'il faut en lire :
1. **Ton critère (écart ≤ 1) tient sur les 2 premières passes pour 3 sondes sur 4.** Avec la 3e passe, il ne tient plus que pour P02, qui a peu de frontières. Sur P07 et P08, l'écart retombe à 5.
2. **La v3 marque beaucoup plus** : 20 au lieu de 3 à 7 sur P07, 30 au lieu de 6 sur P10. En **part**, c'est assez stable : P07 entre 53 et 63 %, P10 79 % et 79 %, P08 entre 45 et 59 %. Avec 20 frontières, un écart de ±1 est un critère très dur. **Je propose de passer à un critère en part : écart ≤ 10 points.** Je l'ai fixé après avoir vu les données, donc il est marqué « non validé » (règle 6). P02, P07 et P10 le tiennent, P08 non (14 points).
3. **Effet secondaire inattendu : la v3 rend P07 et P08 flous sur k**, alors qu'ils étaient concordants en v2 (sur 2 passes seulement). Quand les auteurs pensent davantage aux mécanismes, ils découpent les états différemment. **La v3 ne sert donc pas à mesurer k.** Garder la v2 pour k et la v3 pour les frontières ? C'est à toi de choisir.

## 4. Verdicts

- **H13 (rappel)** : confirmée en v1 (demi-écart ±0,05 sur 10 sondes à 2 passes). Mais sur les sondes riches en mécanismes, elle ne tient pas toujours. P10 était flou en v1, et P03, P05, P09 sont flous en v2. En v3, P07 et P08 deviennent flous. **k est reproductible pour les sondes simples, pas en général.**
- **H18a** (k → trous en découpe) : **pas d'instrument pour la tester.** Le compte du red a une corrélation de 0,00 entre deux reds. Elle reste à discuter jusqu'à ce qu'on ait une mesure des trous qui se répète.
- **H18b** (frontières → tours → part d'exécution) : rien de neuf à l'exécution dans cette étape. Les frontières v3 sont plus reproductibles en part (3 sondes sur 4 à 10 points près), ce qui rend H18b testable sur la grosse sonde.
- **H19** (découpe ≈ coût fixe, la répartition se décide aux tours) : **retenue**, chiffres du V2 inchangés. C'est aujourd'hui le résultat le plus utile pour répartir des tokens.

## 5. Ce qu'il faut retenir, simplement

```
  instrument            se répète ?              sert à…
  ───────────────────── ──────────────────────── ─────────────────────────────
  k (v1, v2)            oui sur sondes simples   densité fonctionnelle
  frontières (v3)       oui en part, ±10 pts     annoncer les tours (H18b, à tester)
  trous a priori (red)  NON (ρ = 0,00)           rien pour l'instant
  tours d'exécution     mesuré, pas prédit       décide la répartition (H19)
```

1. Pour **répartir des tokens**, la seule chose qui compte vraiment est le nombre de tours d'exécution. Il faut un indicateur **avant** le code qui l'annonce : les frontières sont le candidat, et la grosse sonde dira s'il tient.
2. Le compte de trous d'un red est trop bruité. Deux reds sur la même spec ne voient pas les mêmes trous. Si on veut cette mesure, il faudra probablement **plusieurs reds par sonde** et la moyenne, comme on a fait 2 à 3 passes pour k.

## 6. Coût de cette étape

7 attaques a priori (4,49 $), 11 passes v3 (2,58 $). **Total ~7,10 $.**

## Fichiers

- `runs-v3-apriori-B/<sonde>/` : la 2e attaque, faite par un red neuf.
- `prompts/decompositeur-strict-v3.md`, `data/passes/strict-v3/`.
