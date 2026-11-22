# Ce que le banc a trouvé dans BuildForge (sonde P12)

22/11/2026. Livrable pour le fil BuildForge. **Le banc ne corrige rien dans BuildForge.** Il dit seulement ce qu'il a vu.

Code mesuré : `server/src/dce/facts.rs` et `facts/award.rs`, branche `dev`, commit `7785634` (pris tel quel, voir `adaptateurs/bilel/`).
Entrée : le texte page par page (295 RC synthétiques du générateur + 5 RC publics, `pdftotext -layout`). Ce n'est pas la lecture PDFium de BuildForge.
Modèle : NuExtract 3 Q4_K_M en local, température 0. La référence est sonnet, sous la même découpe et la même vérification.
Sources des chiffres : `docs/V5.md` §5 et §6, `runs-v5/h23/resultat.json`, `runs-v5/boucle/it4/bilel.json`.

## Comment lire

- **Justesse** : la part des RC synthétiques où le fait rendu est exactement le vrai (le générateur connaît la vérité). Elle est mesurée sur 100 RC.
- **Divergences** : les RC où ton code rend autre chose que deux greens écrits sur la spec v4, quand ces deux greens sont d'accord entre eux. Un juge opus a classé le cas le plus court de chaque fait.
- **Code ou modèle ?** Quand NuExtract et sonnet font la même erreur, c'est le code (la découpe, le gabarit, la vérification, les règles). Quand seul NuExtract se trompe, c'est le modèle.

## Les constats, du plus coûteux au moins coûteux

| # | Constat | Mesure | Code ou modèle | Où regarder |
|---|---|---|---|---|
| 1 | La partie « attributaire » d'une pièce n'est pas reconnue quand le RC écrit « le candidat auquel il est envisagé d'attribuer le marché » (la tournure du code de la commande publique). Les pièces passent dans « offre ». | Justesse des pièces : 0,24 avec NuExtract, 0,25 avec sonnet. 74 échecs sur 76 viennent de là. 77 divergences à it4. | **Code** | `facts/award.rs:258`, regex `ATTRIBUTAIRE` (« attributaire », « candidat retenu », « titulaire pressenti », « candidat dont l'offre… », « candidat classé premier ») |
| 2 | Des faits faux affichés comme trouvés : une valeur vraie, retrouvée dans la page, mais au mauvais endroit (surtout la partie d'une pièce, voir 1). La vérification par le texte ne peut pas arrêter cette erreur. | 17,6 % des faits rendus « trouvés » avec NuExtract, 10,7 % avec sonnet. La prédiction était ≤ 2 %. | Code surtout | Le rattachement d'une valeur à sa partie (pièces), à son lot (critères), à son fait (dates) |
| 3 | Deux dates limites différentes dans le même RC : une seule est gardée, au lieu du statut « conflict » avec les deux. | Justesse 0,89 pour les deux modèles ; 11 RC sur 11 qui se contredisent. 12 divergences à it4. | **Code** (le gabarit) | `extractor.rs`, `TEMPLATE` : `"date_limite_offres"` n'a qu'une case. Le modèle ne peut proposer qu'une date, donc la vérification n'en voit jamais deux. Hypothèse, non vérifiée dans le code de fusion. |
| 4 | Des critères communs à un groupe de lots (« Pour les lots n° 01, 2 : … », le lot 03 ayant les siens) sont rendus sans lot, au lieu d'être rattachés aux lots 1 et 2. | Critères par lot : 8/16 justes pour les deux modèles. 8 divergences à it4. | **Code** | Le champ `lot` du gabarit (`"lot": "verbatim-string"`, une seule valeur) et le rattachement dans `award.rs` |
| 5 | « Lot unique » puis des lots numérotés dans le même RC : le lot unique disparaît, sans conflit. Contraire à P3 (rien n'est perdu). | 0 RC sur 4, pour les deux modèles. | **Code** | La fusion des lots dans `facts.rs` (le lot unique est-il écarté quand des lots numérotés existent ?) |
| 6 | « Il n'est pas prévu de décomposition en lots » (RC public 1, Plivot, page 4) n'est pas reconnu comme un lot unique : aucun lot n'est rendu. | 2 divergences à it4 (RC1). | **Code** | `facts.rs:828`, regex `LOT_UNIQUE` (« lot unique », « un seul lot », « non alloti », « n'est pas alloti », « pas l'objet d'un allotissement ») |
| 7 | Sous-critères en points sous un critère en %. NuExtract les rate plus souvent que sonnet. | 12/22 avec NuExtract, 19/22 avec sonnet. Critères au total : 0,72 contre 0,92. | **Modèle** | Le seul vrai écart entre NuExtract et sonnet (H23). Une règle ou une lecture de tableau le fermerait. |
| 8 | Mode de remise : NuExtract garde une bonne phrase, mais coupée avant l'adresse de la plateforme. | 45 RC sur 100. Sonnet garde l'adresse sur 100 RC. | Modèle | Sans gravité si le produit veut seulement « électronique ou papier » ; à savoir si la fiche doit montrer l'adresse. |
| 9 | Lot unique avec sonnet : rien n'est rendu (« non trouvé ») sur 32 RC, alors que NuExtract le rend sur 96 %. | Justesse des lots 0,64 avec sonnet. | Interaction du modèle et du gabarit | À savoir seulement si tu changes un jour de modèle : ton gabarit est réglé pour NuExtract. |

**Un cas non retenu.** Sur le RC public 4, une date de visite n'est pas trouvée (1 divergence). Le texte vient de `pdftotext -layout`, qui y mélange deux colonnes sur la même ligne. Ce n'est probablement pas ton code, mais ma lecture du PDF.

## P3 : la décision RC douteux, et ce qu'elle demande au code

> Le RC fait foi dans ses mentions explicites, rien n'est perdu, toute incohérence est signalée.

| Cas vu par le banc | Ce que fait ton code aujourd'hui | Ce que P3 demande |
|---|---|---|
| « MAPA » dans la référence (« 2026-MAPA-71 »), « appel d'offres restreint » dans le texte | La procédure est juste à 0,90 pour les deux modèles ; 3 des 10 échecs sont ce cas (la procédure de la référence l'emporte ou s'ajoute) | La procédure nommée dans le texte, et une alerte qui signale l'écart avec la référence |
| « Lot unique » puis « Lot 1 », « Lot 2 » | « found » avec les lots 1 et 2 seulement : le lot unique est perdu, sans conflit (0 RC sur 4 justes, pour les deux modèles) | Le lot unique et les lots numérotés gardés, et l'incohérence signalée |
| Deux dates limites différentes | Une seule est gardée (constat 3) | Les deux gardées, et le conflit signalé |
| Poids qui ne totalisent pas 100 | `CriteriaChecks` le signale déjà (`WeightIssue`) | Conforme |

## Ce que le banc n'a pas mesuré

- La lecture du PDF (PDFium, OCR) : le banc donne le même texte à tous les codes.
- Le plan du mémoire et le contrôle : ils n'existent pas sur `dev`.
- Les faits sur les 195 autres RC synthétiques : NuExtract a été arrêté à 100, ce qui suffit pour les écarts ci-dessus.
