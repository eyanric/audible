"""The on-disk data cache -- the thing that has to hold when the network does not.

The board's inputs are all third-party URLs. One of them (nflreadpy's DynastyProcess path)
started returning a 404 page mid-afternoon on 2026-08-17 and took the whole board with it,
because nflreadpy caches in memory only and every restart re-downloads. Draft night is
2026-08-28. These tests pin the property that fixes that: **disk first, network optional.**
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audible.adapters.cache import FrameCache, JsonCache

pl = pytest.importorskip("polars")


@pytest.fixture
def frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FrameCache:
    """A FrameCache in tmp_path, with the nflverse module pointed at it too."""
    from audible.adapters import nflverse

    cache = FrameCache(tmp_path)
    monkeypatch.setattr(nflverse, "FrameCache", lambda *a, **k: FrameCache(tmp_path))
    monkeypatch.setattr(nflverse, "_ORIGINS", {})
    return cache


def _frame(n: int = 3) -> Any:
    return pl.DataFrame({"gsis_id": [f"00-{i:07d}" for i in range(n)], "x": list(range(n))})


# --- the cache itself ---------------------------------------------------------------------


def test_a_frame_round_trips_with_a_manifest_entry(frames: FrameCache) -> None:
    frames.put("player_stats_2025", _frame(5), source="nflverse/player_stats")

    back = frames.get("player_stats_2025")
    assert back is not None and back.height == 5

    entry = frames.manifest()["player_stats_2025"]
    assert entry.source == "nflverse/player_stats"
    assert entry.rows == 5
    assert len(entry.sha256) == 64, "a checksum is what makes a stale file identifiable"
    assert entry.age_s() < 60


def test_a_missing_key_is_none_not_an_error(frames: FrameCache) -> None:
    assert frames.get("never_written") is None
    assert frames.has("never_written") is False


def test_a_corrupt_frame_degrades_to_a_refetch(frames: FrameCache) -> None:
    """A half-written parquet must mean "fetch it again", never a crashed cockpit."""
    frames.put("rosters_2026", _frame(), source="nflverse/rosters")
    frames.path("rosters_2026").write_bytes(b"not a parquet file")
    assert frames.get("rosters_2026") is None


def test_summary_reports_what_healthz_shows(frames: FrameCache) -> None:
    frames.put("a", _frame(2), source="s1")
    frames.put("b", _frame(4), source="s2")
    summary = frames.summary()
    assert summary["keys"] == 2
    assert summary["rows"] == 6
    assert summary["oldest_age_s"] is not None


# --- disk first, network optional ---------------------------------------------------------


def test_a_cached_source_never_touches_the_network(frames: FrameCache) -> None:
    from audible.adapters import nflverse

    frames.put("ff_playerids", _frame(7), source="dynastyprocess/db_playerids")

    def explode() -> Any:
        raise AssertionError("the network must not be consulted when the cache is warm")

    out = nflverse._cached("ff_playerids", explode, source="dynastyprocess/db_playerids")
    assert out.height == 7
    assert nflverse.origins()["ff_playerids"] == "disk"


def test_a_failed_fetch_falls_back_to_the_cached_copy(frames: FrameCache) -> None:
    """THE draft-night property. The 404 that broke the board must not break it again."""
    from audible.adapters import nflverse

    frames.put("ff_playerids", _frame(9), source="dynastyprocess/db_playerids")

    def four_oh_four() -> Any:
        raise ConnectionError("404 Client Error: Not Found")

    with nflverse.refreshing():  # even when explicitly told to refresh
        out = nflverse._cached("ff_playerids", four_oh_four, source="dp/db_playerids")

    assert out.height == 9, "a cached copy beats no board"
    assert nflverse.origins()["ff_playerids"] == "disk"


def test_a_failed_fetch_with_no_cache_still_raises(frames: FrameCache) -> None:
    """Silence is the one unacceptable outcome: no data and no cache must be loud."""
    from audible.adapters import nflverse

    def four_oh_four() -> Any:
        raise ConnectionError("404 Client Error: Not Found")

    with pytest.raises(ConnectionError):
        nflverse._cached("never_cached", four_oh_four, source="dp/db_playerids")


def test_refreshing_goes_back_to_the_network(frames: FrameCache) -> None:
    from audible.adapters import nflverse

    frames.put("rosters_2026", _frame(1), source="nflverse/rosters")
    calls: list[int] = []

    def fetch() -> Any:
        calls.append(1)
        return _frame(11)

    assert nflverse._cached("rosters_2026", fetch, source="s").height == 1  # disk
    assert calls == []

    with nflverse.refreshing():
        assert nflverse._cached("rosters_2026", fetch, source="s").height == 11
    assert calls == [1]
    assert nflverse.origins()["rosters_2026"] == "network"
    assert frames.get("rosters_2026").height == 11, "the refresh must be written back"


# --- the JSON side (Sleeper) --------------------------------------------------------------


def test_an_expired_entry_is_still_readable(tmp_path: Path) -> None:
    """A TTL is about freshness. Offline, freshness is not the question -- having it is."""
    cache = JsonCache(tmp_path)
    cache.set("sleeper_players_nfl", {"1": {"full_name": "A Player"}})

    assert cache.get("sleeper_players_nfl", max_age_s=0) is None  # expired by TTL
    assert cache.get_stale("sleeper_players_nfl") == {"1": {"full_name": "A Player"}}
    assert cache.get_stale("never_written") is None


def test_projections_serve_from_disk_when_sleeper_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from audible.adapters.sleeper import SleeperAdapter

    adapter = SleeperAdapter(cache=JsonCache(tmp_path))
    adapter.close()
    rows = [{"player_id": "4034", "stats": {"rec": 60.0}}]
    JsonCache(tmp_path).set("sleeper_projections_2026_RB", rows)

    def unreachable(*_a: Any, **_k: Any) -> Any:
        raise ConnectionError("network unplugged")

    monkeypatch.setattr(SleeperAdapter, "_get", unreachable)
    assert adapter.get_projections(2026, "RB") == rows


def test_the_catalog_survives_an_unreachable_sleeper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from audible.adapters.sleeper import PLAYERS_CACHE_KEY, SleeperAdapter

    adapter = SleeperAdapter(cache=JsonCache(tmp_path))
    adapter.close()
    catalog = {"4034": {"full_name": "A Player", "fantasy_positions": ["RB"]}}
    JsonCache(tmp_path).set(PLAYERS_CACHE_KEY, catalog)

    def unreachable(*_a: Any, **_k: Any) -> Any:
        raise ConnectionError("network unplugged")

    monkeypatch.setattr(SleeperAdapter, "_get", unreachable)
    assert adapter.get_players_catalog(force=True) == catalog
