"""Tests rouges — sonde P10, couche code.

Interface publique fixée par ces tests (module unique `app`) :

    net = app.Network()                      # réseau simulé + serveur + horloge
    net.advance(seconds)                     # fait avancer le temps
    net.server.received() -> list[bytes]     # tout ce que le serveur a reçu, dans l'ordre
    net.set_interceptor(fn | None)           # fn(bytes) -> bytes, appliqué à chaque blob en transit

    user = net.create_user(name)             # utilisateur sans appareil
    dev  = user.link_device(device_name)     # crée et lie un appareil (clés générées sur l'appareil)
    user.remove_device(device_name)
    user.devices() -> list[str]              # noms des appareils liés
    user.add_contact(name)
    user.verification_state(name) -> "vérifié" | "non vérifié"
    user.fingerprint() -> str                # empreinte propre (code de sécurité affiché)
    user.fingerprint_of(name) -> str         # empreinte du contact telle que vue par user
    user.scan_safety_code(name, code)
    user.confirm_identity(name)              # confirme un changement d'empreinte
    gid = user.create_group(group_name)      # le créateur est membre
    user.add_member(gid, name); user.remove_member(gid, name)
    user.group_members(gid) -> list[str]

    dev.name
    dev.send(name, text) -> Message
    dev.send_group(gid, text) -> Message
    dev.conversation(name) -> list[str]      # textes en clair affichés (envoyés et reçus)
    dev.group_conversation(gid) -> list[str]
    dev.warnings(name) -> list[str]
    dev.set_online(bool)
    dev.reinstall()                          # nouvelles clés, l'empreinte de l'utilisateur change
    dev.read(name)                           # lit les messages reçus affichés dans la conversation
    dev.set_timer(name, seconds | None)      # None = minuterie désactivée
    dev.timer(name) -> int | None
    dev.try_open(blob) -> str | None         # tente de déchiffrer avec les seules clés de l'appareil
    dev.message_key(msg) -> bytes            # clé de message utilisée pour msg (divulgation)

    msg.send_state -> "en attente" | "envoyé" | "bloqué"
    msg.receipt(name=None) -> str            # "remis" une fois reçu par un appareil du destinataire

    app.open_with_key(key, blob) -> str | None   # fonction pure : déchiffre blob avec une clé de message
"""

import base64
import os
import subprocess
import sys

import pytest

import app

APP_DIR = os.path.dirname(os.path.abspath(app.__file__))
HOUR = 3600


# --------------------------------------------------------------------------- helpers

def pair():
    net = app.Network()
    alice = net.create_user("alice")
    bob = net.create_user("bob")
    ap = alice.link_device("phone")
    bp = bob.link_device("phone")
    alice.add_contact("bob")
    bob.add_contact("alice")
    return net, alice, bob, ap, bp


def group3():
    net, alice, bob, ap, bp = pair()
    carol = net.create_user("carol")
    cp = carol.link_device("phone")
    carol.add_contact("alice")
    carol.add_contact("bob")
    alice.add_contact("carol")
    bob.add_contact("carol")
    gid = alice.create_group("famille")
    return net, alice, bob, carol, ap, bp, cp, gid


def blobs(net):
    return list(net.server.received())


def mark(net):
    return len(net.server.received())


def since(net, before):
    return list(net.server.received())[before:]


def open_in_fresh_process(key, blob):
    """Appelle app.open_with_key dans un autre processus : aucune table partagée possible."""
    code = (
        "import sys, app\n"
        "k = bytes.fromhex(sys.argv[1]); b = bytes.fromhex(sys.argv[2])\n"
        "r = app.open_with_key(k, b)\n"
        "sys.stdout.write('NONE' if r is None else 'TEXT:' + r.encode('utf-8').hex())\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = APP_DIR + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        [sys.executable, "-c", code, key.hex(), blob.hex()],
        cwd=APP_DIR, capture_output=True, text=True, timeout=15, env=env,
    )
    assert out.returncode == 0, f"le sous-processus a échoué : {out.stderr}"
    if out.stdout == "NONE":
        return None
    assert out.stdout.startswith("TEXT:"), f"sortie inattendue : {out.stdout!r}"
    return bytes.fromhex(out.stdout[5:]).decode("utf-8")


def encodings_of(text):
    raw = text.encode("utf-8")
    return [raw, text.encode("utf-16-le"), base64.b64encode(raw), raw.hex().encode()]


# --------------------------------------------------------------------------- A01

def test_A01_message_affiche_en_clair_chez_destinataire():
    net, alice, bob, ap, bp = pair()
    ap.send("bob", "bonjour Bob, rendez-vous à 18h")
    conv = bp.conversation("alice")
    assert "bonjour Bob, rendez-vous à 18h" in conv, f"attendu le message en clair chez bob, obtenu {conv!r}"


def test_A01_texte_non_ascii_intact():
    net, alice, bob, ap, bp = pair()
    text = "Été — 你好 🙂 \r\n ligne2\n"
    ap.send("bob", text)
    conv = bp.conversation("alice")
    assert text in conv, f"attendu {text!r} intact, obtenu {conv!r}"


def test_A01_echanges_dans_les_deux_sens_restent_lisibles():
    net, alice, bob, ap, bp = pair()
    expected_b, expected_a = [], []
    for i in range(12):
        t = f"a->b numéro {i}"
        ap.send("bob", t)
        expected_b.append(t)
        if i % 3 == 0:
            u = f"b->a numéro {i}"
            bp.send("alice", u)
            expected_a.append(u)
    conv_b = bp.conversation("alice")
    conv_a = ap.conversation("bob")
    missing_b = [t for t in expected_b if t not in conv_b]
    missing_a = [t for t in expected_a if t not in conv_a]
    assert not missing_b, f"messages absents chez bob : {missing_b}"
    assert not missing_a, f"messages absents chez alice : {missing_a}"


# --------------------------------------------------------------------------- A02

def test_A02_message_affiche_sur_les_deux_appareils_lies():
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    ap.send("bob", "pour tous tes appareils")
    assert "pour tous tes appareils" in bp.conversation("alice"), f"absent du phone : {bp.conversation('alice')!r}"
    assert "pour tous tes appareils" in tablet.conversation("alice"), f"absent de la tablette : {tablet.conversation('alice')!r}"


def test_A02_appareils_du_meme_utilisateur_ont_des_cles_distinctes():
    # Chaque appareil génère ses propres clés : l'enveloppe destinée au phone ne s'ouvre
    # pas avec la tablette si on la lui présente avant que le phone ne la consomme.
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    bp.set_online(False)
    tablet.set_online(False)
    before = mark(net)
    ap.send("bob", "enveloppes séparées")
    new = since(net, before)
    assert len(new) >= 2, f"attendu au moins une enveloppe par appareil (2), obtenu {len(new)}"
    opened_by_tablet = [b for b in new if tablet.try_open(b) == "enveloppes séparées"]
    assert len(opened_by_tablet) <= 1, (
        f"la tablette ouvre {len(opened_by_tablet)} enveloppes : les appareils partagent une clé"
    )


# --------------------------------------------------------------------------- A03

def test_A03_appareil_hors_liste_ne_peut_pas_lire():
    net, alice, bob, ap, bp = pair()
    eve = net.create_user("eve")
    ep = eve.link_device("phone")
    eve.add_contact("alice")
    before = mark(net)
    ap.send("bob", "secret pour bob seulement")
    new = since(net, before)
    assert new, "le serveur n'a rien reçu : le message n'a pas transité"
    opened = [ep.try_open(b) for b in new]
    assert all(o is None for o in opened), f"un appareil hors liste a déchiffré : {opened!r}"
    assert "secret pour bob seulement" not in ep.conversation("alice")
    assert "secret pour bob seulement" not in ep.conversation("bob")


def test_A03_trou_autre_appareil_expediteur():
    net, alice, bob, ap, bp = pair()
    laptop = alice.link_device("laptop")
    ap.send("bob", "seulement les appareils de bob")
    assert "seulement les appareils de bob" not in laptop.conversation("bob"), (
        "A03 littéral : l'autre appareil de l'expéditeur n'est pas dans la liste du destinataire"
    )


# --------------------------------------------------------------------------- A04

def test_A04_serveur_ne_recoit_que_des_octets_sans_le_clair():
    net, alice, bob, ap, bp = pair()
    text = "code du coffre : 4815162342 — confidentiel"
    before = mark(net)
    ap.send("bob", text)
    new = since(net, before)
    assert new, "le serveur n'a rien reçu"
    for b in new:
        assert isinstance(b, bytes), f"le serveur a reçu un {type(b).__name__}, attendu bytes"
        for enc in encodings_of(text):
            assert enc not in b, f"le clair (encodage {enc[:12]!r}…) apparaît dans un blob serveur"
        assert b"4815162342" not in b


def test_A04_meme_texte_deux_fois_donne_des_chiffres_differents():
    net, alice, bob, ap, bp = pair()
    m0 = mark(net)
    ap.send("bob", "identique")
    first = since(net, m0)
    m1 = mark(net)
    ap.send("bob", "identique")
    second = since(net, m1)
    common = set(first) & set(second)
    assert not common, "deux envois du même texte produisent un blob identique : chiffrement déterministe ou absent"


def test_A04_cle_de_message_ne_passe_pas_par_le_serveur():
    net, alice, bob, ap, bp = pair()
    msg = ap.send("bob", "la clé reste chez moi")
    key = ap.message_key(msg)
    assert isinstance(key, bytes) and len(key) >= 16, f"clé de message inattendue : {key!r}"
    for b in blobs(net):
        assert key not in b, "la clé de message a transité par le serveur"
        assert key.hex().encode() not in b
        assert base64.b64encode(key) not in b


# --------------------------------------------------------------------------- A05 / A06

def _conversation_with_keys():
    net, alice, bob, ap, bp = pair()
    seq = [(ap, "bob"), (ap, "bob"), (bp, "alice"), (ap, "bob"), (bp, "alice"), (bp, "alice"), (ap, "bob")]
    out = []
    for i, (dev, to) in enumerate(seq):
        text = f"message {i} de la conversation"
        before = mark(net)
        msg = dev.send(to, text)
        window = since(net, before)
        out.append((text, dev.message_key(msg), window))
    return out


def test_A05_cle_divulguee_ne_lit_pas_les_messages_precedents():
    data = _conversation_with_keys()
    leaked_idx = 4
    _, key, _ = data[leaked_idx]
    for text, _, window in data[:leaked_idx]:
        for b in window:
            r = app.open_with_key(key, b)
            assert r is None, f"la clé du message {leaked_idx} déchiffre un message précédent : {r!r}"


def test_A05_cle_divulguee_ouvre_bien_son_propre_message_hors_processus():
    # Garde-fou : la clé divulguée est une vraie clé, utilisable sans aucun état partagé.
    data = _conversation_with_keys()
    text, key, window = data[3]
    results = [open_in_fresh_process(key, b) for b in window]
    assert text in results, f"la clé de message n'ouvre pas son blob dans un processus neuf : {results!r}"
    wrong = os.urandom(len(key))
    assert all(open_in_fresh_process(wrong, b) is None for b in window), "une clé aléatoire ouvre le blob"


def test_A05_cles_de_message_toutes_distinctes():
    data = _conversation_with_keys()
    keys = [k for _, k, _ in data]
    assert len(set(keys)) == len(keys), "deux messages partagent la même clé de message"


def test_A06_cle_divulguee_ne_lit_pas_les_messages_suivants():
    data = _conversation_with_keys()
    leaked_idx = 1
    _, key, _ = data[leaked_idx]
    for text, _, window in data[leaked_idx + 1:]:
        for b in window:
            r = app.open_with_key(key, b)
            assert r is None, f"la clé du message {leaked_idx} déchiffre un message suivant : {r!r}"


# --------------------------------------------------------------------------- A07

def test_A07_tout_octet_altere_empeche_l_affichage():
    net, alice, bob, ap, bp = pair()
    before = mark(net)
    ap.send("bob", "étalon")
    sizes = [len(b) for b in since(net, before)]
    length = max(sizes)
    positions = sorted(set([0, 1, length // 2, length - 1] + list(range(0, length, max(1, length // 16)))))
    for p in positions:
        text = f"altéré à la position {p}"

        def flip(b, p=p):
            ba = bytearray(b)
            ba[p % len(ba)] ^= 0x01
            return bytes(ba)

        net.set_interceptor(flip)
        ap.send("bob", text)
        net.set_interceptor(None)
        assert text not in bp.conversation("alice"), f"un blob altéré à l'octet {p} s'affiche en clair"
    ap.send("bob", "intact après les altérations")
    assert "intact après les altérations" in bp.conversation("alice"), (
        "après des blobs altérés, un message intact devrait encore s'afficher"
    )


def test_A07_blob_tronque_ne_s_affiche_pas():
    net, alice, bob, ap, bp = pair()
    net.set_interceptor(lambda b: b[:-1])
    ap.send("bob", "tronqué en route")
    net.set_interceptor(None)
    assert "tronqué en route" not in bp.conversation("alice")


# --------------------------------------------------------------------------- A08 / A09

def test_A08_appareil_lie_apparait_dans_la_liste():
    net, alice, bob, ap, bp = pair()
    bob.link_device("tablet")
    devs = bob.devices()
    assert "tablet" in devs and "phone" in devs, f"attendu phone et tablet, obtenu {devs!r}"


def test_A09_appareil_retire_disparait_de_la_liste():
    net, alice, bob, ap, bp = pair()
    bob.link_device("tablet")
    bob.remove_device("tablet")
    devs = bob.devices()
    assert "tablet" not in devs, f"la tablette retirée est encore listée : {devs!r}"
    assert "phone" in devs, f"le phone a disparu à tort : {devs!r}"


# --------------------------------------------------------------------------- A10

def test_A10_appareil_retire_ne_lit_pas_les_messages_suivants():
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    ap.send("bob", "avant retrait")
    bob.remove_device("tablet")
    before = mark(net)
    ap.send("bob", "après retrait")
    new = since(net, before)
    assert "après retrait" not in tablet.conversation("alice"), "l'appareil retiré affiche un message ultérieur"
    opened = [tablet.try_open(b) for b in new]
    assert all(o is None for o in opened), f"l'appareil retiré déchiffre un blob ultérieur : {opened!r}"
    assert "après retrait" in bp.conversation("alice"), "l'appareil restant doit toujours lire"


# --------------------------------------------------------------------------- A11

def test_A11_nouvel_appareil_ne_montre_pas_l_historique():
    net, alice, bob, ap, bp = pair()
    ap.send("bob", "ancien message")
    assert "ancien message" in bp.conversation("alice")
    tablet = bob.link_device("tablet")
    assert "ancien message" not in tablet.conversation("alice"), (
        f"le nouvel appareil affiche l'historique : {tablet.conversation('alice')!r}"
    )
    ap.send("bob", "nouveau message")
    assert "nouveau message" in tablet.conversation("alice"), "le nouvel appareil doit lire les messages suivants"


def test_A11_message_en_attente_avant_liaison_ne_s_affiche_pas():
    net, alice, bob, ap, bp = pair()
    bp.set_online(False)
    ap.send("bob", "reçu avant la liaison")
    tablet = bob.link_device("tablet")
    assert "reçu avant la liaison" not in tablet.conversation("alice")


# --------------------------------------------------------------------------- A12 – A14

def test_A12_contact_ajoute_non_verifie():
    net, alice, bob, ap, bp = pair()
    assert alice.verification_state("bob") == "non vérifié"


def test_A13_scan_du_bon_code_verifie():
    net, alice, bob, ap, bp = pair()
    assert alice.fingerprint_of("bob") == bob.fingerprint(), "les deux côtés doivent afficher la même empreinte"
    alice.scan_safety_code("bob", bob.fingerprint())
    assert alice.verification_state("bob") == "vérifié"


def test_A14_scan_d_un_autre_code_laisse_non_verifie():
    net, alice, bob, ap, bp = pair()
    eve = net.create_user("eve")
    eve.link_device("phone")
    alice.scan_safety_code("bob", eve.fingerprint())
    assert alice.verification_state("bob") == "non vérifié"


def test_A14_code_a_un_caractere_pres_laisse_non_verifie():
    net, alice, bob, ap, bp = pair()
    fp = bob.fingerprint()
    last = fp[-1]
    altered = fp[:-1] + ("0" if last != "0" else "1")
    alice.scan_safety_code("bob", altered)
    assert alice.verification_state("bob") == "non vérifié"


def test_A14_scan_du_code_d_alice_elle_meme_laisse_non_verifie():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", alice.fingerprint())
    assert alice.verification_state("bob") == "non vérifié"


# --------------------------------------------------------------------------- A15

def test_A15_reinstallation_change_l_empreinte():
    net, alice, bob, ap, bp = pair()
    fp0 = alice.fingerprint_of("bob")
    bp.reinstall()
    fp1 = alice.fingerprint_of("bob")
    bp.reinstall()
    fp2 = alice.fingerprint_of("bob")
    assert len({fp0, fp1, fp2}) == 3, f"empreintes attendues distinctes, obtenu {fp0!r}, {fp1!r}, {fp2!r}"
    assert fp2 == bob.fingerprint()


def test_A15_utilisateurs_differents_empreintes_differentes():
    net, alice, bob, ap, bp = pair()
    assert alice.fingerprint() != bob.fingerprint()


# --------------------------------------------------------------------------- A16 – A19

def _verified_then_reinstall():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", bob.fingerprint())
    assert alice.verification_state("bob") == "vérifié"
    bp.reinstall()
    return net, alice, bob, ap, bp


def test_A16_changement_d_empreinte_repasse_non_verifie():
    net, alice, bob, ap, bp = _verified_then_reinstall()
    assert alice.verification_state("bob") == "non vérifié"


def test_A16_trou_confirmation_ne_reverifie_pas():
    net, alice, bob, ap, bp = _verified_then_reinstall()
    alice.confirm_identity("bob")
    assert alice.verification_state("bob") == "non vérifié"


def test_A17_avertissement_si_contact_verifie_change():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", bob.fingerprint())
    assert ap.warnings("bob") == [], f"aucun avertissement attendu avant changement, obtenu {ap.warnings('bob')!r}"
    bp.reinstall()
    w = ap.warnings("bob")
    assert len(w) >= 1, "un avertissement doit s'afficher dans la conversation"


def test_A18_pas_d_avertissement_si_contact_non_verifie():
    net, alice, bob, ap, bp = pair()
    bp.reinstall()
    assert alice.fingerprint_of("bob") == bob.fingerprint()
    assert ap.warnings("bob") == [], f"aucun avertissement attendu, obtenu {ap.warnings('bob')!r}"


def test_A19_envoi_bloque_apres_changement_d_empreinte():
    net, alice, bob, ap, bp = _verified_then_reinstall()
    msg = ap.send("bob", "doit attendre la confirmation")
    assert msg.send_state == "bloqué", f"attendu « bloqué », obtenu {msg.send_state!r}"
    assert "doit attendre la confirmation" not in bp.conversation("alice")


def test_A19_rien_ne_part_vers_le_serveur_avant_confirmation():
    net, alice, bob, ap, bp = _verified_then_reinstall()
    before = mark(net)
    ap.send("bob", "rien ne sort")
    for b in since(net, before):
        assert bp.try_open(b) != "rien ne sort", "le message bloqué a quand même été transmis"


def test_A19_trou_confirmation_libere_message():
    net, alice, bob, ap, bp = _verified_then_reinstall()
    msg = ap.send("bob", "libéré par la confirmation")
    alice.confirm_identity("bob")
    assert msg.send_state == "envoyé", f"attendu « envoyé » après confirmation, obtenu {msg.send_state!r}"
    assert "libéré par la confirmation" in bp.conversation("alice")


def test_A19_trou_non_verifie_pas_bloque():
    net, alice, bob, ap, bp = pair()
    bp.reinstall()
    msg = ap.send("bob", "contact non vérifié réinstallé")
    assert msg.send_state != "bloqué"
    assert "contact non vérifié réinstallé" in bp.conversation("alice")


# --------------------------------------------------------------------------- A20 – A23

def test_A20_envoi_hors_ligne_en_attente():
    net, alice, bob, ap, bp = pair()
    ap.set_online(False)
    msg = ap.send("bob", "pas de réseau")
    assert msg.send_state == "en attente", f"attendu « en attente », obtenu {msg.send_state!r}"
    assert "pas de réseau" not in bp.conversation("alice")


def test_A21_retour_en_ligne_passe_a_envoye():
    net, alice, bob, ap, bp = pair()
    ap.set_online(False)
    msg = ap.send("bob", "réseau revenu")
    ap.set_online(True)
    assert msg.send_state == "envoyé", f"attendu « envoyé », obtenu {msg.send_state!r}"
    assert "réseau revenu" in bp.conversation("alice")


def test_A22_destinataire_hors_ligne_pas_remis():
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    bp.set_online(False)
    tablet.set_online(False)
    msg = ap.send("bob", "personne n'est là")
    assert msg.receipt() != "remis", f"accusé « remis » alors qu'aucun appareil n'est en ligne"


def test_A22_trou_un_appareil_en_ligne_suffit():
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    tablet.set_online(False)
    msg = ap.send("bob", "le phone est là")
    assert msg.receipt() == "remis", f"attendu « remis », obtenu {msg.receipt()!r}"


def test_A23_retour_en_ligne_du_destinataire_passe_a_remis():
    net, alice, bob, ap, bp = pair()
    bp.set_online(False)
    msg = ap.send("bob", "je t'attends")
    assert msg.receipt() != "remis"
    bp.set_online(True)
    assert "je t'attends" in bp.conversation("alice")
    assert msg.receipt() == "remis", f"attendu « remis », obtenu {msg.receipt()!r}"


# --------------------------------------------------------------------------- A24 – A29

def test_A24_contact_ajoute_apparait_dans_les_membres():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    assert "bob" in alice.group_members(gid), f"obtenu {alice.group_members(gid)!r}"
    assert "carol" not in alice.group_members(gid)


def test_A24_trou_liste_vue_par_autre_membre():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    assert "carol" in bob.group_members(gid), f"bob voit {bob.group_members(gid)!r}"


def test_A25_contact_retire_disparait_des_membres():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    alice.remove_member(gid, "bob")
    members = alice.group_members(gid)
    assert "bob" not in members and "carol" in members, f"obtenu {members!r}"


def test_A26_message_de_groupe_lisible_chez_chaque_membre():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    ap.send_group(gid, "dîner dimanche ?")
    assert "dîner dimanche ?" in bp.group_conversation(gid)
    assert "dîner dimanche ?" in cp.group_conversation(gid)
    bp.send_group(gid, "oui !")
    assert "oui !" in ap.group_conversation(gid)
    assert "oui !" in cp.group_conversation(gid)


def test_A26_serveur_ne_voit_pas_le_clair_du_groupe():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    before = mark(net)
    ap.send_group(gid, "groupe confidentiel 99731")
    for b in since(net, before):
        assert b"99731" not in b and "groupe confidentiel".encode() not in b


def test_A27_membre_retire_ne_lit_pas():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    ap.send_group(gid, "avant le retrait")
    assert "avant le retrait" in bp.group_conversation(gid)
    alice.remove_member(gid, "bob")
    before = mark(net)
    ap.send_group(gid, "bob ne doit pas lire ceci")
    new = since(net, before)
    assert "bob ne doit pas lire ceci" not in bp.group_conversation(gid)
    opened = [bp.try_open(b) for b in new]
    assert "bob ne doit pas lire ceci" not in opened, "le membre retiré déchiffre un message ultérieur"
    assert "bob ne doit pas lire ceci" in cp.group_conversation(gid)


def test_A27_membre_retire_ne_lit_pas_les_messages_d_un_autre_membre():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    cp.send_group(gid, "carol avant")
    alice.remove_member(gid, "bob")
    before = mark(net)
    cp.send_group(gid, "carol après le retrait de bob")
    opened = [bp.try_open(b) for b in since(net, before)]
    assert "carol après le retrait de bob" not in opened
    assert "carol après le retrait de bob" not in bp.group_conversation(gid)
    assert "carol après le retrait de bob" in ap.group_conversation(gid)


def test_A28_nouveau_membre_ne_voit_pas_l_historique():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    before = mark(net)
    ap.send_group(gid, "avant l'arrivée de carol")
    old = since(net, before)
    alice.add_member(gid, "carol")
    assert "avant l'arrivée de carol" not in cp.group_conversation(gid)
    opened = [cp.try_open(b) for b in old]
    assert "avant l'arrivée de carol" not in opened, "le nouveau membre déchiffre un message antérieur"
    ap.send_group(gid, "bienvenue carol")
    assert "bienvenue carol" in cp.group_conversation(gid)


def test_A29_membre_hors_ligne_pas_remis():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    cp.set_online(False)
    msg = ap.send_group(gid, "carol dort")
    assert msg.receipt("carol") != "remis", "accusé « remis » pour un membre hors ligne"
    assert msg.receipt("bob") == "remis", f"bob en ligne : attendu « remis », obtenu {msg.receipt('bob')!r}"
    cp.set_online(True)
    assert msg.receipt("carol") == "remis"


# --------------------------------------------------------------------------- A30 – A36

def test_A30_minuterie_une_heure_affichee():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    assert ap.timer("bob") == HOUR, f"obtenu {ap.timer('bob')!r}"


def test_A31_minuterie_visible_chez_l_autre_participant():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    assert bp.timer("alice") == HOUR, f"obtenu {bp.timer('alice')!r}"
    bp.set_timer("alice", 300)
    assert ap.timer("bob") == 300, f"obtenu {ap.timer('bob')!r}"


def test_A31_trou_participant_hors_ligne_voit_la_minuterie_au_retour():
    net, alice, bob, ap, bp = pair()
    bp.set_online(False)
    ap.set_timer("bob", HOUR)
    bp.set_online(True)
    assert bp.timer("alice") == HOUR


def test_A32_message_disparait_chez_destinataire():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "éphémère")
    bp.read("alice")
    net.advance(HOUR - 1)
    assert "éphémère" in bp.conversation("alice"), "disparu avant la fin de la minuterie"
    net.advance(2)
    assert "éphémère" not in bp.conversation("alice"), "toujours affiché après la minuterie"


def test_A32_non_lu_ne_disparait_pas():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "pas encore lu")
    net.advance(10 * HOUR)
    assert "pas encore lu" in bp.conversation("alice")


def test_A32_trou_borne_exacte():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "borne")
    bp.read("alice")
    net.advance(HOUR)
    assert "borne" not in bp.conversation("alice")


def test_A33_message_disparait_chez_expediteur():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "côté expéditeur")
    assert "côté expéditeur" in ap.conversation("bob")
    bp.read("alice")
    net.advance(HOUR + 1)
    assert "côté expéditeur" not in ap.conversation("bob")


def test_A33_trou_non_lu_reste_chez_expediteur():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "jamais lu")
    net.advance(HOUR + 1)
    assert "jamais lu" in ap.conversation("bob")


def test_A34_minuterie_desactivee_message_reste():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.set_timer("bob", None)
    assert ap.timer("bob") is None
    ap.send("bob", "permanent")
    bp.read("alice")
    net.advance(10 * 365 * 24 * HOUR)
    assert "permanent" in bp.conversation("alice")
    assert "permanent" in ap.conversation("bob")


def test_A35_modification_conserve_la_duree_d_origine():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "une heure")
    ap.set_timer("bob", 300)
    ap.send("bob", "cinq minutes")
    bp.read("alice")
    net.advance(301)
    conv = bp.conversation("alice")
    assert "cinq minutes" not in conv, f"le message à 5 min devrait avoir disparu : {conv!r}"
    assert "une heure" in conv, f"le message à 1 h a perdu sa durée d'origine : {conv!r}"
    net.advance(HOUR)
    assert "une heure" not in bp.conversation("alice")


def test_A35_desactivation_n_eternise_pas_les_anciens():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "garde sa minuterie")
    bp.set_timer("alice", None)
    bp.read("alice")
    net.advance(HOUR + 1)
    assert "garde sa minuterie" not in bp.conversation("alice")


def test_A36_ephemere_recu_hors_ligne_attend_la_lecture():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    bp.set_online(False)
    ap.send("bob", "pendant ton absence")
    net.advance(5 * HOUR)
    bp.set_online(True)
    assert "pendant ton absence" in bp.conversation("alice"), "disparu avant d'avoir été lu"
    net.advance(5 * HOUR)
    assert "pendant ton absence" in bp.conversation("alice"), "disparu sans lecture"
    bp.read("alice")
    net.advance(HOUR + 1)
    assert "pendant ton absence" not in bp.conversation("alice")
