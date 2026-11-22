#!/bin/bash
# Déroule les itérations de la boucle V5 jusqu'à l'arrêt : taux spec ≥ 0,9, pas de hausse deux fois de suite,
# budget (boucle_v5.py refuse l'étape), ou itération 5 faite.
cd "$(dirname "$0")/../.."
for i in $(seq ${1:-1} 5); do
  python3 outils/v5/boucle_v5.py iteration --it $i || { echo "ARRÊT : étape refusée ou en échec à it$i"; exit 1; }
  python3 - "$i" <<'PY' || exit 0
import json, sys
i = int(sys.argv[1])
t = [json.load(open(f"runs-v5/boucle/it{k}/accord.json"))["taux_spec"] for k in range(i + 1)]
print("taux spec :", t, flush=True)
if t[-1] >= 0.9:
    print("ARRÊT : taux spec ≥ 0,9"); sys.exit(1)
if len(t) >= 3 and t[-1] <= t[-2] and t[-2] <= t[-3]:
    print("ARRÊT : pas de hausse deux itérations de suite"); sys.exit(1)
PY
done
