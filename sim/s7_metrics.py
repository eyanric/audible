"""S7 phase 3 -- new metrics. Inventing them is explicitly in scope.

Each metric here is a function from a weekly scope to `gsis_id -> value`, so phase 2's
adjudication machinery runs over it unchanged: leave-one-season-out strength selection, a floor
matched to the metric's own coverage, a reference-set p, and a pre-registered locus.

THE BOARD TODAY READS ONE INPUT and discards everything else the file it was built from already
holds. Every weekly FFA export carries, per player and unused: a standard deviation for every
stat, an `injury_status`, a `birthdate` and a `draft_year`. Four of the metrics below are just
those columns, read.

WHY EACH ONE MIGHT WORK, stated before it is measured:

  `inj_status` -- the file says a player is Out and the board ranks him anyway. The question is
      not whether being Out matters, it is whether the PROJECTION has already priced it. If FFA
      fully discounts an inactive player the metric is inert and G4 will say so.
      ABSENCE IS INFORMATION HERE, uniquely among the metrics in this project. Everywhere else a
      missing value means "not measured" and earns no adjustment. An injury report is a
      published list: not being on it is a claim that the player is healthy, so no designation
      maps to 0.0 rather than to no adjustment.

  `true_age` -- `signals.age_at_export` is stamped at export time, not at the season it
      describes: 1,395 of 1,397 year-over-year transitions have delta exactly 0.0, and the offset
      against `ff_playerids.birthdate` is +7.50 years in 2019 and +0.95 in 2025. The weekly files
      carry `birthdate` directly, so age at the week is computable and the defect is fixable
      rather than merely documented.

  `true_experience` -- `season_year - draft_year`, both in the file. `ffa_experience` is the
      vendor's own count and this is the arithmetic; they should agree, and if they do not, one
      of them is wrong.

  `weekly_sd_rel` -- the projection's own dispersion for THIS week, from the paired `_sd`
      columns, relative to its mean. At equal projected points, prefer the player the projection
      is more confident about. The seasonal `uncertainty` signal used a season-level `sd_rel`;
      this is the per-week quantity, which exists in all 612 files and has never been read.

  `role_change_snaps` -- THE ONE THE HANDOFF CALLS THE MOST PROMISING. Usage failed preseason
      because a projection already prices a KNOWN role. A role that has just changed is where the
      market has not caught up, and that is only visible week to week. Constructed strictly from
      information available before the week: snap share in week N-1 minus the player's mean over
      the four weeks before that.

  `role_change_proj` -- the same idea read from the market instead of the world: this week's
      league-scored FFA projection minus last week's. If FFA re-prices a role faster than it
      re-prices points, this leads; if slower, it lags and the snap version should win.

WHAT IS DELIBERATELY NOT HERE. Nothing in this module reads the week being scored. `role_change`
stops at week N-1; `weekly_sd_rel` and `inj_status` read week N's own projection file, which is
published before the games and is the same file the board is built from.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from . import rank
from . import s7_weekly as s7

# Severity, not probability. The codes that appear across the corpus are NA, Q, D, O, IR and S;
# anything else is REPORTED rather than silently folded into 0.0, because a code nobody has seen
# before is a schema change and this project has already been bitten by one (`route` at 2023).
INJURY_SEVERITY: dict[str, float] = {
    "": 0.0, "NA": 0.0,
    "Q": -1.0,    # questionable
    "D": -2.0,    # doubtful
    "O": -3.0,    # out
    "IR": -3.0,   # injured reserve
    "S": -3.0,    # suspended
    "PUP": -3.0,
    "NFI": -3.0,
    "DNR": -3.0,
}

# Snap share is keyed on pfr ids and everything else here on gsis, so one crosswalk is needed.
SNAP_LOOKBACK = 4  # weeks of baseline behind the most recent observed week

# A DATA DEFECT FOUND BY BUILDING `true_age`, AND THE REASON THAT METRIC NEEDS A GUARD.
#
# `birthdate` uses the UNIX EPOCH AS A NULL SENTINEL. Measured over the whole weekly weighted
# slice, 177,885 rows: 7,723 of them (4.3%) carry `1970-01-01`, and 19,786 (11.1%) are blank or
# NA. The epoch rate is 0.0% in 2015-2017, appears in 2018 at 2.4%, peaks at 14.4% in 2021 and
# falls to 1.6% in 2025. Read as a date it makes Jake Browning, Tim Boyle and Kyle Trask all
# exactly 54.8 years old in 2024 week 8 -- which is how it was found, because the oldest six
# players on the board shared one age to four significant figures.
#
# So the sentinel is treated as ABSENT, and a plausibility band is applied on top: a
# professional football player is between 18 and 50, and anything outside that is a second
# sentinel nobody has found yet rather than a fact about a player. Both counts are reported.
EPOCH_SENTINEL = "1970-01-01"
PLAUSIBLE_AGE = (18.0, 50.0)

# `season_year - draft_year`. An undrafted player can carry a 0 and a sentinel year would show up
# as a two-digit experience, so the band is stated and violations are counted.
PLAUSIBLE_EXPERIENCE = (0.0, 30.0)


@dataclass(slots=True)
class WeeklyMeta:
    """The columns of a weekly export that the board throws away."""

    season: int
    week: int
    injury: dict[str, float] = field(default_factory=dict)
    age: dict[str, float] = field(default_factory=dict)
    experience: dict[str, float] = field(default_factory=dict)
    sd_points: dict[str, float] = field(default_factory=dict)
    unknown_status: dict[str, int] = field(default_factory=dict)
    epoch_birthdates: int = 0
    implausible_age: int = 0
    implausible_experience: int = 0
    missing_birthdate: int = 0


def _cell(text: str) -> float:
    value = text.strip()
    if value in ("", "NA", "N/A", "null"):
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


@lru_cache(maxsize=512)
def weekly_meta(season: int, week: int, league_key: str,
                aggregation: str = "weighted") -> WeeklyMeta:
    """Read `injury_status`, `birthdate`, `draft_year` and the paired sds for one scope.

    THE SD IS COMBINED ASSUMING INDEPENDENCE across stats: sqrt(sum((w_i * sd_i)^2)). That is an
    assumption and it is the wrong one -- a quarterback's passing yards and passing touchdowns are
    positively correlated, so the true sd is larger. The alternative, sum(|w_i| * sd_i), assumes
    perfect correlation and is an upper bound. Both are monotone in the same direction and only
    the ORDERING is used, so the choice changes the level and barely the rank; independence is
    taken because it is the conventional default and because the corpus ships no covariances.

    A SECOND CODE PATH READS THE SAME FILE AS `build_board`. It reads only metadata and the sd
    columns -- never the point estimates, which stay the single responsibility of `build_board` --
    so the two cannot disagree about a projection. They could disagree about which rows exist, so
    this applies the identical position filter and mfl->gsis join.
    """
    path = s7.corpus_path(season, week, aggregation)
    crosswalk = rank.crosswalk("mfl_id")
    config = s7.league_config(league_key)
    weights_by_position: dict[str, dict[str, float]] = {}

    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline=""))
    header = next(reader)
    column = {name: i for i, name in enumerate(header)}
    paired = [c for c in s7.STAT_KEYS if c in column and f"{c}_sd" in column]
    meta = WeeklyMeta(season=season, week=week)
    # Mid-season, so a birthday inside the season is handled rather than rounded away.
    as_of = dt.date(season, 9, 1) + dt.timedelta(days=7 * (week - 1))

    for row in reader:
        if len(row) != len(header):
            continue
        pos = s7.room.canon_position(row[column["position"]])
        if pos not in s7.OFFENSIVE:
            continue
        gsis = crosswalk.get(row[column["id"]])
        if gsis is None:
            continue

        status = row[column["injury_status"]].strip().upper() if "injury_status" in column else ""
        if status not in INJURY_SEVERITY:
            meta.unknown_status[status] = meta.unknown_status.get(status, 0) + 1
        severity = INJURY_SEVERITY.get(status, 0.0)
        # A player under two team aliases keeps the WORSE designation: an Out row and a healthy
        # row for the same player is the injury report disagreeing with itself, and the safe
        # reading of that is the one that does not start him.
        meta.injury[gsis] = min(severity, meta.injury.get(gsis, 0.0))

        birth = row[column["birthdate"]].strip() if "birthdate" in column else ""
        if birth.startswith(EPOCH_SENTINEL):
            meta.epoch_birthdates += 1
        elif not birth or birth in ("NA", "N/A"):
            meta.missing_birthdate += 1
        else:
            try:
                born = dt.date.fromisoformat(birth[:10])
            except ValueError:
                born = None
            if born is not None:
                years = (as_of - born).days / 365.25
                if PLAUSIBLE_AGE[0] <= years <= PLAUSIBLE_AGE[1]:
                    meta.age[gsis] = years
                else:
                    meta.implausible_age += 1

        drafted = _cell(row[column["draft_year"]]) if "draft_year" in column else 0.0
        if drafted > 1900:
            years_in = float(season) - drafted
            if PLAUSIBLE_EXPERIENCE[0] <= years_in <= PLAUSIBLE_EXPERIENCE[1]:
                meta.experience[gsis] = years_in
            else:
                meta.implausible_experience += 1

        weights = weights_by_position.get(pos)
        if weights is None:
            weights = dict(config.scoring_for(pos))
            weights_by_position[pos] = weights
        variance = 0.0
        for name in paired:
            weight = weights.get(s7.STAT_KEYS[name], 0.0)
            if weight:
                variance += (weight * _cell(row[column[f"{name}_sd"]])) ** 2
        combined = math.sqrt(variance)
        if combined > meta.sd_points.get(gsis, 0.0):
            meta.sd_points[gsis] = combined
    return meta


@lru_cache(maxsize=16)
def _snap_shares(season: int) -> dict[int, dict[str, float]]:
    """week -> gsis_id -> offensive snap share, for one season. Weekly, from `snap_counts_s3`."""
    import polars as pl

    path = rank.CACHE / "nflverse" / "snap_counts_s3.parquet"
    if not path.exists():
        raise rank.PreflightError(f"snap counts pin missing: {path}")
    crosswalk = rank.crosswalk("pfr_id")
    frame = pl.read_parquet(
        path, columns=["season", "week", "game_type", "pfr_player_id", "offense_pct"]
    ).filter((pl.col("season") == season) & (pl.col("game_type") == "REG"))
    out: dict[int, dict[str, float]] = {}
    for row in frame.iter_rows(named=True):
        gsis = crosswalk.get(str(row["pfr_player_id"]))
        if gsis is None:
            continue
        share = row["offense_pct"]
        if share is None:
            continue
        week = int(row["week"])
        held = out.setdefault(week, {})
        # Two rows for one player in one week means two games, which does not happen in the
        # regular season; keep the larger rather than summing a percentage.
        if float(share) > held.get(gsis, -1.0):
            held[gsis] = float(share)
    return out


@lru_cache(maxsize=512)
def role_change_snaps(season: int, week: int) -> dict[str, float]:
    """Snap share in week-1 minus the mean over the `SNAP_LOOKBACK` weeks before that.

    STRICTLY BEFORE THE WEEK BEING SCORED. Week N reads weeks N-1 back to N-5 and never N.
    Week 1 has no history and returns nothing rather than a zero -- an absence, not a claim.
    """
    if week < 3:
        return {}
    shares = _snap_shares(season)
    recent = shares.get(week - 1, {})
    if not recent:
        return {}
    baseline_weeks = [w for w in range(max(1, week - 1 - SNAP_LOOKBACK), week - 1) if w in shares]
    if not baseline_weeks:
        return {}
    out: dict[str, float] = {}
    for gsis, share in recent.items():
        history = [shares[w][gsis] for w in baseline_weeks if gsis in shares[w]]
        if not history:
            continue
        out[gsis] = share - (sum(history) / len(history))
    return out


@lru_cache(maxsize=512)
def role_change_proj(season: int, week: int, league_key: str,
                     aggregation: str = "weighted") -> dict[str, float]:
    """This week's league-scored projection minus last week's, per player.

    CACHED, and the cost is the reason: without it the floor calls this 40 more times per
    scope and each call reads two 1 MB CSVs through `build_board`. Callers must treat the
    returned dict as read-only.

    The market's own re-pricing rather than the world's. Week 1 has no predecessor and returns
    nothing. Uses `build_board` on both scopes, so it cannot disagree with the board under test
    about what the projection is.
    """
    if week < 2:
        return {}
    try:
        now = s7.build_board(season, week, league_key, aggregation=aggregation)
        before = s7.build_board(season, week - 1, league_key, aggregation=aggregation)
    except s7.ScopeMissing:
        return {}
    return {
        gsis: points - before.projected[gsis]
        for gsis, points in now.projected.items()
        if gsis in before.projected
    }


# --- the metric table: name -> a callable with the phase-2 signature ------------------------


def inj_status(board: Any, season: int, week: int, league: str) -> dict[str, float]:
    meta = weekly_meta(season, week, league)
    # Every player on the board gets a value, including 0.0 for "not on the injury report".
    return {gsis: meta.injury.get(gsis, 0.0) for gsis in board.projected}


def true_age(board: Any, season: int, week: int, league: str) -> dict[str, float]:
    meta = weekly_meta(season, week, league)
    # Negated so the signal INCREASES with what it claims is good, like every other term here.
    return {gsis: -age for gsis, age in meta.age.items() if gsis in board.projected}


def true_experience(board: Any, season: int, week: int, league: str) -> dict[str, float]:
    meta = weekly_meta(season, week, league)
    return {gsis: value for gsis, value in meta.experience.items() if gsis in board.projected}


def weekly_sd_rel(board: Any, season: int, week: int, league: str) -> dict[str, float]:
    """Relative dispersion, negated: HIGHER means the projection is more confident.

    Players with a projection at or below zero are omitted rather than divided into: a relative
    dispersion needs a level to be relative to.
    """
    meta = weekly_meta(season, week, league)
    out: dict[str, float] = {}
    for gsis, points in board.projected.items():
        sd = meta.sd_points.get(gsis)
        if sd is None or points <= 0.0:
            continue
        out[gsis] = -(sd / points)
    return out


def snap_role_change(board: Any, season: int, week: int, league: str) -> dict[str, float]:
    values = role_change_snaps(season, week)
    return {gsis: value for gsis, value in values.items() if gsis in board.projected}


def proj_role_change(board: Any, season: int, week: int, league: str) -> dict[str, float]:
    values = role_change_proj(season, week, league)
    return {gsis: value for gsis, value in values.items() if gsis in board.projected}


METRICS: dict[str, Any] = {
    "inj_status": inj_status,
    "true_age": true_age,
    "true_experience": true_experience,
    "weekly_sd_rel": weekly_sd_rel,
    "role_change_snaps": snap_role_change,
    "role_change_proj": proj_role_change,
}
