"""S6 Phase 7 -- the 2026 prediction, committed before any 2026 data exists.

WHY THIS IS THE ONLY CLEAN TEST LEFT. 2024-2025 was read by `audible#84` and `#85`, so every
result in this project is selection-contaminated on those seasons. A prediction written down
now, against a season that has not been played, is the one piece of evidence a future session
can trust without qualification.

The prediction is stated with a DIRECTION and a SIZE, and with what would falsify it. A
prediction that cannot fail is not a prediction.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import rank, referee, signals, transform  # noqa: E402

LK = signals.LEAGUE


def main() -> int:
    seasons = referee.espn_seasons()
    sizes = rank.position_pool_sizes(LK)
    print("S6 PHASE 7 -- PRE-REGISTERED 2026 PREDICTIONS")
    print("  committed before any 2026 board or outcome exists")
    print(f"  fitted seasons {seasons}   league {LK}   indexing {signals.INDEXING}")
    print(f"  per-position pools {sizes}   floor K=80, reference-set p, two-sided")
    print(f"  design columns {len(transform.design(seasons[0]).names)} "
          f"from {len(transform.FEATURES)} inputs")

    print("\n" + "=" * 78)
    print("PREDICTION 1 (PRIMARY) -- the boosted shape's margin will SHRINK toward zero")
    print("=" * 78)
    print("  Measured 2019-2025: boosted 22.114 against the incumbent's 22.425, -0.312.")
    print("  Three of four shapes beat the incumbent by between 0.008 and 0.312 RWRE, which")
    print("  is under a third of a rank slot, and every one of them was selected on the same")
    print("  six seasons it is reported on.")
    print()
    print("  PREDICTED: on 2026, boosted minus incumbent lands in [-0.35, +0.55],")
    print("  and the point estimate is closer to zero than -0.312.")
    print()
    print("  Direction: positive (the rebuild WORSE) is more likely than negative. audible#85's")
    print("  searched winner was 2.5 RWRE worse out of sample; this one has far fewer effective")
    print("  parameters (24.0 against seven knobs) so the regression should be smaller, but the")
    print("  sign of the surprise has gone the same way every time this project has checked.")
    print()
    print("  FALSIFIED BY: a margin beyond -0.35 (a real and durable gain), or beyond +0.55")
    print("  (a collapse larger than the effective-parameter count justifies).")

    print("\n" + "=" * 78)
    print("PREDICTION 2 -- no single input will resolve against the floor on 2026")
    print("=" * 78)
    print("  Measured: 61 loci, 2 resolved, both HARMS, against ~3.1 expected by chance.")
    print()
    print("  PREDICTED: adding 2026 as a seventh season and re-running phase 5 leaves ZERO")
    print("  inputs resolving as improvements at a calibrated 5%.")
    print()
    print("  FALSIFIED BY: any input resolving as an improvement. That would be the first in")
    print("  this project's history and would deserve a session of its own.")

    print("\n" + "=" * 78)
    print("PREDICTION 3 -- ngs_separation at WR stays unresolved")
    print("=" * 78)
    print("  Measured: -0.558, reference-set p 0.074 two-sided, 0.037 one-sided. Reverted here")
    print("  on three lines, and it is the closest call in the session.")
    print()
    print("  PREDICTED: with 2026 added, the two-sided reference-set p at WR stays above 0.05.")
    print()
    print("  FALSIFIED BY: p <= 0.05 on seven seasons. That would say the revert was wrong and")
    print("  that six seasons was simply too few -- the single most useful thing 2026 can say,")
    print("  because it is the only signal that has ever come close twice.")

    print("\n" + "=" * 78)
    print("PREDICTION 4 (STRUCTURAL) -- the interleave/within-position split reproduces")
    print("=" * 78)
    print("  Measured, and reproduced in all three leagues: the quantile shape improves the")
    print("  WITHIN-POSITION orderings and loses at the cross-position interleave, while the")
    print("  boosted shape does the exact opposite -- board-wide -0.312 while being WORSE at")
    print("  QB, RB and WR and better only at TE.")
    print()
    print("  PREDICTED: on 2026 the quantile shape is better than the incumbent at 2 or more")
    print("  of the four positions, and the boosted shape is better board-wide than its own")
    print("  per-position figures imply.")
    print()
    print("  FALSIFIED BY: quantile better at 0 or 1 positions, or boosted's board-wide margin")
    print("  agreeing with its per-position margins in sign.")

    print("\n" + "=" * 78)
    print("WHAT IS NOT PREDICTED, AND WHY")
    print("=" * 78)
    print("  depth_slot has no 2026 value. The pin's newer schema carries a NULL season, so a")
    print("  `season == 2025` filter finds nothing; it is a schema mismatch, not absent data,")
    print("  and it must be fixed before 2026 rather than worked around.")
    print("  availability needs player_stats_2025, which is pinned; it will have a 2026 value.")
    print("  No prediction is made for any individual player. This project ranks boards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
