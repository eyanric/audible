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
from .rookies import DraftCapital, load_draft_capital, normalize_name
from .signals import (
    TrajInfo,
    VacatedShares,
    current_team_by_gsis,
    team_vacated_shares,
    trajectory_factors,
)

OFFENSE = frozenset({"QB", "RB", "WR", "TE"})
IDP = frozenset({"DL", "LB", "DB"})

ANNUAL_GAMES = 17  # annualize a player's per-game opportunity rate to a full season (overlay only)

# `build_board` reads Sleeper stat lines for EVERY league and scores them through that
# league's own weights. For League B that means the projections are Sleeper's even though
# the scoring is ESPN's, and the two vocabularies do not line up everywhere. Shown on the
# board rather than kept in a doc, because a number you cannot see the caveat on is a number
# you will trust. Delete this constant and its one caller when `build_board` reads from the
# platform adapter.
SLEEPER_SOURCED_CAVEAT = (
    "!! SLEEPER-SOURCED BOARD -- projections are Sleeper's stat lines scored through this\n"
    "   league's own weights, not ESPN's. QB runs ~2% high (ESPN pays passing yards in\n"
    "   25-yard buckets, the Sleeper line is scored 0.04/yd continuously); D/ST\n"
    "   yards-allowed and kicker miss distance are unmodelled."
)


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
    position: str  # VORP primary bucket
    eligible_positions: frozenset[str]  # every slot-eligible position (hybrids: DE -> DL+LB)
    team: str | None
    model: str
    points: float
    modeled_xfp: float
    carried: float
    consensus: float
    vorp: float
    vorp_rank: int
    # The three ranks stay three numbers, deliberately. Consensus is the projection of record,
    # VORP applies this league's replacement baselines, and opportunity is the overlay that
    # disagrees with both. Collapsing them hides the disagreement, which is the signal.
    consensus_rank: int
    opp_rank: int
    deviation: bool  # opportunity departs from consensus by more than DEVIATION_BAND ranks
    scarcity: float
    scarcity_rank: int
    adp: float | None
    adp_rank: int | None
    value: int | None  # adp_rank - (league-configured value rank); positive => target
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftBoard:
    league_key: str
    entries: list[DraftEntry]  # sorted by vorp_rank


# Sleeper encodes "undrafted in this market" as 999.0 rather than omitting the key. 91% of the
# catalog (7158/7861 on adp_2qb, 2026-08-15) carries it, so treating it as a real ADP inflates
# every rank and makes `value` meaningless for anyone deep on the board.
_ADP_UNDRAFTED = 999.0

# How far the opportunity overlay may diverge from consensus before we flag it. The overlay
# does not drive the ranking (consensus won the out-of-sample gate), so this raises a marker
# rather than clamping a number -- the disagreement is shown, never silently resolved.
DEVIATION_BAND = 18


def _adp_for(stats: dict[str, float], adp_market: str) -> float | None:
    """This league's ADP for a player, or None when the market never drafts him."""
    value = stats.get(adp_market)
    if value is None or value <= 0 or value >= _ADP_UNDRAFTED:
        return None
    return value


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
) -> _Proj:
    primary = line.primary_position
    # Position-scoped: League B pays receptions to WR/TE but not RB, so the weights a player
    # is scored against depend on what he is. Flat-scoring leagues get `config.scoring` back
    # unchanged. The opportunity overlay below uses the same resolved table, or it would
    # disagree with consensus for a reason that has nothing to do with opportunity.
    scoring = config.scoring_for(primary)
    consensus = score_stat_line(line.stats, scoring)
    adp = _adp_for(line.stats, config.adp_market)
    flags: list[str] = []

    # Rookie: plain consensus. Draft capital is surfaced as a flag and priced ZERO times here,
    # because consensus already prices it. Measured over the 204 rookies with known capital
    # (2026 class): mean consensus by draft round runs 125.8 / 58.8 / 38.0 / 22.5 / 15.0 /
    # 12.2 / 4.3, and Spearman(overall pick, consensus points) is -0.424. Multiplying by a
    # capital tilt on top of that counted the same signal twice -- it was adding +32.6 to
    # Jeremiyah Love and +32.9 to Sonny Styles, enough to move Love from ~#13 to #8 overall.
    #
    # This is the same rule the rest of the board already follows: consensus is the projection
    # of record, and a second view of a signal consensus has already priced becomes a flag,
    # never a multiplier. (The earlier round-keyed floor was a worse version of the same
    # mistake -- it overwrote the projection outright, pinning a QB3 projected 12.6 pts to
    # 286.7 and flattening whole rookie classes into ties.)
    if line.years_exp == 0:
        capital = (dc_by_gsis.get(gsis) if gsis else None) or dc_by_name.get(
            normalize_name(line.name)
        )
        branch = "idp" if primary in IDP else "offense" if primary in OFFENSE else "special"
        flags.append(f"rookie:{branch}")
        if capital is not None:
            flags.append(f"R{capital.round}.{capital.pick:03d}")
        return _Proj(consensus, "rookie", 0.0, 0.0, consensus, adp, tuple(flags))

    # Post-gate: CONSENSUS is the projection of record -- it beat our opportunity model
    # out-of-sample at every position. For matched offense we still compute the opportunity
    # view, but only as an OVERLAY tilt surfaced via flags; it never drives the ranking.
    if primary in OFFENSE and gsis is not None and gsis in opp:
        o = opp[gsis]
        annualized = modeled_xfp(o, scoring) * (ANNUAL_GAMES / max(o.games, 1))
        traj_factor = traj[gsis].factor if gsis in traj else 1.0
        vac = vacated.get(teams.get(gsis, ""))
        vac_factor = 1.0
        if vac is not None:
            if primary in ("WR", "TE"):
                vac_factor = 1.0 + min(0.15, 0.5 * vac.target)
            elif primary == "RB":
                vac_factor = 1.0 + min(0.15, 0.5 * vac.carry)
        opp_view = annualized * traj_factor * vac_factor + carried_value(line.stats, scoring)
        gap = opp_view - consensus
        if gap > 20:
            flags.append(f"opp+{gap:.0f}")  # opportunity sees upside vs consensus (buy tilt)
        elif gap < -20:
            flags.append(f"opp{gap:.0f}")  # opportunity sees downside (sell tilt)
        if traj_factor > 1.10:
            flags.append("riser")
        elif traj_factor < 0.90:
            flags.append("faller")
        if vac_factor > 1.05:
            flags.append(f"vac+{round((vac_factor - 1) * 100)}%")
        return _Proj(consensus, "consensus", opp_view, 0.0, consensus, adp, tuple(flags))

    # IDP / K / DEF / offense without an opportunity row -> consensus.
    return _Proj(consensus, "consensus", 0.0, 0.0, consensus, adp, ())


def build_board(
    config: LeagueConfig,
    prior_season: int = 2025,
    cur_season: int = 2026,
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

    projections: list[PlayerProjection] = []
    meta: dict[str, _Proj] = {}
    for line in lines:
        gsis = xwalk.resolve(line).gsis_id
        proj = _project_line(
            line, config, gsis=gsis, opp=opp, traj=traj, vacated=vacated,
            teams=teams, dc_by_gsis=dc_by_gsis, dc_by_name=dc_by_name,
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

    # The other two of the three displayed ranks. The opportunity view only exists for matched
    # offense; everyone else falls back to consensus so the column is never empty and the two
    # ranks stay comparable over one population.
    def _ranked(score: dict[str, float]) -> dict[str, int]:
        return {
            pid: i + 1
            for i, (pid, _) in enumerate(sorted(score.items(), key=lambda kv: (-kv[1], kv[0])))
        }

    consensus_rank = _ranked({pid: m.consensus for pid, m in meta.items()})
    opp_rank = _ranked({
        pid: (m.modeled if m.modeled > 0 else m.consensus) for pid, m in meta.items()
    })

    # League-aware value metric (learned from the backtest): VORP for deep/scarce formats,
    # scarcity/VONA for shallow/flat ones.
    value_rank = scarcity_rank if config.value_metric == "scarcity" else vorp_rank

    # value = ADP rank - our value rank, but BOTH ranks must span the same population or the
    # difference measures universe size instead of market disagreement: ADP covers ~712 players
    # while the board carries ~7.6k, which alone drives a deep player to -7000. So re-rank our
    # value densely across exactly the players the market prices.
    market_value_rank = {
        pid: i + 1
        for i, pid in enumerate(sorted(adp_rank, key=lambda pid: value_rank[pid]))
    }

    entries: list[DraftEntry] = []
    for e in vorp_entries:
        pid = e.projection.player_id
        m = meta[pid]
        ar = adp_rank.get(pid)
        entries.append(
            DraftEntry(
                player_id=pid, name=e.projection.name, position=e.projection.primary_position,
                eligible_positions=e.projection.eligible_positions,
                team=e.projection.team, model=m.model, points=m.points,
                modeled_xfp=m.modeled, carried=m.carried, consensus=m.consensus,
                vorp=e.vorp, vorp_rank=vorp_rank[pid],
                consensus_rank=consensus_rank[pid], opp_rank=opp_rank[pid],
                deviation=abs(opp_rank[pid] - consensus_rank[pid]) > DEVIATION_BAND,
                scarcity=scarcity[pid],
                scarcity_rank=scarcity_rank[pid], adp=m.adp, adp_rank=ar,
                value=(ar - market_value_rank[pid]) if ar is not None else None, flags=m.flags,
            )
        )
    return DraftBoard(league_key=config.key, entries=entries)
