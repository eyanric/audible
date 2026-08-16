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
