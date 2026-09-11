"""S7 phase 5 -- the 2026 pre-registration. Written before any 2026 outcome exists.

    uv run python -m sim.s7_phase5 > sim/runs/s7-2026.txt

WHY THIS IS THE LAST PHASE AND NOT A FORMALITY. 2024 and 2025 were read by `audible#84` and
`audible#85`, so every seasonal number in this project is SELECTION-CONTAMINATED: the seasons
that decide a question have already been looked at. The weekly sample is fresh, but it is fresh
only once, and phases 2 and 3 have now spent it. 2026 is the only clean holdout left, and the
only way to keep it clean is to write the predictions down first.

EVERY PREDICTION BELOW IS FALSIFIABLE AND CARRIES A DIRECTION AND A SIZE. A prediction that
cannot fail is a description. Each states what would refute it, in the same units the check will
be run in, and P1's numbers are RE-DERIVED from the corpus by this script rather than copied out
of a report, so a transcription error cannot enter the record.

NOTHING HERE IS FITTED. The point predictions are the 2019-2025 per-season means and the
intervals are two between-season standard deviations. That is a statement that 2026 will look
like the seven seasons before it, which is exactly the claim worth testing after a session whose
result was a null.
"""

from __future__ import annotations

import statistics
import subprocess
import sys

from . import rank
from . import s7_phase2 as p2
from . import s7_weekly as s7

LEAGUES: tuple[str, ...] = ("espn_green_hope", "espn_danger_zone", "sleeper_boyfun")
AGGREGATION = "weighted"
SCALE = "vorp"


def head_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 -- a missing git is not a reason to refuse to predict
        return "unknown"


def per_season_weekly(league: str) -> dict[int, float]:
    """The FFA weekly board's mean RWRE per season. No floors, no salts: just the board."""
    out: dict[int, list[float]] = {}
    for season, week in s7.available_scopes(AGGREGATION, require_actuals=True):
        board = s7.build_board(season, week, league, aggregation=AGGREGATION, scale=SCALE)
        outcome = s7.realised_week(season, week, league).on(SCALE, position=board.position)
        if len([pid for pid in board.board if pid in outcome]) < 24:
            continue
        score = s7.score_week(board.board, outcome, league, position=board.position)
        out.setdefault(season, []).append(score.rwre)
    return {season: statistics.mean(values) for season, values in sorted(out.items())}


def main() -> int:
    sha = head_sha()
    print("S7 PHASE 5 -- 2026 PRE-REGISTRATION")
    print(f"written at {sha}")
    print("Today is 2026-09-11. No 2026 regular-season outcome exists. Nothing below has")
    print("been fitted to 2026 and nothing below may be edited after a 2026 game is played;")
    print("a later session checks this file, it does not revise it.")
    print()

    print("== P1: what the FFA weekly board will score in 2026 ==")
    print("Point prediction is the 2019-2025 per-season mean; the interval is two between-")
    print("season standard deviations. REFUTED if the 2026 mean over weeks 1-17 falls outside")
    print("the interval for a league, on the vorp scale with symmetric indexing.")
    print()
    for league in LEAGUES:
        per = per_season_weekly(league)
        values = list(per.values())
        mean = statistics.mean(values)
        sd = statistics.stdev(values)
        print(f"  {league}")
        for season, value in per.items():
            print(f"    {season}  {value:7.3f}")
        print(f"    PREDICTION 2026: {mean:7.3f}   interval "
              f"[{mean - 2 * sd:7.3f}, {mean + 2 * sd:7.3f}]   (sd {sd:.3f}, n {len(values)})")
    print()

    print("== P2: no term re-tested in 2026 will resolve in more than one league ==")
    print("Phases 2 and 3 ran 24 terms in 3 leagues over 7 seasons and produced 7 verdicts of")
    print("RESOLVES across 7 DISTINCT terms -- zero replicated. The prediction is that a 2026")
    print("re-run of the same 24 terms produces at most ONE term with RESOLVES in two or more")
    print("leagues. REFUTED by two or more such terms.")
    print()

    print("== P3: inj_status at WR, the one lead, with a direction and a size ==")
    print("Measured: +0.1125 (p 0.0244) in danger_zone, +0.1919 (p 0.0244) in green_hope,")
    print("-0.0873 (p 0.9512) in boyfun. Both hits are 1-QB ESPN leagues; the reversal is the")
    print("10-team SUPERFLEX. It is OFF its pre-registered locus, which was board-level.")
    print("PREDICTION for 2026, all three parts, each refutable on its own:")
    print("  a) the WR effect is POSITIVE in both espn_green_hope and espn_danger_zone")
    print("  b) its size is between +0.05 and +0.30 RWRE in both")
    print("  c) it is NOT positive-and-significant at WR in sleeper_boyfun")
    print("REFUTED by any of the three failing. If (a) and (b) hold, inj_status at WR is the")
    print("one thing this session found, and it should then be pre-registered board-level for")
    print("2027 rather than mined further.")
    print()

    print("== P4: green_hope will still have no composite ==")
    print("Zero terms survived in green_hope, so no composite exists to carry forward. The")
    print("prediction is that a 2026 re-run again produces no composite there with a material")
    print(f"out-of-sample weekly gain, where material is {p2.MATERIAL} RWRE as pre-registered.")
    print("REFUTED by a green_hope composite improving the out-of-sample weekly RWRE by")
    print(f"{p2.MATERIAL} or more.")
    print()

    print("== P5: the hit count will again be what multiple testing predicts ==")
    print("336 p-values produced 20 hits at p <= 0.05 against 16.4 expected, +0.91 sd. The")
    print("prediction is that a 2026 re-run of the same battery lands within two standard")
    print("deviations of its own expectation. REFUTED by a hit count more than 2 sd above it.")
    print()

    print("== WHAT WOULD CHANGE THE PRODUCT ==")
    print("None of P1, P2, P4 or P5 coming true changes the draft board: they are predictions")
    print("that the null holds. P3 is the only one whose confirmation would, and even then the")
    print("effect is +0.11 to +0.19 RWRE at one position in two leagues, against a board error")
    print("of 34.9 to 48.5. The honest summary is that the incumbent board stands:")
    from . import s7_phase4 as p4

    for league in LEAGUES:
        print(f"  {league:20s} incumbent {p4.INCUMBENT[league]:6.2f} over "
              f"{len(rank.SEASONS_BY_ARM['espn'])} espn seasons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
