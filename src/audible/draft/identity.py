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
#
# THREE HUMAN-VISIBLE STATES, and they are three because two could not be told apart. Until
# 2026-09-07 a config pin and an operator's `--slot` both reported "override", so the served
# value could not say whether the live answer had been DELIBERATELY overridden or was merely
# ABSENT. That is the same defect #64 fixed in `verify-scoring`: a value you cannot trace to
# its source is not a value you can act on.
SOURCE_DRAFT_ORDER = "draft_order"  # Sleeper, authoritative once the draft opens
SOURCE_PICK_ORDER = "pick_order"  # ESPN draftSettings.pickOrder, re-read every poll
SOURCE_OVERRIDE = "override"  # an operator's explicit --slot; deliberately beats the platform
SOURCE_CONFIG_PIN = "config_pin"  # the league's draft_slot, CARRIED because nothing derived
SOURCE_UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str | None
    roster_id: int | None
    slot: int | None
    source: str
    # What the PLATFORM derived, whether or not a pin is in force.
    #
    # `slot` is what the cockpit acts on, so a pin overwrites it -- that is the pin's whole
    # job. But overwriting it also erased the only other opinion in the system, which made
    # "the pin disagrees with the draft room" unrepresentable rather than merely unreported.
    # Keeping the derivation beside the decision is what lets anything downstream compare
    # them. None means the platform could not say (no SWID match, no pick order yet), which
    # is NOT a disagreement -- silence never contradicts a pin.
    derived_slot: int | None = None
    # The human-supplied seat that was available this poll -- an operator's `--slot` or the
    # league's `draft_slot`, whichever was in play. Kept BESIDE the decision for the same
    # reason `derived_slot` is: once the live derivation started winning, `slot` stopped being
    # the pin, so comparing `slot` against the platform would have compared the platform with
    # itself and made the disagreement unrepresentable all over again -- in the other
    # direction. None means nothing was pinned at all.
    pinned_slot: int | None = None

    @property
    def resolved(self) -> bool:
        return self.slot is not None

    @property
    def seat_conflict(self) -> bool:
        """A human-supplied seat and the platform both answered, and they disagree.

        Deliberately independent of which one WON. A pin that loses to the live derivation is
        still a pin that is wrong, and the operator still has to know: on 2026-09-07 the Green
        Hope commissioner re-drew the pick order, and the config kept saying 1 while ESPN said
        6. Reporting only when the pin wins would report only the case where nothing needs
        deciding.
        """
        return (
            self.pinned_slot is not None
            and self.derived_slot is not None
            and self.pinned_slot != self.derived_slot
        )


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
    fallback: int | None = None,
) -> Identity:
    """Work out which draft slot is mine.

    THREE TIERS, and the middle one moved on 2026-09-07:

    1. an explicit *override* -- an operator's ``--slot``. Still wins outright: it is how
       rehearsal against someone else's completed draft works, and an operator who types a
       seat has said something the tool has no business second-guessing.
    2. the LIVE derivation from ``draft_order``.
    3. *fallback* -- the league config's ``draft_slot``.

    Tier 3 used to be tier 1, and that was the defect. ``schema.py`` documents the pin as the
    thing that keeps the timing term alive when sync cannot answer -- a FALLBACK -- but it was
    wired to outrank the platform, so a config value beat a live one. Green Hope proved the
    cost: the commissioner re-drew the pick order, ESPN said seat 6, the config said 1, and
    the cockpit served 1 for hours while logging the disagreement it was ignoring.

    A fallback that beats a live answer is not a fallback. Silence still never contradicts a
    pin -- when the derivation returns None the pin is carried, which is its actual job.
    """
    roster_id = roster_id_for_user(rosters, user_id) if user_id else None

    # Derived FIRST, and unconditionally. It used to be computed only when no override was
    # set, which made a pin that disagrees with the draft room impossible to observe -- the
    # one state the pin exists to protect against.
    order = draft.get("draft_order") or {}
    raw = order.get(user_id) if user_id else None
    derived = int(raw) if raw is not None else None
    pinned = override if override is not None else fallback

    if override is not None:
        return Identity(user_id, roster_id, override, SOURCE_OVERRIDE,
                        derived_slot=derived, pinned_slot=pinned)
    if derived is not None:
        return Identity(user_id, roster_id, derived, SOURCE_DRAFT_ORDER,
                        derived_slot=derived, pinned_slot=pinned)
    if fallback is not None:
        return Identity(user_id, roster_id, fallback, SOURCE_CONFIG_PIN,
                        derived_slot=derived, pinned_slot=pinned)
    return Identity(user_id, roster_id, None, SOURCE_UNRESOLVED)


def roster_id_for_slot(draft: dict[str, Any], slot: int) -> int | None:
    """``slot_to_roster_id`` uses STRING keys; index it accordingly."""
    mapping = draft.get("slot_to_roster_id") or {}
    value = mapping.get(str(slot))
    return int(value) if value is not None else None
