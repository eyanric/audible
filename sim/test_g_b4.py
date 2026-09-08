"""GATES G0-G8, G10 and G14 for B4, plus the six failure injections. There is no G9 here:
B2's determinism and resumability gates already cover it and live in `sim/test_g_runner.py`.

B4 ASKS ONE QUESTION: does audible's scoring transform earn its place, or is it a coat of
paint over ADP? Every gate here is about whether the comparison that answers it is honest --
not about whether the answer is good.

THE GATE ON THE WHOLE SESSION IS G2. B3's finding was that `seat.board_from_season` hands
audible a board that is a monotone transform of ADP rank, 128 of 128 exact in every season, so
every arm comparison B1-B3 produced measured the overlay and never the board. If B4's boards
come back the same way, this session has reproduced that defect and no arm number means
anything. `test_g2_*` asserts they do not, and `test_i1_*` reproduces the defect on purpose to
show the gate can fail.

THE STATISTICAL NUMBERS COME FROM `sim/runs/b4-transform.json`, which is committed alongside
this file. Gates that read a number read it from there rather than re-deriving it at a sample
size too small to mean anything.

THAT FILE BEING ABSENT TURNS 15 OF THE 30 GATES INTO SKIPS AND THE SUITE STILL EXITS 0 --
measured, not estimated, and it is a real weakness rather than a footnote. Of those 15, only
`test_g7_the_size_ceilings_still_fire` executes any production code; the rest are schema and
value assertions over a frozen file and caught zero of 36 mutations in an adversarial pass.
The gates that carry the weight are `test_the_b4_producers_are_actually_executed`, which runs
`runner.execute` end to end, and `test_g0_the_live_projection_matches_the_committed_one`, which
is what stops the code and the artifact drifting apart in silence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "sim" / "runs"
CONFIG = REPO / "sim" / "configs" / "b4-transform.toml"
ARTIFACT = RUNS / "b4-transform.json"

pytestmark = pytest.mark.slow


def _require(name: str) -> Path:
    for root in (SIM_CACHE, LIVE_CACHE):
        if (root / name).exists():
            return root / name
    pytest.skip(f"{name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}")


@pytest.fixture(scope="module")
def mods():
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    from . import accuracy, artifact, boards, projection, room, runner, seat, weekly

    _require("nflverse/ff_playerids.parquet")
    for season in (2021, 2022, 2023):
        _require(f"nflverse/player_stats_{season}.parquet")
    for season in (2022, 2023):
        _require(f"ffc_adp_standard_8_{season}.json")
    return accuracy, artifact, boards, projection, room, runner, seat, weekly


@pytest.fixture(scope="module")
def committed(mods):
    _a, artifact, *_rest = mods
    if not ARTIFACT.exists():
        pytest.skip(f"{ARTIFACT} is not committed yet")
    return artifact.read(ARTIFACT)


@pytest.fixture(scope="module")
def built(mods):
    """The 2023 boards, built once. 2023 is the earliest season with a role blend."""
    _a, _art, boards, _proj, _room, _runner, _seat, weekly = mods
    return boards.build(2023, weekly.league_config())


# --- G0: the pre-registration is pinned -------------------------------------------------------


def test_g0_the_pre_registered_constants_are_pinned(mods) -> None:
    """THE CLAIM "pre-registered and then left alone" IS WORTH EXACTLY THIS TEST AND NO MORE.

    `sim/projection.py`'s docstring said the constants were pinned by a gate. They were not --
    mutation testing rewrote LOOKBACK, ROLE_BLEND, CAPITAL_BUCKETS and MAX_GAMES all at once
    and 26 of 27 gates stayed green, which means a silent re-fit was available to anyone
    including this session. These are the numbers the pre-registration names, and changing one
    is now a failing gate rather than a diff nobody reads.
    """
    _a, _art, _b, projection, _room, _runner, _seat, _weekly = mods
    assert projection.LOOKBACK == (0.6, 0.3, 0.1)
    assert projection.ROLE_BLEND == 0.5
    assert projection.CAPITAL_BUCKETS == (32, 64, 128)
    assert projection.MAX_GAMES == 17
    assert sorted(projection.POOL_POSITIONS) == ["QB", "RB", "TE", "WR"]
    assert projection.REG_WEEKS == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18)
    assert projection.USABLE == (2022, 2023, 2024, 2025)
    assert len(projection.ROLE_KEYS) == 7
    assert set(projection.ROLE_KEYS) == set(projection.ROLE_ACTUAL)


def test_g0_the_live_projection_matches_the_committed_one(mods, committed, built) -> None:
    """THE DIGEST IS ONLY WORTH WRITING DOWN IF SOMETHING COMPARES IT.

    `runner._projection_block` says the digest exists "so a later run that changed the
    projection cannot pass itself off as comparable to this one" -- and nothing compared it.
    Eight separate mutations of the projection's internals survived the whole suite for want
    of this one assertion: unweighting the lookback, zeroing the role blend, dropping the pool
    tail, double-bucketing passing yards, counting the postseason, ignoring draft capital,
    projecting everyone over seventeen games, and dropping the week filter.
    """
    _a, _art, _b, _proj, _room, _runner, _seat, _weekly = mods
    season = str(built.season)
    got = (committed.get("projection") or {}).get("seasons", {}).get(season)
    if got is None:
        pytest.skip(f"{season} is not in the committed run")
    assert built.projected_digest == got["projected_digest"], (
        f"the projection built at HEAD digests {built.projected_digest} while the committed "
        f"run recorded {got['projected_digest']}. The code and the artifact disagree about "
        f"what was measured; re-run the sweep or revert the change."
    )
    assert built.hindsight_digest == got["hindsight_digest"]

    # THE ORDERINGS THAT DO NOT CONSUME REPLACEMENT LEVEL MUST STILL MATCH EXACTLY. `vs_adp`
    # holds one row per arm, and B7 moved the baselines, so the arms sorting on `vorp_rank` --
    # `audible_transform`, `hindsight_board` and `hindsight_total`, which is TWO of the three
    # hindsight arms and not all three -- legitimately disagree with B4's record now.
    # `hindsight_points` sorts on `consensus_rank` (`boards.py:79-82`), `points_greedy` on raw
    # points, `adp_board` on the market's own order, `scarcity_only` on `scarcity_rank`, and
    # `value/scarcity.py` never reads a replacement level. All four must be untouched, and an
    # earlier version of this gate checked only two of them.
    for arm in ("points_greedy", "adp_board", "hindsight_points", "scarcity_only"):
        if arm in built.vs_adp and arm in got["vs_adp"]:
            assert dict(built.vs_adp[arm]) == got["vs_adp"][arm], (
                f"{arm} disagrees with B4's committed run, and it sorts on an ordering that "
                f"does not consume replacement level. B7's change should be invisible to it."
            )

    # REPLACEMENT LEVELS MOVED IN B7, DELIBERATELY, AND THIS GATE NOW SAYS SO RATHER THAN
    # ASSERTING AN EQUALITY THAT IS FALSE BY DESIGN.
    #
    # B4's artifact is a record of what B4 measured, under the bench-split rule that shipped
    # then. B7 changed that rule -- `rostered_counts` used to withhold bench depth from every
    # position with fewer than two starting slots, which swept a 1-QB league's quarterback in
    # with D/ST and K -- so the committed levels and the live ones now differ at exactly the
    # positions the bench split feeds. Re-running B4's sweep to make the numbers agree would
    # rewrite a published result to match later code, which is the opposite of what an
    # artifact is for.
    #
    # What survives is the part that was actually load-bearing: the PROJECTION digests above
    # are unchanged, so the eight projection mutations this gate was built to catch are still
    # caught.
    #
    # THE FIRST VERSION OF THIS REPLACEMENT WAS WEAKER THAN THE EQUALITY IT REPLACED AND SAID
    # IT WAS STRONGER. It pinned K and DEF, asserted a direction for QB, and dropped RB, WR and
    # TE entirely -- so adding "RB" to `NO_BENCH_DEPTH`, silently reverting backs to
    # starters-only, left it green. An adversarial review found that by mutation. Worse, K and
    # DEF are both 0.0 in B4's artifact, so those two assertions were comparing zero to zero.
    #
    # Every position is pinned again. The committed numbers stay the reference for the ones
    # B7 did not touch; the ones it did are pinned to the values it produces, so a further
    # change to the bench split fails here and has to say so.
    live, was = dict(built.replacement), got["replacement_level"]
    moved_by_b7 = {"QB", "RB", "WR", "TE"}
    for position, before in sorted(was.items()):
        if position not in live:
            continue
        if position not in moved_by_b7:
            assert live[position] == before, (
                f"{position} replacement moved from {before} to {live[position]}. B7 changed "
                f"the bench split, which cannot reach a position that never had a bench share."
            )
    assert live["QB"] < was["QB"], (
        f"the QB baseline is {live['QB']} against B4's committed {was['QB']}. B7 put QB into "
        f"the bench split, which moves the baseline DEEPER and therefore LOWER; a QB baseline "
        f"that did not fall means that change is not in effect."
    )
    # The exact post-B7 values, so a fifth position quietly joining or leaving the split fails.
    assert {p: round(v, 3) for p, v in live.items() if p in moved_by_b7} == {
        "QB": 217.623, "RB": 117.927, "TE": 104.044, "WR": 111.142
    }, (
        f"the positions B7 moved no longer produce the values B7 measured: "
        f"{ {p: round(v, 3) for p, v in live.items() if p in moved_by_b7} }"
    )


# --- G1: the projection cannot see the season it projects -------------------------------------


def test_g1_the_projection_reads_only_strictly_prior_seasons(mods) -> None:
    """Stated as ENFORCEMENT, not intent, which is what the handoff asked for.

    Two independent checks, because provenance alone is a label a caller writes and a label
    can be wrong. The second one removes the season's own files from reach and requires the
    projection to be bit-identical, which no amount of mislabelling survives.
    """
    _a, _art, _b, projection, _room, _runner, _seat, weekly = mods
    config = weekly.league_config()
    season = 2023
    lines = projection.project(season, config)

    assert lines.fit_seasons == (2021, 2022), lines.fit_seasons
    assert all(s < season for s in lines.fit_seasons)
    assert all(s < season for s in lines.role_seasons)
    for name in lines.provenance:
        # The board's own ADP file is the ONE season-S input, and it is pre-draft: FFC's
        # `meta.end_date` runs 09-01 to 09-04 against kickoffs of 09-04 to 09-09, so every
        # board closes before its own season starts. Everything else must name a strictly
        # earlier season.
        if name.startswith("ffc_adp_standard_8_"):
            assert name.endswith(str(season)), name
            continue
        if name == "ff_playerids":
            continue
        year = int(name.rsplit("_", 1)[1])
        assert year < season, f"{name} is not strictly prior to {season}"


def test_g1_hiding_the_drafted_season_changes_nothing(mods, monkeypatch) -> None:
    """The construction check. If season S's own files were reachable, this would fail.

    `resolve_input` is made to raise for any path naming the drafted season. A projection that
    peeked would blow up; one that does not is bit-identical, which is asserted on the digest
    rather than on a spot check of a few fields.
    """
    _a, _art, _b, projection, room, _runner, _seat, weekly = mods
    config = weekly.league_config()
    season = 2023
    before = projection.project(season, config).digest()

    real_resolve = room.resolve_input

    def blocked(name: str):
        if f"player_stats_{season}" in name or f"ff_opportunity_{season}" in name:
            raise AssertionError(
                f"the projection for {season} reached for {name}, which is the season it is "
                f"projecting. That is the leak G1 exists to prevent."
            )
        return real_resolve(name)

    monkeypatch.setattr(room, "resolve_input", blocked)
    # `season_totals` caches nothing, so the second build genuinely re-reads every file.
    after = projection.project(season, config).digest()
    assert after == before, "the projection changed when the drafted season was hidden"


def test_i3_a_projection_that_sees_the_drafted_season_is_caught(mods) -> None:
    """Failure injection 3. Proves G1's construction check can fail.

    `actual_lines` IS that leak, built deliberately: the same universe in the same order, from
    the season's own realised totals. It must differ from the honest projection, and it must
    name the drafted season in its provenance so `assert_pre_draft` and the G1 check above both
    reject it.
    """
    _a, _art, _b, projection, _room, _runner, _seat, weekly = mods
    config = weekly.league_config()
    season = 2023
    honest = projection.project(season, config)
    leaked = projection.actual_lines(season, config)

    assert honest.digest() != leaked.digest(), (
        "the leaked lines are byte-identical to the honest ones; the ceiling arm is not a "
        "ceiling and injection 3 proves nothing"
    )
    assert any(str(season) in name for name in leaked.provenance)
    assert not any(
        name.startswith("player_stats_") and name.endswith(str(season))
        for name in honest.provenance
    )

    # THE GUARD MUST ACCEPT THE HONEST LINES AND REJECT THE LEAK.
    projection.assert_pre_draft(honest)
    with pytest.raises(projection.LeakError, match="strictly before"):
        projection.assert_pre_draft(leaked)


def test_i3_the_board_builder_actually_calls_the_leak_guard(mods, monkeypatch) -> None:
    """A guard nobody calls is a comment. `boards.build` must invoke it on every board.

    Deleting the call from `boards.build` left every gate green: `test_i3` above called
    `assert_pre_draft` itself and never checked that production did. This replaces the guard
    with one that always raises and requires the build to fail, which can only pass if the
    call site exists.
    """
    _a, _art, boards, projection, _room, _runner, _seat, weekly = mods

    def always_raises(_lines):
        raise projection.LeakError("tripwire")

    monkeypatch.setattr(projection, "assert_pre_draft", always_raises)
    with pytest.raises(projection.LeakError, match="tripwire"):
        boards.build(2023, weekly.league_config())


# --- G2: the board is not the ADP list --------------------------------------------------------


def g2_failures(row: dict) -> list[str]:
    """G2 as a PREDICATE, so the gate and its injection run the same code.

    A gate whose injection re-implements the check is two checks that can drift apart, and the
    injection then proves the copy fires rather than the gate.
    """
    out: list[str] = []
    if row["exact_of_128"] >= 32:
        out.append(
            f"G2 board-is-adp: the board matches ADP exactly on {row['exact_of_128']} of the "
            f"top 128. That is the B3 defect -- the board IS the market, and no arm number "
            f"measured against it means anything."
        )
    if row["disagree_over_one_round"] <= 32:
        out.append(
            f"G2 board-is-adp: only {row['disagree_over_one_round']} of the top 128 move by "
            f"more than a round; the comparison is not exercising the board."
        )
    if row["pearson"] >= 0.99:
        out.append(f"G2 board-is-adp: pearson {row['pearson']} against ADP rank")
    return out


def test_g2_the_board_disagrees_with_adp(built) -> None:
    """THE GATE ON THE WHOLE SESSION. B3's defect was 128/128 exact; this must not be that.

    The threshold is deliberately loose. What is being excluded is the DEGENERATE case -- a
    board whose ordering is the market's ordering, where `transform - adp` measures nothing.
    A tight threshold would be a claim about how much disagreement is right, which no one
    knows; a loose one rules out the failure that actually happened.
    """
    row = built.vs_adp["audible_transform"]
    assert not g2_failures(row), g2_failures(row)


def test_g2_every_season_in_the_artifact_disagrees_with_adp(committed) -> None:
    block = committed.get("projection") or {}
    seasons = block.get("seasons") or {}
    assert seasons, "the artifact carries no projection block"
    for season, got in seasons.items():
        row = got["vs_adp"]["audible_transform"]
        assert not g2_failures(row), (season, g2_failures(row))


def test_i1_an_adp_ordered_board_fails_g2(mods, built) -> None:
    """Failure injection 1. Reproduces the B3 defect on purpose.

    Ordering the SAME board by `adp_rank` is exactly what `seat.board_from_season` amounts to,
    and it must read 128/128 exact. If this does not fire, G2 is not testing anything.
    """
    _a, _art, _b, _proj, room, _runner, _seat, _weekly = mods
    adp_order = built.orders["adp_board"]
    season_board = room.load_board(built.season)
    ranks = [season_board.rows[i].rank for i in adp_order[: room.PICKS]]
    exact = sum(1 for place, rank in enumerate(ranks, start=1) if rank == place)
    assert exact == room.PICKS, (
        f"an ADP-ordered board matched ADP on only {exact} of {room.PICKS}; the control that "
        f"proves G2 can fail is itself broken"
    )
    # AND G2'S OWN PREDICATE MUST REJECT IT. Counting the matches proves the board is the ADP
    # list; running the gate on it proves the gate notices, which is the part that matters.
    fired = g2_failures(
        {"exact_of_128": exact, "disagree_over_one_round": 0, "pearson": 1.0}
    )
    assert any("board-is-adp" in f for f in fired), fired


# --- G4: one projection, two orderings --------------------------------------------------------


def test_g4_the_two_arms_share_one_projection(mods, built) -> None:
    """THE STRONGEST FORM OF THIS, which is that there is only one object to share.

    `points_greedy` and `audible_transform` are two rank fields read off one `DraftBoard` built
    from one list of lines. There are not two digests to compare because there is not a second
    projection. Asserted anyway on the orderings: they must cover the same players, differ from
    each other, and differ only in order.
    """
    _a, _art, _b, _proj, _room, _runner, _seat, _weekly = mods
    points = built.orders["points_greedy"]
    transform = built.orders["audible_transform"]
    assert set(points) == set(transform), (
        "the two arms do not see the same draft pool; their difference is not the transform"
    )
    assert points != transform, (
        "the two orderings are identical, so `transform - points_greedy` is exactly 0.0 by "
        "construction and measures nothing"
    )
    assert len(points) == len(set(points)), "an ordering repeats a board index"


def g4_failures(arm_digest: dict) -> list[str]:
    """G4 as a PREDICATE. Arms 1 and 2 must have been built from the same lines."""
    out: list[str] = []
    a = arm_digest.get("points_greedy")
    b = arm_digest.get("audible_transform")
    if a is None or b is None:
        return ["G4 shared-projection: one of the two arms recorded no projection digest"]
    if a != b:
        out.append(
            f"G4 shared-projection: points_greedy was built from {a} and audible_transform "
            f"from {b}. Their difference is a difference in PROJECTION, not the transform."
        )
    ceiling = arm_digest.get("hindsight_board")
    if ceiling is not None and ceiling == a:
        out.append(
            f"G4 shared-projection: the ceiling arm shares digest {a} with the honest arms, "
            f"so it is not built from realised lines and is not a ceiling."
        )
    return out


def test_g4_the_artifact_records_one_digest_per_season(committed) -> None:
    seasons = (committed.get("projection") or {}).get("seasons") or {}
    assert seasons
    for season, got in seasons.items():
        assert got["projected_digest"], season
        assert got["hindsight_digest"], season
        assert got["projected_digest"] != got["hindsight_digest"], (
            f"{season}: the projected and hindsight boards share a digest, so the ceiling arm "
            f"is not built from realised lines"
        )
        assert not g4_failures(got["arm_digest"]), (season, g4_failures(got["arm_digest"]))


def test_g4_the_live_build_records_one_digest_per_arm(built) -> None:
    assert not g4_failures(dict(built.arm_digest)), dict(built.arm_digest)
    assert built.arm_digest["points_greedy"] == built.arm_digest["audible_transform"]
    assert built.arm_digest["hindsight_board"] == built.arm_digest["hindsight_points"]


def test_i2_two_different_projections_are_detectable(mods) -> None:
    """Failure injection 2. Proves the digest can tell two projections apart.

    Building the same season twice must agree; building two different seasons must not. If a
    digest could not separate those, G4 would pass on any pair of projections at all.
    """
    _a, _art, _b, projection, _room, _runner, _seat, weekly = mods
    config = weekly.league_config()
    same = projection.project(2023, config).digest()
    again = projection.project(2023, config).digest()
    other = projection.project(2022, config).digest()
    assert same == again, "the projection is not deterministic; its digest cannot gate anything"
    assert same != other, "two different projections produced one digest"
    # AND G4'S OWN PREDICATE MUST REJECT THE PAIR. This is the injection proper: hand the gate
    # two arms built from two different projections and require it to say so.
    fired = g4_failures({
        "points_greedy": same, "audible_transform": other, "hindsight_board": "zzz",
    })
    assert any("shared-projection" in f for f in fired), fired


def test_i6_an_identity_transform_collapses_the_comparison(mods, built) -> None:
    """Failure injection 6. With replacement level removed, the two arms become one arm.

    A flat replacement level -- the same constant at every position -- leaves the VORP sort
    equal to the points sort, so `audible_transform - points_greedy` is exactly 0.0. That is
    the whole claim this session rests on, stated as a construction: what separates the two
    orderings is one constant per position and nothing else.
    """
    from audible.models.player import PlayerProjection
    from audible.value.replacement import compute_vorp

    _a, _art, boards, projection, _room, _runner, _seat, weekly = mods
    config = weekly.league_config()
    from audible.draft.board import build_board_from_lines

    lines = projection.project(built.season, config)
    board = build_board_from_lines(config, list(lines.lines))
    people = [
        PlayerProjection(
            player_id=e.player_id, name=e.name, primary_position=e.position,
            eligible_positions=e.eligible_positions, team=e.team, points=e.points,
        )
        for e in board.entries
    ]
    _entries, levels = compute_vorp(people, config)
    assert len({round(v.points, 6) for v in levels.values()}) > 1, (
        "replacement level is already flat across positions, so the live comparison is "
        "already the identity and this injection proves nothing"
    )

    # With replacement flattened, VORP is points minus one shared constant, so the order is
    # the points order exactly.
    flat = sorted(people, key=lambda p: (-p.points, p.player_id))
    by_points = sorted(board.entries, key=lambda e: e.consensus_rank)
    assert [p.player_id for p in flat] == [e.player_id for e in by_points], (
        "a flat replacement level did not reproduce the points ordering; the two arms differ "
        "by something other than replacement level"
    )
    _ = boards


def test_i6_the_identity_transform_collapses_a_live_comparison(mods, built, tmp_path) -> None:
    """Failure injection 6, run rather than argued. The advantage difference becomes 0.0.

    Both seats draft the SAME ordering, so every pick, every roster, every bootstrap draw and
    every lineup is identical and the difference is exactly zero -- not nearly zero. If it were
    not, something outside the ordering would be moving between the two arms and
    `transform - points_greedy` would not be attributable to the transform.
    """
    _a, _art, _b, _proj, room, _runner, seat, weekly = mods
    config = weekly.league_config()
    season = built.season
    season_board = room.load_board(season)
    fit = room.fit_room()
    week = weekly.weekly_points(season)
    identical = {
        "audible_transform": built.orders["audible_transform"],
        "points_greedy": built.orders["audible_transform"],
    }
    for seed in range(3):
        got = [
            seat.run_arm(
                arm, season, seed, season_board=season_board, fit=fit, week_table=week,
                config=config, state_dir=tmp_path, seat=6, prior={}, orders=identical,
            ).advantage
            for arm in ("audible_transform", "points_greedy")
        ]
        assert got[0] - got[1] == 0.0, (seed, got)

    live = {
        "audible_transform": built.orders["audible_transform"],
        "points_greedy": built.orders["points_greedy"],
    }
    moved = [
        seat.run_arm(
            "audible_transform", season, seed, season_board=season_board, fit=fit,
            week_table=week, config=config, state_dir=tmp_path, seat=6, prior={},
            orders=live,
        ).advantage
        - seat.run_arm(
            "points_greedy", season, seed, season_board=season_board, fit=fit,
            week_table=week, config=config, state_dir=tmp_path, seat=6, prior={},
            orders=live,
        ).advantage
        for seed in range(3)
    ]
    assert any(d != 0.0 for d in moved), (
        f"the two live orderings gave exactly 0.0 on every seed {moved}; the arms are aliases "
        f"and the headline comparison measures nothing"
    )


# --- G3: the projection's own accuracy --------------------------------------------------------


def test_g3_accuracy_is_reported_per_season_and_per_position(committed) -> None:
    report = (committed.get("projection") or {}).get("accuracy") or {}
    assert report.get("usable_seasons"), "no usable seasons reported"
    assert report.get("excluded_because"), "seasons were excluded with no reason given"
    seasons = report.get("seasons") or {}
    assert set(seasons) == {str(s) for s in report["usable_seasons"]}
    for season, got in seasons.items():
        summary = got["summary"]
        for key in ("n", "corr", "spearman", "adp_spearman", "mae"):
            assert key in summary, (season, key)
        assert summary["n"] > 50, (season, summary["n"])
        by_position = got["by_position"]
        assert set(by_position) >= {"QB", "RB", "WR", "TE"}, (season, sorted(by_position))
        for position, row in by_position.items():
            for key in ("n", "corr", "mae", "adp_spearman"):
                assert key in row, (season, position, key)


def test_g3_the_market_baseline_is_reported_beside_the_projection(committed) -> None:
    """A correlation with nothing to beat is not an accuracy report.

    This asserts the ADP baseline is PRESENT and comparable, never that the projection wins.
    Whether it does is the finding and belongs in the report, not in a gate.
    """
    seasons = ((committed.get("projection") or {}).get("accuracy") or {}).get("seasons") or {}
    assert seasons
    for season, got in seasons.items():
        summary = got["summary"]
        # DIRECTIONAL, because presence alone is not a check. A mutation that made
        # `accuracy.measure` compare the projection against ITSELF reported corr 1.0 / MAE 0.0
        # -- a perfect projection -- and both G3 tests passed. Another that dropped the sign
        # flip on the ADP baseline reported the market as anti-correlated with points, which
        # is the single number this report is read against.
        assert 0.0 < summary["corr"] < 0.99, (season, summary["corr"])
        assert 0.0 < summary["spearman"] < 0.99, (season, summary["spearman"])
        assert 0.0 < summary["adp_spearman"] < 0.99, (season, summary["adp_spearman"])
        assert summary["mae"] > 1.0, (season, summary["mae"])
        for position, row in got["by_position"].items():
            assert isinstance(row["adp_spearman"], (int, float)), (season, position)
            assert row["mae"] > 1.0, (season, position, row["mae"])


# --- G5/G6: the headline comparisons and the ceiling ------------------------------------------


def test_g5_both_headlines_are_reported_under_all_three_policies(committed) -> None:
    for key in ("transform_minus_points", "transform_minus_adp"):
        for suffix in ("", "_oracle", "_hindsight"):
            block = committed.get(f"{key}{suffix}")
            assert block, f"{key}{suffix} is missing"
            for field in ("mean", "lo", "hi", "n"):
                assert field in block, (key, suffix, field)


def test_g6_the_ceiling_is_reported_and_every_arm_is_a_fraction_of_it(committed) -> None:
    ceiling = committed.get("ceiling") or {}
    assert set(ceiling) >= {"prior", "oracle", "hindsight"}, sorted(ceiling)
    for policy, block in ceiling.items():
        assert "ceiling" in block, policy
        if "share_undefined_because" in block:
            continue
        for name in ("transform_minus_adp", "points_minus_adp", "transform_minus_points"):
            assert name in block, (policy, name)


def test_i4_a_ceiling_built_from_the_prior_collapses(mods, built) -> None:
    """Failure injection 4. Proves the ceiling measures FORESIGHT and not machinery.

    Built from the projected lines instead of the realised ones, the ceiling arm becomes
    `audible_transform` exactly -- same board, same order, same everything. If that did not
    hold, the gap between them would be something other than foresight.
    """
    _a, _art, boards, projection, room, _runner, _seat, weekly = mods
    from audible.draft.board import build_board_from_lines

    config = weekly.league_config()
    lines = projection.project(built.season, config)
    board = build_board_from_lines(config, list(lines.lines))
    season_board = room.load_board(built.season)
    by_index = {f"ffc{r.rank:04d}": i for i, r in enumerate(season_board.rows)}
    collapsed = boards._order_by(board, "vorp_rank", by_index)

    assert collapsed == built.orders["audible_transform"], (
        "a ceiling built from the PRIOR did not collapse onto audible_transform, so the gap "
        "between them is not foresight alone"
    )
    assert collapsed != built.orders["hindsight_board"], (
        "the real ceiling is already equal to audible_transform, so it measures no foresight"
    )


# --- G7/G8: the controls carried forward ------------------------------------------------------


def test_g7_the_null_control_and_the_leak_detector_are_present(committed) -> None:
    arms = committed["arms"]
    for name in ("bot", "shuffle", "adp", "real"):
        assert name in arms, name
    bot = arms["bot"]["advantage"]
    assert bot["lo"] <= 0.0 <= bot["hi"], (
        f"the null control is not at chance: {bot}. A bot in the seat winning or losing means "
        f"the machinery scores the seat differently from the others."
    )


def test_g7_the_size_ceilings_still_fire(mods, committed) -> None:
    """G6d on the ADP-ordered board, and G6e on the projection boards.

    Both are checked by feeding each a payload that should trip it. Neither is relaxed: G6d
    keeps its constant for `real`, and G6e bounds the board arms by what perfect foresight
    actually managed on this run.
    """
    _a, _art, _b, _proj, _room, runner, seat, _weekly = mods
    assert not runner.leak_ceiling_failures(committed), runner.leak_ceiling_failures(committed)

    # THE CONSTANT IS ASSERTED, NOT READ. Building the trip payload as
    # `seat.LEAK_CEILING + 1.0` proves the `>` operator works and nothing else: raising the
    # ceiling to 1e12 disabled G6d outright and this test still passed.
    assert seat.LEAK_CEILING == 150.0, seat.LEAK_CEILING
    tripped = dict(committed)
    tripped["real_minus_adp"] = {"mean": 151.0, "lo": 0.0, "hi": 0.0, "n": 1}
    assert any("G6d" in f for f in runner.leak_ceiling_failures(tripped))

    ceiling = committed.get("ceiling_minus_adp")
    assert ceiling, "no ceiling comparison, so G6e cannot be checked"
    tripped = dict(committed)
    tripped["transform_minus_adp"] = {
        "mean": float(ceiling["mean"]) + 1.0, "lo": 0.0, "hi": 0.0, "n": 1,
    }
    assert any("G6e" in f for f in runner.leak_ceiling_failures(tripped)), (
        "an arm beating perfect foresight did not trip the foresight ceiling"
    )


def test_g8_every_comparison_carries_a_flat_interval_too(committed) -> None:
    seen = 0
    for key, block in committed.items():
        if not isinstance(block, dict) or "lo" not in block or isinstance(block["lo"], str):
            continue
        if key.startswith(("transform_", "ceiling_", "points_minus")):
            assert "flat_lo" in block and "flat_hi" in block, key
            seen += 1
    assert seen >= 6, f"only {seen} B4 comparisons carry a flat interval"


def test_i5_flattening_the_intervals_changes_a_width(mods, committed) -> None:
    """Failure injection 5. Proves the season clustering is load-bearing, not decoration.

    THE WIDTH IS ASSERTED; THE VERDICT FLIP IS REPORTED. Whether any comparison changes side
    of zero depends on four seasons of data, not on the code, and a gate that demanded one
    would be demanding a particular result. What the code guarantees is that the two intervals
    are computed differently, and if the clustering were unwired they would be identical.
    """
    _a, _art, _b, _proj, _room, _runner, _seat, _weekly = mods
    ratios: dict[str, float] = {}
    flipped: list[str] = []
    for key, block in committed.items():
        if not isinstance(block, dict) or "flat_lo" not in block:
            continue
        if isinstance(block.get("lo"), str) or block["flat_hi"] <= block["flat_lo"]:
            continue
        ratios[key] = (block["hi"] - block["lo"]) / (block["flat_hi"] - block["flat_lo"])
        if (block["lo"] <= 0.0 <= block["hi"]) != (
            block["flat_lo"] <= 0.0 <= block["flat_hi"]
        ):
            flipped.append(key)
    assert ratios, "no comparison carried a flat interval"
    assert max(ratios.values()) > 1.25, (
        f"the clustered interval is at most {max(ratios.values()):.2f}x the flat one across "
        f"{len(ratios)} comparisons; the clustering is doing nothing"
    )
    print(f"clustering flipped: {flipped or 'nothing'}")


# --- G10: the decomposition -------------------------------------------------------------------


def test_g10_every_arm_carries_both_decompositions_and_they_agree(committed) -> None:
    """B3 found RB double-counted at 51% against a true 40%. The two views must sum equal."""
    slot_names = {"QB", "RB", "WR", "TE", "FLEX", "DEF", "K"}
    for name, block in committed["arms"].items():
        slots = block.get("slot_points")
        assert slots, f"arm {name} has no slot_points"
        by_slot = {k for k in slots if not k.startswith("pos:")}
        by_position = {k[4:] for k in slots if k.startswith("pos:")}
        assert by_slot <= slot_names, sorted(by_slot)
        assert by_position, f"arm {name} has no by-position rows"
        slot_total = sum(v for k, v in slots.items() if not k.startswith("pos:"))
        position_total = sum(v for k, v in slots.items() if k.startswith("pos:"))
        assert abs(slot_total - position_total) < 0.5, (
            f"arm {name}: by-slot {slot_total:.1f} != by-position {position_total:.1f}"
        )


def test_the_signs_of_the_known_quantities_are_right(committed) -> None:
    """SOMETHING MUST ASSERT A DIRECTION, or an operand swap is invisible.

    Swapping `_compare`'s two arms inverts every headline in the artifact -- `transform -
    points` becomes `points - transform` -- and the whole suite stayed green, because every
    other assertion is about presence, shape or distinctness. These four are the comparisons
    whose sign is known a priori rather than measured, so they are the ones that can be
    asserted without asserting the answer:

      perfect foresight must beat the market
      perfect foresight must beat a projection of the same board
      the market must beat a seat played by the room's own bots
      the real arm must beat a scrambled board

    The comparison this session exists to make -- `transform_minus_points` -- is deliberately
    NOT in this list. Its sign is the finding.
    """
    for key, why in (
        ("ceiling_minus_adp", "a board built from realised lines must beat the market"),
        ("ceiling_minus_transform", "perfect foresight must beat a projection"),
        ("real_minus_shuffle", "the real board must beat a scrambled one"),
    ):
        block = committed.get(key)
        if block is None or isinstance(block.get("mean"), str):
            continue
        assert block["mean"] > 0.0, f"{key} is {block['mean']:+.1f}: {why}"

    arms = committed["arms"]
    if "adp" in arms and "bot" in arms:
        assert arms["adp"]["advantage"]["mean"] > arms["bot"]["advantage"]["mean"], (
            "a noiseless ADP seat does not beat the room's own bots; the machinery is wrong"
        )


def test_g10_the_board_arms_are_all_present_and_distinct(committed) -> None:
    arms = committed["arms"]
    for name in ("points_greedy", "audible_transform", "adp_board", "hindsight_board"):
        assert name in arms, name
    advantages = {
        name: arms[name]["advantage"]["mean"]
        for name in ("points_greedy", "audible_transform", "hindsight_board")
    }
    assert len(set(advantages.values())) == 3, (
        f"two board arms produced the identical advantage: {advantages}. They are drafting the "
        f"same board."
    )


def test_the_adp_board_arm_reproduces_the_adp_baseline(committed) -> None:
    """A VALIDITY CHECK ON THE NEW MACHINERY, and it is exact rather than approximate.

    `adp_board` drafts through `boards.greedy` on the market's ordering; `adp` drafts through
    `seat._adp_greedy`, which is B2 code this session did not touch. They are two
    implementations of one rule, so they must agree to the last decimal. If they ever diverge,
    every board arm's number is suspect and this is the gate that says so.
    """
    arms = committed["arms"]
    if "adp_board" not in arms:
        pytest.skip("adp_board is not in the committed run")
    a = arms["adp"]["advantage"]["mean"]
    b = arms["adp_board"]["advantage"]["mean"]
    assert a == b, (
        f"adp {a} and adp_board {b} differ. Two implementations of best-available-by-ADP "
        f"disagree, so `boards.greedy` is not the same rule as `seat._adp_greedy`."
    )


# --- G14: a gate that runs the producers ------------------------------------------------------


def test_the_b4_producers_are_actually_executed(mods, tmp_path) -> None:
    """`boards.build`, `_projection_block`, `_ceiling_block` and `_compare`, on a live run.

    THE HOLE THIS CLOSES was found in B3: no gate in `sim/` ever executed the artifact
    producers, so `board_vs_adp` returning `{}` and `_compare` ignoring its `field` argument
    both left every gate green. Everything above reads the committed JSON; this runs the
    pipeline.
    """
    _a, _art, _b, _proj, room, runner, _seat, _weekly = mods
    config = runner.RunConfig(
        name="gate-b4-producers",
        seasons=(2022, 2023),
        seeds=(0, 1),
        arms=(
            "points_greedy", "audible_transform", "adp_board", "hindsight_board",
            "adp", "bot", "shuffle", "real",
        ),
        seat=6,
        league="espn_davis_drive",
        fit_seasons=room.SEASONS,
        raw={},
    )
    payload = runner.execute(
        config, resume=False, state_dir=tmp_path / "state", checkpoint_dir=tmp_path
    )

    block = payload["projection"]
    assert set(block["seasons"]) == {"2022", "2023"}
    assert block["accuracy"]["usable_seasons"]
    for season, got in block["seasons"].items():
        assert got["vs_adp"]["audible_transform"]["exact_of_128"] < 32, season

    # The three lineup policies must give three DIFFERENT numbers, or `_compare` is ignoring
    # its field argument and every `_oracle`/`_hindsight` block is a copy of its primary.
    triple = {
        payload["transform_minus_points"]["mean"],
        payload["transform_minus_points_oracle"]["mean"],
        payload["transform_minus_points_hindsight"]["mean"],
    }
    assert len(triple) == 3, triple

    assert payload["ceiling"]["prior"]["ceiling"] != 0.0
    assert payload["arms"]["adp"]["advantage"]["mean"] == (
        payload["arms"]["adp_board"]["advantage"]["mean"]
    )

    # AND THE GATES MUST RUN ON IT. `gate_failures` is called from `runner.main` and never
    # from `runner.execute`, so a mutation that made it return `[]` unconditionally left every
    # gate in this file green -- the gate checker itself was ungated on this path.
    #
    # G6b IS EXPECTED TO FIRE HERE AND ONLY G6b. This config runs two seasons, which is one
    # degree of freedom and a t quantile of 12.706, so `real - shuffle` comes out around
    # +106 [-615, +828] and cannot exclude zero however sound the machinery is. That is a
    # statement about two season-clusters, not about a leak, and asserting it away would be
    # asserting that an underpowered run is a clean one. Every OTHER gate must pass, which is
    # what makes the check worth running: it is the structural gates that this exercises.
    failures = runner.gate_failures(payload)
    assert all(f.startswith("G6b ") for f in failures), failures
    assert runner.leak_ceiling_failures(payload) == [], runner.leak_ceiling_failures(payload)

    # The per-arm draft composition must be present and must differ between the two headline
    # arms, since it is the mechanism the report attributes the comparison to.
    counts = {
        name: payload["arms"][name]["positions_drafted"]
        for name in ("points_greedy", "audible_transform")
    }
    assert counts["points_greedy"] != counts["audible_transform"], counts

    # THIS ASSERTION USED TO PIN THE DEFECT, AND B7 INVERTED IT.
    #
    # It read `points_greedy QB > audible_transform QB` and called the gap "replacement level's
    # first-order effect in a one-QB league ... to demote QBs". That was an accurate
    # description of what the code did and a wrong description of what it should do. QBs were
    # demoted because `rostered_counts` gave a 1-QB league's quarterback starters-only depth --
    # QB8 in an eight-team room against a real market of 13 -- which put the baseline at a
    # startable quarterback and drove every QB's VORP down. B5 measured the cost at -68.0 of a
    # -66.7 gap; B7 fixed the rule and the demotion stopped.
    #
    # So the gate now asserts the CORRECTED behaviour: with QB priced against a realistic
    # baseline, the transform no longer takes fewer quarterbacks than raw points does. It is
    # still a real check -- a regression to starters-only depth pushes `audible_transform`
    # back below `points_greedy` and fails here -- and the composition must still differ
    # somewhere, which the assertion above requires.
    assert counts["audible_transform"].get("QB", 0) >= counts["points_greedy"].get("QB", 0), (
        f"audible_transform drafted FEWER quarterbacks than points_greedy: {counts}. That is "
        f"the pre-B7 defect returning: a QB baseline set at the starting-slot count demotes "
        f"every quarterback in a one-QB league. Check `replacement.NO_BENCH_DEPTH`."
    )


def test_the_committed_run_matches_its_config(committed) -> None:
    """The artifact must describe the run the config asks for, or it is a different run."""
    import tomllib

    if not CONFIG.exists():
        pytest.skip("no b4-transform.toml")
    raw = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert committed["run"] == raw["run"]["name"]
    assert committed["seasons"] == raw["run"]["seasons"]
    assert sorted(committed["arms"]) == sorted(raw["run"]["arms"])


def test_the_artifact_is_valid_json_under_its_comment_header(mods) -> None:
    """The file is a `#`-commented mobile summary followed by the payload. Both must parse."""
    _a, artifact, *_rest = mods
    if not ARTIFACT.exists():
        pytest.skip("no committed artifact")
    text = ARTIFACT.read_text(encoding="utf-8")
    body = "".join(line for line in text.splitlines(keepends=True) if not line.startswith("#"))
    json.loads(body)
    assert artifact.read(ARTIFACT)["run"] == "b4-transform"
