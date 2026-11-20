"""Messagerie chiffrée simulée en mémoire."""

import hashlib
import os
import itertools

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Unreadable(Exception):
    pass


class Server:
    def __init__(self):
        self.blobs = {}  # msg_id -> bytes chiffré

    def stored(self):
        return list(self.blobs.values())


class Msg:
    def __init__(self, mid, sender, sender_device, to, group, key, duration):
        self.id = mid
        self.sender = sender
        self.sender_device = sender_device
        self.to = to
        self.group = group
        self.key = key
        self.duration = duration
        self.recipients = set()
        self.sent = False
        self.delivered = set()
        self.read_at = None

    def conv_for(self, user_name):
        if self.group:
            return self.to
        return self.to if user_name == self.sender else self.sender


class Device:
    def __init__(self, user, name):
        self.user = user
        self.name = name
        self.online = True
        self.keys = {}
        self.convs = {}
        self.queue = []
        self.outbox = []

    def receive(self, msg):
        self.keys[msg.id] = msg.key
        self.convs.setdefault(msg.conv_for(self.user.name), []).append(msg.id)
        if self.user.name != msg.sender:
            msg.delivered.add(self.user.name)


class Network:
    def __init__(self):
        self.server = Server()
        self.now = 0
        self.users = {}
        self.groups = {}
        self.msgs = {}
        self._ids = itertools.count(1)

    def advance(self, seconds):
        self.now += seconds

    def register(self, name, device="principal"):
        u = User(self, name, device)
        self.users[name] = u
        return u

    def _upload(self, msg):
        msg.sent = True
        nonce = os.urandom(12)
        payload = msg.plain.encode("utf-8")
        self.server.blobs[msg.id] = nonce + AESGCM(msg.key).encrypt(nonce, payload, None)
        names = set(msg.recipients) | {msg.sender}
        for n in names:
            user = self.users[n]
            for dev in user.devs.values():
                if n == msg.sender and dev.name == msg.sender_device:
                    continue
                if dev.online:
                    dev.receive(msg)
                else:
                    dev.queue.append(msg)

    def visible(self, mid):
        m = self.msgs[mid]
        return not (m.duration is not None and m.read_at is not None
                    and self.now >= m.read_at + m.duration)


class Group:
    def __init__(self, members):
        self.members = set(members)
        self.timer = None


class User:
    def __init__(self, net, name, device):
        self.net = net
        self.name = name
        self.devs = {device: Device(self, device)}
        self.identity = os.urandom(32)
        self.verified = set()
        self._alerts = {}
        self.timers = {}

    # appareils
    def devices(self):
        return list(self.devs)

    def link_device(self, device_name):
        self.devs[device_name] = Device(self, device_name)
        return device_name

    def unlink_device(self, device_name):
        self.devs.pop(device_name, None)

    def set_online(self, online, device=None):
        targets = list(self.devs.values()) if device is None else [self.devs[device]]
        for d in targets:
            d.online = online
            if online:
                outbox, d.outbox = d.outbox, []
                for m in outbox:
                    self.net._upload(m)
                queue, d.queue = d.queue, []
                for m in queue:
                    d.receive(m)

    def _dev(self, device):
        return self.devs[device] if device is not None else next(iter(self.devs.values()))

    # messages
    def send(self, to, text, device=None):
        net = self.net
        dev = self._dev(device)
        group = to in net.groups
        if group:
            recipients = set(net.groups[to].members) - {self.name}
            duration = net.groups[to].timer
        else:
            recipients = {to}
            duration = self.timers.get(to)
        mid = "m%d" % next(net._ids)
        msg = Msg(mid, self.name, dev.name, to, group, os.urandom(32), duration)
        msg.plain = text
        msg.recipients = recipients
        net.msgs[mid] = msg
        dev.receive(msg)
        if dev.online:
            net._upload(msg)
        else:
            dev.outbox.append(msg)
        return mid

    def open(self, msg_id, device=None):
        if device is None:
            devs = list(self.devs.values())
        else:
            devs = [self.devs[device]] if device in self.devs else []
        for d in devs:
            key = d.keys.get(msg_id)
            if key is None:
                continue
            blob = self.net.server.blobs.get(msg_id)
            msg = self.net.msgs[msg_id]
            if blob is None:
                text = msg.plain  # message pas encore parti (chez l'expéditeur)
            else:
                text = AESGCM(key).decrypt(blob[:12], blob[12:], None).decode("utf-8")
            if self.name != msg.sender and msg.read_at is None:
                msg.read_at = self.net.now
            return text
        raise Unreadable(msg_id)

    def conversation(self, to, device=None):
        d = self._dev(device)
        return [m for m in d.convs.get(to, []) if self.net.visible(m)]

    def receipt(self, msg_id):
        m = self.net.msgs[msg_id]
        if not m.sent:
            return "en attente"
        if m.read_at is not None:
            return "lu"
        if m.group:
            ok = m.recipients <= m.delivered
        else:
            ok = bool(m.delivered)
        return "remis" if ok and m.recipients else "envoyé"

    def message_key(self, msg_id):
        for d in self.devs.values():
            if msg_id in d.keys:
                return d.keys[msg_id]
        raise Unreadable(msg_id)

    # groupes
    def create_group(self, title, members):
        gid = "groupe:%d" % (len(self.net.groups) + 1)
        self.net.groups[gid] = Group(set(members) | {self.name})
        return gid

    def members(self, group_id):
        return set(self.net.groups[group_id].members)

    def add_member(self, group_id, name):
        self.net.groups[group_id].members.add(name)

    def remove_member(self, group_id, name):
        self.net.groups[group_id].members.discard(name)

    def leave_group(self, group_id):
        self.net.groups[group_id].members.discard(self.name)

    # identité
    def fingerprint(self, contact):
        a = self.identity
        b = self.net.users[contact].identity
        if self.name == contact:
            return hashlib.sha256(a + a).hexdigest()
        lo, hi = sorted([a, b])
        return hashlib.sha256(lo + hi).hexdigest()

    def verification(self, contact):
        return "vérifié" if contact in self.verified else "non vérifié"

    def mark_verified(self, contact):
        self.verified.add(contact)

    def alerts(self, contact):
        return list(self._alerts.get(contact, []))

    def reset_identity(self):
        self.identity = os.urandom(32)
        for u in self.net.users.values():
            if u is self:
                continue
            u.verified.discard(self.name)
            u._alerts.setdefault(self.name, []).append("clé d'identité modifiée")

    # minuteur
    def set_timer(self, to, seconds):
        if to in self.net.groups:
            self.net.groups[to].timer = seconds
        else:
            self.timers[to] = seconds

    def timer(self, to):
        if to in self.net.groups:
            return self.net.groups[to].timer
        return self.timers.get(to)


class Attacker:
    def __init__(self, net):
        self.net = net
        self.keys = []

    def compromise(self, key):
        self.keys.append(key)

    def read(self, msg_id):
        blob = self.net.server.blobs.get(msg_id)
        if blob is None:
            return None
        for k in self.keys:
            try:
                return AESGCM(k).decrypt(blob[:12], blob[12:], None).decode("utf-8")
            except (InvalidTag, ValueError):
                continue
        return None
