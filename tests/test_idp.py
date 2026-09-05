from __future__ import annotations

import pytest

from audible.config import LeagueConfig
from audible.idp import PlayerIdp, idp_projection


def _lb(pid: str, **stats: float) -> PlayerIdp:
    stats.setdefault("gp", 17.0)
    return PlayerIdp(pid, "LB", int(stats["gp"]), 1000.0, dict(stats))


def test_lone_player_projects_to_prior(sleeper_config: LeagueConfig) -> None:
    # A lone player IS the positional mean -> no shrinkage; projects to prior-season points.
    p = _lb("x", idp_tkl_solo=100.0, idp_sack=5.0, idp_int=2.0)
    out = idp_projection({"x": p}, sleeper_config)
    # solo 2.0; sack and int are 3.0 each -- both HALVED live between 2026-08-15 and
    # 2026-09-05, which is why this number moved from 242 to 221.
    assert out["x"] == pytest.approx(100 * 2 + 5 * 3 + 2 * 3)


def test_regresses_noise_keeps_tackles(sleeper_config: LeagueConfig) -> None:
    # A: sticky high-tackle grinder; B: fluky low-tackle high-INT. Tackles persist (w=0.71),
    # INT regresses toward the mean (w=0.17), so A should project well above B.
    a = _lb("a", idp_tkl_solo=170.0, idp_int=0.0)
    b = _lb("b", idp_tkl_solo=34.0, idp_int=17.0)
    out = idp_projection({"a": a, "b": b}, sleeper_config)
    assert out["a"] > out["b"]


def test_excludes_thin_samples(sleeper_config: LeagueConfig) -> None:
    p = _lb("x", gp=3.0, idp_tkl_solo=30.0)  # below min_games -> not projected
    assert idp_projection({"x": p}, sleeper_config, min_games=6) == {}
