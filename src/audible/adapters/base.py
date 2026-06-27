"""The interface every platform data adapter implements.

A platform adapter (Sleeper, ESPN) owns vendor data access and normalisation. It
exposes two things: the unscored player *universe* (``raw_player_lines`` -- who can be
rostered, in which slots, with raw stat lines + cross-source ids) and that platform's
*consensus* projection (``player_projections`` -- the universe scored by the league's
rules). The projection-methodology seam lives separately in ``providers/``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection, RawPlayerLine


@runtime_checkable
class PlatformAdapter(Protocol):
    name: str

    def raw_player_lines(self, config: LeagueConfig) -> list[RawPlayerLine]:
        """Return the unscored, rosterable player universe for *config*."""
        ...

    def player_projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        """Return this platform's consensus projections, scored by *config*'s rules."""
        ...
