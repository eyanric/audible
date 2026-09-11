"""S7 gates -- the weekly harness. The claims `sim/s7_weekly.py` makes about itself.

Written because that module's docstring already claimed "both in `sim/test_g_s7.py`" while no
such file existed. `audible#91`'s review found 16 wrong facts in documentation written the same
session; a docstring citing a gate file that is not there is the same defect, so the gates are
here now and the claims are measured rather than asserted.

EVERY GATE THAT TOUCHES THE CORPUS OR THE PINNED OUTCOMES SKIPS WHEN THEY ARE ABSENT, and the
skip asks the right question. `_CORPUS.exists()` is not it: the directory is tracked, so it
exists on a fresh clone while holding no CSVs, and three gates in `test_g_ffa_scrape.py`
asserted against an empty corpus in CI on their first run for exactly that reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from . import rank, s7_weekly

_CORPUS = Path(__file__).resolve().parent / "data" / "ffa_corpus"

# One scope used by every gate that needs a real week. 2024 week 8 is mid-season, inside the
# pinned-outcome window, and carries a full IDP grid, so nothing here depends on a special week.
SEASON, WEEK = 2024, 8
LEAGUE = "espn_green_hope"


def _corpus_present() -> bool:
    return any(_CORPUS.glob("ffa_raw_*.csv"))


def _actuals_present(season: int) -> bool:
    return (rank.CACHE / "nflverse" / f"player_stats_{season}.parquet").exists()


_needs_corpus = pytest.mark.skipif(
    not _corpus_present(), reason="gitignored corpus not on this machine"
)
_needs_outcomes = pytest.mark.skipif(
    not _actuals_present(SEASON), reason=f"player_stats_{SEASON} not pinned on this machine"
)


# --- G10: raw, never proj -------------------------------------------------------------------


def test_g10_kind_is_raw() -> None:
    """`proj` is scored under the FFAnalytics default league and capped per position."""
    assert s7_weekly.KIND == "raw"


@_needs_corpus
def test_g10_every_path_this_module_builds_is_a_raw_path() -> None:
    for aggregation in s7_weekly.AGGREGATIONS:
        for season, week in s7_weekly.available_scopes(aggregation)[:5]:
            path = s7_weekly.corpus_path(season, week, aggregation)
            assert path.name.startswith("ffa_raw_"), path.name
            assert "_proj_" not in path.name


# --- G11: the 2020 week 17 gap is never substituted ------------------------------------------


def test_g11_missing_scope_raises_and_names_itself() -> None:
    with pytest.raises(s7_weekly.ScopeMissing) as excinfo:
        s7_weekly.corpus_path(2020, 17, "weighted")
    assert "2020" in str(excinfo.value) and "17" in str(excinfo.value)


def test_g11_missing_scope_is_absent_from_every_aggregation() -> None:
    for aggregation in s7_weekly.AGGREGATIONS:
        assert (2020, 17) not in s7_weekly.available_scopes(aggregation)
        assert (2020, 17) not in s7_weekly.available_scopes(aggregation, require_actuals=True)


def test_g11_neighbouring_weeks_are_present_so_the_gap_is_the_gap() -> None:
    """If 16 and 1 of the next season were also missing the gate above would be vacuous."""
    for aggregation in s7_weekly.AGGREGATIONS:
        scopes = s7_weekly.available_scopes(aggregation)
        assert (2020, 16) in scopes
        assert (2021, 1) in scopes


# --- the scope window: the outcome side binds, and the difference is not hidden --------------


def test_actuals_requirement_narrows_to_exactly_the_pinned_seasons() -> None:
    for aggregation in s7_weekly.AGGREGATIONS:
        scoped = s7_weekly.available_scopes(aggregation, require_actuals=True)
        assert {s for s, _ in scoped} <= set(s7_weekly.ACTUALS_SEASONS)
        assert scoped, aggregation


def test_actuals_requirement_actually_drops_something() -> None:
    """A filter that removes nothing would pass the gate above while measuring nothing."""
    offered = s7_weekly.available_scopes("weighted")
    scoped = s7_weekly.available_scopes("weighted", require_actuals=True)
    assert len(scoped) < len(offered)
    assert {s for s, _ in offered} - {s for s, _ in scoped} == {2016, 2017, 2018}


def test_2015_weighted_is_excluded_but_2015_average_is_not() -> None:
    """The 2015 hole is a property of the aggregation, not of the season."""
    assert 2015 not in {s for s, _ in s7_weekly.available_scopes("weighted")}
    assert 2015 in {s for s, _ in s7_weekly.available_scopes("average")}
    assert 2015 in {s for s, _ in s7_weekly.available_scopes("robust")}


@_needs_corpus
def test_the_2015_weighted_defect_is_real_and_2016_is_clean() -> None:
    """The reason `USABLE_WEIGHTED_FROM` is 2016, measured rather than cited.

    sd populated while the paired point estimate is NA. NOT a raw NA rate: about 81% of
    point-estimate cells are legitimately NA corpus-wide because a receiver has no passing
    yards, so a raw rate says nothing.
    """
    bad = s7_weekly.sd_without_value(2015, 8, "weighted")
    good = s7_weekly.sd_without_value(2016, 8, "weighted")
    assert bad > 0.80, bad
    assert good < 0.01, good


# --- G1: the harness scores a known answer correctly ----------------------------------------


@_needs_corpus
@_needs_outcomes
@pytest.mark.parametrize("scale", s7_weekly.SCALES)
def test_g1_perfect_board_scores_exactly_zero(scale: str) -> None:
    board = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale=scale)
    outcome = s7_weekly.realised_week(SEASON, WEEK, LEAGUE).on(scale)
    common = [pid for pid in board.board if pid in outcome]
    perfect = sorted(common, key=lambda pid: (-outcome[pid], pid))
    score = s7_weekly.score_week(perfect, outcome, LEAGUE, position=board.position)
    assert abs(score.rwre) < 1e-9, score.rwre
    assert score.spearman > 0.999


@_needs_corpus
@_needs_outcomes
@pytest.mark.parametrize("scale", s7_weekly.SCALES)
def test_g1_shuffled_board_scores_at_chance(scale: str) -> None:
    import random

    board = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale=scale)
    outcome = s7_weekly.realised_week(SEASON, WEEK, LEAGUE).on(scale)
    common = [pid for pid in board.board if pid in outcome]
    rng = random.Random(20260911)
    draws = []
    for _ in range(8):
        shuffled = list(common)
        rng.shuffle(shuffled)
        draws.append(
            s7_weekly.score_week(shuffled, outcome, LEAGUE, position=board.position).rwre
        )
    assert min(draws) > 20.0, draws
    ffa = s7_weekly.score_week(board.board, outcome, LEAGUE, position=board.position).rwre
    assert ffa < min(draws), (ffa, min(draws))


@_needs_corpus
@_needs_outcomes
def test_the_two_scales_are_not_the_same_board() -> None:
    """Otherwise every `scale`-parametrised gate above is one gate run twice.

    VORP and points agree WITHIN a position and disagree ACROSS positions by the replacement
    level, which is the whole of the 13.99 error `audible#85`'s G1 caught.
    """
    by_points = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale="points")
    by_vorp = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale="vorp")
    assert set(by_points.board) == set(by_vorp.board)
    assert by_points.board != by_vorp.board
    assert by_points.projected == by_vorp.projected  # the POINTS are the same either way
    assert by_points.value != by_vorp.value


def test_an_unknown_scale_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown scale"):
        s7_weekly._scaled({"a": 1.0}, {"a": "RB"}, LEAGUE, "raw_points")


# --- the join, and what happens to what does not join ---------------------------------------


@_needs_corpus
def test_the_mfl_to_gsis_join_is_measured_not_assumed() -> None:
    board = s7_weekly.build_board(SEASON, WEEK, LEAGUE)
    assert board.rows_read > 200, board.rows_read
    assert board.join_rate > 0.95, (board.join_rate, board.dropped_no_gsis)


@_needs_corpus
@_needs_outcomes
def test_a_player_with_no_realised_row_is_dropped_not_scored_zero() -> None:
    """A zero is a claim about production; an absence is not."""
    board = s7_weekly.build_board(SEASON, WEEK, LEAGUE)
    outcome = s7_weekly.realised_week(SEASON, WEEK, LEAGUE).on("vorp")
    absent = [pid for pid in board.board if pid not in outcome]
    assert absent, "no absent player in this scope, so this gate would be vacuous"
    score = s7_weekly.score_week(board.board, outcome, LEAGUE, position=board.position)
    zeroed = dict.fromkeys(absent, 0.0) | outcome
    with_zeros = s7_weekly.score_week(
        board.board, zeroed, LEAGUE, position=board.position
    )
    assert score.rwre != with_zeros.rwre


# --- G12: IDP is a property of the week, never required -------------------------------------


@_needs_corpus
def test_g12_offensive_positions_only_never_requires_idp() -> None:
    """2016 week 14 has no IDP rows at all. A board still builds."""
    board = s7_weekly.build_board(2016, 14, LEAGUE, aggregation="weighted")
    assert len(board.board) > 100
    assert set(board.position.values()) <= s7_weekly.OFFENSIVE
