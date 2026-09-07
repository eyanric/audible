"""GATES G1-G5 for the opponent room, plus the four failure injections.

The room is the thing every later measurement happens inside, and a wrong room fails
silently -- every number it produces is well-formed and means nothing. So it is gated before
it is used, against statistics chosen and written down before the first synthetic draft ran.

WHAT THESE CAN AND CANNOT SAY, stated here rather than left to be inferred:

* The IN-SAMPLE comparison (synthetic mean inside the real five-season range) is what the
  handoff pre-registered, and the room passes all six. But three of the six are quantities
  the fit targets -- ``first K round`` and ``first DEF round`` come out of the fitted pick
  schedule, and ``pick-ADP spread`` is what sigma is fitted to. Passing those in-sample is
  self-consistency and is reported as such.
* The HELD-OUT comparison is the one that is evidence. Refit on four seasons, draft the
  fifth, ask whether that season's real value falls inside the synthetic 5th-95th band. The
  held season contributed nothing to any parameter.
* Two statistics are free of the fit either way: ``first QB round`` and ``runs of 3+``.
  Nothing in the fit targets them.

These gates run against pinned files. They SKIP, loudly and by name, when a file is absent
-- there is no fixture substitute for a completed draft, and a gate that quietly passed on
an empty board would be worse than one that did not run.
"""

from __future__ import annotations

import statistics as st
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]

# Enough drafts per season that `first QB round` -- the tightest of the two statistics free
# of the fit -- clears the real lower bound by more than one standard error. It is the one
# that flips: at 8 and 10 seeds it reads 2.95 and 2.92 against a real floor of 3.0 and the
# verdict goes red; at 20 it is 3.07 (+0.5 sem) and at 50 it is 3.08 (+1.0 sem). `runs of 3+`
# is comfortable throughout (8.51 at 20 seeds, 8.36 at 50, against a real 8-11).
# 50 x 5 seasons = 250 drafts, well under a second. The seed set is fixed, so this is
# reproducible rather than merely large.
SEEDS = 50


def _require(name: str) -> Path:
    for root in (SIM_CACHE, LIVE_CACHE):
        if (root / name).exists():
            return root / name
    pytest.skip(f"{name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}")


@pytest.fixture(scope="module")
def room():
    """The fit and the boards, built once. Skips by name when an input is missing."""
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    from . import room as R

    _require("nflverse/ff_playerids.parquet")
    _require("nflverse/teams.parquet")
    for season in R.SEASONS:
        _require(f"ffc_adp_standard_8_{season}.json")
        _require(f"espn_draft_{R.LEAGUE_ID}_{season}.json")

    fit = R.fit_room()
    boards = {s: R.load_board(s) for s in R.SEASONS}
    identity = R.espn_identity()
    nicks = R.nick_to_abbr()
    real = {s: R.real_stats(s, identity, nicks) for s in R.SEASONS}
    synthetic = [
        R.sim_stats(R.simulate_draft(boards[s], fit, seed))
        for s in R.SEASONS
        for seed in range(SEEDS)
    ]
    return R, fit, boards, real, synthetic


# --- CONTROLS ----------------------------------------------------------------------------
# Each gate below asserts a property of the ROOM. These assert properties of the INPUTS, so
# a red gate can never be blamed on a board that was not what it claimed to be.


def test_control_every_real_pick_resolves_to_a_position_and_almost_all_join(room) -> None:
    """Two counts, because the first cannot see the second.

    `fit.total` counts picks BEFORE the join, so it is blind to a join that silently drops a
    position -- mutation testing confirmed it: breaking the D/ST join entirely leaves this
    number at 640 while `fit.joined` falls by 38. Both are asserted.
    """
    R, fit, _boards, _real, _syn = room
    assert fit.total == len(R.SEASONS) * R.PICKS, (
        f"expected {len(R.SEASONS) * R.PICKS} real picks, got {fit.total}"
    )
    assert fit.joined >= 615, (
        f"only {fit.joined}/{fit.total} picks joined to a board row; B1 shipped at 622 and a "
        f"drop of that size means a join broke, not that the market moved"
    )
    for position, n in fit.position_n.items():
        assert n > 0, f"{position} joined zero picks; the join dropped a whole position"
    assert fit.position_n["DEF"] >= 35, (
        f"DEF joined only {fit.position_n['DEF']} picks. The nickname collision in "
        f"nick_to_abbr is the way this breaks: teams.parquet holds 36 rows for 32 franchises "
        f"and a last-wins map sends Rams to STL, which no FFC board uses."
    )


def test_control_the_adp_files_are_twelve_team_whatever_their_name_says(room) -> None:
    """The premise the whole two-clock finding rests on, checked rather than repeated."""
    import json

    R, _fit, _boards, _real, _syn = room
    for season in R.SEASONS:
        path, _root = R.resolve_input(f"ffc_adp_standard_8_{season}.json")
        meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
        assert meta["teams"] == R.ADP_TEAMS, (
            f"{season} FFC file reports teams={meta['teams']}, not {R.ADP_TEAMS}. The "
            f"specialist offset and the 8/12 corroboration both assume twelve."
        )


def test_control_relocated_franchises_resolve_to_the_abbreviation_ffc_uses(room) -> None:
    """The join bug that shipped once. Three nicknames map to more than one abbreviation."""
    R, _fit, _boards, _real, _syn = room
    nicks = R.nick_to_abbr()
    known = R.ffc_defence_abbrs()
    assert nicks["Rams"] == "LAR", nicks["Rams"]
    assert nicks["Chargers"] == "LAC", nicks["Chargers"]
    assert nicks["Raiders"] in ("LV", "OAK"), nicks["Raiders"]
    # Every abbreviation FFC has ever used must be reachable from some nickname, or a
    # defence on the board can never be joined to the pick that took it.
    assert known <= set(nicks.values()), sorted(known - set(nicks.values()))


def test_control_both_espn_leagues_have_the_same_roster_shape(room) -> None:
    """6012's drafts are evidence for Green Hope only while the two rooms are the same shape."""
    from audible.config import load_league

    R, _fit, _boards, _real, _syn = room
    a = load_league(REPO / "leagues" / "espn_davis_drive.toml")
    b = load_league(REPO / "leagues" / "espn_green_hope.toml")
    assert list(a.starting_slots) == list(b.starting_slots) == list(R.STARTING_SLOTS)
    assert a.num_teams == b.num_teams == R.TEAMS
    assert a.draft_rounds == b.draft_rounds == R.ROUNDS


def test_control_the_board_is_deep_enough_to_run_a_draft(room) -> None:
    R, _fit, boards, _real, _syn = room
    for season, board in boards.items():
        assert len(board.rows) >= R.PICKS, (
            f"{season} board holds {len(board.rows)}; a {R.TEAMS}x{R.ROUNDS} draft needs "
            f"{R.PICKS}"
        )


# --- G1: the fit is fitted ---------------------------------------------------------------


def test_g1_sigma_is_measured_and_moves_when_the_sample_moves(room) -> None:
    """A hardcoded constant is a failed gate. Drop a season and every sigma must react."""
    R, fit, _boards, _real, _syn = room
    subset = R.fit_room([s for s in R.SEASONS if s != 2021])
    moved = sum(
        1
        for pos in fit.sigma
        for b, _lo, _hi in R.BUCKETS
        if abs(fit.sigma[pos][b] - subset.sigma[pos][b]) > 1e-9
    )
    assert moved >= len(fit.sigma), (
        f"only {moved} sigma cells changed when a season was removed; a fitted sigma cannot "
        f"be insensitive to its sample"
    )
    assert all(
        0.0 < fit.sigma[pos][b] < 200.0 for pos in fit.sigma for b, _l, _h in R.BUCKETS
    )


def test_g1_the_pick_schedule_is_measured_and_moves_too(room) -> None:
    R, fit, _boards, _real, _syn = room
    # Without this the loop below is vacuous whenever the classifier returns nothing, and a
    # broken classifier would make this test PASS having asserted nothing at all.
    assert fit.scheduled, "no position is scheduled; the loop below would assert nothing"
    subset = R.fit_room([s for s in R.SEASONS if s != 2024])
    for pos in fit.scheduled:
        assert abs(fit.pick_mu[pos] - subset.pick_mu[pos]) > 1e-9
        assert abs(fit.pick_sd[pos] - subset.pick_sd[pos]) > 1e-9


def test_g1_which_clock_a_position_is_on_is_a_count_with_a_wide_margin(room) -> None:
    """The split has to hold in EVERY season, not just pooled, or the cut is doing the work."""
    R, fit, _boards, _real, _syn = room
    assert fit.scheduled == frozenset({"K", "DEF"}), f"unexpected split: {fit.scheduled}"
    sched = [fit.supply_ratio[p] for p in fit.scheduled]
    board = [fit.supply_ratio[p] for p in fit.supply_ratio if p not in fit.scheduled]
    assert min(sched) > R.SUPPLY_RATIO_CUT >= max(board)
    # Per season, not merely pooled. A position the room drafts more of than the board holds
    # cannot be coming off the board, and that has to be true every year for the split to be
    # a fact about the room rather than an average over five of them.
    worst_scheduled = min(min(fit.supply_by_season[p]) for p in fit.scheduled)
    best_board = max(
        max(fit.supply_by_season[p]) for p in fit.supply_ratio if p not in fit.scheduled
    )
    assert worst_scheduled > best_board, (
        f"per-season supply ratios overlap: worst scheduled {worst_scheduled:.2f}, best board "
        f"{best_board:.2f}. The cut is doing the work rather than the measurement."
    )
    assert worst_scheduled / R.SUPPLY_RATIO_CUT >= 2.0, (
        f"the tightest scheduled season is only {worst_scheduled:.2f}x the cut"
    )


def test_g1_the_correlation_is_reported_but_does_not_decide_anything(room) -> None:
    """It cannot: it is invariant to the rescale the two-clock story is about.

    Correlation with ADP rank equals correlation with the 8/12-rescaled rank to machine
    precision, because both clocks are linear in rank. A classifier keyed on it would be
    keyed on a statistic that cannot see the question, which is why this module classifies
    on a count instead. Asserted so nobody quietly wires it back up.
    """
    R, fit, _boards, _real, _syn = room
    identity = R.espn_identity()
    nicks = R.nick_to_abbr()
    scale = R.TEAMS / R.ADP_TEAMS
    ranks: dict[str, list[float]] = {}
    picks: dict[str, list[float]] = {}
    for season in R.SEASONS:
        index = R.load_board(season).by_key()
        for p in R.load_real_draft(season, identity):
            row = index.get(R.pick_join_key(p, nicks))
            if row is not None:
                ranks.setdefault(p.position, []).append(float(row.rank))
                picks.setdefault(p.position, []).append(float(p.overall))
    for pos, rs in ranks.items():
        plain, _ = R._pearson(rs, picks[pos])
        rescaled, _ = R._pearson([(r - 1) * scale + 1 for r in rs], picks[pos])
        assert abs(plain - rescaled) < 1e-9, (
            f"{pos}: correlation moved under the 8/12 rescale ({plain} vs {rescaled}); if "
            f"that is ever true it would be worth reconsidering"
        )


def test_g1_the_roster_caps_come_from_the_observed_maxima(room) -> None:
    R, fit, _boards, _real, _syn = room
    for pos, hist in fit.cap_hist.items():
        assert fit.caps[pos] == max(hist), f"{pos} cap {fit.caps[pos]} is not max({sorted(hist)})"
    assert sum(fit.cap_hist["K"].values()) == R.TEAMS * len(R.SEASONS)


# --- G2: room validation, pre-registered -------------------------------------------------


def test_g2_every_pre_registered_statistic_lands_in_the_real_range(room) -> None:
    R, _fit, _boards, real, synthetic = room
    failures = [
        f"{c.name}: synth {c.synthetic:.1f} outside real {c.real_lo:.1f}-{c.real_hi:.1f}"
        for c in R.compare(synthetic, list(real.values()))
        if not c.passes
    ]
    assert not failures, "; ".join(failures)


def test_g2_the_two_statistics_the_fit_does_not_target_also_land(room) -> None:
    """Stated separately because these are the only in-sample lines that are evidence."""
    R, _fit, _boards, real, synthetic = room
    free = [c for c in R.compare(synthetic, list(real.values())) if c.kind == "free"]
    assert {c.name for c in free} == {"first QB round", "runs of 3+"}
    assert all(c.passes for c in free), [
        (c.name, c.synthetic, c.real_lo, c.real_hi) for c in free if not c.passes
    ]


def test_g2_held_out_seasons_are_mostly_covered_and_the_misses_are_the_known_ones(room) -> None:
    """The honest test, and it does NOT come out clean. The misses are the deliverable.

    Refit without a season, draft that season's board, ask whether its real value falls in
    the synthetic 5-95 band. Three deficiencies show up and all three are named in the
    report rather than fixed, because closing a held-out miss by adding a mechanism is the
    definition of tuning a gate to pass:

      * K+DEF in 128 is exactly 16 in every synthetic draft and the real room took 17 in
        three of five seasons. The room has no mechanism for a second kicker or a second
        defence, which 3 of 80 real team-slot-seasons did take.
      * pick-ADP spread under-disperses in the two seasons with the deepest boards (2021 at
        224 rows and 27.5, 2025 at 221 and 26.8, against 2024's 180 rows and 20.6). Sigma is
        pooled across seasons and cannot express a season being looser than the average.
      * one single-season order statistic misses: 2023's first defence went in round 11 and
        the synthetic band is 12-14. The schedule is pooled across seasons like sigma is.
        2025 is the other season whose real first K and first D/ST both came in round 11, and
        it is covered -- so this is a near miss on a pooled schedule, not a 2023 anomaly.

    The exact miss list at SEEDS=50 is 2021 K+DEF, 2021 spread, 2023 first DEF, 2024 K+DEF,
    2025 K+DEF, 2025 spread -- six of thirty. It moves with the seed count because the band
    is a percentile over a finite sample, which is why the gate below is on the RATE.

    The gate is on the RATE, so a regression that broke the room broadly still fails here,
    while the three known misses do not turn it red every run.
    """
    R, _fit, _boards, _real, _syn = room
    covered = 0
    total = 0
    for _season, comps in R.holdout(seeds=SEEDS):
        for c in comps:
            total += 1
            covered += 1 if c.covers else 0
    assert total == len(R.SEASONS) * len(R.STAT_LABELS)
    # The bar sits one below the shipped baseline, not four. Mutation testing measured what
    # the loose version was worth: a room with the pick SCHEDULE OFF -- the single mechanism
    # B1 exists to add, and one the in-sample line calls a FAIL -- scored 22/30, and a room
    # with every mu sign flipped, drafting its first quarterback in round 1.6, scored exactly
    # 20. At 23 both go red and only total determinism collapse used to.
    assert covered >= 23, (
        f"only {covered}/{total} held-out season-statistics covered; the room was at 24/30 "
        f"when B1 shipped, and below 23 it is no longer the room that was validated"
    )


def test_g2_the_verdict_function_says_the_room_resembles_real(room) -> None:
    R, _fit, _boards, _real, _syn = room
    _lines, ok = R.report(seeds=SEEDS)
    assert ok


# --- G3: specialists behave --------------------------------------------------------------


def test_g3_specialist_picks_land_inside_the_real_range(room) -> None:
    R, _fit, _boards, real, synthetic = room
    real_kdef = [r.kdef_in_128 for r in real.values()]
    syn = st.mean([s.kdef_in_128 for s in synthetic])
    assert min(real_kdef) <= syn <= max(real_kdef), (
        f"K+DEF in 128: synth {syn:.1f}, real {min(real_kdef):.0f}-{max(real_kdef):.0f}"
    )


def test_g3_every_seat_finishes_holding_a_kicker_and_a_defence(room) -> None:
    """All forty real team-seasons did. Measured against ``deadline=False``: without the
    deadline 0-5 seats a draft finish with no kicker, and with the pick schedule off as well
    that is 0-6, mean 3.1.
    """
    R, fit, boards, _real, _syn = room
    for season in R.SEASONS:
        for seed in range(5):
            per: dict[int, Counter[str]] = {}
            for p in R.simulate_draft(boards[season], fit, seed):
                per.setdefault(p.seat, Counter())[p.position] += 1
            for seat, counts in per.items():
                assert counts["K"] >= 1 and counts["DEF"] >= 1, (
                    f"{season} seed {seed} seat {seat} finished with "
                    f"K={counts['K']} DEF={counts['DEF']}"
                )


def test_g3_every_seat_can_field_a_legal_starting_lineup(room) -> None:
    """The defect no draft-level statistic could see, and the reason the deadline is general.

    The positional TOTALS were already right when this was broken -- QB 12.8 synthetic
    against 13.0 real, TE 10.4 against 10.4 -- and only the ALLOCATION across seats was
    wrong: 34.8% of seats finished with no tight end or no quarterback, which none of forty
    real team-seasons did. Every pre-registered statistic is a draft-level aggregate, so all
    six stayed green through it. This gate reads a roster.
    """
    R, fit, boards, _real, _syn = room
    bad: list[str] = []
    for season in R.SEASONS:
        for seed in range(6):
            per: dict[int, list[str]] = {}
            for p in R.simulate_draft(boards[season], fit, seed):
                per.setdefault(p.seat, []).append(p.position)
            for seat, positions in per.items():
                roster = R._Roster()
                for position in positions:
                    roster.add(position)
                unfilled = roster.unfilled()
                if unfilled:
                    bad.append(f"{season} seed {seed} seat {seat} cannot fill {unfilled}")
    assert not bad, f"{len(bad)} seats cannot field a legal lineup, e.g. {bad[:3]}"


def test_g3_the_deadline_is_what_makes_that_true(room) -> None:
    """Control for the gate above: turn the deadline off and it must go badly wrong.

    Without this, that gate could be green because the room never had the problem.
    """
    R, fit, boards, _real, _syn = room
    illegal = 0
    total = 0
    for season in R.SEASONS:
        for seed in range(4):
            per: dict[int, list[str]] = {}
            for p in R.simulate_draft(boards[season], fit, seed, deadline=False):
                per.setdefault(p.seat, []).append(p.position)
            for positions in per.values():
                total += 1
                roster = R._Roster()
                for position in positions:
                    roster.add(position)
                illegal += 1 if roster.unfilled() else 0
    assert illegal / total > 0.2, (
        f"only {illegal}/{total} seats went illegal with the deadline off; if the room does "
        f"not need the deadline then the gate above is not testing anything"
    )


def test_g4_the_room_drafts_in_snake_order(room) -> None:
    """Mutation testing found this untested: a straight draft passed all 29 gates.

    Every pre-registered statistic is a whole-room aggregate, so none of them can see the
    seat order at all -- yet the seat order is the entire point of B2 and B3, which put
    audible in one specific seat. Two things are asserted: the order itself, and its
    consequence, which is that no seat gets a systematically better board position.
    """
    R, fit, boards, _real, _syn = room
    seats = [R.slot_on_clock(n, R.TEAMS) for n in range(1, R.TEAMS * 2 + 1)]
    assert seats == list(range(1, R.TEAMS + 1)) + list(range(R.TEAMS, 0, -1)), seats

    picks = R.simulate_draft(boards[2024], fit, 0)
    for p in picks:
        assert p.seat == R.slot_on_clock(p.overall, R.TEAMS)
    assert set(Counter(p.seat for p in picks).values()) == {R.ROUNDS}
    # The wheel: the last pick of a round and the first of the next belong to one seat.
    assert picks[R.TEAMS - 1].seat == picks[R.TEAMS].seat == R.TEAMS

    by_seat: dict[int, list[int]] = {}
    for season in R.SEASONS:
        for seed in range(4):
            for p in R.simulate_draft(boards[season], fit, seed):
                by_seat.setdefault(p.seat, []).append(p.rank)
    means = [st.mean(by_seat[s]) for s in sorted(by_seat)]
    assert max(means) - min(means) < 5.0, (
        f"mean board rank by seat spans {max(means) - min(means):.1f}; a snake should be "
        f"nearly flat, and the straight-draft mutation measured 5.7"
    )


def test_g3_beats_the_strict_adp_room_by_the_margin_that_was_measured(room) -> None:
    R, _fit, boards, real, synthetic = room
    naive = [R.adp_only_stats(boards[s]).kdef_in_128 for s in R.SEASONS]
    real_kdef = [r.kdef_in_128 for r in real.values()]
    syn = st.mean([s.kdef_in_128 for s in synthetic])
    assert max(naive) <= 4, f"strict-ADP took {max(naive)} specialists; the premise was 0-4"
    assert syn >= 4 * max(naive) or (max(naive) == 0 and syn > 0)
    assert abs(syn - st.mean(real_kdef)) < abs(st.mean(naive) - st.mean(real_kdef))


# --- G4: determinism ---------------------------------------------------------------------


def test_g2_a_position_never_taken_reads_as_outside_the_draft(room) -> None:
    """The strict-ADP room takes no kicker at all. That must not read as "took one late".

    Untested until mutation testing pointed at it: changing the sentinel from ``rounds + 1``
    to ``rounds`` broke nothing, because both call sites read only ``.kdef_in_128``.
    """
    R, _fit, boards, _real, _syn = room
    assert R._first_round([(1, 1, "RB")], "K", R.ROUNDS) == R.ROUNDS + 1
    for season in R.SEASONS:
        naive = R.adp_only_stats(boards[season])
        assert naive.first_k_round == R.ROUNDS + 1, (
            f"{season}: strict ADP took a kicker inside 128, which the premise says it never "
            f"does -- the first kicker on the board is at ADP rank 138-143"
        )


def test_g4_the_same_seed_produces_a_byte_identical_draft(room) -> None:
    R, fit, boards, _real, _syn = room
    for season in R.SEASONS:
        a = R.draft_digest(R.simulate_draft(boards[season], fit, 11))
        b = R.draft_digest(R.simulate_draft(boards[season], fit, 11))
        assert a == b, f"{season} is not reproducible from its seed"


def test_g4_a_rebuilt_board_does_not_change_the_draft(room) -> None:
    """The TASK 3 design answer, asserted rather than timed: the board is reusable."""
    R, fit, boards, _real, _syn = room
    a = R.draft_digest(R.simulate_draft(boards[2024], fit, 3))
    b = R.draft_digest(R.simulate_draft(R.load_board(2024), fit, 3))
    assert a == b


def test_g4_audibles_own_board_carries_no_draft_state(room) -> None:
    """The same question for the board B2 will actually put in the seat.

    ``DraftEntry`` and ``DraftBoard`` are frozen, and ``build_board_from_lines`` takes no
    picks, no roster and no pick number, so one board is safe to share across every seed of
    a sweep. Asserted here because B2 is going to rely on it and a later change that added a
    mutable field would otherwise be found by a wrong number rather than by a red test.
    """
    import dataclasses
    import inspect

    from audible.draft.board import DraftBoard, DraftEntry, build_board_from_lines

    assert dataclasses.fields(DraftEntry) and DraftEntry.__dataclass_params__.frozen
    assert DraftBoard.__dataclass_params__.frozen
    params = set(inspect.signature(build_board_from_lines).parameters)
    assert not (params & {"picks", "roster", "current_pick", "taken", "session"}), params


def test_i3_changing_the_seed_changes_the_draft(room) -> None:
    """Failure injection 3. Proves G4 tests determinism rather than a constant."""
    R, fit, boards, _real, _syn = room
    digests = {R.draft_digest(R.simulate_draft(boards[2024], fit, s)) for s in range(6)}
    assert len(digests) == 6, f"six seeds produced {len(digests)} distinct drafts"


# --- G5: no leakage ----------------------------------------------------------------------


def test_g5_every_board_passes_the_pre_draft_guard(room) -> None:
    R, _fit, boards, _real, _syn = room
    for season, board in boards.items():
        R.assert_pre_draft(board)
        assert board.asof < R.kickoff(season)
        assert set(board.provenance) <= R.PRE_DRAFT_SOURCES


def test_g5_the_kickoff_dates_are_the_real_ones(room) -> None:
    """The guard is only as good as the cutoff. FFC's 2025 sample closes three days before."""
    R, _fit, _boards, _real, _syn = room
    assert {s: R.kickoff(s) for s in R.SEASONS} == {
        2021: date(2021, 9, 9), 2022: date(2022, 9, 8), 2023: date(2023, 9, 7),
        2024: date(2024, 9, 5), 2025: date(2025, 9, 4),
    }


def test_i4_a_board_built_from_end_of_season_points_is_refused(room) -> None:
    """Failure injection 4. The leakage check, fired rather than asserted about.

    The board is built the way a leaky replay would build one -- rank every player by what
    he actually scored -- and handed to the guard and to the simulator.
    """
    import polars as pl

    R, fit, _boards, _real, _syn = room
    stats = _require("nflverse/player_stats_2024.parquet")
    frame = pl.read_parquet(stats).filter(pl.col("season_type") == "REG")
    totals = (
        frame.group_by("player_display_name", "position")
        .agg(pl.col("receiving_yards").sum().alias("y"))
        .sort("y", descending=True)
        .head(300)
    )
    rows = tuple(
        R.BoardRow(
            rank=i, adp=float(i), name=str(n), position=R.canon_position(p), team="XX",
            stdev=1.0, times_drafted=1,
        )
        for i, (n, p, _y) in enumerate(totals.iter_rows(), start=1)
    )
    leaky = R.SeasonBoard(
        season=2024, rows=rows, provenance=("player_stats_2024",),
        asof=date(2025, 2, 1), roots=("live",),
    )

    with pytest.raises(ValueError, match="non-pre-draft source"):
        R.assert_pre_draft(leaky)
    with pytest.raises(ValueError, match="non-pre-draft source"):
        R.simulate_draft(leaky, fit, 1)

    # And the date alone would stop it, so the allowlist is not the only line of defence.
    renamed = R.SeasonBoard(
        season=2024, rows=rows, provenance=("ffc_adp",), asof=date(2025, 2, 1), roots=("live",)
    )
    with pytest.raises(ValueError, match="not before that season"):
        R.assert_pre_draft(renamed)


# --- injections 1 and 2 -------------------------------------------------------------------


def test_i1_the_strict_adp_room_collapses_the_specialists(room) -> None:
    """Failure injection 1. Reproduces the known-bad model; this is the gate on G3.

    Two ablations, because they separate which mechanism does the work.

    Strict ADP order takes 0-4 specialists in 128 picks against a real 16-17 -- it cannot do
    otherwise, since no season has a single kicker inside the top 128 by ADP.

    Turning ONLY the pick schedule off, keeping the fitted noise, the caps and the deadline,
    breaks it in the OTHER direction and that is worth knowing. Back on the board clock the
    specialists carry mu = -54.4 and -44.7, which makes them look like top-60 players, so
    seats take them early and some take a second (the cap of 2 becomes binding for the first
    time). K+DEF lands ABOVE the real range and the first defence lands around round 8.1
    against a real 11-13. Either way it is out of range, and the schedule is what puts it
    back -- which is the claim G3 rests on.
    """
    R, fit, boards, real, _syn = room
    real_lo = min(r.kdef_in_128 for r in real.values())
    real_hi = max(r.kdef_in_128 for r in real.values())

    naive = [R.adp_only_stats(boards[s]).kdef_in_128 for s in R.SEASONS]
    assert max(naive) < real_lo, f"strict ADP took {naive}, which does not undershoot {real_lo}"
    assert max(naive) <= 4 and min(naive) == 0

    unscheduled = [
        R.sim_stats(R.simulate_draft(boards[s], fit, seed, schedule_specialists=False))
        for s in R.SEASONS
        for seed in range(4)
    ]
    kdef = st.mean([u.kdef_in_128 for u in unscheduled])
    first_def = st.mean([u.first_def_round for u in unscheduled])
    assert not real_lo <= kdef <= real_hi, (
        f"turning the pick schedule off left K+DEF at {kdef:.1f}, inside the real "
        f"{real_lo:.0f}-{real_hi:.0f}, so the schedule is not what G3 is measuring"
    )
    assert first_def < min(r.first_def_round for r in real.values()), (
        f"schedule off, the first defence still lands at round {first_def:.1f}; on the board "
        f"clock a -44.7 offset should pull it far earlier than the real 11-13"
    )


def test_i1_zero_sigma_alone_does_not_reproduce_the_bad_model(room) -> None:
    """The same injection run as the handoff words it, and the result is a finding.

    "Set sigma to 0 and bots draft strict ADP order" is true of a one-mechanism room and
    false of this one: with the noise off the pick schedule still runs, so the specialists
    still arrive. That is the point -- the noise was never what fixed G3.
    """
    R, fit, boards, real, _syn = room
    quiet = [
        R.sim_stats(R.simulate_draft(boards[s], fit, 0, sigma_scale=0.0)) for s in R.SEASONS
    ]
    real_lo = min(r.kdef_in_128 for r in real.values())
    assert st.mean([q.kdef_in_128 for q in quiet]) >= real_lo
    assert st.mean([q.delta_spread for q in quiet]) < st.mean(
        [r.delta_spread for r in real.values()]
    ), "sigma=0 did not narrow the pick-ADP spread, so sigma is not driving it"


def test_i2_a_very_large_sigma_breaks_the_room(room) -> None:
    """Failure injection 2. Blow the noise up and G2 must go red, not merely get worse."""
    R, fit, boards, real, _syn = room
    # Twenty seeds a season, not four. At four (n=20) `runs of 3+` estimates to +-0.5 and
    # lands inside the real 8-11 about as often as not, so the assertion below flickered once
    # B2's refinements added a little clustering back. At twenty (n=100) it reads 7.5 +-0.2,
    # which is 2.3 standard errors clear of the bound. The gate was right; its sample was not.
    wild = [
        R.sim_stats(R.simulate_draft(boards[s], fit, seed, sigma_scale=8.0))
        for s in R.SEASONS
        for seed in range(20)
    ]
    failures = [c for c in R.compare(wild, list(real.values())) if not c.passes]
    assert failures, "an 8x sigma passed every pre-registered statistic; the gates are inert"
    assert {"runs of 3+", "pick-ADP spread"} <= {c.name for c in failures}, (
        f"8x sigma failed on {[c.name for c in failures]}; expected the run frequency and "
        f"the spread to be the ones that break"
    )


# --- the injections as a process, with real exit codes ------------------------------------


@pytest.mark.parametrize(
    "name", ["adp-only", "no-schedule", "no-deadline", "wide-sigma", "leaky-board", "seed"]
)
def test_injections_fire_as_a_process_with_a_nonzero_exit(name: str) -> None:
    """A gate that passes on empty output proves nothing. Run them and read the exit code."""
    _require("nflverse/ff_playerids.parquet")
    proc = subprocess.run(
        [sys.executable, "-m", "sim.room", "--inject", name, "--seeds", "4"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 1, (
        f"injection {name} exited {proc.returncode}; it was supposed to fire.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    # A crash also exits 1, and prints nothing: `INJECTION FIRED` is only emitted by main()
    # after inject() returns, so this string is what separates the two. Measured -- an
    # uncaught exception gives exit 1 with zero bytes of stdout, a bad --inject name gives 2.
    assert "INJECTION FIRED" in proc.stdout, proc.stdout


def test_the_uncorrupted_room_passes_so_the_injections_mean_something(room) -> None:
    """An injection asserts "the corrupted room fails". That is worth nothing on its own.

    Mutation testing showed the exact failure mode: with the classifier broken so that
    nothing is scheduled, `--inject no-schedule` becomes a literal no-op and still exits 1,
    because the UNcorrupted room was already red. Every injection needs this precondition.
    """
    R, _fit, _boards, real, synthetic = room
    failures = [c.name for c in R.compare(synthetic, list(real.values())) if not c.passes]
    assert not failures, (
        f"the uncorrupted room already fails on {failures}; until that is fixed the "
        f"injections cannot distinguish a working gate from a broken subject"
    )
