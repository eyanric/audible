"""Replacement level & VORP -- the analytical heart, derived purely from config.

Replacement level is computed by simulating every team filling its starting lineup
from the projection-ranked pool, respecting slot eligibility (FLEX / SUPER_FLEX /
IDP_FLEX are just slots with wider eligibility -- nothing is special-cased), and then
by handing out the bench rounds the league also drafts. A position's replacement level
is the best projected player nobody rosters: the first guy on the waiver wire.
VORP = projection - replacement.

The bench half is not decoration, it is the whole correctness story at D/ST and K.
"Best non-starter" is only the waiver wire in a league with no bench. League B drafts
16 rounds against 9 starting slots, so 7 of every team's 16 picks -- 56 players -- are
bench, and they are not on the wire. Counting them as replacement sets the baseline at
RB17 and WR25 when the real waiver line is around RB35 and WR52, which compresses every
skill-position VORP by 30-50 points. It does not compress D/ST or K, because nobody
rosters a backup D/ST: their baseline at starters+1 was right all along. The result was
a board that ranked the top D/ST 33rd overall and listed D/ST and K as its eleven
biggest "market underpricing" targets, in a league that drafts them last.

Because eligibility and slot lists come entirely from ``LeagueConfig``, the same code
produces Sleeper's superflex/IDP baselines and ESPN's shallow 1-QB baselines -- only
the config differs. That's why the same player is valued differently per league.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection


@dataclass(frozen=True, slots=True)
class ReplacementLevel:
    position: str
    points: float
    starters_used: int  # how many made a starting lineup
    rostered: int  # how many get drafted at all -- starters plus this position's bench share
    replacement_rank: int  # 1-based rank (within position) of the replacement player


@dataclass(frozen=True, slots=True)
class VorpEntry:
    projection: PlayerProjection
    vorp: float
    is_starter: bool


def _ranked(players: list[PlayerProjection]) -> list[PlayerProjection]:
    """Deterministic ranking: points desc, player_id asc as a stable tie-break."""
    return sorted(players, key=lambda p: (-p.points, p.player_id))


def assign_starters(players: list[PlayerProjection], config: LeagueConfig) -> set[str]:
    """Greedily fill all ``num_teams`` lineups; return the set of started player ids.

    Players are considered best-first. Each is placed in the *most specific* open slot
    they're eligible for (smallest eligibility set), so dedicated slots fill before
    flex slots and flex slots are left for players who can only go there.
    """
    slot_instances: list[frozenset[str]] = []
    for slot_name in config.starting_slots:
        eligible = frozenset(config.slot_eligibility[slot_name])
        slot_instances.extend(eligible for _ in range(config.num_teams))
    filled: list[bool] = [False] * len(slot_instances)

    starters: set[str] = set()
    for player in _ranked(players):
        best_idx = -1
        best_key: tuple[int, int, tuple[str, ...]] | None = None
        for idx, eligible in enumerate(slot_instances):
            if filled[idx] or not (player.eligible_positions & eligible):
                continue
            # Prefer the most specific open slot, and among equally specific slots prefer
            # the one matching the player's primary position. So a hybrid DL/LB whose
            # primary is LB fills an LB slot before a DL slot, and only spills to its
            # other eligibility (or a flex) once primary slots are full.
            key = (
                len(eligible),
                0 if player.primary_position in eligible else 1,
                tuple(sorted(eligible)),
            )
            if best_key is None or key < best_key:
                best_key, best_idx = key, idx
        if best_idx >= 0:
            filled[best_idx] = True
            starters.add(player.player_id)
    return starters


def _startable_slots(config: LeagueConfig, position: str) -> int:
    """How many starting slots ONE team could play *position* in (RB: 2 RB + FLEX = 3)."""
    return sum(1 for slot in config.starting_slots if position in config.slot_eligibility[slot])


def rostered_counts(
    players: list[PlayerProjection], config: LeagueConfig, starters: set[str]
) -> dict[str, int]:
    """How many of each position the league drafts: starters, plus its share of the bench.

    Bench depth goes only to positions a team could start more than one of, split by
    starter demand. Both halves of that rule are load-bearing and neither names a position:

    - **Only multi-slot positions.** A bench player is insurance for a starting slot. A
      team that can start exactly one D/ST gains nothing from a second one, so it drafts
      one and streams the rest -- which is why the waiver wire holds D/ST9 all season.
      Positions a team starts two or three of (RB, WR, TE through the flex) turn bench
      players into starters every week through byes and injuries, so they get hoarded.
    - **Not by VORP.** Allocating the bench by value looks obvious and is exactly wrong:
      replacement is *defined* as the best unrostered player, so VORP is 0.0 at every
      position's own baseline and ranking non-starters by it ranks them by how FLAT the
      curve is. K and D/ST have the flattest curves in football. Bench-by-VORP hands the
      bench to precisely the positions nobody benches, and it is self-confirming -- each
      D/ST it stashes pushes D/ST replacement deeper, which raises D/ST VORP, which
      stashes another. Measured on League B it converged on rostering 24 D/ST and 22 K.

    Checked against the market, which is the only ground truth available for "how many of
    each position actually gets drafted": ADP's first 128 picks hold 43 RB / 53 WR / 16 QB
    / 16 TE and zero D/ST or K (first D/ST at 132, first K at 131). This rule lands League B
    at RB35 / WR52 / QB8 / TE17 with D/ST and K held at 8 -- the same shape.
    """
    counts = {
        position: sum(
            1
            for p in players
            if p.primary_position == position and p.player_id in starters
        )
        for position in config.positions
    }
    bench = config.num_teams * config.replacement_bench_slots
    if bench <= 0:
        return counts

    depth = sorted(
        (pos for pos in counts if _startable_slots(config, pos) >= 2),
        key=lambda pos: (-counts[pos], pos),
    )
    demand = sum(counts[pos] for pos in depth)
    if not demand:
        return counts

    placed = 0
    for i, pos in enumerate(depth):
        # The last (smallest) position absorbs the rounding so the bench is spent exactly.
        share = bench - placed if i == len(depth) - 1 else round(bench * counts[pos] / demand)
        counts[pos] += share
        placed += share
    return counts


def replacement_levels(
    players: list[PlayerProjection],
    config: LeagueConfig,
    starters: set[str] | None = None,
) -> dict[str, ReplacementLevel]:
    """Per-position replacement level: the best player nobody rosters."""
    if starters is None:
        starters = assign_starters(players, config)
    rostered = rostered_counts(players, config, starters)

    levels: dict[str, ReplacementLevel] = {}
    for position in sorted(config.positions):
        at_pos = [p for p in _ranked(players) if p.primary_position == position]
        started = sum(1 for p in at_pos if p.player_id in starters)
        taken = rostered[position]
        levels[position] = ReplacementLevel(
            position=position,
            points=at_pos[taken].points if taken < len(at_pos) else 0.0,
            starters_used=started,
            rostered=taken,
            replacement_rank=taken + 1,
        )
    return levels


def compute_vorp(
    players: list[PlayerProjection], config: LeagueConfig
) -> tuple[list[VorpEntry], dict[str, ReplacementLevel]]:
    """Return (VORP entries sorted desc, replacement levels by position)."""
    starters = assign_starters(players, config)
    levels = replacement_levels(players, config, starters)
    entries = [
        VorpEntry(
            projection=p,
            vorp=p.points - levels[p.primary_position].points,
            is_starter=p.player_id in starters,
        )
        for p in players
    ]
    entries.sort(key=lambda e: (-e.vorp, e.projection.player_id))
    return entries, levels
