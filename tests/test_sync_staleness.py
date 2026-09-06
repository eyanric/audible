"""The cockpit must SAY when picks stop arriving, and must not cry before the draft opens.

A whole draft ran on 2026-09-05 with nobody aware the feed had stopped delivering. The shape
of that failure is general: every clock the cockpit had measured the age of the last
successful POLL, and a conditional request answered 304 is a successful poll. `sync_status`
read "live" all night.

So there are two gates here and they pull against each other, which is the point:

  G1  draft in progress, no pick for long enough -> the page says so
  G2  draft NOT started, no pick ever, any age  -> the page says NOTHING

G2 is the one that keeps G1 useful. An indicator that is lit every quiet afternoon is an
indicator nobody looks at on draft night.

Plus the failure injections: freeze the feed and the warning must appear; set the threshold
to zero and it must be permanent (proving the threshold is live rather than decorative); and
unmap `statId 63` and the reconciliation residual must come back at its documented size.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from audible.adapters.espn import (
    DRAFT_FULL_BODY_EVERY,
    STAT_ID_TO_KEY,
    EspnAdapter,
    translate_stat_line,
)
from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import Pick
from audible.draft.service import PICK_CLOCK_S, PICK_SILENCE_S, CockpitService, SyncHealth
from audible.draft.sync import DraftUpdate
from audible.scoring.engine import score_stat_line
from audible.server import create_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"
POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]


def _entry(i: int) -> DraftEntry:
    pos = POSITIONS[(i - 1) % len(POSITIONS)]
    return DraftEntry(
        player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
        eligible_positions=frozenset({pos}), team="XX", model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=False, scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i), adp_rank=i, value=0, flags=(),
    )


@pytest.fixture
def service(tmp_path: Path, sleeper_config: LeagueConfig) -> CockpitService:
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard("sleeper_boyfun", [_entry(i) for i in range(1, 201)])
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = 4
    svc.session.slot_source = "override"
    svc.health.last_success = time.time()
    return svc


@pytest.fixture
def client(service: CockpitService) -> TestClient:
    return TestClient(create_app(service, warm=False))


def _pick(no: int) -> Pick:
    return Pick(pick_no=no, round=1, draft_slot=no, player_id=f"p{no}", source="sync")


def _update(picks: list[Pick], status: str) -> DraftUpdate:
    return DraftUpdate(draft_id="1", picks=picks, rounds=16, status=status, draft_type="snake")


# --- the threshold itself -------------------------------------------------------------


def test_the_threshold_is_two_pick_clocks() -> None:
    """Not a round number someone liked -- a quantity with a reason.

    The draft is ninety seconds per selection. One clock cannot trip this: a manager using
    every second of their turn is ordinary. Two consecutive clocks with nothing arriving is
    not something a healthy eight-team draft does.
    """
    assert PICK_CLOCK_S == 90.0
    assert PICK_SILENCE_S == 2 * PICK_CLOCK_S == 180.0


# --- G2: silence before the draft is CORRECT ------------------------------------------


def test_g2_a_quiet_afternoon_is_not_an_alarm() -> None:
    """No draft, no picks, any age at all -> nothing. This is the gate that protects G1."""
    health = SyncHealth(last_success=time.time())
    for elapsed in (0, 60, 600, 86_400):
        assert health.pick_silence_s(now=time.time() + elapsed) is None
        assert health.picks_stale(now=time.time() + elapsed) is False


def test_g2_the_served_payload_is_silent_before_the_draft(
    client: Any, service: CockpitService
) -> None:
    """The exact reported pre-draft state: picks 0, sync live, and no warning."""
    service.session.draft_status = "pre_draft"
    service.session.picks = []
    service.health.last_success = time.time()
    service.health.drafting_since = None

    body = client.get("/api/state").json()
    assert body["sync"]["status"] == "live"
    assert body["sync"]["picks_silent_s"] is None, "there is no silence to measure yet"
    assert body["sync"]["picks_stale"] is False
    assert body["draft"]["started"] is False


def test_g2_holds_even_when_the_poll_itself_is_ancient(
    client: Any, service: CockpitService
) -> None:
    """A failing poll is a different complaint, and it must not become a pick-silence one."""
    service.session.draft_status = "pre_draft"
    service.health.last_success = time.time() - 9_000
    service.health.drafting_since = None

    body = client.get("/api/state").json()
    assert body["sync"]["status"] == "failing", "the poll age is still reported honestly"
    assert body["sync"]["picks_stale"] is False, "but it is not a pick-silence alarm"


# --- G1: silence DURING the draft is a failure ----------------------------------------


def test_g1_silence_while_drafting_is_reported(client: Any, service: CockpitService) -> None:
    now = time.time()
    service.session.draft_status = "drafting"
    service.health.last_success = now          # the poll is perfectly healthy...
    service.health.drafting_since = now - 400  # ...and no pick has arrived in 400s
    service.health.last_pick_change = None

    body = client.get("/api/state").json()
    assert body["sync"]["status"] == "live", "this is the trap: the poll looks fine"
    assert body["sync"]["picks_stale"] is True
    assert body["sync"]["picks_silent_s"] >= 400
    assert body["sync"]["pick_silence_limit_s"] == PICK_SILENCE_S


def test_g1_fires_only_after_two_clocks(service: CockpitService) -> None:
    now = time.time()
    service.session.draft_status = "drafting"
    service.health.drafting_since = now
    service.health.last_pick_change = now

    assert service.health.picks_stale(now=now + PICK_SILENCE_S - 1) is False
    assert service.health.picks_stale(now=now + PICK_SILENCE_S + 1) is True


def test_g1_a_draft_that_never_delivers_one_pick_still_fires(
    service: CockpitService,
) -> None:
    """The precise 2026-09-05 shape: the draft opened and not a single pick ever arrived.

    There is no last-pick timestamp to measure from, so without `drafting_since` there is no
    anchor and the silence would read as zero forever.
    """
    now = time.time()
    service.health.drafting_since = now
    service.health.last_pick_change = None
    assert service.health.picks_stale(now=now + PICK_SILENCE_S + 1) is True


# --- injection 1: freeze the feed and the detector must detect ------------------------


def test_injection_freezing_the_feed_raises_the_warning(service: CockpitService) -> None:
    """Replay a draft that starts, delivers three picks, then goes silent.

    Everything here is a SUCCESSFUL poll -- that is the whole point. The frozen half is
    exactly what a stuck ETag produces: the adapter replays the body it already had, the
    update is identical, and nothing raises.
    """
    picks: list[Pick] = []
    service._apply(_update(picks, "drafting"))
    started = service.health.drafting_since
    assert started is not None, "the draft opening must anchor the clock"

    for n in (1, 2, 3):
        picks = picks + [_pick(n)]
        service._apply(_update(picks, "drafting"))
    delivered = service.health.last_pick_change
    assert delivered is not None and delivered >= started

    # ...and now the feed freezes. Same picks, forever.
    for _ in range(40):
        service._apply(_update(picks, "drafting"))
    assert service.health.last_pick_change == delivered, "an identical slate is not a change"

    assert service.health.picks_stale(now=delivered + PICK_SILENCE_S - 1) is False
    assert service.health.picks_stale(now=delivered + PICK_SILENCE_S + 1) is True


def test_a_pick_arriving_clears_the_warning(service: CockpitService) -> None:
    """The other half of any alarm: it has to go out again."""
    picks = [_pick(1)]
    service._apply(_update(picks, "drafting"))
    service.health.drafting_since = time.time() - 10_000
    service.health.last_pick_change = time.time() - 10_000
    assert service.health.picks_stale() is True

    service._apply(_update(picks + [_pick(2)], "drafting"))
    assert service.health.picks_stale() is False


def test_a_hand_entered_pick_does_not_silence_the_feed_warning(
    service: CockpitService,
) -> None:
    """Deliberate, and the opposite of what a naive 'last pick' clock would do.

    Mirroring the room by hand keeps the BOARD correct. It is not evidence the feed came
    back, and letting it reset the clock would switch the warning off at exactly the moment
    someone is working around a dead feed.
    """
    service._apply(_update([], "drafting"))
    service.health.drafting_since = time.time() - 10_000
    assert service.health.picks_stale() is True

    entry = service.board.entries[0] if service.board else None
    assert entry is not None
    service.mark_taken(entry.player_id)

    assert service.session.manual_picks, "the manual pick was recorded"
    assert service.health.picks_stale() is True, "and the feed warning stands"


# --- injection 2: a threshold that cannot move is decoration --------------------------


def test_injection_a_zero_threshold_makes_the_warning_permanent(
    monkeypatch: pytest.MonkeyPatch, service: CockpitService
) -> None:
    """Prove the number is live. With the limit at 0 every in-progress moment is stale."""
    import audible.draft.service as service_mod

    monkeypatch.setattr(service_mod, "PICK_SILENCE_S", 0.0)
    now = time.time()
    service.health.drafting_since = now
    service.health.last_pick_change = now
    assert service.health.picks_stale(now=now) is True, "at zero, silence is instant"

    monkeypatch.setattr(service_mod, "PICK_SILENCE_S", 10_000.0)
    assert service.health.picks_stale(now=now + 5_000) is False, "and a huge limit silences it"


# --- the ETag mitigation --------------------------------------------------------------


def test_the_draft_poll_periodically_forgoes_its_conditional_request(
    espn_config: LeagueConfig,
) -> None:
    """A stuck ETag must not be able to hide a whole draft.

    Nothing in this repo has ever recorded a live ESPN ETag, so whether it advances as picks
    land is unsettled and cannot be settled offline. This is the mitigation that makes the
    answer stop being load-bearing: every Nth poll asks for a full body regardless, bounding
    the blindness to well under one ninety-second pick clock.

    The handler below is the pessimistic case -- an ETag that NEVER changes. Without the
    periodic skip every request after the first is a 304 and the adapter replays its first
    body forever, which for a cockpit started before kickoff is the pre-draft placeholder
    slate for the entire draft.
    """
    payload = json.loads((FIXTURES / "espn_draft_detail.json").read_text(encoding="utf-8"))
    conditional: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent = "If-None-Match" in request.headers
        conditional.append(sent)
        if sent:
            return httpx.Response(304, headers={"etag": 'W/"frozen"'})
        return httpx.Response(200, json=payload, headers={"etag": 'W/"frozen"'})

    adapter = EspnAdapter(swid="{x}", espn_s2="s2", transport=httpx.MockTransport(handler))
    rounds = 3
    for _ in range(DRAFT_FULL_BODY_EVERY * rounds):
        adapter.get_draft_detail(espn_config)

    # The property that matters is BOUNDED BLINDNESS, not a count: however long the run,
    # never more than N-1 conditional requests can pass without a real body. At a 5s poll
    # that is under 30s, a third of a ninety-second pick clock.
    longest_blind = 0
    run = 0
    for sent in conditional:
        run = run + 1 if sent else 0
        longest_blind = max(longest_blind, run)
    assert longest_blind <= DRAFT_FULL_BODY_EVERY - 1, (
        f"a stuck ETag could hide {longest_blind} consecutive polls: {conditional}"
    )
    assert conditional[0] is False, "the first poll has no ETag to send"
    assert conditional.count(False) == rounds + 1, (
        f"one free first poll plus one forced per {DRAFT_FULL_BODY_EVERY}: {conditional}"
    )
    assert any(conditional), "and the conditional request is still used the rest of the time"


# --- injection 4: unmap statId 63 and the residual must come back ---------------------


def _woody_marks() -> dict[str, Any] | None:
    # From __file__, NOT the cwd. Relative to the cwd this skipped silently whenever pytest
    # was invoked from anywhere else -- and a skip exits 0, which is the worst way for the
    # only test pinning Task 4 to fail.
    path = Path(__file__).resolve().parents[1] / "data" / "cache" / (
        "espn_stat_lines_73131979_2025.json"
    )
    if not path.exists():
        return None
    for row in json.loads(path.read_text(encoding="utf-8")).values():
        if float(row.get("raw", {}).get("63", 0) or 0) > 0:
            return row
    return None


def test_injection_unmapping_stat_id_63_restores_the_documented_residual() -> None:
    """statId 63 was the ENTIRE difference between our recomputation and ESPN's total.

    Paying it is only worth anything if not paying it is measurably wrong, so this scores the
    one carrier in the pinned 2025 corpus both ways. Skips where the corpus is absent -- it is
    gitignored local data, not something a clone has.
    """
    row = _woody_marks()
    if row is None:
        pytest.skip("no pinned ESPN stat lines with a statId 63 carrier on this machine")

    from audible.config.loader import load_all_leagues

    cfg = load_all_leagues()["espn_green_hope"]
    position = str(row["position"])
    weights = cfg.scoring_for(position)
    applied = float(row["applied"])

    paid = score_stat_line(
        translate_stat_line(row["raw"], position, frozenset(STAT_ID_TO_KEY)), weights
    )
    assert abs(paid - applied) < 0.005, f"with 63 paid the line reconciles exactly: {paid}"

    unmapped = frozenset(k for k in STAT_ID_TO_KEY if k != 63)
    without = score_stat_line(translate_stat_line(row["raw"], position, unmapped), weights)
    assert abs((without - applied) + 6.0) < 0.005, (
        f"unmapping 63 must restore exactly the documented -6.00: {without - applied:+.2f}"
    )


# --- what the adversarial review found, pinned so it cannot come back -----------------


def test_a_status_blip_does_not_erase_accumulated_silence(service: CockpitService) -> None:
    """One odd poll must not wipe out how long the feed has been quiet.

    The first version cleared `drafting_since` on ANY non-drafting status and re-armed it to
    `now` on the way back in. Measured against that: an hour of a completely frozen slate,
    with a single non-drafting poll a minute, never published more than 50 seconds of
    silence and never once warned.
    """
    service._apply(_update([_pick(1)], "drafting"))
    service.health.drafting_since = time.time() - 600
    service.health.last_pick_change = time.time() - 600
    assert service.health.picks_stale() is True

    service._apply(_update([_pick(1)], "weird_unknown_status"))
    service._apply(_update([_pick(1)], "drafting"))

    assert service.health.picks_stale() is True, "a blip discarded ten minutes of silence"
    assert service.health.pick_silence_s() >= 600


def test_an_emptied_slate_is_not_a_pick_delivery(service: CockpitService) -> None:
    """A slate that SHRANK is the feed breaking, not a pick arriving.

    An all-placeholder ESPN response parses to zero picks, and Sleeper's 304 path hands back
    an empty list for a draft id it has not seen. Either would otherwise stamp the clock and
    clear the warning at the exact moment the feed died.
    """
    service._apply(_update([_pick(n) for n in (1, 2, 3)], "drafting"))
    service.health.drafting_since = time.time() - 600
    service.health.last_pick_change = time.time() - 600
    assert service.health.picks_stale() is True

    service._apply(_update([], "drafting"))
    assert service.health.picks_stale() is True, "an empty slate cleared the warning"


def test_a_pause_is_quiet_on_purpose_and_is_not_called_a_failure(
    service: CockpitService,
) -> None:
    """Silence is still measured through a pause -- it is just not an alarm."""
    service._apply(_update([_pick(1)], "drafting"))
    service.health.drafting_since = time.time() - 600
    service.health.last_pick_change = time.time() - 600
    assert service.health.picks_stale() is True

    service._apply(_update([_pick(1)], "paused"))
    assert service.health.paused is True
    assert service.health.picks_stale() is False, "a pause is not a failure"
    assert service.health.pick_silence_s() >= 600, "but the silence is still counted"

    service._apply(_update([_pick(1)], "drafting"))
    assert service.health.picks_stale() is True, "and it returns when play resumes"


def test_a_restart_carries_the_silence_forward(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """A cockpit restarted mid-draft must not forget a feed that is already dead.

    SyncHealth is not part of DraftSession, so the two silence clocks are persisted
    alongside it. Without that, a crash-restart every two minutes against a totally dead
    feed never published more than 115s of silence and never warned at all.
    """
    first = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    first._apply(_update([_pick(1)], "drafting"))
    dead_since = time.time() - 1200
    first.health.drafting_since = dead_since
    first.health.last_pick_change = dead_since
    first.save()
    assert first.health.picks_stale() is True

    second = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    assert second.restore() is True
    assert second.health.drafting_since == pytest.approx(dead_since)
    assert second.health.picks_stale() is True, "the restart re-armed a fresh blind window"


def test_a_feed_frozen_BEFORE_the_draft_opens_is_not_caught_here(
    service: CockpitService,
) -> None:
    """The honest limit of this detector, pinned rather than papered over.

    If the ESPN body freezes while it still says `pre_draft`, the status the anchor keys off
    is frozen too -- it rides the same response as the picks. So this layer cannot see that
    case, and drafting_since is never armed.

    That case is covered by the OTHER half of this change: `get_draft_detail` forces a full
    body every sixth poll, so a stuck ETag cannot hold the status at pre_draft for more than
    about thirty seconds. The two halves COMPOSE; they are not independent safety nets, and
    any claim that this one catches a frozen feed "whatever the cause" is wrong.
    """
    for _ in range(200):
        service._apply(_update([], "pre_draft"))

    later = time.time() + 7200
    assert service.health.drafting_since is None
    assert service.health.pick_silence_s(now=later) is None
    assert service.health.picks_stale(now=later) is False
