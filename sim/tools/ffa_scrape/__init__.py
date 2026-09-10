"""FFAnalytics projection corpus scraper.

WHY THIS IS A TOOL AND NOT A SCRIPT. A prior attempt drove the app by hand from a chat
session and shipped 36 mislabelled files. Three failures, each of which a tested tool
prevents:

  * No test cycle -- every behaviour was discovered by shipping broken output.
  * No persistence -- state lived in page memory, and a shinyapps.io session reload wiped
    the runner mid-flight with nothing on disk recording what had completed.
  * Filename collisions -- browser downloads let Chrome append `(1)`, `(2)` on re-runs, so
    the FIRST download claimed the clean name. A contaminated early file kept the good name
    and the correct later one was suffixed. Two files ended up holding `weighted` data under
    `average` and `robust` names.

So: files are written from Python with the exact name, every raw file is verified against
the aggregation it was ASKED for before it is kept, and a manifest on disk is the only
record of what completed.

The module split is the point. `naming`, `verify`, `manifest` and `jobs` are pure and
offline -- they are what `sim/test_g_ffa_scrape.py` exercises. `driver` is the only module
that touches a browser, and it holds no policy that a test would want to reach.
"""

from __future__ import annotations

from .jobs import Job, plan, season_jobs, weekly_jobs
from .manifest import ManifestEntry, append_entry, load_manifest
from .naming import AVG_TYPES, KINDS, filename, parse_filename
from .verify import (
    NINE_POSITIONS,
    FileReport,
    inspect_csv,
    min_rows_for,
    verify_payload,
)

__all__ = [
    "AVG_TYPES",
    "KINDS",
    "NINE_POSITIONS",
    "FileReport",
    "Job",
    "ManifestEntry",
    "append_entry",
    "filename",
    "inspect_csv",
    "load_manifest",
    "min_rows_for",
    "parse_filename",
    "plan",
    "season_jobs",
    "verify_payload",
    "weekly_jobs",
]
