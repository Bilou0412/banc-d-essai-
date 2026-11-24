"""Générateur de RC synthétiques (V5, sonde P12) : un règlement de la consultation tiré par graine.

    from generateur import generer
    rc = generer(17)      # {"graine", "pages": [str, ...], "verite": {...}, "traits": [...]}

    python outils/v5/generateur.py 17            # affiche le RC 17
    python outils/v5/generateur.py --stats 295   # fréquence des traits sur 295 graines

Le texte imite un RC de marché de travaux français : page de garde, articles numérotés, listes,
phrases tirées parmi plusieurs tournures, dates écrites de plusieurs façons, articles de remplissage,
coupure en pages par longueur (une liste peut passer sur la page suivante).

Ce que le tirage fait varier (les « traits ») :
  critères en %, en points ou seulement classés ; sous-critères (en points sous un critère en %,
  en %, ou sans poids) ; critères différents selon le lot ; poids qui ne totalisent pas ;
  pièces à remettre sur plusieurs pages ; limites de pages du mémoire ; RC qui se contredit
  (deux dates limites, ou « lot unique » puis plusieurs lots) ; visite obligatoire, facultative ou absente ;
  date limite des questions absente ; variantes interdites, autorisées ou non dites ; validité absente.

`verite` sert à H23 seulement (justesse de NuExtract et de sonnet, fait par fait). Les greens de la
boucle ne la voient jamais : la boucle compare les codes entre eux.
Les noms de communes, d'acheteurs et de personnes sont inventés. Aucune pièce réelle.
"""
import json
import random
import sys
from datetime import date, timedelta

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
COMMUNES = ["Valmorin", "Saint-Aubert-sur-Loue", "Montcressac", "Brévaux", "Lavergne-les-Pins", "Corbelin",
            "Haute-Rive", "Sarlanges", "Pont-de-Méry", "Villefranche-d'Orsan", "Estrées-la-Haute", "Marsolle"]
ACHETEURS = ["Commune de {c}", "Communauté de communes du Pays de {c}", "Syndicat intercommunal des eaux de {c}",
             "Département de la Haute-{c}", "Office public de l'habitat de {c}", "Centre hospitalier de {c}"]
OBJETS = [
    ("Réhabilitation de l'école élémentaire", ["Démolition - Gros œuvre", "Charpente - Couverture", "Menuiseries extérieures",
                                                "Plâtrerie - Isolation", "Électricité", "Plomberie - Chauffage", "Peinture"]),
    ("Construction d'un gymnase", ["Terrassement - VRD", "Gros œuvre", "Charpente métallique", "Étanchéité",
                                   "Menuiseries intérieures", "Sols sportifs", "Chauffage - Ventilation"]),
    ("Aménagement de la place du marché", ["Voirie - Réseaux", "Espaces verts", "Éclairage public", "Mobilier urbain"]),
    ("Restauration de l'église Saint-Martin", ["Maçonnerie - Pierre de taille", "Charpente", "Couverture", "Vitraux"]),
    ("Rénovation énergétique de la mairie", ["Isolation thermique par l'extérieur", "Menuiseries", "Chauffage", "Électricité"]),
    ("Réfection de la voirie communale", ["Chaussées", "Signalisation"]),
    ("Extension du groupe scolaire", ["Gros œuvre", "Charpente bois", "Couverture - Zinguerie", "Cloisons - Doublages",
                                      "Carrelage - Faïence", "Électricité - Courants faibles"]),
]
PLATEFORMES = [("la plateforme de dématérialisation https://www.marches-{s}.fr", "https://www.marches-{s}.fr"),
               ("le profil d'acheteur https://achats.{s}-public.fr", "https://achats.{s}-public.fr"),
               ("la plateforme AWS-Achat (https://www.marches-publics.info)", "https://www.marches-publics.info"),
               ("le site https://www.e-marchespublics.com", "https://www.e-marchespublics.com"),
               ("la plateforme PLACE (https://www.marches-publics.gouv.fr)", "https://www.marches-publics.gouv.fr")]
PROCEDURES = {
    "procedure_adaptee": ["procédure adaptée en application des articles L2123-1 et R2123-1 du Code de la commande publique",
                          "procédure adaptée (MAPA)", "procédure adaptée ouverte"],
    "appel_offres_ouvert": ["appel d'offres ouvert en application des articles R2124-1 et R2161-2 à R2161-5 du Code de la commande publique",
                            "appel d'offres ouvert"],
    "appel_offres_restreint": ["appel d'offres restreint en application des articles R2161-6 à R2161-11 du Code de la commande publique"],
    "procedure_negociee": ["procédure avec négociation en application de l'article R2124-3 du Code de la commande publique"],
}
CRITERES_TECH = ["Valeur technique", "Valeur technique de l'offre", "Qualité technique de l'offre", "Mérite technique"]
CRITERES_PRIX = ["Prix", "Prix des prestations", "Prix de l'offre", "Coût"]
AUTRES_CRITERES = ["Délai d'exécution", "Performances en matière de protection de l'environnement", "Planning prévisionnel",
                   "Performances en matière d'insertion professionnelle"]
SOUS_TECH = ["Méthodologie et organisation du chantier", "Moyens humains affectés au chantier",
             "Moyens matériels affectés au chantier", "Planning détaillé des travaux",
             "Mesures prises en matière d'hygiène et de sécurité", "Gestion des déchets de chantier",
             "Provenance et qualité des matériaux proposés", "Mesures de réduction des nuisances pour les riverains"]
PIECES_CANDIDATURE = ["Lettre de candidature (formulaire DC1) ou DUME", "Déclaration du candidat (formulaire DC2)",
                      "Attestation d'assurance de responsabilité civile professionnelle et décennale en cours de validité",
                      "Liste des travaux exécutés au cours des cinq dernières années",
                      "Certificats de qualification professionnelle (Qualibat ou équivalent)",
                      "Déclaration indiquant les effectifs moyens annuels du candidat",
                      "Pouvoir de la personne habilitée à engager le candidat"]
PIECES_OFFRE = ["Acte d'engagement (AE) complété et signé", "Décomposition du prix global et forfaitaire (DPGF)",
                "Bordereau des prix unitaires (BPU)", "Détail quantitatif estimatif (DQE)", "Mémoire technique",
                "Planning prévisionnel d'exécution", "Attestation de visite", "Cadre de réponse technique complété"]
PIECES_ATTRIBUTAIRE = ["Attestations de régularité fiscale et sociale", "Extrait Kbis de moins de trois mois",
                       "Attestation URSSAF de vigilance de moins de six mois", "Liste nominative des salariés étrangers"]
REMPLISSAGE = [
    ("Dispositions générales", "Le présent règlement de la consultation s'applique à la consultation décrite ci-dessus. "
     "Il précise les conditions dans lesquelles les candidats sont invités à présenter leur offre. Les candidats sont "
     "réputés avoir pris connaissance de l'ensemble des pièces du dossier de consultation des entreprises avant de remettre leur offre."),
    ("Modifications de détail au dossier de consultation", "Le maître d'ouvrage se réserve le droit d'apporter au plus tard "
     "dix jours avant la date limite fixée pour la réception des offres des modifications de détail au dossier de consultation. "
     "Les candidats devront alors répondre sur la base du dossier modifié sans pouvoir élever aucune réclamation à ce sujet."),
    ("Négociation", "Le pouvoir adjudicateur se réserve la possibilité de négocier avec les candidats ayant présenté une offre. "
     "Il peut également attribuer le marché sur la base des offres initiales, sans négociation."),
    ("Offres anormalement basses", "Toute offre paraissant anormalement basse fera l'objet d'une demande de précisions. "
     "Après vérification des justificatifs fournis par le candidat, l'offre pourra être rejetée par décision motivée."),
    ("Confidentialité et données personnelles", "Les informations transmises par les candidats sont traitées dans le respect "
     "du secret des affaires. Les données à caractère personnel recueillies sont utilisées aux seules fins de la passation du marché."),
    ("Délais d'exécution", "Le délai d'exécution des travaux est fixé dans l'acte d'engagement. Il court à compter de la date "
     "fixée par l'ordre de service prescrivant le démarrage des travaux. Une période de préparation d'un mois est prévue."),
    ("Recours", "Le tribunal administratif territorialement compétent peut être saisi d'un référé précontractuel avant la "
     "signature du marché, ou d'un recours en contestation de validité dans un délai de deux mois à compter de la publicité de l'attribution."),
    ("Sous-traitance", "Le titulaire peut sous-traiter l'exécution de certaines parties de son marché, sous réserve de "
     "l'acceptation du sous-traitant et de l'agrément de ses conditions de paiement par le maître d'ouvrage."),
]


# ── écriture des dates ────────────────────────────────────────────────────

def ecrire_date(rng, d):
    f = rng.randrange(4)
    if f == 0:
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    if f == 1:
        return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]} {d.year}"
    if f == 2:
        return f"{JOURS[d.weekday()]} {'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]} {d.year}"
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def ecrire_heure(rng, h, m):
    f = rng.randrange(3)
    if f == 0:
        return f"{h}h{m:02d}"
    if f == 1:
        return f"{h:02d}:{m:02d}"
    return f"{h} heures" if m == 0 else f"{h} h {m:02d}"


def un_jour(rng, base, mini, maxi):
    d = base + timedelta(days=rng.randint(mini, maxi))
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ── le tirage ─────────────────────────────────────────────────────────────

def tirer(rng):
    t = {}
    commune = rng.choice(COMMUNES)
    t["acheteur"] = rng.choice(ACHETEURS).format(c=commune)
    objet, corps = rng.choice(OBJETS)
    t["objet"] = f"{objet} de {commune}"
    t["reference"] = f"{rng.randint(2025, 2026)}-{rng.choice(['TX', 'MAPA', 'AO', 'T'])}-{rng.randint(1, 99):02d}"
    t["procedure"] = rng.choices(list(PROCEDURES), weights=[6, 3, 1, 1])[0]
    nlots = rng.choices([1, 2, 3, 4, 5, 7], weights=[5, 2, 2, 2, 1, 1])[0]
    nlots = min(nlots, len(corps))
    t["lots"] = [None] if nlots == 1 else [(f"{i + 1:02d}" if rng.random() < 0.5 else str(i + 1), corps[i]) for i in range(nlots)]
    if nlots == 1:
        t["lot_unique_titre"] = None
    base = date(2026, rng.randint(1, 10), rng.randint(1, 28))
    t["publication"] = base
    dl = un_jour(rng, base, 25, 45)
    t["date_limite"] = (dl, rng.choice([(12, 0), (12, 0), (11, 0), (16, 0), (17, 30), (10, 0)]))
    t["questions"] = None if rng.random() < 0.25 else (dl - timedelta(days=rng.choice([6, 8, 10, 10, 15])), rng.choice([None, (12, 0), (17, 0)]))
    v = rng.random()
    if v < 0.3:
        t["visite"] = ("obligatoire", sorted({un_jour(rng, base, 5, 20) for _ in range(rng.randint(1, 3))}))
    elif v < 0.6:
        t["visite"] = ("facultative", sorted({un_jour(rng, base, 5, 20) for _ in range(rng.randint(0, 2))}))
    else:
        t["visite"] = None
    t["variantes"] = rng.choices([False, True, None], weights=[5, 2, 2])[0]
    t["validite"] = rng.choices([(120, "days"), (90, "days"), (180, "days"), (6, "months"), (4, "months"), None],
                                weights=[5, 2, 1, 1, 1, 2])[0]
    t["plateforme"] = rng.choice(PLATEFORMES)
    t["plateforme"] = (t["plateforme"][0].format(s=commune.lower().replace(" ", "").replace("'", "")[:8]),
                       t["plateforme"][1].format(s=commune.lower().replace(" ", "").replace("'", "")[:8]))

    # critères
    mode = rng.choices(["pourcent", "points", "classes"], weights=[6, 3, 1])[0]
    t["mode_criteres"] = mode
    t["par_lot"] = nlots > 1 and mode != "classes" and rng.random() < 0.3
    groupes = []
    if t["par_lot"]:
        coupe = rng.randint(1, nlots - 1)
        groupes = [[l[0] for l in t["lots"][:coupe]], [l[0] for l in t["lots"][coupe:]]]
    else:
        groupes = [None]
    t["criteres"] = []
    for gi, g in enumerate(groupes):
        t["criteres"].append((g, tirer_criteres(rng, mode, decal=gi)))
    t["poids_faux"] = False
    if mode != "classes" and rng.random() < 0.12:
        # un poids qui ne totalise pas : on gonfle le dernier critère du premier groupe
        crit = t["criteres"][0][1]
        crit[-1]["poids"] += rng.choice([5, 10])
        t["poids_faux"] = True

    # pièces
    cand = rng.sample(PIECES_CANDIDATURE, rng.randint(2, 6))
    offre = ["Acte d'engagement (AE) complété et signé"] + rng.sample(PIECES_OFFRE[1:], rng.randint(1, 5))
    if t["visite"] and t["visite"][0] == "obligatoire" and "Attestation de visite" not in offre:
        offre.append("Attestation de visite")
    if "Mémoire technique" not in offre:
        offre.append("Mémoire technique")
    attrib = rng.sample(PIECES_ATTRIBUTAIRE, rng.randint(0, 3))
    t["pieces"] = ([(p, "candidature", rng.random() < 0.9) for p in cand] + [(p, "offre", True) for p in offre]
                   + [(p, "attributaire", True) for p in attrib])
    t["pieces_facultatives_dites"] = rng.random() < 0.3
    t["limite_pages"] = None if rng.random() < 0.5 else rng.choice([10, 15, 20, 25, 30])
    t["limite_par_sous"] = t["limite_pages"] is not None and rng.random() < 0.25
    # contradictions
    c = rng.random()
    t["contradiction"] = None
    if c < 0.08:
        autre = t["date_limite"][0] + timedelta(days=rng.choice([-7, 7, 3]))
        t["contradiction"] = ("date_limite", autre)
    elif c < 0.13 and nlots == 1:
        t["contradiction"] = ("lots", None)
    return t


def tirer_criteres(rng, mode, decal=0):
    n = rng.choices([2, 3, 4], weights=[4, 4, 1])[0]
    tech, prix = rng.choice(CRITERES_TECH), rng.choice(CRITERES_PRIX)
    noms = [tech, prix] + rng.sample(AUTRES_CRITERES, n - 2)
    if rng.random() < 0.4:
        noms[0], noms[1] = noms[1], noms[0]
    total = 100 if mode != "points" else rng.choice([100, 20, 10, 60])
    parts = {2: [[60, 40], [40, 60], [50, 50], [70, 30]], 3: [[50, 40, 10], [40, 50, 10], [55, 35, 10], [60, 30, 10]],
             4: [[40, 40, 10, 10], [45, 35, 10, 10]]}[n]
    p = rng.choice(parts)
    if decal:
        p = list(reversed(p)) if n == 2 else p
    crit = []
    for nom, pc in zip(noms, p):
        poids = pc * total // 100 if mode != "classes" else None
        c = {"nom": nom, "poids": poids, "unite": "points" if mode == "points" else ("percent" if mode == "pourcent" else None),
             "sous": []}
        if nom in CRITERES_TECH and rng.random() < 0.65:
            k = rng.randint(2, 4)
            sous = rng.sample(SOUS_TECH, k)
            sm = rng.choices(["points", "percent", "aucun"], weights=[4, 3, 2])[0] if mode != "classes" else "aucun"
            if sm == "points":
                base_pts = poids if mode == "points" else pc
                rep = repartir(rng, base_pts, k)
                c["sous"] = [{"nom": s, "poids": r, "unite": "points"} for s, r in zip(sous, rep)]
            elif sm == "percent":
                rep = repartir(rng, 100, k)
                c["sous"] = [{"nom": s, "poids": r, "unite": "percent"} for s, r in zip(sous, rep)]
            else:
                c["sous"] = [{"nom": s, "poids": None, "unite": None} for s in sous]
        crit.append(c)
    return crit


def repartir(rng, total, k):
    if total < k:
        return [1] * k
    coupe = sorted(rng.sample(range(1, total), k - 1))
    r = [b - a for a, b in zip([0] + coupe, coupe + [total])]
    # des parts rondes quand c'est possible
    if total % (5 * k) == 0 and rng.random() < 0.6:
        r = [total // k] * k
    return r


# ── l'écriture ────────────────────────────────────────────────────────────

def poids_txt(rng, c):
    if c["poids"] is None:
        return ""
    if c["unite"] == "percent":
        return rng.choice([f"{c['poids']} %", f"{c['poids']}%", f"pondération : {c['poids']} %"])
    return rng.choice([f"{c['poids']} points", f"noté sur {c['poids']} points", f"{c['poids']} pts"])


def ecrire_criteres(rng, t, lignes):
    for groupe, crit in t["criteres"]:
        if groupe is not None:
            lignes.append(f"Pour les lots n° {', '.join(groupe)} :" if len(groupe) > 1 else f"Pour le lot n° {groupe[0]} :")
        if t["mode_criteres"] == "classes":
            lignes.append("Les critères sont classés par ordre décroissant d'importance :")
            for i, c in enumerate(crit, 1):
                lignes.append(f"  {i}. {c['nom']}")
                for s in c["sous"]:
                    lignes.append(f"     - {s['nom']}")
            continue
        forme = rng.randrange(2)
        if forme == 0:
            lignes.append("Critères | Pondération")
            for i, c in enumerate(crit, 1):
                lignes.append(f"{i}. {c['nom']} | {poids_txt(rng, c)}")
                for s in c["sous"]:
                    lignes.append(f"   - {s['nom']} | {poids_txt(rng, s)}" if s["poids"] is not None else f"   - {s['nom']}")
        else:
            for i, c in enumerate(crit, 1):
                lignes.append(f"Critère n° {i} : {c['nom']} ({poids_txt(rng, c)})")
                if c["sous"]:
                    lignes.append("  Ce critère sera apprécié au regard des éléments suivants :")
                    for s in c["sous"]:
                        lignes.append(f"  • {s['nom']}" + (f" : {poids_txt(rng, s)}" if s["poids"] is not None else ""))
        lignes.append("")


def ecrire(rng, t):
    """Le RC en articles (liste de blocs de texte), avant la coupure en pages."""
    art = []
    n = [0]

    def article(titre, lignes):
        n[0] += 1
        art.append([f"ARTICLE {n[0]} – {titre.upper()}" if rng.random() < 0.5 else f"Article {n[0]} : {titre}", ""] + lignes + [""])

    garde = [t["acheteur"].upper(), "", "MARCHÉ PUBLIC DE TRAVAUX", "", "RÈGLEMENT DE LA CONSULTATION (R.C.)", "",
             f"Objet : {t['objet']}", f"Référence : {t['reference']}", ""]
    dl, (h, m) = t["date_limite"]
    garde.append(f"Date et heure limites de réception des offres : {ecrire_date(rng, dl)} à {ecrire_heure(rng, h, m)}")
    garde.append("")
    art.append(garde)

    # objet et lots
    lignes = [f"La présente consultation concerne : {t['objet']}."]
    if t["lots"] == [None]:
        lignes.append(rng.choice(["Le marché n'est pas alloti : il fait l'objet d'un lot unique.",
                                  "Les travaux sont traités en lot unique.",
                                  "Le marché est passé en un lot unique, l'allotissement n'étant pas pertinent pour cette opération."]))
        if t["contradiction"] and t["contradiction"][0] == "lots":
            lignes.append("")
            lignes.append("Les candidats peuvent présenter une offre pour l'un ou les deux lots suivants :")
            lignes.append("  Lot 1 : Travaux principaux")
            lignes.append("  Lot 2 : Travaux annexes")
    else:
        lignes.append(f"Les travaux sont répartis en {len(t['lots'])} lots :")
        for num, titre in t["lots"]:
            lignes.append(rng.choice([f"  Lot n° {num} : {titre}", f"  Lot {num} – {titre}", f"  - Lot {num} : {titre}"]))
        lignes.append("Les candidats peuvent présenter une offre pour un ou plusieurs lots.")
    article("Objet de la consultation", lignes)

    article("Procédure", [f"La présente consultation est passée selon la {rng.choice(PROCEDURES[t['procedure']])}."])

    for titre, txt in rng.sample(REMPLISSAGE, rng.randint(1, 3)):
        article(titre, [txt])

    # variantes et validité
    lignes = []
    if t["variantes"] is True:
        lignes.append(rng.choice(["Les variantes sont autorisées.", "Les candidats peuvent présenter des variantes à l'initiative du candidat.",
                                  "Les variantes sont admises, sous réserve de répondre également à la solution de base."]))
    elif t["variantes"] is False:
        lignes.append(rng.choice(["Les variantes ne sont pas autorisées.", "Aucune variante n'est admise.",
                                  "Les variantes à l'initiative du candidat sont interdites."]))
    if t["validite"]:
        a, u = t["validite"]
        mot = "jours" if u == "days" else "mois"
        lignes.append(rng.choice([f"Le délai de validité des offres est fixé à {a} {mot} à compter de la date limite de réception des offres.",
                                  f"Les offres restent valables pendant {a} {mot} à compter de la date limite de remise.",
                                  f"Délai de validité des offres : {a} {mot}."]))
    if lignes:
        article(rng.choice(["Variantes et validité des offres", "Dispositions relatives aux offres"]), lignes)

    # visite
    if t["visite"]:
        nature, dates = t["visite"]
        lignes = []
        if nature == "obligatoire":
            lignes.append(rng.choice(["Une visite du site est obligatoire. Toute offre remise sans attestation de visite sera déclarée irrégulière.",
                                      "La visite des lieux est obligatoire pour pouvoir remettre une offre."]))
        else:
            lignes.append(rng.choice(["Une visite du site est conseillée mais n'est pas obligatoire.",
                                      "La visite des lieux est facultative."]))
        if dates:
            lignes.append("Elle aura lieu " + (f"le {ecrire_date(rng, dates[0])} à {ecrire_heure(rng, 10, 0)}" if len(dates) == 1 else
                                              "aux dates suivantes : " + ", ".join(ecrire_date(rng, d) for d in dates)) + ".")
            lignes.append(f"Les candidats prennent rendez-vous auprès des services techniques au 01 23 45 {rng.randint(10, 99)} {rng.randint(10, 99)}.")
        article(rng.choice(["Visite du site", "Visite des lieux"]), lignes)

    # contenu des offres
    lignes = ["Les candidats remettent un dossier comprenant les pièces suivantes, datées et signées :", ""]
    lignes.append(rng.choice(["Pièces de la candidature :", "1) Au titre de la candidature :"]))
    for p, part, oblig in [x for x in t["pieces"] if x[1] == "candidature"]:
        suffixe = " (facultatif)" if (not oblig and t["pieces_facultatives_dites"]) else ""
        lignes.append(f"  - {p}{suffixe}")
    lignes.append("")
    lignes.append(rng.choice(["Pièces de l'offre :", "2) Au titre de l'offre :"]))
    for p, part, oblig in [x for x in t["pieces"] if x[1] == "offre"]:
        ligne = f"  - {p}"
        if p == "Mémoire technique" and t["limite_pages"]:
            ligne += rng.choice([f", limité à {t['limite_pages']} pages", f" ({t['limite_pages']} pages maximum, annexes non comprises)",
                                 f" de {t['limite_pages']} pages au plus"])
        lignes.append(ligne)
    if t["limite_par_sous"]:
        lignes.append(f"  Chaque partie du mémoire technique ne dépassera pas {max(2, t['limite_pages'] // 4)} pages.")
    attrib = [x for x in t["pieces"] if x[1] == "attributaire"]
    if attrib:
        lignes.append("")
        lignes.append("Le candidat auquel il est envisagé d'attribuer le marché produira dans un délai de 8 jours :")
        for p, _, _ in attrib:
            lignes.append(f"  - {p}")
    article(rng.choice(["Présentation des candidatures et des offres", "Contenu du dossier à remettre"]), lignes)

    # critères
    lignes = [rng.choice(["Le jugement des offres sera effectué selon les critères pondérés suivants :",
                          "L'offre économiquement la plus avantageuse sera appréciée en fonction des critères suivants :"]), ""]
    if t["mode_criteres"] == "classes":
        lignes[0] = "L'offre économiquement la plus avantageuse sera appréciée en fonction des critères énoncés ci-dessous."
    ecrire_criteres(rng, t, lignes)
    if t["mode_criteres"] == "points":
        lignes.append("La note finale est la somme des notes obtenues pour chaque critère.")
    article(rng.choice(["Jugement des offres", "Critères d'attribution", "Sélection des candidatures et jugement des offres"]), lignes)

    # remise
    lignes = [rng.choice([f"Les offres sont transmises par voie électronique sur {t['plateforme'][0]}.",
                          f"La remise des plis se fait exclusivement par voie dématérialisée, sur {t['plateforme'][0]}."]),
              "Aucune offre papier ne sera acceptée."]
    dl2 = t["contradiction"][1] if t["contradiction"] and t["contradiction"][0] == "date_limite" else dl
    lignes.append(f"Les plis doivent parvenir avant le {ecrire_date(rng, dl2)} à {ecrire_heure(rng, h, m)}.")
    article(rng.choice(["Conditions d'envoi et de remise des offres", "Modalités de remise des plis"]), lignes)

    # questions
    if t["questions"]:
        dq, hq = t["questions"]
        q = f"Les candidats peuvent poser leurs questions par écrit sur la plateforme au plus tard le {ecrire_date(rng, dq)}"
        q += f" à {ecrire_heure(rng, *hq)}." if hq else "."
        article(rng.choice(["Renseignements complémentaires", "Questions des candidats"]), [q, "Une réponse sera communiquée à tous les candidats."])
    for titre, txt in rng.sample(REMPLISSAGE, rng.randint(0, 2)):
        article(titre, [txt])
    return art


def paginer(rng, articles):
    taille = rng.choice([1800, 2300, 2800])
    pages, cour = [], []
    for bloc in articles:
        for ligne in bloc:
            cour.append(ligne)
            if sum(len(x) + 1 for x in cour) > taille:
                pages.append(cour)
                cour = []
    if cour:
        pages.append(cour)
    return [f"\n".join(p) + f"\n\nRC – {i + 1}/{len(pages)}\n" for i, p in enumerate(pages)]


# ── la vérité (pour H23) ──────────────────────────────────────────────────

def verite(t):
    dl, (h, m) = t["date_limite"]
    v = {}
    if t["contradiction"] and t["contradiction"][0] == "date_limite":
        v["offer_deadline"] = {"statut": "conflict", "valeurs": sorted([{"date": dl.isoformat(), "time": f"{h:02d}:{m:02d}"},
                                                                         {"date": t["contradiction"][1].isoformat(), "time": f"{h:02d}:{m:02d}"}],
                                                                        key=lambda x: x["date"])}
    else:
        v["offer_deadline"] = {"statut": "found", "valeurs": [{"date": dl.isoformat(), "time": f"{h:02d}:{m:02d}"}]}
    if t["questions"]:
        dq, hq = t["questions"]
        v["questions_deadline"] = {"statut": "found", "valeurs": [{"date": dq.isoformat(), "time": f"{hq[0]:02d}:{hq[1]:02d}" if hq else None}]}
    else:
        v["questions_deadline"] = {"statut": "not_found", "valeurs": []}
    v["procedure"] = {"statut": "found", "valeurs": [t["procedure"]]}
    if t["lots"] == [None]:
        lots = [{"number": None}]
        if t["contradiction"] and t["contradiction"][0] == "lots":
            v["lots"] = {"statut": "conflict", "valeurs": lots + [{"number": "1"}, {"number": "2"}]}
        else:
            v["lots"] = {"statut": "found", "valeurs": lots}
    else:
        v["lots"] = {"statut": "found", "valeurs": [{"number": n, "title": ti} for n, ti in t["lots"]]}
    if t["visite"]:
        v["site_visit"] = {"statut": "found", "valeurs": [t["visite"][0] == "obligatoire"]}
        v["site_visit_dates"] = ({"statut": "found", "valeurs": [d.isoformat() for d in t["visite"][1]]} if t["visite"][1]
                                 else {"statut": "not_found", "valeurs": []})
    else:
        v["site_visit"] = {"statut": "not_found", "valeurs": []}
        v["site_visit_dates"] = {"statut": "not_found", "valeurs": []}
    v["submission_mode"] = {"statut": "found", "valeurs": [t["plateforme"][1]]}
    v["offer_validity"] = ({"statut": "found", "valeurs": [{"amount": t["validite"][0], "unit": t["validite"][1]}]} if t["validite"]
                           else {"statut": "not_found", "valeurs": []})
    v["variants"] = {"statut": "found", "valeurs": [t["variantes"]]} if t["variantes"] is not None else {"statut": "not_found", "valeurs": []}
    crit = []
    for groupe, cs in t["criteres"]:
        for lot in (groupe or [None]):
            for i, c in enumerate(cs, 1):
                crit.append({"lot": lot, "wording": c["nom"],
                             "weight": {"amount": c["poids"], "unit": c["unite"]} if c["poids"] is not None else None,
                             "rank": i if t["mode_criteres"] == "classes" else None,
                             "sub_criteria": [{"wording": s["nom"], "weight": {"amount": s["poids"], "unit": s["unite"]} if s["poids"] is not None else None}
                                              for s in c["sous"]]})
    v["award_criteria"] = {"statut": "found", "valeurs": crit}
    v["documents_to_return"] = {"statut": "found", "valeurs": [{"wording": p, "part": part} for p, part, _ in t["pieces"]]}
    v["limite_pages"] = t["limite_pages"]
    v["poids_faux"] = t["poids_faux"]
    return v


def traits(t, pages):
    tr = [f"criteres:{t['mode_criteres']}"]
    if any(c["sous"] for _, cs in t["criteres"] for c in cs):
        tr.append("sous-criteres")
    if any(c["unite"] == "percent" and any(s["unite"] == "points" for s in c["sous"]) for _, cs in t["criteres"] for c in cs):
        tr.append("sous-points-sous-pourcent")
    if t["par_lot"]:
        tr.append("criteres-par-lot")
    if t["poids_faux"]:
        tr.append("poids-ne-totalisent-pas")
    if t["limite_pages"]:
        tr.append("limite-pages")
    if t["contradiction"]:
        tr.append(f"contradiction:{t['contradiction'][0]}")
    if len(t["lots"]) > 1:
        tr.append("allotissement")
    if t["visite"]:
        tr.append(f"visite:{t['visite'][0]}")
    if t["questions"] is None:
        tr.append("sans-date-questions")
    piece_pages = [i for i, p in enumerate(pages) if any(x[0] in p for x in t["pieces"])]
    if len(piece_pages) > 1:
        tr.append("pieces-sur-plusieurs-pages")
    return tr


def generer(graine):
    rng = random.Random(graine * 7919 + 12)
    t = tirer(rng)
    pages = paginer(rng, ecrire(rng, t))
    return {"graine": graine, "pages": pages, "verite": verite(t), "traits": traits(t, pages)}


if __name__ == "__main__":
    if sys.argv[1] == "--stats":
        from collections import Counter
        n = int(sys.argv[2])
        c, tailles = Counter(), []
        for g in range(n):
            r = generer(g)
            c.update(r["traits"])
            tailles.append(sum(map(len, r["pages"])))
        for k, v in sorted(c.items()):
            print(f"{k:32s} {v:4d}  ({v / n:.0%})")
        tailles.sort()
        print(f"caractères : médiane {tailles[n // 2]}, max {tailles[-1]}")
    else:
        r = generer(int(sys.argv[1]))
        for i, p in enumerate(r["pages"], 1):
            print(f"──── page {i} ────\n{p}")
        print(json.dumps(r["verite"], ensure_ascii=False, indent=1, default=str))
        print(r["traits"])
