"""Value engine: config-derived replacement baselines and VORP."""

from .replacement import (
    ReplacementLevel,
    VorpEntry,
    assign_starters,
    compute_vorp,
    replacement_levels,
)
from .scarcity import scarcity_values

__all__ = [
    "ReplacementLevel",
    "VorpEntry",
    "assign_starters",
    "compute_vorp",
    "replacement_levels",
    "scarcity_values",
]
