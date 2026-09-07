"""SEAT invariants -- defect 1, and it happened on the ESPN path.

WHAT HAPPENED. On 2026-09-07 the Green Hope commissioner re-drew the pick order. ESPN's
`draftSettings.pickOrder` said seat 6. The league config said 1. The cockpit served 1 for
hours, logging the disagreement it was ignoring once per poll into a file nobody was reading,
and every timing number on the board -- need, survival, the whole clock -- was computed for a
seat that was not mine.

THERE ARE TWO RESOLVERS AND ONLY ONE OF THEM IS `resolve_slot`. `identity.resolve_slot` is
Sleeper's. The ESPN path never calls it: `sync.EspnSync._identity` is a second, hand-written
copy of the same three-tier ladder. That matters more than it looks, because the failure was
an ESPN failure -- an invariant that drove `resolve_slot` alone would have watched the wrong
function and reported green. Everything here is therefore run against BOTH, from one table of
cases, and a divergence between them is itself a violation.

WHAT IS ASSERTED, and one of these fails on current main:

  seat_precedence     a live derivation beats a config pin -- and an operator's --slot
                      beats both, and a null derivation carries the pin. ONE kind over
                      seven cases; `seat_override` and `seat_carried` are situations in
                      the table, not separate kinds.
  seat_source_honest  the source names the path that actually produced the value, so a
                      carried pin is distinguishable from a live answer
  seat_bad_order      an out-of-range derivation is refused and the pin carries
  seat_conflict_seen  a pin that disagrees with a live seat is surfaced WHERE A PERSON LOOKS
  seat_parity         the two resolvers agree, case for case
  seat_frozen         once drafting, the seat does not move

`seat_conflict_seen` is the one that fails, and it fails on main rather than under a
restoration. `Identity.seat_conflict` exists, is correct, and has exactly one production
reader -- a `log.error` in `service.py`. It reaches no API field and no rendered element.
(`EspnAdapter.verify_structure` does emit a draft_slot drift row comparing the pin against
the live seat, so the disagreement is not unreportable everywhere in the codebase -- it is
unreportable in the COCKPIT, which is the thing open during a draft.) The 2026-09-07
failure produced that log line once per poll for hours and changed nothing, which is the whole
argument for the check: the state was OBSERVABLE and was not OBSERVED. Reported, not fixed --
the fix is outside `sim/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .invariants import SEAT, Ledger

# The eight-team league the cockpit actually runs, so "out of range" means what it means live.
TEAMS = 8
MY_SWID = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
MY_TEAM_ID = 3


@dataclass(frozen=True, slots=True)
class SeatCase:
    """One seat situation, expressed platform-neutrally so both resolvers can be fed it.

    `pick_order` is the ESPN shape (team ids in seat order) and `draft_order` the Sleeper one
    (user id -> slot). Both are derived from `derived`, so a case cannot accidentally describe
    two different situations to the two resolvers -- which is the only way a parity check
    between them means anything.
    """

    name: str
    derived: int | None
    pin: int | None
    override: int | None
    expect_slot: int | None
    expect_source: str
    why: str
    # Can the ESPN side express this case at all? `espn_slot_by_team` enumerates `pickOrder`
    # from 1, so a team can never land on slot 0 no matter what the commissioner sends. A
    # Sleeper `draft_order` CAN carry a literal 0. Feeding the ESPN resolver a case its input
    # shape cannot represent produced four violations on my first run -- against my own test
    # construction, not against production. A harness that reports its own bugs as defects in
    # the code it watches is worse than no harness.
    espn: bool = True


def cases() -> tuple[SeatCase, ...]:
    """The table. Every row is a situation the cockpit can actually be in."""
    from audible.draft.identity import (
        SOURCE_CONFIG_PIN,
        SOURCE_DRAFT_ORDER,
        SOURCE_OVERRIDE,
        SOURCE_UNRESOLVED,
    )

    return (
        SeatCase(
            "green_hope", derived=6, pin=1, override=None,
            expect_slot=6, expect_source=SOURCE_DRAFT_ORDER,
            why="THE 2026-09-07 FAILURE. Live says 6, the pin says 1; the live seat must win.",
        ),
        SeatCase(
            "agreeing", derived=4, pin=4, override=None,
            expect_slot=4, expect_source=SOURCE_DRAFT_ORDER,
            why="No disagreement. The source must still name the live path, not the pin.",
        ),
        SeatCase(
            "pre_draft", derived=None, pin=2, override=None,
            expect_slot=2, expect_source=SOURCE_CONFIG_PIN,
            why="Silence never contradicts a pin. The pin carries -- and says it is carrying.",
        ),
        SeatCase(
            "operator_override", derived=6, pin=1, override=2,
            expect_slot=2, expect_source=SOURCE_OVERRIDE,
            why="An operator who types a seat has said something the tool may not second-guess.",
        ),
        SeatCase(
            "out_of_range_high", derived=TEAMS + 1, pin=5, override=None,
            expect_slot=5, expect_source=SOURCE_CONFIG_PIN,
            why=(
                "A nine-entry pickOrder in an eight-team league. `compute_view` RAISES on a "
                "slot outside 1..teams and `build_state` does not guard it, so an unrefused "
                "derivation is a 500 on every /api/state for as long as the bad body persists."
            ),
        ),
        SeatCase(
            "out_of_range_zero", derived=0, pin=5, override=None,
            expect_slot=5, expect_source=SOURCE_CONFIG_PIN,
            why="Slot 0 reads as 'me' and quietly attributes the entire room to my roster.",
            espn=False,
        ),
        SeatCase(
            "nothing_at_all", derived=None, pin=None, override=None,
            expect_slot=None, expect_source=SOURCE_UNRESOLVED,
            why="A slot invented when it cannot be derived is the slot=0 bug. Say unresolved.",
        ),
    )


def _sleeper_inputs(case: SeatCase) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    user_id = "u1"
    draft = {"draft_order": ({user_id: case.derived} if case.derived is not None else None)}
    rosters = [{"roster_id": 7, "owner_id": user_id}]
    return draft, rosters, user_id


def _espn_settings(case: SeatCase) -> dict[str, Any]:
    """A `pickOrder` whose enumerate lands MY team on `case.derived`.

    Built rather than hardcoded so the ESPN case and the Sleeper case are provably the same
    situation. An out-of-range case is expressed by padding the order, which is exactly how the
    real one arose: a commissioner's list with one more entry than the league has teams.
    """
    if case.derived is None:
        return {"draftSettings": {"pickOrder": []}}
    order = [900 + i for i in range(max(case.derived, TEAMS))]
    order[case.derived - 1] = MY_TEAM_ID
    return {"draftSettings": {"pickOrder": order}}


def check_resolvers(ledger: Ledger) -> None:
    """Drive BOTH production resolvers over the table, and require them to agree.

    Imports from `audible.draft`, never a local copy: a reimplementation tests itself, and the
    thing under test is precisely whether the shipped precedence is right.
    """
    from audible.draft.identity import SOURCE_PICK_ORDER, resolve_slot

    for case in cases():
        scope = ledger.scoped(case=case.name)
        draft, rosters, user_id = _sleeper_inputs(case)
        sleeper = resolve_slot(
            draft, rosters, user_id,
            override=case.override, fallback=case.pin, teams=TEAMS,
        )
        scope.check(
            sleeper.slot == case.expect_slot, SEAT, "seat_precedence",
            f"sleeper resolve_slot served {sleeper.slot} for {case.name}; "
            f"expected {case.expect_slot}. {case.why}",
            got=sleeper.slot, want=case.expect_slot,
        )
        scope.check(
            sleeper.source == case.expect_source, SEAT, "seat_source_honest",
            f"sleeper source {sleeper.source!r} for {case.name}; "
            f"expected {case.expect_source!r}. A value you cannot trace to its source is "
            f"not a value you can act on.",
            got=sleeper.source, want=case.expect_source,
        )

        if not case.espn:
            continue
        # The ESPN ladder, through the real `_identity`. Constructed without touching the
        # network: see `inv_sync` for why the bridge must be preset.
        espn = _espn_identity(case)
        espn_source = (
            SOURCE_PICK_ORDER if case.expect_source == "draft_order" else case.expect_source
        )
        scope.check(
            espn.slot == case.expect_slot, SEAT, "seat_precedence",
            f"ESPN _identity served {espn.slot} for {case.name}; expected "
            f"{case.expect_slot}. {case.why}",
            got=espn.slot, want=case.expect_slot, resolver="espn",
        )
        scope.check(
            espn.source == espn_source, SEAT, "seat_source_honest",
            f"ESPN source {espn.source!r} for {case.name}; expected {espn_source!r}",
            got=espn.source, want=espn_source, resolver="espn",
        )
        # PARITY. Two hand-maintained copies of one ladder drift; this is what would say so.
        scope.check(
            sleeper.slot == espn.slot, SEAT, "seat_parity",
            f"the two resolvers disagree on {case.name}: Sleeper {sleeper.slot}, "
            f"ESPN {espn.slot}. `sync._identity` is a hand-written copy of `resolve_slot` "
            f"and nothing keeps them in step.",
            sleeper=sleeper.slot, espn=espn.slot,
        )
        # A refused derivation must still be REPORTED, or the operator cannot know the
        # pickOrder is broken. Only the branches that carry a pin can report it.
        if case.derived is not None and case.pin is not None:
            scope.check(
                sleeper.derived_slot == case.derived and espn.derived_slot == case.derived,
                SEAT, "seat_bad_order",
                f"{case.name}: the raw derivation was dropped rather than kept beside the "
                f"decision, so the disagreement cannot be reported at all",
                sleeper=sleeper.derived_slot, espn=espn.derived_slot,
            )

    _check_conflict_is_visible(ledger)
    _check_espn_slot_by_team(ledger)


def _espn_identity(case: SeatCase) -> Any:
    from audible.draft.sync import espn_slot_by_team

    settings = _espn_settings(case)
    payload = {"teams": [{"id": MY_TEAM_ID, "owners": [MY_SWID]}]}
    sync = _offline_sync(case)
    return sync._identity(payload, espn_slot_by_team(settings))  # noqa: SLF001


def _offline_sync(case: SeatCase) -> Any:
    """An `EspnSync` that cannot reach the network.

    The bridge is MANDATORY and its absence is silent: without a preset map `__init__` builds
    an `EspnIdBridge` and calls `warm()`, which opens a real `SleeperAdapter` and fetches a
    15 MB catalog -- inside an `except Exception` that only logs. A test that forgets it passes
    while hitting the network.
    """
    import httpx

    from audible.adapters.espn import EspnAdapter
    from audible.draft.sync import EspnIdBridge, EspnSync

    from .inv_sync import league_config

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("the seat invariants must not make a request")

    adapter = EspnAdapter(
        swid=MY_SWID, espn_s2="s2", transport=httpx.MockTransport(handler)
    )
    return EspnSync(
        adapter=adapter,
        config=league_config(num_teams=TEAMS),
        bridge=EspnIdBridge({}),
        slot_override=case.override,
        slot_fallback=case.pin,
    )


def _check_conflict_is_visible(ledger: Ledger) -> None:
    """A disagreement must reach somewhere a person looks. THIS FAILS ON MAIN.

    `Identity.seat_conflict` is computed correctly and read in exactly one place -- a
    `log.error` in `service.py`. It is on no API response and no rendered element. The
    2026-09-07 failure emitted that line once per poll for hours; the seat stayed wrong.

    The check is deliberately weak -- it asks only that SOME served field carries the
    disagreement, not which one -- because naming a field would be designing the fix, and the
    fix is outside this session's write scope.
    """
    from audible.draft.identity import Identity
    from audible.server import state as state_mod

    conflicted = Identity("u1", 7, 6, "draft_order", derived_slot=6, pinned_slot=1)
    ledger.check(
        conflicted.seat_conflict, SEAT, "seat_conflict_model",
        "Identity.seat_conflict does not report a pin/derivation disagreement",
    )
    served = _served_clock_fields(state_mod)
    # EXACT NAMES. Substring matching passed this check on `bye_conflict_penalty`, an unrelated
    # ordering field that merely contains "conflict" -- a gate that cannot fail, which is the
    # exact failure mode this session exists to catch, written into the session that catches it.
    wanted = {"seat_conflict", "derived_slot", "pinned_slot", "slot_conflict"}
    ledger.check(
        bool(wanted & served),
        SEAT, "seat_conflict_seen",
        "a pin that disagrees with the live seat is reported ONLY by `log.error` in "
        "service.py. No field the server can publish carries `seat_conflict`, "
        "`derived_slot` or `pinned_slot`, so the cockpit renders a seat it already knows is "
        "contested and says nothing. On 2026-09-07 that log line fired once per poll for "
        "hours and the served seat stayed wrong.",
        looked_for=sorted(wanted),
    )


def _served_clock_fields(_state_mod: Any) -> set[str]:
    """Every key a REAL `/api/state` response contains, walked recursively.

    THE FIRST VERSION REGEX-SCRAPED `state.py` FOR `"field":` AND WAS WRONG IN BOTH DIRECTIONS.
    An adversarial review measured it against an actual payload: it missed 26 served keys --
    `clock` is built by subscript assignment (`base["clock"] = {...}`) and everything under
    `the_call` is assembled in `urgency.py`, a module the scrape never opened -- and invented
    19 names that are never served, internals of `_bye_audit` and `_runs`. Worse, it passed on
    a COMMENT: appending `# TODO publish "seat_conflict"` to the source turned this session's
    headline finding green.

    So it drives the app. A real payload cannot be satisfied by a docstring, and if the fix
    ever lands -- wherever it lands -- this notices.
    """
    import tempfile
    from pathlib import Path

    from fastapi.testclient import TestClient

    from audible.server import create_app

    from .inv_exec import _service

    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        client = TestClient(create_app(service, warm=False))
        payload = client.get("/api/state").json()
    return _keys(payload)


def _keys(node: Any) -> set[str]:
    """Every key anywhere in a nested response. A field is served wherever it is nested."""
    out: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            out.add(str(key))
            out |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            out |= _keys(item)
    return out


def _check_espn_slot_by_team(ledger: Ledger) -> None:
    """`pickOrder` shapes that are not a seat order at all.

    A malformed order does not merely give a wrong seat -- it gives a CONFIDENT wrong seat,
    which is worse, because the pin it displaces was right. The freeze in Task 2 exists for
    the same reason: an order missing one team ahead of yours derives a different seat, re-
    attributes the whole drafted roster for a tick, and reverts.
    """
    from audible.draft.identity import usable_slot
    from audible.draft.sync import espn_slot_by_team

    shapes = {
        "empty": [],
        "too_long": [901, 902, 903, MY_TEAM_ID, 905, 906, 907, 908, 909],
        "missing_a_team": [901, 902, MY_TEAM_ID, 904, 905, 906, 907],
        "duplicated_team": [901, MY_TEAM_ID, MY_TEAM_ID, 904, 905, 906, 907, 908],
    }
    for name, order in shapes.items():
        scope = ledger.scoped(shape=name)
        mapping = espn_slot_by_team({"draftSettings": {"pickOrder": order}})
        derived = mapping.get(MY_TEAM_ID)
        # The invariant is NOT "the seat is right" -- for a malformed order there is no right
        # seat. It is that anything served is inside the league, so `compute_view` cannot raise.
        scope.check(
            derived is None or usable_slot(derived, TEAMS), SEAT, "seat_bad_order",
            f"pickOrder shape {name!r} derived slot {derived}, which is outside 1..{TEAMS}. "
            f"`compute_view` raises on that and `build_state` has no guard, so every "
            f"/api/state and /api/taken 500s while the bad body persists.",
            derived=derived, order=order,
        )


def check_freeze(ledger: Ledger) -> None:
    """Once the draft is running, the seat must not move -- asserted by DRIVING `_apply`.

    A `pickOrder` missing one team ahead of yours derives a DIFFERENT seat confidently. Mid-
    draft that re-attributes the entire drafted roster for one tick and then silently reverts,
    which is the worst shape a bug can have: invisible in any snapshot and wrong in between.

    THE FIRST VERSION WAS A SUBSTRING TEST AND `frozenset` SATISFIED IT. It asked whether the
    word "frozen" appeared in `service.py`; `_NOT_RUNNING = frozenset({...})` contains it, so a
    source file with the freeze logic entirely deleted still passed. Replaced by feeding two
    updates through the real `_apply` -- one that opens the draft at seat 6, one that derives a
    different seat while it runs -- and asserting the session keeps the seat it started with.
    """
    import tempfile
    from pathlib import Path

    from audible.draft.identity import SOURCE_PICK_ORDER, Identity
    from audible.draft.service import CockpitService
    from audible.draft.sync import DraftUpdate

    from .inv_sync import league_config

    with tempfile.TemporaryDirectory() as tmp:
        service = CockpitService(league_config(), state_dir=Path(tmp))
        opening = DraftUpdate(
            draft_id="6012", picks=[], rounds=16, status="drafting", draft_type="snake",
            identity=Identity("3", 3, 6, SOURCE_PICK_ORDER, derived_slot=6, pinned_slot=6),
        )
        service._apply(opening)  # noqa: SLF001 -- the production path, driven not copied
        started = service.session.slot

        # The same draft, still running, with one team missing from `pickOrder`: every seat
        # behind the gap shifts by one and the derivation is confident about the wrong answer.
        shifted = DraftUpdate(
            draft_id="6012", picks=[], rounds=16, status="drafting", draft_type="snake",
            identity=Identity("3", 3, 5, SOURCE_PICK_ORDER, derived_slot=5, pinned_slot=6),
        )
        service._apply(shifted)  # noqa: SLF001
        after = service.session.slot

    ledger.check(
        started == 6 and after == started, SEAT, "seat_frozen",
        f"the seat moved from {started} to {after} while the draft was RUNNING. A pickOrder "
        f"that loses one team ahead of yours derives a different seat confidently, "
        f"re-attributes the whole drafted roster for a tick, and reverts.",
        started=started, after=after,
    )


def run(ledger: Ledger) -> Ledger:
    """Every seat invariant, over every case."""
    check_resolvers(ledger)
    check_freeze(ledger)
    return ledger
