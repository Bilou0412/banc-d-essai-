"""Référence B de H23 : un faux serveur llama.cpp qui fait répondre sonnet à la place de NuExtract.

Le pipeline de Bilel (adaptateurs/bilel) ne change pas : mêmes tranches de texte, même gabarit,
même vérification dans la page. Seul le modèle qui propose les valeurs change.
Chaque appel est noté dans runs-v5/budget.jsonl (étape « h23/sonnet »).

    python outils/v5/shim_sonnet.py 8090 &
    EXTRACTOR_URL=http://127.0.0.1:8090 green-bilel < rc.json
"""
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
BUDGET = RACINE / "runs-v5" / "budget.jsonl"
VERROU = threading.Lock()
SYSTEME = ("Tu es un extracteur d'information. Tu rends uniquement un objet JSON qui suit exactement le gabarit donné, "
           "sans texte autour.")
CONSIGNE = """Remplis ce gabarit JSON à partir du texte ci-dessous (un extrait d'un règlement de la consultation).

Gabarit :
{template}

Règles du gabarit :
- "verbatim-string" : recopie exactement les mots du texte, sans reformuler.
- "date-time" : écris la date (et l'heure si le texte la donne) au format ISO, par exemple 2026-09-15T12:00 ou 2026-09-15.
- une liste de choix : une seule des valeurs proposées.
- "boolean", "integer", "number" : la valeur.
- Ce que le texte ne dit pas : null (ou une liste vide).

Texte :
{texte}
"""


def noter(usd, s):
    with VERROU:
        BUDGET.parent.mkdir(exist_ok=True)
        with BUDGET.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"etape": "h23/sonnet", "usd": usd, "secondes": s}) + "\n")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        texte = corps["messages"][0]["content"]
        template = corps.get("chat_template_kwargs", {}).get("template", "")
        p = subprocess.run(["claude", "-p", "--model", "sonnet", "--output-format", "json", "--no-session-persistence",
                            "--system-prompt", SYSTEME, "--tools", ""],
                           input=CONSIGNE.format(template=template, texte=texte), capture_output=True, text=True,
                           timeout=3600, cwd=tempfile.mkdtemp(prefix="h23-"))
        try:
            r = json.loads(p.stdout)
            contenu, usd = r.get("result", ""), r.get("total_cost_usd", 0)
            noter(usd, r.get("duration_ms", 0) / 1000)
        except json.JSONDecodeError:
            contenu = ""
        rep = json.dumps({"choices": [{"message": {"role": "assistant", "content": contenu}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rep)))
        self.end_headers()
        self.wfile.write(rep)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
