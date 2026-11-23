# Historique : comment le banc est né

Résumé de la conversation d'origine (claude.ai, 18-19 novembre 2026), pour reprendre sans rien perdre.

## 1. L'intuition de départ

En utilisant beaucoup de méthodes de spec (SpecKit, BMAD, son propre protocole adversarial), Bilel a remarqué qu'elles répètent toutes la même boucle : un objectif, des questions qui révèlent ses limites, une décomposition, une validation.

Il l'a représentée en **pyramide** : l'objectif en haut, les specs atomiques en bas. Le protocole adversarial fait **descendre** (il attaque et décompose) et l'exécution fait **remonter** (ce qui marche ou casse précise l'objectif).

**La question d'origine :** à quelle vitesse la descente et la montée se rejoignent, pour savoir **comment répartir les tokens** entre découper et exécuter.

**L'observation clé :** certains projets ont « beaucoup de fonctionnel pour peu de technique » (ils se répètent), d'autres l'inverse.

## 2. Le protocole adversarial (existant, à Bilel)

- Un agent écrit des **assertions** à partir de la spec, sans voir le code.
- Un autre agent **écrit le code** en ne voyant que la forme des assertions, pas leur contenu.
- Les tours s'enchaînent jusqu'à une spec sans trou. Un échec révèle **un bug** ou **un trou de spec**.

## 3. Première mesure : fonctionnels × techniques (abandonnée)

- Matrice fonctionnels × techniques, avec son **rang** : abandonné, car le rang ne dépasse jamais le nombre de techniques et ne voit donc pas la répétition.
- **Réutilisation** (liens ÷ techniques) : écrasée par les techniques universelles comme la persistance.

## 4. Le parallèle avec le modèle d'Ising (Bilel)

- **Spin = assertion atomique** (passe ou casse).
- **Couplage = état partagé** entre deux assertions.
- **Champ = état touché par presque tout** (ex. « existence »). Il ne couple personne et doit être exclu. C'est cette distinction qui a réparé l'indicateur.
- **Température = bruit.** Pour Bilel, l'ordre est **déjà là** et le bruit le cache. L'attaque adversariale le révèle, comme un **recuit simulé** (→ H9, H10).
- L'objection « les spins d'Ising sont identiques, les specs ne le sont pas » ne tient pas : il faut des **verres de spin** (couplages hétérogènes). Ils apportent aussi la notion de **frustration**, c'est-à-dire des exigences contradictoires, d'où la troisième catégorie d'échec.

## 5. « Tu n'es pas descendu assez loin » (Bilel)

L'unité n'est pas le fonctionnel (un « aspect »), c'est **l'assertion**. Toutes les assertions ont la même forme ; toute la structure est dans les états qu'elles partagent. C'est l'équivalent des portes logiques NAND : toutes identiques, seul le câblage diffère.

Sur le carnet de contacts, le réseau d'assertions s'est regroupé tout seul en 3 blocs (données, recherche + étiquettes, liste + ordre), qui ne correspondaient pas aux 12 fonctionnels de départ.

## 6. Les biais trouvés (et corrigés)

1. **Claude prédisait et décomposait** : c'était sa propre intuition qui était mesurée. → Les décompositions sont maintenant faites par des agents aveugles.
2. **Les seuils étaient fixés après avoir vu les chiffres.** → Ils restent marqués « non validés ».
3. **Avec des assertions libres, k dépend de l'auteur** : le todo vaut 1,67 écrit par Claude, 2,70 et 2,41 à l'aveugle (H11 réfutée).
4. **La règle d'atomicité stricte** (une action, un seul état observé, conditions minimales) fait converger les auteurs : demi-écart moyen de ±0,05 sur 10 sondes (H13 confirmée). **C'est le résultat le plus solide.**

## 7. La surprise

Avec la mesure fiable, la prédiction de Claude ne tient que pour 3 sondes sur 10. En tête : blog (2,40) et réservation (2,20), où les règles se croisent. En bas : éditeur collaboratif (1,62) et chat chiffré (1,71), qui sont techniquement durs.

**Interprétation (H14) :** il existe deux difficultés distinctes, ce qui rejoint l'observation de départ.
- **Densité fonctionnelle** : les règles se croisent. k la mesure.
- **Difficulté technique** : elle est cachée à l'intérieur d'un spin, c'est son « champ local ». k ne la voit pas. À mesurer pendant l'exécution (nombre d'essais par assertion).

## 8. Où on en est

- **Prouvé :** un instrument reproductible qui mesure la densité fonctionnelle d'une spec avant tout code.
- **Pas prouvé :** que cette mesure aide à répartir les tokens. C'est le but, et il demande d'exécuter.
- **Prochaine étape :** le duel Blog contre Chat chiffré avec le protocole adversarial (V0 de la spec).

## 9. Ce qui reste du tableur

Un tableur « Banc d'essai — Pyramide de specs » existe sur claude.ai : thèses, projets, assertions, spins. **Ce repo devient la source de vérité** ; le tableur n'est plus mis à jour.
