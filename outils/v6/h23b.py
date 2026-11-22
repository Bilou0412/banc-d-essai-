"""H23b (V6) : un petit modèle local écrit le code de P02, en module entier ou assertion par assertion.

    python outils/v6/h23b.py module    [--tours 12]           # condition 1
    python outils/v6/h23b.py assertion [--max 78]             # condition 2
    python outils/v6/h23b.py bilan                            # courbes → runs-v6/h23b/bilan.json

Le modèle tourne dans llama.cpp (llama-server, http://127.0.0.1:8081, température 0). Montage figé
dans data/predictions/V6.md :
- condition 1 : à chaque tour, la spec entière, tous les tests, le code courant et les échecs ;
  le modèle réécrit app.py en entier ;
- condition 2 : à chaque tour, UNE assertion, ses voisines (états partagés), l'en-tête des tests
  (interface et fixtures), les tests qui citent l'assertion et le code courant ; le modèle rend
  seulement les fonctions à ajouter ou changer, fusionnées par l'arbre syntaxique ;
- garde commune : un code n'est gardé que s'il ne fait pas baisser le nombre de tests passés ;
- après chaque tour : tests passés (sur 104) et taux de compilation contre S1 et S2 (V4), 300 situations.
Tout est rangé dans runs-v6/h23b/<condition>/ : tour<NN>/ (prompt, réponse, app.py essayé), app.py gardé,
journal.jsonl (une ligne par tour).
"""
import argparse
import ast
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "outils"))
from differentiel import rejouer, spec_de  # noqa: E402
from duel import REEL, TECH, executer, formater  # noqa: E402

URL = "http://127.0.0.1:8081/v1/chat/completions"
P02 = RACINE / "runs-v4" / "P02"
TESTS = sorted((RACINE / "runs-v2" / "P02").glob("test_app*.py"))
SORTIE = RACINE / "runs-v6" / "h23b"
N = 300

SYSTEME = "Tu es un développeur Python précis. Tu réponds par un seul bloc de code ```python, sans explication."

MODULE = """Tu écris le module Python `app.py` pour que les tests ci-dessous passent.
Les tests sont en lecture seule.

{tech}
{reel}
Règles de la spec (chaque test cite l'une d'elles dans son nom) :
{assertions}

Les tests :
{tests}

{code}
{resultats}
Écris le fichier `app.py` complet, dans un seul bloc ```python."""

UNE = """Tu complètes le module Python `app.py`, une règle à la fois.

{tech}
{reel}
L'interface et les fixtures (en-tête des tests) :
```python
{entete}
```

La règle à réaliser maintenant :
{assertion}

Ses voisines (elles partagent un état avec elle ; le code doit rester compatible) :
{voisines}

Les tests qui vérifient cette règle :
```python
{tests}
```

Le code actuel de app.py :
```python
{code}
```
{resultats}
Rends SEULEMENT ce qu'il faut ajouter ou changer pour cette règle : les imports, les constantes, les classes
ou les méthodes concernées (une méthode se rend dans sa classe : `class App:` puis la méthode).
Ce que tu rends remplace l'élément de même nom ; le reste du code est gardé tel quel. Un seul bloc ```python."""


# ------------------------------------------------------------------ modèle local

def llm(texte, max_tokens):
    corps = json.dumps({"messages": [{"role": "system", "content": SYSTEME}, {"role": "user", "content": texte}],
                        "temperature": 0, "max_tokens": max_tokens, "cache_prompt": True}).encode()
    req = urllib.request.Request(URL, corps, {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=7200) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"], d.get("timings", {}), d.get("usage", {})


def bloc(reponse):
    m = re.findall(r"```(?:python|py)?\s*\n(.*?)```", reponse, re.S)
    if m:
        return max(m, key=len)
    m = re.search(r"```(?:python|py)?\s*\n(.*)$", reponse, re.S)  # bloc coupé par max_tokens
    return m.group(1) if m else reponse


# ------------------------------------------------------------------ mesures

def tests_passes(code):
    d = Path(tempfile.mkdtemp(prefix="h23b-t-"))
    (d / "tests").mkdir()
    for f in TESTS:
        shutil.copy(f, d / "tests" / f.name)
    (d / "app.py").write_text(code, encoding="utf-8")
    res = executer(d)
    shutil.rmtree(d, ignore_errors=True)
    return res


_REF = {}


def taux(code):
    """Taux de compilation du code contre S1 et S2 (mêmes règles que differentiel.comparer)."""
    d = Path(tempfile.mkdtemp(prefix="h23b-r-"))
    app = d / "app.py"
    app.write_text(code, encoding="utf-8")
    gen = P02 / "generateur.py"
    for nom in ("S1", "S2"):
        if nom not in _REF:
            _REF[nom] = (rejouer(gen, P02 / "greens" / nom / "app.py", N)[0], rejouer(gen, P02 / "greens" / nom / "app.py", N)[0])
    try:
        t1, t2 = rejouer(gen, app, N)[0], rejouer(gen, app, N)[0]
    except Exception:  # délai dépassé : le code ne rejoue pas
        t1, t2 = {}, {}
    out = {}
    for nom in ("S1", "S2"):
        r1, r2 = _REF[nom]
        jouees = conc = 0
        for g in range(N):
            if g not in r1 or not isinstance(r1[g], list) or r1[g] != r2.get(g):
                continue
            if g in t1 and t1[g] != t2.get(g):
                continue  # non déterministe
            jouees += 1
            conc += t1.get(g) == r1[g]
        out[nom] = round(conc / jouees, 3) if jouees else 0.0
    shutil.rmtree(d, ignore_errors=True)
    out["moyenne"] = round((out["S1"] + out["S2"]) / 2, 3)
    return out


# ------------------------------------------------------------------ fusion par l'arbre syntaxique

def _nom(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return n.name
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
        return n.targets[0].id
    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
        return n.target.id
    return None


def _fusion_corps(ancien, nouveau, classe=False):
    """Remplace les éléments de même nom, ajoute les nouveaux, garde le reste."""
    out = list(ancien)
    for n in nouveau:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            if ast.dump(n) not in {ast.dump(x) for x in out}:
                pos = max([i + 1 for i, x in enumerate(out) if isinstance(x, (ast.Import, ast.ImportFrom))], default=0)
                out.insert(pos, n)
            continue
        if isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant):
            continue  # docstring rendue seule
        nom = _nom(n)
        i = next((i for i, x in enumerate(out) if nom and _nom(x) == nom), None)
        if i is None:
            out.append(n)
        elif isinstance(n, ast.ClassDef) and isinstance(out[i], ast.ClassDef) and not classe:
            vieux = out[i]
            vieux.body = _fusion_corps(vieux.body, n.body, classe=True)
            if n.bases:
                vieux.bases = n.bases
        else:
            out[i] = n
    return out


def fusionner(code, patch):
    a = ast.parse(code) if code.strip() else ast.Module(body=[], type_ignores=[])
    b = ast.parse(patch)
    a.body = _fusion_corps(a.body, b.body)
    return ast.unparse(ast.fix_missing_locations(a)) + "\n"


# ------------------------------------------------------------------ graphe des assertions et tests

def etats(texte):
    s = set()
    for cle in ("observé", "conditions"):
        m = re.search(cle + r":\s*([^|]+)", texte)
        if m:
            s |= {x.strip() for x in m.group(1).split(",") if x.strip() and x.strip() != "aucune"}
    return s


def voisines(spec, i):
    e = etats(spec[i])
    return {j: t for j, t in spec.items() if j != i and etats(t) & e}


def entete_et_tests():
    """En-tête (tout ce qui précède le premier test) de test_app.py, et source de chaque test par assertion."""
    entete, par = None, {}
    for f in TESTS:
        src = f.read_text(encoding="utf-8")
        arbre = ast.parse(src)
        lignes = src.splitlines()
        tests = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        if entete is None:
            entete = "\n".join(lignes[:min((n.decorator_list[0].lineno if n.decorator_list else n.lineno) for n in tests) - 1])
        # fixtures propres au second fichier : ajoutées à l'en-tête
        else:
            fx = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("test_")]
            entete += "\n\n# --- " + f.name + "\n" + "\n\n".join(
                "\n".join(lignes[(n.decorator_list[0].lineno if n.decorator_list else n.lineno) - 1:n.end_lineno]) for n in fx)
        for n in tests:
            m = re.match(r"test_(A\d+)", n.name)
            if m:
                debut = n.decorator_list[0].lineno if n.decorator_list else n.lineno
                par.setdefault(m.group(1), []).append("\n".join(lignes[debut - 1:n.end_lineno]))
    return entete, par


# ------------------------------------------------------------------ boucle

def echecs(res, filtre=None, n=40):
    l = [f"- {k} : {m}" for k, (v, m) in sorted(res.items()) if not v and (filtre is None or k.startswith(f"test_{filtre}_"))]
    return "\n".join(l[:n]) + (f"\n- … et {len(l) - n} autres" if len(l) > n else "")


def tour_commun(dossier, num, texte, max_tokens, construire, code, res, journal, extra):
    t0 = time.time()
    td = dossier / f"tour{num:02d}"
    td.mkdir(parents=True, exist_ok=True)
    (td / "prompt.txt").write_text(texte, encoding="utf-8")
    try:
        rep, timings, usage = llm(texte, max_tokens)
    except Exception as e:  # noqa: BLE001
        rep, timings, usage = f"ERREUR {e}", {}, {}
    (td / "reponse.txt").write_text(rep, encoding="utf-8")
    t_llm = time.time() - t0
    try:
        essai = construire(code, bloc(rep))
        compile(essai, "app.py", "exec")
        erreur = None
    except Exception as e:  # noqa: BLE001
        essai, erreur = None, f"{type(e).__name__}: {e}"[:300]
    ok_avant = sum(v for v, _ in res.values()) if res else 0
    if essai is not None:
        (td / "app.py").write_text(essai, encoding="utf-8")
        res_essai = tests_passes(essai)
        ok_essai = sum(v for v, _ in res_essai.values())
    else:
        res_essai, ok_essai = {}, -1
    garde = essai is not None and (not res or ok_essai >= ok_avant)
    if garde:
        code, res = essai, res_essai
    rejet = None if garde else (erreur or f"ton dernier essai faisait passer {ok_essai} tests contre {ok_avant} : il n'a pas été gardé")
    tx = taux(code)
    ligne = {"tour": num, **extra, "garde": garde, "rejet": rejet, "essai_passe": ok_essai,
             "passe": sum(v for v, _ in res.values()), "total": len(res) or 104, "taux": tx,
             "secondes_modele": round(t_llm), "secondes": round(time.time() - t0),
             "jetons_prompt": usage.get("prompt_tokens"), "jetons_sortie": usage.get("completion_tokens"),
             "jetons_caches": timings.get("cache_n")}
    journal.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    journal.flush()
    (dossier / "app.py").write_text(code, encoding="utf-8")
    print(json.dumps(ligne, ensure_ascii=False), flush=True)
    return code, res, rejet


def module(a):
    dossier = SORTIE / "module"
    dossier.mkdir(parents=True, exist_ok=True)
    spec = spec_de("P02")
    tests = "\n\n".join(f"# --- {f.name}\n```python\n{f.read_text(encoding='utf-8')}\n```" for f in TESTS)
    code, res, rejet = "", {}, None
    with open(dossier / "journal.jsonl", "a", encoding="utf-8") as journal:
        for num in range(1, a.tours + 1):
            texte = MODULE.format(
                tech=TECH, reel=REEL["P02"], assertions=formater(spec), tests=tests,
                code=f"Le app.py actuel :\n```python\n{code}\n```" if code else "Premier tour : app.py n'existe pas encore.",
                resultats=(("Échecs du app.py actuel :\n" + echecs(res)) if res else "")
                + (f"\nNote : {rejet}." if rejet else ""))
            code, res, rejet = tour_commun(dossier, num, texte, 7000, lambda c, b: b, code, res, journal, {})
            if res and all(v for v, _ in res.values()):
                break


def assertion(a):
    dossier = SORTIE / "assertion"
    dossier.mkdir(parents=True, exist_ok=True)
    spec = spec_de("P02")
    entete, par = entete_et_tests()
    ordre = list(spec)
    code, res, rejet, num = "", {}, None, 0
    with open(dossier / "journal.jsonl", "a", encoding="utf-8") as journal:
        for passage in (1, 2):
            for i in ordre:
                if num >= a.max:
                    return
                if passage == 2 and res and not echecs(res, i):
                    continue
                vois = voisines(spec, i)
                num += 1
                texte = UNE.format(
                    tech=TECH, reel=REEL["P02"], entete=entete, assertion=f"{i} : {spec[i]}",
                    voisines="\n".join(f"{j} : {t}" for j, t in vois.items()) or "(aucune)",
                    tests="\n\n".join(par.get(i, [])) or "# aucun test ne cite cette règle",
                    code=code or "# vide",
                    resultats=(("Échecs actuels des tests de cette règle :\n" + (echecs(res, i) or "(aucun)")) if res else "")
                    + (f"\nNote : {rejet}." if rejet else ""))
                code, res, rejet = tour_commun(dossier, num, texte, 2500, fusionner, code, res, journal,
                                               {"passage": passage, "assertion": i, "voisines": len(vois)})
                if res and all(v for v, _ in res.values()):
                    return


def bilan(_):
    out = {}
    for c in ("module", "assertion"):
        f = SORTIE / c / "journal.jsonl"
        if f.exists():
            l = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            out[c] = {"tours": len(l), "secondes": sum(x["secondes"] for x in l),
                      "courbe": [(x["tour"], x["passe"], x["total"], x["taux"]["moyenne"]) for x in l],
                      "final": l[-1] if l else None}
    (SORTIE / "bilan.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({c: {k: v for k, v in d.items() if k != "courbe"} for c, d in out.items()}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    m = sp.add_parser("module")
    m.add_argument("--tours", type=int, default=12)
    s = sp.add_parser("assertion")
    s.add_argument("--max", type=int, default=78)
    sp.add_parser("bilan")
    a = ap.parse_args()
    {"module": module, "assertion": assertion, "bilan": bilan}[a.cmd](a)
