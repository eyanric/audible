"""SQLite store: dedupe, windowing, filters, and the health block. Temp DB only."""

from __future__ import annotations

import json
import time

import pytest

from audible.news.store import DB_NAME, ENV_NEWS_DIR, NewsStore, news_dir


@pytest.fixture()
def store(tmp_path):
    return NewsStore(tmp_path / "news.sqlite3")


def _row(guid: str, **over):
    row = {
        "guid": guid, "feed_id": "f1", "title": "A title", "body": "A body",
        "link": "https://example.test/x", "published_at": time.time(),
        "player_id": None, "match_confidence": None,
        "event_type": "noise", "severity": 0, "raw": "<p>A body</p>",
    }
    row.update(over)
    return row


# --- dedupe -----------------------------------------------------------------------


def test_guid_dedupe_across_polls(store):
    """Rotowire re-serves its whole window every poll; that must cost nothing."""
    batch = [_row("f1:1"), _row("f1:2"), _row("f1:3")]
    inserted, skipped = store.upsert(batch)
    assert (inserted, skipped) == (3, 0)

    inserted, skipped = store.upsert(batch)
    assert (inserted, skipped) == (0, 3), "a re-poll must insert nothing"
    assert store.stats()["total"] == 3


def test_partial_overlap_inserts_only_the_new(store):
    store.upsert([_row("f1:1"), _row("f1:2")])
    inserted, skipped = store.upsert([_row("f1:2"), _row("f1:3")])
    assert (inserted, skipped) == (1, 1)
    assert store.stats()["total"] == 3


def test_first_write_wins_so_history_is_not_rewritten(store):
    store.upsert([_row("f1:1", title="Original headline")])
    store.upsert([_row("f1:1", title="Silently edited headline")])
    items = store.recent(hours=24)
    assert len(items) == 1
    assert items[0].title == "Original headline"


def test_empty_batch_is_harmless(store):
    assert store.upsert([]) == (0, 0)


# --- reading ----------------------------------------------------------------------

def test_recent_respects_the_window(store):
    now = time.time()
    store.upsert([
        _row("f1:new", published_at=now - 3600),
        _row("f1:old", published_at=now - 80 * 3600),
    ])
    guids = {i.guid for i in store.recent(hours=48, now=now)}
    assert guids == {"f1:new"}
    assert len(store.recent(hours=200, now=now)) == 2


def test_item_with_no_published_date_falls_back_to_fetched_at(store):
    """A feed with junk dates must still be visible, not silently out of every window."""
    store.upsert([_row("f1:undated", published_at=None)])
    assert len(store.recent(hours=1)) == 1


def test_filter_by_player_and_severity(store):
    store.upsert([
        _row("f1:a", player_id="4034", severity=3, event_type="injury_out"),
        _row("f1:b", player_id="4034", severity=0, event_type="noise"),
        _row("f1:c", player_id="9999", severity=3, event_type="injury_out"),
    ])
    assert {i.guid for i in store.recent(player_id="4034")} == {"f1:a", "f1:b"}
    assert {i.guid for i in store.recent(min_severity=3)} == {"f1:a", "f1:c"}
    assert {i.guid for i in store.recent(player_id="4034", min_severity=3)} == {"f1:a"}


def test_recent_is_newest_first(store):
    now = time.time()
    store.upsert([
        _row("f1:mid", published_at=now - 2 * 3600),
        _row("f1:new", published_at=now - 1 * 3600),
        _row("f1:old", published_at=now - 3 * 3600),
    ])
    assert [i.guid for i in store.recent(now=now)] == ["f1:new", "f1:mid", "f1:old"]


def test_limit_is_honoured(store):
    store.upsert([_row(f"f1:{n}") for n in range(50)])
    assert len(store.recent(limit=10)) == 10


# --- stats and health -------------------------------------------------------------

def test_stats_counts_matches_and_histograms(store):
    store.upsert([
        _row("f1:a", player_id="4034", match_confidence="exact_title", event_type="injury_out"),
        _row("f2:b", feed_id="f2", player_id=None, event_type="noise"),
    ])
    s = store.stats()
    assert s["total"] == 2
    assert s["matched"] == 1
    assert s["match_rate"] == 0.5
    assert s["by_feed"] == {"f1": 1, "f2": 1}
    assert s["by_event"]["injury_out"] == 1
    assert s["by_confidence"]["none"] == 1, "unmatched rows report as none, not as missing"
    assert s["db_bytes"] > 0


def test_stats_on_an_empty_store_does_not_divide_by_zero(store):
    s = store.stats()
    assert s["total"] == 0 and s["match_rate"] == 0.0


def test_record_poll_tracks_success_then_keeps_it_through_a_failure(store):
    store.record_poll("f1", ok=True, items=5)
    first = store.health()["feeds"]["f1"]["last_success"]
    assert first is not None

    store.record_poll("f1", ok=False, error="HTTP 500")
    after = store.health()["feeds"]["f1"]
    assert after["last_success"] == first, "a later failure must not erase the last success"
    assert after["last_error"] == "HTTP 500"
    assert after["items_seen"] == 5


def test_health_never_raises_on_a_fresh_store(store):
    h = store.health()
    assert h["items"] == 0 and h["feeds"] == {}


# --- placement --------------------------------------------------------------------

def test_news_dir_follows_the_env_var(monkeypatch, tmp_path):
    """Load-bearing: /app/data is emptyDir in-cluster and news cannot be re-fetched."""
    monkeypatch.setenv(ENV_NEWS_DIR, str(tmp_path / "elsewhere"))
    assert news_dir() == tmp_path / "elsewhere"
    s = NewsStore()
    assert s.path == tmp_path / "elsewhere" / DB_NAME
    assert s.path.parent.is_dir(), "the store must create its own directory"


def test_export_jsonl_round_trips(store, tmp_path):
    store.upsert([_row("f1:a", player_id="4034"), _row("f1:b")])
    out = tmp_path / "news.jsonl"
    assert store.export_jsonl(out) == 2
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert {r["guid"] for r in rows} == {"f1:a", "f1:b"}
    assert rows[0]["raw"], "raw source text is kept on purpose; a human reads it over MCP"
