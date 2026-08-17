"""Resolving *my* draft slot from Sleeper's identity graph.

The join is ``user_id -> draft_order[user_id] -> slot``, cross-checked against
``slot_to_roster_id[str(slot)] -> roster_id`` and ``rosters[].owner_id``. It is separated out
because every part of it has a trap:

* ``draft_order`` is ``null`` until the draft actually opens, so pre-draft there is no slot to
  resolve -- only an override.
* ``slot_to_roster_id`` still *exists* pre-draft, as the identity map ``{1:1, ..., 10:10}``.
  It looks authoritative and is not: the completed 2025 draft of the same league shows
  ``{1:4, 2:2, 3:6, 4:3, ...}``. A slot derived from it before the draft opens is a guess, so
  a resolution derived pre-draft is never cached.
* ``users`` and ``rosters`` are not 1:1 in either direction. The 2026 league has 9 users and
  10 rosters, two rosters with ``owner_id: null``, and a co-owner who owns no roster.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Where a resolved slot came from, so the UI can be honest about how much to trust it.
SOURCE_DRAFT_ORDER = "draft_order"  # Sleeper, authoritative once the draft opens
SOURCE_PICK_ORDER = "pick_order"  # ESPN draftSettings.pickOrder, re-read every poll
SOURCE_OVERRIDE = "override"
SOURCE_UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str | None
    roster_id: int | None
    slot: int | None
    source: str

    @property
    def resolved(self) -> bool:
        return self.slot is not None


def roster_id_for_user(rosters: list[dict[str, Any]], user_id: str) -> int | None:
    """My roster, via ``owner_id`` and falling back to ``co_owners``."""
    for roster in rosters:
        if str(roster.get("owner_id") or "") == user_id:
            return int(roster["roster_id"])
    for roster in rosters:
        co = roster.get("co_owners") or []
        if any(str(c) == user_id for c in co):
            return int(roster["roster_id"])
    return None


def user_id_for_name(users: list[dict[str, Any]], display_name: str) -> str | None:
    wanted = display_name.strip().casefold()
    for user in users:
        for key in ("display_name", "username"):
            if str(user.get(key) or "").strip().casefold() == wanted:
                return str(user["user_id"])
    return None


def resolve_slot(
    draft: dict[str, Any],
    rosters: list[dict[str, Any]],
    user_id: str | None,
    *,
    override: int | None = None,
) -> Identity:
    """Work out which draft slot is mine.

    An explicit *override* always wins -- it is how rehearsal against someone else's completed
    draft works. Otherwise the slot comes from ``draft_order``, and only from ``draft_order``:
    if it is absent the answer is "unresolved", never a guess off the placeholder map.
    """
    roster_id = roster_id_for_user(rosters, user_id) if user_id else None

    if override is not None:
        return Identity(user_id, roster_id, override, SOURCE_OVERRIDE)

    order = draft.get("draft_order") or {}
    if user_id and (slot := order.get(user_id)) is not None:
        return Identity(user_id, roster_id, int(slot), SOURCE_DRAFT_ORDER)

    return Identity(user_id, roster_id, None, SOURCE_UNRESOLVED)


def roster_id_for_slot(draft: dict[str, Any], slot: int) -> int | None:
    """``slot_to_roster_id`` uses STRING keys; index it accordingly."""
    mapping = draft.get("slot_to_roster_id") or {}
    value = mapping.get(str(slot))
    return int(value) if value is not None else None
