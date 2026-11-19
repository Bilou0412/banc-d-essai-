"""Lance une passe aveugle stricte sur une sonde (règle 1 du labo, SPEC 6.2).

Usage :
    python outils/passe_aveugle.py P10 C            # écrit data/passes/strict/P10_C.txt
    python outils/passe_aveugle.py P10 C --model opus
    python outils/passe_aveugle.py P10 A --v2       # consigne v2, écrit data/passes/strict-v2/P10_A.txt

Aveuglement : la consigne est exactement celle de prompts/decompositeur-strict.md
(la partie après « --- »), où seuls {DESCRIPTION} et {FICHIER} sont remplacés.
L'agent est un `claude -p` neuf, lancé dans un dossier temporaire vide (aucun
CLAUDE.md, aucune autre passe), avec le seul outil Write.
Le refus est mécanique : la consigne finale est vérifiée avant l'appel.

Les tokens consommés sont ajoutés à data/passes/journal-passes.jsonl.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CONSIGNE = RACINE / "prompts" / "decompositeur-strict.md"
SONDES = RACINE / "data" / "sondes.md"
JOURNAL = RACINE / "data" / "passes" / "journal-passes.jsonl"
INTERDITS = ("densité", "spin", "ising", " k ", "thèse", "prédiction")


def description(sonde):
    for ligne in SONDES.read_text(encoding="utf-8").splitlines():
        cols = [c.strip() for c in ligne.split("|")]
        if len(cols) > 3 and cols[1] == sonde:
            return cols[3]
    sys.exit(f"sonde inconnue : {sonde}")


def consigne(desc, fichier, modele=CONSIGNE):
    texte = modele.read_text(encoding="utf-8").split("\n---\n", 1)[1].strip() + "\n"
    texte = texte.replace("{DESCRIPTION}", desc).replace("{FICHIER}", fichier)
    bas = f" {texte.lower()} "
    fuite = [m for m in INTERDITS if m in bas]
    if fuite or "{" in texte:
        sys.exit(f"consigne refusée, aveuglement rompu : {fuite}")
    return texte


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sonde")
    ap.add_argument("passe")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--v2", action="store_true", help="consigne v2 (assertions frontière)")
    a = ap.parse_args()
    modele = RACINE / "prompts" / ("decompositeur-strict-v2.md" if a.v2 else "decompositeur-strict.md")
    cible = RACINE / "data" / "passes" / ("strict-v2" if a.v2 else "strict") / f"{a.sonde}_{a.passe}.txt"
    cible.parent.mkdir(exist_ok=True)
    if cible.exists():
        sys.exit(f"{cible} existe déjà")
    vide = Path(tempfile.mkdtemp(prefix="passe-"))
    nom = f"{a.sonde}_{a.passe}.txt"
    texte = consigne(description(a.sonde), nom, modele)
    p = subprocess.run(["claude", "-p", "--model", a.model, "--output-format", "json",
                        "--no-session-persistence", "--allowedTools", "Write"],
                       input=texte, cwd=vide, capture_output=True, text=True, timeout=1800)
    rapport = json.loads(p.stdout)
    rendu = vide / nom
    if not rendu.exists():
        sys.exit(f"pas de fichier rendu : {rapport.get('result', '')[:300]}")
    shutil.copy(rendu, cible)
    tokens = {m: u["inputTokens"] + u["outputTokens"] + u["cacheCreationInputTokens"]
              for m, u in rapport.get("modelUsage", {}).items()}
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"passe": nom, "consigne": modele.name, "modele": a.model, "tokens": tokens,
                            "usd": rapport.get("total_cost_usd")}, ensure_ascii=False) + "\n")
    print(f"{cible.relative_to(RACINE)} écrit ({tokens})")


if __name__ == "__main__":
    main()
