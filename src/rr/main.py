"""App factory. Run with ``uvicorn --factory rr.main:create_app``.

Settings come from the environment:

RR_ADMIN_PASSWORD  organizer password (required to log in)
RR_SECRET_KEY      signs the session cookie; set it, or everyone is logged out
                   whenever the server restarts
RR_DATABASE_URL    default ``sqlite:///rr.db``
RR_HTTPS_ONLY      ``1`` (default) sends the session cookie only over HTTPS; set
                   ``0`` for local development over plain HTTP
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from rr import players, tournaments
from rr.db import init_db
from rr.web import HERE, LoginRequired, flash, render

log = logging.getLogger(__name__)

SESSION_DAYS = 30


def create_app(
    database_url: str | None = None,
    admin_password: str | None = None,
    secret_key: str | None = None,
    https_only: bool | None = None,
) -> FastAPI:
    env = os.environ
    database_url = database_url or env.get("RR_DATABASE_URL", "sqlite:///rr.db")
    if admin_password is None:
        admin_password = env.get("RR_ADMIN_PASSWORD", "")
    if secret_key is None:
        secret_key = env.get("RR_SECRET_KEY") or ""
    if not secret_key:
        log.warning("RR_SECRET_KEY is not set; sessions end when the server restarts")
        secret_key = secrets.token_urlsafe(32)
    if https_only is None:
        https_only = env.get("RR_HTTPS_ONLY", "1") != "0"

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.Session = init_db(database_url)
    app.state.admin_password = admin_password

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        max_age=SESSION_DAYS * 24 * 3600,
        same_site="lax",
        https_only=https_only,
    )
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(players.router)
    app.include_router(tournaments.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired):
        target = request.url.path if request.method == "GET" else "/"
        return RedirectResponse(f"/login?next={target}", status_code=303)

    @app.get("/login")
    def login_form(request: Request, next: str = "/"):
        return render(request, "login.html", next=_safe_next(next))

    @app.post("/login")
    def login(request: Request, password: str = Form(""), next: str = Form("/")):
        expected = request.app.state.admin_password
        if expected and hmac.compare_digest(password.encode(), expected.encode()):
            request.session["organizer"] = True
            return RedirectResponse(_safe_next(next), status_code=303)
        error = (
            "Wrong password."
            if expected
            else "No organizer password is configured (RR_ADMIN_PASSWORD)."
        )
        return render(
            request, "login.html", status_code=401, next=_safe_next(next), error=error
        )

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        flash(request, "Logged out.")
        return RedirectResponse("/", status_code=303)

    return app


def _safe_next(target: str) -> str:
    """Only redirect to paths on this site."""
    parts = urlsplit(target)
    # Browsers treat a backslash like a slash, so "/\\host" means "//host".
    if parts.scheme or parts.netloc or not target.startswith("/") or "\\" in target:
        return "/"
    if target.startswith("//"):
        return "/"
    return target
