"""Synchronisation hors ligne de notes entre appareils (réseau simulé en mémoire).

Modèle :
- le serveur du compte et chaque appareil ont chacun leur propre copie des notes ;
- un appareil applique ses modifications localement (« boîte d'envoi » : opérations
  non acquittées) et les envoie au serveur quand il est en ligne avec session ouverte ;
- chaque opération ne modifie que les champs qu'elle concerne (titre, texte, suppression) ;
- le serveur numérote les versions d'une note (une par écriture acceptée) et retient
  quel appareil a écrit chaque version, et si elle a modifié le texte. Une modification
  de texte est en conflit si un autre appareil a modifié le texte après la version
  que l'appareil connaissait et si le texte diffère ;
- les appareils rattrapent leur retard en demandant l'état du compte (boucle de
  rattrapage du réseau, qui s'arrête quand plus rien ne bouge).
"""

import copy
import random


OFFLINE_STATUS = "hors ligne"
ONLINE_STATUS = "en ligne"
PENDING = "en attente"
SYNCED = "synchronisée"
SERVER = "server"
CONFLICT_SUFFIX = " (copie de conflit)"
MAX_ROUNDS = 200

# champs qu'écrit chaque type d'opération
FIELDS = {
    "create": ("title", "text"),
    "title": ("title",),
    "text": ("text",),
    "resolve": ("text",),
    "delete": (),
}


class Clock:
    """Horloge propre à un appareil."""

    def __init__(self, start=0.0):
        self._now = float(start)

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += float(seconds)


class Network:
    """Réseau simulé : les messages restent en transit jusqu'à livraison."""

    def __init__(self):
        self._nodes = {}
        self._queue = []

    def attach(self, node):
        self._nodes[node.name] = node

    def send(self, src, dst, payload):
        self._queue.append((src, dst, payload))

    def in_flight(self):
        return len(self._queue)

    def deliver(self, i=0):
        src, dst, payload = self._queue.pop(i)
        node = self._nodes.get(dst)
        if node is not None and node.is_online():
            node.receive(src, payload)

    def lose(self, i=0):
        self._queue.pop(i)

    def duplicate(self, i=0):
        self._queue.append(self._queue[i])

    def drop_for(self, name):
        self._queue = [m for m in self._queue if name not in (m[0], m[1])]

    def run(self, seed=None):
        rng = None if seed is None else random.Random(seed)
        self._drain(rng)
        for _ in range(MAX_ROUNDS):
            before = self._state()
            for node in list(self._nodes.values()):
                if hasattr(node, "catch_up"):
                    node.catch_up()
            self._drain(rng)
            if self._state() == before:
                return

    def _drain(self, rng):
        while self._queue:
            i = 0 if rng is None else rng.randrange(len(self._queue))
            self.deliver(i)

    def _state(self):
        return {name: node.state() for name, node in self._nodes.items()}


# --------------------------------------------------------------------------- serveur


class Server:
    """Serveur du compte : sa propre copie, nœud du réseau."""

    def __init__(self, net):
        self.name = SERVER
        self.net = net
        self.accounts = {}  # compte -> {nid: note}
        self.seqs = {}      # (compte, appareil, nid) -> dernier numéro d'opération appliqué
        net.attach(self)

    def is_online(self):
        return True

    def state(self):
        return copy.deepcopy({"accounts": self.accounts, "seqs": self.seqs})

    def receive(self, src, payload):
        account = payload["account"]
        notes = self.accounts.setdefault(account, {})
        if payload["type"] == "op":
            op = payload["op"]
            self._apply(account, notes, src, op)
            nid = op["note"]
            snap = _snap(nid, notes[nid]) if nid in notes else None
            self.net.send(self.name, src, {"type": "ack", "seq": op["seq"], "note": snap})
        else:
            snaps = [_snap(nid, e) for nid, e in notes.items()]
            self.net.send(self.name, src, {"type": "state", "notes": snaps})

    def _apply(self, account, notes, dev, op):
        nid, seq, base, kind = op["note"], op["seq"], op["base"], op["kind"]
        key = (account, dev, nid)
        if seq <= self.seqs.get(key, 0):
            return  # déjà appliqué, ou remplacé par une opération plus récente
        self.seqs[key] = seq
        e = notes.get(nid)
        if kind == "resolve":
            if e is not None and not e["deleted"]:
                _write(e, op, dev)
                e["conflict"] = False
        elif kind == "delete":
            if e is None:
                notes[nid] = _new(op, dev, deleted=True)
            elif not e["deleted"] and not _foreign_after(e, base, dev):
                _write(e, op, dev)
                e["deleted"] = True
            # sinon : la modification de l'autre appareil l'emporte sur la suppression
        elif e is None:
            notes[nid] = _new(op, dev, deleted=False)
        elif e["deleted"]:
            _write(e, op, dev)  # une modification fait revivre la note
            e["deleted"] = False
            e["conflict"] = False
        elif kind == "text" and op["text"] != e["text"] and _foreign_text_after(e, base, dev):
            _conflict(notes, nid, e, op, dev, seq)
        else:
            _write(e, op, dev)


def _new(op, dev, deleted):
    return {
        "title": op["title"], "text": op["text"], "mtime": op["mtime"],
        "deleted": deleted, "conflict": False,
        "writers": [(dev, not deleted)], "last": dev,
    }


def _write(e, op, dev):
    """N'écrit que les champs de l'opération."""
    fields = FIELDS[op["kind"]]
    for f in fields:
        e[f] = op[f]
    e["mtime"] = op["mtime"]
    e["writers"].append((dev, "text" in fields))
    e["last"] = dev


def _foreign_after(e, base, dev):
    """Vrai si un autre appareil a écrit après la version `base` connue de `dev`."""
    return any(w != dev for w, _ in e["writers"][base:])


def _foreign_text_after(e, base, dev):
    """Vrai si un autre appareil a modifié le texte après la version `base`."""
    return any(w != dev and text for w, text in e["writers"][base:])


def _conflict(notes, nid, e, op, dev, seq):
    """Deux modifications de texte concurrentes : la plus récente (heure des appareils)
    reste sur la note d'origine, l'autre devient une copie de conflit."""
    if (op["mtime"], dev) > (e["mtime"], e["last"]):
        loser_text, loser_mtime = e["text"], e["mtime"]
        _write(e, op, dev)
    else:
        loser_text, loser_mtime = op["text"], op["mtime"]
        e["writers"].append((dev, True))
    e["conflict"] = True
    notes[f"{nid}~{dev}{seq}"] = {
        "title": e["title"] + CONFLICT_SUFFIX, "text": loser_text, "mtime": loser_mtime,
        "deleted": False, "conflict": False, "writers": [(dev, True)], "last": dev,
    }


def _snap(nid, e):
    return {
        "id": nid, "title": e["title"], "text": e["text"], "mtime": e["mtime"],
        "deleted": e["deleted"], "conflict": e["conflict"], "version": len(e["writers"]),
    }


# --------------------------------------------------------------------------- appareil


class Device:
    """Appareil : copie locale des notes, travaille hors ligne."""

    def __init__(self, name, net, clock):
        self.name = name
        self.net = net
        self.clock = clock
        self.online = True
        self.app_open = True
        self.session = None
        self.base = {}    # nid -> dernier état connu du serveur
        self.outbox = []  # modifications locales non acquittées, dans l'ordre
        self.touch = {}   # nid -> rang de la dernière modification de contenu
        self._tick = 0
        self._seq = 0
        self._created = 0
        net.attach(self)

    # ----- réseau, session, application

    def is_online(self):
        return self.online

    def state(self):
        return copy.deepcopy({
            "online": self.online, "session": self.session, "app": self.app_open,
            "base": self.base, "outbox": self.outbox, "touch": self.touch,
            "tick": self._tick, "seq": self._seq,
        })

    def status(self):
        return ONLINE_STATUS if self.online else OFFLINE_STATUS

    def go_offline(self):
        self.online = False
        self.net.drop_for(self.name)

    def go_online(self):
        self.online = True
        self._send_outbox()

    def open_session(self, account):
        self.session = account
        self._send_outbox()

    def close_session(self):
        self.session = None

    def close_app(self):
        self.app_open = False

    def open_app(self):
        self.app_open = True
        self._send_outbox()

    def catch_up(self):
        """Appelé par le réseau quand la file est vide : réémet ce qui n'est pas
        acquitté et demande l'état du compte."""
        if not self._connected():
            return
        self._send_outbox()
        self.net.send(self.name, SERVER, {"type": "pull", "account": self.session})

    def _connected(self):
        return self.online and self.session is not None

    def _send_outbox(self):
        if not self._connected():
            return
        for op in self.outbox:
            self.net.send(self.name, SERVER, {"type": "op", "account": self.session, "op": dict(op)})

    def receive(self, src, payload):
        if payload["type"] == "ack":
            def apply():
                self.outbox = [op for op in self.outbox if op["seq"] != payload["seq"]]
                if payload["note"] is not None:
                    self._merge(payload["note"])
        else:
            def apply():
                for snap in payload["notes"]:
                    self._merge(snap)
        self._with_touch(apply)

    # ----- API utilisateur

    def create_note(self, title, text):
        self._created += 1
        nid = f"{self.name}{self._created}"
        self._local(self._op("create", nid, title, text))
        return nid

    def edit_text(self, nid, text):
        v = self._require(nid)
        self._local(self._op("text", nid, v["title"], text))

    def edit_title(self, nid, title):
        v = self._require(nid)
        self._local(self._op("title", nid, title, v["text"]))

    def delete_note(self, nid):
        v = self._require(nid)
        self._local(self._op("delete", nid, v["title"], v["text"]))

    def resolve_conflict(self, nid, text):
        v = self._require(nid)
        self._local(self._op("resolve", nid, v["title"], text))

    def list_notes(self):
        notes = [self._public(nid) for nid in self._known_ids()]
        notes = [n for n in notes if n is not None]
        notes.sort(key=lambda n: self.touch.get(n["id"], 0), reverse=True)
        return notes

    def note(self, nid):
        return self._public(nid)

    def has_conflict(self, nid):
        v = self._view(nid)
        return v["present"] and v["conflict"]

    # ----- interne

    def _op(self, kind, nid, title, text):
        self._seq += 1
        base = self.base[nid]["version"] if nid in self.base else 0
        return {
            "seq": self._seq, "note": nid, "kind": kind, "title": title, "text": text,
            "mtime": self.clock.now(), "base": base,
        }

    def _local(self, op):
        self._with_touch(lambda: self.outbox.append(op))
        self._send_outbox()

    def _require(self, nid):
        v = self._view(nid)
        if not v["present"]:
            raise KeyError(nid)
        return v

    def _known_ids(self):
        return list(dict.fromkeys(list(self.base) + [op["note"] for op in self.outbox]))

    def _merge(self, snap):
        cur = self.base.get(snap["id"])
        if cur is None or snap["version"] > cur["version"]:
            self.base[snap["id"]] = dict(snap)

    def _view(self, nid):
        """État affiché : dernier état serveur, recouvert par les opérations locales."""
        b = self.base.get(nid)
        present = b is not None and not b["deleted"]
        title = b["title"] if b is not None else None
        text = b["text"] if b is not None else None
        conflict = b is not None and b["conflict"]
        pending = False
        for op in self.outbox:
            if op["note"] != nid:
                continue
            pending = True
            kind = op["kind"]
            if kind == "delete":
                present = False
            elif kind == "resolve":
                text, conflict = op["text"], False
            else:
                present = True
                if kind in ("create", "title"):
                    title = op["title"]
                if kind in ("create", "text"):
                    text = op["text"]
        return {"present": present, "title": title, "text": text,
                "conflict": conflict, "pending": pending}

    def _public(self, nid):
        v = self._view(nid)
        if not v["present"]:
            return None
        return {
            "id": nid, "title": v["title"], "text": v["text"],
            "indicator": PENDING if v["pending"] else SYNCED,
        }

    def _content(self, nid):
        v = self._view(nid)
        return (v["title"], v["text"]) if v["present"] else None

    def _with_touch(self, change):
        """Applique `change` et fait passer en tête les notes dont le contenu affiché a changé."""
        before_ids = self._known_ids()
        before = {n: self._content(n) for n in before_ids}
        change()
        for n in list(dict.fromkeys(before_ids + self._known_ids())):
            if self._content(n) != before.get(n):
                self._tick += 1
                self.touch[n] = self._tick
