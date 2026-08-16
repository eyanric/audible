from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from audible.adapters.sleeper import SleeperAdapter
from audible.config import LeagueConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _classify(catalog: dict[str, dict[str, Any]], pid: str, cfg: LeagueConfig):
    return SleeperAdapter.classify(catalog[pid], cfg.positions)


def test_verify_structure_catches_roster_drift(
    monkeypatch: pytest.MonkeyPatch, sleeper_config: LeagueConfig
) -> None:
    """The Phase-0 capture carried 15 starters (DEF plus a full DL/LB/DB/IDP_FLEX stack); the
    live league has since moved to 11 with a single IDP_FLEX and no DEF. Nothing compared the
    two, so the stale structure silently corrupted every replacement baseline the value engine
    derives -- this guard is what makes that failure loud.
    """
    captured = json.loads((FIXTURES / "sleeper_league.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(SleeperAdapter, "get_league", lambda self, league_id: captured)

    with SleeperAdapter() as adapter:
        drift = {slot: (cfg_n, live_n) for slot, cfg_n, live_n in adapter.verify_structure(
            sleeper_config
        )}

    # config no longer has these slots; the June capture had one of each.
    assert drift["DEF"] == (0, 1)
    assert drift["DL"] == (0, 1)
    assert drift["LB"] == (0, 1)
    assert drift["DB"] == (0, 1)
    assert "IDP_FLEX" not in drift  # one in both -- unchanged
    assert "BN" not in drift  # bench never demands a starter


def test_verify_structure_is_quiet_when_faithful(
    monkeypatch: pytest.MonkeyPatch, sleeper_config: LeagueConfig
) -> None:
    live = {"roster_positions": list(sleeper_config.starting_slots) + ["BN"] * 7}
    monkeypatch.setattr(SleeperAdapter, "get_league", lambda self, league_id: live)
    with SleeperAdapter() as adapter:
        assert adapter.verify_structure(sleeper_config) == []


# --- live pick poll: edge-cache bypass ------------------------------------------------------


def _picks_adapter(handler) -> SleeperAdapter:
    """Adapter whose HTTP client is backed by a mock transport (no network)."""
    import httpx

    adapter = SleeperAdapter()
    adapter.close()
    adapter._client = httpx.Client(transport=httpx.MockTransport(handler))
    return adapter


def test_pick_poll_bypasses_the_edge_cache() -> None:
    """Cloudflare serves /picks with s-maxage=30; a plain GET measured 57s stale against a
    60s pick timer. Every poll must carry a unique param so it cannot be answered from cache.
    """
    import httpx

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"pick_no": 1, "player_id": "x"}],
                              headers={"etag": 'W/"abc"'})

    with _picks_adapter(handler) as adapter:
        adapter.get_draft_picks("d1")
        adapter.get_draft_picks("d1")

    assert all(r.headers.get("cache-control") == "no-cache" for r in seen)
    busters = [dict(r.url.params).get("_") for r in seen]
    assert all(b for b in busters), "every poll needs a cache-busting param"
    assert busters[0] != busters[1], "the param must differ per poll or the edge caches it"


def test_pick_poll_sends_etag_and_reuses_last_body_on_304() -> None:
    """Once an ETag is known, origin answers 304 with an empty body -- the cheap common case.
    A 304 must yield the last-known picks, never an empty board.
    """
    import httpx

    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inm = request.headers.get("if-none-match")
        calls.append(inm)
        if inm == 'W/"abc"':
            return httpx.Response(304, headers={"etag": 'W/"abc"'})
        return httpx.Response(200, json=[{"pick_no": 1, "player_id": "x"}],
                              headers={"etag": 'W/"abc"'})

    with _picks_adapter(handler) as adapter:
        first = adapter.get_draft_picks("d1")
        second = adapter.get_draft_picks("d1")

    assert calls == [None, 'W/"abc"']  # no ETag to send on the first poll, then conditional
    assert first == second == [{"pick_no": 1, "player_id": "x"}]


def test_pick_poll_keeps_etags_per_draft() -> None:
    """A rehearsal draft and the real one must not share conditional state."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("if-none-match") is None
        return httpx.Response(200, json=[], headers={"etag": f'W/"{request.url.path}"'})

    with _picks_adapter(handler) as adapter:
        adapter.get_draft_picks("d1")
        adapter.get_draft_picks("d2")  # different draft -> must not send d1's ETag
        assert adapter._picks_etag["d1"] != adapter._picks_etag["d2"]


def test_two_way_player_buckets_to_offense(
    sleeper_config: LeagueConfig, sample_catalog: dict[str, dict[str, Any]]
) -> None:
    # Travis Hunter is fantasy_positions [DB, WR]; his value is WR -> primary must be WR,
    # but he stays eligible for DB (and thus IDP_FLEX) too.
    primary, eligible = _classify(sample_catalog, "12530", sleeper_config)
    assert primary == "WR"
    assert {"WR", "DB"} <= eligible


def test_hybrid_idp_uses_granular_position(
    sleeper_config: LeagueConfig, sample_catalog: dict[str, dict[str, Any]]
) -> None:
    # T.J. Watt: position LB, fantasy_positions [DL, LB] -> primary LB, eligible both.
    primary, eligible = _classify(sample_catalog, "4070", sleeper_config)
    assert primary == "LB"
    assert eligible == frozenset({"DL", "LB"})


def test_interior_dl_buckets_to_dl(
    sleeper_config: LeagueConfig, sample_catalog: dict[str, dict[str, Any]]
) -> None:
    # Poona Ford: position DT -> DL bucket.
    primary, _ = _classify(sample_catalog, "5226", sleeper_config)
    assert primary == "DL"


def test_player_outside_league_positions_is_dropped(
    espn_config: LeagueConfig, sample_catalog: dict[str, dict[str, Any]]
) -> None:
    # A pure DB (Marcus Jones) can't be rostered in the no-IDP ESPN league.
    primary, eligible = _classify(sample_catalog, "8359", espn_config)
    assert primary is None and not eligible
