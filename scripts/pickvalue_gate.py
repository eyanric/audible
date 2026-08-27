"""Tasks 2 and 3: run the pre-registered pick-value gate, and ablate the terms.

    uv run --extra nflverse python scripts/pickvalue_gate.py

The gate is fixed in docs/pre-registration-pick-value.md (e89128a), committed before this
file existed. It is not restated here in a form that could drift from it:

    d(Y,s) = points_objective(Y,s) - points_vorp(Y,s)   over 8 seats x 3 folds
    fold win iff mean(d) > stdev(d)/sqrt(8);  gate clears iff >= 2 of 3 folds win

THE PROJECTION IS HELD CONSTANT. Both arms score the same prior-season opportunity xFP
through this league's own rules. What differs between them is only the DECISION RULE --
VORP order against the objective -- which is the whole question. It also means both arms
inherit that projection's known weakness equally, so the comparison stays fair while the
absolute rosters are worse than a real draft's would be.
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
PROFILE_YEARS = (2021, 2022, 2023, 2024, 2025)
TEAMS, ROUNDS = 8, 16
ROOM_K, ROOM_DEF = 8, 8


def positions_by_espn_id():
    import polars as pl

    ids = pl.read_parquet(REPO / "data/cache/nflverse/ff_playerids.parquet")
    norm = {"PK": "K"}
    return {str(r["espn_id"]): norm.get(r["position"], r["position"])
            for r in ids.select(["espn_id", "position"]).iter_rows(named=True)
            if r["espn_id"] is not None and r["position"]}


def opportunity_points(config, prior_season: int, gsis_to_sleeper):
    """The shared projection: prior-season observed usage, scored by this league's rules."""
    from audible.adapters.nflverse import opportunity_frame
    from audible.draft.opportunity import modeled_xfp, season_opportunity

    opp = season_opportunity([prior_season])
    df = opportunity_frame([prior_season])
    pos_by_gsis = {}
    for r in df.select(["player_id", "position"]).iter_rows(named=True):
        if r["player_id"] and r["position"]:
            pos_by_gsis.setdefault(str(r["player_id"]), str(r["position"]))

    pts, pos = {}, {}
    for gsis, xfp in opp.items():
        pid = gsis_to_sleeper.get(str(gsis))
        p = pos_by_gsis.get(str(gsis))
        # ff_opportunity carries positions this league does not roster (SPEC, and any
        # future addition). A player the config has no slot for is not a draft decision.
        if pid is None or p is None or p not in config.positions:
            continue
        pts[pid] = modeled_xfp(xfp, config.scoring_for(p))
        pos[pid] = p
    return pts, pos


def vorp_order(points, position, config):
    """Baseline arm: the board's own ranking, from the same projection."""
    from audible.models.player import PlayerProjection
    from audible.value import compute_vorp

    projs = [
        PlayerProjection(player_id=pid, name=pid, primary_position=position[pid],
                         eligible_positions=frozenset({position[pid]}), team=None,
                         points=pts, stats={})
        for pid, pts in points.items() if position.get(pid)
    ]
    entries, levels = compute_vorp(projs, config)
    return ({e.projection.player_id: i + 1.0 for i, e in enumerate(entries)},
            {p: lv.points for p, lv in levels.items()})


def wire_after_room_draft(points, position, espn_rank):
    """Best player left at each position after a REALISTIC 128 picks (room behaviour)."""
    by_pos = {}
    for pid, p in position.items():
        by_pos.setdefault(p, []).append(pid)
    for g in by_pos.values():
        g.sort(key=lambda x: -points.get(x, 0.0))

    gone = set()
    for pos, want in (("K", ROOM_K), ("DEF", ROOM_DEF)):
        gone.update(by_pos.get(pos, [])[:want])
    for pid in sorted(espn_rank, key=lambda x: espn_rank[x]):
        if len(gone) >= TEAMS * ROUNDS:
            break
        if pid in position:
            gone.add(pid)

    wire = {}
    for pos, group in by_pos.items():
        left = [p for p in group if p not in gone]
        wire[pos] = points.get(left[0], 0.0) if left else 0.0
    return wire


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--offense-only", action="store_true",
                    help="DIAGNOSTIC, not the gate: restrict the lineup to the slots the "
                         "projection can actually fill, since ff_opportunity is offense-only")
    args = ap.parse_args()

    from backtest_arms import crosswalk
    from replay_seats import ELIG, best_lineup_points, snake_slot
    from replay_seats import SLOTS as FULL_SLOTS

    # ff_opportunity is OFFENSE-ONLY: no kicker and no team defence has an expected-component
    # row, so a board built from it can never fill those two starting slots. Under the
    # pre-registered gate that is left as-is (both arms lose the same two slots). The
    # diagnostic drops them so the remaining seven are scored coherently.
    SLOTS = (tuple(s for s in FULL_SLOTS if s not in ("DEF", "K"))
             if args.offense_only else FULL_SLOTS)

    from audible.adapters.sleeper import SleeperAdapter
    from audible.backtest.arms import assert_one_scoring, espn_arms
    from audible.backtest.data import season_actuals
    from audible.config.loader import load_all_leagues
    from audible.draft.live import next_pick_after
    from audible.draft.pickvalue import PickValue, load_opponent_profile

    config = load_all_leagues()[args.league]
    assert_one_scoring(config)
    espn_map, gsis_map, _ = crosswalk()
    profile = load_opponent_profile(REPO / "data" / "cache", config.league_id,
                                    PROFILE_YEARS, positions_by_espn_id())

    def draft(my_seat, my_rule, opp_rank, points, position, wire, pv=None):
        """One 128-pick snake. Opponents on ESPN order; my seat on `my_rule` or `pv`."""
        rosters = {s: [] for s in range(1, TEAMS + 1)}
        taken = set()
        for pick_no in range(1, TEAMS * ROUNDS + 1):
            seat = snake_slot(pick_no)
            mine = rosters[seat]
            rnd = (pick_no - 1) // TEAMS + 1
            avail = [p for p in position if p not in taken]

            # identical need handling for every seat and every arm, so the only thing that
            # differs is the ordering itself
            pool = list(mine)
            order = sorted(range(len(SLOTS)), key=lambda i: len(ELIG[SLOTS[i]]))
            unfilled = []
            tmp = [position[p] for p in pool if p in position]
            for i in order:
                hit = next((j for j, q in enumerate(tmp) if q in ELIG[SLOTS[i]]), None)
                if hit is None:
                    unfilled.append(SLOTS[i])
                else:
                    tmp.pop(hit)
            need = {q for slot in unfilled for q in ELIG[slot]}
            forced = (ROUNDS - len(mine)) <= len(unfilled)
            legal = [p for p in avail if not forced or position.get(p) in need] or avail
            if not legal:
                break

            if seat == my_seat and pv is not None:
                nxt = next_pick_after(my_seat, TEAMS, ROUNDS, pick_no)
                sc = pv.score(legal, position, points,
                              current_pick=pick_no, my_next_pick=nxt, rnd=rnd)
                best = max(legal, key=lambda p: sc.get(p, float("-inf")))
            else:
                rank = my_rule if seat == my_seat else opp_rank
                best = min(legal, key=lambda p: rank.get(p, float("inf")))
            taken.add(best)
            rosters[seat].append(best)
        return rosters

    print("=" * 100)
    print("PICK-VALUE GATE -- pre-registered in docs/pre-registration-pick-value.md (e89128a)")
    print("=" * 100)
    if args.offense_only:
        print("  *** DIAGNOSTIC RUN, NOT THE GATE: lineup restricted to the seven offensive")
        print("  *** slots, because the projection cannot fill DEF or K. ***")
        print()
    print("  projection held constant across arms: prior-season opportunity xFP,")
    print("  scored through config.scoring_for(position). Opponents draft ESPN standard.\n")

    results = {m: [] for m in ("delay", "wire", "both")}
    for year in FOLDS:
        ranks = json.loads(
            (REPO / "data/cache" / f"espn_ranks_{config.league_id}_{year}.json")
            .read_text(encoding="utf-8"))
        a, _ = espn_arms(ranks, espn_map)
        with SleeperAdapter() as ad:
            actuals = season_actuals(ad, year, config)

        points, position = opportunity_points(config, year - 1, gsis_map)
        # everyone must be draftable by both arms: restrict to the shared universe
        universe = {p for p in points if p in position}
        points = {p: v for p, v in points.items() if p in universe}
        position = {p: v for p, v in position.items() if p in universe}
        opp_rank = {p: r for p, r in a.rank_by_id.items() if p in universe}
        # anyone ESPN never ranked sits behind everyone it did
        far = len(opp_rank) + 1
        for p in universe:
            opp_rank.setdefault(p, float(far))

        vorp_rank, _levels = vorp_order(points, position, config)
        wire = wire_after_room_draft(points, position, opp_rank)
        label = {p: (actuals[p].points if p in actuals else 0.0) for p in universe}

        for mode in ("delay", "wire", "both"):
            pv = PickValue(wire_replacement=wire, profile=profile, teams=TEAMS,
                           mode=mode, enabled=True)
            diffs, rows = [], []
            for seat in range(1, TEAMS + 1):
                base = best_lineup_points(
                    draft(seat, vorp_rank, opp_rank, points, position, wire)[seat],
                    label, position, SLOTS)
                obj = best_lineup_points(
                    draft(seat, vorp_rank, opp_rank, points, position, wire, pv)[seat],
                    label, position, SLOTS)
                diffs.append(obj - base)
                rows.append({"seat": seat, "vorp": base, "obj": obj, "d": obj - base})
            delta = statistics.mean(diffs)
            se = statistics.stdev(diffs) / (len(diffs) ** 0.5)
            results[mode].append({"year": year, "delta": delta, "se": se,
                                  "win": delta > se, "rows": rows})

    for mode in ("delay", "wire", "both"):
        print("=" * 100)
        print(f"ABLATION ARM: {mode.upper()}")
        print("=" * 100)
        for f in results[mode]:
            ds = "".join(f"{r['d']:>+9.1f}" for r in f["rows"])
            print(f"  {f['year']}  per seat:{ds}")
            print(f"        Delta={f['delta']:+8.2f}  SE={f['se']:7.2f}  "
                  f"{'WIN' if f['win'] else 'no'}   (seat 8: {f['rows'][7]['d']:+.1f})")
        wins = sum(1 for f in results[mode] if f["win"])
        pooled = statistics.mean([r["d"] for f in results[mode] for r in f["rows"]])
        seat8 = statistics.mean([f["rows"][7]["d"] for f in results[mode]])
        print(f"\n  folds won: {wins}/3  ->  "
              f"{'GATE CLEARED' if wins >= 2 else 'GATE NOT CLEARED'}"
              f"   pooled {pooled:+.2f}   seat 8 mean {seat8:+.2f}\n")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
