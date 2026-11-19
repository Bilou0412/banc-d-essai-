# Consigne du décompositeur aveugle (règle stricte, v3)

v3 = v2 (`decompositeur-strict-v2.md`) avec la règle 5 précisée : « mécanisme invisible » devient une liste fermée de six mécanismes et un test d'exclusion. Pourquoi : en v2, P07 donnait 3 frontières dans une passe et 7 dans l'autre. La passe A ne marquait que les cas de transmission partielle et d'horloge ; la passe B marquait tout résultat obtenu après une reconnexion. La v2 ne disait pas si « la synchronisation » est un mécanisme invisible en soi. Les passes v3 vont dans `data/passes/strict-v3/` : on ne les compare pas aux v1 ni aux v2 (règle 4 du labo).

À donner **telle quelle** à un agent isolé (sous-agent neuf, sans le contexte du banc).
Remplacer seulement `{DESCRIPTION}` et `{FICHIER}`.

Ne jamais ajouter : la prédiction, les thèses, les mots « densité », « spin », « k », « Ising », ni une autre passe.
C'est cet aveuglement qui rend la mesure fiable (thèse H13).

---

Tu rédiges une spécification par assertions strictement atomiques pour une petite application. Ne cherche pas à deviner un objectif caché : fais simplement une spécification honnête et complète. N'utilise aucun outil sauf l'écriture du fichier final.

Application : {DESCRIPTION}

RÈGLES D'ÉTAT
- Un état = une donnée ou une règle que l'on peut faire varier indépendamment des autres (un ou deux mots).
- Pas de synonymes : un seul nom par notion.
- Pas d'état « technique » non observable par l'utilisateur, sauf s'il change un résultat visible.

RÈGLES D'ATOMICITÉ (obligatoires)
1. Une assertion = une situation de départ, au plus UNE action, et UN seul résultat observé.
2. Le résultat porte sur UN SEUL état (l'état observé). Si tu es tenté d'écrire « et » dans le résultat, fais deux assertions.
3. Les conditions = uniquement les états dont la valeur change le résultat. N'ajoute pas un état juste parce qu'il est présent dans le contexte.
4. Pas d'assertion qui agrège (« tout est restauré », « tout est conservé ») : une assertion par état.
5. Un état ne doit pas résumer un mécanisme invisible. Une assertion est « frontière » si et seulement si son résultat dépend d'au moins un de ces six mécanismes, que l'utilisateur ne voit pas :
   a. une transmission entre appareils ou entre utilisateurs (envoi, réception, synchronisation, fusion de modifications) ;
   b. un chiffrement, une signature ou une vérification de clé ;
   c. la conservation des données après la fermeture de l'application ;
   d. deux actions qui ont lieu au même moment ;
   e. l'écoulement réel du temps, une horloge, une date ou un fuseau horaire ;
   f. un calcul fait par un service extérieur à l'application.
   Test : si l'assertion reste vraie dans une version de l'application où tout se passe dans une seule mémoire, sur un seul appareil, pour un seul utilisateur, une action après l'autre, sans fermeture et sans que le temps passe, elle n'est pas frontière. Le simple fait de mentionner la connexion, un appareil ou une date ne suffit pas : c'est le résultat qui doit en dépendre.
   Écris quand même l'assertion, et pour une assertion frontière ajoute à la fin : | frontière: oui

Écris entre 20 et 40 assertions, en français, dans ce format exact :

ÉTATS: etat1; etat2; etat3
ASSERTIONS:
- texte de l'assertion | observé: etat1 | conditions: etat2, etat3
- texte de l'assertion | observé: etat2 | conditions: aucune

Enregistre ce texte, et rien d'autre, dans le fichier {FICHIER}. Réponds ensuite seulement « ok ».
