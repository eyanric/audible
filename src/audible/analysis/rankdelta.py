"""B-next -- does our board disagree with ESPN's anywhere it matters?

B1 settled that this room drafts off ESPN's served board, so a scoring edge is only worth
anything where **our** ordering departs from ESPN's. The earlier check found the two agreeing
and concluded the edge was dead -- but it only looked at the **top 24**, and that is the one
place agreement is guaranteed for reasons that have nothing to do with scoring. Elite
receivers are elite in every format.

Task B's tier table puts the uncredited reception value at **+48 at the top, +31.4 at ranks
25-60, and +27.7 at 61-120** -- barely decayed. If that value is real and our board is not
moving those players, the value is being computed and thrown away. If it IS moving them, the
exploit lives in rounds 3-10, which is exactly the range this room's ESPN anchoring leaves
open.

So this compares the two orderings tier by tier, and reports the archetypes that move with
their projected reception counts beside them -- because the whole hypothesis is that
receptions are what the two boards disagree about.

Both orderings are dense-ranked over the SAME population before differencing. Comparing a
rank drawn from 1,026 players against one drawn from 400 measures the size of the universe,
not the disagreement.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from ..backtest.metrics import spearman
from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection
from ..value import compute_vorp

# Ranks past this are placeholders rather than an ordering -- ESPN's tail runs to 2687. Same
# horizon and same reason as the anchoring gate; see analysis/anchoring.py.
RANK_HORIZON = 200.0

# The tiers Task B measured the reception value in. 1-24 is carried for continuity: it is the
# slice the earlier check looked at, and it is the control here rather than the result.
TIERS: tuple[tuple[str, int, int], ...] = (
    ("1-24", 1, 24),
    ("25-60", 25, 60),
    ("61-120", 61, 120),
    ("121-200", 121, 200),
)

# A rank move smaller than this is noise between two boards built from different projections.
MATERIAL_MOVE = 10


@dataclass(frozen=True, slots=True)
class Mover:
    name: str
    position: str
    espn_rank: int
    our_rank: int
    receptions: float
    points: float

    @property
    def delta(self) -> int:
        """Positive => we rank him higher (earlier) than ESPN does."""
        return self.espn_rank - self.our_rank


@dataclass(frozen=True, slots=True)
class TierResult:
    label: str
    n: int
    mean_delta: float
    median_delta: float
    mean_abs_delta: float
    material: int  # players moving at least MATERIAL_MOVE ranks either way
    by_position: dict[str, float] = field(default_factory=dict)
    mean_receptions_up: float = 0.0
    mean_receptions_down: float = 0.0
    # Spearman(receptions, delta) WITHIN each position. This is the actual test of the
    # reception hypothesis. Across positions it is confounded: a TE and a WR with the same
    # catch count are not comparable, because the two boards disagree about the positions
    # themselves. Within a position, if uncredited receptions are what moves players, this
    # is strongly positive. If it is ~0, whatever is moving them is not receptions.
    reception_corr: dict[str, tuple[float, int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RankDeltaReport:
    tiers: list[TierResult]
    risers: list[Mover]
    fallers: list[Mover]
    population: int
    excluded_beyond_horizon: int
    excluded_unranked: int

    def diverges(self) -> bool:
        """Do the mid tiers disagree materially? The top tier is the control, not the test."""
        mid = [t for t in self.tiers if t.label in ("25-60", "61-120") and t.n]
        if not mid:
            return False
        return any(t.mean_abs_delta >= MATERIAL_MOVE for t in mid)

    def reception_driven(self, floor: float = 0.3, min_n: int = 8) -> dict[str, float]:
        """Which positions move for reception reasons, in the direction the scoring predicts.

        Averaging the correlations across positions is wrong, and wrongly said "no": the
        scoring predicts OPPOSITE signs by position, so a real WR effect and a real RB effect
        cancel into nothing.

        Against ESPN's ordering, which credits catches at every position:

        * **WR and TE are paid 0.5/reception on our board**, so a high-catch receiver gains
          points we award and ESPN's ordering does not -- he should move UP. Predicted +.
        * **RB is paid 0.0/reception**, so a pass-catching back carries value ESPN's ordering
          credits and ours refuses to -- he should move DOWN. Predicted -.

        Returns the mid-tier correlation per position where it clears the floor with the
        predicted sign; an empty result means the divergence is not about receptions.
        """
        predicted = {"WR": 1.0, "TE": 1.0, "RB": -1.0}
        out: dict[str, float] = {}
        for t in self.tiers:
            if t.label not in ("25-60", "61-120"):
                continue
            for position, (corr, n) in t.reception_corr.items():
                sign = predicted.get(position)
                if sign is None or n < min_n:
                    continue
                if corr * sign >= floor:
                    out[position] = max(out.get(position, 0.0), abs(corr))
        return out


def _dense(values: dict[str, float], *, ascending: bool) -> dict[str, int]:
    sign = 1 if ascending else -1
    ordered = sorted(values, key=lambda pid: (sign * values[pid], pid))
    return {pid: i + 1 for i, pid in enumerate(ordered)}


def build_report(
    players: list[PlayerProjection], config: LeagueConfig, *, top_movers: int = 12
) -> RankDeltaReport:
    """Compare our league-scored VORP ordering against ESPN's served STANDARD ranks."""
    espn_rank: dict[str, float] = {}
    beyond = 0
    unranked = 0
    for p in players:
        rank = p.stats.get("espn_draft_rank")
        if rank is None:
            unranked += 1
        elif rank > RANK_HORIZON:
            beyond += 1
        else:
            espn_rank[p.player_id] = float(rank)

    ranked = [p for p in players if p.player_id in espn_rank]
    entries, _ = compute_vorp(ranked, config)

    # Dense-rank both orderings over exactly this population, so the difference measures
    # disagreement rather than the size of either universe.
    ours = {e.projection.player_id: i + 1 for i, e in enumerate(entries)}
    theirs = _dense(espn_rank, ascending=True)
    by_id = {p.player_id: p for p in ranked}

    movers: list[Mover] = []
    for pid, their_rank in theirs.items():
        p = by_id[pid]
        movers.append(
            Mover(
                name=p.name,
                position=p.primary_position,
                espn_rank=their_rank,
                our_rank=ours[pid],
                receptions=float(p.stats.get("rec", 0.0)),
                points=p.points,
            )
        )

    tiers: list[TierResult] = []
    for label, lo, hi in TIERS:
        group = [m for m in movers if lo <= m.espn_rank <= hi]
        if not group:
            tiers.append(TierResult(label, 0, 0.0, 0.0, 0.0, 0))
            continue
        deltas = [float(m.delta) for m in group]
        by_position: dict[str, float] = {}
        reception_corr: dict[str, tuple[float, int]] = {}
        for position in sorted({m.position for m in group}):
            at_pos = [m for m in group if m.position == position]
            by_position[position] = statistics.fmean([float(m.delta) for m in at_pos])
            if len(at_pos) > 2 and len({m.receptions for m in at_pos}) > 1:
                reception_corr[position] = (
                    spearman(
                        [m.receptions for m in at_pos], [float(m.delta) for m in at_pos]
                    ),
                    len(at_pos),
                )
        up = [m.receptions for m in group if m.delta >= MATERIAL_MOVE]
        down = [m.receptions for m in group if m.delta <= -MATERIAL_MOVE]
        tiers.append(
            TierResult(
                label=label,
                n=len(group),
                mean_delta=statistics.fmean(deltas),
                median_delta=statistics.median(deltas),
                mean_abs_delta=statistics.fmean([abs(d) for d in deltas]),
                material=sum(1 for d in deltas if abs(d) >= MATERIAL_MOVE),
                by_position=by_position,
                mean_receptions_up=statistics.fmean(up) if up else 0.0,
                mean_receptions_down=statistics.fmean(down) if down else 0.0,
                reception_corr=reception_corr,
            )
        )

    mid = [m for m in movers if 25 <= m.espn_rank <= 120]
    ordered = sorted(mid, key=lambda m: -m.delta)
    return RankDeltaReport(
        tiers=tiers,
        risers=ordered[:top_movers],
        fallers=list(reversed(ordered[-top_movers:])),
        population=len(ranked),
        excluded_beyond_horizon=beyond,
        excluded_unranked=unranked,
    )


def load_espn_projections(config: LeagueConfig) -> list[Any]:
    """This league's universe, scored by its own rules, straight from the ESPN adapter."""
    from ..adapters.espn import EspnAdapter

    with EspnAdapter() as adapter:
        return adapter.player_projections(config)
