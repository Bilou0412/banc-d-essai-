# Consigne du décompositeur aveugle (règle stricte, v2)

v2 = v1 (`decompositeur-strict.md`) + la règle d'atomicité 5 (assertions frontière). Les passes v2 vont dans `data/passes/strict-v2/` : on ne les compare pas aux passes v1 (règle 4 du labo).

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
5. Un état ne doit pas résumer un mécanisme invisible. Si le résultat dépend d'un mécanisme que l'utilisateur ne voit pas, écris quand même l'assertion et ajoute à la fin : | frontière: oui

Écris entre 20 et 40 assertions, en français, dans ce format exact :

ÉTATS: etat1; etat2; etat3
ASSERTIONS:
- texte de l'assertion | observé: etat1 | conditions: etat2, etat3
- texte de l'assertion | observé: etat2 | conditions: aucune

Enregistre ce texte, et rien d'autre, dans le fichier {FICHIER}. Réponds ensuite seulement « ok ».
