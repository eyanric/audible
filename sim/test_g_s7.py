"""S7 gates -- the weekly harness. The claims `sim/s7_weekly.py` makes about itself.

Written because that module's docstring already claimed "both in `sim/test_g_s7.py`" while no
such file existed. `audible#91`'s review found 16 wrong facts in documentation written the same
session; a docstring citing a gate file that is not there is the same defect.

THE FIRST VERSION OF THIS FILE HAD SEVEN VACUOUS GATES and the phase-1 review named every one:
a constant asserted against its own literal, an f-string tested for containing the string it
interpolates, `startswith("ffa_raw_")` against a path built by interpolating `KIND`, and a
"shuffled scores at chance" bar of 20.0 against an observed 53-82. Each is rewritten here to
ask a question the code could answer wrongly:

  * anything that could be true by string construction is additionally checked against DISK;
  * anything hardcoded (`MISSING_SCOPES`, `USABLE_WEIGHTED_FROM`, the pinned-outcome window) is
    checked against what is actually on disk, in BOTH directions -- a hardcode that hides a
    present file is the failure mode, and comparing a filter to the constant that implements it
    cannot see it;
  * the chance bar is the analytic permutation floor, not a number chosen by eye;
  * the drop-vs-zero gate runs on a synthetic board sized so the mutation it names is visible.

EVERY GATE THAT TOUCHES THE CORPUS OR THE PINNED OUTCOMES SKIPS WHEN THEY ARE ABSENT, and the
skip asks the right question. `_CORPUS.exists()` is not it: the directory is tracked, so it
exists on a fresh clone while holding no CSVs, and three gates in `test_g_ffa_scrape.py`
asserted against an empty corpus in CI on their first run for exactly that reason.
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path

import pytest

from . import rank, room, s7_weekly

_CORPUS = Path(__file__).resolve().parent / "data" / "ffa_corpus"

# One scope used by every gate that needs a real week. 2024 week 8 is mid-season, inside the
# pinned-outcome window, and carries a full IDP grid (DL 162 / LB 91 / DB 195, measured), so
# nothing here depends on a special week.
SEASON, WEEK = 2024, 8
LEAGUE = "espn_green_hope"

# A scope where the FFA position map and the nflverse position map disagree. `00-0033357` is an
# FFA quarterback and an nflverse tight end here.
DISAGREE_SEASON, DISAGREE_WEEK = 2021, 17

# A season whose regular season is exactly the 17 weeks the corpus covers. From 2021 it is 18.
PARITY_SEASON = 2020


def _corpus_present() -> bool:
    return any(_CORPUS.glob("ffa_raw_*.csv"))


def _outcome_on_disk(season: int) -> bool:
    name = f"player_stats_{season}.parquet"
    return any(
        (Path(root) / "nflverse" / name).exists()
        for root in (room.SIM_CACHE, room.LIVE_CACHE)
    )


def _positions(path: Path) -> Counter[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = header.index("position")
        return Counter(row[index] for row in reader if len(row) == len(header))


_needs_corpus = pytest.mark.skipif(
    not _corpus_present(), reason="gitignored corpus not on this machine"
)
_needs_outcomes = pytest.mark.skipif(
    not _outcome_on_disk(SEASON), reason=f"player_stats_{SEASON} not pinned on this machine"
)


# --- G10: raw, never proj -------------------------------------------------------------------


@_needs_corpus
def test_g10_proj_is_on_disk_and_is_never_what_corpus_path_returns() -> None:
    """`raw` has to be a CHOICE for G10 to mean anything, so `proj` must be reachable.

    Asserting `KIND == "raw"` is a constant against its own literal, and asserting the returned
    filename starts with `ffa_raw_` is true by interpolation. What is not vacuous: `proj` files
    exist, they are structurally unusable, and nothing this module builds points at one.
    """
    proj = sorted(_CORPUS.glob("ffa_proj_*.csv"))
    assert proj, "no proj files on disk, so preferring raw is not a choice and G10 is vacuous"
    for aggregation in s7_weekly.AGGREGATIONS:
        for season, week in s7_weekly.available_scopes(aggregation)[:4]:
            path = s7_weekly.corpus_path(season, week, aggregation)
            assert path.exists(), path
            assert path not in proj


@_needs_corpus
def test_g10_the_reason_proj_is_refused_is_measured_not_cited() -> None:
    """The cap. BoyFun is 10-team SUPERFLEX; 36 quarterbacks in a season file cannot serve it."""
    season_proj = sorted(_CORPUS.glob("ffa_proj_*_wk0_*.csv"))
    if not season_proj:
        pytest.skip("no season proj files on this machine")
    counts = _positions(season_proj[0])
    assert counts["QB"] <= 36, counts["QB"]
    raw_equivalent = _CORPUS / season_proj[0].name.replace("_proj_", "_raw_")
    if raw_equivalent.exists():
        assert _positions(raw_equivalent)["QB"] > counts["QB"]


@_needs_corpus
def test_g10_what_corpus_path_returns_has_the_raw_shape() -> None:
    """A filename is a claim; the fifth column is the evidence. `proj` carries no `avg_type`."""
    path = s7_weekly.corpus_path(SEASON, WEEK, "weighted")
    with path.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert len(header) > 60, len(header)
    assert header[4] == "avg_type", header[:6]


# --- G11: the 2020 week 17 gap is never substituted ------------------------------------------


def test_g11_missing_scope_raises_and_names_itself() -> None:
    with pytest.raises(s7_weekly.ScopeMissing) as excinfo:
        s7_weekly.corpus_path(2020, 17, "weighted")
    assert "2020" in str(excinfo.value) and "17" in str(excinfo.value)


@_needs_corpus
def test_g11_no_hardcoded_gap_hides_a_file_that_is_actually_present() -> None:
    """THE FAILURE MODE OF A HARDCODE, in the direction that comparing it to itself cannot see.

    `MISSING_SCOPES` is a literal. If FFA ever published 2020 week 17, or if a future session
    added a scope to that set by mistake, every scope-exclusion gate would still pass while the
    corpus silently lost a week it holds. So the set is checked against disk.
    """
    for season, week in s7_weekly.MISSING_SCOPES:
        for aggregation in s7_weekly.AGGREGATIONS:
            name = f"ffa_{s7_weekly.KIND}_{season}_wk{week}_{aggregation}.csv"
            assert not (_CORPUS / name).exists(), (
                f"{name} IS on disk but {season} wk{week} is hardcoded as missing"
            )


def test_g11_missing_scope_is_absent_from_every_aggregation() -> None:
    for aggregation in s7_weekly.AGGREGATIONS:
        assert (2020, 17) not in s7_weekly.available_scopes(aggregation)
        assert (2020, 17) not in s7_weekly.available_scopes(aggregation, require_actuals=True)


@_needs_corpus
def test_g11_neighbouring_weeks_are_present_so_the_gap_is_the_gap() -> None:
    """If 2020 wk16 and 2021 wk1 were also absent the gate above would be vacuous."""
    for aggregation in s7_weekly.AGGREGATIONS:
        scopes = s7_weekly.available_scopes(aggregation)
        assert (2020, 16) in scopes
        assert (2021, 1) in scopes
        assert s7_weekly.corpus_path(2020, 16, aggregation).exists()


# --- the scope window: the outcome side binds, and both directions are checked ---------------


@_needs_corpus
def test_the_pinned_window_is_read_from_disk_in_both_directions() -> None:
    """Derived, not asserted. The constant this replaced would have lied under a new pin.

    `ACTUALS_SEASONS = tuple(range(2019, 2026))` was a literal, and the review's point stands:
    pinning `player_stats_2018.parquet` would have dropped 17 scopes while the run's own
    accounting line stayed silent, and no gate read the directory.
    """
    pinned = s7_weekly.pinned_actuals_seasons()
    assert pinned, "no weekly outcomes pinned on this machine at all"
    for season in pinned:
        assert _outcome_on_disk(season), season
    offered = {s for s, _ in s7_weekly.available_scopes("weighted")}
    for season in offered - set(pinned):
        assert not _outcome_on_disk(season), (
            f"{season} has a pinned outcome but is not in the scoreable window"
        )


@_needs_corpus
def test_the_actuals_requirement_drops_exactly_the_unpinned_seasons() -> None:
    """The expected drop is DERIVED from disk, not written as {2016, 2017, 2018}."""
    offered = s7_weekly.available_scopes("weighted")
    scoped = s7_weekly.available_scopes("weighted", require_actuals=True)
    expected = {s for s, _ in offered if not _outcome_on_disk(s)}
    assert {s for s, _ in offered} - {s for s, _ in scoped} == expected
    assert expected, "every offered season is pinned, so this filter is currently inert"
    assert len(scoped) < len(offered)


@_needs_corpus
def test_2015_weighted_is_excluded_by_CHOICE_and_the_files_are_there() -> None:
    """Exclusion by policy, not by absence -- otherwise the constant is doing nothing."""
    assert (_CORPUS / "ffa_raw_2015_wk8_weighted.csv").exists()
    assert 2015 not in {s for s, _ in s7_weekly.available_scopes("weighted")}
    assert 2015 in {s for s, _ in s7_weekly.available_scopes("average")}
    assert 2015 in {s for s, _ in s7_weekly.available_scopes("robust")}


@_needs_corpus
def test_the_2015_weighted_defect_is_real_and_2016_is_clean() -> None:
    """The reason `USABLE_WEIGHTED_FROM` is 2016, measured rather than cited.

    sd populated while the paired point estimate is NA. NOT a raw NA rate: most point-estimate
    cells are legitimately NA -- 81.5% in 2024 wk8, 74.8% in 2016 wk8 -- because a receiver has
    no passing yards, so a raw rate says nothing either way.

    2015 WEEK 1 IS CLEAN (0.0000), so `USABLE_WEIGHTED_FROM = 2016` is one week coarser than the
    defect it cites. That is deliberate -- one clean week of a defective season is not worth a
    special case -- and it is recorded here so the constant is not mistaken for the measurement.
    """
    assert s7_weekly.sd_without_value(2015, 1, "weighted") < 0.01
    for week in (2, 8, 17):
        bad = s7_weekly.sd_without_value(2015, week, "weighted")
        assert bad > 0.80, (week, bad)
    assert s7_weekly.sd_without_value(2016, 8, "weighted") < 0.01


# --- G1: the harness scores a known answer correctly ----------------------------------------


@_needs_corpus
@_needs_outcomes
@pytest.mark.parametrize("scale", s7_weekly.SCALES)
def test_g1_perfect_board_scores_exactly_zero(scale: str) -> None:
    """Kept, and labelled: ON ITS OWN THIS IS A TAUTOLOGY.

    The perfect board is sorted by the same key `rank._realised_order` uses, so it reads
    0.000000 against any outcome dict at all -- the review demonstrated it against uniform
    random numbers. It proves the metric is internally consistent and nothing about units. The
    cross-scale gate below is the one that gates units.
    """
    board = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale=scale)
    outcome = s7_weekly.realised_week(SEASON, WEEK, LEAGUE).on(scale, position=board.position)
    common = [pid for pid in board.board if pid in outcome]
    perfect = sorted(common, key=lambda pid: (-outcome[pid], pid))
    score = s7_weekly.score_week(perfect, outcome, LEAGUE, position=board.position)
    assert abs(score.rwre) < 1e-9, score.rwre
    assert score.spearman > 0.999


@_needs_corpus
@_needs_outcomes
@pytest.mark.parametrize("scale", s7_weekly.SCALES)
@pytest.mark.parametrize("league", ["espn_green_hope", "sleeper_boyfun"])
def test_g1_a_perfect_board_in_the_wrong_unit_costs_something(scale: str, league: str) -> None:
    """FAILURE INJECTION 1, the units half. This is the 13.99 `audible#85` caught.

    THE INVARIANT IS ABOUT THE PERFECT BOARD, not about which FFA ordering wins. The first
    version asserted the latter and fired on sleeper_boyfun -- where the points-ordered board
    beats the vorp-ordered one against the vorp outcome, 51.413 to 52.163. That is a finding
    about `compute_vorp` under SUPERFLEX, not a broken unit, so both leagues are run here and
    only the invariant is asserted.
    """
    other = "points" if scale == "vorp" else "vorp"
    board = s7_weekly.build_board(SEASON, WEEK, league, scale=scale)
    wrong = s7_weekly.build_board(SEASON, WEEK, league, scale=other)
    realised = s7_weekly.realised_week(SEASON, WEEK, league)
    outcome = realised.on(scale, position=board.position)
    wrong_outcome = realised.on(other, position=wrong.position)
    wrong_perfect = sorted(
        [pid for pid in wrong.board if pid in wrong_outcome],
        key=lambda pid: (-wrong_outcome[pid], pid),
    )
    cross = s7_weekly.score_week(
        [pid for pid in wrong_perfect if pid in outcome], outcome, league,
        position=board.position,
    ).rwre
    assert cross > 1e-9, cross


@_needs_corpus
@_needs_outcomes
@pytest.mark.parametrize("scale", s7_weekly.SCALES)
def test_g1_a_shuffled_real_board_matches_the_football_free_floor(scale: str) -> None:
    """The chance bar, against the analytic floor instead of a number picked by eye.

    The old bar was `min(draws) > 20.0` against an observed 53-82 -- nothing could fail it. The
    metric reduces both sides to within-pool ranks, so a shuffled REAL board and a shuffled
    SYNTHETIC one of the same size must land in the same place. If they do not, the metric is
    reading something other than the two ranks and every number in the sweep is suspect.
    """
    board = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale=scale)
    outcome = s7_weekly.realised_week(SEASON, WEEK, LEAGUE).on(scale, position=board.position)
    common = [pid for pid in board.board if pid in outcome]
    pool = min(rank.pool_size_for(LEAGUE), len(common))
    teams = int(rank.league(LEAGUE).num_teams)
    synth_mean, synth_sd = s7_weekly.permutation_floor(pool, teams, draws=120)
    rng = random.Random(20260911)
    draws = []
    for _ in range(12):
        shuffled = list(common)
        rng.shuffle(shuffled)
        draws.append(
            s7_weekly.score_week(shuffled, outcome, LEAGUE, position=board.position).rwre
        )
    observed = sum(draws) / len(draws)
    assert abs(observed - synth_mean) < 3 * synth_sd, (observed, synth_mean, synth_sd)
    ffa = s7_weekly.score_week(board.board, outcome, LEAGUE, position=board.position).rwre
    assert ffa < observed - 3 * synth_sd, (ffa, observed, synth_sd)


def test_the_shuffle_floor_contains_no_football_whatsoever() -> None:
    """The correction the review forced, as a gate: the floor is a function of two integers.

    If this ever fails, "the weekly and seasonal floors agree" stops being arithmetic and
    becomes a claim about data again.
    """
    a, _ = s7_weekly.permutation_floor(128, 8, draws=150, seed=1)
    b, _ = s7_weekly.permutation_floor(128, 8, draws=150, seed=2)
    assert abs(a - b) < 1.5, (a, b)
    c, _ = s7_weekly.permutation_floor(190, 10, draws=150, seed=1)
    assert c > a + 20, (a, c)


@_needs_corpus
@_needs_outcomes
def test_the_two_scales_are_not_the_same_board() -> None:
    """Otherwise every `scale`-parametrised gate above is one gate run twice."""
    by_points = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale="points")
    by_vorp = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale="vorp")
    assert set(by_points.board) == set(by_vorp.board)
    assert by_points.board != by_vorp.board
    assert by_points.projected == by_vorp.projected  # the POINTS are the same either way
    assert by_points.value != by_vorp.value


@_needs_corpus
@_needs_outcomes
def test_the_per_position_metric_is_scale_blind_and_that_is_recorded() -> None:
    """A FACT ABOUT THE METRIC, gated so no later phase reads these numbers as scale-specific.

    VORP is a within-position monotone shift, so it cannot reorder anyone inside a position --
    the per-position figures are therefore identical across scales by construction, and the
    review measured them bitwise identical in 101 of 118 green_hope scopes. Any positional
    signal adjudicated on them is being adjudicated on a scale-blind quantity.
    """
    out: dict[str, dict[str, float]] = {}
    for scale in ("points", "vorp"):
        board = s7_weekly.build_board(SEASON, WEEK, LEAGUE, scale=scale)
        outcome = s7_weekly.realised_week(SEASON, WEEK, LEAGUE).on(
            scale, position=board.position
        )
        score = s7_weekly.score_week(board.board, outcome, LEAGUE, position=board.position)
        out[scale] = dict(score.per_position)
    assert out["points"] == out["vorp"], out


def test_an_unknown_scale_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown scale"):
        s7_weekly._scaled({"a": 1.0}, {"a": "RB"}, LEAGUE, "raw_points")


# --- one position authority across the two sides --------------------------------------------


@_needs_corpus
@pytest.mark.skipif(
    not _outcome_on_disk(DISAGREE_SEASON),
    reason=f"player_stats_{DISAGREE_SEASON} not pinned on this machine",
)
def test_the_position_override_is_not_inert() -> None:
    """The two corpora disagree about some players, and the override is what resolves it.

    Without it the realised VORP groups a player by his nflverse position while the metric
    groups him by his FFA position, the group's shift stops being constant, and the
    within-position order moves. Measured in 17 of 118 green_hope scopes.
    """
    board = s7_weekly.build_board(DISAGREE_SEASON, DISAGREE_WEEK, LEAGUE, scale="vorp")
    realised = s7_weekly.realised_week(DISAGREE_SEASON, DISAGREE_WEEK, LEAGUE)
    disagree = [
        pid for pid, pos in board.position.items()
        if pid in realised.position and realised.position[pid] != pos
    ]
    assert disagree, "no disagreement in this scope, so the override cannot be shown to act"
    assert realised.on("vorp") != realised.on("vorp", position=board.position)


# --- the join, and what happens to what does not join ---------------------------------------


@_needs_corpus
def test_the_mfl_to_gsis_join_is_measured_not_assumed() -> None:
    board = s7_weekly.build_board(SEASON, WEEK, LEAGUE)
    assert board.rows_read > 200, board.rows_read
    assert board.join_rate > 0.95, (board.join_rate, board.dropped_no_gsis)


def test_a_player_with_no_realised_row_is_dropped_not_scored_zero() -> None:
    """A zero is a claim about production; an absence is not.

    RUN ON A SYNTHETIC BOARD, because the real one cannot see the mutation: with 300-odd
    candidates and a 128 pool, deleting the `pid in realised` filter changes which players fill
    the pool but not its size, and the first version of this gate passed under that mutation.
    Here the board is smaller than the pool, so the filter is the only thing that sets `n`.
    """
    board = [f"p{i:03d}" for i in range(30)]
    position = dict.fromkeys(board, "RB")
    realised = {pid: float(30 - i) for i, pid in enumerate(board[:20])}
    score = s7_weekly.score_week(board, realised, LEAGUE, position=position, pool_size=30)
    assert score.n == 20, score.n
    for pid in board[20:]:
        assert pid not in realised


# --- G12: IDP is a property of the week, never required -------------------------------------


@_needs_corpus
def test_g12_a_week_with_no_idp_at_all_still_builds_a_board() -> None:
    """2016 week 14 has zero IDP rows. Measured from the CSV, not cited."""
    path = s7_weekly.corpus_path(2016, 14, "weighted")
    counts = _positions(path)
    assert not {"DL", "LB", "DB"} & set(counts), counts
    board = s7_weekly.build_board(2016, 14, LEAGUE, aggregation="weighted")
    assert len(board.board) > 100, len(board.board)


@_needs_corpus
def test_g12_the_positions_filter_is_load_bearing_not_decorative() -> None:
    """`<= OFFENSIVE` is guaranteed by the filter, so the filter itself has to be exercised.

    2024 week 8 DOES carry IDP. Asking for defensive positions returns them; asking for
    offensive ones does not. Without both halves the assertion is true for any corpus at all.
    """
    counts = _positions(s7_weekly.corpus_path(SEASON, WEEK, "weighted"))
    assert {"DL", "LB", "DB"} <= set(counts), counts
    offence = s7_weekly.build_board(SEASON, WEEK, LEAGUE)
    assert set(offence.position.values()) <= s7_weekly.OFFENSIVE
    defence = s7_weekly.build_board(
        SEASON, WEEK, LEAGUE, positions=frozenset({"DL", "LB", "DB"})
    )
    assert defence.rows_read > 100, defence.rows_read
    assert not set(defence.position.values()) & s7_weekly.OFFENSIVE


# --- the two modes score under the same rulebook --------------------------------------------


@_needs_corpus
@pytest.mark.skipif(
    not _outcome_on_disk(PARITY_SEASON),
    reason=f"player_stats_{PARITY_SEASON} not pinned on this machine",
)
def test_the_weekly_and_seasonal_outcomes_use_the_same_rulebook() -> None:
    """The review found `realised_week` silently omitting three terms the seasonal side pays.

    Return yards, return touchdowns and fumble-recovery touchdowns: 28 offensive players and
    68.0 points in one week of one league, up to 13.0 for a single returner. A script whose
    headline compares the two modes cannot score them two different ways. Summing the weekly
    scorer over a season and dividing by games must reproduce the seasonal scorer.

    RUN ON 2020, NOT 2024, and the reason is the next gate: from 2021 the regular season is 18
    weeks and the corpus stops at 17, so on a later season this sum is missing a game while the
    seasonal scorer divides by one that includes it. On 2024 Aaron Rodgers reads 16.10 against
    17.98 for exactly that reason -- a real coverage gap, not a scoring difference.
    """
    season = PARITY_SEASON
    totals: dict[str, float] = {}
    for week in s7_weekly.REGULAR_WEEKS:
        for pid, pts in s7_weekly.realised_week(season, week, LEAGUE).points.items():
            totals[pid] = totals.get(pid, 0.0) + pts
    seasonal = rank.realised_per_game(season, LEAGUE)
    checked = 0
    for pid, per_game in seasonal.per_game.items():
        games = seasonal.games.get(pid, 0)
        if games < 8 or pid not in totals:
            continue
        assert abs(totals[pid] / games - per_game) < 0.02, (pid, totals[pid] / games, per_game)
        checked += 1
    assert checked > 100, checked


# --- preflight ------------------------------------------------------------------------------


def test_preflight_names_the_missing_file_before_any_work() -> None:
    """`rank.PreflightError`'s contract is "before any work, naming the file, never mid-run".

    The sweep violated it: unpinning a season left every gate green and crashed the run partway
    through with a bare FileNotFoundError.
    """
    with pytest.raises(rank.PreflightError) as excinfo:
        s7_weekly.preflight([(1998, 3)], LEAGUE)
    assert "1998" in str(excinfo.value)


@_needs_corpus
def test_preflight_passes_on_the_window_the_sweep_actually_runs() -> None:
    s7_weekly.preflight(s7_weekly.available_scopes("weighted", require_actuals=True), LEAGUE)


@pytest.mark.skipif(not _outcome_on_disk(2024), reason="player_stats_2024 not pinned")
def test_week_18_exists_in_the_outcomes_and_not_in_the_corpus() -> None:
    """A COVERAGE FACT THE CORPUS DOCS DO NOT STATE, found by the rulebook-parity gate.

    The regular season became 18 weeks in 2021. `REGULAR_WEEKS` is 1-17 because that is the grid
    the FFA weekly exports cover, so for 2021-2025 one week of realised production per season
    has no projection at all and can never be scored. It is not a hole in the scrape -- every
    2021-2025 week 1-17 file is present -- it is the shape of the source.

    The consequence for phase 4: a seasonal per-game outcome INCLUDES week 18 production while
    any weekly aggregate built from this corpus cannot, so the two modes are not summing over
    the same games from 2021 on.
    """
    import polars as pl

    from . import weekly as weekly_module

    frame = weekly_module._frame(2024).filter(pl.col("season_type") == "REG")
    assert int(frame["week"].max()) == 18
    assert max(s7_weekly.REGULAR_WEEKS) == 17
    for aggregation in s7_weekly.AGGREGATIONS:
        assert (2024, 18) not in s7_weekly.available_scopes(aggregation)
    older = weekly_module._frame(2020).filter(pl.col("season_type") == "REG")
    assert int(older["week"].max()) == 17
