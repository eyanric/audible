"""ATTACK 3: is `availability` inert by construction, or did the code skip it?"""
import math
import sys

sys.path.insert(0, r"C:\dev\audible-sim")
from sim import arms, rank, signals

for season in signals.seasons_for("availability"):
    loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
    vals = signals.signal_values("availability", season)
    print(f"\n=== {season} ===")
    for pos in rank.SCOREABLE:
        have = [p for p in loaded.points if loaded.position.get(p) == pos and p in vals]
        if len(have) < 10:
            print(f"  {pos}: only {len(have)} -- skipped by the n>=10 guard")
            continue
        xs = [vals[p] for p in have]
        mu = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
        distinct = len(set(xs))
        flag = "SKIPPED (sd<=0)" if sd <= 0 else f"APPLIED z={(xs[0]-mu)/sd:+.6f}"
        print(f"  {pos}: n={len(have):3d} distinct={distinct} value={xs[0]!r}")
        print(f"       mu={mu!r} sd={sd:.3e}  -> {flag}")
    # does adjust actually change anything?
    for lam in (0.05, 0.10, 0.20):
        adj = signals.adjust(loaded.points, loaded.position, season, lam, "availability")
        n = sum(1 for p in loaded.points if adj[p] != loaded.points[p])
        print(f"  lam {lam:+.2f}: {n} of {len(loaded.points)} point values changed")
