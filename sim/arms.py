"""S2 -- the four projection corpora, each reduced to one thing: gsis_id -> projected points.

One loader per arm. Every corpus speaks its own id space and its own stat vocabulary; this is
where that ends, so `sim/rank.py` never has to know which source it is scoring.

THE TRAPS, all measured in S1 (`sim/runs/s1-sources.md`) and all enforced here rather than
remembered:

  * The TEAM FIELD IS NOT VINTAGE in either stat-line corpus. ESPN's `proTeamId` and Sleeper's
    `team` are end-of-season or fetch-time -- Sleeper matches the week-1 team for ZERO percent
    of mid-season movers. Neither is read. Nothing in this module returns a team, and the
    ranking metric never needs one.
  * ESPN 2023 is empty and its surviving signals are contaminated. Refused.
  * Sleeper 2019 and 2020 are contaminated. Refused.
  * Sleeper's BLANKED STUBS carry vintage ADP and no projection, and they are the
    season-enders. Dropped, and counted.
  * `leaguedefaults/3` is PPR, not standard. Irrelevant here because the stat LINE is scored
    under the league's own rulebook and `appliedTotal` is never read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import ffa, rank

CACHE = rank.CACHE
ARMS: tuple[str, ...] = ("ffa", "espn", "sleeper", "ecr")

# ESPN's positional ids, offence only. K and DEF are excluded upstream by `rank.SCOREABLE`.
ESPN_POSITION: dict[int, str] = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}


@dataclass(slots=True)
class ArmSeason:
    """One arm's view of one season, already joined to gsis and scored under one rulebook."""

    arm: str
    season: int
    league_key: str
    points: dict[str, float] = field(default_factory=dict)
    position: dict[str, str] = field(default_factory=dict)
    order: list[str] | None = None  # set ONLY by ranks-only arms, which are not rescored
    rows: int = 0
    joined: int = 0
    dropped_stub: int = 0
    dropped_unjoined: int = 0

    @property
    def join_rate(self) -> float:
        return self.joined / self.rows if self.rows else 0.0


def _refuse(arm: str, season: int) -> None:
    allowed = rank.SEASONS_BY_ARM[arm]
    if season not in allowed:
        raise rank.PreflightError(
            f"{arm} {season} is excluded and is not substituted. Allowed: {list(allowed)}. "
            f"See sim/runs/s1-sources.md for why."
        )


# --- ffa ------------------------------------------------------------------------------------


def _ffa(season: int, league_key: str) -> ArmSeason:
    from audible.scoring.engine import score_stat_line

    out = ArmSeason("ffa", season, league_key)
    config = rank.league(league_key)
    xw = rank.crosswalk("mfl_id")
    have = ffa.columns(season)
    seen: set[str] = set()
    for row in ffa.read_raw(season):
        pos = (row.get("position") or "").strip().upper()
        if pos not in rank.SCOREABLE:
            continue
        out.rows += 1
        mfl = (row.get("id") or "").strip()
        gsis = xw.get(mfl)
        if not gsis:
            out.dropped_unjoined += 1
            continue
        # `read_raw` carries duplicate ids -- team variants with identical stats, and
        # dual-position players projected twice. `sim/ffa.py` dedupes first-wins; so does this.
        if gsis in seen:
            continue
        seen.add(gsis)
        stats = ffa._stats_for(row, pos, have)
        if not stats:
            continue
        out.points[gsis] = score_stat_line(stats, config.scoring_for(pos))
        out.position[gsis] = pos
        out.joined += 1
    return out


# --- espn -----------------------------------------------------------------------------------


def _espn(season: int, league_key: str) -> ArmSeason:
    from audible.adapters.espn import translate_stat_line
    from audible.scoring.engine import score_stat_line

    out = ArmSeason("espn", season, league_key)
    config = rank.league(league_key)
    xw = rank.crosswalk("espn_id")
    path = CACHE / "espn_probe" / f"leaguedefaults3_{season}.json"
    if not path.exists():
        raise rank.PreflightError(f"espn pin missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))

    for entry in payload.get("players") or []:
        player = entry.get("player") or {}
        pos = ESPN_POSITION.get(player.get("defaultPositionId"))
        if pos is None:
            continue
        # THE SEASON PROJECTION, and only it: statSourceId 1 with statSplitTypeId 0.
        # split=1 (weekly) and split=2 (per-game) are CONTAMINATED -- they collapse to 0.0 the
        # moment a player is ruled out, so a 2020 Barkley reads 0.0 across weeks 3-17 while the
        # season projection correctly still says 288.6.
        line = None
        for st in player.get("stats") or []:
            if (
                st.get("seasonId") == season
                and st.get("statSourceId") == 1
                and st.get("statSplitTypeId") == 0
            ):
                line = st.get("stats") or {}
                break
        if not line:
            continue
        out.rows += 1
        gsis = xw.get(str(player.get("id")))
        if not gsis:
            out.dropped_unjoined += 1
            continue
        pts = score_stat_line(translate_stat_line(line, pos), config.scoring_for(pos))
        if pts <= 0:
            continue
        out.points[gsis] = pts
        out.position[gsis] = pos
        out.joined += 1
    return out


# --- sleeper --------------------------------------------------------------------------------

SLEEPER_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")


def _sleeper(season: int, league_key: str) -> ArmSeason:
    from audible.scoring.engine import score_stat_line

    out = ArmSeason("sleeper", season, league_key)
    config = rank.league(league_key)
    xw = rank.crosswalk("sleeper_id")

    for pos in SLEEPER_POSITIONS:
        path = CACHE / "sleeper_probe" / f"projections_{season}_{pos}.json"
        if not path.exists():
            raise rank.PreflightError(f"sleeper pin missing: {path}")
        for row in json.loads(path.read_text(encoding="utf-8")):
            stats = row.get("stats") or {}
            out.rows += 1
            # THE BLANKED STUB. A superseded projection keeps its vintage ADP and loses its
            # numbers, leaving `{"gp": 17.0}` and nothing else. Those players are the
            # season-enders -- Nick Chubb at ADP 10.6 in 2023 -- so treating a stub as a real
            # zero would rank exactly the wrong people last. Dropped and counted.
            real = {k: v for k, v in stats.items() if k != "gp"}
            if not real:
                out.dropped_stub += 1
                continue
            gsis = xw.get(str(row.get("player_id")))
            if not gsis:
                out.dropped_unjoined += 1
                continue
            # `pts_*` is NOT read. It is not IDP-scored, and for offence it only reproduces
            # what the stat line already says. Scoring the line keeps one path for every arm.
            pts = score_stat_line(
                {k: float(v) for k, v in real.items() if isinstance(v, int | float)},
                config.scoring_for(pos),
            )
            if pts <= 0:
                continue
            out.points[gsis] = pts
            out.position[gsis] = pos
            out.joined += 1
    return out


# --- ffp_ecr: ranks only, never rescored -----------------------------------------------------


def _ecr(season: int, league_key: str) -> ArmSeason:
    """The published expert-consensus ORDER, taken as-is.

    No stat line exists, so there is nothing to score and nothing to transform. It enters as
    its own ordering and its PPR-vs-standard bias is reported rather than corrected -- S1
    measured that bias as uncorrectable, because the file carries no reception count.
    """
    import polars as pl

    out = ArmSeason("ecr", season, league_key)
    path = CACHE / "dynastyprocess" / "db_fpecr.parquet"
    if not path.exists():
        raise rank.PreflightError(f"ecr pin missing: {path}")
    xw = rank.crosswalk("fantasypros_id")

    frame = pl.read_parquet(path)
    # The redraft cheatsheet, either naming era, excluding dynasty/rookie/best-ball/ROS and
    # the separate superflex and IDP boards.
    cand = frame.filter(
        pl.col("fp_page").str.contains("ppr-cheatsheets")
        & ~pl.col("fp_page").str.contains("superflex|ros-|best-ball|dynasty|rookie")
        & pl.col("scrape_date").str.starts_with(str(season))
        & (pl.col("scrape_date") <= f"{season}-09-08")
    )
    if cand.height == 0:
        raise rank.PreflightError(f"no preseason ECR snapshot for {season}")
    snapshot = cand["scrape_date"].max()
    snap = cand.filter(pl.col("scrape_date") == snapshot).sort("ecr")

    order: list[str] = []
    for row in snap.iter_rows(named=True):
        pos = (row.get("pos") or "").strip().upper()
        pos = {"PK": "K"}.get(pos, pos)
        if pos not in rank.SCOREABLE:
            continue
        out.rows += 1
        gsis = xw.get(str(row.get("id") or "").strip())
        if not gsis or gsis in out.position:
            out.dropped_unjoined += not gsis
            continue
        out.position[gsis] = pos
        order.append(gsis)
        out.joined += 1
    out.order = order
    out.points = {pid: float(-i) for i, pid in enumerate(order)}  # order only; never scored
    return out


LOADERS = {"ffa": _ffa, "espn": _espn, "sleeper": _sleeper, "ecr": _ecr}


def load(arm: str, season: int, league_key: str) -> ArmSeason:
    if arm not in LOADERS:
        raise rank.PreflightError(f"unknown arm {arm!r}; expected one of {list(LOADERS)}")
    _refuse(arm, season)
    return LOADERS[arm](season, league_key)


def board_order(loaded: ArmSeason) -> list[str]:
    """The arm's board, best first.

    Stat-line arms go through the SAME transform the realised side goes through. `ecr` does
    not: it has no points, so it enters as its published order.
    """
    if loaded.order is not None:
        return list(loaded.order)
    return rank.vorp_order(loaded.points, loaded.position, loaded.league_key)
