"""GATES G1-G9 for B3, plus the five failure injections.

B3 is DIAGNOSTIC. It does not tune anything and it does not sweep; it splits B2's negative
result into the three stories that could explain it, and every gate here is about whether the
split is trustworthy rather than about whether any number is good.

WHAT THESE GATES CAN AND CANNOT SAY, stated up front because one of them is load-bearing and
easy to misread. `test_g5_the_harness_board_is_the_adp_list` asserts a property of the
HARNESS, not of audible: in this simulation audible's board order and the market's order are
the same list, so `real - adp` measures the OVERLAY and never the board. That is not a defect
being papered over -- it is the honest consequence of having no vintage projections -- but it
does mean no gate here can say anything about audible's value layer.

The heavy gates run small sweeps. The statistical numbers come from `sim/runs/b3-diagnose.json`,
which is committed; gates that read a number read it from there rather than re-deriving it at a
sample size too small to mean anything. That file being absent turns NINE of the 23 gates in this
file into skips and the suite still exits 0 -- measured, not estimated. It is named here rather
than left to be discovered, and `test_the_artifact_producers_are_actually_executed` is the one
gate in this file that runs the real pipeline and therefore cannot be silenced that way.
"""

from __future__ import annotations

import random
import statistics as st
from pathlib import Path

import pytest

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "sim" / "runs"
CONFIG = REPO / "sim" / "configs" / "b3-diagnose.toml"
ARTIFACT = RUNS / "b3-diagnose.json"


def _require(name: str) -> Path:
    for root in (SIM_CACHE, LIVE_CACHE):
        if (root / name).exists():
            return root / name
    pytest.skip(f"{name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}")


@pytest.fixture(scope="module")
def mods():
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    from . import artifact, room, runner, seat, weekly

    _require("nflverse/ff_playerids.parquet")
    for season in (2023, 2024):
        _require(f"ffc_adp_standard_8_{season}.json")
        _require(f"nflverse/player_stats_{season}.parquet")
    return room, runner, seat, weekly, artifact


@pytest.fixture(scope="module")
def committed(mods):
    _room, _runner, _seat, _weekly, artifact = mods
    if not ARTIFACT.exists():
        pytest.skip(f"{ARTIFACT} is not committed yet")
    return artifact.read(ARTIFACT)


@pytest.fixture(scope="module")
def one_season(mods):
    """A board, a fit and a week table for 2024, built once."""
    room, _runner, _seat, weekly, _artifact = mods
    return room.load_board(2024), room.fit_room(), weekly.weekly_points(2024)


@pytest.fixture(scope="module")
def prior_2024(mods):
    """The leave-one-out prior table for 2024: fitted on 2023 only, and that is the point.

    The runner fits it on all four other seasons. Here it is fitted on one, because the gates
    that use it pin only 2023 and 2024 and a gate must not need data it does not require. A
    thinner prior is a WEAKER expectation, so every ordering these gates assert -- prior below
    oracle below realised, tight-end share lower under the prior -- is asserted against the
    harder version of itself.
    """
    _room, runner, _seat, _weekly, _artifact = mods
    return runner._prior_for(2024, (2023, 2024), {}, {})


# --- G1: the ex-ante lineup is primary --------------------------------------------------------


def test_g1_the_ex_ante_lineup_never_sees_the_week_it_sets(mods, one_season) -> None:
    """The lineup must depend on expected points and NOT on the realised draw.

    Proven by changing the realised draw while holding the expectation fixed: the ASSIGNMENT
    must not move. Under the old realised-point lineup it moves on every draw, which is the
    whole artifact.
    """
    room, _runner, _seat, weekly, _artifact = mods
    board, fit, week = one_season
    picks = room.simulate_draft(board, fit, 0)
    roster, _ = weekly.resolve_roster(
        [p for p in picks if p.seat == 6], board, week
    )
    keys = [k for k, _pos in roster]

    # THE LINEUP MUST NOT MOVE WHEN THE REALISED DRAW MOVES. The previous version of this
    # called `optimal_week` twice with the SAME arguments and asserted the results matched,
    # which asserts only that the function is deterministic and cannot fail -- it caught none
    # of the three mutations aimed at the ex-ante wiring.
    expected = weekly.expected_points(week, keys)
    lineups = set()
    for stream in range(4):
        draws = weekly.bootstrap_weeks(random.Random(stream), week, keys)
        assert draws  # the draw really does differ per stream; see the control below
        lineups.add(tuple(weekly.optimal_week(roster, expected)[1]))
    assert len(lineups) == 1, (
        "the lineup chosen on expected points moved when the realised draw did; it is "
        "reading the outcome"
    )

    # And the realised lineup DOES move, which is what makes the ex-ante one a fix.
    draws = weekly.bootstrap_weeks(random.Random(1), week, keys)
    realised_lineups = {
        tuple(
            weekly.optimal_week(roster, {k: draws[k][i] for k in keys})[1]
        )
        for i in range(len(weekly.REG_WEEKS))
    }
    assert len(realised_lineups) > 1, (
        "the realised lineup never changed across 18 draws; the control is inert"
    )


def test_g1_ex_ante_scores_below_realised_and_the_gap_is_the_artifact(
    mods, one_season, prior_2024
) -> None:
    """Hindsight is worth points, and so is an oracle projection. Both must be, in order.

    THE ORDERING IS THE POINT, not any one number. The three policies differ only in how much
    they know about the season being scored -- the prior knows nothing, the season-mean knows
    each player's own final average, the realised knows the week -- so their totals must come
    out in that order. If they did not, `optimal_week` would not be optimising and the "upper
    bound" framing the artifact prints beside every comparison would be false.

    IN EXPECTATION, NOT ON ONE DRAW, and the first version of this gate got that wrong. The
    season-mean lineup is the argmax of the EXPECTED season total; it is scored on a single
    bootstrap draw, and on one draw some other lineup can beat it. It did: at (2024, seed 0)
    the prior lineup came out 2.4 points ahead of the oracle, which is noise and not a defect.
    Averaging over eight draws restores the property the artifact actually relies on, and the
    run-level gap is large -- the artifact reports the oracle worth +95 to +116 a season.
    """
    room, _runner, seat_mod, weekly, _artifact = mods
    board, fit, week = one_season
    ranks = seat_mod.positional_ranks(board, week)

    totals = {"prior": 0.0, "season-mean": 0.0, "realised": 0.0}
    draws = 8
    for seed in range(draws):
        picks = room.simulate_draft(board, fit, seed)
        roster, _ = weekly.resolve_roster([p for p in picks if p.seat == 6], board, week)
        table = weekly.prior_points(prior_2024, roster, ranks)
        for policy in totals:
            got, _slots = weekly.points_for(
                random.Random(seed), week, roster, lineup=policy, prior=table
            )
            totals[policy] += got / draws

    assert totals["prior"] < totals["season-mean"] < totals["realised"], (
        f"the three lineup policies did not come out in information order over {draws} "
        f"draws: {totals}"
    )


def test_g1_the_artifact_says_which_lineup_every_number_uses(committed) -> None:
    """The primary must name the PRIOR, and both upper bounds must be present and labelled.

    This asserted on the word "EX-ANTE", which the measure no longer uses -- and would not
    have caught the thing that mattered anyway. The failure mode is an artifact that prints
    one number and lets a reader assume it is the ex-ante one, so what is asserted here is
    that all three policies reach the artifact under their own names.
    """
    measure = committed["outcome_measure"].upper()
    assert "PRIOR" in measure and "LEAVE-ONE-SEASON-OUT" in measure, measure
    secondary = committed["secondary_measure"].lower()
    assert "oracle" in secondary and "hindsight" in secondary, secondary
    for name, block in committed["arms"].items():
        assert "realised_secondary" in block, f"arm {name} has no secondary"
        assert "SECONDARY" in block["realised_secondary"]["lineup"].upper()
    for key in ("real_minus_adp", "real_minus_shuffle"):
        for suffix in ("_oracle", "_hindsight"):
            assert f"{key}{suffix}" in committed, f"{key} has no {suffix} bound"


def test_i4_reverting_to_the_realised_lineup_restores_the_te_artifact(mods, tmp_path) -> None:
    """Failure injection 4. Proves Task 1 changed what it claims to have changed.

    Under a realised lineup the seat's tight-end edge over the field is several times what it
    is under the prior, because hindsight pays for hoarding: holding k tight ends buys
    E[max of k] for free once the week is already known.

    THREE THINGS THIS GATE GOT WRONG BEFORE, all of them the same mistake in different
    clothes -- measuring something that cannot show the effect and then passing anyway.

    1. It drafted with `room.simulate_draft`, an all-bot room with NO AUDIBLE SEAT IN IT.
       Nothing in that room hoards tight ends, so there was no artifact to detect. Measured
       on bot rosters the tight-end edge is -25 to +28 with no relation to the lineup policy.
    2. It divided tight-end points by the SEAT'S OWN TOTAL, which is dominated by the same
       players under either policy: 0.089 against 0.088, invisible. That is the denominator
       swap the `weekly` module docstring warns about, reproduced inside its own gate.
    3. Dividing by the ADVANTAGE instead is right in aggregate but explodes on a thin sample,
       where the advantage can land near zero (measured: a share of 430).

    So: the `real` arm, the tight-end edge OVER THE FIELD in points, on both pinned seasons.
    """
    room, runner, seat_mod, weekly, _artifact = mods
    config = weekly.league_config()
    fit = room.fit_room()
    seasons = (2023, 2024)
    boards = {season: room.load_board(season) for season in seasons}
    weeks = {season: weekly.weekly_points(season) for season in seasons}

    def tight_end(who, stream, mode, board, week, prior, ranks) -> float:
        """The points a roster's tight ends actually STARTED for, under one lineup policy.

        By POSITION. A surplus tight end started at FLEX is booked to the FLEX slot, so the
        by-slot TE row cannot see the hoarding this gate exists to detect.
        """
        roster, _ = weekly.resolve_roster(who, board, week)
        table = weekly.prior_points(prior, roster, ranks)
        _total, slots = weekly.points_for(
            random.Random(stream), week, roster, lineup=mode, prior=table
        )
        return slots.get("pos:TE", 0.0)

    edge = {"prior": 0.0, "realised": 0.0}
    units = len(seasons) * 4
    for season in seasons:
        board, week = boards[season], weeks[season]
        prior = runner._prior_for(season, seasons, boards, weeks)
        ranks = seat_mod.positional_ranks(board, week)
        for seed in range(4):
            picks = seat_mod.run_arm(
                "real", season, seed, season_board=board, fit=fit, week_table=week,
                config=config, state_dir=tmp_path, seat=6, prior=prior,
            ).picks
            by_seat: dict[int, list] = {}
            for pick in picks:
                by_seat.setdefault(pick.seat, []).append(pick)

            for mode in edge:
                got = [
                    tight_end(
                        by_seat[who], seed * 1_000_003 + who, mode,
                        board, week, prior, ranks,
                    )
                    for who in sorted(by_seat)
                ]
                mine = got[sorted(by_seat).index(6)]
                others = [v for i, v in enumerate(got) if sorted(by_seat)[i] != 6]
                edge[mode] += (mine - sum(others) / len(others)) / units

    assert edge["realised"] > 2.0 * edge["prior"], (
        f"the tight-end edge did not collapse when hindsight was removed: prior "
        f"{edge['prior']:+.1f}, realised {edge['realised']:+.1f} points over the field"
    )


# --- G2: per-slot decomposition ---------------------------------------------------------------


def test_g2_every_arm_carries_a_per_slot_decomposition(committed) -> None:
    """The tight-end result hid for a whole session because nothing broke it down.

    BY SLOT IS NOT ENOUGH, and asserting only on slots was the hole. RB and WR each name two
    starting slots, and a surplus tight end started at FLEX is booked to FLEX -- so the by-slot
    TE row understates tight-end hoarding by exactly the amount that made it worth hoarding.
    Both decompositions must be present, and the by-position one is what the summary prints.
    """
    slot_names = {"QB", "RB", "WR", "TE", "FLEX", "DEF", "K"}
    for name, block in committed["arms"].items():
        slots = block.get("slot_points")
        assert slots, f"arm {name} has no slot_points"
        assert sum(slots.values()) > 0, f"arm {name} scored nothing in any slot"
        by_slot = {k for k in slots if not k.startswith("pos:")}
        by_position = {k[4:] for k in slots if k.startswith("pos:")}
        assert by_slot <= slot_names, sorted(by_slot)
        assert by_position, f"arm {name} has no by-position rows"
        assert by_position <= {"QB", "RB", "WR", "TE", "DEF", "K"}, sorted(by_position)
        # The two views must agree on the total: every point lands in exactly one slot and in
        # exactly one position, so a mismatch means one of the two is dropping rows.
        slot_total = sum(v for k, v in slots.items() if not k.startswith("pos:"))
        position_total = sum(v for k, v in slots.items() if k.startswith("pos:"))
        assert abs(slot_total - position_total) < 0.5, (
            f"arm {name}: by-slot {slot_total:.1f} != by-position {position_total:.1f}"
        )


# --- G3: the legacy arm ------------------------------------------------------------------------


def test_g3_the_legacy_arm_is_reported_and_distinct(committed) -> None:
    assert "legacy" in committed["arms"]
    assert "real_minus_legacy" in committed
    # `legacy` is `the_call`'s pre-#61 form. The pre-#60 `recommend` sort is a DIFFERENT
    # surface and rides in its own arm; asserting the wrong one here is how the two got
    # conflated, and the comparison inverted sign once they were separated.
    assert "pre-audible#61" in committed["arms"]["legacy"]["definition"]
    assert "legacy_recommend" in committed["arms"]
    assert "pre-audible#60" in committed["arms"]["legacy_recommend"]["definition"]
    assert "surface_gap" in committed


def test_g3_the_legacy_sort_is_the_historical_tuple(mods, one_season, tmp_path) -> None:
    """It must be the pre-#60 key, and the third term must be provably dead.

    `vorp_rank` is a unique, gapless integer (`board.py` assigns it by `enumerate` over a
    total order with a `player_id` tiebreak), so `not fills_need` placed after it is never
    compared. That is the defect the arm exists to reproduce, and asserting it here is what
    stops someone "fixing" the arm into something that is not the historical ordering.
    """
    room, _runner, seat_mod, weekly, _artifact = mods
    board, fit, week = one_season
    config = weekly.league_config()
    audible = seat_mod.board_from_season(board, config)
    ranks = [e.vorp_rank for e in audible.entries]
    assert len(set(ranks)) == len(ranks), "vorp_rank is not unique; the legacy key is not dead"

    holder = seat_mod.build_seat(
        board, config, week.byes, tmp_path, seat=6, mode="legacy"
    )
    assert holder.mode == "legacy"


def test_i1_a_legacy_arm_aliased_to_real_collapses_the_difference(
    mods, one_season, tmp_path
) -> None:
    """Failure injection 1. Proves the arm is a distinct ordering, not a mislabelled `real`."""
    room, _runner, seat_mod, weekly, _artifact = mods
    board, fit, week = one_season
    config = weekly.league_config()

    real = [
        seat_mod.run_arm(
            "real", 2024, seed, season_board=board, fit=fit, week_table=week,
            config=config, state_dir=tmp_path, seat=6,
        ).advantage
        for seed in range(4)
    ]
    legacy = [
        seat_mod.run_arm(
            "legacy", 2024, seed, season_board=board, fit=fit, week_table=week,
            config=config, state_dir=tmp_path, seat=6,
        ).advantage
        for seed in range(4)
    ]
    real_again = [
        seat_mod.run_arm(
            "real", 2024, seed, season_board=board, fit=fit, week_table=week,
            config=config, state_dir=tmp_path, seat=6,
        ).advantage
        for seed in range(4)
    ]
    aliased = [a - b for a, b in zip(real, real_again, strict=True)]
    genuine = [a - b for a, b in zip(real, legacy, strict=True)]
    assert all(abs(d) < 1e-9 for d in aliased), (
        "real against itself did not collapse to zero; the injection cannot fire"
    )
    assert any(abs(d) > 1e-9 for d in genuine), (
        f"legacy is indistinguishable from real on every seed ({genuine}); it is an alias"
    )


# --- G4: the ablations ------------------------------------------------------------------------


def test_g4_every_ablation_is_reported_with_a_verdict(committed, mods) -> None:
    _room, _runner, seat_mod, _weekly, _artifact = mods
    _runner_mod = _runner
    ablations = committed.get("ablations") or {}
    assert set(ablations) == set(seat_mod.ABLATIONS), sorted(ablations)
    for name, block in ablations.items():
        assert "n" in block and block["n"] > 0
        # The verdict must be the one `_ablation_verdict` derives from this block's own
        # numbers, not merely a non-empty string. A fabricated verdict used to pass.
        assert block["verdict"] == _runner_mod._ablation_verdict(name, block), (
            f"{name}'s verdict does not follow from its own interval: {block}"
        )


def test_g4_the_bye_ablation_is_labelled_unmeasurable(committed) -> None:
    """It is unmeasurable BY CONSTRUCTION and must not be reported as a null result.

    The bootstrap resamples a player's own observed weeks, so a bye week does not exist in the
    outcome measure. The bye term cannot help or hurt, and calling that "no effect" would be a
    claim about the bye logic when it is a property of the harness.
    """
    block = (committed.get("ablations") or {}).get("no_bye")
    if block is None:
        pytest.skip("no_bye is not in the committed run")
    assert "UNMEASURABLE" in block["verdict"]


def test_i2_an_ablation_aliased_to_real_reads_as_no_change(mods, one_season, tmp_path) -> None:
    """Failure injection 2. The control case must be distinguishable from a genuine null.

    An ablation that is secretly `real` produces an exactly-zero difference. A genuine null
    produces a small non-zero one whose interval spans zero. The verdict function must not
    call them the same thing without the numbers saying so.
    """
    _room, runner, seat_mod, _weekly, _artifact = mods
    exact_zero = {"n": 300, "mean": 0.0, "lo": 0.0, "hi": 0.0}
    assert "no measurable change" in runner._ablation_verdict("no_need", exact_zero)

    genuine_null = {"n": 300, "mean": -1.2, "lo": -14.0, "hi": 11.6}
    assert "no measurable change" in runner._ablation_verdict("no_need", genuine_null)

    real_effect = {"n": 300, "mean": -40.0, "lo": -60.0, "hi": -20.0}
    verdict = runner._ablation_verdict("no_need", real_effect)
    assert "measurable" in verdict and "HURTS" in verdict

    # And the two cases must be TELLABLE APART on real runs, which is the part that was
    # missing: this test used to feed `_ablation_verdict` hand-written dicts and never look at
    # a live ablation, so an ablation silently aliased to `real` produced exactly 0.0 and
    # nothing complained.
    board, fit, week = one_season
    from . import weekly as weekly_mod

    config = weekly_mod.league_config()

    def advantage(arm: str, seed: int) -> float:
        return seat_mod.run_arm(
            arm, 2024, seed, season_board=board, fit=fit, week_table=week,
            config=config, state_dir=tmp_path, seat=6,
        ).advantage

    aliased = [advantage("real", seed) - advantage("real", seed) for seed in range(3)]
    assert all(d == 0.0 for d in aliased), "real against itself is not exactly zero"

    for name in ("no_need", "no_urgency"):
        live = [advantage(name, seed) - advantage("real", seed) for seed in range(3)]
        assert any(d != 0.0 for d in live), (
            f"{name} differed from `real` by exactly 0.0 on every seed; it is an alias, which "
            f"is the condition this test exists to separate from a genuine null"
        )


def test_g4_each_ablation_actually_changes_the_decision_path(mods, one_season, tmp_path) -> None:
    """EVERY ablation must change a pick, checked one at a time.

    This asserted on the SET -- `assert moved` -- and mutation testing showed what that was
    worth: unwiring `no_need` OR `no_urgency` OR `no_slice` individually turned each into an
    exact alias of `real`, advantage delta 0.000 and the same sixteen picks, and all 22 gates
    stayed green because the other three still moved. Three of the four ablations were
    unfalsifiable.

    It is also why the check runs over several seeds. `no_slice` is genuinely inert at
    (2024, seed 0) -- the TOP_N cap does not bind there -- so a one-seed set-based assertion
    could never have caught it even in principle.
    """
    room, _runner, seat_mod, weekly, _artifact = mods
    board, fit, week = one_season
    config = weekly.league_config()

    def roster(arm: str, seed: int) -> list[str]:
        got = seat_mod.run_arm(
            arm, 2024, seed, season_board=board, fit=fit, week_table=week,
            config=config, state_dir=tmp_path, seat=6,
        )
        return [p.name for p in got.picks if p.seat == 6]

    seeds = range(6)
    base = {seed: roster("real", seed) for seed in seeds}
    inert = []
    for name in sorted(seat_mod.ABLATIONS):
        if all(roster(name, seed) == base[seed] for seed in seeds):
            inert.append(name)
    assert not inert, (
        f"{inert} changed no pick on any of {len(list(seeds))} seeds; each is an exact alias "
        f"of `real` and is not wired up"
    )


def test_the_artifact_producers_are_actually_executed(mods, tmp_path) -> None:
    """`build_payload`, `board_vs_adp` and `_compare`'s field argument, on a live tiny run.

    THE HOLE THIS CLOSES. Every other gate here reads the frozen `sim/runs/b3-diagnose.json`,
    so the code that PRODUCES an artifact was never executed by any test in `sim/`. Mutation
    testing confirmed the consequence: `board_vs_adp` returning `{}`, `build_payload` dropping
    the walk-forward block, and `_compare` ignoring its `field` argument all left every gate
    green. That last one is the sharpest -- with it, every `_oracle` and `_hindsight` block
    would silently duplicate its primary, which is the whole distinction B3 turns on.
    """
    room, runner, _seat, _weekly, _artifact = mods
    config = runner.RunConfig(
        name="gate-producers",
        seasons=(2023, 2024),
        seeds=(0, 1),
        arms=("real", "adp", "shuffle", "bot", "legacy", "no_need"),
        seat=6,
        league="espn_davis_drive",
        fit_seasons=room.SEASONS,
        wf_fit=(2023,),
        wf_test=(2024,),
        raw={},
    )
    payload = runner.execute(
        config, resume=False, state_dir=tmp_path / "state", checkpoint_dir=tmp_path
    )

    board = payload["board_vs_adp"]
    assert board["harness"], "board_vs_adp produced nothing"
    assert board["harness"]["2024"]["exact_of_128"] == 128

    assert payload["walk_forward"]["wf-in"]["seasons"] == [2023]
    assert payload["walk_forward"]["wf-out"]["seasons"] == [2024]

    # The three lineup policies must give three DIFFERENT numbers. If `_compare` ignored its
    # field argument they would be identical, and the artifact would be lying about what it
    # measured while every assertion above still held.
    primary = payload["real_minus_adp"]["mean"]
    oracle = payload["real_minus_adp_oracle"]["mean"]
    hindsight = payload["real_minus_adp_hindsight"]["mean"]
    assert len({primary, oracle, hindsight}) == 3, (
        f"the three lineup policies gave {primary}, {oracle}, {hindsight} -- `_compare` is "
        f"ignoring its `field` argument"
    )

    # And the per-slot decomposition must carry by-POSITION rows, not only by-slot.
    for name, block in payload["arms"].items():
        slots = block["slot_points"]
        assert any(k.startswith("pos:") for k in slots), f"{name} has no by-position rows"


# --- G5: how much ordering is there to find ---------------------------------------------------


def test_g5_the_harness_board_is_the_adp_list(mods) -> None:
    """THE FINDING, asserted so it cannot quietly stop being true.

    `board_from_season` gives audible a board whose value is a monotone transform of ADP rank,
    so its ordering IS the market's. `real - adp` therefore measures the OVERLAY alone. If this
    ever stops holding, every conclusion drawn from `real - adp` changes meaning and this gate
    is what says so.
    """
    room, _runner, seat_mod, weekly, _artifact = mods
    config = weekly.league_config()
    for season in room.SEASONS:
        board = room.load_board(season)
        audible = seat_mod.board_from_season(board, config)
        top = audible.entries[: room.PICKS]
        exact = sum(1 for i, e in enumerate(top, start=1) if e.adp_rank == i)
        assert exact == room.PICKS, (
            f"{season}: only {exact}/{room.PICKS} of audible's top 128 match ADP rank. The "
            f"harness board is no longer the ADP list, so `real - adp` no longer measures the "
            f"overlay alone."
        )


def test_g5_the_production_board_is_not_the_adp_list(mods) -> None:
    """And the counterpart, which is why the harness cannot see audible's value layer."""
    import importlib.util

    room, _runner, _seat, _weekly, _artifact = mods
    loader = REPO / "scripts" / "qa_board_fixture.py"
    fixture = loader.parent / "fixtures" / "qa-board-espn_green_hope.json"
    if not (loader.exists() and fixture.exists()):
        pytest.skip("the pinned production board is not present")
    spec = importlib.util.spec_from_file_location("_qa_b3", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    board = module.load_board("espn_green_hope", fixture)
    priced = [e for e in board.entries if e.adp_rank is not None]
    top = sorted(priced, key=lambda e: e.vorp_rank)[: room.PICKS]
    apart = sum(1 for i, e in enumerate(top, start=1) if abs(e.adp_rank - i) > room.TEAMS)
    assert apart > 40, (
        f"the production board disagrees with ADP in only {apart} of 128 positions; the "
        f"contrast this gate rests on is gone"
    )


def test_g5_the_artifact_reports_both(committed) -> None:
    board = committed.get("board_vs_adp") or {}
    assert board.get("harness"), "no harness board comparison in the artifact"
    for season, row in board["harness"].items():
        assert row["exact_of_128"] == 128, f"{season} is no longer exact"
    assert board.get("production"), "no production board comparison in the artifact"


# --- G6: walk-forward ---------------------------------------------------------------------------


def test_g6_the_walk_forward_split_is_reported(committed) -> None:
    walk = committed.get("walk_forward") or {}
    assert set(walk) >= {"wf-in", "wf-out"}, sorted(walk)
    assert walk["wf-in"]["seasons"] == [2021, 2022, 2023]
    assert walk["wf-out"]["seasons"] == [2024, 2025]
    for label in ("wf-in", "wf-out"):
        assert "real_minus_adp" in walk[label], f"{label} has no real_minus_adp"


def test_g6_the_out_of_sample_fit_never_saw_the_test_seasons(mods) -> None:
    """Structural, not a promise: the split's fit seasons and run seasons cannot overlap."""
    _room, runner, _seat, _weekly, _artifact = mods
    config = runner.load_config(CONFIG)
    labels = {label: (fit, run) for label, fit, run in config.splits()}
    assert "wf-out" in labels
    fit_seasons, run_seasons = labels["wf-out"]
    assert not (set(fit_seasons) & set(run_seasons)), (
        f"the out-of-sample split fits on {fit_seasons} and runs on {run_seasons}, which "
        f"overlap"
    )


def test_i5_flattening_the_intervals_flips_a_verdict(mods, committed) -> None:
    """Failure injection 5. Proves the season clustering is load-bearing, not decoration.

    THIS GATE USED TO ASSERT A FALSE PREMISE AND IT IS WORTH SAYING WHY. It had no access to
    the per-season structure, so it took each clustered half-width, divided by "the smallest
    flat-to-clustered ratio B2 measured (2.5x)", and asked whether a verdict changed. That
    constant does not exist. Measured on the B3 run the ratio runs from 1.25x to 3.57x,
    because it depends entirely on how much of a comparison's variance is between seasons
    rather than between seeds. Dividing every interval by one number was wrong for every
    comparison at once -- too narrow for some, too wide for others.

    The fix is not a smaller constant. `_compare` now writes `flat_lo`/`flat_hi` -- the SAME
    paired differences with the clustering removed -- into every comparison, so this reads both
    intervals instead of reconstructing one. That also gives it teeth it did not have: if
    someone unwires the clustering, the two become identical and the first assertion fires.

    What it CANNOT assert is that a verdict flips, so it does not. On the committed run one
    does -- `surface_gap` reads [+1.9, +38.8] flat and [-37.5, +78.1] clustered, so the flat
    version would have called a null effect resolvable -- but whether any flips is a fact
    about five seasons of data rather than a property of the code. The width change is
    asserted; the flips are printed.
    """
    _room, _runner, _seat, _weekly, _artifact = mods
    keys = (
        "real_minus_adp", "real_minus_legacy", "legacy_minus_adp",
        "real_minus_legacy_recommend", "surface_gap", "real_minus_shuffle",
        "shuffle_minus_bot",
    )
    ratios: dict[str, float] = {}
    flipped: list[str] = []
    for key in keys:
        block = committed.get(key)
        if not block or isinstance(block["lo"], str) or "flat_lo" not in block:
            continue
        clustered = block["hi"] - block["lo"]
        flat = block["flat_hi"] - block["flat_lo"]
        assert flat > 0.0, f"{key} has a degenerate flat interval"
        ratios[key] = clustered / flat
        if (block["lo"] <= 0.0 <= block["hi"]) != (
            block["flat_lo"] <= 0.0 <= block["flat_hi"]
        ):
            flipped.append(key)

    assert ratios, "no comparison carried a flat interval; `_compare` is not writing one"
    widest = max(ratios.values())
    assert widest > 1.25, (
        f"the clustered interval is at most {widest:.2f}x the flat one across {len(ratios)} "
        f"comparisons ({ratios}); the clustering is doing nothing and is not load-bearing"
    )
    # Reported, never asserted. A run where clustering flips no verdict is a run where the
    # answer does not turn on it, which is information rather than a failure.
    print(f"clustering flipped verdicts on: {flipped or 'nothing'}; ratios {ratios}")


# --- G7/G8: the B2 gates that must keep holding -------------------------------------------------


def test_g7_the_skill_baseline_is_still_required(mods) -> None:
    _room, _runner, seat_mod, _weekly, _artifact = mods
    assert "adp" in seat_mod.REQUIRED_ARMS
    assert set(seat_mod.REQUIRED_ARMS) == {"real", "shuffle", "bot", "adp"}


def test_g8_the_null_control_and_the_leak_ceiling_still_hold(committed, mods) -> None:
    _room, runner, seat_mod, _weekly, _artifact = mods
    bot = committed["arms"]["bot"]["advantage"]
    assert bot["lo"] <= 0.0 <= bot["hi"], (
        f"the null control is not at chance: {bot['mean']:+.1f} "
        f"[{bot['lo']:+.1f}, {bot['hi']:+.1f}]"
    )
    assert seat_mod.LEAK_CEILING == 150.0
    assert runner.leak_ceiling_failures(committed) == []
    assert runner.gate_failures(committed) == []


def test_i3_an_oracle_seat_still_fires_the_ceiling(mods) -> None:
    """Failure injection 3. B2's ceiling gate must still go red on a real leak."""
    _room, runner, seat_mod, _weekly, _artifact = mods
    leaky = {"real_minus_adp": {"mean": 330.0, "lo": 300.0, "hi": 360.0}}
    assert any("G6d" in f for f in runner.leak_ceiling_failures(leaky))
    honest = {"real_minus_adp": {"mean": -15.9, "lo": -51.3, "hi": 19.5}}
    assert runner.leak_ceiling_failures(honest) == []


def test_g9_intervals_are_clustered_on_season(mods) -> None:
    """t with 4 df on five clusters, not 1.96 on three hundred draws."""
    _room, _runner, seat_mod, _weekly, _artifact = mods
    assert seat_mod._t95(4) == 2.776
    values = [1.0, 2.0, 3.0, 4.0] * 25
    clusters = [2021, 2022, 2023, 2024] * 25
    flat = seat_mod.mean_and_interval(values)
    clustered = seat_mod.mean_and_interval(values, clusters)
    assert (clustered[2] - clustered[1]) > (flat[2] - flat[1]), (
        "clustering did not widen the interval"
    )
    assert clustered[0] == pytest.approx(st.mean(values))
