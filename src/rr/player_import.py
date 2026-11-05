"""Import players from CSV or pasted text.

Accepts what people actually have: a ``name,email`` export with or without a
header, ``first,last,email`` columns, extra columns like phone numbers (when
there's a header to say which is which), or names pasted one per line.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rr.db import Player

NAME_WORDS = {
    "name",
    "full name",
    "player",
    "first",
    "last",
    "first name",
    "last name",
    "firstname",
    "lastname",
}
EMAIL_WORDS = {"email", "e-mail", "email address", "e-mail address"}


@dataclass
class Row:
    line: int
    name: str
    email: str | None


@dataclass
class ImportResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (line, reason)


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")  # Excel adds a BOM
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse(text: str) -> tuple[list[Row], list[tuple[int, str]]]:
    """Return (rows, skipped). Blank lines and a header row are ignored silently.

    With a header row, its column names say which fields are the name and the
    email, and other columns (phone, ...) are ignored. Without one, the field
    containing ``@`` is the email and the rest make up the name.
    """
    rows, skipped = [], []
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    name_cols = email_col = None
    first = True
    for line, raw in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
        fields = [f.strip() for f in raw]
        if not any(fields):
            continue
        if first:
            first = False
            header = [f.lower() for f in fields]
            if not any("@" in f for f in header) and (
                set(header) & (NAME_WORDS | EMAIL_WORDS)
            ):
                name_cols = [i for i, f in enumerate(header) if f in NAME_WORDS]
                email_col = next(
                    (i for i, f in enumerate(header) if f in EMAIL_WORDS), None
                )
                if not name_cols:
                    skipped.append((line, "header has no name column"))
                    return [], skipped
                continue

        if name_cols is not None:
            name = " ".join(
                fields[i] for i in name_cols if i < len(fields) and fields[i]
            )
            email = (
                fields[email_col]
                if email_col is not None and email_col < len(fields)
                else ""
            )
        else:
            emails = [f for f in fields if "@" in f]
            if len(emails) > 1:
                skipped.append((line, "more than one email address"))
                continue
            email = emails[0] if emails else ""
            name = " ".join(f for f in fields if f and "@" not in f)

        if email and not looks_like_email(email):
            skipped.append((line, f"“{email}” isn't an email address"))
            continue
        if not name:
            skipped.append((line, "no name"))
            continue
        rows.append(Row(line, " ".join(name.split())[:100], email.lower() or None))
    return rows, skipped


def looks_like_email(s: str) -> bool:
    local, _, domain = s.partition("@")
    return (
        bool(local) and " " not in s and "@" not in domain and "." in domain.strip(".")
    )


def import_players(db: Session, text: str) -> ImportResult:
    """Add or update players. Match on email when the row has one, otherwise on
    name (ignoring case). Importing someone inactive makes them active again."""
    rows, skipped = parse(text)
    result = ImportResult(skipped=skipped)
    for row in rows:
        player = None
        if row.email:
            player = db.scalar(select(Player).where(Player.email == row.email))
        if player is None:
            # A name match without an email on file is the same person; one
            # with a different email is someone else with the same name.
            player = db.scalar(
                select(Player).where(
                    func.lower(Player.name) == row.name.lower(),
                    Player.email.is_(None) if row.email else True,
                )
            )
        if player is None:
            db.add(Player(name=row.name, email=row.email))
            result.added.append(row.name)
        elif (
            player.name != row.name
            or (row.email and player.email != row.email)
            or not player.active
        ):
            player.name = row.name
            if row.email:
                player.email = row.email
            player.active = True
            result.updated.append(row.name)
        else:
            result.unchanged.append(row.name)
        db.flush()  # so a duplicate later in the file matches this row
    db.commit()
    return result
