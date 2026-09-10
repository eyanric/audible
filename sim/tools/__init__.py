"""Operational tools for `sim/`.

Nothing here is imported by the deterministic core or by a gate's arithmetic. These are
instruments: they fetch, verify and record. Importing this package pulls `sim/__init__.py`
first, which is deliberate -- the cache rebind and its guard apply to a tool exactly as they
apply to a gate.
"""

from __future__ import annotations
