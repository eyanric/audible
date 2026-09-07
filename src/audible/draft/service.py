"""The cockpit service: one board, one draft state, one poll loop.

Both surfaces -- the CLI (`audible live`) and the HTTP server (`audible serve`) -- read from
this. It owns everything stateful about a live draft so nothing else has to:

* the warmed board (built once, held in memory, never rebuilt on a request path),
* the picks last seen from Sleeper plus any manual mark-taken overrides,
* how long ago the last successful poll was, which is the number that decides whether anything
  on screen can be trusted,
* my draft slot, resolved from ``draft_order`` the moment the draft opens.

The decision logic itself is NOT here -- it stays in :mod:`audible.draft.live`, unchanged and
still covered by the 180-pick replay. This layer only feeds it and caches the answer.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..adapters.cache import DEFAULT_CACHE_DIR
from ..config.schema import LeagueConfig
from .board import DraftBoard, build_board
from .identity import SOURCE_DRAFT_ORDER, SOURCE_OVERRIDE, SOURCE_UNRESOLVED
from .live import LiveView, Pick, compute_view, my_slot_on_clock
from .sync import DraftSync, DraftUpdate, build_sync
from .usage import UsageTable, load_usage

log = logging.getLogger("audible.cockpit")

POLL_INTERVAL_S = 5.0
STALE_AFTER_S = 10.0
FAILING_AFTER_S = 30.0

# How long the FEED may go without delivering a pick while the draft is running before the
# cockpit says so. Every number above measures the age of the last successful POLL, which is
# a different question and the reason 2026-09-05 was invisible: ESPN answers a conditional
# request with 304, the adapter replays the body it already had, nothing raises, and
# `last_success` advances. A whole draft can run that way with `sync_status: "live"` and
# `picks: 0`.
#
# 180s is two full pick clocks for the SLOWEST league here. One clock cannot trip it -- a
# manager using every second of their turn is normal, and an indicator that cries during
# normal play is one nobody reads by round three. Two consecutive clocks with nothing
# arriving is not something a healthy draft does.
#
# 90s is espn_green_hope's clock, the longest of the three and the one drafting 2026-09-08.
# League A runs a 60s timer (`pick_timer: 60` in tests/fixtures/sleeper_draft_2025.json), so
# the same 180s is THREE clocks there. Deliberately one threshold rather than one per league:
# the slowest league sets it, which makes the number conservative everywhere and impossible
# to trip during normal play on the faster ones. If a league ever runs a clock longer than
# 90s, this has to move with it.
PICK_CLOCK_S = 90.0
PICK_SILENCE_S = 2 * PICK_CLOCK_S

# Retry with jitter on a failed poll. A draft is 180 picks over a couple of hours; a transient
# 5xx must cost a beat, never the session.
RETRY_BASE_S = 1.0
RETRY_MAX_S = 8.0


@dataclass
class SyncHealth:
    last_success: float | None = None
    last_error: str | None = None
    poll_count: int = 0
    fail_streak: int = 0
    # The SECOND clock. `last_success` answers "did the last request work"; these answer "is
    # the feed actually delivering". A 304 satisfies the first and says nothing about the
    # second, which is the whole defect.
    #
    # `last_pick_change` moves only when the SYNCED pick slate actually changes. A pick typed
    # in by hand deliberately does not touch it: hand-entry keeps the BOARD current, it is not
    # evidence the feed recovered, and letting it reset the clock would silence the warning
    # exactly when someone is working around a dead feed.
    last_pick_change: float | None = None
    # When the draft was first seen in progress. Without it a draft that opens and never
    # delivers a single pick has no anchor to measure silence from, and that is the precise
    # shape of the 2026-09-05 failure.
    drafting_since: float | None = None
    # Set while the platform reports an explicit pause. The silence is still measured and
    # still shown; it is simply not called a failure, because it is quiet on purpose.
    paused: bool = False

    def age_s(self, now: float | None = None) -> float | None:
        if self.last_success is None:
            return None
        return max(0.0, (now if now is not None else time.time()) - self.last_success)

    def pick_silence_s(self, now: float | None = None) -> float | None:
        """Seconds since the feed last delivered a pick, or None when the draft is not live.

        None is the pre-draft answer and it is load-bearing. Before the draft opens a feed
        that has delivered nothing is CORRECT, and an age-only check cannot tell that apart
        from a draft in progress delivering nothing. Returning None means the caller cannot
        accidentally render a permanent false alarm on a quiet Tuesday afternoon.
        """
        if self.drafting_since is None:
            return None
        anchors = [t for t in (self.last_pick_change, self.drafting_since) if t is not None]
        return max(0.0, (now if now is not None else time.time()) - max(anchors))

    def picks_stale(self, now: float | None = None) -> bool:
        if self.paused:
            return False
        silence = self.pick_silence_s(now)
        return silence is not None and silence >= PICK_SILENCE_S

    def status(self, now: float | None = None) -> str:
        age = self.age_s(now)
        if age is None:
            return "failing" if self.last_error else "starting"
        if self.fail_streak and age >= FAILING_AFTER_S:
            return "failing"
        if age >= FAILING_AFTER_S:
            return "failing"
        return "stale" if age >= STALE_AFTER_S else "live"


# The one status value that means "the clock is running". The vocabulary is Sleeper's for
# both platforms -- `sync.espn_draft_status` translates ESPN's two booleans into it.
DRAFTING_STATUS = "drafting"

# Statuses that genuinely end a draft's run, and the ONLY ones that clear the silence anchor.
# Anything else -- a pause, an unrecognised string, a momentary flap -- leaves it armed, so a
# blip cannot wipe out how long the feed has actually been quiet.
_NOT_RUNNING = frozenset({"pre_draft", "complete", ""})

# Sleeper publishes an explicit pause. A paused draft is quiet ON PURPOSE, so the silence is
# still measured and still shown, but it is not called a failure. ESPN has no pause in its
# vocabulary at all -- `espn_draft_status` maps only drafted/inProgress -- so a paused ESPN
# draft will read as silence. That is a known false alarm and it is the right way round: a
# spurious warning during a pause costs a glance, a missed one costs the draft.
PAUSED_STATUS = "paused"


def _pick_fingerprint(picks: Sequence[Pick]) -> tuple[int, int, str]:
    """Cheap identity for a pick slate: how many, how far, and who was last.

    Compared rather than hashed in full because this runs under the service lock on every
    tick. The last pick's number AND player are both included: a re-numbered slate of the
    same length, or a corrected player at the same number, are both real changes.
    """
    if not picks:
        return (0, 0, "")
    last = picks[-1]
    return (len(picks), last.pick_no, last.player_id)


def _pick_json(p: Pick) -> dict[str, Any]:
    return {"pick_no": p.pick_no, "round": p.round, "draft_slot": p.draft_slot,
            "player_id": p.player_id, "source": p.source}


def _pick_from_json(d: dict[str, Any], default_source: str) -> Pick:
    return Pick(
        pick_no=int(d["pick_no"]), round=int(d["round"]), draft_slot=int(d["draft_slot"]),
        player_id=str(d["player_id"]), source=str(d.get("source") or default_source),
    )


@dataclass
class DraftSession:
    """Everything mutable about one draft. Serialisable so a crash costs nothing."""

    league_key: str
    draft_id: str | None = None
    rounds: int = 18
    draft_status: str = "pre_draft"
    draft_type: str = "snake"
    picks: list[Pick] = field(default_factory=list)
    # Picks entered by hand, in the order they were entered. They are REAL picks -- numbered,
    # attributed to whichever slot is on the clock, and moving the clock -- not ghosts.
    manual_picks: list[Pick] = field(default_factory=list)
    slot: int | None = None
    slot_source: str = SOURCE_UNRESOLVED
    user_id: str | None = None
    roster_id: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "league_key": self.league_key, "draft_id": self.draft_id, "rounds": self.rounds,
            "draft_status": self.draft_status, "draft_type": self.draft_type,
            "picks": [_pick_json(p) for p in self.picks],
            "manual_picks": [_pick_json(p) for p in self.manual_picks],
            "slot": self.slot, "slot_source": self.slot_source,
            "user_id": self.user_id, "roster_id": self.roster_id,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DraftSession:
        session = cls(league_key=data["league_key"])
        session.draft_id = data.get("draft_id")
        session.rounds = int(data.get("rounds", 18))
        session.draft_status = data.get("draft_status", "pre_draft")
        session.draft_type = data.get("draft_type", "snake")
        session.picks = [_pick_from_json(p, "sync") for p in data.get("picks", [])]
        session.manual_picks = [
            _pick_from_json(p, "manual") for p in data.get("manual_picks", [])
        ]
        session.slot = data.get("slot")
        session.slot_source = data.get("slot_source", SOURCE_UNRESOLVED)
        session.user_id = data.get("user_id")
        session.roster_id = data.get("roster_id")
        return session

    def effective_picks(self) -> list[Pick]:
        """Synced and manual picks as one stream, in pick order.

        Deliberately indistinguishable downstream. An earlier version numbered manual marks
        ``pick_no = 0, draft_slot = 0`` so they could not move the clock -- which fixed the
        clock but attributed every mark to slot 0, i.e. to me whenever my slot was unresolved.
        One line produced "unlimited players join my roster", "undo leaves them there" and
        "no other team ever appears". Manual picks are now numbered and attributed like any
        other, and the clock advances because the pick really happened.
        """
        return sorted(self.picks + self.manual_picks, key=lambda p: p.pick_no)

    def taken_ids(self) -> set[str]:
        return {p.player_id for p in self.picks} | {p.player_id for p in self.manual_picks}


class CockpitService:
    """Owns the board, the session, and the single poll loop."""

    def __init__(
        self,
        config: LeagueConfig,
        *,
        draft_id: str | None = None,
        slot_override: int | None = None,
        slot_fallback: int | None = None,
        user_name: str | None = None,
        state_dir: Path | None = None,
        poll_interval_s: float = POLL_INTERVAL_S,
        top: int = 60,
        sync: DraftSync | None = None,
    ) -> None:
        self.config = config
        # `slot_override` is an operator's --slot and outranks the platform. `slot_fallback`
        # is the league's draft_slot, carried ONLY when the derivation says nothing. They were
        # one parameter until 2026-09-07, which is how a config pin came to beat a live seat.
        self._slot_override = slot_override
        self._slot_fallback = slot_fallback
        self._user_name = user_name
        self._poll_interval_s = poll_interval_s
        self._top = top
        self._state_dir = state_dir if state_dir is not None else DEFAULT_CACHE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self.board: DraftBoard | None = None
        self.board_error: str | None = None
        # Displayed usage context. Deliberately NOT on the board: it is looked up by player id
        # at the state boundary, after the board is built and ranked, so a usage row can never
        # move a player. Empty until warmed, and an empty table is a blank column, not an error.
        self.usage: UsageTable = UsageTable()
        self.health = SyncHealth()
        self.session = DraftSession(league_key=config.key, draft_id=draft_id)
        if config.draft_rounds is not None:
            self.session.rounds = config.draft_rounds

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # The platform seam. Injected in tests; built from the config's platform at start().
        self._sync: DraftSync | None = sync
        self._view_cache: tuple[int, LiveView] | None = None
        self._state_version = 0

    # --- persistence -------------------------------------------------------
    @property
    def _state_path(self) -> Path:
        return self._state_dir / f"draft-state-{self.config.key}.json"

    def save(self) -> None:
        tmp = self._state_path.with_suffix(".tmp")
        blob = self.session.to_json()
        # The silence clocks ride along with the session. Without this a cockpit restarted
        # mid-draft forgets how long the feed has been quiet and starts a fresh 180s blind
        # window -- measured: a crash-restart every two minutes against a completely dead
        # feed never published more than 115s of silence and never once warned. They are
        # wall-clock, so carrying them forward is what makes a 20-minute outage still read
        # as 20 minutes on the other side of a restart.
        blob["health"] = {
            "last_pick_change": self.health.last_pick_change,
            "drafting_since": self.health.drafting_since,
        }
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(blob, fh)
        tmp.replace(self._state_path)  # atomic: a crash mid-write must not corrupt the session

    def restore(self) -> bool:
        path = self._state_path
        if not path.exists():
            return False
        try:
            with path.open(encoding="utf-8") as fh:
                blob = json.load(fh)
            restored = DraftSession.from_json(blob)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            log.warning("ignoring unreadable draft state %s: %s", path, exc)
            return False
        if restored.league_key != self.config.key:
            return False
        keep_id = self.session.draft_id or restored.draft_id
        self.session = restored
        self.session.draft_id = keep_id
        health = blob.get("health") or {}
        for field_name in ("last_pick_change", "drafting_since"):
            value = health.get(field_name)
            if value is not None:
                setattr(self.health, field_name, float(value))
        log.info("restored %d picks from %s", len(self.session.picks), path)
        return True

    # --- board -------------------------------------------------------------
    def warm_board(self) -> None:
        """Build the board once, up front. Never called from a request path."""
        try:
            self.board = build_board(self.config)
            self.board_error = None
            log.info("board ready: %d players", len(self.board.entries))
            # After the board, and never blocking it: usage is display context, so a source
            # that will not load costs a column rather than the draft.
            # The canonical bye derivation lives on the serving side and self-checks;
            # usage takes its answer rather than deriving a second one. Imported here
            # rather than at module scope so `draft` keeps no import-time edge to `server`.
            from ..server.state import bye_weeks

            self.usage = load_usage(byes=bye_weeks(self.config.season))
            if self.usage.missing_sources:
                log.warning("usage context degraded, missing: %s",
                            ", ".join(self.usage.missing_sources))
            else:
                log.info("usage context ready: %d players", len(self.usage.by_player_id))
        except Exception as exc:  # noqa: BLE001 -- surfaced to the UI, never swallowed
            self.board_error = f"{type(exc).__name__}: {exc}"
            log.exception("board build failed")

    # --- polling -----------------------------------------------------------
    def _apply(self, update: DraftUpdate) -> None:
        """Fold one poll's truth into the session. Caller holds the lock.

        Every field but ``picks`` is optional: a poll that only asked for picks must not blank
        out the draft status, the round count or my slot just because it did not fetch them.
        """
        session = self.session
        if update.draft_id is not None:
            session.draft_id = update.draft_id
        if update.rounds is not None:
            session.rounds = update.rounds
        if update.status is not None:
            session.draft_status = update.status
        if update.draft_type is not None:
            session.draft_type = update.draft_type
        if update.identity is not None:
            # A pinned seat overrides the platform, so a disagreement would otherwise be
            # invisible -- exactly the failure the pin exists to prevent, inverted.
            #
            # This reads `derived_slot`, NOT `slot`. `slot` IS the override whenever one is
            # set, so comparing it against the override compared a value with itself and the
            # branch was unreachable on every league that pins a seat. `derived_slot` is what
            # the platform said independently, so the two can now actually differ.
            if update.identity.seat_conflict:
                # Says WHICH ONE WON, because the answer changed on 2026-09-07 and an operator
                # reading this log has to know whether the tool corrected itself or is still
                # serving the stale number.
                winner = (
                    "the pin is winning -- an explicit --slot outranks the platform"
                    if update.identity.source == SOURCE_OVERRIDE else
                    "the platform is winning; the config pin is stale and should be corrected"
                )
                log.error(
                    "SEAT DRIFT: pinned slot %s but the platform says %s. Serving %s (%s) -- "
                    "%s. Verify the draft room before trusting any timing number.",
                    update.identity.pinned_slot, update.identity.derived_slot,
                    update.identity.slot, update.identity.source, winner,
                )
            session.user_id = update.identity.user_id
            session.roster_id = update.identity.roster_id
            session.slot = update.identity.slot
            session.slot_source = update.identity.source
        # The staleness clock, stamped BEFORE the assignment because it needs both sides.
        # `update.picks` is rebuilt from the payload every tick, so it is never the same list
        # object as `session.picks` -- but on a 304 the adapter replays the identical body, so
        # the two compare EQUAL. That equality is exactly the signal: a poll that succeeded
        # and moved nothing.
        now = time.time()
        before, after = _pick_fingerprint(session.picks), _pick_fingerprint(update.picks)
        # A DELIVERY, not merely a difference. A slate that SHRANK is not evidence the feed is
        # working -- an all-placeholder ESPN response parses to zero picks, and Sleeper's own
        # 304 path hands back `self._picks_last.get(draft_id, [])`, which is empty for a draft
        # id it has never seen. Both would otherwise read as "a pick just arrived" and clear
        # the warning at the exact moment the feed broke.
        if after != before and after[0] >= before[0]:
            self.health.last_pick_change = now

        if session.draft_status == DRAFTING_STATUS and self.health.drafting_since is None:
            self.health.drafting_since = now
        self.health.paused = session.draft_status == PAUSED_STATUS
        if session.draft_status in _NOT_RUNNING:
            # Cleared only when the draft is definitively not running. Re-arming on the way
            # back in would otherwise DISCARD accumulated silence: one spurious non-drafting
            # poll a minute kept the anchor pinned to `now` forever, and an hour of a
            # completely frozen slate never published more than 50 seconds of silence.
            self.health.drafting_since = None

        session.picks = update.picks
        # Sync is authoritative: drop any hand-entered pick it now covers, and renumber the
        # rest to follow it. Without this, regaining sync after mirroring by hand
        # double-counts every player entered twice.
        self._reconcile_manual()

    def poll_once(self) -> bool:
        """One upstream refresh. Returns True on success. Never raises."""
        sync = self._sync
        if sync is None:
            return False
        try:
            with self._lock:
                want_meta = (
                    self.session.draft_id is None
                    or self.health.poll_count % 12 == 0  # ~once a minute
                    or self.session.slot is None
                )
                # Sleeper's draft_order is immutable once the draft opens, so that answer
                # sticks and the two requests behind it stop being made. ESPN ignores this --
                # its whole draft rides one response, so re-resolving costs nothing.
                slot_locked = self.session.slot_source == SOURCE_DRAFT_ORDER
                draft_id = self.session.draft_id

            update = sync.poll(draft_id, want_meta=want_meta, slot_locked=slot_locked)

            with self._lock:
                self._apply(update)
                self.health.last_success = time.time()
                self.health.last_error = None
                self.health.fail_streak = 0
                self.health.poll_count += 1
                self._invalidate()
            self.save()
            return True
        except Exception as exc:  # noqa: BLE001 -- a failed poll must never kill the cockpit
            with self._lock:
                self.health.last_error = f"{type(exc).__name__}: {exc}"
                self.health.fail_streak += 1
                self.health.poll_count += 1
            log.warning("poll failed (streak %d): %s", self.health.fail_streak,
                        self.health.last_error)
            return False

    def _run(self) -> None:
        while not self._stop.is_set():
            ok = self.poll_once()
            if ok:
                delay = self._poll_interval_s
            else:
                # jittered backoff, capped -- never abandon the draft
                delay = min(RETRY_MAX_S, RETRY_BASE_S * (2 ** min(self.health.fail_streak, 3)))
                delay *= 0.5 + random.random()
            self._stop.wait(delay)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("poll loop already started")  # one loop, exactly one
        if self._sync is None:
            self._sync = build_sync(
                self.config, slot_override=self._slot_override,
                slot_fallback=self._slot_fallback, user_name=self._user_name,
            )
        self._thread = threading.Thread(target=self._run, name="audible-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._sync is not None:
            self._sync.close()
            self._sync = None

    # --- manual picks ------------------------------------------------------
    def _renumber_manual(self) -> None:
        """Number manual picks contiguously after the last synced pick.

        Called after any change to either stream so the combined sequence never has a hole or
        a duplicate. Slot comes from the same snake math validated 180/180 against the real
        2025 draft, so a hand-entered pick lands on whichever team is genuinely on the clock.
        """
        teams, rounds = self.config.num_teams, self.session.rounds
        base = max((p.pick_no for p in self.session.picks), default=0)
        renumbered: list[Pick] = []
        for offset, pick in enumerate(self.session.manual_picks, start=1):
            number = base + offset
            slot = my_slot_on_clock(number, teams, rounds)
            if slot is None:
                break  # past the end of the draft; there is no such pick to record
            renumbered.append(Pick(
                pick_no=number, round=(number - 1) // teams + 1, draft_slot=slot,
                player_id=pick.player_id, source="manual",
            ))
        self.session.manual_picks = renumbered

    def _reconcile_manual(self) -> None:
        """Sync is authoritative; supersede any manual pick it now covers.

        Two cases, both real when mirroring a draft by hand and then regaining sync:
        the same player arrives from sync (drop the manual duplicate), and sync disagrees
        about who took him (sync wins -- it is the platform's own record). Anything sync has
        not yet reached is kept and renumbered to follow it, so hand-entered picks made while
        the feed was down are not lost.
        """
        synced = {p.player_id for p in self.session.picks}
        self.session.manual_picks = [
            p for p in self.session.manual_picks if p.player_id not in synced
        ]
        self._renumber_manual()

    def mark_taken(self, player_id: str) -> bool:
        """Record a pick made by whoever is on the clock. Never touches any platform.

        This is a PICK, not a note that someone is unavailable: it is numbered, attributed,
        and it advances the clock, because that is what happened in the room.
        """
        with self._lock:
            if player_id in self.session.taken_ids():
                return False
            self.session.manual_picks.append(
                Pick(pick_no=0, round=0, draft_slot=0, player_id=player_id, source="manual")
            )
            self._renumber_manual()
            if not any(p.player_id == player_id for p in self.session.manual_picks):
                return False  # the draft is full; there is no pick left to record
            self._invalidate()
        self.save()
        return True

    def undo_taken(self, player_id: str | None = None) -> str | None:
        """Reverse a manual pick and roll the clock back. With no id, the most recent one."""
        with self._lock:
            manual = self.session.manual_picks
            if not manual:
                return None
            if player_id is None:
                player_id = manual[-1].player_id
            if not any(p.player_id == player_id for p in manual):
                return None
            self.session.manual_picks = [p for p in manual if p.player_id != player_id]
            self._renumber_manual()
            self._invalidate()
        self.save()
        return player_id

    # --- the view ----------------------------------------------------------
    def _invalidate(self) -> None:
        """Bump the state version. Callers must already hold the lock."""
        self._state_version += 1
        self._view_cache = None

    def view(self) -> LiveView | None:
        """The computed decision surface, memoised until state actually changes.

        Keyed on a monotonic version rather than on collection sizes: mark A, undo, mark B
        leaves (len(picks), len(manual)) identical with different contents, so a size-based
        key is a collision waiting for the next refactor to stop invalidating explicitly.
        """
        if self.board is None:
            return None
        with self._lock:
            version = self._state_version
            cached = self._view_cache
            if cached is not None and cached[0] == version:
                return cached[1]
            picks = self.session.effective_picks()
            slot = self.session.slot  # may be None -- unresolved is a state, not slot 0
            rounds = self.session.rounds
        view = compute_view(self.board, picks, slot, self.config, rounds, top=self._top)
        with self._lock:
            self._view_cache = (version, view)
        return view
