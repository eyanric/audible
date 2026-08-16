"""Typed, validated league configuration.

The whole engine is config-driven: scoring weights, roster structure, and slot
eligibility live in data (``leagues/*.toml``) and are validated here. The value
engine *derives* replacement baselines and positional scarcity from this object,
so two leagues run through one engine with no league-specific branches.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Recognised fantasy-position universe. This is a validation allowlist only --
# the value engine derives a league's actual positions from its slot eligibility,
# never from this constant.
KNOWN_POSITIONS: frozenset[str] = frozenset(
    {"QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"}
)


class Platform(StrEnum):
    SLEEPER = "sleeper"
    ESPN = "espn"


class LeagueConfig(BaseModel):
    """One league's complete, validated configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    platform: Platform
    league_id: str
    season: int
    num_teams: int = Field(gt=0)

    # Starting lineup with positions expanded (e.g. ("QB", "RB", "RB", ...)).
    # Bench/IR slots are excluded -- only slots that demand a weekly starter.
    starting_slots: tuple[str, ...]
    # Each distinct slot name -> the fantasy positions allowed to fill it.
    slot_eligibility: dict[str, tuple[str, ...]]
    # Raw scoring weights keyed by stat key (Sleeper stat vocabulary).
    scoring: dict[str, float]

    # League context / quirks (optional metadata).
    median_match: bool = False
    playoff_teams: int | None = None
    playoff_week_start: int | None = None
    trade_deadline_week: int | None = None
    waiver_type: str | None = None
    faab_budget: int | None = None

    # Adapter drift guards.
    expected_reception_points: float | None = None
    notes: str | None = None

    # Which value metric drives targets-vs-ADP, learned from the backtest per league:
    # "vorp" (over-replacement) for deep/scarce formats (superflex + IDP); "scarcity"
    # (VONA, dropoff-slope) for shallow/flat formats (1-QB), where it beats VORP OOS.
    value_metric: str = "vorp"

    # The single Sleeper ADP field that prices this league's market. One league gets exactly
    # one market: ADP ranks drawn from different markets (e.g. adp_2qb for offense and
    # adp_idp for IDP) are not comparable, so pooling them corrupts every value number.
    adp_market: str = "adp_half_ppr"

    @model_validator(mode="after")
    def _validate_structure(self) -> LeagueConfig:
        if self.value_metric not in ("vorp", "scarcity"):
            raise ValueError(
                f"value_metric must be 'vorp' or 'scarcity', got {self.value_metric!r}"
            )
        if not self.starting_slots:
            raise ValueError("starting_slots must be non-empty")
        for slot in self.starting_slots:
            if slot not in self.slot_eligibility:
                raise ValueError(
                    f"slot {slot!r} in starting_slots has no slot_eligibility entry"
                )
        for slot, eligible in self.slot_eligibility.items():
            if not eligible:
                raise ValueError(f"slot {slot!r} has empty eligibility")
            unknown = set(eligible) - KNOWN_POSITIONS
            if unknown:
                raise ValueError(
                    f"slot {slot!r} references unknown positions {sorted(unknown)}"
                )
        return self

    @property
    def positions(self) -> frozenset[str]:
        """Positions this league rosters, derived from slot eligibility."""
        out: set[str] = set()
        for eligible in self.slot_eligibility.values():
            out.update(eligible)
        return frozenset(out)

    def slot_counts(self) -> dict[str, int]:
        """How many of each starting slot the league demands per team."""
        counts: dict[str, int] = {}
        for slot in self.starting_slots:
            counts[slot] = counts.get(slot, 0) + 1
        return counts
