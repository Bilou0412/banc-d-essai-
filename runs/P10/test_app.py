"""Tests rouges de la sonde de messagerie chiffrée.

Interface publique fixée par ces tests (le module `app` doit l'exposer telle quelle) :

    net = app.Network()                      # serveur + horloge simulée
    net.advance(seconds)                     # fait avancer le temps
    net.server.stored() -> list[bytes]       # tout ce que le serveur conserve

    u = net.register(name, device="principal")  -> app.User (un appareil initial)
    u.name
    u.devices() -> list[str]                 # noms des appareils liés
    u.link_device(device_name) -> str
    u.unlink_device(device_name)
    u.set_online(online: bool, device=None)  # None = tous les appareils

    u.send(to, text, device=None) -> str     # to = nom d'un contact OU id de groupe ; renvoie un id de message
    u.open(msg_id, device=None) -> str       # texte en clair ; lève app.Unreadable si illisible / absent
    u.conversation(to, device=None) -> list[str]   # ids des messages présents, dans l'ordre
    u.receipt(msg_id) -> "en attente" | "envoyé" | "remis" | "lu"
    u.message_key(msg_id) -> bytes           # clé_message du message (envoyé ou reçu)

    u.create_group(title, members: list[str]) -> str   # id de groupe ; le créateur en est membre
    u.members(group_id) -> collection de noms
    u.add_member(group_id, name)
    u.remove_member(group_id, name)
    u.leave_group(group_id)

    u.fingerprint(contact) -> str
    u.verification(contact) -> "vérifié" | "non vérifié"
    u.mark_verified(contact)
    u.alerts(contact) -> list (alertes affichées dans la conversation)
    u.reset_identity()                       # nouvelle clé d'identité

    u.set_timer(to, seconds | None)          # None = minuteur désactivé
    u.timer(to) -> int | None

    att = app.Attacker(net)                  # voit tout ce que stocke le serveur
    att.compromise(key: bytes)
    att.read(msg_id) -> str | None

    app.Unreadable (Exception)
"""

import pytest

import app


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def net():
    return app.Network()


@pytest.fixture
def alice(net):
    return net.register("alice")


@pytest.fixture
def bob(net):
    return net.register("bob")


@pytest.fixture
def carol(net):
    return net.register("carol")


PRIMARY = "principal"


def readable(user, msg_id, device=None):
    """Texte si lisible, None si le système le déclare illisible."""
    try:
        return user.open(msg_id, device=device)
    except app.Unreadable:
        return None


# --------------------------------------------------------------------------- A01


def test_A01_message_sent_to_contact_is_readable_by_contact(alice, bob):
    m = alice.send("bob", "bonjour Bob")
    got = readable(bob, m)
    assert got == "bonjour Bob", f"attendu 'bonjour Bob' lisible par bob, obtenu {got!r}"


def test_A01_non_ascii_message_is_readable_unchanged(alice, bob):
    text = "Ça va ? 🙂 — ñ, 漢字\r\nligne 2"
    m = alice.send("bob", text)
    got = readable(bob, m)
    assert got == text, f"attendu {text!r}, obtenu {got!r}"


def test_A01_reply_is_readable_by_original_sender(alice, bob):
    alice.send("bob", "question")
    r = bob.send("alice", "réponse")
    got = readable(alice, r)
    assert got == "réponse", f"attendu 'réponse' lisible par alice, obtenu {got!r}"


# --------------------------------------------------------------------------- A02


def test_A02_server_storage_does_not_contain_plaintext(net, alice, bob):
    secret = "code-secret-7f3a-éàü"
    bob.set_online(False)  # force le message à rester stocké sur le serveur
    alice.send("bob", secret)
    stored = net.server.stored()
    assert stored, "le serveur devrait stocker au moins un message pour un destinataire hors ligne"
    for blob in stored:
        assert secret.encode("utf-8") not in blob, f"texte clair trouvé dans le stockage serveur : {blob!r}"
        assert b"code-secret-7f3a" not in blob, f"fragment ASCII du texte clair trouvé côté serveur : {blob!r}"


def test_A02_group_message_on_server_does_not_contain_plaintext(net, alice, bob, carol):
    g = alice.create_group("équipe", ["bob", "carol"])
    carol.set_online(False)
    alice.send(g, "groupe-secret-91ab")
    stored = net.server.stored()
    assert stored, "le serveur devrait stocker le message de groupe pour carol hors ligne"
    for blob in stored:
        assert b"groupe-secret-91ab" not in blob, f"texte clair du groupe trouvé côté serveur : {blob!r}"


# --------------------------------------------------------------------------- A03


def test_A03_consecutive_messages_use_different_message_keys(alice, bob):
    ids = [alice.send("bob", f"message {i}") for i in range(6)]
    keys = [alice.message_key(m) for m in ids]
    for k in keys:
        assert isinstance(k, bytes) and len(k) > 0, f"clé_message attendue en bytes non vides, obtenu {k!r}"
    for i in range(1, len(keys)):
        assert keys[i] != keys[i - 1], f"message {i} réutilise la clé_message du message {i - 1}"


def test_A03_key_differs_across_direction_change(alice, bob):
    m1 = alice.send("bob", "a")
    m2 = bob.send("alice", "b")
    m3 = alice.send("bob", "c")
    k1, k2, k3 = bob.message_key(m1), bob.message_key(m2), bob.message_key(m3)
    assert k2 != k1, "la réponse de bob réutilise la clé_message du message précédent"
    assert k3 != k2, "le message d'alice réutilise la clé_message du message précédent"


def test_A03_sender_and_recipient_agree_on_message_key(alice, bob):
    # la clé_message est une propriété du message : les deux extrémités observent la même
    m = alice.send("bob", "x")
    assert alice.message_key(m) == bob.message_key(m), "clé_message différente entre expéditeur et destinataire"


# --------------------------------------------------------------------------- A04 / A05


@pytest.fixture
def exchange(alice, bob):
    """Échange mêlant chaînes symétriques et changements de sens."""
    texts = [
        ("alice", "m0"), ("alice", "m1"), ("bob", "m2"), ("alice", "m3"),
        ("alice", "m4"), ("alice", "m5"), ("bob", "m6"), ("alice", "m7"),
    ]
    users = {"alice": (alice, "bob"), "bob": (bob, "alice")}
    ids = []
    for who, text in texts:
        u, to = users[who]
        ids.append(u.send(to, text))
    return ids, [t for _, t in texts]


def test_A04_A05_attacker_with_compromised_key_reads_that_message(net, alice, exchange):
    # contrôle : l'attaquant est fonctionnel, sinon A04/A05 ne prouvent rien
    ids, texts = exchange
    att = app.Attacker(net)
    att.compromise(alice.message_key(ids[4]))
    assert att.read(ids[4]) == texts[4], "l'attaquant muni de la clé_message doit lire CE message"


def test_A04_earlier_messages_unreadable_after_key_compromise(net, alice, exchange):
    ids, texts = exchange
    att = app.Attacker(net)
    att.compromise(alice.message_key(ids[4]))
    for i in range(4):
        got = att.read(ids[i])
        assert got is None, f"message antérieur {i} lu par l'attaquant : {got!r}"


def test_A05_later_messages_unreadable_after_key_compromise(net, alice, exchange):
    ids, texts = exchange
    att = app.Attacker(net)
    att.compromise(alice.message_key(ids[4]))
    for i in range(5, len(ids)):
        got = att.read(ids[i])
        assert got is None, f"message postérieur {i} lu par l'attaquant : {got!r}"


def test_A05_next_message_in_same_chain_unreadable(net, alice, bob):
    m1 = alice.send("bob", "premier")
    m2 = alice.send("bob", "suivant immédiat")
    att = app.Attacker(net)
    att.compromise(alice.message_key(m1))
    assert att.read(m1) == "premier", "contrôle : la clé compromise doit ouvrir son propre message"
    assert att.read(m2) is None, "le message suivant de la même chaîne est lisible avec la clé du précédent"


# --------------------------------------------------------------------------- A06 / A09


def test_A06_linking_device_adds_it_to_device_list(bob):
    assert "portable" not in bob.devices()
    bob.link_device("portable")
    assert "portable" in bob.devices(), f"'portable' absent de {bob.devices()!r} après liaison"
    assert PRIMARY in bob.devices(), "la liaison ne doit pas retirer l'appareil principal"


def test_A09_unlinking_device_removes_it_from_device_list(bob):
    bob.link_device("portable")
    bob.unlink_device("portable")
    assert "portable" not in bob.devices(), f"'portable' encore présent dans {bob.devices()!r}"
    assert PRIMARY in bob.devices(), "le retrait d'un appareil ne doit pas retirer les autres"


# --------------------------------------------------------------------------- A07 / A08 / A10


def test_A07_message_received_after_linking_is_readable_on_new_device(alice, bob):
    bob.link_device("portable")
    m = alice.send("bob", "après liaison")
    got = readable(bob, m, device="portable")
    assert got == "après liaison", f"attendu lisible sur 'portable', obtenu {got!r}"


def test_A08_message_received_before_linking_is_not_readable_on_new_device(alice, bob):
    m = alice.send("bob", "avant liaison")
    assert readable(bob, m, device=PRIMARY) == "avant liaison", "contrôle : lisible sur l'appareil principal"
    bob.link_device("portable")
    got = readable(bob, m, device="portable")
    assert got is None, f"message antérieur à la liaison lu sur 'portable' : {got!r}"


def test_A10_message_sent_after_unlinking_is_not_readable_on_removed_device(alice, bob):
    bob.link_device("portable")
    bob.unlink_device("portable")
    m = alice.send("bob", "après retrait")
    assert readable(bob, m, device=PRIMARY) == "après retrait", "contrôle : lisible sur l'appareil restant"
    got = readable(bob, m, device="portable")
    assert got is None, f"message postérieur au retrait lu sur l'appareil retiré : {got!r}"


# --------------------------------------------------------------------------- A11


def test_A11_message_sent_from_one_device_appears_on_senders_other_devices(alice, bob):
    alice.link_device("portable")
    m = alice.send("bob", "depuis le portable", device="portable")
    conv = alice.conversation("bob", device=PRIMARY)
    assert m in conv, f"message {m!r} absent de la conversation sur '{PRIMARY}' : {conv!r}"


def test_A11_group_message_appears_on_senders_other_devices(alice, bob):
    g = alice.create_group("g", ["bob"])
    alice.link_device("portable")
    m = alice.send(g, "groupe depuis principal", device=PRIMARY)
    conv = alice.conversation(g, device="portable")
    assert m in conv, f"message de groupe absent sur 'portable' : {conv!r}"


# --------------------------------------------------------------------------- A12 / A15 / A16


def test_A12_adding_person_adds_to_member_list(alice, bob, carol):
    g = alice.create_group("g", ["bob"])
    assert "carol" not in alice.members(g)
    alice.add_member(g, "carol")
    assert "carol" in alice.members(g), f"carol absente de {alice.members(g)!r}"
    assert "carol" in bob.members(g), f"carol absente de la vue de bob : {bob.members(g)!r}"


def test_A15_removing_member_removes_from_member_list(alice, bob, carol):
    g = alice.create_group("g", ["bob", "carol"])
    alice.remove_member(g, "bob")
    assert "bob" not in alice.members(g), f"bob encore dans {alice.members(g)!r}"
    assert "bob" not in carol.members(g), f"bob encore dans la vue de carol : {carol.members(g)!r}"
    assert "carol" in alice.members(g), "le retrait de bob ne doit pas retirer carol"


def test_A16_leaving_group_removes_user_from_member_list(alice, bob, carol):
    g = alice.create_group("g", ["bob", "carol"])
    bob.leave_group(g)
    assert "bob" not in alice.members(g), f"bob encore dans {alice.members(g)!r} après avoir quitté"
    assert "bob" not in carol.members(g), f"bob encore dans la vue de carol : {carol.members(g)!r}"


# --------------------------------------------------------------------------- A13 / A14 / A17


def test_A13_group_message_after_add_is_readable_by_new_member(alice, bob, carol):
    g = alice.create_group("g", ["bob"])
    alice.add_member(g, "carol")
    m = alice.send(g, "bienvenue")
    got = readable(carol, m)
    assert got == "bienvenue", f"attendu lisible par carol, obtenu {got!r}"


def test_A13_message_from_another_member_after_add_is_readable(alice, bob, carol):
    g = alice.create_group("g", ["bob"])
    alice.add_member(g, "carol")
    m = bob.send(g, "salut carol")
    assert readable(carol, m) == "salut carol", "message de bob postérieur à l'ajout illisible par carol"


def test_A14_group_message_before_add_is_not_readable_by_new_member(alice, bob, carol):
    g = alice.create_group("g", ["bob"])
    m = alice.send(g, "avant ton arrivée")
    assert readable(bob, m) == "avant ton arrivée", "contrôle : lisible par un membre existant"
    alice.add_member(g, "carol")
    got = readable(carol, m)
    assert got is None, f"message antérieur à l'ajout lu par carol : {got!r}"


def test_A17_group_message_after_removal_is_not_readable_by_removed_member(alice, bob, carol):
    g = alice.create_group("g", ["bob", "carol"])
    alice.remove_member(g, "bob")
    m = alice.send(g, "sans bob")
    assert readable(carol, m) == "sans bob", "contrôle : lisible par un membre restant"
    got = readable(bob, m)
    assert got is None, f"message postérieur au retrait lu par bob : {got!r}"


def test_A17_message_from_remaining_member_after_removal_not_readable(alice, bob, carol):
    g = alice.create_group("g", ["bob", "carol"])
    bob.send(g, "je suis encore là")  # bob a pu établir des clés avant son retrait
    alice.remove_member(g, "bob")
    m = carol.send(g, "après le départ de bob")
    assert readable(bob, m) is None, "message de carol postérieur au retrait lu par bob"


# --------------------------------------------------------------------------- A18 / A20


def test_A18_both_contacts_see_same_fingerprint(alice, bob):
    fa = alice.fingerprint("bob")
    fb = bob.fingerprint("alice")
    assert isinstance(fa, str) and fa, f"empreinte attendue non vide, obtenu {fa!r}"
    assert fa == fb, f"empreintes différentes : alice voit {fa!r}, bob voit {fb!r}"


def test_A18_after_legitimate_key_change_both_sides_still_agree(alice, bob):
    bob.reset_identity()
    assert alice.fingerprint("bob") == bob.fingerprint("alice"), \
        "après un changement de clé non substitué, les deux côtés doivent voir la même empreinte"


def test_A20_identity_key_change_changes_fingerprint(alice, bob):
    before = alice.fingerprint("bob")
    bob.reset_identity()
    after = alice.fingerprint("bob")
    assert after != before, f"empreinte inchangée après changement de clé : {after!r}"


def test_A20_fingerprint_stable_without_key_change(alice, bob):
    before = alice.fingerprint("bob")
    alice.send("bob", "x")
    bob.send("alice", "y")
    assert alice.fingerprint("bob") == before, "l'empreinte a changé sans changement de clé d'identité"


# --------------------------------------------------------------------------- A19 / A21


def test_A19_marking_contact_verified_sets_verified(alice, bob):
    alice.mark_verified("bob")
    assert alice.verification("bob") == "vérifié", f"obtenu {alice.verification('bob')!r}"


def test_A21_identity_key_change_resets_verification(alice, bob):
    alice.mark_verified("bob")
    assert alice.verification("bob") == "vérifié"
    bob.reset_identity()
    got = alice.verification("bob")
    assert got == "non vérifié", f"attendu 'non vérifié' après changement de clé, obtenu {got!r}"


# --------------------------------------------------------------------------- A22


def test_A22_identity_key_change_shows_alert_in_conversation(alice, bob):
    alice.send("bob", "salut")
    bob.send("alice", "salut")
    n = len(alice.alerts("bob"))
    bob.reset_identity()
    got = alice.alerts("bob")
    assert len(got) == n + 1, f"attendu {n + 1} alerte(s) après changement de clé, obtenu {got!r}"


# --------------------------------------------------------------------------- A23 – A28 (accusés)


def test_A23_message_sent_without_network_is_pending(alice, bob):
    alice.set_online(False)
    m = alice.send("bob", "hors réseau")
    got = alice.receipt(m)
    assert got == "en attente", f"attendu 'en attente', obtenu {got!r}"


def test_A23_pending_message_not_delivered_to_recipient(net, alice, bob):
    alice.set_online(False)
    m = alice.send("bob", "hors réseau")
    net.advance(3600)
    assert alice.receipt(m) == "en attente", "un message sans réseau ne doit pas progresser avec le temps seul"
    assert m not in bob.conversation("alice"), "le destinataire a reçu un message jamais parti"


def test_A24_message_received_by_server_is_sent(alice, bob):
    bob.set_online(False)
    m = alice.send("bob", "au serveur")
    got = alice.receipt(m)
    assert got == "envoyé", f"attendu 'envoyé', obtenu {got!r}"


def test_A24_pending_message_becomes_sent_when_network_returns(alice, bob):
    bob.set_online(False)
    alice.set_online(False)
    m = alice.send("bob", "plus tard")
    alice.set_online(True)
    got = alice.receipt(m)
    assert got == "envoyé", f"attendu 'envoyé' une fois le serveur atteint, obtenu {got!r}"


def test_A25_message_to_offline_contact_stays_sent(net, alice, bob):
    bob.set_online(False)
    m = alice.send("bob", "tu es là ?")
    net.advance(7 * 24 * 3600)
    got = alice.receipt(m)
    assert got == "envoyé", f"attendu 'envoyé' tant que le contact est hors connexion, obtenu {got!r}"


def test_A26_message_received_by_one_device_is_delivered(alice, bob):
    bob.link_device("portable")
    bob.set_online(False, device=PRIMARY)
    m = alice.send("bob", "un seul appareil")
    got = alice.receipt(m)
    assert got == "remis", f"attendu 'remis' (portable en ligne), obtenu {got!r}"


def test_A26_message_becomes_delivered_when_contact_reconnects(alice, bob):
    bob.set_online(False)
    m = alice.send("bob", "à la reconnexion")
    assert alice.receipt(m) == "envoyé"
    bob.set_online(True)
    got = alice.receipt(m)
    assert got == "remis", f"attendu 'remis' après reconnexion du destinataire, obtenu {got!r}"


def test_A27_group_message_not_delivered_until_all_members_received(alice, bob, carol):
    g = alice.create_group("g", ["bob", "carol"])
    carol.set_online(False)
    m = alice.send(g, "pour tous")
    got = alice.receipt(m)
    assert got != "remis", f"'remis' alors que carol n'a pas reçu (obtenu {got!r})"
    carol.set_online(True)
    got = alice.receipt(m)
    assert got == "remis", f"attendu 'remis' quand tous les membres ont reçu, obtenu {got!r}"


def test_A28_opening_by_recipient_marks_read(alice, bob):
    m = alice.send("bob", "lis-moi")
    bob.open(m)
    got = alice.receipt(m)
    assert got == "lu", f"attendu 'lu' après ouverture par bob, obtenu {got!r}"


def test_A28_not_read_before_opening(alice, bob):
    m = alice.send("bob", "pas encore ouvert")
    got = alice.receipt(m)
    assert got == "remis", f"attendu 'remis' avant ouverture, obtenu {got!r}"


# --------------------------------------------------------------------------- A29 / A30


def test_A29_choosing_duration_sets_conversation_timer(alice, bob):
    alice.set_timer("bob", 3600)
    got = alice.timer("bob")
    assert got == 3600, f"attendu minuteur 3600, obtenu {got!r}"


def test_A30_group_timer_change_applies_to_all_members(alice, bob, carol):
    g = alice.create_group("g", ["bob", "carol"])
    bob.set_timer(g, 300)
    for u in (alice, bob, carol):
        got = u.timer(g)
        assert got == 300, f"minuteur de {u.name} : attendu 300, obtenu {got!r}"


# --------------------------------------------------------------------------- A31 – A35 (éphémères)


def set_both_timers(alice, bob, seconds):
    alice.set_timer("bob", seconds)
    bob.set_timer("alice", seconds)


def test_A31_ephemeral_read_message_disappears_after_duration(net, alice, bob):
    set_both_timers(alice, bob, 60)
    m = alice.send("bob", "éphémère")
    bob.open(m)
    net.advance(30)
    assert m in bob.conversation("alice"), "message disparu avant la fin de la durée"
    net.advance(31)
    assert m not in bob.conversation("alice"), \
        f"message encore présent après la durée : {bob.conversation('alice')!r}"


def test_A32_message_with_timer_disabled_stays(net, alice, bob):
    m = alice.send("bob", "permanent")
    bob.open(m)
    net.advance(10 ** 8)
    assert m in bob.conversation("alice"), "message sans minuteur disparu chez le destinataire"
    assert m in alice.conversation("bob"), "message sans minuteur disparu chez l'expéditeur"


def test_A32_message_after_timer_disabled_stays(net, alice, bob):
    set_both_timers(alice, bob, 60)
    set_both_timers(alice, bob, None)
    m = alice.send("bob", "minuteur coupé")
    bob.open(m)
    net.advance(10 ** 6)
    assert m in bob.conversation("alice"), "message envoyé minuteur désactivé a disparu"


def test_A33_unread_ephemeral_message_stays_for_recipient(net, alice, bob):
    set_both_timers(alice, bob, 60)
    m = alice.send("bob", "pas lu")
    net.advance(10 * 60)
    assert alice.receipt(m) != "lu"
    assert m in bob.conversation("alice"), "message éphémère non lu disparu chez le destinataire"


def test_A34_sent_message_keeps_original_duration_when_timer_lengthened(net, alice, bob):
    set_both_timers(alice, bob, 60)
    m = alice.send("bob", "court")
    bob.open(m)
    set_both_timers(alice, bob, 7 * 24 * 3600)
    net.advance(61)
    assert m not in bob.conversation("alice"), "le message a pris la nouvelle durée (plus longue)"


def test_A34_sent_message_keeps_original_duration_when_timer_shortened(net, alice, bob):
    set_both_timers(alice, bob, 3600)
    m = alice.send("bob", "long")
    bob.open(m)
    set_both_timers(alice, bob, 10)
    net.advance(61)
    assert m in bob.conversation("alice"), "le message a pris la nouvelle durée (plus courte)"


def test_A34_sent_message_keeps_duration_when_timer_disabled(net, alice, bob):
    set_both_timers(alice, bob, 60)
    m = alice.send("bob", "toujours éphémère")
    bob.open(m)
    set_both_timers(alice, bob, None)
    net.advance(61)
    assert m not in bob.conversation("alice"), "désactiver le minuteur a rendu permanent un message déjà envoyé"


def test_A35_disappeared_message_disappears_on_other_linked_devices(net, alice, bob):
    bob.link_device("portable")
    set_both_timers(alice, bob, 60)
    m = alice.send("bob", "multi-appareils")
    assert m in bob.conversation("alice", device="portable"), "contrôle : reçu sur 'portable'"
    bob.open(m, device=PRIMARY)
    net.advance(61)
    assert m not in bob.conversation("alice", device=PRIMARY), "contrôle : disparu sur l'appareil principal"
    assert m not in bob.conversation("alice", device="portable"), \
        "message disparu sur l'appareil principal mais encore présent sur 'portable'"
