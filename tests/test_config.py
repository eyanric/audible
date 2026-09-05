from __future__ import annotations

import pytest
from pydantic import ValidationError

from audible.config import LeagueConfig, load_all_leagues
from audible.config.schema import Platform


def test_every_league_loads_and_validates() -> None:
    leagues = load_all_leagues()
    assert set(leagues) == {"sleeper_boyfun", "espn_davis_drive", "espn_danger_zone"}


def test_the_two_espn_leagues_do_not_share_scoring() -> None:
    """They differ in ways nothing signals, which is why neither is derived from the other.

    DDAFFL pays receptions only to QB/WR/TE via per-position overrides and pays passing yards
    through the 25-yard bucket. Danger Zone pays full PPR to every position and pays raw
    passing yards. A config copied from one to the other would be a confident wrong board.
    """
    leagues = load_all_leagues()
    ddaffl, danger = leagues["espn_davis_drive"], leagues["espn_danger_zone"]
    assert ddaffl.scoring_for("RB")["rec"] == 0.0
    assert ddaffl.scoring_for("WR")["rec"] == 0.5
    assert danger.scoring_for("RB")["rec"] == 1.0
    assert danger.scoring_for("WR")["rec"] == 1.0
    assert danger.num_teams == 10 and ddaffl.num_teams == 8
    assert danger.draft_slot == 5


def test_sleeper_config_matches_hand_won_spec(sleeper_config: LeagueConfig) -> None:
    cfg = sleeper_config
    assert cfg.platform is Platform.SLEEPER
    assert cfg.num_teams == 10
    assert cfg.median_match is True
    # 12 starters, re-verified against the live league 2026-09-05, the morning of the draft.
    # A DEF slot APPEARED between the 2026-08-15 capture (11 starters, no DEF) and this one;
    # `roster_positions` and draft settings (slots_def=1, rounds=19) agree. This assertion has
    # now moved twice, which is the point of running `verify-scoring` before every draft
    # rather than trusting a capture.
    assert len(cfg.starting_slots) == 12
    assert cfg.slot_counts() == {
        "QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "SUPER_FLEX": 1,
        "K": 1, "DEF": 1, "IDP_FLEX": 1,
    }
    assert cfg.slot_eligibility["DEF"] == ("DEF",)
    assert cfg.draft_rounds == 19  # 12 starters + slots_bn=7
    assert len(cfg.scoring) == 72
    # the scoring quirks that matter
    assert cfg.scoring["rec"] == 0.5
    assert cfg.scoring["pass_int"] == -2  # harsher than standard
    assert cfg.scoring["rec_40p"] == 1 and cfg.scoring["rush_40p"] == 2  # big-play ON
    assert cfg.scoring["bonus_fd_wr"] == 0  # first-down bonuses OFF
    assert cfg.scoring["fgm_yds"] == 0.1  # distance kicker
    # Tackle-heavy IDP, but the splash plays are worth HALF what they were: the live league
    # dropped idp_sack and idp_int from 6.0 to 3.0 between 2026-08-15 and 2026-09-05.
    assert cfg.scoring["idp_tkl_solo"] == 2
    assert cfg.scoring["idp_sack"] == 3 and cfg.scoring["idp_int"] == 3


def test_positions_are_derived_from_eligibility(sleeper_config: LeagueConfig) -> None:
    # IDP is rosterable through IDP_FLEX, and DEF is back: the live league carries a DEF slot
    # again as of 2026-09-05, so team defences are on League A's board and in its baselines.
    assert sleeper_config.positions == {"QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"}


def test_espn_is_shallow_no_idp(espn_config: LeagueConfig) -> None:
    assert espn_config.num_teams == 8
    assert espn_config.expected_reception_points == 0.5
    assert espn_config.positions == {"QB", "RB", "WR", "TE", "K", "DEF"}
    assert "DL" not in espn_config.positions  # no IDP in League B


def test_value_metric_is_league_aware(
    sleeper_config: LeagueConfig, espn_config: LeagueConfig
) -> None:
    # Both ship on VORP: scarcity/VONA is pathological on flat positions (see espn config note).
    assert sleeper_config.value_metric == "vorp"
    assert espn_config.value_metric == "vorp"


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


# --- League B structural ground truth (Task 2, re-verified live 2026-08-25) --------------
#
# Confirmed two independent ways against ESPN league 6012 on 2026-08-25:
#
#   1. The raw API. `settings.rosterSettings.lineupSlotCounts`, by ESPN lineup-slot id:
#        0 QB=1   2 RB=2   4 WR=2   6 TE=1   16 D/ST=1   17 K=1   23 FLEX=1
#        20 BE=7  21 IR=3        -> 19 slots, minus 3 IR = 16 DRAFTED ROUNDS
#      and `settings.size = 8`.
#
#   2. `uv run audible verify-scoring espn_davis_drive`, which re-reads the live league:
#        "roster structure is FAITHFUL (9 starting slots match)"
#        "config scoring is FAITHFUL to the live league (48 position-scoped weights match)"
#        "receptions confirmed LIVE at 0.5/rec for WR/TE (RB stays 0.0 by design)"
#
# This is pinned in a test because the replacement baselines are DERIVED from it. The bench
# allocation in `value/replacement.py` splits 8 x 7 = 56 bench picks across the positions a
# team can start more than one of, which is what puts RB replacement at RB35 and WR at WR52.
# Change the starting lineup and every one of those numbers is wrong -- silently, because the
# board still builds. A failure here means: re-verify against the live league, then recompute.
EXPECTED_STARTING_LINEUP = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K")


def test_league_b_structure_is_the_one_the_baselines_were_derived_from(
    espn_config: LeagueConfig,
) -> None:
    assert espn_config.num_teams == 8
    assert espn_config.draft_rounds == 16
    assert espn_config.starting_slots == EXPECTED_STARTING_LINEUP
    assert len(espn_config.starting_slots) == 9
    # 16 rounds against 9 starters is where the 7 bench picks come from.
    assert espn_config.draft_rounds - len(espn_config.starting_slots) == 7
    assert espn_config.replacement_bench_slots == 7
    # D/ST and K each occupy exactly one slot and no flex, which is why nobody rosters a
    # backup and why their replacement level sits at the team count.
    assert espn_config.starting_slots.count("DEF") == 1
    assert espn_config.starting_slots.count("K") == 1
    assert "DEF" not in espn_config.slot_eligibility["FLEX"]
    assert "K" not in espn_config.slot_eligibility["FLEX"]
    # No superflex, no IDP -- this is a 1-QB, offence-plus-D/ST league.
    assert "SUPER_FLEX" not in espn_config.starting_slots
    assert "IDP_FLEX" not in espn_config.starting_slots
    assert espn_config.positions == frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})
