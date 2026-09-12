"""S7 phase 2 -- re-adjudicate every seasonal null on the weekly sample.

    uv run python -m sim.s7_phase2 espn_green_hope  >> sim/runs/s7-phase2.txt

THE PRE-REGISTRATION IS THE TOP OF THIS FILE AND IS COMMITTED BEFORE ANY NUMBER. `LOCUS` states
where each signal is expected to act, in code, before it is measured. `audible#87` measured
`ngs_time_to_throw` at +0.669 at QB against +0.038 board-wide -- a 17.5x attenuation that hid a
harm -- so averaging a positional effect over four positions is not a conservative choice, it is
a way of not measuring.

WHAT A SIGNAL IS HERE. A seasonal prior, built from information available before the season
starts, applied to every week of that season as `points * (1 + lam * z)` where z is the signal's
z-score inside its standardisation cell. `signals.adjust` is that transform and this module
imports it rather than reimplementing it -- `audible#87` shipped a gate and a transform that
decided the same question through two code paths, and a term that never applied passed the gate.

STRENGTH IS CHOSEN OUT OF SAMPLE, AND THE FIRST VERSION OF THIS FILE GOT THAT WRONG. It fixed
lambda at 0.10 and adjudicated on "beats the floor". Under a fixed strength EVERY term measured
negative -- a random term at lambda 0.10 costs about -0.55 RWRE, because multiplying a good
ranking by (1 + 0.1z) with noise for z can only add noise -- so "beats the floor" would have
RESOLVED signals that leave the board WORSE than not touching it at all. `snap_share` read
-0.3051 board-wide with p 0.024 and was one commit from being published as a resolution.

So lambda is selected by LEAVE-ONE-SEASON-OUT over `GRID`, which contains 0.0. A term whose best
strength is nothing selects nothing and scores exactly 0.000, and the floor is put through the
identical selection, so the p is a test against SELECTION NOISE rather than against zero. That is
also what makes the weekly number comparable with the seasonal one, which `signals.loso` computes
the same way. The effect at a fixed lambda 0.10 is reported too, because it is the number nobody
chose after the fact.

ABSENCE IS NOT ZERO, in three places. A player with no signal value gets no adjustment. A player
with no realised row is dropped from the pool rather than scored zero. A season whose prior
inputs are not pinned is excluded from that signal's mean rather than filled in -- `prior_facts`
needs `player_stats_{season-1}` and 2018 is not pinned, so every prior-season signal covers
2020-2025 and not 2019. COVERAGE IS PRINTED PER SIGNAL AND PER SEASON for that reason.

THE FLOOR IS MATCHED TO THE SIGNAL'S OWN COVERAGE. A salt is a sha256 of player, season and salt
index -- information-free by construction -- handed to `signals.adjust` through its `values`
argument, and given ONLY to the players the signal itself covers. A floor drawn over the whole
board would be a harder bar for a signal covering 30% of it than for one covering 90%, and the
comparison would then be about coverage rather than about information. `FLOOR_DRAWS` is 40,
pre-registered in `audible#88`; the achievable minimum p is (1+0)/(1+40) = 0.0244 one-sided.

ADJUDICATION IS ON THE REFERENCE-SET p AND ON THE SIGN, AND ON NOTHING ELSE. The bootstrap
interval is reported because G6 asks for it, and `audible#88` measured that interval as a 0.5%
test wearing a 5% label. A single floor draw is never used: `audible#88` measured 5 of 18
dispositions flipping under one, 28%, every one a false resolution.

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

# 0.0 IS IN THE GRID ON PURPOSE. It is what a term that should not be used selects, and without
# it every reported effect is forced to be an intervention.
GRID: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10, 0.20)

# The strength reported beside the selected one, so a number nobody chose is always on the page.
FIXED_LAMBDA = 0.10

# STATISTICAL AND PRACTICAL SIGNIFICANCE ARE REPORTED SEPARATELY, and this is the practical bar.
#
# Out-of-sample selection makes the floor draws cluster on exactly 0.000, because a random term
# usually picks lambda 0.0. So ANY positive selected effect, however tiny, beats every floor draw
# and reads p = 0.0244. That is a correct reference-set test and a useless headline: +0.004 RWRE
# against a board whose error is 34.9 and whose scope-to-scope sd is 4.3 is not a finding anybody
# should act on. A term therefore has to clear both bars to count, and the two are never merged
# into one word.
#
# 0.10 RWRE is pre-registered here: about 0.3% of the FFA weekly board error, and about 1/300th
# of the distance between that board and a coin. Nothing was measured before this constant was
# written down.
MATERIAL = 0.10

FLOOR_DRAWS = 40
BOOTSTRAPS = 2000
SEED = 20260911

POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

Scope = tuple[int, int]


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
           "receiver on the same target count, which target share cannot."),
    Signal("route_share", "route participation", ("WR", "TE", "RB"),
           "a pass-play participation proxy, not routes run; no pinned file holds routes run. "
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
           "where the market with the most information placed a player before anyone had priced "
           "his fantasy role. Restricted to players with no prior-season row.",
           {"rookies_only": True}),
    Signal("depth_slot", "depth slot", ("RB", "WR", "TE"),
           "the team's own declared ordering, which is a role statement rather than a "
           "projection."),
    Signal("adp_gap", "ADP-vs-projection", (),
           "where the market and the projection disagree. A market term, so board-level."),
    Signal("contract", "contract value", (),
           "what the team paid, as a proxy for the role it intends to give him."),
    Signal("ngs_separation", "ngs_separation", ("WR", "TE"),
           "yards of separation at the catch point. Resolved at p=0.049 in `audible#88`, fell to "
           "0.074 under the corrected metric and was reverted. Weekly is its first honest test."),
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


# TWO SIGNALS WERE COUPLED TO THE ESPN ARM AND HAD TO BE UNCOUPLED. `signals.signal_values`
# builds `availability` and `adp_gap` over `arms.load("espn", season, "espn_green_hope")`, which
# is the right universe for S3 seasonal work and the wrong one here -- the board under test comes
# from FFA, and the espn arm REFUSES 2023 outright (`sim/runs/s1-sources.md`), so asking it for a
# 2023 value raised `PreflightError` and `availability` read 0% coverage that season. That is not
# a null, it is a missing measurement wearing a null's clothes.
#
# Both are rebuilt here over the FFA universe, by the same construction:
#   * `availability` maps the position-level rate onto the WEEKLY BOARD position map;
#   * `adp_gap` ranks the FFA PRESEASON projection against ADP, exactly as S3 ranked the espn
#     preseason projection against ADP. Deliberately NOT the weekly projection: comparing week N
#     projection to a preseason ADP measures in-season drift, which is a different and probably
#     better signal, but it is not the one being re-adjudicated.
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
                pid: i for i, pid in enumerate(sorted(members, key=lambda q: meta[q]["adp"]))
            }
            for pid in members:
                # POSITIVE means the market likes him more than the projection does.
                out[pid] = float(proj[pid] - adp[pid])
        return out
    return signals.signal_values(signal.name, season)


def _salt_values(pids: list[str], season: int, salt: int) -> dict[str, float]:
    """A uniform hash on exactly *pids*. SUPERSEDED as the floor; kept for the gates.

    This was the floor through the first phase-2 and phase-3 runs and the adversarial review
    refuted it. See `floor_values` for what replaced it and why.
    """
    return {
        pid: (int(hashlib.sha256(f"{pid}:{season}:{salt}".encode()).hexdigest()[:8], 16)
              / 0xFFFFFFFF) * 2.0 - 1.0
        for pid in pids
    }


def floor_values(values: dict[str, float], covered: list[str], position: dict[str, str],
                 frozen: set[str], key: int, salt: int) -> dict[str, float]:
    """THE FLOOR: this term's OWN values, dealt to the wrong players.

    THE HASH FLOOR THIS REPLACED WAS THE WRONG NULL AND THE REVIEW MEASURED IT TWICE.

    A reference-set p is only meaningful if the salt and the signal are exchangeable under the
    null. A `Uniform(-1, 1)` hash is not exchangeable with a term whose values are 95% exactly
    zero: `inj_status` demotes a handful of players hard while the hash jiggles everyone gently,
    so the two interventions are not the same KIND of intervention and comparing them tests the
    shape of the value distribution rather than its information content. Measured: `inj_status`
    at WR read p 0.0244 against the hash and 0.0976 / 0.3415 against a permutation of its own
    values -- because merely shuffling WHICH player is listed Out already buys +0.119 and +0.081
    RWRE, 62% and 72% of the observed effect.

    The same defect made the null hit rate wrong in the other direction. Out-of-sample selection
    parks most hash-floor draws on exactly 0.000, and `p = (1 + #{f >= obs})/41` cannot reach
    0.05 when three or more of the 41 values tie at the maximum. For five of six sampled terms
    the null probability of a hit was not 2/41 -- it was ZERO. A benchmark of "16.4 expected"
    built from a flat 2/41 was therefore wrong for the 131 of 336 tests whose effect is exactly
    0.000. `s7_multiplicity` now computes the achievable rate per test instead of assuming one.

    Permuting the term's own values fixes both: the marginal distribution is preserved exactly,
    the value-to-player pairing -- the only thing under test -- is destroyed, and the salt is
    exchangeable with the signal by construction. `s7_phase3.run_tilt` already used this null
    for its own sd shuffle, so the session was inconsistent with itself.

    A TERM THAT IS CONSTANT WITHIN EVERY POSITION IS PERMUTED ACROSS POSITIONS INSTEAD. For
    `availability` -- four position-level rates -- dealing the values to individual players
    would manufacture within-position spread the term provably cannot have, and the floor would
    then be a different kind of object from the treatment. Permuting the four rates among the
    four positions is the exact reference set for what that term actually does.
    """
    rng = random.Random(hash((key, salt)) & 0xFFFFFFFF)
    if frozen and frozen >= {pos for pos in POSITIONS if any(
        position.get(pid) == pos for pid in covered
    )}:
        per_position: dict[str, float] = {}
        for pid in covered:
            pos = position.get(pid)
            if pos is not None and pos not in per_position:
                per_position[pos] = values[pid]
        labels = list(per_position)
        held = [per_position[pos] for pos in labels]
        rng.shuffle(held)
        mapped = dict(zip(labels, held, strict=True))
        return {pid: mapped[position[pid]] for pid in covered if position.get(pid) in mapped}
    held = [values[pid] for pid in covered]
    rng.shuffle(held)
    return dict(zip(covered, held, strict=True))


def load_scopes(league: str) -> dict[Scope, tuple[Any, dict[str, float], Any]]:
    """Every scoreable scope's board, outcome and BASELINE score, read once."""
    scopes = s7.available_scopes(AGGREGATION, require_actuals=True)
    s7.preflight(scopes, league)
    out: dict[Scope, tuple[Any, dict[str, float], Any]] = {}
    for season, week in scopes:
        board = s7.build_board(season, week, league, aggregation=AGGREGATION, scale=SCALE)
        outcome = s7.realised_week(season, week, league).on(SCALE, position=board.position)
        if len([pid for pid in board.board if pid in outcome]) < 24:
            continue
        base = s7.score_week(board.board, outcome, league, position=board.position)
        out[(season, week)] = (board, outcome, base)
    return out


def _treated(board: Any, outcome: dict[str, float], league: str, season: int, lam: float,
             name: str, values: dict[str, float], **kwargs: Any) -> Any:
    points = signals.adjust(
        board.projected, board.position, season, lam, name, values=values, **kwargs
    )
    value = rank.vorp_values(points, board.position, league)
    order = sorted(value, key=lambda pid: (-value[pid], pid))
    return s7.score_week(order, outcome, league, position=board.position)


@dataclass(slots=True)
class Series:
    """Every scope's RWRE at every strength: the raw material for out-of-sample selection."""

    base: dict[Scope, float] = field(default_factory=dict)
    base_pos: dict[str, dict[Scope, float]] = field(default_factory=dict)
    treated: dict[float, dict[Scope, float]] = field(default_factory=dict)
    treated_pos: dict[float, dict[str, dict[Scope, float]]] = field(default_factory=dict)


def build_series(signal: Signal, loaded: dict[Scope, Any], league: str,
                 *, salt: int | None = None, frozen: set[str] | None = None) -> Series:
    """Score every scope at every strength in `GRID`, once.

    With *salt*, the signal's values are replaced by an information-free hash over exactly the
    players the signal itself covers -- the floor, matched to this signal's coverage, and put
    through the same selection the signal gets.
    """
    series = Series()
    for lam in GRID:
        series.treated[lam] = {}
        series.treated_pos[lam] = {pos: {} for pos in POSITIONS}
    for scope, (board, outcome, base) in sorted(loaded.items()):
        season = scope[0]
        try:
            values = values_for(signal, board, season, league)
        except rank.PreflightError:
            continue
        if not values:
            continue
        covered = [pid for pid in board.projected if pid in values]
        if not covered:
            continue
        inject = (
            floor_values(values, covered, board.position, frozen or set(), season, salt)
            if salt is not None else values
        )
        series.base[scope] = base.rwre
        for pos, value in base.per_position.items():
            series.base_pos.setdefault(pos, {})[scope] = value
        for lam in GRID:
            if lam == 0.0:
                # Provably the untreated board: `signals.adjust` returns a copy at lam 0.0.
                # Scoring it again would be 118 wasted cycles per signal per salt.
                series.treated[lam][scope] = base.rwre
                for pos, value in base.per_position.items():
                    series.treated_pos[lam][pos][scope] = value
                continue
            score = _treated(
                board, outcome, league, season, lam, signal.name, inject, **signal.kwargs
            )
            series.treated[lam][scope] = score.rwre
            for pos, value in score.per_position.items():
                series.treated_pos[lam][pos][scope] = value
    return series


def loso(base: dict[Scope, float],
         treated: dict[float, dict[Scope, float]]) -> tuple[float, dict[Scope, float],
                                                            dict[int, float]]:
    """Leave-one-season-out strength selection. Returns (mean effect, per-scope, chosen lambdas).

    For each season: choose the strength that minimises RWRE on the OTHER seasons, then score
    this one with it. The held-out season never sees its own strength chosen, and 0.0 is in the
    grid, so a term that should not be used contributes exactly 0.000 rather than a harm.
    """
    if not base:
        return (float("nan"), {}, {})
    seasons = sorted({season for season, _week in base})
    effects: dict[Scope, float] = {}
    chosen: dict[int, float] = {}
    for held in seasons:
        others = [scope for scope in base if scope[0] != held]
        best_lam = 0.0
        if others:
            best = float("inf")
            for lam in GRID:
                scores = treated.get(lam, {})
                usable = [scores[scope] for scope in others if scope in scores]
                if not usable:
                    continue
                mean = statistics.mean(usable)
                if mean < best:
                    best, best_lam = mean, lam
        chosen[held] = best_lam
        picked = treated.get(best_lam, {})
        for scope in base:
            if scope[0] == held and scope in picked:
                effects[scope] = base[scope] - picked[scope]
    return (statistics.mean(effects.values()) if effects else float("nan"), effects, chosen)


def fixed(base: dict[Scope, float], treated: dict[float, dict[Scope, float]],
          lam: float) -> float:
    """The effect at one strength nobody chose, reported beside the selected one."""
    scores = treated.get(lam, {})
    deltas = [base[scope] - scores[scope] for scope in base if scope in scores]
    return statistics.mean(deltas) if deltas else float("nan")


def reference_p(observed: float, floor: list[float]) -> float:
    """(1 + #{floor >= observed}) / (1 + K). One-sided FOR IMPROVEMENT.

    SMALL MEANS THE TERM BEAT THE FLOOR. A p near 1.0 means it lost to almost every draw, which
    is the signature of a harm -- see `harm_p`, and note that the first version of this module
    looked for harms at p <= 0.05, which is exactly backwards and fired zero times in 72
    measurements.
    """
    usable = [f for f in floor if f == f]
    if not usable:
        return float("nan")
    return (1 + sum(1 for f in usable if f >= observed)) / (1 + len(usable))


def harm_p(observed: float, floor: list[float]) -> float:
    """The mirror: (1 + #{floor <= observed}) / (1 + K). Small means the term LOST to the floor."""
    usable = [f for f in floor if f == f]
    if not usable:
        return float("nan")
    return (1 + sum(1 for f in usable if f <= observed)) / (1 + len(usable))


def null_hit_rate(observed: float, floor: list[float], bar: float = 0.05) -> float:
    """P(this test returns p <= bar) under the null, computed from its OWN tie structure.

    THE FLAT 2/41 BENCHMARK WAS WRONG AND THE ADVERSARIAL REVIEW PROVED IT. Under exchangeability
    the observed value is one of the 1+K values and equally likely to be any of them, so the null
    hit rate is the FRACTION OF THOSE POSITIONS that would have produced a p at or under the bar.
    With no ties that is exactly 2/41. With three or more values tied at the maximum it is ZERO --
    every one of them sees at least two others at least as large, so the smallest reachable p is
    3/41 = 0.073. Out-of-sample selection parks most floor draws on exactly 0.000, so this is the
    normal case rather than an edge case: 131 of 336 tests in the hash-floor run sat there.

    Computed by direct enumeration rather than by a closed form, because the tie structure can be
    anything and a closed form is one more thing to get wrong.
    """
    usable = [f for f in floor if f == f]
    if not usable or observed != observed:
        return float("nan")
    combined = [*usable, observed]
    n = len(combined)
    hits = 0
    for index, value in enumerate(combined):
        others = sum(1 for j, other in enumerate(combined) if j != index and other >= value)
        if (1 + others) / n <= bar:
            hits += 1
    return hits / n


def achievable_p(observed: float, floor: list[float]) -> float:
    """The SMALLEST p this test could have returned, given the ties actually present.

    Under exchangeability the observed value is one of the 1+K, so if the maximum of that set is
    attained by m values then the best reachable p is m/(1+K). With m >= 3 a threshold of 0.05 is
    unreachable and the test cannot produce a hit however real the effect is. This is what makes
    a flat "P(hit) = 2/41" benchmark wrong, and it is reported per test rather than assumed.
    """
    usable = [f for f in floor if f == f]
    if not usable:
        return float("nan")
    combined = [*usable, observed]
    top = max(combined)
    return sum(1 for value in combined if value >= top) / len(combined)


def clustered_interval(deltas: dict[Scope, float], *, by: str, seed: int) -> tuple[float, float]:
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
    return (means[int(0.025 * len(means))], means[min(len(means) - 1, int(0.975 * len(means)))])


def coverage(signal: Signal, loaded: dict[Scope, Any], league: str) -> dict[int, tuple[int, int]]:
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


def constant_within_position(signal: Signal, loaded: dict[Scope, Any], league: str) -> set[str]:
    """Positions where this signal holds ONE distinct value, so it cannot reorder them.

    WITHOUT THIS THE PER-POSITION p IS MEANINGLESS FOR A BOARD-LEVEL TERM. `availability` is a
    position-level rate: its per-position effect is exactly 0.0000 by construction, which is
    `audible#87`'s finding reproduced. The FLOOR at those positions is not zero, because a salt
    varies within a position even when z-scored at board scope -- so comparing the two produces
    a p for a quantity the treatment could never move.
    """
    for (season, _week), (board, _outcome, _base) in sorted(loaded.items()):
        try:
            values = values_for(signal, board, season, league)
        except rank.PreflightError:
            continue
        if not values:
            continue
        out: set[str] = set()
        for pos in POSITIONS:
            members = [pid for pid, held in board.position.items()
                       if held == pos and pid in values]
            if members and len({values[pid] for pid in members}) <= 1:
                out.add(pos)
        return out
    return set()


def can_change_ordering(signal: Signal, loaded: dict[Scope, Any],
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
            board.projected, board.position, season, FIXED_LAMBDA, signal.name,
            values=values, **signal.kwargs,
        )
        value = rank.vorp_values(points, board.position, league)
        order = sorted(value, key=lambda pid: (-value[pid], pid))
        moved = sum(1 for a, b in zip(board.board, order, strict=False) if a != b)
        if moved:
            scopes_moved += 1
            worst = max(worst, moved)
    return scopes_moved > 0, scopes_moved, worst


def cell_report(signal: Signal, loaded: dict[Scope, Any], league: str) -> list[str]:
    """G5. Cells applied vs skipped, with the deciding sd, one scope per season.

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
                values=values_for(signal, board, season, league), **signal.kwargs,
            )
        except rank.PreflightError:
            lines.append(f"    {season}  inputs not pinned")
            continue
        applied = [c for c in cells if c.applied]
        skipped = [c for c in cells if not c.applied]
        detail = " ".join(f"{c.label}:n{c.n}/d{c.distinct}/sd{c.sd:.3g}" for c in cells)
        lines.append(f"    {season}  applied {len(applied)} skipped {len(skipped)}   {detail}")
    return lines


def _seasonal_score(signal: Signal, league: str, season: int, loaded: Any,
                    outcome: dict[str, float], strength: float,
                    values: dict[str, float]) -> float:
    points = signals.adjust(
        loaded.points, loaded.position, season, strength, signal.name,
        values=values, **signal.kwargs,
    )
    order = [pid for pid in rank.vorp_order(points, loaded.position, league) if pid in outcome]
    return rank.score_board(
        order, outcome, teams=int(rank.league(league).num_teams),
        pool_size=rank.pool_size_for(league), position=loaded.position,
        indexing="symmetric", position_pool=rank.position_pool_sizes(league),
    ).rwre


def seasonal_effect(signal: Signal, league: str) -> tuple[float, float, int]:
    """G7's other half: the same term on the SEASONAL draft board, FFA arm, same league.

    Selected the same way as the weekly side -- leave-one-season-out over the same grid -- so the
    two modes are comparable. `signals.score` is hardwired to the espn arm and one league, so this
    reproduces its shape rather than editing a function forty gates read.
    """
    base: dict[Scope, float] = {}
    treated: dict[float, dict[Scope, float]] = {lam: {} for lam in GRID}
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
        scope: Scope = (season, 0)
        base[scope] = _seasonal_score(signal, league, season, loaded, outcome, 0.0, values)
        for lam in GRID:
            treated[lam][scope] = (
                base[scope] if lam == 0.0
                else _seasonal_score(signal, league, season, loaded, outcome, lam, values)
            )
    selected, _effects, _chosen = loso(base, treated)
    return (selected, fixed(base, treated, FIXED_LAMBDA), len(base))


def run_signal(signal: Signal, loaded: dict[Scope, Any], league: str) -> dict[str, Any]:
    print(f"-- {signal.label}  [{signal.name}] --")
    print("   LOCUS (pre-registered): "
          f"{'board-level only' if not signal.locus else ' '.join(signal.locus)}")
    print(f"   mechanism: {signal.why}")

    cov = coverage(signal, loaded, league)
    print("   coverage, players with a value / players on the board:")
    for season in sorted(cov):
        have, total = cov[season]
        print(f"    {season}  {have:4d} / {total:4d}  {(have / total if total else 0.0):5.1%}")
    if not any(have > 0 for have, _total in cov.values()):
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
        print(f"   INERT on the weekly board at lambda {FIXED_LAMBDA}: not measured, per G4.")
        print()
        return {"signal": signal.name, "league": league, "verdict": "inert"}

    frozen = constant_within_position(signal, loaded, league)
    if frozen:
        print(f"   structurally unable to reorder: {' '.join(sorted(frozen))} "
              "(one distinct value inside the position)")

    record: dict[str, Any] = {
        "signal": signal.name, "league": league, "locus": list(signal.locus),
        "structurally_zero": sorted(frozen),
    }
    series = build_series(signal, loaded, league)
    selected, effects, chosen = loso(series.base, series.treated)
    at_fixed = fixed(series.base, series.treated, FIXED_LAMBDA)
    print(f"   scopes measured {len(series.base)}   lambda chosen out of sample per season: "
          f"{' '.join(f'{s}:{chosen[s]:g}' for s in sorted(chosen))}")
    print(f"   effect board-wide, SELECTED  {selected:+7.4f}   "
          f"(at fixed lambda {FIXED_LAMBDA}: {at_fixed:+7.4f})")
    record["effect_board"] = selected
    record["effect_board_fixed"] = at_fixed
    record["chosen"] = {str(k): v for k, v in chosen.items()}

    pos_selected: dict[str, float] = {}
    for pos in POSITIONS:
        if pos not in series.base_pos:
            continue
        value, _per_scope, _c = loso(
            series.base_pos[pos], {lam: series.treated_pos[lam][pos] for lam in GRID}
        )
        pos_selected[pos] = value
        mark = "  <- locus" if pos in signal.locus else ""
        if pos in frozen:
            mark += "  STRUCTURALLY ZERO"
        print(f"    {pos}  SELECTED {value:+7.4f}{mark}")
    record["per_position"] = pos_selected

    floor_board: list[float] = []
    floor_pos: dict[str, list[float]] = {pos: [] for pos in POSITIONS}
    for salt in range(FLOOR_DRAWS):
        drawn = build_series(signal, loaded, league, salt=salt, frozen=frozen)
        value, _e, _c = loso(drawn.base, drawn.treated)
        floor_board.append(value)
        for pos in POSITIONS:
            if pos in drawn.base_pos:
                pos_value, _e2, _c2 = loso(
                    drawn.base_pos[pos], {lam: drawn.treated_pos[lam][pos] for lam in GRID}
                )
                floor_pos[pos].append(pos_value)
    usable = [f for f in floor_board if f == f]
    print(f"   FLOOR, {FLOOR_DRAWS} salts matched to this signal's coverage, same selection:")
    print(f"    board-wide  mean {statistics.mean(usable):+7.4f} "
          f"sd {statistics.stdev(usable):.4f} max {max(usable):+7.4f}")
    p_board = reference_p(selected, floor_board)
    p_board_harm = harm_p(selected, floor_board)
    best_possible = achievable_p(selected, floor_board)
    print(f"    reference-set p, board-wide: {p_board:.4f}  "
          f"(harm p {p_board_harm:.4f}; the smallest p this test could return given its own "
          f"ties is {best_possible:.4f})")
    record["p_board"] = p_board
    record["p_board_harm"] = p_board_harm
    record["achievable_p_board"] = best_possible
    record["null_hit_rate_board"] = null_hit_rate(selected, floor_board)
    record["floor_board_mean"] = statistics.mean(usable)
    record["p_position"] = {}
    for pos in POSITIONS:
        if pos in frozen:
            print(f"    reference-set p, {pos}: not reported -- the treatment is structurally "
                  "0.0000 here and the floor is not")
            continue
        if pos in pos_selected and floor_pos[pos]:
            p_pos = reference_p(pos_selected[pos], floor_pos[pos])
            record["p_position"][pos] = p_pos
            record.setdefault("achievable_p_position", {})[pos] = achievable_p(
                pos_selected[pos], floor_pos[pos]
            )
            record.setdefault("harm_p_position", {})[pos] = harm_p(
                pos_selected[pos], floor_pos[pos]
            )
            record.setdefault("null_hit_rate_position", {})[pos] = null_hit_rate(
                pos_selected[pos], floor_pos[pos]
            )
            mark = "  <- locus" if pos in signal.locus else ""
            print(f"    reference-set p, {pos}: {p_pos:.4f}  "
                  f"(floor mean {statistics.mean(floor_pos[pos]):+.4f}, "
                  f"best possible {record['achievable_p_position'][pos]:.4f}){mark}")

    lo, hi = clustered_interval(effects, by="season", seed=SEED)
    slo, shi = clustered_interval(effects, by="scope", seed=SEED)
    print(f"   season-clustered 95% interval (PRIMARY, reported only): [{lo:+.4f}, {hi:+.4f}]")
    print(f"   scope-clustered  95% interval (reported only):          [{slo:+.4f}, {shi:+.4f}]")
    print("   player-clustered: NOT COMPUTED. See the module docstring.")
    record["interval_season"] = [lo, hi]
    record["interval_scope"] = [slo, shi]

    season_sel, season_fixed, n_seasons = seasonal_effect(signal, league)
    print(f"   SEASONAL draft board, {n_seasons} observations: SELECTED {season_sel:+7.4f}  "
          f"(at fixed lambda {FIXED_LAMBDA}: {season_fixed:+7.4f})")
    record["seasonal"] = season_sel
    record["seasonal_fixed"] = season_fixed
    record["seasonal_n"] = n_seasons

    record.update(
        verdict_of(record, signal.locus, selected, pos_selected, p_board, p_board_harm, frozen)
    )
    print(f"   VERDICT: {record['verdict']}  {record['verdict_why']}")
    print()
    return record


def verdict_of(record: dict[str, Any], locus: tuple[str, ...], selected: float,
               pos_selected: dict[str, float], p_board: float, p_board_harm: float,
               frozen: set[str]) -> dict[str, Any]:
    """The disposition, and TWO BUGS THE ADVERSARIAL REVIEW FOUND IN THE FIRST VERSION.

    BUG 1: `material` was `max(abs(...))` over the board effect and the locus effects, so the
    MAGNITUDE OF A TERM'S OWN DAMAGE could certify it. `ngs_separation` in danger_zone scored
    -0.1404 board-wide at p 0.9268 -- it lost to 38 of 40 floor draws -- and shipped as RESOLVES
    because `abs(-0.1404) >= 0.10`, then entered the composite. Materiality is now read at the
    PLACE THAT ACTUALLY QUALIFIED, with its sign.

    BUG 2: the same `max` ignored a hit that landed OFF the pre-registered locus, so
    `inj_status` -- +0.1919 at WR in green_hope and +0.1125 in danger_zone, the only pair of 336
    tests to hit in two leagues -- was recorded as immaterial. An off-locus hit is still not a
    resolution, because the locus was registered in advance and moving it afterwards is how a
    null becomes a headline. It is now `OFF-LOCUS` with its own materiality flag, which is what
    a lead should look like.

    BUG 3: the HARM branch tested `p <= 0.05 AND effect < 0`, which is backwards. `reference_p`
    is one-sided for improvement, so a term that damages the board reads p near 1.0. The branch
    fired zero times in 72 measurements while five terms sat at or past the material harm bar.
    Harm is now read off `harm_p`.
    """
    qualifying: list[tuple[str, float]] = []
    if p_board <= 0.05 and selected > 0.0:
        qualifying.append(("board", selected))
    locus_hits = [
        pos for pos in locus
        if record["p_position"].get(pos, 1.0) <= 0.05 and pos_selected.get(pos, 0.0) > 0.0
    ]
    qualifying.extend((pos, pos_selected[pos]) for pos in locus_hits)
    off_locus = [
        pos for pos in POSITIONS
        if pos not in locus and pos not in frozen
        and record["p_position"].get(pos, 1.0) <= 0.05 and pos_selected.get(pos, 0.0) > 0.0
    ]
    harms = [
        pos for pos in POSITIONS
        if record.get("harm_p_position", {}).get(pos, 1.0) <= 0.05
        and pos_selected.get(pos, 0.0) <= -MATERIAL
    ]
    if p_board_harm <= 0.05 and selected <= -MATERIAL:
        harms.append("board")

    material = bool(qualifying) and max(value for _where, value in qualifying) >= MATERIAL
    off_material = any(abs(pos_selected.get(pos, 0.0)) >= MATERIAL for pos in off_locus)
    if qualifying:
        verdict = "RESOLVES" if material else "resolves but immaterial"
    elif off_locus:
        verdict = "OFF-LOCUS" if off_material else "off-locus but immaterial"
    elif harms:
        verdict = "HARM"
    else:
        verdict = "null"
    why = (
        f"(p board {p_board:.4f}"
        + (", locus " + " ".join(locus_hits) if locus_hits else "")
        + (", OFF-LOCUS at " + " ".join(off_locus) if off_locus else "")
        + (", HARM at " + " ".join(harms) if harms else "")
        + f", material {material}"
        + (f", off-locus material {off_material}" if off_locus else "")
        + f", bar {MATERIAL} RWRE)"
    )
    return {
        "verdict": verdict, "verdict_why": why, "material": material,
        "off_locus_material": off_material, "locus_hits": locus_hits,
        "off_locus": off_locus, "harms": harms,
    }


def main(argv: list[str]) -> int:
    league = argv[1] if len(argv) > 1 else "espn_green_hope"
    # ONE FILE PER LEAGUE. The three leagues are run as three concurrent processes --
    # they share no state and the machine has the cores -- and a single append target
    # would interleave their records.
    out_path = Path(__file__).resolve().parent / "runs" / f"s7-phase2-{league}.jsonl"
    print(f"S7 PHASE 2 -- weekly re-adjudication, {league}")
    print(f"aggregation {AGGREGATION}, scale {SCALE}, grid {GRID}, "
          f"leave-one-season-out selection, {FLOOR_DRAWS} salts, {BOOTSTRAPS} bootstraps, "
          f"seed {SEED}")
    print()
    loaded = load_scopes(league)
    print(f"{len(loaded)} scopes loaded, {len({s for s, _ in loaded})} seasons")
    print()
    for signal in SIGNALS:
        record = run_signal(signal, loaded, league)
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
