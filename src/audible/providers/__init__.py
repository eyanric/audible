"""Projection providers -- the seam the value engine consumes.

ConsensusProvider (baseline) is live. OpportunityProvider (nflverse edge layer) and
its blend land in Phase 2, behind the backtest gate, plugging in here without touching
the VORP path.
"""

from .base import ProjectionProvider
from .blend import BlendProvider
from .consensus import ConsensusProvider, build_consensus_provider

__all__ = [
    "BlendProvider",
    "ConsensusProvider",
    "ProjectionProvider",
    "build_consensus_provider",
]
