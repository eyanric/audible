"""S6 Phase 3 -- four transform shapes, each fitted inside the fold, against the incumbent.

Every shape is scored the same way: build a board for the held-out season, score it with the
phase-1 metric, and compare to the INCUMBENT board -- ESPN's projection through
`points -> subtract replacement -> sort by VORP`, which is what the cockpit ships today.

The penalty is fitted INSIDE each fold on the remaining seasons, never chosen once across all
six. `audible#85`'s winner was 2.5 RWRE worse on unseen seasons because its knobs were selected
on the same data that reported the win.

INJECTION 2  an information-free input is added to the model and its importance reported.
INJECTION 6  every result is reported per position as well as board-wide.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, signals, transform  # noqa: E402

LK = signals.LEAGUE
LAMBDAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)
QUANTILES = (-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0)


def score(order: list[str], season: int) -> tuple[float, dict[str, float]]:
    loaded = arms.load(signals.SOURCE, season, LK)
    rv = rank.realised_vorp(rank.realised_per_game(season, LK))
    s = rank.score_board(
        [p for p in order if p in rv], rv,
        teams=int(rank.league(LK).num_teams), pool_size=rank.pool_size_for(LK),
        position=loaded.position, indexing=signals.INDEXING,
        position_pool=rank.position_pool_sizes(LK),
    )
    return s.rwre, s.per_position


def incumbent(season: int) -> list[str]:
    loaded = arms.load(signals.SOURCE, season, LK)
    return rank.vorp_order(loaded.points, loaded.position, LK)


def _stack(seasons: list[int], target: str) -> tuple[list[list[float]], list[float], list[str]]:
    xs: list[list[float]] = []
    ys: list[float] = []
    names: list[str] = []
    for s in seasons:
        d = transform.design(s)
        names = d.names
        xs.extend(d.x)
        ys.extend(d.y_vorp if target == "vorp" else d.y_points)
    return xs, ys, names


def shape_learned(held: int, others: list[int]) -> tuple[list[str], float, str]:
    """Predict realised VORP from every input and sort by it. Replacement never appears."""
    xs, ys, names = _stack(others, "vorp")
    best = None
    for lam in LAMBDAS:
        # Inner LOSO over the fitting seasons only -- the held-out season is never touched.
        tot = 0.0
        for inner in others:
            tr = [s for s in others if s != inner]
            xi, yi, ni = _stack(tr, "vorp")
            m = transform.fit_ridge(xi, yi, ni, lam)
            d = transform.design(inner)
            pred = {p: m.predict(row) for p, row in zip(d.ids, d.x, strict=True)}
            tot += score(sorted(pred, key=lambda p: -pred[p]), inner)[0]
        if best is None or tot < best[0]:
            best = (tot, lam)
    lam = best[1]
    model = transform.fit_ridge(xs, ys, names, lam)
    d = transform.design(held)
    pred = {p: model.predict(row) for p, row in zip(d.ids, d.x, strict=True)}
    return (sorted(pred, key=lambda p: -pred[p]), model.eff_params,
            f"lam {lam:g}")


def shape_two_stage(held: int, others: list[int]) -> tuple[list[str], float, str]:
    """Predict realised per-game POINTS, then run the INCUMBENT transform on the prediction."""
    xs, ys, names = _stack(others, "points")
    best = None
    for lam in LAMBDAS:
        tot = 0.0
        for inner in others:
            tr = [s for s in others if s != inner]
            xi, yi, ni = _stack(tr, "points")
            m = transform.fit_ridge(xi, yi, ni, lam)
            d = transform.design(inner)
            loaded = arms.load(signals.SOURCE, inner, LK)
            pts = {p: m.predict(row) for p, row in zip(d.ids, d.x, strict=True)}
            tot += score(rank.vorp_order(pts, loaded.position, LK), inner)[0]
        if best is None or tot < best[0]:
            best = (tot, lam)
    lam = best[1]
    model = transform.fit_ridge(xs, ys, names, lam)
    d = transform.design(held)
    loaded = arms.load(signals.SOURCE, held, LK)
    pts = {p: model.predict(row) for p, row in zip(d.ids, d.x, strict=True)}
    return rank.vorp_order(pts, loaded.position, LK), model.eff_params, f"lam {lam:g}"


def shape_quantile(held: int, others: list[int]) -> tuple[list[str], float, str]:
    """Rank on `points + q * sd_pts` rather than on the mean. One fitted parameter."""
    def board(season: int, q: float) -> list[str]:
        loaded = arms.load(signals.SOURCE, season, LK)
        meta = signals.residual.ffa_meta(season)
        pts = dict(loaded.points)
        for p, v in pts.items():
            m = meta.get(p)
            if m and m.get("sd_rel") == m.get("sd_rel"):
                pts[p] = v * (1.0 + q * m["sd_rel"])
        return rank.vorp_order(pts, loaded.position, LK)

    best = None
    for q in QUANTILES:
        tot = sum(score(board(s, q), s)[0] for s in others)
        if best is None or tot < best[0]:
            best = (tot, q)
    q = best[1]
    return board(held, q), 1.0, f"q {q:+g}"


def shape_boosted(held: int, others: list[int]) -> tuple[list[str], float, str, dict]:
    """Depth-1 gradient-boosted stumps on realised VORP. Reports feature importances."""
    xs, ys, names = _stack(others, "vorp")
    model = transform.fit_boosted(xs, ys, names)
    d = transform.design(held)
    pred = {p: model.predict(row) for p, row in zip(d.ids, d.x, strict=True)}
    return (sorted(pred, key=lambda p: -pred[p]), model.eff_params,
            f"{len(model.stumps)} stumps x {model.shrinkage}", model.importances())


def main() -> int:
    seasons = list(referee.espn_seasons())
    print(f"seasons {seasons}   features {len(transform.FEATURES)} "
          f"-> {len(transform.design(seasons[0]).names)} design columns")
    print("  design columns include a `__present` indicator per input: absence is declared,")
    print("  never silently coded as the positional mean.")

    results: dict[str, list[float]] = {}
    per_pos: dict[str, list[dict[str, float]]] = {}
    notes: dict[str, list[str]] = {}
    effs: dict[str, list[float]] = {}
    importances: dict[str, float] = {}

    for held in seasons:
        others = [s for s in seasons if s != held]
        print(f"\n{'-' * 78}\nHELD OUT {held}   fitted on {others}")

        b, pp = score(incumbent(held), held)
        results.setdefault("incumbent", []).append(b)
        per_pos.setdefault("incumbent", []).append(pp)
        effs.setdefault("incumbent", []).append(1.0)
        print(f"  incumbent    RWRE {b:7.3f}   " +
              "  ".join(f"{k} {v:6.2f}" for k, v in sorted(pp.items())))

        for tag, fn in (("learned", shape_learned), ("two-stage", shape_two_stage),
                        ("quantile", shape_quantile)):
            order, eff, note = fn(held, others)
            r, pp2 = score(order, held)
            results.setdefault(tag, []).append(r)
            per_pos.setdefault(tag, []).append(pp2)
            effs.setdefault(tag, []).append(eff)
            notes.setdefault(tag, []).append(note)
            print(f"  {tag:12s} RWRE {r:7.3f}   " +
                  "  ".join(f"{k} {v:6.2f}" for k, v in sorted(pp2.items())) +
                  f"   eff params {eff:6.1f}   {note}")

        order, eff, note, imp = shape_boosted(held, others)
        r, pp2 = score(order, held)
        results.setdefault("boosted", []).append(r)
        per_pos.setdefault("boosted", []).append(pp2)
        effs.setdefault("boosted", []).append(eff)
        notes.setdefault("boosted", []).append(note)
        for k, v in imp.items():
            importances[k] = importances.get(k, 0.0) + v / len(seasons)
        print(f"  {'boosted':12s} RWRE {r:7.3f}   " +
              "  ".join(f"{k} {v:6.2f}" for k, v in sorted(pp2.items())) +
              f"   {note}")

    print("\n" + "=" * 78)
    print("PHASE 3 -- every shape, including the ones that lost")
    print("=" * 78)
    inc = sum(results["incumbent"]) / len(results["incumbent"])
    print(f"  {'shape':12s} {'RWRE':>8s} {'vs incumbent':>14s} {'eff params':>11s}")
    for tag in ("incumbent", "learned", "two-stage", "quantile", "boosted"):
        m = sum(results[tag]) / len(results[tag])
        eff = sum(effs[tag]) / len(effs[tag])
        delta = "" if tag == "incumbent" else f"{m - inc:+14.3f}"
        print(f"  {tag:12s} {m:8.3f} {delta:>14s} {eff:11.1f}")
        if tag in notes:
            print(f"      fitted per fold: {'  '.join(notes[tag])}")

    print("\n  per season:")
    for tag in ("incumbent", "learned", "two-stage", "quantile", "boosted"):
        print(f"    {tag:12s} " + "  ".join(f"{s}:{v:6.2f}"
                                            for s, v in zip(seasons, results[tag], strict=True)))

    print("\n  per position, mean over folds (INJECTION 6 -- never board-wide alone):")
    for tag in ("incumbent", "learned", "two-stage", "quantile", "boosted"):
        agg = {}
        for d in per_pos[tag]:
            for k, v in d.items():
                agg.setdefault(k, []).append(v)
        print(f"    {tag:12s} " + "  ".join(f"{k} {sum(v) / len(v):6.2f}"
                                            for k, v in sorted(agg.items())))

    print("\n  boosted feature importances, mean over folds (top 15):")
    for k, v in sorted(importances.items(), key=lambda kv: -kv[1])[:15]:
        print(f"    {k:28s} {v:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
