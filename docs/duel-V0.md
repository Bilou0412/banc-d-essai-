# V0, le duel : rapport (19 novembre 2026)

Première tâche du `CLAUDE.md`. Résultat en une phrase : **le duel n'a produit aucun échec, sur aucune sonde.** H14 ne peut donc pas être tranchée avec ce montage, mais le duel a appris trois choses utiles.

## 1. Les passes manquantes

| Sonde | A | B | C (nouvelle) | D (nouvelle) | Écart max | Concordante ? |
|---|---|---|---|---|---|---|
| P09 Réservation | 2,05 | 2,35 | 2,18 | | 0,30 | non |
| P10 Chat chiffré | 1,63 | 1,80 | **2,14** | 1,76 | 0,51 | non |

- La 3e passe P10 a **aggravé** l'écart (2,14). La 4e (1,76) suggère que C est une passe atypique : A, B et D tiennent dans 0,17.
- **Trou dans la SPEC du banc** : la règle 6.3 dit « écart > 0,15 → une 3e passe », mais rien sur ce qu'on fait si la 3e ne suffit pas. Avec la règle « écart = max − min », une sonde non concordante ne peut **jamais** le redevenir en ajoutant des passes. Je n'ai rien décidé (règle 6 du labo) : c'est à toi de choisir (médiane ? écarter la passe la plus loin ? garder le refus ?).
- Coût : ~20 000 tokens par passe (opus, ~0,23 $).

## 2. Le branchement du protocole

Le protocole adversarial (`Bilou0412/adversarial-agents-protocol`) est attaché au banc avec son propre outil (`tools/link.py`) : `protocol/` + `.claude/agents/` (red, green, judge, searcher, green-spec).

Ce qu'il rendait déjà, et ce que j'ai ajouté (`outils/duel.py`) :

| Ce que le banc demande (SPEC §11) | Déjà dans le protocole ? | Ajouté |
|---|---|---|
| Statut de chaque assertion à chaque tour | En partie : chaque test cite sa règle dans son nom (§3) | Le pilote exécute pytest et ramène chaque test à son assertion (`test_A07_…`) ; une assertion passe si tous ses tests passent |
| Tokens découpe / exécution | Non par tour (le registre `steps.py` compte par étape, pour le protocole lui-même) | Chaque appel `claude -p` rend sa consommation ; découpe = red + juge, exécution = green |
| De quoi classer chaque échec | Oui : réclamations ancrées du green, juge froid | Règle de classement : réclamation maintenue « gap » → trou (+ nouvelle assertion) ; « contradiction » → contradiction ; rejetée ou absente → bug ; assertion qui repasse deux fois de passe à casse → contradiction |
| Trous vus avant tout code | Oui : le red « ne devine pas », il nomme le trou | Fichier `lacunes.md`, compté à part (« trous signalés à la découpe ») |

Garde-fous : les agents tournent dans un dossier temporaire **hors du dépôt** (ni CLAUDE.md, ni thèses, ni k), le green n'a pas Bash (un tour = un essai), et le diff sur les tests est vérifié à chaque tour.

```
  tour 1                tour t (jusqu'à 20)
  ┌──────┐  tests   ┌───────┐  app.py  ┌────────┐  échecs  ┌──────┐
  │ red  │────────▶│ green │────────▶│ pytest │────────▶│ juge │ (si réclamation)
  └──────┘         └───────┘         └────────┘         └──────┘
     │ lacunes.md      ▲                  │ statut par assertion
     ▼                 └──── échecs ──────┘
  trous signalés
```

## 3. Le duel

Red : opus. Green : sonnet (le protocole veut deux modèles différents). Juge : opus. Passe A de chaque sonde.

| Sonde | k | Assertions | Tests | Tours | Échecs (bug / trou / contra.) | Champ local | Trous signalés | par assertion | Tokens découpe | Tokens exécution | Part découpe |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P05 Blog | 2,40 | 36 | 53 | 1 | 0 / 0 / 0 | 1,00 | 22 | **0,61** | 34 058 | 23 039 | 60 % |
| P10 Chat chiffré (forcé, non concordant) | ~1,8 | 35 | 54 | 1 | 0 / 0 / 0 | 1,00 | 20 | **0,57** | 41 228 | 29 146 | 59 % |
| P08 Éditeur collaboratif | 1,62 | 38 | 50 | 1 | 0 / 0 / 0 | 1,00 | 14 | **0,37** | 33 205 | 40 224 | 45 % |

Coût total du duel : ~1,95 $. Les trois sondes ont tourné (ton choix) : P08 parce que P10 n'est pas concordant, P10 quand même, marqué `--force`.

## 4. Ce que ça veut dire, franchement

1. **Zéro bug, partout.** Le green écrit du code juste du premier coup sur les trois sondes. La difficulté technique a été **simulée hors du problème** : le banc impose « tout en mémoire, pas de réseau, le temps est une valeur ». Sur le chat, le green chiffre bien en AES-GCM, mais la distribution des clés est un objet partagé en mémoire : la partie dure (échange de clés, plusieurs appareils, rotation) n'existe pas. Champ local = 1 partout : **aucune variance à expliquer**. C'est le montage qui est en cause, pas H14.
2. **Les trous ne deviennent jamais des échecs.** Le red du protocole a pour consigne de ne pas deviner : il nomme le trou au lieu d'écrire un test qui casserait. Les trous sortent donc **à la découpe**, avant le code. La classification « échec → trou » de la SPEC 6.4 ne verra presque rien tant que le protocole marche comme prévu.
3. **Le seul signal : les trous signalés par assertion suivent k** sur 3 points : 0,61 (k 2,40) > 0,57 (k ~1,8) > 0,37 (k 1,62). Trois points, un écart faible entre blog et chat, et une valeur de P10 non concordante : c'est une piste, pas un résultat (devenue H15, « à discuter »).
4. **Tokens** : la découpe pèse 60 % sur le blog et 45 % sur l'éditeur, ce qui va dans le sens de H3. Mais red (opus) et green (sonnet) sont deux modèles : les tokens se comparent, pas les coûts.

## 5. Pour que le prochain duel tranche H14

Trois leviers, dans l'ordre du moins cher :
- **Un green plus faible** (haiku) : fait apparaître des bugs sans changer la spec.
- **Une deuxième attaque du red** après un tour tout vert, en ne voyant que les statuts (c'est son objectif mesuré : « un test vert au premier tour est un échec pour toi »).
- **Retirer la simulation** sur les sondes techniques (vraies clés par appareil, vraie concurrence) : c'est là que vit le champ local.

## Fichiers

- `runs/P05`, `runs/P08`, `runs/P10` : tests du red, `app.py` du green, `lacunes.md`, `journal.jsonl` (un objet par tour), `bilan.json`.
- `data/passes/strict/P09_C`, `P10_C`, `P10_D` ; `data/passes/journal-passes.jsonl`.
- `outils/passe_aveugle.py`, `outils/duel.py`.
