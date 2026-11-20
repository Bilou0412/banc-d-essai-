#!/bin/bash
# Enchaîne la boucle après le lot B de it0 ; s'arrête à taux >= 0,9, plateau sur 2 itérations, ou erreur.
cd /home/claude/banc-d-essai-
while pgrep -f "boucle.py lot --it 0 --lot B" >/dev/null; do sleep 30; done
echo "ETAPE lot B fini"
python3 outils/boucle.py analyser --it 0 --lot B || { echo "ERREUR analyser B"; exit 1; }
python3 outils/boucle.py apparier --it 0 || echo "ERREUR apparier"
python3 outils/boucle.py ajouter --it 0 || { echo "ERREUR ajouter 0"; exit 1; }
echo "ETAPE it0 finie"
i=1
while [ $i -le 10 ]; do
  python3 outils/boucle.py iteration --it $i || { echo "ERREUR iteration $i"; exit 1; }
  echo "ETAPE it$i finie"
  stop=$(python3 - <<PY
import json,pathlib
b=pathlib.Path('runs-boucle/P11')
t=[]
for k in range(0,$i+1):
    f=b/f'it{k}/lots/A/accord.json'
    t.append(json.loads(f.read_text())['taux_moyen'])
if t[-1]>=0.9: print('SEUIL')
elif len(t)>=3 and t[-1]<=t[-2] and t[-2]<=t[-3]: print('PLATEAU')
else: print('')
PY
)
  [ -n "$stop" ] && { echo "ARRET $stop"; exit 0; }
  i=$((i+1))
done
