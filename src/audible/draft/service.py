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
from ..adapters.sleeper import SleeperAdapter
from ..config.schema import LeagueConfig
from .board import DraftBoard, build_board
from .identity import SOURCE_DRAFT_ORDER, SOURCE_UNRESOLVED, Identity, resolve_slot
from .live import LiveView, Pick, compute_view, parse_picks

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


@dataclass
class DraftSession:
    """Everything mutable about one draft. Serialisable so a crash costs nothing."""

    league_key: str
    draft_id: str | None = None
    rounds: int = 18
    draft_status: str = "pre_draft"
    draft_type: str = "snake"
    picks: list[Pick] = field(default_factory=list)
    manual_taken: dict[str, int] = field(default_factory=dict)  # player_id -> order marked
    manual_seq: int = 0
    slot: int | None = None
    slot_source: str = SOURCE_UNRESOLVED
    user_id: str | None = None
    roster_id: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "league_key": self.league_key, "draft_id": self.draft_id, "rounds": self.rounds,
            "draft_status": self.draft_status, "draft_type": self.draft_type,
            "picks": [
                {"pick_no": p.pick_no, "round": p.round, "draft_slot": p.draft_slot,
                 "player_id": p.player_id}
                for p in self.picks
            ],
            "manual_taken": self.manual_taken, "manual_seq": self.manual_seq,
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
        session.picks = [
            Pick(pick_no=p["pick_no"], round=p["round"], draft_slot=p["draft_slot"],
                 player_id=p["player_id"])
            for p in data.get("picks", [])
        ]
        session.manual_taken = {str(k): int(v) for k, v in (data.get("manual_taken") or {}).items()}
        session.manual_seq = int(data.get("manual_seq", 0))
        session.slot = data.get("slot")
        session.slot_source = data.get("slot_source", SOURCE_UNRESOLVED)
        session.user_id = data.get("user_id")
        session.roster_id = data.get("roster_id")
        return session

    def effective_picks(self) -> list[Pick]:
        """Real picks plus manual marks, as one stream the decision layer can consume.

        Manual entries carry ``pick_no = 0`` and sort ahead of every real pick. Both details
        matter: the clock is ``max(pick_no) + 1``, so a non-zero synthetic number would advance
        the draft every time you tapped a name, and the positional-run window is the tail of
        this list, so a manual mark must not masquerade as a recent pick.
        """
        if not self.manual_taken:
            return self.picks
        ghosts = [
            Pick(pick_no=0, round=0, draft_slot=0, player_id=pid)
            for pid, _ in sorted(self.manual_taken.items(), key=lambda kv: kv[1])
        ]
        return ghosts + self.picks


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
        self._adapter: SleeperAdapter | None = None
        self._view_cache: tuple[int, int, LiveView] | None = None

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

    # --- draft discovery ---------------------------------------------------
    def _discover_draft(self, adapter: SleeperAdapter) -> None:
        """Find the draft and refresh its settings + my slot.

        Re-discovery is not an error path: if the commissioner deletes and recreates the draft
        while scheduling it, the id changes underneath us and a pinned id starts 404ing.
        """
        drafts = adapter.get_league_drafts(self.config.league_id)
        if not drafts:
            raise RuntimeError(f"league {self.config.league_id} has no drafts")
        self.session.draft_id = str(drafts[0]["draft_id"])

    def _refresh_draft_meta(self, adapter: SleeperAdapter) -> None:
        assert self.session.draft_id is not None
        draft = adapter.get_draft(self.session.draft_id)
        settings = draft.get("settings") or {}
        self.session.rounds = int(settings.get("rounds", self.session.rounds))
        self.session.draft_status = str(draft.get("status") or self.session.draft_status)
        self.session.draft_type = str(draft.get("type") or self.session.draft_type)

        # Slot resolution. draft_order is authoritative and immutable once the draft opens, so
        # that answer sticks; anything else is re-attempted until the draft actually opens.
        if self.session.slot_source == SOURCE_DRAFT_ORDER:
            return
        user_id = self.session.user_id
        if user_id is None and self._user_name:
            from .identity import user_id_for_name
            user_id = user_id_for_name(adapter.get_users(self.config.league_id), self._user_name)
        rosters = adapter.get_rosters(self.config.league_id) if user_id else []
        ident: Identity = resolve_slot(draft, rosters, user_id, override=self._slot_override)
        self.session.user_id = ident.user_id
        self.session.roster_id = ident.roster_id
        self.session.slot = ident.slot
        self.session.slot_source = ident.source

    # --- polling -----------------------------------------------------------
    def poll_once(self) -> bool:
        """One upstream refresh. Returns True on success. Never raises."""
        adapter = self._adapter
        if adapter is None:
            return False
        try:
            with self._lock:
                need_meta = (
                    self.session.draft_id is None
                    or self.health.poll_count % 12 == 0  # ~once a minute
                    or self.session.slot is None
                )
            if self.session.draft_id is None:
                self._discover_draft(adapter)
            if need_meta:
                try:
                    self._refresh_draft_meta(adapter)
                except Exception:  # noqa: BLE001 -- a stale id is recoverable; re-discover
                    log.warning("draft metadata refresh failed; re-discovering draft id")
                    self._discover_draft(adapter)
                    self._refresh_draft_meta(adapter)

            assert self.session.draft_id is not None
            raw = adapter.get_draft_picks(self.session.draft_id)
            picks = parse_picks(raw)
            with self._lock:
                self.session.picks = picks
                self.health.last_success = time.time()
                self.health.last_error = None
                self.health.fail_streak = 0
                self.health.poll_count += 1
                self._view_cache = None
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
        self._adapter = SleeperAdapter()
        self._thread = threading.Thread(target=self._run, name="audible-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._adapter is not None:
            self._adapter.close()
            self._adapter = None

    # --- manual overrides --------------------------------------------------
    def mark_taken(self, player_id: str) -> bool:
        """Locally mark a player unavailable. Idempotent; never touches any platform."""
        with self._lock:
            if player_id in self.session.manual_taken:
                return False
            self.session.manual_seq += 1
            self.session.manual_taken[player_id] = self.session.manual_seq
            self._view_cache = None
        self.save()
        return True

    def undo_taken(self, player_id: str | None = None) -> str | None:
        """Reverse a mark. With no id, reverses the most recent one."""
        with self._lock:
            if not self.session.manual_taken:
                return None
            if player_id is None:
                player_id = max(self.session.manual_taken.items(), key=lambda kv: kv[1])[0]
            if player_id not in self.session.manual_taken:
                return None
            del self.session.manual_taken[player_id]
            self._view_cache = None
        self.save()
        return player_id

    # --- the view ----------------------------------------------------------
    def view(self) -> LiveView | None:
        """The computed decision surface, memoised until state changes."""
        if self.board is None:
            return None
        with self._lock:
            key = (len(self.session.picks), len(self.session.manual_taken))
            cached = self._view_cache
            if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
                return cached[2]
            picks = self.session.effective_picks()
            slot = self.session.slot
            rounds = self.session.rounds
        view = compute_view(
            self.board, picks, slot if slot is not None else 0, self.config, rounds,
            top=self._top,
        )
        with self._lock:
            self._view_cache = (key[0], key[1], view)
        return view
