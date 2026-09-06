"""Defect reproduction gates for audible.

These are NOT part of the fast suite. They are built against the BROKEN code and are
expected to go RED: a harness that cannot detect four defects already known cannot detect
one that is not. Red is the deliverable.

Run them explicitly:

    uv run python -m pytest sim -m slow

They are excluded from `uv run pytest` two ways -- `testpaths = ["tests"]` does not reach
this directory, and `-m "not slow"` deselects them if it ever does.

SIM WRITES ITS OWN CACHE, NEVER THE COCKPIT'S
---------------------------------------------
Importing this package rebinds `audible.adapters.cache.DEFAULT_CACHE_DIR` to `data/sim-cache`
before any sim module runs. Without it, sim shares the root a live cockpit is serving from:

  * `sim/backfill.py::_cache_root()` returns `FrameCache().root` -- the live root -- and
    `unpin()` deletes a parquet from it and rewrites its `manifest.json`. The `pre_existing`
    guard only spares keys that were ALREADY on disk; a key sim fetches fresh and then
    rejects IS deleted from the live root.
  * Re-fetching is not idempotent. `schedules_2026` was measured re-fetching to a different
    sha256 because upstream columns changed, so a loader run from this checkout rewrites the
    key it fetches.

Rebinding the module global is the only mechanism that reaches the write. The object that
writes is constructed inside `adapters/nflverse.py::_cached` as a bare `FrameCache()` -- sim
never holds it, so a root threaded through sim/ cannot reach it, and an opt-in env var can be
forgotten. Both sim entry shapes (`python -m sim.<mod>` and `pytest sim/`) import this package
first, so the rebind is unskippable. It is also the mechanism the existing gates already use
(`monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", tmp_path)`), which works because
`FrameCache.__init__` resolves the global at call time rather than at import.

WHAT THIS DOES NOT COVER, stated so nobody reads it as broader than it is: `audible
refresh-data` and a cockpit restart rewrite the live root by design. That is the same hazard
outside sim's reach, and it is not solved here.
"""

from __future__ import annotations

import os
from pathlib import Path

from audible.adapters import cache as _cache

REPO = Path(__file__).resolve().parents[1]
LIVE_CACHE = REPO / "data" / "cache"
_override = os.environ.get("AUDIBLE_SIM_CACHE")
SIM_CACHE = Path(_override) if _override else REPO / "data" / "sim-cache"

_sim, _live = SIM_CACHE.resolve(), LIVE_CACHE.resolve()
# Containment, not equality. data/cache/sim would pass an == check and still put every pin
# and every unpin inside the tree a cockpit is serving from.
if _sim == _live or _live in _sim.parents or _sim in _live.parents:
    raise RuntimeError(
        f"sim/ must never read or write the live cockpit cache. AUDIBLE_SIM_CACHE resolves "
        f"to {_sim}, which overlaps the live root {_live}. A cockpit serves from there and "
        f"sim deletes from what it is pointed at. Point it somewhere else entirely."
    )

_cache.DEFAULT_CACHE_DIR = SIM_CACHE
