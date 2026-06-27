"""ConsensusProvider -- the baseline projection of record (the thing to beat).

Wraps a platform adapter and serves its consensus projection: Sleeper's raw Rotowire
stat lines scored by our engine, or (Phase 1) ESPN's native projections. This is the
borrowed-consensus baseline every opponent's app also runs on; the OpportunityProvider
exists to outperform it, validated by the backtest gate before it's allowed to lead.
"""

from __future__ import annotations

from ..adapters.base import PlatformAdapter
from ..config.schema import LeagueConfig, Platform
from ..models.player import PlayerProjection


class ConsensusProvider:
    name = "consensus"

    def __init__(self, adapter: PlatformAdapter) -> None:
        self._adapter = adapter

    def projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        return self._adapter.player_projections(config)

    def close(self) -> None:
        close = getattr(self._adapter, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> ConsensusProvider:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_consensus_provider(config: LeagueConfig) -> ConsensusProvider:
    """Construct the consensus provider for *config*'s platform."""
    if config.platform is Platform.SLEEPER:
        from ..adapters.sleeper import SleeperAdapter

        return ConsensusProvider(SleeperAdapter())
    if config.platform is Platform.ESPN:
        from ..adapters.espn import EspnAdapter

        return ConsensusProvider(EspnAdapter())
    raise ValueError(f"no consensus provider for platform {config.platform!r}")
