"""La boucle de compilation de V5 (sonde P12, « du RC au plan du mémoire vérifié »).

Comme outils/boucle.py (P11), avec ce qui change pour V5 (docs/V5-cadrage.md §6 et §10) :
  - lot : 1 haiku (H) et 1 sonnet (S), délai d'une heure par appel, 4 tours au plus ;
  - une situation = un RC (295 synthétiques + 5 publics) ; chaque code rend un JSON par RC ;
  - divergences rangées par CHAMP (chemin du JSON sans les indices de liste, profondeur 2) :
    une situation peut tomber dans plusieurs groupes ; chaque groupe est jugé par deux juges opus ;
  - PORTE « question client » : chaque trou est classé « convention » ou « client » par un juge froid
    qui ne voit que §4 du protocole et le trou ; une convention est tranchée par le choix du juge
    (noté au journal, révisable) ; un trou client devient une décision PROVISOIRE (l'option recommandée)
    et une question à Bilel (A / B, avec exemples, groupée par principe candidat) ;
  - bugs → tests de non-régression dès l'itération 1 (les bugs de it_i protègent la spec v_{i+1}) ;
  - taux spec : une situation compte comme accord si chacun de ses champs divergents est jugé bug.

    python outils/v5/boucle_v5.py init
    python outils/v5/boucle_v5.py iteration --it 0      # lot, rejeu, groupes, juges, porte, ajouts → it1
    python outils/v5/boucle_v5.py bilan

Budget : runs-v5/budget.jsonl (toutes les dépenses de V5) ; plafond 70 $, alerte à 55 $.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[1]
sys.path.insert(0, str(RACINE / "outils"))
sys.path.insert(0, str(ICI))
from duel import GREEN, REEL, TECH, ZERO, additionner, appel, executer, formater, lignes_assertions  # noqa: E402
from boucle import AJOUTS, BUGS, retirer_tests  # noqa: E402
from situations import ids, situation  # noqa: E402

SONDE = "P12"
BASE = RACINE / "runs-v5" / "boucle"
BUDGET = RACINE / "runs-v5" / "budget.jsonl"
DUEL = RACINE / "runs-v5-duel" / SONDE
PLAFOND, ALERTE = 120.0, 100.0  # 22/11 : Bilel lève le plafond de 70 $ (garde-fou 120 $, comme P11)
GREENS = {"H": "haiku", "S": "sonnet"}
# Vérification d'un taux spec > 0,8 (cadrage §10) : V5_GREENS=H:haiku,S:sonnet,H2:haiku,S2:sonnet.
# Les groupes et les juges portent toujours sur la paire H-S ; les autres paires ont leur taux brut, et un taux
# spec approché (une situation compte si chacun de ses champs divergents tombe dans un groupe jugé bug sur H-S).
if os.environ.get("V5_GREENS"):
    GREENS = dict(x.split(":") for x in os.environ["V5_GREENS"].split(","))
MAX_TOURS = 4
DELAI = 3600
MAX_GROUPES = 12
ESTIME = {"haiku": 0.7, "sonnet": 2.2, "juge": 0.15, "red": 1.2, "porte": 0.3}
VERROU = threading.Lock()
SITUATIONS = Path(os.environ.get("V5_SITUATIONS", "/home/user/v5work/situations.json"))

JUGE = """Deux implémentations de la même spécification ont lu le même règlement de la consultation (RC).
Elles passent toutes les deux tous les tests de la spec. Sur un champ de leur résultat, elles ne rendent pas la même chose.

Spécification (assertions) :
{assertions}

Le RC (texte page par page) :
{pages}

Champ où elles divergent : {champ}
{variantes}

Classe ce désaccord. Un seul choix :
- trou : la spec ne tranche pas ce cas ; les deux variantes la respectent.
- bug V<n> : la spec tranche, et la variante V<n> la viole (l'autre a raison).
- invalide : le RC n'est pas un RC, ou le champ n'a pas de sens pour l'utilisateur.

Si c'est un trou, écris l'assertion stricte qui le tranche, au format de la spec
(« texte | observé: état | conditions: états »), en faveur de la variante la plus simple et la plus fidèle au RC.

Rends ton verdict au format de ton rôle, puis termine par exactement cinq lignes :
CLASSE: trou | bug V<n> | invalide
ASSERTION: <identifiant de l'assertion la plus proche, ou « aucune »>
CAS: <le cas en une phrase, sans parler des variantes>
CHOIX: <V<n> retenue si trou, sinon « aucun »>
NOUVELLE: <l'assertion stricte si trou, sinon « aucune »>
N'écris aucun fichier.
"""

PORTE = """Tu appliques une seule règle, celle-ci (protocole, §4) :

« Only what depends on the arbiter is asked of them. The test: would two equally competent arbiters, with
different lives, answer differently? If not, the answer exists in the collective knowledge and is decided
without asking, as a provisional decision with its source. The arbiter receives only what can be found nowhere
but in them: the facts of their life, their product intent where two of their statements contradict, or an
outward or irreversible action. »

L'arbitre est Bilel, qui construit un logiciel pour des entreprises du bâtiment qui répondent aux marchés publics :
le logiciel lit le règlement de la consultation (RC) et prépare le plan du mémoire technique.

Voici des cas que la spécification de ce logiciel ne tranche pas. Pour chacun : « convention » si deux experts
compétents des marchés publics et du logiciel, avec des vies différentes, répondraient pareil (la réponse se trouve
dans le savoir commun : code de la commande publique, usage, bon sens du format) ; « client » si la réponse dépend
d'un choix de produit propre à Bilel (ce que son logiciel doit montrer ou cacher, comment il traite un RC douteux
pour ses clients, ce qu'il promet).

{cas}

Puis regroupe les cas « client » qui relèvent d'un même principe (une seule réponse de Bilel les fermerait tous).
Pour chaque principe, propose deux options A et B, chacune en une phrase, avec un exemple concret tiré des cas,
et l'option que tu recommandes.

Termine par un bloc JSON, et rien après :
```json
{{"cas": [{{"n": 1, "classe": "convention|client", "raison": "..."}}],
  "principes": [{{"principe": "...", "cas": [1, 3], "A": "...", "B": "...", "exemple": "...", "recommande": "A|B"}}]}}
```
N'écris aucun fichier.
"""

REJOUER = r"""
import json, sys, signal, importlib.util
spec = importlib.util.spec_from_file_location("app", sys.argv[1])
app = importlib.util.module_from_spec(spec); sys.modules["app"] = app; spec.loader.exec_module(app)
situations = json.load(open(sys.argv[2], encoding="utf-8"))
def stop(*a): raise TimeoutError()
signal.signal(signal.SIGALRM, stop)
for i, pages in situations.items():
    try:
        signal.alarm(20)
        r = app.analyser(list(pages))
        signal.alarm(0)
        r = json.loads(json.dumps(r, ensure_ascii=False, default=lambda o: "?"))
    except BaseException as e:
        signal.alarm(0)
        r = {"__erreur__": type(e).__name__}
    print(json.dumps({"id": i, "r": r}, ensure_ascii=False), flush=True)
"""


# ── budget ────────────────────────────────────────────────────────────────

def depense():
    if not BUDGET.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in BUDGET.read_text(encoding="utf-8").splitlines() if l.strip())


def noter(etape, t):
    with VERROU:
        with BUDGET.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"etape": etape, "usd": t.get("usd", 0), "neufs": t.get("neufs", 0)}, ensure_ascii=False) + "\n")


def garde(estimation, quoi):
    d = depense()
    if d + estimation > PLAFOND:
        sys.exit(f"BUDGET : {quoi} estimé à {estimation:.2f} $, déjà {d:.2f} $ dépensés sur {PLAFOND:.0f} $. Étape non lancée.")
    if d + estimation > ALERTE:
        (BASE / "ALERTE-55").write_text(f"{d:.2f} $ dépensés avant « {quoi} »\n", encoding="utf-8")
    print(f"budget : {d:.2f} $ dépensés, {quoi} estimé à {estimation:.2f} $", flush=True)


def it_dir(i):
    return BASE / f"it{i}"


def spec(i):
    return json.loads((it_dir(i) / "spec.json").read_text(encoding="utf-8"))


def interface():
    src = (it_dir(0) / "tests" / "test_app.py").read_text(encoding="utf-8")
    m = re.match(r'\s*"""(.*?)"""', src, re.S)
    return m.group(1).strip() if m else src[:4000]


# ── init ──────────────────────────────────────────────────────────────────

def init(a):
    d = it_dir(0)
    if d.exists():
        sys.exit(f"{d} existe déjà")
    (d / "tests").mkdir(parents=True)
    s = lignes_assertions(RACINE / "data" / "v5" / "spec-v0" / f"{SONDE}_A.txt")
    (d / "spec.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in sorted(DUEL.glob("test_app*.py")):
        shutil.copy(f, d / "tests" / f.name)
    if not SITUATIONS.exists():
        SITUATIONS.write_text(json.dumps({i: situation(i)["pages"] for i in ids()}, ensure_ascii=False), encoding="utf-8")
    print(f"it0 : {len(s)} assertions, {len(list((d / 'tests').glob('*.py')))} fichiers de tests")


# ── a. le lot ─────────────────────────────────────────────────────────────

def un_green(i, nom, modele):
    d = it_dir(i) / "greens" / nom
    d.mkdir(parents=True, exist_ok=True)
    travail = Path(tempfile.mkdtemp(prefix=f"v5-{i}{nom}-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    shutil.copytree(it_dir(i) / "tests", travail / "tests")
    (travail / "reclamations").mkdir()
    resultats, total, journal, res, ok = "Premier tour : aucun résultat encore.", dict(ZERO), [], {}, 0
    for tour in range(1, MAX_TOURS + 1):
        existant = "Un app.py existe déjà (ton essai précédent) : lis-le et corrige-le.\n" if (travail / "app.py").exists() else ""
        r, t = appel("green", GREEN.format(tour=tour, dossier=travail, tech=TECH, reel=REEL[SONDE], existant=existant,
                                           assertions=formater(spec(i)), decisions="", resultats=resultats),
                     modele, "Read,Write,Edit", travail, delai=DELAI)
        noter(f"it{i}/{nom}/tour{tour}", t)
        total = additionner(total, t)
        res = executer(travail)
        ok = sum(v for v, _ in res.values())
        journal.append({"tour": tour, "passent": ok, "total": len(res), "usd": t["usd"]})
        print(f"  it{i} {nom} ({modele}) tour {tour} : {ok}/{len(res)} ({t['usd']:.2f} $)", flush=True)
        if res and ok == len(res):
            break
        echecs = [f"- {n} : {m}" for n, (v, m) in sorted(res.items()) if not v]
        resultats = "Échecs à la fin du tour précédent :\n" + "\n".join(echecs[:60])
    if (travail / "app.py").exists():
        shutil.copy(travail / "app.py", d / "app.py")
    for f in (travail / "reclamations").glob("*.md"):
        shutil.copy(f, d / f.name)
    tout = bool(res) and ok == len(res)
    (d / "bilan.json").write_text(json.dumps({"modele": modele, "tours": len(journal), "tout_passe": tout, "passent": ok,
                                              "total": len(res), "tokens": total, "journal": journal},
                                             ensure_ascii=False, indent=1), encoding="utf-8")
    return nom, tout, total["usd"]


def lot(i):
    garde(sum(ESTIME[m] for m in GREENS.values()), f"lot de it{i}")
    with ThreadPoolExecutor(len(GREENS)) as ex:
        for f in [ex.submit(un_green, i, n, m) for n, m in GREENS.items()]:
            print("  fini :", f.result(), flush=True)


# ── b. rejeu et accord ────────────────────────────────────────────────────

def rejouer(app_py):
    out = {}
    try:
        p = subprocess.run([sys.executable, "-I", "-c", REJOUER, str(app_py), str(SITUATIONS)],
                           capture_output=True, text=True, timeout=3 * 3600, cwd=tempfile.mkdtemp())
        lignes = p.stdout.splitlines()
    except subprocess.TimeoutExpired as e:
        lignes = (e.stdout or b"").decode() .splitlines() if isinstance(e.stdout, bytes) else (e.stdout or "").splitlines()
    for l in lignes:
        try:
            o = json.loads(l)
            out[o["id"]] = o["r"]
        except (json.JSONDecodeError, KeyError):
            pass
    return out


def sorties(i):
    d = it_dir(i) / "sorties"
    d.mkdir(exist_ok=True)

    def une(nom):
        f = d / f"{nom}.json"
        if f.exists():
            return nom, json.loads(f.read_text(encoding="utf-8"))
        app_py = it_dir(i) / "greens" / nom / "app.py"
        r1, r2 = rejouer(app_py), rejouer(app_py)
        bonnes = {k: v for k, v in r1.items() if r2.get(k) == v}
        f.write_text(json.dumps(bonnes, ensure_ascii=False), encoding="utf-8")
        return nom, bonnes

    with ThreadPoolExecutor(len(GREENS)) as ex:
        return dict(ex.map(une, GREENS))


def champs_differents(x, y, chemin="", prof=0):
    """Les champs (chemins sans indices de liste, profondeur ≤ 2) où x et y diffèrent."""
    if x == y:
        return set()
    if prof < 2 and isinstance(x, dict) and isinstance(y, dict):
        out = set()
        for k in set(x) | set(y):
            out |= champs_differents(x.get(k), y.get(k), f"{chemin}.{k}" if chemin else str(k), prof + 1)
        return out
    if prof < 2 and isinstance(x, list) and isinstance(y, list) and len(x) == len(y) and all(isinstance(e, dict) for e in x + y):
        out = set()
        for ex_, ey in zip(x, y):
            out |= champs_differents(ex_, ey, f"{chemin}[]", prof + 1)
        return out
    return {chemin or "(tout)"}


def accord(i, so):
    communs = sorted(set(so["H"]) & set(so["S"]), key=lambda k: ids().index(k))
    egaux = [k for k in communs if so["H"][k] == so["S"][k]]
    groupes = {}
    par_situation = {}
    for k in communs:
        if so["H"][k] == so["S"][k]:
            continue
        ch = champs_differents(so["H"][k], so["S"][k])
        par_situation[k] = sorted(ch)
        for c in ch:
            groupes.setdefault(c, []).append(k)
    return {"situations": len(communs), "egales": len(egaux), "taux": round(len(egaux) / max(len(communs), 1), 3),
            "taux_synth": round(sum(1 for k in egaux if k.startswith("S")) / max(sum(1 for k in communs if k.startswith("S")), 1), 3),
            "taux_publics": round(sum(1 for k in egaux if k.startswith("RC")) / max(sum(1 for k in communs if k.startswith("RC")), 1), 3),
            "groupes": {c: len(v) for c, v in sorted(groupes.items(), key=lambda kv: -len(kv[1]))}}, groupes, par_situation


# ── c. juges ──────────────────────────────────────────────────────────────

def extraire(o, chemin):
    """Valeur(s) d'un chemin « a.b[].c » dans la sortie o."""
    if chemin == "(tout)":
        return o
    cur = [o]
    for p in chemin.split("."):
        liste = p.endswith("[]")
        p = p[:-2] if liste else p
        nxt = []
        for c in cur:
            v = c.get(p) if isinstance(c, dict) else None
            if liste and isinstance(v, list):
                nxt.extend(v)
            else:
                nxt.append(v)
        cur = nxt
    return cur[0] if len(cur) == 1 else cur


def montrer(vh, vs):
    """Les deux variantes. Une liste longue est montrée par sa différence (corrigé à it3 : à it1 et it2, les
    variantes étaient coupées à 1 500 caractères et les juges ne voyaient pas l'écart d'une longue liste)."""
    j = lambda x: json.dumps(x, ensure_ascii=False)  # noqa: E731
    if isinstance(vh, list) and isinstance(vs, list) and len(j(vh)) + len(j(vs)) > 3000:
        sh = [j(x) for x in vs]
        hh = [j(x) for x in vh]
        seul_h = [x for x in vh if j(x) not in sh]
        seul_s = [x for x in vs if j(x) not in hh]
        communs = [x for x in vh if j(x) in sh]
        return (f"  Les deux codes rendent une liste ; {len(communs)} éléments identiques chez les deux "
                f"(par exemple : {j(communs[:2])[:600]}).\n"
                f"  V1 (code H) a {len(vh)} éléments ; seulement chez V1 : {j(seul_h)[:2500]}\n"
                f"  V2 (code S) a {len(vs)} éléments ; seulement chez V2 : {j(seul_s)[:2500]}")
    return (f"  V1 (code H) rend : {j(vh)[:3000]}\n"
            f"  V2 (code S) rend : {j(vs)[:3000]}")


def representant(sits):
    """La situation la plus courte (synthétique de préférence) d'un groupe."""
    synth = [k for k in sits if k.startswith("S")]
    cand = synth or sits
    return min(cand, key=lambda k: sum(map(len, situation(k)["pages"])))


def juger(i, champ, sits, so):
    k = representant(sits)
    pages = situation(k)["pages"]
    vh, vs = extraire(so["H"][k], champ), extraire(so["S"][k], champ)
    variantes = montrer(vh, vs)
    texte = JUGE.format(assertions=formater(spec(i)), champ=champ, variantes=variantes,
                        pages="\n".join(f"──── page {n} ────\n{p}" for n, p in enumerate(pages, 1))[:24000])
    verdicts = []
    for j in (1, 2):
        travail = Path(tempfile.mkdtemp(prefix="v5-juge-"))
        shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
        r, t = appel("judge", texte, "opus", "Write", travail, delai=DELAI)
        noter(f"it{i}/juge{j}/{champ}", t)
        txt = str(r.get("result", ""))

        def lire(nom):
            m = re.search(rf"^\**{nom}\**:\s*(.+)$", txt, re.M)
            return m.group(1).strip() if m else ""
        cl = lire("CLASSE").lower()
        mb = re.search(r"bug\s*v(\d)", cl)
        cl = "trou" if cl.startswith("trou") else "invalide" if cl.startswith("invalide") else f"bug V{mb.group(1)}" if mb else "non classé"
        verdicts.append({"classe": cl, "assertion": lire("ASSERTION"), "cas": lire("CAS"), "choix": lire("CHOIX"),
                         "nouvelle": lire("NOUVELLE"), "usd": t["usd"], "texte": txt[-1500:]})
    c1, c2 = verdicts[0]["classe"], verdicts[1]["classe"]
    final = c1 if c1 == c2 and c1 != "non classé" else "à trancher"
    if final.startswith("bug V"):
        final = "bug " + ("H" if final.endswith("1") else "S")
    return {"champ": champ, "situations": len(sits), "representant": k, "V1_H": vh, "V2_S": vs, "final": final, "juges": verdicts}


def porte(i, trous):
    """La porte « question client » : chaque trou est classé convention ou client par un juge froid."""
    if not trous:
        return {"cas": [], "principes": []}
    garde(ESTIME["porte"], f"porte client/convention de it{i}")
    cas = "\n".join(f"{n}. {g['juges'][0]['cas']} (champ {g['champ']} ; tranché par : {g['juges'][0]['nouvelle']})"
                    for n, g in enumerate(trous, 1))
    travail = Path(tempfile.mkdtemp(prefix="v5-porte-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    r, t = appel("judge", PORTE.format(cas=cas), "opus", "Write", travail, delai=DELAI)
    noter(f"it{i}/porte", t)
    txt = str(r.get("result", ""))
    m = re.search(r"```json\s*(\{.*\})\s*```", txt, re.S) or re.search(r"(\{\s*\"cas\".*\})", txt, re.S)
    try:
        return json.loads(m.group(1))
    except (AttributeError, json.JSONDecodeError):
        return {"cas": [], "principes": [], "illisible": txt[-2000:]}


def analyser(i):
    so = sorties(i)
    res, groupes, par_situation = accord(i, so)
    ordre = sorted(groupes.items(), key=lambda kv: -len(kv[1]))
    a_juger = ordre[:MAX_GROUPES]
    garde(2 * len(a_juger) * ESTIME["juge"], f"double juge de {len(a_juger)} groupes (it{i})")
    with ThreadPoolExecutor(4) as ex:
        jug = list(ex.map(lambda kv: juger(i, kv[0], kv[1], so), a_juger))
    for j in jug:
        print(f"  {j['champ']} ({j['situations']}) → {j['final']}  [{j['juges'][0]['classe']} / {j['juges'][1]['classe']}]", flush=True)
    trous = [j for j in jug if j["final"] == "trou"]
    if len(GREENS) > 2:
        finals_hs = {j["champ"]: j["final"] for j in jug}
        noms = list(GREENS)
        paires = {}
        for x in range(len(noms)):
            for y in range(x + 1, len(noms)):
                a_, b_ = so[noms[x]], so[noms[y]]
                cs = [k for k in set(a_) & set(b_)]
                eg = sum(a_[k] == b_[k] for k in cs)
                sp = sum(1 for k in cs if a_[k] != b_[k] and all(finals_hs.get(c, "").startswith("bug")
                                                                for c in champs_differents(a_[k], b_[k])))
                paires[f"{noms[x]}-{noms[y]}"] = {"taux": round(eg / len(cs), 3), "taux_spec_approche": round((eg + sp) / len(cs), 3)}
        tous = set.intersection(*(set(so[n]) for n in noms))
        res["paires"] = paires
        res["accord_tous"] = round(sum(1 for k in tous if all(so[n][k] == so[noms[0]][k] for n in noms)) / len(tous), 3)
    p = porte(i, trous)
    for n, g in enumerate(trous, 1):
        c = next((x for x in p.get("cas", []) if x.get("n") == n), {})
        g["porte"] = c.get("classe", "non classé")
        g["porte_raison"] = c.get("raison", "")
    finals = {j["champ"]: j["final"] for j in jug}
    spec_ok = sum(1 for k, ch in par_situation.items() if all(finals.get(c, "").startswith("bug") for c in ch))
    res.update({"juges": len(jug), "non_juges": [f"{c} ({len(v)})" for c, v in ordre[MAX_GROUPES:]],
                "classes": dict(Counter(j["final"] for j in jug)),
                "accord_juges": round(sum(j["juges"][0]["classe"] == j["juges"][1]["classe"] for j in jug) / max(len(jug), 1), 3),
                "taux_spec": round((res["egales"] + spec_ok) / max(res["situations"], 1), 3),
                "porte": dict(Counter(g["porte"] for g in trous)), "principes": p.get("principes", [])})
    d = it_dir(i)
    (d / "groupes.json").write_text(json.dumps(jug, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "accord.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "par_situation.json").write_text(json.dumps(par_situation, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("non_juges", "groupes", "principes")}, ensure_ascii=False), flush=True)
    return res


# ── d. ajouts : trous → assertions, bugs → tests ──────────────────────────

def valider(tf, i):
    """Un test ajouté doit passer sur au moins un green de it_i ; sinon il est retiré."""
    passages = {}
    for g in GREENS:
        app_py = it_dir(i) / "greens" / g / "app.py"
        if not app_py.exists():
            continue
        essai = Path(tempfile.mkdtemp(prefix="v5-valide-"))
        (essai / "tests").mkdir()
        shutil.copy(tf, essai / "tests" / tf.name)
        shutil.copy(app_py, essai / "app.py")
        for nom, (ok, _) in executer(essai).items():
            passages.setdefault(nom, []).append(g if ok else None)
    retires = [n for n, v in passages.items() if not any(v)]
    if retires:
        retirer_tests(tf, set(retires))
    return passages, retires


def ajouter(i):
    suivant = it_dir(i + 1)
    if suivant.exists():
        sys.exit(f"{suivant} existe déjà")
    jug = json.loads((it_dir(i) / "groupes.json").read_text(encoding="utf-8"))
    trous = [g for g in jug if g["final"] == "trou"]
    bugs = [g for g in jug if g["final"].startswith("bug")]
    s = spec(i)
    deja = [int(k[1:]) for k in s if k.startswith("C")]
    premier = (max(deja) + 1) if deja else 1
    (suivant / "tests").mkdir(parents=True)
    for f in (it_dir(i) / "tests").glob("*.py"):
        shutil.copy(f, suivant / "tests" / f.name)
    bilan = {"iteration": i, "trous": len(trous), "bugs": len(bugs)}
    ajouts = {}
    # trous → assertions (conventions : choix du juge ; client : décision provisoire, question à Bilel)
    if trous:
        blocs = []
        for n, g in enumerate(trous, 1):
            j = g["juges"][0]
            m = re.search(r"V(\d)", j["choix"] or "V1")
            retenu = g["V1_H"] if not m or m.group(1) == "1" else g["V2_S"]
            marque = " (décision PROVISOIRE, question posée au client)" if g.get("porte") == "client" else ""
            blocs.append(f"Cas {n} (champ {g['champ']}){marque} : {j['cas']}\n"
                         f"  comportement retenu : {json.dumps(retenu, ensure_ascii=False)[:700]}\n"
                         f"  assertion proposée : {j['nouvelle']}\n"
                         f"  assertion existante la plus proche : {j['assertion']}")
        garde(ESTIME["red"], f"assertions et tests de it{i + 1}")
        travail = Path(tempfile.mkdtemp(prefix="v5-ajouts-"))
        shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
        (travail / "tests").mkdir()
        fichier = f"test_app_c{i + 1}.py"
        r, t = appel("red", AJOUTS.format(tech=TECH, reel=REEL[SONDE], assertions=formater(s), interface=interface(),
                                          trous="\n\n".join(blocs), premier=f"C{premier:02d}", exemple=f"C{premier:02d}",
                                          dossier=travail, fichier=fichier), "opus", "Write", travail, delai=DELAI)
        noter(f"it{i}/ajouts", t)
        for ligne in (travail / "ajouts.md").read_text(encoding="utf-8").splitlines() if (travail / "ajouts.md").exists() else []:
            m = re.match(r"-\s*(C\d+)\s*:\s*(.+?)(?:\s*\|\s*cas:.*)?$", ligne.strip())
            if m and "observé:" in m.group(2):
                ajouts[m.group(1)] = m.group(2).strip()
        tf = travail / "tests" / fichier
        if tf.exists():
            passages, retires = valider(tf, i)
            shutil.copy(tf, suivant / "tests" / fichier)
            bilan.update({"tests_trous": len(passages) - len(retires), "tests_trous_retires": retires})
        if (travail / "ajouts.md").exists():
            shutil.copy(travail / "ajouts.md", it_dir(i) / "ajouts.md")
    # bugs → tests de non-régression (dès l'itération 0 → spec v1)
    if bugs:
        blocs = []
        for n, g in enumerate(bugs, 1):
            j = next(x for x in g["juges"] if x["classe"].startswith("bug"))
            bon, mauvais = (g["V2_S"], g["V1_H"]) if g["final"] == "bug H" else (g["V1_H"], g["V2_S"])
            pages = situation(g["representant"])["pages"]
            blocs.append(f"Cas {n} (champ {g['champ']}, assertion {j['assertion']}) : {j['cas']}\n"
                         f"  RC où le bug se voit (pages) : {json.dumps(pages, ensure_ascii=False)[:3000]}\n"
                         f"  comportement correct : {json.dumps(bon, ensure_ascii=False)[:600]}\n"
                         f"  comportement fautif : {json.dumps(mauvais, ensure_ascii=False)[:600]}")
        garde(ESTIME["red"], f"tests de non-régression de it{i + 1}")
        travail = Path(tempfile.mkdtemp(prefix="v5-bugs-"))
        shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
        (travail / "tests").mkdir()
        fichier = f"test_app_reg{i + 1}.py"
        r, t = appel("red", BUGS.format(tech=TECH, reel=REEL[SONDE], assertions=formater({**s, **ajouts}), interface=interface(),
                                        cas="\n\n".join(blocs), dossier=travail, fichier=fichier), "opus", "Write", travail, delai=DELAI)
        noter(f"it{i}/bugs", t)
        tf = travail / "tests" / fichier
        if tf.exists():
            passages, retires = valider(tf, i)
            shutil.copy(tf, suivant / "tests" / fichier)
            bilan.update({"tests_bugs": len(passages) - len(retires), "tests_bugs_retires": retires})
    (suivant / "spec.json").write_text(json.dumps({**s, **ajouts}, ensure_ascii=False, indent=1), encoding="utf-8")
    bilan["assertions_ajoutees"] = len(ajouts)
    journal = [{"champ": g["champ"], "cas": g["juges"][0]["cas"], "porte": g.get("porte"), "raison": g.get("porte_raison"),
                "decision": g["juges"][0]["choix"], "proposee": g["juges"][0]["nouvelle"]} for g in trous]
    (it_dir(i) / "decisions.json").write_text(json.dumps({"journal": journal, "ajouts": ajouts, "bilan": bilan},
                                                         ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(bilan, ensure_ascii=False), flush=True)


def iteration(a):
    i = a.it
    if not all((it_dir(i) / "greens" / g / "bilan.json").exists() for g in GREENS):
        lot(i)
    if not (it_dir(i) / "accord.json").exists():
        analyser(i)
    if not it_dir(i + 1).exists():
        ajouter(i)


def bilan(a):
    for d in sorted(BASE.glob("it*"), key=lambda p: int(p.name[2:])):
        f = d / "accord.json"
        if f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
            print(f"{d.name} : {len(json.loads((d / 'spec.json').read_text()))} assertions, taux {r['taux']} "
                  f"(synth {r['taux_synth']}, publics {r['taux_publics']}), taux spec {r['taux_spec']}, classes {r['classes']}, porte {r['porte']}")
    print(f"dépensé : {depense():.2f} $ sur {PLAFOND:.0f} $")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commande", choices=["init", "iteration", "analyser", "ajouter", "bilan"])
    ap.add_argument("--it", type=int, default=0)
    a = ap.parse_args()
    BASE.mkdir(parents=True, exist_ok=True)
    {"init": init, "iteration": iteration, "analyser": lambda a: analyser(a.it), "ajouter": lambda a: ajouter(a.it),
     "bilan": bilan}[a.commande](a)


if __name__ == "__main__":
    main()
