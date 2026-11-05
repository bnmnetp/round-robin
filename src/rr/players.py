"""Organizer pages for the player list: add, edit, deactivate, import."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rr.db import Player
from rr.player_import import looks_like_email, decode, import_players
from rr.web import flash, get_db, render, require_organizer

router = APIRouter(dependencies=[Depends(require_organizer)])

MAX_UPLOAD = 1_000_000  # bytes; a club roster is a few KB


def _all_players(db: Session) -> list[Player]:
    return list(
        db.scalars(
            select(Player).order_by(Player.active.desc(), func.lower(Player.name))
        )
    )


def _clean(name: str, email: str) -> tuple[str, str | None, str | None]:
    """Return (name, email, error)."""
    name = " ".join(name.split())[:100]
    email = email.strip().lower() or None
    if not name:
        return name, email, "Name is required."
    if email and not looks_like_email(email):
        return name, email, f"“{email}” isn't an email address."
    return name, email, None


@router.get("/players")
def player_list(request: Request, db: Session = Depends(get_db)):
    return render(request, "players.html", players=_all_players(db))


@router.post("/players")
def add_player(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    name, email, error = _clean(name, email)
    if not error:
        db.add(Player(name=name, email=email))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            error = f"Someone already has the email {email}."
    if error:
        return render(
            request,
            "players.html",
            status_code=400,
            players=_all_players(db),
            error=error,
            form={"name": name, "email": email or ""},
        )
    flash(request, f"Added {name}.")
    return RedirectResponse("/players", status_code=303)


def _get_player(db: Session, player_id: int) -> Player:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(404)
    return player


@router.get("/players/{player_id}/edit")
def edit_form(request: Request, player_id: int, db: Session = Depends(get_db)):
    player = _get_player(db, player_id)
    return render(
        request,
        "player_edit.html",
        player=player,
        form={"name": player.name, "email": player.email or ""},
    )


@router.post("/players/{player_id}/edit")
def edit_player(
    request: Request,
    player_id: int,
    name: str = Form(""),
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    player = _get_player(db, player_id)
    name, email, error = _clean(name, email)
    if not error:
        player.name, player.email = name, email
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            error = f"Someone else already has the email {email}."
    if error:
        return render(
            request,
            "player_edit.html",
            status_code=400,
            player=player,
            error=error,
            form={"name": name, "email": email or ""},
        )
    flash(request, f"Saved {name}.")
    return RedirectResponse("/players", status_code=303)


@router.post("/players/{player_id}/active")
def set_active(
    request: Request,
    player_id: int,
    active: bool = Form(...),
    db: Session = Depends(get_db),
):
    player = _get_player(db, player_id)
    player.active = active
    db.commit()
    flash(request, f"{player.name} is {'active' if active else 'inactive'}.")
    return RedirectResponse("/players", status_code=303)


@router.get("/players/import")
def import_form(request: Request):
    return render(request, "player_import.html")


@router.post("/players/import")
def do_import(
    request: Request,
    file: UploadFile | None = File(None),
    text: str = Form(""),
    db: Session = Depends(get_db),
):
    if file is not None and file.filename:
        data = file.file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            return render(
                request,
                "player_import.html",
                status_code=400,
                error="That file is too big for a player list.",
            )
        text = decode(data)
    if not text.strip():
        return render(
            request,
            "player_import.html",
            status_code=400,
            error="Choose a CSV file or paste some names.",
            text=text,
        )
    result = import_players(db, text)
    return render(request, "player_import.html", result=result)
