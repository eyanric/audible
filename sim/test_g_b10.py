"""GATES for B10: the leak detector, the board/room scale mismatch, and the fitted statistics.

THREE FINDINGS, each measured and each gated here so it cannot quietly stop being true.

ONE. `mfl_8_std`'s leak detector is SIGNAL, not power. `real - shuffle` is +68.2 with a
clustered half-width of 96.5, and no seed count closes that: the interval is built from the
FIVE SEASON MEANS and nothing else, so seeds only shrink the within-season term. Decomposed,
86.7% of mfl_8's width is between-season against 27.2% of ffc's, and the asymptotic half-width
is 89.8 against a mean of 68.2. The gate is not adjusted; the market is reported as one whose
leak detector cannot resolve.

TWO. The board/room SCALE MISMATCH is real, it is directional, and it is present in
`ffc_12_std` -- the market every headline number this project has published came from. The room
is always fitted from `espn_draft_6012`, which is EIGHT-team, while FFC and MFL-12 serve
TWELVE-team boards. `mu` absorbs the mean offset almost exactly but cannot absorb the SCALE,
because the coherent rank-to-pick map is multiplicative and `mu` is additive. The residue lands
in the left tail -- the FIRST player at a position -- and is measured below.

THREE. Three of the six pre-registered statistics are FITTED, and `STAT_KIND` has said so since
B1: "the fit targets this quantity directly. Only the held-out run says anything." The
in-sample verdict was nonetheless built from all six. B10 moved the fitted ones out of the
in-sample verdict and gated them on the held-out grid instead, which is where the module's own
doctrine says they mean something.

WHAT THIS FILE DOES NOT CLAIM. It does not claim any market is trustworthy. `ffc_12_std` is the
only one whose room passes B1, and it carries the scale bias in TWO. `mfl_8_std` has a
resolvable-nothing leak detector. `mfl_12_std` has both problems.
"""

from __future__ import annotations

import math
import statistics as st
from pathlib import Path

import pytest

from . import artifact, markets, room, runner, weekly
from . import seat as seatmod

REPO = Path(__file__).resolve().parents[1]
MARKETS = tuple(sorted(markets.REGISTRY))
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776}

# MEASURED, SEEDS=50, five seasons. The real 6012 first-QB pick is 27, 26, 22, 35, 25 -- mean
# 27.0. A twelve-team board ranks quarterbacks for a room that competes for them twelve ways,
# and this room is eight. The bias is what that costs, in picks.
FIRST_QB_BIAS: dict[str, float] = {
    "ffc_12_std": -5.76,
    "mfl_12_std": -7.01,
    # The only market whose board and room team counts agree, and the only one that reproduces
    # the real first quarterback. This row is the control that makes the other two legible.
    "mfl_8_std": -0.64,
}


# --- ONE: the leak detector is signal ---------------------------------------------------------


def _decompose(d: dict) -> dict:
    """Split a reported comparison into between-season and within-season variance.

    `seat.mean_and_interval` is an ANALYTIC CLUSTERED t INTERVAL, not a bootstrap -- it takes
    the five season means, their sample sd, divides by sqrt(5) and multiplies by t(4)=2.776.
    (Calling it a bootstrap is a conflation with `weekly.bootstrap_weeks`, which resamples a
    player's observed weeks and is a different object entirely.) Every artifact also records
    the UNCLUSTERED interval as `flat_lo`/`flat_hi`, which is enough to solve for both
    components without re-running anything:

        sd_total   from the flat interval over all n units
        sd_means   from the clustered interval over k season means
        Var(season mean) = tau^2 + sigma_w^2 / seeds
        sd_total^2       = tau^2 + sigma_w^2
    """
    # REFUSED, NOT CRASHED, on a shape this arithmetic does not apply to. `artifact._clean`
    # writes an unresolvable bound as the STRING "inf", a single-cluster run legitimately
    # produces one, and `T95` only carries 1-4 df. Every other reader in the repo guards this;
    # an earlier version of this helper did not and raised TypeError, KeyError or
    # ZeroDivisionError on three legal artifact shapes.
    n, k = d["n"], d["clusters"]
    if not all(isinstance(d[key], int | float) for key in ("lo", "hi", "flat_lo", "flat_hi")):
        pytest.skip("interval is unresolvable (one season-cluster); nothing to decompose")
    if k - 1 not in T95 or k < 2 or n < 2 * k:
        pytest.skip(f"cannot decompose {k} clusters over {n} units")
    seeds = n / k
    sd_total = (d["flat_hi"] - d["flat_lo"]) / 2.0 / 1.96 * math.sqrt(n)
    sd_means = (d["hi"] - d["lo"]) / 2.0 / T95[k - 1] * math.sqrt(k)
    tau_sq = (sd_means**2 - sd_total**2 / seeds) / (1.0 - 1.0 / seeds)
    tau = math.sqrt(max(0.0, tau_sq))
    return {
        "mean": d["mean"], "tau": tau,
        "sigma_w": math.sqrt(max(0.0, sd_total**2 - tau**2)),
        "half_now": (d["hi"] - d["lo"]) / 2.0,
        "half_inf": T95[k - 1] * tau / math.sqrt(k),
    }


@pytest.mark.parametrize(
    "run,resolvable",
    [("b9-ffc", True), ("b9-mfl12", True), ("b9-mfl8", False)],
)
def test_g1_which_markets_leak_detector_can_ever_resolve(run, resolvable) -> None:
    """G1. Whether `real - shuffle` can EVER exclude zero, at any seed count.

    This is the question the handoff asked as "power or signal", answered analytically so it
    does not depend on how far a seed sweep happened to be run. If the asymptotic half-width
    exceeds the point estimate, no number of seeds resolves the gate, and the market's arm
    numbers have to be read with that attached.
    """
    path = REPO / "sim" / "runs" / f"{run}.json"
    if not path.exists():
        pytest.skip(f"{run}.json has not been produced")
    dd = _decompose(artifact.read(path)["real_minus_shuffle"])
    can = abs(dd["mean"]) > dd["half_inf"]
    assert can is resolvable, (
        f"{run}: mean {dd['mean']:+.1f}, asymptotic half-width {dd['half_inf']:.1f}, "
        f"tau {dd['tau']:.1f}. Resolvable-in-the-limit reads {can}, recorded {resolvable}."
    )


def test_g1_seeds_cannot_fix_mfl8_and_the_arithmetic_says_why() -> None:
    """The mechanism, not just the verdict: the width is between-season and seeds do not touch it.

    MEASURED, by running the arms at four seed counts (the artifacts are in the scratchpad,
    not committed -- they are 300 to 2400 units each and say one thing):

        seeds  60  +68.16 [-28.29, +164.61]  half 96.45
        seeds 120  +70.72 [-27.24, +168.67]  half 97.95
        seeds 240  +67.30 [-33.87, +168.48]  half 101.17
        seeds 480  +66.02 [-33.88, +165.93]  half 99.91

    Eight times the seeds and the half-width does not shrink. It sits 5-10% ABOVE the
    decomposition's own prediction (93.2 / 91.5 / 90.7 at 120 / 240 / 480) rather than
    converging down to it, which is what a `tau` estimated from five points looks like when it
    is re-estimated on a different seed draw. Both readings agree on the only thing that
    matters here: the shortfall is about 22 points and at most about 7 are available from
    seeds at any count.
    """
    path = REPO / "sim" / "runs" / "b9-mfl8.json"
    if not path.exists():
        pytest.skip("b9-mfl8.json has not been produced")
    dd = _decompose(artifact.read(path)["real_minus_shuffle"])
    available = dd["half_now"] - dd["half_inf"]
    needed = dd["half_now"] - abs(dd["mean"])
    assert needed > available, (
        f"seeds now buy {available:.1f} of half-width and {needed:.1f} is needed; the sweep "
        f"would resolve this and the SIGNAL verdict is wrong"
    )
    # And the between-season share is what makes that true.
    share = dd["tau"] ** 2 / (dd["tau"] ** 2 + dd["sigma_w"] ** 2)
    assert share > 0.05, f"between-season share is only {share:.1%}"


def test_g1_ffc_resolves_for_a_reason_that_is_not_effect_size() -> None:
    """ffc_12 resolves and mfl_8 does not, and the difference is NOT how big the effect is.

    Means are +97.3 and +68.2, a factor of 1.43. Between-season sds are 16.4 and 72.5, a factor
    of 4.4. Stating it this way stops the result being read as "the real board works better on
    FFC", which is not what the measurement says.

    THE MARGIN HERE IS DELIBERATELY LOOSE. `tau` is a sample sd on FIVE points, so its own
    sampling distribution is very wide -- a chi interval on 4 df spans roughly 0.6x to 2.9x the
    estimate -- and adversarial review measured that a tighter form of this assertion
    (`noise > 2 * effect`) flips on a reseed slightly more often than not. What is robust is
    the ORDERING, not the ratio, so that is what is asserted.
    """
    ffc = _decompose(artifact.read(REPO / "sim" / "runs" / "b9-ffc.json")["real_minus_shuffle"])
    mfl8 = _decompose(artifact.read(REPO / "sim" / "runs" / "b9-mfl8.json")["real_minus_shuffle"])
    assert abs(ffc["mean"]) > abs(mfl8["mean"]), "the effect is not larger on ffc"
    assert mfl8["tau"] > ffc["tau"], "the between-season sd is not larger on mfl_8"
    # And the noise gap has to be the bigger of the two, or the explanation is wrong.
    assert mfl8["tau"] / ffc["tau"] > abs(ffc["mean"]) / abs(mfl8["mean"]), (
        f"between-season sd ratio {mfl8['tau'] / ffc['tau']:.2f} no longer exceeds the effect "
        f"ratio {abs(ffc['mean']) / abs(mfl8['mean']):.2f}"
    )


# --- INJECTION 1: the gate on the leak detector itself, in every market -----------------------


@pytest.mark.parametrize("market", MARKETS)
def test_i1_a_shuffle_arm_reading_the_real_board_collapses_the_detector(market, tmp_path) -> None:
    """INJECTION 1. `leaky-shuffle` is the shuffle arm with the shuffle removed.

    `real - shuffle` must then be exactly zero, which is the signature G6b exists to catch. An
    equivalent test existed in `sim/test_g_runner.py` but ran on ONE market and ONE season --
    the default, which is FFC. A leak detector that has only ever been checked in the market
    whose detector works is not much of a check, and mfl_8's is the one under suspicion.
    """
    with markets.use(market):
        fit = room.fit_room()
        board = room.load_board(2024)
        week = weekly.weekly_points(2024)
        config = weekly.league_config()
        paired = []
        for seed in range(4):
            kw = dict(
                season_board=board, fit=fit, week_table=week, config=config,
                state_dir=tmp_path, seat=6,
            )
            a = seatmod.run_arm("real", 2024, seed, **kw).advantage
            b = seatmod.run_arm("leaky-shuffle", 2024, seed, **kw).advantage
            paired.append(a - b)
    assert all(abs(d) < 1e-9 for d in paired), (
        f"{market}: a shuffle arm reading the real board differed from it by {paired}; the "
        f"injection did not fire, so G6b would not catch a leak in this market"
    )


# --- TWO: the board/room scale mismatch --------------------------------------------------------


@pytest.mark.parametrize("market", MARKETS)
def test_g2_the_first_quarterback_bias_is_recorded_per_market(market) -> None:
    """G2. How early each market's room takes the first quarterback, in PICKS.

    THE ROUND STATISTIC HIDES THIS. `first QB round` buckets by eight, so a six-pick error is
    most of a round and still lands inside a five-season min/max of [3, 5]. ffc_12_std passes
    that gate at +1.2 sem -- inside the module's own marginal band -- while releasing the first
    quarterback 5.8 picks early. Measuring the PICK rather than the round is what makes the
    artifact visible at all.

    WHAT CAUSES IT IS NOT SETTLED, and an earlier version of this docstring asserted that it
    was. The attractive story -- the room is always fitted from `espn_draft_6012`, which is
    eight-team, while FFC and MFL-12 serve twelve-team boards, so the coherent rank-to-pick map
    is multiplicative while `mu` is additive -- is REFUTED three ways by measurement:

      * The first KICKER is 4.6 to 7.3 picks early in ALL THREE markets, the matched control
        included. K is a SCHEDULED position: `Fit.expected_pick` returns `pick_mu["K"]` and
        never reads a rank, so there is no rank-to-pick map for it to get wrong -- and
        `pick_mu`/`pick_sd` reproduce the real kicker mean and sd exactly. A first-of-position
        bias of the same size therefore arises with a perfectly fitted location, a perfectly
        fitted scale, and no scale map at all.
      * The measured slope of pick on rank does not track team count: 0.886 on FFC's
        twelve-team board against 0.741 on MFL's eight-team one. The twelve-team board is the
        CLOSER to 1.0, which is backwards.
      * Rescaling ranks by 8/12 and refitting moves the matched control by +5.4 picks, about as
        much as it moves the two mismatched markets. A transform that does the same thing to
        the control is not correcting what makes the control different.

    What the evidence does support is that a first-of-position statistic is a MINIMUM over
    roughly a dozen draws, so it reads the left tail and a larger `sigma` pulls it earlier --
    halving `sigma["QB"]` moves ffc_12_std's bias from -5.4 to -1.4, which is a bigger lever
    than anything else tested. The bias is real and is recorded; the explanation is open.
    """
    identity = room.espn_identity()
    real = st.mean(
        min(p.overall for p in room.load_real_draft(s, identity) if p.position == "QB")
        for s in room.SEASONS
    )
    with markets.use(market):
        fit = room.fit_room()
        boards = {s: room.load_board(s) for s in room.SEASONS}
        firsts = [
            min(
                (p.overall for p in room.simulate_draft(boards[s], fit, seed)
                 if p.position == "QB"),
                default=float("nan"),
            )
            for s in room.SEASONS
            for seed in range(20)
        ]
    bias = st.mean(firsts) - real
    expected = FIRST_QB_BIAS[market]
    assert abs(bias - expected) <= 2.0, (
        f"{market}: first-QB bias is {bias:+.2f} picks, recorded {expected:+.2f}"
    )


def test_g2_only_the_matched_market_reproduces_the_first_quarterback() -> None:
    """The shape of the finding, so it cannot be read as noise.

    Both twelve-team-board markets are early by MORE THAN FOUR PICKS on the quarterback. The
    one eight-team board is within two. That ordering is the claim.

    IT IS A QB-ONLY ORDERING, and that is the part that keeps the team-count explanation from
    working. The first KICKER is early by 4.6, 7.3 and 7.3 picks in the three markets -- the
    matched control is the WORST -- and the first tight end is worst on the control too. Only
    the quarterback orders the way a board/room team-count story predicts, which is why this
    test asserts the quarterback ordering and the docstring above refuses to explain it.
    """
    matched = FIRST_QB_BIAS["mfl_8_std"]
    mismatched = [FIRST_QB_BIAS["ffc_12_std"], FIRST_QB_BIAS["mfl_12_std"]]
    assert abs(matched) < 2.0, matched
    assert all(b < -4.0 for b in mismatched), mismatched


def test_g2_the_mismatch_is_not_a_reason_to_retire_a_market() -> None:
    """ffc_12 and mfl_12 are the SAME construct, so the argument cannot single one out.

    Every market declares the same league, the room is always eight-team, and both twelve-team
    boards get the same treatment. Whatever is said about mfl_12's coherence has to be said
    about ffc_12, which is the market every published number came from. This asserts the
    structural identity so nobody retires one and keeps the other.
    """
    for name in MARKETS:
        assert markets.get(name).league == "espn_davis_drive"
    assert room.TEAMS == 8 and room.LEAGUE_ID == "6012"
    twelve = {"ffc_12_std", "mfl_12_std"}
    assert twelve <= set(MARKETS)
    # Same construct: the only difference between them is which ADP source ranks the players.
    assert markets.get("ffc_12_std").source != markets.get("mfl_12_std").source


# --- THREE: fitted statistics are gated where they mean something -----------------------------


def test_g3_four_of_the_six_statistics_are_fitted_not_three() -> None:
    """G3. The battery has less independent evidence in it than it has ever claimed.

    `first_qb_round` was labelled `free` -- "the fit targets nothing resembling it" -- and B10
    measured that `mu["QB"]` IS the mean of (real QB pick - board rank), reproduced to the last
    digit. The next test proves the identity rather than asserting the label.

    So four of six are fitted and only `kdef_in_128` (semi) and `runs_3plus` (free) are
    untargeted. That is the honest size of the evidence, and it is why B10 did NOT act on the
    handoff's dichotomy: there is no clean subset of untuned statistics to fall back to, and
    de-gating the fitted ones was measured to let a room with a one-round-wrong specialist
    schedule pass B1 on ffc_12_std.
    """
    fitted = {name for name, kind in room.STAT_KIND.items() if kind == "fitted"}
    assert fitted == {
        "first_qb_round", "first_k_round", "first_def_round", "delta_spread"
    }, fitted
    untargeted = {name for name, kind in room.STAT_KIND.items() if kind != "fitted"}
    assert untargeted == {"kdef_in_128", "runs_3plus"}, untargeted
    assert len(room.Stats.__slots__) == 6


@pytest.mark.parametrize("market", MARKETS)
def test_g3_mu_qb_is_exactly_the_statistic_it_was_called_free_of(market) -> None:
    """The measurement behind the relabel: `mu["QB"]` IS the fitted QB delta, to the last digit."""
    identity = room.espn_identity()
    with markets.use(market):
        fit = room.fit_room()
        nicks = room.nick_to_abbr()
        deltas = []
        for season in room.SEASONS:
            index = room.load_board(season).by_key()
            for pick in room.load_real_draft(season, identity):
                if pick.position != "QB":
                    continue
                hit = index.get(room.pick_join_key(pick, nicks))
                if hit is not None:
                    deltas.append(float(pick.overall - hit.rank))
    assert deltas, f"{market}: no joined quarterbacks"
    assert abs(fit.mu["QB"] - st.mean(deltas)) < 1e-9, (
        f"{market}: mu[QB]={fit.mu['QB']:.6f} against a measured {st.mean(deltas):.6f}; the "
        f"`fitted` relabel rests on these being the same number"
    )


def test_g3_every_statistic_is_still_gated_in_sample() -> None:
    """B10 tried to de-gate the fitted statistics and REVERTED. This is the regression guard.

    Adversarial review measured a room whose K and D/ST schedule is a full round wrong and
    showed the de-gated battery passed it on ffc_12_std -- the market every published number
    comes from. So all six still decide the verdict, and the honest finding is the relabel
    above rather than a smaller battery.
    """
    assert not hasattr(room, "HELD_OUT_MIN_COVER"), (
        "the held-out fitted gate is back; it was reverted because its bar was derived from a "
        "90% nominal coverage the band does not deliver (0.69 at 12 seeds, 0.88 at 50)"
    )
    # Behavioural rather than textual: every statistic must be able to set the verdict, so a
    # room that fails ONE of them must not resemble real.
    with markets.use("mfl_8_std"):
        _lines, ok = room.report(seeds=12)
    assert ok is False, (
        "mfl_8_std passes B1 again. Its only in-sample failure is the fitted pick-ADP spread, "
        "so this passing means the fitted statistics have stopped deciding the verdict -- the "
        "change B10 reverted because it let a one-round-wrong specialist schedule through."
    )


def test_g3_the_held_out_band_does_not_deliver_its_nominal_coverage() -> None:
    """Why B10 did NOT gate the fitted statistics on held-out coverage.

    A bar was derived from Binomial(5, 0.9) on the premise that the synthetic 5-95 percentile
    band covers 90%. It does not. `_pct` indexes at `round(q*(n-1))`, so for a fresh continuous
    draw the band covers (i95 - i5)/(n+1), which is 0.692 at 12 seeds and 0.882 at 50 -- never
    0.90. This asserts the index arithmetic so the premise cannot quietly come back.
    """
    for seeds, want in ((12, 0.70), (50, 0.90)):
        i5 = min(seeds - 1, max(0, round(0.05 * (seeds - 1))))
        i95 = min(seeds - 1, max(0, round(0.95 * (seeds - 1))))
        coverage = (i95 - i5) / (seeds + 1)
        assert coverage < want, (seeds, coverage)
    # And the discrete statistics are conservative rather than 90%, in the other direction, so
    # there is no single p to put in a binomial at all.
    with markets.use("ffc_12_std"):
        fit = room.fit_room()
        board = room.load_board(2024)
        syn = [room.sim_stats(room.simulate_draft(board, fit, seed)) for seed in range(25)]
    distinct = len({s.kdef_in_128 for s in syn})
    assert distinct <= 4, (
        f"K+DEF in 128 now takes {distinct} distinct synthetic values; it was 2-3, which is "
        f"what made its band conservative"
    )


# --- G13: every split's room structure is gated ------------------------------------------------


@pytest.mark.parametrize("run", ["b10-ffc", "b10-mfl12", "b10-mfl8"])
def test_g13_every_split_fit_is_in_the_artifact_and_gated(run) -> None:
    """G13. The walk-forward split's room was never checked, only measured.

    audible#75 recorded the walk-forward structure as ungated and noted it agreed on all three
    markets. An agreement that nothing checks is not a gate: a split whose classifier drifted
    would produce walk-forward numbers that looked ordinary.
    """
    path = REPO / "sim" / "runs" / f"{run}.json"
    if not path.exists():
        pytest.skip(f"{run}.json has not been produced")
    payload = artifact.read(path)
    splits = payload.get("split_fits") or {}
    assert set(splits) >= {"main"}, sorted(splits)
    labels = {s["label"] for s in payload["splits"]}
    assert set(splits) == labels, (sorted(splits), sorted(labels))
    for label, block in splits.items():
        assert set(block["scheduled"]) == set(room.expected_scheduled()), (label, block)


def test_i13_a_drifted_split_fit_fires_g7() -> None:
    """INJECTION. A walk-forward split whose structure drifts must turn the run red."""
    path = REPO / "sim" / "runs" / "b9-ffc.json"
    if not path.exists():
        pytest.skip("no artifact to build on")
    payload = artifact.read(path)
    payload["split_fits"] = {
        "main": {"seasons": [2021], "scheduled": ["DEF", "K"], "clock_ratio": {}},
        "wf-in": {
            "seasons": [2021, 2022, 2023],
            "scheduled": ["DEF", "K", "WR"],
            "clock_ratio": {"WR": 0.9},
        },
    }
    failures = runner.gate_failures(payload)
    assert any("wf-in" in f and f.startswith("G7") for f in failures), failures


# --- regressions on audible#75 -----------------------------------------------------------------


@pytest.mark.parametrize("market", MARKETS)
def test_g4_the_classifier_still_derives_the_leagues_scheduled_set(market) -> None:
    """G4. Regression on audible#75's headline."""
    with markets.use(market):
        assert set(room.fit_room().scheduled) == set(room.expected_scheduled())


def test_g5_the_sample_floor_bracket_still_holds() -> None:
    """G5. The bracket, narrowed by B10 to (14, 20] because the walk-forward window is now gated.

    B9 measured (14, 27] on the pooled and leave-one-out windows. Gating every split's room
    structure made the three-season walk-forward window a checked code path, and its thinnest
    cell -- FFC's kicker at n=20 -- is seven lower than leave-one-out's. A floor of 20 therefore
    sat exactly on the binding edge; 17 is the centre of the real bracket.
    """
    assert 14 < room.MIN_CLOCK_N <= 20, room.MIN_CLOCK_N
    windows = {
        "pooled": tuple(room.SEASONS),
        "walk-forward": (2021, 2022, 2023),
        "hold-2021": (2022, 2023, 2024, 2025),
    }
    original = room.MIN_CLOCK_N
    try:
        for floor in (15, 17, 20):
            room.MIN_CLOCK_N = floor
            for market in MARKETS:
                with markets.use(market):
                    expected = set(room.expected_scheduled())
                    for label, window in windows.items():
                        got = set(room.fit_room(window).scheduled)
                        assert got == expected, (floor, market, label, sorted(got))
    finally:
        room.MIN_CLOCK_N = original


def test_g5_the_walk_forward_window_is_what_narrowed_the_bracket() -> None:
    """The measurement behind the bracket, so the constant can be re-derived rather than trusted.

    FFC's walk-forward kicker is the tightest cell in any window the code fits. If it moves, the
    bracket moves, and `MIN_CLOCK_N` has to be re-centred rather than left where it is.
    """
    thinnest = {}
    for market in MARKETS:
        with markets.use(market):
            thinnest[market] = min(room.fit_room((2021, 2022, 2023)).clock_n.values())
    assert min(thinnest.values()) == 20, thinnest
    assert min(thinnest.values()) > room.MIN_CLOCK_N, (
        f"the floor {room.MIN_CLOCK_N} is at or above the thinnest walk-forward cell "
        f"{min(thinnest.values())}, so a gated split would go unclassified"
    )


def test_i3_the_old_floor_still_reproduces_the_b8_catastrophe() -> None:
    """INJECTION 3. `MIN_CLOCK_N = 10` must still schedule the n=12 quarterback."""
    original = room.MIN_CLOCK_N
    try:
        room.MIN_CLOCK_N = 10
        hits = []
        for market in MARKETS:
            with markets.use(market):
                for season in room.SEASONS:
                    if "QB" in room.fit_room((season,)).scheduled:
                        hits.append(f"{market}:{season}")
    finally:
        room.MIN_CLOCK_N = original
    assert hits, "a floor of 10 no longer schedules the quarterback anywhere"


@pytest.mark.parametrize("market", MARKETS)
def test_g7_assert_pre_draft_guards_every_board(market) -> None:
    """G7 in the handoff's numbering: leakage, every market, every season."""
    with markets.use(market):
        for season in room.SEASONS:
            room.assert_pre_draft(room.load_board(season))


def test_i2_the_retired_supply_ratio_still_misclassifies_mfl8() -> None:
    """INJECTION 2. Restoring the supply ratio must still schedule RB and WR on mfl_8_std."""
    with markets.use("mfl_8_std"):
        fit = room.fit_room()
    would = {p for p, r in fit.supply_ratio.items() if r > room.SUPPLY_RATIO_CUT}
    assert {"RB", "WR"} <= would, sorted(would)


@pytest.mark.parametrize("market", MARKETS)
def test_g8_a_draft_is_reproducible_from_its_seed(market) -> None:
    """G8. Determinism, per market."""
    with markets.use(market):
        fit = room.fit_room()
        board = room.load_board(2024)
        a = room.draft_digest(room.simulate_draft(board, fit, 11))
        b = room.draft_digest(room.simulate_draft(board, fit, 11))
    assert a == b


def test_the_interval_is_an_analytic_clustered_t_not_a_bootstrap() -> None:
    """A wrong name is a defect. Several reports have called this a bootstrap; it is not.

    `mean_and_interval` takes the five season means, their sample sd, and a t quantile. Nothing
    resamples. The word belongs to `weekly.bootstrap_weeks`, which resamples a player's observed
    weeks and is a different object. This asserts the arithmetic so the name can be checked.
    """
    values = [1.0, 2.0, 3.0, 4.0, 10.0, 20.0]
    clusters = ["a", "a", "b", "b", "c", "c"]
    mean, lo, hi = seatmod.mean_and_interval(values, clusters)
    means = [1.5, 3.5, 15.0]
    want = st.mean(means)
    half = T95[2] * st.stdev(means) / math.sqrt(3)
    assert abs(mean - want) < 1e-9
    assert abs((hi - lo) / 2 - half) < 1e-9, ((hi - lo) / 2, half)


def test_i1_the_leak_detector_gate_itself_fires_end_to_end(tmp_path) -> None:
    """INJECTION 1, END TO END. The arm-level check above is not the gate.

    `test_i1_a_shuffle_arm_reading_the_real_board_collapses_the_detector` proves the ARM reads
    the real board. It does not prove `runner.gate_failures` then emits G6b, and those are
    different claims -- the arm could collapse while the gate silently read some other key. So
    this splices `leaky-shuffle` rows in under the name `shuffle` and runs the real gate.

    TWO SEASONS, NOT ONE, and that is load-bearing: with a single cluster
    `seat.mean_and_interval` returns (mean, -inf, +inf) and G6b fires down its UNRESOLVABLE
    branch with a different message, which would make this pass for the wrong reason.

    It cannot be done through `sim run`: `preflight` refuses a config without a `shuffle` arm,
    and `build_payload` computes `real_minus_shuffle` from the arm literally named `shuffle`,
    so adding `leaky-shuffle` to a config just produces an extra unreported arm.
    """
    seasons = (2023, 2024)
    with markets.use("ffc_12_std"):
        fit = room.fit_room()
        config = weekly.league_config()
        rows: list[dict] = []
        for season in seasons:
            board = room.load_board(season)
            week = weekly.weekly_points(season)
            for seed in range(3):
                kw = dict(
                    season_board=board, fit=fit, week_table=week, config=config,
                    state_dir=tmp_path, seat=6,
                )
                for arm, label in (("real", "real"), ("leaky-shuffle", "shuffle")):
                    res = seatmod.run_arm(arm, season, seed, **kw)
                    rows.append(
                        {"split": "main", "arm": label, "season": season, "seed": seed,
                         "advantage": res.advantage}
                    )
    diff, keys = runner._paired_difference(rows, "real", "shuffle")
    assert diff, "no paired rows; the splice did not line up"
    assert all(abs(v) < 1e-9 for v in diff), sorted(diff)[:4]

    payload = artifact.read(REPO / "sim" / "runs" / "b9-ffc.json")
    seasons_of = [k[0] for k in keys]
    mean, lo, hi = seatmod.mean_and_interval(diff, seasons_of)
    payload["real_minus_shuffle"] = {
        "mean": mean, "lo": lo, "hi": hi, "n": len(diff), "clusters": len(set(seasons_of)),
        "flat_lo": lo, "flat_hi": hi,
    }
    failures = runner.gate_failures(payload)
    g6b = [f for f in failures if f.startswith("G6b")]
    assert g6b, f"a shuffle arm reading the real board did not fire G6b: {failures}"
    assert "unresolvable" not in g6b[0], (
        f"G6b fired down its single-cluster branch rather than on the collapsed difference: "
        f"{g6b[0]}"
    )
