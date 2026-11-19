"""Test différentiel : le taux de compilation d'une spec (cap du banc, H20).

Deux greens indépendants (modèles différents) construisent chacun un code depuis la même spec
et les mêmes tests rouges, jusqu'à ce que tout passe. Un générateur de situations, écrit par un
red qui ne voit aucun code, tire au hasard des suites d'actions valides. Les deux codes jouent
les mêmes situations (même graine) ; on compare leurs résultats observables étape par étape.

    taux de compilation = situations où les deux codes donnent partout le même résultat
                          ÷ situations jouées (hors situations non déterministes)

Chaque divergence est un trou candidat. Les divergences sont regroupées par action où elles
apparaissent ; un JUGE froid classe un représentant de chaque groupe : trou de spec, bug de X,
bug de Y, ou situation invalide (le générateur a fait une action hors spec).

Usage :
    python outils/differentiel.py generer  P02 --tests runs-v2/P02          # le red écrit generateur.py
    python outils/differentiel.py green    P02 --tests runs-v2/P02 --model sonnet --nom S1
    python outils/differentiel.py comparer P02 --a H1 --b S1 [--n 300]
    python outils/differentiel.py apparier P02 --paires H1-S1 H2-S2       # H20 : les deux paires voient-elles les mêmes trous ?

Tout est rangé dans runs-v4/<sonde>/ : generateur.py, greens/<nom>/app.py, paires/<a>-<b>/.
Un green déjà construit ailleurs peut être déposé dans greens/<nom>/app.py (avec un bilan.json).
Aveuglement : les agents travaillent dans un dossier temporaire hors du dépôt, comme dans duel.py.
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
sys.path.insert(0, str(RACINE / "outils"))
from duel import GREEN, REEL, REEL_DEFAUT, TECH, ZERO, additionner, appel, executer, formater, lignes_assertions  # noqa: E402

SORTIE = RACINE / "runs-v4"

GENERATEUR = """Couche : code. Tu écris un générateur de situations, pas des tests.

{tech}
{reel}
Spécification (assertions) :
{assertions}

L'interface publique de `app` est celle que fixent ces tests (tu les as écrits ; tu ne vois aucun code) :
```python
{tests}
```

Écris `{dossier}/generateur.py`, qui définit exactement :

    def scenario(app, rng, dossier):
        '''Joue une situation tirée au hasard. `app` est le module à tester, `rng` un random.Random
        déjà semé, `dossier` un dossier vide (pour ce qui doit être conservé sur disque).
        Rend une liste de paires (action, observation).'''

Règles :
- Entre 15 et 40 actions par situation, toutes choisies avec `rng` (jamais `random` directement,
  jamais l'heure réelle) : la même graine doit rejouer exactement la même situation.
- Des actions valides surtout, mais aussi les cas limites et les refus que la spec décrit.
- `action` : une chaîne courte et lisible, nom de l'action puis arguments, par ex. "save_recipe('Tarte', 6)".
- `observation` : après chaque action, ce que l'utilisateur VOIT, sous forme JSON (listes, dicts,
  chaînes, nombres, booléens). Jamais d'identifiant opaque, d'adresse mémoire, d'octets bruts
  (pour des octets, observe leur longueur ou un booléen), ni d'ordre qui n'a pas de sens pour
  l'utilisateur (trie alors ce que tu observes). Pour désigner un objet créé, garde ta propre
  table « mon nom → identifiant rendu par app ».
- Une action qui lève une exception : observation = "refusé" (n'observe pas le type ni le message).
  Le générateur lui-même ne doit jamais lever d'exception.
- N'importe que la bibliothèque standard.

Réponds ensuite seulement « ok ».
"""

JUGE_DIV = """Deux implémentations, X et Y, de la même spécification, ont joué la même situation.
Elles passent toutes les deux tous les tests de la spec. Elles divergent à une étape.

Spécification (assertions) :
{assertions}

Situation (actions et observations communes jusqu'à la divergence) :
{prefixe}

Étape où elles divergent :
  action : {action}
  X observe : {x}
  Y observe : {y}

Classe cette divergence. Un seul choix :
- trou : la spec ne tranche pas ce cas ; les deux comportements la respectent.
- bug X : la spec tranche, et X la viole (Y a raison).
- bug Y : la spec tranche, et Y la viole (X a raison).
- invalide : la situation fait une action que la spec ne permet pas, ou l'observation n'a pas de sens pour l'utilisateur.

Rends ton verdict au format de ton rôle, puis termine par exactement trois lignes :
CLASSE: trou | bug X | bug Y | invalide
ASSERTION: <identifiant de l'assertion concernée, ou « aucune »>
CAS: <le cas en une phrase, sans parler de X ni de Y>
N'écris aucun fichier.
"""

APPARIER = """Deux listes de trous de spec, trouvés indépendamment sur la même spécification.
Pour chaque trou de la liste 1, dis s'il désigne le même cas qu'un trou de la liste 2.

Liste 1 :
{l1}

Liste 2 :
{l2}

Réponds uniquement par des lignes au format `1.<n> = 2.<m>` pour chaque paire qui désigne le même
cas (un trou peut n'avoir aucun pendant), puis une dernière ligne `FIN`. N'écris aucun fichier.
"""

REJOUER = r'''
import importlib.util, json, random, sys, tempfile, traceback
gen_path, app_path, n, debut = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec); sys.modules[nom] = mod; spec.loader.exec_module(mod); return mod
app = charger("app", app_path)
gen = charger("generateur", gen_path)
for graine in range(debut, debut + n):
    with tempfile.TemporaryDirectory() as d:
        try:
            r = gen.scenario(app, random.Random(graine), d)
            r = json.loads(json.dumps(r, default=repr))
        except Exception as e:
            r = {"erreur_generateur": f"{type(e).__name__}: {e}"[:300]}
    print(json.dumps({"graine": graine, "trace": r}, ensure_ascii=False), flush=True)
'''


def dossier_sonde(sonde):
    d = SORTIE / sonde
    d.mkdir(parents=True, exist_ok=True)
    return d


def spec_de(sonde, passes="strict-v2"):
    return lignes_assertions(RACINE / "data" / "passes" / passes / f"{sonde}_A.txt")


def tests_de(dossier_tests):
    return sorted(Path(dossier_tests).glob("test_app*.py"))


def generer(a):
    d = dossier_sonde(a.sonde)
    travail = Path(tempfile.mkdtemp(prefix=f"gen-{a.sonde}-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    tests = "\n\n".join(f.read_text(encoding="utf-8") for f in tests_de(a.tests))
    texte = GENERATEUR.format(tech=TECH, reel=REEL.get(a.sonde, REEL_DEFAUT), assertions=formater(spec_de(a.sonde, a.passes)),
                              tests=tests, dossier=travail)
    r, t = appel("red", texte, a.red, "Write", travail)
    if not (travail / "generateur.py").exists():
        sys.exit(f"pas de générateur : {str(r.get('result'))[:400]}")
    shutil.copy(travail / "generateur.py", d / "generateur.py")
    (d / "generateur.json").write_text(json.dumps({"modele": a.red, "tokens": t}, indent=1), encoding="utf-8")
    print(f"générateur écrit ({t})")


def green(a):
    """Un green construit app.py depuis les tests, sans Bash, jusqu'à ce que tout passe."""
    d = dossier_sonde(a.sonde) / "greens" / a.nom
    if d.exists():
        sys.exit(f"{d} existe déjà")
    d.mkdir(parents=True)
    travail = Path(tempfile.mkdtemp(prefix=f"green-{a.sonde}-{a.nom}-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    (travail / "tests").mkdir()
    (travail / "reclamations").mkdir()
    for f in tests_de(a.tests):
        shutil.copy(f, travail / "tests" / f.name)
    assertions = spec_de(a.sonde, a.passes)
    resultats = "Premier tour : aucun résultat encore."
    total = dict(ZERO)
    journal = []
    for tour in range(1, a.max_tours + 1):
        existant = "Un app.py existe déjà (ton essai précédent) : lis-le et corrige-le.\n" if (travail / "app.py").exists() else ""
        r, t = appel("green", GREEN.format(tour=tour, dossier=travail, tech=TECH, reel=REEL.get(a.sonde, REEL_DEFAUT),
                                           existant=existant, assertions=formater(assertions), decisions="",
                                           resultats=resultats), a.model, "Read,Write,Edit", travail)
        total = additionner(total, t)
        res = executer(travail)
        ok = sum(v for v, _ in res.values())
        journal.append({"tour": tour, "passent": ok, "total": len(res), "tokens": t})
        print(f"{a.nom} tour {tour} : {ok}/{len(res)}", flush=True)
        if res and ok == len(res):
            break
        resultats = "Échecs à la fin du tour précédent :\n" + "\n".join(f"- {n} : {m}" for n, (v, m) in sorted(res.items()) if not v)
    if (travail / "app.py").exists():
        shutil.copy(travail / "app.py", d / "app.py")
    tout = bool(res) and ok == len(res)
    (d / "bilan.json").write_text(json.dumps({"modele": a.model, "tours": tour, "tout_passe": tout, "tokens": total,
                                              "journal": journal}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"green": a.nom, "modele": a.model, "tours": tour, "tout_passe": tout, "tokens": total}))


def rejouer(gen, app_py, n):
    p = subprocess.run([sys.executable, "-I", "-c", REJOUER, str(gen), str(app_py), str(n), "0"],
                       capture_output=True, text=True, timeout=1800, cwd=tempfile.mkdtemp())
    traces = {}
    for l in p.stdout.splitlines():
        try:
            o = json.loads(l)
            traces[o["graine"]] = o["trace"]
        except (json.JSONDecodeError, KeyError):
            pass
    return traces, p.stderr[-500:]


def nom_action(action):
    return re.split(r"[(\s]", str(action), maxsplit=1)[0]


def comparer(a):
    base = dossier_sonde(a.sonde)
    gen = base / "generateur.py"
    paire = base / "paires" / f"{a.a}-{a.b}"
    paire.mkdir(parents=True, exist_ok=True)
    traces = {}
    for nom in (a.a, a.b):
        app_py = base / "greens" / nom / "app.py"
        t1, e1 = rejouer(gen, app_py, a.n)
        t2, _ = rejouer(gen, app_py, a.n)  # deux fois : une graine qui ne rejoue pas pareil est écartée
        traces[nom] = (t1, t2, e1)
    jouees, concordantes, non_det, err_gen = 0, 0, [], []
    divergences = []
    for g in range(a.n):
        ta1, ta2, _ = traces[a.a]
        tb1, tb2, _ = traces[a.b]
        if g not in ta1 or g not in tb1:
            err_gen.append(g)
            continue
        if ta1[g] != ta2.get(g) or tb1[g] != tb2.get(g):
            non_det.append(g)
            continue
        if isinstance(ta1[g], dict) or isinstance(tb1[g], dict):
            err_gen.append(g)
            continue
        jouees += 1
        x, y = ta1[g], tb1[g]
        if x == y:
            concordantes += 1
            continue
        i = next((i for i, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))
        px = x[i] if i < len(x) else ["(fin)", None]
        py = y[i] if i < len(y) else ["(fin)", None]
        divergences.append({"graine": g, "etape": i, "action": px[0], "groupe": nom_action(px[0]),
                            "x": px[1], "y": py[1], "prefixe": x[:i]})
    groupes = {}
    for dv in divergences:
        groupes.setdefault(dv["groupe"], []).append(dv)
    # le juge classe un représentant par groupe : la divergence la plus courte (préfixe le plus court)
    assertions = spec_de(a.sonde, a.passes)
    verdicts = []
    t_juge = dict(ZERO)
    travail = Path(tempfile.mkdtemp(prefix="juge-div-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    for nom, dvs in sorted(groupes.items(), key=lambda kv: -len(kv[1]))[: a.max_juge]:
        rep = min(dvs, key=lambda d: d["etape"])
        prefixe = "\n".join(f"  {act}  →  {json.dumps(obs, ensure_ascii=False)[:300]}" for act, obs in rep["prefixe"][-25:]) or "  (aucune)"
        texte = JUGE_DIV.format(assertions=formater(assertions), prefixe=prefixe, action=rep["action"],
                                x=json.dumps(rep["x"], ensure_ascii=False)[:800], y=json.dumps(rep["y"], ensure_ascii=False)[:800])
        r, t = appel("judge", texte, a.juge, "Write", travail, delai=900)
        t_juge = additionner(t_juge, t)
        txt = str(r.get("result", ""))
        cl = re.search(r"CLASSE:\s*(trou|bug X|bug Y|invalide)", txt)
        cl = cl.group(1) if cl else "non classé"
        cl = {"bug X": f"bug {a.a}", "bug Y": f"bug {a.b}"}.get(cl, cl)
        ass = re.search(r"ASSERTION:\s*(.+)", txt)
        cas = re.search(r"CAS:\s*(.+)", txt)
        verdicts.append({"groupe": nom, "divergences": len(dvs), "graine": rep["graine"], "etape": rep["etape"],
                         "action": rep["action"], "x": rep["x"], "y": rep["y"], "classe": cl,
                         "assertion": ass.group(1).strip() if ass else "", "cas": cas.group(1).strip() if cas else "",
                         "verdict": txt[-1500:]})
        print(f"  {nom} ({len(dvs)}) → {cl}", flush=True)
    taux = round(concordantes / jouees, 3) if jouees else None
    bilan = {"sonde": a.sonde, "a": a.a, "b": a.b, "situations": a.n, "jouees": jouees, "concordantes": concordantes,
             "taux_compilation": taux, "non_deterministes": len(non_det), "erreurs_generateur": len(err_gen),
             "divergences": len(divergences), "groupes": len(groupes), "juges": len(verdicts),
             "classes": {c: sum(1 for v in verdicts if v["classe"] == c) for c in sorted({v["classe"] for v in verdicts})},
             "tokens_juge": t_juge, "stderr": {n: traces[n][2] for n in traces}}
    (paire / "divergences.json").write_text(json.dumps(divergences, ensure_ascii=False, indent=1)[:5_000_000], encoding="utf-8")
    (paire / "verdicts.json").write_text(json.dumps(verdicts, ensure_ascii=False, indent=1), encoding="utf-8")
    (paire / "bilan.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in bilan.items() if k != "stderr"}, ensure_ascii=False))


def apparier(a):
    base = dossier_sonde(a.sonde)
    listes = []
    for p in a.paires:
        v = json.loads((base / "paires" / p / "verdicts.json").read_text(encoding="utf-8"))
        listes.append([x for x in v if x["classe"] == "trou"])
    l1 = "\n".join(f"1.{i + 1} {x['cas']} (action {x['groupe']}, {x['assertion']})" for i, x in enumerate(listes[0])) or "(vide)"
    l2 = "\n".join(f"2.{i + 1} {x['cas']} (action {x['groupe']}, {x['assertion']})" for i, x in enumerate(listes[1])) or "(vide)"
    travail = Path(tempfile.mkdtemp(prefix="apparier-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    r, t = appel("judge", APPARIER.format(l1=l1, l2=l2), a.juge, "Write", travail, delai=900)
    paires = re.findall(r"1\.(\d+)\s*=\s*2\.(\d+)", str(r.get("result", "")))
    communs = len({i for i, _ in paires})
    union = len(listes[0]) + len(listes[1]) - communs
    res = {"paires": a.paires, "trous": [len(listes[0]), len(listes[1])], "communs": communs,
           "jaccard": round(communs / union, 3) if union else None, "appariement": paires, "l1": l1, "l2": l2, "tokens": t}
    (base / f"apparier-{'_'.join(a.paires)}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commande", choices=["generer", "green", "comparer", "apparier"])
    ap.add_argument("sonde")
    ap.add_argument("--passes", default="strict-v2")
    ap.add_argument("--tests", help="dossier contenant test_app*.py (les tests rouges du duel)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--nom")
    ap.add_argument("--max-tours", type=int, default=10)
    ap.add_argument("--red", default="opus")
    ap.add_argument("--juge", default="opus")
    ap.add_argument("--a")
    ap.add_argument("--b")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--max-juge", type=int, default=12, help="groupes de divergences jugés au plus")
    ap.add_argument("--paires", nargs=2)
    a = ap.parse_args()
    {"generer": generer, "green": green, "comparer": comparer, "apparier": apparier}[a.commande](a)


if __name__ == "__main__":
    main()
