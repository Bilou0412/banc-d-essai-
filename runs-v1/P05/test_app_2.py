"""Tests rouges — sonde blog, deuxième attaque (A01..A38).

Même interface publique que tests/test_app.py (module `app`).
Cible : les implémentations qui simulent le mécanisme (minuteries non annulées,
évaluation paresseuse cantonnée à status(), état global au module, comparaison
d'heures naïves, propriété comparée par nom), et les interactions entre règles.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from types import SimpleNamespace

import pytest

import app

T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)
PLUS2 = timezone(timedelta(hours=2))
MINUS5 = timezone(timedelta(hours=-5))


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
        pub = it.findtext("pubDate")
        assert guid is not None and pub is not None, "item sans guid ou pubDate"
        items.append(
            SimpleNamespace(
                guid=guid.strip(),
                title=it.findtext("title"),
                description=it.findtext("description"),
                pub=parsedate_to_datetime(pub.strip()),
            )
        )
    return items


def rss_guids(blog):
    return [i.guid for i in rss_items(blog)]


# ======================================================== isolation (pas d'état global)
def test_A06_trou_deux_blogs_independants():
    c1, c2 = app.Clock(T0), app.Clock(T0)
    b1, b2 = app.Blog(c1), app.Blog(c2)
    a1 = b1.register("alice", "auteur")
    b2.register("alice", "auteur")
    pid = b1.create_post(a1, "T", "C")
    b1.publish(a1, pid)
    assert b2.visible_posts() == [], f"un article publié sur un autre blog fuit : {b2.visible_posts()!r}"
    assert rss_guids(b2) == [], "le flux d'un autre blog ne doit rien contenir"


def test_A11_horloges_independantes_entre_blogs():
    c1, c2 = app.Clock(T0), app.Clock(T0)
    b1, b2 = app.Blog(c1), app.Blog(c2)
    a1 = b1.register("alice", "auteur")
    pid = b1.create_post(a1, "T", "C")
    b1.schedule(a1, pid, T0 + H)
    c2.advance(5 * H)  # l'horloge d'un autre blog ne doit pas faire avancer celui-ci
    assert b1.status(pid) == "planifié", f"obtenu {b1.status(pid)!r} : horloge partagée entre blogs ?"
    c1.advance(H)
    assert b1.status(pid) == "publié"


# ======================================================== propriété par identité, pas par nom
def test_A04_trou_homonyme_ne_publie_pas(env):
    pid = draft(env, env.alice)
    try:
        imposteur = env.blog.register("alice", "auteur")
    except app.Refused:
        return  # nom unique : l'attaque est impossible, c'est conforme
    with pytest.raises(app.Refused):
        env.blog.publish(imposteur, pid)
    assert env.blog.status(pid) == "brouillon", f"un homonyme a publié : {env.blog.status(pid)!r}"


def test_A16_trou_homonyme_ne_modifie_pas(env):
    pid = published(env, env.alice, content="original")
    try:
        imposteur = env.blog.register("alice", "auteur")
    except app.Refused:
        return
    with pytest.raises(app.Refused):
        env.blog.edit(imposteur, pid, "piraté")
    assert env.blog.content(pid) == "original"


def test_A04_refus_ne_bloque_pas_le_proprietaire(env):
    pid = draft(env, env.alice)
    with pytest.raises(app.Refused):
        env.blog.publish(env.bob, pid)
    env.clock.advance(H)
    env.blog.publish(env.alice, pid)
    assert env.blog.status(pid) == "publié"
    assert env.blog.publication_date(pid) == T0 + H


# ======================================================== fuseaux horaires (dates aware)
def test_A09_passe_exprime_dans_un_autre_fuseau(env):
    # T0 - 30 min exprimé en +02:00 vaut 13:30 « à l'horloge murale » > 12:00 :
    # une comparaison naïve l'accepterait comme future.
    when = (T0 - timedelta(minutes=30)).astimezone(PLUS2)
    pid = draft(env)
    with pytest.raises(app.Refused):
        env.blog.schedule(env.alice, pid, when)
    assert env.blog.status(pid) == "brouillon", f"date passée ({when.isoformat()}) acceptée"


def test_A08_futur_exprime_dans_un_autre_fuseau(env):
    # T0 + 1 h exprimé en -05:00 vaut 08:00 « murale » < 12:00 : une comparaison
    # naïve la refuserait comme passée.
    when = (T0 + H).astimezone(MINUS5)
    pid = draft(env)
    env.blog.schedule(env.alice, pid, when)
    assert env.blog.status(pid) == "planifié", f"obtenu {env.blog.status(pid)!r} pour {when.isoformat()}"
    env.clock.advance(timedelta(minutes=59))
    assert env.blog.status(pid) == "planifié"
    env.clock.advance(timedelta(minutes=1))
    assert env.blog.status(pid) == "publié"


def test_A12_date_planifiee_autre_fuseau_meme_instant(env):
    when = (T0 + 2 * H).astimezone(PLUS2)
    pid = draft(env)
    env.blog.schedule(env.alice, pid, when)
    env.clock.advance(3 * H)
    assert env.blog.publication_date(pid) == when, f"attendu {when}, obtenu {env.blog.publication_date(pid)}"
    assert [i.pub for i in rss_items(env.blog)] == [T0 + 2 * H]


# ======================================================== seuil exact de la planification
def test_A10_une_microseconde_avant_la_date(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(H - timedelta(microseconds=1))
    assert env.blog.status(pid) == "planifié", f"publié avec 1 µs d'avance : {env.blog.status(pid)!r}"
    assert pid not in env.blog.visible_posts()
    assert rss_guids(env.blog) == []


def test_A09_une_microseconde_dans_le_futur_acceptee(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + timedelta(microseconds=1))
    assert env.blog.status(pid) == "planifié"


# ======================================================== minuteries : annuler / replanifier
def test_A13_replanifier_plus_tot_puis_l_ancienne_date_ne_reecrit_pas(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + 3 * H)
    env.blog.unschedule(env.alice, pid)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(H)
    assert env.blog.status(pid) == "publié", f"obtenu {env.blog.status(pid)!r}"
    env.clock.advance(5 * H)  # l'ancienne échéance T0+3h est dépassée
    assert env.blog.publication_date(pid) == T0 + H, (
        f"l'échéance annulée a réécrit la date : obtenu {env.blog.publication_date(pid)}"
    )


def test_A13_replanifier_plus_tard_l_ancienne_date_ne_publie_pas(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.blog.unschedule(env.alice, pid)
    env.blog.schedule(env.alice, pid, T0 + 3 * H)
    env.clock.advance(2 * H)
    assert env.blog.status(pid) == "planifié", f"l'échéance annulée a publié : {env.blog.status(pid)!r}"
    assert pid not in env.blog.visible_posts()
    env.clock.advance(H)
    assert env.blog.status(pid) == "publié"
    assert env.blog.publication_date(pid) == T0 + 3 * H


def test_A13_cinquante_cycles_planifier_annuler(env):
    pid = draft(env)
    for i in range(50):
        env.blog.schedule(env.alice, pid, T0 + (i + 1) * H)
        env.blog.unschedule(env.alice, pid)
    env.clock.advance(100 * H)
    assert env.blog.status(pid) == "brouillon", f"une planification annulée a publié : {env.blog.status(pid)!r}"
    assert env.blog.publication_date(pid) is None
    env.blog.schedule(env.alice, pid, T0 + 101 * H)
    env.clock.advance(H)
    assert env.blog.status(pid) == "publié"
    assert env.blog.publication_date(pid) == T0 + 101 * H


def test_A07_publier_apres_annulation_garde_la_date_immediate(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + 2 * H)
    env.blog.unschedule(env.alice, pid)
    env.clock.advance(timedelta(minutes=30))
    env.blog.publish(env.alice, pid)
    env.clock.advance(5 * H)
    assert env.blog.publication_date(pid) == T0 + timedelta(minutes=30), (
        f"l'échéance annulée a écrasé la date : {env.blog.publication_date(pid)}"
    )


# ======================================================== dépublication d'un article issu d'une planification
def test_A14_depublier_un_article_planifie_echu_reste_brouillon(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(2 * H)
    env.blog.unpublish(env.alice, pid)  # aucune lecture préalable : l'échéance doit déjà compter
    assert env.blog.status(pid) == "brouillon"
    env.clock.advance(10 * H)
    assert env.blog.status(pid) == "brouillon", (
        f"la date planifiée échue republie l'article : {env.blog.status(pid)!r}"
    )
    assert pid not in env.blog.visible_posts()
    assert rss_guids(env.blog) == []


def test_A07_republier_un_ancien_planifie_prend_la_date_du_moment(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(2 * H)
    env.blog.unpublish(env.alice, pid)
    env.clock.advance(H)
    env.blog.publish(env.alice, pid)
    assert env.blog.publication_date(pid) == T0 + 3 * H, (
        f"attendu {T0 + 3 * H} (publication immédiate), obtenu {env.blog.publication_date(pid)}"
    )


# ======================================================== l'échéance compte pour toutes les vues
def test_A11_echeance_vue_par_visible_posts_sans_lecture_prealable(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(H)
    assert env.blog.visible_posts() == [pid], f"obtenu {env.blog.visible_posts()!r}"


def test_A12_echeance_vue_par_publication_date_sans_lecture_prealable(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    assert env.blog.publication_date(pid) is None, "un article planifié n'est pas encore publié"
    env.clock.advance(4 * H)
    assert env.blog.publication_date(pid) == T0 + H


def test_A29_commentaire_accepte_sur_planifie_echu_sans_lecture_prealable(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(H)
    cid = env.blog.comment(pid, "visiteur", "premier !")
    assert env.blog.moderation(cid) == "en attente"


def test_A13_trou_annuler_apres_echeance_refuse(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(H)
    with pytest.raises(app.Refused):
        env.blog.unschedule(env.alice, pid)  # l'article est déjà publié
    assert env.blog.status(pid) == "publié"
    assert env.blog.publication_date(pid) == T0 + H


# ======================================================== édition × planification / date
def test_A15_modifier_un_planifie_le_garde_planifie(env):
    pid = draft(env, content="v0")
    env.blog.schedule(env.alice, pid, T0 + H)
    env.blog.edit(env.alice, pid, "v1")
    assert env.blog.status(pid) == "planifié", f"obtenu {env.blog.status(pid)!r}"
    assert env.blog.content(pid) == "v1"
    env.clock.advance(H)
    items = rss_items(env.blog)
    assert [i.description for i in items] == ["v1"], f"obtenu {[i.description for i in items]}"
    assert env.blog.publication_date(pid) == T0 + H


def test_A17_modifier_un_ancien_planifie_garde_la_date_planifiee(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.clock.advance(3 * H)
    env.blog.edit(env.alice, pid, "nouveau")
    assert env.blog.publication_date(pid) == T0 + H, f"obtenu {env.blog.publication_date(pid)}"


def test_A15_contenu_vide(env):
    pid = published(env, content="non vide")
    env.blog.edit(env.alice, pid, "")
    assert env.blog.content(pid) == "", f"le contenu vide a été ignoré : {env.blog.content(pid)!r}"
    assert [(i.description or "") for i in rss_items(env.blog)] == [""]


def test_A15_fins_de_ligne_mixtes_et_espaces(env):
    text = "  ligne 1\r\nligne 2\nligne 3\rfin  "
    pid = draft(env)
    env.blog.edit(env.alice, pid, text)
    assert env.blog.content(pid) == text, f"attendu {text!r}, obtenu {env.blog.content(pid)!r}"


def test_A23_trou_flux_preserve_fins_de_ligne_et_espaces(env):
    text = "  ligne 1\r\nligne 2\nligne 3\rfin  "
    pid = published(env)
    env.blog.edit(env.alice, pid, text)
    items = rss_items(env.blog)
    assert [i.description for i in items] == [text], (
        f"le flux présente {[i.description for i in items]!r} au lieu de {text!r}"
    )


def test_A23_modification_pendant_depublication_puis_republication(env):
    pid = published(env, content="ancien")
    env.blog.unpublish(env.alice, pid)
    env.blog.edit(env.alice, pid, "nouveau")
    env.blog.publish(env.alice, pid)
    assert [i.description for i in rss_items(env.blog)] == ["nouveau"]


def test_A16_refus_sur_brouillon_n_altere_pas(env):
    pid = draft(env, env.alice, content="original")
    with pytest.raises(app.Refused):
        env.blog.edit(env.bob, pid, "piraté")
    env.blog.publish(env.alice, pid)
    assert env.blog.content(pid) == "original"
    assert [i.description for i in rss_items(env.blog)] == ["original"]


# ======================================================== publier deux fois / planifier un publié
def test_A03_trou_republier_un_publie_ne_change_pas_la_date(env):
    pid = published(env)
    env.clock.advance(2 * H)
    try:
        env.blog.publish(env.alice, pid)
    except app.Refused:
        pass
    assert env.blog.status(pid) == "publié"
    assert env.blog.publication_date(pid) == T0, (
        f"une seconde publication a déplacé la date : {env.blog.publication_date(pid)}"
    )


def test_A08_trou_planifier_un_publie_refuse(env):
    pid = published(env)
    with pytest.raises(app.Refused):
        env.blog.schedule(env.alice, pid, T0 + H)
    assert env.blog.status(pid) == "publié"
    assert pid in env.blog.visible_posts()
    env.clock.advance(2 * H)
    assert env.blog.publication_date(pid) == T0


# ======================================================== flux RSS
def test_A18_titre_present_et_echappe(env):
    pid = published(env, title="Été & <hiver> \"x\"", content="c")
    items = rss_items(env.blog)
    assert items[0].guid == str(pid)
    assert items[0].title == "Été & <hiver> \"x\"", f"obtenu {items[0].title!r}"


def test_A21_planifie_plus_tardif_passe_devant(env):
    p1 = draft(env, title="planifié tard")
    env.blog.schedule(env.alice, p1, T0 + 3 * H)
    env.clock.advance(H)
    p2 = published(env, title="immédiat")
    env.clock.advance(4 * H)
    assert rss_guids(env.blog) == [str(p1), str(p2)], f"obtenu {rss_guids(env.blog)}"


def test_A21_cinquante_articles_ordre_decroissant(env):
    ids = []
    # ordre d'insertion dans le temps volontairement non monotone par rapport à la création
    pids = [draft(env, title=f"t{i}") for i in range(50)]
    order = [(i * 17) % 50 for i in range(50)]  # permutation
    for k in order:
        env.blog.publish(env.alice, pids[k])
        ids.append(pids[k])
        env.clock.advance(timedelta(minutes=1))
    got = rss_guids(env.blog)
    assert got == [str(x) for x in reversed(ids)], f"ordre obtenu (début) {got[:5]}"


def test_A22_republication_reintegre_le_flux_a_la_nouvelle_date(env):
    p1 = published(env, title="un")
    env.clock.advance(H)
    p2 = published(env, title="deux")
    env.blog.unpublish(env.alice, p1)
    env.clock.advance(H)
    env.blog.publish(env.alice, p1)
    items = rss_items(env.blog)
    assert [i.guid for i in items] == [str(p1), str(p2)], f"obtenu {[i.guid for i in items]}"
    assert items[0].pub == T0 + 2 * H


# ======================================================== tags
def test_A24_tag_non_ascii(env):
    pid = published(env)
    env.blog.add_tag(env.alice, pid, "été")
    assert "été" in env.blog.tags(pid)
    assert env.blog.tag_page("été") == [pid]


def test_A26_plusieurs_articles_sur_la_page(env):
    p1 = published(env)
    p2 = published(env)
    p3 = draft(env)
    for p in (p1, p2, p3):
        env.blog.add_tag(env.alice, p, "python")
    assert sorted(env.blog.tag_page("python"), key=str) == sorted([p1, p2], key=str), (
        f"obtenu {env.blog.tag_page('python')}"
    )


def test_A28_retrait_ne_touche_que_ce_tag_et_cet_article(env):
    p1 = published(env)
    p2 = published(env)
    env.blog.add_tag(env.alice, p1, "python")
    env.blog.add_tag(env.alice, p1, "rust")
    env.blog.add_tag(env.alice, p2, "python")
    env.blog.remove_tag(env.alice, p1, "python")
    assert env.blog.tag_page("python") == [p2], f"obtenu {env.blog.tag_page('python')}"
    assert env.blog.tag_page("rust") == [p1]
    assert list(env.blog.tags(p1)) == ["rust"]


def test_A28_retirer_puis_rajouter(env):
    pid = published(env)
    env.blog.add_tag(env.alice, pid, "python")
    env.blog.remove_tag(env.alice, pid, "python")
    env.blog.add_tag(env.alice, pid, "python")
    assert env.blog.tag_page("python") == [pid]
    assert list(env.blog.tags(pid)).count("python") == 1


def test_A28_trou_non_proprietaire_ne_retire_pas(env):
    pid = published(env, env.alice)
    env.blog.add_tag(env.alice, pid, "python")
    with pytest.raises(app.Refused):
        env.blog.remove_tag(env.bob, pid, "python")
    assert env.blog.tag_page("python") == [pid]
    assert "python" in env.blog.tags(pid)


def test_A26_tag_ajoute_pendant_planification_apparait_a_l_echeance(env):
    pid = draft(env)
    env.blog.schedule(env.alice, pid, T0 + H)
    env.blog.add_tag(env.alice, pid, "python")
    env.clock.advance(H)
    assert env.blog.tag_page("python") == [pid]


# ======================================================== commentaires
def test_A31_auteur_moderateur_approuve_sur_son_propre_article(env):
    zoe = env.blog.register("zoe", "auteur", "moderateur")
    pid = env.blog.create_post(zoe, "T", "C")
    env.blog.publish(zoe, pid)
    cid = env.blog.comment(pid, "v", "un")
    env.blog.approve(zoe, cid)
    assert env.blog.moderation(cid) == "approuvé"
    assert env.blog.comment_count(pid) == 1


def test_A34_commentaire_affiche_uniquement_sur_son_article(env):
    p1 = published(env)
    p2 = published(env)
    c1 = env.blog.comment(p1, "v", "sur p1")
    env.blog.approve(env.mona, c1)
    assert env.blog.displayed_comments(p2) == [], f"obtenu {env.blog.displayed_comments(p2)}"
    assert env.blog.displayed_comments(p1) == [c1]


def test_A29_identifiants_de_commentaires_distincts(env):
    p1 = published(env)
    p2 = published(env)
    ids = [env.blog.comment(p, "v", "x") for p in (p1, p2, p1, p2)]
    assert len(set(ids)) == 4, f"identifiants de commentaires en double : {ids}"
    env.blog.approve(env.mona, ids[0])
    assert env.blog.moderation(ids[1]) == "en attente"
    assert env.blog.moderation(ids[2]) == "en attente"


def test_A37_poster_apres_approbation_ne_change_pas_compteur(env):
    pid = published(env)
    c1 = env.blog.comment(pid, "v", "un")
    env.blog.approve(env.mona, c1)
    env.blog.comment(pid, "v", "deux")
    env.blog.comment(pid, "v", "trois")
    assert env.blog.comment_count(pid) == 1, f"obtenu {env.blog.comment_count(pid)}"


def test_A36_cent_approbations(env):
    pid = published(env)
    cids = [env.blog.comment(pid, f"v{i}", f"c{i}") for i in range(100)]
    for c in cids[::2]:
        env.blog.approve(env.mona, c)
    for c in cids[1::2]:
        env.blog.reject(env.mona, c)
    assert env.blog.comment_count(pid) == 50, f"obtenu {env.blog.comment_count(pid)}"
    assert sorted(env.blog.displayed_comments(pid), key=str) == sorted(cids[::2], key=str)


def test_A36_compteur_survit_a_depublication(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "un")
    env.blog.approve(env.mona, cid)
    env.blog.unpublish(env.alice, pid)
    env.blog.publish(env.alice, pid)
    assert env.blog.comment_count(pid) == 1, f"obtenu {env.blog.comment_count(pid)}"


def test_A38_republication_ne_reaffiche_ni_attente_ni_rejet(env):
    pid = published(env)
    ok = env.blog.comment(pid, "v", "ok")
    pend = env.blog.comment(pid, "v", "attente")
    rej = env.blog.comment(pid, "v", "rejet")
    env.blog.approve(env.mona, ok)
    env.blog.reject(env.mona, rej)
    env.blog.unpublish(env.alice, pid)
    env.blog.publish(env.alice, pid)
    assert env.blog.displayed_comments(pid) == [ok], f"obtenu {env.blog.displayed_comments(pid)}"
    assert env.blog.moderation(pend) == "en attente"
    assert env.blog.moderation(rej) == "rejeté"


def test_A38_moderation_pendant_depublication_puis_republication(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "un")
    env.blog.unpublish(env.alice, pid)
    env.blog.approve(env.mona, cid)
    assert env.blog.displayed_comments(pid) == []
    env.blog.publish(env.alice, pid)
    assert env.blog.displayed_comments(pid) == [cid]


def test_A33_trou_rejeter_un_approuve_refuse(env):
    pid = published(env)
    cid = env.blog.comment(pid, "v", "un")
    env.blog.approve(env.mona, cid)
    with pytest.raises(app.Refused):
        env.blog.reject(env.mona, cid)
    assert env.blog.moderation(cid) == "approuvé"
    assert env.blog.comment_count(pid) == 1
    assert env.blog.displayed_comments(pid) == [cid]
