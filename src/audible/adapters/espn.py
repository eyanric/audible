"""ESPN adapter -- STUB (lands in Phase 1).

ESPN scoring isn't final (the commish will flip the league from standard to half-PPR)
and the private league needs ``swid``/``espn_s2`` cookies, so this is deliberately not
wired yet. The intended implementation, recorded so the seam is clear:

  * Library: ``cwendt94/espn-api`` -- ``from espn_api.football import League``.
  * Construct:  League(league_id=6012, year=<season>, espn_s2=ESPN_S2, swid=ESPN_SWID)
    (swid MUST keep its curly braces; both cookies from .env, never committed).
  * Projections vs actuals live on BoxPlayer.projected_points / .points
    (via ``league.box_scores(week)`` / ``league.free_agents(...)``).
  * PPR-mismatch guard: read ``league.settings.scoring_format``, find the dict with
    ``id == 53`` (REC); its ``points`` is the live reception value. If it differs from
    the config's ``expected_reception_points``, raise loudly rather than trust it.
"""

from __future__ import annotations

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection, RawPlayerLine

_NOT_WIRED = (
    "ESPN adapter lands in Phase 1: needs swid/espn_s2 cookies and live scoring "
    "reconciliation (target half-PPR vs current standard)."
)


class EspnAdapter:
    name = "espn"

    def __init__(self, swid: str | None = None, espn_s2: str | None = None) -> None:
        self._swid = swid
        self._espn_s2 = espn_s2

    def raw_player_lines(self, config: LeagueConfig) -> list[RawPlayerLine]:
        raise NotImplementedError(_NOT_WIRED)

    def player_projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        raise NotImplementedError(_NOT_WIRED)
