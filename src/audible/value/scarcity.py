"""Scarcity-aware value (Backtest prompt, 6) -- value over *next available*, not replacement.

Plain VORP (points over the Nth starter) can't see a position's dropoff *slope*. In a
1-QB league QB ADP is late because QB is streamable (QB1→QB12 is a shallow drop), not
because the market underprices it -- yet VORP reports the top QBs as huge values and the
board flags false targets (Bo Nix +118).

VONA fixes this: value = a player's points minus the points of the player ~one round of
same-position picks later (window ≈ team count). Flat positions shrink to near zero;
genuinely scarce positions (steep drop) keep their edge. It's the dropoff slope, measured.
"""

from __future__ import annotations

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection


def scarcity_values(
    players: list[PlayerProjection], config: LeagueConfig, window: int | None = None
) -> dict[str, float]:
    """player_id -> value over the same-position player ``window`` ranks below (VONA)."""
    step = window if window is not None else config.num_teams
    by_pos: dict[str, list[PlayerProjection]] = {}
    for p in players:
        by_pos.setdefault(p.primary_position, []).append(p)

    out: dict[str, float] = {}
    for ranked in by_pos.values():
        ranked.sort(key=lambda p: (-p.points, p.player_id))
        n = len(ranked)
        for i, p in enumerate(ranked):
            nxt = ranked[min(i + step, n - 1)]
            out[p.player_id] = p.points - nxt.points
    return out
