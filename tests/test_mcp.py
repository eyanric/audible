"""MCP surface: tools are projections over the one warmed service, and always report staleness.

Exercised through a real FastMCP client over in-memory transport rather than by calling the
functions directly, so the registered schemas and descriptions are covered too.
"""

from __future__ import annotations

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

POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]


def _entry(i: int) -> DraftEntry:
    pos = POSITIONS[(i - 1) % len(POSITIONS)]
    return DraftEntry(
        player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
        eligible_positions=frozenset({pos}), team="XX", model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=(i % 17 == 0), scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i), adp_rank=i, value=0, flags=("riser",) if i % 5 == 0 else (),
    )


@pytest.fixture
def service(tmp_path: Path, sleeper_config: LeagueConfig) -> CockpitService:
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard("sleeper_boyfun", [_entry(i) for i in range(1, 201)])
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = 4
    svc.session.slot_source = "override"
    svc.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)
    ]
    svc.health.last_success = time.time()
    return svc


async def _call(service: CockpitService, tool: str, **kwargs: Any) -> dict[str, Any]:
    async with Client(build_mcp(service)) as client:
        result = await client.call_tool(tool, kwargs)
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    return json.loads(result.content[0].text)  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_every_board_tool_reports_staleness(service: CockpitService) -> None:
    """Non-negotiable: Claude cannot know the sync stalled unless the payload says so, and
    confidently recommending a player who went three picks ago is the worst failure here."""
    for tool, kwargs in [
        ("draft_status", {}), ("best_available", {}), ("recommend", {}),
        ("my_roster", {}), ("recent_picks", {}), ("player_lookup", {"name": "Player 010"}),
        ("compare", {"names": ["Player 010", "Player 011"]}),
        ("mark_taken", {"player_id": "p099"}), ("undo_taken", {}),
    ]:
        body = await _call(service, tool, **kwargs)
        assert "sync" in body, f"{tool} omits staleness"
        assert "age_seconds" in body["sync"], f"{tool} staleness has no age"


@pytest.mark.anyio
async def test_stale_sync_carries_an_explicit_warning(service: CockpitService) -> None:
    service.health.last_success = time.time() - 45
    body = await _call(service, "draft_status")
    assert body["sync"]["status"] == "failing"
    assert body["sync"]["warning"] and "unconfirmed" in body["sync"]["warning"]


@pytest.mark.anyio
async def test_live_sync_has_no_warning(service: CockpitService) -> None:
    body = await _call(service, "draft_status")
    assert body["sync"]["status"] == "live"
    assert body["sync"]["warning"] is None


@pytest.mark.anyio
async def test_draft_status_reports_the_clock(service: CockpitService) -> None:
    body = await _call(service, "draft_status")
    assert body["current_pick"] == 4
    assert body["i_am_on_the_clock"] is True
    assert body["picks_until_mine"] == 0
    assert body["rival_picks_before_my_next"] == 12
    assert "IDP_FLEX" in body["unfilled_starting_slots"]


@pytest.mark.anyio
async def test_best_available_ignores_roster_need(service: CockpitService) -> None:
    """The description promises the raw board; the behaviour must match or the wrong tool gets
    called on the clock."""
    body = await _call(service, "best_available", limit=5)
    assert len(body["players"]) == 5
    assert body["players"][0]["vorp_rank"] < body["players"][-1]["vorp_rank"]
    assert "p001" not in {p["id"] for p in body["players"]}  # drafted


@pytest.mark.anyio
async def test_best_available_filters_by_position(service: CockpitService) -> None:
    body = await _call(service, "best_available", position="qb", limit=25)
    assert body["players"]
    assert {p["position"] for p in body["players"]} == {"QB"}


@pytest.mark.anyio
async def test_recommend_is_roster_aware_and_explains_itself(service: CockpitService) -> None:
    body = await _call(service, "recommend", limit=5)
    assert body["recommendations"]
    for row in body["recommendations"]:
        assert row["reason"], "every recommendation must carry a deterministic reason"
        assert "VORP #" in row["reason"]
    assert body["unfilled_starting_slots"]
    assert body["rival_picks_before_my_next"] == 12


@pytest.mark.anyio
async def test_recommend_and_best_available_are_distinguishable(
    service: CockpitService,
) -> None:
    """If the two descriptions read alike the model picks the wrong one under time pressure."""
    async with Client(build_mcp(service)) as client:
        tools = {t.name: (t.description or "").lower() for t in await client.list_tools()}
    rec, best = tools["recommend"], tools["best_available"]
    assert "roster" in rec and "survive" in rec
    assert "ignoring" in best and "roster" in best
    assert rec != best


@pytest.mark.anyio
async def test_the_tool_surface_is_exactly_the_agreed_nine(service: CockpitService) -> None:
    async with Client(build_mcp(service)) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {
        "draft_status", "best_available", "recommend", "my_roster",
        "player_lookup", "compare", "recent_picks", "mark_taken", "undo_taken",
    }


@pytest.mark.anyio
async def test_player_lookup_distinguishes_missing_from_drafted(
    service: CockpitService,
) -> None:
    hit = await _call(service, "player_lookup", name="Player 010")
    assert hit["found"] and hit["matches"][0]["name"] == "Player 010"

    drafted = await _call(service, "player_lookup", name="Player 001")
    assert drafted["found"] is False
    assert drafted["already_drafted"], "a drafted player must be reported as drafted"
    assert "already been drafted" in drafted["message"]


@pytest.mark.anyio
async def test_compare_reports_players_it_could_not_find(service: CockpitService) -> None:
    body = await _call(service, "compare", names=["Player 010", "Nobody At All"])
    assert [p["name"] for p in body["players"]] == ["Player 010"]
    assert body["not_available"] == ["Nobody At All"]


@pytest.mark.anyio
async def test_mark_taken_is_local_idempotent_and_reversible(
    service: CockpitService,
) -> None:
    first = await _call(service, "mark_taken", player_id="p050")
    assert first["changed"] is True
    again = await _call(service, "mark_taken", player_id="p050")
    assert again["changed"] is False  # idempotent

    board = await _call(service, "best_available", limit=25)
    assert "p050" not in {p["id"] for p in board["players"]}

    undo = await _call(service, "undo_taken", player_id="p050")
    assert undo["undone"] == "p050"
    assert service.session.manual_taken == {}


@pytest.mark.anyio
async def test_mark_taken_never_moves_the_clock(service: CockpitService) -> None:
    before = (await _call(service, "draft_status"))["current_pick"]
    await _call(service, "mark_taken", player_id="p060")
    after = (await _call(service, "draft_status"))["current_pick"]
    assert before == after == 4


@pytest.mark.anyio
async def test_tools_degrade_honestly_when_the_board_is_not_ready(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    cold = CockpitService(sleeper_config, state_dir=tmp_path)
    body = await _call(cold, "recommend")
    assert body["board_ready"] is False
    assert body["message"]
    assert "recommendations" not in body  # never guess from a board that isn't there


@pytest.mark.anyio
async def test_no_tool_triggers_a_board_rebuild(
    service: CockpitService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sub-2s from warm state means no tool may reach for the network."""
    import audible.draft.board as board_mod

    def explode(*a: object, **k: object) -> None:
        raise AssertionError("a tool tried to rebuild the board")

    monkeypatch.setattr(board_mod, "build_board", explode)
    for tool in ("draft_status", "best_available", "recommend", "my_roster", "recent_picks"):
        await _call(service, tool)
