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
  * THAT THE SHUFFLE FLOOR CONTAINS NO FOOTBALL. This is the phase-1 review's correction and
    it retracts this script's first headline. `rank._realised_order` replaces realised values
    with within-pool ranks and `rank._weights` reads only the two ranks, so a shuffled board's
    score is a function of `pool_size` and `teams` and of nothing else -- `permutation_floor`
    reproduces all three leagues' floors from synthetic ids with no data at all. The weekly and
    seasonal floors agree (53.1 / 66.4 / 79.6 against 52.8 / 65.9 / 78.7) because both modes
    score 128 / 160 / 190 pools at 8 / 10 / 10 teams. That is arithmetic. It is NOT evidence
    that the weekly problem is as hard as the seasonal one; the two would agree whichever was
    harder. The first version of this file inferred exactly that and was wrong.

    What the shuffle floor IS good for is a bar on the metric: if a shuffled REAL board departs
    from the synthetic permutation floor, the metric is reading something other than the two
    ranks. That check is now in `validate`.

VALIDATION RUNS FIRST AND THE SCRIPT REFUSES TO CONTINUE WITHOUT IT, weekly and seasonal.
`audible#85` caught a units bug this way on its first run: a VORP-ordered board scored against
points-ordered outcomes read 13.99 with every per-position figure at exactly 0.0. IT CAUGHT THE
SAME CLASS OF BUG AGAIN IN THIS SESSION -- the first seasonal G1 written here fed
`Realised.per_game` to a VORP-ordered perfect board and read 25.060311. That is why the weekly
side carries an explicit `scale`.

The perfect-board half of G1 is a tautology on its own and the review proved it; see
`validate`, where the cross-scale and permutation-floor checks that actually gate the units
live.

WHAT PHASE 1 DOES NOT ESTABLISH, stated because the review asked for it: the sd this script
publishes is the sd of the LEVEL, and what decides whether the weekly sample can resolve a
treatment is the sd of the PAIRED DIFFERENCE between two arms on the same scope. Phase 2
computes that; phase 1 does not, so "weekly resolves what six observations could not" is still
an open claim at the end of this file. Season-clustering is also live: the between-season mean
square is 59.689 against 16.970 within, ICC 0.130, so 118 weekly scopes are worth an effective
n near 39 for a season-level effect -- not 118.
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
    scored: int
    candidates: int


def _weekly(league: str, season: int, week: int, scale: str):
    """A board and its outcome on the same scale, grouped by the same position map."""
    board = s7.build_board(season, week, league, aggregation=AGGREGATION, scale=scale)
    realised = s7.realised_week(season, week, league)
    return board, realised.on(scale, position=board.position)


def validate(league: str, season: int, week: int, scale: str) -> None:
    """G1, and the phase-1 review's correction to it.

    THE PERFECT-BOARD CHECK ALONE IS A TAUTOLOGY and cannot catch the bug G1 exists for. A
    board sorted by `(-outcome[pid], pid)` is sorted by the SAME key `rank._realised_order`
    uses, so it reads 0.000000 against any outcome dict whatsoever -- the review demonstrated
    it against uniform random numbers. It is kept because it proves the metric is internally
    consistent, and the two checks below are what actually gate the units:

      CROSS-SCALE, ON THE PERFECT BOARD. The perfect board built from the OTHER scale's
      outcome, scored against THIS scale's outcome, must be strictly worse than 0.000000. That
      is precisely `audible#85`'s 13.99 -- a perfect answer in the wrong unit -- and it is a
      units invariant, so it can be gated.

      IT IS NOT "THE FFA BOARD ON THE RIGHT SCALE BEATS THE FFA BOARD ON THE WRONG SCALE." The
      first version of this gate asserted that and it FIRED on sleeper_boyfun 2024 wk8: a
      points-ordered board scored 51.413 against the vorp outcome where the vorp-ordered board
      scored 52.163. Which board ranks better is an empirical question about `compute_vorp` in a
      10-team SUPERFLEX league -- `rank.vorp_values` already records its `rostered_counts` as
      known wrong at QB -- not an invariant. It is reported below as a finding instead.

      CHANCE, against the analytic permutation floor rather than an arbitrary bar. The old test
      was `chance < score.rwre + 1.0` where `score.rwre` is always exactly 0, i.e. `chance <
      1.0`, which nothing could fail.
    """
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

    other = "points" if scale == "vorp" else "vorp"
    wrong_board, wrong_outcome = _weekly(league, season, week, other)
    wrong_perfect = sorted(
        [pid for pid in wrong_board.board if pid in wrong_outcome],
        key=lambda pid: (-wrong_outcome[pid], pid),
    )
    cross = s7.score_week(
        [pid for pid in wrong_perfect if pid in outcome], outcome, league,
        position=board.position,
    ).rwre
    if cross <= 1e-9:
        raise SystemExit(
            f"G1 FAILED weekly: {league} {season} wk{week} -- the PERFECT board on {other} "
            f"scored {cross:.6f} against a {scale} outcome. A right answer in the wrong unit "
            "must cost something; if it does not, the two scales are the same object and "
            "nothing here is gating units."
        )
    right = s7.score_week(board.board, outcome, league, position=board.position).rwre
    other_board = s7.score_week(
        wrong_board.board, outcome, league, position=board.position
    ).rwre

    pool = min(rank.pool_size_for(league), len(common))
    teams = int(rank.league(league).num_teams)
    floor_mean, floor_sd = s7.permutation_floor(pool, teams, draws=FLOOR_DRAWS, seed=SEED)
    rng = random.Random(SEED)
    shuffled = list(common)
    rng.shuffle(shuffled)
    chance = s7.score_week(shuffled, outcome, league, position=board.position).rwre
    if abs(chance - floor_mean) > 4 * floor_sd:
        raise SystemExit(
            f"G1 FAILED weekly: {league} {season} wk{week} scale {scale} -- a shuffled real "
            f"board scored {chance:.3f} against a football-free permutation floor of "
            f"{floor_mean:.3f} sd {floor_sd:.3f}. Those must agree; if they do not the metric "
            "is reading something other than the two ranks."
        )
    print(f"G1  {league} {season} wk{week} {scale}: perfect 0.000000, "
          f"perfect-in-wrong-unit {cross:.3f}, shuffled {chance:.3f}, "
          f"permutation floor {floor_mean:.3f}")
    verdict = "beaten by" if other_board < right else "beats"
    print(f"    FFA board ordered on {scale} scores {right:.3f}; ordered on {other} it scores "
          f"{other_board:.3f} against the same {scale} outcome -- {scale} {verdict} {other}")


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
        # `scored` is what enters RWRE; `candidates` is what was available to it. The first
        # report published the second and called it player-weeks, overstating green_hope's
        # sample by 2.4x. They are different numbers and both are printed.
        scored=score.n, candidates=len(common),
    )


def report(league: str, scale: str, results: list[ScopeResult]) -> None:
    ffa = [r.ffa for r in results]
    floor = [r.floor_mean for r in results]
    beat = sum(1 for r in results if r.ffa < r.floor_mean - 2 * r.floor_sd)
    print(f"== {league} {scale} ==")
    print(f"  scopes scored      {len(results)}")
    print(f"  player-weeks SCORED    {sum(r.scored for r in results)}"
          f"   (candidates {sum(r.candidates for r in results)})")
    print(f"  FFA  RWRE  mean {statistics.mean(ffa):7.3f}  sd {statistics.stdev(ffa):6.3f}"
          f"  min {min(ffa):7.3f}  max {max(ffa):7.3f}")
    print(f"  FLOOR RWRE mean {statistics.mean(floor):7.3f}"
          f"  sd {statistics.stdev(floor):6.3f}"
          f"  min {min(floor):7.3f}  max {max(floor):7.3f}")
    print(f"  within-scope floor sd  mean {statistics.mean(r.floor_sd for r in results):.3f}")
    pool = rank.pool_size_for(league)
    teams = int(rank.league(league).num_teams)
    synth_mean, synth_sd = s7.permutation_floor(pool, teams, draws=200, seed=SEED)
    print(f"  PERMUTATION floor (no football at all, pool {pool} teams {teams}): "
          f"{synth_mean:7.3f} sd {synth_sd:5.3f}")
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
    synth_mean, synth_sd = s7.permutation_floor(pool, teams, draws=200, seed=SEED)
    print(f"  PERMUTATION floor (no football at all, pool {pool} teams {teams}): "
          f"{synth_mean:7.3f} sd {synth_sd:5.3f}")
    print("  the weekly and seasonal floors agree BECAUSE the pool and team count agree.")
    print("  That is arithmetic, not a finding about weekly-vs-seasonal difficulty.")
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
    pinned = s7.pinned_actuals_seasons()
    print(f"   pinned for {pinned[0]}-{pinned[-1]} (read from disk, not asserted), so "
          f"{len(offered) - len(scopes)} weekly projections on disk")
    print("   have no pinned outcome and are NOT scored. No substitution.")
    print("   2015 is excluded: its weighted files carry sd without point estimates.")
    print("   2020 wk17 is excluded: FFA has no data, in any aggregation.")
    print()

    for league in LEAGUES:
        s7.preflight(scopes, league)
    print("preflight: every scope's projection and outcome present before any work")
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
