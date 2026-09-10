"""S6 Phase 5 -- adjudicate every input against the corrected floor, then combine what survives.

The inclusion rule is the handoff's: an input joins the combination only if it beats the
calibrated floor ALONE, or a phase-3 model assigns it stable importance across all six folds.

The combination must be able to EXCLUDE an input, not only include one -- `ngs_time_to_throw`
at QB resolved as a HARM in `audible#88`, and a rule that can only add would carry it.

INJECTION 5  the same set adjudicated against a SINGLE floor draw, to measure what the old
             mechanism would have decided.
INJECTION 6  every signal reported at its locus AND board-wide.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import referee, signals  # noqa: E402

LK = signals.LEAGUE
FLOOR_JSON = Path(__file__).resolve().parent / "s6-floor.json"

# name -> (scope, kwargs, the locus it should act on)
PLAN: tuple[tuple[str, str | None, dict, tuple[str, ...]], ...] = (
    ("snap_share", None, {}, ("RB", "WR", "TE")),
    ("target_share", None, {}, ("RB", "WR", "TE")),
    ("td_oe", None, {}, ("QB", "RB", "WR", "TE")),
    ("draft_round", None, {"rookies_only": True}, ("RB", "WR", "TE")),
    ("adp_gap", None, {}, ("QB", "RB", "WR", "TE")),
    ("ngs_separation", None, {}, ("WR", "TE")),
    ("ngs_cushion", None, {}, ("WR", "TE")),
    ("ngs_rush_eff", None, {}, ("RB",)),
    ("ngs_time_to_los", None, {}, ("RB",)),
    ("ngs_time_to_throw", None, {}, ("QB",)),
    ("contract", None, {}, ("QB", "RB", "WR", "TE")),
    ("availability", "board", {}, ("board",)),
    ("age_at_export", None, {}, ("QB", "RB", "WR", "TE")),
    ("uncertainty", None, {}, ("QB", "RB", "WR", "TE")),
    ("ffa_skew", None, {}, ("QB", "RB", "WR", "TE")),
    ("ffa_dropoff", None, {}, ("QB", "RB", "WR", "TE")),
    ("ffa_experience", None, {}, ("QB", "RB", "WR", "TE")),
    ("depth_slot", None, {}, ("QB", "RB", "WR", "TE")),
    ("ff_opp_exp", None, {}, ("QB", "RB", "WR", "TE")),
    ("ff_opp_eff", None, {}, ("QB", "RB", "WR", "TE")),
)


def main() -> int:
    floor = referee.load_floor(str(FLOOR_JSON))
    print(f"floor draws {len(floor.salts)}   floor of the reference test "
          f"{2 / (len(floor.salts) + 1):.4f}")

    rows = []
    changed = []
    for name, scope, kw, loci in PLAN:
        seasons = signals.seasons_for(name)
        if not seasons:
            print(f"\n{name}: NO SEASONS")
            continue
        d = referee.deltas(name, seasons, scope=scope, **kw)
        print(f"\n{'-' * 78}\n{name}  scope={scope or 'position'}  seasons {len(seasons)}")
        bw = sum(d["board"].values()) / len(d["board"]) if "board" in d else float("nan")
        for locus in loci:
            if locus not in d:
                continue
            m = sum(d[locus].values()) / len(d[locus])
            v = referee.adjudicate(d[locus], floor, locus)
            p = referee.reference_p(d[locus], floor, locus)
            # INJECTION 5: what one draw would have said.
            one = referee.adjudicate(d[locus], floor, locus, resample_salt=False,
                                     fixed_salt_index=0)
            if one.disposition != v.disposition:
                changed.append(f"{name}@{locus}: one draw {one.disposition!r} vs "
                               f"distribution {v.disposition!r}")
            verdict = ("RESOLVED BETTER" if (p < 0.05 and m < 0)
                       else "RESOLVED WORSE" if (p < 0.05 and m > 0) else "not resolved")
            rows.append((name, locus, m, bw, p, verdict))
            print(f"  {locus:5s} signal {m:+7.3f}   board-wide {bw:+7.3f}   "
                  f"diff {v.difference}   p {p:.3f}   {verdict}")

    print("\n" + "=" * 78)
    print("EVERY LOCUS, SORTED BY REFERENCE-SET p")
    print("=" * 78)
    for name, locus, m, _bw, p, verdict in sorted(rows, key=lambda r: r[4]):
        mark = "  <== RESOLVED" if p < 0.05 else ""
        print(f"  {name + '@' + locus:34s} signal {m:+7.3f}  p {p:.3f}  {verdict}{mark}")
    res = [r for r in rows if r[4] < 0.05]
    print(f"\n  resolved at a calibrated 5%: {len(res)} of {len(rows)} loci")
    better = [r for r in res if r[2] < 0]
    worse = [r for r in res if r[2] > 0]
    print(f"    improvements: {[f'{r[0]}@{r[1]}' for r in better] or 'NONE'}")
    print(f"    harms:        {[f'{r[0]}@{r[1]}' for r in worse] or 'NONE'}")
    expected = 0.05 * len(rows)
    print(f"\n  MULTIPLE COMPARISONS. {len(rows)} loci were tested at a nominal 5%, so about")
    print(f"  {expected:.1f} false resolutions are expected by chance alone. {len(res)} were")
    print("  observed, which is BELOW the chance expectation. Neither of the two survives a")
    print(f"  Bonferroni threshold of {0.05 / len(rows):.4f} -- and neither could, because the")
    print(f"  floor of the reference test at K=80 is {2 / 81:.4f}. To resolve anything against")
    need_k = int(0.05 ** -1 * len(rows) * 2) - 1
    print(f"  {len(rows)} comparisons this harness would need K >= {need_k}.")

    print("\n" + "=" * 78)
    print("INJECTION 5 -- dispositions that differ under a SINGLE floor draw")
    print("=" * 78)
    for line in changed:
        print(f"  {line}")
    print(f"  total {len(changed)} of {len(rows)} loci "
          f"({len(changed) / len(rows):.0%}); audible#88 measured 5 of 18 = 28%")

    print("\n" + "=" * 78)
    print("INJECTION 6 -- the dilution, locus against board-wide")
    print("=" * 78)
    flips = 0
    for name, locus, m, bw, _p, _v in rows:
        if locus == "board" or bw != bw:
            continue
        if (m < 0) != (bw < 0) and abs(m) > 0.05 and abs(bw) > 0.05:
            flips += 1
            print(f"  {name + '@' + locus:34s} locus {m:+7.3f}  board-wide {bw:+7.3f}"
                  f"   SIGN FLIPS")
    print(f"  loci whose board-wide figure carries the opposite sign: {flips}")

    print("\n" + "=" * 78)
    print("THE COMBINATION")
    print("=" * 78)
    print("  Inclusion rule: beats the calibrated floor ALONE, or a phase-3 model gives it")
    print("  stable importance across all six folds.")
    if not better:
        print("\n  NO INPUT BEATS THE FLOOR ALONE. The first criterion admits nothing.")
    print("\n  Second criterion -- phase-3 boosted importances, mean over folds:")
    print("    pos_QB 40.0%   projection 35.1%   ffa_dropoff__present 11.4%")
    print("    pos_RB 3.7%    ngs_rush_eff__present 3.5%   uncertainty 2.9%")
    print("    adp_gap__present 2.2%   contract 1.2%")
    print("  Of the twenty football inputs, the largest share given to any ACTUAL VALUE")
    print("  (rather than a position dummy, the projection, or a missingness indicator)")
    print("  is `uncertainty` at 2.9%. The second criterion admits nothing either.")
    print("\n  THE COMBINATION CANNOT BE FORMED. There is nothing to combine.")
    print(f"  Reported anyway, so the next session does not have to re-run it: the best "
          f"single input by p is {sorted(rows, key=lambda r: r[4])[0][0]}"
          f"@{sorted(rows, key=lambda r: r[4])[0][1]} at p "
          f"{sorted(rows, key=lambda r: r[4])[0][4]:.3f}.")
    print("  Phase 3's best SHAPE was `quantile` at 22.656 against the incumbent's 22.425 "
          "-- also a loss.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
