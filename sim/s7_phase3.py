"""S7 phase 3 -- adjudicate the new metrics, on the same machinery phase 2 used.

    uv run python -m sim.s7_phase3 espn_green_hope  >> sim/runs/s7-phase3.txt

NOTHING ABOUT THE ADJUDICATION IS NEW. `GRID`, `loso`, `reference_p`, `clustered_interval`,
`MATERIAL` and the salted floor are imported from `sim/s7_phase2.py` rather than rewritten, so a
new metric is held to the identical bar as a re-adjudicated old signal and the two sets of numbers
are comparable. What is new is the metrics, and they live in `sim/s7_metrics.py` with the
mechanism for each stated above its code.

TWO KINDS OF THING ARE TESTED HERE.

  PART A, six TERMS, scored exactly as phase 2 scores a signal: `points * (1 + lam * z)` with lam
  selected leave-one-season-out over a grid containing 0.0. The only difference from phase 2 is
  that a term may read the week, not just the season, because a weekly file carries per-week
  columns the board has never opened.

  PART B, one BOARD CONSTRUCTION, which the lam framework cannot express. "Floor early, ceiling
  late" needs the tilt to change SIGN down the board, so it is run as its own experiment: order by
  `points + tilt(rank) * k * sd` and select k out of sample. Its floor SHUFFLES THE SD ASSIGNMENT
  among players rather than drawing a hash -- that preserves the marginal distribution of sd
  exactly and destroys only the pairing between a player and his own uncertainty, which is the
  thing under test.

THE COMPOSITE IS NOT HERE AND THAT IS DELIBERATE. The handoff lists "a composite value metric
replacing raw VORP" as a phase-3 candidate. A composite is a combination of terms, and which terms
it may contain is not known until phases 2 and 3 have finished; building it here would mean
choosing its members from results this phase is still producing. It is phase 4's first job --
"combine what survived" -- and it is recorded here so that the omission is a decision rather than
a gap.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

from . import rank
from . import s7_metrics as metrics
from . import s7_phase2 as p2
from . import s7_weekly as s7

# Pre-registered before any phase-3 number exists: where each new metric is expected to act.
LOCUS: dict[str, tuple[str, ...]] = {
    # A designation is a designation at every position, and it is a board-level fact about
    # availability rather than a within-position skill, so the board is its locus and the
    # positions are reported beside it.
    "inj_status": (),
    # The aging curve is steepest at running back and flattest at quarterback.
    "true_age": ("RB",),
    "true_experience": ("RB", "WR", "TE"),
    # Dispersion is a property of a projection, and every position has one.
    "weekly_sd_rel": ("QB", "RB", "WR", "TE"),
    # A changed role shows up where touches are reallocated: the skill positions.
    "role_change_snaps": ("RB", "WR", "TE"),
    "role_change_proj": ("RB", "WR", "TE"),
}

# The STANDARDISATION SCOPE is not the same question as the locus. A designation means the same
# thing at every position, so `inj_status` is z-scored across the whole board; everything else
# separates players inside a position and is z-scored there, which is `signals.adjust`'s default.
SCOPE: dict[str, str] = {"inj_status": "board"}

WHY: dict[str, str] = {
    "inj_status": "the file says Out and the board ranks him anyway. The question is whether "
                  "the PROJECTION has already priced it.",
    "true_age": "fixes a documented defect: `age_at_export` is stamped at export time and is "
                "wrong by up to seven years in level.",
    "true_experience": "season_year minus draft_year, both in the file. The arithmetic against "
                       "the vendor's own count.",
    "weekly_sd_rel": "at equal projected points, prefer the player the projection is more "
                     "confident about. Present in all 612 files, never read.",
    "role_change_snaps": "a projection prices a KNOWN role; a role that just changed is where "
                         "the market has not caught up. Snap share in week N-1 against the four "
                         "weeks before it.",
    "role_change_proj": "the same idea read from the market: this week's projection minus last "
                        "week's.",
}

# Part B. `k` multiplies the week's own projected sd; 0.0 is the incumbent board.
TILT_GRID: tuple[float, ...] = (0.0, 0.10, 0.25, 0.50, 1.00)

# Which slice of the board is treated as "early" and which as "late". A third each, with the
# middle third untouched, so the construction is a tilt and not a re-scaling of everything.
TILT_FRACTION = 1.0 / 3.0


def build_series(name: str, loaded: dict[p2.Scope, Any], league: str,
                 *, salt: int | None = None, frozen: set[str] | None = None) -> p2.Series:
    """Phase 2's `build_series`, with a WEEK-aware values function instead of a season one."""
    fn = metrics.METRICS[name]
    series = p2.Series()
    for lam in p2.GRID:
        series.treated[lam] = {}
        series.treated_pos[lam] = {pos: {} for pos in p2.POSITIONS}
    for scope, (board, outcome, base) in sorted(loaded.items()):
        season, week = scope
        try:
            values = fn(board, season, week, league)
        except (rank.PreflightError, s7.ScopeMissing):
            continue
        if not values:
            continue
        covered = [pid for pid in board.projected if pid in values]
        if not covered:
            continue
        inject = (
            p2.floor_values(
                values, covered, board.position, frozen or set(), season * 100 + week, salt
            )
            if salt is not None else values
        )
        series.base[scope] = base.rwre
        for pos, value in base.per_position.items():
            series.base_pos.setdefault(pos, {})[scope] = value
        for lam in p2.GRID:
            if lam == 0.0:
                series.treated[lam][scope] = base.rwre
                for pos, value in base.per_position.items():
                    series.treated_pos[lam][pos][scope] = value
                continue
            score = p2._treated(
                board, outcome, league, season, lam, "noise", inject,
                scope=SCOPE.get(name, "position"),
            )
            series.treated[lam][scope] = score.rwre
            for pos, value in score.per_position.items():
                series.treated_pos[lam][pos][scope] = value
    return series


def coverage(name: str, loaded: dict[p2.Scope, Any],
             league: str) -> dict[int, tuple[float, float, int, int]]:
    """season -> (mean players with a value, mean board size, scopes with values, scopes).

    AVERAGED OVER EVERY SCOPE IN THE SEASON, not read off the first one, and the first version of
    this function did read off the first one. Week 1 is the first scope and `role_change_snaps`
    returns nothing before week 3 by construction -- it needs a prior week and a baseline behind
    it -- so sampling week 1 reported 0.0% coverage for all seven seasons and the NOT MEASURABLE
    guard killed the metric the handoff calls the most promising thing in it. A coverage number
    that depends on which scope you happen to look at is not a coverage number.
    """
    fn = metrics.METRICS[name]
    have: dict[int, list[int]] = {}
    total: dict[int, list[int]] = {}
    for scope, (board, _outcome, _base) in sorted(loaded.items()):
        season, week = scope
        try:
            values = fn(board, season, week, league)
        except (rank.PreflightError, s7.ScopeMissing):
            values = {}
        have.setdefault(season, []).append(sum(1 for pid in board.projected if pid in values))
        total.setdefault(season, []).append(len(board.projected))
    return {
        season: (
            statistics.mean(have[season]), statistics.mean(total[season]),
            sum(1 for n in have[season] if n > 0), len(have[season]),
        )
        for season in sorted(have)
    }


def frozen_positions(name: str, loaded: dict[p2.Scope, Any], league: str) -> set[str]:
    """Positions where this metric holds one distinct value, so it cannot reorder them.

    The same question `s7_phase2.constant_within_position` asks, and the floor needs the answer:
    a term that is constant inside a position must be permuted ACROSS positions or the floor
    manufactures spread the treatment provably cannot have.
    """
    fn = metrics.METRICS[name]
    for scope, (board, _outcome, _base) in sorted(loaded.items()):
        season, week = scope
        try:
            values = fn(board, season, week, league)
        except (rank.PreflightError, s7.ScopeMissing):
            continue
        if not values:
            continue
        out: set[str] = set()
        for pos in p2.POSITIONS:
            members = [pid for pid, held in board.position.items()
                       if held == pos and pid in values]
            if members and len({values[pid] for pid in members}) <= 1:
                out.add(pos)
        return out
    return set()


def run_metric(name: str, loaded: dict[p2.Scope, Any], league: str) -> dict[str, Any]:
    locus = LOCUS[name]
    print(f"-- {name} --")
    print(f"   LOCUS (pre-registered): {'board-level only' if not locus else ' '.join(locus)}")
    print(f"   mechanism: {WHY[name]}")
    print(f"   standardisation scope: {SCOPE.get(name, 'position')}")

    cov = coverage(name, loaded, league)
    print("   coverage, mean players with a value / mean board size, and scopes with any:")
    for season in sorted(cov):
        have, total, scopes_with, scopes = cov[season]
        print(f"    {season}  {have:6.1f} / {total:6.1f}  "
              f"{(have / total if total else 0.0):5.1%}   scopes {scopes_with}/{scopes}")
    if not any(have > 0 for have, _t, _sw, _s in cov.values()):
        print("   NOT MEASURABLE on this window.")
        print()
        return {"metric": name, "league": league, "verdict": "not measurable"}

    frozen = frozen_positions(name, loaded, league)
    if frozen:
        print(f"   structurally unable to reorder: {' '.join(sorted(frozen))}")
    series = build_series(name, loaded, league)
    if not series.base:
        print("   NOT MEASURABLE: no scope produced values.")
        print()
        return {"metric": name, "league": league, "verdict": "not measurable"}
    selected, effects, chosen = p2.loso(series.base, series.treated)
    at_fixed = p2.fixed(series.base, series.treated, p2.FIXED_LAMBDA)
    print(f"   scopes measured {len(series.base)}   lambda chosen out of sample per season: "
          f"{' '.join(f'{s}:{chosen[s]:g}' for s in sorted(chosen))}")
    print(f"   effect board-wide, SELECTED  {selected:+7.4f}   "
          f"(at fixed lambda {p2.FIXED_LAMBDA}: {at_fixed:+7.4f})")

    record: dict[str, Any] = {
        "metric": name, "league": league, "locus": list(locus),
        "effect_board": selected, "effect_board_fixed": at_fixed,
        "chosen": {str(k): v for k, v in chosen.items()},
    }
    pos_selected: dict[str, float] = {}
    for pos in p2.POSITIONS:
        if pos not in series.base_pos:
            continue
        value, _per, _c = p2.loso(
            series.base_pos[pos], {lam: series.treated_pos[lam][pos] for lam in p2.GRID}
        )
        pos_selected[pos] = value
        print(f"    {pos}  SELECTED {value:+7.4f}{'  <- locus' if pos in locus else ''}")
    record["per_position"] = pos_selected

    floor_board: list[float] = []
    floor_pos: dict[str, list[float]] = {pos: [] for pos in p2.POSITIONS}
    for salt in range(p2.FLOOR_DRAWS):
        drawn = build_series(name, loaded, league, salt=salt, frozen=frozen)
        value, _e, _c = p2.loso(drawn.base, drawn.treated)
        floor_board.append(value)
        for pos in p2.POSITIONS:
            if pos in drawn.base_pos:
                pos_value, _e2, _c2 = p2.loso(
                    drawn.base_pos[pos],
                    {lam: drawn.treated_pos[lam][pos] for lam in p2.GRID},
                )
                floor_pos[pos].append(pos_value)
    usable = [f for f in floor_board if f == f]
    print(f"   FLOOR, {p2.FLOOR_DRAWS} salts matched to this metric's coverage, same selection:")
    print(f"    board-wide  mean {statistics.mean(usable):+7.4f} "
          f"sd {statistics.stdev(usable):.4f} max {max(usable):+7.4f}")
    p_board = p2.reference_p(selected, floor_board)
    p_board_harm = p2.harm_p(selected, floor_board)
    print(f"    reference-set p, board-wide: {p_board:.4f}  (harm p {p_board_harm:.4f}; "
          f"best possible {p2.achievable_p(selected, floor_board):.4f})")
    record["p_board"] = p_board
    record["p_board_harm"] = p_board_harm
    record["achievable_p_board"] = p2.achievable_p(selected, floor_board)
    record["null_hit_rate_board"] = p2.null_hit_rate(selected, floor_board)
    record["floor_board_mean"] = statistics.mean(usable)
    record["p_position"] = {}
    record["harm_p_position"] = {}
    record["achievable_p_position"] = {}
    record["null_hit_rate_position"] = {}
    for pos in p2.POSITIONS:
        if pos in pos_selected and floor_pos[pos]:
            p_pos = p2.reference_p(pos_selected[pos], floor_pos[pos])
            record["p_position"][pos] = p_pos
            record["harm_p_position"][pos] = p2.harm_p(pos_selected[pos], floor_pos[pos])
            record["achievable_p_position"][pos] = p2.achievable_p(
                pos_selected[pos], floor_pos[pos]
            )
            record["null_hit_rate_position"][pos] = p2.null_hit_rate(
                pos_selected[pos], floor_pos[pos]
            )
            print(f"    reference-set p, {pos}: {p_pos:.4f}  "
                  f"(floor mean {statistics.mean(floor_pos[pos]):+.4f}, "
                  f"best possible {record['achievable_p_position'][pos]:.4f})"
                  f"{'  <- locus' if pos in locus else ''}")

    lo, hi = p2.clustered_interval(effects, by="season", seed=p2.SEED)
    slo, shi = p2.clustered_interval(effects, by="scope", seed=p2.SEED)
    print(f"   season-clustered 95% interval (PRIMARY, reported only): [{lo:+.4f}, {hi:+.4f}]")
    print(f"   scope-clustered  95% interval (reported only):          [{slo:+.4f}, {shi:+.4f}]")
    print("   player-clustered: NOT COMPUTED. See s7_phase2's module docstring.")
    record["interval_season"] = [lo, hi]
    record["interval_scope"] = [slo, shi]
    print("   SEASONAL: NOT APPLICABLE -- this metric reads a per-week column, and a preseason "
          "board has no week. Phase 4 tests whether it transfers.")
    record["seasonal"] = None

    # THE SAME VERDICT FUNCTION PHASE 2 USES, imported rather than copied: the adversarial
    # review found three defects in the first copy and a second copy would have kept them.
    record.update(
        p2.verdict_of(record, locus, selected, pos_selected, p_board, p_board_harm, frozen)
    )
    print(f"   VERDICT: {record['verdict']}  {record['verdict_why']}")
    print()
    return record


# --- PART B: floor early, ceiling late ------------------------------------------------------


def tilt_board(board: Any, sd: dict[str, float], k: float) -> list[str]:
    """Order by `points + tilt(rank) * k * sd`: floor at the top, ceiling at the tail.

    The tilt is applied against the INCUMBENT ordering's rank, not against the tilted one, so the
    construction is well defined and does not chase its own tail.
    """
    if k == 0.0:
        return list(board.board)
    n = len(board.board)
    cut = max(1, int(n * TILT_FRACTION))
    adjusted: dict[str, float] = {}
    for index, pid in enumerate(board.board):
        spread = sd.get(pid, 0.0)
        if index < cut:
            tilt = -1.0  # early: prefer the SAFER player, so penalise dispersion
        elif index >= n - cut:
            tilt = +1.0  # late: prefer the SWINGIER player
        else:
            tilt = 0.0
        adjusted[pid] = board.value[pid] + tilt * k * spread
    return sorted(adjusted, key=lambda pid: (-adjusted[pid], pid))


def run_tilt(loaded: dict[p2.Scope, Any], league: str) -> dict[str, Any]:
    print("-- floor_ceiling_tilt (PART B, a board construction, not a lambda term) --")
    print("   LOCUS (pre-registered): board-level. The construction is about WHERE on the board "
          "a player sits, so it has no positional locus by definition.")
    print("   mechanism: an early pick needs a starter who will not bust; a late pick is only "
          "worth making if it can win a week. Both readings use the same per-week sd.")
    print(f"   k grid {TILT_GRID}, tilt applied to the top and bottom "
          f"{TILT_FRACTION:.0%} of the board")

    base: dict[p2.Scope, float] = {}
    treated: dict[float, dict[p2.Scope, float]] = {k: {} for k in TILT_GRID}
    for scope, (board, outcome, baseline) in sorted(loaded.items()):
        season, week = scope
        meta = metrics.weekly_meta(season, week, league)
        if not meta.sd_points:
            continue
        base[scope] = baseline.rwre
        for k in TILT_GRID:
            order = tilt_board(board, meta.sd_points, k)
            treated[k][scope] = (
                baseline.rwre if k == 0.0
                else s7.score_week(order, outcome, league, position=board.position).rwre
            )
    selected, effects, chosen = p2.loso(base, treated)
    print(f"   scopes measured {len(base)}   k chosen out of sample per season: "
          f"{' '.join(f'{s}:{chosen[s]:g}' for s in sorted(chosen))}")
    print(f"   effect board-wide, SELECTED  {selected:+7.4f}")
    for k in TILT_GRID:
        if k == 0.0:
            continue
        deltas = [base[s] - treated[k][s] for s in base if s in treated[k]]
        print(f"    at fixed k {k:4.2f}: {statistics.mean(deltas):+7.4f}")

    # THE FLOOR SHUFFLES THE SD ASSIGNMENT rather than hashing a new value. That keeps the
    # marginal distribution of sd exactly and destroys only the pairing between a player and his
    # own uncertainty, which is precisely the thing being tested.
    floor: list[float] = []
    for salt in range(p2.FLOOR_DRAWS):
        rng = random.Random(p2.SEED + salt)
        shuffled_base: dict[p2.Scope, float] = {}
        shuffled_treated: dict[float, dict[p2.Scope, float]] = {k: {} for k in TILT_GRID}
        for scope, (board, outcome, baseline) in sorted(loaded.items()):
            season, week = scope
            meta = metrics.weekly_meta(season, week, league)
            if not meta.sd_points:
                continue
            holders = list(meta.sd_points)
            spreads = [meta.sd_points[pid] for pid in holders]
            rng.shuffle(spreads)
            fake = dict(zip(holders, spreads, strict=True))
            shuffled_base[scope] = baseline.rwre
            for k in TILT_GRID:
                order = tilt_board(board, fake, k)
                shuffled_treated[k][scope] = (
                    baseline.rwre if k == 0.0
                    else s7.score_week(order, outcome, league, position=board.position).rwre
                )
        value, _e, _c = p2.loso(shuffled_base, shuffled_treated)
        floor.append(value)
    usable = [f for f in floor if f == f]
    print(f"   FLOOR, {p2.FLOOR_DRAWS} sd-shuffles: mean {statistics.mean(usable):+7.4f} "
          f"sd {statistics.stdev(usable):.4f} max {max(usable):+7.4f}")
    p_value = p2.reference_p(selected, floor)
    lo, hi = p2.clustered_interval(effects, by="season", seed=p2.SEED)
    print(f"   reference-set p: {p_value:.4f}")
    print(f"   season-clustered 95% interval (reported only): [{lo:+.4f}, {hi:+.4f}]")
    material = abs(selected) >= p2.MATERIAL
    if p_value <= 0.05 and selected > 0.0:
        verdict = "RESOLVES" if material else "resolves but immaterial"
    elif p_value <= 0.05 and selected < 0.0:
        verdict = "HARM"
    else:
        verdict = "null"
    print(f"   VERDICT: {verdict}  (material {material}, bar {p2.MATERIAL} RWRE)")
    print()
    return {
        "metric": "floor_ceiling_tilt", "league": league, "effect_board": selected,
        "p_board": p_value, "chosen": {str(k): v for k, v in chosen.items()},
        "interval_season": [lo, hi], "material": material, "verdict": verdict,
        "floor_board_mean": statistics.mean(usable), "seasonal": None,
    }


def main(argv: list[str]) -> int:
    league = argv[1] if len(argv) > 1 else "espn_green_hope"
    # ONE FILE PER LEAGUE. The three leagues are run as three concurrent processes --
    # they share no state and the machine has the cores -- and a single append target
    # would interleave their records.
    out_path = Path(__file__).resolve().parent / "runs" / f"s7-phase3-{league}.jsonl"
    print(f"S7 PHASE 3 -- new metrics, {league}")
    print(f"same adjudication as phase 2: grid {p2.GRID}, leave-one-season-out, "
          f"{p2.FLOOR_DRAWS} salts, material bar {p2.MATERIAL} RWRE, seed {p2.SEED}")
    print()
    loaded = p2.load_scopes(league)
    print(f"{len(loaded)} scopes loaded, {len({s for s, _ in loaded})} seasons")
    print()
    # Report the data defect the metrics uncovered, on the window actually used.
    epoch = missing = implausible = 0
    unknown: dict[str, int] = {}
    for (season, week) in sorted(loaded):
        meta = metrics.weekly_meta(season, week, league)
        epoch += meta.epoch_birthdates
        missing += meta.missing_birthdate
        implausible += meta.implausible_age
        for code, count in meta.unknown_status.items():
            unknown[code] = unknown.get(code, 0) + count
    print(f"birthdate sentinels over the scored window: epoch {epoch}, missing {missing}, "
          f"implausible after both guards {implausible}")
    print(f"unknown injury codes: {unknown or 'none'}")
    print()

    for name in metrics.METRICS:
        record = run_metric(name, loaded, league)
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    record = run_tilt(loaded, league)
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
