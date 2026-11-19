"""Tests rouges de la sonde P08 : édition collaborative à fusion réelle.

Interface publique de `app` fixée par ces tests (le constructeur l'implémente telle quelle) :

app.Network()
    .deliver(n, seed=None) -> int
        livre au plus n messages en attente : les plus anciens si seed est None,
        sinon tirés au hasard (random.Random(seed)) parmi tous les messages en attente.
    .deliver_all(seed=None) -> int
        livre jusqu'à ce qu'il ne reste aucun message livrable (FIFO, ou ordre aléatoire si seed).
    .advance(seconds)
        fait avancer le temps simulé.

app.Server(network, owner, text="", permissions=None)
    un document ; `owner` en est le propriétaire (permission écriture implicite) ;
    permissions : dict nom -> "write" | "read" ; un nom absent n'a aucune permission.
    .open(name) -> Client          ouvre le document pour ce participant (connecté).

Client (une réplique locale du document) :
    .content -> str | None         contenu affiché (None si aucune permission)
    .insert(pos, text)             édition locale immédiate, sans attendre le réseau
    .delete(pos, length)
    .cursor -> int  /  .move_cursor(pos)
    .remote_cursors -> dict nom -> int
    .presence -> collection de noms (supporte `in`)
    .undo()  /  .redo()  /  .can_redo -> bool
    .disconnect()  (perte de connexion)  /  .reconnect()  /  .close()
    .pending_sync -> bool          indicateur d'attente de synchronisation
    .set_permission(user, level)   level : "write" | "read" | None
    .permission_of(user) -> "write" | "read" | None
    .save_version()  /  .history -> list d'entrées ayant .author et .text (la plus récente en dernier)
    .view_version(index) -> str    /  .restore_version(index)

Une action refusée n'a aucun effet ; elle peut lever PermissionError ou ne rien lever.
"""

import random

import app


# ---------------------------------------------------------------- utilitaires

def make(text="Hello", writers=(), readers=()):
    net = app.Network()
    perms = {w: "write" for w in writers}
    perms.update({r: "read" for r in readers})
    server = app.Server(net, owner="alice", text=text, permissions=perms)
    return net, server


def open_all(net, server, *names):
    clients = [server.open(n) for n in names]
    net.deliver_all()
    return clients


def attempt(action):
    try:
        return action()
    except PermissionError:
        return None


def wait(net, seconds):
    for _ in range(seconds):
        net.advance(1)
        net.deliver_all()


def same_everywhere(clients, expected=None):
    contents = {c: c.content for c in clients}
    values = list(contents.values())
    assert all(v == values[0] for v in values), (
        f"répliques divergentes : attendu un contenu identique, obtenu "
        f"{[(getattr(c, 'name', '?'), v) for c, v in contents.items()]}"
    )
    if expected is not None:
        assert values[0] == expected, f"attendu {expected!r}, obtenu {values[0]!r}"
    return values[0]


def unique_chars():
    k = 0
    while True:
        yield chr(0x4E00 + k)  # caractères non ASCII, tous distincts
        k += 1


def run_fuzz(seed, with_deletes, steps=60):
    rng = random.Random(seed)
    net, server = make("", writers=("bob", "carol"))
    clients = open_all(net, server, "alice", "bob", "carol")
    gen = unique_chars()
    inserted, deleted = set(), set()
    for _ in range(steps):
        r = rng.random()
        c = rng.choice(clients)
        if r < 0.5 or (with_deletes and r < 0.65 and not c.content):
            text = "".join(next(gen) for _ in range(rng.randint(1, 3)))
            before = c.content
            pos = rng.randint(0, len(before))
            c.insert(pos, text)
            assert c.content == before[:pos] + text + before[pos:], (
                f"édition locale non immédiate : attendu {before[:pos] + text + before[pos:]!r}, "
                f"obtenu {c.content!r}"
            )
            inserted.update(text)
        elif with_deletes and r < 0.65:
            before = c.content
            pos = rng.randint(0, len(before) - 1)
            length = rng.randint(1, min(3, len(before) - pos))
            deleted.update(before[pos:pos + length])
            c.delete(pos, length)
            assert c.content == before[:pos] + before[pos + length:], (
                f"suppression locale non immédiate : attendu "
                f"{before[:pos] + before[pos + length:]!r}, obtenu {c.content!r}"
            )
        else:
            net.deliver(rng.randint(1, 4), seed=rng.randrange(10**6))
    net.deliver_all(seed=seed)
    return clients, inserted, deleted


# ---------------------------------------------------------------- A01

def test_A01_insertion_visible_chez_un_autre_participant():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " world")
    net.deliver_all()
    assert bob.content == "Hello world", f"attendu 'Hello world' chez bob, obtenu {bob.content!r}"


def test_A01_insertions_successives_livrees_dans_le_desordre():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        for i, ch in enumerate("abcdefghij"):
            alice.insert(5 + i, ch)
        net.deliver_all(seed=seed)
        for c in (bob, carol):
            assert c.content == "Helloabcdefghij", (
                f"seed={seed} : attendu 'Helloabcdefghij', obtenu {c.content!r}"
            )


def test_A01_insertion_visible_chez_un_lecteur():
    net, server = make("Hello", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    alice.insert(0, "Oh ")
    net.deliver_all()
    assert carol.content == "Oh Hello", f"attendu 'Oh Hello' chez carol, obtenu {carol.content!r}"


# ---------------------------------------------------------------- A02

def test_A02_lecteur_tape_le_contenu_ne_change_pas_meme_localement():
    net, server = make("Hello", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    attempt(lambda: carol.insert(0, "X"))
    assert carol.content == "Hello", f"attendu 'Hello' chez carol juste après la frappe, obtenu {carol.content!r}"
    net.deliver_all()
    same_everywhere([alice, carol], "Hello")


def test_A02_lecteur_supprime_le_contenu_ne_change_pas():
    net, server = make("Hello", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    attempt(lambda: carol.delete(0, 3))
    net.deliver_all()
    same_everywhere([alice, carol], "Hello")


def test_A02_participant_retrograde_en_lecture_ne_modifie_plus():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.set_permission("bob", "read")
    net.deliver_all()
    attempt(lambda: bob.insert(0, "X"))
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")


# ---------------------------------------------------------------- A03

def test_A03_sans_permission_le_contenu_n_est_pas_affiche():
    net, server = make("Hello secret")
    alice, eve = open_all(net, server, "alice", "eve")
    assert eve.content is None, f"attendu None chez eve (aucune permission), obtenu {eve.content!r}"


def test_A03_sans_permission_les_editions_ulterieures_ne_sont_pas_affichees():
    net, server = make("Hello")
    alice, eve = open_all(net, server, "alice", "eve")
    alice.insert(5, " secret")
    net.deliver_all()
    assert eve.content is None, f"attendu None chez eve, obtenu {eve.content!r}"


def test_A03_trou_version_non_affichee():
    net, server = make("Hello secret")
    (alice,) = open_all(net, server, "alice")
    alice.save_version()
    net.deliver_all()
    (eve,) = open_all(net, server, "eve")
    shown = attempt(lambda: eve.view_version(0))
    assert shown is None or "secret" not in shown, (
        f"attendu aucune version affichée à eve (aucune permission), obtenu {shown!r}"
    )


# ---------------------------------------------------------------- A04

def test_A04_lecteur_voit_le_contenu_courant():
    net, server = make("Hello")
    (alice,) = open_all(net, server, "alice")
    alice.insert(5, " world")
    net.deliver_all()
    (carol,) = open_all(net, server, "carol") if False else (None,)
    net2, server2 = make("Hello", readers=("carol",))
    (alice2,) = open_all(net2, server2, "alice")
    alice2.insert(5, " world")
    net2.deliver_all()
    (carol2,) = open_all(net2, server2, "carol")
    assert carol2.content == "Hello world", f"attendu 'Hello world', obtenu {carol2.content!r}"


def test_A04_lecteur_ouvre_pendant_une_edition_en_vol():
    for seed in range(10):
        net, server = make("Hello", readers=("carol",))
        (alice,) = open_all(net, server, "alice")
        alice.insert(5, " world")  # pas encore livrée
        carol = server.open("carol")
        net.deliver_all(seed=seed)
        assert carol.content == "Hello world", (
            f"seed={seed} : attendu 'Hello world' chez carol, obtenu {carol.content!r}"
        )


# ---------------------------------------------------------------- A05

def test_A05_suppression_visible_chez_un_autre():
    net, server = make("Hello world", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.delete(5, 6)
    net.deliver_all()
    assert bob.content == "Hello", f"attendu 'Hello' chez bob, obtenu {bob.content!r}"


def test_A05_suppressions_concurrentes_qui_se_chevauchent():
    for seed in range(10):
        net, server = make("Hello brave new world", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        alice.delete(6, 6)    # "brave "
        bob.delete(6, 10)     # "brave new "
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob, carol], "Hello world")


def test_A05_suppression_concurrente_d_une_insertion_voisine():
    for seed in range(10):
        net, server = make("Hello world", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.delete(0, 6)          # retire "Hello "
        bob.insert(11, "!")         # ajoute en fin
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "world!")


def test_A05_fuzz_les_passages_supprimes_disparaissent_partout():
    for seed in range(12):
        clients, inserted, deleted = run_fuzz(seed, with_deletes=True)
        for c in clients:
            assert set(c.content) == inserted - deleted, (
                f"seed={seed} : attendu exactement les caractères insérés non supprimés "
                f"({len(inserted - deleted)}), obtenu {len(set(c.content))} ; "
                f"en trop={set(c.content) - (inserted - deleted)!r}, "
                f"manquants={(inserted - deleted) - set(c.content)!r}"
            )
            assert len(c.content) == len(set(c.content)), f"seed={seed} : caractère dupliqué dans {c.content!r}"


# ---------------------------------------------------------------- A06

def test_A06_nom_apparait_chez_les_autres():
    net, server = make("Hello", writers=("bob",))
    (alice,) = open_all(net, server, "alice")
    (bob,) = open_all(net, server, "bob")
    assert "bob" in alice.presence, f"attendu 'bob' dans la présence d'alice, obtenu {list(alice.presence)!r}"
    assert "alice" in bob.presence, f"attendu 'alice' dans la présence de bob, obtenu {list(bob.presence)!r}"


def test_A06_lecteur_apparait_aussi():
    net, server = make("Hello", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    assert "carol" in alice.presence, f"attendu 'carol' dans la présence, obtenu {list(alice.presence)!r}"


def test_A06_trou_presence_au_repos():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    wait(net, 300)
    assert "bob" in alice.presence, (
        f"attendu 'bob' toujours présent après 300 s sans activité, obtenu {list(alice.presence)!r}"
    )


# ---------------------------------------------------------------- A07

def test_A07_fermeture_retire_le_nom():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.close()
    net.deliver_all()
    assert "bob" not in alice.presence, f"attendu 'bob' absent, obtenu {list(alice.presence)!r}"
    assert "bob" not in carol.presence, f"attendu 'bob' absent chez carol, obtenu {list(carol.presence)!r}"
    assert "carol" in alice.presence, f"attendu 'carol' toujours présente, obtenu {list(alice.presence)!r}"


# ---------------------------------------------------------------- A08

def test_A08_perte_de_connexion_retire_le_nom():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.disconnect()
    wait(net, 300)
    assert "bob" not in alice.presence, f"attendu 'bob' absent après perte de connexion, obtenu {list(alice.presence)!r}"
    assert "carol" in alice.presence, f"attendu 'carol' toujours présente, obtenu {list(alice.presence)!r}"


def test_A08_trou_delai_detection():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    wait(net, 60)
    assert "bob" not in alice.presence, (
        f"attendu 'bob' absent au plus 60 s après la perte de connexion, obtenu {list(alice.presence)!r}"
    )


# ---------------------------------------------------------------- A09

def test_A09_curseur_distant_suit_le_deplacement():
    net, server = make("Hello world", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.move_cursor(3)
    net.deliver_all()
    assert alice.remote_cursors.get("bob") == 3, f"attendu 3, obtenu {alice.remote_cursors.get('bob')!r}"
    bob.move_cursor(8)
    net.deliver_all()
    assert alice.remote_cursors.get("bob") == 8, f"attendu 8, obtenu {alice.remote_cursors.get('bob')!r}"


def test_A09_curseur_d_un_lecteur_visible():
    net, server = make("Hello world", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    carol.move_cursor(4)
    net.deliver_all()
    assert alice.remote_cursors.get("carol") == 4, f"attendu 4, obtenu {alice.remote_cursors.get('carol')!r}"


# ---------------------------------------------------------------- A10

def test_A10_perte_de_connexion_retire_le_curseur_distant():
    net, server = make("Hello world", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.move_cursor(3)
    net.deliver_all()
    bob.disconnect()
    wait(net, 300)
    assert "bob" not in alice.remote_cursors, f"attendu aucun curseur pour bob, obtenu {alice.remote_cursors!r}"


# ---------------------------------------------------------------- A11

def test_A11_mon_curseur_reste_devant_le_meme_caractere():
    net, server = make("abcdef", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.move_cursor(3)
    net.deliver_all()
    bob.insert(0, "XX")
    net.deliver_all()
    assert alice.cursor == 5, f"attendu 5, obtenu {alice.cursor!r}"
    assert alice.content[alice.cursor] == "d", f"attendu devant 'd', obtenu {alice.content!r}@{alice.cursor}"


def test_A11_mon_curseur_deplace_pendant_une_insertion_concurrente():
    for seed in range(10):
        net, server = make("abcdef", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.move_cursor(3)
        bob.insert(1, "XYZ")
        net.deliver_all(seed=seed)
        assert alice.cursor == 6 and alice.content[alice.cursor] == "d", (
            f"seed={seed} : attendu curseur 6 devant 'd', obtenu {alice.cursor!r} dans {alice.content!r}"
        )


def test_A11_trou_insertion_a_la_position_du_curseur():
    net, server = make("abcdef", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.move_cursor(3)
    net.deliver_all()
    bob.insert(3, "XX")
    net.deliver_all()
    assert alice.cursor == 5 and alice.content[alice.cursor] == "d", (
        f"attendu curseur 5 devant 'd', obtenu {alice.cursor!r} dans {alice.content!r}"
    )


# ---------------------------------------------------------------- A12

def test_A12_curseur_distant_reste_devant_le_meme_caractere():
    net, server = make("abcdef", writers=("bob", "carol"))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.move_cursor(3)
    net.deliver_all()
    carol.insert(0, "XX")
    net.deliver_all()
    pos = alice.remote_cursors.get("bob")
    assert pos == 5 and alice.content[pos] == "d", f"attendu 5 devant 'd', obtenu {pos!r} dans {alice.content!r}"


def test_A12_curseur_distant_et_insertion_concurrente():
    for seed in range(10):
        net, server = make("abcdef", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        bob.move_cursor(3)          # émis sur l'état sans "XX"
        alice.insert(0, "XX")       # concurrent
        net.deliver_all(seed=seed)
        for viewer in (alice, carol):
            pos = viewer.remote_cursors.get("bob")
            assert pos == 5 and viewer.content[pos] == "d", (
                f"seed={seed} : attendu curseur de bob en 5 devant 'd', obtenu {pos!r} dans {viewer.content!r}"
            )


# ---------------------------------------------------------------- A13

def test_A13_suppression_englobant_un_curseur_distant():
    net, server = make("Hello world", writers=("bob", "carol"))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.move_cursor(8)
    net.deliver_all()
    carol.delete(2, 7)  # retire "llo wor" -> "Held"
    net.deliver_all()
    assert alice.content == "Held", f"attendu 'Held', obtenu {alice.content!r}"
    assert alice.remote_cursors.get("bob") == 2, f"attendu 2, obtenu {alice.remote_cursors.get('bob')!r}"
    assert carol.remote_cursors.get("bob") == 2, f"attendu 2 chez carol, obtenu {carol.remote_cursors.get('bob')!r}"


def test_A13_suppression_concurrente_au_deplacement():
    for seed in range(10):
        net, server = make("Hello world", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        bob.move_cursor(8)
        alice.delete(2, 7)
        net.deliver_all(seed=seed)
        assert alice.remote_cursors.get("bob") == 2, (
            f"seed={seed} : attendu 2, obtenu {alice.remote_cursors.get('bob')!r}"
        )


# ---------------------------------------------------------------- A14

def test_A14_annuler_retire_sa_saisie():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " world")
    alice.undo()
    assert alice.content == "Hello", f"attendu 'Hello', obtenu {alice.content!r}"
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")


def test_A14_trou_granularite():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " big")
    alice.insert(9, " world")
    alice.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello big")


# ---------------------------------------------------------------- A15

def test_A15_annuler_preserve_la_modification_ulterieure_d_autrui():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " abc")
    net.deliver_all()
    bob.insert(0, "Z")
    net.deliver_all()
    alice.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "ZHello")


def test_A15_annuler_preserve_une_insertion_au_milieu_de_sa_saisie():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " abc")
    net.deliver_all()
    bob.insert(7, "X")  # "Hello aXbc"
    net.deliver_all()
    alice.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "HelloX")


# ---------------------------------------------------------------- A16

def test_A16_annuler_sans_action_ne_change_rien():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.insert(0, "Z")
    net.deliver_all()
    alice.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "ZHello")


def test_A16_annuler_une_fois_de_trop_ne_change_rien():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, "!")
    alice.undo()
    alice.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")


# ---------------------------------------------------------------- A17

def test_A17_lecteur_annule_rien_ne_change():
    net, server = make("Hello", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    attempt(carol.undo)
    net.deliver_all()
    same_everywhere([alice, carol], "Hello")


def test_A17_retrograde_ne_peut_annuler_sa_saisie_d_avant():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.insert(0, "X")
    net.deliver_all()
    alice.set_permission("bob", "read")
    net.deliver_all()
    attempt(bob.undo)
    assert bob.content == "XHello", f"attendu 'XHello' chez bob, obtenu {bob.content!r}"
    net.deliver_all()
    same_everywhere([alice, bob], "XHello")


# ---------------------------------------------------------------- A18

def test_A18_retablir_apres_annuler():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " world")
    net.deliver_all()
    alice.undo()
    net.deliver_all()
    alice.redo()
    assert alice.content == "Hello world", f"attendu 'Hello world', obtenu {alice.content!r}"
    net.deliver_all()
    same_everywhere([alice, bob], "Hello world")


# ---------------------------------------------------------------- A19

def test_A19_saisie_apres_annulation_vide_le_retablissement():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " world")
    alice.undo()
    assert alice.can_redo is True, f"attendu can_redo True après annulation, obtenu {alice.can_redo!r}"
    alice.insert(5, "!")
    assert alice.can_redo is False, f"attendu can_redo False après une saisie, obtenu {alice.can_redo!r}"
    alice.redo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello!")


def test_A19_trou_saisie_d_autrui():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.insert(5, " world")
    net.deliver_all()
    alice.undo()
    net.deliver_all()
    bob.insert(0, "Z")
    net.deliver_all()
    assert alice.can_redo is True, f"attendu can_redo True malgré la saisie de bob, obtenu {alice.can_redo!r}"
    alice.redo()
    net.deliver_all()
    same_everywhere([alice, bob], "ZHello world")


# ---------------------------------------------------------------- A20

def test_A20_retablir_a_vide_ne_change_rien():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.redo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")
    alice.insert(5, "!")
    alice.redo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello!")


# ---------------------------------------------------------------- A21

def test_A21_insertions_concurrentes_au_meme_endroit_toutes_presentes():
    for seed in range(10):
        net, server = make("Hello", writers=("bob", "carol"))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        alice.insert(5, "AAA")
        bob.insert(5, "BBB")
        carol.insert(5, "CCC")
        # chacun voit sa saisie immédiatement, sans attendre
        assert alice.content == "HelloAAA", f"attendu 'HelloAAA', obtenu {alice.content!r}"
        assert bob.content == "HelloBBB", f"attendu 'HelloBBB', obtenu {bob.content!r}"
        net.deliver_all(seed=seed)
        for c in (alice, bob, carol):
            for part in ("AAA", "BBB", "CCC"):
                assert part in c.content, f"seed={seed} : attendu {part!r} dans {c.content!r}"
            assert c.content.startswith("Hello") and len(c.content) == 14, (
                f"seed={seed} : attendu 'Hello' + 9 caractères, obtenu {c.content!r}"
            )


def test_A21_fuzz_insertions_concurrentes_toutes_presentes():
    for seed in range(12):
        clients, inserted, _ = run_fuzz(seed, with_deletes=False)
        for c in clients:
            assert set(c.content) == inserted and len(c.content) == len(inserted), (
                f"seed={seed} : attendu {len(inserted)} caractères insérés, obtenu {len(c.content)} ; "
                f"manquants={inserted - set(c.content)!r}"
            )


def test_A21_ordre_de_ses_propres_insertions_preserve():
    for seed in range(10):
        rng = random.Random(seed)
        net, server = make("", writers=("bob", "carol"))
        clients = open_all(net, server, "alice", "bob", "carol")
        gen = unique_chars()
        own = {}
        for c in clients:
            for _ in range(8):
                c.insert(rng.randint(0, len(c.content)), next(gen))
            own[c] = c.content
        net.deliver_all(seed=seed)
        for c in clients:
            for author, local in own.items():
                projected = "".join(ch for ch in c.content if ch in set(local))
                assert projected == local, (
                    f"seed={seed} : ordre des insertions d'un participant altéré : "
                    f"attendu {local!r}, obtenu {projected!r}"
                )


# ---------------------------------------------------------------- A22

def test_A22_ordre_identique_chez_tous():
    for seed in range(15):
        net, server = make("Hello", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        alice.insert(5, "AAA")
        bob.insert(5, "BBB")
        net.deliver_all(seed=seed)
        result = same_everywhere([alice, bob, carol])
        assert result in ("HelloAAABBB", "HelloBBBAAA"), f"seed={seed} : obtenu {result!r}"


def test_A22_ordre_identique_apres_insertion_hors_connexion():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.disconnect()
    alice.insert(2, "AA")
    bob.insert(2, "BB")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    result = same_everywhere([alice, bob, carol])
    assert result in ("HeAABBllo", "HeBBAAllo"), f"attendu les deux insertions en position 2, obtenu {result!r}"


def test_A22_fuzz_convergence_insertions_et_suppressions():
    for seed in range(12):
        clients, _, _ = run_fuzz(seed, with_deletes=True)
        same_everywhere(clients)


# ---------------------------------------------------------------- A23

def test_A23_saisie_hors_connexion_visible_localement():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    bob.insert(5, "!")
    assert bob.content == "Hello!", f"attendu 'Hello!' chez bob hors connexion, obtenu {bob.content!r}"
    net.deliver_all()
    assert bob.content == "Hello!", f"attendu 'Hello!' toujours, obtenu {bob.content!r}"
    assert alice.content == "Hello", f"attendu 'Hello' chez alice tant que bob est hors connexion, obtenu {alice.content!r}"


# ---------------------------------------------------------------- A24

def test_A24_indicateur_d_attente_hors_connexion():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    assert bob.pending_sync is False, f"attendu aucune attente au départ, obtenu {bob.pending_sync!r}"
    bob.disconnect()
    bob.insert(5, "!")
    net.deliver_all()
    assert bob.pending_sync is True, f"attendu attente affichée, obtenu {bob.pending_sync!r}"


# ---------------------------------------------------------------- A25

def test_A25_indicateur_disparait_a_la_reconnexion():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    bob.insert(5, "!")
    bob.reconnect()
    net.deliver_all()
    assert bob.pending_sync is False, f"attendu attente disparue, obtenu {bob.pending_sync!r}"


# ---------------------------------------------------------------- A26

def test_A26_modifications_en_attente_publiees_a_la_reconnexion():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.disconnect()
    bob.insert(5, " world")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    same_everywhere([alice, bob, carol], "Hello world")


def test_A26_fusion_avec_les_editions_faites_pendant_l_absence():
    for seed in range(10):
        net, server = make("Hello world", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        bob.disconnect()
        bob.insert(0, "Oh, ")           # "Oh, Hello world"
        bob.delete(9, 6)                # retire " world" -> "Oh, Hello"
        alice.insert(5, " dear")        # "Hello dear world"
        net.deliver_all(seed=seed)
        bob.reconnect()
        net.deliver_all(seed=seed + 100)
        same_everywhere([alice, bob, carol], "Oh, Hello dear")


def test_A26_longue_divergence_hors_connexion():
    for seed in range(6):
        rng = random.Random(seed)
        net, server = make("", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        gen = unique_chars()
        inserted, deleted = set(), set()
        bob.disconnect()
        for _ in range(40):
            c = rng.choice((alice, bob))
            if c.content and rng.random() < 0.3:
                pos = rng.randrange(len(c.content))
                deleted.add(c.content[pos])
                c.delete(pos, 1)
            else:
                ch = next(gen)
                inserted.add(ch)
                c.insert(rng.randint(0, len(c.content)), ch)
            net.deliver(2, seed=rng.randrange(10**6))
        bob.reconnect()
        net.deliver_all(seed=seed)
        result = same_everywhere([alice, bob])
        assert set(result) == inserted - deleted, (
            f"seed={seed} : manquants={(inserted - deleted) - set(result)!r}, "
            f"en trop={set(result) - (inserted - deleted)!r}"
        )


# ---------------------------------------------------------------- A27

def test_A27_retrograde_hors_connexion_ses_modifications_ne_passent_pas():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.disconnect()
    attempt(lambda: bob.insert(5, "XYZ"))
    alice.set_permission("bob", "read")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    for c in (alice, carol):
        assert "XYZ" not in c.content, f"attendu aucune trace de 'XYZ', obtenu {c.content!r}"
        assert c.content == "Hello", f"attendu 'Hello', obtenu {c.content!r}"


def test_A27_trou_contenu_local_rejete():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    attempt(lambda: bob.insert(5, "XYZ"))
    alice.set_permission("bob", "read")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    assert bob.content == "Hello", f"attendu 'Hello' chez bob après rejet, obtenu {bob.content!r}"
    assert bob.pending_sync is False, f"attendu plus aucune attente, obtenu {bob.pending_sync!r}"


# ---------------------------------------------------------------- A28

def test_A28_proprietaire_retrograde_en_lecture():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    assert alice.permission_of("bob") == "write", f"attendu 'write' au départ, obtenu {alice.permission_of('bob')!r}"
    alice.set_permission("bob", "read")
    net.deliver_all()
    assert alice.permission_of("bob") == "read", f"attendu 'read', obtenu {alice.permission_of('bob')!r}"
    assert carol.permission_of("bob") == "read", f"attendu 'read' chez carol, obtenu {carol.permission_of('bob')!r}"


def test_A28_trou_affichee_chez_le_concerne():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.set_permission("bob", "read")
    net.deliver_all()
    assert bob.permission_of("bob") == "read", f"attendu 'read' chez bob, obtenu {bob.permission_of('bob')!r}"


# ---------------------------------------------------------------- A29

def test_A29_non_proprietaire_ne_change_pas_la_permission_d_autrui():
    net, server = make("Hello", writers=("bob", "dave"), readers=("carol",))
    alice, bob, carol, dave = open_all(net, server, "alice", "bob", "carol", "dave")
    attempt(lambda: bob.set_permission("carol", "write"))
    attempt(lambda: bob.set_permission("dave", "read"))
    net.deliver_all()
    for viewer in (alice, bob, carol):
        assert viewer.permission_of("carol") == "read", f"attendu 'read' pour carol, obtenu {viewer.permission_of('carol')!r}"
        assert viewer.permission_of("dave") == "write", f"attendu 'write' pour dave, obtenu {viewer.permission_of('dave')!r}"
    attempt(lambda: carol.insert(0, "X"))
    net.deliver_all()
    same_everywhere([alice, bob, carol, dave], "Hello")


def test_A29_trou_auto_promotion():
    net, server = make("Hello", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    attempt(lambda: carol.set_permission("carol", "write"))
    net.deliver_all()
    assert alice.permission_of("carol") == "read", f"attendu 'read', obtenu {alice.permission_of('carol')!r}"
    attempt(lambda: carol.insert(0, "X"))
    net.deliver_all()
    same_everywhere([alice, carol], "Hello")


# ---------------------------------------------------------------- A30

def test_A30_enregistrer_ajoute_une_entree():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    before = len(bob.history)
    bob.save_version()
    net.deliver_all()
    assert len(bob.history) == before + 1, f"attendu {before + 1} entrées, obtenu {len(bob.history)}"


def test_A30_trou_historique_partage():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    before = len(alice.history)
    bob.save_version()
    net.deliver_all()
    assert len(alice.history) == before + 1, f"attendu {before + 1} entrées chez alice, obtenu {len(alice.history)}"


# ---------------------------------------------------------------- A31

def test_A31_lecteur_n_enregistre_pas():
    net, server = make("Hello", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    before_a, before_c = len(alice.history), len(carol.history)
    attempt(carol.save_version)
    net.deliver_all()
    assert len(alice.history) == before_a, f"attendu {before_a} entrées chez alice, obtenu {len(alice.history)}"
    assert len(carol.history) == before_c, f"attendu {before_c} entrées chez carol, obtenu {len(carol.history)}"


# ---------------------------------------------------------------- A32

def test_A32_entree_porte_le_nom_de_l_auteur():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.save_version()
    net.deliver_all()
    assert bob.history[-1].author == "bob", f"attendu 'bob', obtenu {bob.history[-1].author!r}"
    alice.save_version()
    net.deliver_all()
    assert alice.history[-1].author == "alice", f"attendu 'alice', obtenu {alice.history[-1].author!r}"


# ---------------------------------------------------------------- A33

def test_A33_consulter_une_version_ne_change_pas_le_contenu():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.save_version()
    net.deliver_all()
    index = len(alice.history) - 1
    alice.insert(5, " world")
    net.deliver_all()
    bob.view_version(index)
    alice.view_version(index)
    assert bob.content == "Hello world", f"attendu 'Hello world' chez bob, obtenu {bob.content!r}"
    net.deliver_all()
    same_everywhere([alice, bob], "Hello world")


# ---------------------------------------------------------------- A34

def _saved_then_edited(writers=("bob",), readers=()):
    net, server = make("Hello", writers=writers, readers=readers)
    clients = open_all(net, server, "alice", *writers, *readers)
    alice = clients[0]
    alice.save_version()
    net.deliver_all()
    index = len(alice.history) - 1
    alice.insert(5, " world")
    net.deliver_all()
    return net, clients, index


def test_A34_restaurer_rend_le_contenu_de_la_version():
    net, (alice, bob), index = _saved_then_edited()
    bob.restore_version(index)
    assert bob.content == "Hello", f"attendu 'Hello' chez bob, obtenu {bob.content!r}"


# ---------------------------------------------------------------- A35

def test_A35_lecteur_ne_restaure_pas():
    net, (alice, bob, carol), index = _saved_then_edited(readers=("carol",))
    attempt(lambda: carol.restore_version(index))
    assert carol.content == "Hello world", f"attendu 'Hello world' chez carol, obtenu {carol.content!r}"
    net.deliver_all()
    same_everywhere([alice, bob, carol], "Hello world")


# ---------------------------------------------------------------- A36

def test_A36_restauration_visible_chez_les_autres():
    net, (alice, bob, carol), index = _saved_then_edited(readers=("carol",))
    bob.restore_version(index)
    net.deliver_all()
    same_everywhere([alice, bob, carol], "Hello")


def test_A36_trou_restauration_concurrente():
    for seed in range(10):
        net, (alice, bob), index = _saved_then_edited()
        alice.restore_version(index)
        bob.insert(0, "Z")
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob])


# ---------------------------------------------------------------- A37

def test_A37_restaurer_ajoute_une_entree():
    net, (alice, bob), index = _saved_then_edited()
    before = len(bob.history)
    bob.restore_version(index)
    net.deliver_all()
    assert len(bob.history) == before + 1, f"attendu {before + 1} entrées, obtenu {len(bob.history)}"


def test_A37_trou_auteur_de_la_restauration():
    net, (alice, bob), index = _saved_then_edited()
    bob.restore_version(index)
    net.deliver_all()
    assert alice.history[-1].author == "bob", f"attendu 'bob', obtenu {alice.history[-1].author!r}"


# ---------------------------------------------------------------- A38

def test_A38_annuler_une_restauration():
    net, (alice, bob), index = _saved_then_edited()
    bob.restore_version(index)
    net.deliver_all()
    bob.undo()
    assert bob.content == "Hello world", f"attendu 'Hello world' chez bob, obtenu {bob.content!r}"
    net.deliver_all()
    same_everywhere([alice, bob], "Hello world")


def test_A38_trou_annuler_restauration_apres_modification_d_autrui():
    net, (alice, bob), index = _saved_then_edited()
    bob.restore_version(index)
    net.deliver_all()
    alice.insert(0, "Z")
    net.deliver_all()
    bob.undo()
    net.deliver_all()
    result = same_everywhere([alice, bob])
    assert "Z" in result and result.replace("Z", "", 1) == "Hello world", (
        f"attendu 'Hello world' plus le 'Z' d'alice, obtenu {result!r}"
    )
