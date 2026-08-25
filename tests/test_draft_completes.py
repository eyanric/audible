"""A draft driven by `recommend` must end with every starting slot filled, from any seat.

This is the feasibility question stated as a property rather than a strategy. The tool is
free to prefer whatever it likes while it has picks to spare -- that freedom is the point,
because in League B the receivers ARE the edge -- but it may never spend its way into a
draft that ends with an empty starting slot.

Nothing here caps a position or nudges a ranking. It only asserts the outcome, so a future
change to how `recommend` ranks is free to move every pick as long as the lineup still fills.

The guarantee is structural, not luck: `recommend` counts the picks still held, subtracts
the starting slots still empty, and once that slack reaches zero only need-fillers qualify.
These tests are what stop that arithmetic from being quietly removed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import Pick
from audible.draft.service import CockpitService
from audible.server.mcp import build_mcp

TEAMS = 8
ROUNDS = 16


def _entry(pid: str, name: str, pos: str, rank: int, adp: float | None) -> DraftEntry:
    points = 400.0 - rank
    return DraftEntry(
        player_id=pid, name=name, position=pos, eligible_positions=frozenset({pos}),
        team="XX", model="consensus", points=points, modeled_xfp=0.0, carried=0.0,
        consensus=points, vorp=points, vorp_rank=rank, consensus_rank=rank, opp_rank=rank,
        deviation=False, scarcity=points, scarcity_rank=rank, adp=adp,
        adp_rank=int(adp) if adp else None, value=0, flags=(),
    )


@pytest.fixture(scope="module")
def board() -> DraftBoard:
    """League-B-shaped supply, deep enough that no position can run dry over 128 picks.

    Ranked so that the skill positions dominate the top of the board and D/ST and K sit
    below it -- the shape the real board has after the replacement-baseline fix, and the
    shape that makes the lineup hard to fill if need is never allowed to bind.
    """
    rows: list[tuple[str, int]] = []
    rows += [("WR", i) for i in range(1, 71)]
    rows += [("RB", i) for i in range(1, 51)]
    rows += [("TE", i) for i in range(1, 31)]
    rows += [("QB", i) for i in range(1, 31)]
    rows += [("DEF", i) for i in range(1, 33)]
    rows += [("K", i) for i in range(1, 33)]

    def sort_key(row: tuple[str, int]) -> tuple[int, int]:
        pos, n = row
        base = {"WR": 0, "RB": 40, "TE": 90, "QB": 150, "DEF": 200, "K": 210}[pos]
        return (base + n, 0)

    entries: list[DraftEntry] = []
    for rank, (pos, n) in enumerate(sorted(rows, key=sort_key), start=1):
        # The market prices the skill positions early and the specialists last, like ADP.
        adp = None if pos in ("DEF", "K") and n > 12 else float(rank)
        entries.append(_entry(f"{pos.lower()}{n:03d}", f"{pos} {n:03d}", pos, rank, adp))
    return DraftBoard("espn_davis_drive", entries)


def _snake_slot(pick_no: int) -> int:
    rnd, idx = divmod(pick_no - 1, TEAMS)
    return idx + 1 if rnd % 2 == 0 else TEAMS - idx


def _call(service: CockpitService, tool: str, **kwargs: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with Client(build_mcp(service)) as client:
            result = await client.call_tool(tool, kwargs)
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            return data
        return json.loads(result.content[0].text)  # type: ignore[union-attr]

    return asyncio.run(go())


def _draft_from(
    config: LeagueConfig, board: DraftBoard, state_dir: Path, my_slot: int
) -> dict[str, Any]:
    """Run all 128 picks. My seat takes `recommend`'s top row; the room drafts by ADP."""
    svc = CockpitService(config, state_dir=state_dir, slot_override=my_slot)
    svc.board = board
    svc.session.draft_id = "t"
    svc.session.draft_status = "drafting"
    svc.session.slot = my_slot
    svc.session.slot_source = "override"

    entries = sorted(board.entries, key=lambda e: e.vorp_rank)
    priced = sorted((e for e in entries if e.adp is not None), key=lambda e: e.adp or 0.0)
    room_order = priced + [e for e in entries if e.adp is None]

    taken: set[str] = set()
    picks: list[Pick] = []
    mine: list[str] = []
    for pick_no in range(1, TEAMS * ROUNDS + 1):
        slot = _snake_slot(pick_no)
        if slot == my_slot:
            rec = _call(svc, "recommend", limit=5)
            rows = rec["recommendations"]
            assert rows, f"recommend returned nothing at pick {pick_no} from slot {my_slot}"
            pid, pos = rows[0]["id"], rows[0]["position"]
            mine.append(pos)
        else:
            pid = next(e.player_id for e in room_order if e.player_id not in taken)
            pos = ""
        taken.add(pid)
        picks.append(
            Pick(pick_no=pick_no, round=(pick_no - 1) // TEAMS + 1,
                 draft_slot=slot, player_id=pid)
        )
        svc.session.picks = list(picks)
        svc._invalidate()

    return {"status": _call(svc, "draft_status"), "roster": _call(svc, "my_roster"),
            "positions": mine}


@pytest.mark.parametrize("my_slot", range(1, TEAMS + 1))
def test_every_seat_ends_with_a_legal_lineup(
    tmp_path: Path, espn_config: LeagueConfig, board: DraftBoard, my_slot: int
) -> None:
    """128 picks from each seat in turn; none may finish a starting slot short."""
    out = _draft_from(espn_config, board, tmp_path / f"slot{my_slot}", my_slot)

    assert out["status"]["unfilled_starting_slots"] == [], (
        f"seat {my_slot} finished the draft with empty starting slots: "
        f"{out['status']['unfilled_starting_slots']} -- picks were {out['positions']}"
    )
    short = [s["slot"] for s in out["roster"]["slots"] if s["filled"] < s["total"]]
    assert not short, f"seat {my_slot} roster is short at {short}"


def test_the_specialists_are_taken_late_but_they_are_taken(
    tmp_path: Path, espn_config: LeagueConfig, board: DraftBoard
) -> None:
    """A D/ST and a K must be on the roster, and neither before the draft is nearly over.

    The two halves are one assertion: taking them early is the bug the replacement-level
    fix removed, and never taking them is the bug that removing need-as-a-filter could
    have introduced. Round 10 rather than 14 is the line, so the test pins the shape
    without pinning a ranking that is allowed to move.
    """
    out = _draft_from(espn_config, board, tmp_path / "slot4", 4)
    positions = out["positions"]

    assert "DEF" in positions, "finished the draft with no defence"
    assert "K" in positions, "finished the draft with no kicker"
    assert positions.index("DEF") >= 9, f"defence taken in round {positions.index('DEF') + 1}"
    assert positions.index("K") >= 9, f"kicker taken in round {positions.index('K') + 1}"


def test_need_binds_exactly_when_the_picks_run_out(
    tmp_path: Path, espn_config: LeagueConfig, board: DraftBoard
) -> None:
    """The arithmetic that makes the guarantee structural rather than lucky."""
    svc = CockpitService(espn_config, state_dir=tmp_path, slot_override=1)
    svc.board = board
    svc.session.draft_id = "t"
    svc.session.draft_status = "drafting"
    svc.session.slot = 1
    svc.session.slot_source = "override"

    status = _call(svc, "draft_status")
    # Nothing drafted: 16 picks in hand, 9 slots to fill, so 7 to spend freely.
    assert status["my_picks_remaining"] == ROUNDS
    assert status["slack_picks"] == ROUNDS - len(espn_config.starting_slots)
    assert status["slack_picks"] == 7
