#!/usr/bin/env python3
"""Where is the `vs ESPN` column actually carrying the scoring seam, and where is it noise?

    uv run --extra nflverse python scripts/gap-confidence.py

READ-ONLY. Builds the board, fetches ESPN's served ranks, and reports -- WITHIN POSITION and
split by ESPN overall-rank band -- the Spearman correlation between a player's receptions and
the gap the cockpit shows for him.

WHY THAT QUANTITY. This league pays WR/TE 0.5 a catch and RB 0.0, while ESPN orders the room
on its own ranks. If the disagreement between the two boards is the SCORING SEAM, then inside
a band the gap should track receptions: high-catch receivers move up for us, pass-catching
backs move down. If it is noise, the correlation is flat. That is the same statistic
`analysis/rankdelta.py` computes -- `spearman(receptions, delta)` within position, banded on
ESPN rank -- so the numbers here are directly comparable to what `rank-check` reports.

The gap correlated here is the one the COLUMN SHOWS (within-position dense ranks over the
draftable 200), not rankdelta's overall-rank delta, because the question is whether the thing
on screen can be trusted.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from audible.adapters.espn import EspnAdapter, _draft_rank  # noqa: E402
from audible.adapters.sleeper import SleeperAdapter  # noqa: E402
from audible.backtest.metrics import spearman  # noqa: E402
from audible.config.loader import load_all_leagues  # noqa: E402
from audible.draft.board import build_board  # noqa: E402
from audible.draft.espn_ids import build_supplement  # noqa: E402
from audible.server.state import _GAP_POPULATION  # noqa: E402

BANDS = [("1-60", 1, 60), ("61-120", 61, 120), ("121-200", 121, 200)]
POSITIONS = ["WR", "RB", "TE"]
# Below this a band is reported but must not be trusted; it is indistinguishable from noise.
STRONG = 0.30
MIN_N = 6


def main() -> int:
    cfg = load_all_leagues()["espn_davis_drive"]
    board = build_board(cfg)
    with SleeperAdapter() as sleeper:
        catalog = sleeper.get_players_catalog()
        lines = {ln.player_id: ln for ln in sleeper.raw_player_lines(cfg, season=2026)}
    with EspnAdapter() as espn:
        pool = espn.get_player_pool(cfg)

    by_espn = {
        str(e["espn_id"]): str(pid) for pid, e in catalog.items()
        if isinstance(e, dict) and e.get("espn_id")
    }
    for espn_id, board_id in build_supplement(pool, catalog).items():
        by_espn.setdefault(espn_id, board_id)

    ranks: dict[str, float] = {}
    for row in pool:
        player = row.get("player") or row
        rank = _draft_rank(player)
        board_id = by_espn.get(str(player.get("id")))
        if rank is not None and board_id:
            ranks[board_id] = rank

    # The gap exactly as server/state.py computes it for the column.
    shared = [
        e for e in board.entries
        if e.player_id in ranks
        and e.vorp_rank <= _GAP_POPULATION
        and ranks[e.player_id] <= _GAP_POPULATION
    ]
    gaps: dict[str, int] = {}
    for position in {e.position for e in shared}:
        group = [e for e in shared if e.position == position]
        if len(group) < 3:
            continue
        theirs = {e.player_id: i for i, e in enumerate(
            sorted(group, key=lambda e: ranks[e.player_id]), start=1)}
        ours = {e.player_id: i for i, e in enumerate(
            sorted(group, key=lambda e: e.vorp_rank), start=1)}
        for e in group:
            gaps[e.player_id] = theirs[e.player_id] - ours[e.player_id]

    def receptions(entry) -> float:
        line = lines.get(entry.player_id)
        return float(line.stats.get("rec", 0.0)) if line else 0.0

    print(f"gap population: {len(shared)} players shared inside the top {_GAP_POPULATION}")
    print("Spearman(receptions, gap) WITHIN position, banded on ESPN overall rank.")
    print("Positive => high-reception players move UP for us, which is the seam.\n")
    print(f"  {'band':<10}" + "".join(f"{p:>16}" for p in POSITIONS))
    verdicts: dict[str, list[str]] = {p: [] for p in POSITIONS}
    for label, lo, hi in BANDS:
        cells = []
        for position in POSITIONS:
            group = [
                e for e in shared
                if e.position == position and lo <= ranks[e.player_id] <= hi
                and e.player_id in gaps
            ]
            recs = [receptions(e) for e in group]
            if len(group) < MIN_N or len(set(recs)) < 2:
                cells.append(f"{'n/a':>10} (n={len(group)})")
                continue
            rho = spearman(recs, [float(gaps[e.player_id]) for e in group])
            # MAGNITUDE, not sign. The predicted direction is position-dependent: receivers
            # are paid 0.5 a catch so high-reception WRs should move UP (positive), while
            # backs are paid 0.0 so pass-catching RBs should move DOWN (negative). Testing
            # `rho >= STRONG` would have declared every RB band noise, including -0.40.
            mark = "*" if abs(rho) >= STRONG else " "
            cells.append(f"{rho:>+10.2f}{mark}(n={len(group)})")
            if abs(rho) >= STRONG:
                verdicts[position].append(f"{label} ({rho:+.2f})")
        print(f"  {label:<10}" + "".join(f"{c:>16}" for c in cells))

    print(f"\n  * = >= {STRONG:.2f}, strong enough to show at full intensity")
    for position in POSITIONS:
        bands = ", ".join(verdicts[position]) or "no band clears the bar"
        print(f"    {position}: {bands}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
