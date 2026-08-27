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


def run_usage(check: Any, league: str, state_dir: Path) -> None:
    """Lane 1 invariants: usage is present, sane, and CANNOT have moved the board.

    The last one is the whole contract. Usage is looked up at the serving boundary, so the
    claim "nothing here enters the sort" is structural -- but a claim that is only structural
    is one refactor away from being false, so it is asserted against the board itself.
    """
    from qa_board_fixture import load_usage_table

    board = load_board(league)
    usage = load_usage_table(league)
    top = sorted(board.entries, key=lambda e: e.vorp_rank)[:128]

    check("pinned usage table is not degraded", not usage.missing_sources,
          f"missing={list(usage.missing_sources)}")

    # -- the sort is untouched -------------------------------------------------------------
    # Walk the board in rank order and assert vorp never RISES. Stated this way rather than by
    # rebuilding the ranking, because rebuilding would have to guess the tiebreak between two
    # equal-vorp players and would fail on the guess rather than on a real defect. If usage had
    # ever leaked into the sort, a player would sit above someone worth more and this catches it.
    ordered = sorted(board.entries, key=lambda e: e.vorp_rank)
    drift = [f"#{a.vorp_rank} {a.name} ({a.vorp:.1f}) above #{b.vorp_rank} {b.name} ({b.vorp:.1f})"
             for a, b in zip(ordered, ordered[1:], strict=False) if a.vorp < b.vorp]
    check("usage did not enter the sort", not drift,
          f"out of value order: {drift[:3]}" if drift
          else f"{len(ordered)} entries, vorp non-increasing across every rank")

    # -- coverage over the draftable window --------------------------------------------------
    # Not 100%: a rookie has no prior-season usage and a D/ST has no player row at all. The
    # floor is what makes a silent join failure (a changed id column, a renamed team) fail
    # here rather than showing up as an empty column on a Sunday.
    have_tgt = sum(1 for e in top if (c := usage.get(e.player_id)) and c.target_share is not None)
    have_rte = sum(1 for e in top
                   if (c := usage.get(e.player_id)) and c.route_participation is not None)
    check("target share covers the draftable window", have_tgt >= 100,
          f"{have_tgt}/128 of the top 128 have a target share")
    check("route participation covers the draftable window", have_rte >= 95,
          f"{have_rte}/128 of the top 128 have a route-participation proxy")

    # -- every team resolves a bye ------------------------------------------------------------
    # nflverse spells the Rams "LA" and the board spells them "LAR". That cost one team a
    # silently blank bye, and a defensive alias map then cost Washington its own. Assert the
    # join instead of trusting the map.
    unresolved = sorted({e.team for e in board.entries if e.team and usage.bye(e.team) is None})
    check("every board team resolves to a bye week", not unresolved, f"unresolved={unresolved}")

    byes = list(usage.bye_by_team.values())
    check("bye weeks are inside the regular season",
          bool(byes) and all(1 <= b <= 18 for b in byes),
          f"{len(byes)} teams, range {min(byes)}-{max(byes)}" if byes else "no byes")

    # -- shares are shares ---------------------------------------------------------------------
    # Air-yards share is deliberately excluded from the lower bound: a back whose targets are
    # all behind the line has NEGATIVE air yards, so a negative share is real, not corrupt.
    bad = []
    for e in top:
        c = usage.get(e.player_id)
        if not c:
            continue
        for name in ("target_share", "route_participation", "snap_share"):
            v = getattr(c, name)
            if v is not None and not (0.0 <= v <= 1.0):
                bad.append(f"{e.name}.{name}={v}")
    check("usage shares are fractions in 0..1", not bad, f"out of range: {bad[:4]}")

    # -- the MCP surface carries it too --------------------------------------------------------
    # The cockpit and the chat surface have to answer the same question the same way; a field
    # that reaches the board table but not `_slim` is a split brain by another name.
    from audible.config.loader import load_all_leagues

    svc = _service(load_all_leagues()[league], board, state_dir / "usage", MY_SLOT)
    svc.usage = usage
    rows = (_call(svc, "best_available", limit=10).get("players") or [])
    keys = ("target_share_pct", "route_participation_pct", "snap_share_pct",
            "air_yards_share_pct", "depth_slot", "bye_week")
    absent = [k for k in keys if rows and k not in rows[0]]
    populated = [k for k in keys
                 if any(r.get(k) is not None for r in rows)]
    check("_slim carries every usage field", bool(rows) and not absent,
          f"missing keys={absent}" if absent else f"all {len(keys)} present on {len(rows)} rows")
    check("_slim usage fields are populated, not just present",
          len(populated) == len(keys),
          f"never populated: {sorted(set(keys) - set(populated))}")


def run_adp_calibration(check: Any, league: str) -> None:
    """The assumption that makes rank-based survival correct, asserted rather than assumed.

    `compute_view` never compares an ADP pick number to a pick counter. It sorts the AVAILABLE
    players by ADP and compares a player's INDEX in that queue against the number of rival
    picks before my next pick (live.py:192-201). That is league-size-invariant by construction:
    only the order is used.

    What makes it correct is that Sleeper's ADP is an average OVERALL PICK NUMBER, so the k-th
    player off the board has ADP ~= k in any league size. Measured 2026-08-26 on the pinned
    board: mean(adp - market_rank) = +0.33 over the top 200, max |diff| 0.90.

    If Sleeper ever changed that -- to a round.pick code, or to a per-league-size number -- the
    order would still look sane while every survival estimate quietly moved. This is the check
    that would notice, so nobody has to re-derive the 12-vs-8-team question a third time.
    """
    board = load_board(league)
    priced = sorted((e for e in board.entries if e.adp is not None), key=lambda e: e.adp)
    check("ADP is priced deep enough to rank the draftable window", len(priced) >= 200,
          f"{len(priced)} priced players")
    if len(priced) < 200:
        check("ADP value tracks market rank (a pick number, not a round code)", False,
              "too few priced players to measure")
        return

    diffs = [abs(e.adp - (i + 1)) for i, e in enumerate(priced[:200])]
    worst = max(diffs)
    check("ADP value tracks market rank (a pick number, not a round code)", worst <= 5.0,
          f"max |adp - market_rank| over the top 200 = {worst:.2f} "
          f"(mean {sum(diffs) / len(diffs):.2f})")


def run_waiver_invariants(check: Any, league: str) -> None:
    """The wire numbers the bye-hole answer rests on. Pinned board only, no network.

    These guard a CLAIM, not a ranking: that after 128 picks there is still a startable
    kicker and defence on the wire, and that there is not a startable RB. Both directions
    matter -- the first is why weeks 8 and 14 are cheap, the second is why 7 and 13 are not.
    """
    from waiver_baseline import STARTER_FLOOR, realistic_draft

    board = load_board(league)
    gone = realistic_draft(board)
    check("the realistic draft takes exactly 128", len(gone) == 128, f"took {len(gone)}")

    by_pos: dict[str, list[Any]] = {}
    for e in board.entries:
        by_pos.setdefault(e.position, []).append(e)
    for rows in by_pos.values():
        rows.sort(key=lambda e: -e.points)

    verdicts = {}
    for pos, floor_rk in STARTER_FLOOR.items():
        rows = by_pos.get(pos, [])
        if len(rows) < floor_rk:
            continue
        left = [e for e in rows if e.player_id not in gone]
        floor = rows[floor_rk - 1].points
        verdicts[pos] = bool(left) and left[0].points >= floor

    # Specialists are droppable in an 8-team league: nobody rosters a backup, so the wire
    # always holds a startable one. If this ever flips, streaming a bye is no longer free and
    # the draft-day advice about K and D/ST changes with it.
    check("a startable K is still on the wire after 128 picks", verdicts.get("K") is True,
          f"K startable on the wire: {verdicts.get('K')}")
    check("a startable D/ST is still on the wire after 128 picks", verdicts.get("DEF") is True,
          f"DEF startable on the wire: {verdicts.get('DEF')}")
    # The other half of the same claim: RB is the position the wire CANNOT cover, which is
    # why the two RB byes are the only ones that cost real points.
    check("no startable RB is left on the wire after 128 picks", verdicts.get("RB") is False,
          f"RB startable on the wire: {verdicts.get('RB')}")

    # The replacement baseline must be recoverable from the board, since every wire number is
    # quoted against it. vorp = points - baseline, so one position must yield one baseline.
    bad = [p for p, rows in by_pos.items()
           if len({round(e.points - e.vorp, 3) for e in rows}) != 1]
    check("one replacement baseline per position", not bad, f"inconsistent at {bad}")
