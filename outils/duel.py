"""Duel : fait tourner le protocole adversarial (couche code) sur une sonde, tour par tour.

Usage :
    python outils/duel.py P05            # à partir de data/passes/strict/P05_A.txt
    python outils/duel.py P10 --max-tours 20

Ce que fait un tour (SPEC §2 « Tour » : assertions → code → résultats) :
  1. tour 1 seulement : le RED (agent `red`, couche code) écrit les tests depuis les
     assertions seules. Chaque test cite son assertion dans son nom (test_A07_...).
     Ce que les assertions ne tranchent pas, il ne le devine pas : il l'écrit dans
     lacunes.md (« trou signalé à la découpe »).
  2. le GREEN (agent `green`, autre modèle) écrit app.py. Il n'a ni Bash ni résultat
     du tour en cours : chaque tour est un essai. Un test qu'il juge hors spec est
     levé en réclamation ancrée, jamais neutralisé.
  3. le banc exécute les tests, vérifie que le green n'a pas touché aux tests
     (diff vide, protocol.md §3), et enregistre le statut de chaque assertion.
  4. chaque échec est classé (SPEC 6.4) :
       - réclamation du green → un JUGE froid (agent `judge`) tranche :
           maintenue + « trou »          → trou (une nouvelle assertion est ajoutée)
           maintenue + « contradiction » → contradiction (le test est écarté)
           non tranchable                → trou
           rejetée                       → bug
       - pas de réclamation → bug
       - une assertion qui repasse de « passe » à « casse » deux fois → contradiction
  5. tokens : découpe = red + juge, exécution = green (tokens traités à neuf :
     entrée + sortie + écriture de cache ; la lecture de cache est notée à part).

Aveuglement : les agents tournent dans un dossier temporaire HORS du dépôt, où ne
sont copiés que les agents du protocole (.claude/agents) : ni CLAUDE.md du banc,
ni thèses, ni k. Les artefacts sont recopiés ensuite dans runs/<sonde>/.

Sortie : runs/<sonde>/journal.jsonl (un objet par tour), runs/<sonde>/rapport.md,
et les artefacts (tests, app.py, lacunes.md, réclamations, verdicts).
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
from mesure import lire_passe, mesurer  # noqa: E402

TECH = """Contexte technique (choisi par le banc, identique pour toutes les sondes) :
- Python 3.13, bibliothèque standard + le paquet `cryptography` (déjà installé). Rien d'autre.
- Tout le système est simulé en mémoire, dans un seul module `app.py` (pas de réseau réel,
  pas de disque, pas d'horloge réelle : le temps est une valeur que les tests font avancer).
- Tests : pytest, dans `tests/test_app.py`, qui importe `app`.
"""

RED = """Couche : code.

Tu écris les tests rouges de la sonde ci-dessous. Aucun code n'existe encore : c'est toi
qui fixes l'interface publique de `app` par tes tests (classes, méthodes, valeurs), et le
constructeur l'implémentera telle quelle. Garde-la simple et cohérente d'un test à l'autre.

{tech}
Spécification (assertions, chacune avec son identifiant) :
{assertions}

Règles :
- Chaque test cite l'assertion qu'il protège au début de son nom : `test_A07_...`.
  Plusieurs tests par assertion sont permis. Une assertion sans test n'est pas appliquée.
- Un test vérifie un comportement observable par l'utilisateur, jamais une structure interne.
- Si une assertion ne suffit pas à écrire un test sans deviner (un cas qu'elle ne tranche pas,
  une valeur qu'elle ne fixe pas, deux assertions qui se croisent sans dire qui l'emporte),
  NE DEVINE PAS : écris ce cas dans `lacunes.md`, une ligne par cas, au format
  `- A07 : <le cas non tranché, en une phrase>`.

Écris exactement deux fichiers, avec l'outil Write :
- {dossier}/tests/test_app.py
- {dossier}/lacunes.md (écris « aucune » si tu n'en as pas)
Réponds ensuite seulement « ok ».
"""

GREEN = """Couche : code. Tour {tour}.

Tu écris `{dossier}/app.py` pour que les tests de `{dossier}/tests/test_app.py` passent.
Les tests sont en lecture seule : les modifier invalide tout ton travail.
Tu n'as pas de moyen d'exécuter les tests pendant ce tour : relis-les avec soin.

{tech}
Règles de la spec (chaque test cite l'une d'elles dans son nom) :
{assertions}
{decisions}
{resultats}
Si un test te paraît hors spec, ne le contourne pas : lève une réclamation dans
`{dossier}/reclamations/tour{tour}.md`, un bloc par test, au format exact :

test:      <nom exact du test>
kind:      gap | contradiction
assertion: <ce que le test exige que la spec ne dit pas (gap), ou avec quelle règle il est incompatible (contradiction)>
anchor:    <la règle citée, ou le test + l'assertion qui s'opposent>

N'écris rien d'autre que app.py et, si besoin, ce fichier de réclamations.
Réponds ensuite seulement « ok ».
"""

JUGE = """Une réclamation contestée, couche code. Tranche-la.

Réclamation :
{reclamation}

Règles de la spec citées par le test (et la spec complète, pour l'ancre) :
{assertions}

Test contesté (artefact exécuté) :
```python
{test}
```
Résultat de l'exécution : {resultat}

La réclamation dit que ce test exige ce que la spec ne dit pas (gap), ou qu'il est
incompatible avec une autre règle (contradiction). Rends ton verdict au format de ton
rôle, puis termine par exactement deux lignes :
VERDICT: maintenue | rejetée | non tranchable
NOUVELLE_ASSERTION: <si maintenue et gap : l'assertion stricte qui manquait à la spec,
  au format « texte | observé: état | conditions: états » ; sinon « aucune »>
N'écris aucun fichier.
"""


def appel(role, texte, modele, outils, dossier, delai=1800):
    """Un appel headless d'un agent du protocole, sans session persistante. Rend (rapport, tokens)."""
    p = subprocess.run(["claude", "-p", "--agent", role, "--model", modele, "--output-format", "json",
                        "--no-session-persistence", "--allowedTools", *outils.split(",")],
                       input=texte, cwd=dossier, capture_output=True, text=True, timeout=delai)
    try:
        r = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"is_error": True, "result": (p.stdout + p.stderr)[-1500:]}, {"neufs": 0, "cache": 0, "usd": 0}
    neufs = cache = 0
    for u in r.get("modelUsage", {}).values():
        neufs += u.get("inputTokens", 0) + u.get("outputTokens", 0) + u.get("cacheCreationInputTokens", 0)
        cache += u.get("cacheReadInputTokens", 0)
    return r, {"neufs": neufs, "cache": cache, "usd": r.get("total_cost_usd", 0) or 0}


def additionner(*ts):
    return {k: sum(t[k] for t in ts) for k in ("neufs", "cache", "usd")}


ZERO = {"neufs": 0, "cache": 0, "usd": 0}


def lignes_assertions(chemin):
    out = []
    for ligne in open(chemin, encoding="utf-8"):
        ligne = ligne.strip()
        if ligne.startswith("- ") and "observé:" in ligne:
            out.append(ligne[2:])
    return {f"A{i:02d}": t for i, t in enumerate(out, 1)}


def formater(assertions):
    return "\n".join(f"{i} : {t}" for i, t in assertions.items())


def empreinte(f):
    return hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None


def executer(dossier):
    """Lance pytest ; rend {nom du test: (passe: bool, message)}."""
    xml = dossier / "resultats.xml"
    xml.unlink(missing_ok=True)
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                    f"--junitxml={xml}", "tests"], cwd=dossier, capture_output=True, text=True, timeout=900)
    res = {}
    if not xml.exists():
        return res
    for tc in ET.parse(xml).iter("testcase"):
        nom = tc.get("name")
        echec = tc.find("failure")
        if echec is None:
            echec = tc.find("error")
        if tc.find("skipped") is not None:
            res[nom] = (False, "skipped")
        elif echec is None:
            res[nom] = (True, "")
        else:
            res[nom] = (False, (echec.get("message") or "")[:300])
    return res


def assertion_de(test):
    m = re.match(r"test_([AN]\d+)", test)
    return m.group(1) if m else None


def source_test(dossier, nom):
    src = (dossier / "tests" / "test_app.py").read_text(encoding="utf-8")
    m = re.search(rf"^([ \t]*)def {re.escape(nom)}\(.*?(?=^\1def |^\S|\Z)", src, re.S | re.M)
    return m.group(0) if m else "(source introuvable)"


def lire_reclamations(f):
    if not f.exists():
        return []
    blocs = re.split(r"\n\s*\n(?=test:)", f.read_text(encoding="utf-8").strip())
    out = []
    for b in blocs:
        champs = dict(re.findall(r"^(\w+):\s*(.*)$", b, re.M))
        if "test" in champs:
            out.append({"test": champs["test"].strip(), "kind": champs.get("kind", "gap").strip(), "texte": b})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sonde")
    ap.add_argument("--passe", default="A")
    ap.add_argument("--max-tours", type=int, default=20)  # SPEC 6.4 : vingt tours → non convergente
    ap.add_argument("--red", default="opus")
    ap.add_argument("--green", default="sonnet")
    ap.add_argument("--juge", default="opus")
    ap.add_argument("--force", action="store_true", help="exécuter une sonde non concordante (marqué au journal)")
    a = ap.parse_args()

    # SPEC 6.4 : une sonde non concordante est refusée
    passes = sorted((RACINE / "data" / "passes" / "strict").glob(f"{a.sonde}_*.txt"))
    ks = [mesurer(lire_passe(p))["k"] for p in passes]
    concordante = len(ks) > 1 and max(ks) - min(ks) <= 0.15
    if not concordante and not a.force:
        sys.exit(f"{a.sonde} non concordante (k = {[round(k, 2) for k in ks]}) : exécution refusée (SPEC 6.4)")

    sortie = RACINE / "runs" / a.sonde
    if sortie.exists():
        sys.exit(f"{sortie} existe déjà")
    sortie.mkdir(parents=True)
    travail = Path(tempfile.mkdtemp(prefix=f"duel-{a.sonde}-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    (travail / "tests").mkdir()
    (travail / "reclamations").mkdir()
    journal = (sortie / "journal.jsonl").open("a", encoding="utf-8")

    assertions = lignes_assertions(RACINE / "data" / "passes" / "strict" / f"{a.sonde}_{a.passe}.txt")
    nouvelles = {}
    ecartes = set()  # tests écartés par un verdict de contradiction
    decisions = []
    essais = {}  # assertion → tour où elle passe pour la première fois
    bascules = {}  # assertion → nombre de passages passe → casse
    precedent = {}

    # Tour 1, découpe : le red écrit les tests
    r, t_red = appel("red", RED.format(tech=TECH, assertions=formater(assertions), dossier=travail),
                     a.red, "Write", travail)
    test_f = travail / "tests" / "test_app.py"
    if not test_f.exists():
        sys.exit(f"le red n'a pas écrit de tests : {r.get('result', '')[:500]}")
    sceau = empreinte(test_f)
    shutil.copy(test_f, sortie / "test_app.py")
    lacunes = [l[2:].strip() for l in (travail / "lacunes.md").read_text(encoding="utf-8").splitlines()
               if l.startswith("- ")] if (travail / "lacunes.md").exists() else []

    resultats_txt = "Premier tour : aucun résultat encore."
    convergent = False
    for tour in range(1, a.max_tours + 1):
        t_decoupe = t_red if tour == 1 else dict(ZERO)
        dec_txt = ("Décisions du juge sur les réclamations précédentes :\n" + "\n".join(decisions) + "\n") if decisions else ""
        r, t_green = appel("green", GREEN.format(tour=tour, dossier=travail, tech=TECH,
                                                 assertions=formater({**assertions, **nouvelles}),
                                                 decisions=dec_txt, resultats=resultats_txt),
                           a.green, "Read,Write,Edit", travail)
        viole = empreinte(test_f) != sceau
        if viole:  # diff non vide sur les tests : travail invalidé, tests restaurés
            shutil.copy(sortie / "test_app.py", test_f)
        res = executer(travail)

        # statut par assertion : passe si tous ses tests (non écartés) passent
        par_a = {}
        for nom, (ok, _) in res.items():
            if nom in ecartes:
                continue
            aid = assertion_de(nom) or "?"
            par_a[aid] = par_a.get(aid, True) and ok
        for aid, ok in par_a.items():
            if ok and aid not in essais:
                essais[aid] = tour
            if precedent.get(aid) and not ok:
                bascules[aid] = bascules.get(aid, 0) + 1
        precedent = par_a

        # classement des échecs
        recl = {c["test"]: c for c in lire_reclamations(travail / "reclamations" / f"tour{tour}.md")}
        echecs = []
        t_juge = dict(ZERO)
        for nom, (ok, msg) in sorted(res.items()):
            if ok or nom in ecartes:
                continue
            aid = assertion_de(nom)
            e = {"test": nom, "assertion": aid, "message": msg, "type": "bug", "source": "pas de réclamation"}
            if nom in recl:
                c = recl[nom]
                rj, tj = appel("judge", JUGE.format(reclamation=c["texte"], assertions=formater({**assertions, **nouvelles}),
                                                    test=source_test(travail, nom), resultat=msg or "échec"),
                               a.juge, "Write", travail, delai=900)
                t_juge = additionner(t_juge, tj)
                txt = rj.get("result", "")
                v = re.search(r"VERDICT:\s*(maintenue|rejetée|rejetee|non tranchable)", txt)
                v = v.group(1) if v else "non tranchable"
                na = re.search(r"NOUVELLE_ASSERTION:\s*(.+)", txt)
                na = na.group(1).strip() if na else "aucune"
                (sortie / "verdicts").mkdir(exist_ok=True)
                (sortie / "verdicts" / f"tour{tour}-{nom}.md").write_text(c["texte"] + "\n\n---\n\n" + txt, encoding="utf-8")
                if v == "maintenue" and c["kind"] == "contradiction":
                    e.update(type="contradiction", source="juge")
                    ecartes.add(nom)
                    decisions.append(f"- {nom} : contradiction reconnue, le test est écarté.")
                elif v == "rejetée" or v == "rejetee":
                    e.update(type="bug", source="juge : réclamation rejetée")
                    decisions.append(f"- {nom} : réclamation rejetée, le test reste exigé.")
                else:
                    e.update(type="trou", source=f"juge : {v}")
                    if na.lower() != "aucune":
                        nid = f"N{len(nouvelles) + 1:02d}"
                        nouvelles[nid] = na
                        e["nouvelle_assertion"] = nid
                    decisions.append(f"- {nom} : trou reconnu, le test reste exigé ; la spec gagne : {na}")
            elif aid and bascules.get(aid, 0) >= 2:
                e.update(type="contradiction", source="alternance passe/casse")
            echecs.append(e)

        tout_passe = bool(res) and all(ok for n, (ok, _) in res.items() if n not in ecartes)
        ligne = {
            "tour": tour,
            "statut": {aid: ("passe" if ok else "casse") for aid, ok in sorted(par_a.items())},
            "tests": {"total": len(res), "passent": sum(ok for ok, _ in res.values()), "ecartes": len(ecartes)},
            "tokens_decoupe": additionner(t_decoupe, t_juge),
            "tokens_execution": t_green,
            "echecs": echecs,
            "reclamations": len(recl),
            "violation_tests": viole,
            "nouvelles_assertions": dict(nouvelles),
        }
        journal.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        journal.flush()
        print(f"{a.sonde} tour {tour} : {ligne['tests']['passent']}/{len(res)} tests, "
              f"{sum(1 for v in ligne['statut'].values() if v == 'passe')}/{len(ligne['statut'])} assertions, "
              f"échecs {[e['type'] for e in echecs]}", flush=True)
        if tout_passe:
            convergent = True
            break
        resultats_txt = "Résultats de l'exécution des tests à la fin du tour précédent (échecs seulement) :\n" + "\n".join(
            f"- {nom} : {msg}" for nom, (ok, msg) in sorted(res.items()) if not ok and nom not in ecartes)

    for f in ("app.py", "lacunes.md"):
        if (travail / f).exists():
            shutil.copy(travail / f, sortie / f)
    if any((travail / "reclamations").iterdir()):
        shutil.copytree(travail / "reclamations", sortie / "reclamations")
    fin = {"sonde": a.sonde, "passe": a.passe, "k": [round(k, 2) for k in ks], "concordante": concordante,
           "convergent": convergent, "tours": tour, "essais": essais, "lacunes": lacunes,
           "nouvelles_assertions": nouvelles, "modeles": {"red": a.red, "green": a.green, "juge": a.juge},
           "assertions": len(assertions)}
    (sortie / "bilan.json").write_text(json.dumps(fin, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(fin, ensure_ascii=False))


if __name__ == "__main__":
    main()
