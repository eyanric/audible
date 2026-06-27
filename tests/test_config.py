from __future__ import annotations

import pytest
from pydantic import ValidationError

from audible.config import LeagueConfig, load_all_leagues
from audible.config.schema import Platform


def test_both_leagues_load_and_validate() -> None:
    leagues = load_all_leagues()
    assert set(leagues) == {"sleeper_boyfun", "espn_davis_drive"}


def test_sleeper_config_matches_hand_won_spec(sleeper_config: LeagueConfig) -> None:
    cfg = sleeper_config
    assert cfg.platform is Platform.SLEEPER
    assert cfg.num_teams == 10
    assert cfg.median_match is True
    assert len(cfg.starting_slots) == 15
    assert len(cfg.scoring) == 72
    # the scoring quirks that matter
    assert cfg.scoring["rec"] == 0.5
    assert cfg.scoring["pass_int"] == -2  # harsher than standard
    assert cfg.scoring["rec_40p"] == 1 and cfg.scoring["rush_40p"] == 2  # big-play ON
    assert cfg.scoring["bonus_fd_wr"] == 0  # first-down bonuses OFF
    assert cfg.scoring["fgm_yds"] == 0.1  # distance kicker
    assert cfg.scoring["idp_tkl_solo"] == 2 and cfg.scoring["idp_sack"] == 6  # tackle-heavy IDP


def test_positions_are_derived_from_eligibility(sleeper_config: LeagueConfig) -> None:
    assert sleeper_config.positions == {"QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"}


def test_espn_is_shallow_no_idp(espn_config: LeagueConfig) -> None:
    assert espn_config.num_teams == 8
    assert espn_config.expected_reception_points == 0.5
    assert espn_config.positions == {"QB", "RB", "WR", "TE", "K", "DEF"}
    assert "DL" not in espn_config.positions  # no IDP in League B


def test_value_metric_is_league_aware(
    sleeper_config: LeagueConfig, espn_config: LeagueConfig
) -> None:
    # Learned from the backtest: VORP for deep superflex+IDP, scarcity for flat 1-QB.
    assert sleeper_config.value_metric == "vorp"
    assert espn_config.value_metric == "scarcity"


def test_bad_value_metric_rejected() -> None:
    with pytest.raises(ValidationError):
        LeagueConfig.model_validate(
            {
                "key": "x", "name": "x", "platform": "sleeper", "league_id": "1",
                "season": 2026, "num_teams": 10,
                "starting_slots": ["QB"], "slot_eligibility": {"QB": ["QB"]},
                "scoring": {"rec": 0.5}, "value_metric": "nonsense",
            }
        )


def test_slot_without_eligibility_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LeagueConfig.model_validate(
            {
                "key": "bad", "name": "bad", "platform": "sleeper", "league_id": "1",
                "season": 2026, "num_teams": 10,
                "starting_slots": ["QB", "FLEX"],
                "slot_eligibility": {"QB": ["QB"]},  # FLEX missing
                "scoring": {"rec": 0.5},
            }
        )


def test_unknown_position_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LeagueConfig.model_validate(
            {
                "key": "bad", "name": "bad", "platform": "sleeper", "league_id": "1",
                "season": 2026, "num_teams": 10,
                "starting_slots": ["QB"],
                "slot_eligibility": {"QB": ["QUARTERBACK"]},  # not a known position
                "scoring": {"rec": 0.5},
            }
        )
