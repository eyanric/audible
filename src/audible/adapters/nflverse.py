"""nflverse adapter -- the opportunity/NGS data layer (Phase 2 fuel).

Built on ``nflreadpy`` (the maintained successor to the archived ``nfl_data_py``),
which returns polars frames. We convert to plain dicts at this boundary so the rest
of the engine never imports polars. nflreadpy is an optional extra, so importing it
is lazy: install with ``uv sync --extra nflverse``.

The id map (``load_ff_playerids``) is the cross-source spine that joins Sleeper
(``sleeper_id``) <-> ESPN (``espn_id``) <-> nflverse stats (``gsis_id``).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from .cache import FrameCache

log = logging.getLogger("audible.nflverse")

# --- the disk cache -----------------------------------------------------------------------
# Every source below is a third-party URL. On draft night the network is an update mechanism,
# not a dependency: what is on disk is what the board is built from, and fetching is something
# done deliberately ahead of time with `audible refresh-data`. See adapters/cache.py.
#
# This is not a performance optimisation. nflreadpy caches in memory only, so every process
# restart re-downloads every source; when its DynastyProcess URL started 404ing mid-afternoon
# the board stopped building entirely, and repeated restarts earn a 429 from GitHub on top.

_REFRESH = False
# Which keys this process read from disk vs pulled over the network, for /healthz.
_ORIGINS: dict[str, str] = {}


@contextmanager
def refreshing() -> Iterator[None]:
    """Force every loader in this block to go to the network and rewrite its cache."""
    global _REFRESH
    previous = _REFRESH
    _REFRESH = True
    try:
        yield
    finally:
        _REFRESH = previous


def origins() -> dict[str, str]:
    """key -> "disk" | "network" for everything loaded so far in this process."""
    return dict(_ORIGINS)


def cache_summary() -> dict[str, Any]:
    summary = FrameCache().summary()
    summary["origins"] = dict(_ORIGINS)
    summary["from_disk"] = sum(1 for v in _ORIGINS.values() if v == "disk")
    summary["from_network"] = sum(1 for v in _ORIGINS.values() if v == "network")
    return summary


def _key(name: str, *parts: Any) -> str:
    suffix = "_".join(str(p) for p in parts if p is not None)
    return f"{name}_{suffix}" if suffix else name


def _cached(key: str, fetch: Callable[[], Any], *, source: str) -> Any:
    """Disk first, network only when the cache is missing or a refresh was asked for.

    A network failure with a cached copy present is NOT an error: the copy is the answer.
    That is the whole point -- the board must build with the network unplugged.
    """
    cache = FrameCache()
    if not _REFRESH:
        frame = cache.get(key)
        if frame is not None:
            _ORIGINS[key] = "disk"
            return frame

    try:
        frame = fetch()
    except Exception as exc:  # noqa: BLE001 -- fall back to any copy we already hold
        stale = cache.get(key)
        if stale is None:
            raise
        log.warning("could not refresh %s (%s); using the cached copy", key, exc)
        _ORIGINS[key] = "disk"
        return stale

    cache.put(key, frame, source=source)
    _ORIGINS[key] = "network"
    return frame

# --- upstream breakage workaround -------------------------------------------------------
# nflreadpy 0.1.5 hardcodes `https://github.com/dynastyprocess/data/raw/master/files/` for its
# two DynastyProcess sources, and GitHub now answers that path with a 404 HTML page. The
# canonical raw host still serves the same files, so both loaders fall back to it.
#
# Measured 2026-08-17: github.com/.../raw/... -> 404 with a 305 KB error page;
# raw.githubusercontent.com/... -> 200 with the 2.6 MB CSV. 0.1.5 is the latest release, so
# there is nothing to upgrade to. This blocks `build_board` for BOTH leagues -- the crosswalk
# is the first thing it builds -- which is why it is worth working around here rather than
# waiting. Delete this block when upstream fixes the URL; the primary path is tried first, so
# it will start being used again on its own.
_DYNASTYPROCESS_RAW = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/"


def _dynastyprocess_csv(name: str) -> Any:
    import httpx
    import polars as pl

    url = f"{_DYNASTYPROCESS_RAW}{name}.csv"
    resp = httpx.get(url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    # Every column as a string, deliberately. This is an ID spine: `sleeper_id` read as a
    # float turns 4034 into "4034.0" the moment anything stringifies it, and the join then
    # fails silently for every player rather than loudly for none.
    return pl.read_csv(io.BytesIO(resp.content), infer_schema_length=0)


def _ffverse(load: Any, name: str) -> Any:
    """Call an nflreadpy DynastyProcess loader, falling back to the raw host it can't reach."""
    try:
        return load()
    except Exception as exc:  # noqa: BLE001 -- upstream URL is broken; try the canonical host
        log.warning("nflreadpy could not fetch %s (%s); falling back to the raw host", name, exc)
        return _dynastyprocess_csv(name)


def _require_nflreadpy() -> Any:
    try:
        import nflreadpy  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "The nflverse adapter needs the optional dependency. "
            "Install it with: uv sync --extra nflverse"
        ) from exc
    return nflreadpy


def id_map_frame() -> Any:
    """The DynastyProcess id map: sleeper_id / espn_id / gsis_id and more."""
    nfl = _require_nflreadpy()
    return _cached(
        "ff_playerids",
        lambda: _ffverse(nfl.load_ff_playerids, "db_playerids"),
        source="dynastyprocess/db_playerids",
    )


def load_id_map() -> list[dict[str, Any]]:
    return id_map_frame().to_dicts()


def load_weekly_stats(seasons: list[int]) -> list[dict[str, Any]]:
    """Weekly player stats (targets, target_share, air_yards_share, carries, ...)."""
    return player_stats_frame(seasons).to_dicts()


def load_rankings(rank_type: str = "draft") -> list[dict[str, Any]]:
    """FantasyPros consensus rankings (rank_type: 'draft' | 'week' | 'all').

    Current-only (no historical archive), so we snapshot it weekly -- see audible.snapshot.
    """
    nfl = _require_nflreadpy()
    names = {"draft": "db_fpecr_latest", "week": "fp_latest_weekly", "all": "db_fpecr"}
    return _cached(
        _key("ff_rankings", rank_type),
        lambda: _ffverse(
            lambda: nfl.load_ff_rankings(rank_type), names.get(rank_type, "db_fpecr_latest")
        ),
        source=f"dynastyprocess/{names.get(rank_type, rank_type)}",
    ).to_dicts()


def load_snap_counts(seasons: list[int]) -> list[dict[str, Any]]:
    """Per-game snap counts incl. offense_pct / defense_pct (opportunity signal)."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("snap_counts", *seasons),
        lambda: nfl.load_snap_counts(seasons),
        source="nflverse/snap_counts",
    ).to_dicts()


def load_nextgen_stats(seasons: list[int], stat_type: str) -> list[dict[str, Any]]:
    """Next Gen Stats; stat_type in {"passing", "receiving", "rushing"} (week 0 = season agg)."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("nextgen", stat_type, *seasons),
        lambda: nfl.load_nextgen_stats(seasons, stat_type=stat_type),
        source=f"nflverse/nextgen_{stat_type}",
    ).to_dicts()


# --- polars frame accessors (bulk sources aggregated downstream in polars) ---------
# These return the raw polars DataFrame; the draft layer does the heavy aggregation and
# converts to plain types at its boundary, so polars never leaks past the draft modules.


def opportunity_frame(seasons: list[int]) -> Any:
    """ff_opportunity weekly (expected components); join key ``player_id`` == gsis_id."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("ff_opportunity", *seasons),
        lambda: nfl.load_ff_opportunity(seasons, stat_type="weekly"),
        source="nflverse/ff_opportunity",
    )


def draft_picks_frame(seasons: list[int]) -> Any:
    """NFL draft picks (round, pick, position, team, gsis_id, pfr_player_name)."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("draft_picks", *seasons),
        lambda: nfl.load_draft_picks(seasons),
        source="nflverse/draft_picks",
    )


def rosters_frame(seasons: list[int]) -> Any:
    """Season rosters: sleeper_id <-> gsis_id <-> team, plus years_exp / entry_year."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("rosters", *seasons),
        lambda: nfl.load_rosters(seasons),
        source="nflverse/rosters",
    )


def player_stats_frame(seasons: list[int]) -> Any:
    """Weekly player stats (target_share, carries, air_yards_share, ...); keyed by gsis_id."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("player_stats", *seasons),
        lambda: nfl.load_player_stats(seasons, summary_level="week"),
        source="nflverse/player_stats",
    )


def schedules_frame(seasons: list[int]) -> Any:
    """Season schedule -- the bye-week source. A team's bye is the REG week it does not play."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("schedules", *seasons),
        lambda: nfl.load_schedules(seasons),
        source="nflverse/schedules",
    )


def snap_counts_frame(seasons: list[int]) -> Any:
    """Per-game snap counts. Keyed by ``pfr_player_id`` -- join via the crosswalk's pfr_id."""
    nfl = _require_nflreadpy()
    return _cached(
        _key("snap_counts", *seasons),
        lambda: nfl.load_snap_counts(seasons),
        source="nflverse/snap_counts",
    )


# --- derived-and-pinned sources ---------------------------------------------------------
# The two below are cached AFTER aggregation, not before. Raw participation is 45k rows
# carrying an 11-id string per play, and raw depth charts are 472k rows; pinning either
# whole would bloat the disk cache the draft-day launcher has to read before kickoff, for
# columns nothing downstream ever looks at. The aggregation is deterministic, so pinning
# its OUTPUT is the same guarantee at a fraction of the size.


def route_participation_frame(season: int) -> Any:
    """Per-player pass-snap share for one season: the route-participation PROXY.

    True charted routes-run per player are not in nflverse. What is available is, per play,
    the eleven offensive players on the field (``offense_players``) and the route charted on
    that play (``route``, non-empty only where one was run). So this counts the charted-route
    plays a player was on the field for, over his team's charted-route plays.

    That is a proxy and the name says so: a tight end who stays in to block still counts.
    Validated against 2025 -- Jefferson 95.6%, Chase 91.5%, St. Brown 91.5% -- which is the
    right neighbourhood for published route participation, so the proxy tracks the real thing
    closely for the receivers whose usage this league actually pays for.
    """
    nfl = _require_nflreadpy()

    def build() -> Any:
        import polars as pl

        part = nfl.load_participation([season]).with_columns(
            pl.col("route").fill_null("").alias("route")
        )
        routed = part.filter(pl.col("route") != "")
        on_field = (
            routed.select(["possession_team", "offense_players"])
            .with_columns(pl.col("offense_players").str.split(";").alias("gsis_id"))
            .explode("gsis_id")
            .filter((pl.col("gsis_id").is_not_null()) & (pl.col("gsis_id") != ""))
            .group_by(["gsis_id", "possession_team"])
            .agg(pl.len().alias("route_plays"))
        )
        team_plays = routed.group_by("possession_team").agg(pl.len().alias("team_route_plays"))
        return (
            on_field.join(team_plays, on="possession_team")
            .with_columns(
                (pl.col("route_plays") / pl.col("team_route_plays")).alias("route_participation")
            )
            .select(["gsis_id", "possession_team", "route_plays", "team_route_plays",
                     "route_participation"])
        )

    return _cached(
        _key("route_participation", season),
        build,
        source="nflverse/participation(derived)",
    )


def depth_chart_slots_frame(season: int, as_of: str | None = None) -> Any:
    """One row per player: his depth-chart slot and rank as of `as_of` (default: newest).

    `as_of` is an ISO date. It exists because "newest snapshot" means two different things:
    for the CURRENT season the newest chart is the draft-day chart, since nothing later
    exists; for a COMPLETED season it is the week-18 chart. Measured: 2026 spans
    2026-03-22..2026-08-26, while 2025 spans 2025-08-03..2026-03-14.

    So a backtest fold that asked for season Y without a cutoff would be told who FINISHED
    the season as WR1 -- a fact about the outcome it is trying to predict. Any arm reading a
    past season must pass the draft date.
    """
    nfl = _require_nflreadpy()

    def build() -> Any:
        import polars as pl

        dc = nfl.load_depth_charts([season]).filter(pl.col("gsis_id").is_not_null())
        if as_of is not None:
            dc = dc.filter(pl.col("dt").cast(pl.Utf8).str.slice(0, 10) <= as_of)
        # `dt` is the snapshot timestamp; the LAST one is the current chart. Ties inside a
        # timestamp are broken by the better (lower) rank, so a player listed twice in a
        # week reads as his best listed slot rather than an arbitrary one.
        return (
            dc.sort(["dt", "pos_rank"], descending=[True, False])
            .unique(subset=["gsis_id"], keep="first")
            .select(["gsis_id", "team", "pos_abb", "pos_name", "pos_slot", "pos_rank"])
        )

    return _cached(
        _key("depth_chart_slots", season, as_of),
        build,
        source="nflverse/depth_charts(derived)",
    )
