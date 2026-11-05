from fractions import Fraction

import pytest

from rr.standings import (
    AVERAGE,
    TOTAL,
    ScoredMatch,
    ranking_mode,
    score_error,
    standings,
)


def m(a, b, sa, sb):
    return ScoredMatch(tuple(a), tuple(b), sa, sb)


def table(rows):
    return [(r.rank, r.player, r.points, r.games, r.wins, r.tied) for r in rows]


def test_each_player_gets_team_points():
    rows = standings("ABCD", [m("AB", "CD", 11, 7)], TOTAL)
    assert table(rows) == [
        (1, "A", 11, 1, 1, True),
        (1, "B", 11, 1, 1, True),
        (3, "C", 7, 1, 0, True),
        (3, "D", 7, 1, 0, True),
    ]


def test_points_accumulate_across_rounds():
    games = [
        m("AB", "CD", 11, 7),
        m("AC", "BD", 9, 11),
        m("AD", "BC", 11, 4),
    ]
    rows = standings("ABCD", games, TOTAL)
    assert [(r.player, r.points, r.wins) for r in rows] == [
        ("A", 31, 2),
        ("D", 29, 2),
        ("B", 26, 2),
        ("C", 20, 0),
    ]
    assert [r.rank for r in rows] == [1, 2, 3, 4]
    assert not any(r.tied for r in rows)


def test_shared_rank_skips_next():
    games = [m("AB", "CD", 11, 7), m("EF", "GH", 11, 5)]
    rows = standings("ABCDEFGH", games, TOTAL)
    assert [(r.player, r.rank) for r in rows] == [
        ("A", 1),
        ("B", 1),
        ("E", 1),
        ("F", 1),
        ("C", 5),
        ("D", 5),
        ("G", 7),
        ("H", 7),
    ]


def test_ties_keep_input_order():
    rows = standings(
        ["Zed", "Amy", "Bo", "Cy"], [m(["Zed", "Amy"], ["Bo", "Cy"], 5, 5)], TOTAL
    )
    assert [r.player for r in rows] == ["Zed", "Amy", "Bo", "Cy"]
    assert {r.rank for r in rows} == {1}


def test_tied_game_is_no_ones_win():
    rows = standings("ABCD", [m("AB", "CD", 8, 8)], TOTAL)
    assert all(r.wins == 0 and r.points == 8 for r in rows)


def test_average_mode_doesnt_punish_sitting_out():
    # E sat out one of the three rounds but averages more.
    games = [
        m("AB", "CD", 11, 9),
        m("AE", "BC", 11, 3),
        m("DE", "AC", 11, 6),
    ]
    total = standings("ABCDE", games, TOTAL)
    average = standings("ABCDE", games, AVERAGE)
    assert total[0].player == "A"  # 28 points in 3 games
    assert average[0].player == "E"  # 22 points in 2 games = 11.0
    assert [(r.player, r.average) for r in average] == [
        ("E", 11),
        ("D", 10),
        ("A", Fraction(28, 3)),
        ("B", 7),
        ("C", 6),
    ]


def test_average_ties_are_exact():
    # 10/3 and 20/6 are equal; floats would agree here, but 1/3 + 1/3 + 1/3
    # style sums are exactly where floats go wrong. Fractions never do.
    games = [
        m("AB", "CD", 3, 0),
        m("AB", "CD", 3, 0),
        m("AB", "CD", 4, 0),
        m("EF", "GH", 3, 0),
        m("EF", "GH", 3, 0),
        m("EF", "GH", 4, 0),
        m("EF", "GH", 3, 0),
        m("EF", "GH", 3, 0),
        m("EF", "GH", 4, 0),
    ]
    rows = standings("ABEFCDGH", games, AVERAGE)
    assert rows[0].average == rows[2].average == Fraction(10, 3)
    assert [r.rank for r in rows[:4]] == [1, 1, 1, 1]


def test_no_games_yet():
    assert [r.rank for r in standings("ABCD", [], TOTAL)] == [1, 1, 1, 1]
    # With sit-outs there's no average to rank by until someone plays.
    assert [r.rank for r in standings("ABCD", [], AVERAGE)] == [None] * 4


def test_sat_out_first_round_is_unranked_not_last():
    rows = standings("EABCD", [m("AB", "CD", 11, 0)], AVERAGE)
    assert [(r.player, r.rank) for r in rows] == [
        ("A", 1),
        ("B", 1),
        ("C", 3),
        ("D", 3),
        ("E", None),
    ]


def test_unknown_mode():
    with pytest.raises(ValueError):
        standings("ABCD", [], "median")


@pytest.mark.parametrize(
    "players,courts,mode",
    [
        (8, 2, TOTAL),
        (9, 2, AVERAGE),
        (8, 1, AVERAGE),  # more players than one court holds
        (12, 5, TOTAL),  # spare courts are fine
        (10, 3, AVERAGE),
    ],
)
def test_ranking_mode(players, courts, mode):
    assert ranking_mode(players, courts) == mode


@pytest.mark.parametrize(
    "a,b,ok",
    [
        (11, 7, True),
        (0, 11, True),
        (11, 10, True),  # first to 11, no win-by-2
        (6, 4, True),  # time limit
        (5, 5, True),  # time limit tie
        (0, 0, True),
        (11, 11, False),
        (12, 10, False),
        (-1, 11, False),
    ],
)
def test_score_error(a, b, ok):
    assert (score_error(a, b) is None) is ok
