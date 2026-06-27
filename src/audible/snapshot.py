"""Consensus snapshot store (Metrics Addendum 01, B2).

You can never backtest rankings you didn't save. This captures dated, source-tagged
parquet of the consensus projections/rankings so that a season from now there's a real
historical baseline for the honesty gate. Append-only: a past date's file is never
overwritten (re-running today is idempotent unless ``force``).

Run weekly on the homelab (cron):  ``audible snapshot``
Requires the nflverse extra (parquet + FantasyPros rankings): ``uv sync --extra nflverse``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# repo_root/snapshots -- snapshot.py is at src/audible/snapshot.py
SNAPSHOTS_DIR: Path = Path(__file__).resolve().parents[2] / "snapshots"


def today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


@runtime_checkable
class SnapshotSource(Protocol):
    name: str

    def rows(self) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class SnapshotResult:
    source: str
    path: Path
    rows: int
    skipped: bool


def _write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
    import polars as pl

    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path)


def capture(
    source: SnapshotSource,
    *,
    date: str | None = None,
    out_dir: Path = SNAPSHOTS_DIR,
    force: bool = False,
) -> SnapshotResult:
    """Capture *source* to ``out_dir/{source}/{date}.parquet`` (append-only)."""
    stamp = date or today_utc()
    path = out_dir / source.name / f"{stamp}.parquet"
    if path.exists() and not force:
        return SnapshotResult(source.name, path, 0, skipped=True)
    rows = source.rows()
    for row in rows:
        row["captured_date"] = stamp
        row["source"] = source.name
    _write_parquet(rows, path)
    return SnapshotResult(source.name, path, len(rows), skipped=False)


def run(
    sources: list[SnapshotSource],
    *,
    date: str | None = None,
    out_dir: Path = SNAPSHOTS_DIR,
    force: bool = False,
) -> list[SnapshotResult]:
    return [capture(s, date=date, out_dir=out_dir, force=force) for s in sources]


class SleeperProjectionsSource:
    """Sleeper (Rotowire) season projections across positions -- league-agnostic raw lines."""

    name = "sleeper_projections"

    def __init__(self, season: int, positions: list[str], adapter: Any = None) -> None:
        self.season = season
        self.positions = positions
        self._adapter = adapter

    def rows(self) -> list[dict[str, Any]]:
        from .adapters.sleeper import SleeperAdapter

        adapter = self._adapter or SleeperAdapter()
        try:
            out: list[dict[str, Any]] = []
            for position in self.positions:
                for r in adapter.get_projections(self.season, position):
                    stats = r.get("stats") or {}
                    out.append(
                        {
                            "season": self.season,
                            "scope": "season",
                            "player_id": str(r.get("player_id")),
                            "position": position,
                            "company": r.get("company"),
                            "pts_std": stats.get("pts_std"),
                            "pts_half_ppr": stats.get("pts_half_ppr"),
                            "pts_ppr": stats.get("pts_ppr"),
                            "stats_json": json.dumps(stats, sort_keys=True),
                        }
                    )
            return out
        finally:
            if self._adapter is None:
                adapter.close()


class FantasyProsRankingsSource:
    """FantasyPros consensus rankings via nflverse (current-only -> must be snapshotted)."""

    name = "fantasypros_rankings"

    def __init__(self, rank_type: str = "draft") -> None:
        self.rank_type = rank_type

    def rows(self) -> list[dict[str, Any]]:
        from .adapters.nflverse import load_rankings

        return load_rankings(self.rank_type)
