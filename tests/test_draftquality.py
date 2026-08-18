"""C1/C2 -- draft-quality leaderboard and whether it predicts finishing."""

from __future__ import annotations

from typing import Any

import pytest

from audible.analysis.draftquality import build_report


class _Adapter:
    def __init__(
        self,
        picks: dict[int, list[dict[str, Any]]],
        actuals: dict[int, dict[str, float]],
        standings: dict[int, list[dict[str, Any]]],
    ) -> None:
        self._picks, self._actuals, self._standings = picks, actuals, standings

    def get_season_draft(self, _c: Any, season: int) -> list[dict[str, Any]]:
        return self._picks.get(season, [])

    def get_season_actuals(self, _c: Any, season: int) -> dict[str, float]:
        return self._actuals.get(season, {})

    def get_season_standings(self, _c: Any, season: int) -> list[dict[str, Any]]:
        return self._standings.get(season, [])


def _standing_rows(order: list[int], owners: dict[int, str]) -> list[dict[str, Any]]:
    """`order` is team_ids best-finish-first."""
    return [
        {
            "team_id": tid, "abbrev": f"T{tid}", "owner": owners[tid],
            "standing": i + 1, "playoff_seed": i + 1,
            "wins": 14 - i, "losses": i, "points_for": float(2000 - 100 * i),
        }
        for i, tid in enumerate(order)
    ]


def _season(team_points: dict[int, list[float]]) -> tuple[list[dict], dict[str, float]]:
    picks: list[dict[str, Any]] = []
    actuals: dict[str, float] = {}
    overall = 0
    for tid, values in team_points.items():
        for j, pts in enumerate(values):
            pid = f"{tid}-{j}"
            overall += 1
            picks.append({"overall": overall, "round": 1, "team_id": tid, "player_id": pid})
            actuals[pid] = pts
    return picks, actuals


def test_seats_are_ranked_by_realized_points_of_who_they_drafted() -> None:
    picks, actuals = _season({1: [100.0, 50.0], 2: [200.0, 10.0], 3: [10.0, 10.0]})
    owners = {1: "o1", 2: "o2", 3: "o3"}
    adapter = _Adapter(
        {2024: picks}, {2024: actuals}, {2024: _standing_rows([1, 2, 3], owners)}
    )
    report = build_report(adapter, None, seasons=(2024,))

    by_team = {s.team_id: s for s in report.seat_seasons}
    assert by_team[2].points == 210.0 and by_team[2].draft_rank == 1
    assert by_team[1].points == 150.0 and by_team[1].draft_rank == 2
    assert by_team[3].points == 20.0 and by_team[3].draft_rank == 3


def test_a_player_with_no_realized_total_is_counted_not_zeroed() -> None:
    """Treating him as a zero would silently punish whoever drafted him."""
    picks, actuals = _season({1: [100.0], 2: [50.0]})
    picks.append({"overall": 99, "round": 2, "team_id": 1, "player_id": "ghost"})
    owners = {1: "o1", 2: "o2"}
    report = build_report(
        _Adapter({2024: picks}, {2024: actuals}, {2024: _standing_rows([1, 2], owners)}),
        None, seasons=(2024,),
    )

    assert report.unscored_picks == 1
    assert report.total_picks == 3
    seat = next(s for s in report.seat_seasons if s.team_id == 1)
    assert seat.points == 100.0
    assert seat.drafted == 2 and seat.scored == 1


def test_identity_follows_the_owner_not_the_team_id() -> None:
    """ESPN reuses teamId across seasons. A seat is a person; pooling by slot would merge
    two different managers who happened to inherit the same id."""
    picks_a, actuals_a = _season({1: [100.0], 2: [50.0]})
    picks_b, actuals_b = _season({1: [10.0], 2: [90.0]})
    # The same owner sits at team 1 in 2023 and team 2 in 2024.
    owners_a = {1: "alice", 2: "bob"}
    owners_b = {1: "bob", 2: "alice"}
    report = build_report(
        _Adapter(
            {2023: picks_a, 2024: picks_b},
            {2023: actuals_a, 2024: actuals_b},
            {2023: _standing_rows([1, 2], owners_a), 2024: _standing_rows([1, 2], owners_b)},
        ),
        None, seasons=(2023, 2024),
    )

    alice = next(c for c in report.careers if c.owner == "alice")
    assert alice.seasons == 2
    assert alice.mean_draft_rank == 1.0, "alice drafted best in both, under two team ids"


def test_a_season_without_outcomes_is_skipped() -> None:
    picks, actuals = _season({1: [100.0], 2: [50.0]})
    report = build_report(
        _Adapter({2024: picks}, {2024: actuals}, {2024: []}), None, seasons=(2024,)
    )
    assert report.seasons == ()
    assert report.seat_seasons == []


def test_perfect_agreement_gives_a_positive_correlation() -> None:
    """Draft rank and finish identical => rho +1: drafting decided the season."""
    picks, actuals = _season({1: [300.0], 2: [200.0], 3: [100.0]})
    owners = {1: "o1", 2: "o2", 3: "o3"}
    report = build_report(
        _Adapter({2024: picks}, {2024: actuals}, {2024: _standing_rows([1, 2, 3], owners)}),
        None, seasons=(2024,),
    )
    assert report.corr_standing["2024"][0] == pytest.approx(1.0)


def test_reversed_outcomes_give_a_negative_correlation() -> None:
    picks, actuals = _season({1: [300.0], 2: [200.0], 3: [100.0]})
    owners = {1: "o1", 2: "o2", 3: "o3"}
    report = build_report(
        _Adapter({2024: picks}, {2024: actuals}, {2024: _standing_rows([3, 2, 1], owners)}),
        None, seasons=(2024,),
    )
    assert report.corr_standing["2024"][0] == pytest.approx(-1.0)


def test_the_season_level_interval_is_wider_than_the_pooled_n_implies() -> None:
    """The pooled figure counts one season's evidence once per seat. Seasons are the
    independent unit, and with a handful of them the interval must be wide enough to say so.
    """
    seasons: dict[int, Any] = {}
    actuals: dict[int, Any] = {}
    standings: dict[int, Any] = {}
    owners = {1: "o1", 2: "o2", 3: "o3"}
    # Three seasons that disagree with each other about whether drafting mattered.
    for i, order in enumerate([[1, 2, 3], [3, 2, 1], [1, 2, 3]]):
        year = 2023 + i
        picks, act = _season({1: [300.0], 2: [200.0], 3: [100.0]})
        seasons[year], actuals[year] = picks, act
        standings[year] = _standing_rows(order, owners)

    report = build_report(
        _Adapter(seasons, actuals, standings), None, seasons=(2023, 2024, 2025)
    )
    mean, half_width, n = report.season_level("standing")
    assert n == 3
    assert half_width > 0.5, "seasons that disagree must produce a wide interval"
    assert mean - half_width < 0 < mean + half_width, "and one that admits zero"
