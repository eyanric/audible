"""S6 phase 3 -- transform shapes that are NOT `points -> subtract replacement -> sort by VORP`.

THE INCUMBENT READS ONE INPUT. `arms.load` returns a projected point total per player, the
board subtracts a per-position replacement level and sorts by the remainder. Everything else
the board already carries -- the spread FFA publishes beside every projection, the market's own
price, prior-season usage, physical measurement -- is discarded before the ordering is formed.

FOUR SHAPES ARE TRIED HERE, and the point of the set is that they fail differently:

  learned    predict realised VORP from every input and sort by the prediction. Replacement
             never appears. If the incumbent's shape is load-bearing this must lose.
  two-stage  predict realised per-game POINTS from every input, then run the INCUMBENT's
             transform on the prediction. Isolates whether any gain is in the projection or in
             the transform, which no session has separated.
  quantile   rank on `points + q * sd_pts` rather than on the mean. The board throws the spread
             away and FFA has published it vintage every season since 2018.
  boosted    depth-1 gradient-boosted stumps on the same inputs. Reports feature importances,
             which the linear shapes cannot.

NO NUMPY, NO SKLEARN, BY CHOICE. `sim/residual.py` already hand-rolls OLS for this reason and
`audible#86` verified it to 8.9e-16 against a known answer. A ranking this project ships has to
be reproducible from the repository alone.

SIX SEASONS WILL HAPPILY FIT ANYTHING. `audible#85` searched 4,000 boards over seven effective
knobs and its winner was 2.5 RWRE WORSE on unseen seasons, with a knob made of a sha256 buying
42% of the apparent gain. Every model here is ridge-regularised, the penalty is fitted inside
the fold rather than chosen once, and the EFFECTIVE degrees of freedom are computed exactly --
`tr((X'X + lam I)^-1 X'X)` -- and reported beside every result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from . import arms, rank, signals

LEAGUE = signals.LEAGUE
SOURCE = signals.SOURCE

# Every phase-2 candidate that passed G5, minus the floor itself. `noise` is added separately
# by the injection that checks a model gives an information-free input near-zero importance.
# SIX CANDIDATES WERE DROPPED AFTER THE PHASE-2 REVIEW MEASURED THEM, and the reasons are the
# session's own rules applied to itself:
#
#   ffa_tier, ffa_aav       Spearman 0.99 and 0.91 against FFA's own points within position.
#                           They ARE the projection restated, and phase 2 excluded
#                           `rank`/`position_rank` for exactly that. Keeping these while
#                           excluding those was an inconsistent application of one rule.
#   ffa_ceiling, ffa_floor  Defined as ceiling/points and floor/points, which is mechanically a
#                           monotone INVERSION of the projection (r = -0.59 and +0.58). Both
#                           were labelled "more is better"; at most one of them could be.
#   ffa_spread              r = -0.98 against `uncertainty`. A term and its own negation, in
#   ffa_uncertainty         the list twice. r = -0.80, same construct again.
#
# The dispersion axis is now carried by ONE term (`uncertainty` = sd_pts / points) plus a
# genuinely different one (`ffa_skew`, the ratio of upside to downside rather than their level).
FEATURES: tuple[str, ...] = (
    "snap_share", "target_share", "td_oe", "draft_round", "adp_gap",
    "ngs_separation", "ngs_cushion", "ngs_rush_eff", "ngs_time_to_los", "ngs_time_to_throw",
    "contract", "availability", "age_at_export", "uncertainty", "ffa_skew",
    "ffa_dropoff", "ffa_experience",
    "depth_slot", "ff_opp_exp", "ff_opp_eff",
)


@dataclass(frozen=True, slots=True)
class Design:
    """One season's design matrix, standardised within (season, position)."""

    season: int
    ids: list[str]
    position: list[str]
    x: list[list[float]]  # row per player
    names: list[str]
    y_vorp: list[float]  # realised VORP -- what the board is ultimately ordered by
    y_points: list[float]  # realised per-game points


def _zs_within_position(
    values: dict[str, float], ids: list[str], position: list[str]
) -> tuple[list[float], list[float]]:
    """(z, present) within position, over the players that HAVE a value.

    ABSENCE IS NOT ZERO, and the indicator is why. A player with no value gets z = 0, which is
    the positional mean -- but he also gets `present = 0`, so a model can give absent players
    their own intercept instead of silently asserting they are average. Coding absence as the
    mean with no indicator is the defect `sim/signals.py::adjust` avoids by refusing to touch
    absent players at all; a design matrix cannot refuse, so it declares instead.
    """
    z = [0.0] * len(ids)
    present = [0.0] * len(ids)
    for pos in rank.SCOREABLE:
        idx = [i for i, p in enumerate(position) if p == pos and ids[i] in values]
        if len(idx) < 10:
            continue
        xs = [values[ids[i]] for i in idx]
        mu = sum(xs) / len(xs)
        sd = math.sqrt(sum((v - mu) ** 2 for v in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0
        if len(set(xs)) <= 1 or sd <= 0:
            continue
        for i in idx:
            z[i] = (values[ids[i]] - mu) / sd
            present[i] = 1.0
    return z, present


@lru_cache(maxsize=16)
def design(season: int, league_key: str = LEAGUE) -> Design:
    """Assemble every phase-2 input for one season, plus the target."""
    loaded = arms.load(SOURCE, season, league_key)
    realised = rank.realised_per_game(season, league_key)
    rv = rank.realised_vorp(realised)

    ids = [p for p in rank.vorp_order(loaded.points, loaded.position, league_key) if p in rv]
    position = [loaded.position[p] for p in ids]

    cols: list[list[float]] = []
    names: list[str] = []

    # The incumbent's single input, on the same footing as everything else. A model that cannot
    # beat "use the projection" has to be shown that projection.
    proj_z, _ = _zs_within_position(loaded.points, ids, position)
    cols.append(proj_z)
    names.append("projection")

    for feat in FEATURES:
        try:
            vals = signals.signal_values(feat, season)
        except (rank.PreflightError, ValueError):
            vals = {}
        z, present = _zs_within_position(vals, ids, position)
        # EVERY FEATURE EMITS ITS COLUMNS IN EVERY SEASON, even when the season has no values
        # at all. Skipping an absent feature made the design matrix a different width in 2019 --
        # which has no `target_share` and no `availability` -- so a model fitted on five seasons
        # could not be applied to the sixth at all. The indicator carries the absence.
        cols.append(z)
        names.append(feat)
        cols.append(present)
        names.append(f"{feat}__present")

    # Position dummies AND position-by-projection interactions.
    #
    # THE INTERACTIONS ARE NOT OPTIONAL, and leaving them out was a defect that produced a
    # false null. The incumbent orders by `points - replacement(pos)`. `projection` above is the
    # WITHIN-POSITION z-score of points, so recovering the incumbent from it needs a per-position
    # SLOPE (the position's own sd) as well as a per-position intercept. Dummies alone supply
    # only the intercept, so the design could express a single global slope and no more -- it
    # structurally could not represent the board it was being asked to beat. Handed only the
    # `projection` column and fitted in-sample, ridge scored 33.59 against the incumbent's 18.40
    # in 2019.
    #
    # Adding three columns moved the learned shape from +1.852 to -0.008 against the incumbent.
    # No outcome is involved and both factors are known preseason, so this is a specification
    # fix rather than a new input.
    for pos in rank.SCOREABLE[:-1]:  # one held out as the reference level
        cols.append([1.0 if q == pos else 0.0 for q in position])
        names.append(f"pos_{pos}")
        cols.append([proj_z[i] if q == pos else 0.0 for i, q in enumerate(position)])
        names.append(f"pos_{pos}_x_projection")

    x = [[c[i] for c in cols] for i in range(len(ids))]
    return Design(
        season=season, ids=ids, position=position, x=x, names=names,
        y_vorp=[rv[p] for p in ids],
        y_points=[realised.per_game.get(p, 0.0) for p in ids],
    )


# --- ridge, hand-rolled ----------------------------------------------------------------------


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting. Same routine `residual.ols` uses."""
    m = len(b)
    aa = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(m):
        piv = max(range(i, m), key=lambda r: abs(aa[r][i]))
        if abs(aa[piv][i]) < 1e-12:
            continue
        aa[i], aa[piv] = aa[piv], aa[i]
        inv = 1.0 / aa[i][i]
        for j in range(i, m + 1):
            aa[i][j] *= inv
        for r in range(m):
            if r != i and aa[r][i] != 0.0:
                f = aa[r][i]
                for j in range(i, m + 1):
                    aa[r][j] -= f * aa[i][j]
    return [aa[i][m] for i in range(m)]


def _inverse(a: list[list[float]]) -> list[list[float]]:
    m = len(a)
    return [[c for c in col] for col in zip(
        *[_solve(a, [1.0 if i == j else 0.0 for i in range(m)]) for j in range(m)],
        strict=True)]


@dataclass(frozen=True, slots=True)
class Ridge:
    betas: list[float]
    intercept: float
    names: list[str]
    lam: float
    eff_params: float

    def predict(self, row: list[float]) -> float:
        return self.intercept + sum(b * v for b, v in zip(self.betas, row, strict=True))


def fit_ridge(x: list[list[float]], y: list[float], names: list[str], lam: float) -> Ridge:
    """Closed-form ridge, with the EXACT effective degrees of freedom.

    `eff_params = tr((X'X + lam I)^-1 X'X)`, which is the trace of the hat matrix and the honest
    answer to "how many parameters is this really". At lam = 0 it equals the column count; as
    lam grows it falls continuously. The intercept is not penalised, so it is excluded from the
    penalty and counted separately.
    """
    n, k = len(y), len(names)
    if n <= 1:
        return Ridge([0.0] * k, 0.0, list(names), lam, 0.0)
    mx = [sum(r[j] for r in x) / n for j in range(k)]
    my = sum(y) / n
    xc = [[r[j] - mx[j] for j in range(k)] for r in x]
    yc = [v - my for v in y]

    a = [[sum(xc[t][i] * xc[t][j] for t in range(n)) for j in range(k)] for i in range(k)]
    b = [sum(xc[t][i] * yc[t] for t in range(n)) for i in range(k)]
    reg = [[a[i][j] + (lam if i == j else 0.0) for j in range(k)] for i in range(k)]
    betas = _solve(reg, b)

    inv = _inverse(reg)
    eff = sum(sum(inv[i][t] * a[t][i] for t in range(k)) for i in range(k)) + 1.0
    intercept = my - sum(betas[j] * mx[j] for j in range(k))
    return Ridge(betas, intercept, list(names), lam, eff)


# --- gradient-boosted stumps, hand-rolled ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Stump:
    col: int
    threshold: float
    left: float
    right: float


@dataclass(frozen=True, slots=True)
class Boosted:
    base: float
    stumps: list[Stump]
    shrinkage: float
    names: list[str]

    def predict(self, row: list[float]) -> float:
        out = self.base
        for s in self.stumps:
            out += self.shrinkage * (s.left if row[s.col] <= s.threshold else s.right)
        return out

    def importances(self) -> dict[str, float]:
        """Share of total absolute leaf movement attributable to each feature."""
        tot: dict[str, float] = {}
        for s in self.stumps:
            tot[self.names[s.col]] = tot.get(self.names[s.col], 0.0) + abs(s.right - s.left)
        grand = sum(tot.values()) or 1.0
        return {k: v / grand for k, v in sorted(tot.items(), key=lambda kv: -kv[1])}

    @property
    def eff_params(self) -> float:
        """Two leaves a stump, shrunk. Not comparable to a ridge trace, and labelled so."""
        return 2.0 * len(self.stumps) * self.shrinkage


def fit_boosted(
    x: list[list[float]], y: list[float], names: list[str], *,
    rounds: int = 600, shrinkage: float = 0.02, bins: int = 12,
) -> Boosted:
    """Depth-1 gradient boosting on squared error. Deterministic: no subsampling, no RNG."""
    n, k = len(y), len(names)
    base = sum(y) / n if n else 0.0
    resid = [v - base for v in y]
    stumps: list[Stump] = []

    # Candidate thresholds once, from quantiles of each column. Fixed before fitting, so a
    # stump cannot chase a single player.
    cuts: list[list[float]] = []
    for j in range(k):
        col = sorted(r[j] for r in x)
        qs = sorted({col[min(n - 1, (i * n) // bins)] for i in range(1, bins)})
        cuts.append(qs)

    for _ in range(rounds):
        best = None
        for j in range(k):
            for thr in cuts[j]:
                ls = lc = rs = rc = 0.0
                for t in range(n):
                    if x[t][j] <= thr:
                        ls += resid[t]
                        lc += 1.0
                    else:
                        rs += resid[t]
                        rc += 1.0
                if lc < 20 or rc < 20:
                    continue
                gain = ls * ls / lc + rs * rs / rc
                if best is None or gain > best[0]:
                    best = (gain, j, thr, ls / lc, rs / rc)
        if best is None:
            break
        _g, j, thr, lv, rv_ = best
        stumps.append(Stump(j, thr, lv, rv_))
        for t in range(n):
            resid[t] -= shrinkage * (lv if x[t][j] <= thr else rv_)
    return Boosted(base, stumps, shrinkage, list(names))
