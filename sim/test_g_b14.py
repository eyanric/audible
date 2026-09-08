"""GATES for B14, which are gates AGAINST adopting B14's estimator rather than for it.

B14 set out to reduce between-season variance with a control variate. It did not work, and
these gates pin why so that a later session cannot re-adopt it by writing the same reasoning
again. `sim/adjust.py` is wired to nothing; this file is the reason it is kept at all.

THE DECIDING GATE IS `test_the_adjusted_interval_does_not_cover_the_reported_estimand`. The
adjusted interval is exact for `E[Y | W = Wbar]` and the repo reports `E[Y]`, the season mean.
Measured coverage of a nominal 95% interval falls monotonically in `|rho|` -- 0.950 at 0,
0.904 at the break-even threshold, 0.42 at 0.98 -- so it is most anti-conservative exactly
where the adoption rule says to adopt. That gate asserts the failure rather than the fix,
because the failure is the finding.

TWO THINGS B14 GOT RIGHT AND THEY ARE THE SESSION'S OUTPUT.

`real - adp` WAS ALREADY PAIRED on (season, seed) and clustered on season, exactly as
`transform - ffa_baseline` is. B14's handoff says it "spans zero because it is not paired that
way" and that is false; both go through `runner._compare` -> `_paired_difference`.
`test_the_headline_comparisons_are_already_paired` pins it, and pins the real explanation:
`adp` carries almost no season shock to cancel, so the paired difference is essentially
`real`'s own variance.

THE CONTROL VARIATE CANNOT WORK AT ALL, and not because the correlation is weak. It needs
`E[W]` known a priori and there is no sixth season. So B14's failure injection 3 -- "fix beta
at a large wrong value, the point estimate moves and G6 fires" -- CANNOT FIRE, and a G6 pass
is arithmetic rather than evidence. `test_i3_no_beta_can_move_the_point_estimate` says so.

WHAT THESE GATES CAUGHT WHEN THEY DID NOT EXIST. An adversarial review mutated `adjust()` to
return the unadjusted interval always, and mutated `covariate_table` to return one table for
every name. Both passed all eleven of the first version's gates, because every arithmetic
assertion read `width_ratio` and nothing tied it to `adj_hi - adj_lo`, and nothing ever
compared two named covariates. Both are closed below.
"""

from __future__ import annotations

import json
import math
import random
import statistics as st
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "sim" / "runs"

pytestmark = pytest.mark.slow

# The committed market-board checkpoints. Used rather than B13's production-board ones because
# these are IN THE REPO -- a gate needing a 15MB artifact regenerated before it runs is a gate
# that gets skipped. Every property asserted here is a property of the arithmetic.
MARKETS = (("b10-ffc", "ffc_12"), ("b10-mfl12", "mfl_12"), ("b10-mfl8", "mfl_8"))


def _units(name: str) -> list[dict]:
    path = RUNS / f"{name}.checkpoint.jsonl"
    if not path.exists():
        pytest.skip(f"{path} is not committed")
    out = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except Exception:
                continue
            unit = row.get("unit")
            if unit and unit.get("split", "main") == "main":
                out.append(unit)
    return out


@pytest.fixture(scope="module")
def mods():
    from . import adjust, runner, seat

    return adjust, runner, seat


@pytest.fixture(scope="module")
def rows():
    return {label: _units(name) for name, label in MARKETS}


# --- THE DECIDING GATE ------------------------------------------------------------------


def test_the_adjusted_interval_does_not_cover_the_reported_estimand(mods) -> None:
    """WHY B14 SHIPS NOTHING. Asserting the failure, because the failure is the result.

    `Ybar - E[Y] = beta * (Wbar - E[W]) + ebar`, and the adjusted half-width prices only
    `ebar`. `Wbar` is not `E[W]` for exactly the reason the classical control variate is
    unavailable here: five seasons and no sixth. So the interval is exact for
    `E[Y | W = Wbar]`, a quantity that moves with the sample, and anti-conservative for the
    season mean every gate in this repo reads.

    Two adversarial reviews measured this independently at 60k and 100k replications. This
    runs a smaller version and requires the SHAPE -- coverage at a strong covariate must be
    materially below nominal, and materially below coverage at a useless one. If this gate
    ever fails, either the estimator changed or the arithmetic above is wrong, and either way
    `sim/runs/b14-variance.md` needs rewriting before anything is adopted.
    """
    adjust, _runner, _seat = mods
    rng = random.Random(20240614)
    k, reps = 5, 4000
    seasons = [2021 + i for i in range(k)]

    def coverage(beta_true: float) -> float:
        hits = 0
        for _ in range(reps):
            w = [rng.gauss(0.0, 1.0) for _ in range(k)]
            y = [beta_true * x + rng.gauss(0.0, 10.0) for x in w]
            per_unit = {(s, 0): v for s, v in zip(seasons, y, strict=True)}
            covariate = dict(zip(seasons, w, strict=True))
            got = adjust.adjust(per_unit, covariate)
            # The TRUE marginal mean is 0.0: E[Y] = beta * E[W] = 0.
            if got.adj_lo <= 0.0 <= got.adj_hi:
                hits += 1
        return hits / reps

    useless = coverage(0.0)
    strong = coverage(50.0)
    assert 0.93 <= useless <= 0.97, (
        f"with a zero-information covariate the adjusted interval should be at nominal "
        f"coverage and measured {useless:.3f}. If this moved, the estimator changed."
    )
    assert strong < 0.75, (
        f"the adjusted interval covered the season mean {strong:.3f} of the time with a "
        f"strong covariate. B14's whole finding is that this number collapses -- if it no "
        f"longer does, the refutation in sim/adjust.py and sim/runs/b14-variance.md is "
        f"wrong and the estimator may be usable after all. Do not adopt it on this test "
        f"alone; re-run the full coverage sweep first."
    )
    assert strong < useless - 0.15, (strong, useless)


def test_selecting_on_the_correlation_manufactures_significance(mods) -> None:
    """The second layer, and it fires on a covariate carrying NO information at all.

    `rho` is estimated from the same five points as the interval, so adopting on
    `|rho| > break_even` is selecting on the statistic. Against a pure-noise covariate the
    gate clears often enough to matter, and CONDITIONAL ON CLEARING the interval is both
    narrower and worse-covering. That is manufactured significance, which is the exact failure
    B14's own Task 3 named as worse than wide intervals.
    """
    adjust, _runner, _seat = mods
    rng = random.Random(99)
    k, reps = 5, 6000
    seasons = [2021 + i for i in range(k)]
    adopted, adopted_hits, ratios = 0, 0, []
    for _ in range(reps):
        y = [rng.gauss(0.0, 10.0) for _ in range(k)]
        w = [rng.gauss(0.0, 1.0) for _ in range(k)]
        got = adjust.adjust(
            {(s, 0): v for s, v in zip(seasons, y, strict=True)},
            dict(zip(seasons, w, strict=True)),
        )
        if got.clears_break_even:
            adopted += 1
            ratios.append(got.width_ratio)
            if got.adj_lo <= 0.0 <= got.adj_hi:
                adopted_hits += 1

    rate = adopted / reps
    assert 0.15 < rate < 0.32, (
        f"a covariate with no information clears the adoption gate {rate:.3f} of the time. "
        f"That figure is the point of this test; if it changed, break_even_rho changed."
    )
    conditional = adopted_hits / adopted
    assert conditional < 0.93, (
        f"conditional on clearing the gate, a noise covariate's interval covered "
        f"{conditional:.3f} against a nominal 0.95. If this is no longer below nominal, the "
        f"selection problem has gone away and the decision rule could be revisited."
    )
    assert st.median(ratios) < 1.0, st.median(ratios)


# --- the two things B14 got right --------------------------------------------------------


def test_the_headline_comparisons_are_already_paired(mods, rows) -> None:
    """B14's premise was that `real - adp` is not paired the way `transform - ffa_baseline` is.

    It is. Both reach the artifact through `runner._compare`, which pairs on (season, seed)
    and clusters on season. Recomputed independently and required to match.
    """
    adjust, runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        for left, right in (("real", "adp"), ("audible_transform", "ffa_baseline")):
            block = runner._compare(got, left, right)
            assert block is not None, f"{label} {left}-{right} did not pair"
            per_unit = adjust.paired(got, left, right)
            assert block["n"] == len(per_unit), (
                f"{label} {left}-{right}: `_compare` paired {block['n']} units and an "
                f"independent (season, seed) join found {len(per_unit)}."
            )
            assert block["mean"] == pytest.approx(st.mean(per_unit.values()), abs=1e-3)
            assert block["clusters"] == 5


def test_why_one_resolves_and_the_other_does_not(mods, rows) -> None:
    """The mechanism, on the third attempt, with the first two recorded as refuted.

    B14 said "the season shock cancels because the two arms share a board". An adversarial
    review refuted that: in ffc_12 both comparisons have nearly the same between-season share
    and the separation is effect size, and under an oracle lineup in mfl_8 the ordering
    reverses. A second attempt here -- "pairing needs COMPARABLE season-level spread" -- was
    refuted by this gate on its first run, 0.961 against 0.974 in ffc_12, the wrong way round.

    WHAT SURVIVES IS THE DIRECT MEASUREMENT, which needed no theory: how much the paired
    difference's season spread beats two independent arms', `sd(diff) / sqrt(sdL^2 + sdR^2)`.

        b10 market board          real - adp    transform - ffa_baseline
          ffc_12                    1.12x              0.24x
          mfl_12                    0.98x              0.36x
          mfl_8                     0.84x              0.26x
        b13 production board
          ffc_12                    1.03x              0.24x
          mfl_12                    0.90x              0.36x
          mfl_8                     0.95x              0.26x

    Pairing removes about three quarters of the season spread from `transform -
    ffa_baseline` and NOTHING from `real - adp` -- in ffc_12 it makes it worse. Six cells, no
    overlap. The per-unit between-arm correlation says the same thing: +0.63 to +0.69 against
    +0.32 to +0.44.

    That is the answer to B14's common-random-numbers premise. The two arms ALREADY run on
    common random numbers; the seeds are shared and the room is the same. What they do not
    share is CONDITIONS -- `seat.run_arm`'s docstring measures the room diverging after the
    first differing pick -- and `real` is the full stack against a ten-line baseline, so there
    is very little common variation left in the difference for pairing to cancel.
    """
    adjust, _runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]

        def benefit(unit_rows, left: str, right: str) -> float:
            spread = {
                arm: st.stdev(
                    adjust.season_means(adjust.paired(unit_rows, arm, None)).values()
                )
                for arm in (left, right)
            }
            paired_sd = st.stdev(
                adjust.season_means(adjust.paired(unit_rows, left, right)).values()
            )
            return paired_sd / math.sqrt(spread[left] ** 2 + spread[right] ** 2)

        tight = benefit(got, "audible_transform", "ffa_baseline")
        loose = benefit(got, "real", "adp")
        assert tight < 0.5, (
            f"{label}: pairing removes only {1 - tight:.0%} of the season spread from "
            f"transform - ffa_baseline, and the claim in this docstring is that it removes "
            f"about three quarters"
        )
        assert loose > 0.75, (
            f"{label}: pairing removes {1 - loose:.0%} of the season spread from real - adp. "
            f"The claim is that it removes essentially none; if pairing has started working "
            f"here, B14's premise deserves another look."
        )


# --- the arithmetic ----------------------------------------------------------------------


def test_the_break_even_depends_on_the_number_of_clusters(mods) -> None:
    """It is NOT a constant, and B14 shipped it as one until a review broke it at k = 4.

    The first version hardcoded the k = 5 value, 0.655, and applied it at every k. At k = 4
    the true threshold is 0.797, so a comparison at rho 0.790 was marked as clearing while
    coming out wider -- the identical error the pre-registration made at 0.489, one level up.
    Reachable: `b4-transform` is four seasons and the walk-forward splits are two and three.
    """
    adjust, _runner, seat = mods
    expected = {4: 0.797, 5: 0.655, 6: 0.560, 7: 0.495, 10: 0.380}
    for k, want in expected.items():
        assert pytest.approx(want, abs=2e-3) == adjust.break_even_rho(k), k
    assert adjust.break_even_rho(3) == 1.0, "below four clusters nothing can pay for a slope"
    # And it must be derived, not stored: recompute from the quantiles.
    for k in (4, 5, 6, 7, 10):
        c = seat._t95(k - 2) / seat._t95(k - 1) * math.sqrt((k - 1) / (k - 2))
        assert pytest.approx(math.sqrt(1.0 - 1.0 / c**2), abs=1e-9) == adjust.break_even_rho(k)


def test_the_width_ratio_is_the_interval_it_describes(mods, rows) -> None:
    """CLOSES THE MUTATION THAT PASSED. `adj_lo = lo, adj_hi = hi` was green on all 11 gates.

    Every arithmetic assertion in the first version read `width_ratio`, which is computed from
    the residual spread independently of the two fields a reader actually looks at. Nothing
    tied them together, so an `adjust()` that never adjusted anything was indistinguishable.
    """
    adjust, _runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        covariate = adjust.covariate_table(got, adjust.PRIMARY)
        checked = 0
        for left, right in (("real", "adp"), ("real", "audible_transform"),
                            ("audible_transform", "ffa_baseline"), ("bot", None)):
            result = adjust.adjust(adjust.paired(got, left, right), covariate)
            width = result.adj_hi - result.adj_lo
            assert width == pytest.approx(
                (result.hi - result.lo) * result.width_ratio, rel=1e-9
            ), f"{label} {left}-{right}: width_ratio does not describe adj_lo/adj_hi"
            assert result.adj_lo + result.adj_hi == pytest.approx(2.0 * result.mean, abs=1e-9)
            if abs(result.width_ratio - 1.0) > 1e-9:
                checked += 1
        assert checked, f"{label}: nothing was actually adjusted, so this proved nothing"


def test_two_named_covariates_are_two_different_tables(mods, rows) -> None:
    """CLOSES THE SECOND MUTATION THAT PASSED: one table returned for every name.

    `covariate_table` raises on an unknown name, which is the guard B14 wrote to stop a
    covariate being chosen after the answer was known. The guard was tested and the payload
    was not, so a version ignoring `name` entirely was green.
    """
    adjust, _runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        tables = {n: adjust.covariate_table(got, n) for n in adjust.COVARIATES}
        seen = list(tables.values())
        for i in range(len(seen)):
            for j in range(i + 1, len(seen)):
                assert seen[i] != seen[j], (
                    f"{label}: two named covariates returned identical tables, so the name is "
                    f"being ignored and the pre-registration constrains nothing"
                )


def test_a_covariate_that_is_the_response_is_refused(mods, rows) -> None:
    """`PRIMARY` is `ceiling_minus_adp`, which IS `runner._COMPARISONS`' `hindsight_board - adp`.

    Adjusting that comparison by that covariate is a regression of a response on itself. The
    first version returned rho = 1.000 and a ZERO-WIDTH 95% interval in all three markets and
    nothing refused it. The guard is on the residual rather than the name, so it catches any
    collinear covariate however it was constructed.
    """
    adjust, _runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        covariate = adjust.covariate_table(got, adjust.PRIMARY)
        with pytest.raises(ValueError, match="machine precision"):
            adjust.adjust(adjust.paired(got, "hindsight_board", "adp"), covariate)


def test_an_unknown_covariate_is_refused(mods, rows) -> None:
    """A silent default is how a covariate gets chosen after the answer is known."""
    adjust, _runner, _seat = mods
    with pytest.raises(ValueError, match="unknown covariate"):
        adjust.covariate_table(rows["ffc_12"], "whatever_narrows_it")


def test_reporting_an_adjusted_interval_carries_its_warning(mods, rows) -> None:
    """G8, enforced in code rather than in a review comment.

    The adjusted interval is not an interval for the reported estimand, so `report()` renders
    it with the unadjusted pair and the coverage warning attached. A caller that wants to
    print one alone has to go around the only public renderer.
    """
    adjust, _runner, _seat = mods
    got = rows["ffc_12"]
    covariate = adjust.covariate_table(got, adjust.PRIMARY)
    text = adjust.report(adjust.adjust(adjust.paired(got, "real", "adp"), covariate))
    assert "reported" in text and "conditional" in text
    assert "NOT the reported estimand" in text
    assert adjust.NOT_FOR_REPORTING in text


# --- the injections ----------------------------------------------------------------------


def test_i1_a_pure_noise_covariate_narrows_nothing(mods, rows) -> None:
    """INJECTION 1. The narrowing must come from correlation, not from the machinery.

    Over many noise draws rather than one: with five seasons a noise covariate clears the
    threshold about a fifth of the time by chance, so a single draw proves nothing. What must
    hold is that noise does not narrow ON AVERAGE. The conditional-on-adoption subset, which
    is the one that would ever be reported, is covered by
    `test_selecting_on_the_correlation_manufactures_significance` -- this test alone was the
    hole that let the selection problem through.
    """
    adjust, _runner, _seat = mods
    got = rows["ffc_12"]
    per_unit = adjust.paired(got, "real", "adp")
    seasons = sorted({s for s, _ in per_unit})
    rng = random.Random(7)
    ratios = [
        adjust.adjust(per_unit, {s: rng.gauss(0.0, 1.0) for s in seasons}).width_ratio
        for _ in range(400)
    ]
    assert st.median(ratios) > 1.0, st.median(ratios)
    assert st.mean(ratios) > 1.0, st.mean(ratios)


def test_i2_the_null_control_stays_null_under_adjustment(mods, rows) -> None:
    """INJECTION 2 and G4. Exhaustive over market x lineup policy x covariate.

    `bot` is `simulate_draft` with no chooser: eight seats running identical code, so its
    advantage is zero by symmetry. `mfl_12` is already resolvable unadjusted at +22.0 -- the
    long-standing G6a failure diagnosed in `sim/runs/b9-classifier.md`, byte-identical across
    b8, b9, b10 and b13 -- so the claim that can indict the estimator is that it makes `bot`
    resolvable ANYWHERE IT WAS NOT.

    IT PASSES BY CORRELATION, NOT BY CONSTRUCTION, and that is why it does not rescue the
    method. `bot`'s |rho| never exceeds 0.548 in any of these cells, below break-even, so the
    adjustment only ever widens it. A null control whose covariate happened to correlate would
    not be protected by anything here.
    """
    adjust, _runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        for policy in ("advantage", "advantage_season_mean", "advantage_realised"):
            for name in adjust.COVARIATES:
                covariate = adjust.covariate_table(got, name)
                result = adjust.adjust(adjust.paired(got, "bot", None, policy), covariate)
                if not result.resolvable():
                    assert not result.adj_resolvable(), (
                        f"{label}/{policy}/{name}: `bot` is null at "
                        f"[{result.lo:.2f}, {result.hi:.2f}] and the adjustment made it "
                        f"RESOLVABLE at [{result.adj_lo:.2f}, {result.adj_hi:.2f}]."
                    )
                assert abs(result.rho) < adjust.break_even_rho(result.clusters), (
                    f"{label}/{policy}/{name}: the null control's covariate correlates at "
                    f"{result.rho:+.3f}, above break-even. G4 has been passing because `bot` "
                    f"is uncorrelated, not because the estimator protects it."
                )


def test_i3_no_beta_can_move_the_point_estimate(mods, rows) -> None:
    """INJECTION 3, WHICH CANNOT FIRE. That is the finding, not a failure.

    B14 asked for a wrong beta to move the point estimate and trip G6. The covariate is
    centred on its own sample mean, so `beta * (Wbar - Wbar)` is zero for every beta. The
    injection describes the classical control variate against a KNOWN `E[W]`, which is
    precisely the estimator this session established is unavailable. Demonstrated for three
    betas including a deliberately absurd one.
    """
    adjust, _runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        covariate = adjust.covariate_table(got, adjust.PRIMARY)
        seasons = sorted(covariate)
        centre = st.mean(covariate[s] for s in seasons)
        for left, right in (("real", "adp"), ("real", "audible_transform"), ("bot", None)):
            per_unit = adjust.paired(got, left, right)
            result = adjust.adjust(per_unit, covariate)
            unadjusted = st.mean(adjust.season_means(per_unit).values())
            assert result.mean == pytest.approx(unadjusted, abs=1e-12), f"{label} {left}"
            by_season = adjust.season_means(per_unit)
            for wrong_beta in (0.0, 50.0, -1000.0):
                forced = st.mean(
                    by_season[s] - wrong_beta * (covariate[s] - centre) for s in seasons
                )
                assert forced == pytest.approx(unadjusted, abs=1e-9), (
                    f"{label} {left}-{right}: beta={wrong_beta} moved the point estimate. "
                    f"That would mean the covariate is not centred, and the whole G6 argument "
                    f"depends on it being centred."
                )


def test_i4_unpairing_the_real_comparison_widens_it(mods, rows) -> None:
    """INJECTION 4. Pairing must be doing something, or Task 2 claims a benefit it has not.

    Measured on `real - adp`: the paired interval against the difference of two independently
    clustered intervals. The gap is MODEST -- pairing is real and small here, which is itself
    the answer to why this comparison does not resolve.
    """
    adjust, _runner, seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        per_unit = adjust.paired(got, "real", "adp")
        _m, lo, hi = seat.mean_and_interval(
            list(per_unit.values()), [k[0] for k in per_unit]
        )
        left = [r["advantage"] for r in got if r["arm"] == "real"]
        right = [r["advantage"] for r in got if r["arm"] == "adp"]
        clusters = [r["season"] for r in got if r["arm"] == "real"]
        _, l_lo, l_hi = seat.mean_and_interval(left, clusters)
        _, r_lo, r_hi = seat.mean_and_interval(right, clusters)
        assert (hi - lo) < ((l_hi - r_lo) - (l_lo - r_hi)), (
            f"{label}: the paired interval is not narrower than the unpaired one, so pairing "
            f"is bookkeeping and the arms are not sharing conditions at all"
        )


def test_i5_a_shuffle_that_reads_the_real_board_collapses_the_leak_gate(mods, rows) -> None:
    """INJECTION 5. `real - shuffle` must go to zero when the shuffle stops shuffling.

    `leaky-shuffle` is that arm and it is never reported. Simulated at the estimator level by
    comparing `real` against itself, which is what a shuffle reading the real board reduces
    to. Both intervals must be exactly zero: an estimator that put a spread on a degenerate
    comparison would hide the collapse G6b exists to catch.
    """
    adjust, _runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        covariate = adjust.covariate_table(got, adjust.PRIMARY)
        result = adjust.adjust(adjust.paired(got, "real", "real"), covariate)
        assert result.mean == pytest.approx(0.0, abs=1e-9), result.mean
        assert result.lo == pytest.approx(0.0, abs=1e-9)
        assert result.hi == pytest.approx(0.0, abs=1e-9)
        assert result.adj_lo == pytest.approx(0.0, abs=1e-9), (
            f"{label}: a degenerate comparison acquired a spread of "
            f"[{result.adj_lo}, {result.adj_hi}]"
        )
        assert result.adj_hi == pytest.approx(0.0, abs=1e-9)


def test_g5_the_leak_ceiling_is_untouched_by_the_adjustment(mods, rows) -> None:
    """G5. `runner.leak_ceiling_failures` reads POINT ESTIMATES, which the adjustment fixes.

    Worth asserting rather than stating: every gate reading a `mean` is provably unaffected.
    The three that read `lo`/`hi` -- G6a's null control, G6b's real-beats-shuffle, and the
    unclustered shuffle-at-chance check -- are the ones a reader has to think about, and they
    are listed in `sim/runs/b14-variance.md`. Since nothing imports `adjust`, none of them is
    reading an adjusted number today.
    """
    adjust, runner, _seat = mods
    for _name, label in MARKETS:
        got = rows[label]
        covariate = adjust.covariate_table(got, adjust.PRIMARY)
        block = runner._compare(got, "real", "adp")
        result = adjust.adjust(adjust.paired(got, "real", "adp"), covariate)
        assert block["mean"] == pytest.approx(result.mean, abs=1e-3), label
