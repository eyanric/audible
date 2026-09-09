"""S2 -- how accurately a board RANKS, scored per player against realised per-game production.

WHY THIS AND NOT ROSTER POINTS. Fifteen sessions measured roster outcomes: draft a team, total
what those players scored, compare arms. That collapses ~400 player observations into ONE
NUMBER PER SEASON, and seven seasons gives four to six degrees of freedom -- too few to resolve
anything. Two depth rules, one materially closer to how the league drafts, came out at
+0.25 [-9.53, +10.04].

Worse, it is dominated by injury. Draft Jefferson in 2023, he misses seven games, the roster
drops a hundred points -- in EVERY seed, because he is top of the board and you pick early.
Season shocks do not average out across seeds; they are constants inside a season.

Ranking accuracy is measured PER PLAYER. Four hundred players a season, seven seasons. An
injury is one player in four hundred rather than one-sixteenth of a roster.

THE OUTCOME IS PER-GAME, NOT SEASON TOTAL. Season totals pay availability, and availability is
exactly what a preseason board cannot know. `sim/projection.py::actual_lines` already made this
argument for the ceiling arm and measured it: a per-game ordering of the same realised lines
beat a season-total ordering by +56.0 [+19.0, +93.0] points a season.

THE RULEBOOK IS THE COMMITTED ONE, and that is a stated limitation rather than an oversight.
`sim/weekly.py` corrects league 6012 back to what it historically paid via
`roundtrip.HISTORICAL_DELTAS`, because its TOML describes 2026. No equivalent correction exists
for the other three leagues, so each is scored under its committed table. This is COMMON-MODE
across arms -- every arm is scored under the same rulebook in the same season -- so it cannot
move a comparison BETWEEN arms, which is what this module exists to make. It could move the
absolute level, and no absolute level is claimed.

See `sim/runs/s2-ranking.md` for the pre-registration: the metric, the weighting function and
its justification, the pool, the exclusions and the walk-forward split were all fixed and
committed before this file existed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import room
from .roundtrip import (
    COLUMN_TO_KEY,
    FUMBLE_RECOVERY_TD_POINTS,
    RETURN_TD_POINTS,
    RETURN_YARD_POINTS,
    bucket25,
)

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "sim-cache"

# K and DEF are excluded and it is a gate, not a preference. `player_stats` carries no
# team-defence rows in ANY season, and `roundtrip.COLUMN_TO_KEY` carries no kicking columns, so
# both realise approximately zero. They would enter as a large block of true zeros predicted as
# zeros and inflate every arm identically. `sim/weekly.py` already names them UNSCOREABLE.
SCOREABLE: tuple[str, ...] = ("QB", "RB", "WR", "TE")

# Outcomes are pinned for 2019-2025, so 2018 is unusable however good the projection is.
# Per-arm exclusions are the S1 findings and are enforced here rather than remembered:
#   espn 2023    -- 129 of 1,128 non-zero, and the surviving signals are contaminated
#   sleeper 2019 -- five independent axes break at 2021
#   sleeper 2020 -- same
SEASONS_BY_ARM: dict[str, tuple[int, ...]] = {
    "ffa": (2019, 2020, 2021, 2022, 2023, 2024, 2025),
    "espn": (2019, 2020, 2021, 2022, 2024, 2025),
    "sleeper": (2021, 2022, 2023, 2024, 2025),
    "ecr": (2020, 2021, 2022, 2023, 2024, 2025),
}

FIT_SEASONS: tuple[int, ...] = (2019, 2020, 2021, 2022)
TEST_SEASONS: tuple[int, ...] = (2023, 2024, 2025)

LEAGUES: tuple[str, ...] = ("espn_green_hope", "espn_danger_zone", "sleeper_boyfun")

# Which id column in ff_playerids each corpus speaks.
ARM_ID_COLUMN: dict[str, str] = {
    "ffa": "mfl_id",
    "espn": "espn_id",
    "sleeper": "sleeper_id",
    "ecr": "fantasypros_id",
}


class PreflightError(RuntimeError):
    """An input is missing. Raised BEFORE any work, naming the file, never mid-run."""


@lru_cache(maxsize=8)
def league(key: str) -> Any:
    from audible.config import load_league

    path = REPO / "leagues" / f"{key}.toml"
    if not path.exists():
        raise PreflightError(f"league config missing: {path}")
    return load_league(path)


@lru_cache(maxsize=8)
def crosswalk(column: str) -> dict[str, str]:
    """`<column>` -> gsis_id, from the pinned ff_playerids table.

    Ids arrive as floats in the parquet ("12345.0"), so the trailing decimal is stripped. A
    source id that appears twice is dropped rather than resolved -- a wrong join silently
    credits the wrong player, which is the expensive kind of error.
    """
    import polars as pl

    path = CACHE / "nflverse" / "ff_playerids.parquet"
    if not path.exists():
        raise PreflightError(f"crosswalk missing: {path}")
    frame = pl.read_parquet(path)
    if column not in frame.columns:
        raise PreflightError(f"ff_playerids has no column {column!r}")
    pairs = (
        frame.select([column, "gsis_id"])
        .drop_nulls()
        .with_columns(pl.col(column).cast(pl.Utf8).str.replace(r"\.0$", ""))
    )
    seen: dict[str, str] = {}
    dupes: set[str] = set()
    for src, gsis in pairs.iter_rows():
        if src in seen and seen[src] != gsis:
            dupes.add(src)
        seen[src] = gsis
    for src in dupes:
        seen.pop(src, None)
    return seen


@dataclass(frozen=True, slots=True)
class Realised:
    """One season's realised per-game production, under one league's rulebook."""

    season: int
    league_key: str
    per_game: dict[str, float]  # gsis_id -> points per game played
    games: dict[str, int]  # gsis_id -> regular-season games with a row
    position: dict[str, str]  # gsis_id -> canonical position


def realised_per_game(season: int, league_key: str) -> Realised:
    """Score every regular-season player-week under *league_key*, then divide by games.

    Deliberately NOT `weekly.weekly_points`: that function is hard-wired to league 6012 plus
    its historical deltas, and forty sim gates depend on its exact output. This reproduces the
    same scoring path -- the same COLUMN_TO_KEY, the same 25-yard bucketing, the same return
    and fumble-recovery terms -- parameterised by league instead, and leaves that module alone.
    """
    import polars as pl

    from audible.scoring.engine import score_stat_line

    path = CACHE / "nflverse" / f"player_stats_{season}.parquet"
    if not path.exists():
        raise PreflightError(
            f"realised outcomes missing for {season}: {path}. Pin it before scoring; this "
            f"module never substitutes a nearby season."
        )
    config = league(league_key)
    frame = pl.read_parquet(path).filter(pl.col("season_type") == "REG").fill_null(0)

    totals: dict[str, float] = {}
    games: dict[str, int] = {}
    position: dict[str, str] = {}
    weights_cache: dict[str, dict[str, float]] = {}

    for row in frame.iter_rows(named=True):
        pos = room.canon_position(str(row.get("position") or ""))
        if pos not in SCOREABLE:
            continue
        weights = weights_cache.get(pos)
        if weights is None:
            weights = dict(config.scoring_for(pos))
            weights_cache[pos] = weights

        stats = {key: float(row.get(col) or 0.0) for col, key in COLUMN_TO_KEY.items()}
        stats["pass_yd"] = bucket25(float(row.get("passing_yards") or 0.0))
        pts = score_stat_line(stats, weights)
        pts += RETURN_YARD_POINTS * (
            bucket25(float(row.get("punt_return_yards") or 0.0))
            + bucket25(float(row.get("kickoff_return_yards") or 0.0))
        )
        pts += RETURN_TD_POINTS * float(row.get("special_teams_tds") or 0.0)
        pts += FUMBLE_RECOVERY_TD_POINTS * float(row.get("fumble_recovery_tds") or 0.0)

        pid = str(row["player_id"])
        totals[pid] = totals.get(pid, 0.0) + pts
        games[pid] = games.get(pid, 0) + 1
        position[pid] = pos

    per_game = {pid: totals[pid] / games[pid] for pid in totals if games[pid] > 0}
    return Realised(
        season=season, league_key=league_key, per_game=per_game, games=games,
        position=position,
    )


# --- the metric ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankScore:
    """Everything one (arm, season, league) cell reports."""

    rwre: float  # THE PRIMARY
    spearman: float
    top24_hit: float
    n: int
    per_position: dict[str, float]
    pool_size: int


def _weights(board_rank: int, teams: int) -> float:
    """1 / round. See the pre-registration for why round-decay and not inverse-rank."""
    return 1.0 / math.ceil(board_rank / teams)


def _realised_order(pool: list[str], realised: dict[str, float]) -> dict[str, int]:
    """Realised rank within the pool. A player with no production ranks last, deterministically.

    Not a special case: a board that ranked a player who never produced was wrong, and the
    metric has to be able to say so. `-1e18` sorts him below every real score, and the id
    breaks ties so two such players do not swap places between runs.
    """
    ordered = sorted(pool, key=lambda p: (-realised.get(p, -1e18), p))
    return {pid: i + 1 for i, pid in enumerate(ordered)}


def _spearman(a: dict[str, int], b: dict[str, int]) -> float:
    ids = sorted(a)
    n = len(ids)
    if n < 2:
        return float("nan")
    d2 = sum((a[i] - b[i]) ** 2 for i in ids)
    return 1.0 - (6.0 * d2) / (n * (n * n - 1))


def score_board(
    board: list[str],
    realised: dict[str, float],
    *,
    teams: int,
    pool_size: int,
    position: dict[str, str] | None = None,
) -> RankScore:
    """Round-weighted rank error for *board* against *realised*, over the top `pool_size`.

    *board* is gsis ids in the board's own preference order, best first.
    """
    pool = board[:pool_size]
    if not pool:
        raise ValueError("empty board")
    board_rank = {pid: i + 1 for i, pid in enumerate(pool)}
    real_rank = _realised_order(pool, realised)

    num = den = 0.0
    for pid, br in board_rank.items():
        w = _weights(br, teams)
        num += w * abs(br - real_rank[pid])
        den += w
    rwre = num / den if den else float("nan")

    top24 = set(pool[:24])
    real_top24 = {pid for pid, r in real_rank.items() if r <= 24}
    hit = len(top24 & real_top24) / 24.0 if len(pool) >= 24 else float("nan")

    per_pos: dict[str, float] = {}
    if position is not None:
        for pos in SCOREABLE:
            members = [p for p in pool if position.get(p) == pos]
            if len(members) < 5:
                continue
            # Re-ranked WITHIN the position, so QB depth does not flatter a positional number.
            b_in = {p: i + 1 for i, p in enumerate(members)}
            r_in = _realised_order(members, realised)
            n_ = d_ = 0.0
            for p, br in b_in.items():
                w = _weights(br, teams)
                n_ += w * abs(br - r_in[p])
                d_ += w
            per_pos[pos] = n_ / d_ if d_ else float("nan")

    return RankScore(
        rwre=rwre, spearman=_spearman(board_rank, real_rank), top24_hit=hit,
        n=len(pool), per_position=per_pos, pool_size=pool_size,
    )


def pool_size_for(league_key: str) -> int:
    cfg = league(league_key)
    rounds = cfg.draft_rounds or 16
    return int(cfg.num_teams) * int(rounds)
