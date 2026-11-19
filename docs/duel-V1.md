# V1, le duel : rapport (19 novembre 2026)

En une phrase : **avec un green plus faible, deux attaques et de vrais mécanismes, on obtient 2 échecs réels sur 3 sondes.** C'est mieux que le zéro du V0, mais c'est encore trop peu pour trancher H14.

## 1. La nouvelle règle de concordance (SPEC 6.3)

k retenu = médiane. Avec 2 passes : écart ≤ 0,15. Avec 3 passes ou plus : écart-type ≤ 0,10. Sinon, la sonde est **floue**.

| Sonde (consigne v1) | Passes | Écart-type | Statut |
|---|---|---|---|
| P09 Réservation | 2,05 / 2,35 / 2,18 | 0,15 | **floue** |
| P10 Chat chiffré | 1,63 / 1,80 / 2,14 | 0,26 | **floue** (une 4e passe, 1,76, avait été lancée avant la règle) |

## 2. Consigne v2 (règle 5 : assertions frontière)

`prompts/decompositeur-strict-v2.md`, passes dans `data/passes/strict-v2/` (jamais comparées aux passes v1, règle 4).

| Sonde | k des passes v2 | k retenu | Statut v2 | Frontières (moy.) | Part |
|---|---|---|---|---|---|
| P05 Blog | 2,18 / 2,56 / 2,48 | 2,48 | **floue** (écart-type 0,20) | 2,7 | 7 % |
| P08 Éditeur | 1,87 / 1,79 | 1,83 | concordante (écart 0,07) | 6,0 | 16 % |
| P10 Chat | 1,72 / 1,68 / 1,81 | 1,72 | **concordante** (écart-type 0,06) | 6,0 | 16 % |

Deux surprises :
- **P10 devient concordant, et sur trois passes.** J'ai lancé la 3e passe en contrôle alors que la règle ne l'exigeait pas, parce qu'en v1 aussi les deux premières passes étaient presque d'accord (0,17). En v2, la 3e passe tient. Mais l'état fourre-tout « lisibilité » **est toujours là** dans les trois passes v2 : les auteurs ne l'ont pas découpé, ils l'ont seulement marqué frontière. Ce qui stabilise P10, c'est donc la marque, pas la disparition du fourre-tout.
- **Le blog devient flou en v2** (écart-type 0,20), alors qu'il était concordant en v1 (deux passes seulement). La règle 5 ne réduit donc pas le désaccord partout.

## 3. Le duel V1

Réglages : red opus (deux attaques, il écrit des tests qui cassent, y compris sur les cas non tranchés : `test_A07_trou_…`), green **haiku** sans Bash (un tour = un essai), juge opus. Passe A en v2.

Mécanismes réels, imposés au red comme au green :
- **chat** : X25519, HKDF et ChaCha20-Poly1305 de `cryptography`, clés privées par appareil, serveur qui ne voit que des octets. Vérifié dans `runs-v1/P10/app.py`.
- **éditeur** : une réplique par participant, un réseau qui retarde et désordonne les opérations, et une fusion de type CRDT (`Replica`, `_Elem`). Vérifié dans `runs-v1/P08/app.py`.

Le reste est en mémoire.

| | Blog P05 | Éditeur P08 | Chat P10 |
|---|---|---|---|
| k v2 (statut) | 2,48 (floue, forcée) | 1,83 (concordante) | 1,72 (concordante) |
| Frontières | 3 / 38 | 6 / 38 | 6 / 36 |
| Tests (attaque 1 + 2) | 69 + 48 | 74 + 54 | 62 + 45 |
| Tours | 2 | 3 | 4 |
| Trous a priori, attaque 1 (avant tout code) | 14 (**0,37** / assertion) | 13 (**0,34**) | 9 (**0,25**) |
| Trous a priori, total des 2 attaques | 23 | 30 | 18 |
| Échecs bruts (bug / trou / contradiction) | 0 / 0 / 0 | 0 / 1 / 0 | 53 / 9 / 0 |
| **Échecs réels (causes distinctes)** | **0** | **1 trou** | **1 bug** |
| Champ local (frontière / autres) | 1,00 / 1,00 | 1,00 / 1,03 | 3,00 / 3,00 |
| Tokens découpe / exécution | 87 k / 132 k (40 %) | 164 k / 565 k (23 %) | 172 k / 553 k (24 %) |
| Coût | 1,14 $ | 2,55 $ | 2,55 $ |

**Pourquoi « échecs réels » diffère des échecs bruts sur le chat.** Aux tours 1 et 2, le code de haiku ne s'importait pas, à cause d'une seule ligne : `cryptography.hazmat.primitives.aead` au lieu de `…primitives.ciphers.aead`. Les 62 tests cassent donc pour **une seule cause**, et les 9 « trous » bruts ne sont que des tests « trou » emportés par cette panne. C'est un vrai bug, et il est bien technique : c'est une erreur sur la bibliothèque du mécanisme frontière. Mais il touche toutes les assertions à la fois, si bien que le champ local vaut 3 pour toutes, frontière ou non.

Le green a perdu un tour de plus parce que le banc lui renvoyait seulement « collection failure », sans la vraie erreur. C'est un défaut du banc, corrigé après coup dans `outils/duel.py` : le duel V1 a tourné sans cette correction.

**Le trou de l'éditeur** vient de la 2e attaque : deux changements de permission successifs, livrés dans le désordre, doivent aboutir à la même valeur partout. La spec ne disait pas lequel l'emporte. Il a été ajouté comme N01 (« le dernier changement émis l'emporte partout »).

**Le blog** : zéro échec, encore. Haiku a même pris la même position que le red sur les 23 cas non tranchés. Il a aussi levé 23 réclamations « hors spec » sur deux tours, mais sur des tests qui passaient : ce ne sont pas des échecs, et le juge n'a donc pas été appelé.

## 4. Verdicts

```
                  trous a priori      échecs réels       champ local
                  (attaque 1)         à l'exécution
  Blog   k 2,48   ██████████ 0,37     –                  1,00
  Éditeur k 1,83  █████████  0,34     1 trou             1,03
  Chat   k 1,72   ███████    0,25     1 bug (×62 tests)  3,00
```

- **H14** (k haut → trous, champ local haut → bugs) : **toujours non tranchée.** Le sens est le bon : le seul bug est sur le chat, le seul trou sur une sonde sans difficulté technique de bibliothèque, et le champ local le plus haut est celui du chat. Mais tout repose sur deux échecs réels, et le blog, la sonde censée produire des trous, n'en produit aucun à l'exécution. Ses trous sortent tous a priori.
- **H15** (trous signalés suivent k) : **tient pour la 2e fois**, sur l'attaque 1, c'est-à-dire les trous signalés avant tout code. V0 : 0,61 > 0,57 > 0,37. V1 : 0,37 > 0,34 > 0,25, dans l'ordre des k. Sur le total des deux attaques, en revanche, l'éditeur passe devant (30 contre 23) : la 2e attaque cherche ailleurs. Cela fait 6 points sur 2 montages, toujours 3 sondes : elle reste à discuter.
- **H16** (floue → plus de trous et de contradictions) : **non testable proprement.** La seule sonde floue du duel, le blog en v2, n'a aucune sonde concordante de k proche en face. En brut, elle a 0 trou et 0 contradiction contre 1 trou pour l'éditeur, ce qui va **contre** la prédiction. Le critère que tu avais fixé, « P10 concordant en v2 », est rempli (écart-type 0,06 sur 3 passes), avec la réserve du §2 : le fourre-tout n'a pas disparu, il a été marqué.
- **H17** (frontières → difficulté technique) : **à moitié.** Le compte tient : chat et éditeur ont 6 frontières, le blog 2,7, soit 2,2 fois plus. Mais le champ local ne suit pas ce compte : l'éditeur a autant de frontières que le chat et un champ local de 1,03, contre 3,00. Et dans le chat, frontières et autres assertions ont le même champ local, parce que le seul bug est global.

## 5. Ce qu'il faut retenir, simplement

1. **La découpe trouve les trous avant le code, et l'exécution ne les retrouve presque jamais.** Sur le blog, 23 trous ont été nommés et aucun n'a cassé. Pour mesurer les trous, c'est la découpe qu'il faut compter, pas les échecs : c'est ce que fait H15.
2. **La difficulté technique se voit, mais elle n'est pas locale.** Le seul vrai bug du chat est une ligne d'import de la bibliothèque crypto. Il casse tout d'un coup. Un « champ local par assertion » ne voit pas ce genre de panne : il faudrait compter les **causes** d'échec, pas les tests.
3. **Le coût s'inverse avec la technique.** La découpe pèse 40 % sur le blog, et seulement 23 % et 24 % sur l'éditeur et le chat, où le green a écrit 4 à 5 fois plus de tokens. C'est le sens de H3, vu par l'autre côté. Les tokens d'opus (red) et de haiku (green) ne coûtent pas la même chose : comparer les tokens a un sens, comparer les dollars non.

## 6. Pour aller plus loin

- **Compter les causes, pas les tests** : regrouper les échecs d'un tour par message d'erreur.
- **H16 demande une paire de sondes de k proche, l'une floue, l'autre non.** Le candidat est P09 (floue en v1, k 2,18) contre le blog. Il faut d'abord ses passes v2.
- **Plus de tours forcés** : avec des échecs aussi rares, il faudra plus de sondes avant que les chiffres disent quelque chose.

## Fichiers

`runs-v1/<sonde>/` : tests des deux attaques, `lacunes.md` et `lacunes2.md`, `app_tourNN.py` (chaque essai du green), réclamations, verdicts du juge, `journal.jsonl`, `bilan.json`.
