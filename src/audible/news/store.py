"""SQLite store for collected news items.

WHY A SEPARATE DIRECTORY. `AUDIBLE_NEWS_DIR` is load-bearing rather than tidiness: in the
cluster `/app/data` is an emptyDir, and news history cannot be re-fetched -- Rotowire's feed
serves five items, so a restart with news on emptyDir loses everything older than the last
poll, permanently. In-cluster this points at a separate PVC.

`raw` is kept deliberately. The classifier's job is filtering, not interpretation; a human
reads the original text over MCP and supplies the judgment. Throwing away the source text to
save bytes would trade the useful half for the cheap half.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

log = logging.getLogger(__name__)

ENV_NEWS_DIR = "AUDIBLE_NEWS_DIR"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NEWS_DIR = _REPO_ROOT / "data" / "news"
DB_NAME = "news.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    guid             TEXT PRIMARY KEY,
    feed_id          TEXT NOT NULL,
    title            TEXT NOT NULL,
    body             TEXT NOT NULL DEFAULT '',
    link             TEXT NOT NULL DEFAULT '',
    published_at     REAL,
    fetched_at       REAL NOT NULL,
    player_id        TEXT,
    match_confidence TEXT,
    event_type       TEXT,
    severity         INTEGER,
    raw              TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_player_published ON items(player_id, published_at);
CREATE INDEX IF NOT EXISTS idx_items_published        ON items(published_at);
CREATE TABLE IF NOT EXISTS feed_state (
    feed_id        TEXT PRIMARY KEY,
    last_success   REAL,
    last_attempt   REAL,
    last_error     TEXT,
    items_seen     INTEGER NOT NULL DEFAULT 0
);
"""


def news_dir() -> Path:
    raw = os.environ.get(ENV_NEWS_DIR)
    return Path(raw) if raw else DEFAULT_NEWS_DIR


class NewsStats(TypedDict):
    """The shape `stats()` returns. Declared so callers can do arithmetic on it."""

    total: int
    matched: int
    match_rate: float
    by_feed: dict[str, int]
    by_event: dict[str, int]
    by_confidence: dict[str, int]
    oldest: float | None
    newest: float | None
    db_bytes: int
    feeds: list[dict[str, Any]]


@dataclass(slots=True)
class StoredItem:
    guid: str
    feed_id: str
    title: str
    body: str
    link: str
    published_at: float | None
    fetched_at: float
    player_id: str | None
    match_confidence: str | None
    event_type: str | None
    severity: int | None
    raw: str


class NewsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else news_dir() / DB_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- writing -------------------------------------------------------------------
    def upsert(self, rows: Iterable[dict[str, object]]) -> tuple[int, int]:
        """Insert new items, ignore ones already seen. Returns (inserted, skipped).

        `INSERT OR IGNORE` on the guid primary key is the whole dedupe story: a feed that
        re-serves the same fifty items every fifteen minutes costs one failed insert each,
        and re-polling can never duplicate history.
        """
        inserted = 0
        total = 0
        now = time.time()
        with self._conn() as conn:
            for row in rows:
                total += 1
                cur = conn.execute(
                    """INSERT OR IGNORE INTO items
                       (guid, feed_id, title, body, link, published_at, fetched_at,
                        player_id, match_confidence, event_type, severity, raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["guid"], row["feed_id"], row["title"], row.get("body", ""),
                        row.get("link", ""), row.get("published_at"), now,
                        row.get("player_id"), row.get("match_confidence"),
                        row.get("event_type"), row.get("severity"),
                        row.get("raw", ""),
                    ),
                )
                inserted += cur.rowcount or 0
        return inserted, total - inserted

    def record_poll(
        self, feed_id: str, *, ok: bool, items: int = 0, error: str | None = None
    ) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO feed_state (feed_id, last_success, last_attempt, last_error,
                                           items_seen)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(feed_id) DO UPDATE SET
                     last_success = CASE WHEN ? THEN ? ELSE feed_state.last_success END,
                     last_attempt = ?,
                     last_error   = ?,
                     items_seen   = feed_state.items_seen + ?""",
                (feed_id, now if ok else None, now, error, items,
                 ok, now, now, error, items),
            )

    # --- reading -------------------------------------------------------------------
    def recent(
        self,
        *,
        hours: float = 48.0,
        player_id: str | None = None,
        min_severity: int | None = None,
        limit: int = 200,
        now: float | None = None,
    ) -> list[StoredItem]:
        cutoff = (now if now is not None else time.time()) - hours * 3600.0
        sql = ["SELECT * FROM items WHERE COALESCE(published_at, fetched_at) >= ?"]
        args: list[object] = [cutoff]
        if player_id is not None:
            sql.append("AND player_id = ?")
            args.append(player_id)
        if min_severity is not None:
            sql.append("AND severity >= ?")
            args.append(min_severity)
        sql.append("ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?")
        args.append(limit)
        with self._conn() as conn:
            rows = conn.execute(" ".join(sql), args).fetchall()
        return [StoredItem(**dict(r)) for r in rows]

    def stats(self) -> NewsStats:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            matched = conn.execute(
                "SELECT COUNT(*) FROM items WHERE player_id IS NOT NULL").fetchone()[0]
            by_feed = {
                r["feed_id"]: r["n"] for r in conn.execute(
                    "SELECT feed_id, COUNT(*) AS n FROM items GROUP BY feed_id ORDER BY n DESC")
            }
            by_event = {
                (r["event_type"] or "unclassified"): r["n"] for r in conn.execute(
                    "SELECT event_type, COUNT(*) AS n FROM items GROUP BY event_type "
                    "ORDER BY n DESC")
            }
            by_conf = {
                (r["match_confidence"] or "none"): r["n"] for r in conn.execute(
                    "SELECT match_confidence, COUNT(*) AS n FROM items "
                    "GROUP BY match_confidence ORDER BY n DESC")
            }
            span = conn.execute(
                "SELECT MIN(COALESCE(published_at, fetched_at)), "
                "       MAX(COALESCE(published_at, fetched_at)) FROM items").fetchone()
            feeds = [dict(r) for r in conn.execute("SELECT * FROM feed_state")]
        return NewsStats(
            total=total,
            matched=matched,
            match_rate=(matched / total) if total else 0.0,
            by_feed=by_feed,
            by_event=by_event,
            by_confidence=by_conf,
            oldest=span[0],
            newest=span[1],
            db_bytes=self.path.stat().st_size if self.path.exists() else 0,
            feeds=feeds,
        )

    def health(self) -> dict[str, object]:
        """The `news` block for /healthz. Never gates readiness -- see poll.py."""
        s = self.stats()
        return {
            "items": s["total"],
            "matched": s["matched"],
            "db_bytes": s["db_bytes"],
            "feeds": {
                f["feed_id"]: {
                    "last_success": f["last_success"],
                    "last_error": f["last_error"],
                    "items_seen": f["items_seen"],
                }
                for f in s["feeds"]
            },
        }

    def export_jsonl(self, out: Path) -> int:
        with self._conn() as conn, out.open("w", encoding="utf-8") as fh:
            n = 0
            for r in conn.execute("SELECT * FROM items ORDER BY fetched_at"):
                fh.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
                n += 1
        return n
