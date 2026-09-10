"""S5 Task 1 -- draw the floor twenty-four times and report it as a distribution.

Writes `sim/runs/s5-floor.json` so every later adjudication in this session reads the SAME
draws. G10 requires a committed script behind every published number; this is the script behind
the floor, and the json is the number.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import referee  # noqa: E402

OUT = Path(__file__).resolve().parent / "s5-floor.json"


def main() -> int:
    seasons = referee.espn_seasons()
    print(f"seasons {seasons}   salts {len(referee.SALTS)}")

    cached = referee.load_floor(str(OUT)) if OUT.exists() else None
    if cached is not None and len(cached.salts) == len(referee.SALTS):
        floor = cached
        print(f"reusing {OUT.name} -- the draws are frozen, so re-running this script "
              f"cannot silently move a published number")
    else:
        floor = referee.draw_floor(seasons)
        OUT.write_text(json.dumps({
            "salts": list(floor.salts),
            "seasons": list(floor.seasons),
            "per": {k: [{str(s): v for s, v in d.items()} for d in draws]
                    for k, draws in floor.per.items()},
        }, indent=1), encoding="utf-8")
        print(f"wrote {OUT.name}")

    print("\n=== G1. THE FLOOR IS A DISTRIBUTION ===")
    print("  locus   mean      sd     2.5%      97.5%    min      max")
    for locus in referee.LOCI:
        xs = floor.means(locus)
        s = referee.floor_summary(floor, locus)
        print(f"  {locus:5s} {s.mean:+7.3f} {s.sd:7.3f} {s.lo:+8.3f} {s.hi:+8.3f} "
              f"{min(xs):+8.3f} {max(xs):+8.3f}")

    print("\n=== the single draw audible#86 and #87 published, for comparison ===")
    legacy = referee.deltas("noise", seasons, salt=referee.LEGACY_SALT)
    for locus in referee.LOCI:
        if locus not in legacy:
            continue
        v = legacy[locus]
        m = sum(v.values()) / len(v)
        xs = sorted(floor.means(locus))
        # TIES ARE REPORTED, NOT SWALLOWED. Counting `x < m` alone puts a draw tied with nine
        # others at "rank 1", which reads as extreme when it is not: at QB the fit declines the
        # noise knob outright in many draws and they all sit at exactly +0.000.
        below = sum(1 for x in xs if x < m)
        tied = sum(1 for x in xs if x == m)
        outside = "OUTSIDE the range of all draws" if (m < xs[0] or m > xs[-1]) else ""
        print(f"  {locus:5s} legacy {m:+7.3f}   {below} below, {tied} tied, "
              f"{len(xs) - below - tied} above, of {len(xs)}   {outside}")

    print("\n=== G2. RESAMPLING THE SALT WIDENS THE INTERVAL ===")
    print("  The broken mechanism held the salt fixed and resampled only the unit, so the")
    print("  salt's variance could not enter any interval. The term under test here is")
    print("  ANOTHER information-free draw -- a thing that is known to carry nothing, so the")
    print("  honest interval must contain zero and a mechanism that says otherwise is wrong.")
    print("  locus   conditional width   unconditional width   widened by   verdicts")
    for locus in referee.LOCI:
        draws = [d for d in floor.per[locus] if d]
        if len(draws) < 2:
            continue
        # Conditional: judged against ONE other draw, season bootstrap only -- #87's mechanism.
        cond = referee.adjudicate(draws[1], floor, locus, resample_salt=False,
                                  fixed_salt_index=0)
        # Unconditional: the salt is resampled alongside the season.
        uncond = referee.adjudicate(draws[1], floor, locus, resample_salt=True)
        wc = cond.difference.hi - cond.difference.lo
        wu = uncond.difference.hi - uncond.difference.lo
        ratio = wu / wc if wc else float("nan")
        print(f"  {locus:5s} {wc:17.3f} {wu:21.3f} {ratio:10.2f}x   "
              f"one-draw: {cond.disposition} | distribution: {uncond.disposition}")

    print("\n=== G9. WHAT IS THE REFEREE'S OWN FALSE-RESOLUTION RATE? ===")
    print("  Every draw is information-free, so judging draw j against the OTHER draws is a")
    print("  test whose null is TRUE. A rule reported as 5% that never fires is not a")
    print("  conservative 5% test -- it is a 0% test, and it cannot resolve anything.")
    print("  This is the check audible#86 and #87 never ran.")
    print("  locus  resolved/n     rate  beats  worse   ref-set p:   min    5th    50th")
    for locus in referee.LOCI:
        c = referee.calibrate(floor, locus)
        print(f"  {locus:5s} {int(c['resolved']):6d}/{int(c['n']):-3d} {c['rate']:8.1%} "
              f"{int(c['beats']):6d} {int(c['worse']):6d} "
              f"{c['pmin']:16.3f} {c['p05']:6.3f} {c['p50']:6.3f}")
    k = len(floor.salts)
    print(f"\n  smallest two-sided reference-set p attainable with K={k} draws: "
          f"{2 / (k + 1):.4f}")
    print(f"  K=24 bottoms out at {2 / 25:.3f} and CANNOT express a 5% test at any effect")
    print("  size. K=39 is the smallest that reaches 0.050. That is why K=40 is drawn here.")

    print(f"\n=== per-salt board-wide floor, all {len(floor.salts)} draws ===")
    for salt, m in zip(floor.salts, floor.means("board"), strict=True):
        print(f"  {salt}  {m:+.3f}")
    xs = floor.means("board")
    print(f"  mean {statistics.mean(xs):+.3f}  sd {statistics.stdev(xs):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
