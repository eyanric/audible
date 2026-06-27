"""Run a single backtest fold and score every method against next-season actuals."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.schema import LeagueConfig
from .data import PlayerSeason, regressed_ppg_baseline, season_actuals
from .metrics import mae, rmse, spearman, top_n_hit_rate, value_test

OFFENSE = ("QB", "RB", "WR", "TE")
MIN_PRIOR_GAMES = 6  # population: meaningful prior-season sample (§2)
MOBILE_QB_RUSH_YD = 300.0  # designed-run / scrambling QB threshold (the Lamar subgroup)


@dataclass(frozen=True, slots=True)
class MethodMetrics:
    method: str  # baseline | consensus | board
    spearman: float
    mae: float
    rmse: float
    hit_rate: float
    n: int


@dataclass(frozen=True, slots=True)
class FoldResult:
    league_key: str
    prior_season: int
    cur_season: int
    population: int
    per_position: dict[str, list[MethodMetrics]]  # [baseline, consensus] per position
    overall_offense: list[MethodMetrics]  # [baseline, consensus] pooled over offense
    value_edge_scarcity: tuple[float, float, float, int, int]
    value_edge_vorp: tuple[float, float, float, int, int]
    mobile_qb: dict[str, float]


def _metrics(
    method: str, ids: list[str], pred: list[float], actual: list[float], n: int
) -> MethodMetrics:
    return MethodMetrics(
        method, spearman(pred, actual), mae(pred, actual), rmse(pred, actual),
        top_n_hit_rate(ids, pred, actual, n), len(ids),
    )


def _hit_n(position: str, size: int) -> int:
    base = {"QB": 12, "TE": 12, "K": 12, "DEF": 12, "RB": 30, "WR": 36}.get(position, 24)
    return min(base, size)


def run_fold(
    config: LeagueConfig,
    prior_season: int,
    cur_season: int,
    market: int = 150,
) -> FoldResult:
    from ..adapters.sleeper import SleeperAdapter
    from ..draft.board import build_board

    board = build_board(config, prior_season, cur_season)
    with SleeperAdapter() as adapter:
        prior: dict[str, PlayerSeason] = season_actuals(adapter, prior_season, config)
        cur: dict[str, PlayerSeason] = season_actuals(adapter, cur_season, config)
    baseline = regressed_ppg_baseline(prior)

    rows: list[dict[str, float | str | int | None]] = []
    for e in board.entries:
        ps, act, base = prior.get(e.player_id), cur.get(e.player_id), baseline.get(e.player_id)
        if ps is None or act is None or base is None or ps.games < MIN_PRIOR_GAMES:
            continue  # veterans only, with a real prior sample and a known outcome
        # Compare both value metrics independently of the league's configured choice.
        sc_value = (e.adp_rank - e.scarcity_rank) if e.adp_rank is not None else None
        vorp_value = (e.adp_rank - e.vorp_rank) if e.adp_rank is not None else None
        rows.append({
            "pos": e.position, "baseline": base, "consensus": e.consensus,
            "actual": act.points, "pid": e.player_id, "adp_rank": e.adp_rank,
            "scarcity_value": sc_value, "vorp_value": vorp_value,
            "prior_rush": ps.stats.get("rush_yd", 0.0),
        })

    # per-position metrics for each method
    per_position: dict[str, list[MethodMetrics]] = {}
    for pos in [p for p in OFFENSE + ("K", "DEF", "DL", "LB", "DB") if p in config.positions]:
        group = [r for r in rows if r["pos"] == pos]
        if len(group) < 5:
            continue
        ids = [str(r["pid"]) for r in group]
        actual = [float(r["actual"]) for r in group]  # type: ignore[arg-type]
        n = _hit_n(pos, len(group))
        per_position[pos] = [
            _metrics(m, ids, [float(r[m]) for r in group], actual, n)  # type: ignore[arg-type]
            for m in ("baseline", "consensus")
        ]

    # pooled offense metrics (the headline: does board beat baseline/consensus overall?)
    off = [r for r in rows if r["pos"] in OFFENSE]
    overall_offense: list[MethodMetrics] = []
    if len(off) >= 5:
        off_ids = [str(r["pid"]) for r in off]
        off_actual = [float(r["actual"]) for r in off]  # type: ignore[arg-type]
        overall_offense = [
            _metrics(m, off_ids, [float(r[m]) for r in off], off_actual, 48)  # type: ignore[arg-type]
            for m in ("baseline", "consensus")
        ]

    # value test (within ADP tier): do targets outscore fades? scarcity (§6) vs raw vorp
    tier = [r for r in rows if r["adp_rank"] is not None and int(r["adp_rank"]) <= market]
    actual_tier = [float(r["actual"]) for r in tier]  # type: ignore[arg-type]
    sc = value_test([float(r["scarcity_value"] or 0) for r in tier], actual_tier)
    vp = value_test([float(r["vorp_value"] or 0) for r in tier], actual_tier)

    # mobile-QB subgroup: is the opportunity model's fade of Lamar-types justified OOS?
    mob = [r for r in rows if r["pos"] == "QB" and float(r["prior_rush"]) >= MOBILE_QB_RUSH_YD]  # type: ignore[arg-type]
    mobile_qb: dict[str, float] = {"n": len(mob)}
    if len(mob) >= 3:
        a = [float(r["actual"]) for r in mob]  # type: ignore[arg-type]
        c = [float(r["consensus"]) for r in mob]  # type: ignore[arg-type]
        mobile_qb |= {
            "mean_actual": sum(a) / len(a), "mean_consensus": sum(c) / len(c),
            "consensus_mae": mae(c, a), "consensus_spearman": spearman(c, a),
        }

    return FoldResult(
        league_key=config.key, prior_season=prior_season, cur_season=cur_season,
        population=len(rows), per_position=per_position,
        overall_offense=overall_offense, value_edge_scarcity=sc, value_edge_vorp=vp,
        mobile_qb=mobile_qb,
    )
