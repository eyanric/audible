"""Defect reproduction gates for audible.

These are NOT part of the fast suite. They are built against the BROKEN code and are
expected to go RED: a harness that cannot detect four defects already known cannot detect
one that is not. Red is the deliverable.

Run them explicitly:

    uv run pytest sim -m slow

They are excluded from `uv run pytest` two ways -- `testpaths = ["tests"]` does not reach
this directory, and `-m "not slow"` deselects them if it ever does.
"""
