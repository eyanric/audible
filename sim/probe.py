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

Since B0 it also answers the rows that decide whether a BOOTSTRAP is possible, because those
are the ones that change: whether weekly actuals are pinned per season (`weekly_actuals`),
whether each season's weeks are complete (`weekly_weeks`), and whether that season's ADP
board reaches those rows (`adp_join`). Those rows are computed from the files, so the probe's
output is the evidence for gates G1-G3 rather than a summary written alongside them.

The cache root is now stated on the first line and checked. It used to be derived silently
from this file's location, which meant a probe run from a git worktree -- where `data/` does
not exist at all -- printed thirty `absent` rows and exited 0. "Nothing is pinned" and "I was
looking in the wrong place" are different findings and must not print the same.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

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


def _pinned_frame(season: int) -> Any | None:
    """A pinned player_stats frame, or None. Never raises, never touches the network."""
    path = CACHE / "nflverse" / f"player_stats_{season}.parquet"
    if not path.exists():
        return None
    try:
        import polars as pl
    except ImportError:
        return None
    try:
        return pl.read_parquet(path)
    except Exception:  # noqa: BLE001 -- an unreadable pin is reported, not raised
        return None


def _weekly_lines() -> list[str]:
    """G1 (coverage) and G2 (week completeness), read off the pinned parquet files."""
    from .backfill import inspect_frame

    out: list[str] = []
    have_polars = True
    try:
        import polars  # noqa: F401
    except ImportError:
        have_polars = False

    for season in SEASONS:
        path = CACHE / "nflverse" / f"player_stats_{season}.parquet"
        if not path.exists():
            out.append(_line("weekly_actuals", season, False))
            continue
        if not have_polars:
            out.append(
                _line("weekly_actuals", season, True, "pinned; polars absent, not inspected")
            )
            continue
        frame = _pinned_frame(season)
        if frame is None:
            out.append(_line("weekly_actuals", season, True, "pinned but UNREADABLE"))
            continue
        rep = inspect_frame(frame, season)
        out.append(
            _line(
                "weekly_actuals", season, True,
                f"player_stats_{season}.parquet rows={rep.rows}",
            )
        )
        state = "complete" if rep.ok else "INCOMPLETE"
        detail = (
            f"reg_weeks={rep.week_span()} reg_games={rep.reg_games} "
            f"teams={rep.teams} reg_rows={rep.reg_rows}"
        )
        out.append(f"weekly_weeks: {season}: {state}  {detail}")
        for problem in rep.problems:
            out.append(f"weekly_weeks: {season}: PROBLEM  {problem}")
    return out


def _adp_join_lines() -> list[str]:
    """G3 -- does each season's ADP board reach those weekly rows?

    Skipped rather than guessed at when the crosswalk is not pinned: resolving it would mean
    a network call, and this report has never made one.
    """
    from .adp_join import join_season

    crosswalk = CACHE / "nflverse" / "ff_playerids.parquet"
    if not crosswalk.exists():
        return [
            "adp_join: all: unavailable  ff_playerids is not pinned; "
            "run `python -m sim.adp_join` to pin it"
        ]
    try:
        import polars as pl
    except ImportError:
        return ["adp_join: all: unavailable  polars absent (uv sync --extra nflverse)"]

    id_map_rows = pl.read_parquet(crosswalk).to_dicts()
    out: list[str] = []
    for season in SEASONS:
        try:
            rep = join_season(season, CACHE, id_map_rows)
        except FileNotFoundError:
            out.append(_line("adp_join", season, False, "no weekly rows pinned to join to"))
            continue
        except Exception as exc:  # noqa: BLE001 -- a failed join is a finding, not a crash
            out.append(_line("adp_join", season, False, f"{type(exc).__name__}: {exc}"))
            continue
        out.append(
            _line(
                "adp_join", season, True,
                f"miss={rep.miss_rate * 100:.1f}% "
                f"({rep.pool - rep.with_rows}/{rep.pool} excl DEF) "
                f"incl_def={rep.miss_rate_incl_def * 100:.1f}% "
                f"({rep.total - rep.with_rows}/{rep.total}) "
                f"unscoreable_dst={rep.unscoreable_def} "
                f"stage1={len(rep.stage1_misses)} stage2={len(rep.stage2_misses)} "
                f"ambiguous={len(rep.ambiguous)}",
            )
        )
    return out


def report() -> list[str]:
    out: list[str] = []

    # Where we looked, and whether it was there. Without this row every finding below is
    # unreadable -- thirty `absent` lines mean one thing from an empty cache and another
    # entirely from a path that does not exist.
    out.append(f"cache_root: all: {CACHE}  {'exists' if CACHE.exists() else 'MISSING'}")
    if not CACHE.exists():
        out.append(
            "cache_root: all: WARNING  every row below reads absent because the cache "
            "root is missing, not because nothing is pinned"
        )

    # a. weekly actual stats -- what audible has PINNED, not what nflverse could serve.
    stat_lines = _by_season(r"espn_stat_lines_(?P<league>\d+)_(?P<season>\d{4})\.json")
    actuals = _by_season(r"espn_actuals_(?P<league>\d+)_(?P<season>\d{4})\.json")
    for season in SEASONS:
        hits = actuals.get(season, []) + stat_lines.get(season, [])
        note = ", ".join(f"{p.name} rows={_rows(p)}" for p in hits)
        out.append(_line("season_totals_espn", season, bool(hits), note))
    nflverse_dir = CACHE / "nflverse"
    # Pinned FRAMES, not directory entries. Counting every file made manifest.json a
    # sixteenth "pinned source" next to the fifteen it describes.
    pinned = (
        sorted(p.name for p in nflverse_dir.glob("*.parquet")) if nflverse_dir.exists() else []
    )
    out.append(f"nflverse_pinned: all: {len(pinned)} frame(s)")
    for name in pinned:
        out.append(f"nflverse_pinned: file: {name}")

    # a2. THE B0 ROWS. Weekly actuals are what a bootstrap resamples, and what weekly
    # optimal lineups are computed from; season totals can do neither.
    out.extend(_weekly_lines())
    out.extend(_adp_join_lines())

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


def main(argv: list[str] | None = None) -> int:
    global CACHE

    parser = argparse.ArgumentParser(
        prog="sim.probe",
        description="Replay data inventory. Reports what exists; builds nothing.",
    )
    parser.add_argument(
        "--cache", type=Path, default=None,
        help="cache root to inspect (default: <repo>/data/cache)",
    )
    args = parser.parse_args(argv)
    if args.cache is not None:
        CACHE = args.cache

    for line in report():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
