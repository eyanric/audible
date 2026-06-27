"""Draft board (Addendum 01, 2) -- opportunity-adjusted value vs the market's price.

Per league: assemble a draft projection for every rosterable player (opportunity xFP for
matched offense, consensus for IDP/K/DEF, the rookie prior for rookies), run it through
the existing config-driven VORP, then score it against public ADP:

    value = ADP-implied rank − our VORP-implied rank
            (positive => market underpricing relative to earned opportunity => target)

Truth is our VORP, which already encodes each league's structure (superflex + IDP for A,
shallow 1-QB for B), so the same player can be a target in one league and a fade in the
other -- which is the whole product.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection, RawPlayerLine
from ..scoring.engine import score_stat_line
from ..value import compute_vorp, scarcity_values
from .opportunity import OpportunityXfp, carried_value, modeled_xfp, season_opportunity
from .rookies import DraftCapital, draft_capital_factor, load_draft_capital, normalize_name
from .signals import (
    TrajInfo,
    VacatedShares,
    current_team_by_gsis,
    team_vacated_shares,
    trajectory_factors,
)

OFFENSE = frozenset({"QB", "RB", "WR", "TE"})
IDP = frozenset({"DL", "LB", "DB"})

ANNUAL_GAMES = 17  # annualize a player's per-game opportunity rate to a full season
FULL_CONF_GAMES = 14  # >= this many games -> trust opportunity fully; fewer -> shrink to consensus


@dataclass(frozen=True, slots=True)
class _Proj:
    points: float
    model: str  # opportunity | consensus | consensus_fallback | rookie
    modeled: float
    carried: float
    consensus: float
    adp: float | None
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftEntry:
    player_id: str
    name: str
    position: str
    team: str | None
    model: str
    points: float
    modeled_xfp: float
    carried: float
    consensus: float
    vorp: float
    vorp_rank: int
    scarcity: float
    scarcity_rank: int
    adp: float | None
    adp_rank: int | None
    value: int | None  # adp_rank - scarcity_rank (positive => target); scarcity-aware (§6)
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftBoard:
    league_key: str
    entries: list[DraftEntry]  # sorted by vorp_rank


def _adp_for(stats: dict[str, float], primary: str, platform: str) -> float | None:
    sleeper_key = "adp_idp" if primary in IDP else "adp_2qb"
    key = sleeper_key if platform == "sleeper" else "adp_half_ppr"
    value = stats.get(key)
    return value if value and value > 0 else None


# Draft round -> target depth at the player's position (a R1 pick should land ~a starter).
_ROUND_TARGET: dict[int, int] = {1: 12, 2: 24, 3: 40, 4: 60, 5: 80, 6: 100, 7: 120}


def _rookie_floor(
    consensus_by_pos: dict[str, list[float]], position: str, capital: DraftCapital | None
) -> float:
    """Positional consensus value at a draft-capital-implied depth (0 if undrafted/no peers)."""
    if capital is None:
        return 0.0
    peers = consensus_by_pos.get(position)
    if not peers:
        return 0.0
    target = _ROUND_TARGET.get(capital.round, 140)
    return peers[min(target, len(peers) - 1)]


def _project_line(
    line: RawPlayerLine,
    config: LeagueConfig,
    *,
    gsis: str | None,
    opp: dict[str, OpportunityXfp],
    traj: dict[str, TrajInfo],
    vacated: dict[str, VacatedShares],
    teams: dict[str, str],
    dc_by_gsis: dict[str, DraftCapital],
    dc_by_name: dict[str, DraftCapital],
    consensus_by_pos: dict[str, list[float]],
    full_conf_games: int,
) -> _Proj:
    scoring = config.scoring
    primary = line.primary_position
    consensus = score_stat_line(line.stats, scoring)
    adp = _adp_for(line.stats, primary, config.platform.value)
    flags: list[str] = []

    # Rookie: anchor on draft capital (a positional floor) so an early pick is never
    # replacement-level even when consensus hasn't caught up (e.g. a rookie QB ~0).
    if line.years_exp == 0:
        capital = (dc_by_gsis.get(gsis) if gsis else None) or dc_by_name.get(
            normalize_name(line.name)
        )
        branch = "idp" if primary in IDP else "offense" if primary in OFFENSE else "special"
        flags.append(f"rookie:{branch}")
        if capital is not None:
            flags.append(f"R{capital.round}.{capital.pick:03d}")
        floor = _rookie_floor(consensus_by_pos, primary, capital)
        points = max(consensus * draft_capital_factor(capital), floor)
        return _Proj(points, "rookie", 0.0, 0.0, consensus, adp, tuple(flags))

    # Matched offense veteran: annualized opportunity xFP + trajectory + vacated, carried
    # from consensus, then shrunk toward consensus by games played (sample confidence).
    if primary in OFFENSE and gsis is not None and gsis in opp:
        o = opp[gsis]
        annualized = modeled_xfp(o, scoring) * (ANNUAL_GAMES / max(o.games, 1))
        carried = carried_value(line.stats, scoring)
        traj_factor = traj[gsis].factor if gsis in traj else 1.0
        vac = vacated.get(teams.get(gsis, ""))
        vac_factor = 1.0
        if vac is not None:
            if primary in ("WR", "TE"):
                vac_factor = 1.0 + min(0.15, 0.5 * vac.target)
            elif primary == "RB":
                vac_factor = 1.0 + min(0.15, 0.5 * vac.carry)
        opp_proj = annualized * traj_factor * vac_factor + carried
        conf = min(1.0, o.games / full_conf_games)
        points = conf * opp_proj + (1.0 - conf) * consensus
        if traj_factor > 1.10:
            flags.append("riser")
        elif traj_factor < 0.90:
            flags.append("faller")
        if vac_factor > 1.05:
            flags.append(f"vac+{round((vac_factor - 1) * 100)}%")
        if o.games < full_conf_games:
            flags.append(f"{o.games}g")
        return _Proj(points, "opportunity", annualized, carried, consensus, adp, tuple(flags))

    # Offense with no 2025 opportunity row -> consensus fallback (flagged, not replacement).
    if primary in OFFENSE:
        return _Proj(consensus, "consensus_fallback", 0.0, 0.0, consensus, adp, ("no2025",))

    # IDP / K / DEF -> consensus (ff_opportunity is offense-only).
    return _Proj(consensus, "consensus", 0.0, 0.0, consensus, adp, ())


def build_board(
    config: LeagueConfig,
    prior_season: int = 2025,
    cur_season: int = 2026,
    full_conf_games: int = FULL_CONF_GAMES,
) -> DraftBoard:
    from ..adapters.sleeper import SleeperAdapter
    from ..crosswalk import Crosswalk

    with SleeperAdapter() as sleeper:
        lines = sleeper.raw_player_lines(config, season=cur_season)

    xwalk = Crosswalk.from_nflverse()
    opp = season_opportunity([prior_season])
    traj = trajectory_factors(prior_season)
    vacated = team_vacated_shares(prior_season, cur_season)
    teams = current_team_by_gsis(cur_season)
    dc_by_gsis, dc_by_name = load_draft_capital(cur_season)

    # Veteran consensus distribution per position -> rookie floors by draft round.
    consensus_by_pos: dict[str, list[float]] = {}
    for line in lines:
        if line.years_exp == 0:
            continue
        consensus_by_pos.setdefault(line.primary_position, []).append(
            score_stat_line(line.stats, config.scoring)
        )
    for peers in consensus_by_pos.values():
        peers.sort(reverse=True)

    projections: list[PlayerProjection] = []
    meta: dict[str, _Proj] = {}
    for line in lines:
        gsis = xwalk.resolve(line).gsis_id
        proj = _project_line(
            line, config, gsis=gsis, opp=opp, traj=traj, vacated=vacated,
            teams=teams, dc_by_gsis=dc_by_gsis, dc_by_name=dc_by_name,
            consensus_by_pos=consensus_by_pos, full_conf_games=full_conf_games,
        )
        meta[line.player_id] = proj
        projections.append(
            PlayerProjection(
                player_id=line.player_id, name=line.name, primary_position=line.primary_position,
                eligible_positions=line.eligible_positions, team=line.team,
                points=proj.points, stats=line.stats,
            )
        )

    vorp_entries, _ = compute_vorp(projections, config)
    vorp_rank = {e.projection.player_id: i + 1 for i, e in enumerate(vorp_entries)}

    # Scarcity-aware value (VONA) drives the target/fade signal (§6): captures the
    # dropoff slope so flat positions (streamable 1-QB) don't generate false targets.
    scarcity = scarcity_values(projections, config)
    scarcity_rank = {
        pid: i + 1
        for i, (pid, _) in enumerate(
            sorted(scarcity.items(), key=lambda kv: (-kv[1], kv[0]))
        )
    }

    adp_pairs = [(pid, a) for pid, p in meta.items() if (a := p.adp) is not None]
    adp_pairs.sort(key=lambda pair: pair[1])
    adp_rank = {pid: i + 1 for i, (pid, _) in enumerate(adp_pairs)}

    entries: list[DraftEntry] = []
    for e in vorp_entries:
        pid = e.projection.player_id
        m = meta[pid]
        ar = adp_rank.get(pid)
        sr = scarcity_rank[pid]
        entries.append(
            DraftEntry(
                player_id=pid, name=e.projection.name, position=e.projection.primary_position,
                team=e.projection.team, model=m.model, points=m.points,
                modeled_xfp=m.modeled, carried=m.carried, consensus=m.consensus,
                vorp=e.vorp, vorp_rank=vorp_rank[pid], scarcity=scarcity[pid], scarcity_rank=sr,
                adp=m.adp, adp_rank=ar, value=(ar - sr) if ar is not None else None, flags=m.flags,
            )
        )
    return DraftBoard(league_key=config.key, entries=entries)
