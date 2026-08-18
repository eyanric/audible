"""C1/C2 -- who actually drafts well here, and does it matter?

**C1** sums the realized points of every player a seat drafted, under that season's own
scoring, and ranks the seats. No projections and no ADP are involved, so all five seasons
qualify -- including 2021-22, which are unusable for anything rank-dependent.

**C2** asks the question that sizes everything else: does drafting well predict finishing
well? If the seats that drafted best routinely finished mid-table, then draft edge is a weak
lever in this league, and a model that drafts a few percent better is optimising something
that does not decide seasons. That result would be worth more than a favourable one.

Identity is the **owner GUID**, never ``teamId``: ESPN reuses team ids across seasons and a
seat is a person, not a slot. The GUID is a join key only -- seats are displayed by team
abbreviation, and the real names ESPN serves in ``members`` are never read.

**Stated, not solved:** drafted-roster points ignore waivers, trades and start/sit. This
measures the draft, which is the point, but it is not the season.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from ..backtest.metrics import spearman

ALL_SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)


@dataclass(frozen=True, slots=True)
class SeatSeason:
    season: int
    owner: str
    abbrev: str
    team_id: int
    drafted: int
    scored: int  # drafted players ESPN has a realized total for
    points: float
    draft_rank: int  # 1 = best draft that season
    standing: int  # 1 = league winner
    points_for: float
    wins: int
    losses: int


@dataclass(frozen=True, slots=True)
class SeatCareer:
    owner: str
    abbrev: str
    seasons: int
    mean_draft_rank: float
    stdev_draft_rank: float
    best: int
    worst: int
    mean_standing: float


@dataclass(frozen=True, slots=True)
class QualityReport:
    seasons: tuple[int, ...]
    seat_seasons: list[SeatSeason]
    careers: list[SeatCareer]
    unscored_picks: int
    total_picks: int
    # C2, per season and pooled.
    corr_standing: dict[str, tuple[float, int]]
    corr_points: dict[str, tuple[float, int]]

    @property
    def coverage(self) -> float:
        return (
            (self.total_picks - self.unscored_picks) / self.total_picks
            if self.total_picks
            else 0.0
        )

    def season_level(self, which: str = "standing") -> tuple[float, float, int]:
        """(mean rho, 95% half-width, seasons) treating each SEASON as one observation.

        The pooled figure over 40 seat-seasons looks far better powered than it is. Within a
        season the eight draft ranks are a permutation of 1..8 and so are the finishes -- the
        seats are not independent of each other, and pooling them counts one season's worth
        of evidence eight times.

        Seasons genuinely are independent, so the honest unit is the season. That leaves five
        observations, which is the real precision available here.
        """
        source = self.corr_standing if which == "standing" else self.corr_points
        rhos = [rho for key, (rho, _) in source.items() if key != "pooled"]
        n = len(rhos)
        if n < 2:
            return (rhos[0] if rhos else 0.0, 0.0, n)
        mean = statistics.fmean(rhos)
        stderr = statistics.stdev(rhos) / (n**0.5)
        # t(0.975) for 2..6 seasons; beyond that the normal approximation is close enough.
        critical = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57}.get(n, 2.45)
        return (mean, critical * stderr, n)


def _rank(values: dict[str, float], *, high_is_good: bool) -> dict[str, int]:
    sign = -1 if high_is_good else 1
    order = sorted(values, key=lambda k: (sign * values[k], k))
    return {k: i + 1 for i, k in enumerate(order)}


def build_report(
    adapter: Any, config: Any, *, seasons: tuple[int, ...] = ALL_SEASONS
) -> QualityReport:
    seat_seasons: list[SeatSeason] = []
    unscored = 0
    total = 0
    used: list[int] = []

    corr_standing: dict[str, tuple[float, int]] = {}
    corr_points: dict[str, tuple[float, int]] = {}

    for season in seasons:
        picks = adapter.get_season_draft(config, season)
        actuals = adapter.get_season_actuals(config, season)
        standings = {row["team_id"]: row for row in adapter.get_season_standings(config, season)}
        if not picks or not actuals or not standings:
            continue
        used.append(season)

        points: dict[int, float] = {}
        drafted: dict[int, int] = {}
        scored: dict[int, int] = {}
        for pick in picks:
            team_id = pick["team_id"]
            total += 1
            drafted[team_id] = drafted.get(team_id, 0) + 1
            realized = actuals.get(str(pick["player_id"]))
            if realized is None:
                # A drafted player ESPN has no season total for -- counted, never treated
                # as a zero, which would silently punish whoever drafted him.
                unscored += 1
                continue
            scored[team_id] = scored.get(team_id, 0) + 1
            points[team_id] = points.get(team_id, 0.0) + realized

        draft_rank = _rank({str(k): v for k, v in points.items()}, high_is_good=True)
        for team_id, total_points in points.items():
            row = standings.get(team_id)
            if row is None:
                continue
            seat_seasons.append(
                SeatSeason(
                    season=season,
                    owner=row["owner"],
                    abbrev=row["abbrev"],
                    team_id=team_id,
                    drafted=drafted.get(team_id, 0),
                    scored=scored.get(team_id, 0),
                    points=total_points,
                    draft_rank=draft_rank[str(team_id)],
                    standing=row["standing"],
                    points_for=row["points_for"],
                    wins=row["wins"],
                    losses=row["losses"],
                )
            )

        this_season = [s for s in seat_seasons if s.season == season]
        if len(this_season) > 1:
            ranks = [float(s.draft_rank) for s in this_season]
            corr_standing[str(season)] = (
                spearman(ranks, [float(s.standing) for s in this_season]),
                len(this_season),
            )
            corr_points[str(season)] = (
                spearman(ranks, [-s.points_for for s in this_season]),
                len(this_season),
            )

    if len(seat_seasons) > 1:
        ranks = [float(s.draft_rank) for s in seat_seasons]
        corr_standing["pooled"] = (
            spearman(ranks, [float(s.standing) for s in seat_seasons]),
            len(seat_seasons),
        )
        corr_points["pooled"] = (
            spearman(ranks, [-s.points_for for s in seat_seasons]),
            len(seat_seasons),
        )

    careers: list[SeatCareer] = []
    for owner in sorted({s.owner for s in seat_seasons}):
        mine = [s for s in seat_seasons if s.owner == owner]
        ranks = [float(s.draft_rank) for s in mine]
        careers.append(
            SeatCareer(
                owner=owner,
                abbrev=mine[-1].abbrev,
                seasons=len(mine),
                mean_draft_rank=statistics.fmean(ranks),
                stdev_draft_rank=statistics.stdev(ranks) if len(ranks) > 1 else 0.0,
                best=min(s.draft_rank for s in mine),
                worst=max(s.draft_rank for s in mine),
                mean_standing=statistics.fmean([float(s.standing) for s in mine]),
            )
        )

    return QualityReport(
        seasons=tuple(used),
        seat_seasons=seat_seasons,
        careers=sorted(careers, key=lambda c: c.mean_draft_rank),
        unscored_picks=unscored,
        total_picks=total,
        corr_standing=corr_standing,
        corr_points=corr_points,
    )
