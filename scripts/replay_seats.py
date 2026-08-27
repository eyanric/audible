"""Task 2: replay each fold's draft from all eight seats, arm A against arm B.

    uv run --extra nflverse python scripts/replay_seats.py

Read-only. Nothing enters the sort.

THE PRE-REGISTERED GATE (fixed in PR #36 before these numbers existed):

    Seven opponents always draft off arm A. The eighth drafts off A in one run and off B in
    another, everything else identical. Score each roster on ACTUAL DDAFFL points.

        d(Y, s)  = points_B(Y, s) - points_A(Y, s)      8 seats x 3 folds = 24 observations
        Delta(Y) = mean over seats of d(Y, s)
        SE(Y)    = stdev over seats of d(Y, s) / sqrt(8)
        fold win = Delta(Y) > SE(Y)
        SUCCESS  = at least 2 of 3 folds are wins

The comparison is paired within (fold, seat, opponent set), so seat luck is differenced out
and the residual spread across seats is the scale for "bigger than noise". Seat 8 is reported
separately from the all-seat average so strategy and seat luck stay distinguishable.
"""

from __future__ import annotations

import argparse
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

FOLDS = (2023, 2024, 2025)
TEAMS, ROUNDS = 8, 16
SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K")
ELIG = {"QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
        "FLEX": {"RB", "WR", "TE"}, "DEF": {"DEF"}, "K": {"K"}}


def snake_slot(pick_no: int) -> int:
    rnd, idx = divmod(pick_no - 1, TEAMS)
    return idx + 1 if rnd % 2 == 0 else TEAMS - idx


def _fill(roster_pos: list[str]) -> list[str]:
    """Which starting slots this set of positions still cannot fill (tightest slot first)."""
    order = sorted(range(len(SLOTS)), key=lambda i: len(ELIG[SLOTS[i]]))
    pool, unfilled = list(roster_pos), []
    for i in order:
        hit = next((j for j, p in enumerate(pool) if p in ELIG[SLOTS[i]]), None)
        if hit is None:
            unfilled.append(SLOTS[i])
        else:
            pool.pop(hit)
    return unfilled


def best_lineup_points(roster: list[str], label, position) -> float:
    """The best legal starting nine by SEASON actuals. Bench scores nothing.

    Season totals rather than a week-by-week optimum: it is deterministic, identical for both
    arms, and does not require weekly actuals. It therefore ignores bye weeks and in-season
    streaming, which is a real limitation and is reported as one -- a roster that cannot field
    a legal lineup in week 7 is scored here as though it could.
    """
    order = sorted(range(len(SLOTS)), key=lambda i: len(ELIG[SLOTS[i]]))
    pool = sorted(roster, key=lambda p: -label.get(p, 0.0))
    used, total = set(), 0.0
    for i in order:
        hit = next((p for p in pool
                    if p not in used and position.get(p) in ELIG[SLOTS[i]]), None)
        if hit is not None:
            used.add(hit)
            total += label.get(hit, 0.0)
    return total


def run_draft(ranks_by_seat: dict[int, dict[str, float]], position) -> dict[int, list[str]]:
    """One full 128-pick snake. The ONLY thing that differs between runs is a seat's ranking.

    Policy is identical for every seat and every arm: take the best available by your own
    ranking, unless the picks you have left are down to the starting slots you still cannot
    fill -- then take a filler. That is the same slack arithmetic the production recommender
    uses, and being arm-agnostic is what makes the A/B difference attributable to the ordering.
    """
    rosters: dict[int, list[str]] = {s: [] for s in range(1, TEAMS + 1)}
    taken: set[str] = set()
    for pick_no in range(1, TEAMS * ROUNDS + 1):
        seat = snake_slot(pick_no)
        rank = ranks_by_seat[seat]
        mine = rosters[seat]
        unfilled = _fill([position[p] for p in mine if p in position])
        picks_left = ROUNDS - len(mine)

        need = {p for slot in unfilled for p in ELIG[slot]}
        forced = picks_left <= len(unfilled)
        best, best_rank = None, float("inf")
        for pid, r in rank.items():
            if pid in taken or r >= best_rank:
                continue
            if forced and position.get(pid) not in need:
                continue
            best, best_rank = pid, r
        if best is None:  # nothing legal left under the constraint; fall back to best available
            for pid, r in rank.items():
                if pid not in taken and r < best_rank:
                    best, best_rank = pid, r
        if best is None:
            break
        taken.add(best)
        rosters[seat].append(best)
    return rosters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    from backtest_arms import crosswalk

    from audible.adapters.sleeper import SleeperAdapter
    from audible.backtest.arms import assert_one_scoring, espn_arms
    from audible.backtest.data import season_actuals
    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]
    assert_one_scoring(config)
    espn_map, _gsis_map, xwalk_pos = crosswalk()

    print("=" * 96)
    print("TASK 2 -- DRAFT REPLAY, ALL EIGHT SEATS, ARM A vs ARM B")
    print("=" * 96)
    print("  Gate pre-registered in PR #36: B wins a fold iff Delta > SE; success = 2 of 3.\n")

    results, per_fold = {}, []
    for year in FOLDS:
        ranks = json.loads(
            (REPO / "data" / "cache" / f"espn_ranks_{config.league_id}_{year}.json")
            .read_text(encoding="utf-8"))
        with SleeperAdapter() as ad:
            actuals = season_actuals(ad, year, config)

        a, b = espn_arms(ranks, espn_map)
        position = {pid: ps.primary for pid, ps in actuals.items()}
        for pid, p in xwalk_pos.items():
            position.setdefault(pid, p)
        # A drafted player who never played scores zero -- he is a bust, not an absence.
        label = {pid: (actuals[pid].points if pid in actuals else 0.0) for pid in a.rank_by_id}

        draftable = [p for p in a.rank_by_id if p in position]
        a_r = {p: a.rank_by_id[p] for p in draftable}
        b_r = {p: b.rank_by_id[p] for p in draftable if p in b.rank_by_id}

        diffs, rows = [], []
        for seat in range(1, TEAMS + 1):
            all_a = {s: a_r for s in range(1, TEAMS + 1)}
            pts_a = best_lineup_points(run_draft(all_a, position)[seat], label, position)
            with_b = dict(all_a)
            with_b[seat] = b_r
            pts_b = best_lineup_points(run_draft(with_b, position)[seat], label, position)
            diffs.append(pts_b - pts_a)
            rows.append({"seat": seat, "A": pts_a, "B": pts_b, "d": pts_b - pts_a})

        delta = statistics.mean(diffs)
        se = statistics.stdev(diffs) / (len(diffs) ** 0.5) if len(diffs) > 1 else 0.0
        win = delta > se
        per_fold.append({"year": year, "delta": delta, "se": se, "win": win, "rows": rows})
        results[year] = rows

        print(f"  {year}   seat:" + "".join(f"{r['seat']:>9}" for r in rows))
        print("         A pts:" + "".join(f"{r['A']:>9.1f}" for r in rows))
        print("         B pts:" + "".join(f"{r['B']:>9.1f}" for r in rows))
        print("         B - A:" + "".join(f"{r['d']:>+9.1f}" for r in rows))
        print(f"         Delta={delta:+.2f}  SE={se:.2f}  ->  "
              f"{'WIN for B' if win else 'not a win'}   (seat 8: {rows[7]['d']:+.1f})\n")

    wins = sum(1 for f in per_fold if f["win"])
    pooled = statistics.mean([r["d"] for f in per_fold for r in f["rows"]])
    seat8 = [f["rows"][7]["d"] for f in per_fold]

    print("=" * 96)
    print("VERDICT AGAINST THE PRE-REGISTERED GATE")
    print("=" * 96)
    for f in per_fold:
        print(f"  {f['year']}: Delta={f['delta']:+8.2f}  SE={f['se']:7.2f}  "
              f"{'WIN' if f['win'] else 'no'}")
    print(f"\n  folds won by B: {wins} of 3   ->  "
          f"{'GATE CLEARED' if wins >= 2 else 'GATE NOT CLEARED'}")
    print(f"  pooled mean over all 24 observations: {pooled:+.2f} points")
    seat8_txt = ", ".join(f"{x:+.1f}" for x in seat8)
    print(f"  seat 8 specifically: [{seat8_txt}]  mean {statistics.mean(seat8):+.2f}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(per_fold, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
