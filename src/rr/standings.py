"""Scoring rules and standings.

Each player earns the points their team scored in every game they played. If
anyone sits out during a tournament, players are ranked by average points per
game, so sitting out doesn't cost anyone. Otherwise they're ranked by total
points. Tied players share a rank.

Pure Python: no database or web imports.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction

from rr.scheduler import seats_per_round

TOTAL = "total"
AVERAGE = "average"

GAME_TO = 11


def ranking_mode(num_players: int, num_courts: int) -> str:
    """Average points per game when anyone has to sit out, total points otherwise."""
    return AVERAGE if seats_per_round(num_players, num_courts) < num_players else TOTAL


def score_error(score_a: int, score_b: int) -> str | None:
    """Why a reported score is impossible, or None if it's fine.

    Games are to 11, but a time limit can end one early, so any score from 0 to
    11 is accepted, ties included. The only impossible results are numbers out of
    range and both teams reaching 11.
    """
    for s in (score_a, score_b):
        if not 0 <= s <= GAME_TO:
            return f"Scores must be between 0 and {GAME_TO}."
    if score_a == score_b == GAME_TO:
        return f"Only one team can reach {GAME_TO}."
    return None


@dataclass(frozen=True)
class ScoredMatch:
    team_a: tuple[Hashable, Hashable]
    team_b: tuple[Hashable, Hashable]
    score_a: int
    score_b: int


@dataclass
class Standing:
    player: Hashable
    rank: int | None = None  # None: no games yet, so no average to rank by
    tied: bool = False
    points: int = 0
    games: int = 0
    wins: int = 0

    @property
    def average(self) -> Fraction:
        return Fraction(self.points, self.games) if self.games else Fraction(0)


def standings(
    players: Sequence[Hashable], matches: Iterable[ScoredMatch], mode: str
) -> list[Standing]:
    """Players from best to worst.

    Tied players share a rank, and the next rank skips (1, 2, 2, 4). Within a
    tie, players keep the order they were passed in, so pass them sorted by
    name. Averages are exact fractions, so rounding can't break or create ties.
    A tied game (from a time limit) is a win for neither team.

    In average mode, a player who hasn't played yet (they sat out the only
    round so far) has no average. They're listed last with no rank, rather
    than ranked last on an average of zero.
    """
    if mode not in (TOTAL, AVERAGE):
        raise ValueError(f"unknown ranking mode {mode!r}")
    rows = {p: Standing(p) for p in players}
    for m in matches:
        for team, own, other in (
            (m.team_a, m.score_a, m.score_b),
            (m.team_b, m.score_b, m.score_a),
        ):
            for p in team:
                row = rows[p]
                row.points += own
                row.games += 1
                if own > other:
                    row.wins += 1

    def key(row):
        return row.average if mode == AVERAGE else row.points

    ranked = list(rows.values())
    unranked = []
    if mode == AVERAGE:
        unranked = [r for r in ranked if r.games == 0]
        ranked = [r for r in ranked if r.games > 0]
    ordered = sorted(ranked, key=key, reverse=True)
    for i, row in enumerate(ordered):
        if i and key(row) == key(ordered[i - 1]):
            row.rank = ordered[i - 1].rank
            row.tied = ordered[i - 1].tied = True
        else:
            row.rank = i + 1
    return ordered + unranked
