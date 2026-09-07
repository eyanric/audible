"""TASK B2/4 -- weekly actuals, optimal lineups, and the bootstrap.

The outcome measure for every arm is POINTS-FOR UNDER WEEKLY OPTIMAL LINEUPS. Not simulated
wins: a head-to-head record adds schedule variance that has nothing to do with drafting, and
spending statistical power on it is spending it on noise.

Three things live here, in the order the harness uses them.

1. SCORING. `weekly_points` scores every regular-season player-week from the pinned nflverse
   frames under league 6012's historical rulebook. It reuses `sim/roundtrip.py`'s mapping
   rather than restating it -- that mapping is validated at 99.2 to 100.0 percent exact
   reproduction against ESPN's own season totals for 2021-2025, and a second copy of it would
   be a second thing to keep right.

2. LINEUPS. `optimal_week` fills the nine starting slots to maximise that week's points. It is
   an exact max-weight bipartite matching, not the greedy placement `draft/live.py` uses --
   see `optimal_week` for why both exist and which one is checked against which.

3. THE BOOTSTRAP. `bootstrap_weeks` resamples a player's own weeks, with replacement, to make
   many plausible seasons out of one real one.


WHAT THE BOOTSTRAP MULTIPLIES, AND WHAT IT DOES NOT
---------------------------------------------------
It multiplies OUTCOME samples. It does not multiply MARKET samples.

Five ADP vintages and five real rooms remain five, however many bootstrap draws are taken on
top of them. A thousand draws from 2023 are a thousand views of ONE market, one board and one
opponent field. So the bootstrap buys precision on "given this draft, how did it turn out",
and buys nothing at all on "would this ordering have drafted well in a different year".

That distinction is why B3's walk-forward split is reported separately, and why an effect
small enough to need the bootstrap to detect is exactly the effect forty market-seat
combinations cannot generalise.


TWO POSITIONS CANNOT BE SCORED, AND IT IS STRUCTURAL
-----------------------------------------------------
They score zero, but for two DIFFERENT reasons and only one of them is an absence.

D/ST: `player_stats_<season>` carries no team-defence rows at all. Measured, zero in all five
seasons. There is nothing to score.

K: kickers DO have rows -- 568 to 570 a season -- and they are scored, to exactly 0.0, because
`roundtrip.COLUMN_TO_KEY` carries no kicking columns. Summed over every kicker row in a season
the total is 0.0 for 2021-2024 and 0.6 for 2025. (An earlier version of this docstring said the
pinned frames do not carry kickers. They do; the scoring vocabulary does not reach them.)

So both starting slots score zero. The K slot is FILLED in the matching by a zero-scoring
kicker, the D/ST slot is left empty; either way the lineup yields 7 scoring slots of 9, which
every artifact reports as `slots_scored`. The effect is COMMON-MODE across arms -- every arm
drafts one kicker and one defence, because the room's schedule and deadline make it -- so a
PAIRED comparison is unaffected. Two arms drafting different kickers is worth 0.6 points a
season at the very most. The absolute points-for number understates a real league's by roughly
a kicker and a defence a week, and only the DIFFERENCES between arms are meant to be read.


BYE WEEKS, AND WHY THEY ARE NOT LEAKAGE
----------------------------------------
`byes_from_schedule` reads which regular-season week a team did not play. That is SCHEDULE
information, published in May, months before a September draft -- it is not an outcome, and a
real drafter had it.

The file it is read from also contains outcomes, so the extraction is restricted to four
columns -- `season`, `week`, `team`, `game_id` -- and `test_g_runner.py` asserts that narrowing
the frame to those four changes nothing, which really would fail if a stat column were reached
for.

`SeasonWeekly.provenance` records `player_stats_<season>` and `nfl_schedule_<season>`. NEITHER
IS ON `room.PRE_DRAFT_SOURCES` AND NEITHER SHOULD BE: this table is an outcome table and it
must never reach a `SeasonBoard`. An earlier version of this paragraph claimed
`nfl_schedule_<season>` was on the allowlist "for exactly this reason", which was false in both
halves -- it is not on it, and if it were, the `player_stats_<season>` entry beside it would
still be refused. The guard that matters is structural: `build_seat` has no parameter through
which a weekly table could arrive, and `run_arm` scores only what `simulate_draft` returned.

Everything else in this module is post-draft by construction and is only ever consulted AFTER
a draft is complete. Nothing here reaches a board or a bot.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import room
from .adp_join import normalize
from .roundtrip import (
    COLUMN_TO_KEY,
    FUMBLE_RECOVERY_TD_POINTS,
    HISTORICAL_DELTAS,
    LEAGUE_KEY,
    RETURN_TD_POINTS,
    RETURN_YARD_POINTS,
    bucket25,
)

# The four columns `byes_from_schedule` is allowed to read. Everything else in the frame is an
# outcome, and the gate that checks this is the reason the list is a constant rather than a
# comprehension over whatever happens to be there.
SCHEDULE_COLUMNS: tuple[str, ...] = ("season", "week", "team", "game_id")

# Positions that score zero. D/ST has no rows at all; K has rows that score 0.0 because the
# scoring vocabulary carries no kicking columns. See the module docstring for which is which.
UNSCOREABLE: frozenset[str] = frozenset({"K", "DEF"})

REG_WEEKS: tuple[int, ...] = tuple(range(1, 19))


def league_config() -> Any:
    """League 6012's config, with the historical scoring deltas applied.

    `roundtrip.HISTORICAL_DELTAS` is `{"rec": 0.0}`: 6012 paid nothing per reception in
    2021-2025 and the committed TOML's 0.5 describes 2026. Scoring five historical seasons
    under the 2026 table inflates every receiver -- Ja'Marr Chase's 2024 by 63.5 points, which
    is half of his 127 catches.
    """
    from pathlib import Path

    from audible.config import load_league

    repo = Path(__file__).resolve().parents[1]
    return load_league(repo / "leagues" / f"{LEAGUE_KEY}.toml")


@dataclass(frozen=True, slots=True)
class SeasonWeekly:
    """One season's scored weeks, plus the identity a roster is joined through."""

    season: int
    points: dict[str, dict[int, float]]  # gsis_id -> week -> points
    position: dict[str, str]  # gsis_id -> position
    team: dict[str, str]  # gsis_id -> team, last seen
    byes: dict[str, int]  # team -> bye week
    by_name: dict[str, list[str]]  # normalised name -> gsis ids
    provenance: tuple[str, ...]

    def weeks_for(self, player: str) -> list[int]:
        return sorted(self.points.get(player, {}))


def _frame(season: int) -> Any:
    import polars as pl

    path, _root = room.resolve_input(f"nflverse/player_stats_{season}.parquet")
    return pl.read_parquet(path)


def byes_from_schedule(frame: Any) -> dict[str, int]:
    """team -> the regular-season week it did not play, from schedule columns only.

    Reads `SCHEDULE_COLUMNS` and nothing else. A team with anything other than exactly one
    missing regular-season week is omitted rather than guessed at -- 2022's BUF and CIN each
    have two, because their week-17 game was abandoned and never replayed.
    """
    import polars as pl

    reg = frame.select(SCHEDULE_COLUMNS).filter(pl.col("week").is_in(REG_WEEKS))
    played: dict[str, set[int]] = {}
    for _season, week, team, _game in reg.unique().iter_rows():
        if team is None or week is None:
            continue
        played.setdefault(str(team), set()).add(int(week))
    out: dict[str, int] = {}
    for team, weeks in played.items():
        missing = [w for w in REG_WEEKS if w not in weeks]
        if len(missing) == 1:
            out[team] = missing[0]
    return out


def weekly_points(season: int) -> SeasonWeekly:
    """Every regular-season player-week, scored under 6012's historical rulebook.

    Regular season only. The pinned frames carry weeks 19-22 and scoring them would hand
    every playoff participant three or four extra games.
    """
    import polars as pl

    from audible.scoring.engine import score_stat_line

    config = league_config()
    frame = _frame(season)
    byes = byes_from_schedule(frame)
    reg = frame.filter(pl.col("season_type") == "REG").fill_null(0)

    points: dict[str, dict[int, float]] = {}
    position: dict[str, str] = {}
    team: dict[str, str] = {}
    by_name: dict[str, list[str]] = {}
    weights_cache: dict[str, dict[str, float]] = {}

    for row in reg.iter_rows(named=True):
        pos = room.canon_position(str(row.get("position") or ""))
        weights = weights_cache.get(pos)
        if weights is None:
            weights = {**config.scoring_for(pos), **HISTORICAL_DELTAS}
            weights_cache[pos] = weights

        stats = {key: float(row.get(col) or 0.0) for col, key in COLUMN_TO_KEY.items()}
        stats["pass_yd"] = bucket25(float(row.get("passing_yards") or 0.0))
        pts = score_stat_line(stats, weights)
        pts += RETURN_YARD_POINTS * (
            bucket25(float(row.get("punt_return_yards") or 0.0))
            + bucket25(float(row.get("kickoff_return_yards") or 0.0))
        )
        pts += RETURN_TD_POINTS * float(row.get("special_teams_tds") or 0.0)
        pts += FUMBLE_RECOVERY_TD_POINTS * float(row.get("fumble_recovery_tds") or 0.0)

        pid = str(row["player_id"])
        week = int(row["week"])
        points.setdefault(pid, {})[week] = points.get(pid, {}).get(week, 0.0) + pts
        position[pid] = pos
        if row.get("team"):
            team[pid] = str(row["team"])
        name = normalize(str(row.get("player_display_name") or row.get("player_name") or ""))
        if name and pid not in by_name.setdefault(name, []):
            by_name[name].append(pid)

    return SeasonWeekly(
        season=season, points=points, position=position, team=team, byes=byes,
        by_name=by_name, provenance=(f"player_stats_{season}", f"nfl_schedule_{season}"),
    )


# --- the lineup ---------------------------------------------------------------------------


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment of every row to a distinct column. Rows <= columns.

    The standard O(n^2 m) shortest-augmenting-path formulation. Nine rows and at most a couple
    of dozen columns here, so it costs nothing and is exact, which is the point.
    """
    n = len(cost)
    m = len(cost[0]) if n else 0
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    assign = [-1] * n
    for j in range(1, m + 1):
        if p[j] > 0:
            assign[p[j] - 1] = j - 1
    return assign


# Cost charged for putting a player in a slot he cannot fill. Large enough that the matching
# will always prefer leaving a slot empty, small enough to stay well inside float precision.
_ILLEGAL = 1e9


def optimal_week(
    roster: Sequence[tuple[str, str]],
    week_points: Mapping[str, float],
    *,
    slots: Sequence[str] = room.STARTING_SLOTS,
    eligibility: Mapping[str, Sequence[str]] = room.SLOT_ELIGIBILITY,
) -> tuple[float, list[tuple[str, str | None]]]:
    """The best legal lineup for one week. Returns (points, [(slot, player or None)]).

    *roster* is (player_key, position). A player with no entry in *week_points* scores zero,
    which is how a bye and an inactive both look in the pinned data: no row.

    EXACT, not greedy. `draft/live.py::place_into_slots` fills the most specific open slot
    first, sorted by season projection, and for these nested FLEX structures that happens to
    be optimal -- measured, 0 disagreements over 14,400 player-weeks -- but "happens to be" is
    not a thing to build an outcome measure on. `greedy_week` below exists so
    `test_g_runner.py::test_the_exact_lineup_matches_greedy_on_this_config` can keep saying so.
    A max-weight matching is also the only version that stays correct if a league config ever
    grows a SUPER_FLEX or a second overlapping flex, which is exactly when the equivalence
    stops holding.
    """
    n = len(slots)
    padded = list(roster) + [("", "")] * max(0, n - len(roster))
    cost: list[list[float]] = []
    for slot in slots:
        allowed = set(eligibility[slot])
        cost.append(
            [
                -float(week_points.get(key, 0.0)) if pos in allowed else _ILLEGAL
                for key, pos in padded
            ]
        )
    assign = _hungarian(cost)

    total = 0.0
    filled: list[tuple[str, str | None]] = []
    for i, slot in enumerate(slots):
        j = assign[i]
        if j < 0 or cost[i][j] >= _ILLEGAL:
            filled.append((slot, None))
            continue
        key = padded[j][0]
        total += float(week_points.get(key, 0.0))
        filled.append((slot, key))
    return total, filled


def greedy_week(
    roster: Sequence[tuple[str, str]],
    week_points: Mapping[str, float],
    *,
    slots: Sequence[str] = room.STARTING_SLOTS,
    eligibility: Mapping[str, Sequence[str]] = room.SLOT_ELIGIBILITY,
) -> float:
    """The greedy placement, kept only so a gate can check the exact one against it."""
    order = sorted(
        roster, key=lambda rp: -float(week_points.get(rp[0], 0.0))
    )
    open_slots = list(slots)
    total = 0.0
    for key, pos in order:
        best = None
        for slot in open_slots:
            if pos in eligibility[slot] and (
                best is None or len(eligibility[slot]) < len(eligibility[best])
            ):
                best = slot
        if best is not None:
            open_slots.remove(best)
            total += float(week_points.get(key, 0.0))
    return total


# --- the bootstrap -------------------------------------------------------------------------


def bootstrap_weeks(
    rng: random.Random, weekly: SeasonWeekly, players: Sequence[str]
) -> dict[str, list[float]]:
    """One synthetic season: for each player, 18 weeks drawn from HIS OWN observed weeks.

    Within-player resampling with replacement. A week drawn for a player is a different actual
    week of that player's, so identity and position eligibility survive by construction -- the
    thing being resampled is which of his own games he played, never whose game it was.

    A player with no observed weeks gets eighteen zeros -- he took no snap that season, or he
    is a team defence, which the frames do not carry at all. Kickers DO have rows, so they take
    the resampling branch like anyone else and resample a set of zeros.

    TWO THINGS THE DRAW DOES THAT ARE WORTH KNOWING. A player with one observed week has that
    week replayed eighteen times with no shrinkage, and 0.49 players on a typical sixteen-man
    roster are in that position -- combined with an optimal lineup that starts whoever scored
    most, one lucky game can become a season-long starter. And only 16 of 12,800 drafted-player
    slots have all 18 weeks, so every player is handed a bye-free season, inflating totals by
    roughly one seventeenth. Both are common-mode across arms and survive differencing; both
    inflate the between-unit variance that the season-clustered intervals already have to
    absorb.

    What this does NOT model, stated because it bounds every interval computed downstream:
    weeks are drawn independently, so there is no within-season autocorrelation -- a player
    cannot get hurt in week 4 and stay hurt -- and no cross-player correlation at all, so two
    receivers on the same team never share a game script. Both understate the variance of a
    team's weekly total.
    """
    out: dict[str, list[float]] = {}
    for player in players:
        weeks = weekly.points.get(player)
        if not weeks:
            out[player] = [0.0] * len(REG_WEEKS)
            continue
        values = [weeks[w] for w in sorted(weeks)]
        out[player] = [values[int(rng.random() * len(values))] for _ in REG_WEEKS]
    return out


def points_for(
    rng: random.Random,
    weekly: SeasonWeekly,
    roster: Sequence[tuple[str, str]],
) -> float:
    """Points-for over one bootstrapped season, under weekly optimal lineups.

    *roster* is (player_key, position) for the sixteen players a seat drafted. Unresolved
    players -- an off-board pick, a name the crosswalk does not carry -- have no weeks and
    contribute zero, exactly like a kicker.
    """
    draws = bootstrap_weeks(rng, weekly, [key for key, _pos in roster])
    total = 0.0
    for index in range(len(REG_WEEKS)):
        week_points = {key: draws[key][index] for key, _pos in roster}
        total += optimal_week(roster, week_points)[0]
    return total


def resolve_roster(
    picks: Sequence[Any], board: room.SeasonBoard, weekly: SeasonWeekly
) -> tuple[list[tuple[str, str]], int]:
    """Turn a seat's SimPicks into (gsis_id, position) pairs. Returns (roster, unresolved).

    Joins by normalised name against the season's own weekly rows. Where a name carries
    several ids, the one whose position matches the board is taken; a name that stays
    ambiguous is left unresolved rather than guessed at, because attributing one player's
    season to another is a silent error and a zero is a loud one.
    """
    out: list[tuple[str, str]] = []
    unresolved = 0
    for pick in picks:
        if getattr(pick, "offboard", False):
            unresolved += 1
            out.append((f"offboard:{pick.overall}", pick.position))
            continue
        candidates = weekly.by_name.get(normalize(pick.name), [])
        exact = [c for c in candidates if weekly.position.get(c) == pick.position]
        chosen = exact[0] if len(exact) == 1 else (candidates[0] if len(candidates) == 1 else None)
        if chosen is None:
            unresolved += 1
            out.append((f"unresolved:{pick.overall}", pick.position))
            continue
        out.append((chosen, pick.position))
    return out, unresolved
