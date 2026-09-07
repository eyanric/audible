"""TASK B0 -- pin the weekly actuals a bootstrap draws from. Fetches. Builds nothing else.

`sim/probe.py` established that the nflverse frame cache pins `player_stats_2025` and no
earlier season. Weekly actuals are the whole mechanism for the planned bootstrap: resampling
a player's WEEKS is what produces synthetic seasons with correct player-level variance, and
it is also the only way to compute points-for under weekly OPTIMAL LINEUPS, because an
optimal lineup is a per-week decision. Season totals -- which is all ESPN gives us before
2025 -- can do neither. Five season totals are five points, and a sweep fitted to five
points overfits whichever season is loudest.

So this pins `player_stats_<season>` for the seasons the sim replays.

**It invents no second pin path.** It calls ``adapters.nflverse.player_stats_frame``, which
is the same ``_cached`` -> ``FrameCache.put`` route that wrote `player_stats_2025`: same key
shape, same parquet, same manifest. Disk-first, so a season already pinned is not refetched
and 2025's existing pin is read, never rewritten, unless ``--force`` is passed.

What it adds on top is a GATE. `_cached` pins whatever the loader returns, and a frame that
is short -- a season truncated at week 14, a partial upstream release -- is pinned just as
happily as a complete one. So every season is inspected after the fetch, and a season this
run PINNED and then failed is unpinned again, which makes "present in the manifest" mean
"complete" rather than merely "downloaded".

Three things this deliberately does NOT do, each of which it did in an earlier draft:

* It does not delete a pin it did not write. Inspection failing on a file that was already
  on disk is a report, never a repair -- run from the main checkout that file is the live
  cockpit's data, and a gate that deletes the thing it is complaining about turns a false
  alarm into an outage.
* It does not report "nothing was pinned" without knowing that. Inspection can raise (a
  null week is enough) and by then `_cached` has already written the parquet AND the
  manifest entry, so the honest answer is "pinned, then withdrawn", and the withdrawal has
  to actually happen.
* It does not let ``--force`` pass quietly when the network is down. `_cached` catches every
  exception and falls back to the copy on disk, marking it ``origin: disk`` -- right for
  draft night, wrong here, because "refreshed" and "could not reach the server" would
  otherwise print the same line.

Run it:

    uv run --extra nflverse python -m sim.backfill            # pin 2021-2025
    uv run --extra nflverse python -m sim.backfill --check    # inspect, fetch nothing
    uv run --extra nflverse python -m sim.backfill --seasons 2021 --force

The cache it writes to is ``<repo>/data/sim-cache/nflverse`` (gitignored), NOT the cockpit's
``data/cache``. Importing the ``sim`` package is what moves it, so this must be run as a
MODULE -- ``python -m sim.backfill``, never ``python sim/backfill.py``, which would skip
``sim/__init__.py`` and write the live root. The ``__main__`` block below refuses the second
form rather than trusting anyone to remember.

Why it matters: ANY loader run against a root rewrites the key it fetches, and a refetch is
never a no-op just because the data "should" be the same. Re-fetching `schedules_2026` in a
worktree produced a file with a different sha256 from the live pin (eight betting-odds
columns had changed upstream). `unpin()` below also DELETES a parquet and rewrites the
manifest, and its `pre_existing` guard only spares keys that were already on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Seasons the sim replays. 2021 is the first 18-week season, which is why the backfill starts
# there rather than earlier: every season here has the same 18-week regular-season shape, so a
# bootstrap can resample across them without a structural correction.
SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)

# A 32-team, 17-game regular season is 272 games, every year since 2021. This is the check
# that catches a truncation the week list alone does not: weeks 1-18 can all be PRESENT while
# a week is missing half its games, and the per-week counts would still look plausible to
# anyone not adding them up.
REG_WEEKS: tuple[int, ...] = tuple(range(1, 19))
REG_GAMES: int = 272
REG_TEAMS: int = 32
TEAM_GAMES: int = 17

# Structure checks alone pass on a frame holding three players per game, or only quarterbacks,
# or every stat zeroed. These bound the CONTENT. Measured across 2021-2025 the real files sit
# at 65.5-68.2 rows per regular-season game and carry zero duplicate (player, game) pairs, so
# the floor is loose enough to be safe and tight enough to catch a decimated file.
MIN_ROWS_PER_GAME: float = 40.0
SEASON_TYPES: frozenset[str] = frozenset({"REG", "POST"})
REQUIRED_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE", "K"})

# Columns the scoring engine and the lineup optimiser need from every row. Deliberately not
# the full 150 -- this is the load-bearing subset, so a schema change upstream fails here
# with a name rather than three steps later with a null.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "player_id", "player_name", "position", "season", "week", "season_type", "game_id", "team",
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
    "passing_2pt_conversions", "carries", "rushing_yards", "rushing_tds",
    "rushing_2pt_conversions", "receptions", "targets", "receiving_yards", "receiving_tds",
    "receiving_2pt_conversions", "fumbles_lost_total", "special_teams_tds",
)

# Games the LEAGUE never played, which the data is right to be missing. Encoded as a named
# subtraction rather than a looser bound, so 2022 is still gated at exactly 271 and a genuine
# truncation of that season fails like any other.
#
# This is not a hypothetical allowance -- the check found it. 2022 came back with 271 games,
# and BUF and CIN each have 16 team-games and no week-17 row at all.
CANCELLED: dict[int, tuple[int, str]] = {
    2022: (
        1,
        "BUF@CIN wk17 abandoned after Damar Hamlin's cardiac arrest; ruled a no-contest "
        "and never replayed, so BUF and CIN played 16",
    ),
}


# THE SEVENTEENTH GAME. The NFL played a 16-game, 17-week regular season through 2020 and a
# 17-game, 18-week one from 2021. The constants above describe the LATER era only, so every
# check built on them rejects a COMPLETE pre-2021 season as truncated: measured, 2019 and 2020
# both fetch cleanly -- 17,362 and 17,602 rows, 32 teams, 256 games, weeks 1-17 -- and both were
# reported as "REG weeks missing 18", "short by 16" and "32 teams not on 17 games".
#
# That is a defect in the GATE and not in the data, and it matters beyond tidiness: the failure
# mode is a session concluding a season is unavailable upstream when it is merely being
# measured against the wrong era. A prior handoff carried exactly that conclusion about
# `player_stats_2020`.
#
# The era is a property of the season and nothing else, so it is read from the season rather
# than passed in.
EXPANSION_SEASON: int = 2021
EARLY_REG_WEEKS: tuple[int, ...] = tuple(range(1, 18))
EARLY_REG_GAMES: int = 256
EARLY_TEAM_GAMES: int = 16


def era(season: int) -> tuple[tuple[int, ...], int, int]:
    """(regular-season weeks, total games, games per team) for *season*'s own era."""
    if season < EXPANSION_SEASON:
        return EARLY_REG_WEEKS, EARLY_REG_GAMES, EARLY_TEAM_GAMES
    return REG_WEEKS, REG_GAMES, TEAM_GAMES


def expected_reg_games(season: int) -> tuple[int, str]:
    """Games the regular season should carry, and why it is not simply 272."""
    missing, reason = CANCELLED.get(season, (0, ""))
    _weeks, games, _per_team = era(season)
    return games - missing, reason


@dataclass(frozen=True, slots=True)
class SeasonReport:
    """What one pinned season looks like. `problems` empty is the whole gate."""

    season: int
    rows: int
    reg_rows: int
    reg_weeks: tuple[int, ...]
    games_per_week: tuple[int, ...]
    reg_games: int
    teams: int
    post_weeks: tuple[int, ...]
    note: str
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems

    def week_span(self) -> str:
        if not self.reg_weeks:
            return "none"
        return f"{self.reg_weeks[0]}-{self.reg_weeks[-1]}"


def _empty(season: int, rows: int, problems: list[str]) -> SeasonReport:
    return SeasonReport(season, rows, 0, (), (), 0, 0, (), "", tuple(problems))


def inspect_frame(frame: Any, season: int) -> SeasonReport:
    """Read completeness off a player_stats frame. Pure -- no I/O, no network."""
    import polars as pl

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    problems: list[str] = []
    if missing_cols:
        problems.append(f"season {season}: missing column(s) {', '.join(missing_cols)}")
        # Without these there is nothing further to measure.
        if {"season_type", "week", "game_id", "team", "position"} & set(missing_cols):
            return _empty(season, int(frame.height), problems)

    if frame.height == 0:
        problems.append(f"season {season}: frame is empty")
        return _empty(season, 0, problems)

    seasons_present = sorted({int(s) for s in frame["season"].unique().to_list()})
    if seasons_present != [season]:
        problems.append(
            f"season {season}: frame carries season(s) {seasons_present}, expected [{season}]"
        )

    types_present = {str(t) for t in frame["season_type"].unique().to_list()}
    unexpected_types = sorted(types_present - SEASON_TYPES)
    if unexpected_types:
        problems.append(
            f"season {season}: unexpected season_type(s) {', '.join(unexpected_types)}"
        )

    reg = frame.filter(pl.col("season_type") == "REG")
    post = frame.filter(pl.col("season_type") == "POST")
    if reg.height == 0:
        problems.append(f"season {season}: no regular-season rows")
        return _empty(season, int(frame.height), problems)

    per_week = (
        reg.group_by("week").agg(pl.col("game_id").n_unique().alias("games")).sort("week")
    )
    reg_weeks = tuple(int(w) for w in per_week["week"].to_list())
    games_per_week = tuple(int(g) for g in per_week["games"].to_list())
    reg_games = sum(games_per_week)
    post_weeks = (
        tuple(sorted({int(w) for w in post["week"].unique().to_list()})) if post.height else ()
    )

    want_weeks, _want_games, want_team_games = era(season)
    absent = [w for w in want_weeks if w not in reg_weeks]
    if absent:
        problems.append(
            f"season {season}: REG weeks missing {', '.join(str(w) for w in absent)}"
        )
    extra = [w for w in reg_weeks if w not in want_weeks]
    if extra:
        problems.append(
            f"season {season}: unexpected REG week(s) {', '.join(str(w) for w in extra)}"
        )

    want_games, note = expected_reg_games(season)
    if reg_games != want_games:
        problems.append(
            f"season {season}: {reg_games} REG games, expected {want_games}"
            f" (short by {want_games - reg_games})"
        )

    # Per-team, because a total can come out right while one team is short and another is
    # double-counted. Teams allowed to be short are exactly the ones in a cancelled game.
    per_team = (
        reg.select(["team", "game_id"]).unique()
        .group_by("team").agg(pl.len().alias("games")).sort("team")
    )
    teams = int(per_team.height)
    if teams != REG_TEAMS:
        problems.append(f"season {season}: {teams} teams, expected {REG_TEAMS}")
    short = [
        (str(t), int(g))
        for t, g in zip(per_team["team"].to_list(), per_team["games"].to_list(), strict=True)
        if g != want_team_games
    ]
    allowed_short = CANCELLED.get(season, (0, ""))[0] * 2
    if len(short) != allowed_short:
        detail = ", ".join(f"{t}={g}" for t, g in short) or "none"
        problems.append(
            f"season {season}: {len(short)} team(s) not on {want_team_games} games "
            f"({detail}), expected {allowed_short}"
        )

    # --- content, not just shape -----------------------------------------------------
    # Every check above passes on a frame holding three rows per game, or only quarterbacks.
    duplicates = reg.height - reg.select(["player_id", "game_id"]).unique().height
    if duplicates:
        problems.append(
            f"season {season}: {duplicates} duplicate (player, game) row(s); "
            "a resampled week would double-count them"
        )

    density = reg.height / reg_games if reg_games else 0.0
    if density < MIN_ROWS_PER_GAME:
        problems.append(
            f"season {season}: {density:.1f} rows per REG game, expected at least "
            f"{MIN_ROWS_PER_GAME:.0f} (real seasons sit at 65-68)"
        )

    positions = {str(p) for p in reg["position"].unique().to_list() if p is not None}
    missing_positions = sorted(REQUIRED_POSITIONS - positions)
    if missing_positions:
        problems.append(
            f"season {season}: no rows at position(s) {', '.join(missing_positions)}"
        )

    return SeasonReport(
        season=season,
        rows=int(frame.height),
        reg_rows=int(reg.height),
        reg_weeks=reg_weeks,
        games_per_week=games_per_week,
        reg_games=reg_games,
        teams=teams,
        post_weeks=post_weeks,
        note=note,
        problems=tuple(problems),
    )


def _cache_root() -> Path:
    from audible.adapters.cache import FrameCache

    return FrameCache().root


def unpin(key: str) -> bool:
    """Remove a pinned frame and its manifest entry. Returns whether anything was removed.

    `FrameCache` has no delete -- nothing in the live path ever needed one, because a pinned
    frame is only ever replaced. The backfill needs one: a season IT pinned that then fails
    inspection must not be left behind, or the next run reads it from disk, skips the fetch,
    and the gate never fires again.
    """
    root = _cache_root()
    path = root / f"{key}.parquet"
    removed = path.exists()
    path.unlink(missing_ok=True)

    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            entries = {}
        if entries.pop(key, None) is not None:
            tmp = manifest_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(manifest_path)
            removed = True
    return removed


class StaleRefresh(RuntimeError):
    """A --force refresh silently served the copy already on disk."""


def pin_season(season: int, *, force: bool = False) -> tuple[SeasonReport, bool]:
    """Pin one season through the existing loader, then gate it.

    Returns (report, withdrawn). *withdrawn* is True when this call pinned a file and then
    removed it again because inspection failed.

    A fetch that fails raises out of here rather than pinning anything: `_cached` only
    reaches `FrameCache.put` on a successful fetch, so a season that does not exist leaves
    no file. A fetch that succeeds but returns something incomplete IS pinned by that path,
    so it is withdrawn here -- but only if this call is what put it there.
    """
    from audible.adapters import nflverse
    from audible.adapters.cache import FrameCache

    key = f"player_stats_{season}"
    pre_existing = FrameCache().has(key)

    if force:
        with nflverse.refreshing():
            frame = nflverse.player_stats_frame([season])
        # _cached swallows a fetch failure whenever a copy is on disk and hands back the old
        # one as origin "disk". Without this, `--force` against a dead host prints the same
        # "pinned and complete" line as a real refresh.
        if nflverse.origins().get(key) != "network":
            raise StaleRefresh(
                f"--force asked to refresh {key} but it was served from disk; "
                "the fetch failed and the existing copy was returned unchanged"
            )
    else:
        frame = nflverse.player_stats_frame([season])

    try:
        report = inspect_frame(frame, season)
    except Exception:
        # Inspection itself can fail on a malformed frame -- and by now _cached has already
        # written the parquet and the manifest entry. Withdraw it before the exception
        # leaves, or the next run reads the bad file from disk and never refetches.
        if not pre_existing:
            unpin(key)
        raise

    if report.ok:
        return report, False

    if pre_existing:
        # Report, never repair. From the main checkout this file is the live cockpit's data.
        return report, False
    return report, unpin(key)


def check_season(season: int) -> SeasonReport | None:
    """Inspect what is already pinned, fetching nothing. None when the season is absent."""
    from audible.adapters.cache import FrameCache

    frame = FrameCache().get(f"player_stats_{season}")
    if frame is None:
        return None
    return inspect_frame(frame, season)


def _print_report(report: SeasonReport, *, withdrawn: bool = False) -> None:
    print(
        f"player_stats_{report.season}: rows={report.rows} "
        f"reg_rows={report.reg_rows} reg_weeks={report.week_span()} "
        f"reg_games={report.reg_games} post_weeks="
        f"{report.post_weeks[0] if report.post_weeks else '-'}"
        f"{'-' + str(report.post_weeks[-1]) if len(report.post_weeks) > 1 else ''}"
    )
    print(
        f"  teams={report.teams} games/week: "
        f"{', '.join(str(g) for g in report.games_per_week)}"
    )
    if report.note:
        print(f"  note: {report.note}")
    for problem in report.problems:
        print(f"  PROBLEM: {problem}")
    if report.problems:
        print(
            "  WITHDRAWN: this run pinned it and removed it again"
            if withdrawn
            else "  LEFT IN PLACE: it was already on disk; this run did not write it"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim.backfill",
        description="Pin nflverse weekly player_stats for the seasons the sim replays.",
    )
    parser.add_argument(
        "--seasons", type=int, nargs="+", default=list(SEASONS),
        help=f"seasons to pin (default: {' '.join(str(s) for s in SEASONS)})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="refetch even when already pinned (rewrites the file)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="inspect what is already pinned and fetch nothing",
    )
    args = parser.parse_args(argv)

    print(f"cache root: {_cache_root()}")
    failures = 0
    for season in args.seasons:
        if args.check:
            report = check_season(season)
            if report is None:
                print(f"player_stats_{season}: ABSENT")
                failures += 1
                continue
            _print_report(report)
        else:
            try:
                report, withdrawn = pin_season(season, force=args.force)
            except StaleRefresh as exc:
                print(f"player_stats_{season}: STALE -- {exc}")
                failures += 1
                continue
            except Exception as exc:  # noqa: BLE001 -- an unavailable season is the finding
                print(f"player_stats_{season}: FETCH FAILED -- {type(exc).__name__}: {exc}")
                print("  nothing was left pinned by this run for this season")
                failures += 1
                continue
            _print_report(report, withdrawn=withdrawn)
        if not report.ok:
            failures += 1

    print()
    if failures:
        print(f"{failures} season(s) incomplete or absent")
        return 1
    print(f"{len(args.seasons)} season(s) pinned and complete")
    return 0


if __name__ == "__main__":
    # `python sim/backfill.py` does NOT import sim/__init__.py, so the cache-root rebind that
    # keeps this away from the live cockpit root never happens and every pin and every unpin
    # lands in data/cache. Measured 2026-09-06: run that way with AUDIBLE_SIM_CACHE pointed at
    # the live root, the guard in __init__ never fired and --check read the live pin. Refusing
    # is the fix; a warning would be read once and ignored.
    if __package__ in (None, ""):
        raise SystemExit(
            "sim.backfill must run as a MODULE, not as a script. Run:\n"
            "    uv run --extra nflverse python -m sim.backfill\n"
            "Running `python sim/backfill.py` skips sim/__init__.py, which is what points the "
            "cache at data/sim-cache -- so it would pin into, and unpin out of, the live "
            "cockpit cache instead."
        )
    sys.exit(main())
