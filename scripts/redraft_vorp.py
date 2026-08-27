"""Addendum: give Audible a real VORP arm, and run S / V / E separately.

    uv run --extra nflverse python scripts/redraft_vorp.py

Read-only. Nothing enters the sort. Gate and mapping fixed in
docs/pre-registration-vorp-arm.md (6e8df1f), committed before this file existed.

LEAVE-ONE-YEAR-OUT IS THE WHOLE INTEGRITY OF THIS ARM. The ADP->points curve applied to
fold Y is fitted only on years != Y. A curve fitted on Y would be telling Audible what the
players it is about to draft actually scored, and the win would be fraudulent rather than
small. The assertion that the training set excludes the fold is in the code, not just here.
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
    FFC_POS,
    MEANINGFUL_MARGIN,
    ROUNDS,
    TEAMS,
    YEARS,
    espn_id_by_name,
    lineup_points,
    norm,
    unfilled_slots,
)

SMOOTH = 2  # centred 5-rank window (r-2 .. r+2). Pre-registered; not varied.


def season_table(year: int, league_id: int):
    """(position, positional ADP rank) -> actual points, for one real season."""
    from audible.adapters.ffc import FfcAdapter

    snap = FfcAdapter().snapshot(year)
    n2i = espn_id_by_name(year, league_id)
    actuals = json.loads(
        (REPO / "data" / "cache" / f"espn_actuals_{league_id}_{year}.json")
        .read_text(encoding="utf-8"))
    points = {str(k): float(v) for k, v in actuals.items()}

    rows, seen = [], collections.defaultdict(int)
    for p in sorted(snap.players, key=lambda x: x["adp"]):
        pos = FFC_POS.get(p["position"], p["position"])
        eid = n2i.get(norm(p["name"]))
        if eid is None:
            continue
        seen[pos] += 1
        rows.append({"eid": eid, "pos": pos, "rank": seen[pos],
                     "actual": points.get(eid, 0.0)})
    return rows


def fit_curve(tables: dict[int, list], train_years: list[int], fold: int):
    """Mean actual points at each positional rank over TRAINING years only, smoothed."""
    assert fold not in train_years, (
        f"LEAK: fold {fold} is inside its own training set {train_years}. "
        "The mapping would be telling Audible what these players scored."
    )
    raw: dict[str, dict[int, list[float]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for y in train_years:
        for r in tables[y]:
            raw[r["pos"]][r["rank"]].append(r["actual"])

    curve: dict[str, dict[int, float]] = {}
    for pos, by_rank in raw.items():
        means = {k: statistics.mean(v) for k, v in by_rank.items()}
        deepest = max(means)
        smoothed = {}
        for r in range(1, deepest + 1):
            window = [means[k] for k in range(r - SMOOTH, r + SMOOTH + 1) if k in means]
            if window:
                smoothed[r] = statistics.mean(window)
        # carry the last value forward so a deep rank is priced, not dropped
        last = smoothed[max(smoothed)] if smoothed else 0.0
        curve[pos] = {"_curve": smoothed, "_last": last, "_deepest": deepest}  # type: ignore
    return curve


def predict(curve, pos: str, rank: int) -> float:
    c = curve.get(pos)
    if not c:
        return 0.0
    return c["_curve"].get(rank, c["_last"])  # type: ignore[index]


def vorp_board(rows, curve, config):
    """Real VORP: ADP-implied POINTS -> replacement levels -> points over replacement."""
    from audible.models.player import PlayerProjection
    from audible.value.replacement import replacement_levels

    pred = {r["eid"]: predict(curve, r["pos"], r["rank"]) for r in rows
            if r["pos"] in config.positions}
    position = {r["eid"]: r["pos"] for r in rows if r["pos"] in config.positions}
    projs = [
        PlayerProjection(player_id=eid, name=eid, primary_position=position[eid],
                         eligible_positions=frozenset({position[eid]}), team=None,
                         points=pts, stats={})
        for eid, pts in pred.items()
    ]
    levels = replacement_levels(projs, config)
    vorp = {eid: pts - levels[position[eid]].points for eid, pts in pred.items()}
    return vorp, position, pred, {p: lv.points for p, lv in levels.items()}


def draft_with(value, position, available_pool, picks, replaced_team):
    """One redraft; `value` is the higher-is-better score Audible maximises."""
    taken: set[str] = set()
    real_roster, new_roster = [], []
    collisions = 0
    for pick in sorted(picks, key=lambda x: x["overall"]):
        pid = str(pick["player_id"])
        if pick["team_id"] == replaced_team:
            mine = [position[p] for p in new_roster if p in position]
            unfilled = unfilled_slots(mine)
            need = {q for slot in unfilled for q in ELIG[slot]}
            forced = (ROUNDS - len(mine)) <= len(unfilled)
            best, best_val = None, float("-inf")
            for cand in available_pool:
                if cand in taken:
                    continue
                pos = position.get(cand)
                if pos is None or (forced and pos not in need):
                    continue
                v = value.get(cand, float("-inf"))
                if v > best_val:
                    best, best_val = cand, v
            if best is None:
                remaining = [c for c in available_pool if c not in taken]
                if not remaining:
                    break
                best = max(remaining, key=lambda c: value.get(c, float("-inf")))
            new_roster.append(best)
            real_roster.append(pid)
            taken.add(best)
        else:
            if pid in taken:
                collisions += 1
                alt = [c for c in available_pool if c not in taken]
                pid = max(alt, key=lambda c: value.get(c, float("-inf"))) if alt else pid
            taken.add(pid)
    return real_roster, new_roster, collisions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    from audible.backtest.metrics import spearman
    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]
    lid = config.league_id
    tables = {y: season_table(y, lid) for y in YEARS}

    print("=" * 100)
    print("THE ADP -> POINTS MAPPING, LEAVE-ONE-YEAR-OUT")
    print("=" * 100)
    print("  Each fold's curve is fitted only on the OTHER four seasons. Held-out quality")
    print("  below is measured on the fold the curve never saw.\n")
    print(f"  {'fold':<6}{'pos':<5}{'held-out rho':>14}{'resid SD':>11}"
          f"{'rank1':>9}{'rank5':>9}{'rank12':>9}{'rank24':>9}   verdict")
    curves, fit_rows = {}, []
    for fold in YEARS:
        train = [y for y in YEARS if y != fold]
        curve = fit_curve(tables, train, fold)
        curves[fold] = curve
        for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
            held = [(predict(curve, pos, r["rank"]), r["actual"])
                    for r in tables[fold] if r["pos"] == pos]
            if len(held) < 5:
                continue
            rho = spearman([h[0] for h in held], [h[1] for h in held])
            resid = statistics.stdev([a - p for p, a in held]) if len(held) > 1 else 0.0
            verdict = "usable" if rho >= 0.35 else "WEAK -- noisy input"
            print(f"  {fold:<6}{pos:<5}{rho:>14.3f}{resid:>11.1f}"
                  + "".join(f"{predict(curve, pos, r):>9.0f}" for r in (1, 5, 12, 24))
                  + f"   {verdict}")
            fit_rows.append({"fold": fold, "pos": pos, "rho": rho, "resid": resid})
        print()

    print("=" * 100)
    print("ARM V (full VORP) vs E (Eric's actual picks)")
    print("=" * 100)
    print(f"  Gate: >= 4 of 5 seasons won by more than {MEANINGFUL_MARGIN:.0f} actual points.\n")
    print(f"  {'year':<6}{'Eric actual':>13}{'Audible V':>12}{'margin':>10}{'share':>8}"
          f"{'collisions':>12}   result")
    v_rows = []
    for fold in YEARS:
        rows = tables[fold]
        vorp, position, _pred, _lv = vorp_board(rows, curves[fold], config)
        picks = json.loads(
            (REPO / "data" / "cache" / f"espn_draft_{lid}_{fold}.json").read_text("utf-8"))
        actuals = json.loads(
            (REPO / "data" / "cache" / f"espn_actuals_{lid}_{fold}.json").read_text("utf-8"))
        points = {str(k): float(v) for k, v in actuals.items()}
        rp = REPO / "data" / "cache" / f"espn_ranks_{lid}_{fold}.json"
        if rp.exists():
            for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
                if row.get("position"):
                    position.setdefault(str(eid), row["position"])
        pool = list(vorp)
        real, new, coll = draft_with(vorp, position, pool, picks, ERIC_TEAM)
        e_pts = lineup_points(real, points, position)
        v_pts = lineup_points(new, points, position)
        margin = v_pts - e_pts
        share = margin / e_pts * 100 if e_pts else 0.0
        won = margin > MEANINGFUL_MARGIN
        v_rows.append({"year": fold, "eric": e_pts, "v": v_pts, "margin": margin,
                       "share": share, "won": won, "collisions": coll})
        print(f"  {fold:<6}{e_pts:>13.1f}{v_pts:>12.1f}{margin:>+10.1f}{share:>+7.1f}%"
              f"{coll:>12}   {'WIN' if won else ('win but < margin' if margin > 0 else 'loss')}")

    wins = sum(1 for r in v_rows if r["won"])
    print(f"\n  ARM V: {wins} of 5  ->  {'GATE CLEARED' if wins >= 4 else 'GATE NOT CLEARED'}")
    print(f"  mean margin {statistics.mean(r['margin'] for r in v_rows):+.1f} points "
          f"({statistics.mean(r['share'] for r in v_rows):+.1f}% of season total)")

    print()
    print("=" * 100)
    print("ARM V AGAINST EVERY MANAGER")
    print("=" * 100)
    print(f"  {'team':>5}" + "".join(f"{y:>10}" for y in YEARS) + f"{'record':>9}{'mean':>10}")
    all_rows = []
    for team in range(1, TEAMS + 1):
        margins = []
        for fold in YEARS:
            rows = tables[fold]
            vorp, position, _p, _l = vorp_board(rows, curves[fold], config)
            picks = json.loads(
                (REPO / "data" / "cache" / f"espn_draft_{lid}_{fold}.json").read_text("utf-8"))
            actuals = json.loads(
                (REPO / "data" / "cache" / f"espn_actuals_{lid}_{fold}.json").read_text("utf-8"))
            points = {str(k): float(v) for k, v in actuals.items()}
            rp = REPO / "data" / "cache" / f"espn_ranks_{lid}_{fold}.json"
            if rp.exists():
                for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
                    if row.get("position"):
                        position.setdefault(str(eid), row["position"])
            real, new, _c = draft_with(vorp, position, list(vorp), picks, team)
            m = lineup_points(new, points, position) - lineup_points(real, points, position)
            margins.append(m)
            all_rows.append({"team": team, "year": fold, "margin": m})
        w = sum(1 for m in margins if m > MEANINGFUL_MARGIN)
        tag = "  <- Eric" if team == ERIC_TEAM else ""
        print(f"  {team:>5}" + "".join(f"{m:>+10.1f}" for m in margins)
              + f"{w:>6}/5{statistics.mean(margins):>+10.1f}{tag}")
    overall = [r["margin"] for r in all_rows]
    print(f"\n  across all 40 manager-seasons: wins by >{MEANINGFUL_MARGIN:.0f} in "
          f"{sum(1 for m in overall if m > MEANINGFUL_MARGIN)}/40, "
          f"mean {statistics.mean(overall):+.1f}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"fit": fit_rows, "v": v_rows, "all": all_rows}, indent=2),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
