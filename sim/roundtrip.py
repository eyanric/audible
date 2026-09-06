"""GATE G4 -- do summed weekly rows reproduce ESPN's season total?

G1-G3 establish that weekly rows exist, are complete, and are reachable from a board. This
asks the remaining question: are they the SAME NUMBERS the league actually paid? If summing
a player's weeks does not reproduce what ESPN put on his season, then every bootstrap drawn
from those weeks is measuring a different game from the one that was played.

The comparison is between two INDEPENDENT sources -- nflverse charting on the left, ESPN's
own `appliedTotal` on the right -- so agreement to the cent is a strong statement and any
residual is a real, nameable difference rather than rounding.

## Which rulebook

The handoff asks for `espn_green_hope`'s scoring. That is not satisfiable as written, and
the reason is worth stating rather than papering over:

* The only ESPN season totals on disk for 2021-2024 belong to league **6012**, which is
  `espn_davis_drive`. `espn_green_hope` (73131979) is a 2026 league; its earliest stat lines
  are 2025. There is nothing of green_hope's to round-trip against before then.
* The two configs differ in exactly three keys: `pass_td` (green_hope 6, davis_drive 4),
  `rec` (0.0 vs 0.5, with davis_drive overriding RB to 0.0) and `pts_allow_35p`. Scoring
  6012's totals under green_hope's table mis-scores every quarterback by exactly
  2 x passing TDs -- Joe Burrow's 2024 lands 92.7 points high.

So the round-trip runs under **6012's own historical rulebook**, and the one place that
differs from the committed `espn_davis_drive` TOML is documented below. This is a
measurement of what the league paid in 2021-2025; it deliberately changes no config, because
the committed file describes 2026 and is correct for it.

## The model, term by term -- every one of these was measured, not assumed

* `rec = 0.0`. 6012 paid nothing per reception in all five seasons. Under the committed
  `rec = 0.5` the 2024 receivers come out 0.5 x receptions high -- Ja'Marr Chase by exactly
  63.5, his 127 catches. The commissioner's move to half-PPR is a 2026 change.
* `pass_yd` in ESPN's 25-YARD BUCKETS, not raw yards. ESPN pays statId 8, whole 25-yard
  units, which the repo already models in `adapters/espn.py`. With raw 0.04/yd only 3 of 77
  quarterbacks reproduce; with the bucket, all 77 do.
  The bucket TRUNCATES TOWARD ZERO -- `int(y / 25)`, not `math.floor`. They differ on a
  negative week: a quarterback sacked for a net -2 passing yards scores 0 at ESPN, while
  floor would award a -25 bucket and take a point off his season.
* `fum_lost` from `fumbles_lost_total`, NOT the sum of the three per-phase fumble columns.
  They disagree for 21-30 offensive players a season, at 2 points each.
* Return yards paid at 0.04/yd in 25-yard buckets, with **punt and kickoff bucketed
  SEPARATELY** -- ESPN carries them as different stats, and bucketing the combined figure
  loses the remainder on each. Separating them is worth 4-5 points of exactness a season.
* Return touchdowns (`special_teams_tds`) and fumble-recovery touchdowns
  (`fumble_recovery_tds`) at 6. Neither has a key in our scoring vocabulary.

`fumble_recovery_tds` is the answer to the question the handoff asks about **statId 63**.
`docs/STATE.md` records it as unmapped and quantifies it on the ESPN side. It DOES apply
here: nflverse carries the same event in `fumble_recovery_tds`, our vocabulary has no key
for it, and it is worth exactly 6.00 points when it happens. It is rare -- a handful of
players a season -- but it is a clean 6.00 whenever it lands, so it is paid explicitly here
rather than left in the residual.

## What is deliberately NOT gated

**Kickers.** Not because they are inconvenient -- because the configs say so. Both ESPN
league files describe their kicker block as "declarative only: K and D/ST are never
translated", the board marks them SOURCE_SPECIALIST and takes ESPN's own league-applied
total, and `verify-scoring` does not compare them either. The table was never meant to
reproduce a kicker's season from a stat line, so a gate asserting that it does would be
inventing a requirement the codebase explicitly disclaims. Measured, our kicker sums run
3-12 points high across the board. They are counted, printed, and excluded from the gate,
and that number is the standing evidence if anyone ever decides to translate kickers.

**Team D/ST.** `player_stats` has no team-defence rows at all; there is nothing to sum.

Run it:

    uv run --extra nflverse python -m sim.roundtrip
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)

# The league whose season totals are on disk for every season: 6012 == espn_davis_drive.
LEAGUE_KEY = "espn_davis_drive"
ESPN_ACTUALS = "espn_actuals_6012_{season}.json"

# 6012 paid zero per reception in 2021-2025; the committed TOML's 0.5 describes 2026.
HISTORICAL_DELTAS: dict[str, float] = {"rec": 0.0}

# Positions the gate covers. K is excluded for a config reason named in the module docstring.
OFFENSE: frozenset[str] = frozenset({"QB", "RB", "WR", "TE", "FB"})

# Points per unit for the three effects ESPN pays and our scoring vocabulary has no key for.
RETURN_YARD_POINTS = 0.04
RETURN_TD_POINTS = 6.0
FUMBLE_RECOVERY_TD_POINTS = 6.0
BUCKET = 25.0

# nflverse column -> scoring vocabulary key. pass_yd is handled separately (it is bucketed).
COLUMN_TO_KEY: dict[str, str] = {
    "passing_tds": "pass_td",
    "passing_interceptions": "pass_int",
    "passing_2pt_conversions": "pass_2pt",
    "rushing_yards": "rush_yd",
    "rushing_tds": "rush_td",
    "rushing_2pt_conversions": "rush_2pt",
    "receptions": "rec",
    "receiving_yards": "rec_yd",
    "receiving_tds": "rec_td",
    "receiving_2pt_conversions": "rec_2pt",
    "fumbles_lost_total": "fum_lost",
}

# Measured exact-reproduction rates are 99.2 / 100.0 / 99.8 / 99.6 / 99.3 percent for
# 2021-2025. The gate sits at 99.0 -- below the worst season with a little headroom, rather
# than snug against it, because a threshold fitted to the sample it was measured on is not a
# threshold. A season that drops through this floor means the mapping has broken, not that
# one more return specialist had an odd week.
MIN_EXACT_SHARE = 0.99
EXACT = 0.01


def bucket25(yards: float) -> float:
    """Whole 25-yard units, truncated TOWARD ZERO.

    `int()` rather than `math.floor` is load-bearing on negative weeks: a quarterback with
    net -2 passing yards scores 0 at ESPN, and floor would hand him a -25 bucket.
    """
    return BUCKET * int(yards / BUCKET)


@dataclass(frozen=True, slots=True)
class RoundTripReport:
    season: int
    n: int
    exact: int
    median_abs_error: float
    max_abs_error: float
    kickers_n: int
    kickers_exact: int
    residuals: tuple[tuple[str, float], ...]

    @property
    def exact_share(self) -> float:
        return self.exact / self.n if self.n else 0.0

    @property
    def ok(self) -> bool:
        return self.n > 0 and self.exact_share >= MIN_EXACT_SHARE


def score_weekly_rows(frame: Any, config: Any) -> dict[str, float]:
    """Sum every player's REGULAR-SEASON weeks under the historical 6012 rulebook.

    Regular season only. ESPN's season total is a regular-season number -- scoring REG+POST
    inflates every playoff participant, and the postseason rows are in the pinned files.
    """
    import polars as pl

    from audible.scoring.engine import score_stat_line

    reg = frame.filter(pl.col("season_type") == "REG").fill_null(0)
    totals: dict[str, float] = {}
    weights_cache: dict[str, dict[str, float]] = {}

    for row in reg.iter_rows(named=True):
        position = str(row.get("position") or "")
        weights = weights_cache.get(position)
        if weights is None:
            weights = {**config.scoring_for(position), **HISTORICAL_DELTAS}
            weights_cache[position] = weights

        stats = {key: float(row.get(col) or 0.0) for col, key in COLUMN_TO_KEY.items()}
        stats["pass_yd"] = bucket25(float(row.get("passing_yards") or 0.0))
        points = score_stat_line(stats, weights)

        # The three effects ESPN pays that our vocabulary cannot express.
        punt = bucket25(float(row.get("punt_return_yards") or 0.0))
        kick = bucket25(float(row.get("kickoff_return_yards") or 0.0))
        points += RETURN_YARD_POINTS * (punt + kick)
        points += RETURN_TD_POINTS * float(row.get("special_teams_tds") or 0.0)
        points += FUMBLE_RECOVERY_TD_POINTS * float(row.get("fumble_recovery_tds") or 0.0)

        player = str(row["player_id"])
        totals[player] = totals.get(player, 0.0) + points
    return totals


def espn_to_gsis(cache: Path) -> dict[str, str]:
    import polars as pl

    ids = pl.read_parquet(cache / "nflverse" / "ff_playerids.parquet")
    out: dict[str, str] = {}
    for espn_id, gsis in zip(
        ids["espn_id"].to_list(), ids["gsis_id"].to_list(), strict=True
    ):
        if espn_id and gsis:
            out[str(espn_id).split(".")[0]] = str(gsis)
    return out


def round_trip(season: int, cache: Path, config: Any) -> RoundTripReport:
    from audible.adapters.cache import FrameCache

    frame = FrameCache(cache).get(f"player_stats_{season}")
    if frame is None:
        raise FileNotFoundError(f"player_stats_{season} is not pinned in {cache}")

    actuals = json.loads(
        (cache / ESPN_ACTUALS.format(season=season)).read_text(encoding="utf-8")
    )
    ours = score_weekly_rows(frame, config)
    crosswalk = espn_to_gsis(cache)

    position_of = dict(
        zip(frame["player_id"].to_list(), frame["position"].to_list(), strict=True)
    )
    name_of = dict(
        zip(frame["player_id"].to_list(), frame["player_display_name"].to_list(), strict=True)
    )

    errors: list[float] = []
    residuals: list[tuple[str, float]] = []
    kickers = kickers_exact = 0

    for espn_id, espn_total in actuals.items():
        if not espn_total:
            continue
        gsis = crosswalk.get(str(espn_id))
        if not gsis or gsis not in ours:
            continue
        position = position_of.get(gsis)
        delta = float(espn_total) - ours[gsis]
        if position == "K":
            kickers += 1
            kickers_exact += abs(delta) <= EXACT
            continue
        if position not in OFFENSE:
            continue
        errors.append(abs(delta))
        if abs(delta) > EXACT:
            residuals.append((str(name_of.get(gsis, gsis)), round(delta, 2)))

    if not errors:
        return RoundTripReport(season, 0, 0, 0.0, 0.0, kickers, kickers_exact, ())

    return RoundTripReport(
        season=season,
        n=len(errors),
        exact=sum(1 for e in errors if e <= EXACT),
        median_abs_error=statistics.median(errors),
        max_abs_error=max(errors),
        kickers_n=kickers,
        kickers_exact=kickers_exact,
        residuals=tuple(sorted(residuals, key=lambda r: -abs(r[1]))),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim.roundtrip",
        description="Gate G4: summed weekly rows vs ESPN season totals for league 6012.",
    )
    parser.add_argument("--cache", type=Path, default=REPO / "data" / "cache")
    parser.add_argument("--seasons", type=int, nargs="+", default=list(SEASONS))
    parser.add_argument("--verbose", action="store_true", help="name every residual")
    args = parser.parse_args(argv)

    from audible.config.loader import load_all_leagues

    config = load_all_leagues()[LEAGUE_KEY]

    print(f"rulebook: {LEAGUE_KEY} with historical deltas {HISTORICAL_DELTAS}")
    print(f"gate: at least {MIN_EXACT_SHARE:.0%} of offensive seasons exact to {EXACT}")
    print()

    failures = 0
    for season in args.seasons:
        report = round_trip(season, args.cache, config)
        state = "PASS" if report.ok else "FAIL"
        print(
            f"{season}: {state} offense n={report.n} "
            f"exact={report.exact} ({report.exact_share * 100:.1f}%) "
            f"median={report.median_abs_error:.2f} max={report.max_abs_error:.2f}"
        )
        print(
            f"      kickers (not gated) {report.kickers_exact}/{report.kickers_n} exact"
            f" | residuals {len(report.residuals)}"
        )
        if args.verbose:
            for name, delta in report.residuals:
                print(f"        {name}: ESPN minus ours = {delta:+.2f}")
        if not report.ok:
            failures += 1

    print()
    if failures:
        print(f"{failures} season(s) below the exactness floor")
        return 1
    print(f"{len(args.seasons)} season(s) round-trip within tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
