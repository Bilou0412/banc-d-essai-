"""Tests rouges de la sonde P08, deuxième attaque.

Même interface publique de `app` que tests/test_app.py (voir sa docstring).
Cibles : invariants observables pas à pas (une implémentation qui simule la fusion
par remplacement du texte entier fait disparaître puis réapparaître des caractères,
ou en réordonne), livraisons dans le désordre des messages non textuels (curseur,
présence, permissions, historique), connexion intermittente, annulation concurrente,
cas limites (document vide, non-ASCII, fin de document).
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
    values = [c.content for c in clients]
    assert all(v == values[0] for v in values), (
        f"répliques divergentes : attendu un contenu identique, obtenu {values!r}"
    )
    if expected is not None:
        assert values[0] == expected, f"attendu {expected!r}, obtenu {values[0]!r}"
    return values[0]


def unique_chars():
    k = 0
    while True:
        yield chr(0x4E00 + k)
        k += 1


def run_trace(seed, with_deletes, steps=80, flap=False):
    """Fuzz qui vérifie des invariants après CHAQUE action, sur chaque réplique :
    - aucun caractère dupliqué ;
    - l'ordre relatif de deux caractères présents avant et après ne change jamais ;
    - insertions seules : un caractère vu ne disparaît jamais ;
    - avec suppressions (sans annulation) : un caractère disparu ne réapparaît jamais.
    """
    rng = random.Random(seed)
    net, server = make("", writers=("bob", "carol"), readers=("dave",))
    clients = open_all(net, server, "alice", "bob", "carol", "dave")
    writers = clients[:3]
    names = ["alice", "bob", "carol", "dave"]
    gen = unique_chars()
    inserted, deleted = set(), set()
    prevs = [c.content for c in clients]
    gone = [set() for _ in clients]
    offline = set()

    def check(step):
        for i, c in enumerate(clients):
            now = c.content
            assert now is not None, f"seed={seed} pas={step} : contenu None chez {names[i]}"
            ns, ps = set(now), set(prevs[i])
            assert len(now) == len(ns), (
                f"seed={seed} pas={step} : caractère dupliqué chez {names[i]} : {now!r}"
            )
            a = [ch for ch in prevs[i] if ch in ns]
            b = [ch for ch in now if ch in ps]
            assert a == b, (
                f"seed={seed} pas={step} : ordre relatif modifié chez {names[i]} : "
                f"avant {a!r}, après {b!r}"
            )
            if not with_deletes:
                assert ps <= ns, (
                    f"seed={seed} pas={step} : caractères disparus chez {names[i]} "
                    f"sans aucune suppression : {ps - ns!r}"
                )
            else:
                back = ns & gone[i]
                assert not back, (
                    f"seed={seed} pas={step} : caractères supprimés réapparus chez "
                    f"{names[i]} : {back!r}"
                )
                gone[i] |= ps - ns
            prevs[i] = now

    for step in range(steps):
        r = rng.random()
        c = rng.choice(writers)
        if flap and r < 0.1:
            if c in offline:
                c.reconnect()
                offline.discard(c)
            else:
                c.disconnect()
                offline.add(c)
        elif r < 0.5 or (with_deletes and r < 0.65 and not c.content):
            text = "".join(next(gen) for _ in range(rng.randint(1, 3)))
            before = c.content
            pos = rng.randint(0, len(before))
            c.insert(pos, text)
            assert c.content == before[:pos] + text + before[pos:], (
                f"seed={seed} pas={step} : édition locale non immédiate : attendu "
                f"{before[:pos] + text + before[pos:]!r}, obtenu {c.content!r}"
            )
            inserted.update(text)
        elif with_deletes and r < 0.65:
            before = c.content
            pos = rng.randint(0, len(before) - 1)
            length = rng.randint(1, min(3, len(before) - pos))
            deleted.update(before[pos:pos + length])
            c.delete(pos, length)
        else:
            net.deliver(rng.randint(1, 4), seed=rng.randrange(10**6))
        check(step)
    for c in list(offline):
        c.reconnect()
    net.deliver_all(seed=seed)
    check("fin")
    return clients, inserted, deleted


# ---------------------------------------------------------------- invariants pas à pas

def test_A21_invariant_aucun_caractere_insere_ne_disparait_jamais():
    for seed in range(10):
        clients, inserted, _ = run_trace(seed, with_deletes=False)
        for c in clients:
            assert set(c.content) == inserted, (
                f"seed={seed} : manquants={inserted - set(c.content)!r}"
            )


def test_A05_invariant_un_passage_supprime_ne_reapparait_jamais():
    for seed in range(10):
        clients, inserted, deleted = run_trace(seed, with_deletes=True)
        result = same_everywhere(clients)
        assert set(result) == inserted - deleted, (
            f"seed={seed} : en trop={set(result) - (inserted - deleted)!r}, "
            f"manquants={(inserted - deleted) - set(result)!r}"
        )


def test_A26_fuzz_connexion_intermittente_invariants_et_convergence():
    for seed in range(10):
        clients, inserted, deleted = run_trace(seed, with_deletes=True, steps=100, flap=True)
        result = same_everywhere(clients)
        assert set(result) == inserted - deleted, (
            f"seed={seed} : en trop={set(result) - (inserted - deleted)!r}, "
            f"manquants={(inserted - deleted) - set(result)!r}"
        )
        for c in clients[:3]:
            assert c.pending_sync is False, (
                f"seed={seed} : attendu plus aucune attente après reconnexion, obtenu {c.pending_sync!r}"
            )


def test_A22_charge_soutenue_convergence():
    rng = random.Random(7)
    net, server = make("", writers=("bob", "carol"))
    clients = open_all(net, server, "alice", "bob", "carol")
    gen = unique_chars()
    inserted = set()
    for i in range(600):
        c = clients[i % 3]
        ch = next(gen)
        inserted.add(ch)
        c.insert(rng.randint(0, len(c.content)), ch)
        if i % 10 == 9:
            net.deliver(15, seed=rng.randrange(10**6))
    net.deliver_all(seed=1)
    result = same_everywhere(clients)
    assert set(result) == inserted and len(result) == 600, (
        f"attendu 600 caractères, obtenu {len(result)}"
    )


# ---------------------------------------------------------------- contenu : cas limites

def test_A04_document_vide_affiche_vide_et_non_absent():
    net, server = make("", readers=("carol",))
    alice, carol = open_all(net, server, "alice", "carol")
    assert carol.content == "", f"attendu '' chez carol (lecture), obtenu {carol.content!r}"
    assert alice.content == "", f"attendu '' chez alice, obtenu {alice.content!r}"


def test_A04_document_vide_apres_suppression_totale():
    net, server = make("Hello", readers=("carol",))
    (alice,) = open_all(net, server, "alice")
    alice.delete(0, 5)
    net.deliver_all()
    (carol,) = open_all(net, server, "carol")
    assert carol.content == "", f"attendu '' chez carol, obtenu {carol.content!r}"


def test_A03_document_vide_toujours_non_affiche():
    net, server = make("")
    alice, eve = open_all(net, server, "alice", "eve")
    assert eve.content is None, f"attendu None chez eve, obtenu {eve.content!r}"


def test_A01_non_ascii_et_fins_de_ligne():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.insert(5, "\r\n👍é")
        bob.insert(0, "日本")
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "日本Hello\r\n👍é")
        alice.delete(9, 1)  # retire l'emoji
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "日本Hello\r\né")


def test_A05_suppression_totale_concurrente_a_une_insertion():
    for seed in range(10):
        net, server = make("Hello world", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.delete(0, 11)
        bob.insert(5, "X")
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "X")


def test_A21_trou_frappe_caractere_par_caractere_non_entrelacee():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        for i, ch in enumerate("AAA"):
            alice.insert(5 + i, ch)
        for i, ch in enumerate("BBB"):
            bob.insert(5 + i, ch)
        net.deliver_all(seed=seed)
        result = same_everywhere([alice, bob])
        assert result in ("HelloAAABBB", "HelloBBBAAA"), (
            f"seed={seed} : attendu les deux saisies non entrelacées, obtenu {result!r}"
        )


# ---------------------------------------------------------------- connexion

def test_A26_message_en_vol_a_la_deconnexion_compte_une_seule_fois():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        bob.insert(5, "!")
        net.deliver(seed % 3, seed=seed)  # une partie seulement des messages part
        bob.disconnect()
        net.deliver_all(seed=seed)
        bob.reconnect()
        net.deliver_all(seed=seed + 1)
        same_everywhere([alice, bob, carol], "Hello!")
        assert bob.pending_sync is False, f"seed={seed} : attendu aucune attente, obtenu {bob.pending_sync!r}"


def test_A01_editions_manquees_pendant_la_deconnexion_rattrapees():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.insert(5, " world")
        bob.disconnect()            # le message vers bob était peut-être en vol
        net.deliver_all(seed=seed)
        alice.insert(0, "Oh ")
        net.deliver_all(seed=seed)
        bob.reconnect()
        net.deliver_all(seed=seed + 1)
        assert bob.content == "Oh Hello world", f"seed={seed} : attendu 'Oh Hello world' chez bob, obtenu {bob.content!r}"


def test_A26_reconnexion_double_et_deconnexion_double_sans_effet():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    bob.disconnect()
    bob.insert(5, "!")
    bob.reconnect()
    bob.reconnect()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello!")


def test_A26_trou_reconnexion_apres_longue_absence():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    bob.insert(5, " world")
    wait(net, 300)
    alice.insert(0, "Oh ")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    same_everywhere([alice, bob], "Oh Hello world")


def test_A24_trou_hors_connexion_sans_saisie():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    net.deliver_all()
    assert bob.pending_sync is False, f"attendu aucune attente sans saisie, obtenu {bob.pending_sync!r}"


def test_A14_annuler_hors_connexion_rien_ne_part():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    bob.insert(5, " world")
    bob.undo()
    assert bob.content == "Hello", f"attendu 'Hello' chez bob, obtenu {bob.content!r}"
    bob.reconnect()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")


# ---------------------------------------------------------------- présence et curseurs

def test_A07_ouverture_puis_fermeture_livrees_dans_le_desordre():
    for seed in range(15):
        net, server = make("Hello", writers=("bob",))
        (alice,) = open_all(net, server, "alice")
        bob = server.open("bob")
        bob.move_cursor(2)
        bob.close()
        net.deliver_all(seed=seed)
        assert "bob" not in alice.presence, (
            f"seed={seed} : attendu 'bob' absent après fermeture, obtenu {list(alice.presence)!r}"
        )


def test_A06_fermeture_puis_reouverture_livrees_dans_le_desordre():
    for seed in range(15):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        bob.close()
        server.open("bob")
        net.deliver_all(seed=seed)
        assert "bob" in alice.presence, (
            f"seed={seed} : attendu 'bob' présent après réouverture, obtenu {list(alice.presence)!r}"
        )


def test_A06_trou_reapparait_apres_reconnexion():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    wait(net, 300)
    bob.reconnect()
    net.deliver_all()
    assert "bob" in alice.presence, f"attendu 'bob' de retour, obtenu {list(alice.presence)!r}"


def test_A06_trou_sans_permission_apparait():
    net, server = make("Hello")
    alice, eve = open_all(net, server, "alice", "eve")
    assert "eve" in alice.presence, f"attendu 'eve' dans la présence, obtenu {list(alice.presence)!r}"


def test_A06_trou_double_onglet():
    net, server = make("Hello", writers=("bob",))
    alice, b1, b2 = open_all(net, server, "alice", "bob", "bob")
    b1.close()
    net.deliver_all()
    assert "bob" in alice.presence, (
        f"attendu 'bob' toujours présent (second onglet ouvert), obtenu {list(alice.presence)!r}"
    )


def test_A09_deplacements_livres_dans_le_desordre_le_dernier_gagne():
    for seed in range(15):
        net, server = make("Hello world", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        for p in (2, 5, 9):
            bob.move_cursor(p)
        net.deliver_all(seed=seed)
        for viewer in (alice, carol):
            assert viewer.remote_cursors.get("bob") == 9, (
                f"seed={seed} : attendu 9, obtenu {viewer.remote_cursors.get('bob')!r}"
            )


def test_A10_trou_fermeture_retire_le_curseur():
    net, server = make("Hello world", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.move_cursor(3)
    net.deliver_all()
    bob.close()
    net.deliver_all()
    assert "bob" not in alice.remote_cursors, f"attendu aucun curseur pour bob, obtenu {alice.remote_cursors!r}"


def test_A11_mon_curseur_apres_reconnexion():
    net, server = make("abcdef", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.move_cursor(3)
    net.deliver_all()
    bob.disconnect()
    alice.insert(0, "XX")
    alice.insert(1, "Y")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    assert bob.content == "XYXabcdef", f"attendu 'XYXabcdef', obtenu {bob.content!r}"
    assert bob.content[bob.cursor] == "d", f"attendu curseur devant 'd', obtenu {bob.cursor!r} dans {bob.content!r}"


def test_A12_trou_fuzz_curseur_distant_suit_son_caractere():
    for seed in range(8):
        rng = random.Random(seed)
        net, server = make("abcdef", writers=("bob", "carol"), readers=("dave",))
        alice, bob, carol, dave = open_all(net, server, "alice", "bob", "carol", "dave")
        gen = unique_chars()
        bob.move_cursor(3)  # devant 'd'
        for _ in range(30):
            c = rng.choice((alice, carol))
            if rng.random() < 0.6:
                c.insert(rng.randint(0, len(c.content)), next(gen))
            else:
                net.deliver(rng.randint(1, 3), seed=rng.randrange(10**6))
        net.deliver_all(seed=seed)
        for viewer in (alice, carol, dave):
            pos = viewer.remote_cursors.get("bob")
            assert pos is not None and viewer.content[pos] == "d", (
                f"seed={seed} : attendu curseur de bob devant 'd', obtenu {pos!r} dans {viewer.content!r}"
            )
        assert bob.content[bob.cursor] == "d", (
            f"seed={seed} : attendu le curseur de bob devant 'd' chez lui, obtenu {bob.cursor!r} dans {bob.content!r}"
        )


def test_A13_curseur_en_fin_de_document_et_suppression_de_la_fin():
    net, server = make("Hello world", writers=("bob", "carol"))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    bob.move_cursor(11)
    net.deliver_all()
    carol.delete(5, 6)
    net.deliver_all()
    assert alice.remote_cursors.get("bob") == 5, f"attendu 5, obtenu {alice.remote_cursors.get('bob')!r}"
    assert carol.remote_cursors.get("bob") == 5, f"attendu 5 chez carol, obtenu {carol.remote_cursors.get('bob')!r}"


# ---------------------------------------------------------------- annulation concurrente

def test_A14_annuler_avant_reception_d_une_insertion_concurrente():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.insert(5, " world")
        bob.insert(0, "Z")
        net.deliver(seed % 3, seed=seed)
        alice.undo()
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "ZHello")


def test_A15_annuler_pendant_une_insertion_d_autrui_en_vol():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.insert(5, " abc")
        net.deliver_all()
        bob.insert(7, "X")   # au milieu de la saisie d'alice, pas encore reçue
        alice.undo()
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "HelloX")


def test_A15_saisie_supprimee_par_autrui_puis_annulee():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.insert(5, "abc")
        net.deliver_all()
        bob.delete(3, 5)     # retire "loabc"
        if seed % 2:
            net.deliver_all()
        alice.undo()
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "Hel")


def test_A14_annulations_successives_une_par_saisie():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    for i in range(20):
        alice.insert(len(alice.content), chr(0x4E00 + i))
        net.deliver_all()
        if i == 10:
            bob.insert(0, "Z")
            net.deliver_all()
    for _ in range(20):
        alice.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "ZHello")


def test_A18_retablissements_successifs():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    typed = "".join(chr(0x4E00 + i) for i in range(10))
    for ch in typed:
        alice.insert(len(alice.content), ch)
        net.deliver_all()
    for _ in range(10):
        alice.undo()
    net.deliver_all()
    bob.insert(0, "Z")
    net.deliver_all()
    for _ in range(10):
        alice.redo()
    net.deliver_all()
    same_everywhere([alice, bob], "ZHello" + typed)


def test_A18_cycles_repetes_annuler_retablir_avec_saisie_concurrente():
    for seed in range(5):
        rng = random.Random(seed)
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.insert(5, " world")
        net.deliver_all()
        gen = unique_chars()
        bob_chars = set()
        for _ in range(50):
            alice.undo()
            ch = next(gen)
            bob_chars.add(ch)
            bob.insert(rng.randint(0, len(bob.content)), ch)
            net.deliver(rng.randint(0, 3), seed=rng.randrange(10**6))
            alice.redo()
            net.deliver(rng.randint(0, 3), seed=rng.randrange(10**6))
        net.deliver_all(seed=seed)
        result = same_everywhere([alice, bob])
        rest = "".join(ch for ch in result if ch not in bob_chars)
        assert rest == "Hello world", f"seed={seed} : attendu 'Hello world' hors saisies de bob, obtenu {rest!r}"
        assert set(bob_chars) <= set(result), f"seed={seed} : saisies de bob perdues dans {result!r}"


def test_A22_fuzz_convergence_avec_annulations():
    for seed in range(10):
        rng = random.Random(seed)
        net, server = make("", writers=("bob", "carol"), readers=("dave",))
        clients = open_all(net, server, "alice", "bob", "carol", "dave")
        writers, dave = clients[:3], clients[3]
        gen = unique_chars()
        inserted = set()
        for _ in range(80):
            c = rng.choice(writers)
            r = rng.random()
            if r < 0.4 or not c.content:
                text = "".join(next(gen) for _ in range(rng.randint(1, 2)))
                inserted.update(text)
                c.insert(rng.randint(0, len(c.content)), text)
            elif r < 0.55:
                pos = rng.randrange(len(c.content))
                c.delete(pos, rng.randint(1, min(2, len(c.content) - pos)))
            elif r < 0.7:
                c.undo()
            elif r < 0.75:
                c.redo()
            elif r < 0.78:
                attempt(dave.undo)
            else:
                net.deliver(rng.randint(1, 4), seed=rng.randrange(10**6))
        net.deliver_all(seed=seed)
        result = same_everywhere(clients)
        assert set(result) <= inserted, f"seed={seed} : caractères inconnus {set(result) - inserted!r}"


def test_A14_trou_annuler_une_suppression():
    net, server = make("Hello world", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.delete(5, 6)
    net.deliver_all()
    bob.insert(0, "Z")
    net.deliver_all()
    alice.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "ZHello world")


# ---------------------------------------------------------------- permissions

def test_A02_trou_sans_permission_ne_modifie_pas():
    net, server = make("Hello", writers=("bob",))
    alice, bob, eve = open_all(net, server, "alice", "bob", "eve")
    attempt(lambda: eve.insert(0, "X"))
    attempt(lambda: eve.delete(0, 2))
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")


def test_A03_permission_retiree_puis_reouverture():
    net, server = make("Hello secret", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.set_permission("bob", None)
    net.deliver_all()
    bob.close()
    net.deliver_all()
    (bob2,) = open_all(net, server, "bob")
    assert bob2.content is None, f"attendu None chez bob sans permission, obtenu {bob2.content!r}"


def test_A03_trou_historique_non_divulgue():
    net, server = make("Hello secret")
    (alice,) = open_all(net, server, "alice")
    alice.save_version()
    net.deliver_all()
    (eve,) = open_all(net, server, "eve")
    entries = attempt(lambda: list(eve.history)) or []
    leaked = [e for e in entries if getattr(e, "text", None) and "secret" in e.text]
    assert not leaked, f"attendu aucun texte de version visible par eve, obtenu {[e.text for e in leaked]!r}"


def test_A01_lecteur_promu_peut_ecrire():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    alice.set_permission("carol", "write")
    net.deliver_all()
    carol.insert(5, "!")
    net.deliver_all()
    assert bob.content == "Hello!", f"attendu 'Hello!' chez bob, obtenu {bob.content!r}"


def test_A29_non_proprietaire_ne_retrograde_pas_le_proprietaire():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    attempt(lambda: bob.set_permission("alice", "read"))
    attempt(lambda: bob.set_permission("alice", None))
    net.deliver_all()
    assert bob.permission_of("alice") == "write", f"attendu 'write' pour alice, obtenu {bob.permission_of('alice')!r}"
    alice.insert(5, "!")
    net.deliver_all()
    same_everywhere([alice, bob], "Hello!")


def test_A29_non_proprietaire_n_accorde_pas_l_acces_a_un_tiers():
    net, server = make("Hello secret", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    attempt(lambda: bob.set_permission("eve", "read"))
    net.deliver_all()
    assert alice.permission_of("eve") is None, f"attendu None pour eve, obtenu {alice.permission_of('eve')!r}"
    (eve,) = open_all(net, server, "eve")
    assert eve.content is None, f"attendu None chez eve, obtenu {eve.content!r}"


def test_A28_trou_changements_successifs_livres_dans_le_desordre():
    for seed in range(15):
        net, server = make("Hello", writers=("bob",), readers=("carol",))
        alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
        alice.set_permission("bob", "read")
        alice.set_permission("bob", "write")
        alice.set_permission("bob", "read")
        net.deliver_all(seed=seed)
        for viewer in (alice, bob, carol):
            assert viewer.permission_of("bob") == "read", (
                f"seed={seed} : attendu 'read', obtenu {viewer.permission_of('bob')!r}"
            )
        attempt(lambda: bob.insert(0, "X"))
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob, carol], "Hello")


def test_A28_trou_cible_hors_connexion():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    alice.set_permission("bob", "read")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    assert bob.permission_of("bob") == "read", f"attendu 'read' chez bob, obtenu {bob.permission_of('bob')!r}"


def test_A27_trou_repromu_ne_rejoue_pas():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    bob.disconnect()
    attempt(lambda: bob.insert(5, "XYZ"))
    alice.set_permission("bob", "read")
    net.deliver_all()
    bob.reconnect()
    net.deliver_all()
    alice.set_permission("bob", "write")
    net.deliver_all()
    bob.disconnect()
    bob.reconnect()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")
    bob.insert(0, "Q")
    net.deliver_all()
    same_everywhere([alice, bob], "QHello")


def test_A31_retrograde_n_enregistre_plus():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.set_permission("bob", "read")
    net.deliver_all()
    before = len(alice.history)
    attempt(bob.save_version)
    net.deliver_all()
    assert len(alice.history) == before, f"attendu {before} entrées, obtenu {len(alice.history)}"
    assert len(bob.history) == before, f"attendu {before} entrées chez bob, obtenu {len(bob.history)}"


def test_A35_retrograde_ne_restaure_plus():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.save_version()
    net.deliver_all()
    index = len(alice.history) - 1
    alice.insert(5, " world")
    alice.set_permission("bob", "read")
    net.deliver_all()
    attempt(lambda: bob.restore_version(index))
    assert bob.content == "Hello world", f"attendu 'Hello world' chez bob, obtenu {bob.content!r}"
    net.deliver_all()
    same_everywhere([alice, bob], "Hello world")


# ---------------------------------------------------------------- historique

def test_A30_enregistrements_sans_changement_ajoutent_chacun_une_entree():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    before = len(alice.history)
    alice.save_version()
    alice.save_version()
    net.deliver_all()
    assert len(alice.history) == before + 2, f"attendu {before + 2} entrées, obtenu {len(alice.history)}"
    assert len(bob.history) == before + 2, f"attendu {before + 2} entrées chez bob, obtenu {len(bob.history)}"


def test_A30_trou_historique_meme_ordre_partout():
    for seed in range(15):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        before = len(alice.history)
        alice.save_version()
        bob.save_version()
        net.deliver_all(seed=seed)
        ha = [(e.author, e.text) for e in alice.history]
        hb = [(e.author, e.text) for e in bob.history]
        assert len(ha) == before + 2, f"seed={seed} : attendu {before + 2} entrées, obtenu {len(ha)}"
        assert ha == hb, f"seed={seed} : historiques différents : alice={ha!r}, bob={hb!r}"


def test_A34_restaurer_plusieurs_versions_par_indice():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.save_version()
    net.deliver_all()
    i1 = len(alice.history) - 1
    alice.insert(5, " world")
    net.deliver_all()
    bob.save_version()
    net.deliver_all()
    i2 = len(bob.history) - 1
    alice.delete(0, 6)
    net.deliver_all()
    alice.save_version()
    net.deliver_all()
    i3 = len(alice.history) - 1
    for index, expected in ((i1, "Hello"), (i3, "world"), (i2, "Hello world"), (i1, "Hello")):
        bob.restore_version(index)
        assert bob.content == expected, f"indice {index} : attendu {expected!r}, obtenu {bob.content!r}"
        net.deliver_all()
        same_everywhere([alice, bob], expected)


def test_A34_restaurer_une_version_vide_et_non_ascii():
    net, server = make("", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.save_version()
    net.deliver_all()
    i_empty = len(alice.history) - 1
    alice.insert(0, "日本\r\n👍")
    net.deliver_all()
    alice.save_version()
    net.deliver_all()
    i_text = len(alice.history) - 1
    bob.restore_version(i_empty)
    net.deliver_all()
    same_everywhere([alice, bob], "")
    bob.restore_version(i_text)
    net.deliver_all()
    same_everywhere([alice, bob], "日本\r\n👍")


def test_A37_restaurer_une_version_identique_ajoute_une_entree():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.save_version()
    net.deliver_all()
    index = len(alice.history) - 1
    before = len(alice.history)
    bob.restore_version(index)
    net.deliver_all()
    assert len(alice.history) == before + 1, f"attendu {before + 1} entrées, obtenu {len(alice.history)}"
    assert alice.history[-1].author == "bob", f"attendu 'bob', obtenu {alice.history[-1].author!r}"


def test_A36_restauration_hors_connexion_publiee_a_la_reconnexion():
    net, server = make("Hello", writers=("bob",), readers=("carol",))
    alice, bob, carol = open_all(net, server, "alice", "bob", "carol")
    alice.save_version()
    net.deliver_all()
    index = len(alice.history) - 1
    alice.insert(5, " world")
    net.deliver_all()
    bob.disconnect()
    bob.restore_version(index)
    assert bob.content == "Hello", f"attendu 'Hello' chez bob hors connexion, obtenu {bob.content!r}"
    net.deliver_all()
    assert alice.content == "Hello world", f"attendu 'Hello world' chez alice, obtenu {alice.content!r}"
    bob.reconnect()
    net.deliver_all()
    same_everywhere([alice, bob, carol], "Hello")


def test_A38_annuler_une_restauration_concurrente_a_une_saisie_en_vol():
    for seed in range(10):
        net, server = make("Hello", writers=("bob",))
        alice, bob = open_all(net, server, "alice", "bob")
        alice.save_version()
        net.deliver_all()
        index = len(alice.history) - 1
        alice.insert(5, " world")
        net.deliver_all()
        bob.restore_version(index)
        bob.undo()
        assert bob.content == "Hello world", f"seed={seed} : attendu 'Hello world' chez bob, obtenu {bob.content!r}"
        net.deliver_all(seed=seed)
        same_everywhere([alice, bob], "Hello world")


def test_A38_trou_deux_annulations():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.save_version()
    net.deliver_all()
    index = len(alice.history) - 1
    bob.insert(5, " big")
    net.deliver_all()
    bob.restore_version(index)
    net.deliver_all()
    bob.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello big")
    bob.undo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")


def test_A18_trou_retablir_une_restauration():
    net, server = make("Hello", writers=("bob",))
    alice, bob = open_all(net, server, "alice", "bob")
    alice.save_version()
    net.deliver_all()
    index = len(alice.history) - 1
    alice.insert(5, " world")
    net.deliver_all()
    bob.restore_version(index)
    net.deliver_all()
    bob.undo()
    net.deliver_all()
    bob.redo()
    net.deliver_all()
    same_everywhere([alice, bob], "Hello")
