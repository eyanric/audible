"""The pick-value objective: off by default, and turn-aware in the way that matters.

The gate it was built for did NOT clear (0 of 3 folds on all three ablation arms), so this
code exists in the display lane only. These tests pin the two properties that make it safe
to keep around: it cannot silently start ordering the board, and its one genuinely novel
behaviour -- pricing the turn differently from an ordinary pick -- is real rather than
asserted in a docstring.
"""

from __future__ import annotations

import pytest

from audible.draft.pickvalue import MODES, OpponentProfile, PickValue

# one receiver-heavy round: 50% of picks go to WR, 25% each to RB and TE
PROFILE = OpponentProfile({1: {"WR": 0.5, "RB": 0.25, "TE": 0.25}})
WIRE = {"WR": 10.0, "RB": 10.0, "TE": 10.0}
POINTS = {"wr1": 100.0, "wr2": 90.0, "wr3": 80.0, "wr4": 70.0, "rb1": 95.0}
POS = {"wr1": "WR", "wr2": "WR", "wr3": "WR", "wr4": "WR", "rb1": "RB"}


def _pv(mode: str = "both") -> PickValue:
    return PickValue(wire_replacement=WIRE, profile=PROFILE, mode=mode)


def test_the_flag_is_off_by_default() -> None:
    """Nothing in production flips this. If the default ever changes, this fails first."""
    assert PickValue(wire_replacement={}, profile=OpponentProfile()).enabled is False


def test_an_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="mode must be one of"):
        PickValue(wire_replacement={}, profile=OpponentProfile(), mode="clever")
    for mode in MODES:
        PickValue(wire_replacement={}, profile=OpponentProfile(), mode=mode)


def test_at_the_turn_the_delay_cost_is_only_the_gap_to_the_next_man() -> None:
    """Seat 8 holding 8 and 9: nobody picks in between, so taking wr1 does not cost wr2.

    This is the whole reason the horizon is MY NEXT PICK rather than the next pick. Priced
    against pick 9, wr1's delay term is the gap to wr2 -- ten points, not ninety.
    """
    pv = _pv("delay")
    scores = pv.score(list(POINTS), POS, POINTS, current_pick=8, my_next_pick=9, rnd=1)
    assert scores["wr1"] == pytest.approx(100.0 - 90.0)


def test_across_a_full_round_the_same_player_is_priced_completely_differently() -> None:
    """Pick 9, horizon 24: fourteen rivals intervene and the position drains."""
    pv = _pv("delay")
    turn = pv.score(list(POINTS), POS, POINTS, current_pick=8, my_next_pick=9, rnd=1)
    across = pv.score(list(POINTS), POS, POINTS, current_pick=9, my_next_pick=24, rnd=1)
    # 14 intervening x 0.5 WR rate = 7 receivers gone, so nothing of this tier survives and
    # the delay term falls back to the wire -- a far larger cost than the turn's ten points.
    assert across["wr1"] > turn["wr1"]
    assert across["wr1"] == pytest.approx(100.0 - WIRE["WR"])


def test_the_candidate_is_excluded_from_his_own_replacement() -> None:
    """Taking him is what removes him; pricing him against himself would zero every pick."""
    pv = _pv("delay")
    s = pv.score(["wr1"], {"wr1": "WR"}, {"wr1": 100.0},
                 current_pick=8, my_next_pick=9, rnd=1)
    assert s["wr1"] == pytest.approx(100.0 - WIRE["WR"])


def test_the_composite_double_counts_and_that_was_predicted() -> None:
    """Recorded in the pre-registration BEFORE the run, and the ablation bore it out.

    `both` subtracts the delay term AND the wire term, and the delay term is itself usually
    at or above the wire. The composite is therefore strictly the harshest of the three, which
    is why it finished worst of the ablation arms rather than best.
    """
    delay = _pv("delay").score(list(POINTS), POS, POINTS,
                               current_pick=9, my_next_pick=24, rnd=1)
    wire = _pv("wire").score(list(POINTS), POS, POINTS,
                             current_pick=9, my_next_pick=24, rnd=1)
    both = _pv("both").score(list(POINTS), POS, POINTS,
                             current_pick=9, my_next_pick=24, rnd=1)
    for pid in POINTS:
        assert both[pid] <= min(delay[pid], wire[pid]) + 1e-9


def test_a_missing_next_pick_means_no_delay_cost() -> None:
    """The last round: there is no next pick, so waiting cannot cost anything."""
    pv = _pv("delay")
    s = pv.score(list(POINTS), POS, POINTS, current_pick=128, my_next_pick=None, rnd=16)
    assert s["wr1"] == pytest.approx(100.0 - 90.0)
