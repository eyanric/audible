"""The 2026-09-08 draft, replayed from the pod log that recorded it.

Every prior sync test in this repo replays a sequence built from a HYPOTHESIS about how the
feed fails. This one replays the failure itself: `espn_green_hope_2026_draft_window.json` is
572 consecutive polls lifted out of the container log, each with the HTTP status ESPN actually
returned and the number of real picks `espn_picks` actually parsed out of that poll's body.

WHAT THE LOG SHOWED, and it is not what audible#63 predicted. The forced full body fired the
whole way through -- every sixth poll, ~118 fresh 200s an hour, flat across the container's
entire 43-hour life with no gap or cadence change through the draft. Those bodies were
genuinely fresh and unconditional. Every one of them, for the 35 minutes the draft was
running, was an all-placeholder slate. The picks appeared in a single step at 23:34:59.772Z --
ON a forced-full-body poll, 16 seconds BEFORE ESPN's ETag advanced at 23:35:15.

So the ETag was never what hid the draft, and the mitigation is what eventually broke the
silence. The frozen-ETag story is refuted by its own instrumentation.

What is left is the compound failure, and `test_a_feed_frozen_BEFORE_the_draft_opens_is_not_
caught_here` in test_sync_staleness.py already names its shape. That test's docstring then
argues the gap is closed by composition: "a stuck ETag cannot hold the status at pre_draft for
more than about thirty seconds". True, and insufficient -- because nothing here was stuck. The
status rides `draftDetail`, `draftDetail` is what stopped carrying news, and a full body that
is fresh and empty defeats a mitigation aimed only at bodies that are stale.

The detector keys `drafting_since` off a status that comes from the same object as the picks
it is supposed to guard. When that object goes quiet, the picks stop AND the clock never
starts AND `pick_silence_s()` returns None, so nothing can ever be stale. The cockpit served
`sync: live`, `picks_stale: false`, `picks_silent_s: null` for the whole draft -- which is
exactly what /api/state recorded at 23:38:43, after 30,680 successful polls and zero errors.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from audible.adapters.espn import EspnAdapter
from audible.config import LeagueConfig
from audible.config.loader import load_league
from audible.draft.live import Pick
from audible.draft.service import PICK_SILENCE_S, CockpitService
from audible.draft.sync import EspnIdBridge, EspnSync

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOW: dict[str, Any] = json.loads(
    (FIXTURES / "espn_green_hope_2026_draft_window.json").read_text(encoding="utf-8")
)

# green_hope's real pick order, from leagues/espn_green_hope.toml. Team ids only -- no player
# identity from Eric's draft appears anywhere in this file or its fixture.
PICK_ORDER = [9, 6, 1, 4, 7, 2, 5, 8]
SYNTHETIC_ID_BASE = 900000


@pytest.fixture(scope="module")
def green_hope() -> LeagueConfig:
    return load_league(REPO_ROOT / "leagues" / "espn_green_hope.toml")


class Clock:
    """A controllable wall clock, so 40 minutes of draft costs no wall time."""

    def __init__(self, start: float = 1_788_907_000.0) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _slate(real_picks: int, *, drafted: bool, in_progress: bool) -> dict[str, Any]:
    """A 128-row ESPN draft slate with the first `real_picks` rows filled in.

    Pre-draft ESPN serves the COMPLETE grid with every playerId at -1; a pick landing flips
    one row. That is the shape this replays, at the sizes the log measured.
    """
    picks = []
    for overall in range(1, WINDOW["total_picks"] + 1):
        rnd = (overall - 1) // WINDOW["teams"] + 1
        idx = (overall - 1) % WINDOW["teams"]
        seat = idx if rnd % 2 == 1 else WINDOW["teams"] - 1 - idx
        picks.append(
            {
                "overallPickNumber": overall,
                "roundId": rnd,
                "teamId": PICK_ORDER[seat],
                "playerId": (SYNTHETIC_ID_BASE + overall) if overall <= real_picks else -1,
            }
        )
    return {
        "draftDetail": {"drafted": drafted, "inProgress": in_progress, "picks": picks},
        "settings": {
            "draftSettings": {
                "type": "SNAKE",
                "orderType": "MANUAL",
                "pickOrder": PICK_ORDER,
            },
            # 17 lineup slots, one of them IR -> espn_rounds() derives 16.
            "rosterSettings": {"lineupSlotCounts": {"0": 1, "2": 2, "4": 2, "6": 1,
                                                    "16": 1, "17": 1, "20": 8, "21": 1}},
        },
        "teams": [],
    }


def _flat_polls() -> list[tuple[int, int]]:
    """The recorded window expanded to one (status, real_picks) pair per poll."""
    out: list[tuple[int, int]] = []
    for run in WINDOW["runs"]:
        out.extend([(run["status"], run["real_picks"])] * run["polls"])
    return out


def _bridge() -> EspnIdBridge:
    """Offline, preset: every synthetic ESPN id maps to a board id."""
    return EspnIdBridge(
        {str(SYNTHETIC_ID_BASE + n): f"b{n}" for n in range(1, WINDOW["total_picks"] + 1)}
    )


def _replay(
    service: CockpitService,
    clock: Clock,
    *,
    espn_reports_in_progress: bool,
    config: LeagueConfig,
) -> list[dict[str, Any]]:
    """Drive the real EspnAdapter -> EspnSync.poll -> CockpitService._apply, one recorded
    poll at a time, and return a per-poll trace of what the cockpit believed."""
    polls = _flat_polls()
    # The window opens on a 304, and by then the real adapter had been polling for 43 hours
    # and held a body. A fresh adapter has nothing to replay, so prime it with the slate it
    # actually held at 22:55: all placeholder, no picks. Not traced -- it is not a recorded poll.
    seq = iter([(200, 0), *polls])

    def handler(request: httpx.Request) -> httpx.Response:
        status, real = next(seq)
        if status == 304:
            return httpx.Response(304, headers={"etag": 'W/"recorded"'})
        complete = real == WINDOW["total_picks"]
        body = _slate(
            real,
            drafted=complete,
            # The UNRESOLVED axis. The log measures statuses and pick counts; it does not
            # record ESPN's `inProgress` flag, and the post-draft state file cannot say
            # either way because `_NOT_RUNNING` clears `drafting_since` on completion.
            # False is the branch consistent with the cockpit never raising an alarm.
            in_progress=espn_reports_in_progress and not complete,
        )
        return httpx.Response(200, json=body, headers={"etag": 'W/"recorded"'})

    adapter = EspnAdapter(
        swid="{x}", espn_s2="s2", transport=httpx.MockTransport(handler)
    )
    sync = EspnSync(config, adapter=adapter, bridge=_bridge(), slot_fallback=6)
    adapter.get_draft_detail(config)  # consume the priming body

    trace: list[dict[str, Any]] = []
    for _ in polls:
        clock.advance(WINDOW["poll_interval_s"])
        service._apply(sync.poll(None, want_meta=False, slot_locked=False))
        trace.append(
            {
                "t": clock.now,
                "picks": len(service.session.picks),
                "status": service.session.draft_status,
                "silence": service.health.pick_silence_s(now=clock.now),
                "stale": service.health.picks_stale(now=clock.now),
            }
        )
    return trace


@pytest.fixture
def service(tmp_path: Path, green_hope: LeagueConfig, monkeypatch: pytest.MonkeyPatch,
            ) -> tuple[CockpitService, Clock]:
    clock = Clock()
    monkeypatch.setattr(time, "time", clock)
    svc = CockpitService(green_hope, state_dir=tmp_path)
    svc.health.last_success = clock.now
    return svc, clock


# --- what the recording measures, pinned so a re-extraction cannot drift ------------------


def test_the_recording_says_the_forced_full_body_fired_and_came_back_empty() -> None:
    """The premise the whole diagnosis rests on, asserted against the fixture itself."""
    polls = _flat_polls()
    assert len(polls) == WINDOW["window_polls"] == 572
    fresh = [(s, r) for s, r in polls if s == 200]
    assert len(fresh) == WINDOW["window_status_counts"]["200"] == 97, (
        "the forced full body fired ~97 times across the window"
    )
    # The draft ran from window start + ~300s to the first real pick at +2399s.
    before = polls[: next(i for i, (_, r) in enumerate(polls) if r > 0)]
    assert all(r == 0 for _, r in before), "a pick arrived before 23:34:59"
    assert any(s == 200 for s, _ in before), (
        "no fresh body arrived before the picks did -- then this is a caching failure "
        "after all and the diagnosis is wrong"
    )
    assert sum(1 for s, _ in before if s == 200) >= 70, (
        f"only {sum(1 for s, _ in before if s == 200)} fresh bodies before the first pick; "
        "the mitigation must have fired throughout for the refutation to hold"
    )
    after = polls[next(i for i, (_, r) in enumerate(polls) if r > 0):]
    assert all(r == WINDOW["total_picks"] for _, r in after), (
        "the picks arrived in ONE bulk step, not a trickle"
    )


# --- G2: the gate on the session ---------------------------------------------------------


def test_g2_the_recorded_window_is_a_draft_the_cockpit_never_warned_about(
    service: tuple[CockpitService, Clock], green_hope: LeagueConfig
) -> None:
    """THE REPRODUCTION. 40 minutes of the real recorded feed, and nothing is ever raised.

    The draft was scheduled for 23:00:00Z and the first pick reached audible at 23:34:59 --
    2,399 seconds after this window opens, which is more than thirteen times the 180s
    silence threshold. An operator watching the cockpit had no way to learn the feed was
    not delivering, because `pick_silence_s()` returns None whenever `drafting_since` is
    None, and `drafting_since` only arms on a status that stopped arriving.

    This fails on main. That is the point: it is the failure, not a theory about it.
    """
    svc, clock = service
    trace = _replay(svc, clock, espn_reports_in_progress=False, config=green_hope)

    blind = [row for row in trace if row["picks"] == 0]
    assert len(blind) > 400, "the recorded window should be mostly pick-less"
    silent_for = blind[-1]["t"] - blind[0]["t"]
    assert silent_for > PICK_SILENCE_S * 10, (
        f"the window only covers {silent_for:.0f}s of silence"
    )

    assert any(row["stale"] for row in blind), (
        f"THE 2026-09-08 FAILURE: {silent_for:.0f}s of a scheduled draft delivering nothing "
        f"and picks_stale never went true. Statuses seen: "
        f"{sorted({r['status'] for r in blind})}; silence readings: "
        f"{sorted({r['silence'] for r in blind})}. A draft can run to completion with the "
        f"cockpit reporting a healthy feed."
    )


def test_injection_2_the_same_window_arms_when_espn_admits_it_is_drafting(
    service: tuple[CockpitService, Clock], green_hope: LeagueConfig
) -> None:
    """Isolates arming from ingestion: identical poll sequence, `inProgress` true.

    The detector is not broken in general -- it is broken in its DEPENDENCE. Feed it a
    status and it fires correctly on the very same silence. That is what makes the
    dependence the defect rather than the threshold.
    """
    svc, clock = service
    trace = _replay(svc, clock, espn_reports_in_progress=True, config=green_hope)
    blind = [row for row in trace if row["picks"] == 0]

    assert any(row["stale"] for row in blind), (
        "with a cooperating status the detector must arm on the identical sequence"
    )
    assert any(row["status"] == "drafting" for row in blind)


def test_injection_4_a_healthy_draft_raises_nothing(
    service: tuple[CockpitService, Clock], green_hope: LeagueConfig
) -> None:
    """The check must not fire on correct behaviour.

    A pick every 20s, well inside the 180s threshold, with the feed reporting progress
    honestly. Nothing here is stale and nothing may say it is.
    """
    svc, clock = service
    for n in range(1, 40):
        clock.advance(20.0)
        svc._apply(
            _update_from_picks(
                [Pick(pick_no=i, round=1, draft_slot=i, player_id=f"b{i}", source="sync")
                 for i in range(1, n + 1)],
                "drafting",
            )
        )
        assert svc.health.picks_stale(now=clock.now) is False, (
            f"a healthy draft delivering every 20s was called stale at pick {n}"
        )


def _update_from_picks(picks: list[Pick], status: str) -> Any:
    from audible.draft.sync import DraftUpdate

    return DraftUpdate(draft_id="73131979", picks=picks, rounds=16, status=status,
                       draft_type="snake")


# --- G3: a hand-entered pick is the operator's own datum ----------------------------------


def test_g3_a_hand_entered_pick_survives_the_sync_that_supersedes_it(
    service: tuple[CockpitService, Clock]
) -> None:
    """Mirroring a dead feed by hand must leave a trace that outlives the reconciliation.

    `_reconcile_manual` drops every manual pick the sync now covers, and its reasoning is
    sound -- keeping both double-counts the player. But dropping the RECORD as well as the
    duplicate is what makes the post-mortem impossible: a draft entered entirely by hand and
    then reconciled is byte-identical to one that synced perfectly. `manual_picks: []` with
    128 `source: "sync"` picks is exactly what green_hope's state file says, and it is
    exactly what a healthy draft says too.

    This fails on main.
    """
    svc, clock = service
    svc.session.draft_status = "drafting"
    svc.session.manual_picks = [
        Pick(pick_no=1, round=1, draft_slot=1, player_id="b1", source="manual")
    ]

    svc._apply(
        _update_from_picks(
            [Pick(pick_no=1, round=1, draft_slot=1, player_id="b1", source="sync")],
            "drafting",
        )
    )

    assert svc.session.manual_picks == [], (
        "precondition changed: the duplicate is supposed to be superseded"
    )
    assert svc.manual_provenance(), (
        "a hand-entered pick vanished without trace when sync caught up. The board is right "
        "and the history is gone: nothing in the persisted state can now distinguish a draft "
        "typed in by hand from one the feed delivered."
    )


# --- G4: the state file must not be able to lie -------------------------------------------


def test_g4_the_state_file_distinguishes_a_live_trickle_from_a_bulk_reconciliation(
    tmp_path: Path, green_hope: LeagueConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two drafts, same 128 picks, same final status -- and the artifact must tell them apart.

    green_hope's post-draft state file is `draft_status: complete`, 128 picks, 0 manual,
    `drafting_since: null`. That is indistinguishable from a perfect draft, and the only
    thing that proved otherwise was an 18MB log that dies with the pod.
    """
    clock = Clock()
    monkeypatch.setattr(time, "time", clock)

    def run(bulk: bool) -> dict[str, Any]:
        svc = CockpitService(green_hope, state_dir=tmp_path / ("bulk" if bulk else "live"))
        svc.health.last_success = clock.now
        svc.session.draft_status = "drafting"
        all_picks = [
            Pick(pick_no=i, round=1, draft_slot=i, player_id=f"b{i}", source="sync")
            for i in range(1, 129)
        ]
        if bulk:
            clock.advance(2400.0)
            svc._apply(_update_from_picks(all_picks, "drafting"))
        else:
            for i in range(1, 129):
                clock.advance(16.0)
                svc._apply(_update_from_picks(all_picks[:i], "drafting"))
        svc._apply(_update_from_picks(all_picks, "complete"))
        svc.save()
        return json.loads(
            svc._state_path.read_text(encoding="utf-8")
        )

    bulk, live = run(True), run(False)
    assert len(bulk["picks"]) == len(live["picks"]) == 128
    assert bulk["draft_status"] == live["draft_status"] == "complete"

    # NOT `bulk != live`. Two runs on a moving clock differ in their timestamps whatever the
    # schema records, so that comparison passes without anything being written down -- it
    # reads as a gate and is really a coincidence. The property is that each PICK carries
    # when it was first seen, because that is the one thing that separates the two shapes:
    # 128 picks that appeared together, versus 128 that arrived one at a time.
    def first_seen(state: dict[str, Any]) -> list[float]:
        seen = [p.get("first_seen") for p in state["picks"]]
        assert all(t is not None for t in seen), (
            "picks carry no first_seen, so the state file cannot say when they arrived"
        )
        return sorted(set(seen))

    assert len(first_seen(bulk)) == 1, (
        "a bulk reconciliation must record all 128 picks as first seen at ONE instant"
    )
    assert len(first_seen(live)) == 128, (
        "a live draft must record 128 distinct arrival instants; the state file still "
        "cannot tell a hand-entered-then-reconciled draft from a healthy one"
    )


# --- the defect this handoff did not anticipate -------------------------------------------


def test_the_id_bridge_announces_each_pick_once_not_once_per_poll(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """12,926 log lines in eight and a half minutes, and they are how the draft was solved.

    `translate_logged` says it is "announcing every hit -- the evening has to be auditable",
    and `espn_picks` calls it for every real pick on every poll. Once the slate filled, that
    is 128 INFO lines every five seconds: ~1,536 a minute, unbounded for as long as the
    cockpit runs. The pod wrote 18MB into a 1Gi emptyDir with no rotation and no persistence.

    The sibling path already knows better -- `to_board_id` dedupes its miss warning through
    `unmatched`, so a player with no board row is announced once. The hit path was simply
    never given the same treatment, which is what makes this a bug rather than a choice.

    Auditability is preserved: every distinct translation is still logged, once.
    """
    from audible.draft.sync import espn_picks

    bridge = _bridge()
    detail = _slate(WINDOW["total_picks"], drafted=True, in_progress=False)["draftDetail"]
    slot_by_team = {t: i + 1 for i, t in enumerate(PICK_ORDER)}

    with caplog.at_level("INFO", logger="audible.cockpit"):
        for _ in range(10):
            picks = espn_picks(detail, slot_by_team, bridge)
    assert len(picks) == WINDOW["total_picks"]

    lines = [r for r in caplog.records if r.getMessage().startswith("ESPN ")]
    assert len(lines) == WINDOW["total_picks"], (
        f"{len(lines)} lines for {WINDOW['total_picks']} picks over 10 polls -- the whole "
        f"slate is re-announced every tick. At the cockpit's 5s poll that is "
        f"{WINDOW['total_picks'] * 12} lines a minute for the rest of the draft."
    )
