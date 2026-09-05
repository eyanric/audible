"""Serialise the cockpit into the JSON the page renders.

Kept apart from the FastAPI wiring so the exact payload can be asserted in tests without
standing up a server. Shapes here are the contract the browser codes against; changing a key
is a breaking change to the UI.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from ..draft.live import Candidate, LiveView, my_slot_on_clock
from ..draft.service import CockpitService
from ..draft.usage import UsageTable

log = logging.getLogger(__name__)

GRAB_NOW_LIMIT = 5
# The page shows ~25 rows; the rest feed name search and the position tabs.
BEST_AVAILABLE_LIMIT = 60
# ...but a global top-60 by VORP holds 2 LBs and zero Ks in League A, so a position tab built
# from it would report that 2 linebackers exist when 1,136 do. Every rosterable position also
# contributes its own depth, so filtering never sees a pre-truncated pool.
PER_POSITION_DEPTH = 30
RECENT_PICKS_LIMIT = 12
RUN_WINDOW = 10


def _player(cand: Candidate, *, gaps: dict[str, int] | None = None,
            byes: dict[str, int] | None = None,
            usage: UsageTable | None = None) -> dict[str, Any]:
    """One board row, serialized. Every annotation arrives here and nowhere earlier.

    KEYWORD-ONLY DELIBERATELY. Two branches each widened this signature with a different
    second parameter, and merging them bound a `UsageTable` into `gaps` at three MCP call
    sites -- silently, because the result is a dict of Nones rather than a crash. Every
    usage field on the MCP surface read as "not measured" and the board still looked fine.
    Names cannot collide the way positions can.
    """
    e = cand.entry
    gap = (gaps or {}).get(e.player_id)
    espn_rank = _rank_cache.get(e.player_id)
    # Usage is looked up here, at the SERVING boundary -- after the board is built, ranked and
    # frozen. That is what makes it display-only by construction rather than by promise. The
    # gap and bye annotations above follow the same rule and arrive the same way.
    ctx = usage.get(e.player_id) if usage else None
    pct = lambda v: round(v * 100, 1) if v is not None else None  # noqa: E731
    return {
        # Part 3, additive: how far our order departs from the one the room drafts off.
        # None means "not comparable", which the page renders as blank rather than as 0.
        "vs_espn": gap,
        # Where ESPN ranks him, so the page can tell a gap it can trust from one it cannot.
        "espn_rank": espn_rank,
        "vs_espn_confident": (
            espn_rank is not None and gap is not None and espn_rank >= GAP_CONFIDENT_FROM
        ),
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
        # The NUMBER, not just whether we have one. `survives_by` is `adp - next_pick`
        # shown as a subtraction, so the left-hand side has to reach the surface.
        "adp": e.adp,
        "adp_rank": e.adp_rank,
        "value": e.value,
        "points": round(e.points, 1),
        "grab_now": cand.grab_now,
        "fills_need": cand.fills_need,
        "deviation": e.deviation,
        # Display only, joined by TEAM at assembly time -- never carried on the player model,
        # so no value-engine input can reach it. None means "we could not derive one",
        # which the page renders blank rather than as a week.
        "bye": (byes or {}).get(e.team or ""),
        "flags": list(e.flags),
        # -- displayed usage context; None means UNKNOWN, never zero ----------------------
        # Prior-season observed volume. DDAFFL pays 0.5/reception to WR/TE, so target and
        # route volume is where this league's edge lives and consensus prices yards and TDs.
        "target_share": pct(ctx.target_share) if ctx else None,
        "air_yards_share": pct(ctx.air_yards_share) if ctx else None,
        # A PROXY: pass-snap share, not charted routes. A blocking TE still counts.
        "route_participation": pct(ctx.route_participation) if ctx else None,
        "snap_share": pct(ctx.snap_share) if ctx else None,
        "depth_slot": ctx.depth_slot if ctx else None,
        # Bye joins on team, so a D/ST gets one even though it has no player row anywhere.
        # Same fact as "bye" above, under the name the MCP surface publishes. It reads
        # the usage table rather than `byes` directly so the QA harness stays
        # deterministic against a PINNED table -- and there is still only one
        # derivation, because `load_usage` is handed `bye_weeks()` and no longer
        # computes its own.
        "bye_week": usage.bye(e.team) if usage else None,
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


def _teams(service: CockpitService) -> list[dict[str, Any]]:
    """Every team's picks so far, by draft slot.

    Exists because "no other teams ever appear" was a reported symptom: with every pick
    attributed to slot 0 there was only ever one team. Now that attribution is right, the
    payload has to show it, or the fix is invisible.
    """
    board = service.board
    by_id = {e.player_id: e for e in board.entries} if board else {}
    mine = service.session.slot
    rosters: dict[int, list[dict[str, Any]]] = {
        slot: [] for slot in range(1, service.config.num_teams + 1)
    }
    for p in service.session.effective_picks():
        if p.draft_slot in rosters:
            entry = by_id.get(p.player_id)
            rosters[p.draft_slot].append({
                "pick_no": p.pick_no,
                "name": entry.name if entry else p.player_id,
                "position": entry.position if entry else "?",
                "source": p.source,
            })
    return [
        {"slot": slot, "is_me": (mine is not None and slot == mine), "picks": picks}
        for slot, picks in sorted(rosters.items())
    ]


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
    # effective_picks, not session.picks: a hand-entered pick must appear in the feed and
    # in the run window exactly like a synced one, or the two are distinguishable downstream.
    picks = service.session.effective_picks()[-RECENT_PICKS_LIMIT:]
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
    for p in service.session.effective_picks()[-RUN_WINDOW:]:
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


# Part 3: how our order differs from the one the room is drafting off.
#
# WITHIN POSITION, and only over the DRAFTABLE population. Both restrictions are load-bearing
# and were measured, not assumed. Across positions the comparison is dominated by structure --
# kickers came out at +832 and quarterbacks at -690, which is VORP-vs-market shape, not the
# reception seam, and `rank-check` explicitly says not to draft off those. Over the whole 1007
# shared players the extremes are the junk tail, where both orderings are noise: the top ten
# were receivers projected zero catches. Restricted this way the extremes are real draftable
# players in a +-20 band, and the RB direction matches the prediction (Spearman -0.40 against
# receptions: pass-catching backs move DOWN because this league pays them 0.0 a catch).
_GAP_POPULATION = 200
_gap_cache: dict[str, int] | None = None
_rank_cache: dict[str, int] = {}

# nflverse spells the Rams `LA`; Sleeper and the board spell them `LAR`. Measured across all
# 32 teams on 2026-09-01, that is the ONLY disagreement between the two vocabularies.
_SCHEDULE_TEAM_ALIASES = {"LA": "LAR"}

# Byes have not fallen outside weeks 4-14 in the modern schedule. This is a plausibility
# bound for the self-check, not a claim about any particular season: its job is to catch a
# derivation that has gone wrong, not to encode the league's calendar.
BYE_WINDOW = range(4, 15)

_bye_cache: dict[str, int] | None = None


def bye_consistency(season: int) -> dict[str, Any]:
    """Derive byes and check the derivation against what must be true of any NFL season.

    A CONSISTENCY check, not a coverage one -- and the difference is the whole reason to
    trust it. Coverage asks "how full is this field", which a uniformly meaningless field
    passes. These four have a known-correct answer that the data cannot fake:

      B1  exactly 32 teams appear
      B2  each team has exactly one bye
      B3  every bye falls inside the plausible window
      B4  games in a week == (32 - teams on bye that week) / 2

    B4 is the load-bearing one. It ties the derivation back to the row count it came from,
    so a team silently missing from a week fails it arithmetically rather than plausibly.
    """
    from ..adapters.nflverse import schedules_frame

    frame = schedules_frame([season])
    rows = [r for r in frame.iter_rows(named=True) if r.get("game_type") == "REG"]
    weeks = sorted({r["week"] for r in rows})
    playing: dict[int, set[str]] = {w: set() for w in weeks}
    games: dict[int, int] = dict.fromkeys(weeks, 0)
    for r in rows:
        playing[r["week"]].update((r["home_team"], r["away_team"]))
        games[r["week"]] += 1

    teams = sorted({t for wk in playing.values() for t in wk})
    byes = {t: [w for w in weeks if t not in playing[w]] for t in teams}

    b1 = len(teams) == 32
    multi = {t: v for t, v in byes.items() if len(v) != 1}
    b2 = not multi
    settled = {t: v[0] for t, v in byes.items() if len(v) == 1}
    outside = {t: w for t, w in settled.items() if w not in BYE_WINDOW}
    b3 = not outside
    # Every team that plays in a week is in exactly one game, so games == playing / 2.
    mismatched = {
        w: {"games": games[w], "expected": len(playing[w]) // 2}
        for w in weeks if games[w] != len(playing[w]) // 2
    }
    b4 = not mismatched

    return {
        "season": season, "teams": len(teams), "weeks": weeks,
        "byes": {_SCHEDULE_TEAM_ALIASES.get(t, t): w for t, w in settled.items()},
        "per_week": {w: len(teams) - len(playing[w]) for w in weeks},
        "games_per_week": games,
        "b1": b1, "b2": b2, "b3": b3, "b4": b4,
        "ok": b1 and b2 and b3 and b4,
        "multi_bye": multi, "outside_window": outside, "week_mismatch": mismatched,
    }


def bye_weeks(season: int) -> dict[str, int]:
    """``board team code -> bye week``, or {} if the derivation cannot be trusted.

    Computed once per process and cached. On ANY failure -- import error, network, or a
    failed consistency check -- this returns {} and the column simply does not appear.
    A wrong bye is worse than no bye: it is the kind of error someone plans a whole roster
    around. Same contract as `_espn_gaps` directly above.
    """
    global _bye_cache
    if _bye_cache is not None:
        return _bye_cache
    resolved: dict[str, int] = {}
    try:
        report = bye_consistency(season)
    except Exception as exc:  # noqa: BLE001 -- the board must build without a schedule
        log.warning("bye weeks unavailable (%s); the column will not appear", exc)
    else:
        if report["ok"]:
            resolved = dict(report["byes"])
        else:
            log.warning(
                "bye derivation failed its own consistency check "
                "(B1=%s B2=%s B3=%s B4=%s); refusing to serve byes",
                report["b1"], report["b2"], report["b3"], report["b4"],
            )
    _bye_cache = resolved
    return resolved
# Measured by scripts/gap-confidence.py: Spearman(receptions, gap) within position, banded on
# ESPN rank. WR 61-120 = +0.50 and RB 121-200 = -0.40 both clear |0.30|; nothing in 1-60 does
# (WR +0.24, RB -0.25). So from 61 on the gap is carrying the scoring seam, and above it the
# two boards mostly agree anyway -- the top-of-board gaps measure 0 and +-1.
GAP_CONFIDENT_FROM = 61


def _espn_gaps(service: CockpitService) -> dict[str, int]:
    """``board id -> (ESPN position rank - our position rank)``. Positive = we like him more.

    Computed once per process and cached; on any failure this returns {} and the column
    simply does not appear, because a board with no gap column is much better than a board
    with a wrong one.
    """
    global _gap_cache
    if _gap_cache is not None:
        return _gap_cache
    _gap_cache = {}
    board = service.board
    if board is None or service.config.platform.value != "espn":
        return _gap_cache
    try:
        from ..adapters.espn import EspnAdapter, _draft_rank
        from ..adapters.sleeper import SleeperAdapter
        from ..draft.espn_ids import build_supplement

        with SleeperAdapter() as sleeper:
            catalog = sleeper.get_players_catalog()
        with EspnAdapter() as espn:
            pool = espn.get_player_pool(service.config)
        by_espn = {
            str(entry["espn_id"]): str(pid)
            for pid, entry in catalog.items()
            if isinstance(entry, dict) and entry.get("espn_id")
        }
        for espn_id, board_id in build_supplement(pool, catalog).items():
            by_espn.setdefault(espn_id, board_id)
        ranks: dict[str, float] = {}
        for row in pool:
            player = row.get("player") or row
            rank = _draft_rank(player)
            board_id = by_espn.get(str(player.get("id")))
            if rank is not None and board_id:
                ranks[board_id] = rank
        shared = [
            e for e in board.entries
            if e.player_id in ranks
            and e.vorp_rank <= _GAP_POPULATION
            and ranks[e.player_id] <= _GAP_POPULATION
        ]
        for position in {e.position for e in shared}:
            group = [e for e in shared if e.position == position]
            if len(group) < 3:
                continue
            theirs = {e.player_id: i for i, e in enumerate(
                sorted(group, key=lambda e: ranks[e.player_id]), start=1)}
            ours = {e.player_id: i for i, e in enumerate(
                sorted(group, key=lambda e: e.vorp_rank), start=1)}
            for e in group:
                _gap_cache[e.player_id] = theirs[e.player_id] - ours[e.player_id]
                _rank_cache[e.player_id] = int(ranks[e.player_id])
    except Exception as exc:  # noqa: BLE001 -- no column beats a wrong column
        log.warning("ESPN gap column unavailable (%s); it will not be shown", exc)
        _gap_cache = {}
    return _gap_cache


# Anything older than this is called out. A week-old projection set is still usable -- it
# is what the offline guarantee rests on -- but Eric should know before he trusts it.
STALE_AFTER_DAYS = 7.0


def _data_vintage() -> dict[str, Any]:
    """How old the board's inputs are. Read from the cache manifest; never fetches."""
    try:
        from ..adapters.nflverse import cache_summary  # same source /healthz reports

        summary = cache_summary()
        oldest = summary.get("oldest_age_s")
        days = round(oldest / 86400.0, 1) if oldest is not None else None
        return {
            "sources": summary.get("keys") or 0,
            "oldest_age_s": oldest,
            "oldest_days": days,
            "stale": (days is not None and days > STALE_AFTER_DAYS),
        }
    except Exception as exc:  # noqa: BLE001 -- a readout must never take the board down
        log.warning("data vintage unavailable (%s)", exc)
        return {"sources": 0, "oldest_age_s": None, "oldest_days": None, "stale": False}


def _bye_collisions(service: CockpitService, byes: dict[str, int]) -> list[dict[str, Any]]:
    """Rostered players at the SAME primary position sharing a bye week.

    States the fact and stops. No severity, no ranking, no recommendation -- whether two
    RBs on the same bye is a problem depends on the rest of the roster, the waiver wire and
    how the season has gone, none of which this knows. Deliberately blind to lineup slots
    and starter counts: that is weekly-mode scope, and reaching for it here would be
    inventing a judgment out of a coincidence of dates.
    """
    board = service.board
    if not byes or board is None:
        return []
    by_id = {e.player_id: e for e in board.entries}
    mine = service.session.slot
    if mine is None:
        return []
    grouped: dict[tuple[int, str], list[str]] = {}
    for pick in service.session.effective_picks():
        if pick.draft_slot != mine:
            continue
        entry = by_id.get(pick.player_id)
        if entry is None or not entry.team:
            continue
        week = byes.get(entry.team)
        if week is None:
            continue
        grouped.setdefault((week, entry.position), []).append(entry.name)
    return [
        {"week": week, "position": position, "players": sorted(names)}
        for (week, position), names in sorted(grouped.items())
        if len(names) > 1
    ]


def _undo(service: CockpitService) -> dict[str, Any]:
    """Whether an undoable pick exists, from SERVER truth rather than the browser's stack.

    `takenStack` lives in one page session, so a reload greyed Undo out while the manual
    picks were still sitting on the server and `undo_taken` would still have worked. Over
    three hours and a hundred-odd marks a reload is likely, and a mis-mark right after one
    left no way back through the UI.

    Only MANUAL picks are undoable, and that is a property of `undo_taken` rather than a
    convention observed here: it reads `session.manual_picks`, rejects any id not in that
    list, and the only assignment it makes is back to `session.manual_picks`. It never
    references `session.picks`, so a synced pick cannot be removed by it.
    """
    manual = service.session.manual_picks
    if not manual:
        return {"available": False, "player_id": None, "name": None}
    last = manual[-1]
    board = service.board
    entry = ({e.player_id: e for e in board.entries}.get(last.player_id)) if board else None
    return {
        "available": True,
        "player_id": last.player_id,
        "name": entry.name if entry else last.player_id,
    }


def _next_mark(service: CockpitService) -> dict[str, Any]:
    """The pick number and seat that the NEXT `mark_taken` would be attributed to.

    Mirrors `CockpitService._renumber_manual`: manual picks are numbered contiguously from
    the last synced pick, so the next one is `base + len(manual) + 1`. A slot of None means
    the draft is full and there is no pick left to record -- `mark_taken` returns False.
    """
    session = service.session
    base = max((p.pick_no for p in session.picks), default=0)
    pick_no = base + len(session.manual_picks) + 1
    slot = my_slot_on_clock(pick_no, service.config.num_teams, session.rounds)
    return {
        "pick_no": pick_no if slot is not None else None,
        "slot": slot,
        "is_mine": slot is not None and session.slot is not None and slot == session.slot,
    }


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
        # WHERE THE NEXT MARK WILL ACTUALLY LAND. Additive; nothing else in the payload moves.
        #
        # `mark_taken` appends a manual pick and `_renumber_manual` numbers it as the pick
        # right after the last synced one, attributing it with the same snake math to
        # whichever seat is genuinely on the clock. So a mark made on my turn ALREADY is my
        # pick, recorded correctly -- the machinery was never wrong, the page just never said
        # so, because it asked `draft.started` instead. League B sits in `pre_draft` for the
        # whole of a hand-mirrored round, so that gate is false exactly when the distinction
        # matters most. This asks the honest question instead: whose pick is the next one I
        # record? Recomputed from the same inputs `_renumber_manual` uses rather than read
        # off the ESPN clock, so it is true while mirroring by hand and under live sync.
        "next_mark": _next_mark(service),
        # Part 3, additive and DISPLAY ONLY. `cache_summary` reads the manifest off disk --
        # file metadata, no fetch. Nothing here may trigger a refetch: a surprise network
        # call mid-draft is the exact failure this readout exists to warn about.
        "data": _data_vintage(),
        # Additive: the Undo control reads its enabled state from here, not from the
        # browser's own stack, so it survives a reload.
        "undo": _undo(service),
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
        # How many picks I have left, and how many of them are already spoken for by an
        # unfilled starting slot. `recommend` needs the difference: with rounds to spare you
        # take the best player, and only once every remaining pick is committed does a
        # starting slot become an actual constraint. Without it, need is a hard filter and a
        # D/ST outranks a WR 46 places better because the WR fills nothing.
        "my_picks_remaining": view.my_picks_remaining,
        "slack_picks": (
            None if view.my_picks_remaining is None
            else view.my_picks_remaining - len(view.unfilled)
        ),
        "complete": view.on_the_clock is None,
    }
    base["roster"] = {
        "slots": _roster_slots(view),
        "unfilled": list(view.unfilled),
        "starters_complete": view.starters_complete,
    }
    gaps = _espn_gaps(service)
    byes = bye_weeks(service.config.season)
    usage = getattr(service, "usage", None)
    base["grab_now"] = [_player(c, gaps=gaps, byes=byes, usage=usage) for c in grab]
    base["best_available"] = [
        _player(c, gaps=gaps, byes=byes, usage=usage)
        for c in _served_pool(service, view)
    ]
    base["bye_collisions"] = _bye_collisions(service, byes)
    base["usage_degraded"] = list(usage.missing_sources) if usage else []
    base["teams"] = _teams(service)
    base["recent_picks"] = _recent_picks(service)
    base["runs"] = _runs(service, view)
    base["cliffs"] = _cliffs(view)
    base["counts_last10"] = _counts_last10(service)
    return base
