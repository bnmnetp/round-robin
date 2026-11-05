# Round Robin

A web app for running round robin pickleball (doubles) tournaments from a phone.

- Import players from a CSV, or paste names, then tick who's playing today.
- Pick the number of courts and rounds. The app schedules every round up front:
  - Nobody partners the same person twice unless that can't be avoided, and you
    see a warning before you start when it can't.
  - Opponents are spread out, so the same four don't keep meeting.
  - Sit-outs are fair at every point in the tournament: counts stay within one of
    each other, and nobody sits out two rounds in a row.
- Enter each court's score as its game finishes. Games are to 11, and a lower
  score is fine when time runs out.
- Each player earns their team's points. Standings are ranked by total points,
  or by average points per game when some players sit out. Tied players share a
  rank.
- Players follow along on their own phones with a read-only link or QR code.

## Run it locally

```bash
uv sync
RR_ADMIN_PASSWORD=pick-one RR_HTTPS_ONLY=0 \
  uv run uvicorn --factory rr.main:create_app --reload
```

Open <http://localhost:8000>, tap **Organizer**, and log in.

## Settings

| Variable | Default | |
|---|---|---|
| `RR_ADMIN_PASSWORD` | *(none)* | Organizer password. Nobody can log in until it's set. |
| `RR_SECRET_KEY` | random | Signs the login cookie. Set it to a long random string, or the organizer is logged out whenever the server restarts. `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `RR_DATABASE_URL` | `sqlite:///rr.db` | The Docker image uses `sqlite:////data/rr.db`. |
| `RR_HTTPS_ONLY` | `1` | Login cookie sent over HTTPS only. Use `0` for local development over plain HTTP. |

## Deploy

The app is one container plus one SQLite file. Put it behind a proxy that
terminates HTTPS:

```bash
docker build -t round-robin .
docker run -d --name round-robin --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v round-robin-data:/data \
  -e RR_ADMIN_PASSWORD=... -e RR_SECRET_KEY=... \
  round-robin
```

Caddy, for example:

```
rr.example.org {
    reverse_proxy 127.0.0.1:8000
}
```

The container trusts `X-Forwarded-*` headers so that share links and QR codes
use the public `https://` address. Don't expose port 8000 directly to the
internet. Back up by copying `/data/rr.db` (use `sqlite3 rr.db ".backup copy.db"`
while it's running).

## Develop

```bash
uv run pytest      # ~15 s
uv run black src tests
```

- `src/rr/scheduler.py`: the scheduling algorithm, with notes on why it's built
  the way it is. Pure Python; see `tests/test_scheduler.py`.
- `src/rr/standings.py`: score rules and ranking.
- `src/rr/player_import.py`: CSV and pasted-list parsing.
- `src/rr/players.py`, `src/rr/tournaments.py`: the web routes.
- `src/rr/templates/`, `src/rr/static/`: server-rendered pages and a little JS.
  Every page works without the JS.

`PLAN.md` has the design decisions.
