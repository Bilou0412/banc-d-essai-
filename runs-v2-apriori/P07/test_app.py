"""Tests rouges de la sonde P07 — notes hors ligne synchronisées.

Interface publique de `app` fixée par ces tests (le constructeur l'implémente telle quelle) :

    clock = app.Clock()                       # temps simulé, démarre à 0.0
    clock.now() -> float
    clock.advance(seconds)                    # fait avancer le temps ; tous les événements
                                              # (messages réseau, synchronisations) échus
                                              # pendant l'intervalle sont traités dans l'ordre

    net = app.Network(clock, latency=0.2)     # réseau simulé en mémoire ; chaque message met
                                              # `latency` secondes à arriver ; un message en vol
                                              # vers / depuis un appareil déconnecté est perdu
    net.set_connected(device_name, bool)      # coupe / rétablit le réseau d'un appareil (par nom)

    server = app.Server(net)                  # le service distant du compte, joint par le réseau
    server.create_account(user, password)

    store = app.LocalStorage()                # stockage local persistant d'un appareil
    dev = app.Device(name, net, clock, storage=store, clock_offset=0.0)
                                              # lance l'application ; heure de l'appareil =
                                              # clock.now() + clock_offset
    dev.close()                               # ferme l'application ; relancer = nouveau Device
                                              # sur le même `store`
    dev.status() -> "hors ligne" | "en ligne"
    dev.login(user, password)                 # ouvre une session (passe par le réseau)
    dev.logout()                              # ferme la session
    dev.create_note(title, text) -> note_id   # identifiant commun à tous les appareils
    dev.edit_text(note_id, text)
    dev.edit_title(note_id, title)
    dev.delete_note(note_id)
    dev.list_notes() -> list[NoteView]        # ordre d'affichage, la tête en premier
    dev.get_note(note_id) -> NoteView | None
    dev.conflicts() -> list[note_id]          # notes sur lesquelles un conflit est signalé
    dev.resolve_conflict(note_id, keep)       # keep = "origine" | "copie"

    NoteView : .id, .title, .text, .indicator ("en attente" | "synchronisée"),
               .conflict_copy_of (None, ou l'id de la note d'origine pour une copie de conflit)
"""

import app

USER = "alice"
PW = "correct horse"
PENDING = "en attente"
SYNCED = "synchronisée"
OFFLINE = "hors ligne"


# ---------------------------------------------------------------- outils

def settle(clock, seconds=30.0):
    clock.advance(seconds)


def world(names=("A", "B"), latency=0.2, offsets=None):
    offsets = offsets or {}
    clock = app.Clock()
    net = app.Network(clock, latency=latency)
    server = app.Server(net)
    server.create_account(USER, PW)
    devs = []
    stores = {}
    for name in names:
        store = app.LocalStorage()
        stores[name] = store
        d = app.Device(name, net, clock, storage=store,
                       clock_offset=offsets.get(name, 0.0))
        d.login(USER, PW)
        devs.append(d)
    settle(clock)
    return clock, net, server, devs, stores


def shared_note(clock, a, b, title="Courses", text="lait"):
    nid = a.create_note(title, text)
    settle(clock)
    nb = b.get_note(nid)
    assert nb is not None, "préalable : la note créée sur A en ligne devait arriver sur B"
    assert nb.text == text, f"préalable : B devait afficher {text!r}, obtenu {nb.text!r}"
    return nid


def ids(dev):
    return [n.id for n in dev.list_notes()]


def text_of(dev, nid):
    n = dev.get_note(nid)
    assert n is not None, f"la note {nid!r} devait être présente sur {dev!r}"
    return n.text


def copies_of(dev, nid):
    return [n for n in dev.list_notes() if n.conflict_copy_of == nid]


def concurrent_offline_edits(text_a, text_b, b_first=True, offsets=None):
    """A et B modifient la même note hors ligne (A d'abord, B 10 s plus tard),
    puis retrouvent le réseau l'un après l'autre."""
    clock, net, server, (a, b), _ = world(offsets=offsets)
    nid = shared_note(clock, a, b, text="v0")
    net.set_connected("A", False)
    net.set_connected("B", False)
    clock.advance(1)
    a.edit_text(nid, text_a)
    clock.advance(10)
    b.edit_text(nid, text_b)
    clock.advance(1)
    order = ("B", "A") if b_first else ("A", "B")
    for name in order:
        net.set_connected(name, True)
        settle(clock)
    settle(clock)
    return clock, net, a, b, nid


# ---------------------------------------------------------------- A01 / A02

def test_A01_trou_delai_detection():
    clock, net, _, (a, b), _ = world()
    assert a.status() != OFFLINE, f"en ligne, statut attendu différent de {OFFLINE!r}, obtenu {a.status()!r}"
    net.set_connected("A", False)
    clock.advance(5)
    assert a.status() == OFFLINE, f"après perte du réseau, attendu {OFFLINE!r}, obtenu {a.status()!r}"


def test_A01_seul_l_appareil_coupe_est_hors_ligne():
    clock, net, _, (a, b), _ = world()
    net.set_connected("A", False)
    clock.advance(5)
    assert a.status() == OFFLINE
    assert b.status() != OFFLINE, f"B n'a pas perdu le réseau mais affiche {b.status()!r}"


def test_A02_retour_reseau_retire_hors_ligne():
    clock, net, _, (a, b), _ = world()
    net.set_connected("A", False)
    clock.advance(5)
    assert a.status() == OFFLINE
    net.set_connected("A", True)
    clock.advance(5)
    assert a.status() != OFFLINE, f"réseau revenu, statut encore {a.status()!r}"


# ---------------------------------------------------------------- A03–A07 (local hors ligne)

def test_A03_creation_hors_ligne_apparait():
    clock, net, _, (a, b), _ = world()
    net.set_connected("A", False)
    clock.advance(1)
    nid = a.create_note("Idée", "écrire hors ligne")
    assert nid in ids(a), f"note {nid!r} absente de la liste de A : {ids(a)!r}"
    n = a.get_note(nid)
    assert (n.title, n.text) == ("Idée", "écrire hors ligne"), f"obtenu {(n.title, n.text)!r}"


def test_A04_modification_texte_hors_ligne():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "lait, œufs, café")
    assert text_of(a, nid) == "lait, œufs, café", f"obtenu {text_of(a, nid)!r}"


def test_A05_modification_titre_hors_ligne():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_title(nid, "Marché du samedi")
    n = a.get_note(nid)
    assert n.title == "Marché du samedi", f"obtenu {n.title!r}"
    assert n.text == "lait", f"le texte ne devait pas changer, obtenu {n.text!r}"


def test_A06_suppression_hors_ligne():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    other = shared_note(clock, a, b, title="Autre", text="reste")
    net.set_connected("A", False)
    clock.advance(1)
    a.delete_note(nid)
    assert nid not in ids(a), f"note supprimée encore listée : {ids(a)!r}"
    assert a.get_note(nid) is None
    assert other in ids(a), "l'autre note ne devait pas disparaître"


def test_A07_modification_hors_ligne_en_attente():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    assert a.get_note(nid).indicator == SYNCED, "préalable : note synchronisée"
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "nouveau")
    clock.advance(30)
    ind = a.get_note(nid).indicator
    assert ind == PENDING, f"attendu {PENDING!r}, obtenu {ind!r}"


def test_A07_creation_hors_ligne_en_attente():
    clock, net, _, (a, b), _ = world()
    net.set_connected("A", False)
    clock.advance(1)
    nid = a.create_note("t", "x")
    clock.advance(30)
    assert a.get_note(nid).indicator == PENDING, f"obtenu {a.get_note(nid).indicator!r}"


# ---------------------------------------------------------------- A08–A10 (indicateur)

def test_A08_en_ligne_synchronisee_apres_envoi():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    a.edit_text(nid, "modifié en ligne")
    settle(clock)
    ind = a.get_note(nid).indicator
    assert ind == SYNCED, f"attendu {SYNCED!r}, obtenu {ind!r}"


def test_A08_trou_avant_fin_envoi():
    clock, net, _, (a, b), _ = world(latency=2.0)
    nid = shared_note(clock, a, b)
    a.edit_text(nid, "modifié en ligne")
    clock.advance(0.5)
    ind = a.get_note(nid).indicator
    assert ind == PENDING, f"envoi non terminé (latence 2 s, 0,5 s écoulée) : attendu {PENDING!r}, obtenu {ind!r}"
    settle(clock)
    assert a.get_note(nid).indicator == SYNCED


def test_A09_retour_reseau_synchronisee():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "hors ligne")
    assert a.get_note(nid).indicator == PENDING
    net.set_connected("A", True)
    settle(clock)
    ind = a.get_note(nid).indicator
    assert ind == SYNCED, f"attendu {SYNCED!r}, obtenu {ind!r}"


def test_A10_session_fermee_reste_en_attente():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "hors ligne")
    assert a.get_note(nid).indicator == PENDING
    a.logout()
    net.set_connected("A", True)
    settle(clock)
    ind = a.get_note(nid).indicator
    assert ind == PENDING, f"session fermée : attendu {PENDING!r}, obtenu {ind!r}"


# ---------------------------------------------------------------- A11 / A12 (persistance)

def test_A11_reouverture_sans_reseau_texte_modifie():
    clock, net, _, (a, b), stores = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "survit à la fermeture")
    a.close()
    clock.advance(60)
    a2 = app.Device("A", net, clock, storage=stores["A"])
    assert a2.status() == OFFLINE or True  # le statut n'est pas l'objet de ce test
    assert text_of(a2, nid) == "survit à la fermeture", f"obtenu {text_of(a2, nid)!r}"


def test_A12_reouverture_sans_reseau_creation_presente():
    clock, net, _, (a, b), stores = world()
    net.set_connected("A", False)
    clock.advance(1)
    nid = a.create_note("Persistante", "contenu")
    a.close()
    clock.advance(60)
    a2 = app.Device("A", net, clock, storage=stores["A"])
    assert nid in ids(a2), f"note créée hors ligne absente après réouverture : {ids(a2)!r}"
    assert text_of(a2, nid) == "contenu"


def test_A12_reouverture_puis_reseau_la_creation_part_toujours():
    clock, net, _, (a, b), stores = world()
    net.set_connected("A", False)
    clock.advance(1)
    nid = a.create_note("Persistante", "contenu")
    a.close()
    a2 = app.Device("A", net, clock, storage=stores["A"])
    net.set_connected("A", True)
    settle(clock)
    assert nid in ids(b), "la création persistée devait encore partir après réouverture"


# ---------------------------------------------------------------- A13–A19 (propagation)

def test_A13_b_garde_ancien_texte():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "nouveau sur A")
    settle(clock, 120)
    assert text_of(b, nid) == "lait", f"B devait garder 'lait', obtenu {text_of(b, nid)!r}"


def test_A14_texte_propage_vers_b():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "nouveau sur A")
    clock.advance(5)
    net.set_connected("A", True)
    settle(clock, 120)
    assert text_of(b, nid) == "nouveau sur A", f"obtenu {text_of(b, nid)!r}"


def test_A14_trou_delai_propagation():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "nouveau sur A")
    net.set_connected("A", True)
    clock.advance(30)
    assert text_of(b, nid) == "nouveau sur A", f"30 s après le retour du réseau, obtenu {text_of(b, nid)!r}"


def test_A14_rien_ne_passe_sans_temps():
    clock, net, _, (a, b), _ = world(latency=1.0)
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "nouveau sur A")
    net.set_connected("A", True)
    assert text_of(b, nid) == "lait", (
        "sans avancer l'horloge, avec une latence de 1 s, B ne peut pas encore avoir reçu la modification")
    settle(clock)
    assert text_of(b, nid) == "nouveau sur A"


def test_A15_titre_propage_vers_b():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_title(nid, "Titre neuf")
    net.set_connected("A", True)
    settle(clock, 120)
    n = b.get_note(nid)
    assert n.title == "Titre neuf", f"obtenu {n.title!r}"
    assert n.text == "lait", f"le texte ne devait pas changer, obtenu {n.text!r}"


def test_A16_creation_propagee_vers_b():
    clock, net, _, (a, b), _ = world()
    net.set_connected("A", False)
    clock.advance(1)
    nid = a.create_note("Né hors ligne", "contenu ✓")
    settle(clock)
    assert nid not in ids(b)
    net.set_connected("A", True)
    settle(clock, 120)
    assert nid in ids(b), f"note absente de B : {ids(b)!r}"
    n = b.get_note(nid)
    assert (n.title, n.text) == ("Né hors ligne", "contenu ✓"), f"obtenu {(n.title, n.text)!r}"


def test_A17_suppression_propagee_vers_b():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    keep = shared_note(clock, a, b, title="Garde", text="g")
    net.set_connected("A", False)
    clock.advance(1)
    a.delete_note(nid)
    net.set_connected("A", True)
    settle(clock, 120)
    assert nid not in ids(b), f"note supprimée encore sur B : {ids(b)!r}"
    assert keep in ids(b)


def test_A18_creee_puis_supprimee_jamais_sur_b():
    clock, net, _, (a, b), _ = world()
    net.set_connected("A", False)
    clock.advance(1)
    nid = a.create_note("Éphémère", "x")
    clock.advance(1)
    a.delete_note(nid)
    net.set_connected("A", True)
    for step in range(600):
        clock.advance(0.1)
        assert nid not in ids(b), f"la note éphémère est apparue sur B à t={clock.now()}"
    assert nid not in ids(a)


def test_A19_deux_modifications_derniere_gagne():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "première")
    clock.advance(1)
    a.edit_text(nid, "seconde")
    net.set_connected("A", True)
    settle(clock, 120)
    assert text_of(b, nid) == "seconde", f"obtenu {text_of(b, nid)!r}"
    assert text_of(a, nid) == "seconde"


def test_A19_trou_pas_de_conflit_avec_soi_meme():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "première")
    clock.advance(1)
    a.edit_text(nid, "seconde")
    net.set_connected("A", True)
    settle(clock, 120)
    assert a.conflicts() == [] and b.conflicts() == [], (
        f"aucun conflit attendu, obtenu A={a.conflicts()!r} B={b.conflicts()!r}")
    assert copies_of(a, nid) == [] and copies_of(b, nid) == []


# ---------------------------------------------------------------- A20 / A21 (session)

def test_A20_session_fermee_b_garde_ancien():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "secret local")
    a.logout()
    net.set_connected("A", True)
    settle(clock, 120)
    assert text_of(b, nid) == "lait", f"obtenu {text_of(b, nid)!r}"


def test_A20_trou_mauvais_mot_de_passe():
    clock, net, server, (a, b), stores = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "secret local")
    a.logout()
    net.set_connected("A", True)
    settle(clock)
    try:
        a.login(USER, "mauvais")
    except Exception:
        pass
    settle(clock, 120)
    assert text_of(b, nid) == "lait", f"mot de passe faux : B devait garder 'lait', obtenu {text_of(b, nid)!r}"
    assert a.get_note(nid).indicator == PENDING


def test_A21_reouverture_session_propage():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b)
    net.set_connected("A", False)
    clock.advance(1)
    a.edit_text(nid, "après reconnexion")
    a.logout()
    net.set_connected("A", True)
    settle(clock)
    assert text_of(b, nid) == "lait"
    a.login(USER, PW)
    settle(clock, 120)
    assert text_of(b, nid) == "après reconnexion", f"obtenu {text_of(b, nid)!r}"
    assert a.get_note(nid).indicator == SYNCED


# ---------------------------------------------------------------- A22 / A23 (coupure en cours d'envoi)

LONG_TEXT = "".join(f"ligne {i} — données é\n" for i in range(5000))


def test_A22_coupure_pendant_envoi_reste_en_attente():
    clock, net, _, (a, b), _ = world(latency=0.5)
    nid = shared_note(clock, a, b, text="ancien")
    a.edit_text(nid, LONG_TEXT)
    clock.advance(0.2)
    net.set_connected("A", False)
    for _ in range(100):
        clock.advance(0.1)
        ind = a.get_note(nid).indicator
        assert ind == PENDING, f"coupure avant accusé de réception : attendu {PENDING!r}, obtenu {ind!r} à t={clock.now()}"
    assert text_of(a, nid) == LONG_TEXT
    net.set_connected("A", True)
    settle(clock)
    assert a.get_note(nid).indicator == SYNCED


def test_A23_jamais_de_texte_partiel_sur_b():
    clock, net, _, (a, b), _ = world(latency=0.5)
    nid = shared_note(clock, a, b, text="ancien")
    a.edit_text(nid, LONG_TEXT)
    clock.advance(0.2)
    net.set_connected("A", False)
    seen = set()
    for _ in range(50):
        clock.advance(0.1)
        seen.add(text_of(b, nid))
    net.set_connected("A", True)
    for _ in range(600):
        clock.advance(0.1)
        seen.add(text_of(b, nid))
    partial = [t[:40] for t in seen if t not in ("ancien", LONG_TEXT)]
    assert not partial, f"texte partiel observé sur B : {partial!r}"
    assert text_of(b, nid) == LONG_TEXT, f"B devait finir avec le texte complet, longueur {len(text_of(b, nid))}"


# ---------------------------------------------------------------- A24–A31 (conflits)

def test_A24_textes_differents_conflit():
    clock, net, a, b, nid = concurrent_offline_edits("version A", "version B")
    assert nid in a.conflicts() or nid in b.conflicts(), (
        f"conflit attendu sur {nid!r}, obtenu A={a.conflicts()!r} B={b.conflicts()!r}")


def test_A24_trou_conflit_signale_sur_les_deux_appareils():
    clock, net, a, b, nid = concurrent_offline_edits("version A", "version B")
    assert nid in a.conflicts(), f"A : obtenu {a.conflicts()!r}"
    assert nid in b.conflicts(), f"B : obtenu {b.conflicts()!r}"


def test_A24_trou_modifications_successives_pas_de_conflit():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b, text="v0")
    a.edit_text(nid, "v1 par A")
    settle(clock)
    assert text_of(b, nid) == "v1 par A"
    b.edit_text(nid, "v2 par B, après avoir vu v1")
    settle(clock)
    assert a.conflicts() == [] and b.conflicts() == [], (
        f"modifications successives : aucun conflit attendu, A={a.conflicts()!r} B={b.conflicts()!r}")
    assert text_of(a, nid) == "v2 par B, après avoir vu v1"


def test_A25_texte_identique_pas_de_conflit():
    clock, net, a, b, nid = concurrent_offline_edits("même texte", "même texte")
    assert a.conflicts() == [] and b.conflicts() == [], f"A={a.conflicts()!r} B={b.conflicts()!r}"
    assert copies_of(a, nid) == [] and copies_of(b, nid) == []
    assert text_of(a, nid) == "même texte" and text_of(b, nid) == "même texte"


def test_A26_notes_differentes_pas_de_conflit():
    clock, net, _, (a, b), _ = world()
    n1 = shared_note(clock, a, b, title="Un", text="1")
    n2 = shared_note(clock, a, b, title="Deux", text="2")
    net.set_connected("A", False)
    net.set_connected("B", False)
    clock.advance(1)
    a.edit_text(n1, "1 modifié sur A")
    clock.advance(1)
    b.edit_text(n2, "2 modifié sur B")
    net.set_connected("A", True)
    net.set_connected("B", True)
    settle(clock, 120)
    assert a.conflicts() == [] and b.conflicts() == [], f"A={a.conflicts()!r} B={b.conflicts()!r}"
    assert text_of(b, n1) == "1 modifié sur A"
    assert text_of(a, n2) == "2 modifié sur B"


def test_A27_copie_de_conflit_contient_l_autre_version():
    clock, net, a, b, nid = concurrent_offline_edits("version A", "version B")
    original = text_of(a, nid)
    other = "version A" if original == "version B" else "version B"
    copies = copies_of(a, nid)
    assert len(copies) == 1, f"une copie de conflit attendue sur A, obtenu {len(copies)}"
    assert copies[0].text == other, f"copie attendue {other!r}, obtenu {copies[0].text!r}"
    assert copies[0].id != nid


def test_A27_trou_copie_sur_les_deux_appareils():
    clock, net, a, b, nid = concurrent_offline_edits("version A", "version B")
    ca, cb = copies_of(a, nid), copies_of(b, nid)
    assert len(ca) == 1 and len(cb) == 1, f"copies : A={len(ca)} B={len(cb)}"
    assert ca[0].id == cb[0].id and ca[0].text == cb[0].text


def test_A28_derniere_selon_heure_appareil_pas_ordre_arrivee():
    # B modifie 10 s après A mais retrouve le réseau en premier : la dernière arrivée est A.
    clock, net, a, b, nid = concurrent_offline_edits("version A", "version B", b_first=True)
    assert text_of(a, nid) == "version B", f"A : obtenu {text_of(a, nid)!r}"
    assert text_of(b, nid) == "version B", f"B : obtenu {text_of(b, nid)!r}"
    assert [c.text for c in copies_of(a, nid)] == ["version A"]


def test_A28_heure_des_appareils_et_non_heure_globale():
    # L'horloge de B retarde de 1000 s : sa modification, faite plus tard en temps réel,
    # porte une heure d'appareil antérieure à celle de A. A doit l'emporter.
    clock, net, a, b, nid = concurrent_offline_edits(
        "version A", "version B", b_first=False, offsets={"B": -1000.0})
    assert text_of(a, nid) == "version A", f"A : obtenu {text_of(a, nid)!r}"
    assert text_of(b, nid) == "version A", f"B : obtenu {text_of(b, nid)!r}"
    assert [c.text for c in copies_of(b, nid)] == ["version B"]


def test_A29_choix_leve_le_conflit():
    clock, net, a, b, nid = concurrent_offline_edits("version A", "version B")
    assert nid in a.conflicts()
    a.resolve_conflict(nid, "origine")
    assert nid not in a.conflicts(), f"après choix, obtenu {a.conflicts()!r}"
    settle(clock)
    assert nid not in a.conflicts()


def test_A30_choix_propage_vers_b():
    clock, net, a, b, nid = concurrent_offline_edits("version A", "version B")
    assert text_of(a, nid) == "version B"
    a.resolve_conflict(nid, "copie")
    settle(clock, 120)
    assert text_of(a, nid) == "version A", f"A : obtenu {text_of(a, nid)!r}"
    assert text_of(b, nid) == "version A", f"B : obtenu {text_of(b, nid)!r}"


def test_A31_modification_l_emporte_sur_suppression():
    clock, net, _, (a, b), _ = world()
    nid = shared_note(clock, a, b, text="v0")
    net.set_connected("A", False)
    net.set_connected("B", False)
    clock.advance(1)
    a.edit_text(nid, "modifiée sur A")
    clock.advance(5)
    b.delete_note(nid)
    assert nid not in ids(b)
    net.set_connected("B", True)
    settle(clock)
    net.set_connected("A", True)
    settle(clock, 120)
    assert nid in ids(b), f"la note modifiée devait réapparaître sur B : {ids(b)!r}"
    assert text_of(b, nid) == "modifiée sur A"
    assert nid in ids(a) and text_of(a, nid) == "modifiée sur A"


# ---------------------------------------------------------------- A32 / A33 (ordre)

def test_A32_note_modifiee_en_tete():
    clock, net, _, (a, b), _ = world()
    n1 = a.create_note("Un", "1")
    clock.advance(1)
    n2 = a.create_note("Deux", "2")
    clock.advance(1)
    n3 = a.create_note("Trois", "3")
    clock.advance(1)
    assert ids(a)[0] == n3, f"préalable : la plus récente en tête, obtenu {ids(a)!r}"
    a.edit_text(n1, "1 modifié")
    assert ids(a)[0] == n1, f"note modifiée attendue en tête, obtenu {ids(a)!r}"
    clock.advance(1)
    a.edit_title(n2, "Deux modifié")
    assert ids(a)[:2] == [n2, n1], f"obtenu {ids(a)!r}"


def test_A33_modification_recue_en_tete():
    clock, net, _, (a, b), _ = world()
    n1 = a.create_note("Un", "1")
    clock.advance(1)
    n2 = a.create_note("Deux", "2")
    clock.advance(1)
    n3 = a.create_note("Trois", "3")
    settle(clock)
    assert ids(a)[0] == n3
    b.edit_text(n1, "1 modifié sur B")
    settle(clock, 120)
    assert text_of(a, n1) == "1 modifié sur B"
    assert ids(a)[0] == n1, f"note reçue attendue en tête de A, obtenu {ids(a)!r}"


# ---------------------------------------------------------------- A34 / A35 (nouvel appareil)

def test_A34_nouvel_appareil_en_ligne_recoit_les_notes():
    clock, net, _, (a, b), _ = world()
    n1 = shared_note(clock, a, b, title="Un", text="1")
    n2 = shared_note(clock, a, b, title="Deux", text="2")
    gone = shared_note(clock, a, b, title="Partie", text="x")
    a.delete_note(gone)
    settle(clock)
    c = app.Device("C", net, clock, storage=app.LocalStorage())
    c.login(USER, PW)
    settle(clock, 120)
    assert set(ids(c)) == {n1, n2}, f"attendu {{n1, n2}}, obtenu {ids(c)!r}"
    assert (c.get_note(n2).title, c.get_note(n2).text) == ("Deux", "2")


def test_A34_autre_compte_ne_voit_pas_les_notes():
    clock, net, server, (a, b), _ = world()
    shared_note(clock, a, b)
    server.create_account("bob", "autre")
    c = app.Device("C", net, clock, storage=app.LocalStorage())
    c.login("bob", "autre")
    settle(clock, 120)
    assert ids(c) == [], f"le compte de bob ne doit pas voir les notes d'alice : {ids(c)!r}"


def test_A35_premier_lancement_hors_ligne_vide():
    clock, net, _, (a, b), _ = world()
    shared_note(clock, a, b)
    net.set_connected("C", False)
    c = app.Device("C", net, clock, storage=app.LocalStorage())
    settle(clock, 120)
    assert ids(c) == [], f"premier lancement hors ligne : liste vide attendue, obtenu {ids(c)!r}"
    assert c.status() == OFFLINE


def test_A35_premier_lancement_meme_nom_stockage_vide():
    # Un stockage neuf est un premier lancement, même si le nom d'appareil a déjà servi.
    clock, net, _, (a, b), _ = world()
    shared_note(clock, a, b)
    a.close()
    net.set_connected("A", False)
    a2 = app.Device("A", net, clock, storage=app.LocalStorage())
    settle(clock, 60)
    assert ids(a2) == [], f"stockage neuf hors ligne : liste vide attendue, obtenu {ids(a2)!r}"
