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


# The three ways to index the error weight. See sim/runs/s2b-search.md.
#
# `board` is audible#84's, and its own adversarial review measured it as 4.4x ASYMMETRIC:
# burying the best player at rank 128 costs 1.29, promoting the worst to rank 1 costs 5.66.
# That follows from weighting by the pick you SPEND, so it prices "do not draft a bust early"
# and is nearly blind to "find a sleeper". A source or signal could differ substantially at
# late-round value and that metric structurally could not see it.
#
# `realised` is the mirror and has the mirror blindness: it weights by how good the player
# turned out to be, so burying a star is expensive and rostering a bust is nearly free.
#
# `symmetric` takes the LARGER of the two. An error is costly if EITHER the pick was expensive
# OR the player was valuable, which is the only one of the three that prices both failures.
INDEXINGS: tuple[str, ...] = ("board", "realised", "symmetric")


def _weights(
    board_rank: int, teams: int, realised_rank: int | None = None, indexing: str = "board"
) -> float:
    """Round-decay weight, indexed as *indexing* says. `board` reproduces audible#84 exactly."""
    b = 1.0 / math.ceil(board_rank / teams)
    if indexing == "board" or realised_rank is None:
        return b
    r = 1.0 / math.ceil(realised_rank / teams)
    if indexing == "realised":
        return r
    if indexing == "symmetric":
        return max(b, r)
    raise ValueError(f"unknown indexing {indexing!r}; expected one of {list(INDEXINGS)}")


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
    indexing: str = "board",
    position_pool: dict[str, int] | None = None,
) -> RankScore:
    """Round-weighted rank error for *board* against *realised*, over the top `pool_size`.

    *board* is gsis ids in the board's own preference order, best first.

    *position_pool* sets how many players each position contributes to its own score. It has to
    be board-independent -- `position_pool_sizes` derives it from the league config alone.
    """
    pool = board[:pool_size]
    if not pool:
        raise ValueError("empty board")
    board_rank = {pid: i + 1 for i, pid in enumerate(pool)}
    real_rank = _realised_order(pool, realised)

    num = den = 0.0
    for pid, br in board_rank.items():
        w = _weights(br, teams, real_rank[pid], indexing)
        num += w * abs(br - real_rank[pid])
        den += w
    rwre = num / den if den else float("nan")

    top24 = set(pool[:24])
    real_top24 = {pid for pid, r in real_rank.items() if r <= 24}
    hit = len(top24 & real_top24) / 24.0 if len(pool) >= 24 else float("nan")

    per_pos: dict[str, float] = {}
    if position is not None:
        sizes = position_pool or {}
        default_n = max(5, pool_size // len(SCOREABLE))
        for pos in SCOREABLE:
            # THE POSITION'S OWN TOP-N, TAKEN FROM THE FULL BOARD -- not from the global pool.
            #
            # S6 G1. Slicing the global top-`pool_size` made this metric depend on the
            # CROSS-POSITION INTERLEAVE: a term that never reorders anyone inside a position
            # still changed which of its players fell inside the global pool, and the score
            # moved. `availability` -- provably a within-position constant, so provably unable
            # to reorder a position -- read RB +0.159, QB -0.036, WR -0.028 under the old rule
            # and reads exactly +0.0000 everywhere under this one.
            #
            # `position_pool` must NEVER be derived from the board under test. See
            # `position_pool_sizes`, which reads the league config and nothing else.
            members = [p for p in board if position.get(p) == pos][:sizes.get(pos, default_n)]
            if len(members) < 5:
                continue
            # Re-ranked WITHIN the position, so QB depth does not flatter a positional number.
            b_in = {p: i + 1 for i, p in enumerate(members)}
            r_in = _realised_order(members, realised)
            n_ = d_ = 0.0
            for p, br in b_in.items():
                w = _weights(br, teams, r_in[p], indexing)
                n_ += w * abs(br - r_in[p])
                d_ += w
            per_pos[pos] = n_ / d_ if d_ else float("nan")

    return RankScore(
        rwre=rwre, spearman=_spearman(board_rank, real_rank), top24_hit=hit,
        n=len(pool), per_position=per_pos, pool_size=pool_size,
    )


@lru_cache(maxsize=8)
def position_pool_sizes(league_key: str) -> dict[str, int]:
    """How many players each position contributes to its own per-position score.

    DERIVED FROM THE LEAGUE CONFIG AND NOTHING ELSE, which is the whole point. Any rule that
    reads the board under test reintroduces S6 G1's defect: the per-position metric then moves
    when the cross-position interleave moves, even for a term that provably cannot reorder
    anyone inside a position.

    Each starting slot contributes `num_teams` demand, split evenly across the scoreable
    positions eligible for it, so a FLEX adds a third each to RB, WR and TE. The league's whole
    draft is then apportioned in that ratio. For `espn_green_hope` -- 8 teams, 16 rounds,
    slots QB/RB/RB/WR/WR/TE/FLEX/DEF/K -- that is QB 18, RB 43, WR 43, TE 24.

    A position's own ordering does not depend on N, so a term that cannot reorder a position
    reads exactly +0.000 at EVERY N. N only sets how deep the question is asked.
    """
    cfg = league(league_key)
    teams = int(cfg.num_teams)
    demand = dict.fromkeys(SCOREABLE, 0.0)
    for slot in cfg.starting_slots:
        eligible = [p for p in cfg.slot_eligibility[slot] if p in SCOREABLE]
        for p in eligible:
            demand[p] += teams / len(eligible)
    total = sum(demand.values())
    if total <= 0:
        raise PreflightError(f"{league_key} has no scoreable starting slots")
    pool = pool_size_for(league_key)
    return {p: max(5, round(pool * d / total)) for p, d in demand.items() if d > 0}


def pool_size_for(league_key: str) -> int:
    cfg = league(league_key)
    rounds = cfg.draft_rounds or 16
    return int(cfg.num_teams) * int(rounds)


# --- the ordering under test: VORP, identical on both sides ---------------------------------


def vorp_values(
    points: dict[str, float],
    position: dict[str, str],
    league_key: str,
    *,
    names: dict[str, str] | None = None,
) -> dict[str, float]:
    """Player ids ordered by value over replacement, best first.

    The SAME function orders the board side and the realised side -- see AMENDMENT 1 in
    `sim/runs/s2-ranking.md`. Ordering the realised side by raw points would rank a 27-a-game
    quarterback above a 19-a-game running back in a league that starts one quarterback, and
    would therefore mark a board DOWN for correctly pricing scarcity.

    `compute_vorp` is production's own, used unchanged. Its `rostered_counts` is known wrong at
    QB; that defect lands identically on every arm and is Task 4's subject.
    """
    from audible.models.player import PlayerProjection
    from audible.value.replacement import compute_vorp

    config = league(league_key)
    players = [
        PlayerProjection(
            player_id=pid,
            name=(names or {}).get(pid, pid),
            primary_position=pos,
            eligible_positions=frozenset({pos}),
            team=None,
            points=points[pid],
        )
        for pid, pos in position.items()
        if pid in points and pos in SCOREABLE
    ]
    if not players:
        return []
    entries, _levels = compute_vorp(players, config)
    return {e.projection.player_id: e.vorp for e in entries}


def vorp_order(
    points: dict[str, float],
    position: dict[str, str],
    league_key: str,
    *,
    names: dict[str, str] | None = None,
) -> list[str]:
    """Player ids ordered by VORP, best first. Ties broken by id, so runs are reproducible."""
    values = vorp_values(points, position, league_key, names=names)
    return sorted(values, key=lambda pid: (-values[pid], pid))


def realised_vorp(realised: Realised) -> dict[str, float]:
    """What each player was actually WORTH per game, on the same scale a board is built on.

    THE UNIT ON BOTH SIDES HAS TO MATCH, and G1 is what caught it not matching. Scoring a
    VORP-ordered board against raw realised POINTS gave the perfect board an error of 13.99
    instead of 0.0, with every per-position figure at 0.0 -- because VORP and points agree
    WITHIN a position and disagree ACROSS positions by exactly the replacement level. The
    cross-position disagreement was the whole 13.99.
    """
    return vorp_values(realised.per_game, realised.position, realised.league_key)


def realised_order(realised: Realised) -> list[str]:
    """The perfect board: realised per-game production, put through the same transform."""
    return vorp_order(realised.per_game, realised.position, realised.league_key)


# --- iteration 2: prior-season usage as a projection correction -----------------------------

USAGE_POSITIONS: tuple[str, ...] = ("RB", "WR", "TE")


@lru_cache(maxsize=16)
def prior_target_share(season: int) -> dict[str, float]:
    """Mean weekly target share observed in season-1, by gsis id.

    Available BEFORE season *season* is drafted, which is what makes it usable rather than a
    leak. `target_share` is a native per-week column in the pinned frames; nothing is
    reconstructed here.
    """
    import polars as pl

    path = CACHE / "nflverse" / f"player_stats_{season - 1}.parquet"
    if not path.exists():
        raise PreflightError(
            f"prior-season usage missing for {season}: {path}. Never substituted."
        )
    frame = (
        pl.read_parquet(path)
        .filter(pl.col("season_type") == "REG")
        .select(["player_id", "target_share"])
        .drop_nulls()
    )
    agg = frame.group_by("player_id").agg(pl.col("target_share").mean().alias("ts"))
    return {str(pid): float(ts) for pid, ts in agg.iter_rows()}


def usage_adjusted(
    points: dict[str, float],
    position: dict[str, str],
    season: int,
    lam: float,
) -> dict[str, float]:
    """`points * (1 + lam * z)`, z being the within-position target-share z-score.

    ABSENCE IS NOT ZERO. A player with no prior season -- every rookie -- gets no adjustment at
    all, keeping his projected points untouched. Coding absence as a zero z-score would park
    every rookie on the positional mean and move him on a number nobody measured.

    `lam = 0` returns the input unchanged, so the baseline nests exactly inside the treatment.
    """
    if lam == 0.0:
        return dict(points)
    share = prior_target_share(season)
    out = dict(points)
    for pos in USAGE_POSITIONS:
        members = [p for p in points if position.get(p) == pos and p in share]
        if len(members) < 10:
            continue
        vals = [share[p] for p in members]
        mu = sum(vals) / len(vals)
        var = sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)
        sd = math.sqrt(var)
        if sd <= 0:
            continue
        for p in members:
            out[p] = points[p] * (1.0 + lam * ((share[p] - mu) / sd))
    return out


@lru_cache(maxsize=32)
def prior_share(season: int, column: str) -> dict[str, float]:
    """Mean weekly *column* observed in season-1, by gsis id. Generalises the usage signal."""
    import polars as pl

    path = CACHE / "nflverse" / f"player_stats_{season - 1}.parquet"
    if not path.exists():
        raise PreflightError(f"prior-season usage missing for {season}: {path}")
    frame = (
        pl.read_parquet(path)
        .filter(pl.col("season_type") == "REG")
        .select(["player_id", column])
        .drop_nulls()
    )
    agg = frame.group_by("player_id").agg(pl.col(column).mean().alias("v"))
    return {str(pid): float(v) for pid, v in agg.iter_rows()}


def share_adjusted(
    points: dict[str, float],
    position: dict[str, str],
    season: int,
    lam: float,
    column: str,
) -> dict[str, float]:
    """`usage_adjusted`, for any per-week share column. Absence still means no adjustment."""
    if lam == 0.0:
        return dict(points)
    share = prior_share(season, column)
    out = dict(points)
    for pos in USAGE_POSITIONS:
        members = [p for p in points if position.get(p) == pos and p in share]
        if len(members) < 10:
            continue
        vals = [share[p] for p in members]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1))
        if sd <= 0:
            continue
        for p in members:
            out[p] = points[p] * (1.0 + lam * ((share[p] - mu) / sd))
    return out


# --- iteration 4: how deep a 1-QB league really rosters quarterbacks ------------------------


def vorp_values_qb_depth(
    points: dict[str, float],
    position: dict[str, str],
    league_key: str,
    q: float,
) -> dict[str, float]:
    """VORP with QB rostered depth overridden to `round(teams * q)`.

    `q = 1.0` does not override at all, so it nests `vorp_values` EXACTLY rather than
    approximately -- a gate asserts the two agree to the cent.

    `rostered_counts` hands the bench only to positions with `_startable_slots >= 2`. A
    quarterback in a 1-QB league is eligible for one slot, so he is grouped with D/ST and K and
    gets none, putting replacement at QB9 in an 8-team league. Replacement points are read at
    `at_pos[rostered]`, so under-counting sets QB replacement too HIGH, which depresses QB VORP
    and pushes quarterbacks down the board.
    """
    from audible.models.player import PlayerProjection
    from audible.value.replacement import _ranked, assign_starters, rostered_counts

    config = league(league_key)
    players = [
        PlayerProjection(
            player_id=pid, name=pid, primary_position=pos,
            eligible_positions=frozenset({pos}), team=None, points=points[pid],
        )
        for pid, pos in position.items()
        if pid in points and pos in SCOREABLE
    ]
    if not players:
        return {}
    starters = assign_starters(players, config)
    rostered = dict(rostered_counts(players, config, starters))
    if q != 1.0:
        rostered["QB"] = max(1, round(int(config.num_teams) * q))

    levels: dict[str, float] = {}
    for pos in {p.primary_position for p in players}:
        at_pos = [p for p in _ranked(players) if p.primary_position == pos]
        taken = rostered.get(pos, 0)
        levels[pos] = at_pos[taken].points if taken < len(at_pos) else 0.0
    return {p.player_id: p.points - levels[p.primary_position] for p in players}
