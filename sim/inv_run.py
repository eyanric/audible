"""The B6 driver: run drafts with the invariants attached, and exit non-zero on a violation.

    uv run --extra nflverse python -m sim.inv_run
    uv run --extra nflverse python -m sim.inv_run --arms real legacy_recommend --survey

STRICT IS THE DEFAULT AND THE EXIT CODE IS THE PRODUCT. A violation is a defect with a
reproduction, not a statistic, so the run stops at the first one and says which season, seed
and pick produced it. `--survey` collects them all instead, and is labelled everywhere it
appears -- in the ledger summary, in the artifact and on stdout -- because a survey run that
reads like a strict one is a green check over a red tree.

WHAT IT COSTS. Each watched draft pays one `lineup_holes` call per pick, which is 18 weeks of
`place_into_slots` over a growing roster. That is real: a watched sweep is several times slower
than the same sweep unwatched, which is why the invariants are a separate entry point rather
than something bolted onto every `sim run`. `sim/runner.py` is untouched; `sim/seat.py` gains
a `watch` parameter that defaults to None and hands the chooser back unwrapped, so every
B1-B5 number is produced by exactly the code that produced it before.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import room
from .invariants import Ledger

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "sim" / "runs"

# Small by design. These are invariants, not estimates: a violation needs one occurrence.
# Note the unit -- a watched draft sees the SEAT'S sixteen picks, not all 128, because a
# chooser is consulted only when its own seat is on the clock. Widening the sweep buys
# precision on a number this module deliberately does not report. Measured at seeds 0-19
# over five seasons: 100 drafts, 1,570 decisions, 1,870 checks, zero violations.
DEFAULT_SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
DEFAULT_SEEDS: tuple[int, ...] = (0, 1, 2, 3)
# `real` ALONE is the "is main clean" set, and the distinction matters. `adp`,
# `legacy_recommend` and `no_bye` are deliberately degraded controls -- the market baseline
# ignores need and byes by construction, and the other two ARE the restored historical defects
# -- so their violations are the evidence these checks work, not findings against the cockpit.
# Mixing them into the default set would report four expected failures as if main were broken.
DEFAULT_ARMS: tuple[str, ...] = ("real",)
SEAT = 6


def run_drafts(
    ledger: Ledger,
    *,
    seasons: tuple[int, ...] = DEFAULT_SEASONS,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    arms: tuple[str, ...] = DEFAULT_ARMS,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Every arm x season x seed, with the per-pick checker attached to each draft."""
    import tempfile

    from . import seat as seat_mod
    from . import weekly
    from .inv_order import DraftWatch, prices_byes

    league = weekly.league_config()
    fit = room.fit_room(tuple(seasons))
    drafts = 0
    decisions = 0
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(state_dir) if state_dir is not None else Path(tmp)
        for season in seasons:
            board = room.load_board(season)
            week_table = weekly.weekly_points(season)
            for arm in arms:
                for seed in seeds:
                    watch = DraftWatch(
                        ledger=ledger, config=league, byes=week_table.byes,
                        arm=arm, season=season, seed=seed,
                    )
                    seat_mod.run_arm(
                        arm, season, seed,
                        season_board=board, fit=fit, week_table=week_table,
                        config=league, state_dir=target, seat=SEAT, watch=watch,
                    )
                    watch.need_reaches_sort()
                    watch.finish(prices_byes=prices_byes(arm))
                    drafts += 1
                    decisions += watch.picks_seen
    return {"drafts": drafts, "seasons": list(seasons), "seeds": list(seeds),
            "arms": list(arms), "picks_seen": decisions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim.inv_run",
        description="Run simulated drafts with the B6 invariants attached.",
    )
    parser.add_argument("--seasons", type=int, nargs="+", default=list(DEFAULT_SEASONS))
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--arms", nargs="+", default=list(DEFAULT_ARMS))
    parser.add_argument(
        "--survey", action="store_true",
        help="collect every violation instead of stopping at the first. LABELLED as a survey "
             "in the artifact; it is for counting what exists before anything is fixed.",
    )
    parser.add_argument("--out", type=Path, default=RUNS / "b6-invariants.json")
    parser.add_argument(
        "--families", nargs="+", default=["seat", "sync", "order", "exec"],
        help="which invariant families to run",
    )
    args = parser.parse_args(argv)

    ledger = Ledger(strict=not args.survey)
    swept: dict[str, Any] = {}
    try:
        if "seat" in args.families:
            from . import inv_seat

            inv_seat.run(ledger)
        if "sync" in args.families:
            from . import inv_sync

            inv_sync.run(ledger)
        if "exec" in args.families:
            from . import inv_exec

            inv_exec.run(ledger)
        if "order" in args.families:
            swept = run_drafts(
                ledger,
                seasons=tuple(args.seasons), seeds=tuple(args.seeds),
                arms=tuple(args.arms),
            )
    except Exception as exc:  # noqa: BLE001 -- strict mode raises here by design
        from .invariants import InvariantViolation

        if not isinstance(exc, InvariantViolation):
            raise
        print(f"INVARIANT VIOLATION\n  {exc}", file=sys.stderr)
        _write(args.out, ledger, swept)
        return 1

    _write(args.out, ledger, swept)
    print(ledger.report())
    if ledger.violations:
        print(f"\n{len(ledger.violations)} violation(s) collected in SURVEY mode",
              file=sys.stderr)
        return 1
    return 0


def _write(path: Path, ledger: Ledger, swept: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sweep": swept, **ledger.summary()}
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", "utf-8")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
