"""GATES G0-G10 for the B2 runner, plus seven failure injections.

The runner exists so a sweep can complete with nobody watching it. Everything here is
therefore about the properties that make an unattended run trustworthy rather than merely
finished: it must refuse to start without its inputs, resume where it died, produce the same
artifact twice, and exit non-zero naming what failed.

Gate labels present here are G0, G1, G2, G3, G4, G5, G6, G6a, G6b, G6c, G6d, G7 and G10.
G8, G9, G11, G12 and G13 belong to `sim/test_g_room.py` and to the report, not to this file.

WHAT THE HEAVY GATES DO NOT DO. Several run real sweeps and they are kept small -- one season,
one to six seeds -- because the property being checked is structural, not statistical. The
statistical numbers come from `sim/runs/b2-default.json`, which is committed.

THAT COMMITTED FILE IS ALSO A HOLE, AND IT IS NAMED RATHER THAN LEFT: three gates below
`pytest.skip` when it is absent, so deleting it turns them green-by-skipping. It is tracked in
git (`sim/runs/.gitignore` covers only checkpoints and logs), so a deletion shows in
`git status` -- but nothing here will tell you.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "sim" / "runs"
CONFIGS = REPO / "sim" / "configs"
SMOKE = CONFIGS / "b2-smoke.toml"


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
    _require("nflverse/teams.parquet")
    for season in (2023, 2024):
        _require(f"ffc_adp_standard_8_{season}.json")
        _require(f"espn_draft_{room.LEAGUE_ID}_{season}.json")
        _require(f"nflverse/player_stats_{season}.parquet")
    return room, runner, seat, weekly, artifact


@pytest.fixture(scope="module")
def tiny(mods, tmp_path_factory):
    """One small sweep, run once, reused by every gate that only needs a real artifact."""
    room, runner, _seat, _weekly, _artifact = mods
    config = runner.load_config(SMOKE)
    config = runner.RunConfig(
        name="gate-tiny", seasons=(2023, 2024), seeds=(0, 1, 2, 3),
        arms=("real", "shuffle", "bot", "adp"), seat=config.seat, league=config.league,
        fit_seasons=config.fit_seasons, raw={},
    )
    out = tmp_path_factory.mktemp("tiny")
    original = runner.RUNS_DIR
    runner.RUNS_DIR = out
    try:
        payload = runner.execute(config, resume=False, state_dir=out / "state", checkpoint_dir=out)
    finally:
        runner.RUNS_DIR = original
    return config, payload, out


# --- G5: provenance ------------------------------------------------------------------------


def test_g5_every_provenance_field_is_present(tiny) -> None:
    _config, payload, _out = tiny
    for field in (
        "run", "config_hash", "code_sha", "seasons", "seeds", "seat", "league",
        "fit_seasons", "units", "pins", "fit", "arms", "shuffle", "timing",
        "outcome_measure", "slots_scored",
    ):
        assert field in payload, f"artifact has no `{field}`"
    assert payload["code_sha"] != "unknown"


def test_g5_every_pin_carries_a_checksum(tiny) -> None:
    """A missing pin checksum is a failed gate. It is how you tell a moved number apart."""
    _config, payload, _out = tiny
    assert payload["pins"], "no pins recorded at all"
    for name, pin in payload["pins"].items():
        assert len(pin["sha256"]) == 64, f"{name} has no sha256"
        assert int(pin["bytes"]) > 0, f"{name} is empty"
    assert any("player_stats_" in n for n in payload["pins"])
    assert any("ffc_adp_" in n for n in payload["pins"])
    assert any(n.startswith("leagues/") for n in payload["pins"])


def test_g5_the_fitted_parameters_are_in_the_artifact(tiny) -> None:
    """A run has to be reproducible from its own artifact, not from a memory of the fit."""
    _config, payload, _out = tiny
    fit = payload["fit"]
    for field in (
        "mu", "sigma", "pick_mu", "pick_sd", "caps", "scheduled", "supply_ratio",
        "second_specialist_p", "offboard_cells", "season_sigma_tau",
    ):
        assert field in fit, f"fit block has no `{field}`"
    assert fit["scheduled"] == ["DEF", "K"]
    # `inf` survives the round trip as a string rather than as invalid JSON.
    assert fit["supply_ratio"]["K"] == "inf"


def test_g5_the_artifact_is_strict_json(tiny, mods) -> None:
    _room, _runner, _seat, _weekly, artifact = mods
    _config, payload, out = tiny
    path = artifact.write(out / "strict.json", dict(payload))
    text = path.read_text(encoding="utf-8")
    assert "Infinity" not in text and "NaN" not in text
    assert artifact.read(path)["run"] == payload["run"]


# --- G4: determinism -----------------------------------------------------------------------


def test_g4_the_same_config_gives_a_byte_identical_artifact(mods, tmp_path) -> None:
    """Excluding wall clock, which is the only thing allowed to differ."""
    room, runner, _seat, _weekly, _artifact = mods
    config = runner.RunConfig(
        name="gate-det", seasons=(2023, 2024), seeds=(0, 1), arms=("real", "shuffle", "bot", "adp"),
        seat=6, league="espn_davis_drive", fit_seasons=room.SEASONS, raw={},
    )
    original = runner.RUNS_DIR
    digests = []
    try:
        for run in ("a", "b"):
            runner.RUNS_DIR = tmp_path / run
            payload = runner.execute(config, resume=False, state_dir=tmp_path / f"s{run}")
            digests.append(_artifact_digest(payload))
    finally:
        runner.RUNS_DIR = original
    assert digests[0] == digests[1], "two runs of one config disagreed"


def _artifact_digest(payload: dict) -> str:
    from . import artifact

    return artifact.content_digest(payload)


def test_i3_changing_the_seed_set_changes_the_artifact(mods, tmp_path) -> None:
    """Failure injection 3. Proves G4 tests determinism rather than a constant."""
    room, runner, _seat, _weekly, _artifact = mods
    original = runner.RUNS_DIR
    digests = []
    try:
        for seeds in ((0, 1), (2, 3)):
            runner.RUNS_DIR = tmp_path / f"s{seeds[0]}"
            config = runner.RunConfig(
                name="gate-seed", seasons=(2023, 2024), seeds=seeds,
                arms=("real", "shuffle", "bot", "adp"), seat=6, league="espn_davis_drive",
                fit_seasons=room.SEASONS, raw={},
            )
            digests.append(
                _artifact_digest(
                    runner.execute(config, resume=False, state_dir=tmp_path / f"st{seeds[0]}")
                )
            )
    finally:
        runner.RUNS_DIR = original
    assert digests[0] != digests[1], "two different seed sets produced the same artifact"


# --- G3: offline, and preflight ---------------------------------------------------------------


def test_g3_preflight_names_every_input_before_anything_runs(mods) -> None:
    room, runner, _seat, _weekly, _artifact = mods
    config = runner.load_config(SMOKE)
    names = runner.required_inputs(config)
    assert "nflverse/ff_playerids.parquet" in names
    for season in config.seasons:
        assert f"nflverse/player_stats_{season}.parquet" in names
        assert f"ffc_adp_standard_8_{season}.json" in names
    pins = runner.preflight(config)
    assert set(pins) >= set(names)


def test_i1_a_missing_pin_fails_in_preflight_naming_the_file(mods) -> None:
    """Failure injection 1. It must fail BEFORE the first draft, not forty minutes in."""
    room, runner, _seat, _weekly, _artifact = mods
    config = runner.RunConfig(
        name="gate-missing", seasons=(2019,), seeds=(0,),
        arms=("real", "shuffle", "bot", "adp"),
        seat=6, league="espn_davis_drive", fit_seasons=(2019,), raw={},
    )
    with pytest.raises(SystemExit) as excinfo:
        runner.preflight(config)
    message = str(excinfo.value)
    assert "PREFLIGHT FAILED" in message
    assert "2019" in message, message
    assert "sim.backfill" in message, "the message must say how to fix it"


def test_g3_a_run_makes_no_network_call(mods, tmp_path, monkeypatch) -> None:
    """Offline is asserted by breaking the network, not by intending it.

    Every socket constructor is poisoned for the duration. A run that reaches for anything
    raises here rather than on the night it matters.
    """
    import socket

    room, runner, _seat, _weekly, _artifact = mods

    def refuse(*args, **kwargs):
        raise AssertionError("a run tried to open a socket; it is supposed to be offline")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    config = runner.RunConfig(
        name="gate-offline", seasons=(2023, 2024), seeds=(0,),
        arms=("real", "shuffle", "bot", "adp"),
        seat=6, league="espn_davis_drive", fit_seasons=room.SEASONS, raw={},
    )
    original = runner.RUNS_DIR
    runner.RUNS_DIR = tmp_path
    try:
        payload = runner.execute(config, resume=False, state_dir=tmp_path / "state")
    finally:
        runner.RUNS_DIR = original
    assert payload["units"] == 8


# --- G2: resumable --------------------------------------------------------------------------


def test_g2_a_resumed_run_produces_the_same_artifact(mods, tmp_path) -> None:
    """Kill it halfway and finish it; the artifact must match a straight-through run."""
    room, runner, _seat, _weekly, _artifact = mods
    config = runner.RunConfig(
        name="gate-resume", seasons=(2023, 2024), seeds=(0, 1, 2, 3),
        arms=("real", "shuffle", "bot", "adp"), seat=6, league="espn_davis_drive",
        fit_seasons=room.SEASONS, raw={},
    )
    original = runner.RUNS_DIR
    try:
        runner.RUNS_DIR = tmp_path / "whole"
        whole = _artifact_digest(
            runner.execute(config, resume=False, state_dir=tmp_path / "s1")
        )

        runner.RUNS_DIR = tmp_path / "part"
        # Run the whole sweep, then truncate its checkpoint to five records and resume from
        # there. Not "half a sweep written by hand" -- the point is that the surviving records
        # are genuine ones, so the resume is reading what a killed run would actually leave.
        runner.execute(config, resume=False, state_dir=tmp_path / "s2")
        checkpoint_path = runner.RUNS_DIR / f"{config.name}.checkpoint.jsonl"
        lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) > 5, "the sweep produced too few records to truncate"
        kept = len(lines[:5]) - 1
        checkpoint_path.write_text("\n".join(lines[:5]) + "\n", encoding="utf-8")

        reloaded = runner.Checkpoint(checkpoint_path, config, runner.preflight(config)).load()
        assert len(reloaded) == kept, (
            f"expected {kept} surviving records, the checkpoint reloaded {len(reloaded)}"
        )
        resumed = _artifact_digest(
            runner.execute(config, resume=True, state_dir=tmp_path / "s3")
        )
    finally:
        runner.RUNS_DIR = original
    assert resumed == whole, "a resumed run did not reproduce the straight-through artifact"


def test_i2_a_corrupt_checkpoint_is_refused_rather_than_restarted(mods, tmp_path) -> None:
    """Failure injection 2. Silently restarting is the failure; refusing is the behaviour."""
    room, runner, _seat, _weekly, _artifact = mods
    config = runner.RunConfig(
        name="gate-corrupt", seasons=(2023, 2024), seeds=(0, 1),
        arms=("real", "shuffle", "bot", "adp"),
        seat=6, league="espn_davis_drive", fit_seasons=room.SEASONS, raw={},
    )
    path = tmp_path / "cp.jsonl"
    checkpoint = runner.Checkpoint(path, config)
    checkpoint.start()
    checkpoint.append({"arm": "real", "season": 2024, "seed": 0, "points_for": 1.0})

    # 1. A record whose hash no longer matches its content.
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    row["unit"]["points_for"] = 999.0
    path.write_text(lines[0] + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="fails its own hash"):
        checkpoint.load()

    # 2. A truncated final line, which is how a killed process leaves a file.
    path.write_text(lines[0] + "\n" + lines[1][: len(lines[1]) // 2], encoding="utf-8")
    with pytest.raises(SystemExit, match="not a complete record"):
        checkpoint.load()

    # 3. A checkpoint written by a different config.
    other = runner.RunConfig(
        name="gate-corrupt", seasons=(2023,), seeds=(0, 1), arms=("real", "shuffle", "bot", "adp"),
        seat=6, league="espn_davis_drive", fit_seasons=room.SEASONS, raw={},
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="written by config"):
        runner.Checkpoint(path, other).load()


# --- G6: the leak detector -------------------------------------------------------------------


def test_g6a_a_bot_in_the_seat_lands_at_chance(tiny) -> None:
    """The null control, and the thing that says the machinery is sound.

    A seat played by the room's own logic must score the field average, by symmetry. If it
    does not, the harness is scoring the seat differently from the others and no arm's number
    means anything. Four seeds is a wide interval; the committed run has 300 and reads
    -4.5 [-25.8, +16.7].
    """
    _config, payload, _out = tiny
    bot = payload["arms"]["bot"]["advantage"]
    assert bot["lo"] <= 0.0 <= bot["hi"], (
        f"a bot in the seat scored {bot['mean']:+.1f} [{bot['lo']:+.1f}, {bot['hi']:+.1f}], "
        f"which excludes zero"
    )


def test_g6b_the_real_arm_beats_the_shuffle_arm(mods) -> None:
    """Read off the committed run, because four seeds cannot resolve it.

    A scrambled board doing as well as the real one is what a leak looks like.
    """
    _room, _runner, _seat, _weekly, artifact = mods
    path = RUNS / "b2-default.json"
    if not path.exists():
        pytest.skip("sim/runs/b2-default.json is not committed yet")
    payload = artifact.read(path)
    diff = payload["real_minus_shuffle"]
    assert diff["lo"] > 0.0, (
        f"real - shuffle is {diff['mean']:+.1f} [{diff['lo']:+.1f}, {diff['hi']:+.1f}], "
        f"which includes zero"
    )


def test_g6_the_literal_shuffle_gate_is_reported_whatever_it_says(mods) -> None:
    """It says NO, and the artifact must keep saying NO rather than quietly dropping it.

    B2 was asked for a shuffle arm that lands at chance against the bots. It does not, the
    null control explains why, and the number stays in the artifact either way.
    """
    _room, _runner, _seat, _weekly, artifact = mods
    path = RUNS / "b2-default.json"
    if not path.exists():
        pytest.skip("sim/runs/b2-default.json is not committed yet")
    payload = artifact.read(path)
    assert "at_chance" in payload["shuffle"]
    assert "leak_decomposition" in payload
    decomposition = payload["leak_decomposition"]
    for term in (
        "machinery_bot_in_seat",
        "structure_shuffle_minus_bot",
        "value_ordering_real_minus_shuffle",
        "total_real",
    ):
        assert decomposition[term] is not None, f"no `{term}` in the decomposition"


def test_i5_a_shuffle_arm_reading_the_real_board_fires_the_detector(mods, tmp_path) -> None:
    """Failure injection 5. The gate on the leak detector itself.

    `leaky-shuffle` is the shuffle arm with the shuffle removed -- it reads the real board.
    `real - shuffle` then collapses to zero, which is the signature G6b exists to catch.
    """
    room, runner, seat_mod, weekly_mod, _artifact = mods
    config = weekly_mod.league_config()
    board = room.load_board(2024)
    fit = room.fit_room()
    week = weekly_mod.weekly_points(2024)
    real, leaky = [], []
    for seed in range(6):
        real.append(
            seat_mod.run_arm(
                "real", 2024, seed, season_board=board, fit=fit, week_table=week,
                config=config, state_dir=tmp_path, seat=6,
            ).advantage
        )
        leaky.append(
            seat_mod.run_arm(
                "leaky-shuffle", 2024, seed, season_board=board, fit=fit, week_table=week,
                config=config, state_dir=tmp_path, seat=6,
            ).advantage
        )
    paired = [a - b for a, b in zip(real, leaky, strict=True)]
    assert all(abs(d) < 1e-9 for d in paired), (
        f"a shuffle arm reading the real board still differed from it by {paired}; the "
        f"injection did not fire and G6b would not catch a leak"
    )


# --- G7: no leakage ---------------------------------------------------------------------------


def test_g7_every_board_still_passes_the_pre_draft_guard(mods) -> None:
    room, _runner, _seat, _weekly, _artifact = mods
    for season in (2023, 2024):
        board = room.load_board(season)
        room.assert_pre_draft(board)
        assert board.asof < room.kickoff(season)


def test_g7_the_bye_extractor_reads_only_schedule_columns(mods, monkeypatch) -> None:
    """Byes are schedule, published in May. The restriction is what makes that checkable.

    The frame handed to `byes_from_schedule` is narrowed to the four allowed columns first,
    so a future edit that reached for a stat column raises rather than quietly working.
    """
    _room, _runner, _seat, weekly_mod, _artifact = mods
    import polars as pl

    path, _root = _require("nflverse/player_stats_2024.parquet"), None
    frame = pl.read_parquet(path)
    narrowed = frame.select(weekly_mod.SCHEDULE_COLUMNS)
    assert set(narrowed.columns) == set(weekly_mod.SCHEDULE_COLUMNS)
    byes = weekly_mod.byes_from_schedule(narrowed)
    assert len(byes) == 32, f"expected 32 byes, got {len(byes)}"
    assert all(1 <= w <= 18 for w in byes.values())
    assert byes == weekly_mod.byes_from_schedule(frame)


def test_i4_end_of_season_data_in_the_board_fires_the_guard(mods) -> None:
    """Failure injection 4. The bootstrap's own frames, pointed at a board."""
    room, _runner, _seat, _weekly, _artifact = mods
    from datetime import date

    board = room.load_board(2024)
    leaky = room.SeasonBoard(
        season=2024, rows=board.rows, provenance=("player_stats_2024",),
        asof=date(2025, 2, 1), roots=board.roots,
    )
    with pytest.raises(ValueError, match="non-pre-draft source"):
        room.assert_pre_draft(leaky)
    fit = room.fit_room()
    with pytest.raises(ValueError, match="non-pre-draft source"):
        room.simulate_draft(leaky, fit, 0)


def test_g7_the_bootstrap_is_only_consulted_after_the_draft(mods) -> None:
    """Structural, not a promise: the seat never receives a weekly table.

    `build_seat` takes a board, a config, byes and a state dir. There is no parameter through
    which an outcome could reach it, and `run_arm` calls `weekly.points_for` only after
    `simulate_draft` has returned.
    """
    import inspect

    _room, _runner, seat_mod, _weekly, _artifact = mods
    # The seat cannot be handed an outcome: there is no parameter through which one could
    # arrive. That is structural and survives a refactor in a way a source-order check does
    # not -- this test used to assert that `simulate_draft` appeared before `points_for` in
    # `run_arm`, and it broke the moment scoring moved into its own function while the
    # PROPERTY it was checking was still perfectly true.
    params = set(inspect.signature(seat_mod.build_seat).parameters)
    assert not (params & {"week_table", "weekly", "points", "outcomes"}), params
    chooser_params = set(inspect.signature(seat_mod.AudibleSeat.choose).parameters)
    assert not (chooser_params & {"week_table", "weekly", "points", "outcomes"})
    assert not any(
        f.name in {"week_table", "weekly", "outcomes"}
        for f in __import__("dataclasses").fields(seat_mod.AudibleSeat)
    ), "the seat holds an outcome table"
    # And the scorer only ever sees a COMPLETED draft: its picks argument is the return value
    # of `simulate_draft`, so there is no ordering in which it could inform one.
    scorer = set(inspect.signature(seat_mod._score_draft).parameters)
    assert "picks" in scorer and "week_table" in scorer


def test_the_exact_lineup_matches_greedy_on_this_config(mods) -> None:
    """`weekly.optimal_week` is exact; `place_into_slots` is greedy. On THIS lattice they agree.

    The claim was in `weekly.optimal_week`'s docstring with nothing behind it -- `greedy_week`
    had no caller anywhere and the equivalence the outcome measure rests on was asserted in
    prose only. It holds: measured over 14,400 player-weeks, zero disagreements. It will stop
    holding the day a SUPER_FLEX appears, which is why the exact one is what runs.
    """
    import random as _random

    room, _runner, seat_mod, weekly_mod, _artifact = mods
    fit = room.fit_room()
    disagreements = []
    checked = 0
    for season in (2023, 2024):
        board = room.load_board(season)
        week = weekly_mod.weekly_points(season)
        for seed in range(4):
            picks = room.simulate_draft(board, fit, seed)
            by_seat: dict[int, list] = {}
            for p in picks:
                by_seat.setdefault(p.seat, []).append(p)
            for seat_no, seat_picks in by_seat.items():
                roster, _ = weekly_mod.resolve_roster(seat_picks, board, week)
                draws = weekly_mod.bootstrap_weeks(
                    _random.Random(seed * 1000 + seat_no), week, [k for k, _ in roster]
                )
                for index in range(len(weekly_mod.REG_WEEKS)):
                    points = {k: draws[k][index] for k, _ in roster}
                    exact = weekly_mod.optimal_week(roster, points)[0]
                    greedy = weekly_mod.greedy_week(roster, points)
                    checked += 1
                    if abs(exact - greedy) > 1e-9:
                        disagreements.append((season, seed, seat_no, index, exact, greedy))
    assert checked > 1000, f"only {checked} player-weeks compared"
    assert not disagreements, f"{len(disagreements)} disagreements, e.g. {disagreements[:3]}"
    assert seat_mod is not None


# --- G10: legal lineups -------------------------------------------------------------------------


def test_g10_no_seat_in_any_arm_is_unable_to_start_a_lineup(tiny) -> None:
    _config, payload, _out = tiny
    for name, block in payload["arms"].items():
        assert block["structural"]["illegal_lineups"] == 0, (
            f"arm {name} produced {block['structural']['illegal_lineups']} illegal lineups"
        )


def test_i6_turning_the_deadline_off_breaks_legal_lineups(mods) -> None:
    """Failure injection 6. The measured control on the 34.8% defect."""
    room, _runner, _seat, _weekly, _artifact = mods
    fit = room.fit_room()
    board = room.load_board(2024)
    illegal = total = 0
    for seed in range(4):
        per: dict[int, list[str]] = {}
        for p in room.simulate_draft(board, fit, seed, deadline=False):
            per.setdefault(p.seat, []).append(p.position)
        for positions in per.values():
            total += 1
            roster = room._Roster()
            for position in positions:
                roster.add(position)
            illegal += 1 if roster.unfilled() else 0
    assert illegal / total > 0.2, (
        f"only {illegal}/{total} seats went illegal with the deadline off; the gate above is "
        f"then not testing anything"
    )


# --- the gate function itself, and a leak it could not see ------------------------------------


def test_gate_failures_actually_fails(mods, tiny) -> None:
    """`gate_failures` decides the unattended exit code and NOTHING tested it.

    Mutation testing found this: replacing the whole function with `return []` left all 25
    gates green, including the one that greps the log for "all gates passed". The strongest
    test in the file was borrowing its strength from an untested function.
    """
    _room, runner, _seat, _weekly, artifact = mods
    _config, tiny_payload, _out = tiny

    # A run that genuinely passes: the committed default. The `tiny` fixture is two seasons by
    # four seeds and CANNOT resolve G6b -- its interval is [-1420, +1347] -- so asserting an
    # empty failure list on it would be asserting that an unresolvable run is a clean one.
    committed = RUNS / "b2-default.json"
    if committed.exists():
        assert runner.gate_failures(artifact.read(committed)) == []

    # Everything below injects one defect into a real payload and checks the named gate fires.
    payload = tiny_payload
    broken = json.loads(json.dumps(payload))
    broken["arms"]["real"]["structural"]["illegal_lineups"] = 3
    assert any("G10" in f for f in runner.gate_failures(broken))

    broken = json.loads(json.dumps(payload))
    broken["arms"]["bot"]["advantage"] = {"mean": 200.0, "lo": 150.0, "hi": 250.0}
    assert any("G6a" in f for f in runner.gate_failures(broken))

    broken = json.loads(json.dumps(payload))
    broken["real_minus_shuffle"] = {"n": 4, "mean": 1.0, "lo": -50.0, "hi": 52.0}
    assert any("G6b" in f for f in runner.gate_failures(broken))

    broken = json.loads(json.dumps(payload))
    del broken["real_minus_adp"]
    assert any("G6c" in f for f in runner.gate_failures(broken))

    broken = json.loads(json.dumps(payload))
    broken["units"] = 0
    assert any("G0" in f for f in runner.gate_failures(broken))

    broken = json.loads(json.dumps(payload))
    broken["pins"]["nflverse/teams.parquet"]["sha256"] = ""
    assert any("G5" in f for f in runner.gate_failures(broken))

    broken = json.loads(json.dumps(payload))
    broken["require_shuffle_at_chance"] = True
    broken["shuffle"]["at_chance"] = False
    assert any("G6 shuffle-at-chance" in f for f in runner.gate_failures(broken))


def test_i7_an_outcome_informed_seat_is_caught(mods, tmp_path) -> None:
    """Failure injection 7, and the one the design did not have.

    THE ASSUMED LEAK SIGNATURE IS WRONG. G6b watches for `real - shuffle` COLLAPSING, on the
    reasoning that a leak would let a scrambled board win as hard as a real one. Mutation
    testing built an actual leak -- a seat that re-ranks its own shortlist by what each player
    went on to score that season -- and `real - shuffle` did the opposite: it WIDENED, from
    +92 to +428, because the leak helps the arm with the better shortlist more. All 25 gates
    passed and the real arm went to +479.8.

    So the detectable signature is not the collapse. It is the SIZE. A seat that beats the ADP
    baseline by hundreds of points has not found a better ordering of a board whose values are
    a monotone transform of ADP rank -- there is no such ordering to find -- so it has found
    something outside the board. This gate puts a ceiling on the baseline-relative advantage
    and fires on anything that clears it.
    """
    room, _runner, seat_mod, weekly_mod, _artifact = mods

    board = room.load_board(2024)
    fit = room.fit_room()
    week = weekly_mod.weekly_points(2024)
    config = weekly_mod.league_config()

    honest = [
        seat_mod.run_arm(
            arm, 2024, seed, season_board=board, fit=fit, week_table=week,
            config=config, state_dir=tmp_path, seat=6,
        ).advantage
        for arm in ("real", "adp")
        for seed in range(6)
    ]
    real_adv, adp_adv = honest[:6], honest[6:]
    honest_gap = sum(r - a for r, a in zip(real_adv, adp_adv, strict=True)) / 6

    # The leak: pick, from everything still on the board, whoever actually scored most that
    # season. It respects the caps and the deadline, so only the INFORMATION differs.
    totals = {
        pid: sum(weeks.values()) for pid, weeks in week.points.items()
    }
    by_rank = {r.rank: r for r in board.rows}

    def oracle(overall, taken, rows, *, remaining=0, unfilled=(), counts=None):
        held = dict(counts or {})
        allowed = (
            set(room.SLOT_ELIGIBILITY[unfilled[0]])
            if unfilled and remaining and len(unfilled) >= remaining
            else None
        )
        best, best_points = -1, -1.0
        for i, row in enumerate(rows):
            if taken[i] or (allowed is not None and row.position not in allowed):
                continue
            if held.get(row.position, 0) >= fit.caps.get(row.position, room.ROUNDS):
                continue
            ids = week.by_name.get(
                __import__("sim.adp_join", fromlist=["normalize"]).normalize(row.name), []
            )
            points = max((totals.get(g, 0.0) for g in ids), default=0.0)
            if points > best_points:
                best, best_points = i, points
        return best

    leaked = []
    for seed in range(6):
        picks = room.simulate_draft(board, fit, seed, chooser=oracle, chooser_seat=6)
        leaked.append(
            seat_mod._score_draft("real", 2024, seed, 6, picks, board, week, 16, 0).advantage
        )
    leaked_gap = sum(x - a for x, a in zip(leaked, adp_adv, strict=True)) / 6

    assert by_rank
    assert leaked_gap > honest_gap + seat_mod.LEAK_CEILING, (
        f"an oracle seat beat the ADP baseline by {leaked_gap:+.0f} against the honest "
        f"{honest_gap:+.0f}; the injection did not separate them"
    )
    payload = {"real_minus_adp": {"mean": leaked_gap, "lo": leaked_gap - 1, "hi": leaked_gap}}
    from . import runner as runner_mod

    assert any("G6d" in f for f in runner_mod.leak_ceiling_failures(payload)), (
        "the ceiling gate did not fire on an oracle seat"
    )
    assert not runner_mod.leak_ceiling_failures(
        {"real_minus_adp": {"mean": honest_gap, "lo": honest_gap - 1, "hi": honest_gap}}
    ), "the ceiling gate fires on an honest run"


# --- the runner as a process ----------------------------------------------------------------


def test_g1_the_runner_runs_unattended_and_exits_zero(tmp_path) -> None:
    """A subprocess with no agent attached, reading only a config file."""
    _require("nflverse/player_stats_2024.parquet")
    out = tmp_path / "unattended.json"
    logfile = tmp_path / "unattended.log"
    proc = subprocess.run(
        [
            sys.executable, "-m", "sim", "run", "--config", str(SMOKE),
            "--out", str(out), "--log", str(logfile),
            # Without this the run drops a 600-unit checkpoint into sim/runs, bound to the
            # smoke config's hash, which a later `--resume` would then pick up.
            "--checkpoint-dir", str(tmp_path),
        ],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert out.exists(), "no artifact"
    assert logfile.exists(), "no log"
    text = logfile.read_text(encoding="utf-8")
    assert "preflight ok" in text
    assert "all gates passed" in text
    assert "eta" in text, "the log carries no progress or ETA"


def test_g1_a_bad_config_exits_non_zero_without_running(tmp_path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[run]\nname = "x"\n', encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable, "-m", "sim", "run", "--config", str(bad),
            # `setup_logging` opens RUNS_DIR/<name>.log in APPEND mode, so a test with no
            # --log grows a file inside the repo on every run.
            "--log", str(tmp_path / "t.log"),
        ],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "missing required key" in (proc.stdout + proc.stderr)


def test_g1_a_config_without_the_shuffle_arm_is_refused(tmp_path) -> None:
    """The shuffle arm is not optional and the runner will not start without it."""
    bad = tmp_path / "noshuffle.toml"
    bad.write_text(
        '[run]\nname = "x"\nseasons = [2024]\nseed_count = 1\narms = ["real"]\n'
        'seat = 6\nleague = "espn_davis_drive"\n',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable, "-m", "sim", "run", "--config", str(bad),
            # `setup_logging` opens RUNS_DIR/<name>.log in APPEND mode, so a test with no
            # --log grows a file inside the repo on every run.
            "--log", str(tmp_path / "t.log"),
        ],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "shuffle arm is not optional" in (proc.stdout + proc.stderr)


# --- the committed artifact --------------------------------------------------------------------


def test_the_committed_run_is_readable_and_carries_its_summary(mods) -> None:
    _room, _runner, _seat, _weekly, artifact = mods
    path = RUNS / "b2-default.json"
    if not path.exists():
        pytest.skip("sim/runs/b2-default.json is not committed yet")
    text = path.read_text(encoding="utf-8")
    header = [line for line in text.splitlines() if line.startswith("#")]
    assert header, "the artifact has no mobile summary header"
    assert all(len(line) <= 62 for line in header), "a summary line is wider than 60 columns"
    payload = artifact.read(path)
    assert payload["content_digest"]
    assert payload["units"] == len(payload["seeds"]) * len(payload["seasons"]) * len(
        payload["arms"]
    )
