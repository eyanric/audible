"""Tiny on-disk JSON cache with TTL.

The Sleeper players catalog is ~15 MB / 12k players and changes slowly; the API
guidance is to pull it at most once a day. This caches such payloads locally.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# repo_root/data/cache -- cache.py is at src/audible/adapters/cache.py
DEFAULT_CACHE_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "cache"


class JsonCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else DEFAULT_CACHE_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str, max_age_s: float) -> Any | None:
        """Return the cached value if present and younger than *max_age_s*, else None."""
        path = self._path(key)
        if not path.exists():
            return None
        if (time.time() - path.stat().st_mtime) > max_age_s:
            return None
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def set(self, key: str, value: Any) -> None:
        with self._path(key).open("w", encoding="utf-8") as fh:
            json.dump(value, fh)
