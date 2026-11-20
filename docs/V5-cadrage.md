# V5 : cadrage (projet client + G2)

20/11/2026. Rien de payant n'a été lancé. Ce document attend ton accord (§9).

## 1. Ce que contient le repo BuildForge

Le repo a **deux codes très différents** selon la branche. C'est la première chose à savoir.

```
main  (15/10)  Next.js + Supabase, prototype navigateur          ← abandonné
               src/lib/dce/ : ~500 lignes de regex (RC, CCAP, AE),
               un « plan du mémoire » simple (memo.ts), une DPGF éditable.

dev   (24/10)  serveur Rust (axum) + front React, déployé sur Fly  ← le vrai code
               server/src/dce/ : ~11 000 lignes
```

Sur `dev`, le parcours d'un DCE :

```
 ZIP du DCE ──► inventaire ──► texte page par page ──► classement ──► faits du RC ──► fiche web
                (plafonds)     PDFium + OCR Tesseract   (RC, CCAP…)    NuExtract propose,
                                                                      le texte décide
```

| Brique | État | Où |
|---|---|---|
| Inventaire du ZIP (pièces, type, lot) | marche, testé | `server/src/dce/inventory.rs`, `classify.rs` |
| Lecture du texte (PDF, scans, Word, ODT, tableurs) | marche, testé | `text.rs` (1 232 lignes) |
| Faits du RC : date et heure limites, questions, procédure, lots, visite et ses dates, mode de remise, validité, variantes | marche | `facts.rs` (1 985 lignes) |
| Critères d'attribution (poids, rang, sous-critères, par lot, alerte environnement, poids qui ne totalisent pas) et pièces à remettre | marche | `facts/award.rs` |
| Lecture des tableaux d'un PDF | **en cours**, gros chantier : une spec de 700 Ko, 236 décisions, des centaines de tests, mené avec ton protocole adversarial | `tables/`, `specs/lecture-tableaux/` |
| Comptes, organisations, dépôts, audit, sauvegardes | marche | `accounts.rs`, `deposits.rs`, `audit.rs`, `db/` |
| Import direct depuis PLACE | en cours | `place.rs` |
| Plan du mémoire, contrôle de conformité, export | **absent** sur `dev` (seule la version simple de `main` existe) | — |
| Risques du CCAP, DPGF | absent (lacunes reconnues de ta spec produit) | — |

Le point clé pour le banc : ton extracteur de faits n'est pas déterministe à lui seul. Un **modèle local (NuExtract 3, via llama.cpp, température 0)** propose les valeurs, puis ton code ne garde que celles qu'il retrouve dans le texte de la page. Il couvre 11 faits.

## 2. Confidentialité : ce que j'ai trouvé

Aucun secret : `.env.example` a des valeurs vides, aucune clé ni mot de passe dans les fichiers suivis. Je n'ai lu que le dernier état des branches `main` et `dev`, pas l'historique git.

Deux traces qui ressemblent à un vrai dossier :

1. **`main`, `tests/unit/dce-sandbox.test.ts`** : le test contient le début d'un vrai RC : « Consultation n° 2600671 », « Construction d'un CDI et de 4 salles de classe au lycée Alain », Région Île-de-France, date limite du 22/09/2026, toute la grille de notation. `docs/dce-sandbox.md` parle du « marché 2600671 » comme du vrai DCE. Si c'est le dossier de ton client, il est dans le repo.
2. **`dev`, `server/src/dce/classify.rs`** (vers la ligne 270) : des noms de fichiers « vus dans un DCE déposé », dont `PGC_Alain_BD.pdf` et `RICT-CT_CDI+4 salles.pdf` (la même opération), et surtout `Extrait KBIS - Entreprise 04.06.2026.pdf`, `RIB BANQUE.pdf`, `Attestation d'assurance 2026-2027.PDF`. Ce sont des noms de pièces d'une entreprise candidate, pas d'un acheteur. Seuls les noms y sont, pas les contenus.

Rien de tout cela n'entre dans le banc. Je ne modifie pas ton repo ; c'est à toi de décider s'il faut nettoyer.

## 3. La découpe et la tranche proposée

```
                    ┌──────────── partie compilable ─────────────┐
 PDF ─► texte ─►    │ faits ─► arbre des critères ─► plan ─► contrôle │ ─► JSON   ║  rédaction
 (fixé, commun)     └────────────────────────────────────────────┘           ║  (frontière,
                                                                              ║   hors boucle)
```

**Tranche V5 : « du RC au plan du mémoire vérifié »**, sans rédaction. Entrée : le texte du RC, page par page. Sortie : un JSON comparable entre deux codes, avec :

- les faits : lots, date et heure limites, questions, procédure, visite, variantes, validité, mode de remise ;
- les pièces à remettre (partie candidature, offre ou attributaire ; obligatoire ou non) et les **limites de pages** du mémoire quand le RC en donne ;
- l'arbre des critères : libellé du RC, poids (%, points) ou rang, sous-critères, lot ;
- le plan du mémoire : une section par critère ou sous-critère noté sur la valeur technique, dans l'ordre du RC, avec son poids et sa page source ;
- le contrôle : chaque critère technique a sa section, les poids se recoupent, sinon une alerte nommée.

Deux choix que j'ai faits, révisables :

- **La lecture du PDF reste hors de la tranche.** Tous les greens reçoivent le même texte (`pdftotext`, une page par page). Sinon, on mesurerait les bibliothèques PDF, pas la spec. Ton green garde ce même texte en entrée : ton code accepte un `Document` fait de pages, sans passer par PDFium.
- **Les greens écrivent du code déterministe**, sans modèle au moment de l'exécution. Ton green est l'exception (NuExtract à température 0). Si ton green diverge à cause de son modèle, le juge le verra comme un bug ou un trou, comme pour les autres.

**Les 300 situations.** Avec 5 RC réels, la boucle n'aurait que 5 situations. Je propose un **générateur de RC synthétiques** (comme pour P11), avec un tirage par graine : critères en %, en points ou classés, sous-critères, critères par lot, pièces sur plusieurs pages, poids qui ne totalisent pas, RC qui se contredit, limites de pages. Il donne 295 RC, plus les 5 RC publics. Le générateur ne donne pas la « bonne réponse » ; on compare seulement les codes entre eux. Il respecte aussi la règle de ton repo : des fichiers synthétiques en test.

## 4. Les 5 RC publics proposés (à valider avant usage)

Tous publiés, avec une date limite passée. Je n'en ai lu que le résumé ; rien n'est téléchargé.

| # | RC | Type | Ce qu'il teste |
|---|---|---|---|
| 1 | [Plivot, rue Jeanne d'Arc](https://epernay.fr/sites/epernay-agglo/files/document/mp_2026-06pl_rc.pdf) (Epernay Agglo), 13 p. | Voirie, MAPA, lot unique | Poids en % et sous-critères en points dans le même RC (60 % / 30 % : 20 + 10 pts / 10 % environnement) |
| 2 | [Maison de l'eau, Épernay](https://epernay-agglo.fr/sites/epernay-agglo/files/document/mp_2026-34ca_rc.pdf), 17 p. | Bâtiment neuf, appel d'offres ouvert, **20 lots**, DPGF | Barème sur 100 points ; référence incohérente dans le RC (34CA en tête, 34CC en pied de page) |
| 3 | [Ministère des Armées, La Réunion, lots 01 à 24](https://betterplace.info/files/3020689-reglement.pdf) | Accord-cadre à bons de commande, entretien, 24 lots | **Poids qui changent selon le groupe de lots** (30 % ou 35 % de technique), RC long |
| 4 | [Église de Sainte-Marguerite-sur-Mer, tranche 3](https://www.ste-marguerite-sur-mer.fr/wp-content/uploads/2026/01/rc-eglise-ste-marguerite-tranche-3.pdf), 12 p. | Patrimoine, petite commune | **RC qui se contredit** (« lot unique » puis « les deux lots »), un « coefficient de 2 » non expliqué, mémoire pré-établi |
| 5 | [Pierres sèches de Llasseres](https://www.parc-pyrenees-catalanes.fr/wp-content/uploads/sites/7/2026/08/RC_Llasseres_Lot01_PierresSeches_vf.pdf) (Parc des Pyrénées catalanes), 10 p. | Restauration, MAPA, tranche ferme + 2 optionnelles | Valeur technique sans sous-critères (60/40), tranches |

Je n'ai pas vérifié qu'ils ne sont pas déjà dans le banc réel de ton repo (tu y as une douzaine de RC publics). S'ils y sont, ton code a pu être réglé dessus, et ton green partirait avec un avantage : dis-le-moi et j'en change.

## 5. Les modèles ouverts

- **Qwen3-Coder** (Alibaba) et **Devstral** (Mistral), dans leur dernière version au catalogue le jour du lancement. Deux familles différentes, entre elles et de Claude. Devstral est français, ce qui va avec H23.
- **Hébergeur : OpenRouter**, une seule clé pour les deux. Seuls les RC publics et synthétiques leur sont envoyés.
- **Le harnais** : Claude Code ne pilote pas ces modèles. J'écris `outils/agent_ouvert.py`, une petite boucle « écrire le code, lancer les tests, lire les échecs » avec les **mêmes règles** que les greens Claude (4 tours au plus, mêmes tests, délai d'une heure par appel). Limite à noter : le harnais n'est pas le même que celui de Claude Code, donc une partie de l'écart de H23 peut venir de l'outil et non du modèle.

## 6. Ce qui change par rapport à P11

| | P11 | V5 |
|---|---|---|
| Lot | 2 haiku, 2 sonnet | haiku, sonnet, Qwen3-Coder, Devstral ; green Bilel comparé à part |
| Trous « client » | 7 cas soumis après coup | **porte avant d'écrire** : un juge classe chaque trou en « convention » ou « client » ; seuls les « client » te remontent, en A / B avec exemples, classés par divergences tranchées et groupés par principe candidat ; tu tranches le principe, puis j'écris les assertions |
| Conventions | tranchées par la majorité | tranchées par moi, notées dans le journal, révisables |
| Bugs → tests | à partir de l'itération 6 | dès l'itération 1 |
| Délai par appel | 30 min | 1 h |
| Arrêt | taux ≥ 0,9, pas de hausse 2 fois, budget | **taux spec** ≥ 0,9, pas de hausse 2 fois, budget (je préviens avant) |

## 7. G2, déjà fait (gratuit)

Prédiction figée avant calcul (`data/predictions/G2-H24.md`), outil `outils/fiedler.py`, résultat dans `data/fiedler.json`.

```
Écart relatif entre deux passes d'une même sonde (médiane des 11 sondes v2)

  k   ██                       6,7 %
  λ2  ████████████            41,8 %   (6 fois moins reproductible ; prédit : au moins 3 fois)
```

- λ2 ne se répète bien que sur 4 sondes sur 11 (P06, P07, P08, P11). Sur P10, une passe a 59 % de ses assertions hors du bloc principal, et λ2 varie d'un facteur 13.
- **Tours** (7 sondes) : ρ(λ2) = −0,17, contre ρ(k) = −0,32. λ2 ne fait pas mieux que k, et aucun des deux ne prédit les tours. **H24 réfutée pour les tours**, comme prédit.
- **Trous** : seulement 2 sondes avec des trous mesurés, donc pas testable. On le retestera sur la tranche V5, section par section.

En clair : λ2 regarde la plus faible connexion du réseau, et c'est justement ce qui change le plus d'un auteur à l'autre. k fait une moyenne, il est plus stable.

## 8. Budget estimé

| Poste | $ |
|---|---|
| 2 passes v2 + 2 passes v3 sur la tranche | 2 |
| Spec v0 (passe A) + duel complet (tests du red) | 8 |
| Générateur de RC synthétiques et adaptateur du green Bilel | 3 |
| 6 itérations × ~9 $ (haiku 0,7 ; sonnet 2,2 ; 2 ouverts ~1 ; 2 juges opus sur 16 groupes ~4 ; red ~1,2 ; juge client/convention ~0,3) | 54 |
| Green Bilel (NuExtract en local sur la machine) | 0 |
| **Total** | **≈ 67 $** |

Je propose un plafond de **75 $**, avec une alerte à 60 $.

## 9. Ce qu'il me faut pour lancer

1. **Ton accord** sur la tranche, les 5 RC, les deux modèles et le budget.
2. **L'accès réseau.** Ce fil tourne sur l'environnement intégré par défaut, sans réglages : il bloque OpenRouter, Hugging Face (pour télécharger NuExtract) et les sites des RC. Il faut créer un environnement cloud dans [Project settings](#project-settings/environment) (menu Cloud environment → Add cloud environment), avec ces domaines autorisés : `openrouter.ai`, `huggingface.co`, `epernay.fr`, `epernay-agglo.fr`, `betterplace.info`, `ste-marguerite-sur-mer.fr`, `parc-pyrenees-catalanes.fr`. Pour les RC, tu peux aussi m'envoyer les 5 PDF dans le fil.
3. **La clé OpenRouter**, dans ce même environnement, en variable `OPENROUTER_API_KEY`. Ne la colle pas dans le chat.
4. Un nouvel environnement n'est pris que par une **nouvelle session** : la boucle tournera dans un nouveau fil, qui reprendra ce cadrage et les prédictions figées.

## 10. Révision du 20/11, après ta réponse

**Ce qui change.**

- Plus de modèles hébergés, plus d'OpenRouter. Le lot : **haiku et sonnet** écrivent le code de la tranche ; **ton code** est le green Bilel, comparé sur ses 11 faits.
- **Chaque fait du RC devient une assertion atomique** de la spec (observé : le fait ; conditions : ce qui change sa valeur), et la règle « une valeur n'est gardée que si elle est retrouvée dans la page » fait partie de la spec.
- **H23 redéfinie** : ton pipeline (NuExtract local + vérification dans la page) contre sonnet, qui lit les mêmes pages sous la même règle. Sur les RC synthétiques, le générateur connaît la vérité : on mesure la **justesse** des deux, fait par fait. Sur les 5 RC publics, on mesure leur **accord**. On compte aussi la part des faits confirmés par l'algorithme seul, et la liste des faits où le petit modèle échoue. Seuil et prédictions figés dans `data/predictions/V5.md` (complément du 20/11, 17 h).

```
              ┌─────────────────────────────┐
  pages ───►  │ NuExtract (local, T = 0)    │──► valeur proposée ──► retrouvée dans la page ? ──► fait
  du RC       └─────────────────────────────┘                          non : « non trouvé »
              ┌─────────────────────────────┐
  pages ───►  │ sonnet (modèle fort)        │──► valeur proposée ──► même vérification       ──► fait
              └─────────────────────────────┘
                       justesse face à la vérité du générateur (synthétiques), accord entre eux (publics)
```

**Faisabilité de NuExtract en local.**

- Ton serveur de production le fait déjà tourner sur CPU : `extractor/fly.toml` sert NuExtract 3 (fichier `NuExtract3-Q4_K_M.gguf`) avec llama.cpp sur une machine Fly *performance-4x* de **8 Go**, 4 fils, contexte de 8 192 jetons, et ton commentaire dit qu'une requête « peut prendre plusieurs minutes sur CPU ».
- Mon environnement : 4 cœurs Xeon avec AVX-512, 15 Go de mémoire, 60 Go de disque libres. C'est au moins la machine de production : **NuExtract y tient.**
- **llama.cpp compile ici** : `llama-server` et `llama-bench` construits pour ce processeur (AVX-512), en quelques minutes. Le seul blocage est le téléchargement du modèle : cette session n'a pas encore ton nouvel environnement, qui ouvre `huggingface.co`. Un nouveau fil lancé sur cet environnement le fera.
- Durée attendue, à mesurer au premier RC : 1 à 3 minutes par RC synthétique court (une seule tranche de texte), plusieurs minutes par RC public long. Le pipeline ne change pas d'une itération à l'autre : on le passe **une seule fois** sur les 300 RC, en tâche de fond, soit **5 à 15 heures de calcul, 0 $**. Si c'est trop long, 100 synthétiques + 5 publics suffisent pour H23.
- Sur ton Dell XPS (i7-9750H, 6 cœurs, AVX2, 32 Go), ça tourne aussi, à une vitesse comparable : llama.cpp compilé pour CPU, le même fichier GGUF, `llama-server` lancé avec `--ctx-size 8192 --threads 6 --temp 0`, et `EXTRACTOR_URL=http://localhost:8080`. On n'en a besoin que si l'environnement cloud bloque.

**Budget recalculé, sans modèles hébergés.**

| Poste | Ton choix : 1 haiku + 1 sonnet | Variante : 2 haiku + 2 sonnet |
|---|---|---|
| Passes v2 et v3 sur la tranche | 2 | 2 |
| Spec v0 + duel complet | 8 | 8 |
| Générateur de RC synthétiques + adaptateur du green Bilel | 3 | 3 |
| Référence H23 : sonnet lit 300 RC (11 faits) | 5 | 5 |
| NuExtract local sur 300 RC | 0 | 0 |
| Par itération : greens | 2,9 | 5,8 |
| Par itération : 2 juges, red, juge client/convention, bugs → tests | 5,1 | 6,2 |
| 6 itérations | 48 | 72 |
| **Total** | **≈ 66 $** | **≈ 90 $** |

La variante coûte 24 $ de plus. Ce qu'elle achète : avec une seule paire, un trou ne se voit que si haiku et sonnet ont choisi différemment. Sur P11, chaque paire ne voyait qu'une partie des trous (H20 réfutée pour cette raison), et 4 greens en trouvaient bien plus. Avec une paire, le taux montera plus vite, mais il dira moins bien si la spec compile vraiment. Je recommande quand même **ton choix à 66 $** pour cette tranche : H23 n'en dépend pas, et la boucle reste comparable d'une itération à l'autre. On ajoute des greens si le taux spec dépasse 0,8, pour vérifier qu'il tient.

Plafond proposé : **70 $**, alerte à 55 $.
