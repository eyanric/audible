"""G-OCC -- a filled IDP_FLEX still pulls another linebacker.

THE COMMIT DID WHAT IT SAID, AND IT WAS NOT ENOUGH. `35e51342` ("Roster need asks the
league who can fill a slot, instead of guessing from its name") landed hours before the
BoyFun draft, which still produced the bug. Measured here, that is not a contradiction:

  * OCCUPANCY IS COMPUTED CORRECTLY. With IDP_FLEX filled by a linebacker, IDP_FLEX is
    absent from `unfilled_starting_slots`, and every remaining LB on the board reads
    `fills_a_need: False`. `live.place_into_slots` skips slots that already hold a player
    (`if placed[i] is not None: continue`), so the need set is right.
  * NOTHING CONSUMES IT IN THE ORDER. `server/mcp.py` `recommend` sorts by

        key=lambda p: (not p["grab_now"], p["vorp_rank"], not p["fills_need"])

    and `vorp_rank` is a UNIQUE integer rank. A tiebreaker placed after a unique key can
    never break a tie, so `fills_need` is unreachable in that sort. It binds only through
    the separate `forced` filter, which engages only once `slack_picks <= 0`.

So this gate and G-NEED are ONE defect wearing two hats: need is computed and displayed
correctly and then discarded at the moment of ordering. That matters for the fix -- fixing
"occupancy" again would change nothing.

WHAT CONSUMES THIS SIGNAL: `fills_need` reaches `recommend`'s output as the displayed
`fills_a_need` field and reaches the `forced` filter. It does NOT reach the ordering while
slack remains. `draft/urgency.py`'s The Call is the one surface that does order by it
(`eligible.sort(key=lambda s: (-s["need"], ...))`), over its own top-12 slice.

EXPECTED: RED.
"""

from __future__ import annotations

from pathlib import Path

from sim.harness import call, entry, filler, idp_league, service

# Round 7 of a 16-round draft: six of my picks are in and there is plenty of slack left.
CURRENT_PICK = 49

MY_PICKS = [
    ("my_qb", "My Quarterback", "QB", 3),
    ("my_rb1", "My Back One", "RB", 4),
    ("my_rb2", "My Back Two", "RB", 5),
    ("my_wr1", "My Receiver One", "WR", 6),
    ("my_wr2", "My Receiver Two", "WR", 7),
    ("my_lb", "My Linebacker", "LB", 8),  # <- takes IDP_FLEX, the league's only IDP slot
]


def _board() -> list:
    entries = [entry(pid, name, pos, rank) for pid, name, pos, rank in MY_PICKS]
    # Two linebackers ranked ABOVE the best tight end, and TE is a genuine open slot.
    entries += [
        entry("lb_next", "Next Linebacker", "LB", 20),
        entry("lb_next2", "Another Linebacker", "LB", 21),
        entry("te_best", "Best Tight End", "TE", 30),
    ]
    entries += filler("wr", 40, "WR", 100)
    entries += filler("rb", 40, "RB", 200)
    entries += filler("te", 15, "TE", 300)
    entries += filler("qb", 15, "QB", 400)
    entries += filler("k", 10, "K", 500)
    entries += filler("df", 10, "DEF", 600)
    entries += filler("lb", 20, "LB", 700)
    return entries


def _service(tmp_path: Path):
    return service(
        idp_league(),
        tmp_path,
        current_pick=CURRENT_PICK,
        entries=_board(),
        my_player_ids=[pid for pid, _, _, _ in MY_PICKS],
    )


def test_control_the_idp_slot_really_is_full_and_need_is_computed_right(
    tmp_path: Path,
) -> None:
    """CONTROL, expected GREEN -- and it is the finding.

    Occupancy IS handled. `35e51342` works. If this control ever fails, the defect moved.
    """
    svc = _service(tmp_path)
    status = call(svc, "draft_status")
    assert "IDP_FLEX" not in status["unfilled_starting_slots"], (
        "precondition: my linebacker fills the league's only IDP slot"
    )
    assert "TE" in status["unfilled_starting_slots"], "precondition: a real gap at TE"
    assert status["slack_picks"] > 0, "precondition: need is not yet a hard constraint"

    rows = call(svc, "recommend", limit=6)["recommendations"]
    for row in rows:
        if row["position"] == "LB":
            assert row["fills_a_need"] is False, (
                "a linebacker must not read as filling a need with IDP_FLEX already full"
            )


def test_a_filled_idp_flex_does_not_hand_the_pick_to_another_linebacker(
    tmp_path: Path,
) -> None:
    """EXPECTED RED. The top recommendation is a second LB that fills nothing."""
    svc = _service(tmp_path)
    rows = call(svc, "recommend", limit=6)["recommendations"]
    assert rows, "precondition: the cockpit returns recommendations"

    top = rows[0]
    assert top["position"] != "LB", (
        f"the top recommendation is {top['name']} (LB, VORP #{top['vorp_rank']}, "
        f"fills_a_need={top['fills_a_need']}) while IDP_FLEX is already filled and TE is "
        f"open. Need is computed correctly and then never consulted: recommend sorts by "
        f"vorp_rank before fills_need, and vorp_rank is unique."
    )


def test_no_second_linebacker_is_named_at_all(tmp_path: Path) -> None:
    """EXPECTED RED. The reported bug in its original wording."""
    svc = _service(tmp_path)
    rows = call(svc, "recommend", limit=6)["recommendations"]
    named = [r["name"] for r in rows if r["position"] == "LB"]
    assert not named, (
        f"recommend names {len(named)} further linebacker(s) -- {named} -- with the only "
        f"IDP slot already filled. Every one of them reads fills_a_need False, so the "
        f"information needed to exclude them is present and unused."
    )
