"""A seat check that cannot be seen to have run is not a check.

`verify_structure` reports a `draft_slot` row only when a pin and the live derivation
DISAGREE. A null derivation is deliberately not drift -- the pin exists to carry the seat
when the platform is silent -- so "the seat agrees" and "the seat was never derived" both
return an empty drift list, and until `_print_seat` existed both printed byte-identical text
and exited 0. Measured against the live leagues on 2026-09-06: `diff` of the two full runs
reported zero differing bytes.

These gates are on the OUTPUT, because the drift contract is what makes the two cases
identical and must not change. Nothing here asserts on the return value of
`verify_structure`; `tests/test_espn_seat_and_cookies.py` owns that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from audible.adapters.espn import EspnAdapter
from audible.cli import _print_seat
from audible.config import LeagueConfig

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


# --- the adapter records what it derived ------------------------------------------------


def test_a_fresh_adapter_has_not_checked_the_seat(detail: dict[str, Any]) -> None:
    """`derived_slot is None` alone cannot mean "ESPN said nothing" -- it is also the
    never-ran value. That is exactly the ambiguity being removed, so the flag is separate."""
    adapter = _adapter(detail, detail["_my_swid"])
    with adapter:
        assert adapter.derived_slot is None
        assert adapter.derived_slot_checked is False


def test_verify_structure_records_the_seat_it_derived(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The agreeing case: no drift row, and yet the seat is now knowable."""
    adapter = _adapter(detail, detail["_my_swid"])
    agreeing = espn_config.model_copy(update={"draft_slot": DERIVED_SEAT})
    with adapter:
        assert [r for r in adapter.verify_structure(agreeing) if r[0] == "draft_slot"] == []
        assert adapter.derived_slot == DERIVED_SEAT
        assert adapter.derived_slot_checked is True


def test_a_seat_espn_cannot_derive_is_recorded_as_checked_and_null(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The skipped case. Same empty drift list as above -- and now distinguishable."""
    adapter = _adapter(detail, "{SOMEBODY-ELSE}")
    pinned = espn_config.model_copy(update={"draft_slot": 2})
    with adapter:
        assert [r for r in adapter.verify_structure(pinned) if r[0] == "draft_slot"] == []
        assert adapter.derived_slot is None
        assert adapter.derived_slot_checked is True


# --- the output says which one happened -------------------------------------------------


def test_a_verified_seat_says_so(
    espn_config: LeagueConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = espn_config.model_copy(update={"draft_slot": DERIVED_SEAT})
    _print_seat(cfg, DERIVED_SEAT, True)
    out = capsys.readouterr().out
    assert "VERIFIED" in out
    assert str(DERIVED_SEAT) in out


def test_a_skipped_seat_says_it_was_skipped(
    espn_config: LeagueConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate. A null derivation is still a pass, and the text must say so out loud."""
    cfg = espn_config.model_copy(update={"draft_slot": 2})
    _print_seat(cfg, None, True)
    out = capsys.readouterr().out
    assert "NOT CHECKED" in out
    assert "UNVERIFIED" in out


def test_the_two_passing_cases_do_not_print_the_same_thing(
    espn_config: LeagueConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    """The defect, stated as an assertion. Both cases pass; they must not read alike."""
    cfg = espn_config.model_copy(update={"draft_slot": DERIVED_SEAT})
    _print_seat(cfg, DERIVED_SEAT, True)
    agreed = capsys.readouterr().out
    _print_seat(cfg, None, True)
    skipped = capsys.readouterr().out
    assert agreed != skipped
    assert agreed.strip() and skipped.strip()


def test_an_unpinned_seat_reports_the_derivation(
    espn_config: LeagueConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = espn_config.model_copy(update={"draft_slot": None})
    _print_seat(cfg, DERIVED_SEAT, True)
    out = capsys.readouterr().out
    assert "nothing is pinned" in out
    assert str(DERIVED_SEAT) in out


def test_no_pin_and_no_derivation_does_not_claim_a_seat_is_being_carried(
    espn_config: LeagueConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    """The both-missing case. Saying "the pinned seat None is being carried" would be a
    reassurance about a seat that does not exist in either place."""
    cfg = espn_config.model_copy(update={"draft_slot": None})
    _print_seat(cfg, None, True)
    out = capsys.readouterr().out
    assert "NOT CHECKED" in out
    assert "NOTHING IS PINNED EITHER" in out
    assert "None" not in out


# --- the wiring, not just the helper ----------------------------------------------------


def test_the_command_actually_prints_the_seat_line(
    detail: dict[str, Any], espn_config: LeagueConfig,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The gate on the WIRING. Every test above calls `_print_seat` directly, so deleting its
    call site in `cmd_verify_scoring_espn` would leave them all green while restoring the exact
    defect: a verify-scoring run that says nothing about the seat.
    """
    from audible.adapters import espn as espn_mod
    from audible.cli import cmd_verify_scoring_espn

    adapter = _adapter(detail, detail["_my_swid"])
    monkeypatch.setattr(espn_mod.EspnAdapter, "for_league", classmethod(lambda cls, cfg: adapter))
    monkeypatch.setattr(espn_mod.EspnAdapter, "verify_scoring", lambda self, cfg: [])
    monkeypatch.setattr(espn_mod.EspnAdapter, "live_reception_points", lambda self, cfg: None)
    monkeypatch.setattr(espn_mod.EspnAdapter, "verify_structure", lambda self, cfg: [])

    cfg = espn_config.model_copy(update={"draft_slot": DERIVED_SEAT,
                                         "expected_reception_points": None})
    rc = cmd_verify_scoring_espn(cfg)
    out = capsys.readouterr().out

    assert "draft seat" in out, (
        "verify-scoring printed nothing about the seat -- _print_seat is not wired into "
        "cmd_verify_scoring_espn, which is the whole defect this change exists to fix"
    )
    assert rc == 0
