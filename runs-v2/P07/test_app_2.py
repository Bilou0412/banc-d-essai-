"""Tests rouges — sonde P07, deuxième attaque.

Même interface publique de `app` que tests/test_app.py (voir sa docstring).
Cible : ce qui casse une synchronisation simulée (état partagé, rejeu de
messages, acquittements périmés, identifiants recyclés, horloges égales,
chaînes vides, répétition).
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


def no_conflict_anywhere(w, nid):
    for d in w.dev.values():
        assert not d.has_conflict(nid), f"{d!r} signale un conflit sur {nid!r}"
        assert copies(d, nid) == [], f"{d!r} a une copie de conflit : {copies(d, nid)!r}"


# --------------------------------------------------------------------------- copies réelles, pas d'état partagé


def test_A13_deux_mondes_independants_ne_partagent_aucun_etat():
    w1 = World()
    w2 = World()
    w1.tick("A")
    nid = w1.A.create_note("Monde 1", "secret")
    w1.net.run()
    w2.net.run()
    assert w1.B.note(nid) is not None, "préparation : la note doit arriver sur B du même monde"
    for d in (w2.A, w2.B):
        assert all(n["title"] != "Monde 1" for n in d.list_notes()), (
            f"un appareil d'un autre réseau/serveur voit la note : {d.list_notes()!r} — état global partagé ?"
        )
    c = w2.add("C")
    w2.net.run()
    assert all(n["title"] != "Monde 1" for n in c.list_notes()), f"obtenu {c.list_notes()!r}"


def test_A13_trou_B_ne_voit_rien_avant_livraison():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.edit_text(nid, "nouveau")
    assert w.net.in_flight() >= 1
    assert text_of(w.B, nid) == "ancien", "B voit la modification avant toute livraison : objet partagé"
    w.B.go_offline()
    assert text_of(w.B, nid) == "ancien"
    w.net.run()
    assert text_of(w.B, nid) == "ancien", "B hors ligne a reçu la modification"
    w.B.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "nouveau"


def test_A13_trou_dicts_renvoyes_sont_des_copies():
    w = World()
    nid = seeded(w, title="Titre", text="ancien")
    d = w.B.note(nid)
    d["text"] = "piraté"
    d["title"] = "piraté"
    for n in w.B.list_notes():
        n["text"] = "piraté 2"
    for n in w.A.list_notes():
        n["text"] = "piraté 3"
    assert text_of(w.A, nid) == "ancien", f"A modifié par un dict renvoyé : {w.A.note(nid)!r}"
    assert text_of(w.B, nid) == "ancien", f"B modifié par un dict renvoyé : {w.B.note(nid)!r}"
    w.net.run()
    assert text_of(w.B, nid) == "ancien" and w.B.note(nid)["title"] == "Titre"


# --------------------------------------------------------------------------- identifiants


def test_A16_trou_creations_simultanees_ids_distincts():
    w = World()
    w.A.go_offline()
    w.B.go_offline()
    assert w.clocks["A"].now() == w.clocks["B"].now()
    na = w.A.create_note("Même", "même")
    nb = w.B.create_note("Même", "même")
    assert na != nb, f"deux créations sur deux appareils ont le même identifiant {na!r}"
    w.A.go_online()
    w.B.go_online()
    w.net.run()
    for d in (w.A, w.B):
        same = [n for n in d.list_notes() if n["title"] == "Même"]
        assert len(same) == 2, f"{d!r} : attendu 2 notes « Même », obtenu {same!r}"
        assert not d.has_conflict(na) and not d.has_conflict(nb)


def test_A12_trou_identifiant_unique_apres_redemarrage():
    w = World()
    w.tick("A")
    n0 = w.A.create_note("En ligne", "0")
    w.net.run()
    w.A.go_offline()
    n1 = w.A.create_note("Avant", "1")
    w.A.close_app()
    w.A.open_app()
    n2 = w.A.create_note("Après", "2")
    assert len({n0, n1, n2}) == 3, f"identifiant recyclé après redémarrage : {n0!r} {n1!r} {n2!r}"
    assert text_of(w.A, n1) == "1" and text_of(w.A, n2) == "2" and text_of(w.A, n0) == "0"
    w.A.go_online()
    w.net.run()
    for nid, t in ((n0, "0"), (n1, "1"), (n2, "2")):
        assert text_of(w.B, nid) == t


# --------------------------------------------------------------------------- acquittements, rejeux


def test_A08_trou_acquittement_ancien_ne_marque_pas_synchronisee():
    w = World()
    nid = seeded(w)
    w.A.edit_text(nid, "v1")
    n = w.net.in_flight()
    assert n >= 1
    for _ in range(n):
        w.net.deliver(0)
    m = w.net.in_flight()          # réponses à v1 (acquittement, relais)
    w.tick("A")
    w.A.edit_text(nid, "v2")
    m2 = w.net.in_flight()
    for _ in range(m2 - m):        # l'envoi de v2 est perdu
        w.net.lose(m)
    for _ in range(m):             # seules les réponses à v1 sont livrées
        w.net.deliver(0)
    assert w.A.note(nid)["indicator"] == PENDING, (
        f"v2 n'a jamais été acquittée, obtenu {w.A.note(nid)['indicator']!r}"
    )
    w.net.run()
    assert w.A.note(nid)["indicator"] == SYNCED
    assert text_of(w.A, nid) == "v2" and text_of(w.B, nid) == "v2"


def test_A22_trou_acquittement_perdu_reessai_sans_conflit():
    w = World()
    nid = seeded(w, text="origine")
    w.tick("A")
    w.A.edit_text(nid, "par A")
    n = w.net.in_flight()
    for _ in range(n):
        w.net.deliver(0)           # le serveur a reçu
    w.A.go_offline()               # l'acquittement est perdu
    assert w.A.note(nid)["indicator"] == PENDING
    w.net.run()
    assert text_of(w.B, nid) == "par A"
    w.A.go_online()
    w.net.run()
    no_conflict_anywhere(w, nid)
    assert w.A.note(nid)["indicator"] == SYNCED
    for d in (w.A, w.B):
        assert text_of(d, nid) == "par A"
        assert len(d.list_notes()) == 1, f"doublon : {d.list_notes()!r}"


def test_A22_trou_reessai_tardif_n_ecrase_pas_modification_posterieure():
    w = World()
    nid = seeded(w, text="origine")
    w.tick("A", 100)               # horloge de A en avance
    w.A.edit_text(nid, "par A")
    n = w.net.in_flight()
    for _ in range(n):
        w.net.deliver(0)
    w.A.go_offline()
    w.net.run()
    assert text_of(w.B, nid) == "par A"
    w.tick("B", 5)
    w.B.edit_text(nid, "par B, après avoir vu A")
    w.net.run()
    w.A.go_online()
    w.net.run()
    for d in (w.A, w.B):
        assert text_of(d, nid) == "par B, après avoir vu A", (
            f"{d!r} : le réessai d'une modification déjà appliquée a écrasé la suivante, "
            f"obtenu {text_of(d, nid)!r}"
        )
    no_conflict_anywhere(w, nid)


def test_A17_trou_creation_rejouee_apres_suppression_ne_ressuscite_pas():
    w = World()
    w.tick("A")
    nid = w.A.create_note("Fantôme", "x")
    n = w.net.in_flight()
    assert n >= 1
    for i in range(n):
        w.net.duplicate(i)
    for _ in range(n):
        w.net.deliver(0)
    w.tick("A")
    w.A.delete_note(nid)
    steps = 0
    while w.net.in_flight() and steps < 2000:
        w.net.deliver(w.net.in_flight() - 1)   # le plus récent d'abord, les vieilles copies en dernier
        steps += 1
    w.net.run()
    for d in (w.A, w.B):
        assert d.note(nid) is None, f"{d!r} : la note supprimée est ressuscitée par un rejeu"
        assert all(x["title"] != "Fantôme" for x in d.list_notes()), f"{d!r} : {d.list_notes()!r}"


def test_A19_trou_modification_rejouee_n_ecrase_pas_la_derniere():
    w = World()
    nid = seeded(w, text="v0")
    w.tick("A")
    w.A.edit_text(nid, "v1")
    n = w.net.in_flight()
    for i in range(n):
        w.net.duplicate(i)
    for _ in range(n):
        w.net.deliver(0)
    w.tick("A")
    w.A.edit_text(nid, "v2")
    steps = 0
    while w.net.in_flight() and steps < 2000:
        w.net.deliver(w.net.in_flight() - 1)
        steps += 1
    w.net.run()
    for d in (w.A, w.B):
        assert text_of(d, nid) == "v2", f"{d!r} : rejeu de v1, obtenu {text_of(d, nid)!r}"
    no_conflict_anywhere(w, nid)


def test_A14_trou_relais_perdu_vers_B_rattrape():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.go_offline()
    w.A.edit_text(nid, "nouveau")
    w.A.go_online()
    n = w.net.in_flight()
    for _ in range(n):
        w.net.deliver(0)
    while w.net.in_flight():
        w.net.lose(0)
    w.net.run()
    assert text_of(w.B, nid) == "nouveau", "le relais vers B a été perdu et jamais rattrapé"
    assert w.A.note(nid)["indicator"] == SYNCED


def test_A11_trou_fermeture_pendant_envoi():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.edit_text(nid, "nouveau")
    assert w.net.in_flight() >= 1
    w.A.close_app()
    w.net.run()
    w.A.open_app()
    w.net.run()
    assert text_of(w.A, nid) == "nouveau"
    assert text_of(w.B, nid) == "nouveau"
    assert w.A.note(nid)["indicator"] == SYNCED
    no_conflict_anywhere(w, nid)


# --------------------------------------------------------------------------- vide / zéro


def test_A14_texte_vide_propage():
    w = World()
    nid = seeded(w, text="non vide")
    w.A.go_offline()
    w.A.edit_text(nid, "")
    assert text_of(w.A, nid) == ""
    w.A.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "", f"obtenu {text_of(w.B, nid)!r}"


def test_A15_titre_vide_propage():
    w = World()
    nid = seeded(w, title="Titre")
    w.A.go_offline()
    w.A.edit_title(nid, "")
    w.A.go_online()
    w.net.run()
    assert w.B.note(nid)["title"] == "", f"obtenu {w.B.note(nid)!r}"


def test_A16_note_vide_apparait_sur_B():
    w = World()
    w.A.go_offline()
    nid = w.A.create_note("", "")
    assert nid in ids(w.A)
    w.A.go_online()
    w.net.run()
    assert nid in ids(w.B), f"note vide absente de B : {w.B.list_notes()!r}"
    n = w.B.note(nid)
    assert n["title"] == "" and n["text"] == ""


def test_A24_texte_vide_contre_texte_conflit_signale():
    w = World()
    nid = make_conflict(w, text_a="", text_b="version B")
    assert w.A.has_conflict(nid) or w.B.has_conflict(nid), "texte vidé contre texte : aucun conflit"


def test_A28_version_vide_la_plus_recente_affichee():
    w = World()
    nid = make_conflict(w, text_a="", text_b="version B", a_later=True)
    for d in (w.A, w.B):
        assert text_of(d, nid) == "", f"{d!r} : attendu '' (plus récente), obtenu {text_of(d, nid)!r}"
        assert any(c["text"] == "version B" for c in copies(d, nid)), f"{d!r} : {d.list_notes()!r}"


def test_A25_textes_vides_identiques_pas_de_conflit():
    w = World()
    nid = make_conflict(w, text_a="", text_b="")
    no_conflict_anywhere(w, nid)
    assert text_of(w.A, nid) == "" and text_of(w.B, nid) == ""


# --------------------------------------------------------------------------- conflits : ordre, égalité, champs


def test_A28_ordre_de_livraison_aleatoire_version_la_plus_recente():
    for seed in range(10):
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
        w.net.run(seed=seed)
        w.net.run()
        for d in (w.A, w.B):
            assert text_of(d, nid) == "version A", f"seed={seed} {d!r} : obtenu {text_of(d, nid)!r}"
            cps = copies(d, nid)
            assert len(cps) == 1 and cps[0]["text"] == "version B", f"seed={seed} {d!r} : {cps!r}"


def test_A28_trou_horloges_egales_les_appareils_convergent():
    for seed in range(8):
        w = World()
        nid = seeded(w, text="origine")
        w.tick("B", 1)
        w.A.go_offline()
        w.B.go_offline()
        w.tick("A", 10)
        w.tick("B", 10)
        assert w.clocks["A"].now() == w.clocks["B"].now()
        w.A.edit_text(nid, "version A")
        w.B.edit_text(nid, "version B")
        w.A.go_online()
        w.B.go_online()
        w.net.run(seed=seed)
        assert w.A.has_conflict(nid) or w.B.has_conflict(nid), f"seed={seed} : aucun conflit"
        ta, tb = text_of(w.A, nid), text_of(w.B, nid)
        assert ta == tb and ta in ("version A", "version B"), f"seed={seed} : A={ta!r} B={tb!r} divergent"
        ca, cb = copies(w.A, nid), copies(w.B, nid)
        assert len(ca) == 1 and len(cb) == 1, f"seed={seed} : A={ca!r} B={cb!r}"
        assert ca[0]["id"] == cb[0]["id"] and ca[0]["text"] == cb[0]["text"] != ta, f"seed={seed}"


def test_A24_trou_titre_sur_A_texte_sur_B_pas_de_conflit():
    w = World()
    nid = seeded(w, title="Titre", text="origine")
    w.A.go_offline()
    w.B.go_offline()
    w.tick("A", 10)
    w.tick("B", 20)
    w.A.edit_title(nid, "Titre par A")
    w.B.edit_text(nid, "texte par B")
    w.A.go_online()
    w.net.run()
    w.B.go_online()
    w.net.run()
    no_conflict_anywhere(w, nid)
    for d in (w.A, w.B):
        n = d.note(nid)
        assert n["title"] == "Titre par A" and n["text"] == "texte par B", f"{d!r} : fusion perdue, {n!r}"


def test_A17_trou_supprimee_des_deux_cotes_sans_conflit():
    w = World()
    nid = seeded(w)
    w.A.go_offline()
    w.B.go_offline()
    w.A.delete_note(nid)
    w.B.delete_note(nid)
    w.A.go_online()
    w.B.go_online()
    w.net.run(seed=1)
    for d in (w.A, w.B):
        assert d.note(nid) is None
        assert not d.has_conflict(nid)
        assert d.list_notes() == [], f"{d!r} : {d.list_notes()!r}"


def test_A31_trou_ordre_aleatoire_une_seule_note_modifiee():
    for seed in range(8):
        w = World()
        nid = seeded(w, text="origine")
        w.A.go_offline()
        w.B.go_offline()
        w.tick("A", 5)
        w.tick("B", 10)
        w.A.edit_text(nid, "modifiée sur A")
        w.B.delete_note(nid)
        w.A.go_online()
        w.B.go_online()
        w.net.run(seed=seed)
        w.net.run()
        for d in (w.A, w.B):
            found = [n for n in d.list_notes() if n["text"] == "modifiée sur A"]
            assert len(found) == 1, f"seed={seed} {d!r} : attendu 1 note modifiée, obtenu {found!r}"


def test_A27_trou_trois_appareils_aucune_version_perdue():
    w = World(names=("A", "B", "C"))
    nid = seeded(w, text="origine")
    assert text_of(w.dev["C"], nid) == "origine"
    for name in "ABC":
        w.dev[name].go_offline()
    for i, name in enumerate("ABC"):
        w.tick(name, 10 * (i + 1))
        w.dev[name].edit_text(nid, f"version {name}")
    for name in "ABC":
        w.dev[name].go_online()
    w.net.run(seed=1)
    w.net.run()
    expected = {"version A", "version B", "version C"}
    views = []
    for name in "ABC":
        d = w.dev[name]
        assert d.has_conflict(nid), f"{name} ne signale pas le conflit"
        assert text_of(d, nid) == "version C", f"{name} : obtenu {text_of(d, nid)!r}"
        seen = {text_of(d, nid)} | {c["text"] for c in copies(d, nid)}
        assert seen >= expected, f"{name} : versions perdues, visibles={seen!r}"
        views.append(sorted((c["id"], c["text"]) for c in copies(d, nid)))
    assert views[0] == views[1] == views[2], f"copies divergentes : {views!r}"


def test_A29_trou_modification_apres_resolution_sans_nouveau_conflit():
    w = World()
    nid = make_conflict(w)
    w.A.resolve_conflict(nid, "version B")
    w.net.run()
    w.tick("B", 100)
    w.B.edit_text(nid, "suite")
    w.net.run()
    for d in (w.A, w.B):
        assert not d.has_conflict(nid), f"{d!r} : nouveau conflit après résolution"
        assert text_of(d, nid) == "suite"


def test_A30_B_hors_ligne_pendant_la_resolution():
    w = World()
    nid = make_conflict(w, a_later=True)
    w.B.go_offline()
    w.A.resolve_conflict(nid, "version B")
    w.net.run()
    w.B.go_online()
    w.net.run()
    assert text_of(w.B, nid) == "version B", f"obtenu {text_of(w.B, nid)!r}"
    assert not w.B.has_conflict(nid)


# --------------------------------------------------------------------------- session


def test_A20_modification_en_ligne_session_fermee_reste_locale():
    w = World()
    nid = seeded(w, text="ancien")
    w.A.close_session()
    w.A.edit_text(nid, "nouveau")
    w.net.run()
    assert text_of(w.B, nid) == "ancien", "A sans session a propagé sa modification"
    assert w.A.note(nid)["indicator"] == PENDING
    w.A.open_session("alice")
    w.net.run()
    assert text_of(w.B, nid) == "nouveau"
    assert w.A.note(nid)["indicator"] == SYNCED


# --------------------------------------------------------------------------- nouvel appareil, comptes


def test_A34_nouvel_appareil_texte_courant_sans_note_supprimee():
    w = World()
    n1 = seeded(w, title="Gardée", text="v1")
    n2 = seeded(w, title="Supprimée", text="x")
    w.tick("A")
    w.A.edit_text(n1, "v2")
    w.A.delete_note(n2)
    w.net.run()
    c = w.add("C")
    w.net.run()
    assert text_of(c, n1) == "v2", f"obtenu {text_of(c, n1)!r}"
    assert c.note(n2) is None and all(n["title"] != "Supprimée" for n in c.list_notes()), (
        f"note supprimée transmise au nouvel appareil : {c.list_notes()!r}"
    )


def test_A34_compte_bob_isole_dans_les_deux_sens():
    w = World()
    seeded(w)
    c = w.add("C", account="bob")
    d = w.add("D", account="bob")
    w.net.run()
    bid = c.create_note("Bob", "privé")
    w.net.run()
    assert text_of(d, bid) == "privé", "la note de bob doit arriver sur l'autre appareil de bob"
    for x in (w.A, w.B):
        assert all(n["title"] != "Bob" for n in x.list_notes()), f"alice voit la note de bob : {x.list_notes()!r}"
    assert all(n["title"] == "Bob" for n in d.list_notes()), f"bob voit d'autres notes : {d.list_notes()!r}"


def test_A35_premier_lancement_hors_ligne_avec_session_puis_en_ligne():
    w = World()
    n1 = seeded(w, title="Existante", text="1")
    c = w.add("C", account="alice", offline=True)
    w.net.run()
    assert c.list_notes() == [], f"obtenu {c.list_notes()!r}"
    mine = c.create_note("De C", "c")
    assert ids(c) == [mine]
    c.go_online()
    w.net.run()
    assert set(ids(c)) >= {n1, mine}, f"obtenu {ids(c)!r}"
    assert text_of(w.B, mine) == "c"


# --------------------------------------------------------------------------- ordre


def test_A33_modification_hors_ligne_recue_au_retour_passe_en_tete():
    w = World()
    n1 = seeded(w, title="Un")
    seeded(w, title="Deux")
    seeded(w, title="Trois")
    w.A.go_offline()
    w.tick("A", 5)
    w.A.edit_text(n1, "remonte")
    w.A.go_online()
    w.net.run()
    assert ids(w.A)[0] == n1, f"A : {ids(w.A)!r}"
    assert ids(w.B)[0] == n1, f"B : {ids(w.B)!r}"


# --------------------------------------------------------------------------- répétition


def test_A16_trou_bascules_repetees_sans_doublon():
    w = World()
    rng = random.Random(5)
    w.A.go_offline()
    nid = w.A.create_note("Bascule", "t0")
    last = "t0"
    for k in range(30):
        w.A.go_online()
        for i in range(w.net.in_flight()):
            if rng.random() < 0.5:
                w.net.duplicate(i)
        for _ in range(rng.randrange(w.net.in_flight() + 1)):
            if w.net.in_flight():
                w.net.deliver(rng.randrange(w.net.in_flight()))
        w.A.go_offline()
        w.tick("A")
        last = f"t{k + 1}"
        w.A.edit_text(nid, last)
    w.A.go_online()
    w.net.run(seed=2)
    for d in (w.A, w.B):
        same = [n for n in d.list_notes() if n["title"] == "Bascule"]
        assert len(same) == 1, f"{d!r} : attendu 1 note, obtenu {same!r}"
        assert same[0]["text"] == last, f"{d!r} : attendu {last!r}, obtenu {same[0]['text']!r}"
    assert w.A.note(nid)["indicator"] == SYNCED
    no_conflict_anywhere(w, nid)


def test_A19_deux_cents_modifications_hors_ligne():
    w = World()
    nid = seeded(w, text="v0")
    w.A.go_offline()
    for k in range(1, 201):
        w.tick("A", 0.5)
        w.A.edit_text(nid, f"v{k}")
    w.A.go_online()
    w.net.run(seed=4)
    assert text_of(w.B, nid) == "v200", f"obtenu {text_of(w.B, nid)!r}"
    assert text_of(w.A, nid) == "v200"
    no_conflict_anywhere(w, nid)


def test_A08_trou_modifications_rapprochees_en_ligne_sans_conflit():
    for seed in range(6):
        w = World()
        nid = seeded(w, text="v0")
        for k in range(5):
            w.tick("A")
            w.A.edit_text(nid, f"v{k + 1}")
        w.net.run(seed=seed)
        assert text_of(w.B, nid) == "v5", f"seed={seed} : obtenu {text_of(w.B, nid)!r}"
        assert text_of(w.A, nid) == "v5", f"seed={seed} : A a régressé à {text_of(w.A, nid)!r}"
        assert w.A.note(nid)["indicator"] == SYNCED
        no_conflict_anywhere(w, nid)
