# Banc d'essai des specs — spécification fonctionnelle v1

## 1. But

Savoir, **avant de construire un projet**, comment répartir l'effort d'une IA entre :
- **découper** (clarifier la spec, chercher les trous) ;
- **exécuter** (écrire le code, corriger les bugs).

Le banc mesure deux choses sur un projet :
- **la densité fonctionnelle** : à quel point les règles se croisent (mesurée par **k**) ;
- **la difficulté technique** : à quel point chaque règle est dure à réaliser (mesurée par le **champ local**).

Puis il vérifie, en faisant tourner le protocole adversarial, si ces deux mesures prédisent vraiment ce qui se passe.

## 2. Vocabulaire

| Terme | Sens |
|---|---|
| **Sonde** | Petit projet créé uniquement pour tester la méthode. |
| **État** | Une donnée ou une règle que l'on peut faire varier indépendamment des autres. |
| **Assertion (spin)** | Une situation, au plus une action, un seul résultat portant sur un seul état observé. Elle passe ou elle casse. |
| **Conditions** | Les états dont la valeur change le résultat d'une assertion. Rien d'autre. |
| **Passe** | Une décomposition complète d'une sonde en assertions, faite par un agent qui ne sait pas ce qu'on mesure. |
| **k** | Nombre moyen d'états touchés par assertion (l'état observé plus les conditions). |
| **Champ** | L'état touché par le plus d'assertions. Exclu du réseau, car il pousse tout le monde de la même façon sans coupler personne. |
| **Réseau** | Deux assertions sont reliées si elles partagent au moins un état, hors champ. |
| **Champ local** | Nombre d'essais nécessaires pour faire passer une assertion pendant l'exécution. |
| **Tour** | Un cycle du protocole adversarial : assertions → code → résultats. |
| **Échec : bug** | L'assertion est juste, le code est faux. |
| **Échec : trou** | L'assertion révèle un cas que la spec ne couvre pas. |
| **Échec : contradiction** | Deux assertions ne peuvent pas passer ensemble. |
| **Thèse** | Une hypothèse testable, avec une prédiction et un statut. |

## 3. Acteurs

- **L'opérateur** : la personne qui lance les sondes et lit les résultats.
- **Le décompositeur aveugle** : un agent isolé qui écrit une passe. Il ne voit ni les autres passes, ni la densité attendue, ni les thèses.
- **Le protocole adversarial** (déjà existant) : l'agent qui écrit les assertions sans voir le code, et l'agent qui écrit le code sans voir le contenu des assertions.
- **L'analyste** : calcule les mesures et rend les verdicts.

## 4. Parcours principal

1. L'opérateur **enregistre une sonde** : nom, description en une phrase, liste de fonctions.
2. L'opérateur **note sa prédiction** (densité fonctionnelle et difficulté technique attendues). La prédiction est figée.
3. Le banc **lance deux passes aveugles** avec la règle stricte.
4. Le banc **mesure** chaque passe (k, réseau, champ) et **vérifie qu'elles concordent**.
5. Le banc **lance le protocole adversarial** sur la sonde et **journalise chaque tour**.
6. Le banc **mesure le champ local** de chaque assertion et **classe chaque échec**.
7. Le banc **place la sonde sur la carte** (k en hauteur, champ local en largeur) et **met à jour les thèses**.
8. L'opérateur **lit le rapport**.

## 5. États

sonde ; description ; prédiction ; passe ; aveuglement ; règle stricte ; assertions ; état observé ; conditions ; k ; champ ; réseau ; concordance ; tour ; statut d'assertion ; type d'échec ; essais ; champ local ; remontée ; tokens découpe ; tokens exécution ; carte ; thèse ; statut de thèse ; rapport

## 6. Assertions

Format : `situation → résultat | observé: état | conditions: états`

### 6.1 Sondes

- Enregistrer une sonde avec un nom et une description → la sonde apparaît dans la liste des sondes | observé: sonde | conditions: description
- Enregistrer une sonde sans description → la sonde est refusée | observé: sonde | conditions: description
- Enregistrer une sonde avec un nom déjà utilisé → la sonde est refusée | observé: sonde | conditions: aucune
- Saisir une prédiction sur une sonde sans passe → la prédiction est enregistrée | observé: prédiction | conditions: passe
- Modifier la prédiction d'une sonde qui a déjà une passe → la modification est refusée | observé: prédiction | conditions: passe

### 6.2 Passes aveugles

- Lancer les passes d'une sonde → deux passes sont créées | observé: passe | conditions: sonde
- Le décompositeur reçoit sa consigne → la consigne ne contient ni la prédiction, ni les thèses, ni les mots densité ou spin | observé: aveuglement | conditions: aucune
- Le décompositeur reçoit sa consigne → la consigne ne contient aucune autre passe | observé: aveuglement | conditions: passe
- Le décompositeur reçoit sa consigne → la consigne contient la règle stricte | observé: règle stricte | conditions: aucune
- Une passe est rendue au bon format → ses assertions sont enregistrées | observé: assertions | conditions: passe
- Une passe contient une ligne sans « observé » → la ligne est rejetée et signalée | observé: assertions | conditions: aucune
- Une assertion dont le résultat contient « et » → elle est signalée comme non atomique | observé: assertions | conditions: règle stricte
- Une assertion dont les conditions contiennent l'état observé → l'état observé est retiré des conditions | observé: conditions | conditions: état observé
- Une passe de moins de 20 assertions → la passe est marquée incomplète | observé: passe | conditions: assertions

### 6.3 Mesure statique

- Une passe enregistrée → son k est calculé | observé: k | conditions: assertions
- Une passe enregistrée → son champ est l'état touché par le plus d'assertions | observé: champ | conditions: assertions
- Deux assertions partagent un état autre que le champ → elles sont reliées dans le réseau | observé: réseau | conditions: champ
- Deux assertions ne partagent que le champ → elles ne sont pas reliées | observé: réseau | conditions: champ
- Deux passes d'une sonde avec un écart de k inférieur ou égal à 0,15 → la sonde est marquée concordante | observé: concordance | conditions: k
- Deux passes d'une sonde avec un écart de k supérieur à 0,15 → une troisième passe est lancée | observé: passe | conditions: concordance
- Une sonde concordante → son k retenu est la moyenne des passes | observé: k | conditions: concordance

### 6.4 Exécution (branchement du protocole adversarial)

- Lancer l'exécution d'une sonde concordante → le protocole reçoit les assertions de la passe A | observé: tour | conditions: concordance
- Lancer l'exécution d'une sonde non concordante → l'exécution est refusée | observé: tour | conditions: concordance
- Fin d'un tour → le statut de chaque assertion est enregistré (passe ou casse) | observé: statut d'assertion | conditions: tour
- Fin d'un tour → les tokens de découpe du tour sont enregistrés | observé: tokens découpe | conditions: tour
- Fin d'un tour → les tokens d'exécution du tour sont enregistrés | observé: tokens exécution | conditions: tour
- Une assertion casse et l'assertion est jugée juste → l'échec est classé bug | observé: type d'échec | conditions: statut d'assertion
- Une assertion casse et révèle un cas absent de la spec → l'échec est classé trou | observé: type d'échec | conditions: statut d'assertion
- Deux assertions cassent alternativement d'un tour à l'autre → l'échec est classé contradiction | observé: type d'échec | conditions: statut d'assertion, tour
- Un échec classé trou → la nouvelle assertion qu'il produit est ajoutée aux assertions | observé: assertions | conditions: type d'échec
- Un échec classé trou → le nombre de niveaux remontés est enregistré | observé: remontée | conditions: type d'échec
- Toutes les assertions passent sur un tour → l'exécution est terminée | observé: tour | conditions: statut d'assertion
- Vingt tours sans que tout passe → l'exécution est arrêtée et marquée non convergente | observé: tour | conditions: aucune

### 6.5 Champ local

- Une assertion passe pour la première fois → son nombre d'essais est enregistré | observé: essais | conditions: tour
- Une exécution terminée → le champ local de la sonde est la moyenne des essais | observé: champ local | conditions: essais

### 6.6 Carte et thèses

- Une sonde avec un k retenu et un champ local → elle est placée sur la carte | observé: carte | conditions: k, champ local
- Une sonde sans champ local → elle n'apparaît pas sur la carte | observé: carte | conditions: champ local
- Une thèse a assez de sondes mesurées → sa prédiction est comparée aux mesures | observé: statut de thèse | conditions: thèse
- La prédiction d'une thèse se vérifie sur toutes les sondes concernées → la thèse passe à « confirmée » | observé: statut de thèse | conditions: thèse
- La prédiction d'une thèse échoue sur une majorité de sondes → la thèse passe à « réfutée » | observé: statut de thèse | conditions: thèse
- Une thèse change de statut → la raison chiffrée est enregistrée avec elle | observé: thèse | conditions: statut de thèse

### 6.7 Rapport

- Demander le rapport d'une sonde → il affiche k, champ local et position sur la carte | observé: rapport | conditions: carte
- Demander le rapport d'une sonde → il affiche la part de chaque type d'échec | observé: rapport | conditions: type d'échec
- Demander le rapport d'une sonde → il affiche le rapport tokens découpe / tokens exécution | observé: rapport | conditions: tokens découpe, tokens exécution
- Demander le rapport d'une sonde → il affiche la prédiction à côté de la mesure | observé: rapport | conditions: prédiction

## 7. Thèses actives

| ID | Thèse | Prédiction testable |
|---|---|---|
| H13 | Avec la règle stricte, deux auteurs trouvent le même k. | Écart entre passes ≤ 0,15. **Confirmée sur 10 sondes.** |
| H14 | k mesure la densité fonctionnelle, pas la difficulté technique. | k haut → surtout des trous. Champ local haut → surtout des bugs. |
| H8 | Répartir les tokens selon (k, champ local) réduit le nombre de tours. | Moins de tours qu'une répartition fixe. Phase 2. |
| H9 | L'ordre est déjà là. | Deux passes donnent des blocs communs à plus de 80 %. |
| H10 | Un recuit (température haute puis basse) converge plus vite. | Moins de tours avec recuit. Phase 2. |

## 8. Données de départ

k strict mesuré à l'aveugle (moyenne de 2 passes) :

La colonne ± donne la moitié de l'écart entre les deux passes. Selon la règle 6.3 (écart total ≤ 0,15), **Réservation (écart 0,30) et Chat chiffré (écart 0,18) ne sont pas concordantes** et demandent une troisième passe.

| Sonde | k | ± |
|---|---|---|
| Blog avec commentaires | 2,40 | ±0,05 |
| Réservation de créneaux | 2,20 | ±0,15 |
| Note synchronisée hors ligne | 1,94 | ±0,03 |
| Pomodoro avec statistiques | 1,90 | ±0,05 |
| Inventaire de matériel | 1,83 | ±0,04 |
| Carnet de contacts | 1,76 | ±0,07 |
| Todo multi-listes | 1,76 | ±0,01 |
| Chat chiffré de bout en bout | 1,71 | ±0,09 |
| Éditeur collaboratif temps réel | 1,62 | ±0,01 |
| Gestionnaire de recettes | 1,57 | ±0,05 |

## 9. Hors périmètre (v1)

- Choisir automatiquement la répartition des tokens (c'est H8, phase 2).
- Le recuit de température (H10, phase 2).
- Comparer les blocs entre passes (H9, v2).
- Toute interface graphique : un rapport texte suffit.

## 10. Ordre de livraison

1. **V0, le duel** : sections 6.2, 6.3 et 6.4 sur deux sondes seulement, Blog (k = 2,40) et Chat chiffré (k = 1,71). Ce duel répond à H14.
2. **V1** : ajout du champ local (6.5) et de la carte (6.6).
3. **V2** : les 10 sondes, le rapport (6.7) et le recalage des thèses.

## 11. Point d'intégration à vérifier

Le banc a besoin que le protocole adversarial lui rende, **à chaque tour** :
- la liste des assertions avec leur statut (passe ou casse) ;
- les tokens dépensés pour découper et pour exécuter ;
- pour chaque échec, de quoi le classer (bug, trou ou contradiction).

Si le protocole ne fournit pas déjà l'une de ces trois choses, c'est la première chose à ajouter.
