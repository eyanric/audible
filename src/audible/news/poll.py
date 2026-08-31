"""Fetch -> match -> classify -> store, and the background loop that drives it.

NOT A CRONJOB, and the reason is infrastructural rather than stylistic: `ceph-block` is
RWO/RBD and node-scoped, so a CronJob pod and the Deployment pod cannot both hold the news
volume. The poll therefore lives inside the process that already has it mounted.

NEWS NEVER GATES THE BOARD. Every failure here is logged and swallowed. `/healthz` gains a
`news` block so the state is visible, but it is reporting, not readiness -- a dead website
must never be able to make the cockpit look unhealthy on a draft night.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

from ..adapters.feeds import Feed, FeedAdapter, load_feeds
from .classify import classify
from .entities import PlayerIndex
from .store import NewsStore

log = logging.getLogger(__name__)

ENV_POLL_ENABLED = "AUDIBLE_NEWS_POLL"
DEFAULT_INTERVAL_S = 900.0


def poll_enabled() -> bool:
    return os.environ.get(ENV_POLL_ENABLED, "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass(slots=True)
class PollResult:
    feed_id: str
    fetched: int
    inserted: int
    skipped: int
    matched: int
    error: str | None = None


def poll_feed(
    feed: Feed, adapter: FeedAdapter, index: PlayerIndex | None, store: NewsStore
) -> PollResult:
    """One feed, end to end. Never raises."""
    try:
        items = adapter.fetch(feed)
    except Exception as exc:  # noqa: BLE001 -- a poll loop must survive any website
        log.warning("feed %s failed: %s", feed.id, exc)
        store.record_poll(feed.id, ok=False, error=str(exc))
        return PollResult(feed.id, 0, 0, 0, 0, error=str(exc))

    rows: list[dict[str, object]] = []
    matched = 0
    for item in items:
        player_id = None
        confidence = None
        if index is not None:
            m = index.match(item.title, item.body)
            player_id, confidence = m.player_id, m.confidence
            if player_id:
                matched += 1
        c = classify(item.title, item.body)
        rows.append({
            "guid": item.guid, "feed_id": item.feed_id, "title": item.title,
            "body": item.body, "link": item.link, "published_at": item.published_at,
            "player_id": player_id, "match_confidence": confidence,
            "event_type": c.event_type, "severity": c.severity, "raw": item.raw,
        })
    inserted, skipped = store.upsert(rows)
    # An empty fetch is ambiguous -- unchanged feed, or dead website. Ask the adapter which,
    # or /healthz reports a rolling last_success straight through an outage.
    failure = adapter.last_error(feed.id)
    store.record_poll(feed.id, ok=failure is None, items=inserted, error=failure)
    return PollResult(feed.id, len(items), inserted, skipped, matched, error=failure)


def poll_once(
    *, store: NewsStore | None = None, index: PlayerIndex | None = None,
    feeds: list[Feed] | None = None, adapter: FeedAdapter | None = None,
) -> list[PollResult]:
    store = store or NewsStore()
    feeds = feeds if feeds is not None else load_feeds()
    owns_adapter = adapter is None
    adapter = adapter or FeedAdapter()
    try:
        return [poll_feed(f, adapter, index, store) for f in feeds]
    finally:
        if owns_adapter:
            adapter.close()


class NewsPoller:
    """Background thread for `serve`. Per-feed intervals; one slow feed delays only itself."""

    def __init__(self, store: NewsStore | None = None, index: PlayerIndex | None = None) -> None:
        self._store = store or NewsStore()
        self._index = index
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next: dict[str, float] = {}

    def start(self) -> None:
        if not poll_enabled():
            log.info("news polling disabled (set %s=1 to enable)", ENV_POLL_ENABLED)
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="news-poll", daemon=True)
        self._thread.start()
        log.info("news polling started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        feeds = load_feeds()
        with FeedAdapter() as adapter:
            while not self._stop.is_set():
                now = time.time()
                for feed in feeds:
                    if self._stop.is_set():
                        break
                    if self._next.get(feed.id, 0.0) > now:
                        continue
                    try:
                        result = poll_feed(feed, adapter, self._index, self._store)
                        log.info("news %s: %d fetched, %d new, %d matched",
                                 feed.id, result.fetched, result.inserted, result.matched)
                    except Exception as exc:  # noqa: BLE001 -- never kill the thread
                        log.warning("news poll for %s raised: %s", feed.id, exc)
                    self._next[feed.id] = time.time() + (
                        feed.poll_interval_s or DEFAULT_INTERVAL_S)
                self._stop.wait(30.0)

    def health(self) -> dict[str, object]:
        return self._store.health()
