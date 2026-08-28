"""FastAPI cockpit. One page, one poll loop, served from memory.

Two independent cadences, deliberately uncoupled: the service polls Sleeper every 5s in a
background thread, and the browser polls ``/api/state`` every 2s. A request never waits on an
upstream call, so a slow or failing Sleeper cannot make the page hang -- it only makes the
staleness indicator climb, which is exactly the information the user needs.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..config.schema import LeagueConfig
from ..draft.service import CockpitService
from .state import build_state

log = logging.getLogger("audible.cockpit")

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX = STATIC_DIR / "index.html"

# Beyond this the cached board is too old to bet a pick on; /healthz starts failing.
BOARD_MAX_AGE_S = 12 * 3600


class PlayerRef(BaseModel):
    player_id: str | None = None


def create_app(
    service: CockpitService, *, warm: bool = True, mcp_token: str | None = None
) -> FastAPI:
    @asynccontextmanager
    async def cockpit_lifespan(app: FastAPI):
        service.restore()
        if warm:
            service.warm_board()
            service.start()
        yield
        service.stop()

    # MCP rides the SAME process and the SAME service instance as the UI. Its session manager
    # needs its own lifespan, so the two are combined rather than one replacing the other --
    # dropping either leaves a half-initialised server that fails at the first tool call.
    from fastmcp.utilities.lifespan import combine_lifespans

    from .mcp import build_mcp

    mcp_app = build_mcp(service, auth_token=mcp_token).http_app(path="/")
    app = FastAPI(
        title="audible cockpit", docs_url=None, redoc_url=None,
        lifespan=combine_lifespans(cockpit_lifespan, mcp_app.lifespan),
    )
    app.mount("/mcp", mcp_app)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(INDEX, media_type="text/html")

    @app.get("/api/state")
    def api_state() -> JSONResponse:
        return JSONResponse(build_state(service))

    @app.post("/api/taken")
    def api_taken(ref: PlayerRef) -> JSONResponse:
        if ref.player_id:
            service.mark_taken(ref.player_id)
        return JSONResponse(build_state(service))

    @app.post("/api/taken/undo")
    def api_taken_undo(ref: PlayerRef) -> JSONResponse:
        service.undo_taken(ref.player_id)
        return JSONResponse(build_state(service))

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Liveness is not the question -- a live process serving a stale board is the danger."""
        board = service.board
        age = service.health.age_s()
        problems: list[str] = []
        if board is None:
            problems.append(service.board_error or "board not built")
        elif not board.entries:
            problems.append("board is empty")
        if age is not None and age > BOARD_MAX_AGE_S:
            problems.append(f"last successful poll {age:.0f}s ago")

        # Where the board's inputs came from and how old they are. On draft night a board
        # built from a three-week-old cache is a different thing to trust than one built
        # ten minutes ago, and the difference must be visible without reading logs.
        from ..adapters.nflverse import cache_summary

        data = cache_summary()

        body: dict[str, Any] = {
            "ok": not problems,
            "problems": problems,
            "players": len(board.entries) if board else 0,
            "sync_age_s": round(age, 1) if age is not None else None,
            "sync_status": service.health.status(),
            "draft_id": service.session.draft_id,
            "picks": len(service.session.picks),
            "data": {
                "sources": data["keys"],
                "oldest_age_s": data["oldest_age_s"],
                "newest_age_s": data["newest_age_s"],
                "from_disk": data["from_disk"],
                "from_network": data["from_network"],
                "origin": (
                    "disk" if data["from_network"] == 0 and data["from_disk"] else
                    "network" if data["from_disk"] == 0 and data["from_network"] else
                    "mixed" if data["from_disk"] or data["from_network"] else "none"
                ),
            },
        }
        return JSONResponse(body, status_code=200 if not problems else 503)

    return app


def serve(
    config: LeagueConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    draft_id: str | None = None,
    slot: int | None = None,
    user_name: str | None = None,
) -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    )
    # An explicit --slot still wins; the config seat is the fallback that keeps the timing
    # term alive when sync cannot answer.
    seat = slot if slot is not None else config.draft_slot
    service = CockpitService(
        config, draft_id=draft_id, slot_override=seat, user_name=user_name
    )
    if seat is not None:
        log.info("draft slot pinned to %s (%s)", seat,
                 "--slot" if slot is not None else f"{config.key}.draft_slot")
    token = os.environ.get("MCP_AUTH_TOKEN") or None
    app = create_app(service, mcp_token=token)
    log.info("cockpit for [%s] %s -> http://%s:%d", config.key, config.name, host, port)
    # No app-level bearer is the EXPECTED state, not a problem: the public route is gated by
    # mcp-auth-proxy (GitHub OAuth) at the edge, and the LAN address is deliberately open, same
    # trust model as everything else on this network. A permanent scary warning during normal
    # operation only teaches you to stop reading the logs.
    log.info(
        "MCP at http://%s:%d/mcp  (%s)", host, port,
        "app-level bearer configured from MCP_AUTH_TOKEN" if token
        else "no app-level bearer; auth is expected at the proxy (LAN access is open)",
    )
    uvicorn.run(app, host=host, port=port, log_level="warning")
