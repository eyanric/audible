"""On-disk caches: JSON payloads and polars frames, with a manifest.

Draft night is the only deadline this project has, and every input behind the board is a
third-party URL that can 404, rate-limit, or simply be slow at 8:35pm on the 28th. One of
them already did: nflreadpy's DynastyProcess URL started returning a 404 page mid-afternoon
and took the whole board with it, because nflreadpy caches in memory only and every restart
re-downloads.

So the rule here is: **the network is an update mechanism, not a dependency.** What is on
disk is what the board is built from. Fetching is something you do deliberately, ahead of
time, with `audible refresh-data`.

That is why :class:`FrameCache` has no TTL. A time-to-live expires on its own schedule,
which on draft night means the one restart that matters is the one that decides to go to the
network. Present means used. :class:`JsonCache` keeps its TTL because it predates this and
its callers want freshness -- but it can now serve a stale entry rather than fail, which is
the same principle applied to a cache that already had an age.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("audible.cache")

# repo_root/data/cache -- cache.py is at src/audible/adapters/cache.py
DEFAULT_CACHE_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "cache"

MANIFEST_NAME = "manifest.json"


class JsonCache:
    """TTL cache for JSON payloads (the ~15 MB Sleeper players catalog, projections)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else DEFAULT_CACHE_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def age_s(self, key: str) -> float | None:
        path = self._path(key)
        if not path.exists():
            return None
        return max(0.0, time.time() - path.stat().st_mtime)

    def get(self, key: str, max_age_s: float) -> Any | None:
        """The cached value if present and younger than *max_age_s*, else None."""
        age = self.age_s(key)
        if age is None or age > max_age_s:
            return None
        with self._path(key).open(encoding="utf-8") as fh:
            return json.load(fh)

    def get_stale(self, key: str) -> Any | None:
        """The cached value at ANY age, or None if it was never written.

        The offline path. A catalog from last week beats no board at all, and "no board"
        is what a strict TTL produces the moment the network is unavailable.
        """
        if not self._path(key).exists():
            return None
        with self._path(key).open(encoding="utf-8") as fh:
            return json.load(fh)

    def set(self, key: str, value: Any) -> None:
        tmp = self._path(key).with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh)
        tmp.replace(self._path(key))  # atomic: a crash mid-write must not poison the cache


@dataclass(frozen=True, slots=True)
class CacheEntry:
    key: str
    source: str  # the loader or URL that produced it
    fetched_at: float
    sha256: str
    rows: int

    def age_s(self, now: float | None = None) -> float:
        return max(0.0, (now if now is not None else time.time()) - self.fetched_at)

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key, "source": self.source, "fetched_at": self.fetched_at,
            "sha256": self.sha256, "rows": self.rows,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CacheEntry:
        return cls(
            key=str(data["key"]), source=str(data.get("source") or "?"),
            fetched_at=float(data.get("fetched_at") or 0.0),
            sha256=str(data.get("sha256") or ""), rows=int(data.get("rows") or 0),
        )


class FrameCache:
    """Parquet-on-disk cache for the nflverse / DynastyProcess sources.

    No TTL by design -- see the module docstring. The manifest records where each file came
    from, when, and a checksum, so `/healthz` can say how old the board's inputs are and
    whether they were read from disk or pulled fresh.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root if root is not None else DEFAULT_CACHE_DIR) / "nflverse"
        self.root.mkdir(parents=True, exist_ok=True)

    # --- manifest ----------------------------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    def manifest(self) -> dict[str, CacheEntry]:
        if not self.manifest_path.exists():
            return {}
        try:
            with self.manifest_path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("unreadable cache manifest %s: %s", self.manifest_path, exc)
            return {}
        return {k: CacheEntry.from_json(v) for k, v in raw.items()}

    def _write_manifest(self, entries: dict[str, CacheEntry]) -> None:
        tmp = self.manifest_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({k: e.to_json() for k, e in entries.items()}, fh, indent=1, sort_keys=True)
        tmp.replace(self.manifest_path)

    # --- frames ------------------------------------------------------------------------
    def path(self, key: str) -> Path:
        return self.root / f"{key}.parquet"

    def has(self, key: str) -> bool:
        return self.path(key).exists()

    def get(self, key: str) -> Any | None:
        """The cached frame, at any age, or None if it was never written."""
        path = self.path(key)
        if not path.exists():
            return None
        import polars as pl

        try:
            return pl.read_parquet(path)
        except Exception as exc:  # noqa: BLE001 -- a corrupt file must degrade, not crash
            log.warning("unreadable cached frame %s (%s); will refetch", path, exc)
            return None

    def put(self, key: str, frame: Any, *, source: str) -> None:
        path = self.path(key)
        tmp = path.with_suffix(".tmp")
        frame.write_parquet(tmp)
        tmp.replace(path)

        entries = self.manifest()
        entries[key] = CacheEntry(
            key=key, source=source, fetched_at=time.time(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rows=int(frame.height),
        )
        self._write_manifest(entries)

    # --- reporting ---------------------------------------------------------------------
    def summary(self, now: float | None = None) -> dict[str, Any]:
        """What `/healthz` needs: how many sources are on disk and how old the oldest is."""
        entries = self.manifest()
        if not entries:
            return {"keys": 0, "oldest_age_s": None, "newest_age_s": None, "rows": 0}
        ages = [e.age_s(now) for e in entries.values()]
        return {
            "keys": len(entries),
            "oldest_age_s": round(max(ages), 1),
            "newest_age_s": round(min(ages), 1),
            "rows": sum(e.rows for e in entries.values()),
        }
