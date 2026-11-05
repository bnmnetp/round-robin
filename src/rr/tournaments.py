"""Tournament pages: setup, schedule, rounds and score entry, standings.

Standings, schedule and round pages are public once a tournament has started,
so players can follow along on their phones. Everything that changes data is
organizer-only.
"""

from __future__ import annotations

import datetime as dt
import random
import secrets

import segno
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rr import scheduler
from rr.db import SETUP, STARTED, Match, Player, Round, Tournament
from rr.standings import (
    AVERAGE,
    GAME_TO,
    ScoredMatch,
    ranking_mode,
    score_error,
    standings,
)
from rr.web import flash, get_db, is_organizer, render, require_organizer

router = APIRouter()
organizer_only = [Depends(require_organizer)]

MAX_COURTS = 50
MAX_ROUNDS = 30


# ---------------------------------------------------------------- helpers


def _get(db: Session, request: Request, slug: str) -> Tournament:
    t = db.scalar(select(Tournament).where(Tournament.slug == slug))
    # A tournament still being set up is private to the organizer.
    if t is None or (t.status == SETUP and not is_organizer(request)):
        raise HTTPException(404)
    return t


def _save_schedule(db: Session, t: Tournament) -> None:
    t.rounds.clear()
    db.flush()
    by_id = {p.id: p for p in t.players}
    for sr in scheduler.schedule(
        sorted(by_id), t.num_courts, t.num_rounds, seed=t.seed
    ):
        rnd = Round(number=sr.number)
        rnd.sitting_out = [by_id[p] for p in sr.sitting_out]
        for m in sr.matches:
            (a1, a2), (b1, b2) = m.team_a, m.team_b
            rnd.matches.append(
                Match(court=m.court, a1_id=a1, a2_id=a2, b1_id=b1, b2_id=b2)
            )
        t.rounds.append(rnd)


def _as_scheduler_rounds(t: Tournament) -> list[scheduler.Round]:
    return [
        scheduler.Round(
            number=r.number,
            matches=tuple(
                scheduler.Match(
                    court=m.court,
                    team_a=(m.a1_id, m.a2_id),
                    team_b=(m.b1_id, m.b2_id),
                )
                for m in r.matches
            ),
            sitting_out=tuple(p.id for p in r.sitting_out),
        )
        for r in t.rounds
    ]


def _standings(t: Tournament):
    by_id = {p.id: p for p in t.players}
    scored = [
        ScoredMatch((m.a1_id, m.a2_id), (m.b1_id, m.b2_id), m.score_a, m.score_b)
        for m in t.matches()
        if m.scored
    ]
    rows = standings([p.id for p in t.players], scored, t.ranking)
    return [(row, by_id[row.player]) for row in rows]


def _summary(n: int, courts: int, rounds: int) -> dict:
    """The numbers the setup page shows about a tournament's shape."""
    seats = scheduler.seats_per_round(n, courts)
    sit = n - seats
    return {
        "players": n,
        "courts_used": seats // 4,
        "playing": seats,
        "sitting": sit,
        "ranking": ranking_mode(n, courts) if seats else None,
        "repeats_unavoidable": scheduler.partner_repeats_unavoidable(n, courts, rounds),
    }


def _qr_svg(url: str) -> str:
    return segno.make(url, error="m").svg_inline(scale=5, border=2)


# ---------------------------------------------------------------- pages


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    query = select(Tournament).order_by(Tournament.date.desc(), Tournament.id.desc())
    if not is_organizer(request):
        query = query.where(Tournament.status == STARTED)
    return render(request, "home.html", tournaments=list(db.scalars(query)))


@router.get("/tournaments/new", dependencies=organizer_only)
def new_form(request: Request, db: Session = Depends(get_db)):
    last = db.scalar(select(Tournament).order_by(Tournament.id.desc()))
    today = dt.date.today()
    form = {
        "name": f"Round robin {today:%b} {today.day}",
        "date": today.isoformat(),
        "courts": last.num_courts if last else 2,
        "rounds": last.num_rounds if last else 7,
        "players": set(),
    }
    return _render_new(request, db, form)


def _render_new(request, db, form, error=None, status_code=200):
    players = list(
        db.scalars(
            select(Player)
            .where(Player.active.is_(True))
            .order_by(func.lower(Player.name))
        )
    )
    return render(
        request,
        "tournament_new.html",
        status_code=status_code,
        players=players,
        form=form,
        error=error,
        max_courts=MAX_COURTS,
        max_rounds=MAX_ROUNDS,
    )


@router.post("/tournaments", dependencies=organizer_only)
def create(
    request: Request,
    name: str = Form(""),
    date: str = Form(""),
    courts: int = Form(...),
    rounds: int = Form(...),
    players: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    name = " ".join(name.split())[:100]
    form = {
        "name": name,
        "date": date,
        "courts": courts,
        "rounds": rounds,
        "players": set(players),
    }
    selected = list(db.scalars(select(Player).where(Player.id.in_(set(players)))))
    try:
        day = dt.date.fromisoformat(date)
    except ValueError:
        day = None

    error = None
    if not name:
        error = "Give the tournament a name."
    elif day is None:
        error = "Pick a date."
    elif not 1 <= courts <= MAX_COURTS:
        error = f"Courts must be between 1 and {MAX_COURTS}."
    elif not 1 <= rounds <= MAX_ROUNDS:
        error = f"Rounds must be between 1 and {MAX_ROUNDS}."
    elif len(selected) < 4:
        error = "Pick at least 4 players."
    if error:
        return _render_new(request, db, form, error=error, status_code=400)

    t = Tournament(
        slug=secrets.token_urlsafe(6),
        name=name,
        date=day,
        num_courts=courts,
        num_rounds=rounds,
        seed=random.randrange(2**31),
        ranking=ranking_mode(len(selected), courts),
        status=SETUP,
    )
    t.players = selected
    db.add(t)
    db.flush()
    _save_schedule(db, t)
    db.commit()
    return RedirectResponse(f"/t/{t.slug}/schedule", status_code=303)


@router.get("/t/{slug}/schedule")
def schedule_page(request: Request, slug: str, db: Session = Depends(get_db)):
    t = _get(db, request, slug)
    quality = None
    if t.status == SETUP:
        quality = scheduler.quality(_as_scheduler_rounds(t), [p.id for p in t.players])
    return render(
        request,
        "schedule.html",
        t=t,
        quality=quality,
        summary=_summary(len(t.players), t.num_courts, t.num_rounds),
    )


@router.post("/t/{slug}/reshuffle", dependencies=organizer_only)
def reshuffle(request: Request, slug: str, db: Session = Depends(get_db)):
    t = _get(db, request, slug)
    if t.status != SETUP:
        raise HTTPException(409, "The tournament has started.")
    t.seed = random.randrange(2**31)
    _save_schedule(db, t)
    db.commit()
    flash(request, "New schedule generated.")
    return RedirectResponse(f"/t/{slug}/schedule", status_code=303)


@router.post("/t/{slug}/start", dependencies=organizer_only)
def start(request: Request, slug: str, db: Session = Depends(get_db)):
    t = _get(db, request, slug)
    if t.status == SETUP:
        t.status = STARTED
        db.commit()
    return RedirectResponse(f"/t/{slug}/round/1", status_code=303)


@router.post("/t/{slug}/delete", dependencies=organizer_only)
def delete(request: Request, slug: str, db: Session = Depends(get_db)):
    t = _get(db, request, slug)
    db.delete(t)
    db.commit()
    flash(request, f"Deleted {t.name}.")
    return RedirectResponse("/", status_code=303)


@router.get("/t/{slug}")
def standings_page(request: Request, slug: str, db: Session = Depends(get_db)):
    t = _get(db, request, slug)
    if t.status == SETUP:
        return RedirectResponse(f"/t/{slug}/schedule", status_code=303)
    public_url = str(request.url_for("standings_page", slug=slug))
    return render(
        request,
        "standings.html",
        t=t,
        rows=_standings(t),
        average=t.ranking == AVERAGE,
        public_url=public_url,
        qr=_qr_svg(public_url) if is_organizer(request) else None,
    )


@router.get("/t/{slug}/round/{number}")
def round_page(request: Request, slug: str, number: int, db: Session = Depends(get_db)):
    t = _get(db, request, slug)
    rnd = next((r for r in t.rounds if r.number == number), None)
    if rnd is None:
        raise HTTPException(404)
    return render(
        request,
        "round.html",
        t=t,
        rnd=rnd,
        game_to=GAME_TO,
        editable=is_organizer(request) and t.status == STARTED,
    )


@router.post("/t/{slug}/match/{match_id}", dependencies=organizer_only)
def report_score(
    request: Request,
    slug: str,
    match_id: int,
    score_a: str = Form(""),
    score_b: str = Form(""),
    db: Session = Depends(get_db),
):
    t = _get(db, request, slug)
    match = db.get(Match, match_id)
    if match is None or match.round.tournament_id != t.id:
        raise HTTPException(404)
    rnd = match.round
    back = f"/t/{slug}/round/{rnd.number}#court-{match.court}"
    if t.status != STARTED:
        flash(request, "Start the tournament before entering scores.", "error")
        return RedirectResponse(back, status_code=303)

    score_a, score_b = score_a.strip(), score_b.strip()
    if not score_a and not score_b:
        match.score_a = match.score_b = None
        db.commit()
        flash(request, f"Cleared the score on court {match.court}.")
        return RedirectResponse(back, status_code=303)
    try:
        a, b = int(score_a), int(score_b)
        error = score_error(a, b)
    except ValueError:
        error = "Enter a score for both teams."
    if error:
        flash(request, f"Court {match.court}: {error}", "error")
        return RedirectResponse(back, status_code=303)

    was_complete = rnd.complete
    match.score_a, match.score_b = a, b
    db.commit()

    if rnd.complete and not was_complete:
        flash(request, f"Round {rnd.number} is complete.")
        return RedirectResponse(f"/t/{slug}", status_code=303)
    flash(request, f"Saved court {match.court}: {a}–{b}.")
    return RedirectResponse(back, status_code=303)
