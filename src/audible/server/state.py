"""Serialise the cockpit into the JSON the page renders.

Kept apart from the FastAPI wiring so the exact payload can be asserted in tests without
standing up a server. Shapes here are the contract the browser codes against; changing a key
is a breaking change to the UI.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ..draft.live import Candidate, LiveView
from ..draft.service import CockpitService

GRAB_NOW_LIMIT = 5
# The page shows ~25 rows; the rest feed name search and the position tabs.
BEST_AVAILABLE_LIMIT = 60
# ...but a global top-60 by VORP holds 2 LBs and zero Ks in League A, so a position tab built
# from it would report that 2 linebackers exist when 1,136 do. Every rosterable position also
# contributes its own depth, so filtering never sees a pre-truncated pool.
PER_POSITION_DEPTH = 30
RECENT_PICKS_LIMIT = 12
RUN_WINDOW = 10


def _player(cand: Candidate) -> dict[str, Any]:
    e = cand.entry
    return {
        "id": e.player_id,
        "name": e.name,
        "position": e.position,
        "team": e.team,
        "consensus_rank": e.consensus_rank,
        "vorp_rank": e.vorp_rank,
        "opp_rank": e.opp_rank,
        "survival": round(cand.survival, 4),
        # An unpriced player is AVAILABLE with unknown survival, not absent. survival reads
        # 1.0 for him because the market queue cannot rank someone it does not price -- that
        # is an absence of evidence, and the UI must not present it as evidence of safety.
        "adp_known": e.adp is not None,
        "value": e.value,
        "points": round(e.points, 1),
        "grab_now": cand.grab_now,
        "fills_need": cand.fills_need,
        "deviation": e.deviation,
        "flags": list(e.flags),
    }


def _served_pool(service: CockpitService, view: LiveView) -> list[Candidate]:
    """The global top slice PLUS per-position depth, in value order, deduplicated.

    Serving only a global top-N is what made the board look truncated: every position filter
    and every name search downstream could only ever see those N rows. Sending all ~7,600
    available players on a 2s poll is the other extreme, so each rosterable position also
    contributes its own best PER_POSITION_DEPTH. A filter therefore never reads a pool that
    was cut before it ran.
    """
    keep: set[str] = {c.entry.player_id for c in view.ranked[:BEST_AVAILABLE_LIMIT]}
    for position in sorted(service.config.positions):
        depth = 0
        for cand in view.ranked:
            if cand.entry.position != position:
                continue
            keep.add(cand.entry.player_id)
            depth += 1
            if depth >= PER_POSITION_DEPTH:
                break
    return [c for c in view.ranked if c.entry.player_id in keep]


def _roster_slots(view: LiveView) -> list[dict[str, Any]]:
    """Every starting slot and exactly who fills it, grouped by slot name in config order."""
    grouped: dict[str, dict[str, Any]] = {}
    for slot, entry in view.roster_slots:
        row = grouped.setdefault(slot, {"slot": slot, "total": 0, "filled": 0, "players": []})
        row["total"] += 1
        if entry is not None:
            row["filled"] += 1
            row["players"].append({"name": entry.name, "position": entry.position})
    return list(grouped.values())


def _recent_picks(service: CockpitService) -> list[dict[str, Any]]:
    board = service.board
    by_id = {e.player_id: e for e in board.entries} if board else {}
    picks = sorted(service.session.picks, key=lambda p: p.pick_no)[-RECENT_PICKS_LIMIT:]
    rows: list[dict[str, Any]] = []
    for p in reversed(picks):
        entry = by_id.get(p.player_id)
        rows.append({
            "pick_no": p.pick_no,
            "name": entry.name if entry else p.player_id,
            "position": entry.position if entry else "?",
            "team": entry.team if entry else None,
            "slot": p.draft_slot,
            "mine": p.draft_slot == service.session.slot,
        })
    return rows


def _counts_last10(service: CockpitService) -> dict[str, int]:
    board = service.board
    by_id = {e.player_id: e for e in board.entries} if board else {}
    counts: dict[str, int] = {}
    for p in sorted(service.session.picks, key=lambda p: p.pick_no)[-RUN_WINDOW:]:
        entry = by_id.get(p.player_id)
        if entry is not None:
            counts[entry.position] = counts.get(entry.position, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _runs(service: CockpitService, view: LiveView) -> list[dict[str, Any]]:
    superflex = "SUPER_FLEX" in service.config.starting_slots
    counts = _counts_last10(service)
    ranked: list[tuple[bool, int, dict[str, Any]]] = []
    for position, count in counts.items():
        if count < 3:
            continue
        # In a superflex league a QB run is the single most consequential thing that can happen
        # between your picks -- there are two QB-capable slots and only ten teams' worth of
        # startable QBs -- so it leads the column even when a bigger run is happening elsewhere.
        hot = position == "QB" and superflex
        ranked.append((hot, count, {
            "position": position,
            "count": count,
            "window": RUN_WINDOW,
            "severity": "high" if (hot or count >= 5) else "medium",
            "text": (f"{position} run - {count} of the last {RUN_WINDOW}"
                     + (" - SUPERFLEX QB RUN" if hot else "")),
        }))
    ranked.sort(key=lambda r: (not r[0], r[2]["severity"] != "high", -r[1]))
    return [run for _, _, run in ranked]


def _cliffs(view: LiveView) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for text in view.cliffs:
        position = text.split(":", 1)[0].strip()
        out.append({"position": position, "text": text, "gap": None})
    return out


def build_state(service: CockpitService) -> dict[str, Any]:
    """The full `/api/state` payload."""
    now = time.time()
    session = service.session
    health = service.health
    age = health.age_s(now)

    base: dict[str, Any] = {
        "ok": True,
        "board_ready": service.board is not None,
        "message": None,
        "league": {
            "key": service.config.key,
            "name": service.config.name,
            "num_teams": service.config.num_teams,
            "superflex": "SUPER_FLEX" in service.config.starting_slots,
        },
        "draft": {
            "id": session.draft_id,
            "status": session.draft_status,
            "type": session.draft_type,
            "rounds": session.rounds,
            "started": session.draft_status not in ("pre_draft", ""),
        },
        "sync": {
            "age_s": round(age, 1) if age is not None else None,
            "status": health.status(now),
            "last_error": health.last_error,
            "last_success": (
                datetime.fromtimestamp(health.last_success).strftime("%H:%M:%S")
                if health.last_success else None
            ),
            "poll_count": health.poll_count,
        },
    }

    if service.board is None:
        base["ok"] = service.board_error is None
        base["message"] = (
            f"Board build failed - {service.board_error}. Fix the cause and restart; "
            "the cockpit will not guess."
            if service.board_error else
            "Building the draft board from Sleeper and nflverse. This runs once at startup "
            "and takes a minute or two on a cold cache."
        )
        return base

    view = service.view()
    if view is None:  # board present but view unavailable -- should not happen
        base["ok"] = False
        base["message"] = "Board is present but no view could be computed."
        return base

    opponent_picks = view.opponent_picks_until_horizon
    grab = [c for c in view.best_available if c.grab_now][:GRAB_NOW_LIMIT]

    base["clock"] = {
        "current_pick": view.current_pick,
        "round": (view.current_pick - 1) // service.config.num_teams + 1,
        "slot_on_clock": view.on_the_clock,
        "label": (
            f"R{(view.current_pick - 1) // service.config.num_teams + 1}.{view.on_the_clock}"
            if view.on_the_clock else "-"
        ),
        "my_slot": session.slot,
        "my_slot_source": session.slot_source,
        "my_next_pick": view.my_next_pick,
        "picks_until_me": view.picks_until_me,
        "survival_horizon": view.survival_horizon,
        "opponent_picks_until_horizon": opponent_picks,
        "complete": view.on_the_clock is None,
    }
    base["roster"] = {
        "slots": _roster_slots(view),
        "unfilled": list(view.unfilled),
        "starters_complete": view.starters_complete,
    }
    base["grab_now"] = [_player(c) for c in grab]
    base["best_available"] = [_player(c) for c in _served_pool(service, view)]
    base["recent_picks"] = _recent_picks(service)
    base["runs"] = _runs(service, view)
    base["cliffs"] = _cliffs(view)
    base["counts_last10"] = _counts_last10(service)
    return base
