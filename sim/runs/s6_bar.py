"""S6 -- where does the incumbent bar the handoff quotes actually come from?

The handoff gives 20.33 green_hope / 25.32 danger_zone / 30.94 boyfun as "ESPN's projections
through the current transform, out-of-sample", and requires that bar beside every result. None
of the three reproduces under this session's metric, so this finds the combination that does
produce them.

It matters because comparing a rebuild scored one way against an incumbent scored another is a
UNITS ERROR -- the class of defect S2's G1 caught when a VORP-ordered board was scored against
raw realised points and the PERFECT board came out at 13.99 instead of 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank  # noqa: E402

QUOTED = {"espn_green_hope": 20.33, "espn_danger_zone": 25.32, "sleeper_boyfun": 30.94}


def main() -> int:
    for lk, q in QUOTED.items():
        print(f"\n{lk}  quoted {q}")
        for idx in rank.INDEXINGS:
            per = {}
            for s in rank.SEASONS_BY_ARM["espn"]:
                loaded = arms.load("espn", s, lk)
                rv = rank.realised_vorp(rank.realised_per_game(s, lk))
                order = [p for p in rank.vorp_order(loaded.points, loaded.position, lk)
                         if p in rv]
                per[s] = rank.score_board(
                    order, rv, teams=int(rank.league(lk).num_teams),
                    pool_size=rank.pool_size_for(lk), indexing=idx).rwre
            allm = sum(per.values()) / len(per)
            test = [per[s] for s in (2024, 2025) if s in per]
            fit = [per[s] for s in (2019, 2020, 2021, 2022) if s in per]
            hit = " <== MATCHES THE QUOTED BAR" if abs(
                sum(test) / len(test) - q) < 0.02 else ""
            print(f"  {idx:10s} all6 {allm:6.2f}   fit(19-22) {sum(fit) / len(fit):6.2f}   "
                  f"test(24,25) {sum(test) / len(test):6.2f}{hit}")
    print("\n  The quoted bar is `board` indexing on 2024+2025. This session uses `symmetric`,")
    print("  pre-registered in audible#85 and unchanged since, because `board` was measured as")
    print("  4.4x ASYMMETRIC -- burying the best player costs 1.29, promoting the worst costs")
    print("  5.66. The correct bar under the pre-registered indexing, all six seasons, is")
    print("  green_hope 22.43 / danger_zone 28.10 / boyfun 32.63.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
