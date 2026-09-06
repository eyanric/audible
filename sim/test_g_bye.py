"""G-BYE -- a bye collision must cost the candidate that causes it.

FIXTURE REBUILT, AND THE OLD ONE WAS THE DEFECT. The merged version set `CLEAN_TEAM = "BBB"`
with bye 9 and gave that team to the three receivers, the tight end AND the "clean"
alternative back. So the alternative landed on the roster's already-worst week. Measured on
that exact fixture:

    roster-only                        20.0
    + RB on AAA/13 ("the collider")    25.0    marginal +5.0
    + RB on BBB/9  ("the clean one")   29.0    marginal +9.0

The gate asserted a preference for the back who costs NINE against a back who costs FIVE. It
was not detecting a defect; it was asserting one. A gate that would stay red after a correct
fix is worse than no gate, because the next session spends its time explaining the red.

Rebuilt on the control from `tests/test_ordering.py`, where the mechanism demonstrably
discriminates -- byes spread across AAA/13, BBB/5, CCC/7, and the alternative alone on
DDD/11:

    roster-only                        14.0
    + RB on the SAME bye (AAA/13)      19.0    marginal +5.0
    + RB on an UNSHARED bye (DDD/11)   15.0    marginal +1.0

WHY CONVEX, RESTATED BECAUSE IT IS COUNTERINTUITIVE. Linear slot-weeks discriminate NOTHING:
every player misses exactly one week, so the total number of empty slot-weeks is conserved
however the byes fall, and both candidates score +1. What makes stacking bad is that holes in
one week compound -- losing both backs in week 13 empties both dedicated RB slots at once
with nothing able to cover either, while losing one back in each of two weeks empties one
slot twice and the other back still plays. Same slot-weeks, very different lineups. The
per-week hole count is therefore SQUARED.

WHAT CHANGED SO THIS CAN BE GREEN. Two things, and neither is a relaxed assertion:

  * `bye_conflict_cost` reaches `effective_score` (`server/state.py::_score_rows`), which
    The Call now orders by. `tests/test_byes.py` hard stop 2 blocked this and has been
    NARROWED to what it was always for -- no projection or value number may move -- rather
    than weakened. The value engine still cannot import the bye accessor at all.
  * The two bye sources are reconciled. `bye` came from the schedule and `bye_week` from the
    usage table, and this gate pins a `UsageTable` because no schedule exists offline. Before
    reconciliation the ordering read the empty one, priced every collision at zero, and would
    have gone green while measuring nothing.

EXPECTED: GREEN. Its failure injection is forcing `bye_conflict_cost` to 0.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audible.draft import ordering
from audible.draft.live import place_into_slots
from audible.server.state import build_state
from sim.harness import current_pick_after, entry, filler, service, standard_league

# Byes spread, so the roster's own worst week is unambiguous and the alternative is genuinely
# clean rather than merely differently stacked.
BYES = {"AAA": 13, "BBB": 5, "CCC": 7, "DDD": 11}
STACKED_BYE = 13

MY_PICKS = [
    ("my_rb1", "My Back One", "RB", 3, "AAA"),
    ("my_rb2", "My Back Two", "RB", 4, "AAA"),
    ("my_wr1", "My Receiver One", "WR", 5, "BBB"),
    ("my_wr2", "My Receiver Two", "WR", 6, "BBB"),
    ("my_wr3", "My Receiver Three", "WR", 7, "BBB"),
    ("my_te1", "My Tight End", "TE", 8, "CCC"),
]

# Two near-identical backs. The one that COLLIDES is one rank BETTER, which is the smallest
# disagreement between board value and lineup feasibility -- and the direction that matters,
# since a gate where the right answer is also the better player proves nothing.
CAND_COLLIDES = ("rb_same_bye", "Back On My Bye", "RB", 20, "AAA")
CAND_CLEAN = ("rb_other_bye", "Back On Another Bye", "RB", 21, "DDD")


def _entries() -> list:
    out = [entry(pid, name, pos, rank, team=team)
           for pid, name, pos, rank, team in (*MY_PICKS, CAND_COLLIDES, CAND_CLEAN)]
    out += filler("wr", 40, "WR", 100)
    out += filler("rb", 40, "RB", 200)
    out += filler("te", 20, "TE", 300)
    out += filler("qb", 20, "QB", 400)
    out += filler("k", 10, "K", 500)
    out += filler("df", 10, "DEF", 600)
    return out


def _state(tmp_path: Path) -> dict[str, Any]:
    config = standard_league()
    svc = service(
        config, tmp_path,
        current_pick=current_pick_after(len(MY_PICKS), config.num_teams),
        entries=_entries(),
        my_player_ids=[pid for pid, _, _, _, _ in MY_PICKS],
        byes=BYES,
    )
    return build_state(svc)


def _row(state: dict[str, Any], player_id: str) -> dict[str, Any]:
    return next(p for p in state["best_available"] if p["id"] == player_id)


class _E:
    """A board entry reduced to what placement and byes read, for the cost control."""

    def __init__(self, pid: str, position: str, team: str, points: float) -> None:
        self.player_id, self.position, self.team, self.points = pid, position, team, points
        self.eligible_positions = frozenset({position})


def _roster_entries() -> list[_E]:
    return [_E(pid, pos, team, 400.0 - rank)
            for pid, _name, pos, rank, team in MY_PICKS]


# --- controls -------------------------------------------------------------------------

def test_control_the_roster_really_has_no_legal_lineup_in_the_shared_bye_week() -> None:
    """CONTROL. The consequence, proved from the roster alone and not from any score.

    With both backs on one bye, the two dedicated RB slots cannot both be filled that week,
    and the flex cannot help because it is the only slot a third back could take anyway.
    """
    config = standard_league()
    mine = [entry(pid, name, pos, rank, team=team)
            for pid, name, pos, rank, team in MY_PICKS]

    on_bye = [e for e in mine if BYES.get(e.team or "") == STACKED_BYE]
    assert [e.position for e in on_bye] == ["RB", "RB"], (
        "precondition: exactly my two running backs share the bye"
    )
    unfilled = [slot for slot, who in
                place_into_slots([e for e in mine if e not in on_bye], config)
                if who is None]
    assert unfilled.count("RB") == 2, f"week {STACKED_BYE} leaves {unfilled}"


def test_control_the_mechanism_discriminates_on_this_roster() -> None:
    """CONTROL. The three numbers the fixture is built on, pinned.

    The OLD fixture failed here -- its "clean" candidate cost 9.0 against the collider's
    5.0 -- which is why this control exists before any assertion about an ordering. If the
    cost function stops separating these two, every gate below is measuring noise.
    """
    config = standard_league()
    roster = _roster_entries()
    base = ordering.bye_conflict_cost(roster, config, BYES)
    shared = ordering.bye_conflict_cost([*roster, _E("c", "RB", "AAA", 380)], config, BYES)
    unshared = ordering.bye_conflict_cost([*roster, _E("c", "RB", "DDD", 379)], config, BYES)

    assert (base, shared, unshared) == (14.0, 19.0, 15.0), (base, shared, unshared)
    assert shared - base == 5.0
    assert unshared - base == 1.0


def test_control_the_bye_reaches_the_served_row_as_a_price(tmp_path: Path) -> None:
    """CONTROL. The signal is not merely displayed -- it is charged.

    The merged G-BYE could only assert that a `bye_week` column existed. A column is not an
    input, and this is the assertion that separates the two.
    """
    state = _state(tmp_path)
    collider = _row(state, CAND_COLLIDES[0])
    clean = _row(state, CAND_CLEAN[0])

    assert collider["bye_week"] == STACKED_BYE and clean["bye_week"] == 11
    assert collider["bye_conflict_penalty"] > clean["bye_conflict_penalty"] > 0, (
        f"collider {collider['bye_conflict_penalty']} vs clean "
        f"{clean['bye_conflict_penalty']} -- the collision must cost more"
    )


def test_control_neither_back_is_discounted_for_surplus(tmp_path: Path) -> None:
    """CONTROL. Isolates the bye as the ONLY term that differs between the two.

    Both are third backs against three RB-startable slots, so `marginal_start_factor` is 1.0
    for each. Without this the gate could pass for the wrong reason.
    """
    state = _state(tmp_path)
    assert _row(state, CAND_COLLIDES[0])["marginal_start_factor"] == 1.0
    assert _row(state, CAND_CLEAN[0])["marginal_start_factor"] == 1.0


# --- the gate -------------------------------------------------------------------------

def test_the_call_prefers_the_back_who_does_not_break_week_thirteen(tmp_path: Path) -> None:
    """The bye signal reaches THE CALL -- the panel on the page, not only the MCP list.

    Taking the colliding back leaves three running backs and still no legal week-13 lineup;
    taking the other one fixes the week outright. One rank apart on the board, and the
    lineup consequence is total.
    """
    state = _state(tmp_path)
    pick = state["the_call"].get("pick") or {}
    assert pick.get("id") == CAND_CLEAN[0], (
        f"The Call names {pick.get('name')} (bye {pick.get('bye_week')}), the SAME bye as "
        f"both backs already rostered. The alternative one rank below is on bye 11 and "
        f"would give week {STACKED_BYE} a startable back."
    )


def test_the_reason_shows_what_the_collision_cost(tmp_path: Path) -> None:
    """A price that is not shown cannot be argued with, and the loser has the better rank."""
    state = _state(tmp_path)
    why_not = state["the_call"].get("why_not_the_runner_up") or ""
    assert "his bye" in why_not, why_not
    runner = state["the_call"].get("runner_up") or {}
    assert runner.get("id") == CAND_COLLIDES[0]
    assert (runner.get("bye_conflict_penalty") or 0) > 0, (
        "the runner-up lost on a bye collision and the payload must say so"
    )


def test_the_ordering_agrees_with_the_call(tmp_path: Path) -> None:
    """One board, one number, one answer -- byes included."""
    state = _state(tmp_path)
    best = max(state["best_available"], key=lambda p: float(p["effective_score"]))
    assert best["id"] == CAND_CLEAN[0]
    assert (state["the_call"].get("pick") or {}).get("id") == best["id"]


def test_a_third_back_on_the_same_bye_is_not_the_recommendation(tmp_path: Path) -> None:
    """EXPECTED GREEN. The reported bug in its original wording, on the rebuilt fixture."""
    state = _state(tmp_path)
    pick = state["the_call"].get("pick") or {}
    assert not (pick.get("position") == "RB" and pick.get("bye_week") == STACKED_BYE), (
        f"The Call offers {pick.get('name')} -- a running back on bye {STACKED_BYE}, the "
        f"week my only two backs are already idle"
    )
