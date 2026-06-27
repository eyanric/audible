from __future__ import annotations

from typing import Any

from audible.adapters.sleeper import SleeperAdapter
from audible.config import LeagueConfig


def _classify(catalog: dict[str, dict[str, Any]], pid: str, cfg: LeagueConfig):
    return SleeperAdapter.classify(catalog[pid], cfg.positions)


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
