# Round Robin Pickleball — Build Plan

Spec: `round_robin.md` (this directory).

## Decisions

- **Ranking:** if anyone sits out during the tournament (player count isn't a multiple of
  4, or there are more players than court spots), rank by **average points per game
  played**. Otherwise rank by **total points**.
- **Ties share a rank** (1, 2, 2, 4).
- **Scoring:** games are to 11, but a time limit can end a game early. A valid score is
  two integers from 0 to 11 that aren't both 11. Lower scores and ties (7–7) are
  accepted.
- **Hosted.** The organizer runs it from an iPhone or iPad, so the design is
  touch-first. Players can view standings read-only.
- **The schedule is generated once, at the start.** No late arrivals, so no
  mid-event regeneration.

## Stack

- **FastAPI + Jinja2**, server-rendered pages, plain HTML forms, a little vanilla JS
  (select-all checkboxes, filter box, score steppers).
- **SQLite** through SQLAlchemy 2.0 (sync). `create_all` on startup.
- **uv** project, **pytest** for tests, **black** for formatting.
- **Deploy:** a single Docker container with the SQLite file on a mounted volume, behind
  HTTPS.

```
rr/
  pyproject.toml
  Dockerfile
  src/rr/
    main.py          # FastAPI app, routes
    auth.py          # organizer password -> signed session cookie
    db.py            # engine, session, models
    scheduler.py     # pure Python, no DB or web imports
    standings.py     # ranking logic
    csv_import.py
    templates/ static/
  tests/
```

## Access

- **Organizer:** one password from an env var (`RR_ADMIN_PASSWORD`). Logging in sets a
  signed, long-lived cookie so the iPhone stays logged in all day. Only the organizer can
  manage players, create tournaments, and enter scores.
- **Public:** the standings and schedule pages for a tournament are viewable without
  logging in. The organizer can share that link or show a QR code for it.

## Data model

| Table | Columns |
|---|---|
| `player` | id, name, email (unique, nullable), active |
| `tournament` | id, name, date, num_courts, num_rounds, status (setup / in_progress / done), public_slug |
| `tournament_player` | tournament_id, player_id |
| `round` | id, tournament_id, number, status (scheduled / scored) |
| `match` | id, round_id, court, a1, a2, b1, b2 (player ids), score_a, score_b (nullable until reported) |
| `bye` | round_id, player_id |

Standings are computed from `match`, not stored, so correcting a score automatically
fixes everything after it.

## The scheduler (the hard part — build and test this first)

A pure function:

```python
schedule(players, num_courts, num_rounds, seed=None) -> list[Round]
```

**Status: built** — `src/rr/scheduler.py`, `tests/test_scheduler.py`.

**Who plays each round.** Seats per round = `min(4 * courts, 4 * (n // 4))`; everyone else
sits out. Fairness is a hard constraint at every point in the tournament: after any round,
sit-out counts differ by at most 1, and nobody sits back to back unless more than half
the players sit every round. A block rotation gives the starting sit-outs. A plain
rotation repeats the same foursomes, though (6 players / 1 court put the same four on
court every third round), so the annealer also chooses who sits when (see moves below).

**Who plays with whom.** Score a candidate schedule with a cost over pair counts:

- **partners**: for each pair partnered *k* times, add `W_P * C(k, 2)`. This is heavily
  weighted, so a repeat partner happens only when it can't be avoided.
- **opponents**: for each pair opposed *k* times, add `W_O * C(k, 2)`, to spread out
  who you face.
- **court-mates** (partner or opponent): `W_C * C(k, 2)`. This is what stops the "same
  four rotating" problem.

Weights: `W_P = 30, W_O = 3, W_C = 5`. A partner weight of 100 also never repeated
partners, but the search couldn't climb back over it to reach better opponent spreads.
At 30, 8 players over 7 rounds finds the perfect schedule (every pair partners once and
opposes twice) on every seed tried.

**Search.** Simulated annealing over the whole schedule, with 4 restarts, keeping the
best. There are three kinds of move, and each one's cost change is computed from only
the matches it touches:
- **player swap**: two players in one round, on different teams;
- **team swap**: two teams change courts. Partnerships are kept and only opponents
  change. Without this move the search can't rebalance opponents once partners are all
  distinct;
- **sit-out exchange**: x sits in round A and plays in B, y the reverse; swap them. Sit
  counts are unchanged, and the move is accepted only if prefix fairness and the
  no-back-to-back rule still hold.

Budget: 60k–75k steps per restart. That's 0.5–1 s for small groups, about 1.9 s for
40 players / 10 courts / 12 rounds. The same seed always gives the same schedule, so
store the seed with the tournament.

**Known limits.** Each player gets one partner per game played, so repeats are
unavoidable once games per player exceed `n − 1`. The setup page warns before the
schedule is generated.

**Tests** (pytest, fixed seeds):
- Structural: every playing player appears exactly once per round, courts ≤ num_courts,
  sit-out counts differ by at most 1, and no back-to-back sit-outs when that's avoidable.
- Quality: 8 players / 2 courts / 7 rounds gives zero partner repeats. 12 / 3 / 11 gives
  zero partner repeats. 16 / 4 / 5 gives zero partner repeats and no court-mate pair more
  than twice. 9 players / 2 courts / 9 rounds is a sit-out case, so check the sit-out
  spread and the partner repeats.
- A quality-report helper (max partner repeats, opponent histogram, sit-out spread),
  which the schedule page also shows.

## Standings

- Per player: points (total of their team's scores), games played, wins, average.
- **Ranking mode:** `average` if the tournament has any sit-outs, otherwise `total`.
  This is decided once from the schedule. The page says which mode it is using
  ("Ranked by average points per game because some players sat out").
- **Shared ranks:** standard competition ranking. Sort by the ranking key; equal keys
  get the same rank, and the next rank skips. Averages are compared as exact fractions
  (`Fraction(points, games)`) so float rounding can't break or create a tie. Display
  them to one decimal place.
- A tied game (time limit) counts as a win for neither team. Points still count.

## Pages (designed for iPhone first)

Large tap targets, single-column layout, `inputmode="numeric"`, nothing that needs
hover. Use Safari's safe-area insets so nothing hides behind the notch or home bar.

1. **Login** (`/login`): password only.
2. **Players** (`/players`): list with a search box, plus add, edit, and deactivate.
   **Import:** upload a CSV (iOS Files picker works with a plain file input) *or* paste
   lines of `name,email` into a textarea, which is easier on a phone. Upsert by email (by
   name when there's no email), then show a summary: added, updated, skipped with
   reasons.
3. **New tournament** (`/tournaments/new`): name, date, courts and rounds (steppers),
   and a player checklist with filter and select all/none. A live summary at the bottom:
   "18 players, 4 courts → 16 play, 2 sit each round; ranked by average", plus the
   partner-repeat warning. **Generate schedule** shows a preview with the quality
   report. **Start** locks it in.
4. **Round** (`/t/{id}/round/{n}`): one card per court, for example "Court 1 — Ann &
   Bob vs Cy & Di". Each team's score field has −/+ buttons and is limited to 0–11, with
   a sit-out list below. Each court saves on its own, since games finish at different
   times. Saving the round's last court leads to standings.
5. **Standings** (`/t/{id}/standings`, public): rank, name, points or average, games,
   wins. Organizers also see a **Next round** button. When the last round is scored,
   the page shows "Final" and gets a print/share-friendly layout.
6. **Schedule** (`/t/{id}/schedule`, public): every round at once, so players can see
   where they're headed next.
7. **Fix a score**: any scored match can be edited from the round page, and standings
   recompute.

## Build order

All built (2026-11-05), except trying it on a real iPhone and the deploy itself.

1. ✅ Project skeleton.
2. ✅ Scheduler + tests.
3. ✅ Standings/ranking + tests.
4. ✅ Organizer login.
5. ✅ Players page + CSV/paste import + tests.
6. ✅ Tournament setup → schedule preview → score entry → standings → final.
7. ✅ Public schedule/standings links, share QR code, score corrections.
8. ✅ Dockerfile + README. ⬜ Deploy. ⬜ Try the full flow on an actual iPhone.

### Changes from the plan while building

- **No "Finish round" button.** A round is complete when its last court is
  saved, and that save goes straight to the standings. One less tap, and nothing
  to forget.
- **Unranked until they've played.** In average mode, someone who sat out the only
  round so far has no average. They show "—" at the bottom instead of being
  ranked last on 0.0.
- **"Highlight a player"** on the schedule, round and standings pages. A player
  picks their own name once (remembered on their phone) and sees which court
  they're on.
- **Clear a score** by emptying both boxes and saving.

## Remaining question

- **Where will it be hosted?** For example, an existing server you run behind Caddy, or
  something like Fly.io or Render. This only affects step 8. The app itself is a single
  container plus one SQLite file either way.
