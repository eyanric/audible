"""B-next -- mid-tier rank delta, with synthetic boards that have a known answer."""

from __future__ import annotations

from audible.analysis.rankdelta import MATERIAL_MOVE, RANK_HORIZON, build_report
from audible.config import LeagueConfig
from audible.models.player import PlayerProjection


def _player(pid: str, pos: str, points: float, espn_rank: float | None, rec: float = 0.0):
    stats = {"rec": rec}
    if espn_rank is not None:
        stats["espn_draft_rank"] = espn_rank
    return PlayerProjection(
        player_id=pid, name=f"{pos}{pid}", primary_position=pos,
        eligible_positions=frozenset({pos}), team="AAA", points=points, stats=stats,
    )


def _agreeing(n: int = 200) -> list[PlayerProjection]:
    """Our points order exactly matches ESPN's rank order."""
    return [
        _player(str(i), "WR" if i % 2 else "RB", points=float(1000 - i), espn_rank=float(i))
        for i in range(1, n + 1)
    ]


def test_identical_orderings_show_no_divergence(espn_config: LeagueConfig) -> None:
    report = build_report(_agreeing(), espn_config)
    assert report.diverges() is False
    for tier in report.tiers:
        assert tier.mean_abs_delta < MATERIAL_MOVE


def test_the_degenerate_rank_tail_is_excluded(espn_config: LeagueConfig) -> None:
    """ESPN's tail runs to 2687 and is a placeholder, not an ordering -- same guard, same
    reason as the anchoring gate."""
    players = _agreeing(50)
    players.append(_player("junk", "WR", points=500.0, espn_rank=2554.0))
    report = build_report(players, espn_config)

    assert report.excluded_beyond_horizon == 1
    assert report.population == 50
    assert RANK_HORIZON >= 128, "the horizon must cover the whole 128-pick decision space"


def test_players_with_no_espn_rank_are_counted_not_dropped(espn_config: LeagueConfig) -> None:
    players = _agreeing(30)
    players.append(_player("unranked", "TE", points=400.0, espn_rank=None))
    report = build_report(players, espn_config)
    assert report.excluded_unranked == 1
    assert report.population == 30


def test_reception_driven_reads_the_sign_the_scoring_predicts(
    espn_config: LeagueConfig,
) -> None:
    """The averaged version of this test said "no" by cancelling a real WR effect against a
    real RB one. The scoring predicts OPPOSITE signs: WR/TE are paid 0.5 a catch so high-
    reception receivers must move UP, RB is paid 0.0 so pass-catchers must move DOWN.
    """
    players: list[PlayerProjection] = []
    # 40 WRs across the mid tiers: more receptions => we rank him better than ESPN does.
    for i in range(1, 41):
        espn_rank = float(i + 24)
        receptions = float(i)
        players.append(
            _player(f"wr{i}", "WR", points=200.0 + receptions, espn_rank=espn_rank,
                    rec=receptions)
        )
    # 20 RBs. ESPN's ordering credits catches, so it ranks the pass-catchers EARLY; ours
    # pays them nothing, so it ranks them LATE. The two boards must pull in opposite
    # directions or there is no effect to detect -- an earlier version of this fixture had
    # both orderings agreeing and measured nothing.
    for i in range(1, 21):
        receptions = float(i)
        players.append(
            _player(f"rb{i}", "RB", points=300.0 - receptions, espn_rank=float(85 - i),
                    rec=receptions)
        )

    driven = build_report(players, espn_config).reception_driven()
    assert "WR" in driven and driven["WR"] >= 0.3
    assert "RB" in driven and driven["RB"] >= 0.3


def test_movement_with_no_reception_pattern_is_not_called_reception_driven(
    espn_config: LeagueConfig,
) -> None:
    """A whole position shifting as a block is VORP-vs-market structure, not receptions.
    Every TE here moves the same distance regardless of how much he catches."""
    players: list[PlayerProjection] = []
    for i in range(1, 31):
        players.append(_player(f"wr{i}", "WR", points=float(500 - i), espn_rank=float(i)))
    for i in range(1, 21):
        # ranked late by ESPN, ranked early by us, and receptions carry no signal
        players.append(
            _player(f"te{i}", "TE", points=float(490 - i), espn_rank=float(i + 60),
                    rec=float((i * 7) % 13))
        )

    report = build_report(players, espn_config)
    assert report.diverges() is True
    assert "TE" not in report.reception_driven()


def test_both_orderings_are_dense_ranked_over_one_population(
    espn_config: LeagueConfig,
) -> None:
    """Comparing a rank drawn from 1,026 players against one drawn from 400 measures the
    size of the universe, not the disagreement."""
    players = _agreeing(40)
    players += [_player(f"deep{i}", "WR", points=1.0, espn_rank=None) for i in range(50)]
    report = build_report(players, espn_config)

    assert report.population == 40
    # An agreeing board must still agree once the unranked players are excluded.
    assert report.diverges() is False
