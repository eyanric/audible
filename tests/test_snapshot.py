from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audible.snapshot import SnapshotResult, capture, run

pl = pytest.importorskip("polars")  # parquet writing needs the nflverse extra


class FakeSource:
    name = "fake_source"

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls = 0

    def rows(self) -> list[dict[str, Any]]:
        self.calls += 1
        return [dict(r) for r in self._rows]


def test_capture_writes_dated_parquet(tmp_path: Path) -> None:
    src = FakeSource([{"player_id": "1", "pts": 10.0}, {"player_id": "2", "pts": 5.0}])
    result = capture(src, date="2026-06-27", out_dir=tmp_path)
    expected_path = tmp_path / "fake_source" / "2026-06-27.parquet"
    assert result == SnapshotResult("fake_source", expected_path, 2, False)
    assert result.path.exists()

    df = pl.read_parquet(result.path)
    assert df.height == 2
    # capture stamps every row with the date + source
    assert set(df["captured_date"].to_list()) == {"2026-06-27"}
    assert set(df["source"].to_list()) == {"fake_source"}


def test_capture_is_append_only_unless_forced(tmp_path: Path) -> None:
    src = FakeSource([{"player_id": "1"}])
    first = capture(src, date="2026-06-27", out_dir=tmp_path)
    assert not first.skipped and src.calls == 1

    # same date again -> skipped, source not re-pulled (past data never overwritten)
    second = capture(src, date="2026-06-27", out_dir=tmp_path)
    assert second.skipped and second.rows == 0 and src.calls == 1

    # force overwrites
    third = capture(src, date="2026-06-27", out_dir=tmp_path, force=True)
    assert not third.skipped and src.calls == 2


def test_run_captures_each_source(tmp_path: Path) -> None:
    results = run(
        [FakeSource([{"a": 1}]), FakeSource([{"b": 2}])],
        date="2026-06-27",
        out_dir=tmp_path,
    )
    assert len(results) == 2
    assert all(r.path.exists() for r in results)
