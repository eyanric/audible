"""S2b -- the search space: eight knobs over one board, scored by rank accuracy.

`audible#84` ran four hand-written hypotheses. That is a checklist. This searches.

WHAT IS VARIED is the BOARD. What is NOT varied is the truth: the realised side is scored
through the DEFAULT transform for every candidate, fixed. If the candidate's own depth knobs
also moved the realised side, each candidate would be graded against a different definition of
correct and no two would be comparable.

The limitation that forces, stated rather than discovered: `qb_depth` measures "does tilting
the board's quarterback valuation RELATIVE TO THE DEFAULT TRUTH help". If the default truth is
itself mis-specified at QB -- and `rostered_counts` is known to be, giving a 1-QB league's QB
no bench at all -- this knob cannot discover that. It can only find a board that disagrees with
the default in a useful direction.

See `sim/runs/s2b-search.md` for the pre-registration: indexing, splits, knob ranges, the
shuffled-label null and the disposition rule were all fixed before this file existed.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from . import arms, holdout, rank

INDEXING = "symmetric"  # pre-registered, fixed
LEAGUE = "espn_green_hope"  # production's league; the winner is checked on the others


@dataclass(frozen=True, slots=True)
class Candidate:
    w_espn: float = 1.0
    w_ffa: float = 0.0
    w_sleeper: float = 0.0
    qb_depth: float = 1.0
    flex_depth: float = 1.0
    usage_lambda: float = 0.0
    shrink: float = 0.0
    vorp_mix: float = 0.0
    noise_lambda: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {k: round(float(v), 6) for k, v in asdict(self).items()}


BASELINE = Candidate()  # espn alone, default transform -- audible#84's incumbent


def sample(rng: random.Random) -> Candidate:
    """One draw. Blend weights come off a Dirichlet so the simplex is sampled uniformly."""
    g = [rng.gammavariate(1.0, 1.0) for _ in range(3)]
    tot = sum(g) or 1.0
    w = [x / tot for x in g]
    return Candidate(
        w_espn=w[0], w_ffa=w[1], w_sleeper=w[2],
        qb_depth=rng.uniform(1.0, 2.0),
        flex_depth=rng.uniform(0.7, 1.3),
        usage_lambda=rng.uniform(-0.15, 0.30),
        shrink=rng.uniform(0.0, 0.40),
        vorp_mix=rng.uniform(0.0, 0.50),
        noise_lambda=rng.uniform(-0.20, 0.20),
    )


# --- per-season inputs, built once ----------------------------------------------------------


@lru_cache(maxsize=64)
def _season_inputs(season: int, league_key: str) -> dict[str, Any]:
    """Everything a candidate needs for one season. Built once; candidates are then arithmetic."""
    available = [a for a in ("espn", "ffa", "sleeper") if season in rank.SEASONS_BY_ARM[a]]
    points: dict[str, dict[str, float]] = {}
    position: dict[str, str] = {}
    for a in available:
        loaded = arms.load(a, season, league_key)
        points[a] = loaded.points
        position.update(loaded.position)

    realised = rank.realised_per_game(season, league_key)
    rv = rank.realised_vorp(realised)

    # 2019's prior season is 2018 and player_stats_2018 is not pinned. Absence degrades to NO
    # ADJUSTMENT rather than to a zero z-score, which is the same rule the rest of the harness
    # uses: a player with no prior usage keeps his projection untouched. So the usage knob is
    # simply inert in 2019 rather than the season being dropped.
    try:
        share = rank.prior_share(season, "target_share")
    except rank.PreflightError:
        share = {}
    # Deterministic pseudo-noise: a hash, not an RNG, so a candidate scores the same on every
    # run and the noise knob is reproducible rather than a fresh draw each evaluation.
    noise = {
        pid: (int(hashlib.sha256(f"{pid}:{season}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF)
        * 2.0 - 1.0
        for pid in position
    }
    return {
        "available": available, "points": points, "position": position,
        "realised_vorp": rv, "share": share, "noise": noise,
        "teams": int(rank.league(league_key).num_teams),
        "pool": rank.pool_size_for(league_key),
    }


def _zscores(
    values: dict[str, float], position: dict[str, str], members: list[str]
) -> dict[str, float]:
    """Within-position z-scores over the players that HAVE a value. Absence stays absent."""
    out: dict[str, float] = {}
    for pos in rank.SCOREABLE:
        have = [p for p in members if position.get(p) == pos and p in values]
        if len(have) < 10:
            continue
        vals = [values[p] for p in have]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1))
        if sd <= 0:
            continue
        for p in have:
            out[p] = (values[p] - mu) / sd
    return out


def board_points(c: Candidate, inp: dict[str, Any]) -> dict[str, float]:
    """Blend the arms, then apply shrink, usage and noise. All multiplicative, all nesting 0."""
    weights = {"espn": c.w_espn, "ffa": c.w_ffa, "sleeper": c.w_sleeper}
    avail = inp["available"]
    pts_by_arm = inp["points"]

    blended: dict[str, float] = {}
    everyone = set().union(*(set(pts_by_arm[a]) for a in avail)) if avail else set()
    for pid in everyone:
        num = den = 0.0
        for a in avail:
            v = pts_by_arm[a].get(pid)
            if v is None:
                continue
            w = weights[a]
            num += w * v
            den += w
        # Renormalised over the arms that exist this season AND carry this player. A player one
        # arm has never heard of is not scored as a zero by that arm.
        if den > 0:
            blended[pid] = num / den

    position = inp["position"]
    members = list(blended)

    if c.shrink > 0:
        for pos in rank.SCOREABLE:
            at = [p for p in members if position.get(p) == pos]
            if len(at) < 10:
                continue
            mu = sum(blended[p] for p in at) / len(at)
            for p in at:
                blended[p] = blended[p] * (1 - c.shrink) + mu * c.shrink

    if c.usage_lambda != 0.0:
        z = _zscores(inp["share"], position, members)
        for p, zz in z.items():
            if p in blended:
                blended[p] *= 1.0 + c.usage_lambda * zz

    if c.noise_lambda != 0.0:
        for p in members:
            blended[p] *= 1.0 + c.noise_lambda * inp["noise"].get(p, 0.0)

    return blended


def board_order(c: Candidate, inp: dict[str, Any], league_key: str) -> list[str]:
    """Points -> VORP (with the depth knobs) -> optionally mixed back toward raw points."""
    pts = board_points(c, inp)
    position = inp["position"]
    vorp = _vorp_with_depth(pts, position, league_key, c.qb_depth, c.flex_depth)
    if c.vorp_mix > 0:
        # VORP and points share a unit, so the mix is dimensionally sound: it slides the
        # ordering between "fully de-levelled by position" and "raw points, scarcity ignored".
        vorp = {p: v * (1 - c.vorp_mix) + pts[p] * c.vorp_mix for p, v in vorp.items() if p in pts}
    return sorted(vorp, key=lambda p: (-vorp[p], p))


def _vorp_with_depth(
    points: dict[str, float], position: dict[str, str], league_key: str,
    qb_depth: float, flex_depth: float,
) -> dict[str, float]:
    from audible.models.player import PlayerProjection
    from audible.value.replacement import _ranked, assign_starters, rostered_counts

    config = rank.league(league_key)
    players = [
        PlayerProjection(
            player_id=pid, name=pid, primary_position=pos,
            eligible_positions=frozenset({pos}), team=None, points=points[pid],
        )
        for pid, pos in position.items()
        if pid in points and pos in rank.SCOREABLE
    ]
    if not players:
        return {}
    starters = assign_starters(players, config)
    rostered = dict(rostered_counts(players, config, starters))
    teams = int(config.num_teams)
    if qb_depth != 1.0:
        rostered["QB"] = max(1, round(teams * qb_depth))
    if flex_depth != 1.0:
        for pos in ("RB", "WR", "TE"):
            if pos in rostered:
                rostered[pos] = max(1, round(rostered[pos] * flex_depth))

    levels: dict[str, float] = {}
    for pos in {p.primary_position for p in players}:
        at = [p for p in _ranked(players) if p.primary_position == pos]
        taken = rostered.get(pos, 0)
        levels[pos] = at[taken].points if taken < len(at) else 0.0
    return {p.player_id: p.points - levels[p.primary_position] for p in players}


# --- evaluation -----------------------------------------------------------------------------


def evaluate(
    c: Candidate, seasons: tuple[int, ...], league_key: str = LEAGUE,
    *, permuted: bool = False,
) -> float:
    """Weighted-mean RWRE across *seasons*, under the pre-registered symmetric indexing."""
    holdout.assert_unlocked(seasons)
    num = den = 0.0
    for season in seasons:
        inp = _season_inputs(season, league_key)
        rv = _permuted_realised(season, league_key) if permuted else inp["realised_vorp"]
        order = [p for p in board_order(c, inp, league_key) if p in rv][: inp["pool"]]
        if not order:
            continue
        real_rank = rank._realised_order(order, rv)
        for i, pid in enumerate(order):
            br = i + 1
            w = rank._weights(br, inp["teams"], real_rank[pid], INDEXING)
            num += w * abs(br - real_rank[pid])
            den += w
    return num / den if den else float("nan")


@lru_cache(maxsize=16)
def _permuted_realised(season: int, league_key: str) -> dict[str, float]:
    """The null: realised values shuffled AMONG PLAYERS, so all structure is destroyed.

    Whatever a search finds against this is the floor available from searching alone.
    """
    inp = _season_inputs(season, league_key)
    rv = inp["realised_vorp"]
    ids = sorted(rv)
    vals = [rv[p] for p in ids]
    random.Random(20260909 + season).shuffle(vals)
    return dict(zip(ids, vals, strict=True))
