from __future__ import annotations

import pytest

from audible.config import LeagueConfig
from audible.models import PlayerProjection
from audible.providers import BlendProvider, ConsensusProvider
from audible.providers.base import ProjectionProvider


def _proj(pid: str, pts: float, pos: str = "RB") -> PlayerProjection:
    return PlayerProjection(
        player_id=pid, name=pid, primary_position=pos,
        eligible_positions=frozenset({pos}), team=None, points=pts,
    )


class FakeProvider:
    """A provider returning a fixed list (the projections() seam, no I/O)."""

    def __init__(self, name: str, projections: list[PlayerProjection]) -> None:
        self.name = name
        self._projections = projections

    def projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        return self._projections


class FakeAdapter:
    name = "fake"

    def __init__(self, projections: list[PlayerProjection]) -> None:
        self._projections = projections
        self.closed = False

    def raw_player_lines(self, config: LeagueConfig):  # pragma: no cover - unused here
        raise NotImplementedError

    def player_projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        return self._projections

    def close(self) -> None:
        self.closed = True


def test_provider_satisfies_protocol() -> None:
    assert isinstance(FakeProvider("x", []), ProjectionProvider)


def test_consensus_delegates_and_closes(mini_config: LeagueConfig) -> None:
    adapter = FakeAdapter([_proj("A", 10.0)])
    with ConsensusProvider(adapter) as provider:
        out = provider.projections(mini_config)
    assert [p.player_id for p in out] == ["A"]
    assert adapter.closed is True  # context manager closes the underlying adapter


def test_blend_weights_overlapping_players(mini_config: LeagueConfig) -> None:
    consensus = FakeProvider("consensus", [_proj("A", 100.0), _proj("B", 50.0)])
    opportunity = FakeProvider("opportunity", [_proj("A", 200.0)])
    blend = BlendProvider([(consensus, 0.5), (opportunity, 0.5)])
    out = {p.player_id: p.points for p in blend.projections(mini_config)}
    assert out["A"] == 150.0  # 0.5*100 + 0.5*200
    assert out["B"] == 50.0   # only in consensus -> weight renormalised to 1


def test_blend_identity_from_first_provider(mini_config: LeagueConfig) -> None:
    consensus = FakeProvider("consensus", [_proj("A", 100.0, pos="WR")])
    opportunity = FakeProvider("opportunity", [_proj("A", 200.0, pos="RB")])
    blend = BlendProvider([(consensus, 0.7), (opportunity, 0.3)])
    (a,) = blend.projections(mini_config)
    assert a.primary_position == "WR"  # identity from the first (universe-defining) provider
    assert a.points == pytest.approx(0.7 * 100 + 0.3 * 200)


def test_blend_rejects_bad_weights() -> None:
    p = FakeProvider("p", [])
    with pytest.raises(ValueError):
        BlendProvider([])
    with pytest.raises(ValueError):
        BlendProvider([(p, 0.0)])
    with pytest.raises(ValueError):
        BlendProvider([(p, -1.0)])
