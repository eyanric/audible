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


def _entry(pid: str, pos: str, pts: float, value: int = 0, adp: float | None = None) -> DraftEntry:
    return DraftEntry(
        player_id=pid, name=f"P{pid}", position=pos, team="X", model="consensus",
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
