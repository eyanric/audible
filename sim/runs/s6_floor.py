"""S6 -- redraw the floor under the FIXED per-position metric, at K=80.

WHY REDRAW. `audible#88`'s floor was drawn with `score_board.per_position` slicing the global
pool. Phase 1 fixed that, so every per-position draw in `s5-floor.json` was computed under a
metric that no longer exists. Adjudicating this session's work against it would compare a
signal measured one way to a floor measured another.

WHY EIGHTY AND NOT FORTY. A two-sided reference-set test against K draws cannot report a p
below `2/(K+1)`. K=40 floors at 0.0488 -- just inside 5%, so `audible#88`'s two resolutions sat
exactly at the floor and could say only "more extreme than 40 information-free terms". K=80
floors at 0.0247, which buys a 2.5% test and lets a strong result separate itself from a
marginal one. It costs about thirteen seconds a draw and it is the only lever on power this
harness has left -- six seasons is fixed by the board source.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import referee  # noqa: E402

OUT = Path(__file__).resolve().parent / "s6-floor.json"
SALTS: tuple[str, ...] = tuple(f"s6-floor-{i:03d}" for i in range(80))


def main() -> int:
    seasons = referee.espn_seasons()
    print(f"seasons {seasons}   salts {len(SALTS)}")

    cached = referee.load_floor(str(OUT)) if OUT.exists() else None
    if cached is not None and len(cached.salts) == len(SALTS):
        floor = cached
        print(f"reusing {OUT.name} -- the draws are frozen")
    else:
        floor = referee.draw_floor(seasons, SALTS)
        OUT.write_text(json.dumps({
            "salts": list(floor.salts),
            "seasons": list(floor.seasons),
            "per": {k: [{str(s): v for s, v in d.items()} for d in draws]
                    for k, draws in floor.per.items()},
        }, indent=1), encoding="utf-8")
        print(f"wrote {OUT.name}")

    print("\n=== THE FLOOR, under the FIXED per-position metric ===")
    print("  locus   mean      sd     2.5%      97.5%     min      max")
    for locus in referee.LOCI:
        xs = floor.means(locus)
        s = referee.floor_summary(floor, locus)
        print(f"  {locus:5s} {s.mean:+7.3f} {s.sd:7.3f} {s.lo:+8.3f} {s.hi:+8.3f} "
              f"{min(xs):+8.3f} {max(xs):+8.3f}")

    print("\n=== what the fix did to the floor itself ===")
    old = Path(__file__).resolve().parent / "s5-floor.json"
    if old.exists():
        prev = referee.load_floor(str(old))
        print("  locus   audible#88 (broken metric, K=40)   S6 (fixed, K=80)")
        for locus in referee.LOCI:
            a, b = referee.floor_summary(prev, locus), referee.floor_summary(floor, locus)
            print(f"  {locus:5s} {a.mean:+8.3f} sd {a.sd:5.3f}            "
                  f"{b.mean:+8.3f} sd {b.sd:5.3f}")

    print("\n=== the referee's own false-resolution rate, under the fixed metric ===")
    print("  Every draw is information-free, so judging draw j against the other 79 is a")
    print("  test whose null is TRUE.")
    print("  locus  resolved/n     rate  beats  worse   ref-set p:   min    5th    50th")
    for locus in referee.LOCI:
        c = referee.calibrate(floor, locus)
        print(f"  {locus:5s} {int(c['resolved']):6d}/{int(c['n']):-3d} {c['rate']:8.1%} "
              f"{int(c['beats']):6d} {int(c['worse']):6d} "
              f"{c['pmin']:16.3f} {c['p05']:6.3f} {c['p50']:6.3f}")
    k = len(floor.salts)
    print(f"\n  smallest two-sided reference-set p attainable with K={k}: {2 / (k + 1):.4f}")

    xs = floor.means("board")
    print(f"\n  board-wide mean {statistics.mean(xs):+.3f}  sd {statistics.stdev(xs):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
