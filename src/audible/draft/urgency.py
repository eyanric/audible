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

WHY NOT `survival()`. `live.survival()` SHORT-CIRCUITS on `opponent_picks_until_horizon`:
its first statement is `if not opponent_picks: return 1.0`. It does not divide by that
number -- the divisor is `slope = 1.0 + 0.3 * opponent_picks`, which is never zero -- so
there is no exception to catch and nothing that looks broken from the outside. Seat 8
of 8 in a snake drafts in back-to-back PAIRS -- 8/9, 24/25, 40/41, 56/57 -- so at the
first pick of every pair `opponent_picks = 0` and survival returns 1.0 for everyone. It
goes quiet at exactly the moment two picks are on the clock. This module does not fix it
and does not call it: it shows the subtraction instead, so a wrong number is a visibly
wrong number rather than a confident one.

WHAT THIS IS NOT. Nothing here enters the BOARD's sort. This module is imported by the
state builder and the MCP surface, never by `board.py`, `value/` or `scoring/` -- the board
is built, ranked and frozen before any of this is looked up. Same contract, and the same
mutation gate, as `draft/usage.py`.

It does order its own output, and saying "nothing here enters the sort" flatly is how that
got missed. The distinction is which sort: `vorp_rank` arrives already decided and leaves
untouched, and The Call selects from that frozen list. What it selects BY is
`effective_score`, computed in `server/state.py` from `draft/ordering.py` -- the same
scalar `recommend` sorts by, handed in on the candidate rows.
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
    # "?" is what `_recent_picks` writes for a pick whose player is not on the board -- an
    # ESPN id the bridge could not translate, most often. It is an absence of information,
    # not a position, and counting it as one produced "7 of the last 8 picks were ?" with
    # reach advice attached. Shown in the counts, never eligible to be the run.
    named = {k: v for k, v in counts.items() if k != "?"}
    if not named:
        return {"window": len(picks), "counts": counts, "run_position": None,
                "run_count": 0, "advice": None}
    pos, n = max(named.items(), key=lambda kv: (kv[1], kv[0]))
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
    """A starting slot: how many the league demands, how many are filled, and WHO can fill it.

    `eligible` is the league's own `slot_eligibility` for this slot. It is not decoration:
    without it every flex reads as universal, and a slot only a linebacker can fill hands
    the same credit to a kicker.
    """

    position: str
    required: int
    held: int
    eligible: frozenset[str] | None = None

    @property
    def short(self) -> int:
        return max(0, self.required - self.held)

    @property
    def fills(self) -> frozenset[str]:
        """Positions that can start in this slot. A slot with no declared eligibility is
        dedicated to the position it is named for -- which is what `QB`, `K` and `DEF` are."""
        return self.eligible if self.eligible is not None else frozenset({self.position})


def roster_needs(
    slots: Iterable[Mapping[str, Any]],
    eligibility: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, RosterNeed]:
    """Read the served roster block into per-position need. Visible, so it can be argued
    with: Eric must be able to see why The Call prefers a back and disagree.

    `eligibility` is `LeagueConfig.slot_eligibility`, and passing it is what makes this
    league-aware rather than league-shaped. BoyFun's `IDP_FLEX` takes DL/LB/DB and its
    `SUPER_FLEX` takes QB/RB/WR/TE; Danger Zone has neither. None of that can be inferred
    from the slot name.
    """
    elig = {str(k).upper(): frozenset(str(v).upper() for v in vals)
            for k, vals in (eligibility or {}).items()}
    out: dict[str, RosterNeed] = {}
    for s in slots:
        pos = str(s.get("slot") or "").upper()
        if not pos:
            continue
        out[pos] = RosterNeed(position=pos, required=int(s.get("total") or 0),
                              held=int(s.get("filled") or 0), eligible=elig.get(pos))
    return out


def _need_score(position: str, needs: Mapping[str, RosterNeed]) -> int:
    """How badly this position is wanted: 2 for a slot only he can fill, 1 for a shared one.

    IT ASKS THE LEAGUE WHO CAN FILL A SLOT rather than guessing from its name. The first
    version walked a hardcoded ("FLEX", "SUPER_FLEX", "IDP_FLEX") list and returned 1 if
    ANY of them was short, for ANY position -- so with only `IDP_FLEX` open on BoyFun a
    tight end scored the same as a linebacker, The Call named the tight end because value
    breaks the tie, and its own reason string said "TE still fills a flex" while the roster
    panel beside it read `IDP_FLEX: 0/1 short 1`. A required starting slot would never have
    been recommended for.
    """
    pos = position.upper()
    best = 0
    for need in needs.values():
        if need.short <= 0 or pos not in need.fills:
            continue
        # A slot only this position can fill is a harder constraint than a shared one:
        # someone else can take the flex, nobody else can take the kicker slot.
        best = max(best, 2 if len(need.fills) == 1 else 1)
    return best


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


def _arithmetic(adp: float | None, next_pick: int | None, gap: float | None) -> str:
    """The subtraction, or the specific reason there isn't one.

    THE TWO REASONS ARE NOT THE SAME REASON. This used to say "no ADP for this player"
    whenever the figure was missing -- including when the player had a perfectly good ADP
    and it was the SEAT that was unknown. On BoyFun that is the state right up to kickoff:
    Sleeper's `slot_to_roster_id` is an identity map that lies until the draft opens, so
    `my_next_pick` is None and every row read "no ADP" about players whose ADP was on the
    screen beside it. A wrong explanation for a missing number is worse than none, because
    it sends you looking in the wrong place at the one moment you cannot afford to.
    """
    if gap is not None:
        return f"ADP {adp} - next pick {next_pick} = {gap:+}"
    if next_pick is None:
        return ("MY SEAT IS NOT RESOLVED YET, so there is no next pick to subtract from. "
                "Sleeper does not publish a truthful draft order until the draft opens. "
                "This row is ordered by board value and roster need only.")
    return "no ADP for this player -- availability unknown, not high"


def _why_not(best: Mapping[str, Any], runner: Mapping[str, Any] | None) -> str | None:
    """One line on the candidate that came second, in the terms it lost on.

    NAMES THE DECIDING TERM. "board #21 against #20" is not a reason when the better board
    rank is the one that LOST -- which is the normal case now that a surplus player is
    demoted below someone ranked beneath him. Reading that without the scalar beside it is
    how you talk yourself back into the pick the tool just argued against.
    """
    if runner is None:
        return None
    line = (f"board #{runner['player'].get('vorp_rank')} against "
            f"#{best['player'].get('vorp_rank')}")
    if runner["need"] != best["need"]:
        line += (", and fills less of a roster hole" if runner["need"] < best["need"]
                 else ", and fills more of a roster hole but costs more value")
    elif runner["effective"] != best["effective"]:
        line += (f", and scores {runner['effective']:.0f} against "
                 f"{best['effective']:.0f} once the weeks he would actually start, and his "
                 f"bye, are priced in")
    return line


def the_call(
    candidates: Sequence[Mapping[str, Any]],
    *,
    next_pick: int | None,
    needs: Mapping[str, RosterNeed],
    available_entries: Sequence[Any],
) -> dict[str, Any]:
    """One named pick from the best ``TOP_N`` PICKABLE candidates, and the runner-up.

    It NEVER invents a candidate and NEVER reorders the board: `vorp_rank` arrives and leaves
    exactly as the value engine set it. What it chooses is which rows to look at and which
    one to name.

    THE FILTER IS THE FEATURE. A candidate the market says will still be there well after
    my next turn is not a pick, he is a later pick -- unless waiting costs a tier cliff.

    ORDERED BY `effective_score`, NOT BY `vorp_rank`, AND THAT IS THE FIX. Raw board rank
    was the final key here while `recommend`, reading the same pool, had already moved to
    the composed scalar. Measured on a reconstruction of the live BoyFun state -- every
    starting slot filled but K and DEF -- The Call named a second linebacker at board #20
    over a back at #21, because `need` was 0 for BOTH (the filled `IDP_FLEX` was registered
    correctly) and rank alone then decided. The linebacker's `marginal_start_factor` was
    0.05: he could start in approximately no weeks. `recommend` demoted him 379 to 19 on the
    same data. Need was never the broken term and the top-12 slice held the right answer at
    position 2; the ordering simply could not see surplus, because the number that prices
    surplus was dropped when these rows were built.

    `need` STAYS THE LEADING KEY. It is a different question from value -- "is there a slot
    only he can fill" -- and `marginal_start_factor` deliberately gives no bonus for filling
    an empty slot (see `draft/ordering.py`: rewarding emptiness drafts five tight ends and
    two defences). So the two do not substitute for one another, and the scalar is what
    breaks ties WITHIN a need tier rather than what replaces it.
    """
    # SLICED BY THE SAME NUMBER IT IS ORDERED BY, AND ONLY REAL CANDIDATES COUNT AGAINST
    # THE CAP. This took `candidates[:TOP_N]` -- the top twelve by raw board rank -- which
    # was coherent only while the sort's last key was also raw board rank. Once the ordering
    # moved to `effective_score`, slicing by VORP and then ranking by the scalar threw away
    # exactly the candidates the scalar would have ranked highest.
    #
    # MEASURED ON THE PINNED GREEN HOPE BOARD, holding four backs against three RB-startable
    # slots: this board's top is entirely running backs, so all twelve slice rows were the
    # same surplus position discounted to 0.1562, the best of them scoring 30.8 -- while
    # Jaxon Smith-Njigba sat at pool row 28 scoring 78.8 and was never looked at. `recommend`
    # sorts the whole pool and named him; The Call, on the page beside it, could not see him.
    # A cap on "the best N candidates" has to mean best BY THE TOOL'S OWN MEASURE, or it is a
    # filter that silently overrides the ranking it feeds.
    #
    # THE ELIGIBILITY TEST RUNS BEFORE THE CAP, NOT AFTER. Filtering afterwards spends the
    # twelve places on players who are then thrown away: a first attempt at this filled the
    # slice with deep board rows the market prices fifty picks past my turn, every one of
    # them dropped by `will_last`, leaving a single eligible candidate and no runner-up at
    # all. "Best twelve" has to mean twelve things that are actually pickable.
    #
    # `vorp_rank` breaks ties so the slice is deterministic, and the board itself is still
    # never reordered -- this chooses WHICH rows to consider, and `vorp_rank` arrives and
    # leaves exactly as the value engine set it.
    ordered = sorted(
        candidates,
        key=lambda p: (-float(p.get("effective_score") or 0.0), p["vorp_rank"]),
    )
    if not ordered:
        return {"pick": None, "runner_up": None, "considered": 0,
                "why_none": "no candidates on the board"}

    # `at_a_cliff` rescans the available pool per call, so it is asked only about players
    # `will_last` has already flagged -- the only ones whose answer can change anything --
    # and the walk stops as soon as the cap is met. Without both, this is a per-poll scan of
    # the whole board for every row on it.
    scored: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    considered = 0
    for p in ordered:
        if len(scored) >= TOP_N:
            break
        considered += 1
        pos = str(p.get("position") or "").upper()
        gap = survives_by(p.get("adp"), next_pick)
        # A player the market prices well past my next turn is skipped -- I can have him
        # later AND someone else now -- unless he is the last man above a cliff, where
        # waiting costs points rather than just patience.
        will_last = gap is not None and gap >= SURVIVAL_SAFE
        cliff = at_a_cliff(available_entries, str(p.get("id")), pos) if will_last else None
        if will_last and cliff is None:
            skipped.append({"name": p.get("name"), "survives_by": gap})
            continue
        scored.append({
            "player": p, "position": pos, "survives_by": gap, "cliff": cliff,
            "eligible": True, "will_last": will_last,
            "need": _need_score(pos, needs),
            "confidence": confidence(pos),
            # Absent means the caller did not attach it. 0.0 then makes every candidate tie
            # and `vorp_rank` decides, which is the pre-fix behaviour -- and the rendered
            # `effective_score` field reads 0.0 on every row, so a broken wiring is visible
            # on the page rather than silent.
            "effective": float(p.get("effective_score") or 0.0),
            "urgency": _urgency_tier(gap),
        })

    eligible = scored
    if not eligible:
        return {
            "pick": None, "runner_up": None, "considered": considered,
            "why_none": (f"every one of the {considered} candidates looked at is priced to "
                         f"last past pick {next_pick} and none is at a tier cliff -- take "
                         f"the best available at a position you actually need"),
        }

    # Roster hole first, then URGENCY, then the board's own value. Urgency has to be in
    # the ORDER and not only in the filter, and that is not a stylistic point: the first
    # version of this used the horizon purely to prune, and the pre-registered horizon
    # sensitivity gate caught it -- freezing `next_pick` to a constant produced an
    # identical Call at all four measured turns, because the top need-filler was eligible
    # either way. A horizon that only occasionally prunes is a horizon that is not really
    # being used, which is the "today's recommend with new columns bolted on" failure.
    eligible.sort(key=lambda s: (-s["need"], s["urgency"], -s["effective"],
                                 s["player"]["vorp_rank"]))
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
            "survival_arithmetic": _arithmetic(p.get("adp"), next_pick, s["survives_by"]),
            "survival_confidence": s["confidence"],
            "at_tier_cliff": None if cliff is None else
                f"{cliff.position}{cliff.after_rank}, {cliff.gap} pts below him",
            "fills_need": s["need"] > 0,
            # The ordering, published rather than implied. A recommendation whose reason
            # cannot be checked against the number that produced it is a recommendation you
            # have to take on trust at the one moment there is no time to.
            "effective_score": s["effective"],
            "marginal_start_factor": p.get("marginal_start_factor"),
            "bye_conflict_penalty": p.get("bye_conflict_penalty"),
            "bye_week": p.get("bye_week"),
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
    factor = best["player"].get("marginal_start_factor")
    if isinstance(factor, int | float) and factor < 1.0:
        why.append(f"and even HE is discounted to {factor:.2f} of his value -- I already "
                   f"hold more {best['position']} than I can start")
    penalty = best["player"].get("bye_conflict_penalty")
    if isinstance(penalty, int | float) and penalty > 0:
        why.append(f"costs {penalty:.0f} points of bye collision against this roster")

    cost = None
    if other_pos is not None:
        cost = (f"passing {other_pos['player'].get('name')} "
                f"({other_pos['position']}, board #{other_pos['player'].get('vorp_rank')})")

    if next_pick is None:
        # Say it once, at the top, rather than leaving the reader to infer it from a row of
        # nulls. Until the seat resolves this is a value-and-need ranking wearing the name
        # of an availability one.
        why.insert(0, "SEAT UNRESOLVED -- no availability arithmetic yet, "
                      "this is board value and roster need only")

    return {
        "pick": render(best),
        "runner_up": render(runner),
        "seat_resolved": next_pick is not None,
        "why_now": "; ".join(why) or "best available among those who will not last",
        "what_it_costs": cost,
        "why_not_the_runner_up": _why_not(best, runner),
        "considered": considered,
        # Capped: the walk can pass a long tail of players the market says will keep, and
        # a hundred names is not a reason, it is a wall of text on a sixty-second clock.
        "skipped_as_likely_to_last": skipped[:TOP_N],
        "roster_need": [
            {"slot": n.position, "required": n.required, "held": n.held, "short": n.short}
            for n in sorted(needs.values(), key=lambda n: n.position)
        ],
    }
