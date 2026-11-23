"""Tests rouges — messagerie chiffrée de bout en bout (sonde P10).

Interface publique fixée par ces tests (module `app`) :

    net = app.Network()
    net.advance(seconds)                      # fait avancer le temps simulé
    net.server.received_payloads() -> list[bytes]
        # tous les octets reçus par le serveur, dans l'ordre d'arrivée (journal, jamais vidé)
    net.server.set_tamper(fn)                 # fn(bytes) -> bytes, appliquée à chaque charge
        # utile livrée par le serveur à un appareil (altération en transit) ; None = désactive
    net.server.inject_device(username, name) -> Device
        # serveur malveillant : publie un appareil sous le compte de `username` sans liaison

    user = net.create_user(username, first_device_name) -> User
    user.device(name) -> Device
    user.link_device(name) -> Device
    user.remove_device(name)
    user.list_devices() -> list[str]          # noms des appareils liés

    dev.send(peer_username, text) -> str      # identifiant de message, global
    dev.send_status(message_id) -> "en attente" | "envoyé" | "bloqué"
    dev.receipt(message_id, member=None) -> str   # "remis" quand remis ; member pour un groupe
    dev.conversation(peer_username) -> list[str]  # textes affichés en clair (vue pure, ne lit pas)
    dev.mark_read(peer_username)              # l'utilisateur lit la conversation
    dev.message_key(message_id) -> bytes      # clé avec laquelle CET appareil a déchiffré ce message
    dev.try_open(payload: bytes) -> str | None    # l'appareil tente de déchiffrer avec ses propres clés
    dev.go_offline() / dev.go_online()
    dev.reinstall()                           # réinstallation : nouvelles clés, même nom
    dev.add_contact(username)
    dev.verification_state(username) -> "vérifié" | "non vérifié"
    dev.security_code() -> str                # code de sécurité (QR) de l'appareil lui-même
    dev.scan_code(username, code)
    dev.fingerprint(username) -> str          # empreinte affichée du contact
    dev.warnings(username) -> list[str]       # avertissements affichés dans la conversation
    dev.confirm_fingerprint_change(username)
    dev.set_timer(peer_username, seconds | None) ; dev.timer(peer_username) -> int | None
    dev.create_group(name) -> str             # identifiant de groupe, global
    dev.add_member(group_id, username) ; dev.remove_member(group_id, username)
    dev.group_members(group_id) -> list[str]
    dev.send_group(group_id, text) -> str
    dev.group_conversation(group_id) -> list[str]

    app.try_decrypt(key: bytes, payload: bytes) -> str | None
        # routine de déchiffrement du système, appliquée avec une clé arbitraire
"""

import base64
import os
import zlib

import pytest

import app


# --------------------------------------------------------------------------- helpers

def make(*names):
    net = app.Network()
    users = {n: net.create_user(n, "phone") for n in names}
    devs = {n: users[n].device("phone") for n in names}
    return net, users, devs


def uniq(prefix="secret"):
    return f"{prefix}-{os.urandom(10).hex()}-confidentiel"


def payloads(net):
    return list(net.server.received_payloads())


def leak_forms(text):
    t = text.encode("utf-8")
    forms = [t, t[::-1], text.encode("utf-16-le"), text.encode("utf-16-be"), t.hex().encode()]
    for k in range(3):
        for enc in (base64.b64encode, base64.urlsafe_b64encode):
            b = enc(t[k:])
            if len(b) > 12:
                forms.append(b[4:-4])
    return forms


def leaks(text, blob):
    return any(f in blob for f in leak_forms(text))


def flip(i):
    def fn(p):
        if i < len(p):
            p = bytearray(p)
            p[i] ^= 0x01
            return bytes(p)
        return p
    return fn


# --------------------------------------------------------------------------- A01

def test_A01_message_lisible_chez_le_destinataire():
    net, u, d = make("alice", "bob")
    t = uniq()
    d["alice"].send("bob", t)
    conv = d["bob"].conversation("alice")
    assert t in conv, f"attendu {t!r} affiché chez bob, obtenu {conv!r}"


def test_A01_texte_non_ascii_lisible_a_l_identique():
    net, u, d = make("alice", "bob")
    t = "héllo ✓ 日本語 — ça marche ? \r\n🙂 " + os.urandom(4).hex()
    d["alice"].send("bob", t)
    conv = d["bob"].conversation("alice")
    assert t in conv, f"attendu le texte exact {t!r}, obtenu {conv!r}"


def test_A01_ordre_des_messages_preserve():
    net, u, d = make("alice", "bob")
    texts = [uniq(f"m{i}") for i in range(5)]
    for t in texts:
        d["alice"].send("bob", t)
    conv = d["bob"].conversation("alice")
    got = [c for c in conv if c in texts]
    assert got == texts, f"attendu {texts!r} dans l'ordre, obtenu {got!r}"


def test_A01_conversation_dans_les_deux_sens():
    net, u, d = make("alice", "bob")
    t1, t2, t3 = uniq("a1"), uniq("b1"), uniq("a2")
    d["alice"].send("bob", t1)
    d["bob"].send("alice", t2)
    d["alice"].send("bob", t3)
    assert t1 in d["bob"].conversation("alice") and t3 in d["bob"].conversation("alice"), \
        f"bob devrait voir {t1!r} et {t3!r}, obtenu {d['bob'].conversation('alice')!r}"
    assert t2 in d["alice"].conversation("bob"), \
        f"alice devrait voir {t2!r}, obtenu {d['alice'].conversation('bob')!r}"


# --------------------------------------------------------------------------- A02

def test_A02_message_lisible_sur_les_deux_appareils_lies():
    net, u, d = make("alice", "bob")
    tablet = u["bob"].link_device("tablet")
    t = uniq()
    d["alice"].send("bob", t)
    assert t in d["bob"].conversation("alice"), \
        f"phone de bob : attendu {t!r}, obtenu {d['bob'].conversation('alice')!r}"
    assert t in tablet.conversation("alice"), \
        f"tablet de bob : attendu {t!r}, obtenu {tablet.conversation('alice')!r}"


def test_A02_cles_de_message_distinctes_par_appareil():
    net, u, d = make("alice", "bob")
    tablet = u["bob"].link_device("tablet")
    mid = d["alice"].send("bob", uniq())
    k1 = d["bob"].message_key(mid)
    k2 = tablet.message_key(mid)
    assert isinstance(k1, bytes) and isinstance(k2, bytes)
    assert k1 != k2, "chaque appareil doit avoir sa propre session : même clé obtenue sur phone et tablet"


# --------------------------------------------------------------------------- A03

def test_A03_appareil_d_un_tiers_ne_peut_pas_dechiffrer():
    net, u, d = make("alice", "bob", "eve")
    t = uniq()
    d["alice"].send("bob", t)
    opened = [d["eve"].try_open(p) for p in payloads(net)]
    assert t not in opened, f"eve ne devrait pas ouvrir {t!r}, obtenu {opened!r}"
    assert t not in d["eve"].conversation("alice"), "eve affiche le message de alice à bob"


def test_A03_trou_appareil_fantome_injecte_par_serveur():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    ghost = net.server.inject_device("bob", "ghost")
    assert "ghost" not in u["bob"].list_devices(), \
        f"bob n'a pas lié 'ghost', obtenu la liste {u['bob'].list_devices()!r}"
    before = len(payloads(net))
    t = uniq()
    d["alice"].send("bob", t)
    assert t in d["bob"].conversation("alice"), "le vrai appareil de bob doit toujours lire"
    opened = [ghost.try_open(p) for p in payloads(net)[before:]]
    assert t not in opened, f"l'appareil fantôme a déchiffré {t!r}"
    assert t not in ghost.conversation("alice"), "l'appareil fantôme affiche le message"


# --------------------------------------------------------------------------- A04

def test_A04_le_serveur_recoit_des_octets():
    net, u, d = make("alice", "bob")
    d["alice"].send("bob", uniq())
    ps = payloads(net)
    assert ps, "le message doit transiter par le serveur : aucune charge reçue"
    assert all(isinstance(p, bytes) for p in ps), f"le serveur doit recevoir des bytes, obtenu {[type(p) for p in ps]}"


def test_A04_clair_absent_des_charges_du_serveur():
    net, u, d = make("alice", "bob")
    t = uniq()
    d["alice"].send("bob", t)
    for p in payloads(net):
        assert not leaks(t, p), f"le texte {t!r} (ou un encodage trivial) apparaît dans une charge du serveur"


def test_A04_clair_absent_en_groupe():
    net, u, d = make("alice", "bob", "carol")
    gid = d["alice"].create_group("amis")
    d["alice"].add_member(gid, "bob")
    d["alice"].add_member(gid, "carol")
    t = uniq()
    d["alice"].send_group(gid, t)
    for p in payloads(net):
        assert not leaks(t, p), f"le texte de groupe {t!r} apparaît en clair côté serveur"


def test_A04_charges_incompressibles_comme_un_vrai_chiffre():
    net, u, d = make("alice", "bob")
    d["alice"].send("bob", "A" * 3000)
    big = [p for p in payloads(net) if len(p) >= 1000]
    assert big, "un message de 3000 octets doit produire au moins une charge >= 1000 octets"
    for p in big:
        ratio = len(zlib.compress(p, 9)) / len(p)
        assert ratio > 0.5, f"charge compressible (ratio {ratio:.2f}) : ce n'est pas un chiffrement réel"


def test_A04_meme_texte_deux_fois_donne_deux_chiffres_differents():
    net, u, d = make("alice", "bob")
    d["alice"].send("bob", "bonjour identique")
    n = len(payloads(net))
    d["alice"].send("bob", "bonjour identique")
    first, second = payloads(net)[:n], payloads(net)[n:]
    assert second, "le second envoi n'a produit aucune charge"
    assert not set(first) & set(second), "chiffrement déterministe : même charge pour le même texte"


def test_A04_cle_de_message_ne_passe_pas_par_le_serveur():
    net, u, d = make("alice", "bob")
    mid = d["alice"].send("bob", uniq())
    key = d["bob"].message_key(mid)
    assert isinstance(key, bytes) and len(key) >= 16, f"clé de message attendue >= 16 octets, obtenu {key!r}"
    forms = [key, key.hex().encode(), base64.b64encode(key).rstrip(b"="), base64.urlsafe_b64encode(key).rstrip(b"=")]
    for p in payloads(net):
        assert not any(f in p for f in forms), "la clé du message apparaît dans une charge reçue par le serveur"


def test_A04_cle_aleatoire_ne_dechiffre_rien():
    net, u, d = make("alice", "bob")
    d["alice"].send("bob", uniq())
    for p in payloads(net):
        r = app.try_decrypt(os.urandom(32), p)
        assert r is None, f"une clé aléatoire a 'déchiffré' une charge en {r!r}"


def test_A04_cle_de_message_dechiffre_bien_sa_charge():
    net, u, d = make("alice", "bob")
    t = uniq()
    mid = d["alice"].send("bob", t)
    key = d["bob"].message_key(mid)
    results = [app.try_decrypt(key, p) for p in payloads(net)]
    assert t in results, f"la clé du message doit déchiffrer sa propre charge, obtenu {results!r}"


# --------------------------------------------------------------------------- A05 / A06

def _ratchet_conversation():
    net, u, d = make("alice", "bob")
    a, b = d["alice"], d["bob"]
    seq = [(a, "bob"), (b, "alice"), (a, "bob"), (a, "bob"), (a, "bob"), (b, "alice"), (a, "bob")]
    texts, mids = [], []
    for i, (dev, peer) in enumerate(seq):
        t = uniq(f"msg{i}")
        mids.append(dev.send(peer, t))
        texts.append(t)
    return net, a, b, texts, mids


def test_A05_cle_divulguee_ne_dechiffre_pas_les_precedents():
    net, a, b, texts, mids = _ratchet_conversation()
    key = b.message_key(mids[3])
    results = [app.try_decrypt(key, p) for p in payloads(net)]
    assert texts[3] in results, "contrôle : la clé divulguée doit ouvrir son propre message"
    for t in texts[:3]:
        assert t not in results, f"la clé du message 3 déchiffre le message précédent {t!r}"


def test_A05_cles_precedentes_differentes():
    net, a, b, texts, mids = _ratchet_conversation()
    k3 = b.message_key(mids[3])
    for i in (0, 2):
        assert b.message_key(mids[i]) != k3, f"message {i} et message 3 partagent la même clé"


def test_A06_cle_divulguee_ne_dechiffre_pas_les_suivants():
    net, a, b, texts, mids = _ratchet_conversation()
    key = b.message_key(mids[3])
    results = [app.try_decrypt(key, p) for p in payloads(net)]
    assert texts[3] in results, "contrôle : la clé divulguée doit ouvrir son propre message"
    for t in texts[4:]:
        assert t not in results, f"la clé du message 3 déchiffre le message suivant {t!r}"


def test_A06_cle_divulguee_messages_consecutifs_meme_expediteur():
    net, u, d = make("alice", "bob")
    mids, texts = [], []
    for i in range(4):
        t = uniq(f"c{i}")
        texts.append(t)
        mids.append(d["alice"].send("bob", t))
    key = d["bob"].message_key(mids[1])
    results = [app.try_decrypt(key, p) for p in payloads(net)]
    assert texts[1] in results
    assert texts[2] not in results and texts[3] not in results, \
        "sans changement de sens, la clé du message 1 ouvre les messages suivants"


# --------------------------------------------------------------------------- A07

def test_A07_message_altere_ne_s_affiche_pas():
    net, u, d = make("alice", "bob")
    net.server.set_tamper(lambda p: p[:-1] + bytes([p[-1] ^ 0xFF]))
    t = uniq()
    d["alice"].send("bob", t)
    assert t not in d["bob"].conversation("alice"), "un message altéré (dernier octet) s'affiche"


def test_A07_message_tronque_ne_s_affiche_pas():
    net, u, d = make("alice", "bob")
    net.server.set_tamper(lambda p: p[:-8])
    t = uniq()
    d["alice"].send("bob", t)
    assert t not in d["bob"].conversation("alice"), "un message tronqué s'affiche"


def test_A07_altere_milieu_ne_s_affiche_pas():
    net, u, d = make("alice", "bob")
    net.server.set_tamper(lambda p: flip(len(p) // 2)(p))
    t = uniq()
    d["alice"].send("bob", t)
    assert t not in d["bob"].conversation("alice"), "un message altéré au milieu s'affiche"


def test_A07_trou_toute_position_alteree():
    net, u, d = make("alice", "bob")
    d["alice"].send("bob", "mesure")
    length = max(len(p) for p in payloads(net))
    positions = sorted(set(list(range(0, length, max(1, length // 60))) + [length - 1]))
    shown = []
    for i in positions:
        net, u, d = make("alice", "bob")
        net.server.set_tamper(flip(i))
        t = uniq()
        d["alice"].send("bob", t)
        if t in d["bob"].conversation("alice"):
            shown.append(i)
    assert not shown, f"octets altérés sans détection aux positions {shown} (longueur {length})"


# --------------------------------------------------------------------------- A08 / A09

def test_A08_appareil_lie_apparait_dans_la_liste():
    net, u, d = make("bob")
    u["bob"].link_device("tablet")
    lst = u["bob"].list_devices()
    assert "tablet" in lst and "phone" in lst, f"attendu phone et tablet, obtenu {lst!r}"


def test_A09_appareil_retire_disparait_de_la_liste():
    net, u, d = make("bob")
    u["bob"].link_device("tablet")
    u["bob"].remove_device("tablet")
    lst = u["bob"].list_devices()
    assert "tablet" not in lst, f"tablet retiré mais encore listé : {lst!r}"
    assert "phone" in lst, f"phone ne doit pas disparaître : {lst!r}"


# --------------------------------------------------------------------------- A10

def test_A10_appareil_retire_n_affiche_pas_les_nouveaux_messages():
    net, u, d = make("alice", "bob")
    tablet = u["bob"].link_device("tablet")
    d["alice"].send("bob", uniq("avant"))
    u["bob"].remove_device("tablet")
    before = len(payloads(net))
    t = uniq("apres")
    d["alice"].send("bob", t)
    assert t in d["bob"].conversation("alice"), "contrôle : phone de bob doit lire"
    assert t not in tablet.conversation("alice"), "l'appareil retiré affiche un message postérieur au retrait"
    opened = [tablet.try_open(p) for p in payloads(net)[before:]]
    assert t not in opened, "l'appareil retiré peut déchiffrer une charge postérieure au retrait"


# --------------------------------------------------------------------------- A11

def test_A11_nouvel_appareil_ne_montre_pas_l_historique():
    net, u, d = make("alice", "bob")
    t_old = uniq("ancien")
    d["alice"].send("bob", t_old)
    tablet = u["bob"].link_device("tablet")
    assert t_old not in tablet.conversation("alice"), \
        f"historique affiché sur le nouvel appareil : {tablet.conversation('alice')!r}"
    t_new = uniq("nouveau")
    d["alice"].send("bob", t_new)
    assert t_new in tablet.conversation("alice"), "contrôle : le nouvel appareil doit recevoir les messages suivants"
    assert t_old not in tablet.conversation("alice")


# --------------------------------------------------------------------------- A12 – A14

def test_A12_contact_ajoute_non_verifie():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    assert d["alice"].verification_state("bob") == "non vérifié"


def test_A13_scan_code_correspondant_verifie():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    d["alice"].scan_code("bob", d["bob"].security_code())
    assert d["alice"].verification_state("bob") == "vérifié"


def test_A14_scan_code_d_un_autre_contact_reste_non_verifie():
    net, u, d = make("alice", "bob", "eve")
    d["alice"].add_contact("bob")
    d["alice"].scan_code("bob", d["eve"].security_code())
    assert d["alice"].verification_state("bob") == "non vérifié"


def test_A14_scan_code_arbitraire_reste_non_verifie():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    d["alice"].scan_code("bob", "0" * 60)
    assert d["alice"].verification_state("bob") == "non vérifié"


def test_A14_code_du_meme_nom_sur_un_autre_reseau_ne_verifie_pas():
    net, u, d = make("alice", "bob")
    net2, u2, d2 = make("alice", "bob")
    d["alice"].add_contact("bob")
    d["alice"].scan_code("bob", d2["bob"].security_code())
    assert d["alice"].verification_state("bob") == "non vérifié", \
        "les clés semblent dérivées du nom : un autre 'bob' produit le même code"


def test_A14_ancien_code_apres_reinstallation_ne_verifie_pas():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    old = d["bob"].security_code()
    d["bob"].reinstall()
    d["bob"].send("alice", uniq())
    d["alice"].scan_code("bob", old)
    assert d["alice"].verification_state("bob") == "non vérifié"


# --------------------------------------------------------------------------- A15

def test_A15_reinstallation_change_l_empreinte():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    before = d["alice"].fingerprint("bob")
    d["bob"].reinstall()
    d["bob"].send("alice", uniq())
    after = d["alice"].fingerprint("bob")
    assert after != before, f"empreinte inchangée après réinstallation : {after!r}"


def test_A15_trou_changement_visible_sans_nouveau_message():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    before = d["alice"].fingerprint("bob")
    d["bob"].reinstall()
    after = d["alice"].fingerprint("bob")
    assert after != before, "l'empreinte affichée chez alice (en ligne) n'a pas changé après la réinstallation"


def test_A15_trou_liaison_ne_change_pas_empreinte():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    before = d["alice"].fingerprint("bob")
    u["bob"].link_device("tablet")
    d["alice"].send("bob", uniq())
    assert d["alice"].fingerprint("bob") == before, "lier un appareil a changé l'empreinte affichée"


# --------------------------------------------------------------------------- A16 – A19

def _verified_then_reinstalled():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    d["alice"].scan_code("bob", d["bob"].security_code())
    assert d["alice"].verification_state("bob") == "vérifié"
    assert d["alice"].warnings("bob") == [], "aucun avertissement attendu avant changement"
    d["bob"].reinstall()
    d["bob"].send("alice", uniq("apres-reinstall"))
    return net, u, d


def test_A16_changement_d_empreinte_repasse_non_verifie():
    net, u, d = _verified_then_reinstalled()
    assert d["alice"].verification_state("bob") == "non vérifié"


def test_A16_trou_confirmation_ne_reverifie_pas():
    net, u, d = _verified_then_reinstalled()
    d["alice"].confirm_fingerprint_change("bob")
    assert d["alice"].verification_state("bob") == "non vérifié"


def test_A17_changement_d_empreinte_verifie_affiche_avertissement():
    net, u, d = _verified_then_reinstalled()
    w = d["alice"].warnings("bob")
    assert len(w) >= 1, f"avertissement attendu dans la conversation, obtenu {w!r}"


def test_A18_changement_d_empreinte_non_verifie_sans_avertissement():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    before = d["alice"].fingerprint("bob")
    d["bob"].reinstall()
    d["bob"].send("alice", uniq())
    assert d["alice"].fingerprint("bob") != before, "contrôle : l'empreinte doit avoir changé"
    assert d["alice"].warnings("bob") == [], f"aucun avertissement attendu, obtenu {d['alice'].warnings('bob')!r}"


def test_A19_envoi_bloque_apres_changement_d_empreinte():
    net, u, d = _verified_then_reinstalled()
    t = uniq()
    mid = d["alice"].send("bob", t)
    assert d["alice"].send_status(mid) == "bloqué", f"obtenu {d['alice'].send_status(mid)!r}"
    assert t not in d["bob"].conversation("alice"), "le message bloqué a été remis"
    for p in payloads(net):
        assert d["bob"].try_open(p) != t, "le message bloqué a été transmis au serveur"


def test_A19_reste_bloque_avec_le_temps_et_les_reconnexions():
    net, u, d = _verified_then_reinstalled()
    t = uniq()
    mid = d["alice"].send("bob", t)
    net.advance(86400)
    d["alice"].go_offline()
    d["alice"].go_online()
    assert d["alice"].send_status(mid) == "bloqué"
    assert t not in d["bob"].conversation("alice")


def test_A19_trou_confirmation_envoie_le_message_bloque():
    net, u, d = _verified_then_reinstalled()
    t = uniq()
    mid = d["alice"].send("bob", t)
    d["alice"].confirm_fingerprint_change("bob")
    assert d["alice"].send_status(mid) == "envoyé", f"obtenu {d['alice'].send_status(mid)!r}"
    assert t in d["bob"].conversation("alice"), "après confirmation, le message doit être lisible chez bob"


def test_A19_trou_non_verifie_pas_bloque():
    net, u, d = make("alice", "bob")
    d["alice"].add_contact("bob")
    d["bob"].reinstall()
    d["bob"].send("alice", uniq())
    t = uniq()
    mid = d["alice"].send("bob", t)
    assert d["alice"].send_status(mid) == "envoyé", f"obtenu {d['alice'].send_status(mid)!r}"
    assert t in d["bob"].conversation("alice")


# --------------------------------------------------------------------------- A20 / A21

def test_A20_expediteur_hors_ligne_en_attente():
    net, u, d = make("alice", "bob")
    d["alice"].go_offline()
    t = uniq()
    mid = d["alice"].send("bob", t)
    assert d["alice"].send_status(mid) == "en attente", f"obtenu {d['alice'].send_status(mid)!r}"
    assert t not in d["bob"].conversation("alice"), "un message d'un expéditeur hors ligne est arrivé"


def test_A21_retour_en_ligne_passe_a_envoye():
    net, u, d = make("alice", "bob")
    d["alice"].go_offline()
    t = uniq()
    mid = d["alice"].send("bob", t)
    net.advance(600)
    d["alice"].go_online()
    assert d["alice"].send_status(mid) == "envoyé", f"obtenu {d['alice'].send_status(mid)!r}"
    assert t in d["bob"].conversation("alice")


def test_A21_plusieurs_en_attente_partent_dans_l_ordre():
    net, u, d = make("alice", "bob")
    d["alice"].go_offline()
    texts = [uniq(f"q{i}") for i in range(3)]
    mids = [d["alice"].send("bob", t) for t in texts]
    d["alice"].go_online()
    assert [d["alice"].send_status(m) for m in mids] == ["envoyé"] * 3
    conv = d["bob"].conversation("alice")
    assert [c for c in conv if c in texts] == texts, f"ordre attendu {texts!r}, obtenu {conv!r}"


# --------------------------------------------------------------------------- A22 / A23

def test_A22_destinataire_hors_ligne_pas_remis():
    net, u, d = make("alice", "bob")
    d["bob"].go_offline()
    mid = d["alice"].send("bob", uniq())
    assert d["alice"].receipt(mid) != "remis"


def test_A22_tous_les_appareils_hors_ligne_pas_remis():
    net, u, d = make("alice", "bob")
    tablet = u["bob"].link_device("tablet")
    d["bob"].go_offline()
    tablet.go_offline()
    mid = d["alice"].send("bob", uniq())
    net.advance(3600)
    assert d["alice"].receipt(mid) != "remis"


def test_A23_retour_en_ligne_passe_a_remis():
    net, u, d = make("alice", "bob")
    d["bob"].go_offline()
    t = uniq()
    mid = d["alice"].send("bob", t)
    d["bob"].go_online()
    assert t in d["bob"].conversation("alice")
    assert d["alice"].receipt(mid) == "remis", f"obtenu {d['alice'].receipt(mid)!r}"


def test_A23_trou_un_seul_appareil_suffit():
    net, u, d = make("alice", "bob")
    tablet = u["bob"].link_device("tablet")
    d["bob"].go_offline()
    tablet.go_offline()
    mid = d["alice"].send("bob", uniq())
    tablet.go_online()
    assert d["alice"].receipt(mid) == "remis", f"obtenu {d['alice'].receipt(mid)!r}"


# --------------------------------------------------------------------------- A24 – A29

def _group(*members):
    net, u, d = make("alice", *members)
    gid = d["alice"].create_group("amis")
    for m in members:
        d["alice"].add_member(gid, m)
    return net, u, d, gid


def test_A24_ajout_au_groupe_apparait_dans_les_membres():
    net, u, d, gid = _group("bob")
    assert "bob" in d["alice"].group_members(gid), f"obtenu {d['alice'].group_members(gid)!r}"


def test_A25_retrait_du_groupe_disparait_des_membres():
    net, u, d, gid = _group("bob", "carol")
    d["alice"].remove_member(gid, "bob")
    m = d["alice"].group_members(gid)
    assert "bob" not in m and "carol" in m, f"obtenu {m!r}"


def test_A26_message_de_groupe_lisible_chez_chaque_membre():
    net, u, d, gid = _group("bob", "carol", "dave")
    t = uniq()
    d["alice"].send_group(gid, t)
    for m in ("bob", "carol", "dave"):
        assert t in d[m].group_conversation(gid), f"{m} : obtenu {d[m].group_conversation(gid)!r}"


def test_A26_membre_non_createur_envoie_au_groupe():
    net, u, d, gid = _group("bob", "carol")
    t = uniq()
    d["bob"].send_group(gid, t)
    for m in ("alice", "carol"):
        assert t in d[m].group_conversation(gid), f"{m} : obtenu {d[m].group_conversation(gid)!r}"


def test_A27_membre_retire_ne_lit_pas():
    net, u, d, gid = _group("bob", "carol")
    d["alice"].send_group(gid, uniq("avant"))
    d["alice"].remove_member(gid, "carol")
    before = len(payloads(net))
    t = uniq("apres")
    d["alice"].send_group(gid, t)
    assert t in d["bob"].group_conversation(gid), "contrôle : bob doit lire"
    assert t not in d["carol"].group_conversation(gid), "carol retirée affiche le message"
    opened = [d["carol"].try_open(p) for p in payloads(net)[before:]]
    assert t not in opened, "carol retirée déchiffre une charge postérieure à son retrait"


def test_A27_trou_autre_membre_apres_retrait():
    net, u, d, gid = _group("bob", "carol")
    d["bob"].send_group(gid, uniq("avant"))
    d["alice"].remove_member(gid, "carol")
    before = len(payloads(net))
    t = uniq("bob-apres")
    d["bob"].send_group(gid, t)
    assert t in d["alice"].group_conversation(gid), "contrôle : alice doit lire"
    assert t not in d["carol"].group_conversation(gid)
    opened = [d["carol"].try_open(p) for p in payloads(net)[before:]]
    assert t not in opened, "carol déchiffre un message de bob postérieur à son retrait (clé de groupe non renouvelée)"


def test_A28_nouveau_membre_ne_voit_pas_l_historique():
    net, u, d, gid = _group("bob")
    old = uniq("ancien")
    d["alice"].send_group(gid, old)
    net2 = None
    dave = net.create_user("dave", "phone").device("phone")
    d["alice"].add_member(gid, "dave")
    assert old not in dave.group_conversation(gid), f"obtenu {dave.group_conversation(gid)!r}"
    new = uniq("nouveau")
    d["alice"].send_group(gid, new)
    assert new in dave.group_conversation(gid), "contrôle : dave doit lire les messages postérieurs"


def test_A29_membre_hors_ligne_pas_remis():
    net, u, d, gid = _group("bob", "carol")
    d["carol"].go_offline()
    mid = d["alice"].send_group(gid, uniq())
    assert d["alice"].receipt(mid, "carol") != "remis"
    assert d["alice"].receipt(mid, "bob") == "remis", f"bob en ligne : obtenu {d['alice'].receipt(mid, 'bob')!r}"
    d["carol"].go_online()
    assert d["alice"].receipt(mid, "carol") == "remis"


# --------------------------------------------------------------------------- A30 / A31

def test_A30_minuterie_une_heure_affichee():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 3600)
    assert d["alice"].timer("bob") == 3600


def test_A31_minuterie_visible_chez_l_autre_participant():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 3600)
    assert d["bob"].timer("alice") == 3600
    d["bob"].set_timer("alice", 300)
    assert d["alice"].timer("bob") == 300


# --------------------------------------------------------------------------- A32 – A36

def test_A32_disparait_chez_le_destinataire_apres_lecture():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 3600)
    t = uniq()
    d["alice"].send("bob", t)
    net.advance(100)
    d["bob"].mark_read("alice")
    net.advance(3599)
    assert t in d["bob"].conversation("alice"), "disparu avant la fin de la minuterie"
    net.advance(2)
    assert t not in d["bob"].conversation("alice"), "toujours affiché après la minuterie"


def test_A32_non_lu_ne_disparait_pas():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 60)
    t = uniq()
    d["alice"].send("bob", t)
    net.advance(86400)
    assert t in d["bob"].conversation("alice"), "un message non lu a disparu"


def test_A33_disparait_chez_l_expediteur():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 3600)
    t = uniq()
    d["alice"].send("bob", t)
    d["bob"].mark_read("alice")
    net.advance(3601)
    assert t not in d["alice"].conversation("bob"), "toujours affiché chez l'expéditeur"


def test_A33_trou_depart_a_la_lecture_par_destinataire():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 3600)
    t = uniq()
    d["alice"].send("bob", t)
    net.advance(1800)
    d["bob"].mark_read("alice")
    net.advance(3500)
    assert t in d["alice"].conversation("bob"), "chez l'expéditeur, la minuterie a démarré avant la lecture"
    net.advance(200)
    assert t not in d["alice"].conversation("bob")


def test_A34_minuterie_desactivee_message_reste():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 60)
    d["alice"].set_timer("bob", None)
    assert d["alice"].timer("bob") is None
    t = uniq()
    d["alice"].send("bob", t)
    d["bob"].mark_read("alice")
    net.advance(10 * 365 * 86400)
    assert t in d["bob"].conversation("alice")
    assert t in d["alice"].conversation("bob")


def test_A35_modification_ne_change_pas_les_messages_precedents():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 3600)
    m1 = uniq("long")
    d["alice"].send("bob", m1)
    d["alice"].set_timer("bob", 60)
    m2 = uniq("court")
    d["alice"].send("bob", m2)
    d["bob"].mark_read("alice")
    net.advance(61)
    conv = d["bob"].conversation("alice")
    assert m2 not in conv, "le message à 60 s n'a pas disparu"
    assert m1 in conv, "le message envoyé sous 3600 s a pris la nouvelle durée"
    net.advance(3600)
    assert m1 not in d["bob"].conversation("alice")


def test_A35_allongement_ne_prolonge_pas_les_precedents():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 60)
    m1 = uniq()
    d["alice"].send("bob", m1)
    d["bob"].set_timer("alice", 86400)
    d["bob"].mark_read("alice")
    net.advance(61)
    assert m1 not in d["bob"].conversation("alice"), "le message a pris la durée modifiée"


def test_A36_ephemere_recu_hors_ligne_ne_disparait_pas_avant_lecture():
    net, u, d = make("alice", "bob")
    d["alice"].set_timer("bob", 60)
    d["bob"].go_offline()
    t = uniq()
    d["alice"].send("bob", t)
    net.advance(7200)
    d["bob"].go_online()
    assert t in d["bob"].conversation("alice"), "disparu pendant que l'appareil était hors ligne"
    net.advance(7200)
    assert t in d["bob"].conversation("alice"), "disparu sans avoir été lu"
    d["bob"].mark_read("alice")
    net.advance(61)
    assert t not in d["bob"].conversation("alice"), "contrôle : doit disparaître après lecture + minuterie"
