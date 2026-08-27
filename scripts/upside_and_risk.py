"""Tasks 2 and 3: touchdown regression, boom/bust, and injury CONTEXT.

    uv run --extra nflverse python scripts/upside_and_risk.py

Read-only, display lane. Nothing enters the sort.

TASK 2a uses machinery that already exists. `ff_opportunity` ships expected touchdowns
(`rec_touchdown_exp`, `rush_touchdown_exp`) beside the actual ones, so xTD-vs-TD is a
subtraction rather than a model. A back who scored 14 on 8.1 expected did not find a skill
nobody else has; he finished drives that happened to reach the goal line, and drive-ending
luck is the least sticky thing in football.

TASK 2b is week-to-week variance from the 2025 game logs, scored through this league's own
rules. Mean without spread hides the difference between a player who gives you 12 every week
and one who gives you 4, 4, 4, 40.

TASK 3 IS DESCRIPTIVE AND STOPS THERE. Games played, age, and prior volume. No risk score,
no probability, no composite. The public evidence does not support predicting individual
injury from these inputs, and a number that looks like a forecast will be read as one --
so the tooltip says history, not prediction, and the code produces no such number.
"""

from __future__ import annotations

import argparse
import contextlib
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PRIOR = 2025
HISTORY = (2023, 2024, 2025)

# The established RB age cliff. A flag, not a coefficient -- it marks a player for a human to
# think about and feeds nothing.
RB_AGE_FLAG = 27


def context_flags(position: str, age: float | None,
                  games: dict[int, int], years=HISTORY) -> list[str]:
    """Descriptive flags only. Never a score, never a probability.

    A season the player was not in the league is NOT missed time: a rookie shows no games for
    the years he was in college, and flagging that reads as an injury history for a
    23-year-old who has never been hurt. Those two states are reported separately.
    """
    flags: list[str] = []
    if position == "RB" and age is not None and age >= RB_AGE_FLAG:
        # The label names the THRESHOLD, not the player's age -- "RB 33+" reads as though the
        # cutoff moved with the player.
        flags.append(f"RB {RB_AGE_FLAG}+ cohort (age {age:.0f})")
    played = [games.get(y) for y in years]
    if any(v is not None and 1 <= v <= 12 for v in played):
        flags.append("missed time in the window")
    if any(v in (None, 0) for v in played):
        flags.append("not in the league for part of the window")
    return flags


def td_regression(gsis_to_sleeper: dict[str, str]) -> dict[str, dict[str, float]]:
    """Actual minus expected touchdowns, 2025, from ff_opportunity's own _exp columns."""
    import polars as pl

    from audible.adapters.nflverse import opportunity_frame

    df = opportunity_frame([PRIOR])
    cols = [c for c in ("rec_touchdown", "rush_touchdown",
                        "rec_touchdown_exp", "rush_touchdown_exp") if c in df.columns]
    agg = df.group_by("player_id").agg(*[pl.col(c).sum().alias(c) for c in cols])
    out: dict[str, dict[str, float]] = {}
    for r in agg.iter_rows(named=True):
        pid = gsis_to_sleeper.get(str(r["player_id"]))
        if pid is None:
            continue
        act = (r.get("rec_touchdown") or 0.0) + (r.get("rush_touchdown") or 0.0)
        exp = (r.get("rec_touchdown_exp") or 0.0) + (r.get("rush_touchdown_exp") or 0.0)
        out[pid] = {"td": float(act), "xtd": float(exp), "delta": float(act - exp)}
    return out


def weekly_profile(config) -> dict[str, dict[str, float]]:
    """Per-player mean and stdev of WEEKLY points in 2025, scored by this league's rules."""
    from audible.adapters.sleeper import SleeperAdapter
    from audible.scoring.engine import score_stat_line

    out: dict[str, list[float]] = {}
    prim: dict[str, str] = {}
    with SleeperAdapter() as ad:
        catalog = ad.get_players_catalog()
        for position in sorted(config.positions):
            for week in range(1, 19):
                for row in ad.get_stats(PRIOR, position, week=week):
                    pid = str(row.get("player_id"))
                    stats = row.get("stats")
                    entry = catalog.get(pid)
                    if not stats or entry is None:
                        continue
                    p, _ = ad.classify(entry, config.positions)
                    if p is None:
                        continue
                    prim[pid] = p
                    num = {k: float(v) for k, v in stats.items() if isinstance(v, int | float)}
                    out.setdefault(pid, []).append(score_stat_line(num, config.scoring_for(p)))
    prof = {}
    for pid, vals in out.items():
        if len(vals) >= 4:
            m = statistics.mean(vals)
            sd = statistics.stdev(vals)
            prof[pid] = {"mean": m, "sd": sd, "cv": (sd / m if m > 0 else 0.0),
                         "weeks": len(vals), "pos": prim.get(pid, "?")}
    return prof


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    ap.add_argument("--top", type=int, default=60)
    args = ap.parse_args()

    import polars as pl
    from qa_board_fixture import load_board, load_usage_table

    from audible.adapters.sleeper import SleeperAdapter
    from audible.backtest.data import season_actuals
    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]
    board = load_board(args.league)
    usage = load_usage_table(args.league)

    ids = pl.read_parquet(REPO / "data/cache/nflverse/ff_playerids.parquet")
    g2s, age_by = {}, {}
    for r in ids.select(["sleeper_id", "gsis_id", "age"]).iter_rows(named=True):
        if r["sleeper_id"] is None:
            continue
        sid = str(r["sleeper_id"])
        if r["gsis_id"] is not None:
            g2s[str(r["gsis_id"])] = sid
        if r["age"] is not None:
            age_by[sid] = float(r["age"])

    tds = td_regression(g2s)
    prof = weekly_profile(config)

    games: dict[str, dict[int, int]] = {}
    with SleeperAdapter() as ad:
        for yr in HISTORY:
            for pid, ps in season_actuals(ad, yr, config).items():
                games.setdefault(pid, {})[yr] = ps.games

    top = sorted(board.entries, key=lambda e: e.vorp_rank)[:args.top]

    print("=" * 104)
    print(f"TASK 2a -- TOUCHDOWN REGRESSION, 2025 (actual minus expected, top {args.top})")
    print("=" * 104)
    print("  Positive = he outscored his opportunity and is a REGRESSION-DOWN candidate.")
    print("  Negative = the opportunity was there and the ball did not go in: bounce-back.\n")
    rows = [(e, tds[e.player_id]) for e in top if e.player_id in tds]
    rows.sort(key=lambda kv: -kv[1]["delta"])
    print(f"  {'':<3}{'player':<24}{'pos':<5}{'TD':>6}{'xTD':>7}{'delta':>8}")
    for e, t in rows[:8]:
        print(f"  {'DOWN':<3}  {e.name:<24}{e.position:<5}{t['td']:>6.0f}{t['xtd']:>7.1f}"
              f"{t['delta']:>+8.1f}")
    print("   ...")
    for e, t in rows[-8:]:
        print(f"  {'UP':<3}  {e.name:<24}{e.position:<5}{t['td']:>6.0f}{t['xtd']:>7.1f}"
              f"{t['delta']:>+8.1f}")

    print()
    print("=" * 104)
    print("TASK 2b/2c -- BOOM/BUST, AND WHERE VARIANCE PAYS")
    print("=" * 104)
    print("  cv = stdev/mean of WEEKLY 2025 points. High cv at the TOP of a tier with a big")
    print("  gap below is where variance is worth buying; high cv at the bottom is just risk.\n")
    by_pos: dict[str, list] = {}
    for e in board.entries:
        by_pos.setdefault(e.position, []).append(e)
    for v in by_pos.values():
        v.sort(key=lambda e: -e.vorp)
    print(f"  {'player':<24}{'pos':<5}{'wk mean':>9}{'wk sd':>8}{'cv':>7}"
          f"{'pos rk':>8}{'gap below':>11}")
    shown = 0
    for e in top:
        p = prof.get(e.player_id)
        if not p:
            continue
        rows_p = by_pos[e.position]
        i = rows_p.index(e)
        gap = (rows_p[i].vorp - rows_p[i + 1].vorp) if i + 1 < len(rows_p) else 0.0
        print(f"  {e.name:<24}{e.position:<5}{p['mean']:>9.1f}{p['sd']:>8.1f}{p['cv']:>7.2f}"
              f"{e.position + str(i + 1):>8}{gap:>11.1f}")
        shown += 1
        if shown >= 20:
            break

    print()
    print("=" * 104)
    print("TASK 3 -- INJURY CONTEXT. HISTORY, NOT PREDICTION.")
    print("=" * 104)
    print("  Games played per season, age, and prior-season volume. There is deliberately NO")
    print("  risk score and NO probability here: the public evidence does not support")
    print("  predicting an individual player's injury from these inputs, and a composite")
    print("  number would be read as a forecast whatever the label said.\n")
    print(f"  {'player':<24}{'pos':<5}{'age':>5}{'2023':>6}{'2024':>6}{'2025':>6}"
          f"{'snap%':>8}{'tgt%':>7}   flags")
    for e in top[:24]:
        g = games.get(e.player_id, {})
        ctx = usage.get(e.player_id)
        age = age_by.get(e.player_id)
        flags = context_flags(e.position, age, g)
        print(f"  {e.name:<24}{e.position:<5}{(age if age else 0):>5.0f}"
              + "".join(f"{(str(g[y]) if g.get(y) else '-'):>6}" for y in HISTORY)
              + f"{(ctx.snap_share * 100 if ctx and ctx.snap_share else 0):>8.1f}"
              + f"{(ctx.target_share * 100 if ctx and ctx.target_share else 0):>7.1f}"
              + ("   " + "; ".join(flags) if flags else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
