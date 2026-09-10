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
    seasons = signals.seasons_for("availability")
    d = referee.deltas("availability", seasons, scope="board")
    print("  the numbers under investigation, from the same LOSO as every other term:")
    for locus in referee.LOCI:
        if locus in d:
            v = d[locus]
            print(f"    {locus:5s} mean {sum(v.values()) / len(v):+.6f}   " +
                  "  ".join(f"{s}:{x:+.4f}" for s, x in sorted(v.items())))
    ok = all(abs(x) < 1e-12 for loc in ("QB", "RB", "WR", "TE") if loc in d
             for x in d[loc].values())
    print(f"  prediction was every per-position figure is EXACTLY +0.000000 -- holds: {ok}")
    print()
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


def probe_local_pool() -> None:
    """G15. Score each position over a POSITION-LOCAL pool instead of a slice of the global one.

    Within-position order is provably unchanged under a position-level constant, so a
    position-local top-N is unchanged for ANY N and the prediction must hold exactly. If it
    does, the non-zero per-position figures are entirely an artefact of `score_board` slicing
    the GLOBAL top-128, and the defect is in the metric rather than in the prediction.
    """
    print("\n  COUNTERFACTUAL: per-position scored over a POSITION-LOCAL top-32.")
    teams = int(rank.league(signals.LEAGUE).num_teams)
    for season in signals.seasons_for("availability"):
        loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
        rv = rank.realised_vorp(rank.realised_per_game(season, signals.LEAGUE))
        per_lam = []
        for lam in (0.0, 0.10):
            pts = signals.adjust(loaded.points, loaded.position, season, lam,
                                 "availability", scope="board")
            order = [p for p in rank.vorp_order(pts, loaded.position, signals.LEAGUE)
                     if p in rv]
            per = {}
            for pos in rank.SCOREABLE:
                members = [p for p in order if loaded.position.get(p) == pos][:32]
                if len(members) >= 5:
                    per[pos] = rank.score_board(members, rv, teams=teams,
                                                pool_size=len(members),
                                                indexing=signals.INDEXING).rwre
            per_lam.append(per)
        d = {k: per_lam[1][k] - per_lam[0][k] for k in per_lam[0] if k in per_lam[1]}
        print(f"    {season}: " + "  ".join(f"{k} {v:+.4f}" for k, v in d.items()))
    print("  Every figure exactly +0.0000 means the PREDICTION was right and the metric is")
    print("  wrong: `score_board.per_position` slices the GLOBAL top-128, so the interleave")
    print("  moves which players each position contributes and the score moves with it.")


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
    probe_local_pool()
    probe_separation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
