"""The one-scoring rule, guarded on the path the backtest actually uses.

League B pays WR and TE 0.5 a reception and a running back NOTHING. A backtest that
flattened that to uniform half-PPR or full PPR would not look broken -- it would quietly
answer a question about a different league, and every arm and every label would move
together so no internal comparison would catch it.

tests/test_scoring.py owns the arithmetic. These own the guard: that the backtest refuses
to run at all when the rule is not in force.
"""

from __future__ import annotations

import pytest

from audible.backtest.arms import (
    Arm,
    ScoringRuleViolation,
    assert_one_scoring,
    blended_arm,
    rb_reception_points,
)
from audible.config import LeagueConfig


def test_an_rb_reception_contributes_zero_points(espn_config: LeagueConfig) -> None:
    """Through `score_stat_line` on the real weights, not by reading the table back."""
    assert rb_reception_points(espn_config) == 0.0


def test_a_wr_reception_contributes_half_a_point(espn_config: LeagueConfig) -> None:
    from audible.scoring.engine import score_stat_line

    assert score_stat_line({"rec": 1.0}, espn_config.scoring_for("WR")) == 0.5
    assert score_stat_line({"rec": 1.0}, espn_config.scoring_for("TE")) == 0.5


def test_the_guard_passes_for_the_real_league(espn_config: LeagueConfig) -> None:
    assert_one_scoring(espn_config)  # must not raise


def test_uniform_half_ppr_is_rejected_loudly(espn_config: LeagueConfig) -> None:
    """The exact failure the guard exists for: one flat table for every position."""
    flat = espn_config.model_copy(update={"scoring_by_position": {}})
    with pytest.raises(ScoringRuleViolation, match="RB rec must be 0.0"):
        assert_one_scoring(flat)


def test_full_ppr_is_rejected_loudly(espn_config: LeagueConfig) -> None:
    full = espn_config.model_copy(
        update={"scoring": {**espn_config.scoring, "rec": 1.0}, "scoring_by_position": {}}
    )
    with pytest.raises(ScoringRuleViolation):
        assert_one_scoring(full)


def test_the_models_silence_changes_nothing() -> None:
    """A player the opportunity model never saw keeps B's opinion of him, exactly.

    Stated as: if the model saw NOBODY, C is B. That is the property that stops C quietly
    penalising every rookie for having no prior season, which would look like the model
    disliking rookies rather than the model not knowing them.
    """
    b = Arm("B", {"a": 1.0, "b": 2.0, "c": 3.0}, approximate=True)
    c = blended_arm(b, Arm("C2", {}), lam=0.5)
    assert c.rank_by_id == b.rank_by_id
    assert c.approximate is b.approximate


def test_c_moves_a_player_the_model_likes_past_one_it_does_not() -> None:
    b = Arm("B", {"liked": 3.0, "disliked": 1.0})
    c2 = Arm("C2", {"liked": 1.0, "disliked": 50.0})
    c = blended_arm(b, c2, lam=0.5)
    assert b.rank_by_id["disliked"] < b.rank_by_id["liked"]      # B preferred the other one
    assert c.rank_by_id["liked"] < c.rank_by_id["disliked"]      # the adjustment flipped it


def test_blending_at_lambda_zero_is_exactly_b() -> None:
    b = Arm("B", {"a": 1.0, "b": 2.0, "c": 3.0})
    c2 = Arm("C2", {"a": 3.0, "b": 2.0, "c": 1.0})
    assert blended_arm(b, c2, lam=0.0).rank_by_id == b.rank_by_id


def test_pairwise_accuracy_is_within_position_and_skips_ties() -> None:
    from audible.backtest.metrics import pairwise_accuracy

    rank = {"wr1": 1.0, "wr2": 2.0, "rb1": 3.0}
    actual = {"wr1": 100.0, "wr2": 50.0, "rb1": 999.0}
    position = {"wr1": "WR", "wr2": "WR", "rb1": "RB"}
    acc, pairs = pairwise_accuracy(["wr1", "wr2", "rb1"], rank, actual, position)
    # Only the WR pair is comparable; the RB is alone in his group and forms no pair.
    assert pairs == 1
    assert acc == 1.0

    tied = {"wr1": 100.0, "wr2": 100.0, "rb1": 999.0}
    acc, pairs = pairwise_accuracy(["wr1", "wr2", "rb1"], rank, tied, position)
    assert pairs == 0
    assert acc == 0.5
