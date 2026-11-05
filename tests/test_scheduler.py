import pytest

from rr.scheduler import (
    partner_repeats_unavoidable,
    quality,
    schedule,
    seats_per_round,
)

# Structural checks don't need a good schedule, just a valid one, so they use a
# small budget to keep the suite quick.
FAST = dict(restarts=1, iterations=5_000)

SIZES = [
    (4, 1, 3),
    (5, 1, 5),
    (6, 1, 8),
    (7, 2, 6),  # more courts than players can fill
    (9, 2, 9),
    (11, 1, 6),  # 7 of 11 sit each round: back-to-back unavoidable
    (12, 3, 11),
    (13, 3, 8),
    (18, 4, 12),
    (23, 5, 9),
]


def check_valid(rounds, players, num_courts, num_rounds):
    n = len(players)
    seats = seats_per_round(n, num_courts)
    k = n - seats
    assert [r.number for r in rounds] == list(range(1, num_rounds + 1))

    sat = {p: [] for p in players}
    for rnd in rounds:
        assert [m.court for m in rnd.matches] == list(range(1, seats // 4 + 1))
        on_court = [p for m in rnd.matches for p in m.players]
        assert len(on_court) == seats
        assert len(rnd.sitting_out) == k
        # everyone is exactly once on court or sitting out
        assert sorted(on_court + list(rnd.sitting_out)) == sorted(players)
        for p in rnd.sitting_out:
            sat[p].append(rnd.number)

        # Prefix fairness: after every round, sit-out counts differ by <= 1,
        # so nobody sits twice before everyone has sat once.
        counts = [sum(1 for r in sat[p] if r <= rnd.number) for p in players]
        assert max(counts) - min(counts) <= 1

    if 2 * k <= n:
        for p, rs in sat.items():
            assert all(b - a > 1 for a, b in zip(rs, rs[1:])), (p, rs)


@pytest.mark.parametrize("n,courts,rounds", SIZES)
def test_schedule_is_valid(n, courts, rounds):
    players = list(range(100, 100 + n))
    for seed in range(3):
        check_valid(
            schedule(players, courts, rounds, seed=seed, **FAST),
            players,
            courts,
            rounds,
        )


def test_same_seed_same_schedule():
    players = list(range(10))
    assert schedule(players, 2, 6, seed=7, **FAST) == schedule(
        players, 2, 6, seed=7, **FAST
    )
    assert schedule(players, 2, 6, seed=7, **FAST) != schedule(
        players, 2, 6, seed=8, **FAST
    )


def test_any_hashable_player_ids():
    players = ["Ann", "Bob", "Cy", "Di", "Ed"]
    rounds = schedule(players, 1, 5, seed=1, **FAST)
    check_valid(rounds, players, 1, 5)


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        schedule([1, 2, 3], 1, 3)
    with pytest.raises(ValueError):
        schedule([1, 2, 3, 3], 1, 3)
    with pytest.raises(ValueError):
        schedule([1, 2, 3, 4], 0, 3)
    with pytest.raises(ValueError):
        schedule([1, 2, 3, 4], 1, 0)


# Quality checks use the default budget. They are what the app actually runs.


def test_eight_players_seven_rounds_is_perfect():
    """A perfect schedule exists: every pair partners once and opposes twice."""
    players = list(range(8))
    q = quality(schedule(players, 2, 7, seed=0), players)
    assert q.partner_counts == {1: 28}
    assert q.opponent_counts == {2: 28}


def test_twelve_players_eleven_rounds_no_repeat_partners():
    players = list(range(12))
    q = quality(schedule(players, 3, 11, seed=0), players)
    assert q.partner_counts == {1: 66}  # every pair exactly once
    assert q.max_opponent <= 3


def test_sixteen_players_five_rounds_everyone_new():
    players = list(range(16))
    q = quality(schedule(players, 4, 5, seed=0), players)
    assert q.max_partner == 1
    assert q.max_courtmate == 1  # never share a court with anyone twice


def test_sit_outs_vary_the_foursomes():
    """6 players on 1 court: 2 sit each round. A plain rotation of sit-outs
    puts the same four on court every third round."""
    players = list(range(6))
    q = quality(schedule(players, 1, 6, seed=0), players)
    assert q.max_partner == 1
    assert q.max_opponent <= 2


def test_nine_players_two_courts():
    players = list(range(9))
    q = quality(schedule(players, 2, 9, seed=0), players)
    assert q.max_partner == 1
    assert set(q.sit_outs.values()) == {1}
    assert q.max_courtmate <= 4


def test_unavoidable_repeats_are_minimal():
    # 8 players x 10 rounds needs 40 partnerships from 28 pairs: at least 12
    # pairs must partner twice, and none should need three times.
    players = list(range(8))
    q = quality(schedule(players, 2, 10, seed=0), players)
    assert q.repeat_partner_pairs == 12
    assert q.max_partner == 2


@pytest.mark.parametrize(
    "n,courts,rounds,expected",
    [
        (8, 2, 7, False),
        (8, 2, 8, True),  # 32 partnerships > 28 pairs
        (6, 1, 6, False),
        (6, 1, 8, True),  # someone plays 6 games with only 5 possible partners
        (4, 1, 3, False),
        (4, 1, 4, True),
        (12, 3, 11, False),
        (12, 3, 12, True),
        (40, 10, 12, False),
        (3, 1, 3, False),  # can't schedule at all, so not a repeat question
    ],
)
def test_partner_repeats_unavoidable(n, courts, rounds, expected):
    assert partner_repeats_unavoidable(n, courts, rounds) is expected
