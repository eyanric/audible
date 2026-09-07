"""SYNC invariants -- defect 2, the 2026-09-05 failure.

WHAT HAPPENED. `mDraftDetail` answered a conditional GET with a clean `304` while picks
accumulated behind it. `_draft_etag` and `_draft_last` are written ONLY on a 200, so a tag
that never advances pins the adapter to the first body it ever saw. A cockpit started before
the draft caches the pre-draft placeholder slate and then serves `picks: 0`,
`draft_status: pre_draft`, `sync_status: live` all night. Every poll succeeded. Nothing raised.

THE HARD PART IS THAT NOTHING LOOKS WRONG. `last_success` advances on a 304 -- the request
did work -- so every health number the cockpit had was green. That is why the check cannot be
"did the poll succeed": it has to be "does the board state match the ground truth I fed in".
So these invariants drive the REAL `EspnAdapter.get_draft_detail` and the REAL `EspnSync.poll`
over scripted response sequences and compare the parsed result against the sequence's own
truth, which is the only comparison the 304 cannot satisfy by accident.

OFFLINE, AND TWO SEAMS ARE MANDATORY. `EspnAdapter(transport=httpx.MockTransport(...))` takes
the HTTP path off the network. `EspnSync(bridge=EspnIdBridge({}))` is the one that bites: with
no preset map `__init__` builds a bridge and calls `warm()`, which opens a real
`SleeperAdapter` and pulls a 15 MB catalogue -- inside an `except Exception` that only logs.
A test that forgets it PASSES while hitting the network. `assert_offline` below refuses that.

WHAT IS ASSERTED:

  sync_frozen_etag      a body that changes behind a frozen tag must still reach the board
  sync_placeholder      a full slate of playerId -1 parses to ZERO picks, not to 128
  sync_ordering         picks out of order, duplicated, or gapped land in pick order
  sync_stale_fires      genuine silence during a live draft is reported
  sync_stale_quiet      pre-draft silence is NOT reported
  sync_stale_blip       a status blip cannot wipe accumulated silence
  sync_stale_shrink     an emptied slate cannot reset the clock when it refills
  sync_pause_labelled   a paused ESPN draft reads as silence, and that is stated

TWO OF THESE FAIL ON MAIN -- `sync_stale_blip` and `sync_stale_shrink`, both driven through
the real `_apply`, and both reported with the timestamps that show the clock resetting.
They are reported, not fixed: the fix is outside
`sim/`, and fixing a defect in the same session that first detects it means the detector was
never tested against the bug.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .invariants import SYNC, Ledger

MY_SWID = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
MY_TEAM_ID = 3
TEAMS = 8
ROUNDS = 16


def league_config(num_teams: int = TEAMS) -> Any:
    """The 8-team ESPN league the cockpit actually runs, loaded from the committed TOML.

    Loaded rather than hand-built so a change to the real league's shape reaches these
    invariants instead of being papered over by a fixture that agrees with nothing.
    """
    from pathlib import Path

    from audible.config import load_league

    repo = Path(__file__).resolve().parents[1]
    config = load_league(repo / "leagues" / "espn_davis_drive.toml")
    if num_teams != config.num_teams:
        return config.model_copy(update={"num_teams": num_teams})
    return config


# --- the scripted feed ---------------------------------------------------------------------


@dataclass
class Tick:
    """One HTTP answer, plus the ground truth the board must end up agreeing with."""

    status_code: int
    body: dict[str, Any] | None
    etag: str | None
    # How many REAL picks the caller should see after this tick. Not how many rows the body
    # carries -- the placeholder slate carries 128 rows and zero picks.
    expect_picks: int
    label: str = ""
    # This server's ETag never advances: it answers 304 to any request carrying the tag, and
    # the CURRENT body to any request that omits it. That is what a stuck tag looks like from
    # the client, and it is the only shape under which the periodic full body is a mitigation.
    frozen: bool = False


@dataclass
class Feed:
    """A scripted `mDraftDetail` conversation, and the transport that serves it.

    Records what it was asked for, so an invariant can assert the adapter actually sent
    `If-None-Match` rather than merely that the answer looked right.
    """

    ticks: Sequence[Tick]
    index: int = 0
    seen_headers: list[dict[str, str]] = field(default_factory=list)

    def handler(self) -> Callable[[Any], Any]:
        """A transport that behaves like a CONDITIONAL server, not like a canned list.

        THIS MODELS A STUCK TAG RATHER THAN A STUCK SERVER, and the difference is a false
        defect I reported against production first. A server whose ETag never advances answers
        304 to a request that CARRIES the tag and 200 with the current body to one that does
        not. My first version returned a hardcoded 304 to every request, including the
        unconditional full-body poll -- so `DRAFT_FULL_BODY_EVERY` could not rescue anything
        and the harness accused the adapter of a bug the mock had invented.

        Return `frozen=True` on a tick to say "this server's tag is stuck": it answers 304
        whenever If-None-Match matches, and serves `body` otherwise.
        """
        import httpx

        def _handle(request: httpx.Request) -> httpx.Response:
            self.seen_headers.append(dict(request.headers))
            tick = self.ticks[min(self.index, len(self.ticks) - 1)]
            self.index += 1
            headers = {"etag": tick.etag} if tick.etag else {}
            conditional = request.headers.get("if-none-match")
            if tick.frozen and conditional and conditional == tick.etag:
                return httpx.Response(304, headers=headers)
            if tick.status_code == 304 and conditional:
                return httpx.Response(304, headers=headers)
            return httpx.Response(200, json=tick.body or {}, headers=headers)

        return _handle


def adapter_for(feed: Feed) -> Any:
    """A real `EspnAdapter` over a mock transport. No network, real parsing."""
    import httpx

    from audible.adapters.espn import EspnAdapter

    return EspnAdapter(
        swid=MY_SWID, espn_s2="s2", transport=httpx.MockTransport(feed.handler())
    )


def sync_for(feed: Feed, *, slot_fallback: int | None = 1) -> Any:
    """A real `EspnSync` that provably cannot reach the network."""
    from audible.draft.sync import EspnIdBridge, EspnSync

    return EspnSync(
        league_config(),
        adapter=adapter_for(feed),
        bridge=EspnIdBridge({}),
        slot_fallback=slot_fallback,
    )


# --- bodies ---------------------------------------------------------------------------------


def _pick_row(overall: int, player_id: int, team_id: int = MY_TEAM_ID) -> dict[str, Any]:
    return {
        "overallPickNumber": overall,
        "roundId": (overall - 1) // TEAMS + 1,
        "teamId": team_id,
        "playerId": player_id,
    }


def body(
    picks: Sequence[dict[str, Any]], *, in_progress: bool = True, drafted: bool = False
) -> dict[str, Any]:
    """A `mDraftDetail` body in the shape the adapter actually parses."""
    return {
        "draftDetail": {
            "drafted": drafted,
            "inProgress": in_progress,
            "picks": list(picks),
        },
        "teams": [{"id": MY_TEAM_ID, "owners": [MY_SWID]}],
        "settings": {
            "draftSettings": {
                "pickOrder": [901, 902, MY_TEAM_ID, 904, 905, 906, 907, 908],
                "type": "SNAKE",
            },
            "rosterSettings": {"lineupSlotCounts": {"0": 1, "2": 2, "4": 2, "6": 1, "23": 1,
                                                    "16": 1, "17": 1, "20": 7, "21": 1}},
        },
    }


def placeholder_slate() -> dict[str, Any]:
    """The pre-draft grid: every pick the draft will ever have, all `playerId: -1`.

    128 rows for an 8-team, 16-round draft. A sync that counts ROWS reports a finished draft
    before the first selection is made -- and a cockpit started at 18:00 caches exactly this.
    """
    return body(
        [_pick_row(i, -1, 900 + (i % TEAMS)) for i in range(1, TEAMS * ROUNDS + 1)],
        in_progress=False,
    )


def live_slate(n: int) -> dict[str, Any]:
    """A draft `n` real picks in, with the rest of the grid still placeholders."""
    rows = [_pick_row(i, 1000 + i, 900 + (i % TEAMS)) for i in range(1, n + 1)]
    rows += [
        _pick_row(i, -1, 900 + (i % TEAMS)) for i in range(n + 1, TEAMS * ROUNDS + 1)
    ]
    return body(rows)


# --- the invariants --------------------------------------------------------------------------


def assert_offline(ledger: Ledger) -> None:
    """The bridge seam is load-bearing and its absence is SILENT. Prove it is preset.

    Without `bridge=EspnIdBridge({})` the constructor warms a real bridge against a real
    `SleeperAdapter` inside an `except Exception` that only logs, so the test still passes --
    over the network, with every pick untranslated. An offline harness that is quietly online
    is worse than one that fails.
    """
    from audible.draft.sync import EspnIdBridge

    feed = Feed([Tick(200, live_slate(3), "v1", 3)])
    sync = sync_for(feed)
    bridge = sync._bridge  # noqa: SLF001 -- the seam under assertion
    ledger.check(
        isinstance(bridge, EspnIdBridge), SYNC, "sync_offline",
        "EspnSync was not given a preset id bridge; `warm()` would open a real "
        "SleeperAdapter and pull the 15 MB catalogue, inside an except that only logs",
    )


def check_frozen_etag(ledger: Ledger, *, polls: int | None = None) -> None:
    """THE 2026-09-05 FAILURE. A body that changes behind a tag that does not must still land.

    The sequence is the real one: a pre-draft placeholder slate cached first, then picks
    accumulating behind an ETag that never advances. If the adapter serves the first body it
    ever saw, the board reads zero picks through the whole draft while every poll succeeds.

    THE PERIODIC FULL BODY IS WHAT SAVES IT, and this is a check on that mitigation rather than
    on the ETag logic itself. `DRAFT_FULL_BODY_EVERY` skips the conditional request every Nth
    poll, so a stuck tag costs at most N-1 polls of delay. The invariant is therefore stated as
    a BOUND -- the board must catch up within `DRAFT_FULL_BODY_EVERY` polls -- not as "every
    poll is current", because the latter is false by design and asserting it would fail on
    correct code.
    """
    from audible.adapters.espn import DRAFT_FULL_BODY_EVERY

    scope = ledger.scoped(sequence="frozen_etag")
    # How many polls the sequence runs for. Defaults to just past the full-body period so the
    # mitigation gets its chance; a caller restoring the historical adapter passes its own
    # count, because with no periodic full body there is no period to wait out.
    horizon = polls if polls is not None else DRAFT_FULL_BODY_EVERY + 1
    truth = 24
    # Poll 1 caches the pre-draft slate. From then on the server holds `truth` real picks
    # behind a tag that never moves, so every conditional request gets a 304 and only the
    # periodic unconditional one can see them.
    ticks = [
        Tick(200, placeholder_slate(), "STUCK", 0, "pre-draft slate, cached", frozen=True)
    ]
    ticks += [
        Tick(200, live_slate(truth), "STUCK", truth, f"poll #{i}, tag still STUCK", frozen=True)
        for i in range(1, horizon + 2)
    ]
    feed = Feed(ticks)
    sync = sync_for(feed)
    seen = []
    for _ in range(horizon):
        update = sync.poll(None, want_meta=False, slot_locked=False)
        seen.append(len(update.picks))

    scope.check(
        max(seen) == truth, SYNC, "sync_frozen_etag",
        f"a frozen ETag hid every pick: the board saw {seen} across "
        f"{horizon} polls while {truth} picks existed. "
        f"`_draft_etag`/`_draft_last` are written only on a 200, so a tag that never advances "
        f"pins the adapter to the first body it ever saw.",
        saw=seen, truth=truth, bound=DRAFT_FULL_BODY_EVERY, polls=horizon,
    )
    scope.check(
        any("if-none-match" in {k.lower() for k in h} for h in feed.seen_headers),
        SYNC, "sync_conditional",
        "the adapter never sent If-None-Match, so this sequence did not exercise the "
        "conditional path it claims to",
    )


def check_placeholder(ledger: Ledger) -> None:
    """A full slate of `playerId: -1` is ZERO picks, not 128."""
    scope = ledger.scoped(sequence="placeholder")
    feed = Feed([Tick(200, placeholder_slate(), "v1", 0)])
    sync = sync_for(feed)
    update = sync.poll(None, want_meta=False, slot_locked=False)
    scope.check(
        len(update.picks) == 0, SYNC, "sync_placeholder",
        f"the pre-draft placeholder slate parsed to {len(update.picks)} picks. It carries one "
        f"row per seat per round and every playerId is -1; counting rows reports a finished "
        f"draft before the first selection.",
        parsed=len(update.picks), rows=TEAMS * ROUNDS,
    )
    scope.check(
        update.status == "pre_draft", SYNC, "sync_placeholder",
        f"a placeholder slate reported status {update.status!r}, not 'pre_draft'",
        status=update.status,
    )


def check_ordering(ledger: Ledger) -> None:
    """Out of order, duplicated, gapped. The board must end up in pick order regardless."""
    scope = ledger.scoped(sequence="ordering")
    rows = [_pick_row(3, 1003), _pick_row(1, 1001), _pick_row(2, 1002), _pick_row(2, 1002)]
    feed = Feed([Tick(200, body(rows), "v1", 4)])
    sync = sync_for(feed)
    update = sync.poll(None, want_meta=False, slot_locked=False)
    numbers = [p.pick_no for p in update.picks]
    scope.check(
        numbers == sorted(numbers), SYNC, "sync_ordering",
        f"picks came back out of order: {numbers}. `espn_picks` sorts on pick_no and a "
        f"consumer that trusts arrival order would mis-attribute the board.",
        got=numbers,
    )
    # A GAP is not an error and must not be treated as one -- ESPN can serve a partial slate
    # mid-write. What matters is that nothing is invented to fill it.
    gapped = [_pick_row(1, 1001), _pick_row(5, 1005)]
    feed2 = Feed([Tick(200, body(gapped), "v1", 2)])
    update2 = sync_for(feed2).poll(None, want_meta=False, slot_locked=False)
    scope.check(
        [p.pick_no for p in update2.picks] == [1, 5], SYNC, "sync_ordering",
        f"a gapped slate was not carried through verbatim: {[p.pick_no for p in update2.picks]}",
        got=[p.pick_no for p in update2.picks],
    )


def _service(tmp: Any) -> Any:
    from audible.draft.service import CockpitService

    return CockpitService(league_config(), state_dir=tmp)


def _update(status: str, picks: Sequence[Any]) -> Any:
    from audible.draft.identity import SOURCE_PICK_ORDER, Identity
    from audible.draft.sync import DraftUpdate

    return DraftUpdate(
        draft_id="6012", picks=list(picks), rounds=16, status=status, draft_type="snake",
        identity=Identity("3", 3, 6, SOURCE_PICK_ORDER, derived_slot=6, pinned_slot=6),
    )


def check_staleness(ledger: Ledger) -> None:
    """The clock that answers "is the feed DELIVERING", not "did the request work".

    Driven through the real `SyncHealth`, at a fixed `now` so nothing depends on wall time.
    """
    from audible.draft.service import PICK_SILENCE_S, SyncHealth

    scope = ledger.scoped(sequence="staleness")

    live = SyncHealth(drafting_since=0.0, last_pick_change=0.0)
    scope.check(
        live.picks_stale(now=PICK_SILENCE_S + 1), SYNC, "sync_stale_fires",
        f"{PICK_SILENCE_S + 1:.0f}s of silence in a live draft did not read as stale",
    )
    pre = SyncHealth(drafting_since=None)
    scope.check(
        not pre.picks_stale(now=10_000.0), SYNC, "sync_stale_quiet",
        "a pre-draft feed with no picks read as stale; that alarm is on every day of the year",
    )
    paused = SyncHealth(drafting_since=0.0, last_pick_change=0.0, paused=True)
    scope.check(
        not paused.picks_stale(now=PICK_SILENCE_S + 1), SYNC, "sync_pause_labelled",
        "an explicitly paused draft was reported stale",
    )
    scope.check(
        _espn_has_no_pause(), SYNC, "sync_pause_labelled",
        "espn_draft_status gained a pause value; the documented behaviour that an ESPN pause "
        "reads as silence is now stale and this invariant needs rewriting",
    )


def check_apply_holes(ledger: Ledger) -> None:
    """The two staleness holes, driven through the REAL `_apply` rather than reasoned about.

    THE FIRST VERSION OF BOTH OF THESE WAS A CONSTANT. It copied the delivery predicate out of
    `service.py` -- `after != before and after[0] >= before[0]` -- evaluated it on hand-built
    fingerprints, and never invoked `_apply` at all. An adversarial review wrapped `_apply`
    with a counter and measured ZERO calls: removing the guard from production could not have
    turned either check red, and one of them was `not (True and 0 >= 3)`, permanently green by
    arithmetic. That is the exact failure this session exists to prevent, written into the
    session that prevents it.

    Both now feed updates through `CockpitService._apply` and read `health.last_pick_change`,
    which is the field the warning is computed from.
    """
    import tempfile
    from pathlib import Path

    from audible.draft.sync import Pick

    scope = ledger.scoped(sequence="apply")
    full = [Pick(pick_no=i, round=1, draft_slot=1, player_id=f"p{i}") for i in (1, 2, 3)]

    # (a) THE BLIP. One `pre_draft` poll between two `drafting` polls. `espn_draft_status`
    # returns `pre_draft` for ANY body that does not assert `inProgress`, so a short body or a
    # momentary flag flap is enough, and ESPN rewrites `status` on every tick.
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        service._apply(_update("drafting", full))  # noqa: SLF001
        anchored = service.health.drafting_since
        service._apply(_update("pre_draft", full))  # noqa: SLF001
        blipped = service.health.drafting_since
        service._apply(_update("drafting", full))  # noqa: SLF001
        rearmed = service.health.drafting_since

    scope.check(
        blipped is not None, SYNC, "sync_stale_blip",
        "a single `pre_draft` poll cleared `drafting_since`, discarding every second of "
        "accumulated silence. The next `drafting` poll re-anchors the clock to now, so a flap "
        "more often than the silence window makes `picks_stale` permanently unreachable. "
        "`_NOT_RUNNING` contains 'pre_draft' and that is the DEFAULT `espn_draft_status` "
        "returns for any body that does not assert inProgress.",
        anchored=anchored, after_blip=blipped, rearmed=rearmed,
    )

    # (b) THE SHRINK. An emptied slate is refused as a delivery -- correctly -- but stored
    # anyway, so the NEXT full body reads as a delivery from an empty baseline with no new
    # pick made. An oscillating feed keeps the clock at zero forever.
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        service._apply(_update("drafting", full))  # noqa: SLF001
        service.health.last_pick_change = None
        service._apply(_update("drafting", []))  # noqa: SLF001
        after_empty = service.health.last_pick_change
        service._apply(_update("drafting", full))  # noqa: SLF001
        after_refill = service.health.last_pick_change

    scope.check(
        after_empty is None and after_refill is None, SYNC, "sync_stale_shrink",
        f"an emptied slate followed by the same three picks returning reset the pick clock "
        f"with NO new pick made (empty -> {after_empty!r}, refill -> {after_refill!r}). The "
        f"shrink itself is refused, but `session.picks` is overwritten unconditionally, so the "
        f"refill is measured against an empty baseline. On ESPN an emptied slate almost always "
        f"arrives WITH status pre_draft, which trips the blip in the same tick.",
        after_empty=after_empty, after_refill=after_refill,
    )


def _espn_has_no_pause() -> bool:
    from audible.draft.sync import espn_draft_status

    values = {
        espn_draft_status({"drafted": True}),
        espn_draft_status({"inProgress": True}),
        espn_draft_status({}),
    }
    return not any("pause" in v for v in values)


def run(ledger: Ledger) -> Ledger:
    assert_offline(ledger)
    check_frozen_etag(ledger)
    check_placeholder(ledger)
    check_ordering(ledger)
    check_staleness(ledger)
    check_apply_holes(ledger)
    return ledger


def dump_sequences(path: Any) -> None:
    """The scripted feeds, written beside the artifact so a violation is re-runnable."""
    payload = {
        "placeholder_rows": TEAMS * ROUNDS,
        "sequences": ["frozen_etag", "placeholder", "ordering", "staleness", "apply"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", "utf-8")
