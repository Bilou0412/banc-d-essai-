# Carnet des pistes en attente

Rien ici n'est à exécuter tant qu'un plan ne le choisit pas. Chaque piste porte : son coût estimé, son lien avec le cap (une spec compilable), et la thèse à créer si on la lance.

Coûts : « gratuit » = calcul local sur les passes et traces déjà là, sans appel de modèle ; « $ » = demande des appels (ordre de grandeur donné).

## Pistes notées (20 novembre)

### Théorie des graphes, calculables gratuitement sur les passes et traces existantes

**G1. Dendrogramme du réseau d'assertions.** Des communautés hiérarchiques (par ex. Louvain multi-niveaux) sur le réseau d'assertions donnent les étages du milieu de la pyramide, construits par le bas. Test : deux passes d'une même sonde donnent-elles le même arbre ? (prolonge H9)
- Coût : **gratuit**. `networkx` est déjà là, et il y a 23 passes v1, les passes v2 et v3 et 2 passes xl.
- Lien avec le cap : si l'arbre se répète, la spec a une structure stable, ce qui est une condition pour que deux codes la lisent pareil. On pourrait aussi voir si les trous de la boucle P11 tombent aux **frontières entre communautés**.
- Thèse à créer : **H23** « Deux passes aveugles d'une même sonde donnent le même dendrogramme d'assertions », avec un critère chiffré (par ex. indice de Rand ajusté ≥ 0,6 au 2e niveau).

**G2. Valeur de Fiedler λ2 du laplacien**, vue comme la vitesse de propagation d'une décision dans la spec. Candidate pour remplacer k comme mesure de densité. Test : λ2 prédit-il mieux que k les tours ou le nombre de trous ?
- Coût : **gratuit**. Les tours viennent des duels V0 à V4, les trous de V4 et de la boucle.
- Lien avec le cap : si λ2 annonce les trous, on sait **avant** le code où la spec ne compilera pas.
- Thèse à créer : **H24** « λ2 prédit le nombre de tours (ou de trous) mieux que k », comparée en ρ de Spearman sur les mêmes sondes. La reproductibilité de λ2 entre passes se vérifie d'abord, comme pour k (H13).

**G3. Coloration du graphe et coupe minimale.** La coloration donne le nombre minimal de vagues de travail parallèle. La coupe minimale donne une répartition entre agents.
- Coût : **gratuit** pour le calcul. **$** pour le valider : il faudrait des greens qui construisent par morceaux, à peu près le prix d'un duel par sonde.
- Lien avec le cap : indirect. Une coupe qui sépare mal deux agents crée des divergences à la couture.
- Thèse à créer : **H25** « Construire en parallèle selon la coupe minimale ne baisse pas le taux de compilation, par rapport à un seul green ».

**G4. Graphe signé et cycles frustrés** (équilibre de Harary), pour détecter les contradictions avant le code.
- Coût : **gratuit** si le signe des arêtes se déduit du texte des assertions par règle. **$** (petit, environ 1 $ par sonde) s'il faut un modèle pour signer les arêtes.
- Lien avec le cap : **direct**. Une contradiction est un cas où deux codes ne peuvent pas suivre la spec de la même façon. On a des exemples réels : C07 contre A99, C15 contre P1, C33 contre A50 et C20.
- Thèse à créer : **H26** « Les cycles frustrés du graphe signé annoncent les assertions que la boucle a dû réécrire ou écarter ». Test rétrospectif possible sur la boucle P11.

### Maths et théorie

**M1. Le cadre L* d'Angluin** (déjà noté dans `theses.md`), pour viser des garanties de convergence.
- Coût : **gratuit** (travail théorique).
- Lien avec le cap : il donnerait une **borne** sur le nombre d'itérations pour qu'une spec compile, au lieu d'une courbe constatée.
- Thèse à créer : **H27** « Le nombre de questions au client nécessaires pour compiler une spec est borné par une fonction de sa taille (assertions, états) », à formuler après lecture.

**M2. Géométrie hyperbolique (disque de Poincaré)**, forme naturelle d'une pyramide : plonger les assertions pour mesurer des distances entre specs.
- Coût : **gratuit**, mais à faire après G1, puisqu'il faut un arbre à plonger.
- Lien avec le cap : faible pour l'instant. Il permettrait de comparer deux specs (par ex. v0 et v6 de P11) autrement que par le nombre d'assertions.
- Thèse à créer : **H28** « La distance hyperbolique entre deux passes d'une même sonde est plus petite qu'entre deux sondes », comme critère de reproductibilité.

**M3. Shannon : ordonner les questions au client par l'information qu'elles apportent** (déjà utilisé en principe dans le tri).
- Coût : **gratuit** sur les données de la boucle : chaque trou y a un poids, le nombre de divergences qu'il explique.
- Lien avec le cap : **direct**. P1 a tranché à lui seul 24 % des divergences des itérations 0 et 1. Poser d'abord les questions qui en tranchent le plus fait monter le taux plus vite.
- Thèse à créer : **H29** « Ordonner les questions par information gagnée atteint le même taux de compilation avec moins de questions que l'ordre de découverte ».

### Produit

**P1. Dashboard du banc** : courbe de la boucle, thèses, taux de compilation par projet. Plus tard.
- Coût : **gratuit** en modèle (une page à partir de `runs-boucle/*/taux.json` et `docs/theses.md`). Seulement du temps.
- Lien avec le cap : il rend le taux de compilation **visible** projet par projet.
- Thèse à créer : aucune, c'est un outil.

**P2. Un vrai projet client dans la boucle, avec de vraies questions.**
- Coût : **$**, environ 60 à 80 $ pour une boucle complète au réglage de P11 (passes, duel, 6 à 7 itérations), plus le temps du client pour répondre.
- Lien avec le cap : c'est **le test réel du cap**. Une spec de client compile-t-elle ? Et que coûtent les questions à poser au client ?
- Thèse à créer : **H22** est déjà proposée (conventions contre questions client). Elle se mesurerait sur de vraies réponses, au lieu d'un classement après coup.
