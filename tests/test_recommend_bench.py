"""`recommend` must not treat an empty starting slot as a constraint it isn't yet.

Found by a full 16-round dry run of League B driven through the MCP tools. `recommend`
filtered to players who fill an unfilled STARTING slot, with no concept of the bench. Six
picks in, FLEX was already filled -- by a backup tight end the tool itself had recommended
-- so every RB, WR and TE on the board read `fills_need: False` and the best remaining
"need" was the top defence at VORP #80. It recommended a D/ST in round 7 over a wide
receiver 46 places better, then a kicker in round 9. The resulting roster was five tight
ends, two defences, three running backs.

It is the same omission the replacement baseline had, one layer up: model the starting
lineup, forget the seven bench picks drafted around it. The rule now is arithmetic -- count
the picks still held, subtract the slots still empty, and an empty slot binds only when that
slack runs out.
"""

from __future__ import annotations

import asyncio
import json
import time
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
MY_SLOT = 1


def _entry(pid: str, name: str, pos: str, vorp_rank: int) -> DraftEntry:
    points = 400.0 - vorp_rank
    return DraftEntry(
        player_id=pid, name=name, position=pos, eligible_positions=frozenset({pos}),
        team="XX", model="consensus", points=points, modeled_xfp=0.0, carried=0.0,
        consensus=points, vorp=points, vorp_rank=vorp_rank, consensus_rank=vorp_rank,
        opp_rank=vorp_rank, deviation=False, scarcity=points, scarcity_rank=vorp_rank,
        adp=float(vorp_rank), adp_rank=vorp_rank, value=0, flags=(),
    )


# A board where the best available player is a WR who fills no starting slot, and the best
# player who DOES fill one is a defence 46 ranks below him.
BOARD = [
    _entry("wr_star", "Star Receiver", "WR", 34),
    _entry("te_bench", "Backup Tight End", "TE", 60),
    _entry("def_top", "Top Defence", "DEF", 80),
    _entry("k_top", "Top Kicker", "K", 94),
    _entry("qb_mid", "Middling Quarterback", "QB", 110),
]
# Depth so replacement levels and the served pool are not degenerate.
BOARD += [_entry(f"rb{i:03d}", f"RB {i:03d}", "RB", 200 + i) for i in range(1, 40)]
BOARD += [_entry(f"wr{i:03d}", f"WR {i:03d}", "WR", 300 + i) for i in range(1, 60)]
BOARD += [_entry(f"te{i:03d}", f"TE {i:03d}", "TE", 400 + i) for i in range(1, 20)]

# My six picks: RB, RB, WR, WR, TE fill their own slots and the second TE takes FLEX.
MINE = [
    ("mine_rb1", "My RB One", "RB", 5), ("mine_rb2", "My RB Two", "RB", 6),
    ("mine_wr1", "My WR One", "WR", 7), ("mine_wr2", "My WR Two", "WR", 8),
    ("mine_te1", "My TE One", "TE", 9), ("mine_te2", "My TE Two", "TE", 10),
]


def _service(config: LeagueConfig, state_dir: Path, current_pick: int) -> CockpitService:
    """A League B session mid-draft: my six picks in, everyone else's filling the clock."""
    svc = CockpitService(config, state_dir=state_dir, slot_override=MY_SLOT)
    entries = BOARD + [_entry(p, n, pos, r) for p, n, pos, r in MINE]
    entries += [_entry(f"gone{i:03d}", f"Gone {i:03d}", "RB", 500 + i)
                for i in range(1, current_pick + 1)]
    svc.board = DraftBoard(config.key, sorted(entries, key=lambda e: e.vorp_rank))
    svc.session.draft_id = "t"
    svc.session.draft_status = "drafting"
    svc.session.slot = MY_SLOT
    svc.session.slot_source = "override"

    picks: list[Pick] = []
    mine = iter(MINE)
    for n in range(1, current_pick):
        rnd = (n - 1) // TEAMS + 1
        idx = (n - 1) % TEAMS
        slot = idx + 1 if rnd % 2 == 1 else TEAMS - idx
        fallback = (f"gone{n:03d}", "", "RB", 0)
        pid = next(mine, fallback)[0] if slot == MY_SLOT else f"gone{n:03d}"
        picks.append(Pick(pick_no=n, round=rnd, draft_slot=slot, player_id=pid))
    svc.session.picks = picks
    svc.health.last_success = time.time()
    return svc


def _call(service: CockpitService, tool: str, **kwargs: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with Client(build_mcp(service)) as client:
            result = await client.call_tool(tool, kwargs)
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            return data
        return json.loads(result.content[0].text)  # type: ignore[union-attr]

    return asyncio.run(go())


def test_flex_filled_by_a_backup_does_not_hand_the_pick_to_a_defence(
    tmp_path: Path, espn_config: LeagueConfig
) -> None:
    """Round 7, six picks in, FLEX taken by a second TE. The reported bug, exactly."""
    svc = _service(espn_config, tmp_path, current_pick=49)

    status = _call(svc, "draft_status")
    assert status["unfilled_starting_slots"] == ["QB", "DEF", "K"], (
        "precondition: the starting slots are nominally full except QB/DEF/K"
    )
    assert status["slack_picks"] > 0, "there are still more picks left than empty slots"

    rec = _call(svc, "recommend", limit=5)
    top = rec["recommendations"][0]
    assert top["id"] == "wr_star", (
        f"round 7 pick went to {top['name']} ({top['position']}, VORP #{top['vorp_rank']}) "
        f"instead of the best player on the board"
    )
    assert top["position"] not in ("DEF", "K")


def test_an_empty_slot_binds_once_the_picks_run_out(
    tmp_path: Path, espn_config: LeagueConfig
) -> None:
    """Late, with three empty slots and fewer picks than that, only need-fillers qualify."""
    svc = _service(espn_config, tmp_path, current_pick=113)

    status = _call(svc, "draft_status")
    assert status["slack_picks"] <= 0
    rec = _call(svc, "recommend", limit=5)
    assert rec["recommendations"], "forced must not mean empty"
    for row in rec["recommendations"]:
        assert row["fills_a_need"], f"{row['name']} fills nothing but the picks are committed"
    assert "every remaining pick is committed" in rec["basis"]


def test_the_clock_runs_this_league_s_rounds_not_a_hardcoded_18(
    tmp_path: Path, espn_config: LeagueConfig, sleeper_config: LeagueConfig
) -> None:
    """Rounds seed from the config, not from a constant that happens to be League A's.

    `slack_picks` is derived from how many picks I still hold, so an 18-round clock on a
    16-round draft overstates it by two -- and two picks of slack is the difference between
    filling the last starting slots and finishing the draft without a kicker.
    """
    assert espn_config.draft_rounds == 16
    assert sleeper_config.draft_rounds == 18
    for cfg in (espn_config, sleeper_config):
        svc = CockpitService(cfg, state_dir=tmp_path / cfg.key, slot_override=1)
        assert svc.session.rounds == cfg.draft_rounds


def test_picks_remaining_counts_the_snake_not_the_rounds_left(
    tmp_path: Path, espn_config: LeagueConfig
) -> None:
    """Slot 1 holds picks 1 and 16, so at pick 2 it has 15 left, not 16."""
    svc = _service(espn_config, tmp_path, current_pick=2)
    status = _call(svc, "draft_status")
    assert status["my_picks_remaining"] == 15


@pytest.mark.parametrize("current_pick", [17, 49, 81, 113])
def test_recommend_always_answers(
    tmp_path: Path, espn_config: LeagueConfig, current_pick: int
) -> None:
    """Whatever the slack, the tool has an opinion -- an empty list on the clock is useless."""
    svc = _service(espn_config, tmp_path, current_pick=current_pick)
    rec = _call(svc, "recommend", limit=5)
    assert rec["recommendations"]
    assert rec["basis"]
