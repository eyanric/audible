"""The hybrid reception rule must reach EVERY tool surface, or none of them can be trusted.

League B pays WR and TE 0.5 a catch and a running back nothing. That single fact reorders
RB against WR by ~30 points a season, and it is applied in exactly one place --
`LeagueConfig.scoring_for(position)`, resolved once per player in `_project_line`. Every
number the cockpit and the MCP tools serve is downstream of that one call.

Which is exactly the failure mode worth a test. A correction applied on one code path and
not another does not look broken; it looks like two surfaces quietly disagreeing about what
a pass-catching back is worth, on the clock, with ninety seconds to pick.

So these do not re-check the arithmetic -- tests/test_scoring.py owns that. They drive the
SAME player through the real board assembly and out through best_available, recommend,
compare and player_lookup over a real FastMCP client, and assert two things that only hold
together: the four surfaces agree with each other, AND what they agree on actually moves
when the reception rule is taken away. Agreement alone proves nothing -- four surfaces
reading one uncorrected board agree perfectly.
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
from audible.draft.board import DraftBoard, _project_line, build_board_from_lines
from audible.draft.service import CockpitService
from audible.models.player import RawPlayerLine
from audible.server.mcp import build_mcp

# One stat line, scored as each position. A high-volume receiving back is where the rule bites.
PASS_CATCHING_LINE = {"rec": 60.0, "rec_yd": 600.0, "rush_yd": 1250.0, "rush_td": 8.0}
TARGET = "rb001"
SURFACES = ("best_available", "recommend", "compare", "player_lookup")


def _line(pid: str, name: str, position: str, stats: dict[str, float]) -> RawPlayerLine:
    return RawPlayerLine(
        player_id=pid,
        name=name,
        primary_position=position,
        eligible_positions=frozenset({position}),
        team="XX",
        years_exp=5,
        stats=stats,
    )


def _project(config: LeagueConfig, position: str) -> float:
    """Run the shared line through the board's real projection path as *position*."""
    return _project_line(
        _line("x", "X", position, PASS_CATCHING_LINE),
        config,
        gsis=None,
        opp={},
        traj={},
        vacated={},
        teams={},
        dc_by_gsis={},
        dc_by_name={},
    ).points


def test_the_board_projection_path_applies_the_reception_rule(
    espn_config: LeagueConfig,
) -> None:
    """`_project_line` is the single origin of every served number. If the rule is not
    applied HERE it is applied nowhere, whatever the config says."""
    as_rb = _project(espn_config, "RB")
    as_wr = _project(espn_config, "WR")
    assert as_wr - as_rb == pytest.approx(30.0)

    flat = espn_config.model_copy(update={"scoring_by_position": {}})
    assert _project(flat, "RB") - as_rb == pytest.approx(30.0), (
        "a back scored off the base table runs 30 points a season high"
    )


def _board(config: LeagueConfig) -> DraftBoard:
    """A small League B board, built through the real assembly path, offline.

    Deep enough per position that replacement levels are real rather than degenerate, and
    the pass-catching back is the only player whose points depend on the reception rule --
    so any rank movement is attributable to it and nothing else.
    """
    lines: list[RawPlayerLine] = [_line(TARGET, "Pass Catching Back", "RB", PASS_CATCHING_LINE)]
    for i in range(1, 61):
        lines.append(_line(f"rb{i + 1:03d}", f"RB {i:03d}", "RB", {"rush_yd": 2400.0 - i * 30.0}))
        lines.append(_line(f"wr{i:03d}", f"WR {i:03d}", "WR", {"rec_yd": 2350.0 - i * 30.0}))
        lines.append(_line(f"te{i:03d}", f"TE {i:03d}", "TE", {"rec_yd": 1900.0 - i * 30.0}))
        lines.append(_line(f"qb{i:03d}", f"QB {i:03d}", "QB", {"pass_yd": 8250.0 - i * 75.0}))
    for i in range(1, 21):
        lines.append(_line(f"k{i:03d}", f"K {i:03d}", "K", {"xpm": 40.0 - i}))
        lines.append(_line(f"def{i:03d}", f"DEF {i:03d}", "DEF", {"sack": 40.0 - i}))
    return build_board_from_lines(config, lines)


def _service(config: LeagueConfig, state_dir: Path) -> CockpitService:
    svc = CockpitService(config, state_dir=state_dir, slot_override=1)
    svc.board = _board(config)
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = 1
    svc.session.slot_source = "override"
    svc.health.last_success = time.time()
    return svc


@pytest.fixture
def espn_service(tmp_path: Path, espn_config: LeagueConfig) -> CockpitService:
    return _service(espn_config, tmp_path)


def _call(service: CockpitService, tool: str, **kwargs: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        async with Client(build_mcp(service)) as client:
            result = await client.call_tool(tool, kwargs)
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            return data
        return json.loads(result.content[0].text)  # type: ignore[union-attr]

    return asyncio.run(go())


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("players", "recommendations", "matches"):
        found = payload.get(key)
        if found:
            return found if isinstance(found, list) else [found]
    raise AssertionError(f"no player rows in payload: {sorted(payload)}")


def _find(service: CockpitService, tool: str, **kwargs: Any) -> dict[str, Any]:
    payload = _call(service, tool, **kwargs)
    rows = [r for r in _rows(payload) if r["id"] == TARGET]
    assert rows, f"{tool} did not return {TARGET}"
    return rows[0]


def _every_surface(service: CockpitService) -> dict[str, dict[str, Any]]:
    return {
        "best_available": _find(service, "best_available", limit=25),
        "recommend": _find(service, "recommend", limit=25),
        "compare": _find(service, "compare", names=["Pass Catching Back", "WR 001"]),
        "player_lookup": _find(service, "player_lookup", name="Pass Catching Back"),
    }


def test_every_surface_reports_the_same_player_identically(
    espn_service: CockpitService,
) -> None:
    """The four surfaces are projections over one warmed board, so any disagreement means
    one of them recomputed something -- the silent-failure pattern this file exists for."""
    rows = _every_surface(espn_service)
    pinned = ("position", "vorp_rank", "consensus_rank", "opportunity_rank")
    baseline = {k: rows["best_available"][k] for k in pinned}
    for surface in SURFACES:
        assert {k: rows[surface][k] for k in pinned} == baseline, (
            f"{surface} disagrees with best_available about {TARGET}"
        )


def test_every_surface_moves_when_the_reception_rule_is_removed(
    tmp_path: Path, espn_config: LeagueConfig
) -> None:
    """The real assertion: the served ranks must be DERIVED from the corrected scoring.

    Build the same board off a config with `scoring_by_position` stripped and require every
    surface to report a different rank for the pass-catching back. A surface that does not
    move is serving a value the correction never reached.
    """
    flat = espn_config.model_copy(update={"scoring_by_position": {}})
    corrected = _every_surface(_service(espn_config, tmp_path / "corrected"))
    uncorrected = _every_surface(_service(flat, tmp_path / "flat"))

    assert len({r["vorp_rank"] for r in corrected.values()}) == 1
    assert len({r["vorp_rank"] for r in uncorrected.values()}) == 1
    for surface in SURFACES:
        assert corrected[surface]["vorp_rank"] != uncorrected[surface]["vorp_rank"], (
            f"{surface} reports the same rank with and without the reception rule -- "
            f"it is serving a value the correction never reached"
        )


def test_recommend_never_reports_a_survival_of_none_percent(
    espn_service: CockpitService,
) -> None:
    """An unpriced player's survival is UNKNOWN, and the reason string used to say so with
    the literal text "None%" -- a number-shaped non-number, in the one field the model is
    told to read as the justification."""
    payload = _call(espn_service, "recommend", limit=20)
    assert payload["recommendations"], "no recommendations to check"
    for row in payload["recommendations"]:
        assert "None%" not in row["reason"], row["reason"]
        if row["survival_pct"] is None and "rival picks" in row["reason"]:
            assert "unknown odds" in row["reason"], row["reason"]
