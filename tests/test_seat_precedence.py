"""The live seat outranks the config pin, and the served value says which one it is.

THE DEFECT. `schema.py` documents `draft_slot` as the thing that keeps the timing term alive
when sync cannot answer -- a FALLBACK. It was wired to win outright, so a config value beat a
live one. On 2026-09-07 Green Hope's commissioner re-drew the pick order inside 48 hours of
the draft: ESPN said seat 6, the config still said 1, and the cockpit served 1 for hours while
logging a SEAT DRIFT line nobody was watching. The check saw the problem, said so, and changed
nothing.

A fallback that beats a live answer is not a fallback.

THREE TIERS now, and the middle one moved:

  1. an operator's explicit ``--slot``  -> SOURCE_OVERRIDE. Still wins outright.
  2. the live derivation                -> SOURCE_PICK_ORDER / SOURCE_DRAFT_ORDER.
  3. the league config's ``draft_slot`` -> SOURCE_CONFIG_PIN, carried only when 2 is silent.

Tier 3 is the outage case the field exists for and must not regress while fixing tier 2.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from audible.adapters.espn import EspnAdapter
from audible.config import LeagueConfig
from audible.draft.identity import (
    SOURCE_CONFIG_PIN,
    SOURCE_DRAFT_ORDER,
    SOURCE_OVERRIDE,
    SOURCE_PICK_ORDER,
    SOURCE_UNRESOLVED,
    resolve_slot,
)
from audible.draft.service import DRAFTING_STATUS, CockpitService
from audible.draft.sync import EspnIdBridge, EspnSync

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The committed ESPN capture is league 6012, whose SWID-derived seat is 8.
DERIVED_SEAT = 8


@pytest.fixture
def detail() -> dict[str, Any]:
    return json.loads((FIXTURES / "espn_draft_detail.json").read_text(encoding="utf-8"))


def _sync(payload: dict[str, Any], config: LeagueConfig, **kw: Any) -> EspnSync:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, headers={"etag": 'W/"abc"'})

    return EspnSync(
        config,
        adapter=EspnAdapter(swid=payload["_my_swid"], espn_s2="s2",
                            transport=httpx.MockTransport(handler)),
        bridge=EspnIdBridge({}),
        **kw,
    )


def _identity(payload: dict[str, Any], config: LeagueConfig, **kw: Any) -> Any:
    return _sync(payload, config, **kw).poll(None, want_meta=True, slot_locked=False).identity


# --- ESPN: the live pick order beats the config pin ------------------------------------


def test_a_config_pin_that_disagrees_LOSES_to_the_live_pick_order(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """FAILURE INJECTION 1. Pin 3 against a live 8: the served seat must be 8.

    If this returns 3, the precedence was never inverted and Green Hope's 2026-09-07
    re-draw would be served wrong all over again.
    """
    ident = _identity(detail, espn_config, slot_fallback=3)
    assert ident.slot == DERIVED_SEAT, "the config pin beat the live pick order"
    assert ident.source == SOURCE_PICK_ORDER
    assert ident.derived_slot == DERIVED_SEAT
    assert ident.pinned_slot == 3
    assert ident.seat_conflict is True, "a stale pin must still be reported, even losing"


def test_a_config_pin_is_CARRIED_when_the_platform_cannot_say(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """FAILURE INJECTION 2, and the regression guard on tier 3.

    This is the outage the field exists for: cookies lapse, the SWID matches no team, and
    the timing term must not go null. The seat is served AND marked as carried.
    """
    blind = dict(detail, _my_swid="{SOMEBODY-ELSE}")
    ident = _identity(blind, espn_config, slot_fallback=6)
    assert ident.slot == 6, "the pin was not carried through a null derivation"
    assert ident.source == SOURCE_CONFIG_PIN
    assert ident.derived_slot is None
    assert ident.seat_conflict is False, "silence never contradicts a pin"


def test_an_explicit_slot_flag_still_outranks_the_platform(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """Tier 1 is unchanged. An operator who types a seat has said something the tool has no
    business second-guessing -- it is how rehearsal against a completed draft works."""
    ident = _identity(detail, espn_config, slot_override=3)
    assert ident.slot == 3
    assert ident.source == SOURCE_OVERRIDE
    assert ident.derived_slot == DERIVED_SEAT
    assert ident.seat_conflict is True


def test_an_agreeing_pin_reports_the_derived_source_not_the_pin(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The everyday case, and the one that proves the source is traced rather than assumed:
    the same number from two places must still say which place it came from."""
    ident = _identity(detail, espn_config, slot_fallback=DERIVED_SEAT)
    assert ident.slot == DERIVED_SEAT
    assert ident.source == SOURCE_PICK_ORDER
    assert ident.seat_conflict is False


def test_no_pin_and_no_derivation_is_unresolved(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    blind = dict(detail, _my_swid="{SOMEBODY-ELSE}")
    ident = _identity(blind, espn_config)
    assert ident.slot is None
    assert ident.source == SOURCE_UNRESOLVED


# --- Sleeper: the same three tiers, through resolve_slot -------------------------------

_DRAFT = {"draft_order": {"u1": 4}}
_ROSTERS = [{"roster_id": 7, "owner_id": "u1"}]


def test_sleeper_draft_order_beats_a_config_pin() -> None:
    ident = resolve_slot(_DRAFT, _ROSTERS, "u1", fallback=9)
    assert (ident.slot, ident.source) == (4, SOURCE_DRAFT_ORDER)
    assert ident.pinned_slot == 9
    assert ident.seat_conflict is True


def test_sleeper_carries_the_pin_before_the_draft_opens() -> None:
    """`draft_order` is null until the draft actually opens -- the pin's whole job."""
    ident = resolve_slot({"draft_order": None}, _ROSTERS, "u1", fallback=9)
    assert (ident.slot, ident.source) == (9, SOURCE_CONFIG_PIN)
    assert ident.seat_conflict is False


def test_sleeper_explicit_override_still_wins() -> None:
    ident = resolve_slot(_DRAFT, _ROSTERS, "u1", override=2, fallback=9)
    assert (ident.slot, ident.source) == (2, SOURCE_OVERRIDE)
    assert ident.derived_slot == 4


# --- what the cockpit serves -----------------------------------------------------------


def test_the_served_state_names_the_path_the_seat_came_from(
    detail: dict[str, Any], espn_config: LeagueConfig, tmp_path: Path
) -> None:
    """`my_slot_source` is what an operator reads to know whether to trust the number.

    #64's lesson was that a check which cannot be seen to have run is not a check. The same
    applies to a value that cannot be traced to its source: `override` and `config_pin` are
    different claims and must not print the same.
    """
    svc = CockpitService(espn_config, state_dir=tmp_path, slot_fallback=3,
                         sync=_sync(detail, espn_config, slot_fallback=3))
    svc.poll_once()
    assert svc.session.slot == DERIVED_SEAT
    assert svc.session.slot_source == SOURCE_PICK_ORDER

    blind = dict(detail, _my_swid="{SOMEBODY-ELSE}")
    svc2 = CockpitService(espn_config, state_dir=tmp_path, slot_fallback=3,
                          sync=_sync(blind, espn_config, slot_fallback=3))
    svc2.poll_once()
    assert svc2.session.slot == 3
    assert svc2.session.slot_source == SOURCE_CONFIG_PIN
    assert svc2.session.slot_source != svc.session.slot_source


# --- the paths a surviving mutant proved were ungated ----------------------------------


def test_build_sync_actually_receives_the_config_fallback(
    espn_config: LeagueConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ONE link that carries the fallback into the sync, and it was untested.

    Every other gate here passes `sync=` directly, so `CockpitService.start()` -> `build_sync`
    is never exercised -- and a mutant dropping `slot_fallback=self._slot_fallback` there
    survived the entire suite. That is the production path: serve() -> create_app -> lifespan
    -> start(). With it dropped the deployed cockpit reports my_slot unresolved on exactly the
    outage tier 3 exists for.
    """
    from audible.draft import service as service_mod

    captured: dict[str, Any] = {}

    def _spy(config: LeagueConfig, **kw: Any) -> Any:
        captured.update(kw)
        raise RuntimeError("stop here; the kwargs are the assertion")

    monkeypatch.setattr(service_mod, "build_sync", _spy)
    svc = CockpitService(espn_config, state_dir=tmp_path, slot_fallback=6, slot_override=None)
    with pytest.raises(RuntimeError):
        svc.start()

    assert captured["slot_fallback"] == 6, "build_sync never received the config fallback"
    assert captured["slot_override"] is None


def test_seat_drift_is_logged_when_the_PLATFORM_wins(
    detail: dict[str, Any], espn_config: LeagueConfig, tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The Green Hope case, and the branch this whole change exists for.

    A mutant gating the drift log on `source == SOURCE_OVERRIDE` -- reporting only when the
    pin wins -- survived the whole suite, which is exactly what seat_conflict's docstring
    forbids. Under it the Green Hope scenario logs NOTHING.
    """
    svc = CockpitService(espn_config, state_dir=tmp_path, slot_fallback=3,
                         sync=_sync(detail, espn_config, slot_fallback=3))
    with caplog.at_level(logging.ERROR, logger="audible.cockpit"):
        svc.poll_once()

    drift = [r.getMessage() for r in caplog.records if "SEAT DRIFT" in r.getMessage()]
    assert len(drift) == 1, f"expected one SEAT DRIFT record, got {len(drift)}"
    assert "pinned slot 3" in drift[0]
    assert f"platform says {DERIVED_SEAT}" in drift[0]
    assert "the platform is winning" in drift[0], (
        "the log named the wrong winner -- a swapped winner string also survived the suite"
    )
    assert f"Serving {DERIVED_SEAT} ({SOURCE_PICK_ORDER})" in drift[0]


# --- a wrong derivation is worse than a silent one -------------------------------------


def test_an_out_of_range_derived_seat_is_ignored_and_the_pin_carries(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """`compute_view` RAISES on a slot outside 1..teams and `build_state` has no guard, so an
    over-long pickOrder would 500 every /api/state. Silence falls back; garbage must too."""
    teams = espn_config.num_teams
    # My team parked one past the last legal seat, behind `teams` distinct strangers.
    order = [900 + i for i in range(teams)] + [detail["_my_team_id"]]
    bad = dict(detail)
    bad["settings"] = dict(detail["settings"],
                           draftSettings=dict(detail["settings"]["draftSettings"],
                                              pickOrder=order))
    ident = _identity(bad, espn_config, slot_fallback=6)
    assert ident.slot == 6, "an out-of-range derivation was served"
    assert ident.source == SOURCE_CONFIG_PIN
    assert ident.derived_slot == teams + 1, "the raw value must survive for reporting"
    assert ident.seat_conflict is True


def test_the_seat_is_frozen_once_the_draft_is_in_progress(
    detail: dict[str, Any], espn_config: LeagueConfig, tmp_path: Path
) -> None:
    """A pick order cannot legitimately change with picks on the clock, so following it
    mid-draft only lets a bad body re-attribute the whole roster for a tick."""
    svc = CockpitService(espn_config, state_dir=tmp_path,
                         sync=_sync(detail, espn_config))
    svc.poll_once()
    settled = svc.session.slot
    assert settled == DERIVED_SEAT
    svc.session.draft_status = DRAFTING_STATUS

    moved = dict(detail)
    order = list(detail["settings"]["draftSettings"]["pickOrder"])
    order.remove(detail["teams"][0]["id"])
    moved["settings"] = dict(detail["settings"],
                             draftSettings=dict(detail["settings"]["draftSettings"],
                                                pickOrder=[detail["teams"][0]["id"], *order]))
    svc._sync = _sync(moved, espn_config)
    svc.poll_once()

    assert svc.session.slot == settled, "the seat moved while the draft was in progress"
