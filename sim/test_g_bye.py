"""G-BYE -- the bye week is computed, displayed, and never consumed.

docs/STATE.md records the consequence measured on a dry run: "a legal lineup does not exist
in every week, structurally, because `RB` slots take only `RB` and the roster held exactly
two." That is not bad luck. Two dedicated RB slots and two running backs means any week both
are on bye has two unfillable slots, and no flex can rescue it.

THE ANSWER IS IN THE SOURCE, NOT ONLY IN THE MEASUREMENT. `draft/usage.py`'s own module
docstring states the rule:

    WHAT THIS IS NOT. Nothing here enters the sort. This module is imported by the state
    builder and the MCP surface, never by `board.py`, `value/` or `scoring/` -- the board is
    built, ranked and frozen before any of this is looked up [...] which is the property
    `qa_board_invariants` asserts rather than assumes.

So the bye reaching the ordering is not merely absent, it is ARCHITECTURALLY FORBIDDEN and
there is a QA invariant enforcing the prohibition. This gate is red by design of the system,
and any fix has to decide that byes are a ranking input rather than a usage column -- which
is a real design change, not a bug fix. That distinction is the finding.

WHAT CONSUMES THIS SIGNAL: `UsageTable.bye()` is read by `server/state.py` (the `bye_week`
field on a served row) and surfaced by `server/mcp.py` (`"bye_week": player.get("bye_week")`).
`cli.py cmd_byes` prints a report. NOTHING reads it in any ordering, filter or score.

EXPECTED: RED.
"""

from __future__ import annotations

from pathlib import Path

from audible.draft.live import place_into_slots
from sim.harness import call, entry, filler, service, standard_league

CURRENT_PICK = 49  # round 7 of 16

# One bye week shared by my whole backfield, and a clean alternative.
STACKED_TEAM = "AAA"
STACKED_BYE = 13
CLEAN_TEAM = "BBB"
CLEAN_BYE = 9

# My two running backs, both idle in week 13. Two dedicated RB slots, so week 13 is empty.
MY_PICKS = [
    ("my_rb1", "My Back One", "RB", 3, STACKED_TEAM),
    ("my_rb2", "My Back Two", "RB", 4, STACKED_TEAM),
    ("my_wr1", "My Receiver One", "WR", 5, CLEAN_TEAM),
    ("my_wr2", "My Receiver Two", "WR", 6, CLEAN_TEAM),
    ("my_wr3", "My Receiver Three", "WR", 7, CLEAN_TEAM),
    ("my_te1", "My Tight End", "TE", 8, CLEAN_TEAM),
]

# Two near-identical backs. The one that COLLIDES is one rank better, which is the smallest
# disagreement between board value and lineup feasibility.
CAND_COLLIDES = ("rb_same_bye", "Back On My Bye", "RB", 20, STACKED_TEAM)
CAND_CLEAN = ("rb_other_bye", "Back On Another Bye", "RB", 21, CLEAN_TEAM)

BYES = {STACKED_TEAM: STACKED_BYE, CLEAN_TEAM: CLEAN_BYE}


def _entries() -> list:
    out = [entry(pid, name, pos, rank, team=team) for pid, name, pos, rank, team in MY_PICKS]
    out += [entry(*CAND_COLLIDES[:4], team=CAND_COLLIDES[4])]
    out += [entry(*CAND_CLEAN[:4], team=CAND_CLEAN[4])]
    out += filler("wr", 40, "WR", 100)
    out += filler("rb", 40, "RB", 200)
    out += filler("te", 20, "TE", 300)
    out += filler("qb", 20, "QB", 400)
    out += filler("k", 10, "K", 500)
    out += filler("df", 10, "DEF", 600)
    return out


def _service(tmp_path: Path):
    return service(
        standard_league(),
        tmp_path,
        current_pick=CURRENT_PICK,
        entries=_entries(),
        my_player_ids=[pid for pid, _, _, _, _ in MY_PICKS],
        byes=BYES,
    )


def test_control_the_roster_really_has_no_legal_lineup_in_the_shared_bye_week(
    tmp_path: Path,
) -> None:
    """CONTROL, expected GREEN. The consequence, proved from the roster alone.

    This is docs/STATE.md's measured case reconstructed: with both running backs on the same
    bye, the two dedicated RB slots cannot both be filled in that week, and the flex cannot
    help because it is already the only slot a third back could take.
    """
    config = standard_league()
    mine = [entry(pid, name, pos, rank, team=team) for pid, name, pos, rank, team in MY_PICKS]

    on_bye_week_13 = [e for e in mine if BYES.get(e.team or "") == STACKED_BYE]
    assert [e.position for e in on_bye_week_13] == ["RB", "RB"], (
        "precondition: exactly my two running backs share the bye"
    )

    available_in_week_13 = [e for e in mine if BYES.get(e.team or "") != STACKED_BYE]
    placed = place_into_slots(available_in_week_13, config)
    unfilled = [slot for slot, who in placed if who is None]
    assert unfilled.count("RB") == 2, (
        f"week {STACKED_BYE} leaves {unfilled.count('RB')} RB slot(s) unfillable; "
        f"unfilled = {unfilled}"
    )


def test_control_the_bye_is_computed_and_displayed(tmp_path: Path) -> None:
    """CONTROL, expected GREEN. The signal EXISTS -- that is what makes the red meaningful.

    A displayed column is not an input. This proves the column is there so the failure below
    cannot be dismissed as missing data.
    """
    svc = _service(tmp_path)
    rows = call(svc, "recommend", limit=8)["recommendations"]
    byes = {r["name"]: r["bye_week"] for r in rows}
    assert any(v is not None for v in byes.values()), (
        f"no recommended row carries a bye_week at all: {byes}"
    )


def test_the_bye_signal_reaches_the_ordering(tmp_path: Path) -> None:
    """EXPECTED RED. Two equivalent backs; the one that breaks week 13 is preferred.

    Nothing about this is a close judgement call. Taking the colliding back leaves three
    running backs and still no legal week-13 lineup; taking the other one fixes the week
    outright. The board is one rank apart and the lineup consequence is total.
    """
    svc = _service(tmp_path)
    rows = call(svc, "recommend", limit=8)["recommendations"]
    backs = [r for r in rows if r["position"] == "RB"]
    assert backs, "precondition: at least one running back is recommended"

    top_back = backs[0]
    assert top_back["id"] == CAND_CLEAN[0], (
        f"the first running back recommended is {top_back['name']} (bye "
        f"{top_back['bye_week']}), which is the SAME bye as both backs already rostered. "
        f"The alternative one rank below is on bye {CLEAN_BYE} and would give week "
        f"{STACKED_BYE} a startable back. The bye is on the row and is not in the sort."
    )


def test_stacking_a_third_back_on_the_same_bye_is_not_recommended_at_all(
    tmp_path: Path,
) -> None:
    """EXPECTED RED, stated as the outcome rather than as the ordering."""
    svc = _service(tmp_path)
    rows = call(svc, "recommend", limit=8)["recommendations"]
    stacked = [
        r for r in rows
        if r["position"] == "RB" and r["bye_week"] == STACKED_BYE
    ]
    assert not stacked, (
        f"recommend offers {[r['name'] for r in stacked]} -- running back(s) on bye "
        f"{STACKED_BYE}, the week my only two backs are already idle. Nothing in the "
        f"ordering reads bye_week; usage.py states outright that nothing in it enters "
        f"the sort."
    )
