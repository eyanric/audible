"""The projection seam the value engine consumes.

A ``ProjectionProvider`` answers one question -- "what will each rosterable player
score?" -- and nothing else. VORP/optimization depend on this interface, never on a
platform adapter, so the edge layer (OpportunityProvider, BlendProvider) plugs in here
without touching the value path.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection


@runtime_checkable
class ProjectionProvider(Protocol):
    name: str

    def projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        """Return league-scored projections for every rosterable player."""
        ...
