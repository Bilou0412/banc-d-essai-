"""Tests rouges — sonde blog (A01..A38).

Interface publique fixée par ces tests (module `app`) :

    app.Clock(start: datetime)            horloge simulée (datetime aware UTC)
        .now() -> datetime
        .advance(delta: timedelta) -> None
    app.Refused                           exception levée par toute action refusée
                                          (droits, propriété, date invalide, état invalide)
    app.Blog(clock)
        .register(name, *roles) -> user   rôles : "auteur", "moderateur"
        .create_post(user, title, content) -> post_id
        .status(post_id) -> "brouillon" | "publié" | "planifié"
        .publish(user, post_id)
        .schedule(user, post_id, when: datetime)
        .unschedule(user, post_id)
        .unpublish(user, post_id)
        .edit(user, post_id, content)
        .content(post_id) -> str
        .publication_date(post_id) -> datetime | None
        .visible_posts() -> list[post_id]             (vue d'un visiteur)
        .rss() -> str                                 XML RSS 2.0 : rss/channel/item,
                                                      item/guid == str(post_id),
                                                      item/title, item/description == contenu,
                                                      item/pubDate au format RFC 822
        .add_tag(user, post_id, tag) / .remove_tag(user, post_id, tag)
        .tags(post_id) -> list[str]
        .tag_page(tag) -> list[post_id]
        .comment(post_id, author_name, text) -> comment_id   (visiteur anonyme)
        .moderation(comment_id) -> "en attente" | "approuvé" | "rejeté"
        .approve(user, comment_id) / .reject(user, comment_id)
        .displayed_comments(post_id) -> list[comment_id]
        .comment_count(post_id) -> int

Tout ce qui dépend du temps passe par `Clock` ; T0 est en 2030 pour qu'une
implémentation qui lirait l'heure réelle soit démasquée.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from types import SimpleNamespace

import pytest

import app

T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


@pytest.fixture
def env():
    clock = app.Clock(T0)
    blog = app.Blog(clock)
    alice = blog.register("alice", "auteur")
    bob = blog.register("bob", "auteur")
    mona = blog.register("mona", "moderateur")
    return SimpleNamespace(clock=clock, blog=blog, alice=alice, bob=bob, mona=mona)


def draft(env, user=None, title="Titre", content="Contenu initial"):
    return env.blog.create_post(user if user is not None else env.alice, title, content)


def published(env, user=None, title="Titre", content="Contenu initial"):
    pid = draft(env, user, title, content)
    env.blog.publish(user if user is not None else env.alice, pid)
    return pid


def rss_items(blog):
    xml = blog.rss()
    assert isinstance(xml, str), f"rss() doit renvoyer une chaîne XML, obtenu {type(xml)!r}"
    root = ET.fromstring(xml)
    assert root.tag == "rss", f"élément racine attendu 'rss', obtenu {root.tag!r}"
    channel = root.find("channel")
    assert channel is not None, "élément rss/channel absent"
    items = []
    for it in channel.findall("item"):
        guid = it.findtext("guid")
        desc = it.findtext("description")
        pub = it.findtext("pubDate")
        assert guid is not None and pub is not None, "item sans guid ou pubDate"
        items.append(
            SimpleNamespace(guid=guid.strip(), description=desc, pub=parsedate_to_datetime(pub.strip()))
        )
    return items


def rss_guids(blog):
    return [i.guid for i in rss_items(blog)]


# ---------------------------------------------------------------- A01
def test_A01_nouvel_article_est_brouillon(env):
    pid = draft(env)
    assert env.blog.status(pid) == "brouillon", f"attendu 'brouillon', obtenu {env.blog.status(pid)!r}"


def test_A01_nouvel_article_sans_date_de_publication(env):
    pid = draft(env)
    assert env.blog.publication_date(pid) is None, (
        f"un brouillon n'a pas de date de publication, obtenu {env.blog.publication_date(pid)!r}"
    )


def test_A01_trou_moderateur_sans_role_auteur(env):
    with pytest.raises(app.Refused):
        env.blog.create_post(env.mona, "T", "C")
    assert env.blog.visible_posts() == []


# ---------------------------------------------------------------- A02
def test_A02_brouillon_non_visible(env):
    pid = draft(env)
    assert pid not in env.blog.visible_posts(), "un brouillon ne doit pas être visible des visiteurs"


# ---------------------------------------------------------------- A03
def test_A03_proprietaire_publie(env):
    pid = draft(env)
    env.blog.publish(env.alice, pid)
    assert env.blog.status(pid) == "publié", f"attendu 'publié', obtenu {env.blog.status(pid)!r}"


def test_A03_auteur_et_moderateur_proprietaire_publie(env):
    both = env.blog.register("zoe", "auteur", "moderateur")
    pid = env.blog.create_post(both, "T", "C")
    env.blog.publish(both, pid)
    assert env.blog.status(pid) == "publié"


# ---------------------------------------------------------------- A04
def test_A04_auteur_non_proprietaire_ne_publie_pas(env):
    pid = draft(env, env.alice)
    with pytest.raises(app.Refused):
        env.blog.publish(env.bob, pid)
    assert env.blog.status(pid) == "brouillon", f"attendu 'brouillon', obtenu {env.blog.status(pid)!r}"
    assert pid not in env.blog.visible_posts()
    assert env.blog.publication_date(pid) is None


# ---------------------------------------------------------------- A05
def test_A05_moderateur_non_proprietaire_ne_publie_pas(env):
    pid = draft(env, env.alice)
    with pytest.raises(app.Refused):
        env.blog.publish(env.mona, pid)
    assert env.blog.status(pid) == "brouillon", f"attendu 'brouillon', obtenu {env.blog.status(pid)!r}"
    assert pid not in env.blog.visible_posts()


def test_A05_auteur_moderateur_non_proprietaire_ne_publie_pas(env):
    both = env.blog.register("zoe", "auteur", "moderateur")
    pid = draft(env, env.alice)
    with pytest.raises(app.Refused):
        env.blog.publish(both, pid)
    assert env.blog.status(pid) == "brouillon"


# ---------------------------------------------------------------- A06
def test_A06_publie_visible(env):
    pid = published(env)
    assert pid in env.blog.visible_posts(), "un article publié doit être visible"


def test_A06_seuls_les_publies_sont_visibles(env):
    p1 = published(env)
    p2 = draft(env)
    assert env.blog.visible_posts() == [p1], f"attendu [{p1!r}], obtenu {env.blog.visible_posts()!r} (brouillon {p2!r})"


# ---------------------------------------------------------------- A07
def test_A07_date_publication_egale_maintenant(env):
    env.clock.advance(timedelta(minutes=37, seconds=5))
    pid = draft(env)
    env.blog.publish(env.alice, pid)
    expected = T0 + timedelta(minutes=37, seconds=5)
    assert env.blog.publication_date(pid) == expected, (
        f"attendu {expected}, obtenu {env.blog.publication_date(pid)}"
    )


def test_A07_date_publication_ne_suit_pas_l_horloge(env):
    pid = published(env)
    env.clock.advance(5 * H)
    assert env.blog.publication_date(pid) == T0, (
        f"la date de publication doit rester {T0}, obtenu {env.blog.publication_date(pid)}"
    )


def test_A07_date_publication_dans_le_flux(env):
    env.clock.advance(timedelta(days=3))
    pid = published(env)
    items = rss_items(env.blog)
    assert [i.pub for i in items] == [T0 + timedelta(days=3)], f"pubDate obtenues {[i.pub for i in items]}"
    assert items[0].guid == str(pid)


# ---------------------------------------------------------------- A08
def test_A08_planification_future(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    assert env.blog.status(pid) == "planifié", f"attendu 'planifié', obtenu {env.blog.status(pid)!r}"


def test_A08_trou_non_proprietaire(env):
    pid = draft(env, env.alice)
    with pytest.raises(app.Refused):
        env.blog.schedule(env.bob, pid, T0 + H)
    assert env.blog.status(pid) == "brouillon"
    env.clock.advance(2 * H)
    assert env.blog.status(pid) == "brouillon", "une planification refusée ne doit pas publier plus tard"


# ---------------------------------------------------------------- A09
def test_A09_planification_passee_refusee(env):
    pid = draft(env)
    with pytest.raises(app.Refused):
        env.blog.schedule(env.alice, pid, T0 - H)
    assert env.blog.status(pid) == "brouillon", f"attendu 'brouillon', obtenu {env.blog.status(pid)!r}"
    assert pid not in env.blog.visible_posts()


def test_A09_passe_relatif_a_l_horloge_simulee(env):
    env.clock.advance(timedelta(days=10))
    pid = draft(env)
    with pytest.raises(app.Refused):
        env.blog.schedule(env.alice, pid, T0 + timedelta(days=9))
    assert env.blog.status(pid) == "brouillon"


def test_A09_trou_date_egale_maintenant(env):
    pid = draft(env)
    with pytest.raises(app.Refused):
        env.blog.schedule(env.alice, pid, env.clock.now())
    assert env.blog.status(pid) == "brouillon"


# ---------------------------------------------------------------- A10
def test_A10_planifie_invisible_avant_date(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(timedelta(minutes=59, seconds=59))
    assert pid not in env.blog.visible_posts(), "un article planifié ne doit pas être visible avant sa date"
    assert env.blog.status(pid) == "planifié"


# ---------------------------------------------------------------- A11
def test_A11_date_atteinte_publie(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(H)
    assert env.blog.status(pid) == "publié", f"attendu 'publié' à la date exacte, obtenu {env.blog.status(pid)!r}"
    assert pid in env.blog.visible_posts()


def test_A11_date_depassee_publie_et_figure_dans_le_flux(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(3 * H)
    assert env.blog.status(pid) == "publié"
    assert rss_guids(env.blog) == [str(pid)]


def test_A11_plusieurs_planifications_independantes(env):
    p1 = draft(env, title="un")
    p2 = draft(env, title="deux")
    env.blog.schedule(env.alice, p1, T0 + H)
    env.blog.schedule(env.alice, p2, T0 + 3 * H)
    env.clock.advance(2 * H)
    assert env.blog.status(p1) == "publié"
    assert env.blog.status(p2) == "planifié"
    assert env.blog.visible_posts() == [p1]


# ---------------------------------------------------------------- A12
def test_A12_date_publication_egale_date_planifiee(env):
    pid = draft(env)
    when = T0 + timedelta(hours=1, minutes=13, seconds=7)
    env.blog.schedule(env.alice, pid, when)
    env.clock.advance(timedelta(days=2))
    assert env.blog.publication_date(pid) == when, (
        f"attendu {when} (date planifiée), obtenu {env.blog.publication_date(pid)}"
    )


def test_A12_date_planifiee_dans_le_flux_et_tri(env):
    # p1 planifié pour T0+1h ; on ne lit rien, puis p2 est publié à T0+2h.
    # Une implémentation qui horodaterait p1 lors de sa première observation
    # le placerait à tort devant p2.
    p1 = draft(env, title="planifie")
    env.blog.schedule(env.alice, p1, T0 + H)
    env.clock.advance(2 * H)
    p2 = published(env, title="immediat")
    env.clock.advance(H)
    items = rss_items(env.blog)
    assert [i.guid for i in items] == [str(p2), str(p1)], f"ordre obtenu {[i.guid for i in items]}"
    assert items[1].pub == T0 + H, f"pubDate de l'article planifié : attendu {T0 + H}, obtenu {items[1].pub}"


# ---------------------------------------------------------------- A13
def test_A13_annulation_planification(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.blog.unschedule(env.alice, pid)
    assert env.blog.status(pid) == "brouillon", f"attendu 'brouillon', obtenu {env.blog.status(pid)!r}"


def test_A13_annulation_empeche_publication_ulterieure(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.blog.unschedule(env.alice, pid)
    env.clock.advance(5 * H)
    assert env.blog.status(pid) == "brouillon", "une planification annulée ne doit pas publier à la date"
    assert pid not in env.blog.visible_posts()
    assert env.blog.publication_date(pid) is None
    assert rss_guids(env.blog) == []


def test_A13_trou_non_proprietaire(env):
    pid = draft(env, env.alice)
    env.blog.schedule(env.alice, pid, T0 + H)
    with pytest.raises(app.Refused):
        env.blog.unschedule(env.bob, pid)
    assert env.blog.status(pid) == "planifié"
    env.clock.advance(H)
    assert env.blog.status(pid) == "publié"


# ---------------------------------------------------------------- A14
def test_A14_depublication(env):
    pid = published(env)
    env.blog.unpublish(env.alice, pid)
    assert env.blog.status(pid) == "brouillon", f"attendu 'brouillon', obtenu {env.blog.status(pid)!r}"
    assert pid not in env.blog.visible_posts()


def test_A14_trou_non_proprietaire(env):
    pid = published(env, env.alice)
    with pytest.raises(app.Refused):
        env.blog.unpublish(env.bob, pid)
    with pytest.raises(app.Refused):
        env.blog.unpublish(env.mona, pid)
    assert env.blog.status(pid) == "publié"
    assert pid in env.blog.visible_posts()


# ---------------------------------------------------------------- A15
def test_A15_modification_contenu(env):
    pid = draft(env, content="avant")
    env.blog.edit(env.alice, pid, "après — édité ✓")
    assert env.blog.content(pid) == "après — édité ✓", f"obtenu {env.blog.content(pid)!r}"


def test_A15_modifications_successives_derniere_gagne(env):
    pid = published(env, content="v0")
    for i in range(1, 6):
        env.blog.edit(env.alice, pid, f"v{i}")
    assert env.blog.content(pid) == "v5"


# ---------------------------------------------------------------- A16
def test_A16_non_proprietaire_ne_modifie_pas(env):
    pid = published(env, env.alice, content="original")
    with pytest.raises(app.Refused):
        env.blog.edit(env.bob, pid, "piraté")
    assert env.blog.content(pid) == "original", f"obtenu {env.blog.content(pid)!r}"
    assert [i.description for i in rss_items(env.blog)] == ["original"]


def test_A16_trou_moderateur_non_proprietaire(env):
    pid = published(env, env.alice, content="original")
    with pytest.raises(app.Refused):
        env.blog.edit(env.mona, pid, "modéré")
    assert env.blog.content(pid) == "original"


# ---------------------------------------------------------------- A17
def test_A17_modification_garde_date_publication(env):
    pid = published(env)
    env.clock.advance(4 * H)
    env.blog.edit(env.alice, pid, "nouveau")
    assert env.blog.publication_date(pid) == T0, f"attendu {T0}, obtenu {env.blog.publication_date(pid)}"
    assert [i.pub for i in rss_items(env.blog)] == [T0]


# ---------------------------------------------------------------- A18-A20
def test_A18_publie_dans_flux(env):
    pid = published(env, content="corps")
    items = rss_items(env.blog)
    assert [i.guid for i in items] == [str(pid)], f"obtenu {[i.guid for i in items]}"
    assert items[0].description == "corps"


def test_A18_contenu_avec_caracteres_xml_speciaux(env):
    pid = published(env, title="A & B <c>", content='x < y & "z" — é')
    items = rss_items(env.blog)
    assert items[0].guid == str(pid)
    assert items[0].description == 'x < y & "z" — é', f"obtenu {items[0].description!r}"


def test_A19_brouillon_hors_flux(env):
    draft(env)
    assert rss_guids(env.blog) == []


def test_A20_planifie_hors_flux(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(timedelta(minutes=30))
    assert str(pid) not in rss_guids(env.blog)


# ---------------------------------------------------------------- A21
def test_A21_tri_date_decroissante(env):
    ids = []
    for i in range(4):
        ids.append(published(env, title=f"t{i}"))
        env.clock.advance(H)
    assert rss_guids(env.blog) == [str(x) for x in reversed(ids)], f"obtenu {rss_guids(env.blog)}"


def test_A21_tri_par_date_pas_par_creation(env):
    old = draft(env, title="cree en premier")
    new = draft(env, title="cree en second")
    env.blog.publish(env.alice, new)
    env.clock.advance(H)
    env.blog.publish(env.alice, old)
    assert rss_guids(env.blog) == [str(old), str(new)]


# ---------------------------------------------------------------- A22
def test_A22_depublie_sort_du_flux(env):
    p1 = published(env)
    p2 = published(env)
    env.blog.unpublish(env.alice, p1)
    assert rss_guids(env.blog) == [str(p2)], f"obtenu {rss_guids(env.blog)}"


# ---------------------------------------------------------------- A23
def test_A23_flux_presente_nouveau_contenu(env):
    pid = published(env, content="ancien")
    rss_items(env.blog)  # une lecture préalable ne doit pas figer le flux
    env.blog.edit(env.alice, pid, "nouveau")
    items = rss_items(env.blog)
    assert [i.description for i in items] == ["nouveau"], f"obtenu {[i.description for i in items]}"


# ---------------------------------------------------------------- A24-A28
def test_A24_ajout_tag(env):
    pid = draft(env)
    env.blog.add_tag(env.alice, pid, "python")
    assert "python" in env.blog.tags(pid)


def test_A24_trou_non_proprietaire(env):
    pid = published(env, env.alice)
    with pytest.raises(app.Refused):
        env.blog.add_tag(env.bob, pid, "spam")
    assert "spam" not in env.blog.tags(pid)
    assert env.blog.tag_page("spam") == []


def test_A25_tag_en_double(env):
    pid = draft(env)
    env.blog.add_tag(env.alice, pid, "python")
    env.blog.add_tag(env.alice, pid, "rust")
    env.blog.add_tag(env.alice, pid, "python")
    tags = list(env.blog.tags(pid))
    assert tags.count("python") == 1, f"obtenu {tags}"
    assert sorted(tags) == ["python", "rust"]


def test_A25_double_ne_duplique_pas_la_page(env):
    pid = published(env)
    env.blog.add_tag(env.alice, pid, "python")
    env.blog.add_tag(env.alice, pid, "python")
    assert env.blog.tag_page("python") == [pid]


def test_A26_page_tag_publie(env):
    pid = published(env)
    other = published(env)
    env.blog.add_tag(env.alice, pid, "python")
    env.blog.add_tag(env.alice, other, "rust")
    assert env.blog.tag_page("python") == [pid], f"obtenu {env.blog.tag_page('python')}"


def test_A27_page_tag_brouillon_absent(env):
    pid = draft(env)
    env.blog.add_tag(env.alice, pid, "python")
    assert env.blog.tag_page("python") == []


def test_A27_page_tag_article_depublie_absent(env):
    pid = published(env)
    env.blog.add_tag(env.alice, pid, "python")
    env.blog.unpublish(env.alice, pid)
    assert env.blog.tag_page("python") == []


def test_A27_trou_article_planifie(env):
    pid = draft(env)
    env.blog.add_tag(env.alice, pid, "python")
    env.blog.schedule(env.alice, pid, T0 + H)
    assert env.blog.tag_page("python") == []
    env.clock.advance(H)
    assert env.blog.tag_page("python") == [pid]


def test_A28_retrait_tag(env):
    pid = published(env)
    env.blog.add_tag(env.alice, pid, "python")
    env.blog.remove_tag(env.alice, pid, "python")
    assert env.blog.tag_page("python") == []
    assert "python" not in env.blog.tags(pid)


# ---------------------------------------------------------------- A29-A35
def test_A29_commentaire_en_attente(env):
    pid = published(env)
    cid = env.blog.comment(pid, "visiteur", "bonjour")
    assert env.blog.moderation(cid) == "en attente", f"obtenu {env.blog.moderation(cid)!r}"


def test_A29_trou_commentaire_sur_brouillon(env):
    pid = draft(env)
    with pytest.raises(app.Refused):
        env.blog.comment(pid, "visiteur", "bonjour")
    env.blog.publish(env.alice, pid)
    assert env.blog.displayed_comments(pid) == []
    assert env.blog.comment_count(pid) == 0


def test_A30_en_attente_non_affiche(env):
    pid = published(env)
    env.blog.comment(pid, "visiteur", "bonjour")
    assert env.blog.displayed_comments(pid) == []


def test_A31_moderateur_approuve(env):
    pid = published(env)
    cid = env.blog.comment(pid, "visiteur", "bonjour")
    env.blog.approve(env.mona, cid)
    assert env.blog.moderation(cid) == "approuvé", f"obtenu {env.blog.moderation(cid)!r}"


def test_A31_trou_approuver_rejete(env):
    pid = published(env)
    cid = env.blog.comment(pid, "visiteur", "spam")
    env.blog.reject(env.mona, cid)
    with pytest.raises(app.Refused):
        env.blog.approve(env.mona, cid)
    assert env.blog.moderation(cid) == "rejeté"
    assert env.blog.displayed_comments(pid) == []
    assert env.blog.comment_count(pid) == 0


def test_A32_auteur_sans_role_ne_peut_approuver(env):
    pid = published(env, env.alice)
    cid = env.blog.comment(pid, "visiteur", "bonjour")
    with pytest.raises(app.Refused):
        env.blog.approve(env.alice, cid)  # même propriétaire de l'article
    assert env.blog.moderation(cid) == "en attente", f"obtenu {env.blog.moderation(cid)!r}"
    assert env.blog.displayed_comments(pid) == []
    assert env.blog.comment_count(pid) == 0


def test_A33_moderateur_rejette(env):
    pid = published(env)
    cid = env.blog.comment(pid, "visiteur", "spam")
    env.blog.reject(env.mona, cid)
    assert env.blog.moderation(cid) == "rejeté", f"obtenu {env.blog.moderation(cid)!r}"


def test_A33_trou_auteur_sans_role_ne_peut_rejeter(env):
    pid = published(env, env.alice)
    cid = env.blog.comment(pid, "visiteur", "critique")
    with pytest.raises(app.Refused):
        env.blog.reject(env.alice, cid)
    assert env.blog.moderation(cid) == "en attente"


def test_A34_approuve_affiche(env):
    pid = published(env)
    c1 = env.blog.comment(pid, "v1", "un")
    c2 = env.blog.comment(pid, "v2", "deux")
    env.blog.approve(env.mona, c1)
    assert env.blog.displayed_comments(pid) == [c1], f"obtenu {env.blog.displayed_comments(pid)} (en attente {c2})"


def test_A34_trou_article_depublie(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "un")
    env.blog.approve(env.mona, cid)
    env.blog.unpublish(env.alice, pid)
    assert env.blog.displayed_comments(pid) == []


def test_A35_rejete_non_affiche(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "spam")
    env.blog.reject(env.mona, cid)
    assert cid not in env.blog.displayed_comments(pid)


# ---------------------------------------------------------------- A36-A37
def test_A36_approbation_incremente_compteur(env):
    pid = published(env)
    other = published(env)
    c1 = env.blog.comment(pid, "v", "un")
    c2 = env.blog.comment(pid, "v", "deux")
    assert env.blog.comment_count(pid) == 0
    env.blog.approve(env.mona, c1)
    assert env.blog.comment_count(pid) == 1, f"obtenu {env.blog.comment_count(pid)}"
    env.blog.approve(env.mona, c2)
    assert env.blog.comment_count(pid) == 2
    assert env.blog.comment_count(other) == 0, "le compteur d'un autre article ne doit pas bouger"


def test_A36_rejet_n_incremente_pas(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "spam")
    env.blog.reject(env.mona, cid)
    assert env.blog.comment_count(pid) == 0


def test_A36_trou_double_approbation(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "un")
    env.blog.approve(env.mona, cid)
    try:
        env.blog.approve(env.mona, cid)
    except app.Refused:
        pass
    assert env.blog.comment_count(pid) == 1, f"double approbation : attendu 1, obtenu {env.blog.comment_count(pid)}"
    assert env.blog.displayed_comments(pid) == [cid]


def test_A37_poster_ne_change_pas_compteur(env):
    pid = published(env)
    env.blog.comment(pid, "v", "un")
    env.blog.comment(pid, "v", "deux")
    assert env.blog.comment_count(pid) == 0, f"obtenu {env.blog.comment_count(pid)}"


# ---------------------------------------------------------------- A38
def test_A38_republication_reaffiche_commentaire_approuve(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "un")
    env.blog.approve(env.mona, cid)
    env.blog.unpublish(env.alice, pid)
    env.blog.publish(env.alice, pid)
    assert env.blog.displayed_comments(pid) == [cid], f"obtenu {env.blog.displayed_comments(pid)}"
    assert env.blog.moderation(cid) == "approuvé"


def test_A38_trou_date_republication(env):
    pid = published(env)
    env.blog.unpublish(env.alice, pid)
    env.clock.advance(2 * H)
    env.blog.publish(env.alice, pid)
    assert env.blog.publication_date(pid) == T0 + 2 * H, (
        f"republication : attendu {T0 + 2 * H}, obtenu {env.blog.publication_date(pid)}"
    )
