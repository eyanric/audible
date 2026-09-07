"""TASK B6 -- the checks that catch the four defects that actually cost drafts.

WHY THIS EXISTS, and why it is not more of what B1-B5 built. Five sessions built an OUTCOME
measurement: draft a board, score the roster, compare arms, quote an interval. It answers one
question -- is the ordering good -- and it answers it weakly, because five season-clusters at
four degrees of freedom cannot resolve most of what it is asked.

It cannot see a single one of the four defects that actually cost real drafts:

  1. SEAT. The cockpit served `my_slot: 1` for hours while the live pick order said 6.
  2. SYNC. `mDraftDetail` returned clean 304s through a live draft while picks accumulated.
  3. NEED. `recommend` sorted on `(not grab_now, vorp_rank, not fills_need)` and `vorp_rank`
     is a unique integer, so the third key was never compared.
  4. BYES. Computed, displayed, consumed by nothing.

EVERY ONE OF THOSE IS AN INVARIANT VIOLATION, NOT AN EFFECT SIZE. One occurrence is a bug.
They need no clusters, no intervals and no statistical power -- they need a check that runs at
every decision point and fires the first time it is wrong. An interval around a defect rate is
a category error: it invites "the rate is not significantly different from zero" about a thing
that either happened or did not.

So nothing in this module reports a rate. `Ledger` counts CHECKS (so a checker that silently
stops running is visible) and collects VIOLATIONS (each with the season, seed and pick that
reproduces it). There is no mean, no interval, and deliberately no denominator on the
violation side.

THE ACCEPTANCE CRITERION IS FALSIFIABILITY, and it is the whole session. An invariant nobody
has watched fail is a comment. Each of the four is proven by RESTORING THE REAL HISTORICAL
DEFECT and requiring the check to fire -- not a synthetic mutation, the actual code:

  R1  `resolve_slot` returns the pin before consulting the derivation.
  R2  the ETag cache writes only on a 200, against a frozen-tag sequence.
  R3  the tuple sort `(not grab_now, vorp_rank, not fills_need)`.
  R4  `bye_conflict_cost` forced to 0.0.

`sim/test_g_b6.py` carries all four. If one of them cannot be made to fail, the invariant it
guards does not work and does not ship.

STRICT BY DEFAULT. A run exits non-zero on the first violation. Survey mode
(`Ledger(strict=False)`) exists for exactly one purpose -- counting how many DISTINCT
violations exist before any are fixed -- and it is labelled in the artifact wherever it was
used, because a survey-mode run that looks like a strict one is a green check over a red tree.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# The four families, so a report can say WHERE the harness is thin rather than only how many
# checks it ran. A family with a large check count and no violations says something quite
# different from one with no checks at all, and only naming them makes the difference visible.
SEAT = "seat"
SYNC = "sync"
ORDER = "order"
EXEC = "exec"
FAMILIES: tuple[str, ...] = (SEAT, SYNC, ORDER, EXEC)


class InvariantViolation(AssertionError):
    """Raised the first time an invariant fails, unless the ledger is in survey mode.

    An `AssertionError` rather than a bare `Exception` so a gate can `pytest.raises` it
    without catching every unrelated failure in the same block.
    """

    def __init__(self, violation: Violation) -> None:
        super().__init__(violation.describe())
        self.violation = violation


@dataclass(frozen=True, slots=True)
class Violation:
    """One defect, with everything needed to reproduce it.

    `repro` is the load-bearing field and it is not decoration. A violation reported as a
    count is a rumour: B2's headline was retracted because nobody could re-derive it, and the
    fix was not a better number but a recorded seed. Anything here must be enough to re-run
    the single unit that produced it -- season, seed and pick for an ordering check, the
    response sequence for a sync one.
    """

    family: str
    kind: str
    detail: str
    repro: Mapping[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        where = " ".join(f"{k}={v!r}" for k, v in sorted(self.repro.items()))
        return f"[{self.family}/{self.kind}] {self.detail}" + (f"  ({where})" if where else "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "kind": self.kind,
            "detail": self.detail,
            "repro": dict(self.repro),
        }


@dataclass
class Ledger:
    """Counts checks, collects violations, and stops the run on the first one.

    THE CHECK COUNT IS A GATE IN ITS OWN RIGHT. A checker that silently stops executing is
    indistinguishable from a clean run if only violations are reported, and that is not
    hypothetical: a prior review of this repo found that no gate in `sim/` ever executed the
    artifact producers, so a whole family of assertions had been passing without running. G2
    reads `checks` and `by_family` for exactly that reason.
    """

    strict: bool = True
    violations: list[Violation] = field(default_factory=list)
    by_family: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FAMILIES, 0))
    # Context every violation raised through this ledger inherits -- the season and seed of
    # the draft being replayed. Set once per unit rather than threaded through every call site,
    # because a repro missing its seed is not a repro.
    context: dict[str, Any] = field(default_factory=dict)

    def scoped(self, **context: Any) -> Ledger:
        """A view of this ledger with extra repro context, sharing ONE set of counters.

        Sharing rather than forwarding, and the difference is a bug I wrote first: a scoped
        ledger that kept its own counters AND walked up to the parent's counted every check
        twice, which would have inflated the one number G2 reads. There is exactly one set of
        counters, held by the root, and a scope is only a different `context`.
        """
        clone = Ledger(strict=self.strict)
        clone.violations = self.violations
        clone.by_family = self.by_family
        clone._counter = self._counter
        clone.context = {**self.context, **context}
        return clone

    # One-element list so every scope shares the same mutable cell. A plain int would be
    # rebound per scope and the root would never see a scoped check.
    _counter: list[int] = field(default_factory=lambda: [0], repr=False, compare=False)

    @property
    def checks(self) -> int:
        return self._counter[0]

    def check(
        self, ok: bool, family: str, kind: str, detail: str, **repro: Any
    ) -> bool:
        """Record that an invariant was EVALUATED, and whether it held.

        Counting on both paths is the point. `check(True, ...)` is not a no-op: it is the
        evidence that the invariant ran at all, which is what separates "no violations" from
        "no checks".
        """
        if family not in FAMILIES:
            raise ValueError(f"unknown invariant family {family!r}; expected one of {FAMILIES}")
        self._bump(family)
        if ok:
            return True
        violation = Violation(
            family=family, kind=kind, detail=detail, repro={**self.context, **repro}
        )
        self.violations.append(violation)
        if self.strict:
            raise InvariantViolation(violation)
        return False

    def _bump(self, family: str) -> None:
        self._counter[0] += 1
        self.by_family[family] = self.by_family.get(family, 0) + 1

    @property
    def clean(self) -> bool:
        return not self.violations

    def summary(self) -> dict[str, Any]:
        """What the artifact records. No rates, and that is deliberate -- see the docstring."""
        return {
            "mode": "strict" if self.strict else "SURVEY (violations do not stop the run)",
            "checks_executed": self.checks,
            "checks_by_family": dict(self.by_family),
            "violations": [v.as_dict() for v in self.violations],
            "violation_count": len(self.violations),
            "distinct_kinds": sorted({v.kind for v in self.violations}),
        }

    def report(self) -> str:
        lines = [
            f"invariants: {self.checks} checks, {len(self.violations)} violation(s)",
            "  by family: "
            + "  ".join(f"{f}={self.by_family.get(f, 0)}" for f in FAMILIES),
        ]
        if not self.strict:
            lines.append("  MODE: SURVEY -- violations were collected, not enforced")
        for violation in self.violations:
            lines.append("  " + violation.describe())
        return "\n".join(lines)


# --- ordering invariants -----------------------------------------------------------------
#
# These run at every WATCHED pick of every simulated draft -- the seat's own sixteen, not
# all 128, because a chooser is consulted only when its seat is on the clock -- and against
# the state the simulation actually reached. That is the difference from `test_g_occ`,
# `test_g_bye` and `test_g_need`, which check the same properties over three hand-built
# rosters between them: a situation someone imagined is a situation someone can fail to
# imagine. Those gates were also added AFTER these defects and `sim/__init__.py` says they
# are built against the broken code and expected to go red, so they never guarded production.


def startable(config: Any, position: str) -> int:
    """How many starting slots this league could play *position* in.

    Imported behaviour, not reimplemented behaviour: this delegates to the production helper
    so that a change to slot eligibility cannot make the invariant and the code it guards
    disagree. G4 is the gate on that.
    """
    from audible.draft.ordering import startable_slots

    return startable_slots(config, position)


def eligible_for(config: Any, position: str, slot: str) -> bool:
    return position in config.slot_eligibility.get(slot, ())


# Slots the ROOM fills by schedule and by deadline rather than by the ordering. K and D/ST are
# not on the board at all in `room.fit_room`'s measured regime -- every seat draws a target pick
# for each and takes one when it arrives -- so they sit empty for most of every draft in every
# arm, including the ones that are behaving perfectly. Counting them as "a starting slot is
# empty" makes the occupancy check fire on correct code at pick 75 of every draft, which is
# measured: the `real` arm tripped it five times in one 2024 draft (season 2024, seed 0), and every
# one of the five had ONLY scheduled slots open -- four at `['DEF', 'K']` and one at `['DEF']`.
SCHEDULED_SLOTS: frozenset[str] = frozenset({"K", "DEF", "DST", "D/ST"})


def unstartable_pick(
    config: Any, position: str, counts: Mapping[str, int], unfilled: Sequence[str]
) -> tuple[bool, str]:
    """Would this pick start in NO week, while a starting slot sits empty?

    THE STRONG FORM OF THIS INVARIANT IS WRONG AND WOULD FIRE ON CORRECT CODE, which is worth
    stating because the brief asks for the strong form. "Never take a position whose slots are
    full while any slot is empty" would forbid the round-7 case `tests/test_recommend_bench.py`
    pins: FLEX filled by a backup tight end, every receiver reading as filling nothing, and the
    best remaining "need" the top defence at VORP #80 over a receiver 46 places better.
    `marginal_start_factor` is deliberately a PURE DISCOUNT with no bonus for emptiness for
    exactly that reason, and an invariant that contradicts it would be asserting a policy the
    code has already rejected on evidence.

    So the check is the narrow, undeniable case, and it is the one the real defects were:
    a player who starts in NO week -- every slot he is eligible for already full -- taken while
    some slot he cannot fill is still empty. A second linebacker with IDP_FLEX full. A second
    quarterback in a 1-QB league. Those are not preferences; there is nowhere to play him.

    AND EVEN THAT NEEDED CALIBRATING AGAINST A REAL RUN. The first version counted K and D/ST
    among the empty slots and fired five times on the `real` arm in a single 2024 draft, every
    time with `unfilled == ['DEF', 'K']`. Those slots are not the ordering's to fill -- the room
    schedules them -- so they are excluded by `SCHEDULED_SLOTS`. An invariant is only worth
    having once it has been run against code known to be correct and found silent.
    """
    slots = startable(config, position)
    held = int(counts.get(position, 0))
    if held < slots:
        return False, ""
    open_elsewhere = [
        s for s in unfilled
        if not eligible_for(config, position, s) and s not in SCHEDULED_SLOTS
    ]
    if not open_elsewhere:
        return False, ""
    return True, (
        f"{position} starts in no week (holds {held} of {slots} startable slots) while "
        f"{sorted(set(open_elsewhere))} sit empty"
    )


def lineup_holes(entries: Sequence[Any], config: Any, byes: Mapping[str, int]) -> dict[int, int]:
    """Week -> starting slots this roster cannot fill, ABOVE its own no-bye baseline.

    Delegates the placement to `live.place_into_slots`, which is the same assignment the
    cockpit's roster panel renders, so the invariant and the screen cannot disagree about who
    fills what. Counting above the roster's own baseline is what stops a half-finished draft
    reading as a bye catastrophe -- an empty slot in round 3 is an empty roster, not a bye.
    """
    from audible.draft.live import place_into_slots

    def unfilled_with(absent: frozenset[str]) -> int:
        available = [e for e in entries if e.player_id not in absent]
        return sum(1 for _slot, who in place_into_slots(available, config) if who is None)

    base = unfilled_with(frozenset())
    out: dict[int, int] = {}
    for week in range(1, 19):
        absent = frozenset(
            e.player_id for e in entries if byes.get(str(getattr(e, "team", "") or "")) == week
        )
        if not absent:
            continue
        holes = unfilled_with(absent) - base
        if holes > 0:
            out[week] = holes
    return out


def legal_lineup(entries: Sequence[Any], config: Any) -> tuple[bool, list[str]]:
    """Can this roster field a full starting lineup at all, byes aside? Plus what is missing.

    The end-of-draft bar, and it is 100%. A prior room build left 34.8% of seats unable to
    start a lineup while every draft-level statistic stayed green, because every statistic was
    a draft-level aggregate and the positional TOTALS were right -- only the allocation across
    seats was wrong (`sim/room.py:1020`). An aggregate cannot see that; a per-seat invariant can.

    SCHEDULED SLOTS ARE EXCLUDED HERE FOR THE SAME REASON THEY ARE IN `unstartable_pick`, and
    leaving them in was an inconsistency an adversarial review found by widening the sweep. At
    seeds 0-19 over 2021-2025 the `real` arm went red four times, every one a bare ['DEF'] or
    ['K'] gap -- the exact class the occupancy check already excludes, because the room fills
    those by schedule and by the feasibility deadline rather than by the ordering. Applying the
    rule to one check and not the other left the harness's own narrow default sweep as the only
    thing keeping it green.
    """
    from audible.draft.live import place_into_slots

    missing = [
        slot for slot, who in place_into_slots(list(entries), config)
        if who is None and slot not in SCHEDULED_SLOTS
    ]
    return not missing, missing


def write_violations(path: Any, ledger: Ledger) -> None:
    """The violation ledger beside the run artifact, so a repro survives the terminal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger.summary(), indent=1, sort_keys=True) + "\n", "utf-8")


def divergence_from_rank(picks: Iterable[tuple[int, int]]) -> int:
    """How often an ordering picked something other than the best remaining board rank.

    THE SIGNATURE OF A DEAD SORT KEY, and the only way to see defect 3 without knowing in
    advance which player was wrong. `(not grab_now, vorp_rank, not fills_need)` is not wrong
    on any single pick you can point at -- every pick it makes is the best available by rank,
    which looks entirely reasonable. What is wrong is that it is ALWAYS the best available by
    rank, because a key after a unique integer is never compared. Zero divergences across a
    whole run, while needs existed the whole time, is the defect.

    Takes (chosen_rank, best_available_rank) pairs; returns how many differ.
    """
    return sum(1 for chosen, best in picks if chosen != best)
