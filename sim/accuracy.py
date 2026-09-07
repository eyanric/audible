"""TASK B4/1 -- how good the pre-registered projection actually is.

A PROJECTION THAT IS BARELY BETTER THAN NOTHING MAKES EVERY ARM HARDER TO READ, so this number
is reported before any arm number and is reported whatever it says. It is not a gate on the
projection and nothing here is allowed to change `sim/projection.py`: the pre-registration is
fixed, and a poor score is a fact about the projection rather than a reason to re-fit it.

WHAT IS COMPARED. The projected line is scored under the same weights and the same historical
deltas the outcome measure uses -- `config.scoring_for(position)` overlaid with
`roundtrip.HISTORICAL_DELTAS` -- and compared against the player's realised season total from
`weekly.weekly_points`, which is what every arm is ultimately scored on. Scoring both sides
with one function is the point: an accuracy number computed against a differently-scored target
would be measuring the scoring difference.

TWO KNOWN BIASES, both downward and both common-mode across arms:

  RETURN YARDS. The realised total pays 0.04 a return yard, six for a return touchdown and six
  for a fumble-recovery touchdown. The scoring vocabulary carries none of the three, so the
  projected line cannot express them and every return specialist is under-projected. Measured
  below as `return_share`.

  KICKERS AND DEFENCES, and the two are not the same case. D/ST has no rows in
  `player_stats` at all, in any of the five seasons. Kickers DO have rows -- 568 to 570 a
  season, 542 to 545 of them regular-season -- and they are scored, to 0.0 in 2021-2024 and to
  0.6 in 2025, because `roundtrip.COLUMN_TO_KEY` carries no kicking columns. Either way both
  project to zero and realise (almost) zero, so both are excluded from the correlation, which
  would otherwise be inflated by a large block of true zeros predicted as zeros.

THE BASELINE IS THE MARKET, AND THE POOLED COMPARISON IS A TRAP. A correlation on its own
says nothing about whether a projection is worth having, so ADP rank is scored the same way on
the same players. But the POOLED rank correlation flatters the projection and adversarial
review caught it: the projection predicts points, and ADP in a one-QB league deliberately does
not rank quarterbacks by points. Quarterbacks sit at a mean ADP rank of 115 while scoring twice
what anyone else scores, so pooling positions hands the projection an easy win it does not earn
-- deleting quarterbacks alone lifts ADP's pooled figure by 0.09 to 0.16, more than the whole
margin the projection wins by.

So the pooled figure is reported for continuity and the WITHIN-POSITION figures are the ones to
read. Both are printed. Within position, on this projection, the market wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import projection, room, weekly
from .roundtrip import HISTORICAL_DELTAS

# Positions with a scoreable stat line. K and DEF are excluded; see the module docstring.
SCOREABLE: tuple[str, ...] = ("QB", "RB", "WR", "TE")


@dataclass(frozen=True, slots=True)
class Accuracy:
    season: int
    position: str
    n: int
    corr: float
    mae: float
    realised_mean: float
    projected_mean: float
    # Spearman of ADP rank against realised points, over the same players, so the projection
    # has something to be better or worse than.
    adp_corr: float
    return_share: float


def score_line(stats: dict[str, float], position: str, config: object) -> float:
    """A projected stat line -> league points, under the outcome measure's own weights."""
    from audible.scoring.engine import score_stat_line

    weights = {**config.scoring_for(position), **HISTORICAL_DELTAS}  # type: ignore[attr-defined]
    return score_stat_line(stats, weights)


def _pearson(xs: list[float], ys: list[float]) -> float:
    corr, _slope = room._pearson(xs, ys)
    return corr


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation. ADP is an ordering, so its agreement with points is a rank question."""

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for place, i in enumerate(order, start=1):
            out[i] = float(place)
        return out

    return _pearson(ranks(xs), ranks(ys))


def measure(season: int, config: object) -> tuple[list[Accuracy], dict[str, float]]:
    """(per-position accuracy, whole-season summary) for one target season."""
    lines = projection.project(season, config)
    table = weekly.weekly_points(season)
    board = room.load_board(season)
    fit = {s: projection.season_totals(s) for s in (season,)}

    # DRAFTABLE ROWS ONLY. `projection.project` also emits an undraftable tail so replacement
    # level has a real pool to find a baseline in; those players are not on the market's board
    # and scoring the projection against them would be measuring a different question.
    by_id = {line.player_id: line for line in lines.lines}
    rows: list[tuple[str, float, float, float, float]] = []
    for row in board.rows:
        line = by_id[f"{projection.DRAFTABLE_PREFIX}{row.rank:04d}"]
        if row.position not in SCOREABLE:
            continue
        gsis = projection._resolve(row, fit)
        if gsis is None:
            # No realised season to compare against: he never played. Excluded rather than
            # scored as a zero, which would reward the projection for players who did not
            # exist and punish it for rookies it had no way to place.
            continue
        weeks = table.points.get(gsis)
        if not weeks:
            continue
        realised = sum(weeks.values())
        projected = score_line(dict(line.stats), row.position, config)
        # What the projection structurally cannot see, so the gap is attributable.
        returns = _return_points(gsis, season)
        rows.append((row.position, projected, realised, float(row.rank), returns))

    out: list[Accuracy] = []
    for position in SCOREABLE:
        block = [r for r in rows if r[0] == position]
        if len(block) < 3:
            continue
        proj = [r[1] for r in block]
        real = [r[2] for r in block]
        adp = [r[3] for r in block]
        rets = [r[4] for r in block]
        out.append(
            Accuracy(
                season=season, position=position, n=len(block),
                corr=round(_pearson(proj, real), 4),
                mae=round(sum(abs(p - r) for p, r in zip(proj, real, strict=True)) / len(block), 2),
                realised_mean=round(sum(real) / len(block), 2),
                projected_mean=round(sum(proj) / len(block), 2),
                # Negated: a LOW adp rank should go with HIGH points, so the raw rank
                # correlation is negative and the sign is flipped to make the two comparable.
                adp_corr=round(-_spearman(adp, real), 4),
                return_share=round(sum(rets) / max(1e-9, sum(real)), 4),
            )
        )

    proj_all = [r[1] for r in rows]
    real_all = [r[2] for r in rows]
    adp_all = [r[3] for r in rows]
    summary = {
        "n": float(len(rows)),
        "corr": round(_pearson(proj_all, real_all), 4) if len(rows) > 2 else 0.0,
        "spearman": round(_spearman(proj_all, real_all), 4) if len(rows) > 2 else 0.0,
        "adp_spearman": round(-_spearman(adp_all, real_all), 4) if len(rows) > 2 else 0.0,
        "mae": round(
            sum(abs(p - r) for p, r in zip(proj_all, real_all, strict=True)) / max(1, len(rows)), 2
        ),
        "matched": float(lines.matched),
        "rookies": float(lines.rookies),
        "unmatched": float(lines.unmatched),
    }
    return out, summary


def _return_points(gsis: str, season: int) -> float:
    """The points the vocabulary cannot express, for one player-season. Reported, not fixed."""
    import polars as pl

    from .roundtrip import (
        FUMBLE_RECOVERY_TD_POINTS,
        RETURN_TD_POINTS,
        RETURN_YARD_POINTS,
        bucket25,
    )

    frame = _return_frame(season)
    rows = frame.filter(pl.col("player_id") == gsis)
    total = 0.0
    for row in rows.iter_rows(named=True):
        total += RETURN_YARD_POINTS * (
            bucket25(float(row.get("punt_return_yards") or 0.0))
            + bucket25(float(row.get("kickoff_return_yards") or 0.0))
        )
        total += RETURN_TD_POINTS * float(row.get("special_teams_tds") or 0.0)
        total += FUMBLE_RECOVERY_TD_POINTS * float(row.get("fumble_recovery_tds") or 0.0)
    return total


_RETURN_CACHE: dict[int, Any] = {}


def _return_frame(season: int) -> Any:
    import polars as pl

    if season not in _RETURN_CACHE:
        path, _root = room.resolve_input(f"nflverse/player_stats_{season}.parquet")
        _RETURN_CACHE[season] = (
            pl.read_parquet(path)
            .filter(pl.col("season_type") == "REG")
            .select(
                [
                    "player_id",
                    "punt_return_yards",
                    "kickoff_return_yards",
                    "special_teams_tds",
                    "fumble_recovery_tds",
                ]
            )
            .fill_null(0)
        )
    return _RETURN_CACHE[season]


def report(config: object) -> dict[str, object]:
    """Accuracy for every usable target season. This is G3."""
    seasons: dict[str, object] = {}
    for season in projection.USABLE:
        rows, summary = measure(season, config)
        seasons[str(season)] = {
            "summary": summary,
            "by_position": {
                r.position: {
                    "n": r.n, "corr": r.corr, "mae": r.mae,
                    "realised_mean": r.realised_mean, "projected_mean": r.projected_mean,
                    "adp_spearman": r.adp_corr, "return_share": r.return_share,
                }
                for r in rows
            },
        }
    return {
        "usable_seasons": list(projection.USABLE),
        "excluded_seasons": [s for s in projection.SEASONS if s not in projection.USABLE],
        "excluded_because": (
            "no prior season inside the pinned window; player_stats_2020 exists in neither "
            "cache root and this session does not substitute a nearby season"
        ),
        "seasons": seasons,
    }
