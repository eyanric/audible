"""Gate: sim must not be able to write the cache a live cockpit is serving from.

This is the isolation claim itself, and without these it is untested -- deleting the rebind
and the guard in ``sim/__init__.py`` would change no other gate's result, because every other
gate either monkeypatches ``DEFAULT_CACHE_DIR`` to a tmp_path or reads through an explicit
root. The one thing nothing else checks is that the DEFAULT is safe.

Why the default matters: the object that writes is constructed inside
``adapters/nflverse.py::_cached`` as a bare ``FrameCache()``. sim never holds it, so an
explicit root threaded through sim cannot reach it. Rebinding the module global is the whole
mechanism, and these gates are what say it is still in place.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from audible.adapters import cache as cache_mod

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]


def test_importing_sim_moves_the_default_cache_off_the_live_root() -> None:
    """The rebind. `FrameCache()` with no argument is what nflverse._cached constructs."""
    assert cache_mod.DEFAULT_CACHE_DIR.resolve() == SIM_CACHE.resolve()
    assert cache_mod.DEFAULT_CACHE_DIR.resolve() != LIVE_CACHE.resolve()


def test_the_default_frame_cache_lands_under_the_sim_root() -> None:
    assert cache_mod.FrameCache().root.resolve() == (SIM_CACHE / "nflverse").resolve()


def test_backfill_resolves_its_root_under_sim_not_the_cockpit() -> None:
    """`unpin()` deletes a parquet from this root and rewrites its manifest."""
    from .backfill import _cache_root

    root = _cache_root().resolve()
    assert root == (SIM_CACHE / "nflverse").resolve()
    assert LIVE_CACHE.resolve() not in root.parents
    assert root != (LIVE_CACHE / "nflverse").resolve()


def test_pointing_the_sim_root_at_the_live_cache_refuses_to_import() -> None:
    """Failure injection: the guard, exercised rather than asserted about."""
    proc = subprocess.run(
        [sys.executable, "-c", "import sim"],
        cwd=REPO, capture_output=True, text=True,
        env={**_env(), "AUDIBLE_SIM_CACHE": str(LIVE_CACHE)},
    )
    assert proc.returncode != 0, "sim imported cleanly while pointed at the live cache"
    assert "must never read or write the live cockpit cache" in proc.stderr


def test_a_subdirectory_of_the_live_cache_is_refused_too() -> None:
    """Containment, not equality. data/cache/sim is still inside the tree a cockpit serves."""
    proc = subprocess.run(
        [sys.executable, "-c", "import sim"],
        cwd=REPO, capture_output=True, text=True,
        env={**_env(), "AUDIBLE_SIM_CACHE": str(LIVE_CACHE / "sim")},
    )
    assert proc.returncode != 0, "a root INSIDE the live cache was accepted"
    assert "overlaps the live root" in proc.stderr


def test_running_backfill_as_a_script_is_refused() -> None:
    """`python sim/backfill.py` skips sim/__init__.py, so the rebind never happens and every
    pin and unpin would land in the live root. Measured 2026-09-06: it ran happily."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "sim" / "backfill.py"), "--check"],
        cwd=REPO, capture_output=True, text=True, env=_env(),
    )
    assert proc.returncode != 0, "backfill ran as a script, bypassing the cache-root rebind"
    assert "must run as a MODULE" in (proc.stderr + proc.stdout)


def _env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k != "AUDIBLE_SIM_CACHE"}
