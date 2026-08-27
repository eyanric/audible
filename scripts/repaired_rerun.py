"""DIAGNOSTIC rerun: arms S, V and V' side by side. NOT a gate attempt.

    uv run --extra nflverse python scripts/repaired_rerun.py

The pre-registered gate already failed (arm V, 2 of 5, mean -81.2, room-wide 12/40). That
result stands and nothing here revises it. Rule and prediction fixed in
docs/pre-registration-repaired-instrument.md (0cec38f), committed before this file existed.

V' is a REPAIRED INSTRUMENT, not an out-of-sample test: the fit was published before the
exclusion rule was written, so the positions it removes were known in advance.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from redraft import (  # noqa: E402
    ELIG,
    ERIC_TEAM,
    MEANINGFUL_MARGIN,
    SLOTS,
    TEAMS,
    YEARS,
    lineup_points,
    run_year,
)
from redraft_vorp import (  # noqa: E402
    draft_with,
    fit_curve,
    season_table,
    vorp_board,
)

# Fixed by the rule in 0cec38f: mean held-out rho vs the 1/sqrt(n-1) noise floor.
EXCLUDED_FROM_VORP = ("QB", "K", "DEF")


def load_fold(fold: int, lid: int):
    picks = json.loads(
        (REPO / "data" / "cache" / f"espn_draft_{lid}_{fold}.json").read_text("utf-8"))
    points = {str(k): float(v) for k, v in json.loads(
        (REPO / "data" / "cache" / f"espn_actuals_{lid}_{fold}.json").read_text("utf-8")).items()}
    return picks, points


def add_rank_positions(position: dict, lid: int, fold: int) -> None:
    rp = REPO / "data" / "cache" / f"espn_ranks_{lid}_{fold}.json"
    if rp.exists():
        for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
            if row.get("position"):
                position.setdefault(str(eid), row["position"])


def repaired_value(vorp: dict, position: dict) -> dict:
    """V': positions with no held-out signal are removed from VORP entirely.

    They are not merely down-weighted -- a value the mapping cannot support should not be
    competing with one it can. They come back only through the roster-need path, which the
    draft loop already applies in the final rounds when `forced` binds.
    """
    return {
        pid: (float("-inf") if position.get(pid) in EXCLUDED_FROM_VORP else v)
        for pid, v in vorp.items()
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    args = ap.parse_args()

    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]
    lid = config.league_id
    tables = {y: season_table(y, lid) for y in YEARS}
    curves = {f: fit_curve(tables, [y for y in YEARS if y != f], f) for f in YEARS}

    print("=" * 104)
    print("DIAGNOSTIC RERUN -- NOT A GATE ATTEMPT")
    print("=" * 104)
    print("  The pre-registered gate already failed: arm V, 2 of 5, mean -81.2.")
    print("  V' is a REPAIRED INSTRUMENT (the excluded positions were known before the rule).")
    print(f"  Excluded from VORP in V': {', '.join(EXCLUDED_FROM_VORP)}\n")

    per_arm = {"S": [], "V": [], "V'": []}
    eric_totals, arm_totals = [], collections.defaultdict(list)
    slot_by_year: dict[int, dict] = {}

    for fold in YEARS:
        picks, points = load_fold(fold, lid)
        vorp, position, _pred, _lv = vorp_board(tables[fold], curves[fold], config)
        add_rank_positions(position, lid, fold)

        s = run_year(fold, config, ERIC_TEAM)          # arm S (and Eric's real roster)
        eric_pts = s["real"]
        eric_totals.append(eric_pts)
        per_arm["S"].append(s["audible"] - eric_pts)
        arm_totals["S"].append(s["audible"])

        rosters = {}
        for tag, value in (("V", vorp), ("V'", repaired_value(vorp, position))):
            real, new, _c = draft_with(value, position, list(vorp), picks, ERIC_TEAM)
            pts = lineup_points(new, points, position)
            per_arm[tag].append(pts - eric_pts)
            arm_totals[tag].append(pts)
            rosters[tag] = new
        slot_by_year[fold] = {"real": s["real_roster"], "V": rosters["V"],
                              "V'": rosters["V'"], "points": points, "position": position}

    print(f"  {'year':<6}{'Eric':>10}" + "".join(f"{a:>12}" for a in ("S", "V", "V'"))
          + "   margins  S / V / V'")
    for i, fold in enumerate(YEARS):
        m = "  ".join(f"{per_arm[a][i]:+8.1f}" for a in ("S", "V", "V'"))
        print(f"  {fold:<6}{eric_totals[i]:>10.1f}"
              + "".join(f"{arm_totals[a][i]:>12.1f}" for a in ("S", "V", "V'"))
              + f"   {m}")

    print()
    for arm in ("S", "V", "V'"):
        wins = sum(1 for m in per_arm[arm] if m > MEANINGFUL_MARGIN)
        print(f"  arm {arm:<3} vs Eric: {wins}/5 by >{MEANINGFUL_MARGIN:.0f}   "
              f"mean {statistics.mean(per_arm[arm]):+8.1f}   "
              f"median {statistics.median(per_arm[arm]):+8.1f}")

    print()
    print("=" * 104)
    print("VARIANCE -- a higher-variance strategy with a lower mean is worse on both axes")
    print("=" * 104)
    print(f"  {'series':<26}{'mean':>10}{'SD':>10}{'min':>10}{'max':>10}")
    print(f"  {'Eric actual totals':<26}{statistics.mean(eric_totals):>10.1f}"
          f"{statistics.stdev(eric_totals):>10.1f}{min(eric_totals):>10.1f}"
          f"{max(eric_totals):>10.1f}")
    for arm in ("S", "V", "V'"):
        t = arm_totals[arm]
        print(f"  {'arm ' + arm + ' season totals':<26}{statistics.mean(t):>10.1f}"
              f"{statistics.stdev(t):>10.1f}{min(t):>10.1f}{max(t):>10.1f}")

    print()
    print("=" * 104)
    print("PER-YEAR SLOT DECOMPOSITION -- 2022 and 2021 (arm V minus Eric)")
    print("=" * 104)
    for fold in (2022, 2021):
        d = slot_by_year[fold]
        pos, pts = d["position"], d["points"]
        delta = collections.Counter()
        for tag, roster in (("eric", d["real"]), ("V", d["V"])):
            order = sorted(range(len(SLOTS)), key=lambda i: len(ELIG[SLOTS[i]]))
            pool = sorted(roster, key=lambda p: -pts.get(p, 0.0))
            used = set()
            for i in order:
                hit = next((p for p in pool
                            if p not in used and pos.get(p) in ELIG[SLOTS[i]]), None)
                if hit:
                    used.add(hit)
                    delta[SLOTS[i]] += pts.get(hit, 0.0) * (1 if tag == "V" else -1)
        tot = sum(delta.values())
        worst = sorted(delta.items(), key=lambda kv: kv[1])[:3]
        share = sum(v for _, v in worst) / tot * 100 if tot else 0.0
        print(f"\n  {fold}: total {tot:+.1f}")
        for slot, v in sorted(delta.items(), key=lambda kv: kv[1]):
            print(f"     {slot:<6}{v:>+10.1f}")
        print(f"     -> the three worst slots are {share:.0f}% of the deficit "
              f"({', '.join(s for s, _ in worst)})")

    print()
    print("=" * 104)
    print("ROOM-WIDE (all eight managers)")
    print("=" * 104)
    print(f"  {'arm':<5}{'wins >50 of 40':>18}{'mean':>10}{'SD of margins':>16}")
    for arm, value_fn in (("V", lambda v, p: v), ("V'", repaired_value)):
        margins = []
        for fold in YEARS:
            picks, points = load_fold(fold, lid)
            vorp, position, _p, _l = vorp_board(tables[fold], curves[fold], config)
            add_rank_positions(position, lid, fold)
            val = value_fn(vorp, position)
            for team in range(1, TEAMS + 1):
                real, new, _c = draft_with(val, position, list(vorp), picks, team)
                margins.append(lineup_points(new, points, position)
                               - lineup_points(real, points, position))
        print(f"  {arm:<5}{sum(1 for m in margins if m > MEANINGFUL_MARGIN):>13}/40"
              f"{statistics.mean(margins):>10.1f}{statistics.stdev(margins):>16.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
