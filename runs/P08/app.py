"""Éditeur collaboratif simulé en mémoire (séquence RGA + journal serveur)."""

from dataclasses import dataclass
import itertools

WRITERS = ("owner", "write")
TEXT_OPS = ("ins", "del", "undel")


@dataclass
class Version:
    id: str
    author: str
    text: str


class _Doc:
    def __init__(self, owner):
        self.owner = owner
        self.perms = {owner: "owner"}
        self.log = []
        self.versions = []
        self.clients = []


class Server:
    def __init__(self):
        self._docs = {}
        self._doc_seq = itertools.count(1)
        self._site_seq = itertools.count(1)
        self._ver_seq = itertools.count(1)

    def create_document(self, owner):
        doc_id = f"doc{next(self._doc_seq)}"
        self._docs[doc_id] = _Doc(owner)
        return doc_id

    def open(self, doc_id, user):
        doc = self._docs[doc_id]
        client = Client(self, doc, user, next(self._site_seq))
        doc.clients.append(client)
        doc.log.append(("join", user))
        return client

    def sync(self):
        for doc in self._docs.values():
            for c in doc.clients:
                if c.online and not c.closed:
                    while c._idx < len(doc.log):
                        op = doc.log[c._idx]
                        c._idx += 1
                        c._apply(op)

    # --- appelé par les clients
    def _receive(self, doc, user, ops):
        level = doc.perms.get(user, "read")
        for op in ops:
            if op[0] in TEXT_OPS and level not in WRITERS:
                continue
            doc.log.append(op)

    def _set_perm(self, doc, actor, name, level):
        if doc.perms.get(actor) != "owner":
            return
        if name == doc.owner or level not in ("write", "read"):
            return
        doc.perms[name] = level
        doc.log.append(("perm", name, level))

    def _add_version(self, doc, author, text):
        if doc.perms.get(author, "read") not in WRITERS:
            return
        doc.versions.append(Version(f"v{next(self._ver_seq)}", author, text))


class Client:
    def __init__(self, server, doc, user, site):
        self._server = server
        self._doc = doc
        self.user = user
        self._site = site
        self.online = True
        self.closed = False
        self._idx = 0
        self._outbox = []
        self._seq = []  # éléments [id, caractère, supprimé]
        self._clock = 0
        self._undo = []
        self._presence = set()
        self._cursors = {}
        self._perms = dict(doc.perms)
        self._perms.setdefault(user, "read")

    # ---------------------------------------------------------- réplique
    def _index_of(self, eid):
        for i, e in enumerate(self._seq):
            if e[0] == eid:
                return i
        return -1

    def _visible(self):
        return [e for e in self._seq if not e[2]]

    def _apply(self, op):
        kind = op[0]
        if kind == "ins":
            _, eid, left, ch = op
            if self._index_of(eid) >= 0:
                return
            if left is None:
                start = 0
            else:
                li = self._index_of(left)
                if li < 0:
                    return
                start = li + 1
            while start < len(self._seq) and self._seq[start][0] > eid:
                start += 1
            self._seq.insert(start, [eid, ch, False])
            self._clock = max(self._clock, eid[0])
        elif kind == "del":
            i = self._index_of(op[1])
            if i >= 0:
                self._seq[i][2] = True
        elif kind == "undel":
            i = self._index_of(op[1])
            if i >= 0:
                self._seq[i][2] = False
        elif kind == "cursor":
            self._cursors[op[1]] = op[2]
        elif kind == "join":
            self._presence.add(op[1])
        elif kind == "leave":
            self._presence.discard(op[1])
            self._cursors.pop(op[1], None)
        elif kind == "perm":
            self._perms[op[1]] = op[2]

    def _submit(self, ops):
        for op in ops:
            self._apply(op)
        if self.online:
            self._server._receive(self._doc, self.user, ops)
        else:
            self._outbox.extend(ops)

    def _can_write(self):
        return (not self.closed) and self._perms.get(self.user) in WRITERS

    # ---------------------------------------------------------- texte
    @property
    def text(self):
        return "".join(e[1] for e in self._seq if not e[2])

    def _make_insert(self, position, string):
        vis = self._visible()
        position = max(0, min(position, len(vis)))
        left = vis[position - 1][0] if position > 0 else None
        ops = []
        ids = []
        for ch in string:
            self._clock += 1
            eid = (self._clock, self._site)
            ops.append(("ins", eid, left, ch))
            ids.append(eid)
            left = eid
        return ops, ids

    def insert(self, position, string):
        if not self._can_write() or not string:
            return
        ops, ids = self._make_insert(position, string)
        self._submit(ops)
        self._undo.append(("ins", ids))

    def delete(self, position, length):
        if not self._can_write():
            return
        vis = self._visible()
        position = max(0, position)
        ids = [e[0] for e in vis[position:position + max(0, length)]]
        if not ids:
            return
        self._submit([("del", i) for i in ids])
        self._undo.append(("del", ids))

    def undo(self):
        if not self._can_write() or not self._undo:
            return
        kind, ids = self._undo.pop()
        ops = []
        for i in ids:
            idx = self._index_of(i)
            if idx < 0:
                continue
            deleted = self._seq[idx][2]
            if kind == "ins" and not deleted:
                ops.append(("del", i))
            elif kind == "del" and deleted:
                ops.append(("undel", i))
        if ops:
            self._submit(ops)

    def undo_count(self):
        return len(self._undo)

    # ---------------------------------------------------------- connexion
    def go_offline(self):
        if self.closed or not self.online:
            return
        self.online = False
        self._doc.log.append(("leave", self.user))

    def go_online(self):
        if self.closed or self.online:
            return
        self.online = True
        self._doc.log.append(("join", self.user))
        ops, self._outbox = self._outbox, []
        if ops:
            self._server._receive(self._doc, self.user, ops)

    def close(self):
        if self.closed:
            return
        if self.online:
            self._doc.log.append(("leave", self.user))
        self.closed = True
        self.online = False
        if self in self._doc.clients:
            self._doc.clients.remove(self)

    # ---------------------------------------------------------- présence
    def presence(self):
        return set(self._presence)

    def move_cursor(self, position):
        if self.closed:
            return
        vis = self._visible()
        position = max(0, min(position, len(vis)))
        left = vis[position - 1][0] if position > 0 else None
        self._submit([("cursor", self.user, left)])

    def cursors(self):
        result = {}
        for user, left in self._cursors.items():
            if user == self.user:
                continue
            if left is None:
                result[user] = 0
                continue
            idx = self._index_of(left)
            if idx < 0:
                continue
            result[user] = sum(1 for e in self._seq[:idx + 1] if not e[2])
        return result

    # ---------------------------------------------------------- versions
    def versions(self):
        return list(self._doc.versions)

    def save_version(self):
        if not self._can_write():
            return
        self._server._add_version(self._doc, self.user, self.text)

    def _find_version(self, version_id):
        for v in self._doc.versions:
            if v.id == version_id:
                return v
        raise KeyError(version_id)

    def view_version(self, version_id):
        return self._find_version(version_id).text

    def restore_version(self, version_id):
        if not self._can_write():
            return
        version = self._find_version(version_id)
        ops = [("del", e[0]) for e in self._visible()]
        ins_ops, _ = self._make_insert(0, version.text)
        self._submit(ops + ins_ops)
        self._server._add_version(self._doc, self.user, version.text)

    # ---------------------------------------------------------- permissions
    def set_permission(self, name, level):
        if self.closed or not self.online:
            return
        if self._perms.get(self.user) != "owner":
            return
        self._server._set_perm(self._doc, self.user, name, level)
        if name != self._doc.owner and level in ("write", "read"):
            self._perms[name] = level

    def permission_of(self, name):
        return self._perms.get(name)
