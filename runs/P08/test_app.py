"""Tests rouges de la sonde P08 — éditeur collaboratif simulé en mémoire.

Interface publique fixée par ces tests (module `app`) :

    server = app.Server()
    doc_id = server.create_document(owner="alice")      # document vide, "alice" propriétaire
    client = server.open(doc_id, "bob")                  # ouvre une session -> Client

    Client :
        .text                      -> str, texte vu par ce client
        .insert(position, chaine)  -> taper (un caractère = chaîne d'un caractère, un mot = une chaîne)
        .delete(position, longueur)
        .undo()
        .undo_count()              -> int, nombre d'entrées de la pile d'annulation de ce client
        .go_offline() / .go_online()
        .close()
        .presence()                -> collection des noms d'utilisateurs présents, vue par ce client
        .move_cursor(position)
        .cursors()                 -> dict {nom: position} des curseurs des AUTRES utilisateurs
        .save_version()
        .versions()                -> list de Version (plus ancienne d'abord), Version a .id, .author, .text
        .view_version(version_id)  -> str, texte de la version (consultation)
        .restore_version(version_id)
        .set_permission(nom, "write" | "read")
        .permission_of(nom)        -> "owner" | "write" | "read"

    server.sync() : livre tous les messages en attente entre le serveur et les clients connectés,
                    jusqu'à stabilisation. Aucune propagation n'a lieu sans sync().

Une action refusée (permission) peut lever une exception ou être ignorée silencieusement :
les tests ne tranchent pas (voir lacunes.md) et n'observent que l'effet.
"""

import pytest

import app


# ---------------------------------------------------------------- helpers

def attempt(fn, *args, **kwargs):
    """Exécute une action qui peut être refusée ; seul l'effet observable compte."""
    try:
        fn(*args, **kwargs)
    except Exception:
        pass


@pytest.fixture
def setup():
    """alice propriétaire, bob en écriture, carol en lecture ; tous ouverts et synchronisés."""
    server = app.Server()
    doc = server.create_document(owner="alice")
    alice = server.open(doc, "alice")
    alice.set_permission("bob", "write")
    alice.set_permission("carol", "read")
    server.sync()
    bob = server.open(doc, "bob")
    carol = server.open(doc, "carol")
    server.sync()
    return server, doc, alice, bob, carol


def seeded(setup, text="hello world"):
    server, doc, alice, bob, carol = setup
    alice.insert(0, text)
    server.sync()
    assert alice.text == text, f"pré-condition : attendu {text!r} chez alice, obtenu {alice.text!r}"
    assert bob.text == text, f"pré-condition : attendu {text!r} chez bob, obtenu {bob.text!r}"
    return server, doc, alice, bob, carol


# ---------------------------------------------------------------- permissions & frappe

def test_A01_writer_types_character_appears(setup):
    server, doc, alice, bob, carol = setup
    bob.insert(0, "x")
    assert bob.text == "x", f"attendu 'x' chez bob (écriture), obtenu {bob.text!r}"
    server.sync()
    assert alice.text == "x", f"attendu 'x' chez alice après sync, obtenu {alice.text!r}"


def test_A02_reader_types_character_text_unchanged(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc")
    attempt(carol.insert, 1, "x")
    assert carol.text == "abc", f"lecteur : attendu 'abc' localement, obtenu {carol.text!r}"
    server.sync()
    assert alice.text == "abc", f"lecteur : attendu 'abc' chez alice, obtenu {alice.text!r}"
    assert carol.text == "abc", f"lecteur : attendu 'abc' après sync, obtenu {carol.text!r}"


def test_A03_owner_types_character_appears(setup):
    server, doc, alice, bob, carol = setup
    alice.insert(0, "z")
    assert alice.text == "z", f"propriétaire : attendu 'z', obtenu {alice.text!r}"
    server.sync()
    assert bob.text == "z", f"attendu 'z' chez bob après sync, obtenu {bob.text!r}"


def test_A03_owner_permission_is_owner(setup):
    server, doc, alice, bob, carol = setup
    assert alice.permission_of("alice") == "owner", \
        f"attendu 'owner', obtenu {alice.permission_of('alice')!r}"


# ---------------------------------------------------------------- connexion & synchronisation

def test_A04_connected_insert_seen_by_other(setup):
    server, doc, alice, bob, carol = setup
    alice.insert(0, "bonjour")
    server.sync()
    assert "bonjour" in bob.text, f"attendu 'bonjour' chez bob, obtenu {bob.text!r}"


def test_A05_offline_insert_not_seen_by_other(setup):
    server, doc, alice, bob, carol = setup
    alice.go_offline()
    alice.insert(0, "secret")
    server.sync()
    assert "secret" not in bob.text, f"bob ne doit pas voir 'secret', obtenu {bob.text!r}"
    assert alice.text == "secret", f"alice doit voir son mot localement, obtenu {alice.text!r}"


def test_A06_reconnect_delivers_offline_insert(setup):
    server, doc, alice, bob, carol = setup
    alice.go_offline()
    alice.insert(0, "retard")
    server.sync()
    alice.go_online()
    server.sync()
    assert "retard" in bob.text, f"attendu 'retard' chez bob après reconnexion, obtenu {bob.text!r}"


def test_A06_reconnect_merges_with_concurrent_edit(setup):
    server, doc, alice, bob, carol = seeded(setup, "base")
    alice.go_offline()
    alice.insert(4, " hors")
    bob.insert(0, "debut ")
    server.sync()
    alice.go_online()
    server.sync()
    for name, c in (("alice", alice), ("bob", bob)):
        assert "hors" in c.text and "debut" in c.text, \
            f"{name} : attendu 'hors' et 'debut' dans le texte, obtenu {c.text!r}"


def test_A07_concurrent_insert_same_position_keeps_both(setup):
    server, doc, alice, bob, carol = seeded(setup, "ab")
    alice.insert(1, "PIM")
    bob.insert(1, "POM")
    server.sync()
    for name, c in (("alice", alice), ("bob", bob), ("carol", carol)):
        assert "PIM" in c.text and "POM" in c.text, \
            f"{name} : attendu 'PIM' et 'POM', obtenu {c.text!r}"
        assert c.text.startswith("a") and c.text.endswith("b"), \
            f"{name} : les mots doivent être entre 'a' et 'b', obtenu {c.text!r}"


def test_A07_concurrent_insert_at_start_of_empty_doc(setup):
    server, doc, alice, bob, carol = setup
    alice.insert(0, "UN")
    bob.insert(0, "DEUX")
    server.sync()
    assert "UN" in alice.text and "DEUX" in alice.text, f"obtenu {alice.text!r}"
    assert len(alice.text) == 6, f"attendu 6 caractères, obtenu {alice.text!r}"


def test_A08_delete_paragraph_keeps_concurrent_insert_elsewhere(setup):
    server, doc, alice, bob, carol = seeded(setup, "premier\nsecond")
    alice.delete(0, len("premier\n"))
    bob.insert(len("premier\nsec"), "MOT")
    server.sync()
    for name, c in (("alice", alice), ("bob", bob)):
        assert "MOT" in c.text, f"{name} : 'MOT' doit rester, obtenu {c.text!r}"
        assert "premier" not in c.text, f"{name} : le paragraphe supprimé doit disparaître, obtenu {c.text!r}"
        assert c.text == "secMOTond", f"{name} : attendu 'secMOTond', obtenu {c.text!r}"


def test_A09_synced_texts_identical_after_concurrent_edits(setup):
    server, doc, alice, bob, carol = seeded(setup, "le chat dort")
    alice.insert(3, "gros ")
    bob.delete(8, 4)
    bob.insert(8, "mange")
    alice.delete(0, 3)
    server.sync()
    assert alice.text == bob.text == carol.text, \
        f"divergence : alice={alice.text!r} bob={bob.text!r} carol={carol.text!r}"


def test_A09_identical_after_offline_divergence(setup):
    server, doc, alice, bob, carol = seeded(setup, "abcdef")
    bob.go_offline()
    bob.delete(1, 3)
    bob.insert(0, "X")
    alice.insert(3, "Y")
    alice.delete(5, 1)
    server.sync()
    bob.go_online()
    server.sync()
    assert alice.text == bob.text == carol.text, \
        f"divergence : alice={alice.text!r} bob={bob.text!r} carol={carol.text!r}"


# ---------------------------------------------------------------- présence

def test_A10_open_appears_in_presence(setup):
    server, doc, alice, bob, carol = setup
    alice.set_permission("dave", "write")
    dave = server.open(doc, "dave")
    server.sync()
    assert "dave" in alice.presence(), f"attendu 'dave' dans la présence, obtenu {alice.presence()!r}"


def test_A10_not_present_before_opening(setup):
    server, doc, alice, bob, carol = setup
    alice.set_permission("dave", "write")
    server.sync()
    assert "dave" not in alice.presence(), \
        f"'dave' n'a pas ouvert le document, obtenu {alice.presence()!r}"


def test_A11_close_disappears_from_presence(setup):
    server, doc, alice, bob, carol = setup
    assert "bob" in alice.presence(), f"pré-condition, obtenu {alice.presence()!r}"
    bob.close()
    server.sync()
    assert "bob" not in alice.presence(), f"'bob' a fermé, obtenu {alice.presence()!r}"


def test_A12_connection_loss_disappears_from_presence(setup):
    server, doc, alice, bob, carol = setup
    bob.go_offline()
    server.sync()
    assert "bob" not in alice.presence(), f"'bob' hors connexion, obtenu {alice.presence()!r}"


def test_A12_reconnection_reappears_in_presence(setup):
    server, doc, alice, bob, carol = setup
    bob.go_offline()
    server.sync()
    bob.go_online()
    server.sync()
    assert "bob" in alice.presence(), f"'bob' reconnecté, obtenu {alice.presence()!r}"


def test_A13_reader_open_appears_in_presence(setup):
    server, doc, alice, bob, carol = setup
    assert "carol" in alice.presence(), f"'carol' (lecture) attendue, obtenu {alice.presence()!r}"


# ---------------------------------------------------------------- curseurs

def test_A14_cursor_move_seen_at_new_position(setup):
    server, doc, alice, bob, carol = seeded(setup, "hello world")
    bob.move_cursor(3)
    server.sync()
    assert alice.cursors().get("bob") == 3, f"attendu 3, obtenu {alice.cursors()!r}"
    bob.move_cursor(7)
    server.sync()
    assert alice.cursors().get("bob") == 7, f"attendu 7, obtenu {alice.cursors()!r}"


def test_A15_offline_cursor_move_not_seen(setup):
    server, doc, alice, bob, carol = seeded(setup, "hello world")
    bob.move_cursor(2)
    server.sync()
    bob.go_offline()
    bob.move_cursor(9)
    server.sync()
    assert alice.cursors().get("bob") != 9, \
        f"le déplacement hors connexion ne doit pas être vu, obtenu {alice.cursors()!r}"


def test_A16_cursor_carries_user_name(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc")
    bob.move_cursor(1)
    server.sync()
    cursors = alice.cursors()
    assert "bob" in cursors, f"attendu un curseur nommé 'bob', obtenu {cursors!r}"
    assert cursors["bob"] == 1, f"attendu position 1 pour 'bob', obtenu {cursors!r}"


def test_A17_insert_before_cursor_keeps_same_character(setup):
    server, doc, alice, bob, carol = seeded(setup, "hello world")
    bob.move_cursor(6)  # devant 'w'
    server.sync()
    alice.insert(0, "big ")
    server.sync()
    pos = alice.cursors().get("bob")
    assert pos is not None, f"curseur de bob absent : {alice.cursors()!r}"
    assert alice.text[pos] == "w", \
        f"attendu le curseur devant 'w', position {pos} dans {alice.text!r}"
    assert pos == 10, f"attendu position 10, obtenu {pos}"


def test_A17_concurrent_insert_before_cursor(setup):
    server, doc, alice, bob, carol = seeded(setup, "hello world")
    alice.insert(0, ">> ")
    bob.move_cursor(6)  # devant 'w' dans la version de bob, concurremment
    server.sync()
    pos = alice.cursors().get("bob")
    assert pos is not None and alice.text[pos] == "w", \
        f"attendu le curseur de bob devant 'w', obtenu {pos} dans {alice.text!r}"


def test_A18_close_removes_cursor(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc")
    bob.move_cursor(2)
    server.sync()
    bob.close()
    server.sync()
    assert "bob" not in alice.cursors(), f"curseur de bob encore affiché : {alice.cursors()!r}"


def test_A19_own_cursor_not_among_others(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc")
    alice.move_cursor(1)
    bob.move_cursor(2)
    server.sync()
    assert "alice" not in alice.cursors(), f"alice voit son propre curseur : {alice.cursors()!r}"
    assert "bob" in alice.cursors(), f"alice doit voir bob : {alice.cursors()!r}"


# ---------------------------------------------------------------- annulation

def test_A20_undo_right_after_typing_removes_word(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc ")
    alice.insert(4, "mot")
    alice.undo()
    assert alice.text == "abc ", f"attendu 'abc ', obtenu {alice.text!r}"


def test_A21_undo_does_not_remove_other_users_change(setup):
    server, doc, alice, bob, carol = seeded(setup, "x")
    alice.insert(1, "A")
    server.sync()
    bob.insert(0, "BBB")
    server.sync()
    alice.undo()
    server.sync()
    assert "BBB" in alice.text, f"la modif de bob doit rester, obtenu {alice.text!r}"
    assert "BBB" in bob.text, f"la modif de bob doit rester chez bob, obtenu {bob.text!r}"


def test_A21_undo_with_only_other_users_change(setup):
    server, doc, alice, bob, carol = setup
    bob.insert(0, "BBB")
    server.sync()
    attempt(alice.undo)
    server.sync()
    assert alice.text == "BBB", f"attendu 'BBB', obtenu {alice.text!r}"


def test_A22_undo_empty_stack_text_unchanged(setup):
    server, doc, alice, bob, carol = setup
    assert alice.undo_count() == 0, f"pré-condition : pile vide, obtenu {alice.undo_count()}"
    attempt(alice.undo)
    assert alice.text == "", f"attendu '', obtenu {alice.text!r}"
    assert alice.undo_count() == 0, f"attendu 0, obtenu {alice.undo_count()}"


def test_A22_undo_beyond_stack_text_unchanged(setup):
    server, doc, alice, bob, carol = setup
    alice.insert(0, "un")
    alice.undo()
    attempt(alice.undo)
    attempt(alice.undo)
    assert alice.text == "", f"attendu '', obtenu {alice.text!r}"


def test_A23_reader_undo_text_unchanged(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc")
    attempt(carol.undo)
    server.sync()
    assert carol.text == "abc" and alice.text == "abc", \
        f"attendu 'abc' partout, obtenu carol={carol.text!r} alice={alice.text!r}"


def test_A23_demoted_reader_undo_text_unchanged(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc")
    bob.insert(3, "def")
    server.sync()
    alice.set_permission("bob", "read")
    server.sync()
    attempt(bob.undo)
    server.sync()
    assert alice.text == "abcdef", f"attendu 'abcdef' chez alice, obtenu {alice.text!r}"
    assert bob.text == "abcdef", f"attendu 'abcdef' chez bob, obtenu {bob.text!r}"


def test_A24_undo_propagates_to_other(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc ")
    alice.insert(4, "mot")
    server.sync()
    assert "mot" in bob.text, f"pré-condition, obtenu {bob.text!r}"
    alice.undo()
    server.sync()
    assert "mot" not in bob.text, f"bob doit voir 'mot' disparaître, obtenu {bob.text!r}"
    assert bob.text == "abc ", f"attendu 'abc ', obtenu {bob.text!r}"


def test_A25_typing_word_adds_one_undo_entry(setup):
    server, doc, alice, bob, carol = setup
    before = alice.undo_count()
    alice.insert(0, "mot")
    assert alice.undo_count() == before + 1, \
        f"attendu {before + 1}, obtenu {alice.undo_count()}"


def test_A26_other_user_typing_does_not_change_my_stack(setup):
    server, doc, alice, bob, carol = setup
    alice.insert(0, "a")
    server.sync()
    before = alice.undo_count()
    bob.insert(0, "mot")
    server.sync()
    assert alice.undo_count() == before, f"attendu {before}, obtenu {alice.undo_count()}"


# ---------------------------------------------------------------- versions

def test_A27_writer_saves_version(setup):
    server, doc, alice, bob, carol = seeded(setup, "v1")
    before = len(bob.versions())
    bob.save_version()
    server.sync()
    assert len(bob.versions()) == before + 1, f"attendu {before + 1}, obtenu {len(bob.versions())}"
    assert len(alice.versions()) == before + 1, \
        f"alice doit voir la version, attendu {before + 1}, obtenu {len(alice.versions())}"
    assert bob.versions()[-1].text == "v1", f"attendu 'v1', obtenu {bob.versions()[-1].text!r}"


def test_A28_reader_cannot_save_version(setup):
    server, doc, alice, bob, carol = seeded(setup, "v1")
    before = len(alice.versions())
    attempt(carol.save_version)
    server.sync()
    assert len(alice.versions()) == before, f"attendu {before}, obtenu {len(alice.versions())}"
    assert len(carol.versions()) == before, f"attendu {before}, obtenu {len(carol.versions())}"


def test_A29_each_version_shows_author(setup):
    server, doc, alice, bob, carol = seeded(setup, "v1")
    alice.save_version()
    bob.insert(0, "x")
    bob.save_version()
    server.sync()
    authors = [v.author for v in alice.versions()]
    assert authors[-2:] == ["alice", "bob"], f"attendu ['alice', 'bob'], obtenu {authors!r}"
    assert all(isinstance(a, str) and a for a in authors), f"auteur manquant : {authors!r}"


def test_A30_view_old_version_current_text_unchanged(setup):
    server, doc, alice, bob, carol = seeded(setup, "ancien")
    alice.save_version()
    vid = alice.versions()[-1].id
    alice.delete(0, 6)
    alice.insert(0, "nouveau")
    server.sync()
    shown = alice.view_version(vid)
    assert shown == "ancien", f"consultation : attendu 'ancien', obtenu {shown!r}"
    assert alice.text == "nouveau", f"texte courant : attendu 'nouveau', obtenu {alice.text!r}"
    server.sync()
    assert bob.text == "nouveau", f"chez bob : attendu 'nouveau', obtenu {bob.text!r}"


def _two_versions(setup):
    server, doc, alice, bob, carol = seeded(setup, "ancien")
    alice.save_version()
    old_id = alice.versions()[-1].id
    alice.delete(0, 6)
    alice.insert(0, "nouveau")
    alice.save_version()
    new_id = alice.versions()[-1].id
    server.sync()
    return server, doc, alice, bob, carol, old_id, new_id


def test_A31_writer_restores_old_version(setup):
    server, doc, alice, bob, carol, old_id, new_id = _two_versions(setup)
    bob.restore_version(old_id)
    assert bob.text == "ancien", f"attendu 'ancien', obtenu {bob.text!r}"


def test_A32_reader_cannot_restore(setup):
    server, doc, alice, bob, carol, old_id, new_id = _two_versions(setup)
    attempt(carol.restore_version, old_id)
    server.sync()
    assert alice.text == "nouveau", f"attendu 'nouveau', obtenu {alice.text!r}"
    assert carol.text == "nouveau", f"attendu 'nouveau', obtenu {carol.text!r}"


def test_A32_reader_restore_does_not_add_version(setup):
    server, doc, alice, bob, carol, old_id, new_id = _two_versions(setup)
    before = len(alice.versions())
    attempt(carol.restore_version, old_id)
    server.sync()
    assert len(alice.versions()) == before, f"attendu {before}, obtenu {len(alice.versions())}"


def test_A33_restore_propagates(setup):
    server, doc, alice, bob, carol, old_id, new_id = _two_versions(setup)
    alice.restore_version(old_id)
    server.sync()
    assert bob.text == "ancien", f"bob : attendu 'ancien', obtenu {bob.text!r}"
    assert carol.text == "ancien", f"carol : attendu 'ancien', obtenu {carol.text!r}"


def test_A34_restore_adds_version(setup):
    server, doc, alice, bob, carol, old_id, new_id = _two_versions(setup)
    before = len(alice.versions())
    alice.restore_version(old_id)
    server.sync()
    assert len(alice.versions()) == before + 1, f"attendu {before + 1}, obtenu {len(alice.versions())}"


def test_A35_restore_keeps_newer_versions(setup):
    server, doc, alice, bob, carol, old_id, new_id = _two_versions(setup)
    alice.restore_version(old_id)
    server.sync()
    ids = [v.id for v in alice.versions()]
    assert new_id in ids, f"la version récente {new_id!r} doit rester, obtenu {ids!r}"
    assert old_id in ids, f"la version restaurée {old_id!r} doit rester, obtenu {ids!r}"
    assert alice.view_version(new_id) == "nouveau", \
        f"attendu 'nouveau', obtenu {alice.view_version(new_id)!r}"


# ---------------------------------------------------------------- gestion des permissions

def test_A36_owner_demotes_writer_to_reader(setup):
    server, doc, alice, bob, carol = setup
    assert alice.permission_of("bob") == "write", f"pré-condition, obtenu {alice.permission_of('bob')!r}"
    alice.set_permission("bob", "read")
    server.sync()
    assert alice.permission_of("bob") == "read", f"attendu 'read', obtenu {alice.permission_of('bob')!r}"
    assert bob.permission_of("bob") == "read", f"bob : attendu 'read', obtenu {bob.permission_of('bob')!r}"


def test_A37_writer_cannot_change_permission(setup):
    server, doc, alice, bob, carol = setup
    alice.set_permission("dave", "write")
    dave = server.open(doc, "dave")
    server.sync()
    attempt(dave.set_permission, "bob", "read")
    server.sync()
    assert alice.permission_of("bob") == "write", f"attendu 'write', obtenu {alice.permission_of('bob')!r}"


def test_A37_writer_cannot_promote_reader(setup):
    server, doc, alice, bob, carol = setup
    attempt(bob.set_permission, "carol", "write")
    server.sync()
    assert alice.permission_of("carol") == "read", f"attendu 'read', obtenu {alice.permission_of('carol')!r}"


def test_A38_demoted_during_editing_cannot_type(setup):
    server, doc, alice, bob, carol = seeded(setup, "abc")
    bob.insert(3, "d")
    server.sync()
    alice.set_permission("bob", "read")
    server.sync()
    attempt(bob.insert, 0, "Z")
    server.sync()
    assert alice.text == "abcd", f"alice : attendu 'abcd', obtenu {alice.text!r}"
    assert bob.text == "abcd", f"bob : attendu 'abcd', obtenu {bob.text!r}"
