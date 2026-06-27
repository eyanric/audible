"""League-correct opportunity xFP (Addendum 01, 1).

xFP = Σ(modeled expected components → scoring engine) + Σ(carried elements ← consensus)

The modeled part is what a player's prior-season *usage* should have produced under the
league's exact rules; the carried part (big-play bonuses, fumbles) is inherited from the
consensus projection because ffopportunity can't derive it. Both are surfaced separately.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..scoring.engine import score_stat_line
from .coverage import CARRIED_KEYS, MODELED_COMPONENTS


@dataclass(frozen=True, slots=True)
class OpportunityXfp:
    gsis_id: str
    games: int
    components: dict[str, float]  # season-aggregated expected stats, mapped to our keys


def season_opportunity(seasons: list[int]) -> dict[str, OpportunityXfp]:
    """Aggregate ff_opportunity weekly -> season expected components, keyed by gsis_id."""
    import polars as pl

    from ..adapters.nflverse import opportunity_frame

    df = opportunity_frame(seasons)
    comp_cols = [c for c in MODELED_COMPONENTS if c in df.columns]
    agg = df.group_by("player_id").agg(
        *[pl.col(c).sum().alias(c) for c in comp_cols],
        pl.len().alias("games"),
    )

    out: dict[str, OpportunityXfp] = {}
    for row in agg.iter_rows(named=True):
        gsis = row.get("player_id")
        if not gsis:
            continue
        components = {MODELED_COMPONENTS[c]: float(row[c] or 0.0) for c in comp_cols}
        out[str(gsis)] = OpportunityXfp(str(gsis), int(row["games"]), components)
    return out


def modeled_xfp(opp: OpportunityXfp, scoring: Mapping[str, float]) -> float:
    """Score the season expected components by the league's rules (modeled tail only)."""
    return score_stat_line(opp.components, scoring)


def carried_value(consensus_stats: Mapping[str, float], scoring: Mapping[str, float]) -> float:
    """The carried tail, inherited additively from the consensus projection."""
    return sum(scoring.get(k, 0.0) * consensus_stats.get(k, 0.0) for k in CARRIED_KEYS)
