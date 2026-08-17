"""ESPN draft sync -- offline, against a trimmed live capture of league 6012.

The fixture is a real pre-draft ``mDraftDetail`` + ``mTeam`` + ``mSettings`` response cut to
rounds 1-2 of the placeholder slate. Owner SWIDs are replaced with synthetic GUIDs: SWID is
half the auth cookie pair and seven of the eight belong to other people.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from audible.adapters.espn import EspnAdapter
from audible.config import LeagueConfig
from audible.draft.identity import SOURCE_OVERRIDE, SOURCE_PICK_ORDER, SOURCE_UNRESOLVED
from audible.draft.service import CockpitService
from audible.draft.sync import (
    DraftUpdate,
    EspnIdBridge,
    EspnSync,
    espn_draft_status,
    espn_my_team_id,
    espn_slot_by_team,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def detail() -> dict[str, Any]:
    return json.loads((FIXTURES / "espn_draft_detail.json").read_text(encoding="utf-8"))


def _adapter(payload: dict[str, Any], swid: str) -> EspnAdapter:
    """A real adapter over a mock transport -- exercises the HTTP path, touches no network."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, headers={"etag": 'W/"abc"'})

    return EspnAdapter(swid=swid, espn_s2="s2", transport=httpx.MockTransport(handler))


def _sync(
    payload: dict[str, Any],
    config: LeagueConfig,
    *,
    swid: str | None = None,
    id_map: dict[str, str] | None = None,
    slot_override: int | None = None,
) -> EspnSync:
    return EspnSync(
        config,
        adapter=_adapter(payload, swid if swid is not None else payload["_my_swid"]),
        bridge=EspnIdBridge(id_map if id_map is not None else {}),
        slot_override=slot_override,
    )


def _drafted(detail: dict[str, Any], made: list[tuple[int, int]]) -> dict[str, Any]:
    """Fill the placeholder slate: ``made`` is (overallPickNumber, espn player id)."""
    payload = copy.deepcopy(detail)
    payload["draftDetail"]["inProgress"] = True
    by_overall = {int(p["overallPickNumber"]): p for p in payload["draftDetail"]["picks"]}
    for overall, player_id in made:
        by_overall[overall]["playerId"] = player_id
    return payload


# --- the placeholder slate ---------------------------------------------------------------


def test_pre_draft_slate_yields_no_picks(detail: dict[str, Any], espn_config: LeagueConfig) -> None:
    """Pre-draft ESPN serves a COMPLETE grid of every pick the draft will ever have -- one row
    per seat per round, all ``playerId: -1``. Live that is 128 rows for an 8x16 draft.

    A sync that counts rows instead of filtering believes the draft finished before it started:
    the clock would jump past the final pick and the board would show the room as fully rostered.
    """
    slate = detail["draftDetail"]["picks"]
    assert slate, "the fixture must carry the placeholder slate"
    assert all(row["playerId"] == -1 for row in slate)

    update = _sync(detail, espn_config).poll(None, want_meta=True, slot_locked=False)
    assert update.picks == []
    assert update.status == "pre_draft"


def test_real_picks_are_read_once_the_slate_fills(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    payload = _drafted(detail, [(1, 4362238), (2, 3117251), (3, 4241457)])
    update = _sync(payload, espn_config, id_map={"4362238": "sleeper-a"}).poll(
        None, want_meta=True, slot_locked=False
    )

    assert [p.pick_no for p in update.picks] == [1, 2, 3]
    assert update.status == "drafting"
    # The one id with a board row is translated; the other two keep their ESPN value so the
    # pick still counts, and both are recorded as unmatched rather than absorbed.
    assert update.picks[0].player_id == "sleeper-a"
    assert [p.player_id for p in update.picks[1:]] == ["3117251", "4241457"]


def test_status_maps_espns_two_booleans(detail: dict[str, Any]) -> None:
    assert espn_draft_status(detail["draftDetail"]) == "pre_draft"
    assert espn_draft_status({"inProgress": True}) == "drafting"
    assert espn_draft_status({"drafted": True}) == "complete"
    # drafted wins: a finished draft is not "in progress" even if both flags are set.
    assert espn_draft_status({"drafted": True, "inProgress": True}) == "complete"


# --- teamId -> slot ------------------------------------------------------------------------


def test_pick_order_maps_team_to_seat(detail: dict[str, Any]) -> None:
    """pickOrder is teamIds in seat order, and it is NOT the identity map -- which is what
    distinguishes it from Sleeper's placeholder slot_to_roster_id."""
    slots = espn_slot_by_team(detail["settings"])
    assert slots == {2: 1, 3: 2, 6: 3, 4: 4, 1: 5, 5: 6, 7: 7, 8: 8}
    assert slots != {i: i for i in range(1, 9)}, "an identity map would mean we read a placeholder"

    # ...and it agrees with the round-1 slate, which is the independent check on it.
    round_one = [p for p in detail["draftDetail"]["picks"] if p["roundId"] == 1]
    for row in round_one:
        assert slots[row["teamId"]] == row["roundPickNumber"]


def test_picks_are_attributed_to_the_right_seat(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """Snake: seat 8 picks 8th and 9th at the turn, so both must land on the same slot."""
    payload = _drafted(detail, [(1, 100), (8, 200), (9, 300)])
    picks = _sync(payload, espn_config).poll(None, want_meta=True, slot_locked=False).picks

    by_no = {p.pick_no: p for p in picks}
    assert by_no[1].draft_slot == 1  # teamId 2 sits first
    assert by_no[8].draft_slot == 8 and by_no[9].draft_slot == 8  # the turn


def test_my_seat_is_derived_from_the_cookie(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """No --slot flag: the SWID that authenticates the request already says who I am."""
    update = _sync(detail, espn_config).poll(None, want_meta=True, slot_locked=False)
    assert update.identity is not None
    assert update.identity.slot == 8
    assert update.identity.source == SOURCE_PICK_ORDER


def test_a_co_owned_team_still_resolves(detail: dict[str, Any]) -> None:
    """Team 2 is co-owned. Matching only `primaryOwner` would strand the other owner."""
    teams = detail["teams"]
    co_owned = next(t for t in teams if len(t["owners"]) > 1)
    non_primary = next(o for o in co_owned["owners"] if o != co_owned["primaryOwner"])

    assert espn_my_team_id(teams, non_primary) == co_owned["id"]
    assert espn_my_team_id(teams, co_owned["primaryOwner"]) == co_owned["id"]
    assert espn_my_team_id(teams, co_owned["owners"][0].lower()) == co_owned["id"]  # case


# --- unresolved is a state, never a guess --------------------------------------------------


def test_unknown_cookie_leaves_the_slot_unresolved(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """The slot=0 bug: an invented seat reads as "me" and quietly attributes the whole room
    to my roster. No seat must mean no seat."""
    update = _sync(detail, espn_config, swid="{NOT-IN-THIS-LEAGUE}").poll(
        None, want_meta=True, slot_locked=False
    )
    assert update.identity is not None
    assert update.identity.slot is None
    assert update.identity.source == SOURCE_UNRESOLVED


def test_team_missing_from_pick_order_is_unresolved(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """A team that exists but has no seat yet -- the order is knowable, the seat is not."""
    payload = copy.deepcopy(detail)
    payload["settings"]["draftSettings"]["pickOrder"] = [2, 3, 6, 4, 1, 5, 7]  # my team dropped

    update = _sync(payload, espn_config).poll(None, want_meta=True, slot_locked=False)
    assert update.identity is not None
    assert update.identity.slot is None
    assert update.identity.source == SOURCE_UNRESOLVED
    assert update.identity.roster_id == 8, "the TEAM is still knowable; the seat is not"


def test_override_wins_for_rehearsal(detail: dict[str, Any], espn_config: LeagueConfig) -> None:
    update = _sync(detail, espn_config, slot_override=3).poll(
        None, want_meta=True, slot_locked=False
    )
    assert update.identity is not None
    assert (update.identity.slot, update.identity.source) == (3, SOURCE_OVERRIDE)


def test_no_slot_survives_into_the_session(
    tmp_path: Path, detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """End to end: an unresolvable seat must reach the session as None, not as 0."""
    svc = CockpitService(
        espn_config, state_dir=tmp_path,
        sync=_sync(detail, espn_config, swid="{NOBODY}"),
    )
    assert svc.poll_once() is True
    assert svc.session.slot is None
    assert svc.session.slot_source == SOURCE_UNRESOLVED


# --- rounds, transport, and the update contract --------------------------------------------


def test_rounds_come_from_roster_structure(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """16 = every drafted roster slot, IR excluded. Derived from structure rather than from the
    slate, so the clock survives ESPN changing what it serves in `picks` mid-draft."""
    update = _sync(detail, espn_config).poll(None, want_meta=True, slot_locked=False)
    assert update.rounds == 16
    assert update.draft_id == espn_config.league_id


def test_draft_poll_is_conditional_and_carries_no_cache_buster(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """ESPN is not edge-cached (CloudFront Miss, must-revalidate, no age header), so the poll
    revalidates with an ETag and nothing else. Sleeper's /picks IS edge-cached and needs a
    unique param on every request -- see test_adapters.py. Neither generalises to the other.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("if-none-match") == 'W/"abc"':
            return httpx.Response(304, headers={"etag": 'W/"abc"'})
        return httpx.Response(200, json=detail, headers={"etag": 'W/"abc"'})

    adapter = EspnAdapter(swid="{X}", espn_s2="s2", transport=httpx.MockTransport(handler))
    with adapter:
        first = adapter.get_draft_detail(espn_config)
        second = adapter.get_draft_detail(espn_config)

    assert first == second, "a 304 must yield the last-known payload, never an empty draft"
    assert seen[0].headers.get("if-none-match") is None
    assert seen[1].headers.get("if-none-match") == 'W/"abc"'
    busters = [set(dict(r.url.params)) - {"view"} for r in seen]
    assert busters == [set(), set()], "ESPN must NOT carry a cache-buster"


def test_an_update_never_blanks_what_it_did_not_fetch(
    tmp_path: Path, espn_config: LeagueConfig
) -> None:
    """DraftUpdate uses None for "unchanged". A picks-only poll must not wipe the draft status,
    the round count or my seat just because it did not ask for them."""
    svc = CockpitService(espn_config, state_dir=tmp_path)
    svc.session.rounds = 16
    svc.session.draft_status = "drafting"
    svc.session.slot = 8

    svc._apply(DraftUpdate(draft_id="6012", picks=[]))

    assert svc.session.rounds == 16
    assert svc.session.draft_status == "drafting"
    assert svc.session.slot == 8


def test_the_id_bridge_records_what_it_cannot_translate() -> None:
    bridge = EspnIdBridge({"111": "sleeper-x"})
    assert bridge.to_board_id(111) == "sleeper-x"
    assert bridge.to_board_id("999") == "999", "an untranslatable pick still counts"
    assert bridge.unmatched == {"999"}


# --- roster structure ----------------------------------------------------------------------


def test_verify_structure_is_faithful(detail: dict[str, Any], espn_config: LeagueConfig) -> None:
    with _adapter(detail, "{X}") as adapter:
        assert adapter.verify_structure(espn_config) == []
        assert adapter.draft_rounds(espn_config) == 16


def test_verify_structure_catches_drift(
    detail: dict[str, Any], espn_config: LeagueConfig
) -> None:
    """League A's config silently claimed slots the live league had dropped, and every
    replacement baseline derived from it was wrong. League B now has the same guard."""
    payload = copy.deepcopy(detail)
    counts = payload["settings"]["rosterSettings"]["lineupSlotCounts"]
    counts["4"] = 3  # WR 2 -> 3
    counts["17"] = 0  # K dropped
    counts["11"] = 1  # a DL slot we do not map at all

    with _adapter(payload, "{X}") as adapter:
        drift = {slot: (c, live) for slot, c, live in adapter.verify_structure(espn_config)}

    assert drift["WR"] == (2, 3)
    assert drift["K"] == (1, 0)
    assert drift["slot#11"] == (0, 1), "an unmapped starting slot must be loud, not skipped"
    assert "QB" not in drift and "FLEX" not in drift
