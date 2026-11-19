"""Messagerie à chiffrement de bout en bout — module unique.

Mécanisme :
- chaque appareil génère ses propres clés X25519 et ne les partage avec personne ;
- chaque message a une clé de message aléatoire K (ChaCha20-Poly1305) qui chiffre le corps ;
- pour chaque appareil destinataire, un blob contient K et les métadonnées, chiffrés
  avec une clé dérivée (HKDF) d'un accord X25519 éphémère ↔ clé publique de l'appareil ;
- les accusés de remise et de lecture, ainsi que les minuteries, sont eux aussi des blobs
  chiffrés (messages de contrôle) : le serveur ne stocke que des blobs opaques.

Format d'un blob :
    E (32) | wn (12) | wl (2) | wct (wl) | bn (12) | bct (reste)
    wct = ChaCha20Poly1305(wk, wn)(K || JSON(meta))
    bct = ChaCha20Poly1305(K, bn)(corps UTF-8)
"""

import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_WCT_START = 46  # 32 (E) + 12 (wn) + 2 (wl)
_WRAP_INFO = b"app-wrap-v1"


def _raw_pub(priv):
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _wrap_key(shared, eph_pub, dev_pub):
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=eph_pub + dev_pub,
        info=_WRAP_INFO,
    ).derive(shared)


def _split(blob):
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < _WCT_START:
        return None
    wl = int.from_bytes(blob[44:46], "big")
    end = _WCT_START + wl
    if len(blob) < end + 12 + 16:
        return None
    # (E, wn, wct, bn, bct, en-tête) : l'en-tête est tout ce qui précède bn.
    return (
        bytes(blob[:32]),
        bytes(blob[32:44]),
        bytes(blob[_WCT_START:end]),
        bytes(blob[end:end + 12]),
        bytes(blob[end + 12:]),
        bytes(blob[:end]),
    )


def _seal(key, meta, dev_pub, body):
    eph = X25519PrivateKey.generate()
    eph_pub = _raw_pub(eph)
    shared = eph.exchange(X25519PublicKey.from_public_bytes(dev_pub))
    wn = os.urandom(12)
    wplain = key + json.dumps(meta).encode("utf-8")
    wct = ChaCha20Poly1305(_wrap_key(shared, eph_pub, dev_pub)).encrypt(wn, wplain, None)
    header = eph_pub + wn + len(wct).to_bytes(2, "big") + wct
    bn = os.urandom(12)
    # Le corps authentifie l'en-tête entier : toute altération, même de l'enveloppe, est détectée.
    bct = ChaCha20Poly1305(key).encrypt(bn, body, header)
    return header + bn + bct


def open_with_key(key, blob):
    """Déchiffre le corps d'un blob avec une clé de message seule ; None si impossible."""
    try:
        parts = _split(blob)
        if parts is None:
            return None
        bn, bct, header = parts[3], parts[4], parts[5]
        return ChaCha20Poly1305(bytes(key)).decrypt(bn, bct, header).decode("utf-8")
    except Exception:
        return None


class Server:
    """Ne stocke que des blobs opaques, et l'annuaire des clés publiques."""

    def __init__(self):
        self._blobs = []
        self.directory = {}  # utilisateur -> {appareil: clé publique}

    def received(self):
        return list(self._blobs)

    def count(self):
        return len(self._blobs)

    def store(self, blob):
        self._blobs.append(blob)


class Network:
    def __init__(self):
        self.server = Server()
        self.now = 0
        self._interceptor = None
        self._users = {}
        self._devices = []

    def advance(self, seconds):
        self.now += seconds

    def set_interceptor(self, fn):
        self._interceptor = fn

    def create_user(self, name):
        user = User(self, name)
        self._users[name] = user
        return user

    def _transit(self, blob):
        if self._interceptor is not None:
            blob = self._interceptor(blob)
        self.server.store(blob)
        for dev in list(self._devices):
            if dev.online and not dev.removed:
                dev._pump()

    def _pubkeys(self, user):
        return list(self.server.directory.get(user, {}).values())

    def _fingerprint(self, user):
        keys = sorted(self.server.directory.get(user, {}).values())
        return hashlib.sha256(b"".join(keys)).hexdigest()[:40]

    def _set_key(self, user, dev, pub):
        self.server.directory.setdefault(user, {})[dev] = pub
        self._key_changed(user)

    def _del_key(self, user, dev):
        del self.server.directory[user][dev]
        self._key_changed(user)

    def _key_changed(self, user):
        fp = self._fingerprint(user)
        for other in self._users.values():
            contact = other._contacts.get(user)
            if contact is not None:
                contact.on_fingerprint(fp)


class User:
    def __init__(self, net, name):
        self.net = net
        self.name = name
        self._devices = {}
        self._contacts = {}
        self._groups = {}
        self._sent = {}     # id -> Message (messages envoyés par cet utilisateur)
        self._blocked = []  # (appareil, message) en attente de confirmation
        self._queue = []    # opérations de groupe en attente d'un appareil en ligne

    def link_device(self, name):
        dev = Device(self.net, self, name)
        self._devices[name] = dev
        self.net._set_key(self.name, name, dev.pub)
        return dev

    def remove_device(self, name):
        dev = self._devices.pop(name)
        dev.removed = True
        self.net._del_key(self.name, name)

    def devices(self):
        return list(self._devices)

    def add_contact(self, name):
        self._contacts[name] = Contact(self.net, name)

    def verification_state(self, name):
        return "vérifié" if self._contacts[name].verified else "non vérifié"

    def fingerprint(self):
        return self.net._fingerprint(self.name)

    def fingerprint_of(self, name):
        return self.net._fingerprint(name)

    def scan_safety_code(self, name, code):
        if code == self.net._fingerprint(name):
            self._contacts[name].verified = True

    def confirm_identity(self, name):
        contact = self._contacts.get(name)
        if contact is None:
            return
        contact.blocked = False
        pending = [(d, m) for (d, m) in self._blocked if m.recipient == name]
        self._blocked = [(d, m) for (d, m) in self._blocked if m.recipient != name]
        for dev, m in pending:
            dev._dispatch(m)

    def create_group(self, group_name):
        gid = os.urandom(8).hex()
        self._groups[gid] = [self.name]
        return gid

    def group_members(self, gid):
        return list(self._groups[gid])

    def add_member(self, gid, name):
        members = self._groups[gid]
        if name not in members:
            members.append(name)
        self._emit_group(gid, list(members), [u for u in members if u != self.name])

    def remove_member(self, gid, name):
        old = list(self._groups[gid])
        members = [u for u in old if u != name]
        self._groups[gid] = members
        self._emit_group(gid, list(members), [u for u in old if u != self.name])

    def _emit_group(self, gid, members, users):
        meta = {"kind": "group", "gid": gid, "members": members}
        dev = next((d for d in self._devices.values() if d.online), None)
        if dev is None:
            self._queue.append((meta, users))
        else:
            dev._send_blobs(os.urandom(32), meta, b"", users)


class Contact:
    def __init__(self, net, name):
        self.name = name
        self.verified = False
        self.blocked = False
        self.warnings = []
        self.fingerprint = net._fingerprint(name)

    def on_fingerprint(self, fp):
        if fp == self.fingerprint:
            return
        self.fingerprint = fp
        if self.verified:
            self.verified = False
            self.blocked = True
            self.warnings.append(f"l'empreinte de {self.name} a changé")


class Message:
    def __init__(self, sender, recipient, gid, text, timer):
        self.id = os.urandom(8).hex()
        self.sender = sender
        self.recipient = recipient
        self.gid = gid
        self.text = text
        self.timer = timer
        self.key = os.urandom(32)
        self.send_state = "en attente"
        self.acked_by = set()  # utilisateurs ayant accusé réception
        self.read_at = None    # instant de lecture rapporté par le destinataire

    def receipt(self, name=None):
        if name is None:
            name = self.recipient
        return "remis" if name in self.acked_by else "non remis"


class Device:
    def __init__(self, net, owner, name):
        self.net = net
        self.owner = owner
        self.name = name
        self.online = True
        self.removed = False
        self._pumping = False
        self._new_keys()
        self._cursor = net.server.count()
        self._inbox = {}    # interlocuteur -> entrées
        self._ginbox = {}   # gid -> entrées
        self._timers = {}   # interlocuteur -> secondes | None
        self._outbox = []   # actions différées (hors ligne)
        net._devices.append(self)

    def _new_keys(self):
        self._priv = X25519PrivateKey.generate()
        self.pub = _raw_pub(self._priv)

    def reinstall(self):
        self._new_keys()
        self._inbox = {}
        self._ginbox = {}
        self._cursor = self.net.server.count()
        self.net._set_key(self.owner.name, self.name, self.pub)

    def set_online(self, on):
        self.online = bool(on)
        if self.online and not self.removed:
            self._pump()
            self._flush()

    def _flush(self):
        pending, self._outbox = self._outbox, []
        for action in pending:
            action()
        queued, self.owner._queue = self.owner._queue, []
        for meta, users in queued:
            self._send_blobs(os.urandom(32), meta, b"", users)

    # ---- réception -------------------------------------------------------

    def _pump(self):
        # Garde contre la réentrance : un accusé émis pendant la réception est traité
        # par la boucle en cours, qui relit la longueur du journal à chaque tour.
        if self._pumping:
            return
        self._pumping = True
        try:
            blobs = self.net.server._blobs
            while self._cursor < len(blobs):
                blob = blobs[self._cursor]
                self._cursor += 1
                got = self._open(blob)
                if got is not None:
                    self._handle(*got)
        finally:
            self._pumping = False

    def _open(self, blob):
        try:
            parts = _split(blob)
            if parts is None:
                return None
            eph_pub, wn, wct, bn, bct, header = parts
            shared = self._priv.exchange(X25519PublicKey.from_public_bytes(eph_pub))
            wplain = ChaCha20Poly1305(_wrap_key(shared, eph_pub, self.pub)).decrypt(wn, wct, None)
            key = wplain[:32]
            meta = json.loads(wplain[32:].decode("utf-8"))
            body = ChaCha20Poly1305(key).decrypt(bn, bct, header)
            return body.decode("utf-8"), meta
        except Exception:
            return None

    def _handle(self, text, meta):
        kind = meta.get("kind")
        if kind == "msg":
            gid = meta.get("gid")
            if gid is None:
                bucket = self._inbox.setdefault(meta["from"], [])
            else:
                bucket = self._ginbox.setdefault(gid, [])
            if any(e["id"] == meta["id"] for e in bucket):
                return  # blob rejoué : déjà affiché, rien de nouveau
            bucket.append({
                "id": meta["id"],
                "text": text,
                "timer": meta.get("timer"),
                "read_at": None,
                "own": False,
            })
            ack = {"kind": "ack", "id": meta["id"], "user": self.owner.name}
            self._send_blobs(os.urandom(32), ack, b"", [meta["from"]])
        elif kind == "ack":
            m = self.owner._sent.get(meta["id"])
            if m is not None:
                m.acked_by.add(meta["user"])
        elif kind == "read":
            m = self.owner._sent.get(meta["id"])
            if m is not None and m.read_at is None:
                m.read_at = meta["at"]
        elif kind == "timer":
            self._timers[meta["from"]] = meta["value"]
        elif kind == "group":
            self.owner._groups[meta["gid"]] = list(meta["members"])

    # ---- émission --------------------------------------------------------

    def _send_blobs(self, key, meta, body, users):
        for user in users:
            for pub in self.net._pubkeys(user):
                self.net._transit(_seal(key, meta, pub, body))

    def _control(self, meta, users):
        if not self.online:
            self._outbox.append(lambda: self._control(meta, users))
            return
        self._send_blobs(os.urandom(32), meta, b"", users)

    def send(self, name, text):
        m = Message(self.owner.name, name, None, text, self._timers.get(name))
        self.owner._sent[m.id] = m
        self._inbox.setdefault(name, []).append(self._own_entry(m))
        self._dispatch(m)
        return m

    def send_group(self, gid, text):
        m = Message(self.owner.name, None, gid, text, None)
        self.owner._sent[m.id] = m
        self._ginbox.setdefault(gid, []).append(self._own_entry(m))
        self._dispatch(m)
        return m

    def _own_entry(self, m):
        return {"id": m.id, "text": m.text, "timer": m.timer, "msg": m, "own": True}

    def _dispatch(self, m):
        if not self.online:
            m.send_state = "en attente"
            self._outbox.append(lambda: self._dispatch(m))
            return
        if m.gid is None:
            contact = self.owner._contacts.get(m.recipient)
            if contact is not None and contact.blocked:
                m.send_state = "bloqué"
                self.owner._blocked.append((self, m))
                return
        self._transmit(m)

    def _transmit(self, m):
        if m.gid is None:
            users = [m.recipient]
        else:
            users = [u for u in self.owner._groups.get(m.gid, []) if u != self.owner.name]
        meta = {"kind": "msg", "id": m.id, "from": self.owner.name, "gid": m.gid, "timer": m.timer}
        self._send_blobs(m.key, meta, m.text.encode("utf-8"), users)
        m.send_state = "envoyé"

    # ---- lecture, affichage, minuterie ----------------------------------

    def read(self, name):
        now = self.net.now
        for e in self._inbox.get(name, []):
            if not e["own"] and e["read_at"] is None:
                e["read_at"] = now
                self._control({"kind": "read", "id": e["id"], "at": now}, [name])

    def _visible(self, e):
        if e["timer"] is None:
            return True
        start = e["msg"].read_at if e["own"] else e["read_at"]
        if start is None:
            return True
        return self.net.now < start + e["timer"]

    def conversation(self, name):
        return [e["text"] for e in self._inbox.get(name, []) if self._visible(e)]

    def group_conversation(self, gid):
        return [e["text"] for e in self._ginbox.get(gid, []) if self._visible(e)]

    def warnings(self, name):
        contact = self.owner._contacts.get(name)
        return list(contact.warnings) if contact is not None else []

    def set_timer(self, name, seconds):
        self._timers[name] = seconds
        self._control({"kind": "timer", "from": self.owner.name, "value": seconds}, [name])

    def timer(self, name):
        return self._timers.get(name)

    # ---- outils de test --------------------------------------------------

    def try_open(self, blob):
        got = self._open(blob)
        if got is None or got[1].get("kind") != "msg":
            return None
        return got[0]

    def message_key(self, msg):
        return msg.key
