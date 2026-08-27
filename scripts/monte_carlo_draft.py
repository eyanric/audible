"""Attempt 5: Monte Carlo roster search over the opponent model.

    uv run --extra nflverse python scripts/monte_carlo_draft.py

Gate, parameters and the pre-committed conclusion are fixed in
docs/pre-registration-monte-carlo.md (3d9c9d5), committed before this file existed.

DIFFERENT IN KIND. Every earlier arm ranked players and took the top one. This one takes
each of the top W candidates provisionally, plays the rest of the draft out N times against
the room's own measured behaviour, and keeps whichever candidate leaves the best roster on
average. It optimises the scored quantity directly, and it is the only arm in which the
opponent model is a DECISION INPUT rather than a description of what happened.

TWO LEAKAGE GUARDS, both asserted in code rather than promised here:
  * the ADP->points curve for fold Y is fitted only on years != Y (fit_curve)
  * the opponent profiles for fold Y are built only from years != Y (build_profiles)
A profile fitted on Y would encode how the room actually behaved in the season being
predicted, which is the same class of error as fitting the curve on its own fold.
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

from redraft import (  # noqa: E402
    ELIG,
    ERIC_TEAM,
    MEANINGFUL_MARGIN,
    ROUNDS,
    TEAMS,
    YEARS,
    lineup_points,
    unfilled_slots,
)
from redraft_vorp import fit_curve, season_table, vorp_board  # noqa: E402

# ---- fixed before running (3d9c9d5); not tuned afterwards --------------------------------
N_PRIMARY = 500
N_ROOMWIDE = 200
WIDTH = 12
MARGIN_GATE = 130.0
BOOTSTRAP_N = 10_000
SEED = 20260827
NORM_POS = {"PK": "K"}


def build_profiles(league_id: int, train_years: list[int], fold: int):
    """Per-team positional tendency by round, from TRAINING years only.

    The assertion below is the whole guard. A profile built on the fold would tell the
    simulator what the room actually did in the season it is trying to predict -- the same
    class of leak as fitting the ADP curve on its own fold, and just as invisible in output.
    """
    assert fold not in train_years, (
        f"LEAK: opponent profiles for fold {fold} would be built from {train_years}, "
        "which contains the fold itself."
    )
    import polars as pl

    ids = pl.read_parquet(REPO / "data/cache/nflverse/ff_playerids.parquet")
    pos_by_espn = {str(r["espn_id"]): NORM_POS.get(r["position"], r["position"])
                   for r in ids.select(["espn_id", "position"]).iter_rows(named=True)
                   if r["espn_id"] is not None and r["position"]}

    counts: dict[int, dict[int, collections.Counter]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter))
    for yr in train_years:
        p = REPO / "data" / "cache" / f"espn_draft_{league_id}_{yr}.json"
        if not p.exists():
            continue
        for pick in json.loads(p.read_text(encoding="utf-8")):
            pos = pos_by_espn.get(str(pick["player_id"]), "DEF")
            counts[pick["team_id"]][int(pick["round"])][pos] += 1

    profiles: dict[int, dict[int, list]] = {}
    for team, by_round in counts.items():
        rounds = {}
        for rnd, c in by_round.items():
            tot = sum(c.values())
            rounds[rnd] = [(p, n / tot) for p, n in c.most_common()]
        profiles[team] = rounds
    return profiles


def sample_position(profiles, team: int, rnd: int, rng: random.Random) -> str | None:
    rounds = profiles.get(team) or {}
    row = rounds.get(rnd)
    if not row:
        row = rounds.get(max(rounds)) if rounds else None
    if not row:
        return None
    x = rng.random()
    acc = 0.0
    for pos, prob in row:
        acc += prob
        if x <= acc:
            return pos
    return row[-1][0]


class Pool:
    """Available players, kept sorted per position so a pick is a pointer bump."""

    def __init__(self, value: dict[str, float], position: dict[str, str]):
        self.by_pos: dict[str, list[str]] = {}
        for pid, pos in position.items():
            if pid in value:
                self.by_pos.setdefault(pos, []).append(pid)
        for group in self.by_pos.values():
            group.sort(key=lambda p: -value[p])
        self.value = value
        self.position = position

    def snapshot_ptrs(self) -> dict[str, int]:
        return dict.fromkeys(self.by_pos, 0)

    def take_best(self, ptrs, taken, pos: str, reach: int = 0) -> str | None:
        group = self.by_pos.get(pos)
        if not group:
            return None
        i = ptrs.get(pos, 0)
        while i < len(group) and group[i] in taken:
            i += 1
        ptrs[pos] = i
        if i >= len(group):
            return None
        j = min(i + max(0, reach), len(group) - 1)
        while j > i and group[j] in taken:
            j -= 1
        return group[j] if group[j] not in taken else group[i]

    def best_overall(self, taken, allowed: set[str] | None = None) -> str | None:
        best, bv = None, float("-inf")
        for pos, group in self.by_pos.items():
            if allowed is not None and pos not in allowed:
                continue
            for pid in group:
                if pid not in taken:
                    if self.value[pid] > bv:
                        best, bv = pid, self.value[pid]
                    break
        return best


def simulate_completion(pool, picks_after, my_seat, my_roster, taken, profiles,
                        rng, reach_scale: int = 6) -> list[str]:
    """Play the rest of the draft out once. Opponents follow their own profile."""
    taken = set(taken)
    mine = list(my_roster)
    ptrs = pool.snapshot_ptrs()
    for pick in picks_after:
        rnd = int(pick["round"])
        seat = int(pick["team_id"])
        if seat == my_seat:
            positions = [pool.position[p] for p in mine if p in pool.position]
            unf = unfilled_slots(positions)
            need = {q for slot in unf for q in ELIG[slot]}
            forced = (ROUNDS - len(mine)) <= len(unf)
            chosen = pool.best_overall(taken, need if forced else None) \
                or pool.best_overall(taken)
            if chosen is None:
                break
            mine.append(chosen)
            taken.add(chosen)
        else:
            pos = sample_position(profiles, seat, rnd, rng)
            reach = rng.randrange(0, reach_scale) if reach_scale else 0
            chosen = pool.take_best(ptrs, taken, pos, reach) if pos else None
            if chosen is None:
                chosen = pool.best_overall(taken)
            if chosen is None:
                break
            taken.add(chosen)
    return mine


def mc_draft(picks, pool, profiles, my_seat, n_sims: int, rng: random.Random):
    """Eric's seat, chosen by Monte Carlo search; everyone else keeps their real pick."""
    taken: set[str] = set()
    mine: list[str] = []
    real: list[str] = []
    ordered = sorted(picks, key=lambda x: x["overall"])
    for idx, pick in enumerate(ordered):
        pid = str(pick["player_id"])
        if int(pick["team_id"]) != my_seat:
            if pid in taken:
                alt = pool.best_overall(taken)
                pid = alt if alt else pid
            taken.add(pid)
            continue

        real.append(pid)
        positions = [pool.position[p] for p in mine if p in pool.position]
        unf = unfilled_slots(positions)
        need = {q for slot in unf for q in ELIG[slot]}
        forced = (ROUNDS - len(mine)) <= len(unf)

        cands: list[str] = []
        for pos, group in pool.by_pos.items():
            if forced and pos not in need:
                continue
            for cand in group:
                if cand not in taken:
                    cands.append(cand)
                    break
        cands.sort(key=lambda p: -pool.value[p])
        cands = cands[:WIDTH] or [pool.best_overall(taken)]
        if cands[0] is None:
            break

        rest = ordered[idx + 1:]
        best, best_mean = None, float("-inf")
        for cand in cands:
            tot = 0.0
            for _ in range(n_sims):
                roster = simulate_completion(
                    pool, rest, my_seat, [*mine, cand], taken | {cand}, profiles, rng)
                tot += sum(pool.value.get(p, 0.0) for p in roster)
            mean = tot / n_sims
            if mean > best_mean:
                best, best_mean = cand, mean
        mine.append(best)
        taken.add(best)
    return real, mine


def bootstrap_p(margins: list[float]) -> float:
    """One-sided p that the mean margin is <= 0, by resampling the folds."""
    rng = random.Random(SEED)
    n = len(margins)
    hits = 0
    for _ in range(BOOTSTRAP_N):
        s = [margins[rng.randrange(n)] for _ in range(n)]
        if statistics.mean(s) <= 0:
            hits += 1
    return hits / BOOTSTRAP_N


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--room-wide", action="store_true")
    ap.add_argument("--ddaffl", action="store_true",
                    help="HYPOTHETICAL: score under DDAFFL half-PPR instead of standard")
    args = ap.parse_args()

    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]
    lid = config.league_id
    tables = {y: season_table(y, lid) for y in YEARS}

    label = "DDAFFL half-PPR (HYPOTHETICAL)" if args.ddaffl else "standard (as played)"
    print("=" * 104)
    print(f"ATTEMPT 5 -- MONTE CARLO ROSTER SEARCH   [scoring: {label}]")
    print("=" * 104)
    print(f"  Gate (3d9c9d5): >=4 of 5 folds AND mean margin > +{MARGIN_GATE:.0f}.")
    print("  Bonferroni-adjusted alpha for attempt 5 of 5: 0.010")
    print(f"  N={N_PRIMARY} sims, W={WIDTH} candidates, fixed before running.\n")

    ddaffl_points = {}
    if args.ddaffl:
        from backtest_arms import crosswalk

        from audible.adapters.sleeper import SleeperAdapter
        from audible.backtest.data import season_actuals
        espn_map, _g, _p = crosswalk()
        s2e = {v: k for k, v in espn_map.items()}
        with SleeperAdapter() as ad:
            for yr in YEARS:
                ddaffl_points[yr] = {
                    s2e[sid]: ps.points
                    for sid, ps in season_actuals(ad, yr, config).items() if sid in s2e
                }

    margins, eric_tot, mc_tot = [], [], []
    print(f"  {'year':<6}{'Eric':>10}{'MonteCarlo':>13}{'margin':>10}{'share':>8}   result")
    for fold in YEARS:
        curve = fit_curve(tables, [y for y in YEARS if y != fold], fold)
        vorp, position, _pred, _lv = vorp_board(tables[fold], curve, config)
        rp = REPO / "data" / "cache" / f"espn_ranks_{lid}_{fold}.json"
        if rp.exists():
            for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
                if row.get("position"):
                    position.setdefault(str(eid), row["position"])
        picks = json.loads(
            (REPO / "data" / "cache" / f"espn_draft_{lid}_{fold}.json").read_text("utf-8"))
        profiles = build_profiles(lid, [y for y in YEARS if y != fold], fold)

        pts = ddaffl_points[fold] if args.ddaffl else {
            str(k): float(v) for k, v in json.loads(
                (REPO / "data" / "cache" / f"espn_actuals_{lid}_{fold}.json")
                .read_text("utf-8")).items()}

        pool = Pool(vorp, position)
        rng = random.Random(SEED + fold)
        real, mine = mc_draft(picks, pool, profiles, ERIC_TEAM, N_PRIMARY, rng)
        e = lineup_points(real, pts, position)
        m = lineup_points(mine, pts, position)
        margins.append(m - e)
        eric_tot.append(e)
        mc_tot.append(m)
        share = (m - e) / e * 100 if e else 0.0
        print(f"  {fold:<6}{e:>10.1f}{m:>13.1f}{m - e:>+10.1f}{share:>+7.1f}%   "
              f"{'WIN' if m - e > MEANINGFUL_MARGIN else 'loss'}")

    wins = sum(1 for x in margins if x > MEANINGFUL_MARGIN)
    mean = statistics.mean(margins)
    p = bootstrap_p(margins)
    cond1, cond2 = wins >= 4, mean > MARGIN_GATE
    print(f"\n  folds won (>{MEANINGFUL_MARGIN:.0f}): {wins}/5      condition 1 (>=4): "
          f"{'PASS' if cond1 else 'FAIL'}")
    print(f"  mean margin {mean:+.1f}            condition 2 (>+{MARGIN_GATE:.0f}): "
          f"{'PASS' if cond2 else 'FAIL'}")
    print(f"  one-sided bootstrap p = {p:.4f}    vs Bonferroni alpha 0.010: "
          f"{'PASS' if p < 0.01 else 'FAIL'}")
    print(f"\n  GATE: {'CLEARED' if (cond1 and cond2 and p < 0.01) else 'NOT CLEARED'}")
    print(f"\n  variance: Eric SD {statistics.stdev(eric_tot):.1f}   "
          f"MonteCarlo SD {statistics.stdev(mc_tot):.1f}   "
          f"(Eric mean {statistics.mean(eric_tot):.1f}, MC mean {statistics.mean(mc_tot):.1f})")

    if args.room_wide:
        print()
        print("=" * 104)
        print(f"ROOM-WIDE (all eight managers, N={N_ROOMWIDE} as pre-registered)")
        print("=" * 104)
        allm = []
        for team in range(1, TEAMS + 1):
            tm = []
            for fold in YEARS:
                curve = fit_curve(tables, [y for y in YEARS if y != fold], fold)
                vorp, position, _p2, _l2 = vorp_board(tables[fold], curve, config)
                rp = REPO / "data" / "cache" / f"espn_ranks_{lid}_{fold}.json"
                if rp.exists():
                    for eid, row in json.loads(rp.read_text(encoding="utf-8")).items():
                        if row.get("position"):
                            position.setdefault(str(eid), row["position"])
                picks = json.loads(
                    (REPO / "data/cache" / f"espn_draft_{lid}_{fold}.json").read_text("utf-8"))
                profiles = build_profiles(lid, [y for y in YEARS if y != fold], fold)
                pts = {str(k): float(v) for k, v in json.loads(
                    (REPO / "data/cache" / f"espn_actuals_{lid}_{fold}.json")
                    .read_text("utf-8")).items()}
                pool = Pool(vorp, position)
                real, mine = mc_draft(picks, pool, profiles, team, N_ROOMWIDE,
                                      random.Random(SEED + fold + team * 97))
                tm.append(lineup_points(mine, pts, position)
                          - lineup_points(real, pts, position))
            allm += tm
            print(f"  team {team}: " + "".join(f"{x:>+10.1f}" for x in tm)
                  + f"   {sum(1 for x in tm if x > MEANINGFUL_MARGIN)}/5  "
                  f"mean {statistics.mean(tm):+.1f}"
                  + ("   <- Eric" if team == ERIC_TEAM else ""))
        print(f"\n  across 40 manager-seasons: "
              f"{sum(1 for x in allm if x > MEANINGFUL_MARGIN)}/40, "
              f"mean {statistics.mean(allm):+.1f}, SD {statistics.stdev(allm):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
