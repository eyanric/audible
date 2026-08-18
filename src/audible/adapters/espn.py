"""ESPN adapter -- League B (private league 6012). Read-only, cookie auth, one file.

It rides an unofficial API, so everything it touches lives here: when ESPN moves a field,
this is the only file that changes.

  * **Auth** is two browser cookies, ``espn_s2`` and ``SWID`` (braces kept), read from the
    environment or the repo's ``.env``. Nothing here ever writes to ESPN.
  * **The player pool** comes from the league endpoint under ``view=kona_player_info`` with
    an ``X-Fantasy-Filter`` header. ``sortDraftRanks`` is MANDATORY: without a sort the
    endpoint answers 200 with zero players, which reads downstream as "nobody is available"
    rather than as a failure. The pool saturates at 1,026, so the limit is a guard, not a
    target, and an empty pool is raised rather than returned.
  * **Points never come from ESPN for offense.** Raw stat lines are translated into our
    Sleeper-vocabulary stat keys and scored by the deterministic engine against this
    league's own weights -- including its position-scoped receptions (WR/TE 0.5, RB 0.0).
  * **K and D/ST fall back to ESPN's own projected total.** ESPN reuses statIds across those
    two positions, and our config models neither yards-allowed nor kicker miss distance, so
    there is no faithful translation to make. The fallback is counted, never hidden: see
    :attr:`EspnAdapter.source_counts` and :data:`SPECIALIST_GAP`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config.schema import LeagueConfig
from ..models.player import PlayerProjection, RawPlayerLine
from ..scoring.engine import score_stat_line
from .cache import JsonCache

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"

# Which of ESPN's per-season draft ranks League B is served. Per-season ranks exist
# 400/400 for 2023-2025 and are ABSENT for 2021-2022 -- sorting by a rank type that
# isn't there returns arbitrary order silently, which is why the pool assertion below
# is not optional.
#
# ESPN serves four types on every player (STANDARD, PPR, ELIMINATION, SUPERFLEX). Do not
# read STANDARD as a zero-PPR ranking: measured over the 2026 pool it is the SAME ordering
# as PPR at the top and diverges only for non-receiving backs (Derrick Henry STANDARD #10
# vs PPR #19). STANDARD is still the right one here -- this league pays RBs nothing per
# reception -- but anything treating it as a 0-PPR market baseline will be wrong.
RANK_TYPE = "STANDARD"

# ESPN defaultPositionId -> our position bucket. League B rosters no IDP, so the six
# offensive/specialist ids are the whole map; anything else is dropped by `config.positions`.
POSITION_ID_TO_BUCKET: dict[int, str] = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
BUCKET_TO_POSITION_ID: dict[str, int] = {v: k for k, v in POSITION_ID_TO_BUCKET.items()}

# Positions whose raw stat line we can translate exactly. K and D/ST are deliberately absent.
TRANSLATED_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})

SPECIALIST_GAP = (
    "K and D/ST are scored from ESPN's own projected total, not from a translated stat "
    "line: our vocabulary models neither D/ST yards-allowed nor kicker miss distance. "
    "Worth ~15 pts/season across two positions that occupy one roster slot each."
)

UNTRANSLATED_GAP = (
    "Offensive players whose projected line holds nothing our vocabulary covers also fall "
    "back to ESPN's total. Measured on the 2026 pool: 431 are projected for nothing at all "
    "(0.0 either way) and 74 are pure return specialists scored on return yards/TDs, which "
    "this league does not pay. The largest of them projects 65 pts against a WR replacement "
    "level of 182, so none can reach a starting lineup or move a baseline."
)

# League 6012 pays passing yards through ESPN's BUCKETED stat -- statId 8, one point per
# completed 25 yards. Raw passing yards (statId 3) is not a scoring item in this league at
# all, for any position, so it is not in this map: reading it would score yards ESPN does
# not pay for. Converting the bucket count back to yards reproduces ESPN's number exactly
# through our own `pass_yd` weight (25 x 0.04 = 1.0), so the league stays data and the
# scoring engine keeps one weights table with no ESPN branch in it.
#
# The same bucketing is why a Sleeper-sourced board reads QBs ~2% high: 0.04/yd is
# continuous, ESPN's bucket floors every partial 25 yards away. Measured on Josh Allen's
# 2026 projection: statId 3 = 3944.73 yards, statId 8 = 157 buckets (3925 yards).
PASS_YARD_BUCKET = 25.0
RAW_PASS_YARDS_STAT_ID = 3

# ESPN statId -> (our stat key, multiplier into that key's units).
#
# Reconciled against ESPN's own appliedTotal on the live 2026 projections: QB -0.233,
# RB -0.069, WR -0.045, TE -0.022 points across a full season. The whole residual is one
# stat -- statId 63, an offensive fumble recovered for a touchdown, paid 6.0 -- which our
# config has no key for and which the config is not being changed to add. It is worth
# 0.06% of a QB season, it is monotone in fumbles (already penalised via `fum_lost`), and
# it cannot reorder the board.
STAT_ID_TO_KEY: dict[int, tuple[str, float]] = {
    4: ("pass_td", 1.0),
    8: ("pass_yd", PASS_YARD_BUCKET),
    19: ("pass_2pt", 1.0),
    20: ("pass_int", 1.0),
    24: ("rush_yd", 1.0),
    25: ("rush_td", 1.0),
    26: ("rush_2pt", 1.0),
    42: ("rec_yd", 1.0),
    43: ("rec_td", 1.0),
    44: ("rec_2pt", 1.0),
    53: ("rec", 1.0),
    72: ("fum_lost", 1.0),
}

# ESPN proTeamId -> abbreviation (display only; the nflverse join rides gsis_id elsewhere).
PRO_TEAM_BY_ID: dict[int, str] = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
    9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN",
    17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
    25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

# The pool saturates at 1,026; ask for well past it so saturation is observed, not imposed.
POOL_LIMIT = 2000

# ESPN lineup-slot id -> the slot name our config uses. Only the ids League B actually rosters
# are mapped; a non-zero count on any other id is reported as unknown rather than ignored,
# because a slot we quietly skip is a slot whose drift never shows up.
LINEUP_SLOT_TO_NAME: dict[int, str] = {
    0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "DEF", 17: "K", 23: "FLEX",
}
# Bench and IR never demand a weekly starter -- the same exclusion the Sleeper guard makes.
NON_STARTER_LINEUP_SLOTS = frozenset({20, 21})
IR_LINEUP_SLOT = 21

# Pre-draft, mDraftDetail serves a COMPLETE placeholder slate -- 128 entries for an 8-team,
# 16-round draft -- every one with playerId -1. Counting rows instead of real picks reports a
# finished draft before the first selection is made.
UNDRAFTED_PLAYER_ID = -1

_AUTH_EXPIRED = (
    "ESPN credentials expired, re-pull cookies. fantasy.espn.com -> DevTools -> "
    "Application -> Cookies: copy SWID (keep the curly braces) and espn_s2 into .env."
)
_AUTH_MISSING = (
    "ESPN credentials missing: set ESPN_SWID (keep the curly braces) and ESPN_S2 in .env. "
    "League B is a private league; both cookies are required."
)


class EspnAuthError(RuntimeError):
    """Cookies absent, rejected, or expired -- always actionable, never a traceback."""


class EspnDataError(RuntimeError):
    """ESPN answered, but with something the board cannot be built from."""


# --- credentials -----------------------------------------------------------------------
# .env is read directly rather than pulling in python-dotenv: two cookies do not justify a
# runtime dependency, and this keeps the secret path inside the one quarantined file.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_dotenv_cache: dict[str, str] | None = None


def _dotenv() -> dict[str, str]:
    global _dotenv_cache
    if _dotenv_cache is None:
        values: dict[str, str] = {}
        path = _REPO_ROOT / ".env"
        if path.exists():
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                values[name.strip()] = value.strip().strip('"').strip("'")
        _dotenv_cache = values
    return _dotenv_cache


def _cookie(name: str) -> str | None:
    return os.environ.get(name) or _dotenv().get(name) or None


# --- stat-line translation -------------------------------------------------------------


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int(value: object) -> int:
    """An untyped ESPN id as an int. -1 is no position, no team, and no stat."""
    number = _number(value)
    return int(number) if number is not None else -1


def translate_stat_line(raw: Mapping[str, Any], position: str) -> dict[str, float]:
    """ESPN's ``{statId: value}`` line -> our stat vocabulary, for *position*.

    Unmapped statIds are dropped rather than guessed at; a position we cannot translate
    (K, D/ST) yields ``{}``, which is the caller's signal to fall back to ESPN's own total.
    """
    out: dict[str, float] = {}
    for stat_id, value in raw.items():
        number = _number(value)
        if number is None:
            continue
        try:
            mapped = STAT_ID_TO_KEY.get(int(stat_id))
        except (TypeError, ValueError):
            continue
        if mapped is None:
            continue
        key, factor = mapped
        out[key] = out.get(key, 0.0) + number * factor

    # If ESPN ever stops shipping the bucketed stat, fall back to raw passing yards rather
    # than serving a QB projected to throw for nothing -- which would look like data, not
    # like a break. Scoped to QB because only there is a missing passing line implausible.
    if position == "QB" and "pass_yd" not in out:
        raw_yards = _number(raw.get(str(RAW_PASS_YARDS_STAT_ID)))
        if raw_yards is not None:
            out["pass_yd"] = raw_yards
    return out


def _projected_stat_set(player: Mapping[str, Any], season: int) -> dict[str, Any] | None:
    """The season-total PROJECTION (statSourceId 1, statSplitTypeId 0) for *season*."""
    for stat_set in player.get("stats") or []:
        if (
            stat_set.get("seasonId") == season
            and stat_set.get("statSourceId") == 1
            and stat_set.get("statSplitTypeId") == 0
        ):
            return dict(stat_set)
    return None


def _draft_rank(player: Mapping[str, Any]) -> float | None:
    entry = (player.get("draftRanksByRankType") or {}).get(RANK_TYPE) or {}
    rank = _number(entry.get("rank"))
    return rank if rank is not None and rank > 0 else None


def pool_filter(limit: int = POOL_LIMIT) -> str:
    """The X-Fantasy-Filter payload for the player pool.

    ``sortDraftRanks`` is load-bearing: drop it and the endpoint returns 200 with an empty
    player list and no error of any kind.
    """
    return json.dumps(
        {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS", "ONTEAM"]},
                "limit": limit,
                "offset": 0,
                "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": RANK_TYPE},
            }
        }
    )


# Which path produced a player's points. Only the first is ours; the other two hand the
# number back to ESPN, and both are counted so neither can pass for a computed projection.
SOURCE_STAT_LINE = "stat_line"  # translated into our vocabulary, scored by our engine
SOURCE_SPECIALIST = "vendor_specialist"  # K / D-ST -- see SPECIALIST_GAP
SOURCE_UNTRANSLATED = "vendor_untranslated"  # offense we cannot read -- see UNTRANSLATED_GAP


@dataclass(frozen=True, slots=True)
class _PoolEntry:
    line: RawPlayerLine
    source: str
    espn_points: float


class EspnAdapter:
    name = "espn"

    def __init__(
        self,
        swid: str | None = None,
        espn_s2: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        cache: JsonCache | None = None,
    ) -> None:
        self._swid = swid if swid is not None else _cookie("ESPN_SWID")
        self._espn_s2 = espn_s2 if espn_s2 is not None else _cookie("ESPN_S2")
        self._cache = cache if cache is not None else JsonCache()
        # Cookies live on the client, not the request: httpx deprecated per-request cookies
        # because persistence across a redirect is ambiguous.
        cookies = (
            {"SWID": self._swid, "espn_s2": self._espn_s2}
            if self._swid and self._espn_s2
            else {}
        )
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "audible/0.1 (+personal)"},
            cookies=cookies,
            transport=transport,
        )
        # Observability for the two things that silently go wrong: an empty pool, and how
        # many players were scored by us versus handed back from ESPN's own projection.
        self.pool_size: int = 0
        self.source_counts: dict[str, int] = {}
        # Conditional-request state for the draft poll (see get_draft_detail).
        self._draft_etag: str | None = None
        self._draft_last: dict[str, Any] | None = None

    @property
    def swid(self) -> str | None:
        """The authenticated SWID. It already says who I am, so identity is derived from it
        rather than configured -- a ``--slot`` flag would only be a second place to be wrong."""
        return self._swid

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EspnAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- raw endpoints ------------------------------------------------------------------
    def _league_url(self, config: LeagueConfig) -> str:
        return f"{BASE}/{config.season}/segments/0/leagues/{config.league_id}"

    def _request(
        self, config: LeagueConfig, views: list[str], *, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        if not self._swid or not self._espn_s2:
            raise EspnAuthError(_AUTH_MISSING)
        resp = self._client.get(
            self._league_url(config),
            params=[("view", view) for view in views],
            headers=headers or {},
        )
        if resp.status_code in (401, 403):
            raise EspnAuthError(_AUTH_EXPIRED)
        return resp

    def _get(
        self, config: LeagueConfig, views: list[str], *, fantasy_filter: str | None = None
    ) -> Any:
        headers = {"X-Fantasy-Filter": fantasy_filter} if fantasy_filter is not None else {}
        resp = self._request(config, views, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def get_settings(self, config: LeagueConfig) -> dict[str, Any]:
        payload = self._get(config, ["mSettings"])
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise EspnDataError(
                f"ESPN league {config.league_id} returned no settings block; the league id, "
                "season, or cookie scope is wrong."
            )
        return settings

    def get_scoring_items(self, config: LeagueConfig) -> list[dict[str, Any]]:
        items = (self.get_settings(config).get("scoringSettings") or {}).get("scoringItems")
        if not items:
            raise EspnDataError("ESPN returned no scoringItems; scoring cannot be verified.")
        return list(items)

    def get_player_pool(self, config: LeagueConfig) -> list[dict[str, Any]]:
        payload = self._get(config, ["kona_player_info"], fantasy_filter=pool_filter())
        players = payload.get("players") or []
        if not players:
            raise EspnDataError(
                "ESPN returned an EMPTY player pool with a 200 -- exactly what an "
                "X-Fantasy-Filter without `sortDraftRanks` looks like. The endpoint does "
                "not error, it just serves nothing, so this must fail here rather than "
                "become an empty board."
            )
        self.pool_size = len(players)
        return list(players)

    # --- the live draft -----------------------------------------------------------------
    DRAFT_VIEWS = ["mDraftDetail", "mTeam", "mSettings"]

    def get_draft_detail(self, config: LeagueConfig) -> dict[str, Any]:
        """The whole live-draft picture in ONE conditional GET.

        Draft state, the pick slate, the teams (for identity) and the settings (for pick order
        and roster structure) all ride a single response, so the poll loop makes one request
        per tick rather than four.

        Conditional, and deliberately WITHOUT a cache-buster. Measured on this endpoint:
        ``x-cache: Miss from cloudfront``, ``cache-control: must-revalidate``, no ``age``
        header -- nothing is serving us a stale copy, and a repeat request with
        ``If-None-Match`` comes back 304 with an empty body. This is the OPPOSITE of Sleeper's
        ``/picks``, which is edge-cached at ``s-maxage=30`` and measured 57s stale against a
        60s pick timer, and so must carry a buster. Neither behaviour generalises to the
        other platform; do not copy this decision across.
        """
        headers = {"If-None-Match": self._draft_etag} if self._draft_etag else {}
        resp = self._request(config, self.DRAFT_VIEWS, headers=headers)
        if resp.status_code == 304 and self._draft_last is not None:
            return self._draft_last
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        etag = resp.headers.get("etag")
        if etag:
            self._draft_etag = etag
        self._draft_last = payload
        return payload

    # --- completed seasons (the anchoring corpus) ---------------------------------------
    # Cached without a TTL: a finished draft and its served ranks are immutable. Re-fetching
    # them is pure cost, and on a metered afternoon it is how you earn a 429.

    def _season_config(self, config: LeagueConfig, season: int) -> LeagueConfig:
        return config.model_copy(update={"season": season})

    def get_season_draft(self, config: LeagueConfig, season: int) -> list[dict[str, Any]]:
        """Every real pick from a completed season, in pick order.

        Placeholder rows (``playerId: -1``) are filtered here for the same reason the live
        sync filters them: a pre-draft slate is a full grid of every pick that will ever
        exist, and counting rows reads as a finished draft.
        """
        key = f"espn_draft_{config.league_id}_{season}"
        cached = self._cache.get_stale(key)
        if cached is not None:
            return cached

        payload = self._get(self._season_config(config, season), ["mDraftDetail"])
        detail = payload.get("draftDetail") or {}
        picks = [
            {
                "overall": int(row.get("overallPickNumber") or 0),
                "round": int(row.get("roundId") or 0),
                "team_id": _int(row.get("teamId")),
                "player_id": str(row.get("playerId")),
            }
            for row in (detail.get("picks") or [])
            if row.get("playerId") is not None
            and int(row["playerId"]) != UNDRAFTED_PLAYER_ID
        ]
        picks.sort(key=lambda p: p["overall"])
        self._cache.set(key, picks)
        return picks

    def get_season_ranks(self, config: LeagueConfig, season: int) -> dict[str, dict[str, Any]]:
        """``playerId -> {standard, ppr, name, position}`` as ESPN served them THAT season.

        Period-appropriate by construction: these are the ranks the room actually saw, not a
        present-day board projected backwards.

        Returns ``{}`` for a season ESPN serves no ranks for. 2021 and 2022 are exactly that
        -- 400 players, zero ranks -- and sorting by an absent rank type returns arbitrary
        order with no error, so an empty answer here is the guard, not a gap.
        """
        key = f"espn_ranks_{config.league_id}_{season}"
        cached = self._cache.get_stale(key)
        if cached is not None:
            return cached

        payload = self._get(
            self._season_config(config, season),
            ["kona_player_info"],
            fantasy_filter=pool_filter(),
        )
        ranks: dict[str, dict[str, Any]] = {}
        for row in payload.get("players") or []:
            player = row.get("player") or {}
            by_type = player.get("draftRanksByRankType") or {}
            standard = _number((by_type.get("STANDARD") or {}).get("rank"))
            ppr = _number((by_type.get("PPR") or {}).get("rank"))
            if standard is None and ppr is None:
                continue
            ranks[str(player.get("id"))] = {
                "standard": standard,
                "ppr": ppr,
                "name": player.get("fullName"),
                "position": POSITION_ID_TO_BUCKET.get(_int(player.get("defaultPositionId"))),
            }
        self._cache.set(key, ranks)
        return ranks

    def get_season_actuals(self, config: LeagueConfig, season: int) -> dict[str, float]:
        """``playerId -> realized season points``, scored under THAT season's league rules.

        Read from ESPN's own actual stat set (``statSourceId 0``, ``statSplitTypeId 0``), not
        recomputed here. ESPN applies the league's settings for the season being queried, so
        this is the league's own arithmetic on the league's own scoring -- which is what a
        draft-quality measure needs, and it sidesteps our K and D/ST translation gap entirely.
        """
        key = f"espn_actuals_{config.league_id}_{season}"
        cached = self._cache.get_stale(key)
        if cached is not None:
            return cached

        payload = self._get(
            self._season_config(config, season),
            ["kona_player_info"],
            fantasy_filter=pool_filter(),
        )
        actuals: dict[str, float] = {}
        for row in payload.get("players") or []:
            player = row.get("player") or {}
            for stat_set in player.get("stats") or []:
                if (
                    stat_set.get("seasonId") == season
                    and stat_set.get("statSourceId") == 0
                    and stat_set.get("statSplitTypeId") == 0
                ):
                    points = _number(stat_set.get("appliedTotal"))
                    if points is not None:
                        actuals[str(player.get("id"))] = points
                    break
        self._cache.set(key, actuals)
        return actuals

    def get_season_standings(self, config: LeagueConfig, season: int) -> list[dict[str, Any]]:
        """Final outcomes per team: standing, record, points for.

        ``owner`` is the primary-owner GUID, carried because ESPN reuses ``teamId`` across
        seasons and a seat is a person, not a slot. It is a join key only -- never displayed
        and never written down. Display names live in ``members`` and are not read at all.
        """
        key = f"espn_standings_{config.league_id}_{season}"
        cached = self._cache.get_stale(key)
        if cached is not None:
            return cached

        payload = self._get(self._season_config(config, season), ["mTeam"])
        rows: list[dict[str, Any]] = []
        for team in payload.get("teams") or []:
            overall = (team.get("record") or {}).get("overall") or {}
            rows.append({
                "team_id": _int(team.get("id")),
                "abbrev": str(team.get("abbrev") or team.get("id")),
                "owner": str(team.get("primaryOwner") or ""),
                # rankFinal reads 0 on every season of this league; rankCalculatedFinal is
                # the one that carries the actual finishing order.
                "standing": _int(team.get("rankCalculatedFinal")),
                "playoff_seed": _int(team.get("playoffSeed")),
                "wins": _int(overall.get("wins")),
                "losses": _int(overall.get("losses")),
                "points_for": _number(overall.get("pointsFor")) or 0.0,
            })
        self._cache.set(key, rows)
        return rows

    def get_season_teams(self, config: LeagueConfig, season: int) -> dict[int, str]:
        """``teamId -> abbrev`` for a season. Abbrevs only: owner SWIDs stay out of anything
        that gets written down."""
        key = f"espn_teams_{config.league_id}_{season}"
        cached = self._cache.get_stale(key)
        if cached is not None:
            return {int(k): v for k, v in cached.items()}

        payload = self._get(self._season_config(config, season), ["mTeam"])
        teams = {
            str(_int(t.get("id"))): str(t.get("abbrev") or t.get("id"))
            for t in (payload.get("teams") or [])
        }
        self._cache.set(key, teams)
        return {int(k): v for k, v in teams.items()}

    # --- normalisation ------------------------------------------------------------------
    def _pool_entries(self, config: LeagueConfig) -> list[_PoolEntry]:
        entries: list[_PoolEntry] = []
        counts: dict[str, int] = {}
        for row in self.get_player_pool(config):
            player = row.get("player") or row
            bucket = POSITION_ID_TO_BUCKET.get(_int(player.get("defaultPositionId")))
            if bucket is None or bucket not in config.positions:
                continue

            stat_set = _projected_stat_set(player, config.season) or {}
            espn_points = _number(stat_set.get("appliedTotal")) or 0.0
            raw = stat_set.get("stats") or {}
            if bucket not in TRANSLATED_POSITIONS:
                stats, source = {}, SOURCE_SPECIALIST
            else:
                stats = translate_stat_line(raw, bucket)
                source = SOURCE_STAT_LINE if stats else SOURCE_UNTRANSLATED
            counts[source] = counts.get(source, 0) + 1

            # Non-scoring passengers, the same way Sleeper lines carry adp_* / pts_half_ppr:
            # the engine iterates scoring keys, so neither can leak into a score. ESPN's own
            # total is the reconciliation check; its served rank is the market we are pricing.
            stats["espn_projected_points"] = espn_points
            rank = _draft_rank(player)
            if rank is not None:
                stats["espn_draft_rank"] = rank

            player_id = str(player.get("id"))
            entries.append(
                _PoolEntry(
                    line=RawPlayerLine(
                        player_id=player_id,
                        name=player.get("fullName") or player_id,
                        primary_position=bucket,
                        eligible_positions=frozenset({bucket}),
                        team=PRO_TEAM_BY_ID.get(_int(player.get("proTeamId"))),
                        stats=stats,
                        ids={"espn_id": player_id},
                    ),
                    source=source,
                    espn_points=espn_points,
                )
            )
        self.source_counts = counts
        return entries

    def raw_player_lines(self, config: LeagueConfig) -> list[RawPlayerLine]:
        return [entry.line for entry in self._pool_entries(config)]

    def player_projections(self, config: LeagueConfig) -> list[PlayerProjection]:
        """ESPN's universe scored by this league's rules.

        Offense is recomputed from the translated stat line so the league's own weights --
        including the RB/WR-TE reception split -- decide the number. Everything we cannot
        read carries ESPN's projected total unchanged; see :data:`SPECIALIST_GAP` and
        :data:`UNTRANSLATED_GAP`.
        """
        return [
            PlayerProjection(
                player_id=entry.line.player_id,
                name=entry.line.name,
                primary_position=entry.line.primary_position,
                eligible_positions=entry.line.eligible_positions,
                team=entry.line.team,
                points=(
                    score_stat_line(
                        entry.line.stats, config.scoring_for(entry.line.primary_position)
                    )
                    if entry.source == SOURCE_STAT_LINE
                    else entry.espn_points
                ),
                stats=entry.line.stats,
            )
            for entry in self._pool_entries(config)
        ]

    # --- drift guards -------------------------------------------------------------------
    @staticmethod
    def _live_points(item: Mapping[str, Any], position_id: int) -> float | None:
        """A scoring item's effective value for one position.

        Read ``pointsOverrides`` before ``points``: League B pays receptions as base 0.0
        with overrides for QB/WR/TE, while our config says base 0.5 with an RB override of
        0.0. The two encodings agree at every position that can catch a pass, and a
        base-against-base comparison would report drift across the whole table where there
        is none.
        """
        overrides = item.get("pointsOverrides") or {}
        value = overrides.get(str(position_id), overrides.get(position_id, item.get("points")))
        return _number(value)

    def verify_scoring(self, config: LeagueConfig) -> list[tuple[str, float | None, float | None]]:
        """Compare committed weights against the live league, per position.

        Returns one ``(key, config_value, live_value)`` per mismatch, keyed ``stat[POS]``.
        Live values are converted into our units, so the QB bucketed passing stat (1.0 per
        25 yards) is compared against our 0.04 per yard rather than reported as drift.

        K and D/ST are outside the comparison by the same decision that leaves them on
        ESPN's own projection -- see :data:`SPECIALIST_GAP`.
        """
        items: dict[int, dict[str, Any]] = {}
        for item in self.get_scoring_items(config):
            stat_id = _number(item.get("statId"))
            if stat_id is not None:
                items[int(stat_id)] = dict(item)

        drift: list[tuple[str, float | None, float | None]] = []
        for position in sorted(config.positions & TRANSLATED_POSITIONS):
            position_id = BUCKET_TO_POSITION_ID[position]
            cfg_scoring = config.scoring_for(position)
            for stat_id, (key, factor) in sorted(STAT_ID_TO_KEY.items()):
                cfg_value = cfg_scoring.get(key)
                item = items.get(stat_id)
                live_value = None if item is None else self._live_points(item, position_id)
                if live_value is not None:
                    live_value /= factor
                if (
                    cfg_value is None
                    or live_value is None
                    or abs(float(cfg_value) - live_value) > 1e-9
                ):
                    drift.append((f"{key}[{position}]", cfg_value, live_value))
        return drift

    def lineup_slot_counts(self, config: LeagueConfig) -> dict[int, int]:
        """``settings.rosterSettings.lineupSlotCounts``, keyed by int lineup-slot id."""
        counts = (self.get_settings(config).get("rosterSettings") or {}).get("lineupSlotCounts")
        if not counts:
            raise EspnDataError(
                "ESPN returned no lineupSlotCounts; roster structure cannot be verified."
            )
        out: dict[int, int] = {}
        for slot_id, count in counts.items():
            number = _number(count)
            if number is None:
                continue
            try:
                out[int(slot_id)] = int(number)  # JSON object keys arrive as strings
            except (TypeError, ValueError):
                continue
        return out

    def verify_structure(self, config: LeagueConfig) -> list[tuple[str, int, int]]:
        """Compare the committed starting lineup against the live league's lineup slots.

        Returns one ``(slot, config_count, live_count)`` per mismatched slot; empty means the
        structure is faithful. This is the structural twin of :meth:`verify_scoring`, and it is
        the check that caught League A's June-to-August drift -- a config claiming slots the
        league does not have silently corrupts every replacement baseline the value engine
        derives, and therefore every number on the board.

        An ESPN lineup-slot id we do not map is reported as ``slot#<id>`` rather than skipped:
        a starting slot this league rosters and we have no name for is exactly the drift worth
        being loud about.
        """
        live_counts: dict[str, int] = {}
        for slot_id, count in self.lineup_slot_counts(config).items():
            if slot_id in NON_STARTER_LINEUP_SLOTS or count <= 0:
                continue
            name = LINEUP_SLOT_TO_NAME.get(slot_id, f"slot#{slot_id}")
            live_counts[name] = live_counts.get(name, 0) + count

        cfg_counts = config.slot_counts()
        return [
            (slot, cfg_counts.get(slot, 0), live_counts.get(slot, 0))
            for slot in sorted(set(cfg_counts) | set(live_counts))
            if cfg_counts.get(slot, 0) != live_counts.get(slot, 0)
        ]

    def draft_rounds(self, config: LeagueConfig) -> int:
        """How many rounds the draft runs: every roster slot that is drafted, IR excluded.

        Derived from roster structure rather than from the pick slate, so it stays right
        whatever ESPN chooses to serve in ``draftDetail.picks`` once a draft is under way.
        """
        counts = self.lineup_slot_counts(config)
        return sum(counts.values()) - counts.get(IR_LINEUP_SLOT, 0)

    def live_reception_points(self, config: LeagueConfig, position: str = "WR") -> float | None:
        """The live per-reception value for *position* (statId 53), or None if unscored.

        This is the league's one standing question: the commissioner is flipping League B
        from standard to half-PPR, and until that lands every WR/TE number on the board is
        priced for a scoring system the league is not using yet.
        """
        for item in self.get_scoring_items(config):
            stat_id = _number(item.get("statId"))
            if stat_id is not None and int(stat_id) == 53:
                return self._live_points(item, BUCKET_TO_POSITION_ID[position])
        return None
