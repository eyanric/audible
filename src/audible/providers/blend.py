"""BlendProvider -- weighted combination of providers.

Implements the spec's `final = w_consensus * consensus + w_opportunity * opportunity`.
Weights are tuned by the backtest, not guessed; early season they lean consensus, and
shift toward opportunity as the in-season sample accrues.

A player present in only some providers is blended over just those (weights
renormalised), so a player the opportunity model doesn't cover falls back cleanly to
consensus. Identity/eligibility come from the first provider that has the player, so
list the consensus (universe-defining) provider first.
"""

from __future__ import annotations

from dataclasses import replace

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection
from .base import ProjectionProvider


class BlendProvider:
    name = "blend"

    def __init__(self, weighted: list[tuple[ProjectionProvider, float]]) -> None:
        if not weighted:
            raise ValueError("BlendProvider needs at least one (provider, weight)")
        if any(w < 0 for _, w in weighted):
            raise ValueError("blend weights must be non-negative")
        if sum(w for _, w in weighted) <= 0:
            raise ValueError("blend weights must sum to a positive value")
        self._weighted = weighted

    def projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        # player_id -> (identity projection, weighted points sum, weight sum)
        acc: dict[str, tuple[PlayerProjection, float, float]] = {}
        for provider, weight in self._weighted:
            if weight == 0:
                continue
            for proj in provider.projections(config):
                existing = acc.get(proj.player_id)
                if existing is None:
                    acc[proj.player_id] = (proj, proj.points * weight, weight)
                else:
                    identity, points_sum, weight_sum = existing
                    acc[proj.player_id] = (
                        identity,
                        points_sum + proj.points * weight,
                        weight_sum + weight,
                    )

        return [
            replace(identity, points=points_sum / weight_sum)
            for identity, points_sum, weight_sum in acc.values()
        ]
