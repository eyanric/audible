"""Poll orchestration. Offline: MockTransport plus a temp store."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from audible.adapters.feeds import Feed, FeedAdapter
from audible.news.entities import PlayerIndex
from audible.news.poll import ENV_POLL_ENABLED, NewsPoller, poll_enabled, poll_feed, poll_once
from audible.news.store import NewsStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "news"
CATALOG = {
    "1": {"full_name": "Puka Nacua", "position": "WR", "team": "LAR"},
    "2": {"full_name": "Josh Jacobs", "position": "RB", "team": "GB"},
}


def _feed(fid="f1"):
    return Feed(id=fid, url="https://example.test/rss", name=fid,
                enabled=True, poll_interval_s=900, kind="player_news")


def _ok(body):
    return httpx.MockTransport(lambda request: httpx.Response(200, text=body))


RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><guid>g1</guid><title>Puka Nacua ruled out for Sunday</title>
<link>https://example.test/1</link><description>The Rams WR will not play.</description></item>
<item><guid>g2</guid><title>Josh Jacobs placed on the exempt list</title>
<link>https://example.test/2</link><description>Packers RB unavailable.</description></item>
<item><guid>g3</guid><title>Vikings win 24-10</title>
<link>https://example.test/3</link><description>A recap of Sunday.</description></item>
</channel></rss>"""


@pytest.fixture()
def store(tmp_path):
    return NewsStore(tmp_path / "news.sqlite3")


def test_poll_feed_matches_classifies_and_stores(store):
    index = PlayerIndex(CATALOG)
    with FeedAdapter(transport=_ok(RSS)) as adapter:
        result = poll_feed(_feed(), adapter, index, store)

    assert (result.fetched, result.inserted, result.skipped) == (3, 3, 0)
    assert result.matched == 2, "the recap names nobody in the catalog"
    assert result.error is None

    by_title = {i.title: i for i in store.recent(hours=24)}
    nacua = by_title["Puka Nacua ruled out for Sunday"]
    assert (nacua.player_id, nacua.event_type, nacua.severity) == ("1", "injury_out", 3)
    jacobs = by_title["Josh Jacobs placed on the exempt list"]
    assert (jacobs.player_id, jacobs.event_type, jacobs.severity) == ("2", "suspension", 3)
    recap = by_title["Vikings win 24-10"]
    assert recap.player_id is None and recap.event_type == "noise"


def test_second_poll_inserts_nothing(store):
    index = PlayerIndex(CATALOG)
    with FeedAdapter(transport=_ok(RSS)) as adapter:
        poll_feed(_feed(), adapter, index, store)
        again = poll_feed(_feed(), adapter, index, store)
    assert (again.inserted, again.skipped) == (0, 3)
    assert store.stats()["total"] == 3


def test_poll_without_an_index_still_stores_everything(store):
    """No cached catalog is a degraded mode, not an outage: keep the text, skip the ids."""
    with FeedAdapter(transport=_ok(RSS)) as adapter:
        result = poll_feed(_feed(), adapter, None, store)
    assert result.inserted == 3 and result.matched == 0
    assert all(i.player_id is None for i in store.recent(hours=24))
    assert all(i.event_type for i in store.recent(hours=24)), "still classified"


def test_a_dead_feed_records_the_error_and_does_not_raise(store):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns is having a day")

    with FeedAdapter(transport=httpx.MockTransport(boom)) as adapter:
        result = poll_feed(_feed(), adapter, None, store)

    assert result.fetched == 0 and result.inserted == 0
    assert store.stats()["total"] == 0
    state = store.health()["feeds"]["f1"]
    assert state["last_success"] is None


def test_one_dead_feed_does_not_stop_the_others(store):
    """The board must not care whether a website is up."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "dead" in str(request.url):
            return httpx.Response(500, text="")
        return httpx.Response(200, text=RSS)

    feeds = [
        Feed(id="dead", url="https://dead.test/rss", name="dead", enabled=True,
             poll_interval_s=900, kind="articles"),
        _feed("alive"),
    ]
    with FeedAdapter(transport=httpx.MockTransport(handler)) as adapter:
        results = poll_once(store=store, index=None, feeds=feeds, adapter=adapter)

    by_id = {r.feed_id: r for r in results}
    assert by_id["dead"].inserted == 0
    assert by_id["alive"].inserted == 3, "a dead sibling must not cost the live feed"


# --- the env gate -----------------------------------------------------------------

def test_polling_is_off_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv(ENV_POLL_ENABLED, raising=False)
    assert poll_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_gate_accepts_the_usual_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv(ENV_POLL_ENABLED, value)
    assert poll_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_gate_rejects_everything_else(monkeypatch, value):
    monkeypatch.setenv(ENV_POLL_ENABLED, value)
    assert poll_enabled() is False


def test_poller_does_not_start_a_thread_when_gated_off(monkeypatch, store):
    monkeypatch.setenv(ENV_POLL_ENABLED, "0")
    poller = NewsPoller(store=store)
    poller.start()
    assert poller._thread is None
    poller.stop()


def test_an_unchanged_304_feed_is_a_success_not_a_failure(store):
    """A quiet feed and a dead feed must not look the same in /healthz."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, text=RSS, headers={"ETag": '"v1"'})
        return httpx.Response(304, text="")

    with FeedAdapter(transport=httpx.MockTransport(handler)) as adapter:
        poll_feed(_feed(), adapter, None, store)
        second = poll_feed(_feed(), adapter, None, store)
        assert adapter.last_error("f1") is None

    assert second.error is None and second.inserted == 0
    assert store.health()["feeds"]["f1"]["last_error"] is None


def test_a_feed_that_recovers_clears_its_error(store):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500 if calls["n"] == 1 else 200, text="" if calls["n"] == 1 else RSS)

    with FeedAdapter(transport=httpx.MockTransport(handler)) as adapter:
        assert poll_feed(_feed(), adapter, None, store).error == "HTTP 500"
        assert poll_feed(_feed(), adapter, None, store).error is None
        assert adapter.last_error("f1") is None
