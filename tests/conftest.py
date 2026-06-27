from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from audible.config import LeagueConfig, load_league

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def mini_config() -> LeagueConfig:
    # 2 teams; each starts QB / FLEX(RB,WR,TE) / SUPER_FLEX(QB,RB,WR,TE).
    return LeagueConfig.model_validate(
        {
            "key": "mini", "name": "mini", "platform": "sleeper", "league_id": "0",
            "season": 2026, "num_teams": 2,
            "starting_slots": ["QB", "FLEX", "SUPER_FLEX"],
            "slot_eligibility": {
                "QB": ["QB"], "FLEX": ["RB", "WR", "TE"],
                "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
            },
            "scoring": {"rec": 0.5},
        }
    )


@pytest.fixture(scope="session")
def sleeper_config() -> LeagueConfig:
    return load_league(REPO_ROOT / "leagues" / "sleeper_boyfun.toml")


@pytest.fixture(scope="session")
def espn_config() -> LeagueConfig:
    return load_league(REPO_ROOT / "leagues" / "espn_davis_drive.toml")


@pytest.fixture(scope="session")
def sample_projections() -> dict[str, dict[str, Any]]:
    """player_id -> {player_id, queried_pos, stats} captured from the live API."""
    return json.loads((FIXTURES / "sleeper_projections_sample.json").read_text())


@pytest.fixture(scope="session")
def sample_catalog() -> dict[str, dict[str, Any]]:
    """player_id -> catalog entry for the sampled players."""
    return json.loads((FIXTURES / "sleeper_players_sample.json").read_text())
