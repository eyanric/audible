"""S5 Tasks 3 and 4 -- re-decide every signal that was decided against a single draw.

G7 requires the expected locus to be STATED BEFORE the run, so it is in `PLAN` below and
printed before any number appears.

INJECTION 1  adjudicate against one floor draw as well, and report which dispositions differ.
INJECTION 4  report the locus AND the board-wide figure for every signal, so the dilution the
             board-wide number hides is visible.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import referee, signals  # noqa: E402

FLOOR_JSON = Path(__file__).resolve().parent / "s5-floor.json"

# name, scope, kwargs, expected locus, the decision the broken referee reached
PLAN: tuple[tuple[str, str | None, dict, tuple[str, ...], str, str], ...] = (
    ("snap_share", None, {}, ("RB", "WR", "TE"),
     "REVERTED (audible#86)",
     "snap share is an opportunity rate; it separates players WITHIN a position, and at "
     "quarterback it is nearly saturated so it should do least there"),
    ("adp_gap", None, {}, ("QB", "RB", "WR", "TE"),
     "REVERTED (audible#86)",
     "constructed per position by ranking projection against ADP, so every position is a "
     "locus; the circularity hazard is that ADP is partly derived from the same projections"),
    ("draft_round", None, {"rookies_only": True}, ("RB", "WR", "TE"),
     "REVERTED (audible#86)",
     "draft capital is only news for a player with no prior season, so it is applied to "
     "rookies alone and is inert for everyone else by construction"),
    ("ngs_separation", None, {}, ("WR",),
     "UNRESOLVED, promising (audible#87 retraction)",
     "receiver separation is a receiving measurement; WR is the locus and TE is the control"),
    ("ngs_rush_eff", None, {}, ("RB",),
     "REVERTED (audible#87)",
     "rushing efficiency is charted for ball carriers only"),
    ("ngs_time_to_throw", None, {}, ("QB",),
     "REVERTED (audible#87)",
     "time to throw is charted for passers only"),
    ("contract", None, {}, ("QB", "RB", "WR", "TE"),
     "REVERTED (audible#87)",
     "cap share is priced within a position by the market, so every position is a locus"),
    ("availability", "board", {}, ("board",),
     "NEVER MEASURED (audible#87 measured floating-point residue)",
     "a position-level constant cannot reorder a position, so the ONLY locus is the "
     "cross-position interleave and every per-position figure must be exactly +0.000"),
)


def legacy_for(seasons: tuple[int, ...]) -> dict[str, dict[int, float]]:
    """audible#86/#87's single draw, computed once and reused."""
    return referee.deltas("noise", seasons, salt=referee.LEGACY_SALT)


def main() -> int:
    floor = referee.load_floor(str(FLOOR_JSON))
    print(f"floor: {len(floor.salts)} draws over seasons {floor.seasons}")

    print("\n" + "=" * 78)
    print("G7 -- EXPECTED LOCUS, STATED BEFORE ANY NUMBER")
    print("=" * 78)
    for name, _sc, _kw, locus, old, why in PLAN:
        print(f"  {name:18s} locus {'/'.join(locus):14s} was: {old}")
        print(f"      {why}")

    print("\n" + "=" * 78)
    print("G1 -- THE FLOOR, AS A DISTRIBUTION")
    print("=" * 78)
    for locus in referee.LOCI:
        print(f"  {locus:5s} {referee.floor_summary(floor, locus)}")

    changed: list[str] = []
    ptable: list[tuple[str, float, str]] = []
    print("\n" + "=" * 78)
    print("G3/G6 -- RE-ADJUDICATION, interval against interval")
    print("=" * 78)
    for name, scope, kw, loci, old, _why in PLAN:
        seasons = signals.seasons_for(name)
        print(f"\n{'-' * 78}\n{name}   scope={scope or 'position'}   seasons {seasons}")
        print(f"  was: {old}")
        if not seasons:
            print("  NO SEASONS -- UNRESOLVED")
            continue
        d = referee.deltas(name, seasons, scope=scope, **kw)

        # INJECTION 4: the locus figure and the board-wide figure, side by side.
        print("  locus  signal delta   board-wide delta   dilution")
        for locus in loci:
            if locus not in d or "board" not in d:
                continue
            ls = sum(d[locus].values()) / len(d[locus])
            bs = sum(d["board"].values()) / len(d["board"])
            print(f"  {locus:5s} {ls:+13.3f} {bs:+18.3f} "
                  f"{abs(ls) - abs(bs):+10.3f} of effect lost to averaging")

        for locus in loci:
            if locus not in d:
                print(f"  {locus}: not defined for this term")
                continue
            v = referee.adjudicate(d[locus], floor, locus)
            print(f"\n  === {locus} ===")
            print(f"    signal     {v.signal}")
            print(f"    floor      {v.floor}")
            rp = referee.reference_p(d[locus], floor, locus)
            calibrated = "RESOLVED (reference set)" if rp < 0.05 else "not resolved"
            print(f"    difference {v.difference}   -> {v.disposition}")
            print(f"    reference-set p {rp:.3f} over {len(floor.salts)} draws "
                  f"-> {calibrated}")
            ptable.append((f"{name}@{locus}", rp, v.disposition))
            per = "  ".join(f"{s}:{x:+.2f}" for s, x in sorted(v.per_season.items()))
            print(f"    per season {per}")
            lams = referee.fitted_lambdas(name, seasons, locus, scope=scope, **kw)
            sgn = {(1 if x > 0 else -1 if x < 0 else 0) for x in lams.values()}
            print(f"    fitted lambda {dict(sorted(lams.items()))}"
                  f"{'  SIGN FLIPS ACROSS FOLDS' if len({s for s in sgn if s} ) > 1 else ''}")

            # INJECTION 1: the same call, decided against ONE draw.
            one = referee.adjudicate(d[locus], floor, locus, resample_salt=False,
                                     fixed_salt_index=0)
            legacy_d = legacy_for(seasons)
            tag = f"{name}@{locus}"
            if one.disposition != v.disposition:
                changed.append(f"{tag}: one draw said {one.disposition!r}, "
                               f"distribution says {v.disposition!r}")
            wc = one.difference.hi - one.difference.lo
            wu = v.difference.hi - v.difference.lo
            print(f"    INJECTION 1 against salt[0] alone: {one.difference} "
                  f"-> {one.disposition}")
            print(f"    G2 interval width: one draw {wc:.3f} -> distribution {wu:.3f}"
                  f"  ({wu / wc if wc else float('nan'):.2f}x wider)")
            if locus in legacy_d:
                lm = sum(legacy_d[locus].values()) / len(legacy_d[locus])
                sm = sum(d[locus].values()) / len(d[locus])
                print(f"    INJECTION 1 against the audible#86/#87 draw "
                      f"({lm:+.3f}): signal - floor = {sm - lm:+.3f}")

    print("\n" + "=" * 78)
    print("INJECTION 1 -- dispositions that DIFFER between one draw and the distribution")
    print("=" * 78)
    for line in changed:
        print(f"  {line}")
    print(f"  total: {len(changed)}")

    print("\n" + "=" * 78)
    print("G9 -- THE CALIBRATED TEST. Reference-set p, which needs no bootstrap and whose")
    print("null distribution is uniform on the draws by construction.")
    print("=" * 78)
    for tag, rp, disp in sorted(ptable, key=lambda t: t[1]):
        mark = "  <== RESOLVED at 5%" if rp < 0.05 else ""
        print(f"  {tag:28s} p {rp:.3f}   bootstrap said: {disp}{mark}")
    n_res = sum(1 for _t, rp, _d in ptable if rp < 0.05)
    print(f"\n  resolved at a calibrated 5%: {n_res} of {len(ptable)}")
    print(f"  floor of this test with K={len(floor.salts)}: {2 / (len(floor.salts) + 1):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
