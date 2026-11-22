"""Duel : fait tourner le protocole adversarial (couche code) sur une sonde, tour par tour.

Usage :
    python outils/duel.py P05                         # duel V1 sur data/passes/strict-v2/P05_A.txt
    python outils/duel.py P10 --force                 # sonde floue ou non concordante : exécutée, marquée
    python outils/duel.py P05 --passes strict --attaques 1 --green sonnet --sortie runs   # réglages du V0

(Le V0 du 19/11 a tourné avec la version de ce fichier au commit 2bd7412.)

Un tour (SPEC §2 « Tour ») : assertions → code → résultats.

  ATTAQUE 1 (avant le code) : le RED (agent `red`, couche code) écrit les tests depuis les
     assertions seules ; chaque test cite son assertion (test_A07_...). Quand une assertion
     ne tranche pas un cas, il le note dans lacunes.md (« trou a priori ») ET il écrit quand
     même un test qui prend position, nommé test_A07_trou_... : un test qui casse.
  TOURS : le GREEN (agent `green`, autre modèle) écrit app.py, sans Bash ni résultat du tour
     en cours (un tour = un essai). Le banc exécute les tests, vérifie que le green n'a pas
     touché aux tests, et enregistre le statut de chaque assertion.
  ATTAQUE 2 : dès que tout passe (ou au tour --tour-attaque-2), le red attaque à nouveau :
     il voit ses tests et leur statut, jamais le code, et écrit tests/test_app_2.py.
  FIN : tout passe après la dernière attaque, ou --max-tours (SPEC 6.4 : 20 → non convergente).

Classement de chaque test qui casse (une fois, à son premier échec) :
  - test « _trou_ » du red                         → trou (son assertion présumée rejoint la spec)
  - réclamation du green → JUGE froid (agent `judge`) :
        maintenue + gap            → trou
        maintenue + contradiction  → contradiction (le test est écarté)
        non tranchable             → trou
        rejetée                    → bug
  - sinon                                          → bug
  - une assertion qui repasse deux fois de « passe » à « casse » → contradiction

Champ local (V2, outils/causes.py) : nombre de CAUSES distinctes (même message d'erreur = une cause)
rencontrées avant qu'une assertion passe, séparé pour les assertions frontière et les autres.
L'ancien compte (tours cassés + 1) reste dans bilan.json sous `champ_local` / `essais`.

Mécanismes frontière : interdit de les simuler (vraie cryptographie pour le chat, vraie fusion
d'éditions concurrentes pour l'éditeur) ; le reste peut rester en mémoire.

Tokens : découpe = red + juge, exécution = green (tokens traités à neuf : entrée + sortie +
écriture de cache ; la lecture de cache et le coût en $ sont notés à part).

Aveuglement : les agents tournent dans un dossier temporaire HORS du dépôt, où ne sont copiés
que les agents du protocole : ni CLAUDE.md du banc, ni thèses, ni k, ni marque « frontière ».
"""
import argparse
import ast
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
from mesure import concordance, frontieres, lire_passe, mesurer  # noqa: E402

TECH = """Contexte technique (identique pour toutes les sondes) :
- Python 3.13, bibliothèque standard + le paquet `cryptography` (déjà installé). Rien d'autre.
- Tout le système tient dans un seul module `app.py`. Pas de réseau réel ni de disque : les
  échanges entre machines passent par un réseau simulé en mémoire, et le temps est une valeur
  que les tests font avancer.
- Tests : pytest, dans `tests/`, qui importent `app`. Chaque test s'exécute en moins de 20 s.
"""

REEL = {
    "P10": """Mécanisme à réaliser pour de vrai (interdit de le simuler) : le chiffrement de bout en bout.
- Utiliser `cryptography` : accord de clés (par ex. X25519), dérivation (HKDF), chiffrement
  authentifié (AES-GCM ou ChaCha20-Poly1305).
- Chaque appareil génère ses propres clés privées et ne les partage avec aucun autre objet.
- Le serveur ne reçoit et ne stocke que des octets chiffrés ; aucune clé de message ne passe par
  le serveur ni par un objet partagé entre expéditeur et destinataire.
""",
    "P08": """Mécanisme à réaliser pour de vrai (interdit de le simuler) : la fusion des éditions concurrentes.
- Chaque participant a sa propre réplique du document et édite localement, sans attendre.
- Les éditions sont des opérations échangées entre répliques par un réseau simulé qui peut les
  retarder et les livrer dans n'importe quel ordre.
- Les répliques convergent par un vrai algorithme de fusion (transformation opérationnelle ou CRDT),
  pas par un verrou, ni par un serveur qui remplace tout le texte.
""",
    "P02": """Mécanisme à réaliser pour de vrai (interdit de le simuler) : la persistance entre deux ouvertures.
- Exception à « pas de disque » : l'application enregistre ses données dans un fichier dont le chemin
  est donné par les tests (par ex. `tmp_path`) ; une nouvelle instance créée sur ce chemin relit tout.
- Rien ne passe d'une instance à l'autre par la mémoire (pas de variable globale ni de cache partagé).
""",
    "P06": """Mécanisme à réaliser pour de vrai (interdit de le simuler) : la persistance entre deux ouvertures.
- Exception à « pas de disque » : l'application enregistre ses données dans un fichier dont le chemin
  est donné par les tests (par ex. `tmp_path`) ; une nouvelle instance créée sur ce chemin relit tout.
- Rien ne passe d'une instance à l'autre par la mémoire (pas de variable globale ni de cache partagé).
""",
    "P07": """Mécanisme à réaliser pour de vrai (interdit de le simuler) : la synchronisation hors ligne.
- Chaque appareil a sa propre copie des notes et travaille sans connexion.
- Les modifications passent par un réseau simulé qui peut couper, retarder, perdre un envoi en cours
  et livrer dans n'importe quel ordre ; un envoi coupé est réessayé, sans doublon.
- La réconciliation et la détection de conflit sont faites pour de vrai sur les copies,
  pas par un objet partagé que tous les appareils lisent.
""",
    "P09": """Mécanisme à réaliser pour de vrai (interdit de le simuler) : les fuseaux horaires et la concurrence.
- Les fuseaux passent par `zoneinfo` (vraies règles d'heure d'été), jamais par un décalage fixe.
- Des demandes « simultanées » peuvent arriver depuis plusieurs threads en même temps : la capacité
  doit tenir sous une vraie concurrence (verrou ou opération atomique), pas parce que les appels sont séquentiels.
""",
    "P11": """Mécanismes à réaliser pour de vrai (interdit de les simuler) :
- Formules : un vrai analyseur d'expressions et un recalcul qui suit le graphe des dépendances entre
  cellules ; une référence circulaire est détectée sur ce graphe, pas par une liste de cas connus.
- Collaboration hors ligne : chaque personne a sa propre copie du classeur et édite sans attendre ;
  les modifications passent par un réseau simulé qui peut les retarder, les couper et les livrer dans
  n'importe quel ordre ; la fusion et la détection de conflit se font sur les copies, pas par un
  objet partagé que tout le monde lit.
- Dates : les fuseaux passent par `zoneinfo` (vraies règles d'heure d'été), jamais par un décalage fixe.
""",
    "P12": """Ce que le module doit faire pour de vrai (interdit de le simuler) : lire un règlement de la consultation.
- Point d'entrée unique : `app.analyser(pages)`, où `pages` est une liste de chaînes (le texte de chaque
  page du RC, page 1 en premier). Il rend un dictionnaire sérialisable en JSON (chaînes, nombres,
  booléens, None, listes, dictionnaires), toujours le même pour les mêmes pages.
- Le code est déterministe : expressions régulières, règles écrites, bibliothèque standard. Aucun modèle
  de langage, aucun appel réseau, aucun hasard au moment de l'exécution.
- Les RC sont des textes libres d'acheteurs français : tournures, formats de date et mises en page variés.
  Une règle qui ne marche que sur l'exemple exact d'un test (texte recopié, numéro de page codé en dur)
  est une simulation.
- Une valeur rendue doit être retrouvée dans le texte d'une page, sinon elle n'est pas rendue.
""",
}
REEL_DEFAUT ="""Aucun mécanisme ne doit être simulé par un raccourci qui renvoie directement le
résultat attendu ; ce qui dépend du temps passe par l'horloge que les tests font avancer.
"""

RED1 = """Couche : code. Première attaque.

Tu écris les tests rouges de la sonde ci-dessous. Aucun code n'existe encore : c'est toi
qui fixes l'interface publique de `app` par tes tests (classes, méthodes, valeurs), et le
constructeur l'implémentera telle quelle. Garde-la simple et cohérente d'un test à l'autre.

{tech}
{reel}
Tes tests doivent casser contre une implémentation qui simulerait ce mécanisme.

Spécification (assertions, chacune avec son identifiant) :
{assertions}

Règles :
- Chaque test cite l'assertion qu'il protège au début de son nom : `test_A07_...`.
  Plusieurs tests par assertion sont permis. Une assertion sans test n'est pas appliquée.
- Un test vérifie un comportement observable de l'extérieur, jamais une structure interne.
- Ton objectif est d'écrire des tests qui CASSENT pour une bonne raison. Quand une assertion
  ne tranche pas un cas (une valeur qu'elle ne fixe pas, deux assertions qui se croisent sans
  dire qui l'emporte), fais deux choses :
  1. note le cas dans `lacunes.md`, une ligne par cas, au format exact :
     `- A07 : <le cas non tranché> | test: test_A07_trou_<nom> | présumé: <l'assertion que ton test suppose, au format « texte | observé: état | conditions: états »>`
  2. écris ce test `test_A07_trou_<nom>`, qui prend la position la plus raisonnable.

Écris exactement deux fichiers, avec l'outil Write :
- {dossier}/tests/test_app.py
- {dossier}/lacunes.md (écris « aucune » si tu n'en as pas)
Réponds ensuite seulement « ok ».
"""

RED2 = """Couche : code. Deuxième attaque.

Le constructeur a fait passer tous tes tests (ou s'en est approché) : un test vert est, pour toi,
un test qui n'a rien révélé. Attaque encore. Tu ne vois pas le code, seulement tes propres tests
et leur statut.

{tech}
{reel}
Spécification (assertions, chacune avec son identifiant) :
{assertions}

Tes tests de la première attaque (l'interface de `app` est celle-ci, garde-la) :
```python
{tests}
```
Statut à la fin du dernier tour :
{statut}

Cherche dans cet ordre : les invariants, les cas limites non dits (vide, zéro, un seul élément,
doublon, ordre inversé, non-ASCII), les interactions entre règles, la répétition, la coordination
de deux acteurs, et surtout tout ce qui casserait une implémentation qui simule le mécanisme.

Mêmes règles qu'à la première attaque : chaque test cite son assertion (`test_A07_...`), noms
nouveaux (aucun nom déjà pris), et pour un cas que la spec ne tranche pas, une ligne dans
lacunes2.md au format `- A07 : <cas> | test: test_A07_trou_<nom> | présumé: <assertion>` et le test.

Écris exactement deux fichiers, avec l'outil Write :
- {dossier}/tests/test_app_2.py (il importe `app` comme le premier)
- {dossier}/lacunes2.md (écris « aucune » si tu n'en as pas)
Réponds ensuite seulement « ok ».
"""

GREEN = """Couche : code. Tour {tour}.

Tu écris `{dossier}/app.py` pour que les tests de `{dossier}/tests/` passent.
Les tests sont en lecture seule : les modifier invalide tout ton travail.
Tu n'as pas de moyen d'exécuter les tests pendant ce tour : relis-les avec soin.
{existant}
{tech}
{reel}
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

Spec complète (pour l'ancre) :
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

ZERO = {"neufs": 0, "cache": 0, "usd": 0}


def appel(role, texte, modele, outils, dossier, delai=1800):
    """Un appel headless d'un agent du protocole, sans session persistante. Rend (rapport, tokens)."""
    try:
        p = subprocess.run(["claude", "-p", "--agent", role, "--model", modele, "--output-format", "json",
                            "--no-session-persistence", "--allowedTools", *outils.split(",")],
                           input=texte, cwd=dossier, capture_output=True, text=True, timeout=delai)
        r = json.loads(p.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        return {"is_error": True, "result": str(e)[-1500:]}, dict(ZERO)
    neufs = cache = 0
    for u in r.get("modelUsage", {}).values():
        neufs += u.get("inputTokens", 0) + u.get("outputTokens", 0) + u.get("cacheCreationInputTokens", 0)
        cache += u.get("cacheReadInputTokens", 0)
    return r, {"neufs": neufs, "cache": cache, "usd": r.get("total_cost_usd", 0) or 0}


def additionner(*ts):
    return {k: sum(t[k] for t in ts) for k in ("neufs", "cache", "usd")}


def lignes_assertions(chemin):
    out = []
    for ligne in open(chemin, encoding="utf-8"):
        ligne = ligne.strip()
        if ligne.startswith("- ") and "observé:" in ligne:
            texte = "|".join(m for m in ligne[2:].split("|") if not m.strip().lower().startswith("frontière:"))
            out.append(texte.strip())  # la marque « frontière » n'est jamais montrée aux agents
    return {f"A{i:02d}": t for i, t in enumerate(out, 1)}


def formater(assertions):
    return "\n".join(f"{i} : {t}" for i, t in assertions.items())


def empreinte(dossier):
    h = hashlib.sha256()
    for f in sorted((dossier / "tests").glob("*.py")):
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()


def noms_tests(dossier):
    noms = []
    for f in sorted((dossier / "tests").glob("test_*.py")):
        try:
            arbre = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        noms += [n.name for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    return noms


def executer(dossier):
    """Lance pytest ; rend {nom du test: (passe, message)}. Un test connu absent du rapport
    (module qui ne s'importe pas, délai dépassé) compte comme cassé."""
    xml = dossier / "resultats.xml"
    xml.unlink(missing_ok=True)
    sortie_pytest = ""
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=20",
                            f"--junitxml={xml}", "tests"], cwd=dossier, capture_output=True, text=True, timeout=900)
        sortie_pytest = p.stdout
    except subprocess.TimeoutExpired:
        pass
    res = {}
    collecte = ""
    if xml.exists():
        for tc in ET.parse(xml).iter("testcase"):
            nom = tc.get("name")
            echec = tc.find("failure")
            if echec is None:
                echec = tc.find("error")
            if not nom.startswith("test_"):
                # le message junit dit seulement « collection failure » : on garde la vraie erreur
                # (corrigé après le duel V1, où le green du chat a perdu un tour faute de la voir)
                detail = [l for l in sortie_pytest.splitlines() if "Error" in l or l.startswith("E ")]
                collecte = " / ".join(detail[-3:]) or (echec.get("message") if echec is not None else "") or "erreur de collecte"
                continue
            nom = nom.split("[")[0]
            ok = echec is None and tc.find("skipped") is None
            msg = "" if ok else ("skipped" if echec is None else (echec.get("message") or "")[:300])
            if nom in res:  # test paramétré : il passe si toutes ses variantes passent
                ok, msg = res[nom][0] and ok, res[nom][1] or msg
            res[nom] = (ok, msg)
    for nom in noms_tests(dossier):
        if nom not in res:
            res[nom] = (False, f"non exécuté : {collecte[:400] or 'app.py ne s’importe pas ou délai dépassé'}")
    return res


def assertion_de(test):
    m = re.match(r"test_([AN]\d+)", test)
    return m.group(1) if m else None


def source_test(dossier, nom):
    for f in sorted((dossier / "tests").glob("test_*.py")):
        src = f.read_text(encoding="utf-8")
        m = re.search(rf"^([ \t]*)def {re.escape(nom)}\(.*?(?=^\1def |^\S|\Z)", src, re.S | re.M)
        if m:
            return m.group(0)
    return "(source introuvable)"


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


def lire_lacunes(f):
    """Lignes « - A07 : cas | test: nom | présumé: assertion » → liste de dicts."""
    out = []
    if not f.exists():
        return out
    motif = re.compile(r"^- (?P<cas>.*?)\s*\|\s*test:\s*(?P<test>\S+)\s*(?:\|\s*présumé:\s*(?P<pres>.*))?$")
    for l in f.read_text(encoding="utf-8").splitlines():
        if not l.startswith("- "):
            continue
        m = motif.match(l.strip())
        champs = {"cas": m["cas"], "test": m["test"], "présumé": (m["pres"] or "").strip()} if m else {"cas": l[2:].strip()}
        out.append(champs)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sonde")
    ap.add_argument("--passes", default="strict-v2", help="dossier de data/passes")
    ap.add_argument("--passe", default="A")
    ap.add_argument("--max-tours", type=int, default=20)  # SPEC 6.4 : vingt tours → non convergente
    ap.add_argument("--attaques", type=int, default=2)
    ap.add_argument("--tour-attaque-2", type=int, default=8, help="attaque 2 au plus tard à ce tour")
    ap.add_argument("--red", default="opus")
    ap.add_argument("--green", default="haiku")
    ap.add_argument("--juge", default="opus")
    ap.add_argument("--sortie", default="runs-v1")
    ap.add_argument("--force", action="store_true", help="exécuter une sonde floue ou non concordante (marqué)")
    ap.add_argument("--attaque-seule", action="store_true",
                    help="H15 : seulement l'attaque 1 du red (trous a priori), sans green ni exécution")
    a = ap.parse_args()

    dossier_passes = RACINE / "data" / "passes" / a.passes
    passes = sorted(dossier_passes.glob(f"{a.sonde}_*.txt"))
    ks = [mesurer(lire_passe(p))["k"] for p in passes]
    k, statut_conc = concordance(ks)
    if statut_conc != "concordante" and not a.force:
        sys.exit(f"{a.sonde} : {statut_conc} (k = {[round(x, 2) for x in ks]}) : exécution refusée (SPEC 6.4)")

    sortie = RACINE / a.sortie / a.sonde
    if sortie.exists():
        sys.exit(f"{sortie} existe déjà")
    sortie.mkdir(parents=True)
    travail = Path(tempfile.mkdtemp(prefix=f"duel-{a.sonde}-"))
    shutil.copytree(RACINE / ".claude" / "agents", travail / ".claude" / "agents")
    (travail / "tests").mkdir()
    (travail / "reclamations").mkdir()
    journal = (sortie / "journal.jsonl").open("a", encoding="utf-8")

    fichier_passe = dossier_passes / f"{a.sonde}_{a.passe}.txt"
    assertions = lignes_assertions(fichier_passe)
    frontiere = {aid: f for aid, f in zip(assertions, frontieres(fichier_passe))}
    reel = REEL.get(a.sonde, REEL_DEFAUT)
    nouvelles = {}
    ecartes = set()
    decisions = []
    classes = {}  # test → type d'échec, figé à son premier échec
    casses = {}  # assertion → nombre de tours où elle a cassé
    passee = {}  # assertion → a fini par passer
    bascules = {}
    precedent = {}
    lacunes_par_test = {}
    trous_a_priori = []

    def spec():
        return formater({**assertions, **nouvelles})

    def attaquer(n, statut_txt=""):
        if n == 1:
            texte = RED1.format(tech=TECH, reel=reel, assertions=spec(), dossier=travail)
            fichier, lac = "test_app.py", "lacunes.md"
        else:
            tests = (travail / "tests" / "test_app.py").read_text(encoding="utf-8")
            texte = RED2.format(tech=TECH, reel=reel, assertions=spec(), tests=tests, statut=statut_txt, dossier=travail)
            fichier, lac = "test_app_2.py", "lacunes2.md"
        r, t = appel("red", texte, a.red, "Write", travail)
        if not (travail / "tests" / fichier).exists():
            sys.exit(f"le red n'a pas écrit {fichier} : {str(r.get('result', ''))[:500]}")
        shutil.copy(travail / "tests" / fichier, sortie / fichier)
        if (travail / lac).exists():
            shutil.copy(travail / lac, sortie / lac)
        for l in lire_lacunes(travail / lac):
            l["attaque"] = n
            trous_a_priori.append(l)
            if l.get("test"):
                lacunes_par_test[l["test"]] = l
        return t

    t_attaque = attaquer(1)
    if a.attaque_seule:
        fin = {"sonde": a.sonde, "passes": a.passes, "passe": a.passe, "k_passes": [round(x, 2) for x in ks],
               "k_retenu": round(k, 2) if k else None, "concordance": statut_conc, "assertions": len(assertions),
               "frontieres": sum(frontiere.values()), "tests": len(noms_tests(travail)),
               "trous_a_priori": len(trous_a_priori),
               "trous_par_assertion": round(len(trous_a_priori) / len(assertions), 3),
               "tokens_decoupe": t_attaque, "lacunes": trous_a_priori, "modeles": {"red": a.red}}
        (sortie / "bilan.json").write_text(json.dumps(fin, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in fin.items() if k != "lacunes"}, ensure_ascii=False))
        return
    sceau = empreinte(travail)
    attaques = 1
    resultats_txt = "Premier tour : aucun résultat encore."
    convergent = False
    tour = 0
    while tour < a.max_tours:
        tour += 1
        t_decoupe, t_attaque = t_attaque, dict(ZERO)
        dec_txt = ("Décisions sur les réclamations et les trous des tours précédents :\n" + "\n".join(decisions) + "\n") if decisions else ""
        existant = ("Un app.py existe déjà (ton essai précédent) : lis-le et corrige-le.\n"
                    if (travail / "app.py").exists() else "")
        r, t_green = appel("green", GREEN.format(tour=tour, dossier=travail, tech=TECH, reel=reel, existant=existant,
                                                 assertions=spec(), decisions=dec_txt, resultats=resultats_txt),
                           a.green, "Read,Write,Edit", travail)
        viole = empreinte(travail) != sceau
        if viole:  # diff non vide sur les tests : tests restaurés depuis la copie du banc
            for f in ("test_app.py", "test_app_2.py"):
                if (sortie / f).exists():
                    shutil.copy(sortie / f, travail / "tests" / f)
        res = executer(travail)
        shutil.copy(travail / "app.py", sortie / f"app_tour{tour:02d}.py") if (travail / "app.py").exists() else None

        par_a = {}
        for nom, (ok, _) in res.items():
            if nom in ecartes:
                continue
            aid = assertion_de(nom) or "?"
            par_a[aid] = par_a.get(aid, True) and ok
        for aid, ok in par_a.items():
            if ok:
                passee[aid] = True
            else:
                casses[aid] = casses.get(aid, 0) + 1
                passee[aid] = False
            if precedent.get(aid) and not ok:
                bascules[aid] = bascules.get(aid, 0) + 1
        precedent = par_a

        recl = {c["test"]: c for c in lire_reclamations(travail / "reclamations" / f"tour{tour}.md")}
        echecs = []
        t_juge = dict(ZERO)
        for nom, (ok, msg) in sorted(res.items()):
            if ok or nom in ecartes:
                continue
            aid = assertion_de(nom)
            e = {"test": nom, "assertion": aid, "frontiere": frontiere.get(aid, False), "message": msg}
            if nom in classes and nom not in recl:
                e.update(type=classes[nom], source="déjà classé")
                echecs.append(e)
                continue
            if nom in lacunes_par_test:
                l = lacunes_par_test[nom]
                e.update(type="trou", source="test « trou » du red")
                pres = l.get("présumé", "")
                if pres and nom not in classes:
                    nid = f"N{len(nouvelles) + 1:02d}"
                    nouvelles[nid] = pres
                    e["nouvelle_assertion"] = nid
                    decisions.append(f"- {nom} : trou, la spec gagne {nid} : {pres} (le test reste exigé).")
            elif nom in recl:
                c = recl[nom]
                rj, tj = appel("judge", JUGE.format(reclamation=c["texte"], assertions=spec(),
                                                    test=source_test(travail, nom), resultat=msg or "échec"),
                               a.juge, "Write", travail, delai=900)
                t_juge = additionner(t_juge, tj)
                txt = str(rj.get("result", ""))
                v = re.search(r"VERDICT:\s*(maintenue|rejetée|rejetee|non tranchable)", txt)
                v = v.group(1) if v else "non tranchable"
                na = re.search(r"NOUVELLE_ASSERTION:\s*(.+)", txt)
                na = na.group(1).strip() if na else "aucune"
                (sortie / "verdicts").mkdir(exist_ok=True)
                (sortie / "verdicts" / f"tour{tour:02d}-{nom}.md").write_text(c["texte"] + "\n\n---\n\n" + txt, encoding="utf-8")
                if v == "maintenue" and c["kind"] == "contradiction":
                    e.update(type="contradiction", source="juge")
                    ecartes.add(nom)
                    decisions.append(f"- {nom} : contradiction reconnue, le test est écarté.")
                elif v in ("rejetée", "rejetee"):
                    e.update(type="bug", source="juge : réclamation rejetée")
                    decisions.append(f"- {nom} : réclamation rejetée, le test reste exigé.")
                else:
                    e.update(type="trou", source=f"juge : {v}")
                    if na.lower() != "aucune":
                        nid = f"N{len(nouvelles) + 1:02d}"
                        nouvelles[nid] = na
                        e["nouvelle_assertion"] = nid
                    decisions.append(f"- {nom} : trou reconnu, le test reste exigé ; la spec gagne : {na}")
            else:
                e.update(type="bug", source="pas de réclamation")
            if aid and bascules.get(aid, 0) >= 2 and e["type"] == "bug":
                e.update(type="contradiction", source="alternance passe/casse")
            classes.setdefault(nom, e["type"])
            if e["type"] == "contradiction":
                classes[nom] = "contradiction"
            echecs.append(e)

        tout_passe = bool(res) and all(ok for n, (ok, _) in res.items() if n not in ecartes)
        ligne = {
            "tour": tour,
            "attaque": attaques,
            "statut": {aid: ("passe" if ok else "casse") for aid, ok in sorted(par_a.items())},
            "tests": {"total": len(res), "passent": sum(ok for ok, _ in res.values()), "ecartes": len(ecartes)},
            "tokens_decoupe": additionner(t_decoupe, t_juge),
            "tokens_execution": t_green,
            "echecs": echecs,
            "reclamations": len(recl),
            "violation_tests": viole,
            "green_erreur": bool(r.get("is_error")),
        }
        journal.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        journal.flush()
        print(f"{a.sonde} tour {tour} (attaque {attaques}) : {ligne['tests']['passent']}/{len(res)} tests, "
              f"{sum(1 for v in ligne['statut'].values() if v == 'passe')}/{len(ligne['statut'])} assertions, "
              f"échecs {dict((t, sum(1 for e in echecs if e['type'] == t)) for t in ('bug', 'trou', 'contradiction'))}",
              flush=True)
        statut_txt = "\n".join(f"- {n} : {'passe' if ok else 'casse'}" for n, (ok, _) in sorted(res.items()))
        if attaques < a.attaques and (tout_passe or tour >= a.tour_attaque_2):
            attaques += 1
            t_attaque = attaquer(attaques, statut_txt)
            sceau = empreinte(travail)
            resultats_txt = ("Le red a ajouté des tests (tests/test_app_2.py). Échecs à la fin du tour précédent :\n"
                             + "\n".join(f"- {n} : {m}" for n, (ok, m) in sorted(res.items()) if not ok and n not in ecartes))
            continue
        if tout_passe:
            convergent = True
            break
        resultats_txt = "Résultats de l'exécution des tests à la fin du tour précédent (échecs seulement) :\n" + "\n".join(
            f"- {nom} : {msg}" for nom, (ok, msg) in sorted(res.items()) if not ok and nom not in ecartes)

    for f in ("app.py",):
        if (travail / f).exists():
            shutil.copy(travail / f, sortie / f)
    if any((travail / "reclamations").iterdir()):
        shutil.copytree(travail / "reclamations", sortie / "reclamations")

    # champ local : tours cassés + 1 si l'assertion a fini par passer
    essais = {aid: casses.get(aid, 0) + (1 if passee.get(aid) else 0) for aid in set(casses) | set(passee) if aid in assertions}
    non_passees = sorted(aid for aid in essais if not passee.get(aid))

    def moyenne(ids):
        v = [essais[i] for i in ids if i in essais]
        return round(sum(v) / len(v), 2) if v else None

    fr_ids = [i for i in assertions if frontiere.get(i)]
    autres = [i for i in assertions if not frontiere.get(i)]
    types = {}
    for t in classes.values():
        types[t] = types.get(t, 0) + 1
    fin = {"sonde": a.sonde, "passes": a.passes, "passe": a.passe, "k_passes": [round(x, 2) for x in ks],
           "k_retenu": round(k, 2) if k else None, "concordance": statut_conc, "convergent": convergent,
           "tours": tour, "attaques": attaques, "assertions": len(assertions), "frontieres": len(fr_ids),
           "champ_local": {"tout": moyenne(list(assertions)), "frontiere": moyenne(fr_ids), "autres": moyenne(autres)},
           "essais": dict(sorted(essais.items())), "non_passees": non_passees,
           "trous_a_priori": len(trous_a_priori), "echecs_par_type": types,
           "nouvelles_assertions": nouvelles, "lacunes": trous_a_priori,
           "modeles": {"red": a.red, "green": a.green, "juge": a.juge}}
    tok = lambda cle: additionner(*[json.loads(l)[cle] for l in (sortie / "journal.jsonl").read_text(encoding="utf-8").splitlines()])
    fin["tokens_decoupe"], fin["tokens_execution"] = tok("tokens_decoupe"), tok("tokens_execution")
    fin["part_decoupe"] = round(fin["tokens_decoupe"]["neufs"] / max(1, fin["tokens_decoupe"]["neufs"] + fin["tokens_execution"]["neufs"]), 3)
    (sortie / "bilan.json").write_text(json.dumps(fin, ensure_ascii=False, indent=1), encoding="utf-8")
    from causes import recalculer  # champ local par cause (duel V2)
    _, c = recalculer(sortie)
    fin["causes"] = {k: v for k, v in c.items() if k != "liste"}
    print(json.dumps({k: v for k, v in fin.items() if k not in ("lacunes", "essais")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
