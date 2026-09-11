"""S7 phase 1 -- the weekly harness at full scale, and the noise floor as a distribution.

    uv run python -m sim.s7_phase1 > sim/runs/s7-phase1.txt

WHAT IT ESTABLISHES, and why each number is here rather than asserted:

  * The FFA weekly board's rank error across every scope the corpus AND the pinned outcomes
    can serve, per league, per position, on both value scales. This is the baseline every
    later phase moves against.
  * THE NOISE FLOOR AS A DISTRIBUTION, not a draw. `audible#88` measured 5 of 18
    dispositions flipping when a single floor draw was used instead of a distribution -- 28%,
    every one a false resolution. A shuffled board is scored `FLOOR_DRAWS` times per scope and
    the spread is reported.
  * How the weekly floor compares to the seasonal one. The whole premise of S7 is that the
    weekly sample is large enough to resolve what six observations could not, and that claim
    is only worth anything if both floors are on the page: +2 means one thing against a floor
    of 53 and another against a floor of 79.

VALIDATION RUNS FIRST AND THE SCRIPT REFUSES TO CONTINUE WITHOUT IT, weekly and seasonal. A
board built from the realised order must score exactly 0.000000 and a shuffled board must sit
at chance. `audible#85` caught a units bug this way on its first run: a VORP-ordered board
scored against points-ordered outcomes read 13.99 with every per-position figure at exactly
0.0. IT CAUGHT THE SAME CLASS OF BUG AGAIN IN THIS SESSION -- the first seasonal G1 written
here fed `Realised.per_game` to a VORP-ordered perfect board and read 25.060311. That is the
gate doing its job, and it is why the weekly side now carries an explicit `scale`.
"""

from __future__ import annotations

import random
import statistics
import sys
from dataclasses import dataclass

from . import rank
from . import s7_weekly as s7

LEAGUES: tuple[str, ...] = ("espn_green_hope", "espn_danger_zone", "sleeper_boyfun")
AGGREGATION = "weighted"

# Both are reported for every league. `vorp` is primary -- it is the scale the draft board
# ships on, so it is the only one on which phase 4's transfer question means anything.
SCALES: tuple[str, ...] = ("vorp", "points")

# Per scope. 40 is the pre-registered minimum from `audible#88`; it floors an achievable p at
# 0.0488, which is reported rather than treated as 0.05.
FLOOR_DRAWS = 40

# Deterministic, and seeded from the scope so two runs of this script agree and two different
# scopes do not share a shuffle.
SEED = 20260911


@dataclass(frozen=True, slots=True)
class ScopeResult:
    season: int
    week: int
    league: str
    scale: str
    ffa: float
    spearman: float
    top24: float
    per_position: dict[str, float]
    floor_mean: float
    floor_sd: float
    pool: int
    observations: int


def _weekly(league: str, season: int, week: int, scale: str):
    board = s7.build_board(season, week, league, aggregation=AGGREGATION, scale=scale)
    realised = s7.realised_week(season, week, league)
    return board, realised.on(scale)


def validate(league: str, season: int, week: int, scale: str) -> None:
    board, outcome = _weekly(league, season, week, scale)
    common = [pid for pid in board.board if pid in outcome]
    perfect = sorted(common, key=lambda pid: (-outcome[pid], pid))
    score = s7.score_week(perfect, outcome, league, position=board.position)
    if abs(score.rwre) > 1e-9:
        raise SystemExit(
            f"G1 FAILED weekly: {league} {season} wk{week} scale {scale} -- a board built "
            f"from the realised order scored {score.rwre:.6f}, not 0.000000. Nothing "
            "measured after this would mean anything."
        )
    rng = random.Random(SEED)
    shuffled = list(common)
    rng.shuffle(shuffled)
    chance = s7.score_week(shuffled, outcome, league, position=board.position).rwre
    if chance < score.rwre + 1.0:
        raise SystemExit(
            f"G1 FAILED weekly: {league} {season} wk{week} scale {scale} -- a shuffled board "
            f"scored {chance:.3f}, not at chance."
        )
    print(f"G1  {league} {season} wk{week} {scale}: perfect {score.rwre:.6f}, "
          f"shuffled {chance:.3f}")


def run_scope(league: str, season: int, week: int, scale: str) -> ScopeResult | None:
    try:
        board, outcome = _weekly(league, season, week, scale)
    except s7.ScopeMissing:
        return None
    common = [pid for pid in board.board if pid in outcome]
    if len(common) < 24:
        return None

    score = s7.score_week(board.board, outcome, league, position=board.position)
    rng = random.Random(SEED + season * 100 + week)
    draws = []
    for _ in range(FLOOR_DRAWS):
        shuffled = list(common)
        rng.shuffle(shuffled)
        draws.append(s7.score_week(shuffled, outcome, league, position=board.position).rwre)
    return ScopeResult(
        season=season, week=week, league=league, scale=scale,
        ffa=score.rwre, spearman=score.spearman, top24=score.top24_hit,
        per_position=dict(score.per_position),
        floor_mean=statistics.mean(draws), floor_sd=statistics.stdev(draws),
        pool=len(common), observations=len(outcome),
    )


def report(league: str, scale: str, results: list[ScopeResult]) -> None:
    ffa = [r.ffa for r in results]
    floor = [r.floor_mean for r in results]
    beat = sum(1 for r in results if r.ffa < r.floor_mean - 2 * r.floor_sd)
    print(f"== {league} {scale} ==")
    print(f"  scopes scored      {len(results)}")
    print(f"  player-weeks       {sum(r.pool for r in results)}")
    print(f"  FFA  RWRE  mean {statistics.mean(ffa):7.3f}  sd {statistics.stdev(ffa):6.3f}"
          f"  min {min(ffa):7.3f}  max {max(ffa):7.3f}")
    print(f"  FLOOR RWRE mean {statistics.mean(floor):7.3f}"
          f"  sd {statistics.stdev(floor):6.3f}"
          f"  min {min(floor):7.3f}  max {max(floor):7.3f}")
    print(f"  within-scope floor sd  mean {statistics.mean(r.floor_sd for r in results):.3f}")
    print(f"  scopes where FFA beats its own floor by 2sd: {beat}/{len(results)}")
    print(f"  spearman   mean {statistics.mean(r.spearman for r in results):.4f}")
    print(f"  top24 hit  mean {statistics.mean(r.top24 for r in results):.4f}")
    for position in ("QB", "RB", "WR", "TE"):
        vals = [r.per_position[position] for r in results if position in r.per_position]
        if vals:
            mean, sd = statistics.mean(vals), statistics.stdev(vals)
            print(f"  {position}  mean {mean:6.3f}  sd {sd:5.3f}  n {len(vals)}")
    by_season: dict[int, list[float]] = {}
    for r in results:
        by_season.setdefault(r.season, []).append(r.ffa)
    print("  by season:")
    for season in sorted(by_season):
        vals = by_season[season]
        print(f"    {season}  n {len(vals):2d}  mean {statistics.mean(vals):7.3f}"
              f"  sd {statistics.stdev(vals) if len(vals) > 1 else 0.0:6.3f}")


def seasonal(league: str) -> None:
    """G1 and the floor on the SEASONAL side, so the two modes are comparable.

    The seasonal outcome is `rank.realised_vorp`, not `Realised.per_game`: the board side is
    VORP-ordered and the two sides have to be the same unit. Feeding per-game points here read
    25.060311 for a perfect board on the first attempt written in this session.
    """
    pool = rank.pool_size_for(league)
    sizes = rank.position_pool_sizes(league)
    teams = int(rank.league(league).num_teams)
    per_season = []
    for season in rank.SEASONS_BY_ARM["ffa"]:
        real = rank.realised_per_game(season, league)
        order = rank.realised_order(real)
        outcome = rank.realised_vorp(real)
        perfect = rank.score_board(
            order, outcome, teams=teams, pool_size=pool,
            position=real.position, indexing="symmetric", position_pool=sizes,
        )
        if abs(perfect.rwre) > 1e-9:
            raise SystemExit(
                f"G1 FAILED seasonally: {league} {season} perfect board scored "
                f"{perfect.rwre:.6f}, not 0.000000."
            )
        rng = random.Random(SEED + season)
        draws = []
        for _ in range(FLOOR_DRAWS):
            shuffled = list(order)
            rng.shuffle(shuffled)
            draws.append(
                rank.score_board(
                    shuffled, outcome, teams=teams, pool_size=pool,
                    position=real.position, indexing="symmetric", position_pool=sizes,
                ).rwre
            )
        per_season.append((season, statistics.mean(draws), statistics.stdev(draws)))
    print(f"== {league} SEASONAL ==")
    print(f"  observations {len(per_season)}  pool_size {pool}")
    print("  perfect board 0.000000 in every season: yes")
    means = [m for _, m, _ in per_season]
    print(f"  FLOOR RWRE mean {statistics.mean(means):7.3f}"
          f"  sd {statistics.stdev(means):6.3f}"
          f"  min {min(means):7.3f}  max {max(means):7.3f}")
    for season, mean, sd in per_season:
        print(f"    {season}  floor {mean:7.3f}  within-season sd {sd:5.3f}")


def main() -> int:
    print("S7 PHASE 1 -- weekly harness, full scale")
    print(f"aggregation {AGGREGATION}, floor draws {FLOOR_DRAWS} per scope, seed {SEED}")
    print(f"scales {SCALES} -- vorp is primary, it is what the draft board ships")
    print()

    offered = s7.available_scopes(AGGREGATION)
    scopes = s7.available_scopes(AGGREGATION, require_actuals=True)
    print(f"-- {len(scopes)} scopes scoreable for {AGGREGATION} --")
    print(f"   the corpus offers {len(offered)}; the outcome side binds. player_stats is")
    print(f"   pinned for {s7.ACTUALS_SEASONS[0]}-{s7.ACTUALS_SEASONS[-1]}, so "
          f"{len(offered) - len(scopes)} weekly projections on disk")
    print("   have no pinned outcome and are NOT scored. No substitution.")
    print("   2015 is excluded: its weighted files carry sd without point estimates.")
    print("   2020 wk17 is excluded: FFA has no data, in any aggregation.")
    print()

    print("-- G1 validation, weekly, one scope per league per scale --")
    for scale in SCALES:
        for league in LEAGUES:
            validate(league, 2024, 8, scale)
    print()

    for scale in SCALES:
        for league in LEAGUES:
            results = [
                r for s, w in scopes if (r := run_scope(league, s, w, scale)) is not None
            ]
            if not results:
                print(f"{league} {scale}: no scopes scored")
                continue
            report(league, scale, results)
            print()

    print("-- SEASONAL mode: G1 and the floor, for comparison --")
    for league in LEAGUES:
        seasonal(league)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
