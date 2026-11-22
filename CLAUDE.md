# Banc d'essai des specs

> **Cap : une spec compilable.** Deux codes écrits indépendamment à partir de la même spec ont le même comportement. Tout le reste sert ce chiffre : le **taux de compilation** (`outils/differentiel.py`, H20).

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
7. **Deux consignes, deux séries de passes, jamais mélangées.** La v2 (`decompositeur-strict-v2.md`) mesure **k** ; la v3 (`decompositeur-strict-v3.md`) mesure les **frontières**. Critère de reproductibilité des frontières : écart de **part** ≤ 10 points entre passes (« non validé » jusqu'à la grosse sonde).
8. **Les trous du red ne sont pas des données.** Le red attaque toujours, mais son compte de trous a priori ne se répète pas (ρ = 0,00 entre deux reds, V3) : on ne s'en sert plus comme mesure.
9. **L'arrêt sur le taux spec se vérifie avec 4 greens neufs.** Une paire seule surestime : sur P12, une paire a donné 0,94, puis 4 greens neufs sur la même spec 0,78 à 0,87 (V5). On rapporte le taux du lot de 4.
10. **Un juge voit l'écart complet, jamais un extrait coupé.** Sur P12, des variantes coupées à 1 500 caractères ont rendu le plus gros groupe non classable (it1) : le taux spec de it1 et it2 n'est qu'une borne basse.

## Limites connues du banc

- **La règle frontière v3 ne voit pas les règles métier.** Ses 6 mécanismes nommés (chiffrement, synchronisation…) ne couvrent pas les cas limites d'un métier (poids qui ne totalisent pas, RC qui se contredit) : 0 % de frontières sur P12.
- **Sur de vraies entrées, le banc ne sait pas encore mesurer la compilation.** P12 : taux brut 0 sur les 5 RC publics à toutes les itérations. Un taux mesuré sur un générateur ne vaut que pour ce générateur.
- **Une sonde tirée d'un projet client reste une sonde.** P12 (BuildForge) a produit un audit (`docs/audit-BuildForge.md`), mais le banc ne corrige rien dans le code mesuré.

## Arborescence

```
CLAUDE.md                      ce fichier
docs/SPEC-banc.md              spec fonctionnelle du banc (45 assertions strictes)
docs/theses.md                 registre des thèses H1-H29 (+ cadre théorique L*)
docs/pistes.md                 carnet des pistes en attente (graphes, maths, produit), rien à lancer sans plan
docs/HISTORIQUE.md             la conversation d'origine, résumée
prompts/decompositeur-strict.md  consigne exacte des passes aveugles (v1)
prompts/decompositeur-strict-v2.md  v1 + règle 5 (assertions frontière, « | frontière: oui »)
prompts/decompositeur-strict-v3.md  v2 avec la règle 5 précisée (6 mécanismes nommés + test d'exclusion)
prompts/decompositeur-strict-v2-xl.md, -v3-xl.md  mêmes consignes pour 100 à 160 assertions (grosse sonde)
data/predictions/<sonde>.md    prédictions figées avant les passes (commit qui fait foi)
data/sondes.md                 les 10 sondes, leur description et leur k
data/passes/strict/            23 passes aveugles strictes (P01_A ... P10_D)
data/passes/strict-v2/         passes v2 des 10 sondes (jamais comparées aux v1)
data/passes/strict-v3/         passes v3 de P02, P07, P08, P10 (frontières)
data/passes/strict-v2-xl/, strict-v3-xl/  passes de la grosse sonde P11
data/passes/aveugle-libre/     4 passes aveugles sans la règle stricte (historique)
data/passes/claude-libre/      passes écrites par Claude (biaisées, historique)
outils/mesure.py               calcule k, réseau, champ et concordance
outils/passe_aveugle.py        lance une passe aveugle stricte (claude -p neuf, dossier vide)
outils/duel.py                 fait tourner le protocole adversarial sur une sonde, tour par tour (--attaque-seule : trous a priori)
outils/causes.py               champ local compté par cause d'échec (même message = une cause)
outils/differentiel.py         test différentiel (H20) : générateur, greens indépendants, traces, paires, juge
outils/quatre.py               accord entre N greens sur les mêmes situations (qui s'écarte seul, sur quelle action)
outils/boucle.py               la boucle de compilation (H21) : lots de 4 greens, double juge, trous → assertions, bugs → tests
outils/taux_spec.py            taux brut, taux « spec » (bugs = accord) et taux par action de chaque itération
outils/maths.py                lecture mathématique sans modèle : λ et p, relaxation, trous non vus, corrélation des greens
outils/fiedler.py              G2 : λ2 de Fiedler des passes v2 contre k (H24), écrit data/fiedler.json
runs/<sonde>/                  duel V0 (passes v1, green sonnet, une attaque)
runs-v1/<sonde>/               duel V1 (passes v2, green haiku, deux attaques, mécanismes réels)
runs-v2/<sonde>/               duel V2 (P02, P06, P07 : H18)
runs-v2-apriori/<sonde>/       attaque 1 du red seule (H15, H16)
runs-v3-apriori-B/<sonde>/     même attaque par un red neuf (reproductibilité du red)
runs-v4/<sonde>/               test différentiel : generateur.py, greens/, paires/, accord-*.json (traces/ non versionné)
runs-v4-duel/P11/              duel complet de la grosse sonde
runs-boucle/P11/               la boucle : it<i>/ (spec, tests, lots, décisions), budget.jsonl, taux.json, maths.json
docs/duel-V0.md … V4           rapports des duels
docs/boucle-P11.md             rapport de la boucle de compilation
docs/V5-cadrage.md             V5 : repo client BuildForge, tranche « du RC au plan du mémoire », RC publics, modèles ouverts, budget
docs/V5.md                     rapport de V5 (sonde P12) : boucle, vérification à 4 greens, H23, green Bilel
docs/audit-BuildForge.md       ce que le banc a trouvé dans le code de BuildForge (livrable, le banc ne corrige rien)
outils/v5/                     V5 : générateur de RC, boucle_v5.py, H23 (h23_passer.py, h23.py, shim_sonnet.py), bilel.py
adaptateurs/bilel/             appelle le code BuildForge tel quel (Rust) sur des pages
runs-v5/, runs-v5-duel/        données de V5 (boucle, H23, budget)
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
