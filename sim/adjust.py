"""B14's regression-adjusted season interval, and the measurement that says NOT TO USE IT.

READ THIS BEFORE READING ANYTHING ELSE HERE. This module computes a real estimator correctly
and the estimator is **not usable for anything this repo reports**. It is kept, wired to
nothing, because a refutation that lives only in a PR body gets rediscovered, and because the
gates in `sim/test_g_b14.py` pin the refutation so it cannot be quietly re-adopted.
`report()` is the only public way to obtain the numbers and it refuses to hand back an
adjusted interval without the coverage warning attached.

WHAT B14 SET OUT TO DO. `audible#76` measured 86.7% of `mfl_8`'s interval width as
between-season and concluded only more seasons could fix it. B14's plan was a control variate
on a season covariate -- how much value the season had available -- to remove that shock.

REFUTATION 1, ARITHMETIC. The classical control variate subtracts `beta * (Wbar - E[W])` and
needs `E[W]` KNOWN. There are five seasons and no sixth, so `E[W]` comes from the same five,
the correction is identically zero, and the point estimate cannot move. B14's failure
injection 3 -- "fix beta at a large wrong value, the point estimate moves and G6 fires" --
therefore CANNOT FIRE, and a G6 pass is arithmetic rather than evidence.
`sim/runs/b14-plan.md` recorded this before anything was computed.

REFUTATION 2, THE ONE THAT KILLS IT. What was built instead is the conditional (ANCOVA)
reading: same point estimate, interval from the residual spread about a fitted season slope.
That interval is exact -- for `E[Y | W = Wbar]`. It is NOT an interval for `E[Y]`, the mean
over seasons, which is the estimand every gate and every headline in this repo reads. The
missing piece is the same one that killed refutation 1:

    Ybar - E[Y] = beta * (Wbar - E[W]) + ebar

and the adjusted half-width prices only `ebar`. Two independent adversarial reviews measured
the coverage of a nominal 95% interval, k = 5, 60k-100k replications each:

    |rho|    0.00   0.45   0.50   0.655   0.71   0.80   0.90   0.95   0.98
    covers   .950   .935   .929   .904    .891   .848   .740   .607   .422

**Coverage falls monotonically in exactly the quantity the adoption rule selects on.** The
better the covariate looks, the more anti-conservative the interval. At the break-even
threshold itself a nominal 95% interval covers 90%; at the correlations B14 actually observed
on its headline comparisons it covers 40-75%.

REFUTATION 3, SELECTION. `rho` is estimated from the same five points as the interval, so
adopting on `|rho| > BREAK_EVEN` is selecting on the statistic. Measured against a
ZERO-INFORMATION covariate: it clears the gate 23.1% of the time, and on those draws the
interval is 18% narrower than the honest one and covers 87.7%. Under the full decision rule a
true null is declared resolvable **12.4%** of the time instead of 5%. Taking the best of the
three covariates in `COVARIATES` raises that to 13.7%. Pre-registering the threshold does not
help: `sim/runs/b14-plan.md` fixed the threshold, not the outcome.

WHAT SURVIVED. Two things, and they are the session's real output. `real - adp` was ALREADY
paired on (season, seed) and clustered on season, exactly as `transform - ffa_baseline` is --
B14's premise that it was not is false, verified against the committed artifacts to 1e-6. And
the null control stays null under the adjustment in all 54 market x policy x covariate cells,
which is G4 -- though `bot` is safe by correlation (max |rho| 0.548, below break-even) rather
than by construction, so that pass does not rescue the method.
"""

from __future__ import annotations

import math
import statistics as st
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import seat

# Nothing may report an adjusted interval as a result. `report()` enforces it; this constant
# exists so the reason is greppable from the call site.
NOT_FOR_REPORTING: str = (
    "the adjusted interval covers E[Y | W = Wbar], not the season mean E[Y] that every gate "
    "in this repo reads. Measured coverage of a nominal 95% interval falls from 0.950 at "
    "rho 0 to 0.904 at the break-even threshold and 0.42 at rho 0.98. It is anti-conservative "
    "exactly where it looks most useful. See sim/runs/b14-variance.md."
)

# The covariates B14 measured. `ceiling_minus_adp` is the pre-registered primary --
# `sim/runs/b14-plan.md`, committed before any adjusted interval existed. The other two are
# reported beside it and are NOT promotable after the fact; `covariate_table` refuses an
# unknown name rather than defaulting, because a silent default is how a covariate gets
# chosen after the answer is known.
PRIMARY: str = "ceiling_minus_adp"
COVARIATES: tuple[str, ...] = (PRIMARY, "adp_level", "season_points")


def break_even_rho(k: int) -> float:
    """|rho| above which the adjusted interval is narrower, AT THIS NUMBER OF CLUSTERS.

    IT IS NOT A CONSTANT AND B14 SHIPPED IT AS ONE. The first version hardcoded 0.655, the
    k = 5 value, and applied it at every k -- which an adversarial review broke at k = 4,
    where the true threshold is 0.797 and a comparison at rho 0.790 was marked as clearing
    while coming out 1.5% WIDER. That is the identical error the pre-registration made
    (0.489, derived from the t quantiles alone), relocated one level up. Reachable in this
    repo: `b4-transform` is a four-season run and the walk-forward splits are two and three.

    The derivation, with one regressor and an intercept on k season means:

        s_e^2  = s_Y^2 * (1 - rho^2) * (k - 1) / (k - 2)
        ratio  = t(k-2)/t(k-1) * sqrt((1 - rho^2) * (k - 1) / (k - 2))

    and the threshold is where that ratio is 1. Measured against a bisection of the actual
    crossing on constructed data: 0.65511765 at k = 5, against 0.655118 from this formula.

        k        4      5      6      7     10
        |rho|  .797   .655   .560   .495   .380
    """
    if k < 4:
        # Below four clusters a slope leaves fewer than two residual degrees of freedom and
        # no correlation is high enough to pay for it.
        return 1.0
    c = seat._t95(k - 2) / seat._t95(k - 1) * math.sqrt((k - 1) / (k - 2))
    if c <= 1.0:
        return 0.0
    return math.sqrt(1.0 - 1.0 / c**2)


@dataclass(frozen=True)
class Adjusted:
    """One comparison, both ways, with everything a reader needs to disbelieve it.

    `lo`/`hi` are the repo's own clustered interval for the season mean. `adj_lo`/`adj_hi` are
    the conditional interval and are A DIFFERENT ESTIMAND -- see `NOT_FOR_REPORTING`. They are
    carried together deliberately: B14's G8 requires the pair, and an adjusted interval that
    could be printed alone is the failure mode this whole module documents.
    """

    n: int
    clusters: int
    mean: float
    lo: float
    hi: float
    adj_lo: float
    adj_hi: float
    beta: float
    beta_se: float
    rho: float
    rho_lo: float
    rho_hi: float
    # THE SHARE OF SEASON VARIANCE THE COVARIATE LEAVES BEHIND. Named for what it holds: the
    # first version called this `variance_reduction` and stored `1 - rho^2`, so a covariate
    # that removed 96.6% of the variance reported 0.034 and a useless one reported 1.000.
    # A field whose name is the inverse of its contents is a defect and this one was mine.
    variance_retained: float
    width_ratio: float
    clears_break_even: bool

    def resolvable(self) -> bool:
        return self.lo > 0.0 or self.hi < 0.0

    def adj_resolvable(self) -> bool:
        """Whether the CONDITIONAL interval excludes zero. Not a claim about the season mean."""
        return self.adj_lo > 0.0 or self.adj_hi < 0.0


def season_means(values: Mapping[tuple[int, int], float]) -> dict[int, float]:
    """Collapse (season, seed) keyed values onto season means, sorted by season."""
    grouped: dict[int, list[float]] = {}
    for (season, _seed), value in values.items():
        grouped.setdefault(season, []).append(value)
    return {s: st.mean(v) for s, v in sorted(grouped.items())}


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) < 3:
        return float("nan")
    mx, my = st.mean(xs), st.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0.0 or sy == 0.0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def _fisher(rho: float, k: int) -> tuple[float, float]:
    """A 95% interval for rho itself. At k = 5 the standard error is 1/sqrt(2) = 0.707.

    Checked rather than assumed: measured coverage at k = 5 is 0.952 / 0.954 / 0.957 at rho
    0.0 / 0.5 / 0.9 over 200k replications, so the normal approximation is slightly
    CONSERVATIVE here. It is the one part of B14 an adversarial review could not break.
    """
    if k < 4 or not -1.0 < rho < 1.0:
        return (-1.0, 1.0)
    z = math.atanh(rho)
    half = 1.96 / math.sqrt(k - 3)
    return (math.tanh(z - half), math.tanh(z + half))


def adjust(
    per_unit: Mapping[tuple[int, int], float],
    covariate: Mapping[int, float],
) -> Adjusted | None:
    """Both intervals for one comparison. None when there is nothing to compute.

    A COVARIATE THAT IS THE RESPONSE IS REFUSED. `PRIMARY` is `ceiling_minus_adp`, which is
    also one of `runner._COMPARISONS` -- `hindsight_board - adp`. Adjusting that comparison by
    that covariate is a regression of a response on itself: the first version returned
    rho = 1.000 and a ZERO-WIDTH 95% interval, in all three markets, and nothing refused it.
    An adversarial review found it by looking. The guard is on the residual, not on the name,
    so it catches any covariate that is collinear with the response however it was built.
    """
    if not per_unit:
        return None
    ys = season_means(per_unit)
    seasons = sorted(ys)
    k = len(seasons)
    values = list(per_unit.values())
    clusters = [key[0] for key in per_unit]
    mean, lo, hi = seat.mean_and_interval(values, clusters)
    if k < 4 or any(s not in covariate for s in seasons):
        return Adjusted(
            n=len(values), clusters=k, mean=mean, lo=lo, hi=hi, adj_lo=lo, adj_hi=hi,
            beta=0.0, beta_se=float("nan"), rho=float("nan"), rho_lo=-1.0, rho_hi=1.0,
            variance_retained=1.0, width_ratio=1.0, clears_break_even=False,
        )

    y = [ys[s] for s in seasons]
    w = [covariate[s] for s in seasons]
    my, mw = st.mean(y), st.mean(w)
    sww = sum((x - mw) ** 2 for x in w)
    rho = _pearson(w, y)
    beta = (
        sum((x - mw) * (v - my) for x, v in zip(w, y, strict=True)) / sww if sww > 0 else 0.0
    )
    residual = [v - my - beta * (x - mw) for v, x in zip(y, w, strict=True)]
    dof = k - 2
    sse = sum(r * r for r in residual)
    syy = sum((v - my) ** 2 for v in y)
    if syy > 0 and sse / syy < 1e-12:
        raise ValueError(
            "the covariate explains the response to machine precision, so it IS the response "
            "or a linear function of it. That produces a zero-width interval rather than a "
            f"narrow one. rho={rho:.6f}. Check the covariate against runner._COMPARISONS: "
            f"{PRIMARY} is itself the comparison `hindsight_board - adp`."
        )
    s_e = math.sqrt(sse / dof) if dof > 0 else float("inf")
    beta_se = math.sqrt(sse / dof / sww) if dof > 0 and sww > 0 else float("nan")

    # `alpha_hat` IS `Ybar`, because the covariate is centred. That is why the point estimate
    # cannot move and why B14's G6 is satisfied by construction.
    grand = st.mean(y)
    half = seat._t95(dof) * s_e / math.sqrt(k)
    unadjusted_half = (hi - lo) / 2.0
    return Adjusted(
        n=len(values),
        clusters=k,
        mean=grand,
        lo=lo,
        hi=hi,
        adj_lo=grand - half,
        adj_hi=grand + half,
        beta=beta,
        beta_se=beta_se,
        rho=rho,
        rho_lo=_fisher(rho, k)[0],
        rho_hi=_fisher(rho, k)[1],
        variance_retained=1.0 - rho * rho,
        width_ratio=(half / unadjusted_half) if unadjusted_half > 0 else float("inf"),
        clears_break_even=abs(rho) > break_even_rho(k),
    )


def report(result: Adjusted) -> str:
    """The ONLY sanctioned way to render an adjusted interval: never alone, never unlabelled.

    B14's G8 says no adjusted interval may appear without its unadjusted counterpart. This
    goes further because the measurement demands it -- the adjusted interval is not an
    interval for the reported estimand at all, so it is rendered with the coverage warning
    attached and the word "conditional" in the line.
    """
    lines = [
        f"  {result.mean:+9.2f}",
        f"    reported  [{result.lo:+9.2f},{result.hi:+9.2f}]"
        f"{'  resolvable' if result.resolvable() else ''}",
        f"    conditional (NOT the reported estimand) "
        f"[{result.adj_lo:+9.2f},{result.adj_hi:+9.2f}]  width x{result.width_ratio:.2f}",
        f"    rho {result.rho:+.3f} [{result.rho_lo:+.2f},{result.rho_hi:+.2f}]  "
        f"variance retained {result.variance_retained:.3f}  "
        f"beta {result.beta:+.4f} (se {result.beta_se:.4f})",
        f"    {NOT_FOR_REPORTING}",
    ]
    return "\n".join(lines)


def covariate_table(rows: Sequence[Mapping[str, Any]], name: str) -> dict[int, float]:
    """One season-level covariate, by name. An unknown name is refused, not defaulted.

    `ceiling_minus_adp` is how much value the season had available to be found -- the
    labelled-leak ceiling's advantage less the skill baseline's. `adp_level` is the baseline
    alone. `season_points` is the mean points-for over every arm and seed, which is the
    season's scoring level and knows nothing about any arm's ordering.

    ALL THREE ARE BUILT FROM `advantage`, the PRIOR lineup policy, whatever policy the caller
    is adjusting. That is a real limitation and it is stated rather than hidden: a covariate
    for an oracle-lineup comparison is still the prior-lineup season shock.
    """
    if name not in COVARIATES:
        raise ValueError(f"unknown covariate {name!r}; expected one of {list(COVARIATES)}")

    def arm_means(arm: str) -> dict[int, float]:
        return season_means(
            {(r["season"], r["seed"]): r["advantage"] for r in rows if r["arm"] == arm}
        )

    if name == "season_points":
        grouped: dict[int, list[float]] = {}
        for row in rows:
            grouped.setdefault(row["season"], []).append(row["points_for"])
        return {s: st.mean(v) for s, v in sorted(grouped.items())}

    adp = arm_means("adp")
    if name == "adp_level":
        return adp
    ceiling = arm_means("hindsight_board")
    return {s: ceiling[s] - adp[s] for s in sorted(adp) if s in ceiling}


def paired(
    rows: Sequence[Mapping[str, Any]],
    left: str,
    right: str | None,
    field: str = "advantage",
) -> dict[tuple[int, int], float]:
    """Per-unit values for a comparison, or for a single arm when *right* is None.

    Pairing is on (season, seed), which is what `runner._paired_difference` already does.
    B14's handoff supposed `real - adp` was NOT paired that way and it is: verified against
    the committed artifacts in all three markets, 300 units each, no orphans, to 1e-6.

    `r[field]` raises where `_paired_difference` uses `.get(field, 0.0)`. That divergence is
    deliberate. On a checkpoint with a gap, production would quietly report a zero difference
    and this raises -- and an analysis that silently treats a missing unit as a tie is worse
    than one that stops.
    """
    a = {(r["season"], r["seed"]): r[field] for r in rows if r["arm"] == left}
    if right is None:
        return a
    b = {(r["season"], r["seed"]): r[field] for r in rows if r["arm"] == right}
    return {k: a[k] - b[k] for k in sorted(a.keys() & b.keys())}


def between_arm_rho(
    rows: Sequence[Mapping[str, Any]], left: str, right: str, field: str = "advantage"
) -> float:
    """Correlation between the two arms' PER-UNIT scores. G3's evidence that pairing did work.

    A paired difference narrows things only to the extent the two series move together. Near
    zero means the arms are not sharing conditions in any useful sense and the pairing is
    bookkeeping.
    """
    a = {(r["season"], r["seed"]): r[field] for r in rows if r["arm"] == left}
    b = {(r["season"], r["seed"]): r[field] for r in rows if r["arm"] == right}
    keys = sorted(a.keys() & b.keys())
    if len(keys) < 3:
        return float("nan")
    return _pearson([a[k] for k in keys], [b[k] for k in keys])
