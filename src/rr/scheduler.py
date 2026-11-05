"""Round robin doubles scheduler.

Builds a whole tournament up front: for each round, who sits out and who plays with
and against whom on each court.

Fairness of sit-outs is a hard constraint, held at every point in the tournament:
after any round, sit-out counts differ by at most one. Nobody sits twice before
everyone has sat once. Nobody sits two rounds in a row unless more than half the
players must sit every round.

Everything else is found by simulated annealing over the whole schedule. It
minimises a cost over how often each pair of players has been

* partners     -- weighted most, so a repeat happens only when unavoidable,
* opponents    -- to spread out who you face,
* court-mates  -- partner or opponent; stops the same four people rotating.

Each term is ``weight * C(k, 2)`` for a pair that met ``k`` times. That is zero
for a first meeting and grows quickly with repeats, which also pushes the counts
toward being even.

This module is pure Python and knows nothing about the database or the web app.
Players are any hashable ids.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

# A partner weight of 100 never repeated partners either, but it was a wall the
# search couldn't climb back over. With 8 players / 7 rounds it always settled
# on a lopsided opponent spread. At 30 it finds the perfect schedule (every pair
# partners once and opposes twice) on every seed tried, still with no repeats.
W_PARTNER = 30
W_OPPONENT = 3
W_COURTMATE = 5

T_START = 20.0
T_END = 0.2
TEAM_SWAP_FRACTION = 0.3
SIT_SWAP_FRACTION = 0.15


@dataclass(frozen=True)
class Match:
    court: int  # 1-based
    team_a: tuple[Hashable, Hashable]
    team_b: tuple[Hashable, Hashable]

    @property
    def players(self) -> tuple[Hashable, ...]:
        return self.team_a + self.team_b


@dataclass(frozen=True)
class Round:
    number: int  # 1-based
    matches: tuple[Match, ...]
    sitting_out: tuple[Hashable, ...]


def seats_per_round(num_players: int, num_courts: int) -> int:
    """How many players can play in each round."""
    return 4 * min(num_courts, num_players // 4)


def partner_repeats_unavoidable(
    num_players: int, num_courts: int, num_rounds: int
) -> bool:
    """True when no schedule can avoid someone partnering the same person twice."""
    seats = seats_per_round(num_players, num_courts)
    if seats == 0:
        return False
    total_sit_outs = (num_players - seats) * num_rounds
    most_games = num_rounds - total_sit_outs // num_players
    if most_games > num_players - 1:
        return True
    partner_pairs_needed = (seats // 2) * num_rounds
    return partner_pairs_needed > num_players * (num_players - 1) // 2


def default_iterations(num_players: int, num_courts: int, num_rounds: int) -> int:
    """Annealing steps per restart. Capped so the largest tournaments still
    schedule in a couple of seconds."""
    seats = seats_per_round(num_players, num_courts)
    return min(75_000, max(60_000, 250 * seats * num_rounds))


def schedule(
    players: Sequence[Hashable],
    num_courts: int,
    num_rounds: int,
    seed: int | None = None,
    restarts: int = 4,
    iterations: int | None = None,
) -> list[Round]:
    """Schedule a whole tournament.

    ``iterations`` is the annealing budget per restart; see
    ``default_iterations``. The same arguments always give the same schedule.
    """
    n = len(players)
    if len(set(players)) != n:
        raise ValueError("players must be unique")
    if num_courts < 1 or num_rounds < 1:
        raise ValueError("need at least one court and one round")
    seats = seats_per_round(n, num_courts)
    if seats == 0:
        raise ValueError("need at least 4 players")
    if iterations is None:
        iterations = default_iterations(n, num_courts, num_rounds)

    rng = random.Random(seed)
    best = None
    for _ in range(restarts):
        result = _anneal(n, seats, num_rounds, iterations, random.Random(rng.random()))
        if best is None or result[2] < best[2]:
            best = result
    best_slots, best_sitting, _ = best

    rounds = []
    for r, (slots, sit) in enumerate(zip(best_slots, best_sitting)):
        matches = tuple(
            Match(
                court=m + 1,
                team_a=(players[slots[4 * m]], players[slots[4 * m + 1]]),
                team_b=(players[slots[4 * m + 2]], players[slots[4 * m + 3]]),
            )
            for m in range(len(slots) // 4)
        )
        rounds.append(
            Round(
                number=r + 1,
                matches=matches,
                sitting_out=tuple(players[p] for p in sorted(sit)),
            )
        )
    return rounds


def _initial_sit_outs(
    n: int, seats: int, num_rounds: int, rng: random.Random
) -> list[list[int]]:
    """A fair starting point for who sits out each round.

    Round r takes the next block of ``n - seats`` players from a shuffled order,
    wrapping around. This satisfies every fairness rule, but it repeats the same
    blocks on each pass through the order. The annealer's sit-out exchange
    move breaks that up.
    """
    k = n - seats
    order = list(range(n))
    rng.shuffle(order)
    return [[order[(r * k + i) % n] for i in range(k)] for r in range(num_rounds)]


def _anneal(
    n: int, seats: int, num_rounds: int, iterations: int, rng: random.Random
) -> tuple[list[list[int]], list[list[int]], int]:
    """Simulated annealing over a whole schedule.

    ``slots[r]`` lists round r's players in court order: ``[a1, a2, b1, b2]`` for
    court 1, then court 2, and so on. ``sitting[r]`` lists who sits out. Moves:

    * player swap -- two players in one round, on different teams;
    * team swap   -- two teams in one round, on different courts;
    * sit-out exchange -- x sits in round A and plays in B, y the reverse; swap
      them. Everyone's sit-out count is unchanged.

    Each move's cost change is computed from only the matches it touches.
    Returns ``(slots, sitting, cost)`` for the best schedule seen.
    """
    k = n - seats  # sitting out per round
    sitting = _initial_sit_outs(n, seats, num_rounds, rng)
    sits = [set() for _ in range(n)]  # rounds each player sits out
    slots = []
    for r, sit in enumerate(sitting):
        for p in sit:
            sits[p].add(r)
        group = [p for p in range(n) if r not in sits[p]]
        rng.shuffle(group)
        slots.append(group)
    no_back_to_back = 2 * k <= n

    partner = [0] * (n * n)
    opponent = [0] * (n * n)

    def pair_delta(table, other, i, j, sign, weight):
        # Change one pair's count by +/-1 and return the change in its cost.
        # C(k+1, 2) - C(k, 2) == k.
        idx = i * n + j if i < j else j * n + i
        if sign > 0:
            c, total = table[idx], table[idx] + other[idx]
            table[idx] += 1
            return weight * c + W_COURTMATE * total
        table[idx] -= 1
        c, total = table[idx], table[idx] + other[idx]
        return -(weight * c + W_COURTMATE * total)

    def apply(s, m, sign):
        b = 4 * m
        a1, a2, b1, b2 = s[b], s[b + 1], s[b + 2], s[b + 3]
        return (
            pair_delta(partner, opponent, a1, a2, sign, W_PARTNER)
            + pair_delta(partner, opponent, b1, b2, sign, W_PARTNER)
            + pair_delta(opponent, partner, a1, b1, sign, W_OPPONENT)
            + pair_delta(opponent, partner, a1, b2, sign, W_OPPONENT)
            + pair_delta(opponent, partner, a2, b1, sign, W_OPPONENT)
            + pair_delta(opponent, partner, a2, b2, sign, W_OPPONENT)
        )

    def swap(s, mi, mj, pairs):
        # Swap slot pairs within one round, returning the cost change.
        delta = apply(s, mi, -1)
        if mj != mi:
            delta += apply(s, mj, -1)
        for i, j in pairs:
            s[i], s[j] = s[j], s[i]
        delta += apply(s, mi, +1)
        if mj != mi:
            delta += apply(s, mj, +1)
        return delta

    def put(r, pos, p):
        # Seat player p at slot pos of round r, returning the cost change.
        s = slots[r]
        m = pos // 4
        delta = apply(s, m, -1)
        s[pos] = p
        return delta + apply(s, m, +1)

    def sit_exchange(x, y, a, b):
        # x sits in a and plays in b; y the reverse. Swap them.
        pa, pb = slots[a].index(y), slots[b].index(x)
        delta = put(a, pa, x) + put(b, pb, y)
        sitting[a][sitting[a].index(x)] = y
        sitting[b][sitting[b].index(y)] = x
        sits[x].remove(a)
        sits[x].add(b)
        sits[y].remove(b)
        sits[y].add(a)
        return delta

    def sits_through(p, t):
        return sum(1 for r in sits[p] if r <= t)

    def exchange_is_fair(x, y, a, b):
        # Moving x's sit-out from a to b and y's from b to a. Back-to-back:
        # neither may land next to another of their own sit-outs.
        if no_back_to_back:
            if (b - 1 in sits[x] and b - 1 != a) or (b + 1 in sits[x] and b + 1 != a):
                return False
            if (a - 1 in sits[y] and a - 1 != b) or (a + 1 in sits[y] and a + 1 != b):
                return False
        # Prefix balance: after every round t in [lo, hi), the player who now
        # sits earlier gains one sit-out and the other loses one. That is only
        # allowed when the gainer was at the floor, the loser at the ceiling, and
        # the counts weren't all equal.
        lo, hi = min(a, b), max(a, b)
        gainer, loser = (y, x) if a < b else (x, y)
        for t in range(lo, hi):
            total = k * (t + 1)
            if total % n == 0:
                return False
            floor = total // n
            if sits_through(gainer, t) != floor or sits_through(loser, t) != floor + 1:
                return False
        return True

    cost = 0
    for s in slots:
        for m in range(len(s) // 4):
            cost += apply(s, m, +1)

    def snapshot():
        return [s[:] for s in slots], [s[:] for s in sitting], cost

    best = snapshot()
    teams = seats // 2
    multi_court = seats > 4
    can_exchange = k > 0 and num_rounds > 1

    cooling = (T_END / T_START) ** (1 / iterations)
    temp = T_START

    for _ in range(iterations):
        temp *= cooling
        roll = rng.random()

        if can_exchange and roll < SIT_SWAP_FRACTION:
            a = rng.randrange(num_rounds)
            b = rng.randrange(num_rounds)
            if a == b:
                continue
            x = sitting[a][rng.randrange(k)]
            y = sitting[b][rng.randrange(k)]
            if b in sits[x] or a in sits[y] or not exchange_is_fair(x, y, a, b):
                continue
            delta = sit_exchange(x, y, a, b)
            if delta <= 0 or rng.random() < math.exp(-delta / temp):
                cost += delta
                if cost < best[2]:
                    best = snapshot()
            else:
                sit_exchange(y, x, a, b)  # y now sits in a, x in b: swap back
            continue

        s = slots[rng.randrange(num_rounds)]
        if multi_court and roll < SIT_SWAP_FRACTION + TEAM_SWAP_FRACTION:
            # Move a whole team to another court. Partnerships are untouched;
            # only opponents change. Once partners are all distinct, a player
            # swap always creates a repeat partnership, so this is the cheap
            # way to rebalance opponents.
            t1 = rng.randrange(teams)
            t2 = rng.randrange(teams)
            if t1 // 2 == t2 // 2:
                continue  # same court
            pairs = ((2 * t1, 2 * t2), (2 * t1 + 1, 2 * t2 + 1))
            mi, mj = t1 // 2, t2 // 2
        else:
            i = rng.randrange(seats)
            j = rng.randrange(seats)
            if i // 2 == j // 2:
                continue  # same team: swapping changes nothing
            pairs = ((i, j),)
            mi, mj = i // 4, j // 4

        delta = swap(s, mi, mj, pairs)
        if delta <= 0 or rng.random() < math.exp(-delta / temp):
            cost += delta
            if cost < best[2]:
                best = snapshot()
        else:
            swap(s, mi, mj, pairs)  # every swap is its own inverse

    return best


@dataclass(frozen=True)
class Quality:
    """How well a schedule spreads people out. Pair counts cover every pair of
    players, including pairs who never met."""

    partner_counts: Counter  # times partnered -> number of pairs
    opponent_counts: Counter  # times opposed -> number of pairs
    courtmate_counts: Counter  # times on the same court -> number of pairs
    sit_outs: dict  # player -> rounds sat out
    games: dict  # player -> games played

    @property
    def max_partner(self) -> int:
        return max(self.partner_counts)

    @property
    def repeat_partner_pairs(self) -> int:
        return sum(c for k, c in self.partner_counts.items() if k > 1)

    @property
    def max_opponent(self) -> int:
        return max(self.opponent_counts)

    @property
    def max_courtmate(self) -> int:
        return max(self.courtmate_counts)


def quality(rounds: Sequence[Round], players: Sequence[Hashable]) -> Quality:
    partner: Counter = Counter()
    opponent: Counter = Counter()
    sit_outs = {p: 0 for p in players}
    games = {p: 0 for p in players}

    def key(x, y):
        return frozenset((x, y))

    for rnd in rounds:
        for p in rnd.sitting_out:
            sit_outs[p] += 1
        for m in rnd.matches:
            for p in m.players:
                games[p] += 1
            partner[key(*m.team_a)] += 1
            partner[key(*m.team_b)] += 1
            for x in m.team_a:
                for y in m.team_b:
                    opponent[key(x, y)] += 1

    all_pairs = [
        key(players[i], players[j])
        for i in range(len(players))
        for j in range(i + 1, len(players))
    ]
    return Quality(
        partner_counts=Counter(partner[k] for k in all_pairs),
        opponent_counts=Counter(opponent[k] for k in all_pairs),
        courtmate_counts=Counter(partner[k] + opponent[k] for k in all_pairs),
        sit_outs=sit_outs,
        games=games,
    )
