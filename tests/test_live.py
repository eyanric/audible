from __future__ import annotations

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import (
    Pick,
    compute_view,
    my_slot_on_clock,
    next_pick_after,
    parse_picks,
    snake_pick_numbers,
    unfilled_slots,
)


def test_snake_pick_numbers() -> None:
    assert snake_pick_numbers(1, 10, 3) == [1, 20, 21]
    assert snake_pick_numbers(5, 10, 3) == [5, 16, 25]


def test_next_pick_after() -> None:
    assert next_pick_after(5, 10, 16, 12) == 16  # 5 picks away
    assert next_pick_after(5, 10, 16, 16) == 16
    assert next_pick_after(5, 10, 16, 17) == 25


def test_slot_on_clock_snakes() -> None:
    assert my_slot_on_clock(1, 10) == 1
    assert my_slot_on_clock(10, 10) == 10
    assert my_slot_on_clock(11, 10) == 10  # snake turn: slot 10 picks again
    assert my_slot_on_clock(16, 10) == 5


def test_parse_picks_sorts_and_skips_empty() -> None:
    raw: list[dict[str, object]] = [
        {"player_id": "b", "pick_no": 2, "round": 1, "draft_slot": 2},
        {"player_id": None, "pick_no": 1},
        {"player_id": "a", "pick_no": 1, "round": 1, "draft_slot": 1},
    ]
    assert [p.player_id for p in parse_picks(raw)] == ["a", "b"]


def _entry(
    pid: str, pos: str, pts: float, value: int = 0, adp: float | None = None,
    eligible: frozenset[str] | None = None,
) -> DraftEntry:
    return DraftEntry(
        player_id=pid, name=f"P{pid}", position=pos,
        eligible_positions=eligible if eligible is not None else frozenset({pos}),
        team="X", model="consensus",
        points=pts, modeled_xfp=0.0, carried=0.0, consensus=pts, vorp=pts, vorp_rank=0,
        scarcity=pts, scarcity_rank=0, adp=adp, adp_rank=int(adp) if adp else None,
        value=value, flags=(),
    )


def test_unfilled_slots(mini_config: LeagueConfig) -> None:
    # mini: QB, FLEX(RB/WR/TE), SUPER_FLEX(QB/RB/WR/TE)
    qb, rb = _entry("q", "QB", 300), _entry("r", "RB", 250)
    assert unfilled_slots([qb], mini_config) == ["FLEX", "SUPER_FLEX"]
    assert unfilled_slots([qb, rb], mini_config) == ["SUPER_FLEX"]  # qb->QB, rb->FLEX
    assert set(unfilled_slots([], mini_config)) == {"QB", "FLEX", "SUPER_FLEX"}


def test_compute_view(mini_config: LeagueConfig) -> None:
    board = DraftBoard("mini", [
        _entry("a", "RB", 300, adp=1), _entry("b", "WR", 280, adp=2), _entry("c", "QB", 260, adp=3),
    ])
    view = compute_view(board, [Pick(1, 1, 1, "a")], my_slot=2, config=mini_config, rounds=3)
    avail = [c.entry.player_id for c in view.best_available]
    assert "a" not in avail and "b" in avail  # drafted player removed
    assert view.current_pick == 2
    assert view.on_the_clock == 2  # pick 2 -> slot 2


# --- regression: the six defects found in the Gate-1 recon --------------------------------


def _board_of(n: int, teams: int = 10) -> DraftBoard:
    """n synthetic entries, value-ranked and ADP-ranked identically."""
    pos = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "RB", "WR"]
    return DraftBoard("t", [
        _entry(f"p{i:03d}", pos[(i - 1) % 10], 400.0 - i, adp=float(i)) for i in range(1, n + 1)
    ])


def test_grab_now_is_live_while_i_am_on_the_clock(sleeper_config: LeagueConfig) -> None:
    """The headline defect: survival used '>= current_pick', so on my own clock the horizon
    collapsed to zero and grab_now was False for the entire board."""
    board = _board_of(120)
    # 10-team snake, slot 4 -> picks 4, 17, 24, ... Pick #4 is mine, and I next pick at #17.
    picks = [Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)]
    view = compute_view(board, picks, my_slot=4, config=sleeper_config, rounds=18)

    assert view.current_pick == 4
    assert view.picks_until_me == 0  # I am on the clock
    assert view.survival_horizon == 17  # ... and pick again at 17
    assert view.opponent_picks_until_horizon == 12  # picks 5..16 belong to rivals
    assert any(c.grab_now for c in view.best_available), "grab-now must not be dark on my clock"


def test_wheel_picks_have_a_one_pick_horizon(sleeper_config: LeagueConfig) -> None:
    """At the turn, back-to-back picks mean almost nobody can be sniped."""
    board = _board_of(120)
    picks = [Pick(pick_no=n, round=(n - 1) // 10 + 1, draft_slot=n, player_id=f"p{n:03d}")
             for n in range(1, 20)]
    view = compute_view(board, picks, my_slot=1, config=sleeper_config, rounds=18)

    assert view.current_pick == 20  # slot 1 owns 20 AND 21
    assert view.picks_until_me == 0
    assert view.survival_horizon == 21
    assert view.opponent_picks_until_horizon == 0  # nobody picks in between
    assert not any(c.grab_now for c in view.best_available)


def test_clock_survives_a_dropped_pick_record(sleeper_config: LeagueConfig) -> None:
    """parse_picks drops rows without a player_id; len(picks) then rewinds the draft."""
    board = _board_of(120)
    picks = [Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 10)]
    del picks[3]  # pick #4 never arrived

    view = compute_view(board, picks, my_slot=1, config=sleeper_config, rounds=18)
    assert view.current_pick == 10  # authoritative max(pick_no)+1, not len(picks)+1 == 9
    assert view.on_the_clock == 10


def test_hybrid_eligibility_fills_the_right_slot(sleeper_config: LeagueConfig) -> None:
    """A DL/LB hybrid must be able to fill IDP_FLEX; matching on the VORP bucket alone missed
    241 of 7,653 league-eligible players."""
    hybrid = _entry("h", "DL", 200.0, eligible=frozenset({"DL", "LB"}))
    unfilled = unfilled_slots([hybrid], sleeper_config)
    assert "IDP_FLEX" not in unfilled  # the hybrid filled it


def test_out_of_range_slot_is_rejected(mini_config: LeagueConfig) -> None:
    import pytest
    with pytest.raises(ValueError, match="out of range"):
        compute_view(_board_of(10, teams=2), [], my_slot=99, config=mini_config, rounds=3)


def test_no_phantom_slot_after_the_draft_ends() -> None:
    assert my_slot_on_clock(171, 10, 18) == 10  # round 18 is even -> starts at slot 10
    assert my_slot_on_clock(180, 10, 18) == 1  # ... and ends at slot 1
    assert my_slot_on_clock(181, 10, 18) is None  # nothing past the end
    assert my_slot_on_clock(181, 10) == 1  # unbounded call keeps the old behaviour


def test_recommendations_survive_a_full_starting_lineup(mini_config: LeagueConfig) -> None:
    """Once every slot is placed the needs set empties; the panel must not go blank for the
    whole bench phase."""
    board = _board_of(40, teams=2)
    mine = [c.entry for c in compute_view(board, [], my_slot=1, config=mini_config,
                                          rounds=6).best_available[:3]]
    picks = [Pick(pick_no=i + 1, round=1, draft_slot=1, player_id=e.player_id)
             for i, e in enumerate(mine)]
    view = compute_view(board, picks, my_slot=1, config=mini_config, rounds=6)

    assert view.starters_complete
    assert view.unfilled == []
    assert view.recommendations, "bench rounds still need a recommendation"
