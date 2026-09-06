"""The ordering layer: a discount that cannot become a boost.

`recommend` used to sort by ``(not grab_now, vorp_rank, not fills_need)``. ``vorp_rank`` is a
unique integer, so the third key was never compared and roster need -- computed correctly and
published correctly -- was discarded at the moment of ordering. These pin the replacement.
"""

from __future__ import annotations

import pytest

from audible.config import LeagueConfig
from audible.draft import ordering


@pytest.fixture
def standard() -> LeagueConfig:
    """Two dedicated RB slots, three WR, one flex, one K, one DEF."""
    return LeagueConfig.model_validate(
        {
            "key": "t", "name": "t", "platform": "sleeper", "league_id": "0",
            "season": 2026, "num_teams": 8,
            "starting_slots": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            "slot_eligibility": {
                "QB": ["QB"], "RB": ["RB"], "WR": ["WR"], "TE": ["TE"],
                "FLEX": ["RB", "WR", "TE"], "K": ["K"], "DEF": ["DEF"],
            },
            "scoring": {"rec": 0.5},
        }
    )


def test_slot_counting_reads_the_league_rather_than_the_slot_name(standard: LeagueConfig) -> None:
    assert ordering.startable_slots(standard, "RB") == 3  # RB, RB, FLEX
    assert ordering.startable_slots(standard, "WR") == 4  # WR, WR, WR, FLEX
    assert ordering.startable_slots(standard, "K") == 1
    assert ordering.dedicated_slots(standard, "RB") == 2
    assert ordering.dedicated_slots(standard, "FLEX") == 0


def test_an_empty_slot_earns_no_bonus(standard: LeagueConfig) -> None:
    """THE REGRESSION THIS EXISTS TO PREVENT.

    Rewarding "fills an unfilled starting slot" is how a defence at VORP #80 beat a receiver
    46 places better in round 7 -- see tests/test_recommend_bench.py. An empty slot is a
    preference until every remaining pick is committed to one, and `recommend`'s `forced`
    filter is what expresses that. The factor must stay out of it.
    """
    every_slot_open = list(standard.starting_slots)
    for position in ("QB", "RB", "WR", "TE", "K", "DEF"):
        assert (
            ordering.marginal_start_factor(
                position, config=standard, unfilled=every_slot_open, held_counts={}
            )
            == 1.0
        )
    # ...and the same when nothing is open. Emptiness is simply not an input.
    for position in ("RB", "WR"):
        assert (
            ordering.marginal_start_factor(
                position, config=standard, unfilled=[], held_counts={}
            )
            == 1.0
        )


def test_the_factor_is_never_above_one(standard: LeagueConfig) -> None:
    """The cap is what makes it arithmetically incapable of floating a specialist."""
    for position in sorted(standard.positions):
        for held in range(0, 10):
            factor = ordering.marginal_start_factor(
                position, config=standard, unfilled=[], held_counts={position: held}
            )
            assert 0.0 < factor <= 1.0


def test_a_second_kicker_or_defence_is_worth_almost_nothing(standard: LeagueConfig) -> None:
    """One slot, already held: he starts in approximately no weeks, whatever his value."""
    for position in ("K", "DEF", "QB"):
        held = ordering.marginal_start_factor(
            position, config=standard, unfilled=[], held_counts={position: 1}
        )
        assert held == ordering.UNSTARTABLE_FACTOR


def test_surplus_at_a_multi_slot_position_decays_rather_than_collapsing(
    standard: LeagueConfig,
) -> None:
    """An extra back or receiver still starts sometimes -- byes and injuries -- so it is a
    decay, not the cliff a second kicker falls off."""
    fourth_back = ordering.marginal_start_factor(
        "RB", config=standard, unfilled=[], held_counts={"RB": 3}
    )
    assert ordering.UNSTARTABLE_FACTOR < fourth_back < 1.0


def test_filling_a_slot_never_raises_that_positions_factor(standard: LeagueConfig) -> None:
    """Monotonicity. A roster that grows can only make the next body at that position worth
    less, never more -- otherwise the fix would recommend hoarding."""
    for position in sorted(standard.positions):
        previous = None
        for held in range(0, 10):
            factor = ordering.marginal_start_factor(
                position, config=standard, unfilled=[], held_counts={position: held}
            )
            if previous is not None:
                assert factor <= previous + 1e-9, f"{position} rose at held={held}"
            previous = factor


def test_the_thin_position_outranks_the_deep_one_at_equal_value(
    standard: LeagueConfig,
) -> None:
    """The whole point: identical board value, opposite rosters, different answers."""
    thin_rb = {"RB": 2, "WR": 4}
    thin_wr = {"RB": 4, "WR": 2}
    rb_when_thin = ordering.marginal_start_factor(
        "RB", config=standard, unfilled=[], held_counts=thin_rb
    )
    wr_when_deep = ordering.marginal_start_factor(
        "WR", config=standard, unfilled=[], held_counts=thin_rb
    )
    assert rb_when_thin > wr_when_deep

    rb_when_deep = ordering.marginal_start_factor(
        "RB", config=standard, unfilled=[], held_counts=thin_wr
    )
    wr_when_thin = ordering.marginal_start_factor(
        "WR", config=standard, unfilled=[], held_counts=thin_wr
    )
    assert wr_when_thin > rb_when_deep


def test_a_negative_value_is_the_callers_problem_not_a_sign_flip() -> None:
    """Multiplying a negative by a discount makes it LARGER. The caller clamps at zero, and
    this pins the arithmetic that makes the clamp necessary."""
    assert ordering.effective_score(100.0, 0.5, 0.0) == 50.0
    assert ordering.effective_score(-100.0, 0.5, 0.0) == -50.0  # larger than -100: the trap
    assert ordering.effective_score(100.0, 1.0, 30.0) == 70.0


# --- byes: computed and tested, deliberately NOT wired into the ordering ----------------


class _E:
    """A board entry, reduced to what placement and byes actually read."""

    def __init__(self, pid: str, position: str, team: str, points: float) -> None:
        self.player_id = pid
        self.position = position
        self.eligible_positions = frozenset({position})
        self.team = team
        self.points = points


def _roster() -> list[_E]:
    return [
        _E("rb1", "RB", "AAA", 300), _E("rb2", "RB", "AAA", 290),
        _E("wr1", "WR", "BBB", 280), _E("wr2", "WR", "BBB", 270),
        _E("wr3", "WR", "BBB", 260), _E("te1", "TE", "CCC", 250),
    ]


BYES = {"AAA": 13, "BBB": 5, "CCC": 7, "DDD": 11}


def test_a_shared_bye_costs_more_than_an_unshared_one(standard: LeagueConfig) -> None:
    """LINEAR SLOT-WEEKS DO NOT DISCRIMINATE, WHICH IS WHY THIS IS CONVEX.

    Every player is absent exactly one week, so the total number of empty slot-weeks is
    conserved however the byes fall -- measured, and both candidates scored +1. What makes
    stacking bad is that holes in one week compound: two backs out together empties both
    dedicated RB slots at once, and nothing on the roster can cover either.
    """
    roster = _roster()
    base = ordering.bye_conflict_cost(roster, standard, BYES)
    shared = ordering.bye_conflict_cost(
        [*roster, _E("c", "RB", "AAA", 240)], standard, BYES
    )
    unshared = ordering.bye_conflict_cost(
        [*roster, _E("c", "RB", "DDD", 240)], standard, BYES
    )
    assert shared > unshared > base


def test_the_bye_penalty_is_priced_in_board_points(standard: LeagueConfig) -> None:
    roster = _roster()
    penalty = ordering.bye_conflict_penalty(
        [*roster, _E("c", "RB", "AAA", 240)], standard, BYES, slot_week_points=2.0
    )
    raw = ordering.bye_conflict_cost([*roster, _E("c", "RB", "AAA", 240)], standard, BYES)
    assert penalty == pytest.approx(raw * 2.0)
