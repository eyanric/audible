"""TASK 2 -- replay data inventory. Reports what exists. Builds nothing.

ONE QUESTION: can a season replay use audible's own BOARD, or only its DECISION LOGIC?

That turns entirely on one row -- preseason consensus projections AS THEY STOOD BEFORE
that season's draft. audible ranks on consensus. If only current-vintage projections
exist, a replay can validate ORDERING (given a board, does the tool pick well?) but not
PROJECTIONS (is the board itself any good?). Those are different claims and only one of
them is available.

Run it:

    uv run python -m sim.probe

Read-only. It touches the nflverse disk cache and the repo, and makes no network calls --
every row below is answered from what is already pinned, which is itself the finding for
several of them.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "cache"
SEASONS = (2021, 2022, 2023, 2024, 2025)


def _rows(path: Path) -> int | str:
    """Row count for a cached JSON payload, or a shape note when it is not a list."""
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- an unreadable cache file is a finding
        return f"unreadable ({type(exc).__name__})"
    if isinstance(blob, list):
        return len(blob)
    if isinstance(blob, dict):
        for key in ("players", "items", "data", "entries"):
            inner = blob.get(key)
            if isinstance(inner, list):
                return len(inner)
        return len(blob)
    return "scalar"


def _by_season(pattern: str) -> dict[int, list[Path]]:
    out: dict[int, list[Path]] = defaultdict(list)
    if not CACHE.exists():
        return out
    rx = re.compile(pattern)
    for p in sorted(CACHE.iterdir()):
        m = rx.match(p.name)
        if m:
            out[int(m.group("season"))].append(p)
    return out


def _line(source: str, season: int, available: bool, note: str = "") -> str:
    state = "available" if available else "absent"
    tail = f"  {note}" if note else ""
    return f"{source}: {season}: {state}{tail}"


def report() -> list[str]:
    out: list[str] = []

    # a. weekly actual stats -- what audible has PINNED, not what nflverse could serve.
    stat_lines = _by_season(r"espn_stat_lines_(?P<league>\d+)_(?P<season>\d{4})\.json")
    actuals = _by_season(r"espn_actuals_(?P<league>\d+)_(?P<season>\d{4})\.json")
    for season in SEASONS:
        hits = actuals.get(season, []) + stat_lines.get(season, [])
        note = ", ".join(f"{p.name} rows={_rows(p)}" for p in hits)
        out.append(_line("season_totals_espn", season, bool(hits), note))
    nflverse_dir = CACHE / "nflverse"
    pinned = sorted(p.name for p in nflverse_dir.iterdir()) if nflverse_dir.exists() else []
    out.append(f"nflverse_pinned: all: {len(pinned)} file(s)")
    for name in pinned:
        out.append(f"nflverse_pinned: file: {name}")

    # b. THE DECIDING ROW. Preseason consensus AS OF that season's draft.
    proj = _by_season(r"sleeper_projections_(?P<season>\d{4})(?P<pos>_[A-Z]+)?\.json")
    for season in SEASONS:
        hits = proj.get(season, [])
        out.append(
            _line(
                "preseason_consensus_vintage",
                season,
                False,
                (
                    f"{len(hits)} current-vintage file(s) on disk; the API serves TODAY's "
                    "numbers for a past season, not the numbers that stood before its draft"
                ),
            )
        )

    # c. ADP for a comparable market.
    ffc = _by_season(r"ffc_adp_(?P<market>[a-z_]+?)_(?P<teams>\d+)_(?P<season>\d{4})\.json")
    for season in SEASONS:
        hits = ffc.get(season, [])
        note = ", ".join(f"{p.name} rows={_rows(p)}" for p in hits)
        out.append(_line("adp_ffc", season, bool(hits), note))

    # d. ESPN per-season served ranks.
    ranks = _by_season(r"espn_ranks_(?P<league>\d+)_(?P<season>\d{4})\.json")
    for season in SEASONS:
        hits = ranks.get(season, [])
        note = ", ".join(f"{p.name} rows={_rows(p)}" for p in hits)
        out.append(_line("espn_ranks_6012", season, bool(hits), note))

    # e. completed drafts.
    drafts = _by_season(r"espn_draft_(?P<league>\d+)_(?P<season>\d{4})\.json")
    for season in SEASONS:
        hits = [p for p in drafts.get(season, []) if "_6012_" in p.name]
        note = ", ".join(f"{p.name} rows={_rows(p)}" for p in hits)
        out.append(_line("espn_draft_6012", season, bool(hits), note))
    for season in SEASONS:
        hits = [p for p in drafts.get(season, []) if "_73131979_" in p.name]
        out.append(
            _line(
                "espn_draft_73131979",
                season,
                bool(hits),
                "" if hits else "league drafts 2026-09-08; no completed season exists",
            )
        )

    return out


def main() -> int:
    for line in report():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
