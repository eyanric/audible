"""IDP model + data (IDP build directive, data-shaped post-§1).

Shared by the board (production) and the backtest harness (validation), so it lives at
the top level to avoid a draft<->backtest dependency.

The model is stickiness-weighted shrinkage, straight from the §1 measurements: each stat's
next-season projection = w*prior_rate + (1-w)*positional_mean, where w is that stat's
year-over-year stickiness. Sticky stats (LB tackles +0.71) keep their prior; noise (INT
+0.04-0.17) regresses to the positional mean. Crucially, DL sacks are STICKY (+0.58) -- they
keep a high weight and are projected, not regressed, per the §1 correction to the spec.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config.schema import LeagueConfig
from .scoring.engine import score_stat_line

IDP_POSITIONS = ("DL", "LB", "DB")
EXPECTED_GAMES = 17

# Per-(position, scoring-key) year-over-year stickiness, from `audible idp-stickiness`
# (2021-2025, 4 folds). High -> trust prior; low -> regress to the positional mean.
# tackles measured directly; sacks/qb_hit share the pass-rush signal; INT/FF are noise.
STICKINESS_WEIGHTS: dict[str, dict[str, float]] = {
    "LB": {
        "idp_tkl_solo": 0.71, "idp_tkl_ast": 0.71, "idp_tkl_loss": 0.50,
        "idp_sack": 0.59, "idp_qb_hit": 0.59, "idp_pass_def": 0.46,
        "idp_int": 0.17, "idp_ff": 0.10, "idp_fum_rec": 0.10,
    },
    "DL": {
        "idp_tkl_solo": 0.55, "idp_tkl_ast": 0.55, "idp_tkl_loss": 0.50,
        "idp_sack": 0.58, "idp_qb_hit": 0.58, "idp_pass_def": 0.32,
        "idp_int": 0.04, "idp_ff": 0.10, "idp_fum_rec": 0.10,
    },
    "DB": {
        "idp_tkl_solo": 0.42, "idp_tkl_ast": 0.42, "idp_tkl_loss": 0.30,
        "idp_sack": 0.27, "idp_qb_hit": 0.27, "idp_pass_def": 0.43,
        "idp_int": 0.15, "idp_ff": 0.10, "idp_fum_rec": 0.10,
    },
}
PROJECTED_STATS = (
    "idp_tkl_solo", "idp_tkl_ast", "idp_tkl_loss", "idp_sack", "idp_qb_hit",
    "idp_pass_def", "idp_int", "idp_ff", "idp_fum_rec",
)


@dataclass(frozen=True, slots=True)
class PlayerIdp:
    player_id: str
    position: str  # DL / LB / DB bucket
    gp: int
    snaps: float
    stats: dict[str, float]  # raw season-total stat counts (Sleeper vocabulary)


def idp_season(adapter: object, season: int, config: LeagueConfig) -> dict[str, PlayerIdp]:
    """Per-player IDP actuals for one season (Sleeper stats endpoint, League scoring vocab)."""
    from .adapters.sleeper import SleeperAdapter

    assert isinstance(adapter, SleeperAdapter)
    catalog = adapter.get_players_catalog()
    out: dict[str, PlayerIdp] = {}
    for pos in IDP_POSITIONS:
        if pos not in config.positions:
            continue
        for row in adapter.get_stats(season, pos):
            raw = row.get("stats")
            player_id = str(row.get("player_id"))
            if not raw or player_id in out:
                continue
            entry = catalog.get(player_id)
            if entry is None:
                continue
            primary, _ = adapter.classify(entry, config.positions)
            if primary not in IDP_POSITIONS:
                continue
            stats = {k: float(v) for k, v in raw.items() if isinstance(v, int | float)}
            out[player_id] = PlayerIdp(
                player_id=player_id, position=primary,
                gp=int(stats.get("gp", 0)), snaps=float(stats.get("def_snp", 0.0)), stats=stats,
            )
    return out


def _positional_means(prior: dict[str, PlayerIdp], min_games: int) -> dict[str, dict[str, float]]:
    means: dict[str, dict[str, float]] = {}
    for pos in IDP_POSITIONS:
        players = [p for p in prior.values() if p.position == pos and p.gp >= min_games]
        if not players:
            continue
        means[pos] = {
            stat: sum(p.stats.get(stat, 0.0) / p.gp for p in players) / len(players)
            for stat in PROJECTED_STATS
        }
    return means


def idp_projection(
    prior: dict[str, PlayerIdp], config: LeagueConfig, min_games: int = 6
) -> dict[str, float]:
    """player_id -> projected next-season IDP points (League scoring), from prior-season rates.

    Each stat is shrunk toward its positional mean by (1 - stickiness): sticky tackles barely
    move, noisy INT/FF regress hard. DL sacks keep a high weight (projected, not regressed).
    """
    means = _positional_means(prior, min_games)
    out: dict[str, float] = {}
    for player_id, p in prior.items():
        if p.gp < min_games or p.position not in STICKINESS_WEIGHTS:
            continue
        weights = STICKINESS_WEIGHTS[p.position]
        pos_mean = means.get(p.position, {})
        projected: dict[str, float] = {}
        for stat in PROJECTED_STATS:
            prior_rate = p.stats.get(stat, 0.0) / p.gp if p.gp else 0.0
            w = weights.get(stat, 0.1)
            shrunk = w * prior_rate + (1.0 - w) * pos_mean.get(stat, 0.0)
            projected[stat] = shrunk * EXPECTED_GAMES
        out[player_id] = score_stat_line(projected, config.scoring_for(p.position))
    return out
