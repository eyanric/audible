"""Rookie path (Addendum 01, C).

Rookies have no nflverse usage history, so they can't get an opportunity xFP -- but they
must never fall to null/replacement (a first-round RB at replacement is a board-breaking
bug). They're anchored on the consensus projection (which is rookie-aware) and tilted by
**NFL draft capital**, the best year-one predictor of role. The offense/IDP branch is a
label here (both resolve to consensus * draft-capital tilt); a fitted draft-capital->xFP
and a projected-snap->tackle model are deliberately deferred rather than faked.

The in-season crossover (``opportunity_weight``) is defined now but dormant at the draft
(games_played == 0): as snaps accrue, value shifts continuously from this prior to
observed opportunity so a rookie's number doesn't lurch the week the model flips.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"[^a-z\s]", "", name.lower())
    parts = [p for p in cleaned.split() if p not in _SUFFIXES]
    return " ".join(parts)


@dataclass(frozen=True, slots=True)
class DraftCapital:
    round: int
    pick: int
    position: str
    team: str


def load_draft_capital(
    season: int = 2026,
) -> tuple[dict[str, DraftCapital], dict[str, DraftCapital]]:
    """Return (by gsis_id, by normalized name) lookups for a draft class."""
    from ..adapters.nflverse import draft_picks_frame

    df = draft_picks_frame([season])
    by_gsis: dict[str, DraftCapital] = {}
    by_name: dict[str, DraftCapital] = {}
    for row in df.select(
        ["round", "pick", "position", "team", "gsis_id", "pfr_player_name"]
    ).iter_rows(named=True):
        if row["round"] is None or row["pick"] is None:
            continue
        capital = DraftCapital(
            int(row["round"]), int(row["pick"]),
            str(row["position"] or ""), str(row["team"] or ""),
        )
        if row["gsis_id"]:
            by_gsis[str(row["gsis_id"])] = capital
        name = normalize_name(row["pfr_player_name"])
        if name:
            by_name[name] = capital
    return by_gsis, by_name


# ~262 picks in a 7-round draft; map overall pick -> bounded tilt on the consensus anchor.
_LAST_PICK = 262


def draft_capital_factor(capital: DraftCapital | None, bound: float = 0.15) -> float:
    """Monotonic prior: pick 1 -> 1+bound, mid-draft -> ~1.0, late Day 3 -> 1-bound.

    A transparent heuristic tilt (not a fitted projection): early capital earns role,
    Day 3 rarely does in year one. Bounded so it nudges, never invents.
    """
    if capital is None:
        return 1.0
    pick = min(max(capital.pick, 1), _LAST_PICK)
    progress = (pick - 1) / (_LAST_PICK - 1)
    return (1.0 + bound) - 2.0 * bound * progress


def opportunity_weight(games_played: int, full_by: int = 5) -> float:
    """Crossover weight on observed opportunity vs the rookie prior (dormant at the draft).

    0 games -> 0.0 (pure prior); reaches 1.0 (observed-dominant) by ``full_by`` games.
    """
    if games_played <= 0:
        return 0.0
    return min(1.0, games_played / full_by)
