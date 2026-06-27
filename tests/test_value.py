from __future__ import annotations

import pytest

from audible.config import LeagueConfig
from audible.models import PlayerProjection
from audible.value import assign_starters, compute_vorp, replacement_levels


def _p(pid: str, pos: str, pts: float) -> PlayerProjection:
    return PlayerProjection(
        player_id=pid, name=pid, primary_position=pos,
        eligible_positions=frozenset({pos}), team=None, points=pts,
    )


@pytest.fixture
def mini_players() -> list[PlayerProjection]:
    return [
        _p("QB1", "QB", 30), _p("QB2", "QB", 28), _p("QB3", "QB", 20), _p("QB4", "QB", 10),
        _p("RB1", "RB", 25), _p("RB2", "RB", 22), _p("RB3", "RB", 15),
        _p("WR1", "WR", 24), _p("WR2", "WR", 18),
    ]


def test_superflex_pulls_a_qb_into_flex(
    mini_config: LeagueConfig, mini_players: list[PlayerProjection]
) -> None:
    starters = assign_starters(mini_players, mini_config)
    # 6 slots: 2 QB (QB1,QB2), 2 FLEX (RB1,WR1), 2 SUPER_FLEX (RB2 then QB3).
    assert starters == {"QB1", "QB2", "RB1", "WR1", "RB2", "QB3"}


def test_replacement_levels(
    mini_config: LeagueConfig, mini_players: list[PlayerProjection]
) -> None:
    levels = replacement_levels(mini_players, mini_config)
    assert levels["QB"].points == 10 and levels["QB"].replacement_rank == 4
    assert levels["QB"].starters_used == 3  # superflex absorbs a 3rd QB
    assert levels["RB"].points == 15
    assert levels["WR"].points == 18
    assert levels["TE"].points == 0 and levels["TE"].starters_used == 0


def test_vorp_values_and_starter_flags(
    mini_config: LeagueConfig, mini_players: list[PlayerProjection]
) -> None:
    entries, _ = compute_vorp(mini_players, mini_config)
    by_id = {e.projection.player_id: e for e in entries}
    assert by_id["QB1"].vorp == 20 and by_id["QB1"].is_starter
    assert by_id["RB1"].vorp == 10
    assert by_id["WR1"].vorp == 6
    assert by_id["QB4"].vorp == 0 and not by_id["QB4"].is_starter
    # sorted descending by vorp
    assert [e.vorp for e in entries] == sorted((e.vorp for e in entries), reverse=True)
