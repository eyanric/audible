"""The League A scoring drift guard: absent and 0.0 are the same rule, everything else is drift.

On 2026-09-05, the morning of League A's draft, `verify-scoring sleeper_boyfun` reported 78
differing keys. Seventy-six were the config declining to declare a key that the live league
declares at 0.0 -- the same scoring rule written two ways. The other two were real:
`idp_sack` and `idp_int` had both been HALVED live, 6.0 -> 3.0, and had gone unnoticed
because they sat on lines 36 and 38 of a 78-line wall of false positives.

These tests pin both halves: the no-op pairs stay quiet, and every way a rule can actually
differ still fires.
"""

from __future__ import annotations

from typing import Any

import pytest

from audible.adapters.sleeper import SleeperAdapter
from audible.config import LeagueConfig


def _adapter(monkeypatch: pytest.MonkeyPatch, live_scoring: dict[str, Any]) -> SleeperAdapter:
    monkeypatch.setattr(
        SleeperAdapter,
        "get_league",
        lambda self, league_id: {"scoring_settings": live_scoring},
    )
    return SleeperAdapter()


def test_a_key_the_config_omits_and_the_league_pays_nothing_for_is_not_drift(
    monkeypatch: pytest.MonkeyPatch, sleeper_config: LeagueConfig
) -> None:
    """Sleeper returns its whole vocabulary, most of it 0.0. Absent scores what 0.0 scores."""
    live = {**sleeper_config.scoring, "pass_att": 0.0, "qb_hit": 0.0, "tkl_loss": 0.0}
    with _adapter(monkeypatch, live) as adapter:
        assert adapter.verify_scoring(sleeper_config) == []


def test_a_key_the_config_declares_at_zero_and_the_league_omits_is_not_drift(
    monkeypatch: pytest.MonkeyPatch, sleeper_config: LeagueConfig
) -> None:
    live = {k: v for k, v in sleeper_config.scoring.items() if v != 0}
    cfg = sleeper_config.model_copy(update={"scoring": {**sleeper_config.scoring, "fgm": 0.0}})
    with _adapter(monkeypatch, live) as adapter:
        assert adapter.verify_scoring(cfg) == []


def test_a_halved_weight_is_drift(
    monkeypatch: pytest.MonkeyPatch, sleeper_config: LeagueConfig
) -> None:
    """The exact 2026-09-05 failure: the live league quietly halves an IDP weight."""
    live = {**sleeper_config.scoring, "idp_sack": 3.0}
    cfg = sleeper_config.model_copy(update={"scoring": {**sleeper_config.scoring, "idp_sack": 6.0}})
    with _adapter(monkeypatch, live) as adapter:
        assert adapter.verify_scoring(cfg) == [("idp_sack", 6.0, 3.0)]


def test_a_key_the_config_omits_that_the_league_actually_pays_is_drift(
    monkeypatch: pytest.MonkeyPatch, sleeper_config: LeagueConfig
) -> None:
    """The costly direction: silently scoring nothing for something the league pays for."""
    live = {**sleeper_config.scoring, "pass_att": 0.25}
    with _adapter(monkeypatch, live) as adapter:
        assert adapter.verify_scoring(sleeper_config) == [("pass_att", None, 0.25)]


def test_a_nonzero_config_key_the_league_pays_nothing_for_is_drift(
    monkeypatch: pytest.MonkeyPatch, sleeper_config: LeagueConfig
) -> None:
    live = {**sleeper_config.scoring, "pass_att": 0.0}
    cfg = sleeper_config.model_copy(update={"scoring": {**sleeper_config.scoring, "pass_att": 0.5}})
    with _adapter(monkeypatch, live) as adapter:
        assert adapter.verify_scoring(cfg) == [("pass_att", 0.5, 0.0)]
