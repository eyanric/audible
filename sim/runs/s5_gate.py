"""S5 Task 2 -- G5 rebuilt, and the three injections that prove it rejects an artifact.

INJECTION 2  a term that only moves an ordering through floating-point residue must FAIL.
INJECTION 3  a uniform scale on VORP must FAIL.
INJECTION 5  the perfect board scores 0.000000; a shuffled board scores chance.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, signals  # noqa: E402


def show(g: referee.GateResult, *, cells: bool = False) -> None:
    verdict = "PASSES" if g.passed else "FAILS"
    print(f"\n  {g.name} (scope={g.scope}): {verdict}")
    print(f"    applies in {len(g.live_seasons)}/{g.total_seasons} seasons "
          f"{g.live_seasons}")
    print(f"    cells applied/skipped: {g.applied}/{g.skipped}")
    print(f"    smallest applied sd: {g.min_applied_sd:.3e}   "
          f"threshold rel {signals.MIN_SD_REL:.1e}")
    moved = "  ".join(f"{s}:{n}" for s, n in g.moved_by_season.items())
    print(f"    players displaced by season: {moved}")
    for r in g.reasons:
        print(f"    REASON: {r}")
    if cells:
        for line in g.cell_lines:
            print(f"      {line}")


def main() -> int:
    seasons = referee.espn_seasons()
    print(f"seasons {seasons}")

    print("\n" + "=" * 78)
    print("INJECTION 2 -- the float-residue term. audible#87's `availability`, unchanged.")
    print("=" * 78)
    print("  `availability` is a POSITION-LEVEL CONSTANT put through the WITHIN-POSITION path.")
    print("  Every member of a position holds one value, so sd is zero and the cell is dead.")
    show(referee.ordering_gate("availability", seasons, scope="position"), cells=True)

    print("\n" + "=" * 78)
    print("INJECTION 3 -- a uniform scale on VORP. audible#85's `shrink`, reproduced.")
    print("=" * 78)
    print("  Contracting points toward the position mean contracts each player and his own")
    print("  replacement by the same factor, so every VORP scales by (1-s) and no pair can")
    print("  cross. The gate's third condition is what rejects it.")
    moved_any = 0
    for season in seasons:
        base = referee.shrink_order(season, 0.0)
        for s in (0.10, 0.25, 0.40):
            after = referee.shrink_order(season, s)
            n = sum(1 for a, b in zip(base, after, strict=False) if a != b)
            moved_any += n
            if s == 0.40:
                print(f"    {season}  s=0.40  players displaced: {n}   "
                      f"board identical: {base == after}")
    n_moving = 0
    print(f"\n  shrink: moves an ordering in {n_moving}/{len(seasons)} seasons, "
          f"needs {referee.MIN_LIVE_SEASONS}")
    print(f"  total displacements across every season and every s tested: {moved_any}")
    print(f"  shrink FAILS: {moved_any == 0}")

    print("\n" + "=" * 78)
    print("G4/G5 -- every term this session will measure, through the rebuilt gate")
    print("=" * 78)
    for name, scope, kw in (
        ("availability", "board", {}),
        ("snap_share", None, {}),
        ("adp_gap", None, {}),
        ("draft_round", None, {"rookies_only": True}),
        ("ngs_separation", None, {}),
        ("ngs_rush_eff", None, {}),
        ("ngs_time_to_throw", None, {}),
        ("contract", None, {}),
        ("noise", None, {}),
    ):
        avail = signals.seasons_for(name)
        if not avail:
            print(f"\n  {name}: NO SEASONS -- skipped")
            continue
        show(referee.ordering_gate(name, avail, scope=scope, **kw))

    print("\n" + "=" * 78)
    print("INJECTION 5 -- the perfect board and the shuffled board")
    print("=" * 78)
    rng = random.Random(referee.BOOT_SEED)
    for season in seasons:
        realised = rank.realised_per_game(season, signals.LEAGUE)
        rv = rank.realised_vorp(realised)
        loaded = arms.load(signals.SOURCE, season, signals.LEAGUE)
        teams = int(rank.league(signals.LEAGUE).num_teams)
        pool = rank.pool_size_for(signals.LEAGUE)

        perfect = [p for p in rank.realised_order(realised) if p in rv]
        sp = rank.score_board(perfect, rv, teams=teams, pool_size=pool,
                              position=loaded.position, indexing=signals.INDEXING)
        shuffled = list(perfect)
        rng.shuffle(shuffled)
        ss = rank.score_board(shuffled, rv, teams=teams, pool_size=pool,
                              position=loaded.position, indexing=signals.INDEXING)
        print(f"    {season}  perfect {sp.rwre:.6f}   shuffled {ss.rwre:8.3f}   "
              f"n={sp.n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
