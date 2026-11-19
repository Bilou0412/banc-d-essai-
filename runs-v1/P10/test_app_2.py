"""Tests rouges — sonde P10, couche code, deuxième attaque.

Même interface publique que tests/test_app.py (module unique `app`).

Axes de cette attaque :
  - ce qui casse une implémentation qui SIMULE le chiffrement : clés dérivées des noms
    (réseaux jumeaux), clés privées hors des appareils, clé de message dans un objet
    commun aux deux côtés, état interne du serveur contenant le clair ;
  - authentification complète du blob (chaque octet), substitution, rejeu ;
  - concurrence (deux côtés hors ligne, premier contact simultané), répétition ;
  - interactions entre règles (retrait + hors ligne, nom réutilisé, double réinstallation,
    confirmation puis nouveau changement, minuterie depuis la lecture).
"""

import functools
import hashlib
import hmac
import os
import random
import subprocess
import sys
import types
from collections import deque

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dh, ec, ed448, ed25519, rsa, x448, x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

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


def mark(net):
    return len(net.server.received())


def since(net, before):
    return list(net.server.received())[before:]


def open_in_fresh_process(key, blob):
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


_LEAF = (str, bytes, bytearray, int, float, bool, complex, type(None))
_SKIP = (types.ModuleType, types.BuiltinFunctionType, type, types.CodeType, types.FrameType,
         types.GeneratorType)


def reachable(roots, exclude=(), limit=500_000):
    """Parcours du graphe d'objets (attributs, slots, conteneurs, méthodes liées, fermetures)."""
    excluded = {id(o) for o in exclude}
    seen = set()
    out = []
    stack = list(roots)
    while stack and len(out) < limit:
        o = stack.pop()
        i = id(o)
        if i in seen or i in excluded:
            continue
        seen.add(i)
        out.append(o)
        if isinstance(o, _LEAF) or isinstance(o, _SKIP):
            continue
        if isinstance(o, types.MethodType):
            stack.append(o.__self__)
            stack.append(o.__func__)
            continue
        if isinstance(o, types.FunctionType):
            for c in o.__closure__ or ():
                try:
                    stack.append(c.cell_contents)
                except ValueError:
                    pass
            continue
        if isinstance(o, functools.partial):
            stack.extend([o.func, o.args, o.keywords])
            continue
        if isinstance(o, dict):
            stack.extend(o.keys())
            stack.extend(o.values())
            continue
        if isinstance(o, (list, tuple, set, frozenset, deque)):
            stack.extend(o)
            continue
        try:
            d = object.__getattribute__(o, "__dict__")
        except Exception:
            d = None
        if isinstance(d, dict):
            stack.append(d)
        for cls in type(o).__mro__:
            slots = cls.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for s in slots:
                if s in ("__dict__", "__weakref__"):
                    continue
                try:
                    stack.append(object.__getattribute__(o, s))
                except Exception:
                    pass
    return out


PRIV_TYPES = (
    x25519.X25519PrivateKey, x448.X448PrivateKey, ed25519.Ed25519PrivateKey,
    ed448.Ed448PrivateKey, ec.EllipticCurvePrivateKey, rsa.RSAPrivateKey, dh.DHPrivateKey,
)


def private_keys(objs):
    return {id(o): o for o in objs if isinstance(o, PRIV_TYPES)}


def fit(x, n):
    return x[:n] if len(x) >= n else hashlib.shake_256(x).digest(n)


def naive_derivations(k):
    n = len(k)
    c = [
        fit(hashlib.sha256(k).digest(), n),
        fit(hashlib.sha512(k).digest(), n),
        hashlib.shake_256(k).digest(n),
        hashlib.blake2b(k, digest_size=min(64, n)).digest() if n <= 64 else hashlib.shake_256(b"b" + k).digest(n),
        fit(hmac.new(k, b"\x01", hashlib.sha256).digest(), n),
        fit(hmac.new(k, b"\x02", hashlib.sha256).digest(), n),
        fit(hmac.new(k, b"\x00", hashlib.sha256).digest(), n),
        fit(hmac.new(k, b"", hashlib.sha256).digest(), n),
        (int.from_bytes(k, "big") + 1).to_bytes(n + 1, "big")[-n:],
        (int.from_bytes(k, "big") - 1).to_bytes(n + 1, "big", signed=True)[-n:] if int.from_bytes(k, "big") else k,
        k[::-1],
    ]
    for info in (b"", b"message", b"chain", b"next", b"ratchet"):
        c.append(HKDF(algorithm=hashes.SHA256(), length=n, salt=None, info=info).derive(k))
    return c


# --------------------------------------------------------------------------- A04 : serveur, état interne

def test_A04_etat_interne_du_serveur_sans_clair_ni_cle():
    net, alice, bob, ap, bp = pair()
    m1 = ap.send("bob", "plan secret 77310 — ne pas divulguer")
    m2 = bp.send("alice", "réponse 88425 confidentielle")
    keys = [ap.message_key(m1), bp.message_key(m2)]
    objs = reachable([net.server], exclude=[net, alice, bob, ap, bp, m1, m2])
    for o in objs:
        if isinstance(o, str):
            assert "77310" not in o and "88425" not in o and "plan secret" not in o, (
                f"l'état interne du serveur contient le clair : {o[:80]!r}"
            )
        elif isinstance(o, (bytes, bytearray)):
            assert "plan secret".encode() not in o and b"77310" not in o and b"88425" not in o, (
                "l'état interne du serveur contient le clair en octets"
            )
            for k in keys:
                assert k not in o, "une clé de message est présente dans l'état interne du serveur"
    for o in objs:
        assert not isinstance(o, PRIV_TYPES), f"le serveur détient une clé privée : {type(o).__name__}"


def test_A04_cle_de_message_dans_aucun_objet_commun_aux_deux_cotes():
    # Mécanisme exigé : aucune clé de message ne passe par un objet partagé entre
    # l'expéditeur et le destinataire.
    net, alice, bob, ap, bp = pair()
    sent_a = [ap.send("bob", f"message {i} — objet partagé ?") for i in range(3)]
    sent_b = [bp.send("alice", "retour de bob")]
    keys = [ap.message_key(m) for m in sent_a] + [bp.message_key(m) for m in sent_b]
    side_a = {id(o): o for o in reachable([alice, ap, *sent_a], exclude=[net, net.server, bob, bp])}
    side_b = reachable([bob, bp, *sent_b], exclude=[net, net.server, alice, ap])
    common = [o for o in side_b if id(o) in side_a]
    leaks = [o for o in common if isinstance(o, (bytes, bytearray)) and any(k in o for k in keys)]
    assert not leaks, (
        f"{len(leaks)} objet(s) contenant une clé de message sont atteignables à la fois "
        f"depuis l'expéditeur et depuis le destinataire"
    )


def test_A03_cles_privees_generees_et_gardees_par_chaque_appareil():
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    ap.send("bob", "x")
    bp.send("alice", "y")
    tablet.send("alice", "z")
    bp.reinstall()
    ap.send("bob", "w")
    devices = [ap, bp, tablet]
    users = [alice, bob]
    owned = {}
    for d in devices:
        others = [x for x in devices if x is not d]
        owned[id(d)] = private_keys(reachable([d], exclude=[net, net.server, *users, *others]))
    all_owned = set()
    for ks in owned.values():
        all_owned |= set(ks)
    outside = private_keys(reachable([net], exclude=devices))
    orphans = [type(k).__name__ for i, k in outside.items() if i not in all_owned]
    assert not orphans, f"clés privées détenues hors de tout appareil : {orphans}"
    for d1 in devices:
        for d2 in devices:
            if d1 is d2:
                continue
            shared = set(owned[id(d1)]) & set(owned[id(d2)])
            assert not shared, (
                f"les appareils {d1.name!r} et {d2.name!r} partagent {len(shared)} clé(s) privée(s)"
            )
    a_side = private_keys(reachable([alice, ap], exclude=[net, net.server, bob, bp, tablet]))
    stolen = set(a_side) & (set(owned[id(bp)]) | set(owned[id(tablet)]))
    assert not stolen, "une clé privée d'un appareil de bob est atteignable depuis alice"


# --------------------------------------------------------------------------- réseaux jumeaux : rien ne dérive des noms

def _twin_run():
    net, alice, bob, ap, bp = pair()
    out = []
    for i, (d, to) in enumerate([(ap, "bob"), (bp, "alice"), (ap, "bob"), (ap, "bob")]):
        before = mark(net)
        m = d.send(to, f"jumeau {i}")
        out.append((f"jumeau {i}", d.message_key(m), since(net, before)))
    return net, alice, bob, ap, bp, out


def test_A03_reseau_jumeau_ne_dechiffre_pas():
    net1, a1, b1, ap1, bp1, run1 = _twin_run()
    net2, a2, b2, ap2, bp2, run2 = _twin_run()
    for (t, k1, w1), (_, k2, w2) in zip(run1, run2):
        assert k1 != k2, f"même clé de message pour {t!r} dans deux réseaux identiques : clé dérivée des noms"
        assert not (set(w1) & set(w2)), f"blobs identiques pour {t!r} dans deux réseaux : chiffrement déterministe"
        for b in w1:
            assert app.open_with_key(k2, b) is None, f"la clé du réseau jumeau ouvre {t!r}"
    for t, _, w1 in run1:
        for b in w1:
            r1 = bp2.try_open(b)
            r2 = ap2.try_open(b)
            assert r1 != t and r2 != t, f"un appareil du réseau jumeau déchiffre {t!r}"


def test_A15_empreinte_non_deterministe_entre_reseaux_jumeaux():
    net1, a1, b1, ap1, bp1 = pair()
    net2, a2, b2, ap2, bp2 = pair()
    assert a1.fingerprint() != a2.fingerprint(), "même empreinte pour « alice » dans deux réseaux : empreinte dérivée du nom"
    bp1.reinstall()
    bp2.reinstall()
    assert b1.fingerprint() != b2.fingerprint(), "même empreinte après réinstallation dans deux réseaux jumeaux"


# --------------------------------------------------------------------------- A05 / A06 : clés de message

def test_A06_derivations_naives_de_la_cle_n_ouvrent_aucun_autre_message():
    net, alice, bob, ap, bp = pair()
    data = []
    for i in range(6):
        before = mark(net)
        m = ap.send("bob", f"chaîne {i}")
        data.append((f"chaîne {i}", ap.message_key(m), since(net, before)))
    leaked = 2
    _, k, _ = data[leaked]
    for cand in naive_derivations(k):
        for j, (t, _, w) in enumerate(data):
            if j == leaked:
                continue
            for b in w:
                r = app.open_with_key(cand, b)
                assert r is None, f"une dérivation simple de la clé {leaked} ouvre le message {j} : {r!r}"


def test_A05_cle_d_une_conversation_n_ouvre_pas_une_autre_conversation():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    before = mark(net)
    m_bob = ap.send("bob", "pour bob uniquement")
    w_bob = since(net, before)
    before = mark(net)
    m_carol = ap.send("carol", "pour carol uniquement")
    w_carol = since(net, before)
    k_bob, k_carol = ap.message_key(m_bob), ap.message_key(m_carol)
    assert k_bob != k_carol, "même clé de message pour deux conversations"
    for b in w_carol:
        assert app.open_with_key(k_bob, b) is None, "la clé alice→bob ouvre un message alice→carol"
    for b in w_bob:
        assert app.open_with_key(k_carol, b) is None, "la clé alice→carol ouvre un message alice→bob"


def test_A05_groupe_cle_divulguee_n_ouvre_ni_avant_ni_apres():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    seq = [ap, ap, bp, cp, ap, bp, ap]
    data = []
    for i, d in enumerate(seq):
        before = mark(net)
        m = d.send_group(gid, f"groupe {i}")
        data.append((f"groupe {i}", d.message_key(m), since(net, before)))
    keys = [k for _, k, _ in data]
    assert len(set(keys)) == len(keys), "deux messages de groupe partagent la même clé : clé de groupe statique"
    leaked = 3
    _, k, w = data[leaked]
    for j, (t, _, wj) in enumerate(data):
        if j == leaked:
            continue
        for b in wj:
            r = app.open_with_key(k, b)
            assert r is None, f"la clé du message de groupe {leaked} ouvre le message {j} : {r!r}"
    results = [open_in_fresh_process(k, b) for b in w]
    assert "groupe 3" in results, f"la clé de message de groupe n'ouvre pas son propre blob : {results!r}"


def test_A04_groupe_cle_de_message_absente_du_serveur():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    m = ap.send_group(gid, "clé de groupe")
    k = ap.message_key(m)
    for b in net.server.received():
        assert k not in b, "la clé d'un message de groupe a transité par le serveur"


# --------------------------------------------------------------------------- A07 : authentification

def test_A07_open_with_key_rejette_tout_octet_altere():
    net, alice, bob, ap, bp = pair()
    text = "authentifié de bout en bout"
    before = mark(net)
    m = ap.send("bob", text)
    window = since(net, before)
    key = ap.message_key(m)
    good = [b for b in window if app.open_with_key(key, b) == text]
    assert good, "la clé de message n'ouvre aucun blob de son envoi"
    b = good[0]
    opened_at = []
    for p in range(len(b)):
        ba = bytearray(b)
        ba[p] ^= 0x80
        if app.open_with_key(key, bytes(ba)) is not None:
            opened_at.append(p)
    assert not opened_at, f"blob altéré aux octets {opened_at[:20]} encore ouvert : partie non authentifiée"
    assert app.open_with_key(key, b[:-1]) is None, "blob tronqué ouvert"
    assert app.open_with_key(key, b + b"\x00") is None, "blob rallongé ouvert"
    assert app.open_with_key(key, b"") is None, "blob vide : attendu None"


def test_A07_chaque_position_alteree_en_transit_ne_s_affiche_pas():
    net, alice, bob, ap, bp = pair()
    before = mark(net)
    ap.send("bob", "étalon de longueur")
    length = max(len(b) for b in since(net, before))
    step = max(1, length // 400)
    shown = []
    for p in range(0, length, step):
        text = f"pos {p} altérée"

        def flip(b, p=p):
            ba = bytearray(b)
            ba[p % len(ba)] ^= 0x80
            return bytes(ba)

        net.set_interceptor(flip)
        ap.send("bob", text)
        net.set_interceptor(None)
        if text in bp.conversation("alice"):
            shown.append(p)
    assert not shown, f"blobs altérés affichés en clair aux positions {shown[:20]}"
    ap.send("bob", "intact après la rafale")
    assert "intact après la rafale" in bp.conversation("alice"), "la session ne survit pas aux altérations"
    bp.send("alice", "et dans l'autre sens")
    assert "et dans l'autre sens" in ap.conversation("bob")


def test_A07_blob_vide_puis_message_intact():
    net, alice, bob, ap, bp = pair()
    net.set_interceptor(lambda b: b"")
    ap.send("bob", "avalé en route")
    net.set_interceptor(None)
    assert "avalé en route" not in bp.conversation("alice")
    ap.send("bob", "le suivant passe")
    assert "le suivant passe" in bp.conversation("alice")


def test_A07_message_de_groupe_altere_ne_s_affiche_pas():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    ap.send_group(gid, "premier du groupe")

    def flip(b):
        ba = bytearray(b)
        ba[len(ba) // 2] ^= 0x01
        return bytes(ba)

    net.set_interceptor(flip)
    ap.send_group(gid, "groupe altéré")
    net.set_interceptor(None)
    assert "groupe altéré" not in bp.group_conversation(gid)
    assert "groupe altéré" not in cp.group_conversation(gid)
    ap.send_group(gid, "groupe intact")
    assert "groupe intact" in bp.group_conversation(gid)
    assert "groupe intact" in cp.group_conversation(gid)


def test_A07_trou_substitution_par_blob_d_un_autre_expediteur():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    before = mark(net)
    cp.send("bob", "texte authentique de carol")
    captured = since(net, before)[0]
    net.set_interceptor(lambda b: captured)
    ap.send("bob", "texte d'alice remplacé")
    net.set_interceptor(None)
    conv = bp.conversation("alice")
    assert "texte authentique de carol" not in conv, (
        f"un blob de carol, substitué en transit, s'affiche comme venant d'alice : {conv!r}"
    )
    assert "texte d'alice remplacé" not in conv
    ap.send("bob", "après substitution")
    assert "après substitution" in bp.conversation("alice")


def test_A07_trou_rejeu_ne_duplique_pas():
    net, alice, bob, ap, bp = pair()
    before = mark(net)
    ap.send("bob", "premier envoi")
    captured = since(net, before)[0]
    net.set_interceptor(lambda b: captured)
    ap.send("bob", "second envoi")
    net.set_interceptor(None)
    conv = bp.conversation("alice")
    assert conv.count("premier envoi") == 1, f"blob rejoué affiché de nouveau : {conv!r}"


# --------------------------------------------------------------------------- A01 : concurrence, répétition, limites

def test_A01_premier_contact_simultane_des_deux_cotes():
    net, alice, bob, ap, bp = pair()
    ap.set_online(False)
    bp.set_online(False)
    ap.send("bob", "salut, premier mot d'alice")
    bp.send("alice", "salut, premier mot de bob")
    ap.set_online(True)
    bp.set_online(True)
    assert "salut, premier mot d'alice" in bp.conversation("alice"), f"bob : {bp.conversation('alice')!r}"
    assert "salut, premier mot de bob" in ap.conversation("bob"), f"alice : {ap.conversation('bob')!r}"
    ap.send("bob", "et ensuite ?")
    bp.send("alice", "ça continue")
    assert "et ensuite ?" in bp.conversation("alice")
    assert "ça continue" in ap.conversation("bob")


def test_A01_messages_croises_pendant_que_les_deux_sont_hors_ligne():
    net, alice, bob, ap, bp = pair()
    ap.send("bob", "a0")
    bp.send("alice", "b0")
    ap.set_online(False)
    bp.set_online(False)
    ap.send("bob", "a1 croisé")
    bp.send("alice", "b1 croisé")
    ap.send("bob", "a2 croisé")
    bp.set_online(True)
    ap.set_online(True)
    for t in ("a1 croisé", "a2 croisé"):
        assert t in bp.conversation("alice"), f"{t!r} absent chez bob : {bp.conversation('alice')!r}"
    assert "b1 croisé" in ap.conversation("bob"), f"absent chez alice : {ap.conversation('bob')!r}"
    ap.send("bob", "a3")
    bp.send("alice", "b3")
    assert "a3" in bp.conversation("alice") and "b3" in ap.conversation("bob")


def test_A01_trois_cents_messages_avec_coupures():
    net, alice, bob, ap, bp = pair()
    rnd = random.Random(20261119)
    exp_b, exp_a = [], []
    for i in range(300):
        if i % 37 == 5:
            bp.set_online(False)
        if i % 37 == 20:
            bp.set_online(True)
        if i % 53 == 7:
            ap.set_online(False)
        if i % 53 == 30:
            ap.set_online(True)
        if rnd.random() < 0.6:
            t = f"A→B n°{i} ü"
            ap.send("bob", t)
            exp_b.append(t)
        else:
            t = f"B→A n°{i} ß"
            bp.send("alice", t)
            exp_a.append(t)
    ap.set_online(True)
    bp.set_online(True)
    cb, ca = set(bp.conversation("alice")), set(ap.conversation("bob"))
    miss_b = [t for t in exp_b if t not in cb]
    miss_a = [t for t in exp_a if t not in ca]
    assert not miss_b, f"{len(miss_b)} messages perdus chez bob, ex. {miss_b[:3]}"
    assert not miss_a, f"{len(miss_a)} messages perdus chez alice, ex. {miss_a[:3]}"


def test_A01_message_tres_long_et_message_d_un_caractere():
    net, alice, bob, ap, bp = pair()
    long_text = ("Ünïcödé 🙂 " * 12000) + "fin"
    ap.send("bob", long_text)
    ap.send("bob", "x")
    conv = bp.conversation("alice")
    assert long_text in conv, f"message long altéré ou absent (longueurs : {[len(c) for c in conv]})"
    assert "x" in conv


def test_A01_message_n_apparait_pas_dans_une_autre_conversation():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    ap.send("bob", "réservé à la conversation alice-bob")
    assert "réservé à la conversation alice-bob" not in bp.conversation("carol")
    assert "réservé à la conversation alice-bob" not in cp.conversation("alice")
    assert "réservé à la conversation alice-bob" not in ap.conversation("carol")


# --------------------------------------------------------------------------- A02 / A10 / A11 : appareils

def test_A02_appareil_hors_ligne_recoit_au_retour():
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    tablet.set_online(False)
    ap.send("bob", "la tablette dort")
    assert "la tablette dort" in bp.conversation("alice")
    tablet.set_online(True)
    assert "la tablette dort" in tablet.conversation("alice"), f"tablette : {tablet.conversation('alice')!r}"


def test_A10_appareil_retire_hors_ligne_ne_recoit_rien_au_retour():
    net, alice, bob, ap, bp = pair()
    tablet = bob.link_device("tablet")
    tablet.set_online(False)
    bob.remove_device("tablet")
    before = mark(net)
    ap.send("bob", "envoyé après le retrait, tablette absente")
    new = since(net, before)
    tablet.set_online(True)
    assert "envoyé après le retrait, tablette absente" not in tablet.conversation("alice"), (
        "l'appareil retiré reçoit au retour en ligne un message postérieur au retrait"
    )
    assert all(tablet.try_open(b) is None for b in new), "l'appareil retiré déchiffre un blob postérieur"
    assert "envoyé après le retrait, tablette absente" in bp.conversation("alice")


def test_A10_nom_reutilise_l_ancien_appareil_ne_lit_pas():
    net, alice, bob, ap, bp = pair()
    old = bob.link_device("tablet")
    bob.remove_device("tablet")
    new = bob.link_device("tablet")
    assert bob.devices().count("tablet") == 1, f"liste : {bob.devices()!r}"
    before = mark(net)
    ap.send("bob", "pour la nouvelle tablette")
    blobs = since(net, before)
    assert "pour la nouvelle tablette" in new.conversation("alice"), "la nouvelle tablette ne lit pas"
    assert "pour la nouvelle tablette" not in old.conversation("alice"), (
        "l'ancienne tablette retirée lit le message parce qu'elle porte le même nom"
    )
    assert all(old.try_open(b) is None for b in blobs), "l'ancienne tablette déchiffre un blob destiné à la nouvelle"


def test_A11_messages_envoyes_par_soi_avant_liaison_absents():
    net, alice, bob, ap, bp = pair()
    bp.send("alice", "envoyé par bob avant la tablette")
    tablet = bob.link_device("tablet")
    assert "envoyé par bob avant la tablette" not in tablet.conversation("alice"), (
        f"la tablette affiche l'historique envoyé : {tablet.conversation('alice')!r}"
    )


def test_A11_groupe_nouvel_appareil_sans_historique():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    ap.send_group(gid, "historique du groupe")
    assert "historique du groupe" in bp.group_conversation(gid)
    tablet = bob.link_device("tablet")
    assert "historique du groupe" not in tablet.group_conversation(gid)


# --------------------------------------------------------------------------- A13 – A19 : vérification

def test_A13_verification_n_est_pas_reciproque():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", bob.fingerprint())
    assert alice.verification_state("bob") == "vérifié"
    assert bob.verification_state("alice") == "non vérifié", (
        "bob n'a rien scanné : alice doit rester « non vérifié » chez lui"
    )


def test_A14_ancienne_empreinte_apres_reinstallation_ne_verifie_pas():
    net, alice, bob, ap, bp = pair()
    old = bob.fingerprint()
    alice.scan_safety_code("bob", old)
    bp.reinstall()
    alice.scan_safety_code("bob", old)
    assert alice.verification_state("bob") == "non vérifié", "l'ancien code vérifie la nouvelle identité"
    alice.scan_safety_code("bob", bob.fingerprint())
    assert alice.verification_state("bob") == "vérifié", "le nouveau code doit vérifier (A13)"


def test_A18_apres_confirmation_nouveau_changement_sans_avertissement_ni_blocage():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", bob.fingerprint())
    bp.reinstall()
    w1 = len(ap.warnings("bob"))
    assert w1 >= 1
    alice.confirm_identity("bob")
    assert alice.verification_state("bob") == "non vérifié"
    bp.reinstall()
    assert len(ap.warnings("bob")) == w1, (
        f"contact non vérifié (N02) : aucun nouvel avertissement attendu, {w1} → {len(ap.warnings('bob'))}"
    )
    m = ap.send("bob", "après confirmation puis nouveau changement")
    assert m.send_state != "bloqué", "contact non vérifié : l'envoi ne doit pas être bloqué (N04)"
    assert "après confirmation puis nouveau changement" in bp.conversation("alice")


def test_A17_trou_second_changement_sans_confirmation():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", bob.fingerprint())
    bp.reinstall()
    w1 = len(ap.warnings("bob"))
    bp.reinstall()
    assert len(ap.warnings("bob")) == w1, (
        "après le premier changement le contact est « non vérifié » : le second ne doit pas ajouter d'avertissement"
    )


def test_A19_autre_appareil_de_l_expediteur_aussi_bloque():
    net, alice, bob, ap, bp = pair()
    laptop = alice.link_device("laptop")
    alice.scan_safety_code("bob", bob.fingerprint())
    bp.reinstall()
    m = laptop.send("bob", "depuis le laptop")
    assert m.send_state == "bloqué", f"le laptop contourne le blocage : {m.send_state!r}"
    assert "depuis le laptop" not in bp.conversation("alice")


def test_A19_trou_plusieurs_bloques_liberes_dans_l_ordre():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", bob.fingerprint())
    bp.reinstall()
    texts = [f"bloqué n°{i}" for i in range(4)]
    msgs = [ap.send("bob", t) for t in texts]
    assert all(m.send_state == "bloqué" for m in msgs)
    alice.confirm_identity("bob")
    assert [m.send_state for m in msgs] == ["envoyé"] * 4
    conv = [c for c in bp.conversation("alice") if c in texts]
    assert conv == texts, f"attendu {texts}, obtenu {conv}"


def test_A19_double_reinstallation_avant_confirmation():
    net, alice, bob, ap, bp = pair()
    alice.scan_safety_code("bob", bob.fingerprint())
    bp.reinstall()
    m = ap.send("bob", "attend deux réinstallations")
    assert m.send_state == "bloqué"
    bp.reinstall()
    m2 = ap.send("bob", "toujours bloqué")
    assert m2.send_state == "bloqué", "contact précédemment vérifié, empreinte changée : doit rester bloqué"
    alice.confirm_identity("bob")
    conv = bp.conversation("alice")
    assert "attend deux réinstallations" in conv and "toujours bloqué" in conv, (
        f"après confirmation, les messages doivent être lisibles avec les clés les plus récentes : {conv!r}"
    )


# --------------------------------------------------------------------------- A20 – A23 : envoi, accusés

def test_A20_rien_ne_sort_vers_le_serveur_hors_ligne():
    net, alice, bob, ap, bp = pair()
    ap.set_online(False)
    before = mark(net)
    m = ap.send("bob", "reste sur l'appareil")
    assert since(net, before) == [], "un appareil hors ligne a transmis au serveur"
    assert m.send_state == "en attente"


def test_A21_trou_ordre_des_messages_en_attente():
    net, alice, bob, ap, bp = pair()
    ap.set_online(False)
    texts = [f"file n°{i}" for i in range(5)]
    msgs = [ap.send("bob", t) for t in texts]
    ap.set_online(True)
    assert [m.send_state for m in msgs] == ["envoyé"] * 5, f"obtenu {[m.send_state for m in msgs]}"
    conv = [c for c in bp.conversation("alice") if c in texts]
    assert conv == texts, f"ordre attendu {texts}, obtenu {conv}"


def test_A22_seul_appareil_en_ligne_est_un_appareil_retire():
    net, alice, bob, ap, bp = pair()
    bob.link_device("tablet")
    bp.set_online(False)
    bob.remove_device("tablet")
    m = ap.send("bob", "seule la tablette retirée est en ligne")
    assert m.receipt() != "remis", "accusé « remis » par un appareil retiré"
    bp.set_online(True)
    assert m.receipt() == "remis"


def test_A22_expediteur_hors_ligne_pas_remis():
    net, alice, bob, ap, bp = pair()
    ap.set_online(False)
    m = ap.send("bob", "pas encore parti")
    assert m.receipt() != "remis", "accusé « remis » pour un message jamais parti"
    ap.set_online(True)
    assert m.receipt() == "remis", f"attendu « remis » après envoi, obtenu {m.receipt()!r}"


# --------------------------------------------------------------------------- A24 – A28 : groupes

def test_A24_trou_ajout_en_double():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "bob")
    members = alice.group_members(gid)
    assert members.count("bob") == 1, f"obtenu {members!r}"
    ap.send_group(gid, "une seule fois")
    assert bp.group_conversation(gid).count("une seule fois") == 1


def test_A28_membre_retire_puis_readmis_ne_voit_pas_l_intervalle():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    alice.add_member(gid, "carol")
    alice.remove_member(gid, "bob")
    before = mark(net)
    ap.send_group(gid, "pendant l'absence de bob")
    gap = since(net, before)
    alice.add_member(gid, "bob")
    ap.send_group(gid, "retour de bob")
    conv = bp.group_conversation(gid)
    assert "retour de bob" in conv, f"bob réadmis ne lit pas : {conv!r}"
    assert "pendant l'absence de bob" not in conv, "bob réadmis voit un message de son absence"
    assert all(bp.try_open(b) != "pendant l'absence de bob" for b in gap)


def test_A27_trou_non_membre_ne_dechiffre_pas():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    alice.add_member(gid, "bob")
    before = mark(net)
    ap.send_group(gid, "entre alice et bob seulement")
    opened = [cp.try_open(b) for b in since(net, before)]
    assert "entre alice et bob seulement" not in opened, "carol, jamais membre, déchiffre un message de groupe"


def test_A26_trou_membre_a_deux_appareils():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    tablet = bob.link_device("tablet")
    alice.add_member(gid, "bob")
    ap.send_group(gid, "pour tous les appareils de bob")
    assert "pour tous les appareils de bob" in bp.group_conversation(gid)
    assert "pour tous les appareils de bob" in tablet.group_conversation(gid), (
        f"tablette : {tablet.group_conversation(gid)!r}"
    )


# --------------------------------------------------------------------------- A30 – A36 : minuterie

def test_A30_trou_minuterie_propre_a_la_conversation():
    net, alice, bob, carol, ap, bp, cp, gid = group3()
    ap.set_timer("bob", HOUR)
    assert ap.timer("carol") is None, f"la minuterie alice-bob déborde sur alice-carol : {ap.timer('carol')!r}"
    ap.send("carol", "durable")
    cp.read("alice")
    net.advance(2 * HOUR)
    assert "durable" in cp.conversation("alice")
    assert "durable" in ap.conversation("carol")


def test_A31_desactivation_propagee():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.set_timer("bob", None)
    assert bp.timer("alice") is None, f"obtenu {bp.timer('alice')!r}"


def test_A32_delai_compte_depuis_la_lecture_pas_depuis_l_envoi():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "compté depuis la lecture")
    net.advance(HOUR // 2)
    bp.read("alice")
    net.advance(HOUR // 2 + 60)
    assert "compté depuis la lecture" in bp.conversation("alice"), "disparu chez bob avant une heure de lecture"
    assert "compté depuis la lecture" in ap.conversation("bob"), "disparu chez alice avant une heure de lecture"
    net.advance(HOUR // 2)
    assert "compté depuis la lecture" not in bp.conversation("alice")
    assert "compté depuis la lecture" not in ap.conversation("bob")


def test_A32_message_arrive_apres_la_lecture_n_est_pas_lu():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "lu")
    bp.read("alice")
    ap.send("bob", "arrivé après la lecture")
    net.advance(HOUR + 1)
    assert "lu" not in bp.conversation("alice")
    assert "arrivé après la lecture" in bp.conversation("alice"), "un message non lu a disparu"
    assert "arrivé après la lecture" in ap.conversation("bob"), "non lu : ne doit pas disparaître chez l'expéditeur (N09)"


def test_N09_lecture_par_l_expediteur_ne_declenche_rien():
    net, alice, bob, ap, bp = pair()
    ap.set_timer("bob", HOUR)
    ap.send("bob", "alice relit son envoi")
    ap.read("bob")
    net.advance(HOUR + 1)
    assert "alice relit son envoi" in bp.conversation("alice"), "disparu chez bob sans qu'il l'ait lu"
    assert "alice relit son envoi" in ap.conversation("bob"), "disparu chez alice sans lecture du destinataire"
