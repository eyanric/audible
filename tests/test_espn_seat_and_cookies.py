"""The two things that were silently unenforceable before: a pinned seat, and whose cookies.

Both had the same shape of bug -- a value that could only ever agree with itself, so the check
written to catch a disagreement could never fire. ``_identity`` returned the override before
deriving anything, and every adapter read one fixed pair of environment keys.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from audible.adapters.espn import EspnAdapter, EspnAuthError
from audible.config import LeagueConfig
from audible.draft.identity import SOURCE_OVERRIDE, SOURCE_PICK_ORDER
from audible.draft.service import CockpitService
from audible.draft.sync import EspnIdBridge, EspnSync

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The committed capture is league 6012, whose SWID-derived seat is 8.
DERIVED_SEAT = 8


@pytest.fixture
def detail() -> dict[str, Any]:
    return json.loads((FIXTURES / "espn_draft_detail.json").read_text(encoding="utf-8"))


def _adapter(payload: dict[str, Any], swid: str) -> EspnAdapter:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, headers={"etag": 'W/"abc"'})

    return EspnAdapter(swid=swid, espn_s2="s2", transport=httpx.MockTransport(handler))


def _sync(payload: dict[str, Any], config: LeagueConfig, *, slot_override: int | None) -> EspnSync:
    return EspnSync(
        config,
        adapter=_adapter(payload, payload["_my_swid"]),
        bridge=EspnIdBridge({}),
        slot_override=slot_override,
    )


# --- the seat -------------------------------------------------------------------------


def test_the_derivation_runs_even_when_a_seat_is_pinned(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The pin still wins, but it no longer erases the platform's own answer.

    This is the whole fix. Returning the override before reading ``teams[].owners`` made
    "derived disagrees with pinned" unrepresentable, so every check for it was dead code.
    """
    update = _sync(detail, espn_config, slot_override=2).poll(
        None, want_meta=True, slot_locked=False
    )
    assert update.identity is not None
    assert update.identity.slot == 2, "the pin must still win -- that is what a pin is for"
    assert update.identity.source == SOURCE_OVERRIDE
    assert update.identity.derived_slot == DERIVED_SEAT, "the derivation must still have run"
    assert update.identity.seat_conflict is True


def test_a_pin_that_agrees_with_the_platform_is_not_a_conflict(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    update = _sync(detail, espn_config, slot_override=DERIVED_SEAT).poll(
        None, want_meta=True, slot_locked=False
    )
    assert update.identity is not None
    assert update.identity.seat_conflict is False


def test_an_unpinned_seat_reports_the_derivation_as_both(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    update = _sync(detail, espn_config, slot_override=None).poll(
        None, want_meta=True, slot_locked=False
    )
    assert update.identity is not None
    assert update.identity.slot == DERIVED_SEAT
    assert update.identity.derived_slot == DERIVED_SEAT
    assert update.identity.source == SOURCE_PICK_ORDER
    assert update.identity.seat_conflict is False


def test_seat_drift_reaches_the_log_when_the_pin_disagrees(
    detail: dict[str, Any], espn_config: LeagueConfig, caplog: pytest.LogCaptureFixture
) -> None:
    """The error CockpitService has always carried, and could never reach."""
    service = CockpitService(
        espn_config, slot_override=2, sync=_sync(detail, espn_config, slot_override=2)
    )
    with caplog.at_level(logging.ERROR, logger="audible.cockpit"):
        service.poll_once()
    drift = [r for r in caplog.records if "SEAT DRIFT" in r.getMessage()]
    assert len(drift) == 1, f"expected exactly one SEAT DRIFT record, got {len(drift)}"
    assert "pinned slot 2" in drift[0].getMessage()
    assert f"platform says {DERIVED_SEAT}" in drift[0].getMessage()


def test_verify_structure_reports_a_seat_that_disagrees(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """A wrong pin is now a non-zero exit from verify-scoring, not a log line nobody reads."""
    adapter = _adapter(detail, detail["_my_swid"])
    agreeing = espn_config.model_copy(update={"draft_slot": DERIVED_SEAT})
    disagreeing = espn_config.model_copy(update={"draft_slot": 2})
    with adapter:
        assert adapter.derived_draft_slot(agreeing) == DERIVED_SEAT
        assert not [row for row in adapter.verify_structure(agreeing) if row[0] == "draft_slot"]
        rows = [row for row in adapter.verify_structure(disagreeing) if row[0] == "draft_slot"]
    assert rows == [("draft_slot", 2, DERIVED_SEAT)]


def test_a_seat_the_platform_cannot_derive_never_contradicts_a_pin(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """Silence is not disagreement -- carrying the seat through an outage is the pin's job."""
    adapter = _adapter(detail, "{SOMEBODY-ELSE}")
    pinned = espn_config.model_copy(update={"draft_slot": 2})
    with adapter:
        assert adapter.derived_draft_slot(pinned) is None
        assert not [row for row in adapter.verify_structure(pinned) if row[0] == "draft_slot"]


# --- whose cookies --------------------------------------------------------------------


def test_for_league_reads_the_environment_keys_the_league_names(
    espn_config: LeagueConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ESPN_SWID", "{ACCOUNT-ONE}")
    monkeypatch.setenv("ESPN_S2", "one")
    monkeypatch.setenv("ESPN_SWID_OTHER", "{ACCOUNT-TWO}")
    monkeypatch.setenv("ESPN_S2_OTHER", "two")

    with EspnAdapter.for_league(espn_config) as default_account:
        assert default_account.swid == "{ACCOUNT-ONE}"

    other = espn_config.model_copy(
        update={"espn_swid_env": "ESPN_SWID_OTHER", "espn_s2_env": "ESPN_S2_OTHER"}
    )
    with EspnAdapter.for_league(other) as second_account:
        assert second_account.swid == "{ACCOUNT-TWO}"


def test_a_league_naming_an_absent_key_does_not_fall_back_to_the_default_account(
    espn_config: LeagueConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trap for_league exists to avoid: silently serving the wrong account."""
    monkeypatch.setenv("ESPN_SWID", "{ACCOUNT-ONE}")
    monkeypatch.setenv("ESPN_S2", "one")
    monkeypatch.delenv("ESPN_SWID_MISSING", raising=False)
    monkeypatch.delenv("ESPN_S2_MISSING", raising=False)

    absent = espn_config.model_copy(
        update={"espn_swid_env": "ESPN_SWID_MISSING", "espn_s2_env": "ESPN_S2_MISSING"}
    )
    with EspnAdapter.for_league(absent) as adapter:
        assert adapter.swid != "{ACCOUNT-ONE}"


def test_a_rejected_cookie_names_the_league_and_the_keys_it_read(
    espn_config: LeagueConfig,
) -> None:
    """Wrong account and no cookie are different problems, and must read differently."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    named = espn_config.model_copy(
        update={"espn_swid_env": "ESPN_SWID_ESPN2", "espn_s2_env": "ESPN_S2_ESPN2"}
    )
    adapter = EspnAdapter(swid="{X}", espn_s2="s2", transport=httpx.MockTransport(handler))
    with adapter, pytest.raises(EspnAuthError) as exc:
        adapter.get_player_pool(named)
    message = str(exc.value)
    assert named.key in message
    assert named.league_id in message
    assert "ESPN_SWID_ESPN2" in message and "ESPN_S2_ESPN2" in message
    assert "DIFFERENT ESPN account" in message
