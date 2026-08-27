"""Task 1: does re-scoring the room's own board beat holding it, and does the model add more?

    uv run --extra nflverse python scripts/backtest_arms.py

Read-only. Builds nothing into the sort, changes no ranking, writes no draft state.

Reports B - A FIRST, because that is the core strategy: the opponents' board is KNOWN (it is
ESPN's preseason rank, and this room demonstrably drafts from it), so the first question is
whether re-expressing that same board for a league that pays WR/TE 0.5 a catch and a running
back nothing beats simply holding it. C - B comes second and asks a narrower question: what
does the opportunity adjustment add on top, with the projection source held constant.

Folds are 2023, 2024, 2025 -- every season for which ESPN serves a period-appropriate rank
snapshot for this league. Per-fold sign is reported beside any pooled interval, because three
folds agreeing in direction is worth more than one wide interval that straddles zero.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

FOLDS = (2023, 2024, 2025)
TEAMS = 8

# Reported separately, never pooled. Rounds 1-2 are near-deterministic (everyone agrees on the
# top 16) and rounds 11-16 are mostly noise; the decision that a draft is won or lost on sits
# in the middle, which is why the correction asks for that band on its own.
BANDS = {"rounds 1-2": (1, 2), "rounds 3-10": (3, 10), "rounds 11-16": (11, 16)}


def crosswalk() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """espn_id -> sleeper_id, gsis_id -> sleeper_id, sleeper_id -> position."""
    from audible.adapters.nflverse import id_map_frame

    df = id_map_frame().select(["sleeper_id", "espn_id", "gsis_id", "position"])
    espn, gsis, pos = {}, {}, {}
    for r in df.iter_rows(named=True):
        sid = r["sleeper_id"]
        if sid is None:
            continue
        sid = str(sid)
        if r["espn_id"] is not None:
            espn[str(r["espn_id"])] = sid
        if r["gsis_id"] is not None:
            gsis[str(r["gsis_id"])] = sid
        if r["position"] is not None:
            pos[sid] = str(r["position"])
    return espn, gsis, pos


def run_fold(config, year: int, espn_map, gsis_map, xwalk_pos) -> dict:
    from audible.adapters.sleeper import SleeperAdapter
    from audible.backtest.arms import blended_arm, espn_arms, opportunity_arm
    from audible.backtest.data import season_actuals
    from audible.backtest.metrics import paired_bootstrap, pairwise_accuracy

    ranks_path = REPO / "data" / "cache" / f"espn_ranks_{config.league_id}_{year}.json"
    ranks = json.loads(ranks_path.read_text(encoding="utf-8"))

    with SleeperAdapter() as ad:
        actuals = season_actuals(ad, year, config)

    # Labels: THIS league's scoring on the season that actually happened. Position comes from
    # the same record, so a label and its position can never disagree.
    label = {pid: ps.points for pid, ps in actuals.items() if ps.games > 0}
    position = {pid: ps.primary for pid, ps in actuals.items() if ps.games > 0}
    for pid, p in xwalk_pos.items():
        position.setdefault(pid, p)

    a, b = espn_arms(ranks, espn_map)
    c2 = opportunity_arm(config, year - 1, gsis_map)
    c = blended_arm(b, c2)

    # The population is everyone the ROOM could have drafted: on ESPN's board that year, with
    # a real outcome. A player ESPN never ranked was not a draft decision anybody faced.
    universe = [pid for pid in a.rank_by_id if pid in label and pid in position]

    out = {"year": year, "universe": len(universe), "bands": {}}
    for band, (lo_r, hi_r) in BANDS.items():
        lo, hi = (lo_r - 1) * TEAMS + 1, hi_r * TEAMS
        ids = [p for p in universe if lo <= a.rank_by_id[p] <= hi]
        row = {"n": len(ids), "arms": {}}
        for arm in (a, b, c, c2):
            acc, pairs = pairwise_accuracy(ids, arm.rank_by_id, label, position)
            row["arms"][arm.name] = {"acc": acc, "pairs": pairs}
        # TASK 1: pooled accuracy cannot see the construction rule. Under corrected B only WR
        # and TE move; RB, QB, K and D/ST keep A's ordering exactly, so their B-A must be
        # EXACTLY 0.000. Anything else is a harness bug, and that would be the finding.
        row["by_pos"] = {}
        for pos in ("WR", "TE", "RB", "QB", "K", "DEF"):
            sub = [p for p in ids if position.get(p) == pos]
            acc_a, pairs = pairwise_accuracy(sub, a.rank_by_id, label, position)
            acc_b, _ = pairwise_accuracy(sub, b.rank_by_id, label, position)
            row["by_pos"][pos] = {"n": len(sub), "pairs": pairs,
                                  "A": acc_a, "B": acc_b, "B-A": acc_b - acc_a}
        row["B-A"] = paired_bootstrap(ids, b.rank_by_id, a.rank_by_id, label, position)
        row["C-B"] = paired_bootstrap(ids, c.rank_by_id, b.rank_by_id, label, position)
        row["C2-B"] = paired_bootstrap(ids, c2.rank_by_id, b.rank_by_id, label, position)
        out["bands"][band] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    from audible.backtest.arms import C_LAMBDA, assert_one_scoring, rb_reception_points
    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]

    # Before anything is measured. A flattened reception rule would not look broken; it would
    # answer a question about a different league.
    assert_one_scoring(config)
    print("=" * 96)
    print("SCORING GUARD")
    print("=" * 96)
    print(f"  scoring_for('RB')['rec'] = {config.scoring_for('RB')['rec']}   "
          f"one RB reception scores {rb_reception_points(config)} points")
    print(f"  scoring_for('WR')['rec'] = {config.scoring_for('WR')['rec']}   "
          f"scoring_for('TE')['rec'] = {config.scoring_for('TE')['rec']}")
    print("  labels and every arm route through config.scoring_for(position).\n")

    espn_map, gsis_map, xwalk_pos = crosswalk()
    folds = [run_fold(config, y, espn_map, gsis_map, xwalk_pos) for y in FOLDS]

    for title, key in (("B - A   (the core strategy: re-score the room's own board)", "B-A"),
                       ("C - B   (the model's marginal contribution)", "C-B"),
                       ("C2 - B  (opportunity with no market anchor)", "C2-B")):
        print("=" * 96)
        print(title)
        print("=" * 96)
        print(f"  {'band':<14} " + "".join(f"{f['year']:>22}" for f in folds) + f"{'signs':>10}")
        for band in BANDS:
            cells, signs = [], []
            for f in folds:
                mean, lo, hi = f["bands"][band][key]
                cells.append(f"{mean:+.3f} [{lo:+.3f},{hi:+.3f}]".rjust(22))
                signs.append("+" if mean > 0 else "-" if mean < 0 else "0")
            agree = "ALL +" if all(s == "+" for s in signs) else \
                    "ALL -" if all(s == "-" for s in signs) else "mixed"
            print(f"  {band:<14} " + "".join(cells) + f"{agree:>10}")
        print()

    print("=" * 96)
    print("RAW ACCURACY BY ARM (within-position pairwise, ADP band by ESPN standard rank)")
    print("=" * 96)
    names = list(folds[0]["bands"]["rounds 3-10"]["arms"])
    header = f"  {'band':<14}{'fold':>6}{'n':>6}{'pairs':>8}  "
    print(header + "".join(f"{n[:20]:>22}" for n in names))
    for band in BANDS:
        for f in folds:
            r = f["bands"][band]
            pairs = r["arms"][names[0]]["pairs"]
            print(f"  {band:<14}{f['year']:>6}{r['n']:>6}{pairs:>8}  "
                  + "".join(f"{r['arms'][n]['acc']:>22.3f}" for n in names))
    print("=" * 96)
    print("TASK 1 -- B - A DECOMPOSED BY POSITION, rounds 3-10")
    print("=" * 96)
    print("  Under corrected B only WR and TE move. RB/QB/K/DEF keep A's ordering by")
    print("  construction, so their B - A must be EXACTLY 0.000 -- a pre-registered check.")
    print()
    print(f"  {'pos':<5}{'fold':>6}{'n':>5}{'pairs':>7}{'A':>9}{'B':>9}{'B-A':>10}   verdict")
    violations = []
    for pos in ("WR", "TE", "RB", "QB", "K", "DEF"):
        for f in folds:
            r = f["bands"]["rounds 3-10"]["by_pos"][pos]
            note = ""
            if pos not in ("WR", "TE"):
                if r["pairs"] == 0:
                    note = "no pairs"
                elif r["B-A"] != 0.0:
                    note = "** HARNESS BUG **"
                    violations.append((pos, f["year"], r["B-A"]))
                else:
                    note = "identical to A, as constructed"
            print(f"  {pos:<5}{f['year']:>6}{r['n']:>5}{r['pairs']:>7}"
                  f"{r['A']:>9.3f}{r['B']:>9.3f}{r['B-A']:>+10.3f}   {note}")
        print()
    if violations:
        print(f"  !! {len(violations)} construction violation(s): {violations}")
        print("  !! B is not what it claims to be. This is the finding; the arm is invalid.")
    else:
        print("  All non-WR/TE positions returned exactly 0.000. B is what it claims to be.")

    print()
    print(f"  lambda for C = {C_LAMBDA} (pre-registered, not tuned)")
    print("  B is APPROXIMATE: ESPN serves ranks for a past season, not projected points, so B")
    print("  blends two ORDERINGS rather than re-scoring a projection.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(folds, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
