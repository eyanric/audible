"""Per-player usage context -- DISPLAYED, never ranked.

DDAFFL pays 0.5 a reception to WR/TE, so targets are the currency of the edge while the
consensus projection prices yards and touchdowns. These are the volume-and-role numbers
behind that gap, surfaced next to a player so the disagreement is visible at the pick.

WHAT THIS IS NOT. Nothing here enters the sort. This module is imported by the state
builder and the MCP surface, never by `board.py`, `value/` or `scoring/` -- the board is
built, ranked and frozen before any of this is looked up, and the lookup is keyed by the
board's own player id. A missing usage row moves a player on the board by exactly nothing,
which is the property `qa_board_invariants` asserts rather than assumes.

SEASONS. Usage is PRIOR-season (2025) observed volume; the depth-chart slot and the bye
week are CURRENT-season (2026), because those are the only ones you can act on.

DEGRADATION. Every source is read through the nflverse disk cache, and each is wrapped so a
failure costs one field rather than the board. `missing_sources` records what could not be
read, so the cockpit can say a number is absent instead of implying it is zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class UsageContext:
    """One player's displayed usage. Every field is optional -- absence is not zero."""

    target_share: float | None = None          # mean weekly share of team targets, prior season
    air_yards_share: float | None = None       # mean weekly share of team air yards, prior season
    route_participation: float | None = None   # PROXY: pass-snap share (see the adapter)
    snap_share: float | None = None            # mean offensive snap %, prior season
    depth_slot: str | None = None              # e.g. "WR2", from the current depth chart


@dataclass(frozen=True, slots=True)
class UsageTable:
    by_player_id: dict[str, UsageContext] = field(default_factory=dict)
    # Bye joins on TEAM, not on a player id. That is deliberate: a team defence has no gsis
    # id and never appears in the crosswalk, so a player-keyed bye would silently leave every
    # D/ST blank -- and a D/ST bye is exactly the one you cannot stream around.
    bye_by_team: dict[str, int] = field(default_factory=dict)
    missing_sources: tuple[str, ...] = ()

    def get(self, player_id: str) -> UsageContext | None:
        return self.by_player_id.get(str(player_id))

    def bye(self, team: str | None) -> int | None:
        return self.bye_by_team.get(str(team)) if team else None


def _safe(name: str, fn, missing: list[str]):
    """Run one source; on failure record it and return None rather than killing the board."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 -- a missing usage table must never block a draft
        missing.append(name)
        return None


# nflverse schedules and Sleeper do not spell every franchise the same way. MEASURED against
# the 2026 schedule, exactly one differs: the Rams are "LA" upstream and "LAR" on the board,
# and the cost of missing it is a silently blank bye on a team whose WR1 goes in round one.
#
# Only measured differences belong here. A first pass at this mapped the plausible-looking
# historical aliases too and mapped WAS -> WSH, which broke Washington -- both sides already
# said "WAS". `qa_board_invariants` now asserts every board team resolves to a bye, so a
# wrong entry here fails a check rather than blanking a column on a Sunday.
_TEAM_ALIASES = {"LA": "LAR"}


def _bye_weeks(sch, pl) -> dict[str, int]:
    """Team -> its single regular-season bye: the REG week the team does not appear in."""
    reg = sch.filter(pl.col("game_type") == "REG") if "game_type" in sch.columns else sch
    weeks = sorted({int(w) for w in reg["week"].to_list() if w is not None})
    playing = {
        w: set(reg.filter(pl.col("week") == w)["home_team"].to_list())
        | set(reg.filter(pl.col("week") == w)["away_team"].to_list())
        for w in weeks
    }
    teams = set(reg["home_team"].to_list()) | set(reg["away_team"].to_list())
    out: dict[str, int] = {}
    for t in teams:
        off = [w for w in weeks if t not in playing[w]]
        # Exactly one, or none reported. Two would mean the schedule is not what we think it
        # is, and guessing which one to show is worse than showing nothing.
        if len(off) == 1:
            code = str(t)
            out[_TEAM_ALIASES.get(code, code)] = off[0]
    return out


def load_usage(prior_season: int = 2025, cur_season: int = 2026) -> UsageTable:
    """Assemble every displayed usage field, keyed by SLEEPER player id (the board's key)."""
    import polars as pl

    from ..adapters.nflverse import (
        depth_chart_slots_frame,
        id_map_frame,
        player_stats_frame,
        route_participation_frame,
        schedules_frame,
        snap_counts_frame,
    )

    missing: list[str] = []

    # Bye first: it joins on team, so it survives a crosswalk failure that kills everything else.
    sch = _safe("schedules", lambda: schedules_frame([cur_season]), missing)
    byes = _bye_weeks(sch, pl) if sch is not None else {}

    # The board keys on Sleeper ids while every nflverse table keys on gsis or pfr, so the
    # crosswalk is the spine -- and the one source with no fallback.
    ids = _safe("ff_playerids", id_map_frame, missing)
    if ids is None:
        return UsageTable({}, byes, tuple(missing))
    ids = ids.select(["sleeper_id", "gsis_id", "pfr_id"]).filter(
        pl.col("sleeper_id").is_not_null()
    )

    acc: dict[str, dict[str, object]] = {}
    by_gsis: dict[str, list[str]] = {}
    by_pfr: dict[str, list[str]] = {}
    for r in ids.iter_rows(named=True):
        sid = str(r["sleeper_id"])
        acc[sid] = {}
        if r["gsis_id"]:
            by_gsis.setdefault(str(r["gsis_id"]), []).append(sid)
        if r["pfr_id"]:
            by_pfr.setdefault(str(r["pfr_id"]), []).append(sid)

    def spread(frame, key_map: dict[str, list[str]], key_col: str, cols: list[str]) -> None:
        for r in frame.iter_rows(named=True):
            for sid in key_map.get(str(r[key_col]), ()):
                for c in cols:
                    val = r.get(c)
                    if val is not None:
                        acc[sid][c] = float(val)

    # -- target share + air-yards share: already in the cached weekly stats ------------------
    # Mean of the weekly shares over the weeks he recorded a line, not total/total: a player
    # who missed six games should read as the share he commanded when he played.
    ps = _safe("player_stats", lambda: player_stats_frame([prior_season]), missing)
    if ps is not None:
        have = [c for c in ("target_share", "air_yards_share") if c in ps.columns]
        if have:
            agg = ps.group_by("player_id").agg(*[pl.col(c).mean().alias(c) for c in have])
            spread(agg, by_gsis, "player_id", have)

    # -- snap share --------------------------------------------------------------------------
    sc = _safe("snap_counts", lambda: snap_counts_frame([prior_season]), missing)
    if sc is not None and "offense_pct" in sc.columns:
        agg = sc.group_by("pfr_player_id").agg(pl.col("offense_pct").mean().alias("snap_share"))
        spread(agg, by_pfr, "pfr_player_id", ["snap_share"])

    # -- route participation (proxy) -----------------------------------------------------------
    rp = _safe("participation", lambda: route_participation_frame(prior_season), missing)
    if rp is not None:
        spread(rp, by_gsis, "gsis_id", ["route_participation"])

    # -- depth-chart slot ------------------------------------------------------------------------
    dc = _safe("depth_charts", lambda: depth_chart_slots_frame(cur_season), missing)
    if dc is not None:
        for r in dc.iter_rows(named=True):
            for sid in by_gsis.get(str(r["gsis_id"]), ()):
                abb, rank = r.get("pos_abb"), r.get("pos_rank")
                if abb and rank is not None:
                    acc[sid]["depth_slot"] = f"{abb}{int(rank)}"

    table = {
        sid: UsageContext(
            target_share=row.get("target_share"),                 # type: ignore[arg-type]
            air_yards_share=row.get("air_yards_share"),           # type: ignore[arg-type]
            route_participation=row.get("route_participation"),   # type: ignore[arg-type]
            snap_share=row.get("snap_share"),                     # type: ignore[arg-type]
            depth_slot=row.get("depth_slot"),                     # type: ignore[arg-type]
        )
        for sid, row in acc.items()
    }
    return UsageTable(table, byes, tuple(missing))
