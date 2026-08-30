"""Live draft sync: one poll loop, two upstreams behind one seam.

:class:`~audible.draft.service.CockpitService` owns the loop, the state and the staleness
clock; it does not know which platform it is talking to. Everything platform-shaped lives
here, in one small protocol:

    poll(draft_id, want_meta=..., slot_locked=...) -> DraftUpdate

The two implementations are shaped very differently and that is the point of the seam.
Sleeper needs three endpoints (drafts, draft, picks) plus users and rosters to resolve a slot,
so it takes the ``want_meta`` hint seriously. ESPN answers the entire question -- state, picks,
teams, settings -- in a single conditional GET, so it refreshes everything every tick and
ignores the hint.

``DraftUpdate`` uses ``None`` to mean "leave what's there alone". A poll that only fetched
picks must not blank out the draft status it did not ask about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..config.schema import LeagueConfig, Platform
from .identity import (
    SOURCE_OVERRIDE,
    SOURCE_PICK_ORDER,
    SOURCE_UNRESOLVED,
    Identity,
    resolve_slot,
    user_id_for_name,
)
from .live import Pick, parse_picks

log = logging.getLogger("audible.cockpit")


@dataclass(frozen=True, slots=True)
class DraftUpdate:
    """One poll's worth of upstream truth. ``None`` means "unchanged, do not touch"."""

    draft_id: str | None = None
    picks: list[Pick] = field(default_factory=list)
    rounds: int | None = None
    status: str | None = None
    draft_type: str | None = None
    identity: Identity | None = None


@runtime_checkable
class DraftSync(Protocol):
    name: str

    def poll(
        self, draft_id: str | None, *, want_meta: bool, slot_locked: bool
    ) -> DraftUpdate:
        """Fetch current draft truth. Raises on failure; the caller owns retry and health."""
        ...

    def close(self) -> None: ...


# --- Sleeper ------------------------------------------------------------------------------


class SleeperSync:
    """Sleeper's three-endpoint draft feed, unchanged in behaviour from the pre-seam service."""

    name = "sleeper"

    def __init__(
        self,
        config: LeagueConfig,
        *,
        slot_override: int | None = None,
        user_name: str | None = None,
        adapter: Any | None = None,
    ) -> None:
        from ..adapters.sleeper import SleeperAdapter

        self._config = config
        self._adapter = adapter if adapter is not None else SleeperAdapter()
        self._slot_override = slot_override
        self._user_name = user_name
        self._user_id: str | None = None

    def close(self) -> None:
        self._adapter.close()

    def _discover(self) -> str:
        """Find the league's draft.

        Re-discovery is not an error path: if the commissioner deletes and recreates the draft
        while scheduling it, the id changes underneath us and a pinned id starts 404ing.
        """
        drafts = self._adapter.get_league_drafts(self._config.league_id)
        if not drafts:
            raise RuntimeError(f"league {self._config.league_id} has no drafts")
        return str(drafts[0]["draft_id"])

    def _identity(self, draft: dict[str, Any]) -> Identity:
        if self._user_id is None and self._user_name:
            self._user_id = user_id_for_name(
                self._adapter.get_users(self._config.league_id), self._user_name
            )
        rosters = self._adapter.get_rosters(self._config.league_id) if self._user_id else []
        return resolve_slot(draft, rosters, self._user_id, override=self._slot_override)

    def poll(self, draft_id: str | None, *, want_meta: bool, slot_locked: bool) -> DraftUpdate:
        if draft_id is None:
            draft_id, want_meta = self._discover(), True

        if not want_meta:
            return DraftUpdate(
                draft_id=draft_id, picks=parse_picks(self._adapter.get_draft_picks(draft_id))
            )

        try:
            draft = self._adapter.get_draft(draft_id)
        except Exception:  # noqa: BLE001 -- a stale id is recoverable; re-discover and retry
            log.warning("draft metadata refresh failed; re-discovering draft id")
            draft_id = self._discover()
            draft = self._adapter.get_draft(draft_id)

        settings = draft.get("settings") or {}
        return DraftUpdate(
            draft_id=draft_id,
            picks=parse_picks(self._adapter.get_draft_picks(draft_id)),
            rounds=int(settings["rounds"]) if settings.get("rounds") else None,
            status=str(draft.get("status")) if draft.get("status") else None,
            draft_type=str(draft.get("type")) if draft.get("type") else None,
            # draft_order is authoritative and immutable once the draft opens, so that answer
            # sticks and the two extra requests behind it are skipped from then on.
            identity=None if slot_locked else self._identity(draft),
        )


# --- ESPN ---------------------------------------------------------------------------------

# Our draft-status vocabulary is Sleeper's, because the UI already codes against it. ESPN
# reports two booleans instead; this is the whole translation.
ESPN_PRE_DRAFT = "pre_draft"
ESPN_DRAFTING = "drafting"
ESPN_COMPLETE = "complete"


def espn_draft_status(detail: dict[str, Any]) -> str:
    if detail.get("drafted"):
        return ESPN_COMPLETE
    if detail.get("inProgress"):
        return ESPN_DRAFTING
    return ESPN_PRE_DRAFT


def espn_slot_by_team(settings: dict[str, Any]) -> dict[int, int]:
    """``teamId -> draft slot`` from ``draftSettings.pickOrder``.

    pickOrder is the teamIds in seat order, and it is real commissioner-set data rather than a
    Sleeper-style placeholder: measured ``[2, 3, 6, 4, 1, 5, 7, 8]``, which is not the identity
    map and matches the round-1 slate exactly.
    """
    order = (settings.get("draftSettings") or {}).get("pickOrder") or []
    return {int(team_id): slot for slot, team_id in enumerate(order, start=1)}


def espn_rounds(settings: dict[str, Any]) -> int | None:
    """How many rounds the draft runs: every roster slot that is drafted, IR excluded.

    Read from the settings block the draft poll ALREADY fetched. Calling the adapter's
    standalone ``draft_rounds`` here would fire a second, unconditional request on every tick
    -- which is exactly what the single-request design exists to avoid.

    Derived from roster structure rather than from the pick slate, so the clock stays right
    whatever ESPN chooses to serve in ``draftDetail.picks`` once a draft is under way.
    """
    from ..adapters.espn import IR_LINEUP_SLOT

    counts = (settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    total = 0
    ir = 0
    for slot_id, count in counts.items():
        try:
            slot, number = int(slot_id), int(count)
        except (TypeError, ValueError):
            continue
        total += number
        if slot == IR_LINEUP_SLOT:
            ir = number
    return (total - ir) or None


def espn_my_team_id(teams: list[dict[str, Any]], swid: str | None) -> int | None:
    """Which team is mine, by matching my SWID cookie against ``teams[].owners``.

    Derived rather than configured: the cookie that authenticates the request already says who
    I am, so a ``--slot`` flag would just be a second place for the answer to be wrong.
    """
    if not swid:
        return None
    wanted = swid.strip().upper()
    for team in teams:
        owners = [str(o).strip().upper() for o in (team.get("owners") or [])]
        if str(team.get("primaryOwner") or "").strip().upper() == wanted or wanted in owners:
            return int(team["id"])
    return None


class EspnIdBridge:
    """ESPN player id -> the id space the board is built in.

    The board is built from Sleeper stat lines for BOTH leagues, so an ESPN pick arrives
    carrying an id the board has never seen. Without translation nothing would ever be marked
    drafted: every pick would look like a player who is not on the board, and the cockpit would
    keep recommending players who are already gone.

    The map comes from the Sleeper catalog's own ``espn_id`` field, which is cached on disk for
    a day, so it costs one read. When ``build_board`` reads from the platform adapter this
    becomes an identity map and the class goes away.

    An id that will not translate keeps its ESPN value rather than being dropped: the pick
    really happened, so the clock must move and the player must count as taken even when we
    cannot name him. Those are counted and logged, never silently absorbed.
    """

    def __init__(
        self, id_map: dict[str, str] | None = None, *, adapter: Any | None = None,
        config: LeagueConfig | None = None,
    ) -> None:
        # A preset map skips the catalog read entirely -- which is how tests stay offline.
        self._map: dict[str, str] | None = id_map
        self.unmatched: set[str] = set()
        # For the name-match supplement: the ESPN pool comes from the adapter that is already
        # authenticated, so this costs one extra request at STARTUP and none per pick.
        self._adapter = adapter
        self._config = config
        self.supplement_size = 0

    def _load(self) -> dict[str, str]:
        if self._map is None:
            from ..adapters.sleeper import SleeperAdapter

            with SleeperAdapter() as sleeper:
                catalog = sleeper.get_players_catalog()
            built = {
                str(entry["espn_id"]): str(player_id)
                for player_id, entry in catalog.items()
                if isinstance(entry, dict) and entry.get("espn_id")
            }
            # ADDITIVE. The catalog is authoritative where it has an answer; the name match
            # only fills ids it left blank, which is 143 of the top 200. `setdefault` is the
            # whole guarantee -- this can add coverage and can never overwrite it.
            if self._adapter is not None and self._config is not None:
                from .espn_ids import build_supplement

                try:
                    pool = self._adapter.get_player_pool(self._config)
                    supplement = build_supplement(pool, catalog)
                except Exception as exc:  # noqa: BLE001 -- degrade to catalog-only, never fail
                    log.warning("ESPN name-match supplement unavailable (%s); "
                                "falling back to the catalog-only bridge", exc)
                    supplement = {}
                before = len(built)
                for espn_id, board_id in supplement.items():
                    built.setdefault(espn_id, board_id)
                self.supplement_size = len(built) - before
                log.info("ESPN->board id bridge: %d from the catalog, %d added by name match",
                         before, self.supplement_size)
            self._map = built
            log.info("ESPN->board id bridge: %d players", len(self._map))
        return self._map

    def warm(self) -> int:
        """Build the map NOW rather than on the first pick translation.

        The lazy load fired on the first pick of the draft, which is when a cold Sleeper
        catalog would have been fetched over the network -- at the worst possible moment.
        """
        return len(self._load())

    def to_board_id(self, espn_player_id: int | str) -> str:
        espn_id = str(espn_player_id)
        board_id = self._load().get(espn_id)
        if board_id is not None:
            return board_id
        if espn_id not in self.unmatched:
            self.unmatched.add(espn_id)
            log.warning(
                "ESPN player %s has no board row; the pick still counts but he cannot be "
                "named or removed from the board", espn_id,
            )
        return espn_id

    def translate_logged(self, espn_player_id: int | str) -> str:
        """`to_board_id`, but announcing every hit -- the evening has to be auditable."""
        board_id = self.to_board_id(espn_player_id)
        if str(board_id) != str(espn_player_id):
            log.info("ESPN %s -> board %s", espn_player_id, board_id)
        return board_id


def espn_picks(
    detail: dict[str, Any], slot_by_team: dict[int, int], bridge: EspnIdBridge
) -> list[Pick]:
    """Real picks only, in pick order.

    ``playerId: -1`` is the placeholder slate -- pre-draft ESPN serves a COMPLETE 128-entry
    grid of every pick the draft will ever have, one row per seat per round, all unfilled. A
    sync that counts rows instead of filtering on this reports a finished draft before the
    first selection is made.
    """
    from ..adapters.espn import UNDRAFTED_PLAYER_ID

    picks: list[Pick] = []
    for row in detail.get("picks") or []:
        player_id = row.get("playerId")
        if player_id is None or int(player_id) == UNDRAFTED_PLAYER_ID:
            continue
        team_id = row.get("teamId")
        picks.append(
            Pick(
                pick_no=int(row.get("overallPickNumber") or 0),
                round=int(row.get("roundId") or 0),
                draft_slot=slot_by_team.get(int(team_id), 0) if team_id is not None else 0,
                player_id=bridge.translate_logged(player_id),
            )
        )
    return sorted(picks, key=lambda p: p.pick_no)


class EspnSync:
    """ESPN's whole draft in one conditional GET per tick."""

    name = "espn"

    def __init__(
        self,
        config: LeagueConfig,
        *,
        slot_override: int | None = None,
        adapter: Any | None = None,
        bridge: EspnIdBridge | None = None,
    ) -> None:
        from ..adapters.espn import EspnAdapter

        self._config = config
        self._adapter = adapter if adapter is not None else EspnAdapter()
        self._slot_override = slot_override
        self._bridge = bridge if bridge is not None else EspnIdBridge(
            adapter=self._adapter, config=config
        )
        # Eagerly, at startup: see EspnIdBridge.warm.
        try:
            self._bridge.warm()
        except Exception as exc:  # noqa: BLE001 -- a cold bridge must not stop the cockpit
            log.warning("could not warm the ESPN id bridge at startup (%s); "
                        "it will build on the first pick", exc)

    def close(self) -> None:
        self._adapter.close()

    def _identity(self, payload: dict[str, Any], slot_by_team: dict[int, int]) -> Identity:
        """My seat, or an explicit unresolved state -- never a guess.

        A slot invented when it cannot be derived is the ``slot = 0`` bug: it reads as "me",
        which quietly attributes the entire room to my roster.
        """
        if self._slot_override is not None:
            return Identity(None, None, self._slot_override, SOURCE_OVERRIDE)
        team_id = espn_my_team_id(payload.get("teams") or [], self._adapter.swid)
        if team_id is None:
            return Identity(None, None, None, SOURCE_UNRESOLVED)
        slot = slot_by_team.get(team_id)
        if slot is None:
            return Identity(str(team_id), team_id, None, SOURCE_UNRESOLVED)
        return Identity(str(team_id), team_id, slot, SOURCE_PICK_ORDER)

    def poll(self, draft_id: str | None, *, want_meta: bool, slot_locked: bool) -> DraftUpdate:
        # want_meta and slot_locked are ignored on purpose: one request already carries state,
        # picks, teams and settings, so there is nothing cheaper to fetch and nothing stale to
        # hold on to. Re-resolving every tick also means a pre-draft pick order that the
        # commissioner reshuffles is followed rather than cached.
        payload = self._adapter.get_draft_detail(self._config)
        detail = payload.get("draftDetail") or {}
        settings = payload.get("settings") or {}
        slot_by_team = espn_slot_by_team(settings)

        # Everything below comes out of the ONE response above -- no second request per tick.
        rounds = espn_rounds(settings) or max(
            (int(r.get("roundId") or 0) for r in detail.get("picks") or []), default=0
        ) or None

        return DraftUpdate(
            # ESPN has no separate draft id -- the league IS the draft.
            draft_id=str(self._config.league_id),
            picks=espn_picks(detail, slot_by_team, self._bridge),
            rounds=rounds,
            status=espn_draft_status(detail),
            draft_type=str((settings.get("draftSettings") or {}).get("type") or "").lower()
            or None,
            identity=self._identity(payload, slot_by_team),
        )


def build_sync(
    config: LeagueConfig, *, slot_override: int | None = None, user_name: str | None = None
) -> DraftSync:
    """The draft sync for *config*'s platform."""
    if config.platform is Platform.SLEEPER:
        return SleeperSync(config, slot_override=slot_override, user_name=user_name)
    if config.platform is Platform.ESPN:
        return EspnSync(config, slot_override=slot_override)
    raise ValueError(f"no draft sync for platform {config.platform!r}")
