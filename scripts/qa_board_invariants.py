"""Phase 2: the checks that guard PICKS, not pixels.

The browser half of QA can only see that a control responds. These assert that what the
control is showing is a sane board: that a kicker never outranks a startable running back,
that the four MCP tools are four views of ONE board rather than four boards, and that a
draft driven end-to-end by `recommend` still fills a legal lineup.

They run against the PINNED board (scripts/fixtures/qa-board-<league>.json), in-process,
with an isolated state dir -- deterministic input, no network, and no contact with the real
draft session. tests/test_draft_completes.py asserts the same lineup property against a
synthetic board shaped by hand; this asserts it against the board we would actually draft
from, where the supply is lumpy and 3302 deep.

NOTE ON SCOPE. A failure here is NOT loop-fixable. The board comes from the value engine,
which is read-only for this work -- a UI check must never be resolvable by changing what
the board recommends. A red invariant is a STOP and a report, not a fix.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from qa_board_fixture import load_board

TEAMS = 8
ROUNDS = 16
MY_SLOT = 8

# The line the spec draws for a specialist. Below it, a D/ST pick is spending a startable
# skill pick on a position whose spread is a couple of points a week.
DST_EARLIEST_ROUND = 13

# "the ~24th RB or WR" -- three startable rounds' worth in an 8-team league.
STARTABLE_DEPTH = 24


def _call(service: Any, tool: str, **kwargs: Any) -> dict[str, Any]:
    """Invoke one MCP tool the way a client would, so the check exercises the real surface."""
    from fastmcp import Client

    from audible.server.mcp import build_mcp

    async def go() -> dict[str, Any]:
        async with Client(build_mcp(service)) as client:
            result = await client.call_tool(tool, kwargs)
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            return data
        return json.loads(result.content[0].text)

    return asyncio.run(go())


def _snake_slot(pick_no: int) -> int:
    rnd, idx = divmod(pick_no - 1, TEAMS)
    return idx + 1 if rnd % 2 == 0 else TEAMS - idx


def _service(config: Any, board: Any, state_dir: Path, my_slot: int) -> Any:
    from audible.draft.service import CockpitService

    svc = CockpitService(config, state_dir=state_dir, slot_override=my_slot)
    svc.board = board
    svc.session.draft_id = "qa-invariants"
    svc.session.draft_status = "drafting"
    svc.session.slot = my_slot
    svc.session.slot_source = "override"
    return svc


def _dry_run(config: Any, board: Any, state_dir: Path, my_slot: int) -> dict[str, Any]:
    """All 128 picks. My seat takes `recommend`'s top row; the room drafts by ADP."""
    from audible.draft.live import Pick

    svc = _service(config, board, state_dir, my_slot)
    entries = sorted(board.entries, key=lambda e: e.vorp_rank)
    priced = sorted((e for e in entries if e.adp is not None), key=lambda e: e.adp or 0.0)
    room_order = priced + [e for e in entries if e.adp is None]

    taken: set[str] = set()
    picks: list[Pick] = []
    mine: list[dict[str, Any]] = []
    for pick_no in range(1, TEAMS * ROUNDS + 1):
        slot = _snake_slot(pick_no)
        rnd = (pick_no - 1) // TEAMS + 1
        if slot == my_slot:
            rec = _call(svc, "recommend", limit=5)
            rows = rec.get("recommendations") or []
            if not rows:
                return {"error": f"recommend returned nothing at pick {pick_no} (round {rnd})",
                        "mine": mine}
            pid = rows[0]["id"]
            mine.append({"round": rnd, "pick_no": pick_no,
                         "position": rows[0]["position"], "name": rows[0]["name"]})
        else:
            pid = next(e.player_id for e in room_order if e.player_id not in taken)
        taken.add(pid)
        picks.append(Pick(pick_no=pick_no, round=rnd, draft_slot=slot, player_id=pid))
        svc.session.picks = list(picks)
        svc._invalidate()

    return {"status": _call(svc, "draft_status"), "roster": _call(svc, "my_roster"),
            "mine": mine, "error": None}


def run(check: Any, league: str, state_dir: Path) -> None:
    """Add every board invariant to the caller's results list."""
    from audible.config.loader import load_all_leagues

    board = load_board(league)
    config = load_all_leagues()[league]
    entries = board.entries

    # -- A. the rank column is a real ranking -------------------------------------------
    # A collision here is the shape an off-by-one takes, and every check that reads "the
    # Nth RB" is meaningless underneath it, so this is asserted before anything uses a rank.
    ranks = sorted(e.vorp_rank for e in entries)
    clean = ranks == list(range(1, len(entries) + 1))
    dupes = sorted({r for r in ranks if ranks.count(r) > 1}) if not clean else []
    check("board vorp ranks are a clean 1..N sequence", clean,
          f"n={len(entries)}" if clean else f"duplicated/missing ranks: {dupes[:6]}")

    # -- B. a specialist never outranks a startable skill player -------------------------
    by_pos: dict[str, list[Any]] = {}
    for e in entries:
        by_pos.setdefault(e.position, []).append(e)
    for rows in by_pos.values():
        rows.sort(key=lambda e: -e.vorp)

    floors = {}
    for pos in ("RB", "WR"):
        rows = by_pos.get(pos, [])
        floors[pos] = rows[STARTABLE_DEPTH - 1].vorp if len(rows) >= STARTABLE_DEPTH else None
    floor = min(v for v in floors.values() if v is not None)

    for pos in ("DEF", "K"):
        rows = by_pos.get(pos, [])
        if not rows:
            check(f"{pos} vorp stays under the startable skill floor", False, "no such position")
            continue
        top = rows[0]
        check(f"{pos} vorp stays under the startable skill floor", top.vorp <= floor,
              f"best {pos} {top.name} vorp={top.vorp:.1f} vs floor={floor:.1f} "
              f"(RB{STARTABLE_DEPTH}={floors['RB']:.1f} WR{STARTABLE_DEPTH}={floors['WR']:.1f})")

    # -- C. four tools, one board --------------------------------------------------------
    svc = _service(config, board, state_dir / "agree", MY_SLOT)
    best = _call(svc, "best_available", limit=25)
    rows = best.get("players") or []
    check("best_available returns a populated board", len(rows) >= 10, f"returned={len(rows)}")

    if rows:
        probe = rows[:3]
        names = [p["name"] for p in probe]

        lookups = {n: _call(svc, "player_lookup", name=n) for n in names}
        mismatched = []
        for p in probe:
            hit = (lookups[p["name"]].get("matches") or [None])[0]
            if hit is None or any(hit.get(k) != p.get(k)
                                  for k in ("id", "vorp_rank", "consensus_rank", "position")):
                mismatched.append(p["name"])
        check("player_lookup agrees with best_available", not mismatched,
              f"probed={names} mismatched={mismatched}")

        cmp_out = _call(svc, "compare", names=names)
        cmp_by_id = {p["id"]: p for p in (cmp_out.get("players") or [])}
        bad = [p["name"] for p in probe
               if p["id"] not in cmp_by_id
               or cmp_by_id[p["id"]]["vorp_rank"] != p["vorp_rank"]]
        check("compare agrees with best_available", not bad,
              f"not_available={cmp_out.get('not_available')} mismatched={bad}")

        rec = _call(svc, "recommend", limit=5)
        rec_rows = rec.get("recommendations") or []
        off_board = []
        for r in rec_rows:
            hit = (_call(svc, "player_lookup", name=r["name"]).get("matches") or [None])[0]
            if hit is None or hit["vorp_rank"] != r["vorp_rank"]:
                off_board.append(r["name"])
        check("recommend agrees with the same board", rec_rows and not off_board,
              f"recommended={[r['name'] for r in rec_rows]} disagreeing={off_board}")

    # -- D. a full draft from seat 8 still fills a legal lineup ---------------------------
    out = _dry_run(config, board, state_dir / "dryrun", MY_SLOT)
    if out.get("error"):
        check("slot-8 dry run fills every starting slot", False, out["error"])
        check(f"no D/ST before round {DST_EARLIEST_ROUND}", False, "dry run did not complete")
        return

    unfilled = out["status"]["unfilled_starting_slots"]
    check("slot-8 dry run fills every starting slot", unfilled == [],
          f"unfilled={unfilled}" if unfilled else
          f"{len(out['mine'])} picks, starters_complete={out['roster']['starters_complete']}")

    short = [s["slot"] for s in out["roster"]["slots"] if s["filled"] < s["total"]]
    check("slot-8 roster has no short slot", not short, f"short={short}")

    dst = next((p for p in out["mine"] if p["position"] == "DEF"), None)
    check(f"no D/ST before round {DST_EARLIEST_ROUND}",
          dst is not None and dst["round"] >= DST_EARLIEST_ROUND,
          "never drafted a D/ST" if dst is None
          else f"first D/ST {dst['name']} in round {dst['round']} (pick {dst['pick_no']})")
