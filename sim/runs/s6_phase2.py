"""S6 Phase 2 -- inventory every input, and prove each can move an ordering.

The current transform reads ONE input: projected points. Everything else the board already
carries is discarded. This enumerates what exists, measures coverage against ESPN's pool, and
puts each candidate through the rebuilt G5 -- which asks whether a term moves an ordering FOR
THE REASON CLAIMED, in more than one season, with real spread.

Excluded candidates are named with the reason. A candidate silently dropped is a candidate
nobody can audit.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim import arms, rank, referee, signals  # noqa: E402

LK = signals.LEAGUE

# name -> (scope, kwargs, what it is, why it might carry ordering information)
CANDIDATES: tuple[tuple[str, str | None, dict, str], ...] = (
    ("snap_share", None, {}, "prior-season offensive snap share"),
    ("target_share", None, {}, "prior-season target share"),
    ("td_oe", None, {}, "prior-season touchdowns over expected"),
    ("draft_round", None, {"rookies_only": True}, "draft capital, rookies only"),
    ("adp_gap", None, {}, "market rank minus projection rank"),
    ("ngs_separation", None, {}, "NGS average separation, receivers"),
    ("ngs_cushion", None, {}, "NGS average cushion, receivers"),
    ("ngs_rush_eff", None, {}, "NGS rushing efficiency, backs"),
    ("ngs_time_to_los", None, {}, "NGS time to line of scrimmage, backs"),
    ("ngs_time_to_throw", None, {}, "NGS time to throw, passers"),
    ("contract", None, {}, "cap share of the most recent prior contract"),
    ("availability", "board", {}, "position-level games-played rate"),
    ("age_at_export", None, {}, "FFA age -- STAMPED AT EXPORT, not vintage"),
    ("uncertainty", None, {}, "FFA sd_pts relative to points"),
    ("ffa_dropoff", None, {}, "FFA points to the next player at the position"),
    ("ffa_experience", None, {}, "FFA years of experience"),
    ("depth_slot", None, {}, "prior-season mean depth-chart slot, negated"),
    ("ff_opp_exp", None, {}, "prior-season expected fantasy points per TEAM game"),
    ("ff_opp_eff", None, {}, "prior-season points over expected, per appearance"),
    ("ffa_skew", None, {}, "FFA (ceiling-points)/(points-floor): upside over downside"),
    ("noise", None, {}, "THE FLOOR: a sha256, information-free by construction"),
)

EXCLUDED: tuple[tuple[str, str], ...] = (
    ("injuries / practice participation",
     "HARD STOP. audible#71 measured RB 2.58 games missed against WR 3.29 at ADP <= 100 -- the "
     "opposite of the folklore -- and this session is forbidden a player-level injury term."),
    ("participation (route running)",
     "Play-level with no season column and no gsis key; route participation is the known "
     "nflverse gap and is delivered post-season only."),
    ("ftn_charting",
     "Pinned 2022-2025. As a PRIOR-season term that is seasons 2023-2026, and ESPN has no 2023 "
     "board -- so two usable seasons. Too few for a six-fold LOSO."),
    ("officials",
     "Not player-keyed. Nothing to join to a board."),
    ("ffa points_vor / floor_vor / ceiling_vor / rank / position_rank",
     "These are FFA's OWN replacement transform of its own projection. Feeding them to a "
     "ranking model tests FFA's transform, not an input."),
)


def coverage(name: str, season: int) -> tuple[int, int, float]:
    """How many of ESPN's scoreable pool this input actually covers."""
    loaded = arms.load(signals.SOURCE, season, LK)
    pool = [p for p in loaded.points if loaded.position.get(p) in rank.SCOREABLE]
    # NO SILENT ZERO. An earlier version returned 0% here on any exception, which reported a
    # polars dtype error as "this input covers nothing" -- a broken input indistinguishable
    # from an absent one. The error is raised.
    vals = signals.signal_values(name, season)
    have = sum(1 for p in pool if p in vals)
    return have, len(pool), (have / len(pool) if pool else 0.0)


def main() -> int:
    seasons = referee.espn_seasons()
    print(f"seasons {seasons}   pool source {signals.SOURCE}   league {LK}")

    print("\n" + "=" * 78)
    print("COVERAGE -- what fraction of ESPN's scoreable pool each input reaches")
    print("=" * 78)
    print("  FFA's projections file is a TOP-N EXPORT (72 RB / 72 WR / 37 QB / 36 TE in 2022),")
    print("  so every FFA-derived input is capped well below the board's size.")
    cov: dict[str, float] = {}
    for name, _scope, _kw, what in CANDIDATES:
        per = [coverage(name, s) for s in seasons]
        mean = sum(c[2] for c in per) / len(per)
        cov[name] = mean
        detail = "  ".join(f"{s}:{c[2]:.0%}" for s, c in zip(seasons, per, strict=True))
        print(f"  {name:18s} {mean:5.0%}   {detail}")
        print(f"      {what}")

    print("\n" + "=" * 78)
    print("G5 -- does each candidate move an ordering, FOR THE REASON CLAIMED?")
    print("=" * 78)
    passed, failed = [], []
    for name, scope, kw, _what in CANDIDATES:
        try:
            avail = signals.seasons_for(name)
        except Exception as exc:  # noqa: BLE001
            print(f"\n  {name}: UNAVAILABLE -- {type(exc).__name__}: {exc}")
            failed.append((name, f"unavailable: {type(exc).__name__}"))
            continue
        if not avail:
            print(f"\n  {name}: NO SEASONS")
            failed.append((name, "no seasons"))
            continue
        g = referee.ordering_gate(name, avail, scope=scope, **kw)
        nw = sum(1 for v in g.within_moves.values() if v > 0)
        verdict = "PASSES" if g.passed else "FAILS"
        print(f"\n  {name} (scope={g.scope}): {verdict}   coverage {cov[name]:.0%}")
        print(f"    seasons {len(avail)}  cells applied/skipped {g.applied}/{g.skipped}  "
              f"min sd {g.min_applied_sd:.3e}")
        print(f"    within-position orderings moved in {nw}/{g.total_seasons} seasons")
        for r in g.reasons:
            print(f"    REASON: {r}")
        (passed if g.passed else failed).append(
            (name, "" if g.passed else "; ".join(g.reasons)))

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  candidates {len(CANDIDATES)}   pass G5 {len(passed)}   fail G5 {len(failed)}")
    for name, why in failed:
        print(f"    FAILS  {name}: {why}")
    print(f"\n  excluded before testing, with the reason ({len(EXCLUDED)}):")
    for what, why in EXCLUDED:
        print(f"    {what}")
        print(f"        {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
