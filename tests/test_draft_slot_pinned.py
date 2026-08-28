"""The seat must resolve, and it must be 8. Draft day depends on both.

An unresolved slot is not a cosmetic gap: picks_until_me, my_next_pick,
rival_picks_before_my_next and slack_picks all go null with it, and `recommend` then loses
its timing term and degrades to best-available WITHOUT SAYING SO. The cluster ran in exactly
that state for 11,925 consecutive failed polls while answering every question as though
nothing were wrong.
"""

from __future__ import annotations

import pytest

from audible.config import LeagueConfig
from audible.draft.service import CockpitService
from audible.server.mcp import _sync

ERIC_SEAT = 8


def test_the_league_pins_the_seat(espn_config: LeagueConfig) -> None:
    """Confirmed with the commissioner 2026-08-27: 8 teams, pure snake, Eric picks 8th."""
    assert espn_config.draft_slot == ERIC_SEAT


def test_the_seat_resolves_without_any_sync(espn_config: LeagueConfig, tmp_path) -> None:
    """The whole point of the pin: no network, no platform, still seat 8."""
    svc = CockpitService(espn_config, state_dir=tmp_path,
                         slot_override=espn_config.draft_slot)
    assert svc._slot_override == ERIC_SEAT


def test_the_turns_follow_from_the_seat(espn_config: LeagueConfig) -> None:
    """8/9, 24/25, 40/41, 56/57, 72/73, 88/89, 104/105, 120/121 -- pure snake, no reversal."""
    from audible.draft.live import snake_pick_numbers

    picks = snake_pick_numbers(ERIC_SEAT, espn_config.num_teams,
                               espn_config.draft_rounds or 16)
    assert picks[:8] == [8, 9, 24, 25, 40, 41, 56, 57]
    assert picks[8:] == [72, 73, 88, 89, 104, 105, 120, 121]


def test_a_never_synced_warning_does_not_render_a_null(espn_config: LeagueConfig) -> None:
    """The bug this replaces rendered "Data is Nones old" -- a null in a format placeholder.

    A malformed alarm is a broken alarm: the reader learns the tool is confused, not that
    the data is untrustworthy.
    """
    warning = _sync({"sync": {"age_s": None, "status": "failing", "last_success": None}})
    assert warning["warning"] is not None
    assert "None" not in warning["warning"]
    assert "NEVER SYNCED" in warning["warning"]


def test_a_stale_warning_still_reports_its_age(espn_config: LeagueConfig) -> None:
    warning = _sync({"sync": {"age_s": 42.7, "status": "stale", "last_success": 1.0}})
    assert "43s old" in warning["warning"]


def test_a_live_sync_raises_no_warning(espn_config: LeagueConfig) -> None:
    assert _sync({"sync": {"age_s": 2.0, "status": "live"}})["warning"] is None


@pytest.mark.parametrize("bad", [0, -1])
def test_a_nonsense_seat_is_rejected_by_the_schema(espn_config: LeagueConfig, bad: int) -> None:
    with pytest.raises(ValueError):
        espn_config.model_copy(update={"draft_slot": bad}).model_validate(
            espn_config.model_dump() | {"draft_slot": bad}
        )


# ---------------------------------------------------------------------------
# The wiring, not just the value.
#
# WHY THESE EXIST. `test_the_seat_resolves_without_any_sync` above constructs
# CockpitService with `slot_override=espn_config.draft_slot` and then asserts
# the service kept it -- it passes in the answer and checks it came back. That
# is worth something, but it does NOT test the line that actually makes the
# cluster resolve seat 8:
#
#     seat = slot if slot is not None else config.draft_slot      (server/app.py)
#
# Verified by mutation on 2026-08-28: replacing that line with `seat = slot`
# left ALL 263 tests passing, while the deployed cockpit would silently return
# my_slot: unresolved and drop every timing term out of `recommend`. The suite
# had no opinion about the one line the whole fix depends on.
#
# These two kill that mutant. They drive the real `serve()` and capture what it
# hands the service, with uvicorn and the app factory stubbed so nothing binds a
# port or touches the network.


class _CapturedService:
    """Stands in for CockpitService so serve() can be driven without a board."""

    last: dict = {}

    def __init__(self, config, *, draft_id=None, slot_override=None, user_name=None):
        type(self).last = {
            "config": config,
            "draft_id": draft_id,
            "slot_override": slot_override,
            "user_name": user_name,
        }


def _drive_serve(monkeypatch, config, **kwargs) -> dict:
    """Run serve() far enough to see what it built, then stop before uvicorn."""
    import uvicorn

    from audible.server import app as app_module

    monkeypatch.setattr(app_module, "CockpitService", _CapturedService)
    monkeypatch.setattr(app_module, "create_app", lambda svc, **kw: object())
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: None)
    _CapturedService.last = {}
    app_module.serve(config, **kwargs)
    return _CapturedService.last


def test_serve_pins_the_seat_from_config_when_no_slot_flag(monkeypatch, espn_config) -> None:
    """The cluster passes no --slot. This is the line that saves it."""
    captured = _drive_serve(monkeypatch, espn_config)
    assert captured["slot_override"] == ERIC_SEAT, (
        "serve() did not read draft_slot from the league config -- the deployed "
        "cockpit would report my_slot: unresolved and drop every timing term"
    )


def test_an_explicit_slot_flag_still_beats_the_config_pin(monkeypatch, espn_config) -> None:
    """The pin is a fallback, not an override of the operator."""
    captured = _drive_serve(monkeypatch, espn_config, slot=3)
    assert captured["slot_override"] == 3
