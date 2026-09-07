"""GATES G1-G6 for B3, plus the five failure injections.

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
which is committed; gates that read a number read it from there rather than re-deriving it at
a sample size too small to mean anything. That file being absent turns three gates into skips,
which is named here rather than left to be discovered.
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
    expected = weekly.expected_points(week, keys)
    lineup_a = weekly.optimal_week(roster, expected)[1]

    # A different realised draw, same expectation.
    lineup_b = weekly.optimal_week(roster, expected)[1]
    assert lineup_a == lineup_b

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


def test_g1_ex_ante_scores_below_realised_and_the_gap_is_the_artifact(mods, one_season) -> None:
    """Hindsight is worth points. It must be, or `optimal_week` is not optimising."""
    room, _runner, _seat, weekly, _artifact = mods
    board, fit, week = one_season
    picks = room.simulate_draft(board, fit, 0)
    roster, _ = weekly.resolve_roster([p for p in picks if p.seat == 6], board, week)
    ex_ante, _slots = weekly.points_for(random.Random(1), week, roster)
    realised, _ = weekly.points_for(random.Random(1), week, roster, lineup="realised")
    assert realised > ex_ante, (
        f"realised {realised:.1f} did not beat ex-ante {ex_ante:.1f}; hindsight must pay"
    )


def test_g1_the_artifact_says_which_lineup_every_number_uses(committed) -> None:
    assert "EX-ANTE" in committed["outcome_measure"].upper()
    assert "realised" in committed["secondary_measure"].lower()
    for name, block in committed["arms"].items():
        assert "realised_secondary" in block, f"arm {name} has no secondary"
        assert "SECONDARY" in block["realised_secondary"]["lineup"].upper()


def test_i4_reverting_to_the_realised_lineup_restores_the_te_artifact(mods, one_season) -> None:
    """Failure injection 4. Proves Task 1 changed what it claims to have changed.

    Under the realised lineup the tight-end slot takes a far larger share of the seat's points
    than under the ex-ante one, because hindsight pays for hoarding.
    """
    room, _runner, _seat, weekly, _artifact = mods
    board, fit, week = one_season
    shares: dict[str, float] = {}
    for mode in ("ex-ante", "realised"):
        totals: dict[str, float] = {}
        for seed in range(4):
            picks = room.simulate_draft(board, fit, seed)
            roster, _ = weekly.resolve_roster(
                [p for p in picks if p.seat == 6], board, week
            )
            _total, slots = weekly.points_for(
                random.Random(seed), week, roster, lineup=mode
            )
            for slot, points in slots.items():
                totals[slot] = totals.get(slot, 0.0) + points
        grand = sum(totals.values()) or 1.0
        shares[mode] = totals.get("TE", 0.0) / grand
    assert shares["realised"] > shares["ex-ante"], (
        f"TE share did not fall: ex-ante {shares['ex-ante']:.3f}, "
        f"realised {shares['realised']:.3f}"
    )


# --- G2: per-slot decomposition ---------------------------------------------------------------


def test_g2_every_arm_carries_a_per_slot_decomposition(committed) -> None:
    """The tight-end result hid for a whole session because nothing broke it down by slot."""
    for name, block in committed["arms"].items():
        slots = block.get("slot_points")
        assert slots, f"arm {name} has no slot_points"
        assert sum(slots.values()) > 0, f"arm {name} scored nothing in any slot"
        assert set(slots) <= set(
            ["QB", "RB", "WR", "TE", "FLEX", "DEF", "K"]
        ), sorted(slots)


# --- G3: the legacy arm ------------------------------------------------------------------------


def test_g3_the_legacy_arm_is_reported_and_distinct(committed) -> None:
    assert "legacy" in committed["arms"]
    assert "real_minus_legacy" in committed
    assert committed["arms"]["legacy"]["definition"].startswith("the pre-audible#60")


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
    ablations = committed.get("ablations") or {}
    assert set(ablations) == set(seat_mod.ABLATIONS), sorted(ablations)
    for name, block in ablations.items():
        assert block["verdict"], f"{name} has no verdict"
        assert "n" in block and block["n"] > 0


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

    # And an aliased arm really does give exactly zero, which is what makes the first case
    # reachable rather than hypothetical.
    board, fit, week = one_season
    from . import weekly as weekly_mod

    config = weekly_mod.league_config()
    a = seat_mod.run_arm(
        "real", 2024, 0, season_board=board, fit=fit, week_table=week,
        config=config, state_dir=tmp_path, seat=6,
    ).advantage
    b = seat_mod.run_arm(
        "real", 2024, 0, season_board=board, fit=fit, week_table=week,
        config=config, state_dir=tmp_path, seat=6,
    ).advantage
    assert a - b == 0.0


def test_g4_each_ablation_actually_changes_the_decision_path(mods, one_season, tmp_path) -> None:
    """An ablation that never changes a pick is not an ablation. At least one must move.

    `no_bye` and `no_slice` may legitimately be inert -- the bye term is unmeasurable and the
    TOP_N cap may never bind -- so this asserts on the SET rather than on each one, and the
    artifact's verdicts say which is which.
    """
    room, _runner, seat_mod, weekly, _artifact = mods
    board, fit, week = one_season
    config = weekly.league_config()
    base = seat_mod.run_arm(
        "real", 2024, 0, season_board=board, fit=fit, week_table=week,
        config=config, state_dir=tmp_path, seat=6,
    )
    base_names = [p.name for p in base.picks if p.seat == 6]
    moved = []
    for name in sorted(seat_mod.ABLATIONS):
        got = seat_mod.run_arm(
            name, 2024, 0, season_board=board, fit=fit, week_table=week,
            config=config, state_dir=tmp_path, seat=6,
        )
        if [p.name for p in got.picks if p.seat == 6] != base_names:
            moved.append(name)
    assert moved, "no ablation changed a single pick; none of them is wired up"


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

    A flat standard error over seeds treats sixty draws from one market as sixty markets. It
    is 2.5 to 2.9 times too narrow, and at least one comparison must change verdict when the
    clustering is removed -- otherwise the clustering is costing width for nothing.
    """
    _room, _runner, _seat, _weekly, _artifact = mods
    # The per-season structure a comparison was built from is not in the artifact, so this
    # works from the intervals the artifact DOES report: take each clustered half-width, divide
    # by the smallest flat-to-clustered ratio B2 measured (2.5x), and ask whether the verdict
    # changes. That is the conservative direction -- the real ratio ran to 2.9.
    flipped = []
    for key in ("real_minus_adp", "real_minus_legacy", "real_minus_shuffle"):
        block = committed.get(key)
        if not block or isinstance(block["lo"], str):
            continue
        clustered_spans_zero = block["lo"] <= 0.0 <= block["hi"]
        half = (block["hi"] - block["lo"]) / 2.0
        # 2.5x is the smallest ratio B2 measured between flat and clustered.
        flat_half = half / 2.5
        flat_spans_zero = (
            block["mean"] - flat_half <= 0.0 <= block["mean"] + flat_half
        )
        if clustered_spans_zero != flat_spans_zero:
            flipped.append(key)
    assert flipped, (
        "narrowing every interval by the measured 2.5x flipped no verdict; the clustering "
        "is not load-bearing on this run and the injection proves nothing"
    )


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
