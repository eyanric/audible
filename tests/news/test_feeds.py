"""Feed registry, conditional GET, and parsing. No network: httpx.MockTransport only."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from audible.adapters.feeds import (
    Feed,
    FeedAdapter,
    load_feeds,
    parse_feed,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "news"


def _feed(fid: str = "t", url: str = "https://example.test/rss") -> Feed:
    return Feed(id=fid, url=url, name=fid, enabled=True, poll_interval_s=900, kind="player_news")


def _transport(handler):
    return httpx.MockTransport(handler)


# --- registry ---------------------------------------------------------------------

def test_registry_loads_and_hides_disabled():
    enabled = load_feeds()
    every = load_feeds(include_disabled=True)
    assert enabled, "registry must ship at least one enabled feed"
    assert len(every) > len(enabled), "the dead fantasypros feed is kept, disabled"
    assert all(f.enabled for f in enabled)
    assert len({f.id for f in every}) == len(every), "feed ids must be unique"


def test_registry_urls_are_https():
    for f in load_feeds(include_disabled=True):
        assert f.url.startswith("https://"), f"{f.id} is not https"


# --- parsing ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["rotowire_news", "espn_nfl", "reddit_ff_atom"])
def test_real_fixtures_parse(name):
    items = parse_feed(name, (FIXTURES / f"{name}.xml").read_text(encoding="utf-8"))
    assert items, f"{name} produced no items"
    for it in items:
        assert it.guid.startswith(f"{name}:")
        assert it.title.strip()
        assert it.feed_id == name


def test_atom_and_rss_both_yield_timestamps():
    rss = parse_feed(
        "rotowire_news", (FIXTURES / "rotowire_news.xml").read_text(encoding="utf-8"))
    atom = parse_feed(
        "reddit_ff_atom", (FIXTURES / "reddit_ff_atom.xml").read_text(encoding="utf-8"))
    assert any(i.published_at for i in rss), "RSS pubDate did not survive parsing"
    assert any(i.published_at for i in atom), "Atom updated did not survive parsing"


def test_malformed_feed_degrades_instead_of_raising():
    """Unescaped ampersand, junk pubDate, no guid: parse what is there, drop what is not."""
    items = parse_feed("broken", (FIXTURES / "malformed.xml").read_text(encoding="utf-8"))
    assert len(items) == 2
    assert all(i.published_at is None for i in items), "a junk date must not become a number"
    assert all(i.guid.startswith("broken:sha256:") for i in items), "no guid -> hashed fallback"
    assert items[0].guid != items[1].guid


def test_guid_falls_back_to_hash_and_is_stable_across_parses():
    xml = (FIXTURES / "malformed.xml").read_text(encoding="utf-8")
    first = [i.guid for i in parse_feed("broken", xml)]
    second = [i.guid for i in parse_feed("broken", xml)]
    assert first == second, "the fallback guid must be deterministic or dedupe fails"


def test_same_story_from_two_feeds_stays_two_rows():
    xml = (FIXTURES / "malformed.xml").read_text(encoding="utf-8")
    a = parse_feed("feed_a", xml)[0].guid
    b = parse_feed("feed_b", xml)[0].guid
    assert a != b, "guids are feed-scoped on purpose; bodies differ between syndicators"


def test_empty_and_garbage_input_yield_nothing():
    assert parse_feed("t", "") == []
    assert parse_feed("t", "this is not xml at all") == []


# --- conditional GET --------------------------------------------------------------

def test_304_returns_no_items_and_resends_the_etag():
    seen: list[dict[str, str]] = []
    body = (FIXTURES / "rotowire_news.xml").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        if len(seen) == 1:
            return httpx.Response(200, text=body, headers={"ETag": 'W/"abc123"'})
        return httpx.Response(304, text="")

    with FeedAdapter(transport=_transport(handler)) as adapter:
        first = adapter.fetch(_feed())
        second = adapter.fetch(_feed())

    assert first, "first fetch should return items"
    assert second == [], "304 means unchanged, not empty-feed"
    assert "if-none-match" not in seen[0], "nothing to send on the first request"
    assert seen[1]["if-none-match"] == 'W/"abc123"', "the ETag must come back on request two"


def test_last_modified_is_echoed_as_if_modified_since():
    seen: list[dict[str, str]] = []
    stamp = "Sun, 30 Aug 2026 12:00:00 GMT"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        return httpx.Response(200, text="<rss version='2.0'><channel></channel></rss>",
                              headers={"Last-Modified": stamp})

    with FeedAdapter(transport=_transport(handler)) as adapter:
        adapter.fetch(_feed())
        adapter.fetch(_feed())

    assert seen[1]["if-modified-since"] == stamp


def test_429_backs_off_and_skips_the_next_poll_without_a_request():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, text="slow down")

    with FeedAdapter(transport=_transport(handler)) as adapter:
        assert adapter.fetch(_feed()) == []
        deferred = adapter.deferred_until("t")
        assert deferred is not None and deferred > time.time()
        assert adapter.fetch(_feed()) == []
        assert calls["n"] == 1, "a deferred feed must not be contacted again"


def test_garbage_retry_after_still_backs_off():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"Retry-After": "whenever"}, text="")

    with FeedAdapter(transport=_transport(handler)) as adapter:
        adapter.fetch(_feed())
        assert adapter.deferred_until("t") is not None


@pytest.mark.parametrize("status", [404, 410, 500])
def test_dead_feed_returns_empty_and_never_raises(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="gone")

    with FeedAdapter(transport=_transport(handler)) as adapter:
        assert adapter.fetch(_feed()) == []


def test_network_error_is_swallowed():
    """A poll loop must survive DNS dying mid-draft."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with FeedAdapter(transport=_transport(handler)) as adapter:
        assert adapter.fetch(_feed()) == []
