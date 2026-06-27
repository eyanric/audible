"""Replacement level & VORP -- the analytical heart, derived purely from config.

Replacement level is computed by simulating every team filling its starting lineup
from the projection-ranked pool, respecting slot eligibility (FLEX / SUPER_FLEX /
IDP_FLEX are just slots with wider eligibility -- nothing is special-cased). A
position's replacement level is then the best projected player who did *not* make any
starting lineup: the first guy on the waiver wire. VORP = projection - replacement.

Because eligibility and slot lists come entirely from ``LeagueConfig``, the same code
produces Sleeper's superflex/IDP baselines and ESPN's shallow 1-QB baselines -- only
the config differs. That's why the same player is valued differently per league.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection


@dataclass(frozen=True, slots=True)
class ReplacementLevel:
    position: str
    points: float
    starters_used: int
    replacement_rank: int  # 1-based rank (within position) of the replacement player


@dataclass(frozen=True, slots=True)
class VorpEntry:
    projection: PlayerProjection
    vorp: float
    is_starter: bool


def _ranked(players: list[PlayerProjection]) -> list[PlayerProjection]:
    """Deterministic ranking: points desc, player_id asc as a stable tie-break."""
    return sorted(players, key=lambda p: (-p.points, p.player_id))


def assign_starters(players: list[PlayerProjection], config: LeagueConfig) -> set[str]:
    """Greedily fill all ``num_teams`` lineups; return the set of started player ids.

    Players are considered best-first. Each is placed in the *most specific* open slot
    they're eligible for (smallest eligibility set), so dedicated slots fill before
    flex slots and flex slots are left for players who can only go there.
    """
    slot_instances: list[frozenset[str]] = []
    for slot_name in config.starting_slots:
        eligible = frozenset(config.slot_eligibility[slot_name])
        slot_instances.extend(eligible for _ in range(config.num_teams))
    filled: list[bool] = [False] * len(slot_instances)

    starters: set[str] = set()
    for player in _ranked(players):
        best_idx = -1
        best_key: tuple[int, int, tuple[str, ...]] | None = None
        for idx, eligible in enumerate(slot_instances):
            if filled[idx] or not (player.eligible_positions & eligible):
                continue
            # Prefer the most specific open slot, and among equally specific slots prefer
            # the one matching the player's primary position. So a hybrid DL/LB whose
            # primary is LB fills an LB slot before a DL slot, and only spills to its
            # other eligibility (or a flex) once primary slots are full.
            key = (
                len(eligible),
                0 if player.primary_position in eligible else 1,
                tuple(sorted(eligible)),
            )
            if best_key is None or key < best_key:
                best_key, best_idx = key, idx
        if best_idx >= 0:
            filled[best_idx] = True
            starters.add(player.player_id)
    return starters


def replacement_levels(
    players: list[PlayerProjection],
    config: LeagueConfig,
    starters: set[str] | None = None,
) -> dict[str, ReplacementLevel]:
    """Per-position replacement level: the best non-starter at each position."""
    if starters is None:
        starters = assign_starters(players, config)

    levels: dict[str, ReplacementLevel] = {}
    for position in sorted(config.positions):
        at_pos = [p for p in _ranked(players) if p.primary_position == position]
        started = sum(1 for p in at_pos if p.player_id in starters)
        bench = [p for p in at_pos if p.player_id not in starters]
        levels[position] = ReplacementLevel(
            position=position,
            points=bench[0].points if bench else 0.0,
            starters_used=started,
            replacement_rank=started + 1,
        )
    return levels


def compute_vorp(
    players: list[PlayerProjection], config: LeagueConfig
) -> tuple[list[VorpEntry], dict[str, ReplacementLevel]]:
    """Return (VORP entries sorted desc, replacement levels by position)."""
    starters = assign_starters(players, config)
    levels = replacement_levels(players, config, starters)
    entries = [
        VorpEntry(
            projection=p,
            vorp=p.points - levels[p.primary_position].points,
            is_starter=p.player_id in starters,
        )
        for p in players
    ]
    entries.sort(key=lambda e: (-e.vorp, e.projection.player_id))
    return entries, levels
