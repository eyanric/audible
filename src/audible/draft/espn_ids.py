"""Supplementary ESPN player id -> board id matching, by name and position.

WHY THIS EXISTS. The board is built from Sleeper data; ESPN's draft feed reports picks with
ESPN ids. `EspnIdBridge` translates through the Sleeper catalog's ``espn_id`` field, and that
field is blank for **143 of the top 200** -- Gibbs, Bijan, Nacua and Chase among them. On a
miss the pick counts and the clock advances, but the player never leaves the board, so the
cockpit keeps recommending someone already drafted. Measured before this module: 57/200.
With it: 200/200, with zero ambiguous matches.

WHAT IT WILL NOT DO. A MISSED match leaves a drafted player on the board -- visible, annoying,
survivable. A WRONG match removes the wrong player and credits him to a roster, silently and
unrecoverably. Those risks are not symmetric, so matching here is deliberately timid:

  * exact normalised name AND position must both agree;
  * the pair must be UNIQUE on both sides -- two Josh Allens means no match, not a guess;
  * nothing is inferred from team, jersey number, or fuzzy distance.

It is additive. `EspnIdBridge` tries the catalog first, this second, and on any miss still
passes the raw ESPN id through exactly as it did before -- so the worst case is the behaviour
that shipped this morning, never worse.

KILL SWITCH. Set AUDIBLE_ESPN_NAME_MATCH=0 to disable this entirely and revert to the
catalog-only bridge.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any

from .rookies import normalize_name

log = logging.getLogger(__name__)

ENV_KILL_SWITCH = "AUDIBLE_ESPN_NAME_MATCH"

# ESPN spells Washington WSH; the Sleeper catalog (and so the board) spells it WAS. This is
# the only abbreviation the two disagree on across all 32 D/ST rows, and it is a rename rather
# than an ambiguity, so it is safe to state explicitly. Anything not listed here is matched
# only when the two sides already agree.
TEAM_ALIASES: dict[str, str] = {"WSH": "WAS"}


def disabled() -> bool:
    """True when the kill switch is set. Checked at build time, not per lookup."""
    return os.environ.get(ENV_KILL_SWITCH, "1").strip().lower() in ("0", "false", "no", "off")


def _as_int(value: object) -> int:
    """ESPN serves these as ints, but a string would silently miss every lookup."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1


def _espn_index(pool: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    """(position, key) -> [espn id]. D/ST keys on the team abbreviation, everyone else on name."""
    from ..adapters.espn import POSITION_ID_TO_BUCKET, PRO_TEAM_BY_ID

    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in pool:
        player = row.get("player") or row
        espn_id = player.get("id")
        position = POSITION_ID_TO_BUCKET.get(_as_int(player.get("defaultPositionId")))
        if espn_id is None or not position:
            continue
        if position == "DEF":
            abbrev = PRO_TEAM_BY_ID.get(_as_int(player.get("proTeamId")))
            if not abbrev:
                continue
            key = TEAM_ALIASES.get(abbrev, abbrev)
        else:
            key = normalize_name(player.get("fullName"))
            if not key:
                continue
        index[(position, key)].append(str(espn_id))
    return index


def _board_index(catalog: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """(position, key) -> [board id], from the same catalog the board is built from."""
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for player_id, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        position = entry.get("position")
        if not position:
            continue
        if position == "DEF":
            key = str(player_id)  # the catalog keys D/ST by team abbreviation
        else:
            key = normalize_name(entry.get("full_name"))
            if not key:
                continue
        index[(position, key)].append(str(player_id))
    return index


def build_supplement(
    pool: list[dict[str, Any]], catalog: dict[str, Any]
) -> dict[str, str]:
    """``espn id -> board id`` for pairs that match uniquely on BOTH sides.

    Ambiguity on either side is dropped rather than resolved -- see the module docstring on
    why a wrong match is the expensive kind of error.
    """
    if disabled():
        log.warning(
            "%s is set: ESPN name matching is OFF, falling back to the catalog-only bridge",
            ENV_KILL_SWITCH,
        )
        return {}

    espn = _espn_index(pool)
    board = _board_index(catalog)
    supplement: dict[str, str] = {}
    ambiguous = 0
    for key, espn_ids in espn.items():
        board_ids = board.get(key)
        if not board_ids:
            continue
        if len(espn_ids) != 1 or len(board_ids) != 1:
            ambiguous += 1
            continue
        supplement[espn_ids[0]] = board_ids[0]
    log.info(
        "ESPN name-match supplement: %d ids matched, %d ambiguous pairs skipped",
        len(supplement), ambiguous,
    )
    return supplement
