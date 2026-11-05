import re

import pytest
from sqlalchemy import select

from rr.db import Match, Player, Tournament

NAMES = ["Ann", "Bob", "Cy", "Di", "Ed", "Flo", "Gus", "Hal", "Ivy"]


def add_players(c, names=NAMES):
    text = "\n".join(f"{n},{n.lower()}@example.com" for n in names)
    r = c.post("/players/import", data={"text": text})
    assert r.status_code == 200
    with c.app.state.Session() as db:
        return {p.name: p.id for p in db.scalars(select(Player))}


def create(c, ids, courts=2, rounds=3, name="Tuesday"):
    return c.post(
        "/tournaments",
        data={
            "name": name,
            "date": "2026-11-10",
            "courts": courts,
            "rounds": rounds,
            "players": list(ids),
        },
        follow_redirects=False,
    )


def tournament(db, slug=None) -> Tournament:
    db.expire_all()
    q = select(Tournament)
    if slug:
        q = q.where(Tournament.slug == slug)
    return db.scalars(q).first()


def slug_from(response):
    return re.match(r"/t/([^/]+)/schedule", response.headers["location"]).group(1)


def report_all(c, db, slug, number, score=(11, 7)):
    t = tournament(db, slug)
    rnd = t.rounds[number - 1]
    last = None
    for m in rnd.matches:
        last = c.post(
            f"/t/{slug}/match/{m.id}",
            data={"score_a": score[0], "score_b": score[1]},
            follow_redirects=False,
        )
    return last


# ---------------------------------------------------------------- auth


@pytest.mark.parametrize("path", ["/players", "/players/import", "/tournaments/new"])
def test_organizer_pages_need_login(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/login?next={path}"


def test_wrong_password(client):
    r = client.post("/login", data={"password": "nope"})
    assert r.status_code == 401
    assert "Wrong password" in r.text
    assert client.get("/players", follow_redirects=False).status_code == 303


def test_login_redirects_only_on_site(client):
    for bad in ["https://evil.example", "//evil.example", "/\\evil.example"]:
        r = client.post(
            "/login",
            data={"password": "court-sweep", "next": bad},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/"
    r = client.post(
        "/login",
        data={"password": "court-sweep", "next": "/players"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/players"


def test_no_password_configured_means_no_login(tmp_path):
    from fastapi.testclient import TestClient

    from rr.main import create_app

    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'x.db'}",
        admin_password="",
        secret_key="k",
        https_only=False,
    )
    with TestClient(app) as c:
        r = c.post("/login", data={"password": ""})
        assert r.status_code == 401
        assert "RR_ADMIN_PASSWORD" in r.text


def test_logout(organizer):
    organizer.post("/logout")
    assert organizer.get("/players", follow_redirects=False).status_code == 303


# ---------------------------------------------------------------- players


def test_add_edit_deactivate_player(organizer, db):
    r = organizer.post(
        "/players", data={"name": "  Ann   Smith ", "email": "Ann@X.com"}
    )
    assert "Added Ann Smith" in r.text
    p = db.scalar(select(Player))
    assert (p.name, p.email) == ("Ann Smith", "ann@x.com")

    r = organizer.post(f"/players/{p.id}/edit", data={"name": "Ann Lee", "email": ""})
    assert "Saved Ann Lee" in r.text
    db.refresh(p)
    assert (p.name, p.email) == ("Ann Lee", None)

    organizer.post(f"/players/{p.id}/active", data={"active": "false"})
    db.refresh(p)
    assert not p.active
    assert "Ann Lee" not in organizer.get("/tournaments/new").text


def test_duplicate_email_is_an_error(organizer):
    organizer.post("/players", data={"name": "Ann", "email": "a@x.com"})
    r = organizer.post("/players", data={"name": "Other", "email": "a@x.com"})
    assert r.status_code == 400
    assert "already has the email" in r.text


def test_import_from_file(organizer, db):
    csv = b"\xef\xbb\xbfName,Email\nAnn,ann@x.com\nBob,bob@x.com\n,\n"
    r = organizer.post(
        "/players/import", files={"file": ("roster.csv", csv, "text/csv")}
    )
    assert r.status_code == 200
    assert "2 added" in r.text
    assert sorted(db.scalars(select(Player.name))) == ["Ann", "Bob"]


def test_import_needs_something(organizer):
    r = organizer.post("/players/import", data={"text": "  "})
    assert r.status_code == 400


# ---------------------------------------------------------------- tournaments


def test_create_validates(organizer):
    ids = add_players(organizer)
    r = create(organizer, list(ids.values())[:3])
    assert r.status_code == 400
    assert "at least 4 players" in r.text
    r = create(organizer, ids.values(), courts=0)
    assert r.status_code == 400
    r = create(organizer, ids.values(), rounds=99)
    assert r.status_code == 400


def test_setup_is_private_until_started(organizer, client, db):
    ids = add_players(organizer)
    slug = slug_from(create(organizer, ids.values()))
    page = organizer.get(f"/t/{slug}/schedule")
    assert "Schedule preview" in page.text
    assert "Nobody partners the same person twice" in page.text
    assert "1 sits out each round" in page.text
    assert "average points per game" in page.text

    assert client.get(f"/t/{slug}").status_code == 404
    assert client.get(f"/t/{slug}/schedule").status_code == 404
    assert "Tuesday" not in client.get("/").text

    organizer.post(f"/t/{slug}/start")
    assert client.get(f"/t/{slug}").status_code == 200
    assert "Tuesday" in client.get("/").text


def test_reshuffle_only_before_start(organizer, db):
    ids = add_players(organizer)
    slug = slug_from(create(organizer, ids.values()))
    seed = tournament(db, slug).seed
    organizer.post(f"/t/{slug}/reshuffle")
    assert tournament(db, slug).seed != seed
    organizer.post(f"/t/{slug}/start")
    assert organizer.post(f"/t/{slug}/reshuffle").status_code == 409


def test_schedule_matches_scheduler_rules(organizer, db):
    ids = add_players(organizer)
    slug = slug_from(create(organizer, ids.values(), courts=2, rounds=9))
    t = tournament(db, slug)
    assert t.ranking == "average"
    assert len(t.rounds) == 9
    sat = {}
    for r in t.rounds:
        assert len(r.matches) == 2
        assert len(r.sitting_out) == 1
        on_court = [p for m in r.matches for p in (m.a1_id, m.a2_id, m.b1_id, m.b2_id)]
        assert sorted(on_court + [r.sitting_out[0].id]) == sorted(ids.values())
        sat[r.sitting_out[0].id] = sat.get(r.sitting_out[0].id, 0) + 1
    assert set(sat.values()) == {1}


def test_full_tournament(organizer, client, db):
    ids = add_players(organizer, NAMES[:8])
    slug = slug_from(create(organizer, ids.values(), courts=2, rounds=2))
    assert tournament(db, slug).ranking == "total"
    organizer.post(f"/t/{slug}/start")

    page = organizer.get(f"/t/{slug}/round/1")
    assert page.text.count('name="score_a"') == 2
    assert "0 of 2 courts reported" in page.text

    # first court: stays on the round page
    t = tournament(db, slug)
    m1, m2 = t.rounds[0].matches
    r = organizer.post(
        f"/t/{slug}/match/{m1.id}",
        data={"score_a": "11", "score_b": "4"},
        follow_redirects=False,
    )
    assert r.headers["location"] == f"/t/{slug}/round/1#court-1"
    # last court: round complete, go to standings
    r = organizer.post(
        f"/t/{slug}/match/{m2.id}",
        data={"score_a": "9", "score_b": "6"},  # time limit
        follow_redirects=False,
    )
    assert r.headers["location"] == f"/t/{slug}"
    page = organizer.get(f"/t/{slug}")
    assert "Round 1 is complete" in page.text
    assert "After round 1" in page.text
    assert "Enter round 2 scores" in page.text

    report_all(organizer, db, slug, 2)
    page = client.get(f"/t/{slug}")
    assert "Final standings" in page.text
    assert "Enter round" not in page.text  # public view has no controls

    t = tournament(db, slug)
    assert t.finished
    totals = {}
    for m in t.matches():
        for p in (m.a1_id, m.a2_id):
            totals[p] = totals.get(p, 0) + m.score_a
        for p in (m.b1_id, m.b2_id):
            totals[p] = totals.get(p, 0) + m.score_b
    by_id = {v: k for k, v in ids.items()}
    # Most points first; tied players alphabetically.
    expected = sorted(totals, key=lambda p: (-totals[p], by_id[p].lower()))
    shown = re.findall(r'<th scope="row">([^<]+)</th>', page.text)
    assert shown == [by_id[p] for p in expected]
    assert max(totals.values()) == 22  # two wins at 11


def test_score_validation_and_corrections(organizer, db):
    ids = add_players(organizer, NAMES[:4])
    slug = slug_from(create(organizer, ids.values(), courts=1, rounds=3))
    organizer.post(f"/t/{slug}/start")
    m = tournament(db, slug).rounds[0].matches[0]

    for a, b, message in [
        ("11", "11", "Only one team can reach 11"),
        ("12", "3", "between 0 and 11"),
        ("11", "", "Enter a score for both teams"),
        ("x", "3", "Enter a score for both teams"),
    ]:
        r = organizer.post(f"/t/{slug}/match/{m.id}", data={"score_a": a, "score_b": b})
        assert message in r.text, (a, b)
        db.refresh(m)
        assert m.score_a is None

    organizer.post(f"/t/{slug}/match/{m.id}", data={"score_a": "11", "score_b": "5"})
    organizer.post(f"/t/{slug}/match/{m.id}", data={"score_a": "5", "score_b": "11"})
    db.refresh(m)
    assert (m.score_a, m.score_b) == (5, 11)

    r = organizer.post(f"/t/{slug}/match/{m.id}", data={"score_a": "", "score_b": ""})
    assert "Cleared" in r.text
    db.refresh(m)
    assert m.score_a is None


def test_cannot_score_before_start(organizer, db):
    ids = add_players(organizer, NAMES[:4])
    slug = slug_from(create(organizer, ids.values(), courts=1, rounds=1))
    m = tournament(db, slug).rounds[0].matches[0]
    r = organizer.post(
        f"/t/{slug}/match/{m.id}", data={"score_a": "11", "score_b": "2"}
    )
    assert "Start the tournament" in r.text
    db.refresh(m)
    assert m.score_a is None


def test_match_must_belong_to_tournament(organizer, db):
    ids = add_players(organizer, NAMES[:4])
    one = slug_from(create(organizer, ids.values(), courts=1, rounds=1, name="One"))
    two = slug_from(create(organizer, ids.values(), courts=1, rounds=1, name="Two"))
    organizer.post(f"/t/{one}/start")
    organizer.post(f"/t/{two}/start")
    other = tournament(db, two).rounds[0].matches[0]
    r = organizer.post(
        f"/t/{one}/match/{other.id}", data={"score_a": "1", "score_b": "2"}
    )
    assert r.status_code == 404


def test_public_cannot_change_anything(organizer, client, db):
    ids = add_players(organizer, NAMES[:4])
    slug = slug_from(create(organizer, ids.values(), courts=1, rounds=1))
    organizer.post(f"/t/{slug}/start")
    m = tournament(db, slug).rounds[0].matches[0]

    page = client.get(f"/t/{slug}/round/1")
    assert page.status_code == 200
    assert 'name="score_a"' not in page.text
    for path in [
        f"/t/{slug}/match/{m.id}",
        f"/t/{slug}/delete",
        f"/t/{slug}/reshuffle",
    ]:
        r = client.post(
            path, data={"score_a": "11", "score_b": "0"}, follow_redirects=False
        )
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
    db.refresh(m)
    assert m.score_a is None
    assert tournament(db, slug) is not None


def test_standings_page_has_share_link_for_organizer(organizer, client, db):
    ids = add_players(organizer, NAMES[:4])
    slug = slug_from(create(organizer, ids.values(), courts=1, rounds=1))
    organizer.post(f"/t/{slug}/start")
    page = organizer.get(f"/t/{slug}")
    assert f"/t/{slug}" in page.text
    assert "<svg" in page.text
    assert "<svg" not in client.get(f"/t/{slug}").text


def test_delete_tournament(organizer, db):
    ids = add_players(organizer, NAMES[:4])
    slug = slug_from(create(organizer, ids.values(), courts=1, rounds=2))
    organizer.post(f"/t/{slug}/start")
    organizer.post(f"/t/{slug}/delete")
    db.expire_all()
    assert db.scalars(select(Tournament)).first() is None
    assert db.scalars(select(Match)).first() is None
    assert len(db.scalars(select(Player)).all()) == 4  # players stay


def test_unknown_pages_404(client):
    assert client.get("/t/nope").status_code == 404
    assert client.get("/t/nope/round/1").status_code == 404
