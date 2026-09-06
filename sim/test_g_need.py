"""G-NEED -- roster need never reaches the ordering while slack remains.

docs/STATE.md: "The dry run produced 10 WR, 2 RB, 1 TE, 1 QB, 1 DEF, 1 K." The mechanism is
one line, `server/mcp.py` `recommend`:

    ranked = sorted(
        candidates,
        key=lambda p: (not p["grab_now"], p["vorp_rank"], not p["fills_need"]),
    )[:limit]

`vorp_rank` is a UNIQUE integer. A key placed after a unique key is unreachable, so
`fills_need` never breaks a tie because there are no ties to break. Need binds only through
the separate `forced` filter:

    forced = slack is not None and slack <= 0

which is exactly "need binds only when slack hits zero" -- the handoff's claim, CONFIRMED,
with the additional detail that the third sort term is not merely weak but dead.

THE ASSERTION IS RESPONSIVENESS, NOT A CHOSEN WINNER. Asserting "the RB must be first" would
smuggle in a scoring rule nobody has agreed. So instead: hold the board FIXED and vary only
the roster. A recommender with any notion of roster balance must answer differently when the
roster is thin at RB than when it is thin at WR. This one returns the same player both
times, which is a statement about the roster being ignored rather than about which player is
better.

WHAT CONSUMES THIS SIGNAL: `fills_need` reaches the displayed `fills_a_need` field and the
`forced` filter. It does NOT reach the ordering while slack remains. `draft/urgency.py`'s
The Call does order by need -- `eligible.sort(key=lambda s: (-s["need"], s["urgency"],
s["player"]["vorp_rank"]))` -- but only within its own top-12 VORP slice (`TOP_N = 12`), so
a need-filler ranked 13th or worse is never considered by it either.

EXPECTED: RED.
"""

from __future__ import annotations

from pathlib import Path

from sim.harness import call, entry, filler, service, standard_league

CURRENT_PICK = 49  # round 7 of 16: six picks in, slack still positive

# Two candidates of deliberately adjacent value. The WR is ONE rank better, which is the
# smallest possible disagreement between board value and roster need.
CAND_WR = ("cand_wr", "Candidate Receiver", "WR", 20)
CAND_RB = ("cand_rb", "Candidate Back", "RB", 21)

# Six picks. THIN_AT_RB holds two backs and four receivers; THIN_AT_WR is the mirror.
THIN_AT_RB = [
    ("my_rb1", "My Back One", "RB", 3),
    ("my_rb2", "My Back Two", "RB", 4),
    ("my_wr1", "My Receiver One", "WR", 5),
    ("my_wr2", "My Receiver Two", "WR", 6),
    ("my_wr3", "My Receiver Three", "WR", 7),
    ("my_wr4", "My Receiver Four", "WR", 8),
]
THIN_AT_WR = [
    ("my_rb1", "My Back One", "RB", 3),
    ("my_rb2", "My Back Two", "RB", 4),
    ("my_rb3", "My Back Three", "RB", 5),
    ("my_rb4", "My Back Four", "RB", 6),
    ("my_wr1", "My Receiver One", "WR", 7),
    ("my_wr2", "My Receiver Two", "WR", 8),
]


def _board(mine: list[tuple[str, str, str, int]]) -> list:
    entries = [entry(pid, name, pos, rank) for pid, name, pos, rank in mine]
    entries += [entry(*CAND_WR), entry(*CAND_RB)]
    entries += filler("wr", 40, "WR", 100)
    entries += filler("rb", 40, "RB", 200)
    entries += filler("te", 20, "TE", 300)
    entries += filler("qb", 20, "QB", 400)
    entries += filler("k", 10, "K", 500)
    entries += filler("df", 10, "DEF", 600)
    return entries


def _top_of(tmp_path: Path, mine: list[tuple[str, str, str, int]], tag: str) -> dict:
    svc = service(
        standard_league(),
        tmp_path / tag,
        current_pick=CURRENT_PICK,
        entries=_board(mine),
        my_player_ids=[pid for pid, _, _, _ in mine],
    )
    status = call(svc, "draft_status")
    assert status["slack_picks"] > 0, "precondition: need is not yet a hard constraint"
    rows = call(svc, "recommend", limit=5)["recommendations"]
    assert rows, "precondition: the cockpit returns recommendations"
    return rows[0]


def test_control_both_rosters_are_built_and_served(tmp_path: Path) -> None:
    """CONTROL, expected GREEN. Both scenarios are valid states of the same league."""
    thin_rb = _top_of(tmp_path, THIN_AT_RB, "ctl_rb")
    thin_wr = _top_of(tmp_path, THIN_AT_WR, "ctl_wr")
    assert thin_rb["id"] and thin_wr["id"]


def test_the_recommendation_responds_to_which_position_the_roster_is_thin_at(
    tmp_path: Path,
) -> None:
    """EXPECTED RED. Same board, opposite rosters, identical answer.

    In a league starting two dedicated RB slots plus a flex, a roster holding two backs and
    four receivers wants a back; the mirror roster wants a receiver. The board is identical
    in both runs and only the roster differs, so any dependence on roster state at all would
    show up as a different name.
    """
    thin_rb = _top_of(tmp_path, THIN_AT_RB, "rb")
    thin_wr = _top_of(tmp_path, THIN_AT_WR, "wr")

    assert thin_rb["id"] != thin_wr["id"], (
        f"the top recommendation is {thin_rb['name']} ({thin_rb['position']}, VORP "
        f"#{thin_rb['vorp_rank']}) for BOTH a roster thin at RB and a roster thin at WR. "
        f"The board did not change and the roster did; the answer did not. Roster need is "
        f"computed (fills_a_need={thin_rb['fills_a_need']}) and then discarded by a sort "
        f"whose second key, vorp_rank, is unique."
    )


def test_control_the_third_sort_key_is_unreachable_because_vorp_rank_is_unique(
    tmp_path: Path,
) -> None:
    """CONTROL, expected GREEN. The mechanism, stated as arithmetic rather than as a story.

    `recommend` sorts by ``(not grab_now, vorp_rank, not fills_need)``. A tiebreaker only
    fires on a tie. If ``vorp_rank`` is unique across the served pool then the pair
    ``(grab_now, vorp_rank)`` is unique too, and the third element is never compared -- so
    ``fills_need`` cannot influence the order no matter what it holds.

    This is why G-OCC and G-NEED are one defect: both are need computed correctly and then
    dropped by the same dead key.
    """
    svc = service(
        standard_league(),
        tmp_path / "unique",
        current_pick=CURRENT_PICK,
        entries=_board(THIN_AT_RB),
        my_player_ids=[pid for pid, _, _, _ in THIN_AT_RB],
    )
    # limit is capped at MAX_ROWS = 25 by the tool schema; 25 is plenty to show
    # uniqueness, and the sort runs over the whole pool regardless of the slice.
    pool = call(svc, "best_available", limit=25)["players"]
    ranks = [p["vorp_rank"] for p in pool]
    assert len(ranks) == len(set(ranks)), "vorp_rank is meant to be a unique board rank"
    assert len(ranks) > 1, "precondition: a pool worth sorting"


def test_a_roster_holding_two_backs_prefers_the_back(tmp_path: Path) -> None:
    """EXPECTED RED. The handoff's wording, asserted directly."""
    top = _top_of(tmp_path, THIN_AT_RB, "direct")
    assert top["id"] == CAND_RB[0], (
        f"with two running backs held in a league starting two plus a flex, the top "
        f"recommendation is {top['name']} ({top['position']}, VORP #{top['vorp_rank']}) "
        f"rather than the running back one rank below him"
    )
