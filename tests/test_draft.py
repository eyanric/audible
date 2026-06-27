from __future__ import annotations

import pytest

from audible.config import LeagueConfig
from audible.draft.coverage import classify_key, split_scoring
from audible.draft.opportunity import OpportunityXfp, carried_value, modeled_xfp
from audible.draft.rookies import (
    DraftCapital,
    draft_capital_factor,
    normalize_name,
    opportunity_weight,
)


def test_coverage_classifies_locked_keys() -> None:
    assert classify_key("pass_int") == "modeled"  # verified: pass_interception_exp exists
    assert classify_key("rec_40p") == "carried"
    assert classify_key("rush_40p") == "carried"
    assert classify_key("fum_lost") == "carried"
    assert classify_key("idp_sack") == "ignored"
    assert classify_key("fgm_yds") == "ignored"


def test_split_scoring_on_real_config(sleeper_config: LeagueConfig) -> None:
    buckets = split_scoring(sleeper_config.scoring)
    assert len(buckets["modeled"]) == 11  # all 11 modeled keys are in this league's scoring
    assert set(buckets["carried"]) == {"rec_40p", "rec_30_39", "rush_40p", "fum_lost"}
    assert "pass_int" in buckets["modeled"]
    assert "idp_tkl_solo" in buckets["ignored"]


def test_modeled_xfp_scores_components_via_engine(sleeper_config: LeagueConfig) -> None:
    opp = OpportunityXfp("g", games=15, components={"rec": 50.0, "rec_yd": 600.0, "rec_td": 4.0})
    # half-PPR: 50*0.5 + 600*0.1 + 4*6 (annualization + consensus blend happen in the board)
    assert modeled_xfp(opp, sleeper_config.scoring) == pytest.approx(109.0)


def test_carried_value_only_carried_keys(sleeper_config: LeagueConfig) -> None:
    stats = {"rec_40p": 2.0, "rec_30_39": 3.0, "rush_40p": 1.0, "fum_lost": 2.0, "rec_yd": 999.0}
    # 2*1 + 3*0.5 + 1*2 + 2*(-1)  (rec_yd is modeled, must NOT count as carried)
    assert carried_value(stats, sleeper_config.scoring) == pytest.approx(3.5)


def test_normalize_name_strips_suffixes_and_punct() -> None:
    assert normalize_name("Travis Hunter Jr.") == "travis hunter"
    assert normalize_name("Marvin Harrison III") == "marvin harrison"
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name(None) == ""


def test_draft_capital_factor_monotonic_and_bounded() -> None:
    early = draft_capital_factor(DraftCapital(1, 1, "RB", "ATL"))
    late = draft_capital_factor(DraftCapital(7, 260, "DB", "NE"))
    assert early == pytest.approx(1.15)
    assert late == pytest.approx(0.85, abs=0.01)
    assert early > draft_capital_factor(DraftCapital(2, 40, "WR", "x")) > late
    assert draft_capital_factor(None) == 1.0  # undrafted -> no tilt


def test_opportunity_crossover_weight() -> None:
    assert opportunity_weight(0) == 0.0  # draft day: pure prior
    assert opportunity_weight(3, full_by=5) == pytest.approx(0.6)
    assert opportunity_weight(5, full_by=5) == 1.0
    assert opportunity_weight(12, full_by=5) == 1.0  # capped
