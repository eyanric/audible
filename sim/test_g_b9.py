"""GATES for B9, and the injections that prove each one can fail.

B9 REPLACED THE ROOM'S CLASSIFIER, which is the third one this project has had, and
parameterised room validation over every declared market. Both halves have the same motive: a
number measured in one room, against one market, was being read as a fact about the harness.

WHAT THE TWO PREDECESSORS GOT WRONG, because a third classifier that does not say why the
first two failed is just a fourth guess waiting to happen:

  THE CORRELATION TEST keyed on corr(ADP rank, actual pick) and was refuted twice -- it is
  INVARIANT to the 8/12 rescaling the two-clock story is about, and its gap between skill and
  specialist positions reverses under range restriction.

  THE SUPPLY RATIO counted drafted / available in the top 128. Its numerator is a whole
  eight-team draft and its denominator is the market board's top 128 by rank, and those two
  windows only correspond when the market's team count DIFFERS from the room's. On a
  twelve-team board rank 128 is round 10.7, before a kicker goes; on an eight-team board rank
  128 IS the draft. So it collapses toward 1.0 exactly when the market fits the league -- WR
  1.111 against DEF 1.105 on mfl_8_std, a separation of 1.005 on the wrong side of its cut.

  THE CLOCK RATIO is sd(pick) / sd(pick - rank). It reads no window and conditions on nothing.
  The tests below re-run BOTH refutations against it rather than assuming they do not apply,
  and one of them partly lands: see `test_the_range_restriction_refutation_partly_applies`.

WHAT THIS FILE DOES NOT CLAIM. It does not claim the two MFL rooms are valid. They are not --
mfl_12_std misses `first QB round` by 0.04 of a round and mfl_8_std under-disperses the
pick-ADP spread. Those verdicts live in `sim/test_g_room.py`'s ROOM_FACTS, measured and
asserted per market, and they are the B9 deliverable rather than something this file hides.
"""

from __future__ import annotations

import statistics as st
from pathlib import Path

import pytest

from . import markets, room

REPO = Path(__file__).resolve().parents[1]
MARKETS = tuple(sorted(markets.REGISTRY))


@pytest.fixture(scope="module")
def joined() -> dict[str, dict[str, list[tuple[float, float]]]]:
    """(pick, rank) pairs per position per market: the classifier's entire input."""
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    out: dict[str, dict[str, list[tuple[float, float]]]] = {}
    identity = room.espn_identity()
    for name in MARKETS:
        with markets.use(name):
            nicks = room.nick_to_abbr()
            rows: dict[str, list[tuple[float, float]]] = {}
            for season in room.SEASONS:
                index = room.load_board(season).by_key()
                for pick in room.load_real_draft(season, identity):
                    hit = index.get(room.pick_join_key(pick, nicks))
                    if hit is not None:
                        rows.setdefault(pick.position, []).append(
                            (float(pick.overall), float(hit.rank))
                        )
        out[name] = rows
    return out


def _ratio(pairs: list[tuple[float, float]], scale: float = 1.0) -> float:
    resid = st.pstdev([p - scale * r for p, r in pairs])
    return st.pstdev([p for p, _ in pairs]) / resid if resid else float("inf")


# --- G1: the classifier ---------------------------------------------------------------------


@pytest.mark.parametrize("market", MARKETS)
def test_g1_the_classifier_derives_the_leagues_own_scheduled_set(market) -> None:
    """G1, the session's acceptance criterion, in every market.

    Both sides derived and from different inputs: the classifier reads picks and ranks, the
    expectation reads `STARTING_SLOTS`. They share nothing, so agreement is evidence.
    """
    with markets.use(market):
        fit = room.fit_room()
    assert set(fit.scheduled) == set(room.expected_scheduled()), (
        f"{market}: derived {sorted(fit.scheduled)}, league slots imply "
        f"{sorted(room.expected_scheduled())}"
    )


def test_g1_the_cut_is_not_doing_the_work_in_any_market(joined) -> None:
    """The worst separation across all three markets, in one place.

    The retired supply ratio managed 1.005x on mfl_8_std, on the wrong side. This asserts the
    clock ratio's worst case is a real gap rather than a coin flip, pooled over every market at
    once so a single bad market cannot hide behind two good ones.
    """
    worst_board, worst_sched = float("inf"), 0.0
    for market in MARKETS:
        with markets.use(market):
            expected = set(room.expected_scheduled())
        for pos, pairs in joined[market].items():
            ratio = _ratio(pairs)
            if pos in expected:
                worst_sched = max(worst_sched, ratio)
            else:
                worst_board = min(worst_board, ratio)
    assert worst_sched < room.CLOCK_RATIO_CUT <= worst_board
    assert worst_board / worst_sched >= 2.0, (
        f"the two regimes are only {worst_board / worst_sched:.2f}x apart across all markets "
        f"(worst board {worst_board:.3f}, worst scheduled {worst_sched:.3f})"
    )


# --- the two refutations, re-run rather than assumed away -------------------------------------


def test_the_rescaling_refutation_does_not_apply(joined) -> None:
    """REFUTATION 1, re-run. The correlation test died because it could not SEE the rescaling.

    Multiply every rank by c and re-classify. `r` agrees to six decimal places under that
    transform, which is why it could not tell the two clocks apart. The clock ratio is not
    invariant -- sd(pick - c*rank) moves with c -- and that is the point rather than a flaw.
    What matters is whether the verdicts survive the range of c that could plausibly be in
    play. c = 8/12 is the one the two-clock story is actually about: a twelve-team board
    rescaled into eight-team rounds.

    Measured: at c = 2/3 every verdict is unchanged and every margin IMPROVES.

    THE FLIP POINT IS ASSERTED, not just the safe side. Adversarial review pointed out that
    probing only c <= 1.0 is a test that cannot fail -- every probe sits on the safe side by
    construction, so a regression drifting toward the cut would stay green. The flip point has
    a closed form, c* = 2 * slope, and the nearest board position in any market is WR on
    mfl_8_std at c* = 1.241. Asserting a FLOOR under that is what makes this a measurement.
    """
    for market in MARKETS:
        with markets.use(market):
            expected = set(room.expected_scheduled())
        for c in (0.5, 2.0 / 3.0, 0.8, 1.0):
            derived = {p for p, pairs in joined[market].items() if _ratio(pairs, c) < 1.0}
            assert derived == expected, (
                f"{market} at rank scale c={c:.2f} derives {sorted(derived)}, not "
                f"{sorted(expected)}"
            )

    # The flip point itself. c* = 2 * slope for a board position; below 1.20 the classifier
    # would be one modest rescale away from scheduling a receiver.
    worst = min(
        (2.0 * st.correlation([r for _, r in pairs], [p for p, _ in pairs])
         * st.pstdev([p for p, _ in pairs]) / st.pstdev([r for _, r in pairs]), market, pos)
        for market in MARKETS
        for pos, pairs in joined[market].items()
        if pos not in {"K", "DEF"}
    )
    assert worst[0] >= 1.20, (
        f"the nearest board position to flipping is {worst[1]}/{worst[2]} at c*={worst[0]:.3f}; "
        f"below 1.20 a rank rescale the size of the gap between two of these markets would "
        f"schedule a skill position"
    )


def test_the_range_restriction_refutation_partly_applies(joined) -> None:
    """REFUTATION 2, re-run -- AND IT LANDS. This is a limitation, recorded as one.

    Restricted to the specialists' own (rank, pick) box, EVERY position reads below the cut,
    skill positions included. That is the same family of failure that killed the correlation
    test, so it is asserted here rather than left for someone else to find.

    It is mechanical rather than substantive: the box is about 46 picks wide and 120-206 ranks
    wide, so sd(rank)/sd(pick) is inflated by the box's aspect ratio and pushes everything under
    the cut by construction. The consequence is a rule, not a caveat: THE CUT IS ONLY MEANINGFUL
    ON A POSITION'S UNCONDITIONED POPULATION, which is what `fit_room` uses. This test exists so
    that anyone who later adds a conditional to the classifier finds out what it costs.
    """
    landed = []
    for market in MARKETS:
        with markets.use(market):
            expected = set(room.expected_scheduled())
        spec = [p for pos in expected for p in joined[market].get(pos, [])]
        lo_r, hi_r = min(r for _, r in spec), max(r for _, r in spec)
        lo_p, hi_p = min(p for p, _ in spec), max(p for p, _ in spec)
        for pos, pairs in joined[market].items():
            if pos in expected:
                continue
            inside = [(p, r) for p, r in pairs if lo_r <= r <= hi_r and lo_p <= p <= hi_p]
            if len(inside) >= 3 and _ratio(inside) < room.CLOCK_RATIO_CUT:
                landed.append(f"{market}:{pos}")
    assert landed, (
        "range restriction no longer moves any board position below the cut. That would be "
        "good news, but this test records a KNOWN limitation -- if it has genuinely gone away "
        "the docstring above is now wrong and must be rewritten rather than deleted."
    )


def test_the_supply_ratio_is_computed_and_reported_but_decides_nothing(joined) -> None:
    """The retired classifier stays on the page, exactly as the correlation already does.

    And on mfl_8_std it must still DISAGREE with the shipped one, because that disagreement is
    the whole reason B9 exists. If it stops disagreeing, the defect is no longer reproducible
    and the argument for the replacement has lost its evidence.
    """
    disagreements = {}
    for market in MARKETS:
        with markets.use(market):
            fit = room.fit_room()
        would = {p for p, r in fit.supply_ratio.items() if r > room.SUPPLY_RATIO_CUT}
        assert fit.supply_ratio, f"{market}: the retired diagnostic stopped being computed"
        if would != set(fit.scheduled):
            disagreements[market] = sorted(would ^ set(fit.scheduled))
    assert disagreements == {"mfl_8_std": ["RB", "WR"]}, disagreements


# --- G4: no market-specific literal decides anything -------------------------------------------


def test_g4_the_scheduled_set_is_derived_and_not_a_literal() -> None:
    """INJECTION 2 from the handoff, in the only form that can actually fail.

    A grep for `{"DEF", "K"}` in `room.py` proves nothing: the expectation legitimately
    evaluates to that set, and a hardcoded branch can be written without the literal. What
    distinguishes derivation from a constant is that the derivation MOVES when its input moves.
    `expected_scheduled` reads `STARTING_SLOTS`, so a league with no kicker slot must stop
    expecting a kicker.
    """
    assert room.expected_scheduled() == {"DEF", "K"}
    original = room.STARTING_SLOTS
    try:
        room.STARTING_SLOTS = tuple(s for s in original if s != "K")
        assert room.expected_scheduled() == {"DEF"}, (
            "removing the kicker slot did not change the expected scheduled set, so it is a "
            "literal wearing a function's clothes"
        )
    finally:
        room.STARTING_SLOTS = original
    assert room.expected_scheduled() == {"DEF", "K"}


def test_g4_the_classifier_moves_when_its_input_moves(joined) -> None:
    """The other half: the DERIVED side must be a measurement too.

    Swap each position's picks for its ranks and every verdict must flip -- a board position
    whose pick tracks its rank becomes one whose rank tracks its pick. A classifier that
    returned a constant would not notice.
    """
    for market in MARKETS:
        with markets.use(market):
            expected = set(room.expected_scheduled())
        flipped = {
            p for p, pairs in joined[market].items()
            if _ratio([(r, p_) for p_, r in pairs]) < room.CLOCK_RATIO_CUT
        }
        assert flipped != expected, (
            f"{market}: swapping pick and rank left the verdict at {sorted(flipped)}, so the "
            f"classifier is not reading its input"
        )


# --- injection 5: the market reaches the draft, not only the report ----------------------------


def test_i5_the_same_seed_in_two_markets_drafts_differently() -> None:
    """Handoff injection 5. If the market only reached the REPORT, this would be identical."""
    digests = {}
    for market in MARKETS:
        with markets.use(market):
            fit = room.fit_room()
            digests[market] = room.draft_digest(
                room.simulate_draft(room.load_board(2024), fit, 11)
            )
    assert len(set(digests.values())) == len(MARKETS), digests


@pytest.mark.parametrize("market", MARKETS)
def test_i5_the_same_seed_in_one_market_drafts_identically(market) -> None:
    """The control for the above: the difference has to be the MARKET and not the run."""
    with markets.use(market):
        fit = room.fit_room()
        board = room.load_board(2024)
        a = room.draft_digest(room.simulate_draft(board, fit, 11))
        b = room.draft_digest(room.simulate_draft(board, fit, 11))
    assert a == b


# --- G6a: the null control's premise -----------------------------------------------------------


def test_g6a_the_null_controls_premise_is_a_contrast_that_sums_to_zero() -> None:
    """G6a asserts a bot in seat 6 must score the field average "by symmetry". It must not.

    TWO REASONS, AND B9 MEASURED BOTH. A snake draft gives every seat the same SUM of pick
    numbers -- the +8s the odd rounds hand seat s are cancelled by the -8s the even rounds take
    back -- but not the same DISTRIBUTION: seat 1 takes picks 1 and 16 where seat 8 takes 8 and
    9, and draft value is not linear in pick number. And the statistic is a CONTRAST, seat minus
    the mean of the other seven, so the eight of them are algebraically constrained to sum to
    zero. "The eight average to zero" is guaranteed; "seat 6 is zero" is not implied by anything.

    This asserts the algebra, which is what makes the measurement in
    `sim/runs/b9-classifier.md` interpretable: measured at every seat, one of twenty-four
    seat-market intervals excluded zero on seeds 0-59 and a different one did on seeds 500-559,
    which is the 5% a 95% interval is supposed to produce.
    """
    # Every seat's pick numbers, from the room's own snake.
    per_seat: dict[int, list[int]] = {}
    for overall in range(1, room.PICKS + 1):
        rnd = (overall - 1) // room.TEAMS + 1
        slot = (overall - 1) % room.TEAMS
        who = slot + 1 if rnd % 2 == 1 else room.TEAMS - slot
        per_seat.setdefault(who, []).append(overall)

    sums = {s: sum(v) for s, v in per_seat.items()}
    assert len(set(sums.values())) == 1, (
        f"the snake does not equalise the sum of pick numbers: {sums}. The premise that the "
        f"seats are exchangeable would be even weaker than B9 measured."
    )
    # ...but the distributions differ, which is what makes value non-exchangeable.
    firsts = {s: v[0] for s, v in per_seat.items()}
    assert len(set(firsts.values())) == room.TEAMS, firsts
    # And the contrast sums to zero for ANY assignment of values to seats, which is why a
    # single seat's contrast has no reason to be zero.
    values = {s: float(s * s) for s in per_seat}  # any non-constant assignment will do
    contrasts = [
        values[s] - st.mean([v for t, v in values.items() if t != s]) for s in sorted(values)
    ]
    assert abs(sum(contrasts)) < 1e-9
    assert max(contrasts) > 0 > min(contrasts), (
        "a non-constant per-seat value produced no positive and negative contrasts, so this "
        "test is not exercising the algebra it claims to"
    )


# --- G5: the injections, per market ------------------------------------------------------------


# WHICH INJECTIONS FIRE IN WHICH MARKET, measured. `room.inject` returns False when the
# injection FIRED -- the corrupted room went red, which is the outcome that says the gates
# work -- so `True` here means the corruption was NOT detected.
#
# SEVENTEEN OF EIGHTEEN FIRE. The one that does not is `adp-only` on mfl_8_std, and the reason
# is the same fact B9 is built on, seen from a third angle: the injection reproduces the
# known-bad model in which a room drafts strictly by ADP and collapses the specialists. On
# FFC's twelve-team board that collapse is total, because its top 128 holds no kicker at all.
# On MFL's EIGHT-team board, strict ADP takes 11-16 specialists against a real 16-17 and lands
# inside the range -- so there is no defect there for the injection to reproduce.
#
# Read plainly: the pick schedule exists to correct a board/room TEAM-COUNT MISMATCH. Where the
# market already matches the league, the correction is not doing much, and an injection that
# removes it cannot go red. That is a limit on injection COVERAGE in that market, and it is
# recorded rather than papered over.
INJECTION_FIRES: dict[str, dict[str, bool]] = {
    "ffc_12_std": dict.fromkeys(room.INJECTIONS, True),
    "mfl_12_std": dict.fromkeys(room.INJECTIONS, True),
    "mfl_8_std": {**dict.fromkeys(room.INJECTIONS, True), "adp-only": False},
}


@pytest.mark.parametrize("market", MARKETS)
@pytest.mark.parametrize("injection", room.INJECTIONS)
def test_g5_each_injection_fires_where_it_was_measured_to(injection, market) -> None:
    """G5. Every injection, every market, against what was measured -- not against a hope."""
    with markets.use(market):
        _lines, ok = room.inject(injection, seeds=12)
    fired = not ok
    assert fired is INJECTION_FIRES[market][injection], (
        f"{market} / {injection}: fired={fired}, recorded "
        f"{INJECTION_FIRES[market][injection]}"
    )


def test_g5_the_only_injection_that_does_not_fire_is_the_one_that_cannot() -> None:
    """Guard on the table above: exactly one hole, and it is the one B9 explained.

    If a second injection ever stops firing, this goes red even though the parameterised test
    above would have been quietly updated to match. A table of measurements needs something
    watching its shape.
    """
    holes = sorted(
        (market, name)
        for market, row in INJECTION_FIRES.items()
        for name, fires in row.items()
        if not fires
    )
    assert holes == [("mfl_8_std", "adp-only")], holes


def test_g5_the_adp_only_hole_is_the_board_and_not_the_room() -> None:
    """WHY that hole exists, asserted rather than asserted-about.

    The injection cannot fire because strict ADP already lands inside the real specialist
    range on this board. That is a property of the BOARD's composition, so it is checked
    against the board rather than against the injection's exit code.
    """
    with markets.use("mfl_8_std"):
        boards = {s: room.load_board(s) for s in room.SEASONS}
        identity = room.espn_identity()
        nicks = room.nick_to_abbr()
        naive = [room.adp_only_stats(boards[s]).kdef_in_128 for s in room.SEASONS]
        real = [room.real_stats(s, identity, nicks).kdef_in_128 for s in room.SEASONS]
    assert max(naive) >= min(real), (
        f"strict ADP took {naive} against a real floor of {min(real)}; it now undershoots, so "
        f"the adp-only injection should fire on mfl_8_std and the table above is stale"
    )


# --- D1: G7 must FIRE on a thin fit, not raise ---------------------------------------------


def test_g7_reports_rather_than_raising_when_a_position_is_unclassified() -> None:
    """A thin fit must make G7 FIRE. It used to make `gate_failures` raise.

    `fit_room` writes `inf` for a position it cannot classify and `artifact._clean` turns that
    into the STRING "inf" so the payload stays JSON-safe. G7's message builder then did
    `f"{value:.3f}"` on it and raised ValueError -- and because `gate_failures` is called bare,
    that aborted the ENTIRE gate list, so G0, G5, G6a, G6b and G9 never evaluated either. The
    run died on a traceback in exactly the configuration that most needs a gate: a fit window
    too thin to determine the room's structure.

    Reachable from a config `runner.load_config` accepts, which is what made it a defect rather
    than a hypothetical.
    """
    from . import artifact, runner

    with markets.use("ffc_12_std"):
        thin = room.fit_room((2023,))
    assert thin.clock_unclassified, "2023 alone now classifies every position; pick a thinner fit"
    assert not thin.scheduled, (
        "an unclassified position reached the scheduled set; it must never be scheduled"
    )

    block = artifact.fit_block(thin)
    assert any(isinstance(v, str) for v in block["clock_ratio"].values()), (
        "no clock ratio survived `_clean` as a string, so this test is no longer exercising "
        "the shape that raised"
    )
    payload = artifact.read(REPO / "sim" / "runs" / "b9-ffc.json")
    payload["fit"] = block
    failures = runner.gate_failures(payload)  # must not raise
    assert any(f.startswith("G7 room-fidelity") for f in failures), failures


def test_a_thin_fit_refuses_to_guess_rather_than_scheduling_a_quarterback() -> None:
    """The D2 half. A single-season fit must classify NOTHING, not schedule the quarterback.

    Measured before the bootstrap guard existed: on a 2022-only fit both MFL markets put QB at
    a ratio of about 0.80 on twelve joined picks -- clearing the old `MIN_CLOCK_N` of 10 -- and
    scheduled him, which removes every quarterback from the board the bots draft off in a
    one-QB league. That is the B8 catastrophe reproduced by a legal config. The bootstrap
    interval on that cell is [0.528, 1.840], which contains the cut and both regimes.
    """
    for market in MARKETS:
        with markets.use(market):
            thin = room.fit_room((2022,))
        assert "QB" not in thin.scheduled, (
            f"{market}: a single-season fit scheduled the quarterback, which takes every QB "
            f"off the board in a one-QB league"
        )
        assert not thin.scheduled, f"{market}: thin fit scheduled {sorted(thin.scheduled)}"


def test_the_sample_floor_is_bracketed_rather_than_tuned() -> None:
    """MIN_CLOCK_N must be a window, not a number somebody liked.

    The requirement has two ends and both are measured: a single-season fit puts the
    quarterback at n=12-14 and must be REFUSED (scheduling him removes every QB from the board
    in a one-QB league), while a leave-one-season-out fit's thinnest cell is n=27-32 and must
    be ADMITTED (`room.holdout` refits on four seasons, and the held-out battery is the
    evidence that counts). So any floor in (14, 27] does the same job.

    This asserts that EVERY floor in that window gives the identical pooled and leave-one-out
    verdict in all three markets. If it does, where the constant sits inside the window changes
    nothing, which is what distinguishes bracketing from tuning.
    """
    assert 14 < room.MIN_CLOCK_N <= 27, room.MIN_CLOCK_N
    original = room.MIN_CLOCK_N
    try:
        for floor in range(15, 28):
            room.MIN_CLOCK_N = floor
            for market in MARKETS:
                with markets.use(market):
                    expected = set(room.expected_scheduled())
                    assert set(room.fit_room().scheduled) == expected, (
                        f"floor {floor}: {market} pooled fit derives "
                        f"{sorted(room.fit_room().scheduled)}"
                    )
                    for held in room.SEASONS:
                        kept = tuple(s for s in room.SEASONS if s != held)
                        assert set(room.fit_room(kept).scheduled) == expected, (
                            f"floor {floor}: {market} holding out {held} derives "
                            f"{sorted(room.fit_room(kept).scheduled)}"
                        )
    finally:
        room.MIN_CLOCK_N = original


def test_a_floor_low_enough_to_admit_the_quarterback_breaks_the_room() -> None:
    """The other end of the bracket, as an injection: the old floor of 10 reproduces the defect."""
    original = room.MIN_CLOCK_N
    try:
        room.MIN_CLOCK_N = 10
        scheduled_qb = []
        for market in MARKETS:
            with markets.use(market):
                for season in room.SEASONS:
                    if "QB" in room.fit_room((season,)).scheduled:
                        scheduled_qb.append(f"{market}:{season}")
    finally:
        room.MIN_CLOCK_N = original
    assert scheduled_qb, (
        "a floor of 10 no longer schedules the quarterback on any single-season fit, so the "
        "defect MIN_CLOCK_N was raised to prevent is no longer reproducible and the bracket "
        "above has lost its lower end"
    )
