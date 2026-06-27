"""IDP thesis validation (IDP build prompt, §1) -- the stickiness analysis.

Run BEFORE any tackle model: is prior-season tackle rate predictive of next season, per
IDP position, and are big plays noise? Data + model live in ``audible.idp``; this is the
year-over-year diagnostic that shaped the model's stickiness weights.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config.schema import LeagueConfig
from ..idp import IDP_POSITIONS, PlayerIdp, idp_season
from .metrics import spearman


def _rate(stat: str) -> Callable[[PlayerIdp], float | None]:
    return lambda p: p.stats.get(stat, 0.0) / p.gp if p.gp else None


def _tkl_rate(p: PlayerIdp) -> float | None:
    if not p.gp:
        return None
    return (p.stats.get("idp_tkl_solo", 0.0) + p.stats.get("idp_tkl_ast", 0.0)) / p.gp


# metric name -> per-player per-game rate (None when undefined).
METRICS: dict[str, Callable[[PlayerIdp], float | None]] = {
    "solo/gm": _rate("idp_tkl_solo"),
    "solo/snap": lambda p: p.stats.get("idp_tkl_solo", 0.0) / p.snaps if p.snaps else None,
    "tkl/gm": _tkl_rate,
    "sack/gm": _rate("idp_sack"),
    "int/gm": _rate("idp_int"),
    "pd/gm": _rate("idp_pass_def"),
}
STICKY_METRICS = ("solo/gm", "solo/snap", "tkl/gm")
NOISE_METRICS = ("sack/gm", "int/gm", "pd/gm")


def stickiness(
    adapter: object,
    seasons: list[int],
    config: LeagueConfig,
    min_games: int = 8,
    min_snaps: float = 200.0,
) -> dict[tuple[str, str], tuple[float, int]]:
    """(position, metric) -> (year-over-year Spearman, n), pooled over all consecutive folds.

    Population: players with >= min_games and >= min_snaps in BOTH seasons of a pair (real
    defenders, meaningful samples), staying in the same IDP position.
    """
    by_season = {s: idp_season(adapter, s, config) for s in seasons}
    pairs = list(zip(seasons, seasons[1:], strict=False))

    results: dict[tuple[str, str], tuple[float, int]] = {}
    for pos in IDP_POSITIONS:
        if pos not in config.positions:
            continue
        for name, rate in METRICS.items():
            xs: list[float] = []
            ys: list[float] = []
            for y0, y1 in pairs:
                prev, nxt = by_season[y0], by_season[y1]
                for pid, a in prev.items():
                    b = nxt.get(pid)
                    if b is None or a.position != pos or b.position != pos:
                        continue
                    if a.gp < min_games or b.gp < min_games:
                        continue
                    if a.snaps < min_snaps or b.snaps < min_snaps:
                        continue
                    va, vb = rate(a), rate(b)
                    if va is None or vb is None:
                        continue
                    xs.append(va)
                    ys.append(vb)
            results[(pos, name)] = (spearman(xs, ys), len(xs))
    return results
