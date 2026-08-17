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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..adapters.cache import DEFAULT_CACHE_DIR
from ..config.schema import LeagueConfig
from .board import DraftBoard, build_board
from .identity import SOURCE_DRAFT_ORDER, SOURCE_UNRESOLVED
from .live import LiveView, Pick, compute_view, my_slot_on_clock
from .sync import DraftSync, DraftUpdate, build_sync

log = logging.getLogger("audible.cockpit")

POLL_INTERVAL_S = 5.0
STALE_AFTER_S = 10.0
FAILING_AFTER_S = 30.0

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

    def age_s(self, now: float | None = None) -> float | None:
        if self.last_success is None:
            return None
        return max(0.0, (now if now is not None else time.time()) - self.last_success)

    def status(self, now: float | None = None) -> str:
        age = self.age_s(now)
        if age is None:
            return "failing" if self.last_error else "starting"
        if self.fail_streak and age >= FAILING_AFTER_S:
            return "failing"
        if age >= FAILING_AFTER_S:
            return "failing"
        return "stale" if age >= STALE_AFTER_S else "live"


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
        user_name: str | None = None,
        state_dir: Path | None = None,
        poll_interval_s: float = POLL_INTERVAL_S,
        top: int = 60,
        sync: DraftSync | None = None,
    ) -> None:
        self.config = config
        self._slot_override = slot_override
        self._user_name = user_name
        self._poll_interval_s = poll_interval_s
        self._top = top
        self._state_dir = state_dir if state_dir is not None else DEFAULT_CACHE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self.board: DraftBoard | None = None
        self.board_error: str | None = None
        self.health = SyncHealth()
        self.session = DraftSession(league_key=config.key, draft_id=draft_id)

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
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.session.to_json(), fh)
        tmp.replace(self._state_path)  # atomic: a crash mid-write must not corrupt the session

    def restore(self) -> bool:
        path = self._state_path
        if not path.exists():
            return False
        try:
            with path.open(encoding="utf-8") as fh:
                restored = DraftSession.from_json(json.load(fh))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            log.warning("ignoring unreadable draft state %s: %s", path, exc)
            return False
        if restored.league_key != self.config.key:
            return False
        keep_id = self.session.draft_id or restored.draft_id
        self.session = restored
        self.session.draft_id = keep_id
        log.info("restored %d picks from %s", len(self.session.picks), path)
        return True

    # --- board -------------------------------------------------------------
    def warm_board(self) -> None:
        """Build the board once, up front. Never called from a request path."""
        try:
            self.board = build_board(self.config)
            self.board_error = None
            log.info("board ready: %d players", len(self.board.entries))
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
            session.user_id = update.identity.user_id
            session.roster_id = update.identity.roster_id
            session.slot = update.identity.slot
            session.slot_source = update.identity.source
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
                self.config, slot_override=self._slot_override, user_name=self._user_name
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
