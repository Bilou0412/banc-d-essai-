"""Tests rouges — sonde P08 : édition collaborative à fusion réelle.

Interface publique fixée par ces tests (module `app`) :

    net = app.Network()
        net.flush(seed=None)   livre tous les messages en attente, y compris ceux produits
                               pendant la livraison, jusqu'à ce qu'il n'en reste aucun.
                               seed=None : ordre d'émission ; seed=int : ordre pseudo-aléatoire
                               (random.Random(seed)) — n'importe quel message, de n'importe quel
                               émetteur, peut passer avant n'importe quel autre.
        net.advance(seconds)   fait avancer l'horloge simulée (ne livre rien par elle-même).

    doc = app.Document(net, owner="alice", content="...")
        doc.open(name) -> Client   ouvre le document pour le participant `name`.
                                   Le propriétaire a la permission écriture.
                                   Les autres n'ont aucune permission tant que le propriétaire
                                   ne leur en a pas donné une.

    Client (une réplique par participant ; toute action est locale et immédiate,
    la propagation passe uniquement par le réseau) :
        .content            str affiché, ou None si le participant n'a pas accès
        .insert(pos, text)  insère `text` avant le caractère d'indice `pos`
        .delete(pos, length)
        .cursor             position de mon curseur (int)
        .move_cursor(pos)
        .remote_cursors     dict nom -> position, curseurs des autres participants connectés
        .presence           collection des noms des participants présents
        .undo() / .redo()
        .can_redo           bool : le rétablissement n'est pas vide
        .pending            bool : indicateur d'attente de synchronisation
        .disconnect()       perte de connexion (silencieuse : personne n'est prévenu)
        .reconnect()
        .close()            fermeture volontaire du document
        .set_permission(name, "write" | "read")
        .permission_of(name) -> "write" | "read" | None
        .save_version()
        .history            liste chronologique d'entrées ayant .id et .author
        .view_version(id) -> str   contenu de la version, sans toucher au document
        .restore_version(id)
"""
import random

import pytest

import app


SEEDS = [None, 1, 2, 3, 7, 42, 1234]


# ---------------------------------------------------------------- helpers

def wait(net, seconds):
    """Avance le temps seconde par seconde en laissant le réseau livrer entre deux pas."""
    for _ in range(int(seconds)):
        net.advance(1)
        net.flush()


def make(content="", writers=(), readers=(), owner="alice"):
    net = app.Network()
    doc = app.Document(net, owner=owner, content=content)
    clients = {owner: doc.open(owner)}
    net.flush()
    o = clients[owner]
    for w in writers:
        o.set_permission(w, "write")
    for r in readers:
        o.set_permission(r, "read")
    net.flush()
    for name in list(writers) + list(readers):
        clients[name] = doc.open(name)
    net.flush()
    return net, doc, clients


def all_equal(clients, expected=None):
    contents = {n: c.content for n, c in clients.items()}
    values = set(contents.values())
    assert len(values) == 1, f"répliques divergentes : {contents}"
    if expected is not None:
        assert values == {expected}, f"attendu {expected!r} partout, obtenu {contents}"


# ---------------------------------------------------------------- A01

def test_A01_insertion_visible_chez_autre_connecte_apres_livraison():
    net, doc, c = make("Hello", writers=["bob"], readers=["carol"])
    c["alice"].insert(5, " world")
    assert c["alice"].content == "Hello world", "l'édition locale doit être immédiate"
    assert "world" not in c["bob"].content, (
        "bob ne doit rien voir avant que le réseau ait livré : les répliques ne partagent pas d'état")
    net.flush()
    for n in ("bob", "carol"):
        assert "world" in c[n].content, f"{n} devrait voir l'insertion, obtenu {c[n].content!r}"


def test_A01_insertion_par_un_ecrivain_non_proprietaire():
    net, doc, c = make("Hello", writers=["bob"])
    c["bob"].insert(0, ">> ")
    net.flush()
    assert c["alice"].content == ">> Hello", f"obtenu {c['alice'].content!r}"


def test_A01_trou_positions_preservees():
    for seed in SEEDS:
        net, doc, c = make("Hello", writers=["bob"])
        c["alice"].insert(5, " world")
        c["bob"].insert(0, "Oh, ")
        net.flush(seed=seed)
        all_equal(c, "Oh, Hello world")


# ---------------------------------------------------------------- A02

def test_A02_lecteur_tape_contenu_inchange_localement_et_ailleurs():
    net, doc, c = make("Hello", readers=["carol"])
    c["carol"].insert(0, "XXX")
    assert c["carol"].content == "Hello", f"chez le lecteur : obtenu {c['carol'].content!r}"
    net.flush()
    all_equal(c, "Hello")


def test_A02_lecteur_supprime_contenu_inchange():
    net, doc, c = make("Hello", readers=["carol"])
    c["carol"].delete(0, 3)
    net.flush()
    all_equal(c, "Hello")


# ---------------------------------------------------------------- A03

def test_A03_sans_permission_contenu_non_affiche():
    net, doc, c = make("secret plan")
    eve = doc.open("eve")
    net.flush()
    assert eve.content in (None, ""), f"eve ne doit rien voir, obtenu {eve.content!r}"
    c["alice"].insert(0, "top ")
    net.flush()
    assert eve.content in (None, ""), f"eve ne doit pas recevoir les éditions, obtenu {eve.content!r}"


# ---------------------------------------------------------------- A04

def test_A04_lecteur_voit_contenu_courant_a_l_ouverture():
    net, doc, c = make("Hello")
    a = c["alice"]
    a.insert(5, " world")
    a.delete(0, 1)
    net.flush()
    a.set_permission("dan", "read")
    net.flush()
    dan = doc.open("dan")
    net.flush()
    assert dan.content == "ello world", f"obtenu {dan.content!r}"


# ---------------------------------------------------------------- A05

def test_A05_suppression_propagee():
    net, doc, c = make("Hello world", writers=["bob"])
    c["alice"].delete(5, 6)
    assert c["alice"].content == "Hello"
    net.flush()
    all_equal(c, "Hello")


@pytest.mark.parametrize("seed", SEEDS)
def test_A05_suppressions_concurrentes_du_meme_passage(seed):
    net, doc, c = make("Hello world", writers=["bob"])
    c["alice"].delete(5, 6)
    c["bob"].delete(5, 6)
    net.flush(seed=seed)
    all_equal(c, "Hello")


@pytest.mark.parametrize("seed", SEEDS)
def test_A05_trou_suppression_contre_insertion_concurrente_dedans(seed):
    net, doc, c = make("Hello world", writers=["bob"])
    c["alice"].delete(6, 5)          # supprime "world"
    c["bob"].insert(8, "ZZ")         # "Hello woZZrld"
    net.flush(seed=seed)
    all_equal(c, "Hello ZZ")


# ---------------------------------------------------------------- A06 / A07 / A08

def test_A06_ouverture_apparait_dans_presence():
    net, doc, c = make("x", writers=["bob"])
    assert "bob" in c["alice"].presence, f"présence chez alice : {c['alice'].presence!r}"
    assert "alice" in c["bob"].presence, f"présence chez bob : {c['bob'].presence!r}"


def test_A07_fermeture_disparait_de_presence():
    net, doc, c = make("x", writers=["bob", "carol"])
    c["bob"].close()
    net.flush()
    for n in ("alice", "carol"):
        assert "bob" not in c[n].presence, f"chez {n} : {c[n].presence!r}"
    assert "carol" in c["alice"].presence


def test_A08_trou_perte_connexion_disparait_de_presence():
    net, doc, c = make("x", writers=["bob", "carol"])
    c["bob"].disconnect()
    wait(net, 30)
    assert "bob" not in c["alice"].presence, f"chez alice : {c['alice'].presence!r}"
    assert "bob" not in c["carol"].presence, f"chez carol : {c['carol'].presence!r}"
    assert "carol" in c["alice"].presence, (
        "carol, connectée et inactive, ne doit pas disparaître de la présence")


def test_A08_participants_connectes_restent_presents_dans_la_duree():
    net, doc, c = make("x", writers=["bob"])
    wait(net, 120)
    assert "bob" in c["alice"].presence and "alice" in c["bob"].presence


# ---------------------------------------------------------------- A09 / A10

def test_A09_curseur_distant_suit_le_deplacement():
    net, doc, c = make("Hello world", writers=["bob"])
    c["bob"].move_cursor(4)
    net.flush()
    assert c["alice"].remote_cursors.get("bob") == 4, f"obtenu {c['alice'].remote_cursors!r}"
    c["bob"].move_cursor(9)
    net.flush()
    assert c["alice"].remote_cursors.get("bob") == 9, f"obtenu {c['alice'].remote_cursors!r}"


def test_A10_perte_connexion_curseur_distant_disparait():
    net, doc, c = make("Hello", writers=["bob"])
    c["bob"].move_cursor(2)
    net.flush()
    assert "bob" in c["alice"].remote_cursors
    c["bob"].disconnect()
    wait(net, 30)
    assert "bob" not in c["alice"].remote_cursors, f"obtenu {c['alice'].remote_cursors!r}"


# ---------------------------------------------------------------- A11 / A12 / A13

def test_A11_mon_curseur_reste_devant_le_meme_caractere():
    net, doc, c = make("Hello", writers=["bob"])
    b = c["bob"]
    b.move_cursor(3)                 # devant le second "l"
    c["alice"].insert(0, "XX")
    net.flush()
    assert b.cursor == 5, f"attendu 5, obtenu {b.cursor}"
    assert b.content[b.cursor] == "l"


@pytest.mark.parametrize("seed", SEEDS)
def test_A11_curseur_et_insertion_concurrents(seed):
    net, doc, c = make("abcdef", writers=["bob"])
    c["bob"].move_cursor(4)          # devant "e"
    c["alice"].insert(1, "ZZZ")
    net.flush(seed=seed)
    b = c["bob"]
    assert b.content[b.cursor] == "e", f"curseur {b.cursor} dans {b.content!r}"


def test_A12_curseur_distant_reste_devant_le_meme_caractere():
    net, doc, c = make("Hello", writers=["bob", "carol"])
    c["bob"].move_cursor(3)
    net.flush()
    c["carol"].insert(1, "XY")
    net.flush()
    a = c["alice"]
    assert a.remote_cursors.get("bob") == 5, f"obtenu {a.remote_cursors!r}"
    assert a.content[a.remote_cursors["bob"]] == "l"


def test_A12_insertion_locale_decale_le_curseur_distant_immediatement():
    net, doc, c = make("Hello", writers=["bob"])
    c["bob"].move_cursor(3)
    net.flush()
    a = c["alice"]
    a.insert(0, "XX")
    assert a.remote_cursors.get("bob") == 5, f"avant livraison : {a.remote_cursors!r}"
    net.flush()
    assert a.remote_cursors.get("bob") == 5, f"après livraison : {a.remote_cursors!r}"


@pytest.mark.parametrize("seed", SEEDS)
def test_A12_deplacement_et_insertion_concurrents(seed):
    net, doc, c = make("abcdef", writers=["bob", "carol"])
    c["bob"].move_cursor(4)          # devant "e"
    c["carol"].insert(0, "123")
    net.flush(seed=seed)
    for n in ("alice", "carol"):
        pos = c[n].remote_cursors.get("bob")
        assert pos is not None and c[n].content[pos] == "e", (
            f"chez {n} : curseur de bob {pos} dans {c[n].content!r}")


def test_A13_suppression_contenant_curseur_distant():
    net, doc, c = make("Hello world", writers=["bob", "carol"])
    c["bob"].move_cursor(8)
    net.flush()
    c["alice"].delete(6, 5)
    assert c["alice"].remote_cursors.get("bob") == 6
    net.flush()
    for n in ("alice", "carol"):
        assert c[n].remote_cursors.get("bob") == 6, f"chez {n} : {c[n].remote_cursors!r}"


# ---------------------------------------------------------------- A14 .. A20

def test_A14_annuler_retire_sa_saisie():
    net, doc, c = make("Hello", writers=["bob"])
    c["alice"].insert(5, " world")
    net.flush()
    c["alice"].undo()
    assert c["alice"].content == "Hello"
    net.flush()
    all_equal(c, "Hello")


def test_A14_trou_annule_seulement_la_derniere_saisie():
    net, doc, c = make("Hello", writers=["bob"])
    a = c["alice"]
    a.insert(5, " big")
    a.insert(9, " world")
    a.undo()
    net.flush()
    all_equal(c, "Hello big")


def test_A15_modification_d_autrui_survit_a_l_annulation():
    net, doc, c = make("Hello", writers=["bob"])
    c["alice"].insert(5, " world")
    net.flush()
    c["bob"].insert(0, "Oh, ")
    net.flush()
    c["alice"].undo()
    net.flush()
    all_equal(c, "Oh, Hello")


def test_A15_insertion_d_autrui_au_milieu_du_texte_annule():
    net, doc, c = make("Hello", writers=["bob"])
    c["alice"].insert(5, "AAAA")
    net.flush()
    c["bob"].insert(7, "B")          # HelloAABAA
    net.flush()
    c["alice"].undo()
    net.flush()
    all_equal(c, "HelloB")


def test_A16_annuler_sans_action_ne_change_rien():
    net, doc, c = make("Hello", writers=["bob"])
    c["alice"].undo()
    net.flush()
    all_equal(c, "Hello")
    c["bob"].insert(5, "!")
    net.flush()
    c["alice"].undo()                # alice n'a rien fait : l'édition de bob reste
    net.flush()
    all_equal(c, "Hello!")


def test_A17_lecteur_annule_contenu_inchange():
    net, doc, c = make("Hello", readers=["carol"])
    c["alice"].insert(5, "!")
    net.flush()
    c["carol"].insert(0, "X")
    c["carol"].undo()
    net.flush()
    all_equal(c, "Hello!")


def test_A18_retablir_fait_reapparaitre():
    net, doc, c = make("Hello", writers=["bob"])
    a = c["alice"]
    a.insert(5, " world")
    a.undo()
    a.redo()
    assert a.content == "Hello world"
    net.flush()
    all_equal(c, "Hello world")


def test_A19_saisie_apres_annulation_vide_le_retablissement():
    net, doc, c = make("Hello", writers=["bob"])
    a = c["alice"]
    a.insert(5, " world")
    a.undo()
    assert a.can_redo is True
    a.insert(5, "!")
    assert a.can_redo is False
    a.redo()
    net.flush()
    all_equal(c, "Hello!")


def test_A19_trou_edition_distante_ne_vide_pas_le_retablissement():
    net, doc, c = make("Hello", writers=["bob"])
    a = c["alice"]
    a.insert(5, " world")
    net.flush()
    a.undo()
    net.flush()
    c["bob"].insert(0, ">")
    net.flush()
    assert a.can_redo is True
    a.redo()
    net.flush()
    all_equal(c, ">Hello world")


def test_A20_retablir_vide_ne_change_rien():
    net, doc, c = make("Hello", writers=["bob"])
    a = c["alice"]
    assert a.can_redo is False
    a.redo()
    net.flush()
    all_equal(c, "Hello")


# ---------------------------------------------------------------- A21 / A22

@pytest.mark.parametrize("seed", SEEDS)
def test_A21_insertions_concurrentes_au_meme_endroit_conservees(seed):
    net, doc, c = make("ab", writers=["bob"])
    c["alice"].insert(1, "XXX")
    c["bob"].insert(1, "YYY")
    assert c["alice"].content == "aXXXb" and c["bob"].content == "aYYYb", (
        "chacun édite localement sans attendre")
    net.flush(seed=seed)
    for n, cl in c.items():
        assert "XXX" in cl.content and "YYY" in cl.content, f"chez {n} : {cl.content!r}"
        assert len(cl.content) == 8 and cl.content[0] == "a" and cl.content[-1] == "b"


@pytest.mark.parametrize("seed", SEEDS)
def test_A21_insertions_aleatoires_concurrentes_aucune_perdue(seed):
    rng = random.Random(seed or 0)
    names = ["alice", "bob", "carol"]
    net, doc, c = make("0123456789", writers=["bob", "carol"])
    inserted = []
    for _ in range(6):
        for n in names:
            for _ in range(3):
                ch = rng.choice("ABCDEFGHIJ")
                pos = rng.randint(0, len(c[n].content))
                c[n].insert(pos, ch)
                inserted.append(ch)
        net.flush(seed=rng.randint(0, 10**6))
    all_equal(c)
    assert sorted(c["alice"].content) == sorted("0123456789" + "".join(inserted)), (
        f"caractères perdus ou dupliqués : {c['alice'].content!r}")


@pytest.mark.parametrize("seed", SEEDS)
def test_A22_ordre_identique_chez_tous(seed):
    net, doc, c = make("[]", writers=["bob", "carol"], readers=["dan"])
    c["alice"].insert(1, "aa")
    c["bob"].insert(1, "bb")
    c["carol"].insert(1, "cc")
    net.flush(seed=seed)
    all_equal(c)
    content = c["alice"].content
    for t in ("aa", "bb", "cc"):
        assert t in content, f"{t!r} absent de {content!r}"


# ---------------------------------------------------------------- A23 .. A27

def test_A23_saisie_hors_connexion_visible_localement():
    net, doc, c = make("Hello", writers=["bob"])
    b = c["bob"]
    b.disconnect()
    b.insert(5, " offline")
    assert b.content == "Hello offline"
    net.flush()
    assert c["alice"].content == "Hello", "alice ne peut rien recevoir pendant la coupure"


def test_A24_indicateur_attente_hors_connexion():
    net, doc, c = make("Hello", writers=["bob"])
    b = c["bob"]
    b.disconnect()
    b.insert(0, "x")
    wait(net, 5)
    assert b.pending is True


def test_A25_indicateur_disparait_au_retour():
    net, doc, c = make("Hello", writers=["bob"])
    b = c["bob"]
    b.disconnect()
    b.insert(0, "x")
    b.reconnect()
    net.flush()
    assert b.pending is False


@pytest.mark.parametrize("seed", SEEDS)
def test_A26_modifications_en_attente_fusionnees_au_retour(seed):
    net, doc, c = make("Hello world", writers=["bob"])
    b = c["bob"]
    b.disconnect()
    b.insert(0, "[B]")
    b.insert(len(b.content), "[E]")
    c["alice"].insert(5, ",")        # édition concurrente pendant la coupure
    c["alice"].delete(7, 4)          # "Hello, world" -> "Hello, d"
    net.flush(seed=seed)
    b.reconnect()
    net.flush(seed=seed)
    all_equal(c, "[B]Hello, d[E]")


def test_A27_passe_en_lecture_hors_connexion_attente_rejetee():
    net, doc, c = make("Hello", writers=["bob", "carol"])
    b = c["bob"]
    b.disconnect()
    c["alice"].set_permission("bob", "read")
    net.flush()
    b.insert(0, "ZZZ")
    b.reconnect()
    net.flush()
    for n in ("alice", "carol"):
        assert "ZZZ" not in c[n].content, f"chez {n} : {c[n].content!r}"


def test_A27_trou_auteur_rejete_reconverge():
    net, doc, c = make("Hello", writers=["bob", "carol"])
    b = c["bob"]
    b.disconnect()
    c["alice"].set_permission("bob", "read")
    c["carol"].insert(5, "!")
    net.flush()
    b.insert(0, "ZZZ")
    b.reconnect()
    net.flush()
    all_equal(c, "Hello!")


# ---------------------------------------------------------------- A28 / A29

def test_A28_proprietaire_passe_en_lecture():
    net, doc, c = make("Hello", writers=["bob", "carol"])
    c["alice"].set_permission("bob", "read")
    net.flush()
    for n in ("alice", "bob", "carol"):
        assert c[n].permission_of("bob") == "read", f"chez {n} : {c[n].permission_of('bob')!r}"
    c["bob"].insert(0, "X")
    net.flush()
    all_equal(c, "Hello")


def test_A29_non_proprietaire_ne_peut_pas_modifier_permission():
    net, doc, c = make("Hello", writers=["bob"], readers=["carol"])
    c["bob"].set_permission("carol", "write")
    net.flush()
    for n in ("alice", "bob", "carol"):
        assert c[n].permission_of("carol") == "read", f"chez {n} : {c[n].permission_of('carol')!r}"
    c["carol"].insert(0, "X")
    net.flush()
    all_equal(c, "Hello")


def test_A29_ecrivain_ne_peut_pas_retrograder_un_autre_ecrivain():
    net, doc, c = make("Hello", writers=["bob", "carol"])
    c["bob"].set_permission("carol", "read")
    net.flush()
    assert c["alice"].permission_of("carol") == "write"
    c["carol"].insert(5, "!")
    net.flush()
    all_equal(c, "Hello!")


# ---------------------------------------------------------------- A30 .. A38

def test_A30_enregistrer_ajoute_une_entree():
    net, doc, c = make("Hello", writers=["bob"])
    before = len(c["bob"].history)
    c["alice"].save_version()
    net.flush()
    assert len(c["alice"].history) == before + 1
    assert len(c["bob"].history) == before + 1


def test_A31_lecteur_ne_peut_pas_enregistrer():
    net, doc, c = make("Hello", readers=["carol"])
    before = len(c["alice"].history)
    c["carol"].save_version()
    net.flush()
    assert len(c["alice"].history) == before
    assert len(c["carol"].history) == before


def test_A32_entree_porte_le_nom():
    net, doc, c = make("Hello", writers=["bob"])
    c["bob"].save_version()
    net.flush()
    assert c["alice"].history[-1].author == "bob"
    c["alice"].save_version()
    net.flush()
    assert c["bob"].history[-1].author == "alice"


def test_A33_consulter_ne_change_pas_le_contenu():
    net, doc, c = make("v1", writers=["bob"])
    c["alice"].save_version()
    net.flush()
    vid = c["alice"].history[-1].id
    c["alice"].delete(0, 2)
    c["alice"].insert(0, "v2")
    net.flush()
    assert c["bob"].view_version(vid) == "v1"
    net.flush()
    all_equal(c, "v2")


def _versioned(writers=("bob",), readers=()):
    net, doc, c = make("first draft", writers=list(writers), readers=list(readers))
    c["alice"].save_version()
    net.flush()
    vid = c["alice"].history[-1].id
    c["alice"].delete(0, 5)
    c["alice"].insert(0, "second")
    net.flush()
    return net, doc, c, vid


def test_A34_restaurer_rend_le_contenu_de_la_version():
    net, doc, c, vid = _versioned()
    c["bob"].restore_version(vid)
    assert c["bob"].content == "first draft"


def test_A35_lecteur_ne_peut_pas_restaurer():
    net, doc, c, vid = _versioned(readers=("carol",))
    c["carol"].restore_version(vid)
    net.flush()
    all_equal(c, "second draft")


def test_A36_restauration_propagee():
    net, doc, c, vid = _versioned(readers=("carol",))
    c["alice"].restore_version(vid)
    net.flush()
    all_equal(c, "first draft")


@pytest.mark.parametrize("seed", SEEDS)
def test_A36_trou_edition_concurrente_a_la_restauration_converge(seed):
    net, doc, c, vid = _versioned()
    c["alice"].restore_version(vid)
    c["bob"].insert(0, "!")
    net.flush(seed=seed)
    all_equal(c)


def test_A37_restauration_ajoute_une_entree():
    net, doc, c, vid = _versioned()
    before = len(c["bob"].history)
    c["alice"].restore_version(vid)
    net.flush()
    assert len(c["bob"].history) == before + 1
    assert len(c["alice"].history) == before + 1


def test_A38_annuler_apres_restauration():
    net, doc, c, vid = _versioned()
    c["alice"].restore_version(vid)
    net.flush()
    c["alice"].undo()
    assert c["alice"].content == "second draft"
    net.flush()
    all_equal(c, "second draft")
