"""Tests rouges — sonde P07 : synchronisation hors ligne des notes.

Interface publique fixée par ces tests (module `app`) :

    app.Clock(t0: float)              .now() -> float ; .advance(dt: float)
    app.Storage()                     stockage local persistant d'un appareil (survit à la fermeture de l'app)
    app.Network(seed: int = 0)        réseau simulé en mémoire ; livre dans un ordre arbitraire (dépendant de seed)
        .step() -> bool               fait avancer le réseau d'un pas (une livraison / un réessai) ;
                                      False quand plus rien ne peut progresser
        .run(max_steps=100000)        appelle step() jusqu'à quiescence
        .cut_next_send(name)          le prochain envoi de l'appareil `name` est perdu en cours de route
                                      ET la connexion de cet appareil se coupe (comme set_online(False))
        .drop_next_to(name)           le prochain message destiné à l'appareil `name` est perdu
                                      (la connexion reste ouverte : l'émetteur devra réessayer)
    app.Server(network)               le nœud distant du compte ; ne parle qu'à travers le réseau
    app.Device(name, network, clock, storage=None, online=True)
        .set_online(bool) ; .status() -> "hors ligne" | "en ligne"
        .login(account) ; .logout()
        .create_note(title, text) -> note_id
        .edit_text(note_id, text) ; .edit_title(note_id, title) ; .delete_note(note_id)
        .list_notes() -> list[Note]   ordonnée, la tête de liste en premier
        .get_note(note_id) -> Note | None
        .conflicts() -> list[note_id] notes sur lesquelles un conflit est signalé
        .resolve_conflict(note_id, keep_note_id)   keep_note_id = note_id (version d'origine)
                                                   ou l'id de sa copie de conflit
        .close_app()                  ferme l'application ; on la rouvre en construisant un nouveau
                                      Device avec le même `storage`
    Note : .id, .title, .text, .indicator ("en attente" | "synchronisée"),
           .conflict_copy_of (id de la note d'origine si c'est une « copie de conflit », sinon None)
"""

import pytest

import app

SEEDS = list(range(6))
ACCOUNT = "alice"
OFFLINE = "hors ligne"
PENDING = "en attente"
SYNCED = "synchronisée"


# --------------------------------------------------------------------------- outillage


class World:
    def __init__(self, seed=0):
        self.net = app.Network(seed=seed)
        self.server = app.Server(self.net)
        self.clocks = {}

    def device(self, name, t0=1000.0, online=True, login=True, storage=None):
        clock = app.Clock(t0)
        dev = app.Device(name, self.net, clock, storage=storage, online=True)
        if login:
            dev.login(ACCOUNT)
        self.net.run()
        dev.set_online(online)
        self.clocks[name] = clock
        return dev

    def tick(self, dt=1.0):
        for c in self.clocks.values():
            c.advance(dt)

    def settle(self):
        self.net.run()


def ids(dev):
    return [n.id for n in dev.list_notes()]


def titles(dev):
    return [n.title for n in dev.list_notes()]


def text_of(dev, nid):
    n = dev.get_note(nid)
    return None if n is None else n.text


def copies_of(dev, nid):
    return [n for n in dev.list_notes() if n.conflict_copy_of == nid]


def shared(seed=0, title="Titre", text="ancien"):
    """A et B en ligne, session ouverte, partagent une note synchronisée."""
    w = World(seed)
    a = w.device("A")
    b = w.device("B")
    nid = a.create_note(title, text)
    w.settle()
    assert text_of(b, nid) == text, (
        f"pré-condition : B devrait avoir reçu la note {nid!r} avec le texte {text!r}, "
        f"obtenu {text_of(b, nid)!r} (liste B : {titles(b)})"
    )
    return w, a, b, nid


def make_conflict(seed, text_a="version A", text_b="version B", a_later=True, a_first=True):
    w, a, b, nid = shared(seed)
    a.set_online(False)
    b.set_online(False)
    w.tick(10)
    if a_later:
        w.clocks["B"].advance(1)
        b.edit_text(nid, text_b)
        w.clocks["A"].advance(100)
        a.edit_text(nid, text_a)
    else:
        w.clocks["A"].advance(1)
        a.edit_text(nid, text_a)
        w.clocks["B"].advance(100)
        b.edit_text(nid, text_b)
    first, second = (a, b) if a_first else (b, a)
    first.set_online(True)
    w.settle()
    second.set_online(True)
    w.settle()
    return w, a, b, nid


# --------------------------------------------------------------------------- A01 / A02


def test_A01_perte_reseau_affiche_hors_ligne():
    w = World()
    a = w.device("A")
    a.set_online(False)
    assert a.status() == OFFLINE, f"attendu {OFFLINE!r} après perte du réseau, obtenu {a.status()!r}"


def test_A01_coupure_pendant_envoi_affiche_hors_ligne():
    w, a, b, nid = shared()
    w.net.cut_next_send("A")
    a.edit_text(nid, "nouveau")
    w.settle()
    assert a.status() == OFFLINE, (
        f"la connexion de A a été coupée pendant un envoi : attendu {OFFLINE!r}, obtenu {a.status()!r}"
    )


def test_A02_retour_reseau_cesse_hors_ligne():
    w = World()
    a = w.device("A")
    a.set_online(False)
    a.set_online(True)
    assert a.status() != OFFLINE, f"après retour du réseau, le statut ne doit plus être {OFFLINE!r}"
    assert a.status() == "en ligne", f"attendu 'en ligne', obtenu {a.status()!r}"


# --------------------------------------------------------------------------- A03..A06


def test_A03_creation_hors_ligne_apparait():
    w = World()
    a = w.device("A", online=False)
    nid = a.create_note("Courses", "lait")
    assert nid in ids(a), f"note créée hors ligne {nid!r} absente de la liste de A : {ids(a)}"
    assert a.get_note(nid).title == "Courses"
    assert a.get_note(nid).text == "lait"


def test_A04_modif_texte_hors_ligne():
    w, a, b, nid = shared()
    a.set_online(False)
    a.edit_text(nid, "nouveau texte é漢\r\nfin\n")
    assert text_of(a, nid) == "nouveau texte é漢\r\nfin\n", f"obtenu {text_of(a, nid)!r}"


def test_A05_modif_titre_hors_ligne():
    w, a, b, nid = shared()
    a.set_online(False)
    a.edit_title(nid, "Nouveau titre")
    assert a.get_note(nid).title == "Nouveau titre", f"obtenu {a.get_note(nid).title!r}"
    assert a.get_note(nid).text == "ancien", "modifier le titre ne doit pas changer le texte"


def test_A06_suppression_hors_ligne():
    w, a, b, nid = shared()
    a.set_online(False)
    a.delete_note(nid)
    assert nid not in ids(a), f"note supprimée encore présente sur A : {ids(a)}"
    assert a.get_note(nid) is None


# --------------------------------------------------------------------------- A07..A10


def test_A07_modif_hors_ligne_en_attente():
    w, a, b, nid = shared()
    assert a.get_note(nid).indicator == SYNCED, "pré-condition : la note devrait être synchronisée"
    a.set_online(False)
    a.edit_text(nid, "nouveau")
    assert a.get_note(nid).indicator == PENDING, (
        f"attendu {PENDING!r} après modification hors ligne, obtenu {a.get_note(nid).indicator!r}"
    )


def test_A07_trou_creation_hors_ligne_en_attente():
    w = World()
    a = w.device("A", online=False)
    nid = a.create_note("T", "x")
    assert a.get_note(nid).indicator == PENDING, (
        f"une création hors ligne n'a pas été envoyée : attendu {PENDING!r}, obtenu {a.get_note(nid).indicator!r}"
    )


def test_A08_en_ligne_synchronisee_une_fois_envoi_termine():
    w, a, b, nid = shared()
    a.edit_text(nid, "nouveau")
    assert a.get_note(nid).indicator != SYNCED, (
        "avant que le réseau n'ait livré l'envoi, la note ne peut pas déjà être « synchronisée »"
    )
    w.settle()
    assert a.get_note(nid).indicator == SYNCED, (
        f"après envoi terminé : attendu {SYNCED!r}, obtenu {a.get_note(nid).indicator!r}"
    )


def test_A09_retour_reseau_passe_synchronisee():
    w, a, b, nid = shared()
    a.set_online(False)
    a.edit_text(nid, "nouveau")
    assert a.get_note(nid).indicator == PENDING
    a.set_online(True)
    w.settle()
    assert a.get_note(nid).indicator == SYNCED, f"obtenu {a.get_note(nid).indicator!r}"


def test_A10_retour_reseau_session_fermee_reste_en_attente():
    w, a, b, nid = shared()
    a.set_online(False)
    a.edit_text(nid, "nouveau")
    a.logout()
    a.set_online(True)
    w.settle()
    assert a.get_note(nid).indicator == PENDING, (
        f"session fermée : attendu {PENDING!r}, obtenu {a.get_note(nid).indicator!r}"
    )


# --------------------------------------------------------------------------- A11 / A12


def test_A11_redemarrage_sans_reseau_conserve_modif():
    w = World()
    st = app.Storage()
    a = w.device("A", storage=st)
    nid = a.create_note("T", "ancien")
    w.settle()
    a.set_online(False)
    a.edit_text(nid, "modifié hors ligne")
    a.close_app()
    a2 = app.Device("A", w.net, w.clocks["A"], storage=st, online=False)
    assert text_of(a2, nid) == "modifié hors ligne", f"après réouverture, obtenu {text_of(a2, nid)!r}"


def test_A11_trou_attente_survit_au_redemarrage():
    w = World()
    st = app.Storage()
    a = w.device("A", storage=st)
    b = w.device("B")
    nid = a.create_note("T", "ancien")
    w.settle()
    a.set_online(False)
    a.edit_text(nid, "modifié avant fermeture")
    a.close_app()
    a2 = app.Device("A", w.net, w.clocks["A"], storage=st, online=False)
    assert a2.get_note(nid).indicator == PENDING, f"obtenu {a2.get_note(nid).indicator!r}"
    a2.set_online(True)
    a2.login(ACCOUNT)
    w.settle()
    assert text_of(b, nid) == "modifié avant fermeture", (
        f"la modification en attente avant redémarrage n'a pas atteint B : obtenu {text_of(b, nid)!r}"
    )
    assert a2.get_note(nid).indicator == SYNCED


def test_A12_redemarrage_sans_reseau_conserve_creation():
    w = World()
    st = app.Storage()
    a = w.device("A", online=False, storage=st)
    nid = a.create_note("Créée hors ligne", "contenu")
    a.close_app()
    a2 = app.Device("A", w.net, w.clocks["A"], storage=st, online=False)
    assert nid in ids(a2), f"note créée hors ligne absente après réouverture : {ids(a2)}"
    assert a2.get_note(nid).title == "Créée hors ligne"


# --------------------------------------------------------------------------- A13..A21


def test_A13_b_garde_ancien_texte_quand_a_hors_ligne():
    w, a, b, nid = shared()
    a.set_online(False)
    a.edit_text(nid, "nouveau")
    w.settle()
    assert text_of(b, nid) == "ancien", (
        f"A est hors ligne : B ne doit rien recevoir, obtenu {text_of(b, nid)!r}"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_A14_texte_modifie_hors_ligne_atteint_b(seed):
    w, a, b, nid = shared(seed)
    a.set_online(False)
    new = "nouveau é漢字 🙂\r\nligne2\nligne3"
    a.edit_text(nid, new)
    a.set_online(True)
    w.settle()
    assert text_of(b, nid) == new, f"seed={seed} : attendu {new!r} sur B, obtenu {text_of(b, nid)!r}"


def test_A14_trou_b_hors_ligne_rattrape_au_retour():
    w, a, b, nid = shared()
    b.set_online(False)
    a.edit_text(nid, "nouveau")
    w.settle()
    assert text_of(b, nid) == "ancien", (
        f"B hors ligne ne doit pas voir la modification (copie propre à B), obtenu {text_of(b, nid)!r}"
    )
    b.set_online(True)
    w.settle()
    assert text_of(b, nid) == "nouveau", f"B revenu en ligne : obtenu {text_of(b, nid)!r}"


@pytest.mark.parametrize("seed", SEEDS)
def test_A15_titre_modifie_hors_ligne_atteint_b(seed):
    w, a, b, nid = shared(seed)
    a.set_online(False)
    a.edit_title(nid, "Titre neuf")
    a.set_online(True)
    w.settle()
    assert b.get_note(nid).title == "Titre neuf", f"seed={seed} : obtenu {b.get_note(nid).title!r}"
    assert text_of(b, nid) == "ancien"


@pytest.mark.parametrize("seed", SEEDS)
def test_A16_creation_hors_ligne_apparait_sur_b(seed):
    w = World(seed)
    a = w.device("A")
    b = w.device("B")
    a.set_online(False)
    nid = a.create_note("Créée-16", "corps")
    a.set_online(True)
    w.settle()
    assert nid in ids(b), f"seed={seed} : note {nid!r} absente de B : {ids(b)}"
    assert titles(b).count("Créée-16") == 1, f"seed={seed} : doublon sur B : {titles(b)}"


def test_A16_trou_accuse_perdu_sans_doublon():
    w = World()
    a = w.device("A")
    b = w.device("B")
    w.net.drop_next_to("A")
    a.create_note("Unique-16", "corps")
    w.settle()
    assert titles(b).count("Unique-16") == 1, f"envoi réessayé : doublon ou absence sur B : {titles(b)}"
    assert titles(a).count("Unique-16") == 1, f"doublon sur A : {titles(a)}"
    note_a = [n for n in a.list_notes() if n.title == "Unique-16"][0]
    assert note_a.indicator == SYNCED, f"après réessai réussi : obtenu {note_a.indicator!r}"


@pytest.mark.parametrize("seed", SEEDS)
def test_A17_suppression_hors_ligne_atteint_b(seed):
    w, a, b, nid = shared(seed)
    a.set_online(False)
    a.delete_note(nid)
    a.set_online(True)
    w.settle()
    assert nid not in ids(b), f"seed={seed} : note supprimée sur A encore présente sur B : {ids(b)}"


@pytest.mark.parametrize("seed", SEEDS)
def test_A18_creee_puis_supprimee_jamais_sur_b(seed):
    w = World(seed)
    a = w.device("A")
    b = w.device("B")
    a.set_online(False)
    nid = a.create_note("Éphémère-18", "x")
    a.edit_text(nid, "y")
    a.delete_note(nid)
    a.set_online(True)
    for step in range(10000):
        assert "Éphémère-18" not in titles(b) and nid not in ids(b), (
            f"seed={seed}, pas {step} : la note créée puis supprimée est apparue sur B"
        )
        if not w.net.step():
            break
    assert "Éphémère-18" not in titles(b) and nid not in ids(b)


@pytest.mark.parametrize("seed", SEEDS)
def test_A19_deux_modifs_b_affiche_la_derniere(seed):
    w, a, b, nid = shared(seed)
    a.set_online(False)
    a.edit_text(nid, "première")
    w.tick(1)
    a.edit_text(nid, "seconde")
    a.set_online(True)
    w.settle()
    assert text_of(b, nid) == "seconde", f"seed={seed} : attendu 'seconde', obtenu {text_of(b, nid)!r}"
    assert text_of(a, nid) == "seconde"


def test_A20_session_fermee_b_garde_ancien_texte():
    w, a, b, nid = shared()
    a.set_online(False)
    a.edit_text(nid, "nouveau")
    a.logout()
    a.set_online(True)
    w.settle()
    assert text_of(b, nid) == "ancien", f"session de A fermée : B doit garder 'ancien', obtenu {text_of(b, nid)!r}"


def test_A21_reouverture_session_envoie_modifs():
    w, a, b, nid = shared()
    a.set_online(False)
    a.edit_text(nid, "nouveau")
    a.logout()
    a.set_online(True)
    w.settle()
    a.login(ACCOUNT)
    w.settle()
    assert text_of(b, nid) == "nouveau", f"après réouverture de session : obtenu {text_of(b, nid)!r}"


# --------------------------------------------------------------------------- A22 / A23


def test_A22_coupure_pendant_envoi_reste_en_attente():
    w, a, b, nid = shared()
    w.net.cut_next_send("A")
    a.edit_text(nid, "nouveau")
    w.settle()
    assert a.get_note(nid).indicator == PENDING, (
        f"envoi coupé : attendu {PENDING!r}, obtenu {a.get_note(nid).indicator!r}"
    )
    assert text_of(b, nid) == "ancien", f"l'envoi a été perdu : B ne peut pas l'avoir, obtenu {text_of(b, nid)!r}"


@pytest.mark.parametrize("seed", SEEDS)
def test_A23_coupure_puis_retour_texte_complet_jamais_partiel(seed):
    w, a, b, nid = shared(seed)
    big = "".join(f"ligne {i} é漢\r\n" for i in range(20000))
    w.net.cut_next_send("A")
    a.edit_text(nid, big)
    w.settle()
    a.set_online(True)
    for step in range(100000):
        t = text_of(b, nid)
        assert t in ("ancien", big), (
            f"seed={seed}, pas {step} : texte partiel sur B (longueur {len(t) if t else None}, attendu "
            f"{len('ancien')} ou {len(big)})"
        )
        if not w.net.step():
            break
    assert text_of(b, nid) == big, f"seed={seed} : B n'a pas le texte complet après retour du réseau"
    assert ids(b).count(nid) == 1, f"seed={seed} : doublon sur B après réessai : {ids(b)}"
    assert a.get_note(nid).indicator == SYNCED


# --------------------------------------------------------------------------- A24..A31 (conflits)


@pytest.mark.parametrize("seed", SEEDS)
def test_A24_textes_differents_conflit_signale(seed):
    w, a, b, nid = make_conflict(seed)
    assert nid in set(a.conflicts()) | set(b.conflicts()), (
        f"seed={seed} : aucun conflit signalé (A: {a.conflicts()}, B: {b.conflicts()})"
    )


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("a_first", [True, False])
def test_A24_trou_conflit_signale_sur_les_deux_appareils(seed, a_first):
    w, a, b, nid = make_conflict(seed, a_first=a_first)
    assert nid in a.conflicts(), f"seed={seed}, a_first={a_first} : conflit non signalé sur A : {a.conflicts()}"
    assert nid in b.conflicts(), f"seed={seed}, a_first={a_first} : conflit non signalé sur B : {b.conflicts()}"


def test_A24_trou_modifications_successives_sans_conflit():
    w, a, b, nid = shared()
    w.tick(5)
    a.edit_text(nid, "v2 par A")
    w.settle()
    assert text_of(b, nid) == "v2 par A"
    w.tick(5)
    b.edit_text(nid, "v3 par B")
    w.settle()
    # B reçoit la version de A, part hors ligne, la modifie, revient
    b.set_online(False)
    w.tick(5)
    b.edit_text(nid, "v4 par B hors ligne")
    b.set_online(True)
    w.settle()
    assert a.conflicts() == [] and b.conflicts() == [], (
        f"modifications successives (chacune partant de la dernière version) : aucun conflit attendu, "
        f"obtenu A={a.conflicts()} B={b.conflicts()}"
    )
    assert text_of(a, nid) == "v4 par B hors ligne"
    assert copies_of(a, nid) == [] and copies_of(b, nid) == []


@pytest.mark.parametrize("seed", SEEDS)
def test_A25_texte_identique_aucun_conflit(seed):
    w, a, b, nid = make_conflict(seed, text_a="même texte", text_b="même texte")
    assert nid not in a.conflicts() and nid not in b.conflicts(), (
        f"seed={seed} : texte identique, conflit signalé à tort (A: {a.conflicts()}, B: {b.conflicts()})"
    )
    assert copies_of(a, nid) == [] and copies_of(b, nid) == [], f"seed={seed} : copie de conflit créée à tort"
    assert text_of(a, nid) == text_of(b, nid) == "même texte"


@pytest.mark.parametrize("seed", SEEDS)
def test_A26_notes_differentes_aucun_conflit(seed):
    w = World(seed)
    a = w.device("A")
    b = w.device("B")
    n1 = a.create_note("N1", "un")
    n2 = a.create_note("N2", "deux")
    w.settle()
    a.set_online(False)
    b.set_online(False)
    w.tick(10)
    a.edit_text(n1, "un modifié par A")
    b.edit_text(n2, "deux modifié par B")
    a.set_online(True)
    b.set_online(True)
    w.settle()
    assert a.conflicts() == [] and b.conflicts() == [], (
        f"seed={seed} : notes différentes, aucun conflit attendu (A: {a.conflicts()}, B: {b.conflicts()})"
    )
    for d in (a, b):
        assert text_of(d, n1) == "un modifié par A", f"seed={seed} : {text_of(d, n1)!r}"
        assert text_of(d, n2) == "deux modifié par B", f"seed={seed} : {text_of(d, n2)!r}"


@pytest.mark.parametrize("seed", SEEDS)
def test_A27_copie_de_conflit_contient_autre_version(seed):
    w, a, b, nid = make_conflict(seed, text_a="version A", text_b="version B", a_later=True)
    for name, d in (("A", a), ("B", b)):
        cps = copies_of(d, nid)
        assert len(cps) == 1, f"seed={seed} : sur {name}, attendu une copie de conflit, obtenu {len(cps)}"
        assert cps[0].text == "version B", (
            f"seed={seed} : la copie sur {name} doit contenir l'autre version 'version B', obtenu {cps[0].text!r}"
        )
        assert cps[0].id != nid


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("a_later", [True, False])
@pytest.mark.parametrize("a_first", [True, False])
def test_A28_origine_affiche_version_la_plus_recente(seed, a_later, a_first):
    w, a, b, nid = make_conflict(seed, a_later=a_later, a_first=a_first)
    expected = "version A" if a_later else "version B"
    for name, d in (("A", a), ("B", b)):
        assert text_of(d, nid) == expected, (
            f"seed={seed}, a_later={a_later}, a_first={a_first} : sur {name} la note d'origine doit afficher "
            f"{expected!r}, obtenu {text_of(d, nid)!r}"
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_A28_trou_heures_egales_meme_version_partout(seed):
    w, a, b, nid = shared(seed)
    a.set_online(False)
    b.set_online(False)
    w.tick(10)  # les deux horloges avancent ensemble : mêmes heures
    a.edit_text(nid, "version A")
    b.edit_text(nid, "version B")
    a.set_online(True)
    b.set_online(True)
    w.settle()
    assert text_of(a, nid) == text_of(b, nid), (
        f"seed={seed} : heures égales, les appareils divergent : A={text_of(a, nid)!r} B={text_of(b, nid)!r}"
    )
    assert text_of(a, nid) in ("version A", "version B")
    assert [c.text for c in copies_of(a, nid)] == [c.text for c in copies_of(b, nid)]


def test_A29_choix_leve_le_conflit():
    w, a, b, nid = make_conflict(0)
    assert nid in a.conflicts()
    a.resolve_conflict(nid, nid)
    assert nid not in a.conflicts(), f"après choix, conflit encore signalé sur A : {a.conflicts()}"


def test_A29_trou_conflit_leve_sur_b():
    w, a, b, nid = make_conflict(0)
    a.resolve_conflict(nid, nid)
    w.settle()
    assert nid not in b.conflicts(), f"choix fait sur A en ligne : conflit encore signalé sur B : {b.conflicts()}"


def test_A29_trou_copie_disparait_apres_choix():
    w, a, b, nid = make_conflict(0)
    copy_id = copies_of(a, nid)[0].id
    a.resolve_conflict(nid, copy_id)
    w.settle()
    for name, d in (("A", a), ("B", b)):
        assert copies_of(d, nid) == [], f"sur {name}, la copie de conflit subsiste après le choix"
        assert copy_id not in ids(d), f"sur {name}, la copie {copy_id!r} est encore listée"


@pytest.mark.parametrize("seed", SEEDS)
def test_A30_version_choisie_atteint_b(seed):
    w, a, b, nid = make_conflict(seed, text_a="version A", text_b="version B", a_later=True)
    assert text_of(a, nid) == "version A"
    copy_id = copies_of(a, nid)[0].id
    a.resolve_conflict(nid, copy_id)  # l'utilisateur choisit la version perdante
    w.settle()
    assert text_of(a, nid) == "version B", f"seed={seed} : A doit afficher la version choisie, obtenu {text_of(a, nid)!r}"
    assert text_of(b, nid) == "version B", f"seed={seed} : B doit afficher la version choisie, obtenu {text_of(b, nid)!r}"


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("a_first", [True, False])
def test_A31_modif_contre_suppression_la_note_revient_sur_b(seed, a_first):
    w, a, b, nid = shared(seed)
    a.set_online(False)
    b.set_online(False)
    w.tick(10)
    a.edit_text(nid, "modifiée sur A")
    b.delete_note(nid)
    first, second = (a, b) if a_first else (b, a)
    first.set_online(True)
    w.settle()
    second.set_online(True)
    w.settle()
    assert nid in ids(b), f"seed={seed}, a_first={a_first} : la note modifiée doit réapparaître sur B : {ids(b)}"
    assert text_of(b, nid) == "modifiée sur A", f"obtenu {text_of(b, nid)!r}"
    assert nid in ids(a), f"seed={seed}, a_first={a_first} : la note modifiée a disparu de A"


# --------------------------------------------------------------------------- A32 / A33 (ordre)


@pytest.mark.parametrize("online", [True, False])
def test_A32_modification_passe_en_tete(online):
    w = World()
    a = w.device("A", online=online)
    n1 = a.create_note("N1", "1")
    w.tick(1)
    n2 = a.create_note("N2", "2")
    w.tick(1)
    n3 = a.create_note("N3", "3")
    w.tick(1)
    a.edit_text(n1, "1 modifié")
    assert ids(a)[0] == n1, f"après modification du texte de N1, attendu N1 en tête, obtenu {titles(a)}"
    w.tick(1)
    a.edit_title(n2, "N2 bis")
    assert ids(a)[0] == n2, f"après modification du titre de N2, attendu N2 en tête, obtenu {titles(a)}"


def _two_notes_n1_not_on_top(seed=0):
    w = World(seed)
    a = w.device("A")
    b = w.device("B")
    n1 = a.create_note("N1", "1")
    w.tick(1)
    n2 = a.create_note("N2", "2")
    w.tick(1)
    a.edit_text(n2, "2 bis")
    w.settle()
    assert ids(a)[0] == n2, f"pré-condition : N2 devrait être en tête sur A, obtenu {titles(a)}"
    return w, a, b, n1


def test_A33_modif_recue_passe_en_tete():
    w, a, b, n1 = _two_notes_n1_not_on_top()
    w.tick(5)
    b.edit_text(n1, "1 modifié sur B")
    w.settle()
    assert text_of(a, n1) == "1 modifié sur B"
    assert ids(a)[0] == n1, f"modification reçue de B : attendu N1 en tête sur A, obtenu {titles(a)}"


def test_A33_trou_horloge_de_b_en_retard():
    w, a, b, n1 = _two_notes_n1_not_on_top()
    w.clocks["A"].advance(10000)  # l'horloge de B est très en retard sur celle de A
    b.edit_text(n1, "1 modifié sur B")
    w.settle()
    assert text_of(a, n1) == "1 modifié sur B"
    assert ids(a)[0] == n1, (
        f"modification reçue (horloge de B en retard) : attendu N1 en tête sur A, obtenu {titles(a)}"
    )


# --------------------------------------------------------------------------- A34 / A35


def test_A34_nouvel_appareil_en_ligne_recupere_les_notes():
    w = World()
    a = w.device("A")
    n1 = a.create_note("N1", "un")
    n2 = a.create_note("N2", "deux")
    w.settle()
    c = w.device("C", t0=5000.0)
    w.settle()
    assert set(ids(c)) >= {n1, n2}, f"nouvel appareil : attendu {n1!r}, {n2!r}, obtenu {ids(c)}"
    assert text_of(c, n1) == "un" and text_of(c, n2) == "deux"


def test_A35_premier_lancement_hors_ligne_aucune_note():
    w = World()
    a = w.device("A")
    a.create_note("N1", "un")
    w.settle()
    c = app.Device("C", w.net, app.Clock(5000.0), online=False)
    w.settle()
    assert c.list_notes() == [], f"nouvel appareil hors ligne : aucune note attendue, obtenu {titles(c)}"
