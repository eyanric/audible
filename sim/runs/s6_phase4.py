"""S6 Phase 4 -- is `ngs_separation` a real effect concentrated in two seasons, or two seasons
of noise?

WHAT IS AT STAKE. It is the only calibrated resolution this project has produced: p = 0.049 at
WR in `audible#88`, with a fitted weight of +0.05 in all six folds -- the only term whose weight
never flips sign. It is also 83% carried by 2021 and 2025; drop both and it is -0.038.

FOUR TESTS THAT DISTINGUISH THE TWO STORIES:

  1. the verdict itself, against the K=80 floor drawn under the FIXED per-position metric, and
     across N -- phase 1 established that N can decide a sign for a term that carries
     information, so a conclusion that does not survive the sweep is not a conclusion;
  2. does the per-season effect track anything MEASURABLE about the season, or is 2021/2025
     just where the dice fell;
  3. does separation help the SAME PLAYERS across folds? A real mechanism should. Noise
     should not;
  4. leave-two-seasons-out over every pair, not just the convenient one.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, signals  # noqa: E402

LK = signals.LEAGUE
FLOOR_JSON = Path(__file__).resolve().parent / "s6-floor.json"
LAM = 0.05  # the weight every fold chose in audible#88


def per_player_benefit(season: int, lam: float = LAM) -> dict[str, float]:
    """How much each WR's own rank error improves when separation is applied.

    POSITIVE means the adjustment moved him CLOSER to where he finished. Computed inside the
    position's own pool, so the cross-position interleave cannot contribute.
    """
    loaded = arms.load(signals.SOURCE, season, LK)
    rv = rank.realised_vorp(rank.realised_per_game(season, LK))
    n_wr = rank.position_pool_sizes(LK)["WR"]
    out: dict[str, float] = {}
    err: list[dict[str, float]] = []
    for lm in (0.0, lam):
        pts = signals.adjust(loaded.points, loaded.position, season, lm, "ngs_separation")
        order = [p for p in rank.vorp_order(pts, loaded.position, LK) if p in rv]
        wrs = [p for p in order if loaded.position.get(p) == "WR"][:n_wr]
        board_rank = {p: i + 1 for i, p in enumerate(wrs)}
        real = sorted(wrs, key=lambda q: (-rv.get(q, -1e18), q))
        real_rank = {p: i + 1 for i, p in enumerate(real)}
        err.append({p: abs(board_rank[p] - real_rank[p]) for p in wrs})
    for p in err[0]:
        if p in err[1]:
            out[p] = err[0][p] - err[1][p]
    return out


def main() -> int:
    seasons = signals.seasons_for("ngs_separation")
    floor = referee.load_floor(str(FLOOR_JSON))
    print(f"seasons {seasons}   floor draws {len(floor.salts)}")

    print("\n" + "=" * 78)
    print("1. THE VERDICT, against the K=80 floor drawn under the FIXED metric")
    print("=" * 78)
    d = referee.deltas("ngs_separation", seasons)
    v = referee.adjudicate(d["WR"], floor, "WR")
    p = referee.reference_p(d["WR"], floor, "WR")
    print(f"  signal     {v.signal}")
    print(f"  floor      {v.floor}")
    print(f"  difference {v.difference}   bootstrap: {v.disposition}")
    print(f"  reference-set p {p:.3f} over {len(floor.salts)} draws  "
          f"(floor of the test {2 / (len(floor.salts) + 1):.4f})")
    print(f"  -> {'RESOLVED at a calibrated 5%' if p < 0.05 else 'NOT resolved'}")
    print("  audible#88 read p = 0.049 at K=40 under the BROKEN per-position metric")
    lams = referee.fitted_lambdas("ngs_separation", seasons, "WR")
    print(f"  fitted lambda {dict(sorted(lams.items()))}")
    print("  per season " + "  ".join(f"{s}:{x:+.2f}" for s, x in sorted(d['WR'].items())))

    print("\n  ACROSS N -- phase 1 showed N can decide a sign for a term that carries")
    print("  information, so the verdict has to survive the sweep to be a verdict:")
    base = rank.position_pool_sizes(LK)
    original = rank.position_pool_sizes
    try:
        for scale, tag in ((0.5, "half"), (1.0, "config"), (2.0, "double")):
            sizes = {k: max(5, int(n * scale)) for k, n in base.items()}
            rank.position_pool_sizes = lambda _k, _s=sizes: _s  # noqa: E731
            referee.table.cache_clear()
            dd = referee.deltas("ngs_separation", seasons)
            m = sum(dd["WR"].values()) / len(dd["WR"])
            print(f"    {tag:7s} WR N={sizes['WR']:3d}   signal {m:+.3f}   "
                  f"per season " + "  ".join(f"{x:+.2f}" for _s, x in sorted(dd['WR'].items())))
    finally:
        rank.position_pool_sizes = original
        referee.table.cache_clear()

    print("\n" + "=" * 78)
    print("2. DOES THE PER-SEASON EFFECT TRACK ANYTHING MEASURABLE ABOUT THE SEASON?")
    print("=" * 78)
    d_wr = referee.deltas("ngs_separation", seasons)["WR"]
    rows = []
    for s in seasons:
        loaded = arms.load(signals.SOURCE, s, LK)
        rv = rank.realised_vorp(rank.realised_per_game(s, LK))
        vals = signals.signal_values("ngs_separation", s)
        wrs = [p for p in loaded.points if loaded.position.get(p) == "WR"]
        charted = [p for p in wrs if p in vals]
        xs = [vals[p] for p in charted]
        mu = sum(xs) / len(xs) if xs else float("nan")
        sd = (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5 if len(xs) > 1 else 0.0
        rvs = [rv[p] for p in wrs if p in rv]
        rmu = sum(rvs) / len(rvs) if rvs else float("nan")
        rsd = (sum((x - rmu) ** 2 for x in rvs) / (len(rvs) - 1)) ** 0.5 if len(rvs) > 1 else 0.0
        rows.append((s, d_wr[s], len(wrs), len(charted), sd, rsd))
        print(f"  {s}  delta {d_wr[s]:+6.2f}   WRs {len(wrs):3d}  charted {len(charted):3d} "
              f"({len(charted) / len(wrs):4.0%})   separation sd {sd:.3f}   "
              f"realised WR VORP sd {rsd:6.2f}")

    def corr(a: list[float], b: list[float]) -> float:
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
        da = sum((x - ma) ** 2 for x in a) ** 0.5
        db = sum((y - mb) ** 2 for y in b) ** 0.5
        return num / (da * db) if da and db else float("nan")

    deltas_l = [r[1] for r in rows]
    print("\n  correlation of the per-season delta with, over six seasons:")
    for j, label in ((2, "WR pool size"), (3, "charted count"), (4, "separation sd"),
                     (5, "realised WR VORP sd")):
        print(f"    {label:24s} r = {corr(deltas_l, [float(r[j]) for r in rows]):+.3f}")
    print("  SIX POINTS. Any |r| below about 0.81 is not distinguishable from zero here, and")
    print("  four correlations were examined, so this is descriptive rather than a test.")

    print("\n" + "=" * 78)
    print("3. DOES SEPARATION HELP THE SAME PLAYERS ACROSS SEASONS?")
    print("=" * 78)
    print("  A real mechanism should move the same receivers the same way. Noise should not.")
    ben = {s: per_player_benefit(s) for s in seasons}
    pairs = []
    for i, a in enumerate(seasons):
        for b in seasons[i + 1:]:
            both = [p for p in ben[a] if p in ben[b]]
            if len(both) < 15:
                continue
            r = corr([ben[a][p] for p in both], [ben[b][p] for p in both])
            pairs.append(r)
            print(f"    {a} vs {b}: n={len(both):3d}  r = {r:+.3f}")
    if pairs:
        print(f"\n  mean pairwise r {sum(pairs) / len(pairs):+.3f} over {len(pairs)} pairs; "
              f"positive in {sum(1 for r in pairs if r > 0)}/{len(pairs)}")

    print("\n" + "=" * 78)
    print("4. LEAVE-TWO-SEASONS-OUT, over EVERY pair rather than the convenient one")
    print("=" * 78)
    full = sum(d_wr.values()) / len(d_wr)
    print(f"  all six seasons: {full:+.3f}")
    out = []
    for i, a in enumerate(seasons):
        for b in seasons[i + 1:]:
            keep = {s: x for s, x in d_wr.items() if s not in (a, b)}
            m = sum(keep.values()) / len(keep)
            pp = referee.reference_p(keep, floor, "WR")
            out.append((m, a, b, pp))
    for m, a, b, pp in sorted(out):
        flag = "  <== the pair audible#88 dropped" if {a, b} == {2021, 2025} else ""
        print(f"    without {a} and {b}: {m:+.3f}   reference-set p {pp:.3f}{flag}")
    worst = max(out)
    print(f"\n  WORST pair: without {worst[1]} and {worst[2]} the effect is {worst[0]:+.3f}")
    print(f"  {sum(1 for m, _a, _b, _p in out if m < 0)}/{len(out)} pairs leave it negative")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
