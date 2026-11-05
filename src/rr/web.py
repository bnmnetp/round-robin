"""Shared web plumbing: templates, DB sessions, organizer auth, flash messages."""

from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")


def _one_decimal(value: Fraction) -> str:
    return f"{float(value):.1f}"


templates.env.filters["one_decimal"] = _one_decimal


class LoginRequired(Exception):
    pass


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.Session() as db:
        yield db


def is_organizer(request: Request) -> bool:
    return request.session.get("organizer") is True


def require_organizer(request: Request) -> None:
    if not is_organizer(request):
        raise LoginRequired()


def flash(request: Request, message: str, kind: str = "ok") -> None:
    # Assign rather than append: the session cookie is only rewritten when a
    # key is set, so appending to the existing list would be silently lost.
    request.session["flash"] = request.session.get("flash", []) + [[kind, message]]


def render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("organizer", is_organizer(request))
    context["flashes"] = request.session.pop("flash", [])
    return templates.TemplateResponse(request, name, context, status_code=status_code)
