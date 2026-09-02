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

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection, RawPlayerLine
from ..scoring.engine import score_stat_line
from .cache import JsonCache

log = logging.getLogger("audible.sleeper")

# Set by `audible refresh-data` so a deliberate refresh goes to the network. Everything else
# reads the disk copy -- see adapters/cache.py for why this is not a TTL.
PROJECTIONS_REFRESH = False

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

# Roster/injury fields, read straight off the catalog entry and never interpreted here.
STATUS_FIELDS = (
    "status", "injury_status", "injury_body_part", "injury_notes", "injury_start_date",
)


@dataclass(frozen=True, slots=True)
class PlayerStatus:
    """Roster and injury state exactly as the PLATFORM reports it. Display only.

    DELIBERATELY NOT A FIELD ON ``RawPlayerLine`` OR ``PlayerProjection``. Those two are
    what the value engine consumes, and a status field on them would make "display only" a
    rule a human has to keep remembering -- one join, one `if`, and an injury flag is
    silently moving a projection. As a sidecar keyed by player_id it is something the
    engine cannot see even by accident, which is a structural guarantee rather than a
    convention. (Both models are also ``frozen=True, slots=True``, so adding a field risks
    any positional construction downstream -- a second, smaller reason.)

    Nothing here is derived. `status` is Sleeper's string, `injury_status` is Sleeper's
    string, and if Sleeper says ``Questionable`` then the only honest thing to render is
    ``Questionable``. Severity ranking, precedence between the two fields, and date
    arithmetic are all absent on purpose: they would be judgments this data does not
    contain, invented at the point of display.
    """

    player_id: str
    status: str | None = None
    injury_status: str | None = None
    injury_body_part: str | None = None
    injury_notes: str | None = None
    injury_start_date: str | None = None


class SleeperAdapter:
    name = "sleeper"

    def __init__(self, cache: JsonCache | None = None, timeout: float = 30.0) -> None:
        self._cache = cache if cache is not None else JsonCache()
        self._client = httpx.Client(
            timeout=timeout, headers={"User-Agent": "audible/0.1 (+personal)"}
        )
        # Per-draft conditional-request state for the live pick poll (see get_draft_picks).
        self._picks_etag: dict[str, str] = {}
        self._picks_last: dict[str, list[dict[str, Any]]] = {}

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

    def get_league_drafts(self, league_id: str) -> list[dict[str, Any]]:
        """Drafts for a league, most recent first. Note ``slot_to_roster_id`` is NOT on these
        summaries -- it only appears on ``GET /draft/{id}``."""
        return self._get(f"{BASE_APP}/league/{league_id}/drafts")

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        return self._get(f"{BASE_APP}/draft/{draft_id}")

    def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        """Live picks as they come off the board (player_id, pick_no, round, draft_slot).

        Bypasses the edge cache deliberately. Cloudflare serves this endpoint with
        ``s-maxage=30, stale-while-revalidate=300``; measured against the live API the
        ``age`` header reached 57s on a repeated poll, which is a full pick stale against a
        60s timer -- the cockpit would show a player as available after he was taken.

        A unique query param forces a cache MISS so the answer comes from origin (~110ms vs
        ~15ms at the edge, still trivial at a 5s cadence). The weak ETag then lets origin
        reply 304 with an empty body when nothing has changed, so the common case stays cheap.
        """
        headers = {"Cache-Control": "no-cache"}
        etag = self._picks_etag.get(draft_id)
        if etag is not None:
            headers["If-None-Match"] = etag

        resp = self._client.get(
            f"{BASE_APP}/draft/{draft_id}/picks",
            params=[("_", str(time.time_ns()))],
            headers=headers,
        )
        if resp.status_code == 304:
            return self._picks_last.get(draft_id, [])

        resp.raise_for_status()
        picks: list[dict[str, Any]] = resp.json()
        new_etag = resp.headers.get("etag")
        if new_etag:
            self._picks_etag[draft_id] = new_etag
        self._picks_last[draft_id] = picks
        return picks

    def get_players_catalog(self, *, force: bool = False) -> dict[str, Any]:
        if not force:
            cached = self._cache.get(PLAYERS_CACHE_KEY, PLAYERS_TTL_S)
            if cached is not None:
                return cached
        try:
            catalog: dict[str, Any] = self._get(f"{BASE_APP}/players/nfl")
        except Exception as exc:  # noqa: BLE001 -- a week-old catalog beats no board at all
            stale = self._cache.get_stale(PLAYERS_CACHE_KEY)
            if stale is None:
                raise
            log.warning("players catalog fetch failed (%s); using the cached copy", exc)
            return stale
        self._cache.set(PLAYERS_CACHE_KEY, catalog)
        return catalog

    def get_projections(
        self, season: int, position: str, week: int | None = None
    ) -> list[dict[str, Any]]:
        """Projections, cached to disk.

        Cached for the same reason the nflverse sources are: on draft night the network is
        an update mechanism, not a dependency. Without this the board cannot be built offline
        no matter how much else is cached -- these ARE the projections.
        """
        key = f"sleeper_projections_{season}_{position}" + (f"_w{week}" if week else "")
        if not PROJECTIONS_REFRESH:
            cached = self._cache.get_stale(key)
            if cached is not None:
                return cached

        suffix = f"/{week}" if week is not None else ""
        url = f"{BASE_COM}/projections/nfl/{season}{suffix}"
        params: _Params = [
            ("season_type", "regular"),
            ("position[]", position),
            ("order_by", "pts_half_ppr"),
        ]
        try:
            rows: list[dict[str, Any]] = self._get(url, params=params)
        except Exception as exc:  # noqa: BLE001 -- fall back to any copy we already hold
            stale = self._cache.get_stale(key)
            if stale is None:
                raise
            log.warning("projections fetch failed for %s (%s); using the cached copy", key, exc)
            return stale
        self._cache.set(key, rows)
        return rows

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

    def player_status(self, player_ids: Iterable[str] | None = None) -> dict[str, PlayerStatus]:
        """``player_id -> PlayerStatus`` from the cached catalog. Display only.

        A SIDECAR, not a column. The value path must never import this -- there is a test
        asserting exactly that, because the guarantee is only worth as much as its guard.

        Reads the same catalog the board is already built from, so it costs no extra fetch.
        Players absent from the catalog are absent from the mapping rather than present with
        nulls: "we have no record of him" and "he is Active" must not collapse into one
        value, or the chip would report health it never observed.
        """
        catalog = self.get_players_catalog()
        wanted = set(player_ids) if player_ids is not None else None
        out: dict[str, PlayerStatus] = {}
        for pid, entry in catalog.items():
            if not isinstance(entry, dict):
                continue
            key = str(pid)
            if wanted is not None and key not in wanted:
                continue
            values = {f: entry.get(f) for f in STATUS_FIELDS}
            # An entry that carries nothing at all is not evidence of anything; leaving it
            # out keeps the coverage measurement honest about what the wire actually served.
            if all(v is None or v == "" for v in values.values()):
                continue
            out[key] = PlayerStatus(
                player_id=key,
                **{f: (str(v) if v not in (None, "") else None) for f, v in values.items()},
            )
        return out

    def player_projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        """Sleeper *consensus* projections: raw lines scored by the league's rules."""
        return [
            PlayerProjection(
                player_id=line.player_id,
                name=line.name,
                primary_position=line.primary_position,
                eligible_positions=line.eligible_positions,
                team=line.team,
                points=score_stat_line(line.stats, config.scoring_for(line.primary_position)),
                stats=line.stats,
            )
            for line in self.raw_player_lines(config)
        ]

    # --- drift guards ------------------------------------------------------
    # Bench/IR slots never demand a weekly starter, so they're excluded from the comparison.
    _NON_STARTER_SLOTS = frozenset({"BN", "IR", "TAXI"})

    def verify_structure(self, config: LeagueConfig) -> list[tuple[str, int, int]]:
        """Compare the committed starting lineup against the live league's roster_positions.

        Returns one ``(slot, config_count, live_count)`` tuple per mismatched slot; an empty
        list means the structure is faithful. This is the structural twin of
        :meth:`verify_scoring`, and it exists because its absence is exactly how the config
        came to claim four IDP slots and a DEF slot the live league does not have -- which
        silently corrupts every replacement baseline the value engine derives.
        """
        live_positions: list[str] = self.get_league(config.league_id).get("roster_positions", [])
        live_counts: dict[str, int] = {}
        for slot in live_positions:
            if slot in self._NON_STARTER_SLOTS:
                continue
            live_counts[slot] = live_counts.get(slot, 0) + 1

        cfg_counts = config.slot_counts()
        return [
            (slot, cfg_counts.get(slot, 0), live_counts.get(slot, 0))
            for slot in sorted(set(cfg_counts) | set(live_counts))
            if cfg_counts.get(slot, 0) != live_counts.get(slot, 0)
        ]

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
