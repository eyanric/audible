"""S6 Phase 1 -- the two defects that corrupt everything downstream.

G1  `score_board.per_position` scored each position over its slice of the GLOBAL pool, so a
    term that only moved the cross-position interleave registered a per-position effect.
G2  `search.py` and `signals.py` built different boards, because `_season_inputs` resolved
    position by `.update()` in arm order and the last arm won.

INJECTION 1  perfect board -> 0.000000 exactly; shuffled -> chance.
INJECTION 3  a term that moves an ordering only through float residue -> G5 fails.
INJECTION 4  a position-scope term that cannot move a within-position ordering -> G5 fails.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, search, signals  # noqa: E402

LK = signals.LEAGUE


def g1_position_pools() -> None:
    print("=" * 78)
    print("G1 -- the per-position pool is now derived from the league config alone")
    print("=" * 78)
    for key in ("espn_green_hope", "espn_danger_zone", "sleeper_boyfun"):
        try:
            sizes = rank.position_pool_sizes(key)
            print(f"  {key:20s} pool {rank.pool_size_for(key):3d}  " +
                  "  ".join(f"{p} {n}" for p, n in sorted(sizes.items())))
        except Exception as exc:  # noqa: BLE001
            print(f"  {key:20s} UNAVAILABLE: {type(exc).__name__}: {exc}")


def g1_availability() -> None:
    print("\n" + "=" * 78)
    print("G1 -- `availability` must now read EXACTLY +0.0000 at every position")
    print("=" * 78)
    print("  It is a within-position CONSTANT, so it multiplies each position by one positive")
    print("  scalar and provably cannot reorder anyone inside a position.")
    seasons = signals.seasons_for("availability")
    d = referee.deltas("availability", seasons, scope="board")
    for locus in referee.LOCI:
        if locus in d:
            v = d[locus]
            print(f"    {locus:5s} mean {sum(v.values()) / len(v):+.6f}   " +
                  "  ".join(f"{s}:{x:+.4f}" for s, x in sorted(v.items())))
    ok = all(abs(x) < 1e-12 for loc in ("QB", "RB", "WR", "TE") if loc in d
             for x in d[loc].values())
    print(f"  exactly +0.000000 at every position, every season: {ok}")
    print("  audible#87 read RB +0.159  QB -0.036  WR -0.028  TE +0.0004 under the old rule")

    print("\n  and it cannot depend on N -- the same term at three different pool sizes:")
    base = rank.position_pool_sizes(LK)
    for scale, tag in ((0.5, "half"), (1.0, "config"), (2.0, "double")):
        sizes = {p: max(5, int(n * scale)) for p, n in base.items()}
        vals = []
        for season in seasons:
            loaded = arms.load(signals.SOURCE, season, LK)
            rv = rank.realised_vorp(rank.realised_per_game(season, LK))
            per = []
            for lam in (0.0, 0.10):
                pts = signals.adjust(loaded.points, loaded.position, season, lam,
                                     "availability", scope="board")
                order = [p for p in rank.vorp_order(pts, loaded.position, LK) if p in rv]
                per.append(rank.score_board(
                    order, rv, teams=int(rank.league(LK).num_teams),
                    pool_size=rank.pool_size_for(LK), position=loaded.position,
                    indexing=signals.INDEXING, position_pool=sizes).per_position)
            vals.append(max(abs(per[1][p] - per[0][p]) for p in per[0] if p in per[1]))
        print(f"    {tag:7s} sizes {sizes}  worst per-position delta {max(vals):.2e}")


def g1_leakage() -> None:
    """The NON-tautological test. `availability` alone proves nothing -- see the note below.

    A per-player pseudo-random term applied to RB ONLY. Under `scope=position` the QB, WR and TE
    cells hold no values at all, so those three positions are untouched by construction and MUST
    read exactly zero. RB must move. That is falsifiable, and the old global-slice rule fails it.
    """
    print("\n" + "=" * 78)
    print("G1 -- THE TEST THAT IS NOT CIRCULAR: does an RB-only term leak into QB/WR/TE?")
    print("=" * 78)
    print("  `availability` reading +0.000000 is TRUE BY CONSTRUCTION under the new rule: it")
    print("  scales each position by one positive scalar, so the position's own top-N is the")
    print("  same list in the same order and the metric compares x with x. It is a")
    print("  consistency check, not evidence. This is the evidence.")
    sizes = rank.position_pool_sizes(LK)
    teams, pool = int(rank.league(LK).num_teams), rank.pool_size_for(LK)
    worst_new = worst_old = 0.0
    leaky_old = 0
    for season in referee.espn_seasons():
        loaded = arms.load(signals.SOURCE, season, LK)
        rv = rank.realised_vorp(rank.realised_per_game(season, LK))
        vals = {p: v for p, v in referee.salt_values("s6-rb-only", season).items()
                if loaded.position.get(p) == "RB"}

        scored = []
        for lam in (0.0, 0.20):
            pts = signals.adjust(loaded.points, loaded.position, season, lam, "noise",
                                 scope="position", values=vals)
            order = [p for p in rank.vorp_order(pts, loaded.position, LK) if p in rv]
            new = rank.score_board(order, rv, teams=teams, pool_size=pool,
                                   position=loaded.position, indexing=signals.INDEXING,
                                   position_pool=sizes).per_position
            # The OLD rule, reproduced here so the comparison is like-for-like.
            old = {}
            for pos in rank.SCOREABLE:
                members = [p for p in order[:pool] if loaded.position.get(p) == pos]
                if len(members) < 5:
                    continue
                old[pos] = rank.score_board(members, rv, teams=teams,
                                            pool_size=len(members),
                                            indexing=signals.INDEXING).rwre
            scored.append((new, old))
        dn = {p: scored[1][0][p] - scored[0][0][p] for p in scored[0][0]}
        do = {p: scored[1][1][p] - scored[0][1][p] for p in scored[0][1] if p in scored[1][1]}
        leak_new = max(abs(v) for p, v in dn.items() if p != "RB")
        leak_old = max(abs(v) for p, v in do.items() if p != "RB")
        worst_new, worst_old = max(worst_new, leak_new), max(worst_old, leak_old)
        leaky_old += leak_old > 1e-12
        print(f"  {season}  NEW " + "  ".join(f"{p} {dn[p]:+.6f}" for p in ("QB", "RB", "WR", "TE")
                                              if p in dn))
        print("        OLD " + "  ".join(f"{p} {do[p]:+.6f}" for p in ("QB", "RB", "WR", "TE")
                                          if p in do))
    print(f"\n  worst leak into an UNTOUCHED position -- NEW {worst_new:.2e}, "
          f"OLD {worst_old:.3f}")
    print(f"  seasons where the OLD rule leaked: {leaky_old}/6")
    print(f"  NEW rule leaks nothing anywhere: {worst_new < 1e-12}")


def g2_boards_agree() -> None:
    print("\n" + "=" * 78)
    print("G2 -- `search.py` and `signals.py` must build the SAME board")
    print("=" * 78)
    incumbent = search.Candidate()  # espn alone, default transform
    bad = 0
    for season in referee.espn_seasons():
        inp = search._season_inputs(season, LK)
        loaded = arms.load(signals.SOURCE, season, LK)

        mismatched = [p for p, q in loaded.position.items()
                      if p in inp["position"] and inp["position"][p] != q]
        pts = search.board_points(incumbent, inp)
        s_order = rank.vorp_order(pts, inp["position"], LK)
        g_order = rank.vorp_order(loaded.points, loaded.position, LK)
        same = s_order == g_order
        bad += 0 if same else 1
        print(f"  {season}: position disagreements {len(mismatched):2d}   "
              f"boards identical: {same}")
        if mismatched[:3]:
            for p in mismatched[:3]:
                print(f"      {p}: signals says {loaded.position[p]}, "
                      f"search says {inp['position'][p]}")
    print(f"  ASSERTED: search.py == signals.py in all seasons: {bad == 0}")
    assert bad == 0, "search.py and signals.py still build different boards"


def injection_1() -> None:
    print("\n" + "=" * 78)
    print("INJECTION 1 -- perfect board 0.000000 exactly; shuffled is chance")
    print("=" * 78)
    rng = random.Random(referee.BOOT_SEED)
    sizes = rank.position_pool_sizes(LK)
    for season in referee.espn_seasons():
        realised = rank.realised_per_game(season, LK)
        rv = rank.realised_vorp(realised)
        loaded = arms.load(signals.SOURCE, season, LK)
        teams, pool = int(rank.league(LK).num_teams), rank.pool_size_for(LK)
        perfect = [p for p in rank.realised_order(realised) if p in rv]
        sp = rank.score_board(perfect, rv, teams=teams, pool_size=pool,
                              position=loaded.position, indexing=signals.INDEXING,
                              position_pool=sizes)
        shuffled = list(perfect)
        rng.shuffle(shuffled)
        ss = rank.score_board(shuffled, rv, teams=teams, pool_size=pool,
                              position=loaded.position, indexing=signals.INDEXING,
                              position_pool=sizes)
        pp = "  ".join(f"{k} {v:.6f}" for k, v in sorted(sp.per_position.items()))
        print(f"    {season}  perfect {sp.rwre:.6f}  shuffled {ss.rwre:7.3f}   "
              f"per-position perfect: {pp}")


def injections_3_and_4() -> None:
    print("\n" + "=" * 78)
    print("INJECTION 3 -- float-residue term FAILS G5; INJECTION 4 -- shrink FAILS G5")
    print("=" * 78)
    seasons = referee.espn_seasons()
    for tag, kw in (("availability (audible#87 within-position path)",
                     {"scope": "position"}),
                    ("shrink (uniform VORP scale)",
                     {"scope": "position", "lam": 0.40,
                      "order_fn": referee.shrink_order})):
        name = "shrink" if "shrink" in tag else "availability"
        g = referee.ordering_gate(name, seasons, **kw)
        print(f"\n  {tag}: {'PASSES' if g.passed else 'FAILS'}")
        print(f"    cells applied/skipped {g.applied}/{g.skipped}   "
              f"applies in {len(g.live_seasons)}/{g.total_seasons} seasons")
        nw = sum(1 for v in g.within_moves.values() if v > 0)
        print(f"    within-position orderings moved: {nw}/{g.total_seasons} seasons")
        for r in g.reasons:
            print(f"    REASON: {r}")


def main() -> int:
    g1_position_pools()
    g1_availability()
    g1_leakage()
    g2_boards_agree()
    injection_1()
    injections_3_and_4()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
