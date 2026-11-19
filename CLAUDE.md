# Banc d'essai des specs

Laboratoire pour mesurer les specs **avant** de construire, et vérifier en exécutant si la mesure prédit quelque chose.
But final : savoir comment répartir l'effort d'une IA entre **découper** (spec) et **exécuter** (code).

À lire dans cet ordre avant toute tâche :
1. `docs/HISTORIQUE.md` : d'où vient le banc et ce qui est déjà prouvé ou réfuté.
2. `docs/SPEC-banc.md` : ce que le banc doit faire (assertions au format strict).
3. `docs/theses.md` : les hypothèses en cours et leur statut.

## Avec qui tu travailles

Bilel, développeur freelance. Il pense par **intuitions structurelles et parallèles** (Ising, recuit, havrouta…) et s'arrête souvent dès qu'il a vu le parallèle. Ton rôle :
- **Transformer chaque parallèle en thèse testable** (prédiction chiffrée + statut dans `docs/theses.md`). Ne pas juste approuver.
- **Dire franchement** quand quelque chose ne tient pas, chiffres à l'appui. C'est ce qui a fait avancer le banc.
- **Expliquer simplement, en français, avec des schémas** quand c'est possible.
- Il a déjà un **protocole adversarial** branché dans Claude Code. Il vit dans `Bilou0412/adversarial-agents-protocol`, attaché ici dans `protocol/` et `.claude/agents/` ; `outils/duel.py` l'appelle en `claude -p --agent red|green|judge`.

## Règles du labo (ne pas casser)

1. **Aveuglement.** Les passes sont faites par des sous-agents neufs avec `prompts/decompositeur-strict.md`, **sans rien ajouter**. Jamais de prédiction, de thèse, ni de mots comme « densité », « spin » ou « k » dans leur consigne. C'est ce qui rend k fiable.
2. **Prédiction figée avant les passes.** Elle sépare densité fonctionnelle et difficulté technique.
3. **Deux passes minimum par sonde.** Si l'écart de k dépasse 0,15, une troisième passe. À 3 passes, concordante si écart-type ≤ 0,10, sinon **floue** : pas de 4e passe, on creuse la spec. k retenu = médiane.
4. **Ne comparer que des passes faites avec la même règle** (stricte).
5. **Toute thèse qui change de statut garde sa raison chiffrée.**
6. **Pas de seuil fixé après avoir vu les données** sans le marquer « non validé ».

## Arborescence

```
CLAUDE.md                      ce fichier
docs/SPEC-banc.md              spec fonctionnelle du banc (45 assertions strictes)
docs/theses.md                 registre des thèses H1-H18
docs/HISTORIQUE.md             la conversation d'origine, résumée
prompts/decompositeur-strict.md  consigne exacte des passes aveugles (v1)
prompts/decompositeur-strict-v2.md  v1 + règle 5 (assertions frontière, « | frontière: oui »)
data/sondes.md                 les 10 sondes, leur description et leur k
data/passes/strict/            23 passes aveugles strictes (P01_A ... P10_D)
data/passes/strict-v2/         passes v2 des 10 sondes (jamais comparées aux v1)
data/passes/aveugle-libre/     4 passes aveugles sans la règle stricte (historique)
data/passes/claude-libre/      passes écrites par Claude (biaisées, historique)
outils/mesure.py               calcule k, réseau, champ et concordance
outils/passe_aveugle.py        lance une passe aveugle stricte (claude -p neuf, dossier vide)
outils/duel.py                 fait tourner le protocole adversarial sur une sonde, tour par tour (--attaque-seule : trous a priori)
outils/causes.py               champ local compté par cause d'échec (même message = une cause)
runs/<sonde>/                  duel V0 (passes v1, green sonnet, une attaque)
runs-v1/<sonde>/               duel V1 (passes v2, green haiku, deux attaques, mécanismes réels)
runs-v2/<sonde>/               duel V2 (P02, P06, P07 : H18)
runs-v2-apriori/<sonde>/       attaque 1 du red seule (H15, H16)
docs/duel-V0.md, V1, V2        rapports des duels
protocol/, .claude/agents/     le protocole adversarial attaché (tools/link.py), ne pas éditer protocol/
```

`python outils/mesure.py data/passes/strict` doit redonner les k de `data/sondes.md`. Dépendance : `pip install networkx`.

## Première tâche : V0, le duel (teste H14) — faite le 19/11, voir `docs/duel-V0.md`

1. **Compléter les passes** : P10 (chat chiffré) et P09 ne sont pas concordantes (écart > 0,15). Lancer une 3e passe aveugle pour P10 au minimum.
2. **Brancher le protocole adversarial** (SPEC section 11). Vérifier qu'il rend, à chaque tour : le statut de chaque assertion, les tokens dépensés pour découper et pour exécuter, et de quoi classer chaque échec (bug / trou / contradiction). Ajouter ce qui manque.
3. **Lancer le protocole sur P05 (blog, k 2,40) et P10 (chat chiffré, k 1,71)**, à partir de leur passe A.
4. **Journaliser chaque tour** et compter, pour chaque assertion, le nombre d'essais avant qu'elle passe (champ local).
5. **Verdict H14** : le blog doit produire surtout des **trous**, le chat surtout des **bugs**. Mettre à jour `docs/theses.md` avec les chiffres.

Commencer petit : un rapport texte suffit, pas d'interface.
