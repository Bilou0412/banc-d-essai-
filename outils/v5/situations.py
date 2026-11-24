"""Les 300 situations de V5 : 295 RC synthétiques (graines 0 à 294) puis les 5 RC publics."""
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generateur import generer  # noqa: E402

N_SYNTH = 295
PUBLICS = [f"RC{i}" for i in range(1, 6)]


def ids():
    return [f"S{g:03d}" for g in range(N_SYNTH)] + PUBLICS


def situation(i):
    """{"id", "pages", "verite" (None pour un RC public), "traits"}"""
    if i.startswith("RC"):
        d = json.loads((RACINE / "data" / "v5" / "rc-publics" / f"{i}.json").read_text(encoding="utf-8"))
        return {"id": i, "pages": d["pages"], "verite": None, "traits": ["public"]}
    r = generer(int(i[1:]))
    return {"id": i, "pages": r["pages"], "verite": r["verite"], "traits": r["traits"]}
