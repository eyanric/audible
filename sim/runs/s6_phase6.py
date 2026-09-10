"""S6 Phase 6 -- the rebuilt transform against the incumbent, per league and per position.

The bar is ESPN's projections through `points -> subtract replacement -> sort by VORP`, scored
under the PRE-REGISTERED `symmetric` indexing rather than the superseded `board` indexing the
handoff quoted. See `s6_bar.py`: the quoted 20.33 / 25.32 / 30.94 are `board` on 2024+2025, and
comparing across indexings is a units error.

THREE shapes are carried to all three leagues: `quantile` (rank on `points + q*sd_pts`) and
`learned` (predict realised VORP from every input and sort by the prediction). Running only the
first was a defect the phase 3-6 review caught -- the learned shape ties the incumbent in
green_hope once its design matrix can express the incumbent, and a verdict of "does not beat in
any league" that never ran the shape that ties is not a verdict.

The per-league p is an EXACT SIGN TEST over the six per-season deltas rather than a bootstrap or
a floor of hashes, because the question here is "does this shape beat that shape".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, residual, signals, transform  # noqa: E402

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


LAMBDAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)


def learned_board(held: int, others: list[int], lk: str) -> list[str]:
    """Predict realised VORP from every input and sort by it, penalty fitted inside the fold."""
    def stack(ss: list[int]):
        xs: list[list[float]] = []
        ys: list[float] = []
        names: list[str] = []
        for s_ in ss:
            d = transform.design(s_, lk)
            names = d.names
            xs.extend(d.x)
            ys.extend(d.y_vorp)
        return xs, ys, names

    best = None
    for lam in LAMBDAS:
        tot = 0.0
        for inner in others:
            tr = [s_ for s_ in others if s_ != inner]
            xi, yi, ni = stack(tr)
            m = transform.fit_ridge(xi, yi, ni, lam)
            d = transform.design(inner, lk)
            pred = {q_: m.predict(r_) for q_, r_ in zip(d.ids, d.x, strict=True)}
            tot += score(sorted(pred, key=lambda z: -pred[z]), inner, lk).rwre
        if best is None or tot < best[0]:
            best = (tot, lam)
    xs, ys, names = stack(others)
    model = transform.fit_ridge(xs, ys, names, best[1])
    d = transform.design(held, lk)
    pred = {q_: model.predict(r_) for q_, r_ in zip(d.ids, d.x, strict=True)}
    return sorted(pred, key=lambda z: -pred[z])


def boosted_board(held: int, others: list[int], lk: str) -> list[str]:
    """Depth-1 gradient-boosted stumps on realised VORP. Phase 3's best shape."""
    xs: list[list[float]] = []
    ys: list[float] = []
    names: list[str] = []
    for s_ in others:
        d = transform.design(s_, lk)
        names = d.names
        xs.extend(d.x)
        ys.extend(d.y_vorp)
    model = transform.fit_boosted(xs, ys, names)
    d = transform.design(held, lk)
    pred = {q_: model.predict(r_) for q_, r_ in zip(d.ids, d.x, strict=True)}
    return sorted(pred, key=lambda z: -pred[z])


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
        inc_s, q_s, l_s, b_s = [], [], [], []
        inc_pp: dict[str, list[float]] = {}
        q_pp: dict[str, list[float]] = {}
        l_pp: dict[str, list[float]] = {}
        b_pp: dict[str, list[float]] = {}
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
            c = score(learned_board(held, others, lk), held, lk)
            e = score(boosted_board(held, others, lk), held, lk)
            inc_s.append(a.rwre)
            q_s.append(b.rwre)
            l_s.append(c.rwre)
            b_s.append(e.rwre)
            for k, v in a.per_position.items():
                inc_pp.setdefault(k, []).append(v)
            for k, v in b.per_position.items():
                q_pp.setdefault(k, []).append(v)
            for k, v in c.per_position.items():
                l_pp.setdefault(k, []).append(v)
            for k, v in e.per_position.items():
                b_pp.setdefault(k, []).append(v)
            print(f"  {held}  inc {a.rwre:7.3f}   quant {b.rwre:7.3f} "
                  f"({b.rwre - a.rwre:+6.3f})   learn {c.rwre:7.3f} "
                  f"({c.rwre - a.rwre:+6.3f})   boost {e.rwre:7.3f} "
                  f"({e.rwre - a.rwre:+6.3f})   q {q:+g}")

        mi = sum(inc_s) / len(inc_s)
        results = {"quantile": q_s, "learned": l_s, "boosted": b_s}
        # Reference-set p over the six seasons: how extreme is the mean delta among the 2^6
        # sign flips of the per-season deltas. An exact sign test, no bootstrap.
        # EXACT SIGN TEST, and the earlier version of it was anti-conservative. Using `<=`
        # placed ties AND the observed assignment itself in `count` and excluded both from the
        # complement, so when the observed sum was the maximum the p came out 0.000 -- which a
        # two-sided sign test on six points cannot produce. Its floor is 2/64 = 0.031.
        #
        # Seasons whose delta is exactly zero carry no sign and are dropped, which is what makes
        # danger_zone honest: four of its six deltas are 0.000 because the fitted q is 0 and the
        # shape collapses to the incumbent, so only two seasons are informative and the smallest
        # attainable p there is 0.500.
        print(f"  MEAN  incumbent {mi:7.3f}    fitted q per fold {chosen}")
        for tag, vals in results.items():
            mv = sum(vals) / len(vals)
            deltas = [x - y for x, y in zip(vals, inc_s, strict=True)]
            wins = sum(1 for d in deltas if d < 0)
            informative = [d for d in deltas if d != 0.0]
            n = len(informative)
            obs = sum(informative)
            if n == 0:
                p = 1.0
            else:
                atleast = sum(
                    1 for mask in range(1 << n)
                    if sum(d if (mask >> i) & 1 else -d
                           for i, d in enumerate(informative)) >= abs(obs))
                atmost = sum(
                    1 for mask in range(1 << n)
                    if sum(d if (mask >> i) & 1 else -d
                           for i, d in enumerate(informative)) <= -abs(obs))
                p = min(1.0, (atleast + atmost) / (1 << n))
            print(f"    {tag:9s} {mv:7.3f}   delta {mv - mi:+7.3f}   improved "
                  f"{wins}/{len(deltas)}   informative {n}/{len(deltas)}   "
                  f"exact sign p {p:.3f}")
            summary.append((lk, tag, mi, mv, p))
        print("  per position (G7 -- never board-wide alone):")
        for k in sorted(inc_pp):
            a_ = sum(inc_pp[k]) / len(inc_pp[k])
            b_ = sum(q_pp[k]) / len(q_pp[k])
            c_ = sum(l_pp[k]) / len(l_pp[k]) if k in l_pp else float("nan")
            e_ = sum(b_pp[k]) / len(b_pp[k]) if k in b_pp else float("nan")
            print(f"    {k}  inc {a_:6.2f}   quant {b_:6.2f} ({b_ - a_:+5.2f})   "
                  f"learn {c_:6.2f} ({c_ - a_:+5.2f})   boost {e_:6.2f} ({e_ - a_:+5.2f})")

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    beats = 0
    for lk, tag, mi, mv, p in summary:
        verdict = "BEATS" if (mv < mi and p < 0.05) else "DOES NOT BEAT"
        beats += verdict == "BEATS"
        print(f"  {lk:20s} {tag:9s} incumbent {mi:6.2f} -> {mv:6.2f}   "
              f"delta {mv - mi:+6.2f}   p {p:.3f}   {verdict}")
    print(f"\n  BEATS THE INCUMBENT: {'yes' if beats else 'no'} "
          f"({beats} of {len(summary)} league-shape pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
