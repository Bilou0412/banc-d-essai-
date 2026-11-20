"""Édition collaborative à fusion réelle : RGA (séquence répliquée) sur réseau simulé.

Chaque participant a sa réplique et édite localement. Les éditions sont des opérations
relayées par le serveur, qui contrôle les permissions, numérote le journal et suit la
présence. Les répliques convergent par la fusion RGA : pas de verrou, pas de remplacement
global du texte.

Suppression et annulation : un caractère est masqué tant qu'il porte au moins une étiquette
de masquage (identifiant de l'opération qui l'a masqué). Masquer ajoute une étiquette ;
démasquer retire les seules étiquettes observées localement. L'annulation d'une suppression
fait donc réapparaître les mêmes caractères, et une suppression concurrente d'autrui reste
active.
"""

import random
from collections import namedtuple

Version = namedtuple("Version", "author text")

END = "end"


class _Elem:
    __slots__ = ("ts", "origin", "char", "tags")

    def __init__(self, ts, origin, char):
        self.ts = ts
        self.origin = origin
        self.char = char
        self.tags = set()  # identifiants des opérations qui masquent ce caractère


class Replica:
    """Séquence RGA : chaque caractère porte son identifiant (ts) et son origine."""

    def __init__(self, text):
        self.seq = []
        self.index = {}
        prev = None
        for i, ch in enumerate(text):
            ts = (0, "", i)
            self.insert(ts, prev, ch)
            prev = ts

    def insert(self, ts, origin, char):
        if ts in self.index:
            return
        elem = _Elem(ts, origin, char)
        if origin is None:
            i = 0
        else:
            i = self.seq.index(self.index[origin]) + 1
        # Les éléments plus récents que le nouveau passent devant (règle RGA).
        while i < len(self.seq) and self.seq[i].ts > ts:
            i += 1
        self.seq.insert(i, elem)
        self.index[ts] = elem

    def hide(self, ts, tag):
        elem = self.index.get(ts)
        if elem is not None:
            elem.tags.add(tag)

    def reveal(self, ts, tags):
        elem = self.index.get(ts)
        if elem is not None:
            elem.tags -= set(tags)

    def visible(self):
        return [e for e in self.seq if not e.tags]

    def text(self):
        return "".join(e.char for e in self.seq if not e.tags)

    def position(self, anchor):
        """Position visible du point d'ancrage (le caractère qui suit le curseur)."""
        if anchor == END:
            return len(self.visible())
        elem = self.index.get(anchor)
        if elem is None:
            return None
        count = 0
        for e in self.seq:
            if e is elem:
                break
            if not e.tags:
                count += 1
        return count


class Network:
    """Réseau simulé en mémoire : messages en attente, livrés dans l'ordre ou au hasard."""

    def __init__(self):
        self._queue = []
        self.now = 0

    def send(self, dst, msg):
        self._queue.append((dst, msg))

    def advance(self, seconds):
        self.now += seconds

    def _pop(self, rng):
        idx = rng.randrange(len(self._queue)) if rng is not None else 0
        dst, msg = self._queue.pop(idx)
        # Un client déconnecté ne reçoit rien : les messages qui lui sont destinés sont perdus.
        if getattr(dst, "connected", True):
            dst._receive(msg)

    def deliver(self, n, seed=None):
        rng = random.Random(seed) if seed is not None else None
        count = 0
        while count < n and self._queue:
            self._pop(rng)
            count += 1
        return count

    def deliver_all(self, seed=None):
        rng = random.Random(seed) if seed is not None else None
        count = 0
        while self._queue:
            self._pop(rng)
            count += 1
        return count


class Server:
    """Document partagé côté serveur : journal ordonné, permissions, présence, curseurs."""

    def __init__(self, network, owner, text="", permissions=None):
        self.network = network
        self.owner = owner
        self.base = text
        self.perms = {k: v for k, v in (permissions or {}).items() if k != owner}
        self.log = []
        self._op_index = {}
        self.sessions = {}   # nom -> client connecté (présence, quel que soit son droit)
        self.cursors = {}    # nom -> ancrage du curseur
        self._cseq = {}      # nom -> numéro du dernier déplacement de curseur retenu
        self._pseq = {}      # nom -> numéro du dernier changement de permission retenu
        self._version = 0

    def open(self, name):
        return Client(self, name)

    def can_read(self, name):
        return name == self.owner or self.perms.get(name) in ("read", "write")

    def can_write(self, name):
        return name == self.owner or self.perms.get(name) == "write"

    def session_lost(self, client):
        if self.sessions.get(client.name) is client:
            del self.sessions[client.name]
            self.cursors.pop(client.name, None)
            self._broadcast_state()

    def _receive(self, msg):
        kind = msg[0]
        if kind == "sync":
            self._on_sync(*msg[1:])
        elif kind == "op":
            self._on_op(*msg[1:])
        elif kind == "cursor":
            self._on_cursor(*msg[1:])
        elif kind == "perm":
            self._on_perm(*msg[1:])

    def _on_sync(self, client, have, outbox, anchor, cseq):
        name = client.name
        if client.connected:
            self.sessions[name] = client
            if cseq > 0 and cseq >= self._cseq.get(name, 0):
                self._cseq[name] = cseq
                self.cursors[name] = anchor
        rejected = [op["id"] for op in outbox if not self._submit(op)]
        if rejected:
            self.network.send(client, ("reject", rejected))
        if self.can_read(name):
            for idx in range(have, len(self.log)):
                self.network.send(client, ("entry", idx, self.log[idx]))
        self._broadcast_state()

    def _on_op(self, client, op):
        if not self._submit(op):
            self.network.send(client, ("reject", [op["id"]]))

    def _on_cursor(self, client, anchor, seq):
        name = client.name
        if self.sessions.get(name) is not client:
            return
        if seq > self._cseq.get(name, 0):
            self._cseq[name] = seq
            self.cursors[name] = anchor
            self._broadcast_state()

    def _on_perm(self, client, user, level, seq=0):
        if client.name != self.owner or user == self.owner:
            return
        # N01 : le dernier changement émis l'emporte, quel que soit l'ordre de livraison.
        if seq <= self._pseq.get(user, 0):
            return
        self._pseq[user] = seq
        if level in ("read", "write"):
            self.perms[user] = level
        elif level is None:
            self.perms.pop(user, None)
        else:
            return
        self._broadcast_state()

    def _submit(self, op):
        if op["id"] in self._op_index:
            return True
        if not self.can_write(op["author"]):
            return False
        idx = len(self.log)
        self.log.append(op)
        self._op_index[op["id"]] = idx
        for client in list(self.sessions.values()):
            if self.can_read(client.name):
                self.network.send(client, ("entry", idx, op))
        return True

    def _broadcast_state(self):
        self._version += 1
        names = sorted(self.sessions)
        cursors = {n: self.cursors[n] for n in names if n in self.cursors}
        state = ("state", self._version, self.owner, names, cursors, dict(self.perms))
        for client in list(self.sessions.values()):
            self.network.send(client, state)


def _opposite(effects):
    return [("show" if mode == "hide" else "hide", ids) for mode, ids in effects]


class Client:
    """Réplique locale d'un participant. Édite sans attendre le réseau."""

    def __init__(self, server, name):
        self.server = server
        self.network = server.network
        self.name = name
        self.connected = True
        self.replica = Replica(server.base)
        self._owner = server.owner
        self._perms = dict(server.perms)
        self._presence = []
        self._cursors = {}
        self._state_version = 0
        self.entries = {}     # idx du journal -> opération
        self.outbox = []      # opérations locales non encore confirmées par le serveur
        self.applied = []     # opérations appliquées à la réplique, dans l'ordre
        self._applied_ids = set()
        self._pending = []    # opérations distantes en attente de leurs dépendances
        self._clock = 0
        self._op_seq = 0
        self._cseq = 0
        self._pseq = 0        # numéro des changements de permission émis (propriétaire)
        self._undo = []       # chaque entrée : liste d'effets ("hide"|"show", ids)
        self._redo = []
        vis = self.replica.visible()
        self._anchor = vis[0].ts if vis else END
        self._send_sync()

    # ------------------------------------------------------------ réseau

    def _send(self, msg):
        self.network.send(self.server, msg)

    def _send_sync(self):
        self._send(("sync", self, self._have(), list(self.outbox), self._anchor, self._cseq))

    def _have(self):
        n = 0
        while n in self.entries:
            n += 1
        return n

    def _receive(self, msg):
        kind = msg[0]
        if kind == "entry":
            self._on_entry(msg[1], msg[2])
        elif kind == "reject":
            self._on_reject(msg[1])
        elif kind == "state":
            self._on_state(*msg[1:])

    def _on_entry(self, idx, op):
        self.entries.setdefault(idx, op)
        self.outbox = [o for o in self.outbox if o["id"] != op["id"]]
        if op["id"] not in self._applied_ids and all(p["id"] != op["id"] for p in self._pending):
            self._pending.append(op)
            self._drain()

    def _on_reject(self, ids):
        gone = set(ids)
        self.outbox = [o for o in self.outbox if o["id"] not in gone]
        if gone & self._applied_ids:
            # Reconstruit la réplique sans les opérations refusées.
            old = [o for o in self.applied if o["id"] not in gone]
            self.applied = []
            self._applied_ids = set()
            self.replica = Replica(self.server.base)
            self._pending = old + self._pending
            self._drain()
            self.outbox = [o for o in self.outbox if o["id"] in self._applied_ids]

    def _on_state(self, version, owner, names, cursors, perms):
        if version <= self._state_version:
            return
        self._state_version = version
        self._owner = owner
        self._presence = list(names)
        self._cursors = dict(cursors)
        self._perms = dict(perms)

    # ------------------------------------------------------------ fusion

    def _drain(self):
        progress = True
        while progress:
            progress = False
            rest = []
            for op in self._pending:
                if op["id"] in self._applied_ids:
                    continue
                if self._ready(op):
                    self._apply(op)
                    progress = True
                else:
                    rest.append(op)
            self._pending = rest

    def _ready(self, op):
        local = {p[1] for p in op["prims"] if p[0] == "ins"}

        def known(ts):
            return ts in local or ts in self.replica.index

        for p in op["prims"]:
            if p[0] == "ins":
                if p[2] is not None and not known(p[2]):
                    return False
            elif p[0] == "hide":
                if not known(p[1]):
                    return False
            else:
                if not known(p[1]) or any(t not in self._applied_ids for t in p[2]):
                    return False
        return True

    def _apply(self, op):
        for p in op["prims"]:
            kind = p[0]
            if kind == "ins":
                _, ts, origin, ch = p
                self._clock = max(self._clock, ts[0])
                self.replica.insert(ts, origin, ch)
            elif kind == "hide":
                self.replica.hide(p[1], op["id"])
            else:
                self.replica.reveal(p[1], p[2])
        self.applied.append(op)
        self._applied_ids.add(op["id"])

    def _chain(self, origin, text):
        prims, ids = [], []
        for ch in text:
            self._clock += 1
            ts = (self._clock, self.name, 0)
            prims.append(("ins", ts, origin, ch))
            ids.append(ts)
            origin = ts
        return prims, ids

    def _commit(self, prims, hist=None):
        self._op_seq += 1
        op = {"id": (self.name, self._op_seq), "author": self.name,
              "prims": prims, "hist": hist}
        self._apply(op)
        self.outbox.append(op)
        if self.connected:
            self._send(("op", self, op))

    def _effect_prims(self, effects):
        prims = []
        for mode, ids in effects:
            for ts in ids:
                elem = self.replica.index.get(ts)
                if elem is None:
                    continue
                if mode == "hide":
                    prims.append(("hide", ts))
                elif elem.tags:
                    prims.append(("show", ts, frozenset(elem.tags)))
        return prims

    def _play(self, effects):
        prims = self._effect_prims(effects)
        if prims:
            self._commit(prims)

    # ------------------------------------------------------------ permissions

    def _permission(self):
        if self.name == self._owner:
            return "write"
        return self._perms.get(self.name)

    def _require(self, level):
        perm = self._permission()
        if perm is None or (level == "write" and perm != "write"):
            raise PermissionError(f"{self.name} : permission {level} requise")

    def permission_of(self, user):
        if user == self._owner:
            return "write"
        return self._perms.get(user)

    def set_permission(self, user, level):
        if self.name != self._owner:
            raise PermissionError("seul le propriétaire modifie les permissions")
        if self.connected:
            self._pseq += 1
            self._send(("perm", self, user, level, self._pseq))

    # ------------------------------------------------------------ lecture

    @property
    def content(self):
        if self._permission() is None:
            return None
        return self.replica.text()

    @property
    def presence(self):
        return list(self._presence)

    @property
    def cursor(self):
        pos = self.replica.position(self._anchor)
        return 0 if pos is None else pos

    @property
    def remote_cursors(self):
        out = {}
        for name, anchor in self._cursors.items():
            if name == self.name:
                continue
            pos = self.replica.position(anchor)
            if pos is not None:
                out[name] = pos
        return out

    @property
    def pending_sync(self):
        return bool(self.outbox)

    @property
    def can_redo(self):
        return bool(self._redo)

    @property
    def history(self):
        out = []
        for i in range(self._have()):
            op = self.entries[i]
            if op["hist"] is not None:
                out.append(Version(op["author"], op["hist"]))
        return out

    def view_version(self, index):
        self._require("read")
        return self.history[index].text

    # ------------------------------------------------------------ édition

    def move_cursor(self, pos):
        vis = self.replica.visible()
        self._anchor = vis[pos].ts if pos < len(vis) else END
        self._cseq += 1
        if self.connected:
            self._send(("cursor", self, self._anchor, self._cseq))

    def insert(self, pos, text):
        self._require("write")
        if not text:
            return
        vis = self.replica.visible()
        origin = vis[pos - 1].ts if pos > 0 else None
        prims, ids = self._chain(origin, text)
        self._redo.clear()
        self._commit(prims)
        self._undo.append([("hide", ids)])

    def delete(self, pos, length):
        self._require("write")
        vis = self.replica.visible()
        ids = [e.ts for e in vis[pos:pos + length]]
        if not ids:
            return
        self._redo.clear()
        self._commit([("hide", ts) for ts in ids])
        self._undo.append([("show", ids)])

    def save_version(self):
        self._require("write")
        self._commit([], hist=self.content)

    def restore_version(self, index):
        self._require("write")
        text = self.history[index].text
        vis_ids = [e.ts for e in self.replica.visible()]
        ins, new_ids = self._chain(None, text)
        self._redo.clear()
        self._commit([("hide", ts) for ts in vis_ids] + ins, hist=text)
        self._undo.append([("show", vis_ids), ("hide", new_ids)])

    def undo(self):
        self._require("write")
        if self._undo:
            effects = self._undo.pop()
            self._redo.append(_opposite(effects))
            self._play(effects)

    def redo(self):
        self._require("write")
        if self._redo:
            effects = self._redo.pop()
            self._undo.append(_opposite(effects))
            self._play(effects)

    # ------------------------------------------------------------ connexion

    def disconnect(self):
        if self.connected:
            self.connected = False
            self.server.session_lost(self)

    def reconnect(self):
        if not self.connected:
            self.connected = True
            self._send_sync()

    def close(self):
        self.disconnect()
