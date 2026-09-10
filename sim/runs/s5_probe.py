"""S5 -- two things the adjudication turned up that needed their own check.

A. `availability` is constant within a position, so its per-position RWRE was predicted to be
   exactly +0.000. It is not. Is the within-position ORDER changing, or only the POOL?
B. `ngs_separation` at WR: which seasons carry it?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, signals  # noqa: E402


def probe_availability() -> None:
    print("=" * 78)
    print("A. why does a position-level constant move a per-position score?")
    print("=" * 78)
    print("  prediction was: constant within a position -> constant multiplier -> the")
    print("  within-position ORDER cannot change -> per-position RWRE is inert.")
    for season in signals.seasons_for("availability"):
        loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
        pool_size = rank.pool_size_for(signals.LEAGUE)
        realised = rank.realised_per_game(season, signals.LEAGUE)
        rv = rank.realised_vorp(realised)

        base_order = [p for p in rank.vorp_order(loaded.points, loaded.position,
                                                 signals.LEAGUE) if p in rv]
        adj = signals.adjust(loaded.points, loaded.position, season, 0.10,
                             "availability", scope="board")
        new_order = [p for p in rank.vorp_order(adj, loaded.position, signals.LEAGUE)
                     if p in rv]

        line = [f"  {season}:"]
        for pos in rank.SCOREABLE:
            b_all = [p for p in base_order if loaded.position.get(p) == pos]
            n_all = [p for p in new_order if loaded.position.get(p) == pos]
            order_same = b_all == n_all
            b_pool = [p for p in base_order[:pool_size] if loaded.position.get(p) == pos]
            n_pool = [p for p in new_order[:pool_size] if loaded.position.get(p) == pos]
            line.append(f"{pos} order_same={str(order_same):5s} "
                        f"pool {len(b_pool)}->{len(n_pool)}")
        print("\n".join(line[:1]) + "\n      " + "\n      ".join(line[1:]))


def probe_separation() -> None:
    print("\n" + "=" * 78)
    print("B. ngs_separation at WR -- which seasons carry it?")
    print("=" * 78)
    seasons = signals.seasons_for("ngs_separation")
    floor = referee.load_floor(str(Path(__file__).resolve().parent / "s5-floor.json"))
    d = referee.deltas("ngs_separation", seasons)["WR"]
    print("  per season: " + "  ".join(f"{s}:{v:+.2f}" for s, v in sorted(d.items())))
    full = sum(d.values()) / len(d)
    print(f"  all six seasons: {full:+.3f}")
    ranked = sorted(d.items(), key=lambda kv: kv[1])
    print(f"  the two most favourable seasons are {ranked[0][0]} ({ranked[0][1]:+.2f}) "
          f"and {ranked[1][0]} ({ranked[1][1]:+.2f})")
    for drop in ([ranked[0][0]], [ranked[1][0]], [ranked[0][0], ranked[1][0]]):
        keep = {s: v for s, v in d.items() if s not in drop}
        m = sum(keep.values()) / len(keep)
        v = referee.adjudicate(keep, floor, "WR")
        print(f"  dropping {drop}: signal {m:+.3f}   difference {v.difference} "
              f"-> {v.disposition}")
    share = sum(v for v in d.values() if v < 0)
    print(f"\n  sum of the negative seasons {share:+.2f}; "
          f"{ranked[0][1] + ranked[1][1]:+.2f} of it is those two "
          f"({100 * (ranked[0][1] + ranked[1][1]) / share:.0f}%)")


def main() -> int:
    probe_availability()
    probe_separation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
