"""Two stat ids, the same yards, and the league decides which one counts.

ESPN ships BOTH passing-yard stats on every line regardless of which one the league pays --
measured 2026-09-02 on Josh Allen, whose 2025 actual line carries statId 3 = 3668 AND
statId 8 = 139, and whose 2026 projection carries 3944.73 and 157. They are the same yards
counted two ways -- and NOT the same number, because the bucket floors. That difference is
what makes these tests able to tell the two apart; see the fixture note below.

League 6012 pays the bucket. League 485267278 pays the raw stat. So the map has to hold both,
and the moment it does, anything that reads both double-counts every quarterback in the
league. These tests pin the resolution, because the failure mode is silent: a QB scored
without passing yards still looks like a plausible QB, roughly 160 points light.
"""

from __future__ import annotations

from audible.adapters.espn import (
    PASS_YARD_BUCKET,
    RAW_PASS_YARDS_STAT_ID,
    STAT_ID_TO_KEY,
    translate_stat_line,
)

BUCKET_STAT_ID = 8

# THE TWO NUMBERS MUST NOT BE THE SAME NUMBER. The bucket is a FLOOR -- 157 completed 25-yard
# buckets is 3,925 yards of credit against 3,944.73 actual -- and this fixture used to carry
# 3925.0 raw alongside 157 buckets, which is 157 x 25 exactly. Both spellings then read the
# same value, so every test below passed under EITHER preference and flipping the resolution
# failed nothing in this file. The only thing holding it was one captured Josh Allen line in
# test_espn.py: a single point of failure under the check that stops every quarterback in a
# raw-yards league scoring with zero passing yards.
#
# 3944.73 is the real 2026 projection ESPN serves for that line (measured 2026-09-02).
RAW_YARDS = 3944.73
BUCKETS = 157.0
BUCKETED_YARDS = BUCKETS * 25.0  # 3925.0 -- the same yards, floored to the bucket

assert RAW_YARDS != BUCKETED_YARDS, "a fixture that cannot tell the two apart tests nothing"

# A quarterback line carrying both spellings of the same passing yards, as ESPN really serves it.
BOTH = {
    str(RAW_PASS_YARDS_STAT_ID): RAW_YARDS,
    str(BUCKET_STAT_ID): BUCKETS,
    "4": 30.0,
    "20": 6.0,
}


def test_both_passing_stats_are_mapped() -> None:
    assert STAT_ID_TO_KEY[RAW_PASS_YARDS_STAT_ID] == ("pass_yd", 1.0)
    assert STAT_ID_TO_KEY[BUCKET_STAT_ID] == ("pass_yd", PASS_YARD_BUCKET)


def test_a_line_carrying_both_is_never_counted_twice() -> None:
    """The whole point. 3944.73 + (157 x 25) = 7869.73 would be a QB with double the yards."""
    out = translate_stat_line(BOTH, "QB")
    assert out["pass_yd"] == BUCKETED_YARDS, "unfiltered, the bucket leads the group"
    assert out["pass_yd"] != RAW_YARDS + BUCKETS * PASS_YARD_BUCKET


def test_the_league_that_pays_the_bucket_reads_the_bucket() -> None:
    out = translate_stat_line(BOTH, "QB", frozenset({BUCKET_STAT_ID, 4, 20}))
    assert out["pass_yd"] == BUCKETED_YARDS
    assert out["pass_yd"] != RAW_YARDS


def test_the_league_that_pays_raw_yards_reads_raw_yards() -> None:
    out = translate_stat_line(BOTH, "QB", frozenset({RAW_PASS_YARDS_STAT_ID, 4, 20}))
    assert out["pass_yd"] == RAW_YARDS
    assert out["pass_yd"] != BUCKETED_YARDS


def test_a_league_paying_neither_scores_no_passing_yards() -> None:
    """Not a guess at which one it meant -- it pays for neither, so neither is read."""
    out = translate_stat_line(BOTH, "QB", frozenset({4, 20}))
    assert "pass_yd" not in out


def test_a_league_somehow_paying_both_still_counts_once() -> None:
    """Defensive: an unexpected league shape must not silently double a quarterback."""
    out = translate_stat_line(BOTH, "QB", frozenset({RAW_PASS_YARDS_STAT_ID, BUCKET_STAT_ID}))
    assert out["pass_yd"] == BUCKETED_YARDS
    assert out["pass_yd"] != RAW_YARDS


def test_unfiltered_behaviour_is_unchanged_for_a_bucket_only_line() -> None:
    """League 6012's shape: no raw stat in the line at all."""
    out = translate_stat_line({str(BUCKET_STAT_ID): BUCKETS}, "QB")
    assert out["pass_yd"] == BUCKETED_YARDS


def test_a_raw_only_line_is_read_even_unfiltered() -> None:
    """League 485267278's shape, before scoring context is available."""
    out = translate_stat_line({str(RAW_PASS_YARDS_STAT_ID): RAW_YARDS}, "QB")
    assert out["pass_yd"] == RAW_YARDS


def test_the_filter_does_not_disturb_other_stats() -> None:
    out = translate_stat_line(BOTH, "QB", frozenset({RAW_PASS_YARDS_STAT_ID, 4, 20}))
    assert out["pass_td"] == 30.0
    assert out["pass_int"] == 6.0


def test_a_non_quarterback_line_is_unaffected() -> None:
    line = {"24": 1200.0, "53": 80.0, "42": 640.0}
    out = translate_stat_line(line, "RB", frozenset({24, 53, 42}))
    assert out == {"rush_yd": 1200.0, "rec": 80.0, "rec_yd": 640.0}
