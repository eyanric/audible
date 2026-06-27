"""IDP thesis validation (IDP build prompt, §1) -- run BEFORE any tackle model.

The entire IDP edge rests on one assumption: tackle volume is sticky and role-predictable
year over year, while big plays (sacks/INT/passes-defended) are noise. This measures it
directly -- prior-season rate vs next-season rate, per IDP position, pooled over folds --
the IDP equivalent of the mobile-QB diagnostic. If tackles aren't sticky, the thesis is
dead and we don't build the model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..config.schema import LeagueConfig
from .metrics import spearman

IDP_POSITIONS = ("DL", "LB", "DB")


@dataclass(frozen=True, slots=True)
class PlayerIdp:
    player_id: str
    position: str
    gp: int
    snaps: float
    solo: float
    assist: float
    sack: float
    intc: float
    pd: float


# metric name -> per-player rate (None when undefined).
METRICS: dict[str, Callable[[PlayerIdp], float | None]] = {
    "solo/gm": lambda p: p.solo / p.gp if p.gp else None,
    "solo/snap": lambda p: p.solo / p.snaps if p.snaps else None,
    "tkl/gm": lambda p: (p.solo + p.assist) / p.gp if p.gp else None,
    "sack/gm": lambda p: p.sack / p.gp if p.gp else None,
    "int/gm": lambda p: p.intc / p.gp if p.gp else None,
    "pd/gm": lambda p: p.pd / p.gp if p.gp else None,
}
STICKY_METRICS = ("solo/gm", "solo/snap", "tkl/gm")
NOISE_METRICS = ("sack/gm", "int/gm", "pd/gm")


def idp_season(adapter: object, season: int, config: LeagueConfig) -> dict[str, PlayerIdp]:
    """Per-player IDP actuals for one season (tackles, big plays, snaps), from Sleeper."""
    from ..adapters.sleeper import SleeperAdapter

    assert isinstance(adapter, SleeperAdapter)
    catalog = adapter.get_players_catalog()
    out: dict[str, PlayerIdp] = {}
    for pos in IDP_POSITIONS:
        if pos not in config.positions:
            continue
        for row in adapter.get_stats(season, pos):
            stats = row.get("stats")
            player_id = str(row.get("player_id"))
            if not stats or player_id in out:
                continue
            entry = catalog.get(player_id)
            if entry is None:
                continue
            primary, _ = adapter.classify(entry, config.positions)
            if primary not in IDP_POSITIONS:
                continue
            out[player_id] = PlayerIdp(
                player_id=player_id, position=primary,
                gp=int(stats.get("gp", 0)), snaps=float(stats.get("def_snp", 0) or 0),
                solo=float(stats.get("idp_tkl_solo", 0) or 0),
                assist=float(stats.get("idp_tkl_ast", 0) or 0),
                sack=float(stats.get("idp_sack", 0) or 0),
                intc=float(stats.get("idp_int", 0) or 0),
                pd=float(stats.get("idp_pass_def", 0) or 0),
            )
    return out


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
