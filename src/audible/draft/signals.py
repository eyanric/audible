"""Trajectory + situation-change signals (Addendum 01, 3).

Season aggregates hide the two things that move draft value, so we compute both from
data (flag-don't-fake for non-derivable shifts, which are left to the AI layer later):

  * vacated target/carry share -- prior-season usage of teammates who left the team;
    the strongest fully-computable preseason breakout signal (opportunity flows to whoever
    remains).
  * opportunity trajectory -- last-N-game usage vs the season average; a back-half riser's
    true baseline is the later number.

All adjustments are bounded and surfaced; nothing here silently swings a projection.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VacatedShares:
    target: float
    carry: float


@dataclass(frozen=True, slots=True)
class TrajInfo:
    factor: float  # bounded recent/season ratio applied to modeled xFP
    recent_mean: float
    season_mean: float


def current_team_by_gsis(season: int = 2026) -> dict[str, str]:
    """gsis_id -> current-season team (for situation-change and vacated-share lookup)."""
    import polars as pl

    from ..adapters.nflverse import rosters_frame

    df = rosters_frame([season]).filter(pl.col("gsis_id").is_not_null())
    out: dict[str, str] = {}
    for row in df.select(["gsis_id", "team"]).iter_rows(named=True):
        out.setdefault(str(row["gsis_id"]), str(row["team"]))
    return out


def team_vacated_shares(
    prev_season: int = 2025, cur_season: int = 2026
) -> dict[str, VacatedShares]:
    """Per team: prior-season target/carry share of players no longer on the team."""
    import polars as pl

    from ..adapters.nflverse import player_stats_frame, rosters_frame

    ps = player_stats_frame([prev_season])
    player_team = ps.group_by(["player_id", "team"]).agg(
        pl.col("targets").fill_null(0).sum().alias("targets"),
        pl.col("carries").fill_null(0).sum().alias("carries"),
    )
    team_tot = player_team.group_by("team").agg(
        pl.col("targets").sum().alias("team_targets"),
        pl.col("carries").sum().alias("team_carries"),
    )
    player_team = player_team.join(team_tot, on="team").with_columns(
        tshare=pl.col("targets") / pl.col("team_targets").clip(lower_bound=1),
        cshare=pl.col("carries") / pl.col("team_carries").clip(lower_bound=1),
    )

    cur = (
        rosters_frame([cur_season])
        .filter(pl.col("gsis_id").is_not_null())
        .select(["gsis_id", "team"])
        .unique(subset=["gsis_id"])
        .rename({"gsis_id": "player_id", "team": "cur_team"})
    )
    joined = player_team.join(cur, on="player_id", how="left").with_columns(
        (pl.col("cur_team") != pl.col("team")).fill_null(True).alias("departed")
    )
    vac = (
        joined.filter(pl.col("departed"))
        .group_by("team")
        .agg(pl.col("tshare").sum().alias("vac_t"), pl.col("cshare").sum().alias("vac_c"))
    )

    out: dict[str, VacatedShares] = {}
    for row in vac.iter_rows(named=True):
        out[str(row["team"])] = VacatedShares(
            float(row["vac_t"] or 0.0), float(row["vac_c"] or 0.0)
        )
    return out


def trajectory_factors(
    season: int = 2025, recent_games: int = 6, bound: float = 0.20
) -> dict[str, TrajInfo]:
    """gsis_id -> bounded recent/season usage ratio (targets+carries) and the raw means."""
    import polars as pl

    from ..adapters.nflverse import player_stats_frame

    ps = player_stats_frame([season]).with_columns(
        (pl.col("targets").fill_null(0) + pl.col("carries").fill_null(0)).alias("opp")
    )
    grouped = ps.group_by("player_id").agg(
        pl.col("opp").mean().alias("season_mean"),
        pl.col("opp").sort_by("week").tail(recent_games).mean().alias("recent_mean"),
    )

    lo, hi = 1.0 - bound, 1.0 + bound
    out: dict[str, TrajInfo] = {}
    for row in grouped.iter_rows(named=True):
        gsis = row.get("player_id")
        if not gsis:
            continue
        season_mean = float(row["season_mean"] or 0.0)
        recent_mean = float(row["recent_mean"] or 0.0)
        factor = 1.0 if season_mean <= 0 else min(hi, max(lo, recent_mean / season_mean))
        out[str(gsis)] = TrajInfo(factor, recent_mean, season_mean)
    return out
