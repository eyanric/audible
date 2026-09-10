"""S6 phase 1 -- did the `.update()` board defect actually exist before the fix?

A fix that fixed nothing is worse than no fix, because it launders a false premise into the
record. `audible#87` spent a session on G9 before establishing that the defect it was sent to
fix was not real. This reproduces the OLD position resolution and counts the disagreements it
produced, so the claim "16 across six seasons" has a script behind it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, signals  # noqa: E402

LK = signals.LEAGUE


def main() -> int:
    total = 0
    for season in (2019, 2020, 2021, 2022, 2024, 2025):
        available = [a for a in ("espn", "ffa", "sleeper")
                     if season in rank.SEASONS_BY_ARM[a]]
        old: dict[str, str] = {}
        for a in available:  # audible#88 and earlier: LAST arm wins
            old.update(arms.load(a, season, LK).position)
        new: dict[str, str] = {}
        for a in available:  # S6: FIRST arm wins
            for pid, pos in arms.load(a, season, LK).position.items():
                new.setdefault(pid, pos)

        espn = arms.load("espn", season, LK).position
        d_old = [p for p, q in espn.items() if p in old and old[p] != q]
        d_new = [p for p, q in espn.items() if p in new and new[p] != q]
        total += len(d_old)
        print(f"  {season}: arms {available}  OLD disagreed with espn on {len(d_old)}, "
              f"NEW on {len(d_new)}")
        for p in d_old[:3]:
            print(f"      {p}: espn {espn[p]} -> old resolution {old[p]}")
    print(f"\n  total pre-fix disagreements across six seasons: {total}")
    print("  the handoff said 1-7 a season; the defect was real")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
