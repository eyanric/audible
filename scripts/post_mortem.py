"""Post-mortem: why the arms failed. Descriptive only -- no new arm, no gate, no edge claim.

    uv run --extra nflverse python scripts/post_mortem.py

Five pre-registered gates have failed on five fixed folds. A sixth test would not be
independent, so none is run here. This asks the question none of the five asked: what do the
losing years have in common, and what did Eric do that no arm reproduces.

Everything is computed from ONE reconstruction of each fold, so the four sections reconcile
with each other -- the quarterback share in Task 3 is the same arithmetic as the slot
decomposition, not a second estimate of it.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import json
import random
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from monte_carlo_draft import (  # noqa: E402
    N_PRIMARY,
    SEED,
    Pool,
    build_profiles,
    mc_draft,
)
from redraft import (  # noqa: E402
    ELIG,
    ERIC_TEAM,
    FFC_POS,
    SLOTS,
    YEARS,
    espn_id_by_name,
    norm,
    run_year,
)
from redraft_vorp import (  # noqa: E402
    draft_with,
    fit_curve,
    predict,
    season_table,
    vorp_board,
)

WIN_YEARS, LOSS_YEARS = (2023, 2024), (2021, 2022, 2025)


def fold_data(fold: int, config):
    """One reconstruction per fold: the board, the expectations, and every arm's roster."""
    from audible.adapters.ffc import FfcAdapter

    lid = config.league_id
    tables = {y: season_table(y, lid) for y in YEARS}
    curve = fit_curve(tables, [y for y in YEARS if y != fold], fold)
    vorp, position, _pred, _lv = vorp_board(tables[fold], curve, config)

    rp = REPO / "data" / "cache" / f"espn_ranks_{lid}_{fold}.json"
    if rp.exists():
        for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
            if row.get("position"):
                position.setdefault(str(eid), row["position"])

    picks = json.loads(
        (REPO / "data" / "cache" / f"espn_draft_{lid}_{fold}.json").read_text("utf-8"))
    points = {str(k): float(v) for k, v in json.loads(
        (REPO / "data" / "cache" / f"espn_actuals_{lid}_{fold}.json").read_text("utf-8")).items()}

    # name + ADP + expectation for every player the consensus board carries
    snap = FfcAdapter().snapshot(fold)
    n2i = espn_id_by_name(fold, lid)
    meta, seen = {}, collections.defaultdict(int)
    for p in sorted(snap.players, key=lambda x: x["adp"]):
        pos = FFC_POS.get(p["position"], p["position"])
        eid = n2i.get(norm(p["name"]))
        if eid is None:
            continue
        seen[pos] += 1
        meta[eid] = {"name": p["name"], "pos": pos, "adp": p["adp"], "rank": seen[pos],
                     "expected": predict(curve, pos, seen[pos]),
                     "actual": points.get(eid, 0.0)}

    # overall consensus order, for measuring how far past the board a pick reached
    board_order = {e: i + 1 for i, e in enumerate(
        sorted(meta, key=lambda e: meta[e]["adp"]))}

    s = run_year(fold, config, ERIC_TEAM)
    _r, v_roster, _c = draft_with(vorp, position, list(vorp), picks, ERIC_TEAM)
    profiles = build_profiles(lid, [y for y in YEARS if y != fold], fold)
    _r2, mc_roster = mc_draft(picks, Pool(vorp, position), profiles, ERIC_TEAM,
                              N_PRIMARY, random.Random(SEED + fold))

    return {"fold": fold, "picks": picks, "points": points, "position": position,
            "meta": meta, "board_order": board_order, "eric": s["real_roster"],
            "S": s["audible"], "S_roster": s["new_roster"], "V_roster": v_roster,
            "MC_roster": mc_roster}


def reach_of(d, eid: str, taken: set[str]) -> int | None:
    """How many better-ADP players were still on the board when he was taken."""
    order = d["board_order"]
    if eid not in order:
        return None
    return sum(1 for q, o in order.items() if o < order[eid] and q not in taken)


def slot_delta(roster_a, roster_b, points, position) -> collections.Counter:
    """Starting-lineup points of A minus B, per slot."""
    out = collections.Counter()
    for tag, roster in (("a", roster_a), ("b", roster_b)):
        order = sorted(range(len(SLOTS)), key=lambda i: len(ELIG[SLOTS[i]]))
        pool = sorted(roster, key=lambda p: -points.get(p, 0.0))
        used = set()
        for i in order:
            hit = next((p for p in pool
                        if p not in used and position.get(p) in ELIG[SLOTS[i]]), None)
            if hit:
                used.add(hit)
                out[SLOTS[i]] += points.get(hit, 0.0) * (1 if tag == "a" else -1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    args = ap.parse_args()

    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]
    folds = {y: fold_data(y, config) for y in YEARS}

    # ---- TASK 1 -------------------------------------------------------------------------
    print("=" * 104)
    print("TASK 1 -- WHAT SEPARATES THE WON YEARS FROM THE LOST ONES")
    print("=" * 104)
    print("  All arms win 2023/2024 and lose 2021/2022/2025. If they fail together they")
    print("  share a cause, so the question is what is structurally different.\n")
    print(f"  {'year':<6}{'':<4}{'room reach SD':>15}{'room reach med':>16}"
          f"{'biggest early run':>19}{'Eric beat ADP':>16}")
    t1 = {}
    for y in YEARS:
        d = folds[y]
        taken, reaches, run_window = set(), [], []
        for pick in sorted(d["picks"], key=lambda x: x["overall"]):
            eid = str(pick["player_id"])
            r = reach_of(d, eid, taken)
            if r is not None:
                reaches.append(r)
            taken.add(eid)
            run_window.append(d["position"].get(eid, "?"))
        # biggest positional run inside any 8-pick window in rounds 1-6
        best_run = 0
        for i in range(0, min(48, len(run_window)) - 7):
            c = collections.Counter(run_window[i:i + 8])
            best_run = max(best_run, c.most_common(1)[0][1])
        beat = [e for e in d["eric"]
                if e in d["meta"] and d["meta"][e]["actual"] > d["meta"][e]["expected"]]
        gained = sum(d["meta"][e]["actual"] - d["meta"][e]["expected"] for e in beat)
        tag = "WON " if y in WIN_YEARS else "lost"
        t1[y] = {"sd": statistics.stdev(reaches), "med": statistics.median(reaches),
                 "run": best_run, "beat": len(beat), "gained": gained}
        print(f"  {y:<6}{tag:<4}{t1[y]['sd']:>15.1f}{t1[y]['med']:>16.0f}"
              f"{best_run:>15} of 8{len(beat):>8}/16{gained:>+8.0f}")
    w = [t1[y] for y in WIN_YEARS]
    lo = [t1[y] for y in LOSS_YEARS]
    print(f"\n  won  years: reach SD {statistics.mean(x['sd'] for x in w):>6.1f}   "
          f"Eric beat ADP on {statistics.mean(x['beat'] for x in w):.1f}/16 picks, "
          f"{statistics.mean(x['gained'] for x in w):+.0f} pts over expectation")
    print(f"  lost years: reach SD {statistics.mean(x['sd'] for x in lo):>6.1f}   "
          f"Eric beat ADP on {statistics.mean(x['beat'] for x in lo):.1f}/16 picks, "
          f"{statistics.mean(x['gained'] for x in lo):+.0f} pts over expectation")

    # ---- TASK 2 -------------------------------------------------------------------------
    print()
    print("=" * 104)
    print("TASK 2 -- WHAT ERIC DID THAT NO ARM REPRODUCES")
    print("=" * 104)
    for y in YEARS:
        d = folds[y]
        rows = []
        taken = set()
        for pick in sorted(d["picks"], key=lambda x: x["overall"]):
            eid = str(pick["player_id"])
            if int(pick["team_id"]) == ERIC_TEAM and eid in d["meta"]:
                m = d["meta"][eid]
                rows.append({"eid": eid, "rnd": pick["round"], "name": m["name"],
                             "pos": m["pos"], "over": m["actual"] - m["expected"],
                             "reach": reach_of(d, eid, taken)})
            taken.add(eid)
        rows.sort(key=lambda r: -r["over"])
        print(f"\n  {y}  Eric's four biggest beats of ADP expectation:")
        print(f"     {'rnd':>4}  {'player':<24}{'pos':<5}{'over exp':>10}{'reach':>7}   in arm?")
        for r in rows[:4]:
            arms = [n for n, k in (("S", "S_roster"), ("V", "V_roster"), ("MC", "MC_roster"))
                    if r["eid"] in d[k]]
            print(f"     {r['rnd']:>4}  {r['name']:<24}{r['pos']:<5}{r['over']:>+10.0f}"
                  f"{(r['reach'] if r['reach'] is not None else -1):>7}   "
                  f"{','.join(arms) if arms else 'NONE'}")

    print()
    print("  DO ERIC'S REACHES PAY? (a reach = more better-ADP men left than his median)")
    print(f"  {'year':<6}{'reach picks':>13}{'their mean over-exp':>22}"
          f"{'non-reach mean':>17}{'difference':>13}")
    pooled_r, pooled_n = [], []
    for y in YEARS:
        d = folds[y]
        taken, rr = set(), []
        for pick in sorted(d["picks"], key=lambda x: x["overall"]):
            eid = str(pick["player_id"])
            if int(pick["team_id"]) == ERIC_TEAM and eid in d["meta"]:
                rc = reach_of(d, eid, taken)
                if rc is not None:
                    rr.append((rc, d["meta"][eid]["actual"] - d["meta"][eid]["expected"]))
            taken.add(eid)
        if not rr:
            continue
        med = statistics.median([x[0] for x in rr])
        hi = [o for c, o in rr if c > med]
        lowr = [o for c, o in rr if c <= med]
        pooled_r += hi
        pooled_n += lowr
        print(f"  {y:<6}{len(hi):>13}{statistics.mean(hi):>+22.1f}"
              f"{statistics.mean(lowr):>+17.1f}"
              f"{statistics.mean(hi) - statistics.mean(lowr):>+13.1f}")
    print(f"  {'POOLED':<6}{len(pooled_r):>13}{statistics.mean(pooled_r):>+22.1f}"
          f"{statistics.mean(pooled_n):>+17.1f}"
          f"{statistics.mean(pooled_r) - statistics.mean(pooled_n):>+13.1f}")

    # ---- TASK 3 -------------------------------------------------------------------------
    print()
    print("=" * 104)
    print("TASK 3 -- THE QUARTERBACK PROBLEM, ISOLATED")
    print("=" * 104)
    print(f"  {'year':<6}{'Eric QB (round)':<34}{'arm V QB (round)':<34}")
    qb_tot = collections.Counter()
    tot_deficit = collections.Counter()
    for y in YEARS:
        d = folds[y]
        rnd_of = {str(p["player_id"]): p["round"] for p in d["picks"]}
        def qbs(roster, d=d, rnd_of=rnd_of):  # bind, do not close over the loop variable
            out = []
            for e in roster:
                if d["position"].get(e) == "QB":
                    nm = d["meta"].get(e, {}).get("name", e)
                    out.append(f"{nm} (R{rnd_of.get(e, '?')}, {d['points'].get(e, 0):.0f})")
            return "; ".join(out) or "-"
        print(f"  {y:<6}{qbs(d['eric'])[:33]:<34}{qbs(d['V_roster'])[:33]:<34}")
        for arm in ("S_roster", "V_roster", "MC_roster"):
            sd = slot_delta(d[arm], d["eric"], d["points"], d["position"])
            qb_tot[arm] += sd["QB"]
            tot_deficit[arm] += sum(sd.values())
    print(f"\n  {'arm':<6}{'total 5-fold deficit':>24}{'of which QB':>14}{'QB share':>11}")
    for arm, label in (("S_roster", "S"), ("V_roster", "V"), ("MC_roster", "MC")):
        t, q = tot_deficit[arm], qb_tot[arm]
        print(f"  {label:<6}{t:>+24.0f}{q:>+14.0f}"
              f"{(q / t * 100 if t else 0):>10.0f}%")

    # ---- TASK 4 -------------------------------------------------------------------------
    print()
    print("=" * 104)
    print("TASK 4 -- K AND D/ST AS A FIXED COST")
    print("=" * 104)
    kd = collections.Counter()
    for y in YEARS:
        d = folds[y]
        for arm in ("S_roster", "V_roster", "MC_roster"):
            sd = slot_delta(d[arm], d["eric"], d["points"], d["position"])
            kd[arm] += sd["K"] + sd["DEF"]
    print(f"  {'arm':<6}{'K + DEF, pooled 5 folds':>28}{'share of that arm deficit':>28}")
    for arm, label in (("S_roster", "S"), ("V_roster", "V"), ("MC_roster", "MC")):
        t = tot_deficit[arm]
        print(f"  {label:<6}{kd[arm]:>+28.0f}"
              f"{(kd[arm] / t * 100 if t else 0):>27.0f}%")

    print("\n  Descriptive counterfactual, NOT a new arm: what the best K and D/ST still")
    print("  available at Eric's last two picks were actually worth that season.")
    print(f"\n  {'year':<6}{'best K left @R15/16':>22}{'best DEF left @R15/16':>24}"
          f"{'vs what arm V got':>20}")
    for y in YEARS:
        d = folds[y]
        taken = set()
        late = None
        for pick in sorted(d["picks"], key=lambda x: x["overall"]):
            if int(pick["team_id"]) == ERIC_TEAM and pick["round"] == 15:
                late = set(taken)
            taken.add(str(pick["player_id"]))
        if late is None:
            continue
        best = {}
        for pos in ("K", "DEF"):
            cands = [e for e, m in d["meta"].items()
                     if m["pos"] == pos and e not in late]
            best[pos] = max((d["points"].get(e, 0.0) for e in cands), default=0.0)
        got = collections.Counter()
        for e in d["V_roster"]:
            p = d["position"].get(e)
            if p in ("K", "DEF"):
                got[p] = max(got[p], d["points"].get(e, 0.0))
        print(f"  {y:<6}{best['K']:>22.0f}{best['DEF']:>24.0f}"
              f"{(got['K'] + got['DEF']) - (best['K'] + best['DEF']):>+20.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
