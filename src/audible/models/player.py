"""Domain models for projected players flowing into the value engine."""

from __future__ import annotations

from dataclasses import dataclass, field


def _empty_stats() -> dict[str, float]:
    return {}


def _empty_ids() -> dict[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class RawPlayerLine:
    """A rosterable player's identity + raw, unscored consensus stat line.

    This is the *universe* a ``ProjectionProvider`` scores. Identity and eligibility
    come from the platform (who can be rostered, and in which slots); ``stats`` is the
    raw projected stat counts; ``ids`` carries cross-source ids (gsis/espn/...) so the
    nflverse opportunity layer can join without re-fetching the catalog.
    """

    player_id: str
    name: str
    primary_position: str
    eligible_positions: frozenset[str]
    team: str | None
    stats: dict[str, float] = field(default_factory=_empty_stats)
    ids: dict[str, str] = field(default_factory=_empty_ids)
    years_exp: int | None = None  # 0 => rookie (drives the §C rookie path)


@dataclass(frozen=True, slots=True)
class PlayerProjection:
    """A single player's league-scored projection.

    ``points`` is computed by the deterministic scoring engine against a league's
    scoring weights -- the value engine never recomputes it.

    ``primary_position`` is the bucket used for replacement grouping (one position);
    ``eligible_positions`` is the full set of slots the player can fill (a hybrid
    like a DE may be ``{"DL", "LB"}``; a two-way player may span offense + IDP).
    """

    player_id: str
    name: str
    primary_position: str
    eligible_positions: frozenset[str]
    team: str | None
    points: float
    stats: dict[str, float] = field(default_factory=_empty_stats, compare=False)
