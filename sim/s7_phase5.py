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

THE POINT PREDICTIONS ARE NOT FITTED. They are the 2019-2025 per-season means, with a 95%
PREDICTION interval for one future season -- t(6, .975) * s * sqrt(1 + 1/7), not the `2 * sd` the
first version of this file shipped, which covers a new draw only about 89% of the time. An OLS
trend IS fitted, but only as the alternative P1 has to discriminate against: all three leagues
decline across the window and the trend extrapolation sits inside the flat interval, so "2026
looks like the seven seasons before it" and "2026 continues the decline" are not separated by the
interval alone. The line that separates them is stated separately and can fail on its own.
"""

from __future__ import annotations

import statistics
import subprocess
import sys

from . import rank
from . import s7_phase2 as p2
from . import s7_weekly as s7

LEAGUES: tuple[str, ...] = ("espn_green_hope", "espn_danger_zone", "sleeper_boyfun")

# t(6, 0.975). Hardcoded rather than pulled from scipy, which is not a dependency of this repo
# and would not be worth adding for one constant. Seven seasons means six degrees of freedom.
T_CRITICAL = 2.446951
AGGREGATION = "weighted"
SCALE = "vorp"


def strongest_lead() -> tuple[str, str, list[tuple[str, float, float]]] | None:
    """The one (term, place) pair that hit at p <= 0.05 in two or more leagues, from disk.

    Returns None when nothing replicated, which is itself a prediction worth writing down.
    """
    import json
    from collections import defaultdict
    from pathlib import Path

    runs = Path(__file__).resolve().parent / "runs"
    rows: list[dict] = []
    for path in sorted(runs.glob("s7-phase[23]-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                record["_name"] = record.get("signal") or record.get("metric")
                rows.append(record)
    hit_leagues: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in rows:
        places = {"board": record.get("p_board")}
        places.update(record.get("p_position") or {})
        for where, value in places.items():
            if value is not None and value <= 0.05:
                hit_leagues[(record["_name"], where)].add(record["league"])
    replicated = {k: v for k, v in hit_leagues.items() if len(v) >= 2}
    if not replicated:
        return None

    def _strength(item: tuple[tuple[str, str], set[str]]) -> tuple[int, float]:
        (name, where), leagues = item
        best = 0.0
        for record in rows:
            if record["_name"] != name or record["league"] not in leagues:
                continue
            effect = (
                record.get("effect_board") if where == "board"
                else (record.get("per_position") or {}).get(where, 0.0)
            )
            best = max(best, abs(effect or 0.0))
        return (len(leagues), best)

    (name, where), leagues = max(replicated.items(), key=_strength)
    detail: list[tuple[str, float, float]] = []
    for record in rows:
        if record["_name"] != name:
            continue
        effect = (
            record.get("effect_board") if where == "board"
            else (record.get("per_position") or {}).get(where)
        )
        p_value = (
            record.get("p_board") if where == "board"
            else (record.get("p_position") or {}).get(where)
        )
        if effect is not None and p_value is not None:
            detail.append((record["league"], float(effect), float(p_value)))
    return (name, where, sorted(detail))


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
    print("A PREDICTION INTERVAL, NOT A CONFIDENCE INTERVAL, and the first version of this file")
    print("shipped the wrong one. `mean +- 2*sd` covers a NEW draw only about 89% of the time at")
    print("n = 7, because it ignores both the uncertainty in the mean and the t-distribution's")
    print("tails. The 95% interval for one future season is mean +- t(6, .975) * s * sqrt(1 +")
    print(f"1/7) = mean +- {T_CRITICAL:.3f} * s * {(1 + 1 / 7) ** 0.5:.4f}, which is 1.31x wider.")
    print("REFUTED if the 2026 mean over weeks 1-17 falls outside it, vorp scale, symmetric.")
    print()
    print("A FLAT PREDICTION CANNOT DISCRIMINATE A TREND, so the trend is stated beside it. All")
    print("three leagues decline across 2019-2025 and the OLS extrapolation for 2026 sits INSIDE")
    print("the flat interval, so P1 holding is consistent with both models. The second line is")
    print("the discriminating one: it says which of the two 2026 will land closer to.")
    print()
    for league in LEAGUES:
        per = per_season_weekly(league)
        seasons = list(per)
        values = list(per.values())
        mean = statistics.mean(values)
        sd = statistics.stdev(values)
        half = T_CRITICAL * sd * (1 + 1 / len(values)) ** 0.5
        n = len(values)
        mean_x = statistics.mean(seasons)
        denominator = sum((x - mean_x) ** 2 for x in seasons)
        slope = sum(
            (x - mean_x) * (y - mean) for x, y in zip(seasons, values, strict=True)
        ) / denominator
        intercept = mean - slope * mean_x
        trend_2026 = intercept + slope * 2026
        print(f"  {league}")
        for season, value in per.items():
            print(f"    {season}  {value:7.3f}")
        print(f"    FLAT  prediction 2026: {mean:7.3f}   95% interval "
              f"[{mean - half:7.3f}, {mean + half:7.3f}]   (s {sd:.3f}, n {n})")
        print(f"    TREND prediction 2026: {trend_2026:7.3f}   "
              f"(OLS slope {slope:+.3f} RWRE per season)")
        print(f"    DISCRIMINATING: 2026 lands closer to the FLAT number "
              f"({mean:.3f}) than to the TREND number ({trend_2026:.3f}).")
    print()

    print("== P2: no term re-tested in 2026 will resolve in more than one league ==")
    print("Phases 2 and 3 ran 24 terms in 3 leagues over 7 seasons. The prediction is that a")
    print("2026 re-run of the same 24 terms produces at most ONE term with RESOLVES in two or")
    print("more leagues. REFUTED by two or more such terms.")
    print()
    print("P2 IS THE WEAKEST PREDICTION HERE AND IS LABELLED AS SUCH. At the observed base rate")
    print("of resolutions, the chance that two or more terms replicate under a pure null is")
    print("roughly 13%, so P2 confirms about seven times in eight whether or not anything is")
    print("real. It is kept because a refutation would be informative and because removing a")
    print("weak prediction after writing it is worse than labelling it.")
    print()

    print("== P3: the strongest surviving lead, whatever it turns out to be ==")
    print("READ FROM THE COMMITTED RECORDS, not typed in. A hardcoded lead becomes a wrong fact")
    print("the moment the adjudication is corrected, and this session corrected it twice.")
    lead = strongest_lead()
    if lead is None:
        print("  NO LEAD. Nothing hit at p <= 0.05 in more than one league under the")
        print("  permutation floor. The prediction is that a 2026 re-run also produces none.")
        print("  REFUTED by any (term, place) pair hitting in two or more leagues in 2026 with")
        print(f"  an effect at or above {p2.MATERIAL} RWRE in both.")
    else:
        name, where, rows = lead
        print(f"  {name} at {where}, the only (term, place) pair hit in two or more leagues:")
        for league, effect, p_value in rows:
            print(f"    {league:18s} effect {effect:+7.4f}  p {p_value:.4f}")
        positive = [league for league, effect, p_value in rows if p_value <= 0.05]
        print("  PREDICTION for 2026, each part refutable on its own:")
        print(f"   a) the effect at {where} is POSITIVE in {' and '.join(positive)}")
        print("   b) its size is between +0.05 and +0.30 RWRE in each of them")
        print("   c) the pattern does NOT extend to the leagues it missed here")
        print("  REFUTED by any of the three failing.")
    print()

    print("== P4: green_hope will still have no composite ==")
    print("No term survived in green_hope, so no composite exists to carry forward. The")
    print("prediction is that a 2026 re-run again produces no composite there with a material")
    print(f"out-of-sample weekly gain, where material is {p2.MATERIAL} RWRE as pre-registered.")
    print("REFUTED by a green_hope composite improving the out-of-sample weekly RWRE by")
    print(f"{p2.MATERIAL} or more.")
    print()

    print("== P5: the hit count will again be what multiple testing predicts ==")
    print("The benchmark is in sim/runs/s7-multiplicity.txt and is the SUM OF EACH TEST'S OWN")
    print("null hit rate, enumerated from its own tie structure -- not a flat 2/41, which the")
    print("adversarial review showed is zero for a test whose floor ties at the maximum. The")
    print("prediction is that a 2026 re-run of the same battery lands within two standard")
    print("deviations of its own expectation, using the overdispersion-corrected sd. REFUTED by")
    print("a hit count more than 2 sd above it.")
    print()

    print("== WHAT WOULD CHANGE THE PRODUCT ==")
    print("None of P1, P2, P4 or P5 coming true changes the draft board: they are predictions")
    print("that the null holds. P3 is the only one whose confirmation would, and it is a")
    print("fraction of an RWRE point at one position against a board error of 34.9 to 48.5.")
    print("The honest summary is that the incumbent board stands:")
    from . import s7_phase4 as p4

    for league in LEAGUES:
        print(f"  {league:20s} incumbent {p4.INCUMBENT[league]:6.2f} over "
              f"{len(rank.SEASONS_BY_ARM['espn'])} espn seasons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
