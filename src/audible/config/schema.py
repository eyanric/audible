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
    # Per-position overrides layered on `scoring`, keyed by position then stat key. Empty for
    # every Sleeper league, which scores a stat identically for everyone.
    #
    # League B needs it: the commissioner pays 0.5 per reception to WR and TE and 0.0 to RB,
    # deliberately (confirmed 2026-08-17). A flat table cannot express that, and the difference
    # is worth ~30 points a season on a pass-catching back -- enough to reorder RB against WR.
    #
    # Semantics match ESPN's, which was verified rather than assumed: a position listed for a
    # stat takes the override, a position NOT listed falls back to the base weight. Measured on
    # 12 players who record stats where the two rules differ: fallback-to-base matched 12/12,
    # fallback-to-zero 0/12.
    scoring_by_position: dict[str, dict[str, float]] = Field(default_factory=dict)

    # League context / quirks (optional metadata).
    median_match: bool = False
    playoff_teams: int | None = None
    playoff_week_start: int | None = None
    trade_deadline_week: int | None = None
    waiver_type: str | None = None
    faab_budget: int | None = None

    # How many rounds this league's draft runs. Structural, unlike `replacement_bench_slots`
    # below, which is a model knob. Live sync overrides it the moment it answers; this is what
    # the clock uses BEFORE that, and until now that was a hardcoded 18 -- League A's number,
    # sitting in shared logic. On League B's 16-round draft an 18-round clock overstates the
    # picks you have left, which is exactly the quantity `recommend` uses to decide whether an
    # empty starting slot is still optional.
    draft_rounds: int | None = Field(default=None, gt=0)

    # Bench rounds per team that the replacement baseline prices in. This is a MODEL knob,
    # not a structural fact: 0 means "price in none", which pins replacement at starters+1.
    #
    # It matters because replacement level is meant to be the first player on the WAIVER
    # WIRE. In a 16-round draft against 9 starting slots, 7 of every team's picks are bench
    # and those players are not on the wire. Leaving them in the pool sets a baseline that is
    # far too shallow at RB/WR/TE and exactly right at D/ST and K -- nobody drafts a backup
    # D/ST -- so it inflates D/ST and K relative to every position that actually gets hoarded.
    replacement_bench_slots: int = Field(default=0, ge=0)

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

    def scoring_for(self, position: str) -> dict[str, float]:
        """The effective scoring weights for *position*: base, with that position's overrides.

        Resolution lives here rather than in the engine because league shape is data, and
        `score_stat_line` stays a pure function of one weights table. A league with no
        overrides -- every Sleeper league -- returns `scoring` unchanged, so nothing that
        predates position-scoped scoring changes behaviour or identity.

        `position` is REQUIRED, and that is the point. It used to default to None, which
        returned the BASE table -- the one that pays a running back 0.5 a catch in a league
        that pays him nothing. Every call site already passed a position, so the default
        bought nothing and made the silently-wrong call spellable. Now it is a type error.
        """
        if not self.scoring_by_position:
            return self.scoring
        overrides = self.scoring_by_position.get(position)
        if not overrides:
            return self.scoring
        return {**self.scoring, **overrides}

    def slot_counts(self) -> dict[str, int]:
        """How many of each starting slot the league demands per team."""
        counts: dict[str, int] = {}
        for slot in self.starting_slots:
            counts[slot] = counts.get(slot, 0) + 1
        return counts
