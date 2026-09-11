"""S7 -- score a ranking against WEEKLY realised production.

WHY WEEKLY. Every prior measurement in this project ran on about six observations -- one per
season -- and six observations cannot distinguish a real improvement from noise. That is why
every attempt stalled, not because the board was optimal. `audible#91` landed 612 FFA files;
the weighted weekly slice alone is 177,885 rows.

THE PRODUCT IS STILL A DRAFT BOARD. The ranking is ONE model, used at the draft and in-season,
so it may be *tested* where the data is and must be *confirmed* where it ships. Both numbers
are reported for every change; a change that helps weekly and hurts the draft board is a
finding, not a win.

WHAT THIS MODULE IS NOT. It does not rank. It scores a ranking somebody else produced. The
board comes in as gsis ids in preference order and a number comes out.

TWO THINGS MEASURED BEFORE ANY OF IT WAS TRUSTED, both in `sim/test_g_s7.py`:

  * The mfl -> gsis join. `sim/weekly.py::prior_points` once looked players up with `ffc####`
    keys against a roster keyed on gsis ids: every lookup missed, every prior read 0.0, and
    because `optimal_week` is an exact matching every lineup tied and fell out of the
    tie-break. Two sessions of headline numbers were computed against arbitrary lineups.
    Measured here: 99.6% of 2019 wk5 offensive rows and 100% of 2024 wk8 join.
  * A board built from the realised order scores exactly 0.000000, and a shuffled board scores
    at chance. `audible#85` caught a units bug this way on its first run -- a VORP-ordered
    board scored against points-ordered outcomes read 13.99 with every per-position figure at
    exactly 0.0.

THE 2015 WEIGHTED HOLE. Sixteen files -- 2015 weeks 2-17, `weighted` only -- carry `X_sd`
populated while `X` is `NA` for 93-95% of paired cells. `USABLE_WEIGHTED_FROM` is 2016 for
that reason; 2015 is reachable through `average` or `robust`, which are clean. See
`sim/data/ffa_corpus/README.md`.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import rank, room, weekly

CORPUS: Path = Path(__file__).resolve().parent / "data" / "ffa_corpus"

# `raw`, never `proj`. A proj export is scored under the FFAnalytics DEFAULT league -- neither
# of Eric's -- and is capped at 36 QB / 72 RB / 72 WR / 36 TE per season, measured in distinct
# players over all nine seasons. BoyFun is 10-team SUPERFLEX; 36 quarterbacks in total is
# structurally insufficient before any question of accuracy.
KIND = "raw"

AGGREGATIONS: tuple[str, ...] = ("weighted", "average", "robust")

# The weekly window the corpus actually supports, per aggregation.
WEEKLY_SEASONS: tuple[int, ...] = tuple(range(2015, 2026))
REGULAR_WEEKS: tuple[int, ...] = tuple(range(1, 18))
USABLE_WEIGHTED_FROM = 2016

# FFA has no data for it in any aggregation: 23 bytes for raw weighted, three defensive
# players for average and robust, a 500 for proj. Never substituted.
MISSING_SCOPES: frozenset[tuple[int, int]] = frozenset({(2020, 17)})

# FFA raw stat columns -> the scoring engine's keys. Only what a rulebook can pay for.
STAT_KEYS: dict[str, str] = {
    "pass_yds": "pass_yd",
    "pass_tds": "pass_td",
    "pass_int": "pass_int",
    "rush_yds": "rush_yd",
    "rush_tds": "rush_td",
    "rec_yds": "rec_yd",
    "rec_tds": "rec_td",
    "rec": "rec",
    "fumbles_lost": "fum_lost",
    "two_pts": "two_pt",
}

OFFENSIVE: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class ScopeMissing(LookupError):
    """The corpus has no file for this (season, week, aggregation). Never substituted."""


@dataclass(frozen=True, slots=True)
class WeeklyBoard:
    """A ranking for one scope, with the joins it survived recorded beside it."""

    season: int
    week: int
    league_key: str
    aggregation: str
    board: list[str]  # gsis ids, best first
    projected: dict[str, float]
    position: dict[str, str]
    rows_read: int
    joined: int
    dropped_no_gsis: int

    @property
    def join_rate(self) -> float:
        return self.joined / self.rows_read if self.rows_read else 0.0


def corpus_path(season: int, week: int, aggregation: str) -> Path:
    if (season, week) in MISSING_SCOPES:
        raise ScopeMissing(
            f"{season} wk{week} is absent from the corpus in every aggregation -- FFA has no "
            "data for it. Do not substitute a neighbouring week."
        )
    path = CORPUS / f"ffa_{KIND}_{season}_wk{week}_{aggregation}.csv"
    if not path.exists():
        raise ScopeMissing(f"{path.name} is not on disk")
    return path


def available_scopes(aggregation: str) -> list[tuple[int, int]]:
    """Every (season, week) this aggregation can serve, honouring the 2015 weighted hole."""
    scopes = []
    for season in WEEKLY_SEASONS:
        if aggregation == "weighted" and season < USABLE_WEIGHTED_FROM:
            continue
        for week in REGULAR_WEEKS:
            if (season, week) in MISSING_SCOPES:
                continue
            if (CORPUS / f"ffa_{KIND}_{season}_wk{week}_{aggregation}.csv").exists():
                scopes.append((season, week))
    return scopes


def _cell(value: str | None) -> float:
    """FFA writes `NA` for a stat a player has no projection for. That is not zero.

    It is returned as 0.0 for SCORING, because a rulebook pays nothing for an absent stat --
    but a caller that needs to know the difference must look at the raw row, which is why
    `sd_without_value` exists below.
    """
    if value is None:
        return 0.0
    text = value.strip()
    if text in ("", "NA", "N/A", "null"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def sd_without_value(season: int, week: int, aggregation: str) -> float:
    """Fraction of sd-populated cells whose point estimate is absent.

    0.0 everywhere except 2015 weeks 2-17 weighted, where it is 93-95%. A harness that reads
    those files as though the estimates were zero is scoring 1,100 players at nothing.
    """
    path = corpus_path(season, week, aggregation)
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline=""))
    header = next(reader)
    paired = [c for c in header if f"{c}_sd" in header]
    index = {c: (header.index(c), header.index(f"{c}_sd")) for c in paired}
    absent = total = 0
    for row in reader:
        if len(row) != len(header):
            continue
        for column in paired:
            value_i, sd_i = index[column]
            if row[sd_i].strip() not in ("", "NA"):
                total += 1
                if row[value_i].strip() in ("", "NA"):
                    absent += 1
    return absent / total if total else 0.0


def league_config(league_key: str) -> Any:
    from audible.config import load_league

    repo = Path(__file__).resolve().parents[1]
    return load_league(repo / "leagues" / f"{league_key}.toml")


def build_board(
    season: int,
    week: int,
    league_key: str,
    *,
    aggregation: str = "weighted",
    positions: frozenset[str] = OFFENSIVE,
    deltas: dict[str, float] | None = None,
) -> WeeklyBoard:
    """Rank the FFA weekly projection for one scope under one league's rulebook.

    The ordering is projected points under THIS league, which is the whole reason to use
    `raw`: the same stat line ranks differently in a PPR league than in a standard one, and a
    `proj` file has already committed to somebody else's answer.
    """
    from audible.scoring.engine import score_stat_line

    path = corpus_path(season, week, aggregation)
    crosswalk = rank.crosswalk("mfl_id")
    config = league_config(league_key)
    weights_by_position: dict[str, dict[str, float]] = {}

    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline=""))
    header = next(reader)
    column = {name: i for i, name in enumerate(header)}
    have = [c for c in STAT_KEYS if c in column]

    projected: dict[str, float] = {}
    position: dict[str, str] = {}
    rows_read = joined = dropped = 0

    for row in reader:
        if len(row) != len(header):
            continue
        pos = room.canon_position(row[column["position"]])
        if pos not in positions:
            continue
        rows_read += 1
        gsis = crosswalk.get(row[column["id"]])
        if gsis is None:
            dropped += 1
            continue
        joined += 1

        weights = weights_by_position.get(pos)
        if weights is None:
            weights = dict(config.scoring_for(pos))
            if deltas:
                weights.update(deltas)
            weights_by_position[pos] = weights

        stats = {STAT_KEYS[c]: _cell(row[column[c]]) for c in have}
        points = score_stat_line(stats, weights)
        # A player can appear twice under two team aliases with identical stats. Keep the
        # larger rather than summing: summing would double a traded player's projection.
        if points > projected.get(gsis, float("-inf")):
            projected[gsis] = points
        position[gsis] = pos

    board = sorted(projected, key=lambda pid: (-projected[pid], pid))
    return WeeklyBoard(
        season=season, week=week, league_key=league_key, aggregation=aggregation,
        board=board, projected=projected, position=position,
        rows_read=rows_read, joined=joined, dropped_no_gsis=dropped,
    )


def realised_week(
    season: int, week: int, league_key: str, *, positions: frozenset[str] = OFFENSIVE
) -> dict[str, float]:
    """That week's realised points per gsis id, under *league_key*'s own rulebook.

    `sim/weekly.py::weekly_points` scores one league only -- 6012, with its historical
    reception delta -- so this re-scores the same pinned frames per league rather than
    refactoring a module four other gate files depend on.
    """
    import polars as pl

    from audible.scoring.engine import score_stat_line

    frame = weekly._frame(season)
    config = league_config(league_key)
    reg = frame.filter(
        (pl.col("season_type") == "REG") & (pl.col("week") == week)
    ).fill_null(0)

    weights_by_position: dict[str, dict[str, float]] = {}
    points: dict[str, float] = {}
    for row in reg.iter_rows(named=True):
        pos = room.canon_position(str(row.get("position") or ""))
        if pos not in positions:
            continue
        weights = weights_by_position.get(pos)
        if weights is None:
            weights = dict(config.scoring_for(pos))
            weights_by_position[pos] = weights
        stats = {key: float(row.get(col) or 0.0) for col, key in weekly.COLUMN_TO_KEY.items()}
        stats["pass_yd"] = weekly.bucket25(float(row.get("passing_yards") or 0.0))
        pid = str(row["player_id"])
        points[pid] = points.get(pid, 0.0) + score_stat_line(stats, weights)
    return points


def score_week(
    board: list[str],
    realised: dict[str, float],
    league_key: str,
    *,
    position: dict[str, str] | None = None,
    pool_size: int | None = None,
    indexing: str = "symmetric",
) -> Any:
    """Round-weighted rank error for one week, symmetric indexing.

    Symmetric was settled in `audible#85` and `#88`: board-rank weighting was 4.38x
    asymmetric and realised weighting 0.23x, against symmetric's 1.00x. Spearman and the
    top-24 hit rate come back in the same object and are never optimised against.

    THE POOL IS THE BOARD'S OWN TOP N, and every player in it must have a realised number --
    `rank._realised_order` ranks within the pool, so a player absent from `realised` would be
    ranked against nothing. Missing players are dropped from the pool, not scored as zero: a
    zero is a claim about production and an absence is not.
    """
    config = league_config(league_key)
    scoreable = [pid for pid in board if pid in realised]
    if pool_size is None:
        pool_size = rank.pool_size_for(league_key)
    return rank.score_board(
        scoreable,
        realised,
        teams=int(config.num_teams),
        pool_size=min(pool_size, len(scoreable)),
        position=position,
        indexing=indexing,
        position_pool=rank.position_pool_sizes(league_key),
    )
