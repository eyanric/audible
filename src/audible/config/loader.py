"""Load and validate league configs from ``leagues/*.toml``."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .schema import LeagueConfig

# repo_root/leagues -- loader.py is at src/audible/config/loader.py
LEAGUES_DIR: Path = Path(__file__).resolve().parents[3] / "leagues"


def load_league(path: str | Path) -> LeagueConfig:
    """Parse and validate a single league TOML into a :class:`LeagueConfig`."""
    p = Path(path)
    with p.open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    return LeagueConfig.model_validate(data)


def load_all_leagues(directory: str | Path | None = None) -> dict[str, LeagueConfig]:
    """Load every ``*.toml`` league in *directory* (default ``leagues/``), keyed by ``key``."""
    base = Path(directory) if directory is not None else LEAGUES_DIR
    leagues: dict[str, LeagueConfig] = {}
    for toml_path in sorted(base.glob("*.toml")):
        cfg = load_league(toml_path)
        if cfg.key in leagues:
            raise ValueError(f"duplicate league key {cfg.key!r} in {base}")
        leagues[cfg.key] = cfg
    return leagues
