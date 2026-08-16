"""Backtest data: league-scored season actuals + the naive regressed-PPG baseline (§B1)."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.schema import LeagueConfig
from ..scoring.engine import score_stat_line


@dataclass(frozen=True, slots=True)
class PlayerSeason:
    player_id: str
    name: str
    primary: str
    points: float  # league-scored season total (our engine, incl. IDP + custom rules)
    games: int
    stats: dict[str, float]


def season_actuals(adapter: object, season: int, config: LeagueConfig) -> dict[str, PlayerSeason]:
    """Actual season totals from the Sleeper stats endpoint, scored by the league's rules."""
    from ..adapters.sleeper import SleeperAdapter

    assert isinstance(adapter, SleeperAdapter)
    catalog = adapter.get_players_catalog()
    out: dict[str, PlayerSeason] = {}
    for position in sorted(config.positions):
        for row in adapter.get_stats(season, position):
            stats = row.get("stats")
            player_id = str(row.get("player_id"))
            if not stats or player_id in out:
                continue
            entry = catalog.get(player_id)
            if entry is None:
                continue
            primary, _ = adapter.classify(entry, config.positions)
            if primary is None:
                continue
            numeric = {k: float(v) for k, v in stats.items() if isinstance(v, int | float)}
            out[player_id] = PlayerSeason(
                player_id=player_id,
                name=entry.get("full_name") or entry.get("team") or player_id,
                primary=primary,
                points=score_stat_line(numeric, config.scoring),
                games=int(numeric.get("gp", 0)),
                stats=numeric,
            )
    return out


def regressed_ppg_baseline(
    prior: dict[str, PlayerSeason], k: float = 8.0, full_games: int = 17
) -> dict[str, float]:
    """§B1: prior-season PPG shrunk toward the positional mean by games, x expected games.

    Deliberately dumb -- the fair minimum bar the opportunity model must clear.
    """
    by_pos: dict[str, list[float]] = {}
    for ps in prior.values():
        if ps.games > 0:
            by_pos.setdefault(ps.primary, []).append(ps.points / ps.games)
    pos_mean = {p: (sum(v) / len(v) if v else 0.0) for p, v in by_pos.items()}

    out: dict[str, float] = {}
    for ps in prior.values():
        if ps.games <= 0:
            continue
        ppg = ps.points / ps.games
        regressed = (ps.games * ppg + k * pos_mean.get(ps.primary, 0.0)) / (ps.games + k)
        out[ps.player_id] = regressed * full_games
    return out
