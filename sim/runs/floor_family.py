"""Is the pre-registered hash an extreme DRAW, or does its exact formulation matter?

Three families, all information-free by construction:
  A  salt-suffixed   sha256(f"{pid}:{season}|{i}")[:8]
  B  the EXACT pre-registered string, different 32 bits: sha256(f"{pid}:{season}")[8:16], [16:24]...
     -- the closest possible neighbours to the published draw.
"""
from __future__ import annotations

import hashlib
import statistics
import sys

sys.path.insert(0, r"C:\dev\audible-sim")
from sim import arms, rank, signals  # noqa: E402

GRID = (-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20)
LK, POS = signals.LEAGUE, ("QB", "RB", "WR", "TE")


def maker(fmt, lo):
    def f(name, season):
        loaded = arms.load(signals.SOURCE, season, LK)
        return {
            pid: (int(hashlib.sha256(fmt(pid, season).encode()).hexdigest()[lo:lo + 8], 16)
                  / 0xFFFFFFFF) * 2.0 - 1.0
            for pid in loaded.position
        }
    return f


def detail(season, lam):
    loaded = arms.load(signals.SOURCE, season, LK)
    rv = rank.realised_vorp(rank.realised_per_game(season, LK))
    pts = signals.adjust(loaded.points, loaded.position, season, lam, "noise")
    order = [p for p in rank.vorp_order(pts, loaded.position, LK) if p in rv]
    s = rank.score_board(order, rv, teams=int(rank.league(LK).num_teams),
                         pool_size=rank.pool_size_for(LK), position=loaded.position,
                         indexing=signals.INDEXING,
                         position_pool=rank.position_pool_sizes(LK))
    return s.rwre, s.per_position


def floors(seasons):
    tab = {(s, lam): detail(s, lam) for s in seasons for lam in GRID}

    def fit(key):
        out = []
        for held in seasons:
            others = [s for s in seasons if s != held]
            best, blam = float("inf"), 0.0
            for lam in GRID:
                v = [x for x in (key(tab[(s, lam)]) for s in others) if x is not None]
                if v and sum(v) / len(v) < best:
                    best, blam = sum(v) / len(v), lam
            b, t = key(tab[(held, 0.0)]), key(tab[(held, blam)])
            if b is not None and t is not None:
                out.append(t - b)
        return sum(out) / len(out) if out else float("nan")

    return fit(lambda r: r[0]), {p: fit(lambda r, p=p: r[1].get(p)) for p in POS}


def main() -> int:
    seasons = signals.seasons_for("noise")
    orig = signals.signal_values
    cases = []
    for i in range(6):
        cases.append((f"A suffix |{i}", maker(lambda p, s, i=i: f"{p}:{s}|{i}", 0)))
    for lo in (8, 16, 24, 32):
        cases.append((f"B same string, bits[{lo}:{lo+8}]",
                      maker(lambda p, s: f"{p}:{s}", lo)))

    rows = []
    try:
        for tag, fn in cases:
            signals.signal_values = fn
            b, d = floors(seasons)
            rows.append((tag, b, d))
            print(f"  {tag:28s} board {b:+.3f}   " + "  ".join(f"{p} {d[p]:+.3f}" for p in POS))
    finally:
        signals.signal_values = orig

    print("\n=== family B is the SAME INPUT STRING as the pre-registered hash, different bits ===")
    b_only = [d for tag, _b, d in rows if tag.startswith("B")]
    for p in POS:
        xs = [d[p] for d in b_only]
        print(f"  {p}: " + "  ".join(f"{x:+.3f}" for x in xs) +
              f"   mean {statistics.mean(xs):+.3f}")
    print("\n  pre-registered draw:  QB +0.000  RB +0.113  WR -0.620  TE -1.083")
    allrows = [d for _t, _b, d in rows]
    for p in POS:
        xs = [d[p] for d in allrows]
        print(f"  {p}: all-10 mean {statistics.mean(xs):+.3f}  sd {statistics.stdev(xs):.3f}  "
              f"range {min(xs):+.3f}..{max(xs):+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
