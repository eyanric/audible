"""G-SURV -- `survival()` at back-to-back turns.

Seat 1 of 8 picks at 1, 16/17, 32/33, 48/49. At every one of those pairs the number of
rival picks between this pick and the next I control is ZERO, and `live.compute_view`'s
inner `survival()` opens with:

    if not opponent_picks:
        return 1.0

So every player on the board is certain to survive, at exactly the moment two picks are on
the clock and the question "who will not last?" is the only one being asked. `grab_now`
goes empty in the same breath, because `gone` is built from the same falsy check.

Note the mechanism, because docs/STATE.md describes it as a division: it is not a
ZeroDivisionError waiting to happen, it is an explicit guard clause returning 1.0. The
OUTCOME is what STATE.md says; the arithmetic is not.

WHAT CONSUMES IT: `compute_view` -> `LiveView.ranked`/`best_available` -> `server/state.py`
-> the `survival_pct` field on every `recommend` row, and `grab_now`, which IS the first
term of `recommend`'s sort key. So this is not dead code -- it reaches the ordering through
`grab_now`, and at a back-to-back turn it silently contributes nothing.

EXPECTED: RED.
"""

from __future__ import annotations

from pathlib import Path

from sim.harness import (
    TEAMS,
    call,
    entry,
    filler,
    service,
    standard_league,
)

# Seat 1 of 8 over 16 rounds: 1, 16, 17, 32, 33, 48, 49, ...
BACK_TO_BACK = 16  # I hold 16 and 17, so nobody picks in between
NORMAL_TURN = 17  # I hold 17, my next is 32, fourteen rivals in between


def _board() -> list:
    entries = [
        entry("wr_a", "Wideout A", "WR", 10),
        entry("rb_a", "Back A", "RB", 11),
    ]
    entries += filler("wr", 40, "WR", 100)
    entries += filler("rb", 40, "RB", 200)
    entries += filler("te", 20, "TE", 300)
    entries += filler("qb", 20, "QB", 400)
    entries += filler("k", 10, "K", 500)
    entries += filler("df", 10, "DEF", 600)
    return entries


def _view(tmp_path: Path, current_pick: int):
    svc = service(
        standard_league(),
        tmp_path / f"p{current_pick}",
        current_pick=current_pick,
        entries=_board(),
        my_player_ids=["wr_a"],
    )
    view = svc.view()
    assert view is not None
    return svc, view


def test_control_a_normal_turn_discriminates_between_players(tmp_path: Path) -> None:
    """CONTROL, expected GREEN. If this fails the harness is wrong, not the code.

    At pick 17 there are fourteen rival picks before my next, and survival must spread.
    """
    _, view = _view(tmp_path, NORMAL_TURN)
    assert view.opponent_picks_until_horizon == 14
    survivals = {c.survival for c in view.ranked}
    assert len(survivals) > 1, "a normal turn must distinguish players by survival"
    assert any(c.grab_now for c in view.ranked), "a normal turn must flag someone grab-now"


def test_survival_is_not_uniformly_certain_at_a_back_to_back_turn(tmp_path: Path) -> None:
    """EXPECTED RED. Every player reads 100% at the turn, so the signal says nothing."""
    _, view = _view(tmp_path, BACK_TO_BACK)
    assert view.opponent_picks_until_horizon == 0, "precondition: this is the wheel"

    certain = [c for c in view.ranked if c.survival == 1.0]
    assert len(certain) != len(view.ranked), (
        f"all {len(view.ranked)} available players report survival 1.0 at pick "
        f"{BACK_TO_BACK}, because compute_view returns 1.0 whenever "
        f"opponent_picks_until_horizon is 0. At the wheel the real question is who will not "
        f"last the two picks, and the model answers 'everyone will'."
    )


def test_grab_now_is_not_silenced_at_a_back_to_back_turn(tmp_path: Path) -> None:
    """EXPECTED RED. `grab_now` IS the first term of recommend's sort key.

    This is what makes G-SURV a live defect rather than a cosmetic one: with `gone` empty,
    the first term of `sorted(..., key=lambda p: (not p["grab_now"], p["vorp_rank"], ...))`
    is constant, and the ordering collapses to raw board rank.
    """
    _, view = _view(tmp_path, BACK_TO_BACK)
    assert any(c.grab_now for c in view.ranked), (
        "nobody is flagged grab-now at the wheel, so urgency contributes nothing to the "
        "recommendation order at the one turn where two players come off the board at once"
    )


def test_the_served_row_does_not_promise_everyone_survives(tmp_path: Path) -> None:
    """EXPECTED RED, at the surface Eric actually reads."""
    svc, _ = _view(tmp_path, BACK_TO_BACK)
    rows = call(svc, "recommend", limit=5)["recommendations"]
    assert rows, "precondition: the cockpit returns recommendations"
    pcts = {r["survival_pct"] for r in rows}
    assert pcts != {100}, (
        f"every recommended row reports survival_pct 100 at pick {BACK_TO_BACK} "
        f"({[r['name'] for r in rows]}), which reads as certainty rather than as "
        f"'the model has nothing to say here'"
    )


def test_the_wheel_is_where_this_bites_for_seat_one_of_eight(tmp_path: Path) -> None:
    """CONTROL, expected GREEN: name the turns Tuesday actually hits."""
    from audible.draft.live import snake_pick_numbers

    picks = snake_pick_numbers(1, TEAMS, 16)
    assert picks[:7] == [1, 16, 17, 32, 33, 48, 49]
    wheels = [n for n, m in zip(picks, picks[1:], strict=False) if m == n + 1]
    assert wheels == [16, 32, 48, 64, 80, 96, 112], (
        "seat 1 of 8 picks in pairs at every round turn, so the degenerate case is not an "
        "edge case -- it is half of this seat's picks"
    )
