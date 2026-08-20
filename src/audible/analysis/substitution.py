"""C3 -- would drafting off this machinery have beaten the alternatives, in past seasons?

The question C1/C2 could not answer. C1 measured who drafts well; C2 measured whether that
predicts finishing. Neither asks whether *this tool* would have helped. C3 replays each
completed draft and substitutes a different decision rule into one seat -- mine -- leaving
every other seat's behaviour where it was.

WHAT IS COMPARED, per season
----------------------------

``actual``      what the seat really drafted. The thing to beat.
``market``      ESPN's STANDARD rank as ESPN served it that season -- the ADP-naive line and
                the honest control, because B1 established that all seven opposing seats
                read this board.
``baseline``    a projection built from season N-1 actuals only, ranked by raw points.
``machinery``   the same N-1 baseline run through this league's VORP engine -- replacement
                levels derived from the league's own slot structure.
``hindsight``   the same VORP engine run over *realized* season-N points -- the machinery
                with projection error removed.

``hindsight`` is deliberately not "take the highest scorer left". That line is worse than
it sounds and, measured, worse than the machinery: greedy-by-points spends early picks on
whoever scored most in the abstract and ends up with a roster whose best legal lineup is
mediocre. Running the perfect projection through the *same* engine is the comparison that
means something, because ``hindsight - machinery`` is then the cost of being wrong about
the players and nothing else. It is not a proven optimum -- a greedy static order never
is -- so it is never described as a ceiling.

WHY A HANDICAPPED PROJECTION, AND WHAT A RESULT MEANS
-----------------------------------------------------

The real board takes its projections from Sleeper's season-N endpoint, which serves a
*current* projection state for a past season. Nothing about that endpoint establishes the
values are as they stood before the draft, so a board built from it would leak the answer
into the question. ``regressed_ppg_baseline`` over N-1 actuals cannot leak -- it is
assertable in code that no season-N data enters season N's line.

That makes this gate asymmetric, and the asymmetry is the point:

* ``machinery`` beats ``market``  ->  a **lower bound** on the real board's edge. The
  machinery cleared the market while carrying a deliberately dumb projection.
* ``machinery`` loses to ``market``  ->  **uninformative**. The handicap and the machinery
  are confounded: a worse projection ranked by a better method can lose for either reason,
  and this design cannot separate them. It is not a null result and must not be read as one.

``baseline`` exists to split that further. ``machinery`` minus ``baseline`` is the VORP
layer's contribution with the projection held identical, which *is* separable.

MODELLING CHOICES, STATED
-------------------------

* **Opponents do not react.** Each opposing seat takes the player it really took if he is
  still there, and otherwise the best available on ESPN's board -- which is what B1 says
  this room does. A real room would respond to a different pick in front of it; this one
  cannot. The effect is small at one substituted seat and is not zero.
* **The candidate pool is the players actually drafted that season.** A line cannot reach
  for someone the room left on the wire: nobody knows what the undrafted would have scored
  in this league's lineup, and a free option is worth more than a measured one.
* **A drafted player with no realized total is never voluntarily selectable** and is never
  scored, exactly as C1 counts-but-never-zeroes him. He stays in the pool because an
  opponent really did take him and the pick really did happen. The count is reported.
* **Rosters must stay legal.** A pick is allowed only if the remaining picks can still fill
  every starting slot. That is derived from ``config.starting_slots`` and slot eligibility,
  not from a positional cap anyone chose, and it is what stops a static ranking from
  drafting nine quarterbacks.
* **The two sides are in different currencies, and it handicaps us further.** Realized
  points come from ESPN's own applied totals under *that season's* settings, which for
  2023-25 was STANDARD -- zero PPR. The baseline is scored through ``LeagueConfig``, which
  is half-PPR for WR/TE. So the baseline over-rates receivers relative to what the season
  actually paid, in exactly the place B-next showed our board departs from ESPN's. The
  direction is knowable and it runs one way: it makes ``machinery`` worse, never better. A
  win is therefore an even stronger lower bound, and a loss is even less informative. It is
  not corrected because per-season ESPN scoring tables are not fetched anywhere in this repo
  and inventing them would be a larger claim than the one being tested.
* **Scoring is best-ball on season totals**: the optimal legal starting lineup out of the
  drafted roster, by realized points, through the same ``assign_starters`` the value engine
  uses. Identical for every line, so the comparison is fair even though no real season is
  played that way. It ignores waivers, trades and weekly start/sit -- it measures the
  draft, not the season.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Any, Protocol

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection
from ..value.replacement import assign_starters, compute_vorp

# ESPN serves per-season draft ranks for these and not for 2021-22 (400 players, zero
# ranks). Without the market line there is no control to compare against, so a season
# without ranks is not a thin season here -- it is a season this gate cannot run.
ADP_COMPARABLE_SEASONS: tuple[int, ...] = (2023, 2024, 2025)

LINES: tuple[str, ...] = ("actual", "market", "baseline", "machinery", "hindsight")

# A line never voluntarily reaches for a player nobody can score.
UNSELECTABLE = float("-inf")


class BaselineSource(Protocol):
    """``season -> {board_player_id: projected_points}``, built from season-1 actuals.

    A callable rather than an adapter so the ESPN half of this module stays testable with
    no Sleeper anywhere near it.
    """

    def __call__(self, season: int) -> dict[str, float]: ...


class IdBridge(Protocol):
    def to_board_id(self, espn_player_id: int | str) -> str: ...


@dataclass(frozen=True, slots=True)
class Candidate:
    espn_id: str
    position: str | None
    realized: float | None
    market_rank: float | None
    baseline_points: float | None
    machinery_vorp: float | None
    hindsight_vorp: float | None


@dataclass(frozen=True, slots=True)
class SeasonResult:
    season: int
    my_team_id: int
    picks: int
    my_picks: int
    pool: int
    unscored: int  # drafted players ESPN has no realized total for
    unbridged: int  # ESPN ids the Sleeper catalog cannot translate
    no_baseline: int  # bridged players the N-1 baseline has no line for
    points: dict[str, float]  # line -> best-ball realized points
    roster: dict[str, tuple[str, ...]]  # line -> espn ids drafted, in pick order

    def delta(self, line: str, against: str = "market") -> float:
        return self.points[line] - self.points[against]


@dataclass(frozen=True, slots=True)
class SubstitutionReport:
    seasons: tuple[int, ...]
    results: list[SeasonResult]
    skipped: dict[int, str]

    @property
    def coverage(self) -> float:
        pool = sum(r.pool for r in self.results)
        missing = sum(r.unscored for r in self.results)
        return (pool - missing) / pool if pool else 0.0

    def season_level(self, line: str, against: str = "market") -> tuple[float, float, int]:
        """(mean delta, 95% half-width, seasons), one observation per SEASON.

        The same discipline C2 arrived at the hard way. A per-pick or per-player unit would
        look far better powered than it is: within a season the picks are one draft's worth
        of evidence, not 128 independent ones. Three seasons is what exists.
        """
        deltas = [r.delta(line, against) for r in self.results]
        n = len(deltas)
        if n < 2:
            return (deltas[0] if deltas else 0.0, 0.0, n)
        mean = statistics.fmean(deltas)
        stderr = statistics.stdev(deltas) / (n**0.5)
        critical = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57}.get(n, 2.45)
        return (mean, critical * stderr, n)

    def verdict(self) -> str:
        """The asymmetric reading, spelled out. See the module docstring."""
        if not self.results:
            return "NO SEASONS RAN -- nothing is established either way."
        mean, half, n = self.season_level("machinery", "market")
        if mean > 0 and mean - half > 0:
            return (
                f"LOWER BOUND. machinery beat the ADP-naive line by {mean:+.1f} pts/season "
                f"[{mean - half:+.1f}, {mean + half:+.1f}] over n={n}. The projection "
                "carried was deliberately handicapped, so the real board's edge is at "
                "least this and the interval does not cross zero."
            )
        if mean > 0:
            return (
                f"POSITIVE BUT UNRESOLVED. machinery beat the ADP-naive line by "
                f"{mean:+.1f} pts/season, but the interval [{mean - half:+.1f}, "
                f"{mean + half:+.1f}] crosses zero at n={n}. Consistent with a real edge "
                "and consistent with none."
            )
        return (
            f"UNINFORMATIVE, NOT A NULL. machinery came in {mean:+.1f} pts/season against "
            "the ADP-naive line. The handicap and the machinery are confounded by design: "
            "a deliberately dumb projection ranked by a good method can lose for either "
            "reason, and nothing here separates them. Read the machinery-vs-baseline "
            "column instead -- that comparison holds the projection fixed."
        )


# ── roster legality ───────────────────────────────────────────────────────────


def _one_team(config: LeagueConfig) -> LeagueConfig:
    """The league's own lineup, for exactly one team. Reuses the value engine's slot
    assignment rather than re-deriving eligibility here."""
    return config.model_copy(update={"num_teams": 1})


def _as_projection(espn_id: str, position: str, points: float) -> PlayerProjection:
    return PlayerProjection(
        player_id=espn_id,
        name=espn_id,
        primary_position=position,
        eligible_positions=frozenset({position}),
        team=None,
        points=points,
    )


def _filled_slots(positions: list[str], solo: LeagueConfig) -> int:
    """How many starting slots this set of positions can cover at once."""
    if not positions:
        return 0
    roster = [_as_projection(f"x{i}", pos, 1.0) for i, pos in enumerate(positions)]
    return len(assign_starters(roster, solo))


def _best_ball(roster: list[tuple[str, str, float]], solo: LeagueConfig) -> float:
    """Realized points of the optimal legal starting lineup from a drafted roster."""
    projections = [_as_projection(pid, pos, pts) for pid, pos, pts in roster]
    starters = assign_starters(projections, solo)
    return sum(p.points for p in projections if p.player_id in starters)


# ── the replay ────────────────────────────────────────────────────────────────


def _priority(cand: Candidate, line: str) -> float:
    if line == "market":
        # A player ESPN declined to rank is not a candidate the market would reach for.
        return -cand.market_rank if cand.market_rank is not None else UNSELECTABLE
    if line == "baseline":
        return cand.baseline_points if cand.baseline_points is not None else UNSELECTABLE
    if line == "machinery":
        return cand.machinery_vorp if cand.machinery_vorp is not None else UNSELECTABLE
    if line == "hindsight":
        # VORP over realized points, not the realized points themselves -- see the module
        # docstring. A line that cannot be scored is never reached for either way.
        if cand.realized is None:
            return UNSELECTABLE
        return cand.hindsight_vorp if cand.hindsight_vorp is not None else UNSELECTABLE
    raise ValueError(f"no priority defined for line {line!r}")


def replay(
    picks: list[dict[str, Any]],
    pool: dict[str, Candidate],
    my_team_id: int,
    line: str,
    config: LeagueConfig,
) -> list[str]:
    """Re-run a completed draft with one seat's decision rule replaced.

    Returns my resulting roster as ESPN ids in pick order. ``line="actual"`` returns the
    picks as they really happened, which is what makes the control exactly comparable --
    same function, same scoring, no separate path to disagree with.
    """
    solo = _one_team(config)
    total_slots = len(config.starting_slots)

    my_pick_numbers = [p["overall"] for p in picks if p["team_id"] == my_team_id]
    remaining = {overall: len(my_pick_numbers) - i for i, overall in enumerate(my_pick_numbers)}

    taken: set[str] = set()
    mine: list[str] = []
    my_positions: list[str] = []
    # Each opposing seat's own future picks, so a seat whose player I took falls through to
    # the next player it actually wanted before it falls back to the room's board.
    future: dict[int, list[str]] = {}
    for pick in picks:
        future.setdefault(pick["team_id"], []).append(str(pick["player_id"]))

    for pick in picks:
        team_id = pick["team_id"]
        actual = str(pick["player_id"])

        if team_id != my_team_id or line == "actual":
            chosen = actual
            if chosen in taken:
                chosen = _opponent_fallback(future[team_id], taken, pool)
            if chosen is None:
                continue
            taken.add(chosen)
            if team_id == my_team_id:
                mine.append(chosen)
                cand = pool.get(chosen)
                if cand and cand.position:
                    my_positions.append(cand.position)
            continue

        left = remaining[pick["overall"]] - 1  # picks I have AFTER this one
        chosen = _my_pick(pool, taken, line, my_positions, left, total_slots, solo)
        if chosen is None:
            continue
        taken.add(chosen)
        mine.append(chosen)
        cand = pool[chosen]
        if cand.position:
            my_positions.append(cand.position)

    return mine


def _opponent_fallback(
    their_picks: list[str], taken: set[str], pool: dict[str, Candidate]
) -> str | None:
    """The player they took is gone. Take their next real pick, else the room's board.

    B1 is what licenses the second half: all seven opposing seats read ESPN's ordering, so
    "best available on ESPN's board" is this room's behaviour rather than a convenient
    assumption.
    """
    for pid in their_picks:
        if pid not in taken:
            return pid
    ranked = [
        (cand.market_rank, pid)
        for pid, cand in pool.items()
        if pid not in taken and cand.market_rank is not None
    ]
    if ranked:
        return min(ranked)[1]
    left = sorted(pid for pid in pool if pid not in taken)
    return left[0] if left else None


def _my_pick(
    pool: dict[str, Candidate],
    taken: set[str],
    line: str,
    my_positions: list[str],
    picks_left_after: int,
    total_slots: int,
    solo: LeagueConfig,
) -> str | None:
    """Best available on this line that keeps a legal roster reachable."""
    ordered = sorted(
        (
            (-_priority(cand, line), pid, cand)
            for pid, cand in pool.items()
            if pid not in taken and _priority(cand, line) != UNSELECTABLE
        ),
        key=lambda row: (row[0], row[1]),
    )
    for _, pid, cand in ordered:
        if cand.position is None:
            continue
        after = my_positions + [cand.position]
        unfilled = total_slots - _filled_slots(after, solo)
        if unfilled <= picks_left_after:
            return pid
    # Nothing on this line keeps the roster legal: take whatever does, by the room's board.
    return _opponent_fallback([], taken, pool)


# ── the report ────────────────────────────────────────────────────────────────


def build_report(
    adapter: Any,
    config: LeagueConfig,
    baselines: BaselineSource,
    bridge: IdBridge,
    *,
    seasons: tuple[int, ...] = ADP_COMPARABLE_SEASONS,
    me: str | None = None,
) -> SubstitutionReport:
    """Run the gate over completed seasons.

    ``me`` is an owner GUID. Identity is the GUID and never ``teamId``, for the reason C1
    found: ESPN reuses team ids across seasons and a seat is a person, not a slot.
    """
    owner = me if me is not None else getattr(adapter, "swid", None)
    results: list[SeasonResult] = []
    skipped: dict[int, str] = {}

    for season in seasons:
        picks = adapter.get_season_draft(config, season)
        ranks = adapter.get_season_ranks(config, season)
        actuals = adapter.get_season_actuals(config, season)
        standings = adapter.get_season_standings(config, season)
        if not picks:
            skipped[season] = "no draft"
            continue
        if not ranks:
            # The control line is what makes every other line interpretable.
            skipped[season] = "ESPN served no draft ranks -- the ADP-naive control cannot"
            continue
        if not actuals:
            skipped[season] = "no realized totals"
            continue

        my_team_id = _resolve_seat(standings, owner)
        if my_team_id is None:
            skipped[season] = "could not resolve my seat from the owner GUID"
            continue

        baseline = baselines(season)
        pool, stats = _build_pool(picks, ranks, actuals, baseline, bridge, config)
        if not pool:
            skipped[season] = "empty candidate pool"
            continue

        points: dict[str, float] = {}
        rosters: dict[str, tuple[str, ...]] = {}
        solo = _one_team(config)
        for line in LINES:
            roster_ids = replay(picks, pool, my_team_id, line, config)
            rosters[line] = tuple(roster_ids)
            scored = [
                (pid, pool[pid].position or "", pool[pid].realized or 0.0)
                for pid in roster_ids
                if pid in pool and pool[pid].realized is not None and pool[pid].position
            ]
            points[line] = _best_ball(scored, solo)

        results.append(
            SeasonResult(
                season=season,
                my_team_id=my_team_id,
                picks=len(picks),
                my_picks=sum(1 for p in picks if p["team_id"] == my_team_id),
                pool=len(pool),
                unscored=stats["unscored"],
                unbridged=stats["unbridged"],
                no_baseline=stats["no_baseline"],
                points=points,
                roster=rosters,
            )
        )

    return SubstitutionReport(seasons=seasons, results=results, skipped=skipped)


def _resolve_seat(standings: list[dict[str, Any]], owner: str | None) -> int | None:
    if not owner:
        return None
    want = str(owner).strip().upper()
    for row in standings:
        if str(row.get("owner") or "").strip().upper() == want:
            return int(row["team_id"])
    return None


def _build_pool(
    picks: list[dict[str, Any]],
    ranks: dict[str, dict[str, Any]],
    actuals: dict[str, float],
    baseline: dict[str, float],
    bridge: IdBridge,
    config: LeagueConfig,
) -> tuple[dict[str, Candidate], dict[str, int]]:
    """Every drafted player, carrying each line's view of him.

    The machinery line's VORP is computed over this pool through the league's own
    replacement levels -- so it is the league's arithmetic, not a global ranking sliced.
    """
    stats = {"unscored": 0, "unbridged": 0, "no_baseline": 0}
    rows: dict[str, Candidate] = {}
    projections: list[PlayerProjection] = []
    realized_rows: list[PlayerProjection] = []

    for pick in picks:
        espn_id = str(pick["player_id"])
        if espn_id in rows:
            continue
        meta = ranks.get(espn_id) or {}
        position = meta.get("position")
        realized = actuals.get(espn_id)
        if realized is None:
            stats["unscored"] += 1
        elif position:
            realized_rows.append(_as_projection(espn_id, position, realized))

        board_id = bridge.to_board_id(espn_id)
        if board_id == espn_id:
            stats["unbridged"] += 1
        points = baseline.get(board_id)
        if points is None:
            stats["no_baseline"] += 1
        elif position:
            projections.append(_as_projection(espn_id, position, points))

        rows[espn_id] = Candidate(
            espn_id=espn_id,
            position=position,
            realized=realized,
            market_rank=meta.get("standard"),
            baseline_points=points,
            machinery_vorp=None,
            hindsight_vorp=None,
        )

    # Both VORP lines are computed over THIS pool through the league's own replacement
    # levels -- the league's arithmetic on the players who were actually drafted, not a
    # global ranking sliced down to them.
    for field, rows_in in (("machinery_vorp", projections), ("hindsight_vorp", realized_rows)):
        if not rows_in:
            continue
        entries, _ = compute_vorp(rows_in, config)
        for entry in entries:
            pid = entry.projection.player_id
            rows[pid] = replace(rows[pid], **{field: entry.vorp})

    return rows, stats
