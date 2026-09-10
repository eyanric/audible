"""S6 INJECTION 2 -- put an information-free input into the phase-3 model.

Its importance must be near zero and it must not beat the calibrated floor. `audible#85`
searched 4,000 boards and a knob made of a sha256 bought 42% of the winner's apparent gain, so
this is the specific failure the injection exists to catch.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import referee, transform  # noqa: E402
from sim.runs import s6_phase3 as p3  # noqa: E402


def main() -> int:
    seasons = list(referee.espn_seasons())
    original = transform.FEATURES
    try:
        # `noise` is a sha256 of player and season: information-free by construction.
        transform.FEATURES = (*original, "noise")
        transform.design.cache_clear()
        d0 = transform.design(seasons[0])
        print(f"features {len(transform.FEATURES)}  design columns {len(d0.names)}")
        print(f"  noise columns present: {[n for n in d0.names if n.startswith('noise')]}")

        imps: dict[str, float] = {}
        scores: list[float] = []
        for held in seasons:
            others = [s for s in seasons if s != held]
            xs, ys, names = p3._stack(others, "vorp")
            model = transform.fit_boosted(xs, ys, names)
            d = transform.design(held)
            pred = {p: model.predict(row) for p, row in zip(d.ids, d.x, strict=True)}
            r, _pp = p3.score(sorted(pred, key=lambda p: -pred[p]), held)
            scores.append(r)
            for k, v in model.importances().items():
                imps[k] = imps.get(k, 0.0) + v / len(seasons)
            print(f"  {held}: RWRE {r:7.3f}   noise importance "
                  f"{imps.get('noise', 0.0) * len(seasons) / (seasons.index(held) + 1):.4%}")

        print("\n  mean importances with the information-free input included:")
        for k, v in sorted(imps.items(), key=lambda kv: -kv[1])[:10]:
            mark = "   <== INFORMATION-FREE" if k.startswith("noise") else ""
            print(f"    {k:28s} {v:7.2%}{mark}")
        n_imp = imps.get("noise", 0.0) + imps.get("noise__present", 0.0)
        print(f"\n  INJECTION 2: total importance given to the sha256: {n_imp:.2%}")
        print(f"  boosted RWRE with noise {sum(scores) / len(scores):7.3f}  "
              f"without noise 24.574  incumbent 22.425")
        print(f"  passes (importance under 2%): {n_imp < 0.02}")
    finally:
        transform.FEATURES = original
        transform.design.cache_clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
