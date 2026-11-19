# Registre des thèses

Statuts : à discuter · retenue · confirmée · réfutée.
Règle : toute thèse qui change de statut garde sa **raison chiffrée**.

| ID | Thèse | Prédiction testable | Statut | Raison |
|---|---|---|---|---|
| H1 | Plus la réutilisation est haute, plus la descente et la montée de la pyramide se rejoignent haut. | Corrélation positive avec le point de rencontre. | Retenue | Pas encore mesurable : demande l'exécution. |
| H2 | Dans le protocole, les échecs d'un projet dense sont surtout des trous de spec ; ceux d'un projet compressible, surtout des bugs. | Denses > 50 % de trous. | Retenue | Reformulée en H14. |
| H3 | Un projet dense consomme plus de tokens en découpe qu'en exécution. | Denses > 50 % de tokens de découpe. | Retenue | V0 : découpe 60 % sur le blog (k 2,40), 59 % sur le chat (k ~1,8), 45 % sur l'éditeur (k 1,62). Va dans le sens, mais red (opus) et green (sonnet) sont deux modèles, et un seul tour par sonde. |
| H4 | Les questions adversariales s'épuisent plus vite sur un projet compressible. | Rendement plus bas sur les compressibles. | Retenue | Secondaire. |
| H5 | Sur un projet dense, les échecs remontent plus haut dans la pyramide. | Denses > compressibles. | Retenue | Prioritaire, demande l'exécution. |
| H6 | Contrôle : une spec atomique passe quelle que soit la densité. | Taux de validité > 80 %. | Retenue | V0 : 100 % sur 3 sondes (P05 53/53 tests, P08 50/50, P10 54/54, au 1er tour). Tenue sur 3/10 sondes, pas encore confirmée. |
| H7 | L'intuition de départ sur la densité d'un projet est fiable. | ≥ 7/10 prédictions tenues. | **Réfutée** | 3/10 avec le k strict. Claude avait prédit la difficulté technique, pas la densité fonctionnelle. |
| H8 | Répartir les tokens selon (k, champ local) réduit le nombre de tours. | Moins de tours qu'une répartition fixe. | À discuter | Phase 2 : c'est le but final. |
| H9 | L'ordre est déjà là : deux passes indépendantes retrouvent la même structure. | Blocs communs > 80 %. | Retenue | En aveugle strict, les passes retrouvent presque le même nombre d'assertions et d'états. Blocs pas encore comparés. |
| H10 | Un recuit (température du modèle haute puis basse) converge plus vite. | Moins de tours avec recuit. | Retenue | Phase 2. |
| H11 | La valeur absolue de k suffit à classer un projet, quel que soit l'auteur. | Même classement pour tout auteur. | **Réfutée** | Avec des assertions libres, le todo valait 1,67 (Claude) contre 2,70 et 2,41 (aveugle). |
| H12 | La densité du réseau et la modularité séparent les projets attendus denses des compressibles. | Séparation nette. | **Réfutée** | Tenue sur 2 sondes, pas sur 10 (modularité 0,45–0,63 contre 0,37–0,53). |
| H13 | Avec la règle stricte, deux auteurs trouvent le même k. | Écart entre auteurs bien plus petit que l'écart entre projets. | **Confirmée** | 10 sondes × 2 passes : demi-écart moyen ±0,05 contre une étendue de 1,57 à 2,40. Attention : P09 et P10 dépassent l'écart toléré de 0,15. 3e passe (V0) : P09_C 2,18 (écart reste 0,30) ; P10_C 2,14 et P10_D 1,76 (écart 0,51). La règle stricte ne suffit pas pour P10. |
| H14 | k mesure la densité fonctionnelle (règles qui se croisent), pas la difficulté technique, qui vit dans le champ local d'un spin. | k haut → surtout des trous ; champ local haut → surtout des bugs. | Retenue | **V0 non concluant** : 0 échec sur 3 sondes (blog, chat, éditeur), champ local = 1,00 partout, donc ni bug ni trou à classer. Le montage (tout simulé en mémoire) retire la difficulté technique, et les trous sortent à la découpe (`lacunes.md`), pas en échec. Voir `docs/duel-V0.md`. |
| H15 | Le nombre de trous signalés à la découpe par assertion croît avec k. | Corrélation de rang positive entre k et trous signalés / assertion, sur les 10 sondes. | À discuter | V0, 3 points : blog 0,61 (k 2,40) > chat 0,57 (k ~1,8, non concordant) > éditeur 0,37 (k 1,62). Aucun seuil fixé. |
