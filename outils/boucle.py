"""La boucle de compilation (H21) : différentiel → trous classés → assertions ajoutées → lot neuf.

Itération i, sur la spec v_i (assertions) et ses tests :
  a. un lot NEUF de 4 greens (H1, H2 haiku ; S1, S2 sonnet) construit app.py jusqu'à ce que tous les tests passent ;
  b. les 4 codes rejouent les 300 mêmes situations (le générateur de V4 ne change jamais) ;
     taux de compilation des 6 paires, accord à 4 ;
  c. à la première étape où les 4 ne sont plus d'accord, la divergence est rangée dans un groupe
     (action sans la personne + champs observés qui diffèrent) ; chaque groupe est jugé par DEUX juges
     indépendants : trou / bug d'une variante / invalide. Désaccord → « à trancher » ;
  d. pour chaque trou (les deux juges d'accord), une assertion stricte qui tranche en faveur de la
     variante majoritaire (sinon la plus simple), écrite avec son test par un red qui ne voit aucun code ;
     un test qui casse sur tous les greens du lot est retiré (noté au journal) ;
  e. v_{i+1} = v_i + ces assertions ; tests_{i+1} = tests_i + leurs tests.
Les bugs ne changent pas la spec : ils sont seulement notés.

Usage :
    python outils/boucle.py init                       # it0 : spec v0, tests du duel, lot A = greens de V4
    python outils/boucle.py lot      --it 0 --lot B    # 4 greens neufs
    python outils/boucle.py analyser --it 0 --lot A    # traces, taux, groupes, double juge
    python outils/boucle.py apparier --it 0            # H20b : union des trous du lot A contre lot B
    python outils/boucle.py ajouter  --it 0            # assertions + tests → it1
    python outils/boucle.py iteration --it 1           # lot A neuf + analyser + ajouter
    python outils/boucle.py bilan                      # tableau de toutes les itérations

Budget : chaque appel est noté dans runs-boucle/P11/budget.jsonl ; une étape dont l'estimation
dépasserait le plafond (120 $, garde-fou) n'est pas lancée.
"""
import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
from duel import GREEN, REEL, TECH, ZERO, additionner, appel, executer, formater, lignes_assertions  # noqa: E402
from differentiel import APPARIER, REJOUER, nom_action  # noqa: E402

SONDE = "P11"
BASE = RACINE / "runs-boucle" / SONDE
GEN = RACINE / "runs-v4" / SONDE / "generateur.py"
PLAFOND = 75.8  # 20/11 : 60,80 $ dépensés + 15 $ accordés par Bilel pour la fin de la boucle
N = 300
GREENS = {"H1": "haiku", "H2": "haiku", "S1": "sonnet", "S2": "sonnet"}
ESTIME = {"haiku": 0.7, "sonnet": 2.2, "juge": 0.13, "red": 1.2}
MAX_GROUPES = 16
VERROU = threading.Lock()

JUGE_N = """Plusieurs implémentations de la même spécification ont joué la même situation.
Elles passent toutes tous les tests de la spec. À une étape, elles ne montrent pas la même chose.

Spécification (assertions) :
{assertions}

Situation (actions et observations communes jusqu'à l'étape où elles divergent, les dernières seulement) :
{prefixe}

Étape où elles divergent :
  action : {action}
{variantes}

Ce qui diffère entre les variantes :
{differences}

Classe ce désaccord. Un seul choix :
- trou : la spec ne tranche pas ce cas ; toutes les variantes la respectent.
- bug V<n> : la spec tranche, et la variante V<n> la viole (les autres ont raison).
- invalide : la situation fait une action que la spec ne permet pas, ou l'observation n'a pas de sens pour l'utilisateur.

Si c'est un trou, écris l'assertion stricte qui le tranche, au format de la spec
(« texte | observé: état | conditions: états »), en faveur de {choix}.

Rends ton verdict au format de ton rôle, puis termine par exactement cinq lignes :
CLASSE: trou | bug V<n> | invalide
ASSERTION: <identifiant de l'assertion la plus proche, ou « aucune »>
CAS: <le cas en une phrase, sans parler des variantes>
CHOIX: <V<n> retenue si trou, sinon « aucun »>
NOUVELLE: <l'assertion stricte si trou, sinon « aucune »>
N'écris aucun fichier.
"""

AJOUTS = """Couche : code. Tu complètes une spécification et ses tests rouges.

{tech}
{reel}
Spécification actuelle (assertions) :
{assertions}

Interface publique de `app` (fixée par les tests existants, tu ne vois aucun code) :
```
{interface}
```

Des implémentations conformes à cette spec se sont contredites sur les cas ci-dessous : la spec ne les
tranchait pas. Pour chacun, une décision a été prise (comportement retenu) et une assertion proposée.

{trous}

Ton travail :
1. Dédoublonne : deux cas qui disent la même chose donnent une seule assertion.
2. Pour chaque cas restant, écris UNE assertion stricte qui tranche, au format exact de la spec
   (« texte | observé: état | conditions: états »), fidèle au comportement retenu. Elle ne doit
   contredire aucune assertion existante ; si c'est impossible, ne l'écris pas et note pourquoi.
3. Numérote-les à partir de {premier} : {exemple}.
4. Écris pour chacune au moins un test pytest qui la vérifie de l'extérieur, nommé `test_<id>_...`
   (par ex. `test_{exemple}_...`), avec l'interface ci-dessus seulement.

Écris exactement deux fichiers, avec l'outil Write :
- {dossier}/ajouts.md : une ligne par assertion, `- <id> : <assertion> | cas: <numéros des cas couverts>`,
  puis, s'il y en a, une ligne `- écarté : <cas> | raison: <pourquoi>`.
- {dossier}/tests/{fichier} (il importe `app` comme les tests existants).
Réponds ensuite seulement « ok ».
"""


# ── budget ────────────────────────────────────────────────────────────────

def depense():
    f = BASE / "budget.jsonl"
    if not f.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in f.read_text(encoding="utf-8").splitlines() if l.strip())


def noter(etape, t):
    with VERROU:
        with (BASE / "budget.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"etape": etape, "usd": t.get("usd", 0), "neufs": t.get("neufs", 0)}, ensure_ascii=False) + "\n")


def garde(estimation, quoi):
    d = depense()
    if d + estimation > PLAFOND:
        sys.exit(f"BUDGET : {quoi} estimé à {estimation:.2f} $, déjà {d:.2f} $ dépensés sur {PLAFOND:.0f} $. Étape non lancée.")
    print(f"budget : {d:.2f} $ dépensés, {quoi} estimé à {estimation:.2f} $", flush=True)


# ── spec et tests d'une itération ─────────────────────────────────────────

def it_dir(i):
    return BASE / f"it{i}"


def spec(i):
    return json.loads((it_dir(i) / "spec.json").read_text(encoding="utf-8"))


def init(a):
    d = it_dir(0)
    if d.exists():
        sys.exit(f"{d} existe déjà")
    (d / "tests").mkdir(parents=True)
    s = lignes_assertions(RACINE / "data" / "passes" / "strict-v2-xl" / f"{SONDE}_A.txt")
    (d / "spec.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in sorted((RACINE / "runs-v4-duel" / SONDE).glob("test_app*.py")):
        shutil.copy(f, d / "tests" / f.name)
    for g in GREENS:
        src = RACINE / "runs-v4" / SONDE / "greens" / g
        dst = d / "lots" / "A" / "greens" / g
        dst.mkdir(parents=True)
        shutil.copy(src / "app.py", dst / "app.py")
        shutil.copy(src / "bilan.json", dst / "bilan.json")
    (BASE / "budget.jsonl").touch()
    print(f"it0 : {len(s)} assertions, {len(list((d / 'tests').glob('*.py')))} fichiers de tests, lot A = greens de V4")


# ── a. un lot de greens ───────────────────────────────────────────────────

def un_green(i, lot, nom, modele, max_tours):
    d = it_dir(i) / "lots" / lot / "greens" / nom
    d.mkdir(parents=True, exist_ok=True)
    travail = Path(tempfile.mkdtemp(prefix=f"boucle-{i}{lot}{nom}-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    shutil.copytree(it_dir(i) / "tests", travail / "tests")
    (travail / "reclamations").mkdir()
    assertions = spec(i)
    resultats, total, journal, res, ok = "Premier tour : aucun résultat encore.", dict(ZERO), [], {}, 0
    for tour in range(1, max_tours + 1):
        existant = "Un app.py existe déjà (ton essai précédent) : lis-le et corrige-le.\n" if (travail / "app.py").exists() else ""
        r, t = appel("green", GREEN.format(tour=tour, dossier=travail, tech=TECH, reel=REEL[SONDE], existant=existant,
                                           assertions=formater(assertions), decisions="", resultats=resultats),
                     modele, "Read,Write,Edit", travail)
        noter(f"it{i}/{lot}/{nom}/tour{tour}", t)
        total = additionner(total, t)
        res = executer(travail)
        ok = sum(v for v, _ in res.values())
        journal.append({"tour": tour, "passent": ok, "total": len(res), "usd": t["usd"]})
        print(f"  it{i} lot {lot} {nom} ({modele}) tour {tour} : {ok}/{len(res)}", flush=True)
        if res and ok == len(res):
            break
        echecs = [f"- {n} : {m}" for n, (v, m) in sorted(res.items()) if not v]
        resultats = "Échecs à la fin du tour précédent :\n" + "\n".join(echecs[:60])
    if (travail / "app.py").exists():
        shutil.copy(travail / "app.py", d / "app.py")
    for f in (travail / "reclamations").glob("*.md"):
        shutil.copy(f, d / f.name)
    tout = bool(res) and ok == len(res)
    (d / "bilan.json").write_text(json.dumps({"modele": modele, "tours": len(journal), "tout_passe": tout,
                                              "passent": ok, "total": len(res), "tokens": total, "journal": journal},
                                             ensure_ascii=False, indent=1), encoding="utf-8")
    return nom, tout, total["usd"]


def lot(a):
    i, l = a.it, a.lot
    if (it_dir(i) / "lots" / l / "greens").exists():
        sys.exit(f"le lot {l} de it{i} existe déjà")
    garde(2 * ESTIME["haiku"] + 2 * ESTIME["sonnet"], f"lot {l} de it{i} (4 greens)")
    with ThreadPoolExecutor(4) as ex:
        fut = [ex.submit(un_green, i, l, n, m, 4 if m == "haiku" else 3) for n, m in GREENS.items()]
        for f in fut:
            print("  fini :", f.result(), flush=True)


# ── b. traces, taux, accord à 4 ───────────────────────────────────────────

def rejouer(app_py):
    p = subprocess.run([sys.executable, "-I", "-c", REJOUER, str(GEN), str(app_py), str(N), "0"],
                       capture_output=True, text=True, timeout=3600, cwd=tempfile.mkdtemp())
    t = {}
    for l in p.stdout.splitlines():
        try:
            o = json.loads(l)
            t[o["graine"]] = o["trace"]
        except (json.JSONDecodeError, KeyError):
            pass
    return t


def traces(i, l):
    """Traces de chaque green (deux passages ; une graine qui ne rejoue pas pareil, ou qui casse le générateur, est écartée)."""
    d = it_dir(i) / "lots" / l
    (d / "traces").mkdir(exist_ok=True)

    def une(nom):
        f = d / "traces" / f"{nom}.json"
        if f.exists():
            return nom, {int(k): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()}
        app_py = d / "greens" / nom / "app.py"
        t1, t2 = rejouer(app_py), rejouer(app_py)
        bonnes = {g: v for g, v in t1.items() if t2.get(g) == v and not isinstance(v, dict)}
        f.write_text(json.dumps(bonnes, ensure_ascii=False), encoding="utf-8")
        return nom, bonnes

    with ThreadPoolExecutor(4) as ex:
        return dict(ex.map(une, GREENS))


def chemins_differents(obs, prefixe="", profondeur=0):
    """Les champs (chemins) où les observations ne sont pas toutes égales. Les cellules sont anonymisées."""
    if all(o == obs[0] for o in obs):
        return []
    if profondeur < 3 and all(isinstance(o, dict) for o in obs):
        out = []
        for k in sorted(set().union(*obs)):
            nom = "*" if re.fullmatch(r"[A-Z]{1,2}\d{1,3}", str(k)) else str(k)
            out += chemins_differents([o.get(k) for o in obs], f"{prefixe}.{nom}" if prefixe else nom, profondeur + 1)
        return out
    return [prefixe or "(tout)"]


def accord(i, l, tr):
    noms = list(GREENS)
    graines = sorted(set.intersection(*(set(t) for t in tr.values())))
    paires = {}
    for x in range(4):
        for y in range(x + 1, 4):
            a, b = noms[x], noms[y]
            paires[f"{a}-{b}"] = round(sum(tr[a][g] == tr[b][g] for g in graines) / len(graines), 3)
    tous, divergences = 0, []
    for g in graines:
        seqs = [tr[n][g] for n in noms]
        if all(s == seqs[0] for s in seqs):
            tous += 1
            continue
        k = 0
        while all(k < len(s) for s in seqs) and all(s[k] == seqs[0][k] for s in seqs):
            k += 1
        obs = [s[k][1] if k < len(s) else "(fin de la situation)" for s in seqs]
        action = next((s[k][0] for s in seqs if k < len(s)), "?")
        base = nom_action(action).split(".")[-1]
        champs = sorted(set(chemins_differents(obs)))
        divergences.append({"graine": g, "etape": k, "action": action, "groupe": f"{base} [{', '.join(champs[:3])}]",
                            "obs": obs, "prefixe": seqs[0][:k]})
    return {"situations": len(graines), "paires": paires, "taux_moyen": round(sum(paires.values()) / 6, 3),
            "accord_4": tous, "accord_4_part": round(tous / len(graines), 3)}, divergences


# ── c. groupes et double juge ─────────────────────────────────────────────

def variantes(obs):
    """Variantes distinctes, de la plus suivie à la moins suivie : [(observation, [greens])]."""
    noms = list(GREENS)
    v = {}
    for n, o in zip(noms, obs):
        v.setdefault(json.dumps(o, ensure_ascii=False, sort_keys=True), []).append(n)
    return sorted(((json.loads(k), g) for k, g in v.items()), key=lambda kv: -len(kv[1]))


def extraire(obs, chemin):
    for p in chemin.split(".") if chemin != "(tout)" else []:
        if isinstance(obs, dict):
            if p == "*":
                return {k: v for k, v in obs.items()}
            obs = obs.get(p)
        else:
            return obs
    return obs


def juger(i, l, groupe, rep):
    vs = variantes(rep["obs"])
    texte_v = "\n".join(f"  V{n + 1} ({len(g)} code{'s' if len(g) > 1 else ''} sur 4) observe : "
                        f"{json.dumps(o, ensure_ascii=False)[:900]}" for n, (o, g) in enumerate(vs))
    champs = re.search(r"\[(.*)\]", groupe).group(1).split(", ")
    diff = []
    for c in champs:
        if c:
            diff.append(f"  {c} : " + " ; ".join(f"V{n + 1} = {json.dumps(extraire(o, c), ensure_ascii=False)[:300]}"
                                                  for n, (o, _) in enumerate(vs)))
    tailles = [len(g) for _, g in vs]
    choix = ("V1, suivie par la majorité des codes" if tailles[0] > (tailles[1] if len(tailles) > 1 else 0)
             else "la variante la plus simple (aucune n'est majoritaire) ; dis laquelle sur la ligne CHOIX")
    prefixe = "\n".join(f"  {act}  →  {json.dumps(o, ensure_ascii=False)[:250]}" for act, o in rep["prefixe"][-20:]) or "  (aucune)"
    texte = JUGE_N.format(assertions=formater(spec(i)), prefixe=prefixe, action=rep["action"], variantes=texte_v,
                          differences="\n".join(diff) or "  (voir les variantes)", choix=choix)
    verdicts = []
    for j in (1, 2):
        travail = Path(tempfile.mkdtemp(prefix="boucle-juge-"))
        shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
        r, t = appel("judge", texte, "opus", "Write", travail, delai=900)
        noter(f"it{i}/{l}/juge{j}/{groupe}", t)
        txt = str(r.get("result", ""))

        def champ(nom):
            m = re.search(rf"^{nom}:\s*(.+)$", txt, re.M)
            return m.group(1).strip() if m else ""
        cl = champ("CLASSE").lower()
        mb = re.search(r"bug\s*v(\d+)", cl)
        cl = "trou" if cl.startswith("trou") else "invalide" if cl.startswith("invalide") else f"bug V{mb.group(1)}" if mb else "non classé"
        verdicts.append({"classe": cl, "assertion": champ("ASSERTION"), "cas": champ("CAS"), "choix": champ("CHOIX"),
                         "nouvelle": champ("NOUVELLE"), "usd": t["usd"], "texte": txt[-1200:]})
    c1, c2 = verdicts[0]["classe"], verdicts[1]["classe"]
    final = c1 if c1 == c2 and c1 != "non classé" else "à trancher"
    if final.startswith("bug V"):
        final = f"bug {'+'.join(vs[int(final[5:]) - 1][1])}" if int(final[5:]) <= len(vs) else "à trancher"
    return {"groupe": groupe, "graine": rep["graine"], "etape": rep["etape"], "action": rep["action"],
            "variantes": [{"greens": g, "obs": o} for o, g in vs], "final": final, "juges": verdicts}


def analyser_lot(i, l):
    d = it_dir(i) / "lots" / l
    tr = traces(i, l)
    res, divs = accord(i, l, tr)
    groupes = {}
    for dv in divs:
        groupes.setdefault(dv["groupe"], []).append(dv)
    ordre = sorted(groupes.items(), key=lambda kv: -len(kv[1]))
    a_juger = ordre[:MAX_GROUPES]
    garde(2 * len(a_juger) * ESTIME["juge"], f"double juge de {len(a_juger)} groupes (it{i}, lot {l})")
    with ThreadPoolExecutor(4) as ex:
        jug = list(ex.map(lambda kv: juger(i, l, kv[0], min(kv[1], key=lambda x: x["etape"])), a_juger))
    for j, (nom, dvs) in zip(jug, a_juger):
        j["divergences"] = len(dvs)
        print(f"  {nom} ({len(dvs)}) → {j['final']}  [{j['juges'][0]['classe']} / {j['juges'][1]['classe']}]", flush=True)
    res.update({"groupes": len(groupes), "juges": len(jug), "non_juges": [f"{n} ({len(v)})" for n, v in ordre[MAX_GROUPES:]],
                "classes": dict(Counter(j["final"] for j in jug)),
                "accord_juges": round(sum(j["juges"][0]["classe"] == j["juges"][1]["classe"] for j in jug) / max(len(jug), 1), 3)})
    (d / "groupes.json").write_text(json.dumps(jug, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "accord.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "non_juges"}, ensure_ascii=False), flush=True)
    return res


def analyser(a):
    analyser_lot(a.it, a.lot)


# ── H20b : union des trous lot A contre lot B ─────────────────────────────

def trous_du_lot(i, l):
    return [g for g in json.loads((it_dir(i) / "lots" / l / "groupes.json").read_text(encoding="utf-8")) if g["final"] == "trou"]


def apparier(a):
    i = a.it
    la, lb = trous_du_lot(i, "A"), trous_du_lot(i, "B")
    l1 = "\n".join(f"1.{n + 1} {g['juges'][0]['cas']} (action {g['groupe']})" for n, g in enumerate(la)) or "(vide)"
    l2 = "\n".join(f"2.{n + 1} {g['juges'][0]['cas']} (action {g['groupe']})" for n, g in enumerate(lb)) or "(vide)"
    garde(ESTIME["juge"], "appariement H20b")
    travail = Path(tempfile.mkdtemp(prefix="boucle-apparier-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    r, t = appel("judge", APPARIER.format(l1=l1, l2=l2), "opus", "Write", travail, delai=900)
    noter(f"it{i}/apparier", t)
    paires = re.findall(r"1\.(\d+)\s*=\s*2\.(\d+)", str(r.get("result", "")))
    # trous distincts de chaque lot : un trou vu par plusieurs groupes compte une fois. On fusionne par composantes.
    parent = {}

    def trouver(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x
    for n in range(len(la)):
        trouver(("A", n + 1))
    for n in range(len(lb)):
        trouver(("B", n + 1))
    for x, y in paires:
        parent[trouver(("A", int(x)))] = trouver(("B", int(y)))
    comp = {}
    for k in list(parent):
        comp.setdefault(trouver(k), set()).add(k[0])
    communs = sum(1 for s in comp.values() if s == {"A", "B"})
    union = len(comp)
    res = {"trous_A": len(la), "trous_B": len(lb), "cas_distincts": union, "communs": communs,
           "seulement_A": sum(1 for s in comp.values() if s == {"A"}), "seulement_B": sum(1 for s in comp.values() if s == {"B"}),
           "jaccard": round(communs / union, 3) if union else None, "appariement": paires, "l1": l1, "l2": l2, "tokens": t}
    (it_dir(i) / "h20b.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("l1", "l2")}, ensure_ascii=False))


# ── d. assertions et tests ajoutés ────────────────────────────────────────

def interface():
    src = (it_dir(0) / "tests" / "test_app.py").read_text(encoding="utf-8")
    m = re.match(r'\s*"""(.*?)"""', src, re.S)
    return m.group(1).strip() if m else src[:4000]


def retirer_tests(fichier, noms):
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    arbre.body = [n for n in arbre.body if not (isinstance(n, ast.FunctionDef) and n.name in noms)]
    fichier.write_text(ast.unparse(arbre) + "\n", encoding="utf-8")


def ajouter(a):
    i = a.it
    suivant = it_dir(i + 1)
    if suivant.exists():
        sys.exit(f"{suivant} existe déjà")
    lots = sorted(p.name for p in (it_dir(i) / "lots").iterdir() if (p / "groupes.json").exists())
    trous, bugs, a_trancher = [], [], []
    for l in lots:
        for g in json.loads((it_dir(i) / "lots" / l / "groupes.json").read_text(encoding="utf-8")):
            g = {**g, "lot": l}
            if g["final"] == "trou":
                trous.append(g)
            elif g["final"].startswith("bug"):
                bugs.append(g)
            elif g["final"] == "à trancher":
                a_trancher.append(g)
    s = spec(i)
    deja = [int(k[1:]) for k in s if k.startswith("C")]
    premier = (max(deja) + 1) if deja else 1
    blocs = []
    for n, g in enumerate(trous, 1):
        j = g["juges"][0]
        choix = j["choix"] or "V1"
        m = re.search(r"V(\d+)", choix)
        v = g["variantes"][int(m.group(1)) - 1] if m and int(m.group(1)) <= len(g["variantes"]) else g["variantes"][0]
        blocs.append(f"Cas {n} (action {g['action']}) : {j['cas']}\n"
                     f"  comportement retenu ({len(v['greens'])} codes sur 4) : {json.dumps(v['obs'], ensure_ascii=False)[:700]}\n"
                     f"  assertion proposée : {j['nouvelle']}\n"
                     f"  assertion existante la plus proche : {j['assertion']}")
    journal = [{"lot": g["lot"], "groupe": g["groupe"], "cas": g["juges"][0]["cas"], "decision": g["juges"][0]["choix"],
                "proposee": g["juges"][0]["nouvelle"]} for g in trous]
    fichier = f"test_app_c{i + 1}.py"
    ajouts, retires, passages = {}, [], {}
    travail = Path(tempfile.mkdtemp(prefix="boucle-ajouts-"))
    if trous:
        garde(ESTIME["red"], f"écriture des assertions et tests de it{i + 1}")
        shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
        (travail / "tests").mkdir()
        texte = AJOUTS.format(tech=TECH, reel=REEL[SONDE], assertions=formater(s), interface=interface(),
                              trous="\n\n".join(blocs), premier=f"C{premier:02d}", exemple=f"C{premier:02d}",
                              dossier=travail, fichier=fichier)
        r, t = appel("red", texte, "opus", "Write", travail)
        noter(f"it{i}/ajouts", t)
        for ligne in (travail / "ajouts.md").read_text(encoding="utf-8").splitlines() if (travail / "ajouts.md").exists() else []:
            m = re.match(r"-\s*(C\d+)\s*:\s*(.+?)(?:\s*\|\s*cas:.*)?$", ligne.strip())
            if m and "observé:" in m.group(2):
                ajouts[m.group(1)] = m.group(2).strip()
    # validation des tests ajoutés : chaque test doit passer sur au moins un green des lots de cette itération
    tf = travail / "tests" / fichier
    if tf.exists():
        for l in lots:
            for g in GREENS:
                app_py = it_dir(i) / "lots" / l / "greens" / g / "app.py"
                if not app_py.exists():
                    continue
                essai = Path(tempfile.mkdtemp(prefix="boucle-valide-"))
                (essai / "tests").mkdir()
                shutil.copy(tf, essai / "tests" / fichier)
                shutil.copy(app_py, essai / "app.py")
                for nom, (ok, _) in executer(essai).items():
                    passages.setdefault(nom, []).append(f"{l}{g}" if ok else None)
        retires = [n for n, v in passages.items() if not any(v)]
        if retires:
            retirer_tests(tf, set(retires))
    (suivant / "tests").mkdir(parents=True)
    for f in (it_dir(i) / "tests").glob("*.py"):
        shutil.copy(f, suivant / "tests" / f.name)
    if tf.exists():
        shutil.copy(tf, suivant / "tests" / fichier)
        shutil.copy(travail / "ajouts.md", it_dir(i) / "ajouts.md")
    nouvelle = {**s, **ajouts}
    (suivant / "spec.json").write_text(json.dumps(nouvelle, ensure_ascii=False, indent=1), encoding="utf-8")
    bilan = {"iteration": i, "trous_juges": len(trous), "assertions_ajoutees": len(ajouts), "bugs": len(bugs),
             "a_trancher": len(a_trancher), "tests_ajoutes": len(passages) - len(retires), "tests_retires": retires,
             "passages": {n: sum(1 for x in v if x) for n, v in passages.items()}, "ajouts": ajouts}
    (it_dir(i) / "decisions.json").write_text(json.dumps({"journal": journal, "bugs": [
        {"lot": g["lot"], "groupe": g["groupe"], "final": g["final"], "cas": g["juges"][0]["cas"]} for g in bugs],
        "a_trancher": [{"lot": g["lot"], "groupe": g["groupe"], "juges": [j["classe"] for j in g["juges"]],
                        "cas": [j["cas"] for j in g["juges"]], "variantes": g["variantes"]} for g in a_trancher],
        "bilan": bilan}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in bilan.items() if k not in ("ajouts", "passages")}, ensure_ascii=False))


ARBITRE = """Couche : code. Tu écris les tests rouges de règles que l'arbitre vient de trancher.

{tech}
{reel}
Spécification complète (assertions) :
{assertions}

Interface publique de `app` (fixée par les tests existants, tu ne vois aucun code) :
```
{interface}
```

Règles à protéger (décisions de l'arbitre, à respecter à la lettre) :
{regles}

Pour chacune, écris au moins un test pytest qui la vérifie de l'extérieur, nommé `test_<id>_...`.
Pour un principe général, écris un test par situation concrète qu'il couvre et que les autres règles
ne testent pas déjà. N'utilise que l'interface ci-dessus.

Écris exactement un fichier, avec l'outil Write : {dossier}/tests/{fichier} (il importe `app` comme les tests existants).
Réponds ensuite seulement « ok ».
"""


def decider(a):
    """Applique les décisions de l'arbitre (it<i>/arbitre.json) à la spec v_i avant que son lot ne tourne."""
    i = a.it
    d = it_dir(i)
    if (d / "lots").exists():
        sys.exit("le lot de cette itération a déjà commencé : décider avant")
    arb = json.loads((d / "arbitre.json").read_text(encoding="utf-8"))
    s = spec(i)
    a_tester = {}
    for k, v in arb["remplace"].items():
        if v["texte"]:
            s[k] = v["texte"]
        if v["tests"] == "réécrire":
            a_tester[k] = s[k]
            for f in (d / "tests").glob("*.py"):
                arbre = ast.parse(f.read_text(encoding="utf-8"))
                noms = {n.name for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name.startswith(f"test_{k}_")}
                if noms:
                    retirer_tests(f, noms)
                    print(f"  {f.name} : {len(noms)} test(s) de {k} retiré(s)")
    for k, v in arb["ajouts"].items():
        s[k] = v["texte"]
        a_tester[k] = v["texte"]
    garde(ESTIME["red"], "tests des décisions de l'arbitre")
    travail = Path(tempfile.mkdtemp(prefix="boucle-arbitre-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    (travail / "tests").mkdir()
    fichier = f"test_app_arbitre{i}.py"
    r, t = appel("red", ARBITRE.format(tech=TECH, reel=REEL[SONDE], assertions=formater(s), interface=interface(),
                                       regles="\n".join(f"{k} : {v}" for k, v in a_tester.items()),
                                       dossier=travail, fichier=fichier), "opus", "Write", travail)
    noter(f"it{i}/arbitre", t)
    tf = travail / "tests" / fichier
    if not tf.exists():
        sys.exit(f"pas de tests écrits : {str(r.get('result'))[:300]}")
    shutil.copy(tf, d / "tests" / fichier)
    (d / "spec.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    # contrôle : sur les greens de l'itération précédente (écrits avant les décisions), qui passe quoi
    passages = {}
    for g in GREENS:
        app_py = it_dir(i - 1) / "lots" / "A" / "greens" / g / "app.py"
        essai = Path(tempfile.mkdtemp(prefix="boucle-valide-"))
        (essai / "tests").mkdir()
        shutil.copy(tf, essai / "tests" / fichier)
        shutil.copy(app_py, essai / "app.py")
        for nom, (ok, msg) in executer(essai).items():
            passages.setdefault(nom, []).append(g if ok else f"{g}✗ {msg[:120]}")
    (d / "arbitre-controle.json").write_text(json.dumps(passages, ensure_ascii=False, indent=1), encoding="utf-8")
    for nom, v in sorted(passages.items()):
        print(f"  {sum('✗' not in x for x in v)}/4  {nom}")
    print(f"spec v{i} : {len(s)} assertions")


BUGS = """Couche : code. Tu écris des tests de non-régression.

{tech}
{reel}
Spécification (assertions) :
{assertions}

Interface publique de `app` (fixée par les tests existants, tu ne vois aucun code) :
```
{interface}
```

Des implémentations qui passaient tous les tests existants se sont trompées sur les cas ci-dessous.
La spec les tranchait déjà (deux juges indépendants l'ont confirmé) : il manquait seulement un test.

{cas}

Pour chaque cas, écris au moins un test pytest qui reproduit la situation par le chemin le plus court
et vérifie le comportement correct exigé par l'assertion citée. Nomme-le `test_<assertion>_reg_...`
(par ex. `test_A89_reg_...`). Deux cas identiques donnent un seul test. N'utilise que l'interface ci-dessus.

Écris exactement un fichier, avec l'outil Write : {dossier}/tests/{fichier} (il importe `app` comme les tests existants).
Réponds ensuite seulement « ok ».
"""


def est_bug(g):
    """Bug retenu : les deux juges disent bug de la même variante, ou un seul le dit et l'autre ne classe pas (pas de désaccord)."""
    c = [j["classe"] for j in g["juges"]]
    if g["final"].startswith("bug"):
        return g["final"][4:].split("+")
    b = [x for x in c if x.startswith("bug V")]
    if len(b) == 1 and "non classé" in c:
        n = int(b[0][5:])
        return g["variantes"][n - 1]["greens"] if n <= len(g["variantes"]) else None
    return None


def bugs_en_tests(cible, iterations):
    """Les bugs jugés aux itérations données deviennent des tests de non-régression de la spec v_cible (la spec ne change pas)."""
    marque = it_dir(cible) / "bugs-tests.json"
    if marque.exists():
        sys.exit(f"{marque} existe déjà")
    blocs, vus = [], set()
    for i in iterations:
        for l in sorted((it_dir(i) / "lots").iterdir()):
            if not (l / "groupes.json").exists():
                continue
            for g in json.loads((l / "groupes.json").read_text(encoding="utf-8")):
                fautifs = est_bug(g)
                if not fautifs:
                    continue
                j = next(x for x in g["juges"] if x["classe"].startswith("bug"))
                cle = (g["groupe"], j["assertion"])
                if cle in vus:
                    continue
                vus.add(cle)
                bons = [v for v in g["variantes"] if not set(fautifs) & set(v["greens"])]
                mauvais = [v for v in g["variantes"] if set(fautifs) & set(v["greens"])]
                blocs.append(f"Cas {len(blocs) + 1} (itération {i}, action {g['action']}, assertion {j['assertion']}) : {j['cas']}\n"
                             f"  comportement correct : {json.dumps(bons[0]['obs'] if bons else None, ensure_ascii=False)[:600]}\n"
                             f"  comportement fautif : {json.dumps(mauvais[0]['obs'] if mauvais else None, ensure_ascii=False)[:600]}")
    garde(ESTIME["red"] * 1.5, f"tests de non-régression ({len(blocs)} bugs)")
    travail = Path(tempfile.mkdtemp(prefix="boucle-bugs-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    (travail / "tests").mkdir()
    fichier = f"test_app_reg{cible}.py"
    r, t = appel("red", BUGS.format(tech=TECH, reel=REEL[SONDE], assertions=formater(spec(cible)), interface=interface(),
                                    cas="\n\n".join(blocs), dossier=travail, fichier=fichier), "opus", "Write", travail)
    noter(f"it{cible}/bugs", t)
    tf = travail / "tests" / fichier
    if not tf.exists():
        sys.exit("pas de tests de non-régression écrits")
    # contrôle sur les greens des itérations d'où viennent les bugs : un test doit passer sur au moins un green
    passages = {}
    for i in iterations:
        for g in GREENS:
            app_py = it_dir(i) / "lots" / "A" / "greens" / g / "app.py"
            essai = Path(tempfile.mkdtemp(prefix="boucle-valide-"))
            (essai / "tests").mkdir()
            shutil.copy(tf, essai / "tests" / fichier)
            shutil.copy(app_py, essai / "app.py")
            for nom, (ok, _) in executer(essai).items():
                passages.setdefault(nom, []).append(f"it{i}{g}" if ok else None)
    retires = [n for n, v in passages.items() if not any(v)]
    if retires:
        retirer_tests(tf, set(retires))
    shutil.copy(tf, it_dir(cible) / "tests" / fichier)
    res = {"iterations": list(iterations), "bugs": len(blocs), "cas": blocs, "retires": retires, "usd": t["usd"],
           "tests": {n: sum(1 for x in v if x) for n, v in passages.items()}}
    marque.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"non-régression → it{cible} : {len(blocs)} bugs, {len(passages) - len(retires)} tests gardés "
          f"(sur {len(iterations) * 4} greens), {len(retires)} retirés")

def iteration(a):
    i = a.it
    if not (it_dir(i) / "lots" / "A" / "greens").exists():
        a.lot = "A"
        lot(a)
    if not (it_dir(i) / "lots" / "A" / "groupes.json").exists():
        analyser_lot(i, "A")
    if not (it_dir(i + 1)).exists():
        ajouter(a)


def bilan(a):
    for d in sorted(BASE.glob("it*"), key=lambda p: int(p.name[2:])):
        s = json.loads((d / "spec.json").read_text(encoding="utf-8"))
        for l in sorted((d / "lots").glob("*")) if (d / "lots").exists() else []:
            f = l / "accord.json"
            if f.exists():
                r = json.loads(f.read_text(encoding="utf-8"))
                print(f"{d.name} lot {l.name} : {len(s)} assertions, taux moyen {r['taux_moyen']}, accord à 4 {r['accord_4_part']}, "
                      f"{r['groupes']} groupes, classes {r['classes']}, accord des juges {r['accord_juges']}")
    print(f"dépensé : {depense():.2f} $ sur {PLAFOND:.0f} $")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commande", choices=["init", "lot", "analyser", "apparier", "ajouter", "iteration", "bilan", "decider", "bugs"])
    ap.add_argument("--it", type=int, default=0)
    ap.add_argument("--lot", default="A")
    ap.add_argument("--depuis", type=int, nargs="*", default=None)
    a = ap.parse_args()
    BASE.mkdir(parents=True, exist_ok=True)
    {"init": init, "lot": lot, "analyser": analyser, "apparier": apparier, "ajouter": ajouter,
     "iteration": iteration, "bilan": bilan, "decider": decider, "bugs": lambda a: bugs_en_tests(a.it, a.depuis)}[a.commande](a)


if __name__ == "__main__":
    main()
