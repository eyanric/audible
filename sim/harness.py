"""Hand-built draft states. No network, no cached data, no season replay.

Every gate in this package constructs a situation whose correct answer is known by
construction and asserts against it. That is the whole design: a defect you can only
see by replaying a season is a defect you cannot put in CI.

Nothing here imports from ``tests/``. The patterns are the same ones
``tests/test_recommend_bench.py`` established -- a synthetic board, a synthetic pick
list, a ``CockpitService`` with both stuffed in, and the MCP tools called over an
in-process client -- but the gates own their own copy so a change to the fast suite
cannot silently retune them.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastmcp import Client

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import Pick
from audible.draft.service import CockpitService
from audible.draft.usage import UsageTable
from audible.server.mcp import build_mcp

TEAMS = 8
MY_SLOT = 1


# --- board ----------------------------------------------------------------------------


def entry(
    pid: str,
    name: str,
    pos: str,
    vorp_rank: int,
    *,
    adp: float | None = None,
    eligible: frozenset[str] | None = None,
    team: str = "XX",
    points: float | None = None,
) -> DraftEntry:
    """One board row.

    ``points`` defaults to a strictly decreasing function of ``vorp_rank`` so the board is
    internally consistent: a better rank is always worth more. ``adp`` defaults to the rank,
    which makes the market agree with the board unless a gate deliberately parts them.
    """
    pts = 400.0 - vorp_rank if points is None else points
    return DraftEntry(
        player_id=pid,
        name=name,
        position=pos,
        eligible_positions=eligible if eligible is not None else frozenset({pos}),
        team=team,
        model="consensus",
        points=pts,
        modeled_xfp=0.0,
        carried=0.0,
        consensus=pts,
        vorp=pts,
        vorp_rank=vorp_rank,
        consensus_rank=vorp_rank,
        opp_rank=vorp_rank,
        deviation=False,
        scarcity=pts,
        scarcity_rank=vorp_rank,
        adp=float(vorp_rank) if adp is None else adp,
        adp_rank=vorp_rank,
        value=0,
        flags=(),
    )


def board_of(entries: list[DraftEntry], key: str = "sim") -> DraftBoard:
    """A board in the order the engine expects: sorted by ``vorp_rank``."""
    return DraftBoard(key, sorted(entries, key=lambda e: e.vorp_rank))


def filler(prefix: str, count: int, pos: str, first_rank: int) -> list[DraftEntry]:
    """Depth so replacement baselines and the served pool are not degenerate.

    A three-player board makes every position scarce and every baseline meaningless, which
    is its own artefact. These are deliberately ranked below anything a gate asserts on.
    """
    return [
        entry(f"{prefix}{i:03d}", f"{pos} {prefix}{i:03d}", pos, first_rank + i)
        for i in range(1, count + 1)
    ]


# --- leagues --------------------------------------------------------------------------


def standard_league(
    *,
    teams: int = TEAMS,
    rounds: int = 16,
    key: str = "sim_standard",
    starting_slots: tuple[str, ...] | None = None,
    slot_eligibility: dict[str, tuple[str, ...]] | None = None,
) -> LeagueConfig:
    """A 1-QB league with two dedicated RB slots and a flex -- the shape G-NEED needs.

    Two RB slots that take ONLY RB is the structural fact behind the bye-week finding in
    docs/STATE.md: a roster holding exactly two running backs has no legal lineup in any
    week both are out, and no flex can rescue it because the RB slots are dedicated.
    """
    slots = starting_slots or ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "K", "DEF")
    elig = slot_eligibility or {
        "QB": ("QB",),
        "RB": ("RB",),
        "WR": ("WR",),
        "TE": ("TE",),
        "FLEX": ("RB", "WR", "TE"),
        "K": ("K",),
        "DEF": ("DEF",),
    }
    return LeagueConfig.model_validate(
        {
            "key": key,
            "name": "sim standard",
            "platform": "sleeper",
            "league_id": "0",
            "season": 2026,
            "num_teams": teams,
            "draft_rounds": rounds,
            "starting_slots": list(slots),
            "slot_eligibility": {k: list(v) for k, v in elig.items()},
            "scoring": {"rec": 0.5},
        }
    )


def idp_league(*, teams: int = TEAMS, rounds: int = 16, key: str = "sim_idp") -> LeagueConfig:
    """BoyFun's shape, reduced: one IDP_FLEX taking DL/LB/DB, and a SUPER_FLEX.

    The slot names carry no meaning to the engine -- eligibility is what it reads -- which is
    exactly the thing commit 35e51342 changed and G-OCC exists to check.
    """
    return LeagueConfig.model_validate(
        {
            "key": key,
            "name": "sim idp",
            "platform": "sleeper",
            "league_id": "0",
            "season": 2026,
            "num_teams": teams,
            "draft_rounds": rounds,
            "starting_slots": [
                "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "IDP_FLEX", "K", "DEF"
            ],
            "slot_eligibility": {
                "QB": ["QB"],
                "RB": ["RB"],
                "WR": ["WR"],
                "TE": ["TE"],
                "FLEX": ["RB", "WR", "TE"],
                "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
                "IDP_FLEX": ["DL", "LB", "DB"],
                "K": ["K"],
                "DEF": ["DEF"],
            },
            "scoring": {"rec": 0.5},
        }
    )


# --- the draft ------------------------------------------------------------------------


def slot_on_clock(pick_no: int, teams: int) -> int:
    """Which draft slot owns ``pick_no`` in a snake."""
    rnd = (pick_no - 1) // teams + 1
    idx = (pick_no - 1) % teams
    return idx + 1 if rnd % 2 == 1 else teams - idx


def current_pick_after(n_picks: int, teams: int, *, my_slot: int = MY_SLOT) -> int:
    """The pick number at which I am on the clock having ALREADY made *n_picks*.

    A GATE THAT GETS THIS WRONG SILENTLY BUILDS A DIFFERENT SCENARIO. `picks_up_to` hands my
    ids out only at picks my seat owns, so passing more ids than the seat owns by
    `current_pick` drops the surplus on the floor -- and because those ids are still on the
    board, the extra players read as AVAILABLE. A roster meant to be full of receivers is
    then a roster with two receivers and two suspiciously good ones still on the board, and
    every assertion about surplus is measuring nothing. Seen twice while building G-CALL.
    """
    mine = [n for n in range(1, teams * 64) if slot_on_clock(n, teams) == my_slot]
    if n_picks >= len(mine):
        raise ValueError(f"seat {my_slot} of {teams} does not make {n_picks + 1} picks")
    return mine[n_picks]


def picks_up_to(
    current_pick: int,
    teams: int,
    *,
    my_slot: int,
    my_player_ids: list[str],
) -> list[Pick]:
    """Every pick BEFORE ``current_pick``: mine in order, everyone else's as filler.

    Filler ids are ``gone###`` and must exist on the board, or they are silently dropped
    from the roster view and the draft looks emptier than it is.
    """
    picks: list[Pick] = []
    mine = iter(my_player_ids)
    for n in range(1, current_pick):
        rnd = (n - 1) // teams + 1
        slot = slot_on_clock(n, teams)
        pid = next(mine, f"gone{n:03d}") if slot == my_slot else f"gone{n:03d}"
        picks.append(Pick(pick_no=n, round=rnd, draft_slot=slot, player_id=pid))
    return picks


def service(
    config: LeagueConfig,
    state_dir: Path,
    *,
    current_pick: int,
    entries: list[DraftEntry],
    my_player_ids: list[str],
    my_slot: int = MY_SLOT,
    byes: dict[str, int] | None = None,
) -> CockpitService:
    """A cockpit mid-draft, with a hand-built board and a hand-built pick list.

    ``byes`` is injected as a ``UsageTable`` rather than derived. `CockpitService` seeds an
    empty one at construction and fills it from the nflverse cache at board-build time, which
    a gate must not depend on: the schedule is network- and cache-shaped, and G-BYE is about
    whether the number is CONSUMED, not about where it comes from.
    """
    svc = CockpitService(config, state_dir=state_dir, slot_override=my_slot)
    all_entries = list(entries)
    all_entries += [
        entry(f"gone{i:03d}", f"Gone {i:03d}", "RB", 900 + i) for i in range(1, current_pick + 1)
    ]
    svc.board = board_of(all_entries, config.key)
    svc.session.draft_id = "sim"
    svc.session.draft_status = "drafting"
    svc.session.slot = my_slot
    svc.session.slot_source = "override"
    svc.session.picks = picks_up_to(
        current_pick, config.num_teams, my_slot=my_slot, my_player_ids=my_player_ids
    )
    if byes is not None:
        svc.usage = UsageTable(bye_by_team=dict(byes))
    svc.health.last_success = time.time()
    return svc


def call(svc: CockpitService, tool: str, **kwargs: Any) -> dict[str, Any]:
    """Invoke one MCP tool over an in-process client -- the surface Eric actually reads."""

    async def go() -> dict[str, Any]:
        async with Client(build_mcp(svc)) as client:
            result = await client.call_tool(tool, kwargs)
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            return data
        return json.loads(result.content[0].text)  # type: ignore[union-attr]

    return asyncio.run(go())
