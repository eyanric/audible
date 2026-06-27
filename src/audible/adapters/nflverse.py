"""nflverse adapter -- the opportunity/NGS data layer (Phase 2 fuel).

Built on ``nflreadpy`` (the maintained successor to the archived ``nfl_data_py``),
which returns polars frames. We convert to plain dicts at this boundary so the rest
of the engine never imports polars. nflreadpy is an optional extra, so importing it
is lazy: install with ``uv sync --extra nflverse``.

The id map (``load_ff_playerids``) is the cross-source spine that joins Sleeper
(``sleeper_id``) <-> ESPN (``espn_id``) <-> nflverse stats (``gsis_id``).
"""

from __future__ import annotations

from typing import Any


def _require_nflreadpy() -> Any:
    try:
        import nflreadpy  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "The nflverse adapter needs the optional dependency. "
            "Install it with: uv sync --extra nflverse"
        ) from exc
    return nflreadpy


def load_id_map() -> list[dict[str, Any]]:
    """The DynastyProcess id map: sleeper_id / espn_id / gsis_id and more, as dict rows."""
    nfl = _require_nflreadpy()
    return nfl.load_ff_playerids().to_dicts()


def load_weekly_stats(seasons: list[int]) -> list[dict[str, Any]]:
    """Weekly player stats (targets, target_share, air_yards_share, carries, ...)."""
    nfl = _require_nflreadpy()
    return nfl.load_player_stats(seasons, summary_level="week").to_dicts()


def load_rankings(rank_type: str = "draft") -> list[dict[str, Any]]:
    """FantasyPros consensus rankings (rank_type: 'draft' | 'week' | 'all').

    Current-only (no historical archive), so we snapshot it weekly -- see audible.snapshot.
    """
    nfl = _require_nflreadpy()
    return nfl.load_ff_rankings(rank_type).to_dicts()


def load_snap_counts(seasons: list[int]) -> list[dict[str, Any]]:
    """Per-game snap counts incl. offense_pct / defense_pct (opportunity signal)."""
    nfl = _require_nflreadpy()
    return nfl.load_snap_counts(seasons).to_dicts()


def load_nextgen_stats(seasons: list[int], stat_type: str) -> list[dict[str, Any]]:
    """Next Gen Stats; stat_type in {"passing", "receiving", "rushing"} (week 0 = season agg)."""
    nfl = _require_nflreadpy()
    return nfl.load_nextgen_stats(seasons, stat_type=stat_type).to_dicts()


# --- polars frame accessors (bulk sources aggregated downstream in polars) ---------
# These return the raw polars DataFrame; the draft layer does the heavy aggregation and
# converts to plain types at its boundary, so polars never leaks past the draft modules.


def opportunity_frame(seasons: list[int]) -> Any:
    """ff_opportunity weekly (expected components); join key ``player_id`` == gsis_id."""
    return _require_nflreadpy().load_ff_opportunity(seasons, stat_type="weekly")


def draft_picks_frame(seasons: list[int]) -> Any:
    """NFL draft picks (round, pick, position, team, gsis_id, pfr_player_name)."""
    return _require_nflreadpy().load_draft_picks(seasons)


def rosters_frame(seasons: list[int]) -> Any:
    """Season rosters: sleeper_id <-> gsis_id <-> team, plus years_exp / entry_year."""
    return _require_nflreadpy().load_rosters(seasons)


def player_stats_frame(seasons: list[int]) -> Any:
    """Weekly player stats (target_share, carries, air_yards_share, ...); keyed by gsis_id."""
    return _require_nflreadpy().load_player_stats(seasons, summary_level="week")
