"""MCP surface over the running cockpit.

`audible` makes no model calls and holds no API key. It *exposes* itself: Claude reads these
tools and reasons about the numbers conversationally, while the ranking stays deterministic
Python. That split is the whole point -- the engine is testable and replayable, and it gives
the same answer whether you read it in the browser or ask about it in chat.

Every tool is a projection over :func:`audible.server.state.build_state`, reading the ONE
warmed :class:`CockpitService` the HTTP server already owns. No tool builds a board, opens a
session, or starts a poll loop; a second poller would disagree with the first about who is
available with no way to tell which is right.

Two rules the tools cannot break:

* **Every board-returning tool reports staleness.** Claude cannot know the sync stalled unless
  the payload says so, and confidently recommending a player who went three picks ago is the
  worst failure this system has.
* **Nothing writes to a platform.** ``mark_taken`` mutates local draft state only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from pydantic import Field

from ..draft.service import CockpitService
from .state import _player as _state_player
from .state import build_state

# Responses are read on a 60-second clock, so they are capped hard. A dump of 60 players is
# not more useful than 10; it is less useful.
MAX_ROWS = 25
DEFAULT_ROWS = 10


def _sync(state: dict[str, Any]) -> dict[str, Any]:
    """The staleness block every board-returning tool must carry."""
    sync = state.get("sync") or {}
    age = sync.get("age_s")
    return {
        "age_seconds": age,
        "status": sync.get("status"),
        "last_success": sync.get("last_success"),
        "warning": (
            None if sync.get("status") == "live"
            else f"Data is {age}s old ({sync.get('status')}). "
                 "Treat availability as unconfirmed and check the draft room before acting."
        ),
    }


def _not_ready(state: dict[str, Any]) -> dict[str, Any]:
    return {"board_ready": False, "message": state.get("message"), "sync": _sync(state)}


def _slim(player: dict[str, Any]) -> dict[str, Any]:
    """One player, trimmed to what a decision actually needs."""
    return {
        "id": player["id"],
        "name": player["name"],
        "position": player["position"],
        "team": player["team"],
        "consensus_rank": player["consensus_rank"],
        "vorp_rank": player["vorp_rank"],
        "opportunity_rank": player["opp_rank"],
        # None, not a number, when the market does not price him: survival is UNKNOWN there,
        # and reporting 100% would read as "safe to wait" on no evidence at all.
        "survival_pct": round(player["survival"] * 100) if player.get("adp_known") else None,
        "priced_by_market": player.get("adp_known", True),
        "fills_a_need": player["fills_need"],
        "grab_now": player["grab_now"],
        "opportunity_disagrees": player["deviation"],
        "flags": player["flags"],
    }


def build_mcp(service: CockpitService, *, auth_token: str | None = None) -> FastMCP:
    """The MCP server, bound to an already-warmed service."""
    auth = (
        StaticTokenVerifier(tokens={auth_token: {"client_id": "audible", "scopes": []}})
        if auth_token else None
    )
    mcp: FastMCP = FastMCP(name="audible", auth=auth)

    def state() -> dict[str, Any]:
        return build_state(service)

    # -- clock ------------------------------------------------------------------
    @mcp.tool
    def draft_status() -> dict[str, Any]:
        """Where the draft stands right now: whose pick it is, how many picks until mine, and
        how fresh the data is. Call this first in any conversation about the live draft, and
        again whenever more than a few picks may have passed."""
        s = state()
        if not s.get("board_ready"):
            return _not_ready(s)
        clock, roster = s["clock"], s["roster"]
        return {
            "current_pick": clock["current_pick"],
            "round": clock["round"],
            "on_the_clock_slot": clock["slot_on_clock"],
            "my_slot": clock["my_slot"],
            "my_slot_source": clock["my_slot_source"],
            "picks_until_mine": clock["picks_until_me"],
            "i_am_on_the_clock": clock["picks_until_me"] == 0,
            "my_next_pick": clock["my_next_pick"],
            "rival_picks_before_my_next": clock["opponent_picks_until_horizon"],
            "draft_complete": clock["complete"],
            "draft_started": s["draft"]["started"],
            "unfilled_starting_slots": roster["unfilled"],
            "sync": _sync(s),
        }

    # -- the board --------------------------------------------------------------
    @mcp.tool
    def best_available(
        limit: Annotated[int, Field(ge=1, le=MAX_ROWS)] = DEFAULT_ROWS,
        position: Annotated[str | None, Field(description="QB/RB/WR/TE/K/DL/LB/DB")] = None,
    ) -> dict[str, Any]:
        """The raw value board: the best players left, in league-value order, IGNORING what my
        roster needs. Use this to answer "who is the best player available" or to look at a
        position in isolation. For "who should I actually take", use `recommend` instead --
        this tool will happily put a fourth running back at the top."""
        s = state()
        if not s.get("board_ready"):
            return _not_ready(s)
        # Filter the FULL ranked pool, never the served slice. The slice is a global top-N by
        # value, so filtering it answers "how many LBs are in the top 60" (2) when the question
        # is "how many LBs are available" (1,136).
        view = service.view()
        rows = s["best_available"] if view is None else [
            _state_player(c) for c in view.ranked
        ]
        if position:
            want = position.strip().upper()
            rows = [p for p in rows if p["position"] == want]
        priced = sum(1 for p in rows if p.get("adp_known"))
        return {
            "players": [_slim(p) for p in rows[:limit]],
            "returned": min(len(rows), limit),
            "available_matching": len(rows),
            "of_which_priced_by_market": priced,
            "note": ("Players the market does not price are still AVAILABLE; their survival "
                     "is unknown, not high." if priced < len(rows) else None),
            "sync": _sync(s),
        }

    @mcp.tool
    def recommend(
        limit: Annotated[int, Field(ge=1, le=MAX_ROWS)] = 5,
    ) -> dict[str, Any]:
        """What to actually draft at my next pick, weighing league value against my unfilled
        starting slots and against how likely each player is to survive until I pick again.
        This is the roster-aware answer and the one to use on the clock. Each row carries a
        deterministic reason; the ranking is computed in Python, not inferred here."""
        s = state()
        if not s.get("board_ready"):
            return _not_ready(s)
        clock = s["clock"]
        rivals = clock["opponent_picks_until_horizon"]
        unfilled = s["roster"]["unfilled"]

        # Need first, then value. Among players who fill a hole, the ones unlikely to last are
        # the real decision; everything else can wait by definition.
        pool = s["best_available"]
        need = [p for p in pool if p["fills_need"]]
        ranked = (need or pool)[: limit * 3]
        ranked = sorted(ranked, key=lambda p: (not p["grab_now"], p["vorp_rank"]))[:limit]

        out = []
        for p in ranked:
            row = _slim(p)
            bits = [f"VORP #{p['vorp_rank']} (consensus #{p['consensus_rank']})"]
            bits.append("fills an unfilled starting slot" if p["fills_need"]
                        else "does not fill a starting slot")
            if rivals is not None:
                bits.append(
                    f"{row['survival_pct']}% to last the {rivals} rival picks before my next"
                )
            if p["grab_now"]:
                bits.append("unlikely to survive -- take him now or lose him")
            if p["deviation"]:
                bits.append("our opportunity model disagrees sharply with consensus here")
            row["reason"] = "; ".join(bits)
            out.append(row)

        return {
            "recommendations": out,
            "unfilled_starting_slots": unfilled,
            "starters_complete": s["roster"]["starters_complete"],
            "picks_until_mine": clock["picks_until_me"],
            "rival_picks_before_my_next": rivals,
            "basis": ("roster need, then league value, with survival to my next pick as the "
                      "tiebreaker"),
            "sync": _sync(s),
        }

    @mcp.tool
    def player_lookup(name: str) -> dict[str, Any]:
        """Everything known about one player by name (partial matches allowed): all three
        ranks, survival, flags, and whether he is still available."""
        s = state()
        if not s.get("board_ready"):
            return _not_ready(s)
        q = name.strip().lower()
        view = service.view()  # search the full pool, not the served slice
        pool = s["best_available"] if view is None else [
            _state_player(c) for c in view.ranked
        ]
        hits = [p for p in pool if q in p["name"].lower()]
        if not hits:
            gone = [p for p in s["recent_picks"] if q in str(p["name"]).lower()]
            return {
                "found": False,
                "already_drafted": [
                    {"name": p["name"], "position": p["position"], "pick_no": p["pick_no"],
                     "by_slot": p["slot"]} for p in gone
                ],
                "message": (f"No available player matches {name!r}."
                            + (" He has already been drafted." if gone else
                               " He may be drafted, or outside the top of the board.")),
                "sync": _sync(s),
            }
        return {"found": True, "matches": [_slim(p) for p in hits[:5]], "sync": _sync(s)}

    @mcp.tool
    def compare(names: Annotated[list[str], Field(min_length=2, max_length=5)]) -> dict[str, Any]:
        """Put 2-5 available players side by side on the same axes, so the tradeoff between
        them is explicit rather than inferred from separate lookups."""
        s = state()
        if not s.get("board_ready"):
            return _not_ready(s)
        view = service.view()  # full pool, so a deep player is comparable
        pool = s["best_available"] if view is None else [
            _state_player(c) for c in view.ranked
        ]
        found, missing = [], []
        for n in names:
            q = n.strip().lower()
            hit = next((p for p in pool if q in p["name"].lower()), None)
            (found.append(_slim(hit)) if hit else missing.append(n))
        return {
            "players": found,
            "not_available": missing,
            "axes": ["consensus_rank", "vorp_rank", "opportunity_rank", "survival_pct",
                     "fills_a_need"],
            "sync": _sync(s),
        }

    # -- context ----------------------------------------------------------------
    @mcp.tool
    def my_roster() -> dict[str, Any]:
        """My team so far: every starting slot, who fills it, and what is still open."""
        s = state()
        if not s.get("board_ready"):
            return _not_ready(s)
        r = s["roster"]
        return {
            "slots": r["slots"],
            "unfilled": r["unfilled"],
            "starters_complete": r["starters_complete"],
            "sync": _sync(s),
        }

    @mcp.tool
    def recent_picks(
        limit: Annotated[int, Field(ge=1, le=30)] = 12,
    ) -> dict[str, Any]:
        """The last N picks plus positional run detection -- what the room is doing right now.
        A run means the position is drying up faster than ADP implies."""
        s = state()
        if not s.get("board_ready"):
            return _not_ready(s)
        return {
            "picks": s["recent_picks"][:limit],
            "position_counts_last_10": s["counts_last10"],
            "runs": s["runs"],
            "tier_cliffs": s["cliffs"],
            "sync": _sync(s),
        }

    # -- local availability override --------------------------------------------
    @mcp.tool
    def mark_taken(player_id: str) -> dict[str, Any]:
        """Mark a player unavailable in MY LOCAL board only -- nothing is ever written to
        Sleeper or ESPN. This is the fallback when live sync lags or for a league with no
        sync at all. Idempotent, and `undo_taken` fully reverses it. Takes the player `id`
        from any board tool, not a name."""
        changed = service.mark_taken(player_id)
        s = state()
        return {
            "player_id": player_id,
            "changed": changed,
            "note": "already marked" if not changed else "marked unavailable locally",
            "manual_overrides": len(service.session.manual_taken),
            "sync": _sync(s),
        }

    @mcp.tool
    def undo_taken(player_id: str | None = None) -> dict[str, Any]:
        """Reverse a `mark_taken`. With no id, reverses the most recent one."""
        undone = service.undo_taken(player_id)
        s = state()
        return {
            "undone": undone,
            "note": "nothing to undo" if undone is None else f"{undone} is available again",
            "manual_overrides": len(service.session.manual_taken),
            "sync": _sync(s),
        }

    return mcp


__all__ = ["build_mcp"]


# Kept narrow on purpose: the tool surface is the API, and every extra tool is one more thing
# for a model to pick wrongly at pick 47 with forty seconds on the clock.
ToolName = Literal[
    "draft_status", "best_available", "recommend", "my_roster",
    "player_lookup", "compare", "recent_picks", "mark_taken", "undo_taken",
]
