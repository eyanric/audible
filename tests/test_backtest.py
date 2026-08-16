from __future__ import annotations

import math

import pytest

from audible.backtest.metrics import mae, rmse, spearman, top_n_hit_rate, value_test
from audible.config import LeagueConfig
from audible.models import PlayerProjection
from audible.value import scarcity_values


def test_spearman_monotonic() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert math.isnan(spearman([1.0], [2.0]))  # too few points


def test_mae_rmse() -> None:
    assert mae([1, 2, 3], [1, 2, 5]) == pytest.approx(2 / 3)
    assert rmse([1, 2, 3], [1, 2, 5]) == pytest.approx(math.sqrt(4 / 3))


def test_top_n_hit_rate() -> None:
    ids = ["a", "b", "c", "d"]
    # predicted favours a,b; actual favours c,d -> no overlap in top-2
    assert top_n_hit_rate(ids, [4, 3, 2, 1], [1, 2, 4, 3], 2) == pytest.approx(0.0)
    # perfect agreement
    assert top_n_hit_rate(ids, [4, 3, 2, 1], [4, 3, 2, 1], 2) == pytest.approx(1.0)


def test_value_test_edge() -> None:
    mt, mf, edge, nt, nf = value_test([1, 1, -1, -1], [10, 20, 5, 1])
    assert (nt, nf) == (2, 2)
    assert (mt, mf, edge) == (pytest.approx(15.0), pytest.approx(3.0), pytest.approx(12.0))


def _p(pid: str, pos: str, pts: float) -> PlayerProjection:
    return PlayerProjection(pid, pid, pos, frozenset({pos}), None, pts)


def test_scarcity_discounts_flat_positions(mini_config: LeagueConfig) -> None:
    # mini_config has num_teams=2 -> VONA window=2.
    flat = [_p(f"q{i}", "QB", 100 - i) for i in range(5)]   # 100,99,98,97,96 (streamable)
    steep = [_p("r1", "RB", 100), _p("r2", "RB", 50), _p("r3", "RB", 25),
             _p("r4", "RB", 10), _p("r5", "RB", 5)]
    vals = scarcity_values(flat + steep, mini_config)
    assert vals["q0"] == pytest.approx(2.0)   # 100 - 98 (two QBs later): tiny -> no false target
    assert vals["r1"] == pytest.approx(75.0)  # 100 - 25: real scarcity
    assert vals["q0"] < vals["r1"]
