"""League configuration: typed schema + loader. Config is data, never logic."""

from .loader import LEAGUES_DIR, load_all_leagues, load_league
from .schema import KNOWN_POSITIONS, LeagueConfig, Platform

__all__ = [
    "KNOWN_POSITIONS",
    "LEAGUES_DIR",
    "LeagueConfig",
    "Platform",
    "load_all_leagues",
    "load_league",
]
