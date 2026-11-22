"""H23 : passe le pipeline de Bilel (adaptateurs/bilel) sur les situations, avec un modèle donné.

    python outils/v5/h23_passer.py nuextract http://127.0.0.1:8080 [--ordre publics-d-abord] [--max N]
    python outils/v5/h23_passer.py sonnet    http://127.0.0.1:8090 --ids S000 S001 ...

Écrit runs-v5/h23/<modele>/<id>.json (le Facts de BuildForge + « secondes »). Une sortie existante est gardée.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from situations import RACINE, ids, situation  # noqa: E402

BIN = Path(os.environ.get("GREEN_BILEL", "/home/user/v5work/target/release/green-bilel"))

ap = argparse.ArgumentParser()
ap.add_argument("modele")
ap.add_argument("url")
ap.add_argument("--ids", nargs="*")
ap.add_argument("--max", type=int, default=None)
a = ap.parse_args()
sortie = RACINE / "runs-v5" / "h23" / a.modele
sortie.mkdir(parents=True, exist_ok=True)
liste = a.ids or ([i for i in ids() if i.startswith("RC")] + [i for i in ids() if i.startswith("S")])
if a.max:
    liste = liste[:a.max]
for i in liste:
    f = sortie / f"{i}.json"
    if f.exists():
        continue
    s = situation(i)
    p = subprocess.run([str(BIN)], input=json.dumps({"pages": s["pages"]}), capture_output=True, text=True,
                       env={**os.environ, "EXTRACTOR_URL": a.url, "DELAI_S": "3600"}, timeout=4 * 3600)
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        d = {"erreur": "sortie illisible", "stderr": p.stderr[-500:]}
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    print(i, d.get("secondes"), d.get("erreur", ""), flush=True)
