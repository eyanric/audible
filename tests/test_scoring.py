from __future__ import annotations

from typing import Any

from audible.config import LeagueConfig
from audible.scoring import score_stat_line


def test_qb_line_applies_harsh_int_penalty() -> None:
    scoring = {"pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "rush_yd": 0.1}
    stats = {"pass_yd": 300.0, "pass_td": 2.0, "pass_int": 1.0, "rush_yd": 20.0}
    # 12 + 8 - 2 + 2
    assert score_stat_line(stats, scoring) == 20.0


def test_idp_line_is_tackle_heavy() -> None:
    scoring = {"idp_tkl_solo": 2.0, "idp_tkl_ast": 1.0, "idp_sack": 6.0, "idp_int": 6.0}
    stats = {"idp_tkl_solo": 5.0, "idp_tkl_ast": 3.0, "idp_sack": 1.0}
    # 10 + 3 + 6 + 0
    assert score_stat_line(stats, scoring) == 19.0


def test_distance_kicker() -> None:
    scoring = {"fgm_yds": 0.1, "xpm": 1.0, "fgmiss_50p": -0.5}
    stats = {"fgm_yds": 50.0, "xpm": 3.0, "fgmiss_50p": 1.0}
    # 5 + 3 - 0.5
    assert score_stat_line(stats, scoring) == 7.5


def test_non_scoring_keys_never_leak() -> None:
    # adp_*, pts_*, gp and total-tackle idp_tkl must not affect the score.
    scoring = {"idp_tkl_solo": 2.0}
    stats = {
        "idp_tkl_solo": 4.0, "idp_tkl": 7.0, "pts_half_ppr": 99.0,
        "gp": 17.0, "adp_half_ppr": 12.3,
    }
    assert score_stat_line(stats, scoring) == 8.0


def test_big_play_bonus_applies_on_real_config(
    sleeper_config: LeagueConfig, sample_projections: dict[str, dict[str, Any]]
) -> None:
    # Ja'Marr Chase (7564) projects fractional 40+ catches -> rec_40p bonus must contribute.
    stats = sample_projections["7564"]["stats"]
    assert stats.get("rec_40p", 0) > 0
    with_bonus = score_stat_line(stats, sleeper_config.scoring)
    bonus_keys = ("rec_40p", "rec_30_39")
    no_bonus = {k: v for k, v in sleeper_config.scoring.items() if k not in bonus_keys}
    assert with_bonus > score_stat_line(stats, no_bonus)


def test_recompute_differs_from_standard_on_int(
    sleeper_config: LeagueConfig, sample_projections: dict[str, dict[str, Any]]
) -> None:
    # On a real QB line, our -2 INT scoring is exactly 1*projected_int below a -1 league.
    stats = sample_projections["4881"]["stats"]  # Lamar Jackson
    assert stats.get("pass_int", 0) > 0
    ours = score_stat_line(stats, sleeper_config.scoring)
    standard = dict(sleeper_config.scoring)
    standard["pass_int"] = -1.0
    standard_pts = score_stat_line(stats, standard)
    assert abs((standard_pts - ours) - stats["pass_int"]) < 1e-9


# --- position-scoped scoring (Gate 17) ----------------------------------------------------


def test_sleeper_scoring_is_untouched_by_the_position_layer(
    sleeper_config: LeagueConfig,
) -> None:
    """Every Sleeper league scores a stat identically for everyone. Adding per-position
    overrides for League B must not change League A's numbers or even its identity."""
    assert sleeper_config.scoring_by_position == {}
    assert sleeper_config.scoring_for("RB") is sleeper_config.scoring
    assert sleeper_config.scoring_for("nonsense") is sleeper_config.scoring


def test_scoring_for_will_not_answer_without_a_position() -> None:
    """The base table is only ever correct by accident, so it must not be reachable by
    forgetting an argument. This is the bug class made unspellable."""
    import inspect

    param = inspect.signature(LeagueConfig.scoring_for).parameters["position"]
    assert param.default is inspect.Parameter.empty


def test_espn_pays_receptions_to_receivers_but_not_backs(
    espn_config: LeagueConfig,
) -> None:
    """Confirmed by the commissioner 2026-08-17 and verified against the live API: WR and TE
    score 0.5 per reception, RB scores zero."""
    assert espn_config.scoring_for("WR")["rec"] == 0.5
    assert espn_config.scoring_for("TE")["rec"] == 0.5
    assert espn_config.scoring_for("RB")["rec"] == 0.0


def test_an_override_changes_only_its_own_stat(espn_config: LeagueConfig) -> None:
    """A position listed for one stat still takes the BASE weight for every other stat --
    the fallback semantics measured against ESPN (12/12 vs 0/12 for fallback-to-zero)."""
    rb = espn_config.scoring_for("RB")
    base = espn_config.scoring
    assert rb["rec"] != base["rec"]
    for key in base:
        if key != "rec":
            assert rb[key] == base[key], key


def test_the_reception_rule_is_worth_real_points(espn_config: LeagueConfig) -> None:
    """A 60-catch back must score 30 points less than a 60-catch receiver on the same line --
    enough to reorder RB against WR, which is why a flat table could not express it."""
    line = {"rec": 60.0, "rec_yd": 500.0, "rush_yd": 900.0, "rush_td": 6.0}
    rb = score_stat_line(line, espn_config.scoring_for("RB"))
    wr = score_stat_line(line, espn_config.scoring_for("WR"))
    assert wr - rb == 30.0
