"""Opportunity cost at the serving boundary -- DISPLAYED and never ranked.

THE QUESTION THIS ANSWERS. The board answers "who is best?". On the clock the only
question that matters is "who is best *among those who will not survive to my next
turn?*". Those are different lists, and taking the wrong one converts a pick into
nothing: you could have had the scarce player AND the one who was going to last.

Measured on the completed DDAFFL draft, seat 8. At pick 57, with 14 opponents before
his next turn at 72, the board offered David Montgomery (VORP #40, ADP 46.9),
D'Andre Swift (#43, 48.7) and Josh Jacobs (#46, 27.1). Swift went at 58 -- the very
next pick -- and Montgomery at 63. Both were gone long before 72. That is what a pick
costs when availability is invisible.

WHY NOT `survival()`. `live.survival()` divides by `opponent_picks_until_horizon`. Seat 8
of 8 in a snake drafts in back-to-back PAIRS -- 8/9, 24/25, 40/41, 56/57 -- so at the
first pick of every pair `opponent_picks = 0` and survival returns 1.0 for everyone. It
goes quiet at exactly the moment two picks are on the clock. This module does not fix it
and does not call it: it shows the subtraction instead, so a wrong number is a visibly
wrong number rather than a confident one.

WHAT THIS IS NOT. Nothing here enters the sort. This module is imported by the state
builder and the MCP surface, never by `board.py`, `value/` or `scoring/` -- the board is
built, ranked and frozen before any of this is looked up. Same contract, and the same
mutation gate, as `draft/usage.py`.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# A candidate whose ADP is this far past my next pick is one the market says I can wait
# for. Threshold, not a model: it is the number the pre-registration fixed, and it is
# shown next to the arithmetic that produced it so it can be argued with.
SURVIVAL_SAFE = 10

# Positions where ADP does not predict points, from #36's leave-one-year-out fit against
# the `1/sqrt(n-1)` noise floor in `docs/pre-registration-repaired-instrument.md`:
#
#     RB  rho 0.547 vs floor 0.130   usable
#     WR      0.464        0.122     usable
#     TE      0.253        0.229     MARGINAL -- clears by 0.024, weak in 4 folds of 5
#     QB      0.187        0.204     below
#     DEF     0.103        0.289     below
#     K      -0.017        0.277     below
#
# A survival figure for one of these is arithmetic on a number that does not carry
# signal. It is still shown -- hiding it would hide the picks it was built for -- but it
# is marked everywhere it appears. An unmarked confident number at QB is the failure the
# reach annotation reproduced twice.
NOISE_FLOOR_POSITIONS = frozenset({"QB", "TE", "K", "DEF"})

# #36's cliff rule, unchanged: a gap counts only if it is large in absolute terms AND
# against the position's own normal step, or every position reports its own noise as
# structure.
_CLIFF_DEPTH = 40
_CLIFF_FACTOR = 3.0
_CLIFF_FLOOR = 8.0


def survives_by(adp: float | None, next_pick: int | None) -> float | None:
    """``adp - next_pick``. Positive means the market expects him to last that many picks
    past my next turn. None when either side is unknown -- never 0, which would read as
    "exactly on the bubble" rather than "not measured"."""
    if adp is None or next_pick is None:
        return None
    return round(adp - next_pick, 1)


def confidence(position: str | None) -> str:
    """``"low"`` where ADP is at or below its noise floor for this position."""
    return "low" if (position or "").upper() in NOISE_FLOOR_POSITIONS else "usable"


@dataclass(frozen=True, slots=True)
class Cliff:
    """A drop in VORP big enough to be structure rather than the position's normal step."""

    position: str
    after_rank: int      # positional rank of the last man ABOVE the drop
    gap: float           # VORP points lost by waiting past him


def position_cliffs(entries: Sequence[Any], position: str) -> list[Cliff]:
    """Cliffs among the AVAILABLE players at *position*, best-first by VORP.

    Entries must already be the available pool in board order. Returns at most five, which
    is #36's cap -- past that they are deep-bench noise (its QB run reported cliffs at
    overall #350 and #2977).
    """
    rows = [e for e in entries if getattr(e, "position", None) == position][:_CLIFF_DEPTH]
    if len(rows) < 6:
        return []
    drops = [rows[i].vorp - rows[i + 1].vorp for i in range(len(rows) - 1)]
    typical = statistics.median(drops)
    bar = max(_CLIFF_FACTOR * typical, _CLIFF_FLOOR)
    return [
        Cliff(position=position, after_rank=i + 1, gap=round(d, 1))
        for i, d in enumerate(drops)
        if d >= bar
    ][:5]


def next_cliff_after(
    entries: Sequence[Any], position: str, positional_rank: int
) -> Cliff | None:
    """The first cliff at or after *positional_rank*, or None."""
    return next(
        (c for c in position_cliffs(entries, position) if c.after_rank >= positional_rank),
        None,
    )


def at_a_cliff(entries: Sequence[Any], player_id: str, position: str) -> Cliff | None:
    """The cliff this player is the last man above, if he is one."""
    rows = [e for e in entries if getattr(e, "position", None) == position][:_CLIFF_DEPTH]
    rank = next((i + 1 for i, e in enumerate(rows) if e.player_id == player_id), None)
    if rank is None:
        return None
    return next((c for c in position_cliffs(entries, position) if c.after_rank == rank), None)


def detect_run(recent: Iterable[Mapping[str, Any]], window: int = 8) -> dict[str, Any]:
    """Positional distribution of the last *window* picks, and the run if there is one.

    THE RESPONSE TO A RUN IS USUALLY NOT TO JOIN IT. Nine picks spent on quarterbacks are
    nine not spent on backs and receivers, so the non-QB board gets CHEAPER while the run
    is on. Joining late is how you take the fourth-best remaining player at that position
    at a reach. The exception is a real tier cliff, which is why `cliff_gap` rides along:
    per #36 quarterback has exactly ONE cliff, at Allen, and then 21 flat ranks, so a QB
    run after Allen is almost never worth joining -- while tight end is a four-cliff
    staircase inside the top five at 13-16 points each.
    """
    picks = list(recent)[:window]
    counts: dict[str, int] = {}
    for p in picks:
        pos = str(p.get("position") or "?").upper()
        counts[pos] = counts.get(pos, 0) + 1
    if not picks:
        return {"window": 0, "counts": {}, "run_position": None, "run_count": 0,
                "advice": None}
    pos, n = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    # Half the window at one position is a run worth naming. Below that it is a draft.
    is_run = n * 2 >= len(picks) and n >= 3
    return {
        "window": len(picks),
        "counts": counts,
        "run_position": pos if is_run else None,
        "run_count": n if is_run else 0,
        "advice": (
            f"{n} of the last {len(picks)} picks were {pos}. A run makes every OTHER "
            f"position cheaper, so joining it late is usually how you reach. Join only "
            f"for a named tier cliff."
        ) if is_run else None,
    }


@dataclass(frozen=True, slots=True)
class RosterNeed:
    """Startable bodies held against starting slots required, per position."""

    position: str
    required: int
    held: int

    @property
    def short(self) -> int:
        return max(0, self.required - self.held)


def roster_needs(slots: Iterable[Mapping[str, Any]]) -> dict[str, RosterNeed]:
    """Read the served roster block into per-position need. Visible, so it can be argued
    with: Eric must be able to see why The Call prefers a back and disagree."""
    out: dict[str, RosterNeed] = {}
    for s in slots:
        pos = str(s.get("slot") or "").upper()
        if not pos:
            continue
        out[pos] = RosterNeed(position=pos, required=int(s.get("total") or 0),
                              held=int(s.get("filled") or 0))
    return out


def _need_score(position: str, needs: Mapping[str, RosterNeed]) -> int:
    """How badly this position is wanted. Direct slot first, then any flex that takes it."""
    direct = needs.get(position)
    if direct is not None and direct.short > 0:
        return 2
    for name in ("FLEX", "SUPER_FLEX", "IDP_FLEX"):
        flex = needs.get(name)
        if flex is not None and flex.short > 0:
            return 1
    return 0


def _urgency_tier(gap: float | None) -> int:
    """0 = the market takes him before my next turn, 1 = marginal, 2 = he will last.

    Buckets rather than the raw number on purpose. Ordering by raw `survives_by` would
    prefer whoever is going soonest regardless of value -- which takes the least valuable
    player in the room every time. The question is "best among those who will not last",
    so urgency separates the groups and the board's own value orders inside them.
    """
    if gap is None:
        return 1          # unpriced: available with UNKNOWN survival, not safe
    if gap < 0:
        return 0
    return 1 if gap < SURVIVAL_SAFE else 2


TOP_N = 12


def _why_not(best: Mapping[str, Any], runner: Mapping[str, Any] | None) -> str | None:
    """One line on the candidate that came second, in the terms it lost on."""
    if runner is None:
        return None
    line = (f"{runner['player'].get('name')} is board "
            f"#{runner['player'].get('vorp_rank')} against "
            f"#{best['player'].get('vorp_rank')}")
    if runner["need"] != best["need"]:
        line += (", and fills less of a roster hole" if runner["need"] < best["need"]
                 else ", and fills more of a roster hole but costs more value")
    return line


def the_call(
    candidates: Sequence[Mapping[str, Any]],
    *,
    next_pick: int | None,
    needs: Mapping[str, RosterNeed],
    available_entries: Sequence[Any],
) -> dict[str, Any]:
    """One named pick from the board's top ``TOP_N`` by VORP, and the runner-up it rejected.

    It NEVER invents a candidate and NEVER reorders the board: it filters and picks from a
    list handed to it in the board's own frozen order.

    THE FILTER IS THE FEATURE. A candidate the market says will still be there well after
    my next turn is not a pick, he is a later pick -- unless waiting costs a tier cliff.
    Everything else is ordered by roster need first and then by the board's own value,
    because among players who will NOT last, value is the whole question.
    """
    pool = list(candidates)[:TOP_N]
    if not pool:
        return {"pick": None, "runner_up": None, "considered": 0,
                "why_none": "no candidates on the board"}

    scored = []
    for p in pool:
        pos = str(p.get("position") or "").upper()
        gap = survives_by(p.get("adp"), next_pick)
        cliff = at_a_cliff(available_entries, str(p.get("id")), pos)
        # A player the market prices well past my next turn is skipped -- I can have him
        # later AND someone else now -- unless he is the last man above a cliff, where
        # waiting costs points rather than just patience.
        will_last = gap is not None and gap >= SURVIVAL_SAFE
        eligible = (not will_last) or (cliff is not None)
        scored.append({
            "player": p, "position": pos, "survives_by": gap, "cliff": cliff,
            "eligible": eligible, "will_last": will_last,
            "need": _need_score(pos, needs),
            "confidence": confidence(pos),
        })

    for s2 in scored:
        s2["urgency"] = _urgency_tier(s2["survives_by"])

    eligible = [s for s in scored if s["eligible"]]
    if not eligible:
        return {
            "pick": None, "runner_up": None, "considered": len(pool),
            "why_none": (f"every candidate in the top {TOP_N} is priced to last past pick "
                         f"{next_pick} and none is at a tier cliff -- take the best "
                         f"available at a position you actually need"),
        }

    # Roster hole first, then URGENCY, then the board's own value. Urgency has to be in
    # the ORDER and not only in the filter, and that is not a stylistic point: the first
    # version of this used the horizon purely to prune, and the pre-registered horizon
    # sensitivity gate caught it -- freezing `next_pick` to a constant produced an
    # identical Call at all four measured turns, because the top need-filler was eligible
    # either way. A horizon that only occasionally prunes is a horizon that is not really
    # being used, which is the "today's recommend with new columns bolted on" failure.
    eligible.sort(key=lambda s: (-s["need"], s["urgency"], s["player"]["vorp_rank"]))
    best = eligible[0]
    other_pos = next((s for s in eligible[1:] if s["position"] != best["position"]), None)
    runner = eligible[1] if len(eligible) > 1 else None

    def render(s: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if s is None:
            return None
        p = s["player"]
        cliff: Cliff | None = s["cliff"]
        return {
            "id": p.get("id"), "name": p.get("name"), "position": s["position"],
            "board_rank": p.get("vorp_rank"),
            "platform_rank": p.get("platform_rank"),
            "adp": p.get("adp"),
            "survives_by": s["survives_by"],
            "survival_arithmetic": (
                f"ADP {p.get('adp')} - next pick {next_pick} = {s['survives_by']:+}"
                if s["survives_by"] is not None else
                "no ADP for this player -- availability unknown, not high"
            ),
            "survival_confidence": s["confidence"],
            "at_tier_cliff": None if cliff is None else
                f"{cliff.position}{cliff.after_rank}, {cliff.gap} pts below him",
            "fills_need": s["need"] > 0,
        }

    why = []
    if best["need"] == 2:
        why.append(f"fills an empty {best['position']} starting slot")
    elif best["need"] == 1:
        why.append(f"{best['position']} still fills a flex")
    if best["cliff"] is not None:
        why.append(f"last man above a {best['cliff'].gap}-point {best['position']} cliff")
    if best["survives_by"] is not None and best["survives_by"] < 0:
        why.append(f"the market takes him {abs(best['survives_by'])} picks BEFORE my next turn")
    elif best["survives_by"] is not None:
        why.append(f"only {best['survives_by']} picks of cushion past my next turn")
    if best["confidence"] == "low":
        why.append(f"ADP does not predict points at {best['position']} -- "
                   f"this figure is low confidence")

    cost = None
    if other_pos is not None:
        cost = (f"passing {other_pos['player'].get('name')} "
                f"({other_pos['position']}, board #{other_pos['player'].get('vorp_rank')})")

    return {
        "pick": render(best),
        "runner_up": render(runner),
        "why_now": "; ".join(why) or "best available among those who will not last",
        "what_it_costs": cost,
        "why_not_the_runner_up": _why_not(best, runner),
        "considered": len(pool),
        "skipped_as_likely_to_last": [
            {"name": s["player"].get("name"), "survives_by": s["survives_by"]}
            for s in scored if s["will_last"] and s["cliff"] is None
        ],
        "roster_need": [
            {"slot": n.position, "required": n.required, "held": n.held, "short": n.short}
            for n in sorted(needs.values(), key=lambda n: n.position)
        ],
    }
