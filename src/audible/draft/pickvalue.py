"""The pick-value objective: scarcity, recoverability and the turn. OFF by default.

Seven opponents in this room take the top standard-scored name off a shared board. Nobody
prices what it costs to WAIT on a position, and nobody prices how cheaply a position can be
refilled from the wire. That is the edge this objective tries to spend -- decision quality on
a board everybody can see, rather than a better projection, which C-B already settled.

    pick_value(c) = points(c)
                  - E[best OTHER player at c.position available at my NEXT pick]   # delay
                  - wire_replacement[c.position]                                   # recoverability

TURN-AWARE BY CONSTRUCTION. The horizon is MY NEXT PICK, never the next pick. At seat 8
holding 8 and 9 no opponent picks in between, so the delay term collapses to the gap between
the best and second-best at that position -- taking one does not cost you the other. At pick
9 the horizon is 24 and fourteen rivals intervene, so the same position is priced completely
differently ten seconds later. A model that used "the next pick" would price both the same
and be wrong at exactly the moment the draft is won or lost.

NOTHING HERE ENTERS THE SORT. `PickValue.enabled` defaults to False and no production caller
sets it. Promotion requires clearing the gate pre-registered in docs/pre-registration-pick-value.md.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

MODES = ("delay", "wire", "both")


@dataclass(frozen=True, slots=True)
class OpponentProfile:
    """P(a given opponent pick in round r goes to position p), measured, not assumed.

    Room-average rather than per-seat: in a replay the managers are not in known seats, so
    using a specific manager's profile would be inventing information the objective would not
    have. The per-seat profiles exist (scripts/opponent_model.py) and are what a live draft
    would use, where the seat map IS known.
    """

    rate: dict[int, dict[str, float]] = field(default_factory=dict)

    def position_rate(self, rnd: int, position: str) -> float:
        row = self.rate.get(rnd) or self.rate.get(max(self.rate) if self.rate else 0) or {}
        return row.get(position, 0.0)


def load_opponent_profile(
    cache_dir: Path, league_id: int, years: Sequence[int], positions_by_espn: Mapping[str, str]
) -> OpponentProfile:
    """Positional composition per round, pooled over every real draft in `years`."""
    counts: dict[int, dict[str, float]] = {}
    totals: dict[int, float] = {}
    for yr in years:
        p = cache_dir / f"espn_draft_{league_id}_{yr}.json"
        if not p.exists():
            continue
        for pick in json.loads(p.read_text(encoding="utf-8")):
            rnd = int(pick["round"])
            # an unresolved espn id in this league is a team D/ST: no player row exists
            pos = positions_by_espn.get(str(pick["player_id"]), "DEF")
            counts.setdefault(rnd, {})[pos] = counts.setdefault(rnd, {}).get(pos, 0.0) + 1.0
            totals[rnd] = totals.get(rnd, 0.0) + 1.0
    rate = {r: {p: c / totals[r] for p, c in row.items()} for r, row in counts.items()}
    return OpponentProfile(rate)


@dataclass(frozen=True, slots=True)
class PickValue:
    """The objective. `enabled` is the flag; it is False and production never flips it."""

    wire_replacement: dict[str, float]
    profile: OpponentProfile
    teams: int = 8
    mode: str = "both"
    enabled: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")

    def expected_best_other(
        self,
        candidate: str,
        position: str,
        available_at_pos: Sequence[str],
        points: Mapping[str, float],
        intervening: int,
        rnd: int,
    ) -> float:
        """What this position is still worth to me at my NEXT pick, if I skip him now.

        `intervening` opponents pick before I do again; the profile says what share of a
        round's picks go to this position, so the expected number taken here is the product.
        The answer is the best man left after that many are gone -- interpolated, because
        "2.4 receivers will go" is a real quantity and rounding it to 2 throws away the part
        that distinguishes a position under pressure from one that is not.

        Excludes the candidate himself: taking him now is precisely what removes him.
        """
        others = [p for p in available_at_pos if p != candidate]
        if not others:
            return self.wire_replacement.get(position, 0.0)
        taken = intervening * self.profile.position_rate(rnd, position)
        idx = int(taken)
        frac = taken - idx
        wire = self.wire_replacement.get(position, 0.0)
        lo = points.get(others[idx], wire) if idx < len(others) else wire
        hi = points.get(others[idx + 1], wire) if idx + 1 < len(others) else wire
        return lo + frac * (hi - lo)

    def score(
        self,
        available: Sequence[str],
        position_of: Mapping[str, str],
        points: Mapping[str, float],
        *,
        current_pick: int,
        my_next_pick: int | None,
        rnd: int,
    ) -> dict[str, float]:
        """Objective value for every available candidate at this pick."""
        # The number of rivals who act before I do again. At the turn this is ZERO, and every
        # delay term collapses to the gap between the top two -- which is the turn's whole
        # character and the thing a next-pick horizon gets wrong.
        intervening = max(0, (my_next_pick - current_pick - 1)) if my_next_pick else 0

        by_pos: dict[str, list[str]] = {}
        for pid in available:
            by_pos.setdefault(position_of.get(pid, "?"), []).append(pid)
        for group in by_pos.values():
            group.sort(key=lambda p: -points.get(p, 0.0))

        out: dict[str, float] = {}
        for pid in available:
            pos = position_of.get(pid, "?")
            val = points.get(pid, 0.0)
            if self.mode in ("delay", "both"):
                val -= self.expected_best_other(
                    pid, pos, by_pos.get(pos, ()), points, intervening, rnd
                )
            if self.mode in ("wire", "both"):
                val -= self.wire_replacement.get(pos, 0.0)
            out[pid] = val
        return out
