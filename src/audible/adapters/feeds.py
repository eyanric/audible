"""NFL news feeds: registry, conditional fetch, and parse.

READ-ONLY, like every adapter here. Nothing in this module writes to any platform.

CONDITIONAL GET, MEASURED. The house pattern is `SleeperAdapter.get_draft_picks`: send
`If-None-Match`, handle a 304 with an empty body, and keep the previous payload. That is
mirrored here, but with an honest caveat recorded at probe time on 2026-08-31: of the six
live feeds, only CBS served an `ETag` and **none** served `Last-Modified`. So the
conditional path is mostly inert against today's sources. It costs one header and it is
correct the moment a feed starts honouring it, which is why it is here rather than absent.

A feed that errors is logged and skipped. One bad feed never fails a poll -- news is a
convenience, and the board must not care whether a website is up.
"""

from __future__ import annotations

import hashlib
import logging
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "audible/0.1 (+personal)"
FEEDS_TOML = Path(__file__).resolve().parents[1] / "config" / "feeds.toml"
DEFAULT_TIMEOUT_S = 20.0


@dataclass(frozen=True, slots=True)
class Feed:
    id: str
    url: str
    name: str
    enabled: bool
    poll_interval_s: int
    kind: str  # "player_news" | "articles"


@dataclass(slots=True)
class FeedItem:
    """One entry, normalised across RSS 2.0 and Atom."""

    feed_id: str
    guid: str
    title: str
    body: str
    link: str
    published_at: float | None  # epoch seconds, UTC
    raw: str


@dataclass(slots=True)
class ProbeResult:
    feed_id: str
    url: str
    status: int | None
    content_type: str
    parses: str  # "rss" | "atom" | "unparseable" | "-"
    items: int
    newest_age_h: float | None
    etag: bool
    last_modified: bool
    error: str | None = None

    @property
    def healthy(self) -> bool:
        """Live enough to build on: parses, has items, and one is younger than a day."""
        return (
            self.status == 200
            and self.parses in ("rss", "atom")
            and self.items > 0
            and self.newest_age_h is not None
            and self.newest_age_h < 24.0
        )


def load_feeds(path: Path | None = None, *, include_disabled: bool = False) -> list[Feed]:
    """The registry. `enabled` is set by the probe, never by hand-optimism."""
    with (path or FEEDS_TOML).open("rb") as fh:
        raw = tomllib.load(fh)
    feeds = [
        Feed(
            id=str(f["id"]), url=str(f["url"]), name=str(f.get("name") or f["id"]),
            enabled=bool(f.get("enabled", False)),
            poll_interval_s=int(f.get("poll_interval_s", 900)),
            kind=str(f.get("kind") or "articles"),
        )
        for f in raw.get("feed", [])
    ]
    return feeds if include_disabled else [f for f in feeds if f.enabled]


def _epoch(parsed: Any) -> float | None:
    """feedparser's struct_time is already UTC; anything else is not trusted."""
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=UTC).timestamp()
    except (TypeError, ValueError):
        return None


def _stable_guid(feed_id: str, link: str, title: str, entry_id: str | None) -> str:
    """A feed that omits <guid> still needs a stable key, or every poll re-inserts it.

    Falls back to sha256(link+title) per the store contract. Prefixed with the feed id so
    two sources syndicating the same wire story stay separate rows -- they usually differ
    in body, and collapsing them would lose the one that had the useful text.
    """
    if entry_id:
        return f"{feed_id}:{entry_id}"
    digest = hashlib.sha256(f"{link}\n{title}".encode()).hexdigest()
    return f"{feed_id}:sha256:{digest}"


class FeedAdapter:
    """Fetches and parses the registry. Holds ETag/Last-Modified per feed, in memory."""

    name = "feeds"

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
            follow_redirects=True,
        )
        self._etag: dict[str, str] = {}
        self._modified: dict[str, str] = {}
        # Set when a feed answers 429/503 with Retry-After; polling skips it until then.
        self._retry_after: dict[str, float] = {}
        # Why a fetch returned nothing. `fetch` never raises, so without this a dead
        # website is indistinguishable from a quiet one and /healthz reports a rolling
        # last_success straight through an outage.
        self._last_error: dict[str, str] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FeedAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- fetching ------------------------------------------------------------------
    def _conditional_headers(self, feed_id: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        etag = self._etag.get(feed_id)
        if etag:
            headers["If-None-Match"] = etag
        modified = self._modified.get(feed_id)
        if modified:
            headers["If-Modified-Since"] = modified
        return headers

    def _remember(self, feed_id: str, resp: httpx.Response) -> None:
        etag = resp.headers.get("ETag")
        if etag:
            self._etag[feed_id] = etag
        modified = resp.headers.get("Last-Modified")
        if modified:
            self._modified[feed_id] = modified

    def _note_retry_after(self, feed_id: str, resp: httpx.Response) -> None:
        """Honour Retry-After. A news feed is never worth arguing with about rate limits."""
        value = resp.headers.get("Retry-After")
        if not value:
            self._retry_after[feed_id] = time.time() + 300.0
            return
        try:
            self._retry_after[feed_id] = time.time() + float(int(value))
        except ValueError:
            self._retry_after[feed_id] = time.time() + 300.0

    def deferred_until(self, feed_id: str) -> float | None:
        until = self._retry_after.get(feed_id)
        return until if until and until > time.time() else None

    def fetch(self, feed: Feed) -> list[FeedItem]:
        """Items for one feed. Empty on 304, on error, or while deferred by Retry-After.

        Never raises: the caller is a poll loop that must survive a dead website.
        """
        deferred = self.deferred_until(feed.id)
        if deferred is not None:
            log.info("feed %s deferred by Retry-After for %.0fs", feed.id, deferred - time.time())
            self._last_error[feed.id] = "deferred by Retry-After"
            return []
        try:
            resp = self._client.get(feed.url, headers=self._conditional_headers(feed.id))
        except httpx.HTTPError as exc:
            log.warning("feed %s fetch failed (%s); skipping this poll", feed.id, exc)
            self._last_error[feed.id] = f"{type(exc).__name__}: {exc}"
            return []

        if resp.status_code == 304:
            log.debug("feed %s unchanged (304)", feed.id)
            self._last_error.pop(feed.id, None)  # unchanged is a success, not a failure
            return []
        if resp.status_code in (429, 503):
            self._note_retry_after(feed.id, resp)
            log.warning("feed %s returned %s; backing off", feed.id, resp.status_code)
            self._last_error[feed.id] = f"HTTP {resp.status_code}"
            return []
        if resp.status_code != 200:
            log.warning("feed %s returned HTTP %s; skipping", feed.id, resp.status_code)
            self._last_error[feed.id] = f"HTTP {resp.status_code}"
            return []

        self._last_error.pop(feed.id, None)
        self._remember(feed.id, resp)
        return parse_feed(feed.id, resp.text)

    def last_error(self, feed_id: str) -> str | None:
        """Why the last fetch returned nothing, or None if it succeeded."""
        return self._last_error.get(feed_id)

    # --- probing -------------------------------------------------------------------
    def probe(self, feed: Feed, *, now: float | None = None) -> ProbeResult:
        """One unconditional fetch, reporting what the source actually serves.

        Deliberately does NOT send conditional headers -- the point is to see the body.
        """
        now = now if now is not None else time.time()
        try:
            resp = self._client.get(feed.url)
        except httpx.HTTPError as exc:
            return ProbeResult(feed.id, feed.url, None, "-", "-", 0, None, False, False,
                               error=f"{type(exc).__name__}: {exc}")
        ct = resp.headers.get("Content-Type", "")
        etag = bool(resp.headers.get("ETag"))
        modified = bool(resp.headers.get("Last-Modified"))
        if resp.status_code != 200:
            return ProbeResult(feed.id, feed.url, resp.status_code, ct, "-", 0, None,
                               etag, modified)

        import feedparser

        parsed = feedparser.parse(resp.text)
        entries = parsed.get("entries") or []
        version = str(parsed.get("version") or "")
        if not version and not entries:
            kind = "unparseable"
        elif version.startswith("atom"):
            kind = "atom"
        elif version:
            kind = "rss"
        else:
            kind = "rss" if entries else "unparseable"

        ages = []
        for e in entries:
            ts = _epoch(e.get("published_parsed") or e.get("updated_parsed"))
            if ts is not None:
                ages.append((now - ts) / 3600.0)
        return ProbeResult(feed.id, feed.url, resp.status_code, ct, kind, len(entries),
                           min(ages) if ages else None, etag, modified)


def parse_feed(feed_id: str, text: str) -> list[FeedItem]:
    """RSS 2.0 or Atom into FeedItems. Malformed input yields what it can, never raises.

    feedparser is deliberately lenient -- it recovers entries from feeds with broken dates
    and unescaped entities, which real sports feeds serve regularly. `bozo` is therefore
    logged and ignored rather than treated as failure.
    """
    import feedparser

    parsed = feedparser.parse(text)
    if parsed.get("bozo") and not parsed.get("entries"):
        log.warning("feed %s did not parse: %s", feed_id, parsed.get("bozo_exception"))
        return []
    if parsed.get("bozo"):
        log.debug("feed %s parsed with warnings: %s", feed_id, parsed.get("bozo_exception"))

    items: list[FeedItem] = []
    for entry in parsed.get("entries") or []:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        body = ""
        for key in ("summary", "description"):
            value = entry.get(key)
            if value:
                body = str(value).strip()
                break
        if not body:
            content = entry.get("content") or []
            if content:
                body = str(content[0].get("value") or "").strip()
        if not title and not body:
            continue
        items.append(FeedItem(
            feed_id=feed_id,
            guid=_stable_guid(feed_id, link, title, entry.get("id") or entry.get("guid")),
            title=title,
            body=_strip_html(body),
            link=link,
            published_at=_epoch(entry.get("published_parsed") or entry.get("updated_parsed")),
            raw=str(entry.get("summary") or entry.get("title") or ""),
        ))
    return items


_TAG_OPEN = "<"
_TAG_CLOSE = ">"


def _strip_html(text: str) -> str:
    """Crude tag strip -- enough to match names in, and `raw` keeps the original.

    Deliberately not an HTML parser: this text is only ever read by the entity matcher and
    by a human over MCP, and both cope with stray markup better than they cope with a new
    dependency.
    """
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == _TAG_OPEN:
            depth += 1
        elif ch == _TAG_CLOSE:
            if depth:
                depth -= 1
        elif depth == 0:
            out.append(ch)
    import html

    return html.unescape("".join(out)).strip()


@dataclass(slots=True)
class ProbeReport:
    results: list[ProbeResult] = field(default_factory=list)

    @property
    def healthy(self) -> list[ProbeResult]:
        return [r for r in self.results if r.healthy]

    def gate_g3(self) -> bool:
        """G3: at least two feeds serving valid XML with an item younger than 24h."""
        return len(self.healthy) >= 2


def probe_all(feeds: list[Feed] | None = None) -> ProbeReport:
    feeds = feeds if feeds is not None else load_feeds(include_disabled=True)
    report = ProbeReport()
    with FeedAdapter() as adapter:
        for feed in feeds:
            report.results.append(adapter.probe(feed))
    return report
