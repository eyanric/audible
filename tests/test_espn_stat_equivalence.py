"""Two stat ids, the same yards, and the league decides which one counts.

ESPN ships BOTH passing-yard stats on every line regardless of which one the league pays --
measured 2026-09-02 on Josh Allen, whose 2025 actual line carries statId 3 = 3668 AND
statId 8 = 139, and whose 2026 projection carries 3949.1 and 157. They are the same yards
counted two ways.

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

# A quarterback line carrying both spellings of the same 3,925 yards, as ESPN really serves it.
BOTH = {
    str(RAW_PASS_YARDS_STAT_ID): 3925.0,
    str(BUCKET_STAT_ID): 157.0,
    "4": 30.0,
    "20": 6.0,
}


def test_both_passing_stats_are_mapped() -> None:
    assert STAT_ID_TO_KEY[RAW_PASS_YARDS_STAT_ID] == ("pass_yd", 1.0)
    assert STAT_ID_TO_KEY[BUCKET_STAT_ID] == ("pass_yd", PASS_YARD_BUCKET)


def test_a_line_carrying_both_is_never_counted_twice() -> None:
    """The whole point. 3925 + (157 x 25) = 7850 would be a QB with double the yards."""
    out = translate_stat_line(BOTH, "QB")
    assert out["pass_yd"] == 3925.0
    assert out["pass_yd"] != 3925.0 + 157.0 * PASS_YARD_BUCKET


def test_the_league_that_pays_the_bucket_reads_the_bucket() -> None:
    out = translate_stat_line(BOTH, "QB", frozenset({BUCKET_STAT_ID, 4, 20}))
    assert out["pass_yd"] == 157.0 * PASS_YARD_BUCKET


def test_the_league_that_pays_raw_yards_reads_raw_yards() -> None:
    out = translate_stat_line(BOTH, "QB", frozenset({RAW_PASS_YARDS_STAT_ID, 4, 20}))
    assert out["pass_yd"] == 3925.0


def test_a_league_paying_neither_scores_no_passing_yards() -> None:
    """Not a guess at which one it meant -- it pays for neither, so neither is read."""
    out = translate_stat_line(BOTH, "QB", frozenset({4, 20}))
    assert "pass_yd" not in out


def test_a_league_somehow_paying_both_still_counts_once() -> None:
    """Defensive: an unexpected league shape must not silently double a quarterback."""
    out = translate_stat_line(BOTH, "QB", frozenset({RAW_PASS_YARDS_STAT_ID, BUCKET_STAT_ID}))
    assert out["pass_yd"] == 157.0 * PASS_YARD_BUCKET


def test_unfiltered_behaviour_is_unchanged_for_a_bucket_only_line() -> None:
    """League 6012's shape: no raw stat in the line at all."""
    out = translate_stat_line({str(BUCKET_STAT_ID): 157.0}, "QB")
    assert out["pass_yd"] == 157.0 * PASS_YARD_BUCKET


def test_a_raw_only_line_is_read_even_unfiltered() -> None:
    """League 485267278's shape, before scoring context is available."""
    out = translate_stat_line({str(RAW_PASS_YARDS_STAT_ID): 3925.0}, "QB")
    assert out["pass_yd"] == 3925.0


def test_the_filter_does_not_disturb_other_stats() -> None:
    out = translate_stat_line(BOTH, "QB", frozenset({RAW_PASS_YARDS_STAT_ID, 4, 20}))
    assert out["pass_td"] == 30.0
    assert out["pass_int"] == 6.0


def test_a_non_quarterback_line_is_unaffected() -> None:
    line = {"24": 1200.0, "53": 80.0, "42": 640.0}
    out = translate_stat_line(line, "RB", frozenset({24, 53, 42}))
    assert out == {"rush_yd": 1200.0, "rec": 80.0, "rec_yd": 640.0}
