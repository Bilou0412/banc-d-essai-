"""Red tests — code layer.

Public interface fixed by these tests (module `app`):

    blog = app.Blog()                     # simulated system, clock starts at blog.now == 0
    blog.now                              # int, current simulated time
    blog.advance(delta)                   # moves the clock forward by `delta` (int > 0)

    alice = blog.add_author("alice")      # returns a user handle
    mod   = blog.add_moderator("mod")     # returns a user handle (not an author)
    app.VISITOR                           # the anonymous visitor

    aid = blog.create_article(author, text)          -> article id
    blog.status(aid)                                 -> "draft" | "scheduled" | "published"
    blog.is_visible(aid, viewer)                     -> bool
    blog.content(aid)                                -> displayed text (str)
    blog.publish(user, aid)
    blog.schedule(user, aid, at)                     # at: int, absolute simulated time
    blog.unschedule(user, aid)
    blog.unpublish(user, aid)                        # back to draft
    blog.edit(user, aid, text)
    blog.add_tag(user, aid, tag) / blog.remove_tag(user, aid, tag)
    blog.tags(aid)                                   -> collection of str
    blog.tag_list(tag)                               -> list of article ids (public view)
    blog.feed()                                      -> list of article ids (public view)
    blog.open_comments(user, aid) / blog.close_comments(user, aid)
    blog.comments_open(aid)                          -> bool
    cid = blog.comment(user, aid, text)              -> comment id
    blog.comments(aid)                               -> list of ALL comment ids created on aid
    blog.displayed_comments(aid, viewer)             -> list of comment ids displayed to viewer
    blog.moderation(cid)                             -> "pending" | "approved" | "rejected"
    blog.approve(user, cid) / blog.reject(user, cid)

Any refused operation either raises `app.Refused` or silently does nothing;
the tests accept both and only check the observable state afterwards.
"""

import pytest

import app


# ---------------------------------------------------------------- helpers

def attempt(fn, *args):
    """Run an operation that the spec says must be refused.
    Raising app.Refused is accepted; any other exception is a bug."""
    try:
        return fn(*args)
    except app.Refused:
        return None


@pytest.fixture
def blog():
    return app.Blog()


@pytest.fixture
def alice(blog):
    return blog.add_author("alice")


@pytest.fixture
def bob(blog):
    return blog.add_author("bob")


@pytest.fixture
def mod(blog):
    return blog.add_moderator("mod")


def published(blog, author, text="hello"):
    aid = blog.create_article(author, text)
    blog.publish(author, aid)
    assert blog.status(aid) == "published", "setup: publish failed"
    return aid


def open_published(blog, author, text="hello"):
    aid = published(blog, author, text)
    blog.open_comments(author, aid)
    assert blog.comments_open(aid) is True, "setup: open_comments failed"
    return aid


def pending_comment(blog, author):
    aid = open_published(blog, author)
    cid = blog.comment(app.VISITOR, aid, "nice")
    assert blog.moderation(cid) == "pending", "setup: comment not pending"
    return aid, cid


# ---------------------------------------------------------------- A01

def test_A01_new_article_is_draft(blog, alice):
    aid = blog.create_article(alice, "hello")
    assert blog.status(aid) == "draft", f"expected 'draft', got {blog.status(aid)!r}"


def test_A01_new_article_is_draft_even_after_clock_moves(blog, alice):
    blog.advance(1000)
    aid = blog.create_article(alice, "hello")
    blog.advance(1000)
    assert blog.status(aid) == "draft", f"expected 'draft', got {blog.status(aid)!r}"


# ---------------------------------------------------------------- A02 / A03 / A04

def test_A02_draft_not_visible_to_visitor(blog, alice):
    aid = blog.create_article(alice, "hello")
    assert blog.is_visible(aid, app.VISITOR) is False, "draft must not be visible to a visitor"


def test_A03_draft_visible_to_its_author(blog, alice):
    aid = blog.create_article(alice, "hello")
    assert blog.is_visible(aid, alice) is True, "draft must be visible to its author"


def test_A04_draft_of_other_author_not_visible_to_author(blog, alice, bob):
    aid = blog.create_article(alice, "hello")
    assert blog.is_visible(aid, bob) is False, "bob must not see alice's draft"
    assert blog.is_visible(aid, alice) is True, "alice must still see her own draft"


# ---------------------------------------------------------------- A05 / A06 / A07

def test_A05_author_publishes_own_draft(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.publish(alice, aid)
    assert blog.status(aid) == "published", f"expected 'published', got {blog.status(aid)!r}"


def test_A06_author_cannot_publish_other_authors_draft(blog, alice, bob):
    aid = blog.create_article(alice, "hello")
    attempt(blog.publish, bob, aid)
    assert blog.status(aid) == "draft", f"expected 'draft', got {blog.status(aid)!r}"
    assert blog.is_visible(aid, app.VISITOR) is False, "refused publish leaked visibility"
    assert aid not in blog.feed(), "refused publish leaked into the feed"


def test_A07_published_visible_to_visitor(blog, alice):
    aid = published(blog, alice)
    assert blog.is_visible(aid, app.VISITOR) is True, "published article must be visible"


def test_A07_published_visible_to_other_author(blog, alice, bob):
    aid = published(blog, alice)
    assert blog.is_visible(aid, bob) is True, "published article must be visible to anyone"


# ---------------------------------------------------------------- A08 / A09 / A10 / A11

def test_A08_schedule_future_date_makes_scheduled(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    assert blog.status(aid) == "scheduled", f"expected 'scheduled', got {blog.status(aid)!r}"


def test_A08_schedule_one_tick_ahead_is_future(blog, alice):
    blog.advance(50)
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 1)
    assert blog.status(aid) == "scheduled", f"expected 'scheduled', got {blog.status(aid)!r}"


def test_A09_schedule_past_date_stays_draft(blog, alice):
    blog.advance(100)
    aid = blog.create_article(alice, "hello")
    attempt(blog.schedule, alice, aid, blog.now - 10)
    assert blog.status(aid) == "draft", f"expected 'draft', got {blog.status(aid)!r}"


def test_A09_schedule_past_date_never_publishes_later(blog, alice):
    blog.advance(100)
    aid = blog.create_article(alice, "hello")
    attempt(blog.schedule, alice, aid, blog.now - 1)
    blog.advance(1000)
    assert blog.status(aid) == "draft", f"expected 'draft' after time passes, got {blog.status(aid)!r}"
    assert blog.is_visible(aid, app.VISITOR) is False, "refused schedule leaked visibility"


def test_A10_scheduled_not_visible_before_date(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    blog.advance(9)
    assert blog.is_visible(aid, app.VISITOR) is False, "scheduled article visible one tick before its date"


def test_A11_clock_reaching_date_exactly_publishes(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    blog.advance(10)
    assert blog.status(aid) == "published", f"expected 'published' at the date, got {blog.status(aid)!r}"
    assert blog.is_visible(aid, app.VISITOR) is True, "article published by the clock must be visible"


def test_A11_clock_passing_date_publishes(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    blog.advance(500)
    assert blog.status(aid) == "published", f"expected 'published', got {blog.status(aid)!r}"


def test_A11_clock_in_small_steps_publishes(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 5)
    for _ in range(4):
        blog.advance(1)
        assert blog.status(aid) == "scheduled", "published before the date"
    blog.advance(1)
    assert blog.status(aid) == "published", f"expected 'published', got {blog.status(aid)!r}"


# ---------------------------------------------------------------- A12 / A13

def test_A12_unpublish_hides_from_visitor(blog, alice):
    aid = published(blog, alice)
    blog.unpublish(alice, aid)
    assert blog.is_visible(aid, app.VISITOR) is False, "unpublished article still visible"
    assert aid not in blog.feed(), "unpublished article still in feed"


def test_A13_unschedule_returns_to_draft(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    blog.unschedule(alice, aid)
    assert blog.status(aid) == "draft", f"expected 'draft', got {blog.status(aid)!r}"


def test_A13_unscheduled_article_not_published_when_old_date_reached(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    blog.unschedule(alice, aid)
    blog.advance(20)
    assert blog.status(aid) == "draft", f"cancelled schedule still fired: {blog.status(aid)!r}"
    assert blog.is_visible(aid, app.VISITOR) is False, "cancelled schedule made article visible"


# ---------------------------------------------------------------- A14 / A15

def test_A14_author_edit_changes_displayed_content(blog, alice):
    aid = blog.create_article(alice, "old text")
    blog.edit(alice, aid, "new text")
    assert blog.content(aid) == "new text", f"expected 'new text', got {blog.content(aid)!r}"


def test_A14_author_edit_published_article_non_ascii(blog, alice):
    aid = published(blog, alice, "old")
    blog.edit(alice, aid, "Été — 東京 ✓\r\nligne 2")
    assert blog.content(aid) == "Été — 東京 ✓\r\nligne 2", f"got {blog.content(aid)!r}"


def test_A15_moderator_edit_of_others_article_is_ignored(blog, alice, mod):
    aid = published(blog, alice, "original")
    attempt(blog.edit, mod, aid, "tampered")
    assert blog.content(aid) == "original", f"expected 'original', got {blog.content(aid)!r}"


# ---------------------------------------------------------------- A16 / A17 / A18 / A19

def test_A16_author_adds_tag(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.add_tag(alice, aid, "python")
    assert "python" in blog.tags(aid), f"'python' missing from {list(blog.tags(aid))!r}"


def test_A17_author_removes_tag(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.add_tag(alice, aid, "python")
    blog.add_tag(alice, aid, "rust")
    blog.remove_tag(alice, aid, "python")
    assert "python" not in blog.tags(aid), f"'python' still in {list(blog.tags(aid))!r}"
    assert "rust" in blog.tags(aid), "removing one tag removed another"


def test_A18_published_tagged_article_in_tag_list(blog, alice):
    aid = published(blog, alice)
    blog.add_tag(alice, aid, "python")
    assert aid in blog.tag_list("python"), f"article missing from tag list {blog.tag_list('python')!r}"


def test_A18_tag_list_only_lists_that_tag(blog, alice):
    a = published(blog, alice)
    b = published(blog, alice)
    blog.add_tag(alice, a, "python")
    blog.add_tag(alice, b, "rust")
    assert a in blog.tag_list("python") and b not in blog.tag_list("python"), \
        f"tag list for 'python' is {blog.tag_list('python')!r}"


def test_A18_A17_removed_tag_leaves_tag_list(blog, alice):
    aid = published(blog, alice)
    blog.add_tag(alice, aid, "python")
    blog.remove_tag(alice, aid, "python")
    assert aid not in blog.tag_list("python"), "article still listed under a removed tag"


def test_A19_draft_tagged_article_not_in_tag_list(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.add_tag(alice, aid, "python")
    assert aid not in blog.tag_list("python"), "draft leaked into tag list"


def test_A19_unpublished_tagged_article_leaves_tag_list(blog, alice):
    aid = published(blog, alice)
    blog.add_tag(alice, aid, "python")
    blog.unpublish(alice, aid)
    assert aid not in blog.tag_list("python"), "article back in draft still in tag list"


# ---------------------------------------------------------------- A20 / A21 / A22 / A23

def test_A20_published_in_feed(blog, alice):
    aid = published(blog, alice)
    assert aid in blog.feed(), f"published article missing from feed {blog.feed()!r}"


def test_A21_draft_not_in_feed(blog, alice):
    aid = blog.create_article(alice, "hello")
    assert aid not in blog.feed(), "draft in feed"


def test_A22_scheduled_not_in_feed_before_date(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    blog.advance(9)
    assert aid not in blog.feed(), "scheduled article in feed before its date"


def test_A22_scheduled_in_feed_once_date_reached(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.schedule(alice, aid, blog.now + 10)
    blog.advance(10)
    assert aid in blog.feed(), "scheduled article missing from feed once its date is reached"


def test_A23_feed_sorted_newest_first(blog, alice):
    first = published(blog, alice, "one")
    blog.advance(5)
    second = published(blog, alice, "two")
    blog.advance(5)
    third = published(blog, alice, "three")
    assert blog.feed() == [third, second, first], f"expected newest first, got {blog.feed()!r}"


def test_A23_feed_sorted_by_publication_not_creation(blog, alice):
    created_first = blog.create_article(alice, "one")
    blog.advance(1)
    created_second = blog.create_article(alice, "two")
    blog.advance(1)
    blog.publish(alice, created_second)
    blog.advance(1)
    blog.publish(alice, created_first)
    assert blog.feed() == [created_first, created_second], \
        f"expected order by publication date, got {blog.feed()!r}"


def test_A23_scheduled_publication_takes_its_place_in_feed(blog, alice):
    early = published(blog, alice, "early")
    sched = blog.create_article(alice, "sched")
    blog.schedule(alice, sched, blog.now + 10)
    blog.advance(5)
    middle = published(blog, alice, "middle")
    blog.advance(5)  # sched publishes exactly now (t=10)
    assert blog.feed() == [sched, middle, early], f"got {blog.feed()!r}"


# ---------------------------------------------------------------- A24 / A25 / A26

def test_A24_visitor_comment_on_open_published_is_pending(blog, alice):
    aid = open_published(blog, alice)
    cid = blog.comment(app.VISITOR, aid, "nice")
    assert blog.moderation(cid) == "pending", f"expected 'pending', got {blog.moderation(cid)!r}"
    assert cid in blog.comments(aid), "comment not recorded on the article"


def test_A25_comment_on_closed_article_creates_nothing(blog, alice):
    aid = published(blog, alice)
    blog.close_comments(alice, aid)
    attempt(blog.comment, app.VISITOR, aid, "nice")
    assert list(blog.comments(aid)) == [], f"comment created on closed article: {blog.comments(aid)!r}"


def test_A26_comment_on_draft_creates_nothing(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.open_comments(alice, aid)
    attempt(blog.comment, app.VISITOR, aid, "nice")
    assert list(blog.comments(aid)) == [], f"comment created on draft: {blog.comments(aid)!r}"


def test_A26_comment_on_draft_not_created_even_after_publish(blog, alice):
    aid = blog.create_article(alice, "hello")
    blog.open_comments(alice, aid)
    attempt(blog.comment, app.VISITOR, aid, "nice")
    blog.publish(alice, aid)
    assert list(blog.comments(aid)) == [], "refused comment surfaced after publication"


# ---------------------------------------------------------------- A27 / A28

def test_A27_pending_comment_hidden_from_visitor(blog, alice):
    aid, cid = pending_comment(blog, alice)
    assert cid not in blog.displayed_comments(aid, app.VISITOR), "pending comment shown to visitor"


def test_A28_pending_comment_shown_to_moderator(blog, alice, mod):
    aid, cid = pending_comment(blog, alice)
    assert cid in blog.displayed_comments(aid, mod), "pending comment hidden from moderator"


# ---------------------------------------------------------------- A29 / A30 / A31

def test_A29_moderator_approves_pending(blog, alice, mod):
    aid, cid = pending_comment(blog, alice)
    blog.approve(mod, cid)
    assert blog.moderation(cid) == "approved", f"expected 'approved', got {blog.moderation(cid)!r}"


def test_A30_author_cannot_approve(blog, alice):
    aid, cid = pending_comment(blog, alice)
    attempt(blog.approve, alice, cid)
    assert blog.moderation(cid) == "pending", f"expected 'pending', got {blog.moderation(cid)!r}"
    assert cid not in blog.displayed_comments(aid, app.VISITOR), "refused approval leaked display"


def test_A30_other_author_cannot_approve(blog, alice, bob):
    aid, cid = pending_comment(blog, alice)
    attempt(blog.approve, bob, cid)
    assert blog.moderation(cid) == "pending", f"expected 'pending', got {blog.moderation(cid)!r}"


def test_A31_approved_comment_shown_to_visitor(blog, alice, mod):
    aid, cid = pending_comment(blog, alice)
    blog.approve(mod, cid)
    assert cid in blog.displayed_comments(aid, app.VISITOR), "approved comment hidden from visitor"


def test_A31_only_approved_comment_shown_among_several(blog, alice, mod):
    aid = open_published(blog, alice)
    c1 = blog.comment(app.VISITOR, aid, "one")
    c2 = blog.comment(app.VISITOR, aid, "two")
    c3 = blog.comment(app.VISITOR, aid, "three")
    blog.approve(mod, c2)
    blog.reject(mod, c3)
    assert list(blog.displayed_comments(aid, app.VISITOR)) == [c2], \
        f"expected only {c2!r}, got {blog.displayed_comments(aid, app.VISITOR)!r} (c1={c1!r})"


# ---------------------------------------------------------------- A32 / A33

def test_A32_moderator_rejects_pending(blog, alice, mod):
    aid, cid = pending_comment(blog, alice)
    blog.reject(mod, cid)
    assert blog.moderation(cid) == "rejected", f"expected 'rejected', got {blog.moderation(cid)!r}"


def test_A33_rejected_comment_hidden_from_visitor(blog, alice, mod):
    aid, cid = pending_comment(blog, alice)
    blog.reject(mod, cid)
    assert cid not in blog.displayed_comments(aid, app.VISITOR), "rejected comment shown to visitor"


# ---------------------------------------------------------------- A34

def test_A34_unpublish_hides_approved_comments(blog, alice, mod):
    aid, cid = pending_comment(blog, alice)
    blog.approve(mod, cid)
    blog.unpublish(alice, aid)
    assert cid not in blog.displayed_comments(aid, app.VISITOR), \
        "approved comment still shown after article returned to draft"


# ---------------------------------------------------------------- A35 / A36

def test_A35_author_closes_comments(blog, alice):
    aid = open_published(blog, alice)
    blog.close_comments(alice, aid)
    assert blog.comments_open(aid) is False, "comments still open after close"


def test_A36_closing_keeps_approved_comments_displayed(blog, alice, mod):
    aid, cid = pending_comment(blog, alice)
    blog.approve(mod, cid)
    blog.close_comments(alice, aid)
    assert cid in blog.displayed_comments(aid, app.VISITOR), \
        "approved comment disappeared after comments were closed"
    assert blog.moderation(cid) == "approved", "closing changed moderation state"
