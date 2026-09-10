"""S3 Task 1 -- WHERE the board's error actually is, measured rather than hypothesised.

Every board this project has built came from a hypothesis. `audible#85` then searched 4,000 of
them over eight knobs and the winner was 2.522 RWRE WORSE on a holdout. Reweighting information
the board already has does not work.

So this asks a different question: take the residual -- how far a player finished from where he
was projected -- and regress it on things knowable BEFORE the season. Two outputs matter:

  * a RANKING of candidate signals by measured explanatory power, rather than by which blog
    post was most recent;
  * a CEILING. If everything together explains 4% of residual variance, no weighting scheme
    will move the board much, and that is the most useful number this session can produce.

IT CANNOT OVERFIT THE BOARD, because no board is being chosen. It is a description of where
error lives. Coefficients are still fit on early seasons and checked on later ones, because a
coefficient that flips sign across seasons is noise whatever its t-statistic.

RESIDUAL SIGN, fixed once: `residual = realised_rank - projected_rank`, within position, within
season. POSITIVE means he finished WORSE than projected -- a bust. NEGATIVE means he
outperformed -- a sleeper.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import arms, rank

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "sim-cache"
FFA_DIR = REPO / "sim" / "data" / "ffa"

# Every predictor here must be knowable BEFORE the season is played. Each is named with where
# it comes from, because "is this a leak?" is the only question that matters about a feature.
PREDICTORS: tuple[str, ...] = (
    "age",                 # FFA preseason projection file, vintage
    "experience",          # FFA preseason projection file, vintage
    "sd_rel",              # sd_pts / points -- projection dispersion, FFA preseason
    "spread_rel",          # (ceiling - floor) / points, FFA preseason
    "dropoff",             # FFA preseason: points above the next player at the position
    "adp_gap",             # projection position-rank minus ADP position-rank, FFA preseason
    "prior_games",         # games with a row in season-1, player_stats
    "prior_tgt_share",     # mean weekly target share in season-1
    "prior_ay_share",      # mean weekly air-yards share in season-1
    "prior_snap_share",    # mean offensive snap share in season-1, snap_counts
    "td_oe",               # season-1 touchdowns minus expected, ff_opportunity
    "draft_round",         # static, draft_picks
    "career_outlier",      # season-1 per-game points vs the player's own prior mean
)

SEASONS: tuple[int, ...] = (2019, 2020, 2021, 2022, 2023, 2024, 2025)
EARLY: tuple[int, ...] = (2019, 2020, 2021, 2022)
LATE: tuple[int, ...] = (2023, 2024, 2025)


# --- vintage FFA metadata -------------------------------------------------------------------


@lru_cache(maxsize=16)
def ffa_meta(season: int) -> dict[str, dict[str, float]]:
    """gsis_id -> the vintage preseason metadata FFA published that year.

    The projections file carries `age`, `experience`, `sd_pts`, `dropoff`, `floor`, `ceiling`
    and `adp` but no id, so it is joined to `raw_stats` (which has the MFL id) on name and
    position within the same season, and from there to gsis.
    """
    proj = FFA_DIR / f"projections_{season}_wk0.csv"
    raw = FFA_DIR / f"raw_stats_{season}_wk0.csv"
    if not proj.exists() or not raw.exists():
        raise rank.PreflightError(f"FFA files missing for {season}")

    by_key: dict[tuple[str, str], str] = {}
    draft_year: dict[str, str] = {}
    with raw.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = ((row.get("player") or "").strip().lower(), (row.get("position") or "").strip())
            mfl = (row.get("id") or "").strip()
            if key[0] and mfl:
                by_key.setdefault(key, mfl)
                draft_year.setdefault(mfl, (row.get("draft_year") or "").strip())

    xw = rank.crosswalk("mfl_id")
    out: dict[str, dict[str, float]] = {}
    with proj.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = ((row.get("player") or "").strip().lower(), (row.get("position") or "").strip())
            mfl = by_key.get(key)
            gsis = xw.get(mfl) if mfl else None
            if not gsis:
                continue

            def num(name: str, _row: dict = row) -> float | None:
                v = (_row.get(name) or "").strip()
                try:
                    return float(v)
                except ValueError:
                    return None

            pts = num("points") or 0.0
            sd = num("sd_pts")
            ceil_, floor_ = num("ceiling"), num("floor")
            out[gsis] = {
                "points": pts,
                "age": num("age") or float("nan"),
                "experience": num("experience") or float("nan"),
                "sd_rel": (sd / pts) if (sd is not None and pts > 0) else float("nan"),
                "spread_rel": (
                    ((ceil_ - floor_) / pts)
                    if (ceil_ is not None and floor_ is not None and pts > 0)
                    else float("nan")
                ),
                "dropoff": num("dropoff") if num("dropoff") is not None else float("nan"),
                "adp": num("adp") if num("adp") is not None else float("nan"),
                "position": row.get("position") or "",
            }
    return out


# --- prior-season nflverse facts -------------------------------------------------------------


@lru_cache(maxsize=16)
def prior_facts(season: int) -> dict[str, dict[str, float]]:
    """Everything observed in season-1, by gsis id. Empty when season-1 is not pinned."""
    import polars as pl

    out: dict[str, dict[str, float]] = {}
    ps = CACHE / "nflverse" / f"player_stats_{season - 1}.parquet"
    if ps.exists():
        f = pl.read_parquet(ps).filter(pl.col("season_type") == "REG").fill_null(0)
        agg = f.group_by("player_id").agg([
            pl.len().alias("games"),
            pl.col("target_share").mean().alias("tgt"),
            pl.col("air_yards_share").mean().alias("ay"),
            pl.col("fantasy_points_ppr").sum().alias("pts"),
        ])
        for pid, games, tgt, ay, pts in agg.iter_rows():
            out.setdefault(str(pid), {}).update({
                "prior_games": float(games),
                "prior_tgt_share": float(tgt or 0.0),
                "prior_ay_share": float(ay or 0.0),
                "prior_ppg": float(pts or 0.0) / max(1.0, float(games)),
            })

    snaps = CACHE / "nflverse" / "snap_counts_s3.parquet"
    if snaps.exists():
        f = pl.read_parquet(snaps)
        if "season" in f.columns and "offense_pct" in f.columns and "pfr_player_id" in f.columns:
            sub = f.filter(pl.col("season") == season - 1)
            agg = sub.group_by("pfr_player_id").agg(
                pl.col("offense_pct").mean().alias("snap")
            )
            pfr = rank.crosswalk("pfr_id")
            for pid, snap in agg.iter_rows():
                g = pfr.get(str(pid))
                if g:
                    out.setdefault(g, {})["prior_snap_share"] = float(snap or 0.0)

    opp = CACHE / "nflverse" / "ff_opportunity_s3.parquet"
    if opp.exists():
        f = pl.read_parquet(opp)
        sub = f.filter(pl.col("season") == str(season - 1))
        if sub.height == 0:
            sub = f.filter(pl.col("season") == season - 1)
        if sub.height:
            agg = sub.group_by("player_id").agg([
                pl.col("total_touchdown").sum().alias("td"),
                pl.col("total_touchdown_exp").sum().alias("td_exp"),
            ])
            for pid, td, td_exp in agg.iter_rows():
                out.setdefault(str(pid), {})["td_oe"] = float(td or 0.0) - float(td_exp or 0.0)
    return out


@lru_cache(maxsize=1)
def draft_round() -> dict[str, float]:
    import polars as pl

    p = CACHE / "nflverse" / "draft_picks_s3.parquet"
    if not p.exists():
        return {}
    f = pl.read_parquet(p)
    col = "gsis_id" if "gsis_id" in f.columns else None
    if col is None or "round" not in f.columns:
        return {}
    return {
        str(g): float(r)
        for g, r in f.select([col, "round"]).drop_nulls().iter_rows()
    }


@lru_cache(maxsize=16)
def career_mean_before(season: int) -> dict[str, float]:
    """A player's mean per-game points across every pinned season STRICTLY BEFORE season-1."""
    import polars as pl

    tot: dict[str, list[float]] = {}
    for s in range(2019, season - 1):
        p = CACHE / "nflverse" / f"player_stats_{s}.parquet"
        if not p.exists():
            continue
        f = pl.read_parquet(p).filter(pl.col("season_type") == "REG").fill_null(0)
        agg = f.group_by("player_id").agg([
            pl.len().alias("g"), pl.col("fantasy_points_ppr").sum().alias("pts")
        ])
        for pid, g, pts in agg.iter_rows():
            if g:
                tot.setdefault(str(pid), []).append(float(pts) / float(g))
    return {p: sum(v) / len(v) for p, v in tot.items() if v}


# --- the feature table ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Row:
    gsis: str
    season: int
    position: str
    residual: float
    x: dict[str, float]


def table(season: int, source: str, league_key: str = "espn_green_hope") -> list[Row]:
    """One season's residuals and predictors, for one projection source."""
    loaded = arms.load(source, season, league_key)
    realised = rank.realised_per_game(season, league_key)
    rv = rank.realised_vorp(realised)

    meta = ffa_meta(season)
    prior = prior_facts(season)
    rounds = draft_round()
    career = career_mean_before(season)

    rows: list[Row] = []
    for pos in rank.SCOREABLE:
        members = [
            p for p, q in loaded.position.items()
            if q == pos and p in loaded.points and p in rv
        ]
        if len(members) < 20:
            continue
        proj_rank = {
            p: i + 1
            for i, p in enumerate(sorted(members, key=lambda q: (-loaded.points[q], q)))
        }
        real_rank = {
            p: i + 1 for i, p in enumerate(sorted(members, key=lambda q: (-rv[q], q)))
        }
        for p in members:
            m = meta.get(p, {})
            pr = prior.get(p, {})
            adp = m.get("adp")
            # ADP gap in POSITION-RANK space: both sides are ranks, so the difference is
            # "the market likes him more/less than the projection does".
            adp_gap = float("nan")
            if adp is not None and adp == adp and adp > 0:
                adp_gap = float("nan")  # filled below, needs the positional ADP ordering
            prior_ppg = pr.get("prior_ppg")
            cm = career.get(p)
            outlier = (
                (prior_ppg - cm) if (prior_ppg is not None and cm is not None) else float("nan")
            )
            rows.append(Row(
                gsis=p, season=season, position=pos,
                residual=float(real_rank[p] - proj_rank[p]),
                x={
                    "age": m.get("age", float("nan")),
                    "experience": m.get("experience", float("nan")),
                    "sd_rel": m.get("sd_rel", float("nan")),
                    "spread_rel": m.get("spread_rel", float("nan")),
                    "dropoff": m.get("dropoff", float("nan")),
                    "adp_gap": adp_gap,
                    "prior_games": pr.get("prior_games", float("nan")),
                    "prior_tgt_share": pr.get("prior_tgt_share", float("nan")),
                    "prior_ay_share": pr.get("prior_ay_share", float("nan")),
                    "prior_snap_share": pr.get("prior_snap_share", float("nan")),
                    "td_oe": pr.get("td_oe", float("nan")),
                    "draft_round": rounds.get(p, float("nan")),
                    "career_outlier": outlier,
                },
            ))
        # adp_gap needs the positional ADP ordering, so it is filled once the group is known
        have_adp = [p for p in members if (meta.get(p, {}).get("adp") or 0) > 0]
        if len(have_adp) >= 20:
            adp_rank = {
                p: i + 1
                for i, p in enumerate(sorted(have_adp, key=lambda q: meta[q]["adp"]))
            }
            for r in rows:
                if r.position == pos and r.gsis in adp_rank:
                    r.x["adp_gap"] = float(proj_rank[r.gsis] - adp_rank[r.gsis])
    return rows


# --- a small OLS, since numpy is not a dependency ---------------------------------------------


def _standardise(vals: list[float]) -> tuple[list[float], float, float]:
    good = [v for v in vals if v == v]
    if len(good) < 5:
        return [0.0] * len(vals), 0.0, 1.0
    mu = sum(good) / len(good)
    var = sum((v - mu) ** 2 for v in good) / max(1, len(good) - 1)
    sd = math.sqrt(var) or 1.0
    return [((v - mu) / sd if v == v else 0.0) for v in vals], mu, sd


def ols(y: list[float], xs: list[list[float]]) -> tuple[list[float], float]:
    """Least squares with an intercept, via normal equations. Returns (betas, r_squared)."""
    n = len(y)
    k = len(xs)
    if n <= k + 1:
        return [0.0] * k, 0.0
    cols = [[1.0] * n, *xs]
    m = k + 1
    a = [[sum(cols[i][t] * cols[j][t] for t in range(n)) for j in range(m)] for i in range(m)]
    b = [sum(cols[i][t] * y[t] for t in range(n)) for i in range(m)]
    for i in range(m):  # Gaussian elimination with partial pivoting
        piv = max(range(i, m), key=lambda r: abs(a[r][i]))
        if abs(a[piv][i]) < 1e-12:
            return [0.0] * k, 0.0
        a[i], a[piv] = a[piv], a[i]
        b[i], b[piv] = b[piv], b[i]
        for r in range(i + 1, m):
            f = a[r][i] / a[i][i]
            for c in range(i, m):
                a[r][c] -= f * a[i][c]
            b[r] -= f * b[i]
    beta = [0.0] * m
    for i in range(m - 1, -1, -1):
        beta[i] = (b[i] - sum(a[i][j] * beta[j] for j in range(i + 1, m))) / a[i][i]
    fitted = [sum(beta[j] * cols[j][t] for j in range(m)) for t in range(n)]
    ybar = sum(y) / n
    ss_tot = sum((v - ybar) ** 2 for v in y)
    ss_res = sum((y[t] - fitted[t]) ** 2 for t in range(n))
    return beta[1:], (1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
