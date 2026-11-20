"""Tests rouges — sonde P07 : synchronisation hors ligne de notes.

Interface publique de `app` fixée par ces tests (le constructeur l'implémente telle quelle) :

    app.Clock(start: float = 0.0)
        .now() -> float
        .advance(seconds: float) -> None
        Horloge propre à un appareil ; c'est « l'heure de l'appareil ».

    app.Network()
        Réseau simulé en mémoire. Les messages envoyés restent EN TRANSIT tant
        qu'on ne les livre pas.
        .in_flight() -> int            nombre de messages en transit
        .deliver(i: int = 0) -> None   livre le i-ème message en transit
                                       (perdu si son destinataire est hors ligne)
        .lose(i: int = 0) -> None      perd le i-ème message en transit
        .duplicate(i: int = 0) -> None ajoute une copie du i-ème message en fin de file
        .run(seed: int | None = None) -> None
            livre jusqu'au calme (ordre de file si seed is None, sinon ordre
            aléatoire tiré de random.Random(seed)) ; quand la file est vide, chaque
            appareil en ligne avec session ouverte réémet ce qui n'a pas été
            acquitté et récupère ce qu'il a manqué ; recommence jusqu'à ce que
            plus rien ne bouge.

    app.Server(net)                     serveur du compte, nœud du réseau simulé
                                        (il a sa propre copie ; les appareils aussi).

    app.Device(name: str, net, clock)   démarre en ligne, application ouverte, sans session
        .go_offline() / .go_online()    perte / retour du réseau ; passer hors ligne
                                        perd les messages en transit depuis/vers l'appareil
        .status() -> str                "hors ligne" quand hors ligne, autre chose sinon
        .open_session(account: str) / .close_session()
        .close_app() / .open_app()      fermeture / réouverture de l'application
        .create_note(title: str, text: str) -> str   (identifiant, identique sur tous les appareils)
        .edit_text(note_id, text) / .edit_title(note_id, title) / .delete_note(note_id)
        .list_notes() -> list[dict]     de la tête vers la fin ; chaque dict a les clés
                                        "id", "title", "text", "indicator"
                                        indicator ∈ {"en attente", "synchronisée"}
        .note(note_id) -> dict | None   même forme ; None si absente de la liste
        .has_conflict(note_id) -> bool
        .resolve_conflict(note_id, text) -> None   l'utilisateur choisit la version `text`

    Une « copie de conflit » est une note de la liste, d'identifiant différent de
    l'original, dont le titre contient « copie de conflit ».
"""

import random

import app


PENDING = "en attente"
SYNCED = "synchronisée"
OFFLINE = "hors ligne"
COPY_MARK = "copie de conflit"


# --------------------------------------------------------------------------- outils


class World:
    def __init__(self, names=("A", "B"), account="alice"):
        self.net = app.Network()
        self.server = app.Server(self.net)
        self.clocks = {}
        self.dev = {}
        for name in names:
            self.add(name, account=account)
        self.net.run()

    def add(self, name, account="alice", offline=False):
        clock = app.Clock(1000.0)
        dev = app.Device(name, self.net, clock)
        if offline:
            dev.go_offline()
        if account is not None:
            dev.open_session(account)
        self.clocks[name] = clock
        self.dev[name] = dev
        return dev

    def tick(self, name, seconds=1.0):
        self.clocks[name].advance(seconds)

    @property
    def A(self):
        return self.dev["A"]

    @property
    def B(self):
        return self.dev["B"]


def ids(dev):
    return [n["id"] for n in dev.list_notes()]


def text_of(dev, note_id):
    n = dev.note(note_id)
    assert n is not None, f"note {note_id!r} attendue sur {dev!r}, absente ; liste={dev.list_notes()!r}"
    return n["text"]


def seeded(w, title="Courses", text="lait"):
    """Note créée sur A en ligne, propagée à B."""
    w.tick("A")
    nid = w.A.create_note(title, text)
    w.net.run()
    assert w.B.note(nid) is not None, "préparation : la note créée sur A devrait arriver sur B"
    assert text_of(w.B, nid) == text
    return nid


def copies(dev, original_id):
    return [n for n in dev.list_notes() if n["id"] != original_id and COPY_MARK in n["title"]]


def make_conflict(w, text_a="version A", text_b="version B", a_later=True):
    nid = seeded(w, text="origine")
    w.A.go_offline()
    w.B.go_offline()
    w.tick("A", 50 if a_later else 10)
    w.tick("B", 10 if a_later else 50)
    w.A.edit_text(nid, text_a)
    w.B.edit_text(nid, text_b)
    w.A.go_online()
    w.net.run()
    w.B.go_online()
    w.net.run()
    return nid


# --------------------------------------------------------------------------- A01–A02


def test_A01_perte_reseau_affiche_hors_ligne():
    w = World()
    assert w.A.status() != OFFLINE, f"en ligne au départ, obtenu {w.A.status()!r}"
    w.A.go_offline()
    assert w.A.status() == OFFLINE, f"attendu {OFFLINE!r}, obtenu {w.A.status()!r}"


def test_A01_perte_reseau_ne_touche_pas_l_autre_appareil():
    w = World()
    w.A.go_offline()
    assert w.B.status() != OFFLINE, f"B n'a pas perdu le réseau, obtenu {w.B.status()!r}"


def test_A02_retour_reseau_cesse_hors_ligne():
    w = World()
    w.A.go_offline()
    w.A.go_online()
    assert w.A.status() != OFFLINE, f"attendu autre chose que {OFFLINE!r}, obtenu {w.A.status()!r}"


# --------------------------------------------------------------------------- A03–A06


def test_A03_creation_hors_ligne_apparait_dans_la_liste():
    w = World()
    w.A.go_offline()
    nid = w.A.create_note("Idée", "écrire à Zoé — 日本")
    assert nid in ids(w.A), f"note {nid!r} absente de {ids(w.A)!r}"
    n = w.A.note(nid)
    assert n["title"] == "Idée" and n["text"] == "écrire à Zoé — 日本", f"obtenu {n!r}"


def test_A04_modification_texte_hors_ligne():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.edit_text(nid, "lait, œufs")
    assert text_of(w.A, nid) == "lait, œufs"


def test_A05_modification_titre_hors_ligne():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.edit_title(nid, "Courses samedi")
    assert w.A.note(nid)["title"] == "Courses samedi", f"obtenu {w.A.note(nid)!r}"


def test_A06_suppression_hors_ligne():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.delete_note(nid)
    assert nid not in ids(w.A), f"{nid!r} encore présente : {ids(w.A)!r}"
    assert w.A.note(nid) is None


# --------------------------------------------------------------------------- A07–A10 indicateur


def test_A07_modification_hors_ligne_en_attente():
    w = World()
    nid = seeded(w)
    assert w.A.note(nid)["indicator"] == SYNCED, "préparation : note synchronisée"
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    assert w.A.note(nid)["indicator"] == PENDING, f"obtenu {w.A.note(nid)['indicator']!r}"


def test_A07_reste_en_attente_tant_que_hors_ligne_meme_si_le_reseau_tourne():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.net.run()
    assert w.A.note(nid)["indicator"] == PENDING, f"obtenu {w.A.note(nid)['indicator']!r}"


def test_A08_en_ligne_synchronisee_une_fois_envoi_termine():
    w = World()
    nid = seeded(w)
    w.A.edit_text(nid, "nouveau")
    assert w.net.in_flight() >= 1, "la modification doit passer par le réseau simulé"
    assert w.A.note(nid)["indicator"] != SYNCED, (
        "avant livraison de l'envoi, la note ne peut pas être « synchronisée »"
    )
    w.net.run()
    assert w.A.note(nid)["indicator"] == SYNCED, f"obtenu {w.A.note(nid)['indicator']!r}"


def test_A08_envoi_perdu_puis_reessaye_finit_synchronise():
    w = World()
    nid = seeded(w)
    w.A.edit_text(nid, "nouveau")
    assert w.net.in_flight() >= 1
    w.net.lose(0)
    assert w.A.note(nid)["indicator"] != SYNCED, "envoi perdu : pas encore synchronisée"
    w.net.run()
    assert w.A.note(nid)["indicator"] == SYNCED, f"le réessai aurait dû aboutir, obtenu {w.A.note(nid)!r}"
    assert text_of(w.B, nid) == "nouveau"


def test_A09_retour_reseau_passe_synchronisee():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    assert w.A.note(nid)["indicator"] == PENDING
    w.A.go_online()
    w.net.run()
    assert w.A.note(nid)["indicator"] == SYNCED, f"obtenu {w.A.note(nid)['indicator']!r}"


def test_A10_retour_reseau_session_fermee_reste_en_attente():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.A.close_session()
    w.A.go_online()
    w.net.run()
    assert w.A.note(nid)["indicator"] == PENDING, f"obtenu {w.A.note(nid)['indicator']!r}"


# --------------------------------------------------------------------------- A11–A12 persistance


def test_A11_redemarrage_hors_ligne_conserve_texte_modifie():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.edit_text(nid, "après redémarrage")
    w.A.close_app()
    w.A.open_app()
    assert w.A.status() == OFFLINE
    assert text_of(w.A, nid) == "après redémarrage"


def test_A11_trou_modification_en_attente_survit_au_redemarrage():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.edit_text(nid, "après redémarrage")
    w.A.close_app()
    w.A.open_app()
    assert w.A.note(nid)["indicator"] == PENDING, f"obtenu {w.A.note(nid)!r}"
    w.A.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "après redémarrage", "la modification en attente a été perdue au redémarrage"
    assert w.A.note(nid)["indicator"] == SYNCED


def test_A12_redemarrage_hors_ligne_conserve_creation():
    w = World()
    w.A.go_offline()
    nid = w.A.create_note("Hors ligne", "brouillon")
    w.A.close_app()
    w.A.open_app()
    assert nid in ids(w.A), f"{nid!r} absente après redémarrage : {ids(w.A)!r}"
    assert text_of(w.A, nid) == "brouillon"


# --------------------------------------------------------------------------- A13–A21 propagation


def test_A13_A_hors_ligne_B_garde_ancien_texte():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.net.run()
    assert text_of(w.B, nid) == "ancien", "B voit une modification qui n'a jamais quitté A : état partagé ?"


def test_A13_copies_independantes_quand_B_est_hors_ligne():
    w = World()
    nid = seeded(w, text="ancien")
    w.B.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.net.run()
    assert text_of(w.B, nid) == "ancien", "B hors ligne ne peut rien avoir reçu"
    w.B.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "nouveau", "au retour en ligne B doit rattraper"


def test_A14_retour_reseau_B_affiche_nouveau_texte():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.A.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "nouveau"


def test_A15_retour_reseau_B_affiche_nouveau_titre():
    w = World()
    nid = seeded(w, title="Ancien titre")
    w.A.go_offline()
    w.A.edit_title(nid, "Nouveau titre ✓")
    w.A.go_online()
    w.net.run()
    assert w.B.note(nid)["title"] == "Nouveau titre ✓", f"obtenu {w.B.note(nid)!r}"


def test_A16_creation_hors_ligne_apparait_sur_B():
    w = World()
    w.A.go_offline()
    nid = w.A.create_note("Nouvelle", "contenu")
    w.A.go_online()
    w.net.run()
    assert nid in ids(w.B), f"{nid!r} absente de B : {w.B.list_notes()!r}"
    assert text_of(w.B, nid) == "contenu"


def test_A16_envoi_duplique_ne_cree_pas_de_doublon():
    w = World()
    w.A.go_offline()
    nid = w.A.create_note("Unique", "une seule fois")
    w.A.go_online()
    assert w.net.in_flight() >= 1
    for i in range(w.net.in_flight()):
        w.net.duplicate(i)
    w.net.run()
    on_b = [n for n in w.B.list_notes() if n["title"] == "Unique"]
    on_a = [n for n in w.A.list_notes() if n["title"] == "Unique"]
    assert len(on_b) == 1, f"attendu 1 note sur B, obtenu {on_b!r}"
    assert len(on_a) == 1, f"attendu 1 note sur A, obtenu {on_a!r}"
    assert on_b[0]["id"] == nid


def test_A17_suppression_hors_ligne_disparait_de_B():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.A.delete_note(nid)
    w.A.go_online()
    w.net.run()
    assert nid not in ids(w.B), f"{nid!r} encore sur B : {ids(w.B)!r}"


def test_A18_creee_puis_supprimee_hors_ligne_jamais_sur_B():
    for seed in range(12):
        w = World()
        w.A.go_offline()
        nid = w.A.create_note("Éphémère", "x")
        w.A.edit_text(nid, "y")
        w.A.delete_note(nid)
        w.A.go_online()
        rng = random.Random(seed)
        steps = 0
        while w.net.in_flight() and steps < 1000:
            w.net.deliver(rng.randrange(w.net.in_flight()))
            steps += 1
            assert all(n["title"] != "Éphémère" for n in w.B.list_notes()), (
                f"seed={seed} étape={steps} : la note éphémère est apparue sur B"
            )
        w.net.run(seed=seed)
        assert all(n["title"] != "Éphémère" for n in w.B.list_notes()), f"seed={seed}"
        assert w.B.note(nid) is None


def test_A19_deux_modifications_B_affiche_la_derniere_ordre_inverse():
    w = World()
    nid = seeded(w, text="v0")
    w.A.go_offline()
    w.tick("A")
    w.A.edit_text(nid, "v1")
    w.tick("A")
    w.A.edit_text(nid, "v2")
    w.A.go_online()
    while w.net.in_flight():
        w.net.deliver(w.net.in_flight() - 1)
    w.net.run()
    assert text_of(w.B, nid) == "v2", f"attendu 'v2', obtenu {text_of(w.B, nid)!r}"


def test_A19_deux_modifications_ordre_aleatoire():
    for seed in range(12):
        w = World()
        nid = seeded(w, text="v0")
        w.A.go_offline()
        w.tick("A")
        w.A.edit_text(nid, "v1")
        w.tick("A")
        w.A.edit_text(nid, "v2")
        w.A.go_online()
        w.net.run(seed=seed)
        assert text_of(w.B, nid) == "v2", f"seed={seed} : obtenu {text_of(w.B, nid)!r}"
        assert text_of(w.A, nid) == "v2", f"seed={seed} : A a régressé : {text_of(w.A, nid)!r}"


def test_A20_session_fermee_B_garde_ancien_texte():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.A.close_session()
    w.A.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "ancien", "A sans session ne doit rien avoir envoyé"


def test_A21_reouverture_session_propage_a_B():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.A.close_session()
    w.A.go_online()
    w.net.run()
    w.A.open_session("alice")
    w.net.run()
    assert text_of(w.B, nid) == "nouveau"


# --------------------------------------------------------------------------- A22–A23 coupure en cours d'envoi


def test_A22_coupure_pendant_envoi_reste_en_attente():
    w = World()
    nid = seeded(w)
    w.A.edit_text(nid, "nouveau")
    assert w.net.in_flight() >= 1
    w.A.go_offline()
    w.net.run()
    assert w.A.note(nid)["indicator"] == PENDING, f"obtenu {w.A.note(nid)['indicator']!r}"


def test_A22_envoi_perdu_puis_coupure_reste_en_attente():
    w = World()
    nid = seeded(w)
    w.A.edit_text(nid, "nouveau")
    w.net.lose(0)
    w.A.go_offline()
    assert w.A.note(nid)["indicator"] == PENDING, f"obtenu {w.A.note(nid)['indicator']!r}"


def test_A23_coupure_puis_retour_jamais_texte_partiel():
    old = "ancien"
    new = "Texte long — " + "ligne é∑漢字\r\n" * 200 + "fin"
    for seed in range(8):
        w = World()
        nid = seeded(w, text=old)
        w.A.edit_text(nid, new)
        w.A.go_offline()
        assert text_of(w.B, nid) == old
        w.A.go_online()
        rng = random.Random(seed)
        steps = 0
        while w.net.in_flight() and steps < 1000:
            w.net.deliver(rng.randrange(w.net.in_flight()))
            steps += 1
            got = text_of(w.B, nid)
            assert got in (old, new), f"seed={seed} : texte partiel sur B ({len(got)} car.)"
        w.net.run(seed=seed)
        assert text_of(w.B, nid) == new, f"seed={seed} : B n'a pas le texte complet"


def test_A23_pertes_repetees_finit_par_livrer_texte_complet():
    old, new = "ancien", "complet\n" * 50
    w = World()
    nid = seeded(w, text=old)
    w.A.edit_text(nid, new)
    rng = random.Random(7)
    for _ in range(5):
        while w.net.in_flight():
            if rng.random() < 0.5:
                w.net.lose(0)
            else:
                w.net.deliver(0)
            assert text_of(w.B, nid) in (old, new)
        w.A.go_offline()
        w.A.go_online()
    w.net.run()
    assert text_of(w.B, nid) == new
    assert w.A.note(nid)["indicator"] == SYNCED


# --------------------------------------------------------------------------- A24–A31 conflits


def test_A24_textes_differents_conflit_signale():
    w = World()
    nid = make_conflict(w)
    assert w.A.has_conflict(nid) or w.B.has_conflict(nid), "aucun conflit signalé"


def test_A24_conflit_detecte_quel_que_soit_l_ordre_de_livraison():
    for seed in range(10):
        w = World()
        nid = seeded(w, text="origine")
        w.A.go_offline()
        w.B.go_offline()
        w.A.edit_text(nid, "version A")
        w.B.edit_text(nid, "version B")
        w.A.go_online()
        w.B.go_online()
        w.net.run(seed=seed)
        assert w.A.has_conflict(nid) or w.B.has_conflict(nid), f"seed={seed} : aucun conflit"


def test_A24_trou_conflit_signale_sur_les_deux_appareils():
    w = World()
    nid = make_conflict(w)
    assert w.A.has_conflict(nid), "A ne signale pas le conflit"
    assert w.B.has_conflict(nid), "B ne signale pas le conflit"


def test_A24_trou_modifications_successives_pas_de_conflit():
    w = World()
    nid = seeded(w, text="origine")
    w.A.go_offline()
    w.tick("A")
    w.A.edit_text(nid, "par A")
    w.A.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "par A"
    w.B.go_offline()
    w.tick("B", 5)
    w.B.edit_text(nid, "par B, après avoir vu A")
    w.B.go_online()
    w.net.run()
    assert not w.A.has_conflict(nid), "B a modifié la version de A : ce n'est pas un conflit"
    assert not w.B.has_conflict(nid)
    assert text_of(w.A, nid) == "par B, après avoir vu A"
    assert copies(w.A, nid) == [] and copies(w.B, nid) == []


def test_A25_texte_identique_pas_de_conflit():
    w = World()
    nid = make_conflict(w, text_a="même texte", text_b="même texte")
    assert not w.A.has_conflict(nid), "A signale un conflit sur un texte identique"
    assert not w.B.has_conflict(nid), "B signale un conflit sur un texte identique"
    assert text_of(w.A, nid) == "même texte" and text_of(w.B, nid) == "même texte"


def test_A26_notes_differentes_pas_de_conflit():
    w = World()
    n1 = seeded(w, title="Une", text="1")
    n2 = seeded(w, title="Deux", text="2")
    w.A.go_offline()
    w.B.go_offline()
    w.A.edit_text(n1, "1 par A")
    w.B.edit_text(n2, "2 par B")
    w.A.go_online()
    w.B.go_online()
    w.net.run()
    for d in (w.A, w.B):
        assert not d.has_conflict(n1) and not d.has_conflict(n2), f"conflit signalé sur {d!r}"
    assert text_of(w.A, n2) == "2 par B" and text_of(w.B, n1) == "1 par A"


def test_A27_conflit_cree_copie_avec_l_autre_version():
    w = World()
    nid = make_conflict(w)
    checked = 0
    for d in (w.A, w.B):
        if not d.has_conflict(nid):
            continue
        checked += 1
        shown = text_of(d, nid)
        assert shown in ("version A", "version B"), f"original affiche {shown!r}"
        other = "version B" if shown == "version A" else "version A"
        cps = copies(d, nid)
        assert any(c["text"] == other for c in cps), (
            f"attendu une « {COPY_MARK} » contenant {other!r}, obtenu {cps!r}"
        )
    assert checked, "aucun appareil ne signale le conflit"


def test_A27_trou_une_seule_copie_identique_sur_les_deux_appareils():
    w = World()
    nid = seeded(w, text="origine")
    w.A.go_offline()
    w.B.go_offline()
    w.tick("A", 50)
    w.tick("B", 10)
    w.A.edit_text(nid, "version A")
    w.B.edit_text(nid, "version B")
    w.A.go_online()
    w.B.go_online()
    for i in range(w.net.in_flight()):
        w.net.duplicate(i)
    w.net.run(seed=3)
    ca, cb = copies(w.A, nid), copies(w.B, nid)
    assert len(ca) == 1, f"attendu 1 copie sur A, obtenu {ca!r}"
    assert len(cb) == 1, f"attendu 1 copie sur B, obtenu {cb!r}"
    assert ca[0]["id"] == cb[0]["id"] and ca[0]["text"] == cb[0]["text"] == "version B"


def test_A28_original_affiche_version_la_plus_recente_selon_horloge():
    # A modifie plus tard (horloge), mais B arrive en dernier au serveur.
    w = World()
    nid = make_conflict(w, a_later=True)
    for d in (w.A, w.B):
        assert text_of(d, nid) == "version A", (
            f"{d!r} : attendu la version la plus récente selon l'heure ('version A'), "
            f"obtenu {text_of(d, nid)!r}"
        )


def test_A28_symetrique_B_plus_recent():
    w = World()
    nid = make_conflict(w, a_later=False)
    for d in (w.A, w.B):
        assert text_of(d, nid) == "version B", f"{d!r} : obtenu {text_of(d, nid)!r}"


def test_A29_choix_d_une_version_leve_le_conflit():
    w = World()
    nid = make_conflict(w)
    assert w.A.has_conflict(nid), "préparation : A doit signaler le conflit"
    w.A.resolve_conflict(nid, "version B")
    assert not w.A.has_conflict(nid), "le conflit est toujours signalé après le choix"


def test_A29_trou_conflit_leve_aussi_sur_l_autre_appareil():
    w = World()
    nid = make_conflict(w)
    w.A.resolve_conflict(nid, "version B")
    w.net.run()
    assert not w.B.has_conflict(nid), "B signale encore un conflit déjà tranché sur A"


def test_A30_version_choisie_sur_A_affichee_sur_B():
    w = World()
    nid = make_conflict(w, a_later=True)
    assert text_of(w.B, nid) == "version A"
    w.A.resolve_conflict(nid, "version B")
    w.net.run()
    assert text_of(w.B, nid) == "version B", f"obtenu {text_of(w.B, nid)!r}"
    assert text_of(w.A, nid) == "version B"


def test_A31_modifiee_sur_A_supprimee_sur_B_reapparait_sur_B():
    for a_first in (True, False):
        w = World()
        nid = seeded(w, text="origine")
        w.A.go_offline()
        w.B.go_offline()
        w.tick("A", 5)
        w.tick("B", 10)
        w.A.edit_text(nid, "modifiée sur A")
        w.B.delete_note(nid)
        first, second = (w.A, w.B) if a_first else (w.B, w.A)
        first.go_online()
        w.net.run()
        second.go_online()
        w.net.run()
        assert any(n["text"] == "modifiée sur A" for n in w.B.list_notes()), (
            f"a_first={a_first} : la note modifiée n'est pas sur B : {w.B.list_notes()!r}"
        )


# --------------------------------------------------------------------------- A32–A33 ordre


def test_A32_note_modifiee_passe_en_tete():
    w = World()
    n1 = seeded(w, title="Un")
    n2 = seeded(w, title="Deux")
    n3 = seeded(w, title="Trois")
    assert ids(w.A)[0] != n1
    w.tick("A", 5)
    w.A.edit_text(n1, "remonte")
    assert ids(w.A)[0] == n1, f"attendu {n1!r} en tête, obtenu {ids(w.A)!r}"
    w.A.go_offline()
    w.tick("A", 5)
    w.A.edit_title(n2, "Deux bis")
    assert ids(w.A)[0] == n2, f"attendu {n2!r} en tête, obtenu {ids(w.A)!r}"
    assert set(ids(w.A)) == {n1, n2, n3}


def test_A33_modification_recue_passe_en_tete_sur_A():
    w = World()
    n1 = seeded(w, title="Un")
    seeded(w, title="Deux")
    seeded(w, title="Trois")
    w.tick("B", 5)
    w.B.edit_text(n1, "modifiée sur B")
    w.net.run()
    assert ids(w.A)[0] == n1, f"attendu {n1!r} en tête sur A, obtenu {ids(w.A)!r}"


def test_A33_trou_en_tete_meme_si_horloge_de_B_en_retard():
    w = World()
    n1 = seeded(w, title="Un")
    w.tick("A", 100)
    n2 = w.A.create_note("Deux", "2")
    w.net.run()
    w.tick("A", 100)
    w.A.edit_text(n2, "2 bis")
    w.net.run()
    assert ids(w.A)[0] == n2
    # l'horloge de B est loin derrière celle de A
    w.B.edit_text(n1, "modifiée sur B")
    w.net.run()
    assert text_of(w.A, n1) == "modifiée sur B"
    assert ids(w.A)[0] == n1, f"attendu {n1!r} en tête sur A à réception, obtenu {ids(w.A)!r}"


# --------------------------------------------------------------------------- A34–A35 nouvel appareil


def test_A34_nouvel_appareil_en_ligne_recoit_les_notes_du_compte():
    w = World()
    n1 = seeded(w, title="Un", text="1")
    n2 = seeded(w, title="Deux", text="2")
    c = w.add("C", account="alice")
    w.net.run()
    assert set(ids(c)) >= {n1, n2}, f"obtenu {ids(c)!r}"
    assert text_of(c, n1) == "1" and text_of(c, n2) == "2"


def test_A34_autre_compte_ne_recoit_pas_les_notes():
    w = World()
    seeded(w)
    c = w.add("C", account="bob")
    w.net.run()
    assert c.list_notes() == [], f"le compte bob voit les notes d'alice : {c.list_notes()!r}"


def test_A35_premier_lancement_hors_ligne_liste_vide():
    w = World()
    seeded(w)
    c = w.add("C", account=None, offline=True)
    w.net.run()
    w.A.create_note("Encore", "x")
    w.net.run()
    assert c.status() == OFFLINE
    assert c.list_notes() == [], f"un appareil jamais connecté voit des notes : {c.list_notes()!r}"
