"""S7 phase 2 -- re-adjudicate every seasonal null on the weekly sample.

    uv run python -m sim.s7_phase2 espn_green_hope  >> sim/runs/s7-phase2.txt

THE PRE-REGISTRATION IS THE TOP OF THIS FILE AND IT IS COMMITTED BEFORE ANY NUMBER. `LOCUS`
states where each signal is expected to act, in code, before it is measured. `audible#87`
measured `ngs_time_to_throw` at +0.669 at QB against +0.038 board-wide -- a 17.5x attenuation
that hid a harm -- so averaging a positional effect over four positions is not a conservative
choice, it is a way of not measuring.

WHAT A SIGNAL IS HERE. A seasonal prior, built from information available before the season
starts, applied to every week of that season as `points * (1 + lam * z)` where z is the signal's
z-score inside its standardisation cell. `signals.adjust` is that transform and this module
imports it rather than reimplementing it -- `audible#87` shipped a gate and a transform that
decided the same question through two code paths and a term that never applied passed the gate.

ABSENCE IS NOT ZERO, in three places. A player with no signal value gets no adjustment. A player
with no realised row is dropped from the pool rather than scored zero. A season whose prior
inputs are not pinned is excluded from that signal's mean rather than filled in -- `prior_facts`
needs `player_stats_{season-1}` and 2018 is not pinned, so every prior-season signal covers
2020-2025 and not 2019. COVERAGE IS PRINTED PER SIGNAL for that reason.

THE FLOOR IS MATCHED TO THE SIGNAL'S OWN COVERAGE. A salt is a sha256 of player, season and salt
index -- information-free by construction -- handed to `signals.adjust` through its `values`
argument, and given ONLY to the players the signal itself covers. A floor drawn over the whole
board would be a harder bar for a signal covering 30% of it than for one covering 90%, and the
comparison would then be about coverage rather than about information. `FLOOR_DRAWS` is 40,
pre-registered in `audible#88`, and the achievable minimum p is (1+0)/(1+40) = 0.0244 one-sided.

ADJUDICATION IS ON THE REFERENCE-SET p AND ON NOTHING ELSE. The bootstrap interval is reported
because G6 asks for it, and `audible#88` measured that interval as a 0.5% test wearing a 5%
label. A single floor draw is never used: `audible#88` measured 5 of 18 dispositions flipping
under one, 28%, every one a false resolution.

WHAT IS NOT COMPUTED, AND WHY. G6 asks for a player-clustered interval alongside the
season-clustered one. There is none here. The statistic is a scope-level ranking error and
`rank.score_board` exposes no per-player decomposition of it; producing one would mean
reimplementing the metric beside the one under test, which is the exact defect this project has
shipped four times. The season-clustered interval is primary and a SCOPE-clustered interval is
reported in its place, with this paragraph as the reason.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import arms, rank, signals
from . import s7_weekly as s7

AGGREGATION = "weighted"
SCALE = "vorp"  # the scale the draft board ships on; see `s7_weekly.build_board`

# Pre-registered treatment strength. `signals.can_change_ordering` uses 0.10 as its default and
# the seasonal work fit lambda on a grid; fitting it weekly would buy a selected number, so one
# strength is fixed in advance and the opposite sign is reported beside it. A signal that only
# helps at a lambda chosen after the fact has not been resolved.
PRIMARY_LAMBDA = 0.10
LAMBDAS: tuple[float, ...] = (0.10, -0.10)

FLOOR_DRAWS = 40
BOOTSTRAPS = 2000
SEED = 20260911

POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")


@dataclass(frozen=True, slots=True)
class Signal:
    """One row of the handoff's list, with its locus fixed before it is measured."""

    name: str  # the `signals.signal_values` key
    label: str  # the handoff's own name for it
    locus: tuple[str, ...]  # PRE-REGISTERED. () means the signal is a board-level term.
    why: str  # the mechanism, stated before the number
    kwargs: dict[str, Any] = field(default_factory=dict)


# THE SIXTEEN, IN THE HANDOFF'S ORDER. `age / experience` is one line there and two terms here,
# so seventeen rows are measured. Nothing is dropped and nothing is added.
SIGNALS: tuple[Signal, ...] = (
    Signal("snap_share", "snap share", ("RB", "WR", "TE"),
           "playing time leads the box score, and a starter's snap share is stickier than his "
           "points. QB is excluded from the locus: a starting quarterback's snap share is ~1.0 "
           "and carries no within-position spread."),
    Signal("target_share", "target share", ("WR", "TE", "RB"),
           "volume, at the positions whose points come through the air."),
    Signal("ay_share", "air-yards share", ("WR", "TE"),
           "volume weighted by depth of target. Separates a boom receiver from a possession "
           "receiver on the same target count -- which target share cannot."),
    Signal("route_share", "route participation", ("WR", "TE", "RB"),
           "a pass-play participation proxy, not routes run; no pinned file has routes run. "
           "See `signals.route_share`, including the 2023 schema break it has to dodge."),
    Signal("ff_opp_exp", "ff_opportunity expected points", ("RB", "WR", "TE"),
           "expected fantasy points per TEAM game from volume and situation -- an opportunity "
           "measure that prices missed games as missed opportunity."),
    Signal("td_oe", "td over expected", ("RB", "WR", "TE"),
           "touchdown luck. Came twelfth of thirteen in S3's residual ranking with a sign that "
           "flips half the time, so the honest prior is that it does nothing."),
    Signal("availability", "availability", (),
           "a POSITION-LEVEL rate, so it is constant within a position and provably cannot "
           "reorder one. Its locus is the board and nowhere else; see G5."),
    Signal("draft_round", "rookie draft capital", ("RB", "WR", "TE", "QB"),
           "where the market with the most information placed a player before anyone had "
           "priced his fantasy role. Restricted to players with no prior-season row.",
           {"rookies_only": True}),
    Signal("depth_slot", "depth slot", ("RB", "WR", "TE"),
           "the team's own declared ordering, which is a role statement rather than a "
           "projection."),
    Signal("adp_gap", "ADP-vs-projection", (),
           "where the market and the projection disagree. A market term, so board-level."),
    Signal("contract", "contract value", (),
           "what the team paid, as a proxy for the role it intends to give him."),
    Signal("ngs_separation", "ngs_separation", ("WR", "TE"),
           "yards of separation at the catch point. Resolved at p=0.049 in `audible#88`, fell "
           "to 0.074 under the corrected metric and was reverted. Weekly is its first honest "
           "test."),
    Signal("ngs_time_to_throw", "ngs_time_to_throw", ("QB",),
           "the 17.5x attenuation case. +0.669 at QB against +0.038 board-wide."),
    Signal("ngs_rush_eff", "ngs_rush_eff", ("RB",),
           "how much lateral distance a back travels per yard gained."),
    Signal("uncertainty", "projection uncertainty (sd_pts)", ("QB", "RB", "WR", "TE"),
           "the projection's own dispersion, which the board currently discards entirely."),
    Signal("age_at_export", "age", ("QB", "RB", "WR", "TE"),
           "the aging curve. NOTE the field is stamped at EXPORT time, not at the season it "
           "describes -- see `signals.signal_values`. Level is wrong by up to seven years; the "
           "within-position ORDER is nearly unharmed, which is what a z-score reads."),
    Signal("ffa_experience", "experience", ("QB", "RB", "WR", "TE"),
           "seasons played. This IS vintage, where `age_at_export` is not."),
)


@dataclass(frozen=True, slots=True)
class Effect:
    """One (signal, league, lambda) measurement, board-wide and per position."""

    board: float
    per_position: dict[str, float]
    scopes: int


# THREE SIGNALS WERE COUPLED TO THE ESPN ARM AND TWO HAD TO BE UNCOUPLED.
# `signals.signal_values` builds `availability` and `adp_gap` over
# `arms.load("espn", season, "espn_green_hope")`, which is the right universe for S3 seasonal
# work and the wrong one here -- the board under test comes from FFA, and the espn arm REFUSES
# 2023 outright (`sim/runs/s1-sources.md`), so asking it for a 2023 value raised
# `PreflightError` and `availability` read 0% coverage in that season. That is not a null, it is
# a missing measurement wearing a null's clothes.
#
# Both are rebuilt here over the FFA universe, by the same construction:
#   * `availability` maps the position-level rate onto the WEEKLY BOARD position map;
#   * `adp_gap` ranks the FFA PRESEASON projection against ADP, exactly as S3 ranked the espn
#     preseason projection against ADP. Deliberately NOT the weekly projection: comparing week
#     N projection to a preseason ADP measures in-season drift, which is a different and
#     probably better signal, but it is not the one being re-adjudicated.
COUPLED: frozenset[str] = frozenset({"availability", "adp_gap"})


def values_for(signal: Signal, board: Any, season: int, league: str) -> dict[str, float]:
    """The signal values over the FFA universe. Raises nothing that is not a real absence."""
    if signal.name == "availability":
        rates = signals.position_availability(season)
        return {pid: rates[pos] for pid, pos in board.position.items() if pos in rates}
    if signal.name == "adp_gap":
        from . import residual

        meta = residual.ffa_meta(season)
        loaded = arms.load("ffa", season, league)
        out: dict[str, float] = {}
        for pos in rank.SCOREABLE:
            members = [
                pid for pid, held in loaded.position.items()
                if held == pos and pid in loaded.points
                and (meta.get(pid, {}).get("adp") or 0) > 0
            ]
            if len(members) < 20:
                continue
            proj = {
                pid: i for i, pid
                in enumerate(sorted(members, key=lambda q: -loaded.points[q]))
            }
            adp = {
                pid: i for i, pid
                in enumerate(sorted(members, key=lambda q: meta[q]["adp"]))
            }
            for pid in members:
                # POSITIVE means the market likes him more than the projection does.
                out[pid] = float(proj[pid] - adp[pid])
        return out
    return signals.signal_values(signal.name, season)


def _salt_values(pids: list[str], season: int, salt: int) -> dict[str, float]:
    """Information-free values on exactly *pids*. Not an RNG draw, so a run is reproducible."""
    return {
        pid: (int(hashlib.sha256(f"{pid}:{season}:{salt}".encode()).hexdigest()[:8], 16)
              / 0xFFFFFFFF) * 2.0 - 1.0
        for pid in pids
    }


def load_scopes(league: str) -> dict[tuple[int, int], tuple[Any, dict[str, float], Any]]:
    """Every scoreable scope's board, outcome and BASELINE score, read once."""
    scopes = s7.available_scopes(AGGREGATION, require_actuals=True)
    s7.preflight(scopes, league)
    out: dict[tuple[int, int], tuple[Any, dict[str, float], Any]] = {}
    for season, week in scopes:
        board = s7.build_board(season, week, league, aggregation=AGGREGATION, scale=SCALE)
        outcome = s7.realised_week(season, week, league).on(SCALE, position=board.position)
        if len([pid for pid in board.board if pid in outcome]) < 24:
            continue
        base = s7.score_week(board.board, outcome, league, position=board.position)
        out[(season, week)] = (board, outcome, base)
    return out


def _treated(board: Any, outcome: dict[str, float], league: str, season: int,
             lam: float, name: str, *, values: dict[str, float] | None = None,
             **kwargs: Any) -> Any:
    points = signals.adjust(
        board.projected, board.position, season, lam, name, values=values, **kwargs
    )
    value = rank.vorp_values(points, board.position, league)
    order = sorted(value, key=lambda pid: (-value[pid], pid))
    return s7.score_week(order, outcome, league, position=board.position)


def coverage(signal: Signal, loaded: dict[tuple[int, int], Any],
             league: str) -> dict[int, tuple[int, int]]:
    """season -> (players with a value, players on the board). Never filled in, only reported."""
    out: dict[int, tuple[int, int]] = {}
    for (season, _week), (board, _outcome, _base) in sorted(loaded.items()):
        if season in out:
            continue
        try:
            values = values_for(signal, board, season, league)
        except rank.PreflightError:
            values = {}
        have = [pid for pid in board.projected if pid in values]
        if signal.kwargs.get("rookies_only"):
            # A draft-capital term adjusts ONLY players with no prior-season row, so the count
            # that matters is rookies with a value, not everyone with a draft round on file.
            from . import residual

            try:
                prior = residual.prior_facts(season)
            except rank.PreflightError:
                prior = {}
            have = [pid for pid in have if pid not in prior]
        out[season] = (len(have), len(board.projected))
    return out


def constant_within_position(signal: Signal, loaded: dict[tuple[int, int], Any],
                             league: str) -> set[str]:
    """Positions where this signal holds ONE distinct value, so it cannot reorder them.

    WITHOUT THIS THE PER-POSITION p IS MEANINGLESS FOR A BOARD-LEVEL TERM. `availability` is a
    position-level rate: its per-position effect is exactly +0.0000 by construction, which is
    `audible#87`'s finding reproduced. The FLOOR at those positions is not zero, because a salt
    varies within a position even when z-scored at board scope -- so comparing the two produces
    a p for a quantity the treatment could never move. Those positions are reported as
    structurally zero and no p is printed for them.
    """
    out: set[str] = set()
    for (season, _week), (board, _outcome, _base) in sorted(loaded.items()):
        try:
            values = values_for(signal, board, season, league)
        except rank.PreflightError:
            continue
        if not values:
            continue
        for pos in POSITIONS:
            members = [
                pid for pid, held in board.position.items()
                if held == pos and pid in values
            ]
            if members and len({values[pid] for pid in members}) <= 1:
                out.add(pos)
        return out
    return out


def can_change_ordering(signal: Signal, loaded: dict[tuple[int, int], Any],
                        league: str) -> tuple[bool, int, int]:
    """G4, on the WEEKLY board. Returns (moved anywhere, scopes moved, max players moved).

    `shrink` was called provably inert by three handoffs and was not, so this is measured on
    every term before any effect is reported, and a term that cannot move an ordering is not
    measured at all.
    """
    scopes_moved = worst = 0
    for (season, _week), (board, _outcome, _base) in sorted(loaded.items()):
        try:
            values = values_for(signal, board, season, league)
        except rank.PreflightError:
            continue
        if not values:
            continue
        points = signals.adjust(
            board.projected, board.position, season, PRIMARY_LAMBDA, signal.name,
            values=values, **signal.kwargs,
        )
        value = rank.vorp_values(points, board.position, league)
        order = sorted(value, key=lambda pid: (-value[pid], pid))
        moved = sum(1 for a, b in zip(board.board, order, strict=False) if a != b)
        if moved:
            scopes_moved += 1
            worst = max(worst, moved)
    return scopes_moved > 0, scopes_moved, worst


def cell_report(signal: Signal, loaded: dict[tuple[int, int], Any],
                league: str) -> list[str]:
    """G5. Cells applied vs skipped, with the deciding sd, for one scope per season.

    `availability` is why this exists: z-scoring a position-level constant WITHIN position gives
    sd == 0 and skips the cell, so 19 of 20 cells were a literal no-op and the twentieth applied
    8.95e-16 of floating-point residue. The term was never measured and the published number was
    IEEE-754 dust.
    """
    lines: list[str] = []
    seen: set[int] = set()
    for (season, _week), (board, _outcome, _base) in sorted(loaded.items()):
        if season in seen:
            continue
        seen.add(season)
        try:
            cells = signals.cells(
                board.projected, board.position, season, signal.name,
                values=values_for(signal, board, season, league), **signal.kwargs
            )
        except rank.PreflightError:
            lines.append(f"    {season}  inputs not pinned")
            continue
        applied = [c for c in cells if c.applied]
        skipped = [c for c in cells if not c.applied]
        detail = " ".join(f"{c.label}:n{c.n}/d{c.distinct}/sd{c.sd:.3g}" for c in cells)
        lines.append(
            f"    {season}  applied {len(applied)} skipped {len(skipped)}   {detail}"
        )
    return lines


def effect(signal: Signal, loaded: dict[tuple[int, int], Any], league: str, lam: float,
           *, salt: int | None = None) -> tuple[Effect, dict[tuple[int, int], float]]:
    """Mean improvement in RWRE, board-wide and per position. Positive means BETTER.

    With *salt*, the signal's values are replaced by an information-free hash over exactly the
    players the signal itself covers -- the floor, matched to this signal's coverage.
    """
    board_deltas: dict[tuple[int, int], float] = {}
    pos_deltas: dict[str, list[float]] = {p: [] for p in POSITIONS}
    for (season, week), (board, outcome, base) in sorted(loaded.items()):
        try:
            values = values_for(signal, board, season, league)
        except rank.PreflightError:
            continue
        if not values:
            continue
        covered = [pid for pid in board.projected if pid in values]
        if not covered:
            continue
        inject = _salt_values(covered, season, salt) if salt is not None else values
        treated = _treated(
            board, outcome, league, season, lam, signal.name, values=inject, **signal.kwargs
        )
        board_deltas[(season, week)] = base.rwre - treated.rwre
        for pos in POSITIONS:
            if pos in base.per_position and pos in treated.per_position:
                pos_deltas[pos].append(base.per_position[pos] - treated.per_position[pos])
    board_mean = statistics.mean(board_deltas.values()) if board_deltas else float("nan")
    per_pos = {
        p: statistics.mean(v) for p, v in pos_deltas.items() if v
    }
    return Effect(board_mean, per_pos, len(board_deltas)), board_deltas


def reference_p(observed: float, floor: list[float]) -> float:
    """(1 + #{floor >= observed}) / (1 + K). One-sided, because the direction is pre-registered."""
    if not floor:
        return float("nan")
    return (1 + sum(1 for f in floor if f >= observed)) / (1 + len(floor))


def clustered_interval(deltas: dict[tuple[int, int], float], *, by: str,
                       seed: int) -> tuple[float, float]:
    """Bootstrap the mean effect, resampling whole clusters. REPORTED, never adjudicated on."""
    if not deltas:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    if by == "season":
        groups: dict[int, list[float]] = {}
        for (season, _week), value in deltas.items():
            groups.setdefault(season, []).append(value)
        units = list(groups.values())
    elif by == "scope":
        units = [[value] for value in deltas.values()]
    else:
        raise ValueError(f"unknown clustering {by!r}")
    means = []
    for _ in range(BOOTSTRAPS):
        drawn: list[float] = []
        for _ in range(len(units)):
            drawn.extend(units[rng.randrange(len(units))])
        means.append(statistics.mean(drawn))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[min(len(means) - 1, int(0.975 * len(means)))]
    return (lo, hi)


def _seasonal_score(signal: Signal, league: str, season: int, loaded: Any,
                    outcome: dict[str, float], strength: float,
                    values: dict[str, float]) -> float:
    points = signals.adjust(
        loaded.points, loaded.position, season, strength, signal.name,
        values=values, **signal.kwargs
    )
    order = [
        pid for pid in rank.vorp_order(points, loaded.position, league) if pid in outcome
    ]
    return rank.score_board(
        order, outcome, teams=int(rank.league(league).num_teams),
        pool_size=rank.pool_size_for(league), position=loaded.position,
        indexing="symmetric", position_pool=rank.position_pool_sizes(league),
    ).rwre


def seasonal_effect(signal: Signal, league: str, lam: float) -> tuple[float, int]:
    """G7's other half: the same term on the SEASONAL draft board, FFA arm, same league.

    `signals.score` is hardwired to the espn arm and one league, so this reproduces its shape
    against `arms.load("ffa", ...)` per league rather than editing a function forty gates read.
    """
    total = []
    for season in rank.SEASONS_BY_ARM["ffa"]:
        try:
            loaded = arms.load("ffa", season, league)
            realised = rank.realised_per_game(season, league)
            values = values_for(signal, loaded, season, league)
        except rank.PreflightError:
            continue
        if not values:
            continue
        outcome = rank.realised_vorp(realised)
        total.append(
            _seasonal_score(signal, league, season, loaded, outcome, 0.0, values)
            - _seasonal_score(signal, league, season, loaded, outcome, lam, values)
        )
    return (statistics.mean(total) if total else float("nan"), len(total))


def run_signal(signal: Signal, loaded: dict[tuple[int, int], Any], league: str) -> dict[str, Any]:
    print(f"-- {signal.label}  [{signal.name}] --")
    print(f"   LOCUS (pre-registered): "
          f"{'board-level only' if not signal.locus else ' '.join(signal.locus)}")
    print(f"   mechanism: {signal.why}")

    cov = coverage(signal, loaded, league)
    covered_seasons = [s for s, (have, _total) in cov.items() if have > 0]
    print("   coverage, players with a value / players on the board:")
    for season in sorted(cov):
        have, total = cov[season]
        share = have / total if total else 0.0
        print(f"    {season}  {have:4d} / {total:4d}  {share:5.1%}")
    if not covered_seasons:
        print("   NOT MEASURABLE: no season in the weekly window has a value for this signal.")
        print()
        return {"signal": signal.name, "league": league, "verdict": "not measurable"}

    moved, scopes_moved, worst = can_change_ordering(signal, loaded, league)
    print(f"   G4 can change an ordering: {moved}  "
          f"({scopes_moved}/{len(loaded)} scopes moved, worst {worst} players)")
    print("   G5 standardisation cells:")
    for line in cell_report(signal, loaded, league):
        print(line)
    if not moved:
        print("   INERT on the weekly board at lambda "
              f"{PRIMARY_LAMBDA}: not measured, per G4.")
        print()
        return {"signal": signal.name, "league": league, "verdict": "inert"}

    record: dict[str, Any] = {"signal": signal.name, "league": league,
                             "locus": list(signal.locus)}
    frozen = constant_within_position(signal, loaded, league)
    if frozen:
        print(f"   structurally unable to reorder: {' '.join(sorted(frozen))} "
              "(one distinct value inside the position)")
    primary, primary_deltas = effect(signal, loaded, league, PRIMARY_LAMBDA)
    print(f"   effect at lambda +{PRIMARY_LAMBDA} over {primary.scopes} scopes "
          "(positive = better):")
    print(f"    board-wide  {primary.board:+7.4f}")
    for pos in POSITIONS:
        if pos in primary.per_position:
            mark = "  <- locus" if pos in signal.locus else ""
            if pos in frozen:
                mark += "  STRUCTURALLY ZERO"
            print(f"    {pos}          {primary.per_position[pos]:+7.4f}{mark}")
    other, _ = effect(signal, loaded, league, -PRIMARY_LAMBDA)
    print(f"   effect at lambda -{PRIMARY_LAMBDA} board-wide {other.board:+7.4f}  "
          "(reported so a harm is visible, never adjudicated on)")

    floor_board: list[float] = []
    floor_pos: dict[str, list[float]] = {p: [] for p in POSITIONS}
    for salt in range(FLOOR_DRAWS):
        drawn, _ = effect(signal, loaded, league, PRIMARY_LAMBDA, salt=salt)
        floor_board.append(drawn.board)
        for pos, value in drawn.per_position.items():
            floor_pos[pos].append(value)
    print(f"   FLOOR, {FLOOR_DRAWS} salts matched to this signal's coverage:")
    print(f"    board-wide  mean {statistics.mean(floor_board):+7.4f} "
          f"sd {statistics.stdev(floor_board):.4f} "
          f"max {max(floor_board):+7.4f}")
    p_board = reference_p(primary.board, floor_board)
    print(f"    reference-set p, board-wide: {p_board:.4f}")
    record["p_board"] = p_board
    record["effect_board"] = primary.board
    record["effect_board_negative_lambda"] = other.board
    record["per_position"] = primary.per_position
    record["p_position"] = {}
    for pos in POSITIONS:
        if pos in frozen:
            print(f"    reference-set p, {pos}: not reported -- the treatment is structurally "
                  "0.0000 here and the floor is not")
            continue
        if pos in primary.per_position and floor_pos[pos]:
            p_pos = reference_p(primary.per_position[pos], floor_pos[pos])
            record["p_position"][pos] = p_pos
            mark = "  <- locus" if pos in signal.locus else ""
            print(f"    reference-set p, {pos}: {p_pos:.4f}  "
                  f"(floor mean {statistics.mean(floor_pos[pos]):+.4f} "
                  f"max {max(floor_pos[pos]):+.4f}){mark}")

    lo, hi = clustered_interval(primary_deltas, by="season", seed=SEED)
    slo, shi = clustered_interval(primary_deltas, by="scope", seed=SEED)
    print(f"   season-clustered 95% interval (PRIMARY, reported only): [{lo:+.4f}, {hi:+.4f}]")
    print(f"   scope-clustered  95% interval (reported only):          [{slo:+.4f}, {shi:+.4f}]")
    print("   player-clustered: NOT COMPUTED. See the module docstring.")
    record["interval_season"] = [lo, hi]
    record["interval_scope"] = [slo, shi]

    seasonal, n_seasons = seasonal_effect(signal, league, PRIMARY_LAMBDA)
    print(f"   SEASONAL draft board, same term, {n_seasons} observations: {seasonal:+7.4f}")
    record["seasonal"] = seasonal
    record["seasonal_n"] = n_seasons

    # RESOLUTION REQUIRES BOTH A p AND THE RIGHT SIGN, at one place. A p of 0.02 on an effect
    # of -0.4 says the signal reliably makes the board WORSE, which is a harm and not a
    # resolution, and `audible#87`'s 17.5x attenuation is why the locus counts separately from
    # the board: a real positional effect diluted over four positions reads as nothing.
    board_resolves = p_board <= 0.05 and primary.board > 0.0
    locus_hits = [
        pos for pos in signal.locus
        if record["p_position"].get(pos, 1.0) <= 0.05
        and primary.per_position.get(pos, 0.0) > 0.0
    ]
    harms = [
        pos for pos in POSITIONS
        if record["p_position"].get(pos, 1.0) <= 0.05
        and primary.per_position.get(pos, 0.0) < 0.0
    ]
    if p_board <= 0.05 and primary.board < 0.0:
        harms.append("board")
    if board_resolves or locus_hits:
        record["verdict"] = "RESOLVES"
    elif harms:
        record["verdict"] = "HARM"
    else:
        record["verdict"] = "null"
    record["locus_hits"] = locus_hits
    record["harms"] = harms
    locus_ps = [record["p_position"][pos] for pos in signal.locus
                if pos in record["p_position"]]
    best = min([p_board, *locus_ps])
    print(f"   VERDICT: {record['verdict']}  (best p {best:.4f}"
          f"{', locus ' + ' '.join(locus_hits) if locus_hits else ''}"
          f"{', harm at ' + ' '.join(harms) if harms else ''})")
    print()
    return record


def main(argv: list[str]) -> int:
    league = argv[1] if len(argv) > 1 else "espn_green_hope"
    out_path = Path(__file__).resolve().parent / "runs" / "s7-phase2.jsonl"
    print(f"S7 PHASE 2 -- weekly re-adjudication, {league}")
    print(f"aggregation {AGGREGATION}, scale {SCALE}, lambda +/-{PRIMARY_LAMBDA}, "
          f"{FLOOR_DRAWS} salts, {BOOTSTRAPS} bootstraps, seed {SEED}")
    print()
    loaded = load_scopes(league)
    print(f"{len(loaded)} scopes loaded, "
          f"{len({s for s, _ in loaded})} seasons")
    print()
    for signal in SIGNALS:
        record = run_signal(signal, loaded, league)
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
