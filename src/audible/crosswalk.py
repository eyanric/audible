"""Tier-0 identity spine: resolve rostered Sleeper players to nflverse ``gsis_id``.

Nothing in the opportunity layer works until a rostered player joins to nflverse rows,
so this is a first-class, tested component with explicit unmatched handling.

Resolution order (first hit wins):
  1. ``gsis_id`` carried on the Sleeper catalog entry -- authoritative, no join needed.
  2. the ``load_ff_playerids`` crosswalk, keyed by ``sleeper_id`` -- covers catalog gaps.
  3. unmatched -- rookies before their first nflverse row, team D/ST (no gsis), or
     mid-season id churn. Surfaced, never silently dropped or coerced to a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models.player import RawPlayerLine


@dataclass(frozen=True, slots=True)
class ResolvedPlayer:
    sleeper_id: str
    name: str
    primary_position: str
    gsis_id: str | None
    source: str  # "catalog" | "ff_playerids" | "unmatched"

    @property
    def matched(self) -> bool:
        return self.gsis_id is not None


@dataclass(frozen=True, slots=True)
class CrosswalkReport:
    resolved: list[ResolvedPlayer]
    matched: list[ResolvedPlayer]
    unmatched: list[ResolvedPlayer]

    @property
    def match_rate(self) -> float:
        return len(self.matched) / len(self.resolved) if self.resolved else 0.0

    def source_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for player in self.resolved:
            counts[player.source] = counts.get(player.source, 0) + 1
        return counts


class Crosswalk:
    """Sleeper player_id -> nflverse gsis_id, with catalog-first, ff_playerids fallback."""

    def __init__(self, id_map_rows: list[dict[str, Any]]) -> None:
        self._by_sleeper: dict[str, str] = {}
        for row in id_map_rows:
            sleeper_id = row.get("sleeper_id")
            gsis_id = row.get("gsis_id")
            if not sleeper_id or not gsis_id:
                continue
            self._by_sleeper[str(sleeper_id)] = str(gsis_id)

    @classmethod
    def from_nflverse(cls) -> Crosswalk:
        from .adapters.nflverse import load_id_map

        return cls(load_id_map())

    def resolve(self, line: RawPlayerLine) -> ResolvedPlayer:
        catalog_gsis = line.ids.get("gsis_id")
        if catalog_gsis:
            return ResolvedPlayer(
                line.player_id, line.name, line.primary_position, catalog_gsis, "catalog"
            )
        fallback_gsis = self._by_sleeper.get(line.player_id)
        if fallback_gsis:
            return ResolvedPlayer(
                line.player_id, line.name, line.primary_position, fallback_gsis, "ff_playerids"
            )
        return ResolvedPlayer(
            line.player_id, line.name, line.primary_position, None, "unmatched"
        )

    def resolve_all(self, lines: list[RawPlayerLine]) -> CrosswalkReport:
        resolved = [self.resolve(line) for line in lines]
        matched = [r for r in resolved if r.matched]
        unmatched = [r for r in resolved if not r.matched]
        return CrosswalkReport(resolved=resolved, matched=matched, unmatched=unmatched)
