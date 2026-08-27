"""Tasks 4 and 5: who I am drafting against, and where the cliffs are.

    uv run --extra nflverse python scripts/opponent_model.py

Read-only, display lane. Neither of these depends on any model edge existing, which is the
point: they survive a null ordering result and still change what happens on Sunday.

TASK 4 profiles the room from five real drafts. 2021 and 2022 carry no ESPN rank snapshot so
they cannot be backtest folds, but they are perfectly good BEHAVIOURAL data -- positional
tendency needs no market order to measure. Deviation from ESPN order is measured on
2023-2025 only, and the report says which years back which claim.

Profiles are keyed by TEAM, not by seat. Seats are redrawn every year; the managers are the
same people, and it is the manager who reaches for a quarterback.

TASK 5 finds the value cliffs on the current pinned board. A cliff is where the next player
at a position is materially worse than the last one, which is exactly the decision the 8/9
turn turns on: take the last man above a cliff, or take the position that has none coming.
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

ALL_YEARS = (2021, 2022, 2023, 2024, 2025)
RANKED_YEARS = (2023, 2024, 2025)
TEAMS = 8
NORM = {"PK": "K"}


def positions_by_espn_id():
    import polars as pl

    ids = pl.read_parquet(REPO / "data/cache/nflverse/ff_playerids.parquet")
    out = {}
    for r in ids.select(["espn_id", "position"]).iter_rows(named=True):
        if r["espn_id"] is not None and r["position"]:
            out[str(r["espn_id"])] = NORM.get(r["position"], r["position"])
    return out


def task4(league_id: int) -> None:
    pos_by_espn = positions_by_espn_id()

    picks_by_team = collections.defaultdict(list)
    for yr in ALL_YEARS:
        p = REPO / "data" / "cache" / f"espn_draft_{league_id}_{yr}.json"
        if not p.exists():
            continue
        for pick in json.loads(p.read_text(encoding="utf-8")):
            # an unresolved espn id in this league is a team D/ST -- it has no player row
            pos = pos_by_espn.get(str(pick["player_id"]), "DEF")
            picks_by_team[pick["team_id"]].append(
                {"year": yr, "round": pick["round"], "overall": pick["overall"],
                 "pid": str(pick["player_id"]), "pos": pos})

    # deviation from the market: only where a rank snapshot exists
    dev_by_team = collections.defaultdict(list)
    for yr in RANKED_YEARS:
        rp = REPO / "data" / "cache" / f"espn_ranks_{league_id}_{yr}.json"
        dp = REPO / "data" / "cache" / f"espn_draft_{league_id}_{yr}.json"
        if not (rp.exists() and dp.exists()):
            continue
        ranks = json.loads(rp.read_text(encoding="utf-8"))
        order = sorted((str(k) for k in ranks if ranks[k].get("standard") is not None),
                       key=lambda k: ranks[k]["standard"])
        market_rank = {pid: i + 1 for i, pid in enumerate(order)}
        taken = set()
        for pick in json.loads(dp.read_text(encoding="utf-8")):
            pid = str(pick["player_id"])
            taken.add(pid)
            mr = market_rank.get(pid)
            if mr is None:
                continue
            # How many BETTER-ranked players were still on the board when he picked?
            # Positive = he reached past that many; 0 = he took the best available.
            reached = sum(1 for q, r in market_rank.items() if r < mr and q not in taken)
            dev_by_team[pick["team_id"]].append(reached)

    print("=" * 100)
    print("TASK 4 -- OPPONENT PROFILES (team id, 5 drafts; deviation from 2023-2025 only)")
    print("=" * 100)
    cols = "".join(f"{p:>5}" for p in ("QB", "RB", "WR", "TE", "K", "DEF"))
    print(f"  {'team':>5}{'picks':>7}{'reach med':>11}{'reach p90':>11}  {cols}"
          f"   {'first QB':>9}{'first TE':>9}")
    for team in sorted(picks_by_team):
        ps = picks_by_team[team]
        c = collections.Counter(x["pos"] for x in ps)
        n_years = len({x["year"] for x in ps})
        dev = dev_by_team.get(team, [])
        med = statistics.median(dev) if dev else float("nan")
        p90 = sorted(dev)[int(0.9 * (len(dev) - 1))] if dev else float("nan")

        def first_round(pos: str, ps: list = ps) -> str:  # noqa: B008 -- bind, do not close
            rounds = [min((x["round"] for x in ps if x["pos"] == pos and x["year"] == y),
                          default=None) for y in {x["year"] for x in ps}]
            got = [r for r in rounds if r is not None]
            return f"R{statistics.mean(got):.1f}" if got else "never"

        counts = "".join(f"{c.get(p, 0) / n_years:>5.1f}"
                         for p in ("QB", "RB", "WR", "TE", "K", "DEF"))
        print(f"  {team:>5}{len(ps):>7}{med:>11.0f}{p90:>11.0f}  {counts}"
              f"   {first_round('QB'):>9}{first_round('TE'):>9}")
    print("\n  reach = better-ranked players still available when he picked (0 = best available).")
    print("  positional columns are picks per draft, averaged over the years that team appears.")


def task5(league: str) -> None:
    from qa_board_fixture import load_board

    board = load_board(league)
    by_pos = collections.defaultdict(list)
    for e in board.entries:
        by_pos[e.position].append(e)

    print()
    print("=" * 100)
    print("TASK 5 -- TIER CLIFFS ON THE CURRENT PINNED BOARD (display lane)")
    print("=" * 100)
    print("  A cliff is a drop to the next man at that position larger than the typical step.")
    print("  Reported as: rank at the cliff, the drop, and who is the last man above it.\n")
    for pos in ("RB", "WR", "TE", "QB"):
        rows = sorted(by_pos.get(pos, []), key=lambda e: -e.vorp)[:40]
        if len(rows) < 6:
            continue
        drops = [rows[i].vorp - rows[i + 1].vorp for i in range(len(rows) - 1)]
        typical = statistics.median(drops)
        # A cliff has to be big in absolute terms AND relative to this position's normal step,
        # or every position reports its own noise as structure.
        cliffs = [(i, d) for i, d in enumerate(drops) if d >= max(3.0 * typical, 8.0)][:5]
        print(f"  {pos}   (median step between adjacent players: {typical:.1f} pts)")
        if not cliffs:
            print("     no cliff clears the bar -- this position is a smooth slope\n")
            continue
        for i, d in cliffs:
            print(f"     after {pos}{i + 1:<2} drop {d:5.1f}  -- last man above: "
                  f"{rows[i].name} ({rows[i].vorp:.0f} vorp, overall #{rows[i].vorp_rank})")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    args = ap.parse_args()
    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[args.league]
    task4(config.league_id)
    task5(args.league)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
