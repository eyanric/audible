"""ORDERING invariants -- defects 3 and 4, checked at EVERY pick of every simulated draft.

DEFECT 3. `recommend` sorted on `(not grab_now, vorp_rank, not fills_need)`. `vorp_rank` is a
unique, gapless integer, so the third key was never compared: roster need was computed
correctly, published correctly, and discarded at the moment of ordering. The B6 handoff
reports it naming a second linebacker with IDP_FLEX full and producing a 10-WR / 2-RB roster;
neither figure is recorded anywhere in this repository, so both are cited rather than asserted.

DEFECT 4. Byes were computed, rendered as a column, and consumed by nothing. The handoff
reports a dry run with no legal lineup in weeks 7, 8, 13 and 14 -- again cited, not asserted:
that run is not in the repository either.

WHY A PER-PICK CHECK AND NOT ANOTHER ARM. `sim/test_g_occ.py`, `test_g_bye.py` and
`test_g_need.py` already assert these properties -- 15 tests over three hand-built rosters
(`test_g_occ` and `test_g_bye` share one apiece; `test_g_need` has two). Those gates were
added AFTER the defects, in `77d2552`, and `sim/__init__.py` says they are built against the
broken code and expected to go red -- so they never guarded anything in production. These run
the same properties against the states the simulation actually reaches, at every one of the
seat's sixteen picks in every draft and every seed.

THE HARD PART IS NOT DETECTING A BAD PICK. It is that defect 3 makes no individually bad pick.
Every pick `(not grab_now, vorp_rank, not fills_need)` makes is the best available by board
rank, which is exactly what a reasonable ordering looks like. What is wrong is that it is
ALWAYS the best available by rank -- a key after a unique integer cannot ever be reached. So
`order_need_reaches_sort` is a check on the RUN, not on a pick: across a whole draft in which
needs existed throughout, an ordering that never once departed from board rank has a dead key,
whatever its individual picks looked like. That is a binary property of the ordering, not a
rate, and it is reported as one.

WHAT IS ASSERTED:

  order_occupancy         PER PICK. Never take a player who starts in NO week while a
                          non-scheduled starting slot sits empty.
  order_bye_feasible      per draft, over holes accumulated per pick: the roster keeps a legal
                          lineup in every week, OR the ordering priced byes -- and which.
  order_need_reaches_sort per draft. No key carrying roster need sits behind a unique key.
  order_legal_lineup      per draft. The finished roster can field a starting lineup.

THE OCCUPANCY CHECK IS THE NARROW FORM AND THAT IS DELIBERATE. See
`invariants.unstartable_pick`: the strong form the brief asks for would fail on correct code,
because `marginal_start_factor` is a pure discount that deliberately gives no bonus for
filling an empty slot, and rewarding emptiness is a bug this repo has already had and fixed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .invariants import ORDER, Ledger, legal_lineup, lineup_holes, unstartable_pick


@dataclass(frozen=True, slots=True)
class Held:
    """The minimum a roster entry needs to be placed into a slot and priced for byes.

    A stand-in for `DraftEntry` built from a `room.BoardRow`, because the room's rows are what
    the simulation actually drafts. `points` drives `place_into_slots`' greedy order and here it
    is the board's own rank inverted, so a better player places first -- the same relative order
    the production placement sees.
    """

    player_id: str
    name: str
    position: str
    team: str | None
    points: float

    @property
    def eligible_positions(self) -> frozenset[str]:
        return frozenset({self.position})


@dataclass
class DraftWatch:
    """One draft's worth of ordering invariants, plus what it needs to judge them.

    Holds the roster as it accumulates, because the room hands the chooser position COUNTS and
    unfilled SLOTS but not the players -- and a bye check needs the teams.
    """

    ledger: Ledger
    config: Any
    byes: Mapping[str, int]
    arm: str
    season: int
    seed: int
    held: list[Held] = field(default_factory=list)
    # (chosen board rank, best available board rank) per pick, for the dead-key check.
    rank_choices: list[tuple[int, int]] = field(default_factory=list)
    # Picks where the roster afterwards had an unfillable week. Whether that is a violation
    # depends on whether the ordering PRICED byes, which is the arm's business, not the pick's.
    bye_holes: list[dict[str, Any]] = field(default_factory=list)
    picks_seen: int = 0
    # The sort key tuples this ordering produced, and which of their positions carry SIGNAL
    # rather than being a terminal tiebreak. Empty for an arm that does not expose its sort;
    # `need_reaches_sort` then has nothing to judge and says so by not checking.
    sort_keys: list[tuple[Any, ...]] = field(default_factory=list)
    signal_keys: dict[int, str] = field(default_factory=dict)

    def scope(self, **extra: Any) -> Ledger:
        return self.ledger.scoped(
            arm=self.arm, season=self.season, seed=self.seed, **extra
        )

    def before_pick(
        self,
        overall: int,
        taken: Sequence[int],
        rows: Sequence[Any],
        *,
        unfilled: Sequence[str],
        counts: Mapping[str, int],
        picked: int,
    ) -> None:
        """Every ordering invariant that can be judged at the moment of the pick."""
        self.picks_seen += 1
        if picked is None or picked < 0 or picked >= len(rows):
            # The chooser declined and the room falls through to its bot cascade. That is a
            # finding about the ordering, counted by `ArmResult.calls`, and not a violation
            # here -- there is no recommendation to judge.
            return
        row = rows[picked]
        scope = self.scope(pick=overall, player=row.name, position=row.position)

        bad, why = unstartable_pick(self.config, row.position, counts, unfilled)
        scope.check(
            not bad, ORDER, "order_occupancy",
            f"pick {overall} took {row.name} ({row.position}) and {why}. This is the shape of "
            f"the 2026 defect: a second linebacker with IDP_FLEX full starts in no week, and "
            f"the ordering could not see it because the key that knew was never compared.",
            unfilled=sorted(set(unfilled)), counts=dict(counts),
        )

        best = min(
            (r.rank for i, r in enumerate(rows) if not taken[i]), default=row.rank
        )
        self.rank_choices.append((row.rank, best))

        self.held.append(
            Held(
                player_id=f"r{row.rank:04d}", name=row.name, position=row.position,
                team=row.team, points=float(len(rows) - row.rank),
            )
        )
        holes = lineup_holes(self.held, self.config, self.byes)
        if holes:
            self.bye_holes.append({"pick": overall, "weeks": sorted(holes), "player": row.name})

    def finish(self, *, prices_byes: bool) -> None:
        """The two per-DRAFT invariants, judged once the roster is complete.

        *prices_byes* says whether this arm's ordering consumed the bye term at all. It changes
        what an unfillable week MEANS: for an ordering that priced byes and took the player
        anyway, a hole is a considered trade and the brief asks only that it be reported. For
        one that never looked, a hole is defect 4.
        """
        scope = self.scope()
        ok, missing = legal_lineup(self.held, self.config)
        scope.check(
            ok, ORDER, "order_legal_lineup",
            "the finished roster cannot field a starting lineup at all. A prior room build "
            "left 34.8% of seats in this state while every draft-level statistic stayed "
            "green, because the positional totals were right and only the allocation across "
            "seats was wrong.",
            missing=missing, roster=[f"{h.position}:{h.name}" for h in self.held],
        )
        scope.check(
            not (self.bye_holes and not prices_byes), ORDER, "order_bye_feasible",
            f"this ordering does not price byes and produced {len(self.bye_holes)} pick(s) "
            f"after which the roster had no legal lineup in some week "
            f"({self.bye_holes[0]['weeks'] if self.bye_holes else []} first). Byes were "
            f"computed and rendered and consumed by nothing; that is defect 4.",
            holes=self.bye_holes[:4],
        )

    def need_reaches_sort(self) -> None:
        """Is a key carrying roster need REACHABLE in this ordering's sort? Defect 3.

        THE OBVIOUS VERSION OF THIS CHECK DOES NOT WORK AND WAS SHIPPED BROKEN FIRST. "Did the
        ordering ever depart from best-available board rank" sounds like the right question and
        is not: measured over 2024 seeds 0-3, the restored R3 sort departs on 9 of 63 picks and
        the check stayed green on every arm in the repo, including the defective one. Those
        departures are not evidence of a live key either -- every one falls at pick index 13-15
        and is a DEF, K or TE, which is the harness's own feasibility deadline firing, not the
        sort.

        The property is STRUCTURAL. Sort keys are compared left to right and stop at the first
        difference, so once a prefix is unique across the candidates nothing after it is ever
        consulted. `vorp_rank` is a unique gapless integer over any candidate set, so a signal
        key placed after it is unreachable -- not usually, never. That is checkable directly
        from the key tuples, and `dead_signal_key` is what checks it.
        """
        from .invariants import ORDER as _ORDER

        scope = self.scope()
        tuples, signal = self.sort_keys, self.signal_keys
        if not tuples:
            return
        dead = dead_signal_key(tuples, signal)
        scope.check(
            dead is None, _ORDER, "order_need_reaches_sort",
            f"the ordering places {dead[0] if dead else '?'} at key index "
            f"{dead[1] if dead else '?'}, after a key that is already unique across every "
            f"candidate. It can never be compared, so roster need is computed, published and "
            f"discarded at the moment of ordering. No individual pick looks wrong; that is "
            f"precisely how this defect hid.",
            dead_key=dead[0] if dead else None, index=dead[1] if dead else None,
        )


def watched(
    chooser: Callable[..., int],
    watch: DraftWatch,
) -> Callable[..., int]:
    """Wrap a room chooser so every pick it makes is judged as it is made.

    THE SEAM IS THE ROOM'S OWN. `simulate_draft` calls
    `chooser(overall, taken, rows, remaining=, unfilled=, counts=)` whenever the watched seat is
    on the clock, which is exactly the pre-pick state an ordering invariant needs: the pool, the
    roster shape and the pick number. Wrapping rather than editing `room.simulate_draft` keeps
    the room byte-identical for every arm that is not being watched.
    """

    def wrapped(
        overall: int,
        taken: Sequence[int],
        rows: Sequence[Any],
        *,
        remaining: int,
        unfilled: Sequence[str],
        counts: Mapping[str, int],
    ) -> int:
        picked = chooser(
            overall, taken, rows,
            remaining=remaining, unfilled=unfilled, counts=counts,
        )
        watch.before_pick(
            overall, taken, rows, unfilled=unfilled, counts=counts, picked=picked
        )
        return picked

    return wrapped


# Which arms price byes in their ordering. `no_bye` is B3's ablation, which neutralises
# `bye_conflict_penalty` when the rows are recomposed -- RELATED to R4 but not the same thing:
# R4 forces `bye_conflict_cost` itself to 0.0. `legacy_recommend` is R3, whose sort cannot
# reach any key after `vorp_rank` and so cannot reach the bye term either.
BYE_BLIND: frozenset[str] = frozenset({"no_bye", "legacy_recommend", "adp", "adp_board",
                                       "points_greedy", "bot", "shuffle"})


def prices_byes(arm: str) -> bool:
    return arm not in BYE_BLIND

def unreachable_after_unique(key_tuples: Sequence[tuple[Any, ...]]) -> int | None:
    """The index of the first sort key that can NEVER break a tie. None when every key is live.

    THIS IS DEFECT 3 STATED AS A PROPERTY OF THE SORT RATHER THAN OF ANY PICK, and it is the
    only formulation that catches it cleanly. `order_need_reaches_sort` -- "did the ordering
    ever depart from best-available board rank" -- is masked by `grab_now`: the historical sort
    is `(not grab_now, vorp_rank, not fills_need)` and its FIRST key is live, so it departs
    from rank often enough to look healthy while the third key is stone dead. Measured:
    `legacy_recommend` over a real 2024 draft departs from rank on plenty of picks and that
    check stayed green.

    What is actually wrong is structural. Sort keys are compared left to right and stop at the
    first difference, so once a prefix is UNIQUE across the candidates, nothing after it is ever
    consulted. `vorp_rank` is a unique gapless integer over any candidate set, so any key placed
    after it is unreachable -- not usually, not mostly, but never. Roster need was computed
    correctly, published correctly, and discarded at the moment of ordering.

    Returns the index of the first such key so a violation can name it.
    """
    if not key_tuples:
        return None
    width = min(len(k) for k in key_tuples)
    for i in range(width - 1):
        prefixes = [k[: i + 1] for k in key_tuples]
        if len(set(prefixes)) == len(prefixes):
            # Every candidate already differs by key i, so key i+1 onwards is never compared.
            return i + 1
    return None

def dead_signal_key(
    key_tuples: Sequence[tuple[Any, ...]], signal: Mapping[int, str]
) -> tuple[str, int] | None:
    """A key that CARRIES INFORMATION and can never be reached. Defect 3, exactly.

    `unreachable_after_unique` alone is not the invariant, and running it on both sorts is what
    shows why: it returns index 2 for the historical `(not grab_now, vorp_rank, not fills_need)`
    AND for production's `(not grab_now, -effective_score, vorp_rank)`. Both have an unreachable
    third key. Only one of them is a bug.

    The difference is WHAT is unreachable. Production's dead key is `vorp_rank`, placed last on
    purpose as a total order so the below-replacement tail keeps the board's own sequence -- a
    tiebreak that never ties is simply never needed. The historical sort's dead key is
    `fills_need`, which is the roster's opinion about whether the player can start. Losing a
    tiebreak costs nothing; losing the need signal produced a 10-WR / 2-RB roster.

    *signal* names the indices that carry information, so the check can tell the two apart
    rather than flagging every terminal tiebreak in the codebase.
    """
    dead = unreachable_after_unique(key_tuples)
    if dead is None:
        return None
    for index in sorted(signal):
        if index >= dead:
            return signal[index], index
    return None

def check_bye_term_is_live(ledger: Ledger, config: Any) -> None:
    """Defect 4 as a property of the TERM, not of a roster. Three things must all hold.

    "Byes were computed, displayed as a column, and consumed by nothing" has three failure
    points and only the third is about any particular draft:

      1. the term COMPUTES something -- a roster with two backs on one bye costs more than zero
      2. the term DISCRIMINATES -- a third back on that same bye costs more than one on a free
         week. The linear version failed exactly here: slot-weeks are conserved, so summing
         them scored both candidates +1 and the term was inert while looking alive.
      3. the term REACHES the sort -- `effective_score` actually subtracts the penalty

    Forcing `bye_conflict_cost` to 0.0 (R4, the real historical state) breaks 1 and 2. Dropping
    the penalty from `effective_score` breaks 3. Checking only a finished roster would catch
    neither reliably, because a roster can happen to have no bye collisions.
    """
    from audible.draft.ordering import (
        bye_conflict_cost,
        effective_score,
        marginal_bye_cost,
    )

    scope = ledger.scoped(check="bye_term")
    stacked = [
        Held("a", "Back A", "RB", "AAA", 300.0),
        Held("b", "Back B", "RB", "AAA", 290.0),
        Held("c", "Rec A", "WR", "BBB", 280.0),
        Held("d", "Rec B", "WR", "CCC", 270.0),
        Held("e", "Pass A", "QB", "DDD", 260.0),
        Held("f", "End A", "TE", "EEE", 250.0),
    ]
    byes = {"AAA": 13, "BBB": 7, "CCC": 9, "DDD": 5, "EEE": 11, "FFF": 4}

    cost = bye_conflict_cost(stacked, config, byes)
    scope.check(
        cost > 0.0, ORDER, "order_bye_term_live",
        f"`bye_conflict_cost` returned {cost} for a roster with two starting backs sharing "
        f"week 13. The bye term computes nothing, so byes are a displayed column and no more.",
        cost=cost,
    )

    same = marginal_bye_cost(stacked, Held("g", "Back C", "RB", "AAA", 240.0), config, byes)
    free = marginal_bye_cost(stacked, Held("h", "Back D", "RB", "FFF", 240.0), config, byes)
    scope.check(
        same > free, ORDER, "order_bye_term_live",
        f"a third back on the STACKED bye cost {same} and one on a free week cost {free}. The "
        f"term does not discriminate, which is the inert-but-alive shape the linear version "
        f"had: slot-weeks are conserved, so summing them scores both candidates identically.",
        stacked=same, free=free,
    )

    scope.check(
        effective_score(100.0, 1.0, 5.0) < effective_score(100.0, 1.0, 0.0),
        ORDER, "order_bye_term_reaches_sort",
        "`effective_score` does not subtract the bye penalty, so the term is computed and "
        "then discarded at the moment of ordering -- which is defect 4 exactly",
    )
