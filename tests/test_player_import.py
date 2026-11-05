from sqlalchemy import select

from rr.db import Player
from rr.player_import import decode, import_players, parse


def rows(text):
    parsed, skipped = parse(text)
    return [(r.name, r.email) for r in parsed], skipped


def test_name_email_with_header():
    assert rows(
        "Name,Email\nAnn Smith,Ann@Example.com\nBob Jones,bob@example.com\n"
    ) == (
        [("Ann Smith", "ann@example.com"), ("Bob Jones", "bob@example.com")],
        [],
    )


def test_no_header_and_email_in_any_column():
    assert rows("ann@example.com,Ann Smith\nBob Jones,bob@example.com") == (
        [("Ann Smith", "ann@example.com"), ("Bob Jones", "bob@example.com")],
        [],
    )


def test_first_last_email_header():
    text = "First Name,Last Name,Email\nAnn,Smith,ann@example.com\n"
    assert rows(text) == ([("Ann Smith", "ann@example.com")], [])


def test_header_with_extra_columns_ignores_them():
    text = "Name,Phone,Email\nAnn Smith,555-1234,ann@example.com\nBob,,\n"
    assert rows(text) == ([("Ann Smith", "ann@example.com"), ("Bob", None)], [])


def test_names_only_pasted_with_blank_lines_and_spaces():
    text = "\n  Ann   Smith  \n\nBob Jones\n\n"
    assert rows(text) == ([("Ann Smith", None), ("Bob Jones", None)], [])


def test_semicolons_and_tabs():
    assert rows("Ann;ann@example.com\nBob;bob@example.com")[0] == [
        ("Ann", "ann@example.com"),
        ("Bob", "bob@example.com"),
    ]
    assert rows("Ann\tann@example.com\nBob\tbob@example.com")[0] == [
        ("Ann", "ann@example.com"),
        ("Bob", "bob@example.com"),
    ]


def test_quoted_names_with_commas():
    assert rows('"Smith, Ann",ann@example.com\n')[0] == [
        ("Smith, Ann", "ann@example.com")
    ]


def test_skips_bad_rows_with_reasons():
    text = (
        "Ann,ann@example.com\n,nobody@example.com\nCy,cy@nowhere\nDi,a@b.com,c@d.com\n"
    )
    parsed, skipped = rows(text)
    assert parsed == [("Ann", "ann@example.com")]
    assert [line for line, _ in skipped] == [2, 3, 4]


def test_excel_bom():
    assert decode(b"\xef\xbb\xbfName,Email\n") == "Name,Email\n"
    assert decode("Zoë".encode("latin-1")) == "Zoë"


def test_import_adds_updates_and_matches(db):
    first = import_players(db, "Ann Smith,ann@example.com\nBob\n")
    assert first.added == ["Ann Smith", "Bob"]

    # Same email with a new name updates; a name-only row matches by name,
    # ignoring case; a duplicate within the file is only added once.
    second = import_players(
        db, "Ann Smith-Lee,ANN@example.com\nbob\nCy,cy@example.com\nCy,cy@example.com\n"
    )
    assert second.updated == ["Ann Smith-Lee", "bob"]
    assert second.added == ["Cy"]
    assert second.unchanged == ["Cy"]

    players = db.scalars(select(Player).order_by(Player.id)).all()
    assert [(p.name, p.email) for p in players] == [
        ("Ann Smith-Lee", "ann@example.com"),
        ("bob", None),
        ("Cy", "cy@example.com"),
    ]


def test_import_gives_emailless_player_an_email(db):
    import_players(db, "Bob\n")
    result = import_players(db, "Bob,bob@example.com\n")
    assert result.updated == ["Bob"]
    assert db.scalar(select(Player.email)) == "bob@example.com"


def test_same_name_different_email_is_a_different_person(db):
    import_players(db, "Pat Lee,pat1@example.com\n")
    result = import_players(db, "Pat Lee,pat2@example.com\n")
    assert result.added == ["Pat Lee"]


def test_import_reactivates(db):
    import_players(db, "Ann,ann@example.com\n")
    db.scalar(select(Player)).active = False
    db.commit()
    result = import_players(db, "Ann,ann@example.com\n")
    assert result.updated == ["Ann"]
    assert db.scalar(select(Player)).active
