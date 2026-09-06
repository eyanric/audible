"""The ordering layer: how a recommendation is scored, once the board is frozen.

WHAT THIS FIXES. `recommend` sorted by ``(not grab_now, vorp_rank, not fills_need)``.
``vorp_rank`` is a UNIQUE integer, so a key placed after it is never compared -- roster need
was computed correctly, published correctly, and then discarded at the moment of ordering.
Three separately-reported bugs were that one dead key: a second linebacker named with
IDP_FLEX full, a dry run drafting 10 WR and 2 RB, and a back recommended onto the same bye
as both backs already rostered.

Signals COMPOSE into one scalar instead of queueing behind a unique key:

    effective = base_value * marginal_start_factor(...) - bye_conflict_penalty(...)

BOTH TERMS ARE NOW LIVE, AND THE SCALAR REACHES BOTH SURFACES. The bye term was blocked by
`tests/test_byes.py`'s hard stop 2, which read "every number must be untouched by the join".
That invariant existed to stop bye data contaminating PROJECTIONS AND VALUE, and in that
form it is correct and still enforced -- narrowed to say so explicitly, and widened in
precision rather than in permission: the value engine still may not import the bye accessor,
byes are still not a field on any player model, and every projection, rank and value number
on a served row is still asserted byte-identical with and without the join. What may now
move is the SERVING-BOUNDARY ordering -- `effective_score` and The Call -- which is the one
thing byes were always supposed to inform.

WHERE THE LINE SITS. Making need and byes reach the sort is a CORRECTNESS fix: the tool did
not understand the situation. Tuning the weights to beat the market is an EDGE claim and
needs the replay harness, which does not exist. So every factor here is derived from slot
structure, from byes, or from one measured position-independent rate -- and nothing is
tuned to make a board look better.

THE BOARD IS NOT TOUCHED. This runs at the serving boundary, after `board.py`, `value/` and
`scoring/` have built, ranked and frozen the board. `qa_mutation_gate`'s `usage_in_sort`
protects the BOARD's ordering -- it mutates the pinned board fixture and is caught by a
check that walks the board asserting value never rises. Re-ordering `recommend`'s output is
a different layer and leaves `vorp_rank` exactly as the value engine set it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..config.schema import LeagueConfig

# Weeks in a regular season. Byes fall inside it; a player is absent for exactly one.
SEASON_WEEKS = 18

# Per-week probability that a drafted starter is unavailable, measured rather than assumed.
#
# Derived from the pinned 2025 data: every player in `ffc_adp_standard_8_2025.json` (a
# PRESEASON list, so selection cannot depend on who stayed healthy) resolved to
# `nflverse/player_stats_2025.parquet`, counting distinct regular-season weeks with a row
# against a 17-game season. Drafted-but-never-appeared counts as a missed season.
#
# THE JOIN VARIANT IS PART OF THE MEASUREMENT, because the numbers move with it. These are
# the two-stage resolver in `sim/adp_join.py` -- FFC name -> `ff_playerids` -> gsis_id, with
# a six-entry nickname alias table and position breaking same-name ties (n=201, 2025):
#
#   QB 3.00 games missed   RB 3.34   WR 3.45   TE 2.72   K 2.24   mean 3.19
#
# A naive exact-name join instead gives WR 3.88 and leaves the other four unchanged; the
# whole difference is two receivers FFC lists under nicknames (Hollywood Brown, Joshua
# Palmer) who read as never having played. An earlier revision of this comment recorded
# WR 3.80, which reproduces under neither variant and could not be sourced.
#
# ONE RATE, NOT ONE PER POSITION, AND THAT IS A FINDING. The brief asserted "RBs miss
# materially more than WRs". The 2025 data will not support a position term in either
# direction: RB 1.87 vs WR 3.31 at ADP <= 60, RB 2.58 vs WR 3.27 at 100, RB 3.49 vs WR 3.32
# at 150. The sign FLIPS with draft depth, which is what no stable effect looks like. One
# season is a small sample and "games missed" also captures benchings, so this is not
# evidence that WRs are frailer either -- it is evidence that a position-differentiated term
# is not supported by what is pinned. Differentiating anyway would be a coefficient
# asserting something the data does not.
#
# 3.19 games / 17 = 0.188. Used only to price DEPTH, never to move a starter.
WEEKLY_ABSENCE_RATE = 0.19

# What a player who cannot start in any week is worth. Not zero -- he is still a body who
# can be traded or promoted after an injury the model cannot see -- but close to it, and
# far enough below a startable player that value alone cannot promote him.
UNSTARTABLE_FACTOR = 0.05


def startable_slots(config: LeagueConfig, position: str) -> int:
    """How many starting slots one team could play *position* in (RB: 2 RB + FLEX = 3).

    Mirrors ``value.replacement._startable_slots`` deliberately rather than importing it:
    that one is a private helper of the value engine, and the value engine is upstream of
    the frozen board. Same rule, and the same reason -- a team that can start exactly one
    D/ST gains nothing from a second, which is why the wire holds D/ST9 all season.
    """
    return sum(
        1 for slot in config.starting_slots if position in config.slot_eligibility[slot]
    )


def dedicated_slots(config: LeagueConfig, position: str) -> int:
    """Slots ONLY this position can fill. The RB slots in ``RB, RB, FLEX`` -- so, two."""
    return sum(
        1
        for slot in config.starting_slots
        if tuple(config.slot_eligibility[slot]) == (position,)
    )


def marginal_start_factor(
    position: str,
    *,
    config: LeagueConfig,
    unfilled: Sequence[str],
    held_counts: Mapping[str, int],
) -> float:
    """In how many weeks would this player actually start, relative to a starter?

    A PURE DISCOUNT. It is never above 1.0 and it gives NO bonus for filling an empty slot,
    and both halves of that were learned the hard way.

    An earlier version returned 1.0 for "fills an unfilled starting slot" and discounted
    everyone else. That resurrected a bug this repo already had and already fixed:
    `tests/test_recommend_bench.py` pins the round-7 case where FLEX was filled by a backup
    tight end, so every receiver read as filling nothing and the best "need" left was the
    top defence at VORP #80 -- over a receiver 46 places better. `server/mcp.py` says it
    outright: an unfilled starting slot is only a CONSTRAINT once every remaining pick is
    committed to one; before that it is a preference. Rewarding emptiness turns the
    preference back into a constraint and drafts five tight ends and two defences.

    So emptiness earns nothing here. What the roster genuinely adds over the board is the
    other direction: once I hold MORE of a position than I could ever start, the next one
    starts in fewer and fewer weeks, and that is worth pricing. Whether a defence belongs
    in round 7 at all is a question about replacement level, and VORP already answers it.

    The cap at 1.0 is what makes this arithmetically incapable of floating a specialist up
    the board: nothing is ever multiplied above its own value.
    """
    slots = startable_slots(config, position)
    held = int(held_counts.get(position, 0))

    if held < slots:
        # Still short of the number I could start in a single week. No discount.
        return 1.0

    if slots <= 1:
        # A one-slot position I already hold: a second kicker, a second defence, a second
        # quarterback in a 1-QB league. He starts in approximately no weeks, whatever his
        # value says, because there is nowhere to play him.
        return UNSTARTABLE_FACTOR

    # Surplus at a multi-slot position. He starts when an incumbent is absent --
    # P(at least one of `slots` incumbents out in a given week) ...
    cover = 1.0 - (1.0 - WEEKLY_ABSENCE_RATE) ** slots
    # ... and only when the backups ahead of him are not already covering it.
    depth_index = max(0, held - max(1, dedicated_slots(config, position)))
    return min(1.0, cover / (1.0 + depth_index))


def _unfilled_count(
    entries: Iterable[Any], config: LeagueConfig, absent: frozenset[str]
) -> int:
    """Starting slots left empty once *absent* player ids are removed from the roster."""
    from .live import place_into_slots

    available = [e for e in entries if e.player_id not in absent]
    return sum(1 for _slot, who in place_into_slots(available, config) if who is None)


def bye_conflict_cost(
    entries: Sequence[Any],
    config: LeagueConfig,
    byes: Mapping[str, int],
) -> float:
    """What this roster's byes cost across the season. CONVEX in holes-per-week.

    THE LINEAR VERSION DOES NOT WORK, AND MEASURING IT IS HOW THAT WAS FOUND. Summing
    unfilled slot-weeks discriminates nothing, because the total is CONSERVED: every player
    is absent exactly one week, so whether those absences land in the same week or different
    ones only changes WHICH slots go empty, never how many slot-weeks are empty. Measured on
    a roster with two backs on week 13, a candidate sharing that bye and a candidate on an
    unshared one both scored +1. Identical, and obviously wrong.

    What actually makes stacking bad is that holes in ONE week compound. Losing both backs
    in week 13 empties both RB slots at once, with nothing on the roster able to cover
    either; losing one back in each of two weeks empties one slot twice, and the other back
    still plays. Same slot-weeks, very different lineups. So the per-week hole count is
    SQUARED: the second hole in a week costs more than the first, which is the "making a
    week unfillable is severe, merely stacking is mild" distinction expressed as arithmetic
    rather than as a constant.

    Counted against the roster's OWN no-bye baseline, so slots that are empty because the
    draft is half finished are not charged to byes. ``place_into_slots`` is the same
    placement the cockpit's roster panel shows, so the two cannot disagree about who fills
    what.
    """
    base = _unfilled_count(entries, config, frozenset())
    cost = 0.0
    for week in range(1, SEASON_WEEKS + 1):
        out = frozenset(
            e.player_id for e in entries if byes.get(str(e.team or "")) == week
        )
        if not out:
            continue
        holes = max(0, _unfilled_count(entries, config, out) - base)
        cost += float(holes * holes)
    return cost


def bye_conflict_penalty(
    entries: Sequence[Any],
    config: LeagueConfig,
    byes: Mapping[str, int],
    *,
    slot_week_points: float,
) -> float:
    """What this roster's bye collisions cost, in the same points units as the board.

    One hole for one week is worth ``slot_week_points`` -- derived per league from the
    board itself, not chosen. Beyond the first hole in a week the cost is superlinear; see
    :func:`bye_conflict_cost`.
    """
    return bye_conflict_cost(entries, config, byes) * slot_week_points


def marginal_bye_cost(
    entries: Sequence[Any],
    candidate: Any,
    config: LeagueConfig,
    byes: Mapping[str, int],
    *,
    base: float | None = None,
) -> float:
    """What ADDING *candidate* to this roster costs, in :func:`bye_conflict_cost` units.

    The roster-level cost is not itself an ordering signal -- it is the same number for every
    candidate, so subtracting it from all of them changes nothing. What discriminates is the
    DIFFERENCE one player makes, which is what this returns.

    NOT CLAMPED AT ZERO, DELIBERATELY. Clamping would assert that a player can never improve
    a roster's bye shape, and that is a claim rather than an observation. Measured instead:
    sweeping every position against all 18 weeks on the sim standard roster produces no
    negative marginal, so the clamp would be inert here anyway -- and if a covering player
    ever does score below zero, a small bonus for filling the roster's worst week is the
    behaviour this term exists to produce.

    ``base`` is the caller's cached roster-only cost. Passing it halves the work, and the
    caller has it because it is constant across every row on a poll.
    """
    if base is None:
        base = bye_conflict_cost(entries, config, byes)
    return bye_conflict_cost([*entries, candidate], config, byes) - base


def effective_score(
    base_value: float,
    factor: float,
    penalty: float,
) -> float:
    """The one scalar every signal composes into.

    ``base_value`` is clamped at zero by the caller: below replacement, VORP is negative and
    multiplying a negative by a discount would make it LARGER, ordering the tail backwards.
    """
    return base_value * factor - penalty
