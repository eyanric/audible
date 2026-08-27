"""Display-lane signals: descriptive only, and honest about which state they are describing.

Both cases here were real bugs in the first cut, caught by reading the output rather than by
a test -- which is why they are tests now. A draft-night panel that tells you a 23-year-old
rookie has an injury history is worse than one that says nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from upside_and_risk import RB_AGE_FLAG, context_flags  # noqa: E402

YEARS = (2023, 2024, 2025)


def test_a_rookie_is_not_flagged_as_having_missed_time() -> None:
    """Ashton Jeanty: no 2023, no 2024, then a full 17-game 2025. Nothing was missed."""
    flags = context_flags("RB", 23.0, {2025: 17}, YEARS)
    assert not any("missed time" in f for f in flags)
    assert any("not in the league" in f for f in flags)


def test_zero_games_is_treated_as_absence_not_injury() -> None:
    flags = context_flags("WR", 24.0, {2023: 0, 2024: 17, 2025: 17}, YEARS)
    assert not any("missed time" in f for f in flags)


def test_a_real_partial_season_is_flagged() -> None:
    """Christian McCaffrey's four-game 2024 is exactly what this flag is for."""
    flags = context_flags("RB", 30.0, {2023: 16, 2024: 4, 2025: 17}, YEARS)
    assert any("missed time" in f for f in flags)


def test_the_age_flag_names_the_threshold_not_the_player() -> None:
    """'RB 33+' would read as though the cutoff moved with the player. It does not."""
    flags = context_flags("RB", 33.0, dict.fromkeys(YEARS, 17), YEARS)
    age_flag = next(f for f in flags if "cohort" in f)
    assert f"RB {RB_AGE_FLAG}+" in age_flag
    assert "age 33" in age_flag


def test_the_age_flag_is_rb_only_and_respects_the_threshold() -> None:
    assert not context_flags("WR", 34.0, dict.fromkeys(YEARS, 17), YEARS)
    assert not context_flags("RB", RB_AGE_FLAG - 1.0, dict.fromkeys(YEARS, 17), YEARS)
    assert context_flags("RB", float(RB_AGE_FLAG), dict.fromkeys(YEARS, 17), YEARS)


def test_flags_never_produce_a_score() -> None:
    """The contract: this returns human-readable history, never a number to sort on."""
    flags = context_flags("RB", 33.0, {2023: 4, 2024: 17, 2025: 17}, YEARS)
    assert all(isinstance(f, str) for f in flags)
    assert not any(f.replace(".", "").replace("-", "").isdigit() for f in flags)
