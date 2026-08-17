"""B1 -- which board is each opponent actually drafting off?

The scoring edge in League B is archetype-specific, and this decides whether it is worth
anything against *this* room.

ESPN's served STANDARD ordering already tracks PPR at the top -- Chase, Nacua, Gibbs, McBride
and Bowers sit at identical ranks in both -- so the 0.5/reception split does not produce a
top-of-board mispricing anyone could exploit. The two orderings diverge in exactly one place:
**non-receiving running backs**, where STANDARD rates them far higher (Derrick Henry STANDARD
#10 against PPR #19), because a PPR board pays receiving backs for catches this league does
not pay RBs for at all.

So the question is not "is our board better". It is: *when a manager is choosing, whose
ordering does the choice look like?*

- A manager anchored to **ESPN's own board** already prices Henry-types correctly. No edge.
- A manager anchored to a **generic PPR/half-PPR** board undervalues pure rushing backs in a
  league that pays RBs nothing per reception. That is the exploitable seat.

Method, per manager per season:

* **Spearman(pick order, rank)** -- did they draft down the board in order?
* **MAD** -- mean |rank - overall pick number|, i.e. how far from the board they reach.
* **The discriminating test** -- restricted to picks where the two boards actually disagree,
  is the pick number closer to the STANDARD rank or the PPR rank?

The last one is the only one with any power to separate the two anchors, because on the ~90%
of players where the boards agree, both fit equally well by construction. It is also where
the sample gets thin, which is why this module refuses to classify a seat it cannot resolve
rather than reporting a direction it has not earned.

2021 and 2022 are excluded throughout: ESPN serves no ranks for those seasons, and sorting by
an absent rank type returns arbitrary order with no error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..backtest.metrics import spearman

# Seasons ESPN serves per-season draft ranks for. 2021-22 return 400 players and zero ranks.
RANKED_SEASONS: tuple[int, ...] = (2023, 2024, 2025)

# How far the two boards must disagree about a player before his selection says anything
# about which board the manager was reading. Below this the boards agree and every pick fits
# both equally well.
DIVERGENCE_MIN = 10.0

# Minimum discriminating picks before a seat gets a label at all. Under this the honest
# answer is "unclassified", not a direction read off three players.
MIN_DIVERGENT = 6

# Ranks past this are not an ordering and must not be treated as one.
#
# ESPN's served board is dense to roughly 200 and degenerates after: measured per season,
# ~155 players hold a STANDARD rank <= 200, ~280 hold one <= 400, and ~800 more carry values
# running to 2687. That tail is a placeholder, not a judgement, and it wrecks the comparison
# -- a player can sit at STANDARD 57 and PPR 2554, which is not the two boards disagreeing
# about him, it is one board declining to rank him. Left in, those few picks dominated every
# average (mean divergence 85.2 against a median of 10.0).
#
# The draft is 128 picks, so a horizon of 200 covers the whole decision space with room to
# spare. Picks outside it are counted and reported, never silently included.
RANK_HORIZON = 200.0


@dataclass(frozen=True, slots=True)
class SeatSeason:
    season: int
    team_id: int
    picks: int
    ranked_picks: int
    spearman_standard: float
    spearman_ppr: float
    mad_standard: float
    mad_ppr: float


@dataclass(frozen=True, slots=True)
class SeatVerdict:
    """One manager, pooled across the ranked seasons."""

    team_id: int
    abbrev: str
    picks: int
    ranked_picks: int
    divergent: int
    spearman_standard: float
    spearman_ppr: float
    mad_standard: float
    mad_ppr: float
    # Mean of |ppr - pick| - |standard - pick| over the divergent picks. Positive => the
    # STANDARD board explains this manager's choices better; negative => the PPR board does.
    edge: float
    stderr: float
    label: str  # "espn" | "ppr" | "unclassified"

    @property
    def exploitable(self) -> bool:
        """A PPR-anchored manager undervalues the archetype this league overpays."""
        return self.label == "ppr"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stderr(xs: list[float]) -> float:
    """Standard error of the mean. Zero for n<2 -- an interval needs at least two points."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean = _mean(xs)
    variance = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(variance / n)


@dataclass(frozen=True, slots=True)
class _Pick:
    overall: int
    order: int  # this manager's Nth pick of the season
    standard: float
    ppr: float


def _seat_picks(
    picks: list[dict[str, Any]], ranks: dict[str, dict[str, Any]], team_id: int
) -> list[_Pick]:
    """This manager's picks that BOTH boards priced, in draft order.

    A pick whose player is off either board carries no information about which board was
    being read, so it is excluded here and counted separately -- never silently dropped.
    """
    out: list[_Pick] = []
    order = 0
    for row in picks:
        if row["team_id"] != team_id:
            continue
        order += 1
        entry = ranks.get(str(row["player_id"]))
        if entry is None:
            continue
        standard, ppr = entry.get("standard"), entry.get("ppr")
        if standard is None or ppr is None:
            continue
        if float(standard) > RANK_HORIZON or float(ppr) > RANK_HORIZON:
            continue  # outside the served board's dense range -- see RANK_HORIZON
        out.append(_Pick(int(row["overall"]), order, float(standard), float(ppr)))
    return out


def seat_season(
    season: int, team_id: int, picks: list[dict[str, Any]], ranks: dict[str, dict[str, Any]]
) -> SeatSeason:
    mine = _seat_picks(picks, ranks, team_id)
    total = sum(1 for row in picks if row["team_id"] == team_id)
    order = [float(p.order) for p in mine]
    return SeatSeason(
        season=season,
        team_id=team_id,
        picks=total,
        ranked_picks=len(mine),
        spearman_standard=spearman(order, [p.standard for p in mine]) if len(mine) > 1 else 0.0,
        spearman_ppr=spearman(order, [p.ppr for p in mine]) if len(mine) > 1 else 0.0,
        mad_standard=_mean([abs(p.standard - p.overall) for p in mine]),
        mad_ppr=_mean([abs(p.ppr - p.overall) for p in mine]),
    )


def seat_verdict(
    team_id: int, abbrev: str, seasons: dict[int, tuple[list[dict[str, Any]], dict[str, Any]]]
) -> SeatVerdict:
    """Pool a manager's ranked seasons into one verdict.

    Pooling is over PICKS, not over per-season averages: seasons contribute unequal numbers
    of usable picks, and averaging averages would weight a thin season like a full one.
    """
    all_picks: list[_Pick] = []
    total = 0
    per_season: list[SeatSeason] = []
    for season, (picks, ranks) in sorted(seasons.items()):
        all_picks.extend(_seat_picks(picks, ranks, team_id))
        total += sum(1 for row in picks if row["team_id"] == team_id)
        per_season.append(seat_season(season, team_id, picks, ranks))

    order = [float(p.order) for p in all_picks]
    divergent = [p for p in all_picks if abs(p.standard - p.ppr) >= DIVERGENCE_MIN]
    # Positive => taking him at this pick number looks more like the STANDARD board.
    deltas = [abs(p.ppr - p.overall) - abs(p.standard - p.overall) for p in divergent]
    edge, stderr = _mean(deltas), _stderr(deltas)

    # A zero standard error is not a missing signal, it is a perfect one: every
    # discriminating pick pointed the same way by the same margin. Requiring stderr > 0
    # here rejected exactly the cases with nothing left to doubt.
    label = "unclassified"
    if len(divergent) >= MIN_DIVERGENT and edge != 0 and abs(edge) > 1.96 * stderr:
        label = "espn" if edge > 0 else "ppr"

    return SeatVerdict(
        team_id=team_id,
        abbrev=abbrev,
        picks=total,
        ranked_picks=len(all_picks),
        divergent=len(divergent),
        spearman_standard=(
            spearman(order, [p.standard for p in all_picks]) if len(all_picks) > 1 else 0.0
        ),
        spearman_ppr=spearman(order, [p.ppr for p in all_picks]) if len(all_picks) > 1 else 0.0,
        mad_standard=_mean([abs(p.standard - p.overall) for p in all_picks]),
        mad_ppr=_mean([abs(p.ppr - p.overall) for p in all_picks]),
        edge=edge,
        stderr=stderr,
        label=label,
    )


def sign_test(values: list[float]) -> tuple[int, int, float]:
    """(positive, n, two-sided p) that the signs are a fair coin.

    Seven managers with a dozen discriminating picks each will rarely resolve individually,
    but *every seat leaning the same way* is itself evidence about the room. This is the
    test for that, and it is the level the verdict is stated at -- deliberately, because it
    is the level the data supports.
    """
    nonzero = [v for v in values if v != 0]
    n = len(nonzero)
    if n == 0:
        return 0, 0, 1.0
    positive = sum(1 for v in nonzero if v > 0)
    extreme = max(positive, n - positive)
    tail = sum(math.comb(n, k) for k in range(extreme, n + 1)) / (2**n)
    return positive, n, min(1.0, 2 * tail)


@dataclass(frozen=True, slots=True)
class AnchoringReport:
    seasons: tuple[int, ...]
    excluded_seasons: tuple[int, ...]
    seats: list[SeatVerdict]
    per_season: list[SeatSeason]
    unranked_picks: int  # picks whose player was on neither board -- coverage, not a gap
    total_picks: int

    @property
    def coverage(self) -> float:
        return (
            (self.total_picks - self.unranked_picks) / self.total_picks
            if self.total_picks
            else 0.0
        )

    def exploitable(self) -> list[SeatVerdict]:
        return [s for s in self.seats if s.exploitable]

    def room_lean(self) -> tuple[int, int, float]:
        """How many seats lean toward ESPN's board, out of how many, and the sign-test p."""
        return sign_test([s.edge for s in self.seats])


def build_report(
    adapter: Any, config: Any, *, seasons: tuple[int, ...] = RANKED_SEASONS, me: int | None = None
) -> AnchoringReport:
    """Pull the completed drafts and served ranks, and classify every seat but mine."""
    data: dict[int, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
    abbrevs: dict[int, str] = {}
    unranked = 0
    total = 0

    for season in seasons:
        picks = adapter.get_season_draft(config, season)
        ranks = adapter.get_season_ranks(config, season)
        if not ranks:
            # An empty rank board is the documented 2021-22 shape. Including the season
            # would silently compare picks against nothing.
            continue
        data[season] = (picks, ranks)
        abbrevs.update(adapter.get_season_teams(config, season))
        total += len(picks)
        for p in picks:
            entry = ranks.get(str(p["player_id"]))
            if (
                entry is None
                or entry.get("standard") is None
                or entry.get("ppr") is None
                or float(entry["standard"]) > RANK_HORIZON
                or float(entry["ppr"]) > RANK_HORIZON
            ):
                unranked += 1

    team_ids = sorted({p["team_id"] for picks, _ in data.values() for p in picks})
    seats = [
        seat_verdict(team_id, abbrevs.get(team_id, str(team_id)), data)
        for team_id in team_ids
        if me is None or team_id != me
    ]
    per_season = [
        seat_season(season, team_id, picks, ranks)
        for season, (picks, ranks) in sorted(data.items())
        for team_id in sorted({p["team_id"] for p in picks})
        if me is None or team_id != me
    ]
    return AnchoringReport(
        seasons=tuple(sorted(data)),
        excluded_seasons=tuple(s for s in seasons if s not in data),
        seats=sorted(seats, key=lambda s: -s.edge),
        per_season=per_season,
        unranked_picks=unranked,
        total_picks=total,
    )
