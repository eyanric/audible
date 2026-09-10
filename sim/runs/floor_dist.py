"""Is the 'positional noise floor' a property of the POSITION, or of the HASH DRAW?

One stated recipe, held fixed for every seed and every position:
  * lambda fitted by leave-one-season-out on the HELD-OUT-EXCLUDED seasons,
    scored on the position's OWN per-position RWRE (what `run_s4.py` implies);
  * the per-position delta is treated - baseline at the fitted lambda;
  * the reported floor is the mean over the six held-out seasons.
"""
from __future__ import annotations

import hashlib
import statistics
import sys

sys.path.insert(0, r"C:\dev\audible-sim")
from sim import arms, rank, signals  # noqa: E402

GRID = (-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20)
LK, POS = signals.LEAGUE, ("QB", "RB", "WR", "TE")


def seeded(salt: str):
    def f(name: str, season: int) -> dict[str, float]:
        loaded = arms.load(signals.SOURCE, season, LK)
        return {
            pid: (int(hashlib.sha256(f"{salt}|{pid}:{season}".encode()).hexdigest()[:8], 16)
                  / 0xFFFFFFFF) * 2.0 - 1.0
            for pid in loaded.position
        }
    return f


def detail(season: int, lam: float):
    loaded = arms.load(signals.SOURCE, season, LK)
    rv = rank.realised_vorp(rank.realised_per_game(season, LK))
    pts = signals.adjust(loaded.points, loaded.position, season, lam, "noise")
    order = [p for p in rank.vorp_order(pts, loaded.position, LK) if p in rv]
    s = rank.score_board(order, rv, teams=int(rank.league(LK).num_teams),
                         pool_size=rank.pool_size_for(LK), position=loaded.position,
                         indexing=signals.INDEXING)
    return s.rwre, s.per_position


def floors(seasons):
    """One seed -> (board_wide_floor, {pos: floor}). 6x7 scored boards, reused for all loci."""
    tab = {(s, lam): detail(s, lam) for s in seasons for lam in GRID}

    def fit(key):
        out = []
        for held in seasons:
            others = [s for s in seasons if s != held]
            best, blam = float("inf"), 0.0
            for lam in GRID:
                v = [key(tab[(s, lam)]) for s in others]
                v = [x for x in v if x is not None]
                if v and sum(v) / len(v) < best:
                    best, blam = sum(v) / len(v), lam
            b, t = key(tab[(held, 0.0)]), key(tab[(held, blam)])
            if b is not None and t is not None:
                out.append(t - b)
        return sum(out) / len(out) if out else float("nan")

    return fit(lambda r: r[0]), {p: fit(lambda r, p=p: r[1].get(p)) for p in POS}


def main() -> int:
    seasons = signals.seasons_for("noise")
    print(f"seasons {seasons}\n")

    print("=== the PRE-REGISTERED seed (the one audible#86 and this session reported) ===")
    bw, pp = floors(seasons)
    print(f"  board-wide {bw:+.3f}   " + "  ".join(f"{p} {pp[p]:+.3f}" for p in POS))
    print("  PUBLISHED  +0.364   QB +0.000  RB +0.412  WR -0.296  TE -0.701\n")

    print("=== TWELVE independent information-free hashes, same recipe ===")
    orig = signals.signal_values
    rows = []
    try:
        for i in range(12):
            signals.signal_values = seeded(f"s{i}")
            b, d = floors(seasons)
            rows.append((b, d))
            print(f"  seed {i:2d}: board {b:+.3f}   " + "  ".join(f"{p} {d[p]:+.3f}" for p in POS))
    finally:
        signals.signal_values = orig

    print("\n=== so which varies more: the POSITION, or the DRAW? ===")
    for p in POS:
        xs = [d[p] for _b, d in rows]
        print(f"  {p}: mean {statistics.mean(xs):+.3f}  sd {statistics.stdev(xs):.3f}  "
              f"range {min(xs):+.3f}..{max(xs):+.3f}  (spread {max(xs)-min(xs):.3f})")
    bs = [b for b, _d in rows]
    print(f"  board-wide: mean {statistics.mean(bs):+.3f}  sd {statistics.stdev(bs):.3f}")

    means = [statistics.mean([d[p] for _b, d in rows]) for p in POS]
    print(f"\n  spread ACROSS POSITIONS of the seed-averaged floor: {max(means)-min(means):.3f}")
    print(f"  worst spread WITHIN one position across seeds:       "
          f"{max(max(d[p] for _b, d in rows) - min(d[p] for _b, d in rows) for p in POS):.3f}")
    print("\n  the published claim was a positional spread of 1.11 RWRE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
