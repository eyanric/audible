"""Full-draft replay: feed picks in one at a time and assert the cockpit never lies.

Offline and deterministic. The real-data equivalent (the completed 2025 draft against the
live board) is run as a rehearsal, but the invariants worth regressing are all here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import Pick, my_slot_on_clock
from audible.draft.service import CockpitService
from audible.server.state import build_state

TEAMS, ROUNDS = 10, 18
TOTAL = TEAMS * ROUNDS
MY_SLOT = 4
POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]


def _board(n: int = 400) -> DraftBoard:
    entries = []
    for i in range(1, n + 1):
        pos = POSITIONS[(i - 1) % len(POSITIONS)]
        entries.append(DraftEntry(
            player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
            eligible_positions=frozenset({pos}), team="XX", model="consensus",
            points=800.0 - i, modeled_xfp=0.0, carried=0.0, consensus=800.0 - i,
            vorp=800.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i, deviation=False,
            scarcity=800.0 - i, scarcity_rank=i, adp=float(i), adp_rank=i, value=0, flags=(),
        ))
    return DraftBoard("sleeper_boyfun", entries)


def _service(tmp_path: Path, cfg: LeagueConfig) -> CockpitService:
    svc = CockpitService(cfg, state_dir=tmp_path, slot_override=MY_SLOT)
    svc.board = _board()
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.rounds = ROUNDS
    svc.session.slot = MY_SLOT
    svc.session.slot_source = "override"
    return svc


def _stream() -> list[Pick]:
    """A full snake draft, one player per pick, in board order."""
    return [
        Pick(pick_no=n, round=(n - 1) // TEAMS + 1,
             draft_slot=my_slot_on_clock(n, TEAMS, ROUNDS) or 0, player_id=f"p{n:03d}")
        for n in range(1, TOTAL + 1)
    ]


def test_full_draft_replay_holds_every_invariant(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    svc = _service(tmp_path, sleeper_config)
    stream = _stream()

    last_pick = 0
    my_picks_seen: list[int] = []
    grab_now_at_my_picks = 0

    for i in range(len(stream) + 1):
        svc.session.picks = stream[:i]
        svc._view_cache = None
        state = build_state(svc)
        clock = state["clock"]

        # the clock never rewinds, ever
        assert clock["current_pick"] >= last_pick, f"clock went backwards at step {i}"
        last_pick = clock["current_pick"]

        if clock["complete"]:
            assert i == TOTAL  # only the very end
            continue

        # the board drains: taken players are never offered
        taken = {p.player_id for p in stream[:i]}
        offered = {p["id"] for p in state["best_available"]}
        assert not (offered & taken), f"drafted player still on the board at step {i}"

        if clock["picks_until_me"] == 0:
            my_picks_seen.append(clock["current_pick"])
            if state["grab_now"]:
                grab_now_at_my_picks += 1

    # I own exactly one pick per round, and grab-now works on my clock, not just others'
    assert len(my_picks_seen) == ROUNDS
    assert my_picks_seen[:4] == [4, 17, 24, 37]  # snake, including the turn
    assert grab_now_at_my_picks >= ROUNDS - 2, (
        f"grab-now was dark at {ROUNDS - grab_now_at_my_picks} of my {ROUNDS} picks"
    )


def test_roster_fills_as_the_draft_runs(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    svc = _service(tmp_path, sleeper_config)
    stream = _stream()
    svc.session.picks = stream

    state = build_state(svc)
    roster = state["roster"]
    named = sum(len(s["players"]) for s in roster["slots"])
    filled = sum(s["filled"] for s in roster["slots"])

    assert named == filled, "every filled slot must name the player filling it"
    assert filled == len(sleeper_config.starting_slots) - len(roster["unfilled"])
    assert roster["starters_complete"] is (not roster["unfilled"])


def test_restart_midway_loses_nothing(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    """A crash at pick 40 must be invisible after a restart."""
    svc = _service(tmp_path, sleeper_config)
    stream = _stream()
    svc.session.picks = stream[:40]
    svc.mark_taken("p300")  # also persists
    before = build_state(svc)

    revived = _service(tmp_path, sleeper_config)
    assert revived.restore() is True
    after = build_state(revived)

    # 42, not 41: the hand-entered p300 became pick 41, so the clock is on 42. Manual picks
    # are real picks now, and a restart must restore the advanced clock too.
    assert after["clock"]["current_pick"] == before["clock"]["current_pick"] == 42
    assert [p["id"] for p in after["best_available"]] == [
        p["id"] for p in before["best_available"]
    ]
    assert "p300" not in {p["id"] for p in after["best_available"]}


def test_draft_id_is_rediscovered_when_the_pinned_id_is_wrong(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """If the commissioner deletes and recreates the draft when scheduling it, the id changes
    underneath us. A 404 on a known id means re-discover, not fail."""
    svc = _service(tmp_path, sleeper_config)
    svc.session.draft_id = "stale-id"
    svc.health.poll_count = 0  # forces a metadata refresh on this poll

    class Adapter:
        def __init__(self) -> None:
            self.discovered = 0

        def get_league_drafts(self, league_id: str) -> list[dict[str, Any]]:
            self.discovered += 1
            return [{"draft_id": "fresh-id"}]

        def get_draft(self, draft_id: str) -> dict[str, Any]:
            if draft_id == "stale-id":
                raise RuntimeError("404 draft not found")
            return {"settings": {"rounds": ROUNDS}, "status": "drafting", "type": "snake",
                    "draft_order": None, "slot_to_roster_id": {}}

        def get_users(self, league_id: str) -> list[dict[str, Any]]:
            return []

        def get_rosters(self, league_id: str) -> list[dict[str, Any]]:
            return []

        def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
            assert draft_id == "fresh-id", "must poll the rediscovered draft"
            return [{"player_id": "p001", "pick_no": 1, "round": 1, "draft_slot": 1}]

    adapter = Adapter()
    svc._adapter = adapter  # type: ignore[assignment]

    assert svc.poll_once() is True
    assert svc.session.draft_id == "fresh-id"
    assert adapter.discovered >= 1
    assert len(svc.session.picks) == 1


def test_draft_not_started_renders_no_clock(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    svc = _service(tmp_path, sleeper_config)
    svc.session.draft_status = "pre_draft"
    svc.session.picks = []
    state = build_state(svc)
    assert state["draft"]["started"] is False
    assert state["board_ready"] is True
    assert state["best_available"], "the board is still useful before the draft opens"


def test_completed_draft_freezes_instead_of_erroring(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    svc = _service(tmp_path, sleeper_config)
    svc.session.picks = _stream()
    state = build_state(svc)
    assert state["ok"] is True
    assert state["clock"]["complete"] is True
    assert state["clock"]["slot_on_clock"] is None


@pytest.mark.parametrize("slot", [1, 4, 10])
def test_my_picks_match_snake_ground_truth(
    tmp_path: Path, sleeper_config: LeagueConfig, slot: int
) -> None:
    """Every seat, not just the convenient middle one -- the wheel is where this breaks."""
    svc = _service(tmp_path, sleeper_config)
    svc._slot_override = slot
    svc.session.slot = slot
    stream = _stream()

    mine: list[int] = []
    for i in range(len(stream)):
        svc.session.picks = stream[:i]
        svc._view_cache = None
        clock = build_state(svc)["clock"]
        if clock["picks_until_me"] == 0 and not clock["complete"]:
            mine.append(clock["current_pick"])

    expected = [p.pick_no for p in stream if p.draft_slot == slot]
    assert mine == expected
