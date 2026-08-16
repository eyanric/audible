"""Cockpit service: identity resolution, persistence, manual overrides, poll resilience."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from audible.config import LeagueConfig
from audible.draft.identity import (
    SOURCE_DRAFT_ORDER,
    SOURCE_OVERRIDE,
    SOURCE_UNRESOLVED,
    resolve_slot,
    roster_id_for_slot,
    roster_id_for_user,
    user_id_for_name,
)
from audible.draft.live import Pick
from audible.draft.service import CockpitService, DraftSession, SyncHealth

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def draft_2025() -> dict[str, Any]:
    """The real completed 2025 draft of League A -- a genuine non-identity slot map."""
    return json.loads((FIXTURES / "sleeper_draft_2025.json").read_text(encoding="utf-8"))


# --- identity ------------------------------------------------------------------------------


def test_slot_resolution_matches_ground_truth(draft_2025: dict[str, Any]) -> None:
    me = draft_2025["me"]
    ident = resolve_slot(draft_2025["draft"], draft_2025["rosters"], me["user_id"])

    assert ident.slot == me["expected_slot"] == 3
    assert ident.roster_id == me["expected_roster_id"] == 6
    assert ident.source == SOURCE_DRAFT_ORDER


def test_the_identity_slot_map_would_have_lied(draft_2025: dict[str, Any]) -> None:
    """Pre-draft, slot_to_roster_id is the placeholder {1:1..10:10}. This asserts why we must
    never derive a slot from it: on the real completed draft, roster 6 sits at slot 3, so the
    placeholder would have put us in the wrong seat all night.
    """
    draft = draft_2025["draft"]
    me = draft_2025["me"]
    assert roster_id_for_slot(draft, 3) == me["expected_roster_id"]
    assert roster_id_for_slot(draft, me["expected_roster_id"]) != me["expected_roster_id"]


def test_unresolved_when_draft_order_is_absent(draft_2025: dict[str, Any]) -> None:
    """Our live 2026 draft has draft_order: null. The answer is "unknown", never a guess."""
    pre_draft = {**draft_2025["draft"], "draft_order": None}
    ident = resolve_slot(pre_draft, draft_2025["rosters"], draft_2025["me"]["user_id"])
    assert ident.slot is None
    assert ident.source == SOURCE_UNRESOLVED
    assert ident.roster_id == 6  # roster is still knowable; the SEAT is not


def test_override_wins_for_rehearsal(draft_2025: dict[str, Any]) -> None:
    ident = resolve_slot(
        draft_2025["draft"], draft_2025["rosters"], draft_2025["me"]["user_id"], override=7
    )
    assert (ident.slot, ident.source) == (7, SOURCE_OVERRIDE)


def test_user_lookup_by_display_name(draft_2025: dict[str, Any]) -> None:
    assert user_id_for_name(draft_2025["users"], "eyanric") == draft_2025["me"]["user_id"]
    assert user_id_for_name(draft_2025["users"], "EYANRIC") == draft_2025["me"]["user_id"]
    assert user_id_for_name(draft_2025["users"], "nobody") is None


def test_roster_join_survives_ragged_membership() -> None:
    """League A has more users than rosters, rosters with no owner, and a co-owner who owns
    no roster. A join that assumes 1:1 breaks on all three."""
    rosters = [
        {"roster_id": 3, "owner_id": None, "co_owners": None},
        {"roster_id": 4, "owner_id": "u9", "co_owners": ["u_co"]},
    ]
    assert roster_id_for_user(rosters, "u9") == 4
    assert roster_id_for_user(rosters, "u_co") == 4  # co-owner falls back correctly
    assert roster_id_for_user(rosters, "ghost") is None


# --- session state -------------------------------------------------------------------------


def _service(tmp_path: Path, cfg: LeagueConfig) -> CockpitService:
    return CockpitService(cfg, state_dir=tmp_path)


def test_state_survives_a_restart(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    """A crash at pick 40 must not cost the session."""
    svc = _service(tmp_path, sleeper_config)
    svc.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n}") for n in range(1, 41)
    ]
    svc.session.draft_id = "d1"
    svc.session.slot = 3
    svc.session.slot_source = SOURCE_DRAFT_ORDER
    svc.mark_taken("manual-1")

    revived = _service(tmp_path, sleeper_config)
    assert revived.restore() is True
    assert len(revived.session.picks) == 40
    assert revived.session.picks[-1].pick_no == 40
    assert revived.session.slot == 3
    assert revived.session.manual_taken == {"manual-1": 1}


def test_restore_ignores_another_league(tmp_path: Path, sleeper_config: LeagueConfig,
                                        espn_config: LeagueConfig) -> None:
    svc = _service(tmp_path, sleeper_config)
    svc.save()
    other = CockpitService(espn_config, state_dir=tmp_path)
    assert other.restore() is False


def test_restore_tolerates_a_corrupt_file(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    """A half-written file must degrade to "start fresh", never crash the cockpit."""
    svc = _service(tmp_path, sleeper_config)
    svc._state_path.write_text("{not json", encoding="utf-8")
    assert svc.restore() is False


def test_mark_taken_is_idempotent_and_reversible(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    svc = _service(tmp_path, sleeper_config)
    assert svc.mark_taken("x") is True
    assert svc.mark_taken("x") is False  # idempotent
    assert svc.undo_taken("x") == "x"
    assert svc.session.manual_taken == {}
    assert svc.undo_taken("x") is None


def test_undo_reverses_the_most_recent_mark(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    svc = _service(tmp_path, sleeper_config)
    svc.mark_taken("a")
    svc.mark_taken("b")
    assert svc.undo_taken() == "b"
    assert set(svc.session.manual_taken) == {"a"}


def test_manual_marks_never_move_the_clock(sleeper_config: LeagueConfig) -> None:
    """Manual picks remove a player from the pool; they must not advance the draft clock,
    which comes only from real picks."""
    session = DraftSession(league_key="k")
    session.picks = [Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n}") for n in (1, 2, 3)]
    session.manual_seq, session.manual_taken = 1, {"ghost": 1}

    effective = session.effective_picks()
    assert {p.player_id for p in effective} == {"p1", "p2", "p3", "ghost"}

    real_max = max(p.pick_no for p in session.picks)
    ghost = next(p for p in effective if p.player_id == "ghost")
    # pick_no 0: the clock is max(pick_no)+1, so any synthetic number would advance the draft
    # every time you tapped a name.
    assert ghost.pick_no == 0
    assert max(p.pick_no for p in effective) == real_max
    # ...and it sorts ahead of the real picks, so it can't masquerade as a recent pick in the
    # positional-run window, which is the tail of this list.
    assert effective[0].player_id == "ghost"


# --- sync health ---------------------------------------------------------------------------


def test_staleness_thresholds() -> None:
    h = SyncHealth()
    assert h.status() == "starting"  # nothing polled yet
    h.last_success = 1000.0
    assert h.status(1002.0) == "live"
    assert h.status(1015.0) == "stale"
    assert h.status(1040.0) == "failing"


def test_a_failed_poll_holds_last_known_state(
    tmp_path: Path, sleeper_config: LeagueConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 5xx must cost a beat, never the session -- picks stay, staleness rises."""
    svc = _service(tmp_path, sleeper_config)
    svc.session.draft_id = "d1"
    svc.session.picks = [Pick(pick_no=1, round=1, draft_slot=1, player_id="p1")]

    class Boom:
        def get_draft_picks(self, draft_id: str):
            raise RuntimeError("503 upstream")

        def get_draft(self, draft_id: str):
            return {"settings": {"rounds": 18}, "status": "drafting", "type": "snake"}

    svc._adapter = Boom()  # type: ignore[assignment]
    assert svc.poll_once() is False
    assert svc.session.picks  # last-known state retained
    assert svc.health.fail_streak == 1
    assert svc.health.last_error and "503" in svc.health.last_error


def test_only_one_poll_loop_can_start(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    """Two pollers would disagree about who is available, with no way to tell which is right."""
    svc = _service(tmp_path, sleeper_config)
    svc.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            svc.start()
    finally:
        svc.stop()
