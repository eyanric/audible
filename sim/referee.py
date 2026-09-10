"""S5 -- the referee. The floor is a DISTRIBUTION, and the gate must reject an artifact.

WHAT WAS BROKEN. `audible#86` published +2.317 as "the floor". `audible#87` published +0.364.
Both were single draws of an information-free sha256, and both decided dispositions. Measured
across 42 independent draws in `audible#87`, the spread ACROSS POSITIONS of the seed-averaged
floor is 0.321 while the spread WITHIN one position across seeds reaches 2.097 -- so the
quantity that varies is the draw, not the position. A "resolved" tight-end reading of
-0.701 [-1.301, -0.138] -- a hash IMPROVING the board -- was the extreme of those 42.

THE MECHANISM OF THE ERROR, stated precisely because the fix follows from it: the paired
bootstrap resampled PLAYERS CONDITIONAL ON THE SALT. The salt was a constant inside the
resampling loop, so its own variance -- sd 0.2 to 0.6, larger than most effects this project
has measured -- could not appear in any interval.

THE FIX. The salt is resampled INSIDE the bootstrap, alongside the season. A signal is
adjudicated against the floor's distribution rather than against one of its draws, and the
reported statistic is the DIFFERENCE `signal - floor` with both sources of variance in it.

THE UNIT OF RESAMPLING IS THE SEASON. The fit is leave-one-season-out, there are six seasons,
and `audible#87`'s review showed the player-level interval is anticonservative here because
players recur across seasons. Season clustering is the honest choice and it is the default;
the player-level figure is reported beside it and labelled.

WHY THE FLOOR IS NOT SUBTRACTED AS A CONSTANT. A floor is not a bias to correct. It is the
answer to "how much does this harness move when handed nothing", and a signal earns a
disposition only by moving it further than an information-free term of the same shape moves it.
"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from dataclasses import dataclass
from functools import lru_cache

from . import arms, rank, signals

# Pre-registered and fixed for this session. The grid is `audible#87`'s, unchanged, so that a
# re-adjudication differs from the original only in the referee and never in the search.
GRID: tuple[float, ...] = (-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20)
LOCI: tuple[str, ...] = ("board", "QB", "RB", "WR", "TE")

# G1 requires at least twenty. FORTY are drawn, and the count is not arbitrary: a two-sided
# reference-set test against K draws cannot report a p-value below 2/(K+1), so K=24 bottoms out
# at 0.080 and CANNOT EXPRESS A 5% TEST AT ANY EFFECT SIZE. K=39 is the smallest that reaches
# 0.050. They are named rather than seeded from a global RNG, so any one can be reproduced alone.
SALTS: tuple[str, ...] = tuple(f"s5-floor-{i:02d}" for i in range(40))

# `audible#86` and `#87`'s single draw, kept ONLY so the damage it did can be measured:
# `sha256(f"{pid}:{season}")`, no salt. Injection 1 adjudicates against it and reports which
# dispositions it would have got wrong.
LEGACY_SALT: str | None = None

N_BOOT = 4000
BOOT_SEED = 20260910


@lru_cache(maxsize=512)
def salt_values(salt: str | None, season: int) -> dict[str, float]:
    """An information-free value per player: reproducible, and carrying nothing by design.

    Not an RNG draw. A named salt scores identically on every run and on every machine, which
    is what lets a floor draw be re-run in isolation years later.
    """
    loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
    out: dict[str, float] = {}
    for pid in loaded.position:
        key = f"{pid}:{season}" if salt is None else f"{salt}|{pid}:{season}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:8]
        out[pid] = (int(digest, 16) / 0xFFFFFFFF) * 2.0 - 1.0
    return out


def espn_seasons() -> tuple[int, ...]:
    """The seasons the board source actually serves. ESPN has no 2023 -- see trap 2."""
    return signals.seasons_for("noise")


def score_at(
    season: int, lam: float, name: str, *,
    values: dict[str, float] | None = None, scope: str | None = None,
    rookies_only: bool = False,
) -> tuple[float, dict[str, float]]:
    """(board-wide RWRE, {position: RWRE}) for one season at one weight."""
    loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
    realised = rank.realised_per_game(season, signals.LEAGUE)
    rv = rank.realised_vorp(realised)
    pts = signals.adjust(
        loaded.points, loaded.position, season, lam, name,
        rookies_only=rookies_only, scope=scope, values=values,
    )
    order = [p for p in rank.vorp_order(pts, loaded.position, signals.LEAGUE) if p in rv]
    if not order:
        raise rank.PreflightError(f"no board for {season}")
    s = rank.score_board(
        order, rv, teams=int(rank.league(signals.LEAGUE).num_teams),
        pool_size=rank.pool_size_for(signals.LEAGUE), position=loaded.position,
        indexing=signals.INDEXING,
        # S6 G1. Position-local pools, so a term that moves only the interleave cannot
        # register a per-position effect.
        position_pool=rank.position_pool_sizes(signals.LEAGUE),
    )
    return s.rwre, s.per_position


def _pick(cell: tuple[float, dict[str, float]], locus: str) -> float | None:
    return cell[0] if locus == "board" else cell[1].get(locus)


@lru_cache(maxsize=256)
def table(
    name: str, seasons: tuple[int, ...], salt: str | None = "__signal__",
    scope: str | None = None, rookies_only: bool = False,
) -> dict[tuple[int, float], tuple[float, dict[str, float]]]:
    """Every (season, weight) board scored once, and reused by every locus.

    ONE TABLE PER TERM IS THE POINT, not the speed. `audible#87` reported a per-position
    number and a board-wide number that came from two different statistics, and neither
    reproduced. Deriving every locus from the same scored boards makes that impossible.
    """
    def values_for(season: int) -> dict[str, float] | None:
        return None if salt == "__signal__" else salt_values(salt, season)

    return {
        (s, lam): score_at(s, lam, name, values=values_for(s), scope=scope,
                           rookies_only=rookies_only)
        for s in seasons for lam in GRID
    }


def _fit(tab: dict, seasons: tuple[int, ...], locus: str, held: int) -> float:
    """The weight the OTHER seasons choose at this locus. Ties go to the smaller |lambda|."""
    others = [s for s in seasons if s != held]
    best, best_lam = float("inf"), 0.0
    for lam in GRID:
        vals = [v for v in (_pick(tab[(s, lam)], locus) for s in others) if v is not None]
        if vals and sum(vals) / len(vals) < best:
            best, best_lam = sum(vals) / len(vals), lam
    return best_lam


def deltas(
    name: str, seasons: tuple[int, ...], *,
    salt: str | None = "__signal__", scope: str | None = None,
    rookies_only: bool = False,
) -> dict[str, dict[int, float]]:
    """Leave-one-season-out delta per locus per season, from ONE table of scored boards.

    For each held-out season the weight is fitted on the OTHER seasons at that locus, then the
    held-out season is scored at the fitted weight and at zero.
    """
    tab = table(name, seasons, salt, scope, rookies_only)
    out: dict[str, dict[int, float]] = {}
    for locus in LOCI:
        per_season: dict[int, float] = {}
        for held in seasons:
            best_lam = _fit(tab, seasons, locus, held)
            base = _pick(tab[(held, 0.0)], locus)
            treated = _pick(tab[(held, best_lam)], locus)
            if base is not None and treated is not None:
                per_season[held] = treated - base
        if per_season:
            out[locus] = per_season
    return out


def fitted_lambdas(
    name: str, seasons: tuple[int, ...], locus: str, *,
    salt: str | None = "__signal__", scope: str | None = None,
    rookies_only: bool = False,
) -> dict[int, float]:
    """The weight each fold chose. A sign that flips across folds is not a fitted weight."""
    tab = table(name, seasons, salt, scope, rookies_only)
    return {held: _fit(tab, seasons, locus, held) for held in seasons}


# --- the floor as a distribution -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Floor:
    """Every draw of the floor, kept per season so the bootstrap can resample both."""

    salts: tuple[str, ...]
    seasons: tuple[int, ...]
    per: dict[str, list[dict[int, float]]]  # locus -> one {season: delta} per salt

    def means(self, locus: str) -> list[float]:
        """One number per salt: that draw's floor at this locus."""
        return [sum(d.values()) / len(d) for d in self.per[locus] if d]


def draw_floor(seasons: tuple[int, ...], salts: tuple[str, ...] = SALTS) -> Floor:
    """G1. Draw the floor many times and keep every draw."""
    per: dict[str, list[dict[int, float]]] = {locus: [] for locus in LOCI}
    for salt in salts:
        d = deltas("noise", seasons, salt=salt)
        for locus in LOCI:
            per[locus].append(d.get(locus, {}))
    return Floor(salts=salts, seasons=seasons, per=per)


def load_floor(path: str) -> Floor:
    """Read the draws `s5_floor.py` wrote, so every adjudication uses the SAME floor."""
    import json
    from pathlib import Path

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Floor(
        salts=tuple(raw["salts"]),
        seasons=tuple(int(s) for s in raw["seasons"]),
        per={k: [{int(s): float(v) for s, v in d.items()} for d in draws]
             for k, draws in raw["per"].items()},
    )


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    i = q * (len(s) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (i - lo)


@dataclass(frozen=True, slots=True)
class Summary:
    mean: float
    sd: float
    lo: float
    hi: float

    def __str__(self) -> str:
        return f"{self.mean:+.3f} [{self.lo:+.3f}, {self.hi:+.3f}] sd {self.sd:.3f}"


def floor_summary(floor: Floor, locus: str) -> Summary:
    """G1. The floor's own distribution at one locus, across salts."""
    xs = floor.means(locus)
    return Summary(
        mean=_mean(xs),
        sd=statistics.stdev(xs) if len(xs) > 1 else float("nan"),
        lo=_pct(xs, 0.025), hi=_pct(xs, 0.975),
    )


@dataclass(frozen=True, slots=True)
class Verdict:
    """One adjudication, with both intervals it was decided on."""

    locus: str
    n_seasons: int
    signal: Summary
    floor: Summary
    difference: Summary
    disposition: str
    per_season: dict[int, float]

    def line(self) -> str:
        return (f"{self.locus:5s} signal {self.signal}  floor {self.floor}  "
                f"diff {self.difference}  {self.disposition}")


def adjudicate(
    signal: dict[int, float], floor: Floor, locus: str, *,
    n_boot: int = N_BOOT, seed: int = BOOT_SEED, resample_salt: bool = True,
    fixed_salt_index: int = 0,
) -> Verdict:
    """G2/G3. `signal - floor`, resampling the SEASON and the SALT together.

    *resample_salt* False reproduces the broken mechanism: the salt is held at one draw and
    only the season is resampled, which is what `audible#86` and `#87` did. Injection 1 runs
    both and reports where they disagree.
    """
    seasons = [s for s in floor.seasons if s in signal]
    draws = [d for d in floor.per[locus] if d]
    if not seasons or not draws:
        raise ValueError(f"nothing to adjudicate at {locus}")

    rng = random.Random(seed)
    sig_stats: list[float] = []
    flo_stats: list[float] = []
    dif_stats: list[float] = []
    for _ in range(n_boot):
        pick = [seasons[rng.randrange(len(seasons))] for _ in range(len(seasons))]
        k = rng.randrange(len(draws)) if resample_salt else fixed_salt_index
        fl = draws[k]
        s_vals = [signal[s] for s in pick]
        f_vals = [fl[s] for s in pick if s in fl]
        if not f_vals:
            continue
        sm, fm = _mean(s_vals), _mean(f_vals)
        sig_stats.append(sm)
        flo_stats.append(fm)
        dif_stats.append(sm - fm)

    point_sig = _mean([signal[s] for s in seasons])
    point_flo = _mean([_mean([d[s] for s in seasons if s in d]) for d in draws])
    sig = Summary(point_sig, statistics.stdev(sig_stats), _pct(sig_stats, 0.025),
                  _pct(sig_stats, 0.975))
    flo = Summary(point_flo, statistics.stdev(flo_stats), _pct(flo_stats, 0.025),
                  _pct(flo_stats, 0.975))
    dif = Summary(point_sig - point_flo, statistics.stdev(dif_stats),
                  _pct(dif_stats, 0.025), _pct(dif_stats, 0.975))

    if dif.hi < 0:
        disposition = "RESOLVED BEATS FLOOR"
    elif dif.lo > 0:
        disposition = "RESOLVED WORSE THAN FLOOR"
    else:
        disposition = "not resolved"
    return Verdict(locus, len(seasons), sig, flo, dif, disposition, dict(signal))


def reference_p(signal: dict[int, float], floor: Floor, locus: str) -> float:
    """Two-sided reference-set p-value: where the signal sits among the draws themselves.

    NO BOOTSTRAP AT ALL. Both sides are measured on the SAME six seasons, so the season shock
    is common to every draw and conditioning on it is correct -- the honest question is simply
    "how extreme is this term among terms known to carry nothing".

    THE FLOOR OF THIS TEST IS 2/(K+1), so K draws cannot report a p below that at ANY effect
    size. K=24 bottoms out at 0.080 and cannot express a 5% test; K=40 reaches 0.049.
    """
    draws = [d for d in floor.per[locus] if d]
    seasons = [s for s in floor.seasons if s in signal]
    t = _mean([signal[s] for s in seasons])
    ts = [_mean([d[s] for s in seasons if s in d]) for d in draws]
    below = sum(1 for x in ts if x <= t)
    above = sum(1 for x in ts if x >= t)
    return min(1.0, (2 * min(below, above) + 2) / (len(ts) + 1))


def calibrate(floor: Floor, locus: str, *, n_boot: int = 1000) -> dict[str, float]:
    """What is the referee's ACTUAL false-resolution rate when the truth is known to be null?

    Every draw is information-free by construction, so adjudicating draw j against a floor
    built from the OTHER draws is a test whose null is true. The rate at which that resolves
    is the referee's real size. A rule reported as "5%" that fires 0% of the time is not a
    conservative 5% test -- it is a 0% test, and it cannot resolve anything at any effect size.

    This is the check `audible#86` and `#87` never ran, and it is the reason their referee's
    30%-plus false-resolution rate went unnoticed.
    """
    draws = [d for d in floor.per[locus] if d]
    resolved = beats = worse = 0
    ps: list[float] = []
    for j, d in enumerate(draws):
        rest = Floor(
            salts=tuple(s for i, s in enumerate(floor.salts) if i != j),
            seasons=floor.seasons,
            per={k: [x for i, x in enumerate(v) if i != j] for k, v in floor.per.items()},
        )
        v = adjudicate(d, rest, locus, n_boot=n_boot, seed=BOOT_SEED + j)
        if v.disposition.startswith("RESOLVED"):
            resolved += 1
            beats += v.disposition.endswith("FLOOR") and "BEATS" in v.disposition
            worse += "WORSE" in v.disposition
        ps.append(reference_p(d, rest, locus))
    n = len(draws)
    ps.sort()
    return {
        "n": float(n),
        "resolved": float(resolved),
        "rate": resolved / n if n else float("nan"),
        "beats": float(beats),
        "worse": float(worse),
        "p05": ps[max(0, int(0.05 * (len(ps) - 1)))] if ps else float("nan"),
        "p50": ps[len(ps) // 2] if ps else float("nan"),
        "pmin": ps[0] if ps else float("nan"),
    }


# --- G5 rebuilt: an artifact cannot pass ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateResult:
    """G4/G5. Why a term may or may not be measured."""

    name: str
    scope: str
    live_seasons: tuple[int, ...]
    total_seasons: int
    applied: int
    skipped: int
    min_applied_sd: float
    moved_by_season: dict[int, int]
    within_moves: dict[int, int]
    passed: bool
    reasons: tuple[str, ...]
    cell_lines: tuple[str, ...]


MIN_LIVE_SEASONS = 2


def ordering_gate(
    name: str, seasons: tuple[int, ...], *, scope: str | None = None,
    lam: float = 0.10, rookies_only: bool = False,
    order_fn: callable | None = None,
) -> GateResult:
    """G5, rebuilt. A term is measurable only if it moves an ordering FOR THE REASON CLAIMED.

    `audible#87`'s gate asked one question -- "did some ordering move" -- and an inert term
    passed it on 214 players displaced by 8.95e-16 of floating-point residue. Four conditions
    now have to hold together, and every one of them exists because a specific term slipped
    through the version before it:

      1. the term APPLIES in at least two seasons          -- `availability` was live in one
      2. every applied cell clears `signals.MIN_SD_REL`    -- that one cell was float residue
      3. the board ordering MOVES in at least two seasons  -- the weakest of the four
      4. a POSITION-SCOPE term moves a WITHIN-POSITION ordering in at least two seasons

    Condition 4 is what rejects `shrink`, and it is a statement about the mechanism rather than
    a tuned threshold: a term that claims to separate players inside a position must be shown
    to do that, and `shrink` provably cannot -- it multiplies each position by one positive
    scalar. A `board`-scope term like `availability` is EXEMPT by construction, because moving
    only the cross-position interleave is exactly what it claims to do. Raising condition 3's
    season count until `shrink` failed would have been gerrymandering; naming the mechanism is
    not.

    Condition 2 is enforced inside `signals.cells`, which `adjust` itself uses, so the gate
    cannot pass a cell the transform would skip or skip one the transform would apply.

    *order_fn* supplies the board for a term that is not a z-scored signal -- `shrink` has no
    cells at all, so it could not otherwise be put through this gate at all. `audible#87`'s
    injection counted displacements by hand instead, which is not the same as running the gate.
    """
    applied = skipped = 0
    live: list[int] = []
    moved: dict[int, int] = {}
    within: dict[int, int] = {}
    sds: list[float] = []
    lines: list[str] = []
    has_cells = order_fn is None

    for season in seasons:
        loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
        if has_cells:
            cs = signals.cells(loaded.points, loaded.position, season, name,
                               rookies_only=rookies_only, scope=scope)
            any_applied = False
            for c in cs:
                if c.applied:
                    applied += 1
                    any_applied = True
                    sds.append(c.sd)
                else:
                    skipped += 1
                lines.append(
                    f"{season} {c.label:5s} n={c.n:3d} distinct={c.distinct:3d} "
                    f"sd={c.sd:.3e} {'APPLIED' if c.applied else 'skipped'} ({c.reason})"
                )
            if any_applied:
                live.append(season)

        base = rank.vorp_order(loaded.points, loaded.position, signals.LEAGUE)
        if order_fn is None:
            adj = signals.adjust(loaded.points, loaded.position, season, lam, name,
                                 rookies_only=rookies_only, scope=scope)
            after = rank.vorp_order(adj, loaded.position, signals.LEAGUE)
        else:
            after = order_fn(season, lam)
        moved[season] = sum(1 for a, b in zip(base, after, strict=False) if a != b)

        # Condition 4. Strip each position out of both orderings and compare them alone, so a
        # change in the interleave cannot be mistaken for within-position information.
        n_within = 0
        for pos in rank.SCOREABLE:
            b_at = [p for p in base if loaded.position.get(p) == pos]
            a_at = [p for p in after if loaded.position.get(p) == pos]
            if b_at != a_at:
                n_within += 1
        within[season] = n_within

    eff_scope = scope or signals.SIGNAL_SCOPE.get(name, "position")
    reasons: list[str] = []
    if has_cells:
        if len(live) < MIN_LIVE_SEASONS:
            reasons.append(f"applies in {len(live)} season(s), needs {MIN_LIVE_SEASONS}")
        if applied == 0:
            reasons.append("no cell clears the minimum standard deviation")
    n_moving = sum(1 for v in moved.values() if v > 0)
    if n_moving < MIN_LIVE_SEASONS:
        reasons.append(f"moves an ordering in {n_moving} season(s), needs {MIN_LIVE_SEASONS}")
    n_within_moving = sum(1 for v in within.values() if v > 0)
    if eff_scope == "position" and n_within_moving < MIN_LIVE_SEASONS:
        reasons.append(
            f"position-scope term moves a WITHIN-POSITION ordering in {n_within_moving} "
            f"season(s), needs {MIN_LIVE_SEASONS} -- it carries no within-position information"
        )

    return GateResult(
        name=name, scope=eff_scope,
        live_seasons=tuple(live), total_seasons=len(seasons),
        applied=applied, skipped=skipped,
        min_applied_sd=min(sds) if sds else float("nan"),
        moved_by_season=moved, within_moves=within,
        passed=not reasons, reasons=tuple(reasons),
        cell_lines=tuple(lines),
    )


def shrink_order(season: int, s: float) -> list[str]:
    """Injection 3. `audible#85`'s `shrink`, reproduced: contract points toward the position mean.

    Inert on the ORDERING and provably so rather than empirically: within a position both the
    player and his own replacement contract by the same factor, so every VORP scales by (1-s)
    and no pair can cross. `can_change_ordering` in `audible#87` never exercised this path.
    """
    loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
    pts = dict(loaded.points)
    if s > 0:
        for pos in rank.SCOREABLE:
            at = [p for p in pts if loaded.position.get(p) == pos]
            if len(at) < 10:
                continue
            mu = sum(pts[p] for p in at) / len(at)
            for p in at:
                pts[p] = pts[p] * (1 - s) + mu * s
    return rank.vorp_order(pts, loaded.position, signals.LEAGUE)
