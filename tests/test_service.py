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
from audible.draft.service import CockpitService, SyncHealth

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
    assert [p.player_id for p in revived.session.manual_picks] == ["manual-1"]
    assert revived.session.manual_picks[0].source == "manual"
    assert revived.session.manual_picks[0].pick_no == 41  # it followed the synced picks


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
    assert svc.session.manual_picks == []
    assert svc.undo_taken("x") is None


def test_undo_reverses_the_most_recent_mark(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    svc = _service(tmp_path, sleeper_config)
    svc.mark_taken("a")
    svc.mark_taken("b")
    assert svc.undo_taken() == "b"
    assert [p.player_id for p in svc.session.manual_picks] == ["a"]


def test_a_manual_mark_is_a_real_pick(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """DELIBERATE REVERSAL of the previous behaviour, and the fix for the whole gate.

    Manual marks used to carry pick_no=0 and draft_slot=0 so they could not advance the
    clock. That stopped the clock drifting and attributed every mark to slot 0 -- which is
    me whenever my slot is unresolved -- producing "unlimited players join my roster", "undo
    leaves them there", and "no other team ever appears" from one line.

    Mirroring a draft by hand means pick 4 happened, some team made it, and the clock is now
    at 5. That is what gets recorded.
    """
    svc = _service(tmp_path, sleeper_config)
    svc.session.rounds = 18
    svc.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n}") for n in (1, 2, 3)
    ]
    assert svc.mark_taken("hand") is True

    entered = svc.session.manual_picks[0]
    assert entered.pick_no == 4  # follows the synced picks
    assert entered.round == 1
    assert entered.draft_slot == 4  # 10-team snake: pick 4 belongs to slot 4, not to slot 0
    assert entered.source == "manual"

    effective = svc.session.effective_picks()
    assert [p.pick_no for p in effective] == [1, 2, 3, 4]  # one contiguous stream
    assert max(p.pick_no for p in effective) == 4  # the clock moved, because the pick happened


def test_manual_picks_are_attributed_around_the_table(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """The headline symptom: twelve marks must land on twelve different teams, not all on me."""
    svc = _service(tmp_path, sleeper_config)
    svc.session.rounds = 18
    for i in range(12):
        assert svc.mark_taken(f"p{i}") is True

    slots = [p.draft_slot for p in svc.session.manual_picks]
    assert slots == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 9]  # snake, including the turn
    assert len(set(slots)) == 10, "every team must receive picks, not just one"


def test_undo_restores_state_exactly(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    """Undo must be a true inverse -- board, clock and numbering identical to before."""
    svc = _service(tmp_path, sleeper_config)
    svc.session.rounds = 18
    svc.mark_taken("a")
    before = [(p.pick_no, p.draft_slot, p.player_id) for p in svc.session.effective_picks()]

    svc.mark_taken("b")
    assert svc.undo_taken() == "b"
    after = [(p.pick_no, p.draft_slot, p.player_id) for p in svc.session.effective_picks()]
    assert after == before


def test_undoing_from_the_middle_leaves_no_hole(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    svc = _service(tmp_path, sleeper_config)
    svc.session.rounds = 18
    for pid in ("a", "b", "c"):
        svc.mark_taken(pid)
    assert svc.undo_taken("b") == "b"

    picks = svc.session.manual_picks
    assert [p.player_id for p in picks] == ["a", "c"]
    assert [p.pick_no for p in picks] == [1, 2], "numbering must stay contiguous"
    assert [p.draft_slot for p in picks] == [1, 2]


def test_sync_supersedes_a_manual_pick_for_the_same_player(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """Regaining sync after mirroring by hand must not double-count anyone."""
    svc = _service(tmp_path, sleeper_config)
    svc.session.rounds = 18
    svc.mark_taken("star")
    svc.mark_taken("other")

    # Sync catches up and reports `star` at pick 1, taken by a different slot than we guessed.
    svc.session.picks = [Pick(pick_no=1, round=1, draft_slot=7, player_id="star")]
    svc._reconcile_manual()

    ids = [p.player_id for p in svc.session.manual_picks]
    assert ids == ["other"], "the synced player must be dropped from the manual list"
    effective = svc.session.effective_picks()
    assert [p.player_id for p in effective].count("star") == 1, "no double count"
    star = next(p for p in effective if p.player_id == "star")
    assert star.draft_slot == 7 and star.source == "sync", "sync wins on disagreement"
    assert [p.pick_no for p in effective] == [1, 2]


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
