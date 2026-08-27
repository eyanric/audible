"""Tasks 1 and 4: what is actually on the wire after 128 picks, and whether the bye holes bite.

    uv run --extra nflverse python scripts/waiver_baseline.py

Read-only, display lane. Nothing enters the sort.

WHY THIS IS THE DECISIVE NUMBER FOR AN 8-TEAM LEAGUE. Eight teams x 16 rounds is 128
players. A 12-team league drafts 192, so the wire here starts 64 players higher. Every
"roster hole" claim -- including this project's own bye-week finding -- is only real if the
wire cannot patch it, and that is a measurable question rather than an intuition.

THE DRAFT MODEL IS THE ROOM'S, NOT ADP'S. Sorting by ADP and cutting at 128 would say the
best kicker alive is still on the wire, because the market prices no kicker inside 128. This
room does not behave that way: measured over five drafts it spends 8.2 picks on kickers and
8.4 on defences inside those same 128. Using ADP order would therefore overstate the skill
talent left on the wire, which is exactly the direction that would make a bye hole look
patchable when it is not.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TEAMS, ROUNDS = 8, 16

# Measured over ESPN 6012, 2021-2025 (640 picks): the room takes this many of each specialist
# inside its 128, against zero K and four DEF implied by market order.
ROOM_K, ROOM_DEF = 8, 8

# Starting slots x 8 teams = the worst player at that position anybody starts in a given week.
# A wire option at or above this line is a genuine start, not a hole plugged with a body.
STARTER_FLOOR = {"QB": 8, "RB": 16, "WR": 16, "TE": 8, "K": 8, "DEF": 8}

# The four weeks the slot-8 dry-run roster could not field a legal nine.
BYE_HOLES = {7: ["RB"], 8: ["QB", "DEF"], 13: ["RB"], 14: ["TE", "K"]}

# A bye is ONE WEEK. Season totals answer "is there a body" and per-week answers "what does
# the week cost", which is the number a decision is actually made on -- a patch 54 season
# points light sounds fatal and is 3.2 points on the Sunday it is used.
GAMES = 17


def realistic_draft(board, n: int = TEAMS * ROUNDS) -> set[str]:
    """The 128 players this ROOM would plausibly take: market order, plus its specialists."""
    priced = sorted((e for e in board.entries if e.adp is not None), key=lambda e: e.adp)
    spec = []
    for pos, want in (("K", ROOM_K), ("DEF", ROOM_DEF)):
        spec += sorted((e for e in board.entries if e.position == pos),
                       key=lambda e: -e.points)[:want]
    gone = {e.player_id for e in spec}
    for e in priced:
        if len(gone) >= n:
            break
        gone.add(e.player_id)
    return gone


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="espn_davis_drive")
    args = ap.parse_args()

    from qa_board_fixture import load_board, load_usage_table

    board = load_board(args.league)
    usage = load_usage_table(args.league)
    gone = realistic_draft(board)

    by_pos: dict[str, list] = {}
    for e in board.entries:
        by_pos.setdefault(e.position, []).append(e)
    for rows in by_pos.values():
        rows.sort(key=lambda e: -e.points)
    baseline = {p: round(rows[0].points - rows[0].vorp, 1) for p, rows in by_pos.items()}

    print("=" * 100)
    print("TASK 1 -- THE WIRE AFTER 128 PICKS")
    print("=" * 100)
    print(f"  draft model: market order + the room's {ROOM_K} kickers and {ROOM_DEF} defences")
    print(f"  {len(gone)} players gone; the wire is everyone else.\n")
    print(f"  {'pos':<5}{'best on the wire':<24}{'pts':>8}{'pos rk':>8}"
          f"{'baseline':>10}{'surplus':>9}{'starter floor':>15}{'startable?':>12}")
    wire_best = {}
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        rows = by_pos.get(pos, [])
        left = [e for e in rows if e.player_id not in gone]
        if not left:
            continue
        top = left[0]
        rk = rows.index(top) + 1
        floor_rk = STARTER_FLOOR[pos]
        floor_pts = rows[floor_rk - 1].points if len(rows) >= floor_rk else 0.0
        wire_best[pos] = top
        print(f"  {pos:<5}{top.name:<24}{top.points:>8.1f}{pos + str(rk):>8}"
              f"{baseline[pos]:>10.1f}{top.points - baseline[pos]:>+9.1f}"
              f"{f'{pos}{floor_rk} = {floor_pts:.0f}':>15}"
              f"{('YES' if top.points >= floor_pts else 'no'):>12}")

    print()
    print("=" * 100)
    print("TASK 1 -- ARE THE BYE HOLES REAL, OR PATCHABLE FROM THE WIRE?")
    print("=" * 100)
    print("  A patch has to be available AND not on bye itself that week.\n")
    for wk in sorted(BYE_HOLES):
        print(f"  week {wk}:")
        for pos in BYE_HOLES[wk]:
            rows = by_pos.get(pos, [])
            floor_rk = STARTER_FLOOR[pos]
            floor_pts = rows[floor_rk - 1].points if len(rows) >= floor_rk else 0.0
            avail = [e for e in rows
                     if e.player_id not in gone and usage.bye(e.team) != wk]
            if not avail:
                print(f"     {pos:<4} nothing on the wire at all")
                continue
            top = avail[0]
            ok = top.points >= floor_pts
            per_wk = (top.points - floor_pts) / GAMES
            starter = rows[0]
            vs_best = (top.points - starter.points) / GAMES
            print(f"     {pos:<4} best patch {top.name:<22} {top.points:6.1f} pts "
                  f"({top.points / GAMES:4.1f}/wk)  vs {pos}{floor_rk} floor "
                  f"{floor_pts / GAMES:4.1f}/wk -> {per_wk:+5.1f}/wk   "
                  f"{'STARTABLE' if ok else 'below the floor'}"
                  f"   [vs {pos}1 {vs_best:+.1f}/wk]")
        print()

    print("=" * 100)
    print("TASK 4 -- HENRY AND COOK, AND THE RB CLIFFS AROUND THEM")
    print("=" * 100)
    rbs = by_pos["RB"]
    drops = [rbs[i].vorp - rbs[i + 1].vorp for i in range(min(39, len(rbs) - 1))]
    import statistics as st
    typ = st.median(drops)
    cliffs = [i + 1 for i, d in enumerate(drops) if d >= max(3.0 * typ, 8.0)]
    for name in ("Derrick Henry", "James Cook"):
        e = next((x for x in rbs if x.name == name), None)
        if e is None:
            continue
        rk = rbs.index(e) + 1
        below = next((c for c in cliffs if c >= rk), None)
        above = max((c for c in cliffs if c < rk), default=None)
        ctx = usage.get(e.player_id)
        print(f"\n  {name} ({e.team}, bye wk {usage.bye(e.team)})")
        print(f"     RB{rk} on the board, {e.points:.1f} pts, vorp {e.vorp:.1f}, "
              f"overall #{e.vorp_rank}")
        print(f"     tier: cliff above at RB{above}, next cliff below at RB{below}"
              if above else f"     tier: top tier, next cliff below at RB{below}")
        if ctx:
            def pct(v: float | None) -> str:
                return "-" if v is None else f"{v * 100:.1f}%"

            print(f"     2025 usage: target share {pct(ctx.target_share)}, "
                  f"routes(proxy) {pct(ctx.route_participation)}, "
                  f"snaps {pct(ctx.snap_share)}")
        wire = wire_best.get("RB")
        if wire:
            print(f"     if he misses a week the wire offers {wire.name} "
                  f"({wire.points:.1f}) -- {(e.points - wire.points) / GAMES:.1f} pts/wk worse "
                  f"than him, and {(rbs[15].points - wire.points) / GAMES:.1f}/wk worse than "
                  f"a marginal RB16 starter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
