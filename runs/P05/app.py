class Refused(Exception):
    pass


class User:
    def __init__(self, name, role):
        self.name = name
        self.role = role


VISITOR = User("visitor", "visitor")


class _Article:
    def __init__(self, author, text):
        self.author = author
        self.text = text
        self.status = "draft"
        self.at = None
        self.pub_key = None
        self.tags = []
        self.open = False
        self.comments = []


class Blog:
    def __init__(self):
        self.now = 0
        self._articles = {}
        self._comments = {}
        self._seq = 0

    def _next(self):
        self._seq += 1
        return self._seq

    def advance(self, delta):
        self.now += delta
        due = [a for a in self._articles.values()
               if a.status == "scheduled" and a.at <= self.now]
        for a in sorted(due, key=lambda x: x.at):
            self._set_published(a, a.at)

    def _set_published(self, a, when):
        a.status = "published"
        a.at = None
        a.pub_key = (when, self._next())

    def add_author(self, name):
        return User(name, "author")

    def add_moderator(self, name):
        return User(name, "moderator")

    def _owned(self, user, aid):
        a = self._articles[aid]
        if a.author is not user:
            raise Refused("not the owner")
        return a

    def create_article(self, author, text):
        if author.role != "author":
            raise Refused("only authors create")
        aid = self._next()
        self._articles[aid] = _Article(author, text)
        return aid

    def status(self, aid):
        return self._articles[aid].status

    def is_visible(self, aid, viewer):
        a = self._articles[aid]
        return a.status == "published" or a.author is viewer

    def content(self, aid):
        return self._articles[aid].text

    def publish(self, user, aid):
        a = self._owned(user, aid)
        if a.status != "draft":
            raise Refused("not a draft")
        self._set_published(a, self.now)

    def schedule(self, user, aid, at):
        a = self._owned(user, aid)
        if a.status != "draft":
            raise Refused("not a draft")
        if at <= self.now:
            raise Refused("date not in the future")
        a.status = "scheduled"
        a.at = at

    def unschedule(self, user, aid):
        a = self._owned(user, aid)
        if a.status != "scheduled":
            raise Refused("not scheduled")
        a.status = "draft"
        a.at = None

    def unpublish(self, user, aid):
        a = self._owned(user, aid)
        if a.status != "published":
            raise Refused("not published")
        a.status = "draft"
        a.pub_key = None

    def edit(self, user, aid, text):
        self._owned(user, aid).text = text

    def add_tag(self, user, aid, tag):
        a = self._owned(user, aid)
        if tag not in a.tags:
            a.tags.append(tag)

    def remove_tag(self, user, aid, tag):
        a = self._owned(user, aid)
        if tag in a.tags:
            a.tags.remove(tag)

    def tags(self, aid):
        return list(self._articles[aid].tags)

    def feed(self):
        pub = [(a.pub_key, aid) for aid, a in self._articles.items()
               if a.status == "published"]
        return [aid for _, aid in sorted(pub, reverse=True)]

    def tag_list(self, tag):
        return [aid for aid in self.feed() if tag in self._articles[aid].tags]

    def open_comments(self, user, aid):
        self._owned(user, aid).open = True

    def close_comments(self, user, aid):
        self._owned(user, aid).open = False

    def comments_open(self, aid):
        return self._articles[aid].open

    def comment(self, user, aid, text):
        a = self._articles[aid]
        if a.status != "published" or not a.open:
            raise Refused("cannot comment")
        cid = self._next()
        self._comments[cid] = {"article": a, "text": text, "mod": "pending"}
        a.comments.append(cid)
        return cid

    def comments(self, aid):
        return list(self._articles[aid].comments)

    def displayed_comments(self, aid, viewer):
        a = self._articles[aid]
        if a.status != "published":
            return []
        is_mod = viewer.role == "moderator"
        return [c for c in a.comments
                if self._comments[c]["mod"] == "approved"
                or (is_mod and self._comments[c]["mod"] == "pending")]

    def moderation(self, cid):
        return self._comments[cid]["mod"]

    def approve(self, user, cid):
        self._moderate(user, cid, "approved")

    def reject(self, user, cid):
        self._moderate(user, cid, "rejected")

    def _moderate(self, user, cid, state):
        if user.role != "moderator":
            raise Refused("moderators only")
        c = self._comments[cid]
        if c["mod"] != "pending":
            raise Refused("not pending")
        c["mod"] = state
