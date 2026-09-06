"""G-CALL -- The Call ordered by board rank while `recommend` ordered by the scalar.

THE HANDOFF OFFERED TWO EXPLANATIONS AND BOTH ARE WRONG. It reasoned that since The Call
sorts by ``-need`` first, either that need term has its own occupancy bug or ``TOP_N = 12``
starves the sort by slicing the right answer away. Measured here, neither holds:

  * NEED REGISTERS OCCUPANCY CORRECTLY. With BoyFun's only `IDP_FLEX` filled, `_need_score`
    returns 0 for a second linebacker -- `roster_needs` reads the served roster block and
    `RosterNeed.short` is 0 for a slot that is full. `35e51342` works, on this surface too.
  * THE SLICE HELD THE RIGHT ANSWER. In the reported case the correct candidate sits at
    position 2 of the top-12 BY BOARD RANK, which each gate asserts directly. Swept: these
    gates go red at `TOP_N = 1` and stay green at 2, 3, 6 and 12. `TOP_N` is not what
    decided the BoyFun report.

BUT THE SLICE DOES STARVE THE ORDERING, IN A CASE NOBODY PROPOSED IT FOR -- see G-CALL-SLICE
at the foot of this file. Green Hope's board top is entirely running backs, so a roster
already deep at RB got twelve rows of the same surplus position and never saw the receiver
who scored twice as well. That is a second, separate defect with a separate fix: the cap now
counts the best PICKABLE candidates by the tool's own measure instead of the best twelve by a
measure the tool no longer sorts on. Both were real; neither was the other.

THE ACTUAL DEFECT IS THAT NEED CANNOT DISCRIMINATE INSIDE A TIER. `_need_score` answers "is
some short slot open to this position" -- 2, 1 or 0. Once the starting lineup is nearly full
the honest answer for almost everybody is 0, the leading key ties, and the ordering fell
through to ``s["player"]["vorp_rank"]``: raw board rank, the one number that knows nothing
about my roster. So a second linebacker with `IDP_FLEX` full beat a back one rank below him,
even though his `marginal_start_factor` was 0.05 -- he starts in approximately no weeks.

`recommend` got the same board right, because `audible#60` moved it to `effective_score`.
The two surfaces disagreed because `server/state.py::_the_call` rebuilds its candidate rows
by hand from `best_available` and named six fields, and the composed scalar -- attached to
those very rows three lines earlier by `_score_rows` -- was not one of them. A hand-built
projection silently drops what it does not name.

So the fix is not another occupancy fix and not a bigger slice. It is that both surfaces
read ONE number. `need` stays the leading key, because "a slot only he can fill" is a
different question from value and `marginal_start_factor` deliberately pays no bonus for
filling an empty slot; the scalar breaks ties WITHIN a need tier, which is where the ties
actually were.

EXPECTED: RED before the wiring, GREEN after. Each gate carries controls that must be GREEN
on both sides -- if a control flips, the fix broke a correct case rather than a wrong one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audible.config import load_league
from audible.config.loader import LEAGUES_DIR
from audible.draft.urgency import TOP_N, _need_score, roster_needs
from audible.server.state import build_state
from sim.harness import current_pick_after, entry, filler, service

BOYFUN = load_league(LEAGUES_DIR / "sleeper_boyfun.toml")
GREEN_HOPE = load_league(LEAGUES_DIR / "espn_green_hope.toml")

# Depth below anything a gate asserts on, so replacement baselines are not degenerate.
DEPTH = (
    ("wr", 40, "WR", 100), ("rb", 40, "RB", 200), ("te", 20, "TE", 300),
    ("qb", 20, "QB", 400), ("k", 10, "K", 500), ("df", 10, "DEF", 600),
    ("lb", 20, "LB", 700),
)


def _state(
    config: Any, tmp_path: Path, mine: list[tuple[str, str, str, int]],
    extra: list[tuple[str, str, str, int]],
) -> dict[str, Any]:
    """Build the page's own payload for a roster of *mine* with *extra* still available.

    `current_pick_after` rather than a hand-counted pick number: a seat that has not reached
    its Nth turn silently leaves the surplus ids ON THE BOARD, and the gate then measures a
    roster it did not build. That mistake was made twice writing this file.
    """
    entries = [entry(pid, name, pos, rank) for pid, name, pos, rank in (*mine, *extra)]
    for prefix, count, pos, first in DEPTH:
        entries += filler(prefix, count, pos, first)
    svc = service(
        config, tmp_path,
        current_pick=current_pick_after(len(mine), config.num_teams),
        entries=entries, my_player_ids=[m[0] for m in mine],
    )
    return build_state(svc)


def _slice(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The first `TOP_N` of the served pool IN BOARD ORDER -- what `the_call` used to look at.

    Deliberately still board order. The Call now caps on `effective_score` instead, and the
    controls below are about the OLD slice: they are what establishes that the reported
    defect was not a slicing problem, so they have to keep measuring the slice that was
    accused of it.
    """
    return state["best_available"][:TOP_N]


def _in_slice(state: dict[str, Any], player_id: str) -> bool:
    return any(p["id"] == player_id for p in _slice(state))


def _named(state: dict[str, Any]) -> dict[str, Any]:
    return state["the_call"].get("pick") or {}


# =====================================================================================
# G-CALL-BOYFUN -- the live report, reconstructed under the real BoyFun config
# =====================================================================================
#
# Every starting slot filled except K and DEF, which no board puts inside a top-12 by value.
# That is the state a draft is actually in by round 11, and it is the state in which every
# candidate's need score is 0.
BOYFUN_ROSTER = [
    ("my_qb", "My Quarterback", "QB", 3),
    ("my_rb1", "My Back One", "RB", 4),
    ("my_rb2", "My Back Two", "RB", 5),
    ("my_wr1", "My Receiver One", "WR", 6),
    ("my_wr2", "My Receiver Two", "WR", 7),
    ("my_wr3", "My Receiver Three", "WR", 8),
    ("my_te", "My Tight End", "TE", 9),
    ("my_wr4", "My Receiver Four", "WR", 10),      # FLEX
    ("my_qb2", "My Second Quarterback", "QB", 11),  # SUPER_FLEX
    ("my_lb", "My Linebacker", "LB", 12),           # IDP_FLEX -- the league's only IDP slot
]
BOYFUN_LB = ("lb_next", "Next Linebacker", "LB", 20)
BOYFUN_RB = ("rb_next", "Next Back", "RB", 21)


def _boyfun(tmp_path: Path) -> dict[str, Any]:
    return _state(BOYFUN, tmp_path, BOYFUN_ROSTER, [BOYFUN_LB, BOYFUN_RB])


def test_control_boyfun_the_idp_slot_is_full_and_need_says_so(tmp_path: Path) -> None:
    """CONTROL, GREEN both sides. Occupancy is not the broken term -- prove it on The Call.

    If this ever fails, the defect moved back into `_need_score` and the gates below are
    measuring the wrong thing.
    """
    state = _boyfun(tmp_path)
    assert "IDP_FLEX" not in state["roster"]["unfilled"], (
        "precondition: my linebacker fills the league's only IDP slot"
    )
    needs = roster_needs(state["roster"]["slots"], BOYFUN.slot_eligibility)
    assert _need_score("LB", needs) == 0, "a second LB fills nothing, and need knows it"
    assert _need_score("RB", needs) == 0, (
        "and so does a third back -- which is exactly why need cannot break this tie"
    )


def test_control_boyfun_the_slice_contains_the_right_answer(tmp_path: Path) -> None:
    """CONTROL, GREEN both sides. `TOP_N` is not what starves this ordering.

    The handoff's second hypothesis was that the top-12 never surfaces the candidate that
    would fix the call. It does, at position 2. A slice that excludes the right answer and a
    sort that mis-orders it are different bugs with different fixes, so this is asserted
    rather than assumed.
    """
    state = _boyfun(tmp_path)
    assert _in_slice(state, BOYFUN_RB[0]), (
        f"the back is outside the top-{TOP_N} slice: "
        f"{[(p['position'], p['vorp_rank']) for p in _slice(state)]}"
    )
    assert _in_slice(state, BOYFUN_LB[0]), "and so is the linebacker, so both were compared"


def test_control_boyfun_the_linebacker_can_start_in_almost_no_weeks(tmp_path: Path) -> None:
    """CONTROL, GREEN both sides. The magnitude that makes this unambiguous.

    BoyFun has exactly one IDP slot, so a second linebacker is `UNSTARTABLE_FACTOR` -- not a
    close call between two usable players.
    """
    state = _boyfun(tmp_path)
    rows = {p["id"]: p for p in state["best_available"]}
    assert rows[BOYFUN_LB[0]]["marginal_start_factor"] < 0.1
    assert rows[BOYFUN_RB[0]]["marginal_start_factor"] == 1.0


def test_the_call_does_not_name_a_second_linebacker(tmp_path: Path) -> None:
    """RED before the wiring. The live BoyFun report, on the surface it was reported from."""
    state = _boyfun(tmp_path)
    pick = _named(state)
    assert pick.get("position") != "LB", (
        f"The Call names {pick.get('name')} (LB, board #{pick.get('board_rank')}) with "
        f"IDP_FLEX already filled. He is the league's second linebacker and can start in no "
        f"week; the back at board #{BOYFUN_RB[3]} was in the same slice and was passed over "
        f"because raw vorp_rank, not the composed score, was the final key."
    )


def test_the_call_and_recommend_agree_on_the_same_board(tmp_path: Path) -> None:
    """RED before the wiring. TWO SURFACES, ONE BOARD, ONE ANSWER.

    Nothing is harder to act on at pick 101 with forty seconds left than a page whose
    headline recommendation contradicts the list underneath it.
    """
    state = _boyfun(tmp_path)
    best = max(state["best_available"], key=lambda p: float(p["effective_score"]))
    assert _named(state).get("id") == best["id"], (
        f"The Call names {_named(state).get('name')} while the ordering `recommend` uses "
        f"puts {best['name']} first ({best['effective_score']})"
    )


# =====================================================================================
# G-CALL-GH -- Tuesday's league, whose slots are the ones that matter
# =====================================================================================
#
# espn_green_hope: QB RB RB WR WR TE FLEX DEF K. One quarterback, no IDP, one of each
# specialist. The literal second-linebacker case cannot recur here; the CLASS -- a filled
# slot the ordering cannot see -- recurs at QB, K and DEF, which are all `slots <= 1`.

GH_SIX = [
    ("my_qb", "My Quarterback", "QB", 3),
    ("my_rb1", "My Back One", "RB", 4),
    ("my_rb2", "My Back Two", "RB", 5),
    ("my_wr1", "My Receiver One", "WR", 6),
    ("my_wr2", "My Receiver Two", "WR", 7),
    ("my_wr3", "My Receiver Three", "WR", 8),  # FLEX
]
GH_TE = ("te_best", "Best Tight End", "TE", 30)


def test_control_gh_a_second_qb_loses_to_an_open_starting_slot(tmp_path: Path) -> None:
    """CONTROL, GREEN both sides. The handoff's literal ask, and it already worked.

    With TE genuinely open, `need` alone settles it: 2 for the tight end against 0 for a
    second quarterback. This is the case where the leading key does its job, and keeping it
    green is what proves the fix did not replace need with value.
    """
    state = _state(GREEN_HOPE, tmp_path, GH_SIX,
                   [("qb_next", "Next Quarterback", "QB", 20), GH_TE])
    assert "TE" in state["roster"]["unfilled"], "precondition: a real gap at TE"
    assert _in_slice(state, GH_TE[0]), "precondition: the tight end is inside the slice"
    pick = _named(state)
    assert pick.get("position") != "QB", (
        f"The Call names a second quarterback ({pick.get('name')}) in a 1-QB league with "
        f"the TE slot empty"
    )
    assert pick.get("id") == GH_TE[0]


# Every starting slot full but DEF and K. This is the tier in which need ties at 0 for
# everyone, and it is where Tuesday's draft spends rounds 9 through 16.
GH_FULL = [
    ("my_qb", "My Quarterback", "QB", 3),
    ("my_rb1", "My Back One", "RB", 4),
    ("my_rb2", "My Back Two", "RB", 5),
    ("my_wr1", "My Receiver One", "WR", 6),
    ("my_wr2", "My Receiver Two", "WR", 7),
    ("my_te", "My Tight End", "TE", 8),
    ("my_wr3", "My Receiver Three", "WR", 9),   # FLEX
    ("my_k", "My Kicker", "K", 10),
]
GH_RIVAL_RB = ("rb_next", "Next Back", "RB", 21)


def _gh_surplus_case(tmp_path: Path, surplus: tuple[str, str, str, int]) -> dict[str, Any]:
    return _state(GREEN_HOPE, tmp_path, GH_FULL, [surplus, GH_RIVAL_RB])


def test_control_gh_the_only_slots_left_are_ones_no_top_board_offers(tmp_path: Path) -> None:
    """CONTROL, GREEN both sides. Establishes that need ties at 0 across the slice.

    DEF is the one starting slot still open, and the first defence on any real Green Hope
    board is ADP 123 -- far outside a top-12 by value. So need cannot discriminate here, and
    the gates below are genuinely about the term that runs after it.
    """
    state = _gh_surplus_case(tmp_path, ("qb_next", "Next Quarterback", "QB", 20))
    assert state["roster"]["unfilled"] == ["DEF"], state["roster"]["unfilled"]
    needs = roster_needs(state["roster"]["slots"], GREEN_HOPE.slot_eligibility)
    assert {_need_score(p["position"], needs) for p in _slice(state)} == {0}, (
        "precondition: every candidate in the slice fills nothing"
    )


def test_the_call_does_not_name_a_second_quarterback_in_a_one_qb_league(
    tmp_path: Path,
) -> None:
    """RED before the wiring. The Green Hope form of the BoyFun defect."""
    state = _gh_surplus_case(tmp_path, ("qb_next", "Next Quarterback", "QB", 20))
    pick = _named(state)
    assert pick.get("position") != "QB", (
        f"The Call names {pick.get('name')} (QB, board #{pick.get('board_rank')}) in a "
        f"1-QB league with my quarterback slot already filled. There is nowhere to play him."
    )
    assert pick.get("id") == GH_RIVAL_RB[0]


def test_the_call_does_not_name_a_second_kicker(tmp_path: Path) -> None:
    """RED before the wiring.

    THE BOARD RANK HERE IS SYNTHETIC AND THAT IS THE POINT. A kicker does not really rank
    20th; Green Hope's own market takes the first one at ADP 121. But an ordering that only
    avoids a second kicker because kickers happen to rank low is not avoiding him for any
    reason at all, and the day a specialist does creep into the slice -- which is what the
    "D/ST at VORP #80 in round 7" bug already was -- it has nothing to say. The rank is
    forced so the ORDERING is what is being measured.
    """
    state = _gh_surplus_case(tmp_path, ("k_next", "Next Kicker", "K", 20))
    pick = _named(state)
    assert pick.get("position") != "K", (
        f"The Call names a second kicker ({pick.get('name')}, board "
        f"#{pick.get('board_rank')}) with my kicker slot already filled"
    )


def test_the_call_does_not_name_a_second_defence(tmp_path: Path) -> None:
    """RED before the wiring. Same shape as the kicker; DEF is the slot still open here.

    Note this one is NOT a surplus case -- DEF is genuinely unfilled, so `need` is 2 and the
    defence SHOULD be named. Asserting the opposite would be asserting a bug. What is
    checked instead is that the ordering does not name a second defence once one is held.
    """
    held_def = [*GH_FULL, ("my_def", "My Defence", "DEF", 11)]
    entries_extra = [("df_next", "Next Defence", "DEF", 20), GH_RIVAL_RB]
    state = _state(GREEN_HOPE, tmp_path, held_def, entries_extra)
    assert state["roster"]["unfilled"] == [], "precondition: every starting slot is filled"
    pick = _named(state)
    assert pick.get("position") != "DEF", (
        f"The Call names a second defence ({pick.get('name')}, board "
        f"#{pick.get('board_rank')}) with the D/ST slot already filled -- the wire holds "
        f"D/ST9 all season and a team can start exactly one"
    )


# =====================================================================================
# G-CALL-SURPLUS -- more receivers than FLEX can absorb
# =====================================================================================
#
# The multi-slot form. QB, K and DEF fall off a cliff to `UNSTARTABLE_FACTOR` at the second
# body; WR degrades gradually, which is the harder case and the one the dry run produced
# when it drafted 10 WR and 2 RB.

SURPLUS_ROSTER = [
    ("my_qb", "My Quarterback", "QB", 3),
    ("my_rb1", "My Back One", "RB", 4),
    ("my_rb2", "My Back Two", "RB", 5),
    ("my_wr1", "My Receiver One", "WR", 6),
    ("my_wr2", "My Receiver Two", "WR", 7),
    ("my_wr3", "My Receiver Three", "WR", 8),
    ("my_wr4", "My Receiver Four", "WR", 9),   # FLEX -- WR capacity is now exhausted
    ("my_te", "My Tight End", "TE", 10),
]
SURPLUS_WR = ("cand_wr", "Candidate Receiver", "WR", 20)
SURPLUS_RB = ("cand_rb", "Candidate Back", "RB", 21)


def _surplus(tmp_path: Path) -> dict[str, Any]:
    return _state(GREEN_HOPE, tmp_path, SURPLUS_ROSTER, [SURPLUS_WR, SURPLUS_RB])


def test_control_surplus_the_receiver_capacity_really_is_exhausted(
    tmp_path: Path,
) -> None:
    """CONTROL, GREEN both sides. Green Hope starts WR, WR and a FLEX: three, and I hold four.

    The back is the mirror -- two dedicated RB slots plus the same FLEX is three, and I hold
    two -- so he is still a starter and takes no discount at all.
    """
    state = _surplus(tmp_path)
    rows = {p["id"]: p for p in state["best_available"]}
    assert rows[SURPLUS_WR[0]]["marginal_start_factor"] < 0.25, "a fifth receiver is surplus"
    assert rows[SURPLUS_RB[0]]["marginal_start_factor"] == 1.0, "a third back is not"
    assert _in_slice(state, SURPLUS_RB[0]), "and the back is inside the slice"


def test_control_surplus_how_far_down_the_slice_the_right_answer_sits(
    tmp_path: Path,
) -> None:
    """CONTROL. Pins the ONE number that decides whether `TOP_N` could ever starve this.

    Measured by sweeping the constant: these gates go red at ``TOP_N = 1`` and stay green at
    2, 3, 6 and 12. The correct candidate is the SECOND row of the BOARD-RANK slice -- the
    thing the old code looked at -- which is why the slice was not what broke the BoyFun
    report, however plausible that was as a hypothesis.

    Asserted rather than left to a sweep so that shrinking `TOP_N` fails here, naming the
    reason, instead of failing four gates that would each blame the sort.
    """
    state = _surplus(tmp_path)
    order = [p["id"] for p in _slice(state)]
    assert order.index(SURPLUS_RB[0]) == 1, (
        f"the back is row {order.index(SURPLUS_RB[0]) + 1} of the slice, not row 2; "
        f"TOP_N's relationship to this gate has changed"
    )


def test_the_call_prefers_the_position_with_startable_slots_left(tmp_path: Path) -> None:
    """RED before the wiring. One rank apart on the board, three starting slots apart in fact."""
    state = _surplus(tmp_path)
    pick = _named(state)
    assert pick.get("id") == SURPLUS_RB[0], (
        f"The Call names {pick.get('name')} ({pick.get('position')}, board "
        f"#{pick.get('board_rank')}) over the back one rank below him, with four receivers "
        f"already held against three receiver-startable slots. Both fill no need, so need "
        f"ties at 0 and board rank decided."
    )


def test_the_reason_names_the_term_that_decided(tmp_path: Path) -> None:
    """RED before the wiring. A number that is not shown cannot be argued with.

    The runner-up here has the BETTER board rank, so "board #21 against #20" alone reads as
    an argument for the loser. The scalar has to appear beside it.
    """
    state = _surplus(tmp_path)
    why_not = state["the_call"].get("why_not_the_runner_up") or ""
    assert "once the weeks he would actually start" in why_not, why_not
    pick = _named(state)
    assert pick.get("effective_score") is not None, "the ordering must publish its own number"


# =====================================================================================
# G-CALL-SLICE -- the cap looked at twelve rows of the SAME surplus position
# =====================================================================================
#
# The handoff's second hypothesis, vindicated in a case it was not proposed for. It is not
# what caused the BoyFun report -- there the right answer was slice row 2 -- but it is real,
# it is live, and Green Hope is its worst case: this board's top is entirely running backs,
# so a roster already deep at RB gets a slice with nothing else in it.
#
# Measured on the pinned board holding four backs against three RB-startable slots: every one
# of the top twelve was a back discounted to 0.1562, the best scoring 30.8, while Jaxon
# Smith-Njigba scored 78.8 at pool row 28 and was never looked at. `recommend` named him.

SLICE_ROSTER = [
    ("my_rb1", "My Back One", "RB", 3),
    ("my_rb2", "My Back Two", "RB", 4),
    ("my_rb3", "My Back Three", "RB", 5),   # FLEX -- RB capacity is now exhausted
    ("my_rb4", "My Back Four", "RB", 6),    # and this one is surplus
    ("my_qb", "My Quarterback", "QB", 7),
    ("my_wr1", "My Receiver One", "WR", 8),
    ("my_wr2", "My Receiver Two", "WR", 9),
    ("my_te", "My Tight End", "TE", 10),
    ("my_def", "My Defence", "DEF", 11),
    ("my_k", "My Kicker", "K", 12),
]
# Fourteen backs ahead of him by board rank, so the top-12 by VORP cannot reach the receiver.
SLICE_BACKS = [(f"rb_top{i}", f"Top Back {i}", "RB", 19 + i) for i in range(1, 15)]
SLICE_WR = ("wr_open", "Receiver With A Slot", "WR", 40)


def _slice_case(tmp_path: Path) -> dict[str, Any]:
    return _state(GREEN_HOPE, tmp_path, SLICE_ROSTER, [*SLICE_BACKS, SLICE_WR])


def test_control_slice_the_board_top_is_one_surplus_position(tmp_path: Path) -> None:
    """CONTROL, GREEN both sides. The precondition that makes the cap bite.

    Every row of the top twelve BY BOARD RANK is a running back, and every one of them is
    surplus. If this stops being true the gate below proves nothing.
    """
    state = _slice_case(tmp_path)
    assert state["roster"]["unfilled"] == [], "precondition: every starting slot is filled"
    by_rank = sorted(state["best_available"], key=lambda p: p["vorp_rank"])[:TOP_N]
    assert {p["position"] for p in by_rank} == {"RB"}, [p["position"] for p in by_rank]
    assert all(p["marginal_start_factor"] < 0.25 for p in by_rank), (
        "precondition: the whole board-rank slice can barely start"
    )
    assert not _in_slice(state, SLICE_WR[0]), (
        "precondition: the receiver is OUTSIDE the top-12 by board rank -- which is exactly "
        "what the old slice looked at"
    )


def test_control_slice_the_receiver_still_has_a_startable_slot(tmp_path: Path) -> None:
    """CONTROL, GREEN both sides. He is the better pick for a structural reason, not a tuned one."""
    state = _slice_case(tmp_path)
    rows = {p["id"]: p for p in state["best_available"]}
    assert rows[SLICE_WR[0]]["marginal_start_factor"] == 1.0, (
        "two receivers held against three receiver-startable slots: no discount"
    )
    assert rows[SLICE_WR[0]]["effective_score"] > rows[SLICE_BACKS[0][0]]["effective_score"]


def test_the_call_looks_past_a_slice_full_of_one_surplus_position(tmp_path: Path) -> None:
    """RED before the cap was moved onto the composed scalar.

    A cap on "the best N candidates" that ranks by a different number from the one it slices
    by is a filter silently overriding the ranking it feeds.
    """
    state = _slice_case(tmp_path)
    pick = _named(state)
    assert pick.get("id") == SLICE_WR[0], (
        f"The Call names {pick.get('name')} ({pick.get('position')}, board "
        f"#{pick.get('board_rank')}) with four backs already held against three "
        f"RB-startable slots. The receiver at board #{SLICE_WR[3]} scores higher on the "
        f"very number this ordering uses, and sits outside the top-12 BY BOARD RANK."
    )


def test_the_call_still_agrees_with_recommend_when_the_answer_is_deep(
    tmp_path: Path,
) -> None:
    """The whole point of the change: one board, one number, one answer -- at any depth."""
    state = _slice_case(tmp_path)
    best = max(state["best_available"], key=lambda p: float(p["effective_score"]))
    assert _named(state).get("id") == best["id"]
