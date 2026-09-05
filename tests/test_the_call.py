"""The Call and the availability arithmetic, over a real FastMCP client.

G9 of the pre-registered gate set: The Call, its reasoning, both market ranks and the
roster table all have to reach the surface Eric queries from his phone. A number that is
computed correctly and then dropped by `_slim` is the failure this whole lane exists to
fix -- `points` and `value` were computed correctly for months and never reached a single
MCP response.
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
from audible.draft.urgency import (
    NOISE_FLOOR_POSITIONS,
    SURVIVAL_SAFE,
    RosterNeed,
    _need_score,
    confidence,
    detect_run,
    roster_needs,
    survives_by,
    the_call,
)
from audible.server.mcp import build_mcp

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# Same hand-built board as `test_mcp.py`, with ADP spread wide enough that some candidates
# sit past the horizon and some do not -- a fixture where everyone is urgent cannot tell a
# working horizon from an ignored one.
_POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]


def _entry(i: int) -> DraftEntry:
    pos = _POSITIONS[(i - 1) % len(_POSITIONS)]
    return DraftEntry(
        player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
        eligible_positions=frozenset({pos}), team="XX", model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=(i % 17 == 0), scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i) * 1.5, adp_rank=i, value=0, flags=(),
    )


@pytest.fixture
def service(tmp_path: Path, sleeper_config: LeagueConfig) -> CockpitService:
    """Isolated `state_dir` per test -- the real draft state is never opened."""
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


async def _call(service: Any, tool: str, **kwargs: Any) -> dict[str, Any]:
    async with Client(build_mcp(service)) as client:
        result = await client.call_tool(tool, kwargs)
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    return json.loads(result.content[0].text)  # type: ignore[union-attr]


# -- the arithmetic itself: pure, and it must stay subtraction ---------------------------


def test_survival_is_exactly_adp_minus_next_pick() -> None:
    assert survives_by(61.9, 57) == 4.9
    assert survives_by(46.9, 72) == -25.1
    # Unknown on either side is None, never 0 -- 0 would read as "exactly on the bubble".
    assert survives_by(None, 57) is None
    assert survives_by(61.9, None) is None


def test_every_noise_floor_position_is_marked_low() -> None:
    for pos in NOISE_FLOOR_POSITIONS:
        assert confidence(pos) == "low"
    for pos in ("RB", "WR"):
        assert confidence(pos) == "usable"


def test_a_run_is_named_and_the_advice_is_not_to_join_it() -> None:
    picks = [{"position": "QB"}] * 5 + [{"position": "RB"}] * 3
    run = detect_run(picks)
    assert run["run_position"] == "QB"
    assert run["run_count"] == 5
    assert "cheaper" in run["advice"]
    # A spread of positions is a draft, not a run.
    spread = [{"position": p} for p in ("QB", "RB", "WR", "TE", "RB", "WR", "QB", "TE")]
    assert detect_run(spread)["run_position"] is None


# -- The Call's contract -----------------------------------------------------------------


def _cand(pid: str, name: str, pos: str, rank: int, adp: float | None) -> dict[str, Any]:
    return {"id": pid, "name": name, "position": pos, "vorp_rank": rank, "adp": adp,
            "platform_rank": None}


def test_a_player_the_market_says_will_last_is_not_the_call() -> None:
    """The pick that motivated this: the board loves him, the market says wait, so wait."""
    cands = [
        _cand("1", "Waits Easily", "WR", 1, 90.0),   # +33 past my next pick
        _cand("2", "Going Now", "RB", 2, 45.0),      # -12: gone before I pick again
    ]
    out = the_call(cands, next_pick=57,
                   needs={"RB": RosterNeed("RB", 2, 0), "WR": RosterNeed("WR", 2, 0)},
                   available_entries=[])
    assert out["pick"]["name"] == "Going Now"
    assert [s["name"] for s in out["skipped_as_likely_to_last"]] == ["Waits Easily"]
    assert out["pick"]["survives_by"] == 45.0 - 57


def test_the_call_never_names_a_player_outside_the_top_twelve() -> None:
    cands = [_cand(str(i), f"P{i}", "WR", i, 40.0) for i in range(1, 30)]
    out = the_call(cands, next_pick=57, needs={}, available_entries=[])
    assert out["considered"] == 12
    assert int(out["pick"]["id"]) <= 12


def test_the_survival_figure_is_the_subtraction_it_claims_to_be() -> None:
    out = the_call([_cand("1", "X", "RB", 1, 61.9)], next_pick=57, needs={},
                   available_entries=[])
    assert out["pick"]["survives_by"] == round(61.9 - 57, 1)
    assert "61.9 - next pick 57" in out["pick"]["survival_arithmetic"]


def test_a_quarterback_figure_is_marked_low_confidence() -> None:
    out = the_call([_cand("1", "A QB", "QB", 1, 50.0)], next_pick=57, needs={},
                   available_entries=[])
    assert out["pick"]["survival_confidence"] == "low"


def test_roster_need_is_visible_and_changes_the_call() -> None:
    cands = [_cand("1", "Best WR", "WR", 1, 50.0), _cand("2", "Good RB", "RB", 2, 50.0)]
    wr_full = {"WR": RosterNeed("WR", 2, 2), "RB": RosterNeed("RB", 2, 0)}
    rb_full = {"WR": RosterNeed("WR", 2, 0), "RB": RosterNeed("RB", 2, 2)}
    a = the_call(cands, next_pick=57, needs=wr_full, available_entries=[])
    b = the_call(cands, next_pick=57, needs=rb_full, available_entries=[])
    assert a["pick"]["name"] == "Good RB"
    assert b["pick"]["name"] == "Best WR"
    assert {r["slot"] for r in a["roster_need"]} == {"WR", "RB"}
    # The reason must NOT open with the runner-up's name: the page composes the sentence
    # around it, and returning the name here printed it twice.
    assert not (a["why_not_the_runner_up"] or "").startswith(a["runner_up"]["name"])


def test_the_horizon_changes_the_answer() -> None:
    """G4 in miniature. The first implementation used the horizon only as a filter and
    produced an identical Call with the horizon frozen -- the inert-column failure."""
    cands = [_cand("1", "Lasts", "WR", 1, 70.0), _cand("2", "Going", "WR", 2, 50.0)]
    near = the_call(cands, next_pick=55, needs={}, available_entries=[])
    far = the_call(cands, next_pick=200, needs={}, available_entries=[])
    assert near["pick"]["name"] == "Going"
    assert far["pick"]["name"] == "Lasts"


# -- G9: it all reaches a real FastMCP client -------------------------------------------


async def test_slim_carries_the_magnitudes_not_just_the_ranks(service: Any) -> None:
    """`_slim` dropped `points` and `value`, so a model on this surface had order but no
    distance, and reasoned from general football knowledge instead."""
    body = await _call(service, "best_available", limit=5)
    rows = body["players"]
    assert rows, "no rows to check"
    for key in ("points", "value", "adp", "platform_rank", "survives_by",
                "survival_arithmetic", "survival_confidence"):
        assert key in rows[0], f"_slim dropped {key}"
    # Present is not enough -- the usage lane shipped once with every field null.
    assert any(r.get("points") is not None for r in rows), "points never populated"
    assert any(r.get("survival_confidence") is not None for r in rows)


async def test_the_call_and_its_reasoning_reach_the_client(service: Any) -> None:
    body = await _call(service, "recommend", limit=5)
    assert "the_call" in body, "The Call is absent from recommend"
    call = body["the_call"]
    for key in ("pick", "runner_up", "why_now", "what_it_costs",
                "why_not_the_runner_up", "roster_need", "skipped_as_likely_to_last"):
        assert key in call, f"The Call is missing {key}"
    assert "run" in body, "run detection is absent"
    if call["pick"] is not None:
        for key in ("board_rank", "platform_rank", "adp", "survives_by",
                    "survival_arithmetic", "survival_confidence"):
            assert key in call["pick"], f"The Call's pick is missing {key}"


async def test_the_call_stays_inside_the_top_twelve_on_a_real_board(service: Any) -> None:
    body = await _call(service, "recommend", limit=5)
    call = body["the_call"]
    if call["pick"] is None:
        pytest.skip("no eligible candidate on this fixture board")
    top = await _call(service, "best_available", limit=12)
    assert call["pick"]["id"] in {r["id"] for r in top["players"]}


def test_the_threshold_is_the_one_that_was_pre_registered() -> None:
    assert SURVIVAL_SAFE == 10


# -- roster need reads the league's own slot eligibility ---------------------------------
# Step 0b on 2026-09-05 found `_need_score` walking a hardcoded flex list and crediting
# every position for every flex. With only `IDP_FLEX` open on BoyFun, The Call named a
# tight end and said "TE still fills a flex" while the roster panel beside it read
# `IDP_FLEX: 0/1 short 1`. These pin the fix in both directions.

_BOYFUN_ELIGIBILITY = {
    "QB": ["QB"], "RB": ["RB"], "WR": ["WR"], "TE": ["TE"],
    "FLEX": ["RB", "WR", "TE"], "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
    "K": ["K"], "DEF": ["DEF"], "IDP_FLEX": ["DL", "LB", "DB"],
}


def _needs(open_slot: str) -> dict[str, RosterNeed]:
    """Every BoyFun slot filled except *open_slot*."""
    counts = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "SUPER_FLEX": 1,
              "K": 1, "DEF": 1, "IDP_FLEX": 1}
    return roster_needs(
        [{"slot": s, "total": t, "filled": 0 if s == open_slot else t}
         for s, t in counts.items()],
        _BOYFUN_ELIGIBILITY,
    )


def test_only_an_idp_can_score_for_the_idp_slot() -> None:
    needs = _needs("IDP_FLEX")
    for pos in ("DL", "LB", "DB"):
        assert _need_score(pos, needs) > 0, f"{pos} can fill IDP_FLEX"
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        assert _need_score(pos, needs) == 0, f"{pos} cannot fill IDP_FLEX"


def test_a_kicker_scores_nothing_from_an_open_flex() -> None:
    needs = _needs("FLEX")
    for pos in ("RB", "WR", "TE"):
        assert _need_score(pos, needs) == 1
    for pos in ("K", "DEF", "QB", "LB"):
        assert _need_score(pos, needs) == 0


def test_superflex_is_quarterback_demand_and_only_for_who_can_fill_it() -> None:
    needs = _needs("SUPER_FLEX")
    for pos in ("QB", "RB", "WR", "TE"):
        assert _need_score(pos, needs) == 1
    for pos in ("K", "DEF", "LB"):
        assert _need_score(pos, needs) == 0


def test_a_dedicated_slot_outranks_a_shared_one() -> None:
    """Someone else can take the flex; nobody else can take the kicker slot."""
    assert _need_score("K", _needs("K")) == 2
    assert _need_score("RB", _needs("FLEX")) == 1


def test_the_call_names_a_player_who_can_actually_fill_the_hole() -> None:
    cands = [_cand("1", "A TE", "TE", 1, 40.0), _cand("2", "A LB", "LB", 9, 40.0)]
    out = the_call(cands, next_pick=57, needs=_needs("IDP_FLEX"), available_entries=[])
    assert out["pick"]["name"] == "A LB", "named someone who cannot fill the only open slot"


# -- the unresolved seat says which number is missing, and why ---------------------------


def test_an_unresolved_seat_is_named_as_such_not_blamed_on_a_missing_adp() -> None:
    """BoyFun's seat is unresolved until kickoff, so this is the pre-draft state."""
    out = the_call([_cand("1", "Has An ADP", "RB", 1, 2.0)], next_pick=None, needs={},
                   available_entries=[])
    assert out["seat_resolved"] is False
    assert "SEAT UNRESOLVED" in out["why_now"]
    text = out["pick"]["survival_arithmetic"]
    assert "SEAT IS NOT RESOLVED" in text
    assert "no ADP" not in text, "blamed a missing ADP on a player who has one"
    assert out["pick"]["survives_by"] is None, "invented a figure it could not compute"


def test_a_resolved_seat_shows_the_subtraction() -> None:
    out = the_call([_cand("1", "X", "RB", 1, 2.0)], next_pick=20, needs={},
                   available_entries=[])
    assert out["seat_resolved"] is True
    assert out["pick"]["survival_arithmetic"] == "ADP 2.0 - next pick 20 = -18.0"


def test_unresolved_picks_are_counted_but_never_called_a_run() -> None:
    """`_recent_picks` writes "?" when a pick's player is not on the board. That is an
    absence of information, not a position -- calling it a run printed reach advice about
    a question mark."""
    run = detect_run([{"position": "?"}] * 7)
    assert run["counts"] == {"?": 7}
    assert run["run_position"] is None
    assert run["advice"] is None
    mixed = detect_run([{"position": "?"}] * 4 + [{"position": "QB"}] * 4)
    assert mixed["run_position"] == "QB"
