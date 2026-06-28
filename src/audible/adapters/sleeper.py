"""Sleeper adapter -- open, read-only, no auth.

Two hosts:
  * ``api.sleeper.app/v1`` -- documented league/roster/player endpoints.
  * ``api.sleeper.com``    -- undocumented projections/stats (source: Rotowire).

Projections ship only std/half/full-PPR point totals (no IDP, no custom bonuses),
so this adapter never trusts those precomputed points -- it recomputes every player's
value from the raw stat line through the deterministic scoring engine against the
league's own scoring weights.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection, RawPlayerLine
from ..scoring.engine import score_stat_line
from .cache import JsonCache

BASE_APP = "https://api.sleeper.app/v1"
BASE_COM = "https://api.sleeper.com"

# httpx accepts repeated query keys (e.g. position[]) as a list of (key, value) tuples.
_Params = list[tuple[str, str | int | float | bool | None]]

# Sleeper's granular `position` -> the league's fantasy-position bucket.
POSITION_TO_BUCKET: dict[str, str] = {
    "QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DEF": "DEF",
    "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL",
    "OLB": "LB", "ILB": "LB", "MLB": "LB", "LB": "LB",
    "CB": "DB", "SS": "DB", "FS": "DB", "S": "DB", "DB": "DB",
}

PLAYERS_CACHE_KEY = "sleeper_players_nfl"
PLAYERS_TTL_S = 24 * 3600  # pull the ~15 MB catalog at most once a day

# Cross-source ids carried from the catalog for the nflverse opportunity join.
_ID_FIELDS = ("gsis_id", "espn_id", "yahoo_id", "sportradar_id", "rotowire_id")


class SleeperAdapter:
    name = "sleeper"

    def __init__(self, cache: JsonCache | None = None, timeout: float = 30.0) -> None:
        self._cache = cache if cache is not None else JsonCache()
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "audible/0.1 (+personal)"}
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SleeperAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- raw endpoints -----------------------------------------------------
    def _get(self, url: str, params: _Params | None = None) -> Any:
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_league(self, league_id: str) -> dict[str, Any]:
        return self._get(f"{BASE_APP}/league/{league_id}")

    def get_rosters(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"{BASE_APP}/league/{league_id}/rosters")

    def get_users(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"{BASE_APP}/league/{league_id}/users")

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        return self._get(f"{BASE_APP}/draft/{draft_id}")

    def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        """Live picks as they come off the board (player_id, pick_no, round, draft_slot)."""
        return self._get(f"{BASE_APP}/draft/{draft_id}/picks")

    def get_players_catalog(self, *, force: bool = False) -> dict[str, Any]:
        if not force:
            cached = self._cache.get(PLAYERS_CACHE_KEY, PLAYERS_TTL_S)
            if cached is not None:
                return cached
        catalog: dict[str, Any] = self._get(f"{BASE_APP}/players/nfl")
        self._cache.set(PLAYERS_CACHE_KEY, catalog)
        return catalog

    def get_projections(
        self, season: int, position: str, week: int | None = None
    ) -> list[dict[str, Any]]:
        suffix = f"/{week}" if week is not None else ""
        url = f"{BASE_COM}/projections/nfl/{season}{suffix}"
        params: _Params = [
            ("season_type", "regular"),
            ("position[]", position),
            ("order_by", "pts_half_ppr"),
        ]
        return self._get(url, params=params)

    def get_stats(
        self, season: int, position: str, week: int | None = None
    ) -> list[dict[str, Any]]:
        """Actual stats (season totals when week is None) -- the backtest answer key.

        Same stat-key vocabulary as projections, incl. IDP (idp_tkl_solo, ...) and ``gp``,
        so league-correct actuals come straight through the scoring engine.
        """
        suffix = f"/{week}" if week is not None else ""
        url = f"{BASE_COM}/stats/nfl/{season}{suffix}"
        params: _Params = [("season_type", "regular"), ("position[]", position)]
        return self._get(url, params=params)

    # --- normalisation -----------------------------------------------------
    @staticmethod
    def classify(
        catalog_entry: dict[str, Any], league_positions: frozenset[str]
    ) -> tuple[str | None, frozenset[str]]:
        """Map a catalog entry to (primary bucket, eligible positions) for this league.

        Eligibility is the player's ``fantasy_positions`` intersected with the league.
        Primary (the VORP grouping bucket) is the granular ``position`` mapped to a
        bucket when that bucket is eligible -- so a two-way player like a WR/DB lands
        in WR, not DB. Returns ``(None, {})`` for players this league can't roster.
        """
        fantasy_positions: list[str] = list(catalog_entry.get("fantasy_positions") or [])
        eligible = frozenset(fantasy_positions) & league_positions
        if not eligible:
            return None, frozenset()

        position = catalog_entry.get("position")
        bucket = POSITION_TO_BUCKET.get(position) if position else None
        if bucket is not None and bucket in eligible:
            primary = bucket
        else:
            primary = next((p for p in fantasy_positions if p in eligible), None)
            if primary is None:
                primary = sorted(eligible)[0]
        return primary, eligible

    def raw_player_lines(
        self, config: LeagueConfig, season: int | None = None
    ) -> list[RawPlayerLine]:
        """The unscored universe: every rosterable player + raw projected stat line.

        Projection-source-agnostic on purpose -- this is what a ProjectionProvider
        scores. The ConsensusProvider runs these through the scoring engine; a future
        OpportunityProvider joins them to nflverse via ``ids`` instead. ``season``
        overrides the projection season for historical backtest folds.
        """
        catalog = self.get_players_catalog()
        proj_season = season if season is not None else config.season

        # Merge raw stat lines across the league's positions (hybrids dedupe by id).
        stat_lines: dict[str, dict[str, float]] = {}
        for position in sorted(config.positions):
            for row in self.get_projections(proj_season, position):
                stats = row.get("stats")
                if stats:
                    stat_lines[str(row["player_id"])] = stats

        lines: list[RawPlayerLine] = []
        for player_id, stats in stat_lines.items():
            entry = catalog.get(player_id)
            if entry is None:
                continue
            primary, eligible = self.classify(entry, config.positions)
            if primary is None:
                continue
            lines.append(
                RawPlayerLine(
                    player_id=player_id,
                    name=entry.get("full_name") or entry.get("team") or player_id,
                    primary_position=primary,
                    eligible_positions=eligible,
                    team=entry.get("team"),
                    stats={k: float(v) for k, v in stats.items() if isinstance(v, int | float)},
                    ids={k: str(entry[k]) for k in _ID_FIELDS if entry.get(k)},
                    years_exp=entry.get("years_exp"),
                )
            )
        return lines

    def player_projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        """Sleeper *consensus* projections: raw lines scored by the league's rules."""
        return [
            PlayerProjection(
                player_id=line.player_id,
                name=line.name,
                primary_position=line.primary_position,
                eligible_positions=line.eligible_positions,
                team=line.team,
                points=score_stat_line(line.stats, config.scoring),
                stats=line.stats,
            )
            for line in self.raw_player_lines(config)
        ]

    # --- drift guard -------------------------------------------------------
    def verify_scoring(self, config: LeagueConfig) -> list[tuple[str, float | None, float | None]]:
        """Compare the committed config scoring against the live league.

        Returns one (key, config_value, live_value) tuple per mismatch (missing on
        either side, or differing values). Empty list means the config is faithful.
        """
        live: dict[str, Any] = self.get_league(config.league_id).get("scoring_settings", {})
        drift: list[tuple[str, float | None, float | None]] = []
        for key in sorted(set(config.scoring) | set(live)):
            cfg_val = config.scoring.get(key)
            live_val = live.get(key)
            if cfg_val is None or live_val is None or abs(float(cfg_val) - float(live_val)) > 1e-9:
                drift.append((key, cfg_val, live_val if live_val is None else float(live_val)))
        return drift
