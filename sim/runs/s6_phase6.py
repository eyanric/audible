"""S6 Phase 6 -- the rebuilt transform against the incumbent, per league and per position.

The bar is ESPN's projections through `points -> subtract replacement -> sort by VORP`, scored
under the PRE-REGISTERED `symmetric` indexing rather than the superseded `board` indexing the
handoff quoted. See `s6_bar.py`: the quoted 20.33 / 25.32 / 30.94 are `board` on 2024+2025, and
comparing across indexings is a units error.

The best shape phase 3 produced is `quantile` -- rank on `points + q*sd_pts`. It is carried to
all three leagues here, and the per-league p is a reference-set p against the season-to-season
spread rather than against a floor of hashes, because the question here is "does this shape beat
that shape", not "does this input beat nothing".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, residual, signals  # noqa: E402

QUANTILES = (-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0)
LEAGUES = ("espn_green_hope", "espn_danger_zone", "sleeper_boyfun")


def score(order: list[str], season: int, lk: str):
    loaded = arms.load(signals.SOURCE, season, lk)
    rv = rank.realised_vorp(rank.realised_per_game(season, lk))
    return rank.score_board(
        [p for p in order if p in rv], rv,
        teams=int(rank.league(lk).num_teams), pool_size=rank.pool_size_for(lk),
        position=loaded.position, indexing=signals.INDEXING,
        position_pool=rank.position_pool_sizes(lk),
    )


def board(season: int, q: float, lk: str) -> list[str]:
    loaded = arms.load(signals.SOURCE, season, lk)
    meta = residual.ffa_meta(season)
    pts = dict(loaded.points)
    if q != 0.0:
        for p, v in pts.items():
            m = meta.get(p)
            if m and m.get("sd_rel") == m.get("sd_rel"):
                pts[p] = v * (1.0 + q * m["sd_rel"])
    return rank.vorp_order(pts, loaded.position, lk)


def main() -> int:
    seasons = list(referee.espn_seasons())
    print(f"seasons {seasons}   indexing {signals.INDEXING} (pre-registered in audible#85)")

    print("\n" + "=" * 78)
    print("G8 -- THE INCUMBENT BAR, and why the quoted one is not usable")
    print("=" * 78)
    print("  quoted by the handoff : green_hope 20.33  danger_zone 25.32  boyfun 30.94")
    print("  those are `board` indexing on 2024+2025 -- see s6-bar.out, they match to the digit")
    print("  the pre-registered `symmetric` bar, all six seasons, is measured below")

    summary = []
    for lk in LEAGUES:
        print(f"\n{'-' * 78}\n{lk}")
        inc_s, q_s = [], []
        inc_pp: dict[str, list[float]] = {}
        q_pp: dict[str, list[float]] = {}
        chosen = []
        for held in seasons:
            others = [s for s in seasons if s != held]
            best = None
            for q in QUANTILES:
                tot = sum(score(board(s, q, lk), s, lk).rwre for s in others)
                if best is None or tot < best[0]:
                    best = (tot, q)
            q = best[1]
            chosen.append(q)
            a = score(board(held, 0.0, lk), held, lk)
            b = score(board(held, q, lk), held, lk)
            inc_s.append(a.rwre)
            q_s.append(b.rwre)
            for k, v in a.per_position.items():
                inc_pp.setdefault(k, []).append(v)
            for k, v in b.per_position.items():
                q_pp.setdefault(k, []).append(v)
            print(f"  {held}  incumbent {a.rwre:7.3f}   quantile {b.rwre:7.3f}   "
                  f"delta {b.rwre - a.rwre:+7.3f}   fitted q {q:+g}")

        mi = sum(inc_s) / len(inc_s)
        mq = sum(q_s) / len(q_s)
        deltas = [x - y for x, y in zip(q_s, inc_s, strict=True)]
        wins = sum(1 for d in deltas if d < 0)
        # Reference-set p over the six seasons: how extreme is the mean delta among the 2^6
        # sign flips of the per-season deltas. An exact sign test, no bootstrap.
        n = len(deltas)
        count = 0
        for mask in range(1 << n):
            flipped = [d if (mask >> i) & 1 else -d for i, d in enumerate(deltas)]
            if sum(flipped) <= sum(deltas):
                count += 1
        p = 2.0 * min(count, (1 << n) - count) / (1 << n)
        print(f"  MEAN  incumbent {mi:7.3f}   quantile {mq:7.3f}   delta {mq - mi:+7.3f}")
        print(f"        seasons improved {wins}/{len(deltas)}   exact sign-flip p {p:.3f}")
        print(f"        fitted q per fold {chosen}")
        print("  per position (G7 -- never board-wide alone):")
        for k in sorted(inc_pp):
            a_ = sum(inc_pp[k]) / len(inc_pp[k])
            b_ = sum(q_pp[k]) / len(q_pp[k])
            flag = "  quantile better" if b_ < a_ else ""
            print(f"    {k}  incumbent {a_:6.2f}   quantile {b_:6.2f}   "
                  f"delta {b_ - a_:+6.2f}{flag}")
        summary.append((lk, mi, mq, p))

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    beats = 0
    for lk, mi, mq, p in summary:
        verdict = "BEATS" if (mq < mi and p < 0.05) else "DOES NOT BEAT"
        beats += verdict == "BEATS"
        print(f"  {lk:20s} incumbent {mi:6.2f} -> rebuilt {mq:6.2f}   "
              f"delta {mq - mi:+6.2f}   p {p:.3f}   {verdict}")
    print(f"\n  BEATS THE INCUMBENT: {'yes' if beats == len(LEAGUES) else 'no'} "
          f"({beats} of {len(LEAGUES)} leagues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
