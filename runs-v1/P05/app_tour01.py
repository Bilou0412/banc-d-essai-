"""Blog minimal (A01..A38). Tout ce qui dépend du temps passe par `Clock`."""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime


class Refused(Exception):
    """Action refusée (droits, propriété, date invalide, état invalide)."""


class Clock:
    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


class User:
    def __init__(self, uid: int, name: str, roles):
        self.id = uid
        self.name = name
        self.roles = frozenset(roles)

    def has(self, role: str) -> bool:
        return role in self.roles


class _Post:
    def __init__(self, pid: int, owner_id: int, title: str, content: str):
        self.id = pid
        self.owner_id = owner_id
        self.title = title
        self.content = content
        self.status = "brouillon"
        self.published_at = None
        self.scheduled_at = None
        self.tags = []


class _Comment:
    def __init__(self, cid: int, post_id: int, author: str, text: str):
        self.id = cid
        self.post_id = post_id
        self.author = author
        self.text = text
        self.moderation = "en attente"


class Blog:
    def __init__(self, clock: Clock):
        self._clock = clock
        self._next_user = 1
        self._next_post = 1
        self._next_comment = 1
        self._posts = {}
        self._comments = {}

    # ------------------------------------------------------------ temps
    def _tick(self) -> None:
        """Applique les échéances de planification atteintes à l'instant courant.

        La date de publication est la date planifiée, jamais l'instant de l'observation.
        """
        now = self._clock.now()
        for post in self._posts.values():
            if post.status == "planifié" and now >= post.scheduled_at:
                post.status = "publié"
                post.published_at = post.scheduled_at
                post.scheduled_at = None

    # ------------------------------------------------------------ utilisateurs
    def register(self, name: str, *roles: str) -> User:
        user = User(self._next_user, name, roles)
        self._next_user += 1
        return user

    @staticmethod
    def _owned(user: User, post: _Post) -> None:
        if post.owner_id != user.id:
            raise Refused("l'utilisateur n'est pas propriétaire de l'article")

    # ------------------------------------------------------------ articles
    def create_post(self, user: User, title: str, content: str) -> int:
        self._tick()
        if not user.has("auteur"):
            raise Refused("rôle auteur requis pour créer un article")
        pid = self._next_post
        self._next_post += 1
        self._posts[pid] = _Post(pid, user.id, title, content)
        return pid

    def status(self, pid: int) -> str:
        self._tick()
        return self._posts[pid].status

    def publish(self, user: User, pid: int) -> None:
        self._tick()
        post = self._posts[pid]
        self._owned(user, post)
        if post.status != "brouillon":
            raise Refused("seul un brouillon peut être publié")
        post.status = "publié"
        post.published_at = self._clock.now()

    def schedule(self, user: User, pid: int, when: datetime) -> None:
        self._tick()
        post = self._posts[pid]
        self._owned(user, post)
        if post.status != "brouillon":
            raise Refused("seul un brouillon peut être planifié")
        if when <= self._clock.now():
            raise Refused("la date planifiée doit être dans le futur")
        post.status = "planifié"
        post.scheduled_at = when

    def unschedule(self, user: User, pid: int) -> None:
        self._tick()
        post = self._posts[pid]
        self._owned(user, post)
        if post.status != "planifié":
            raise Refused("l'article n'est pas planifié")
        post.status = "brouillon"
        post.scheduled_at = None

    def unpublish(self, user: User, pid: int) -> None:
        self._tick()
        post = self._posts[pid]
        self._owned(user, post)
        if post.status != "publié":
            raise Refused("l'article n'est pas publié")
        post.status = "brouillon"
        post.published_at = None

    def edit(self, user: User, pid: int, content: str) -> None:
        self._tick()
        post = self._posts[pid]
        self._owned(user, post)
        post.content = content

    def content(self, pid: int) -> str:
        self._tick()
        return self._posts[pid].content

    def publication_date(self, pid: int):
        self._tick()
        return self._posts[pid].published_at

    def _published(self) -> list:
        self._tick()
        return [p for p in self._posts.values() if p.status == "publié"]

    def visible_posts(self) -> list:
        return sorted(p.id for p in self._published())

    # ------------------------------------------------------------ flux RSS
    def rss(self) -> str:
        posts = sorted(self._published(), key=lambda p: (p.published_at, p.id), reverse=True)
        root = ET.Element("rss", version="2.0")
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = "Blog"
        ET.SubElement(channel, "link").text = "/"
        ET.SubElement(channel, "description").text = "Blog"
        for p in posts:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = p.title
            ET.SubElement(item, "description").text = p.content
            ET.SubElement(item, "guid").text = str(p.id)
            ET.SubElement(item, "pubDate").text = format_datetime(
                p.published_at.astimezone(timezone.utc), usegmt=True
            )
        return ET.tostring(root, encoding="unicode")

    # ------------------------------------------------------------ tags
    def add_tag(self, user: User, pid: int, tag: str) -> None:
        self._tick()
        post = self._posts[pid]
        self._owned(user, post)
        if tag not in post.tags:
            post.tags.append(tag)

    def remove_tag(self, user: User, pid: int, tag: str) -> None:
        self._tick()
        post = self._posts[pid]
        self._owned(user, post)
        if tag in post.tags:
            post.tags.remove(tag)

    def tags(self, pid: int) -> list:
        self._tick()
        return list(self._posts[pid].tags)

    def tag_page(self, tag: str) -> list:
        self._tick()
        return sorted(p.id for p in self._posts.values() if p.status == "publié" and tag in p.tags)

    # ------------------------------------------------------------ commentaires
    def comment(self, pid: int, author_name: str, text: str) -> int:
        self._tick()
        post = self._posts[pid]
        if post.status != "publié":
            raise Refused("commentaires uniquement sur un article publié")
        cid = self._next_comment
        self._next_comment += 1
        self._comments[cid] = _Comment(cid, pid, author_name, text)
        return cid

    def moderation(self, cid: int) -> str:
        return self._comments[cid].moderation

    def approve(self, user: User, cid: int) -> None:
        if not user.has("moderateur"):
            raise Refused("rôle modérateur requis")
        comment = self._comments[cid]
        if comment.moderation != "en attente":
            raise Refused("seul un commentaire en attente peut être approuvé")
        comment.moderation = "approuvé"

    def reject(self, user: User, cid: int) -> None:
        if not user.has("moderateur"):
            raise Refused("rôle modérateur requis")
        comment = self._comments[cid]
        if comment.moderation != "en attente":
            raise Refused("seul un commentaire en attente peut être rejeté")
        comment.moderation = "rejeté"

    def displayed_comments(self, pid: int) -> list:
        self._tick()
        if self._posts[pid].status != "publié":
            return []
        return sorted(
            c.id for c in self._comments.values()
            if c.post_id == pid and c.moderation == "approuvé"
        )

    def comment_count(self, pid: int) -> int:
        return sum(
            1 for c in self._comments.values()
            if c.post_id == pid and c.moderation == "approuvé"
        )
