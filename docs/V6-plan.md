# V6 : plan proposé (rien n'est lancé)

22/11/2026. Deux pistes, dans l'ordre de tes priorités. La piste c (compilation sur entrées réelles) est laissée de côté : elle demande d'abord de savoir quoi mesurer, et les deux pistes ci-dessous n'en dépendent pas.

## Piste A : la part déterministe (thèse H30, à créer)

**Thèse H30.** Une grande part des assertions d'une spec atomique est satisfaite par un algorithme déterministe, sans LLM. Le LLM ne sert qu'à une minorité d'assertions, qu'on peut nommer d'avance.

**Mesure, sans aucun appel payant.** On réutilise les données déjà là :

```
 assertion ──► état observé ──► champ de sortie (P12) / action (P11)
                                     │
             4 greens déterministes, écrits sur la même spec, 300 situations
                                     │
     « satisfaite sans LLM » si : les 4 codes sont d'accord sur ce champ dans ≥ 95 % des situations
                                   ET (P12, où la vérité est connue) justes dans ≥ 95 % des RC
```

- **P12** : les 4 greens de it4 (tous déterministes), les 300 RC, et la vérité du générateur sur 100 RC. On a aussi, par fait, la justesse de NuExtract et de sonnet. On peut donc classer chaque fait : le déterministe suffit, un modèle aide, ou personne ne sait.
- **P11** : les 4 greens de la dernière itération et le taux par action (`outils/taux_spec.py`). Je te dois une franchise : sur P11, il n'y a aucune entrée en langue libre, donc la question « sans LLM » y est presque triviale (tout est déterministe). Ce que P11 mesure, c'est seulement la part des assertions que la spec rend **compilable** par du code déterministe. C'est utile comme point de comparaison, pas comme preuve de la vision.
- **Le travail** : une table assertion → champ ou action (≈ 180 assertions pour P12, ≈ 230 pour P11), faite à la main puis relue, et un petit outil `outils/part_deterministe.py`.
- **Prédiction à figer avant le calcul** (proposition) : P12 ≥ 70 % des assertions satisfaites sans LLM ; les autres se concentrent sur les critères (sous-critères, lots) et les pièces. P11 ≥ 85 %.
- **Coût : 0 $.** Temps : une demi-journée de session.

## Piste B : H23 sur une sonde d'une autre nature (H23b, à créer)

**Thèse H23b.** Avec une spec atomique et ses tests comme vérification, un petit modèle local **écrit le code** presque aussi bien qu'un modèle fort. Ce n'est plus une extraction, c'est de la génération de code.

**Sonde : P02 (recettes).** Tout existe déjà : spec, tests du duel, générateur de situations et 4 greens de V4 (2 haiku, 2 sonnet) comme référence.

```
 spec P02 + tests ──► petit modèle local (llama.cpp, CPU) ──► app.py ──► tests (vérification)
                                                                 │
                       taux de compilation contre les 4 greens de V4, sur les mêmes 300 situations
```

- **Modèle local** : un modèle de code ouvert de 7 milliards de paramètres en GGUF (par exemple Qwen2.5-Coder-7B-Instruct, Apache-2.0), avec le même llama.cpp qu'en V5. Aucun modèle hébergé.
- **Harnais** : une petite boucle « écrire app.py → lancer les tests → lire les échecs », 4 tours au plus, avec les mêmes règles que les greens Claude. Limite à noter : ce n'est pas le harnais de Claude Code, donc une partie de l'écart peut venir de l'outil.
- **Seuil à figer** (proposition) : H23b confirmée si le taux de compilation du green local avec les greens sonnet est à 0,10 ou moins de celui de haiku avec sonnet. Je prédis qu'elle est **réfutée** : écrire un module entier est plus dur qu'extraire une valeur que la page contient déjà.
- **Coût** : 0 $ pour le modèle local. 1 à 2 $ si un juge classe les divergences. Temps de calcul : 4 tours × environ 15 min sur 4 cœurs, puis le rejeu.

## Budget

| | Coût | Garde-fou |
|---|---|---|
| Piste A | 0 $ | — |
| Piste B | 1 à 2 $ | 5 $ |
| **Total** | **≤ 2 $** | **5 $** |
