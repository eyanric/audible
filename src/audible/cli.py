"""audible CLI -- Phase 0 surface.

  audible configs                      validate + summarise every league config
  audible verify-scoring <key>         compare a Sleeper config vs the live league
  audible vorp <key> [--top N]         compute per-position replacement + VORP (the milestone)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .config import LeagueConfig, load_all_leagues
from .value import VorpEntry, compute_vorp

if TYPE_CHECKING:
    from .draft.board import DraftBoard
    from .draft.live import LiveView, Pick

# Display order for positions (offense, then specialists, then IDP).
_POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"]


def _order_positions(positions: frozenset[str]) -> list[str]:
    ranked = [p for p in _POS_ORDER if p in positions]
    return ranked + sorted(positions - set(ranked))


def _load(key: str) -> LeagueConfig:
    leagues = load_all_leagues()
    if key not in leagues:
        raise SystemExit(f"unknown league {key!r}. Known: {', '.join(sorted(leagues))}")
    return leagues[key]


def cmd_configs(_args: argparse.Namespace) -> int:
    leagues = load_all_leagues()
    print(f"Loaded and validated {len(leagues)} league config(s):\n")
    for cfg in leagues.values():
        slots = cfg.slot_counts()
        slot_str = " ".join(f"{n}x{name}" if n > 1 else name for name, n in slots.items())
        print(f"  [{cfg.key}] {cfg.name}  ({cfg.platform.value}, id={cfg.league_id})")
        print(f"     season={cfg.season}  teams={cfg.num_teams}  scoring_keys={len(cfg.scoring)}")
        print(f"     positions: {', '.join(_order_positions(cfg.positions))}")
        print(f"     starters ({len(cfg.starting_slots)}): {slot_str}")
        flags = []
        if cfg.median_match:
            flags.append("median-match")
        if cfg.expected_reception_points is not None:
            flags.append(f"expect REC={cfg.expected_reception_points}")
        if cfg.playoff_teams:
            flags.append(f"playoffs {cfg.playoff_teams}@wk{cfg.playoff_week_start}")
        if flags:
            print(f"     flags: {', '.join(flags)}")
        print()
    return 0


def _print_drift(cfg: LeagueConfig, drift: Sequence[tuple[str, float | None, float | None]],
                 faithful: str) -> None:
    if drift:
        print(f"[{cfg.key}] SCORING DRIFT -- {len(drift)} key(s) differ (config vs live):")
        for key, cfg_val, live_val in drift:
            print(f"   {key:<18} config={cfg_val!s:<8} live={live_val!s}")
    else:
        print(f"[{cfg.key}] config scoring is FAITHFUL to the live league ({faithful}).")


def _print_structure(cfg: LeagueConfig, structure: Sequence[tuple[str, int, int]]) -> None:
    if structure:
        print(f"\n[{cfg.key}] !! ROSTER DRIFT -- {len(structure)} slot(s) differ (config vs live).")
        print("   Replacement baselines are derived from this, so EVERY value number is wrong:")
        for slot, cfg_n, live_n in structure:
            print(f"   {slot:<12} config={cfg_n:<4} live={live_n}")
    else:
        print(f"\n[{cfg.key}] roster structure is FAITHFUL "
              f"({len(cfg.starting_slots)} starting slots match).")


def cmd_verify_scoring_espn(cfg: LeagueConfig) -> int:
    """ESPN's weights are position-scoped, so the comparison has to be too.

    ESPN encodes League B's receptions as base 0.0 with per-position overrides; our config
    encodes the same rule as base 0.5 with an RB override. Comparing the two base tables
    would report drift across the whole table where there is none -- so this reads
    ``pointsOverrides`` and compares one position at a time.
    """
    from .adapters.espn import SPECIALIST_GAP, STAT_ID_TO_KEY, TRANSLATED_POSITIONS, EspnAdapter

    with EspnAdapter() as espn:
        drift = espn.verify_scoring(cfg)
        live_rec = espn.live_reception_points(cfg)
        structure = espn.verify_structure(cfg)

    checked = len(STAT_ID_TO_KEY) * len(cfg.positions & TRANSLATED_POSITIONS)
    _print_drift(cfg, drift, f"{checked} position-scoped weights match")

    # The league's one standing question: League B is still standard until the commissioner
    # flips it, and until then every WR/TE number is priced for scoring nobody is playing.
    mismatch = False
    expected = cfg.expected_reception_points
    if expected is not None:
        rb_rec = cfg.scoring_for("RB").get("rec")
        if live_rec is None:
            mismatch = True
            print(f"\n[{cfg.key}] !! RECEPTIONS ARE UNSCORED LIVE -- config expects {expected}.")
        elif abs(live_rec - expected) > 1e-9:
            mismatch = True
            print(f"\n[{cfg.key}] !! PPR MISMATCH: config expects {expected}/reception, the live "
                  f"league pays {live_rec}. The half-PPR flip has NOT landed -- every WR/TE "
                  f"number on the board is priced for scoring this league is not using.")
        else:
            print(f"\n[{cfg.key}] receptions confirmed LIVE at {live_rec}/rec for WR/TE "
                  f"(RB stays {rb_rec} by design, not drift).")

    _print_structure(cfg, structure)
    print(f"\n[{cfg.key}] known gap -- {SPECIALIST_GAP}")
    return 1 if (drift or mismatch or structure) else 0


def cmd_verify_scoring(args: argparse.Namespace) -> int:
    from .adapters.sleeper import SleeperAdapter

    cfg = _load(args.league)
    if cfg.platform.value == "espn":
        return cmd_verify_scoring_espn(cfg)
    with SleeperAdapter() as sleeper:
        drift = sleeper.verify_scoring(cfg)
        structure = sleeper.verify_structure(cfg)

    _print_drift(cfg, drift, f"{len(cfg.scoring)} keys match")
    _print_structure(cfg, structure)
    return 1 if (drift or structure) else 0


def _print_top(entries: Sequence[VorpEntry], n: int) -> None:
    print(f"  {'#':>3}  {'player':<26} {'pos':<4} {'team':<4} {'proj':>7} {'vorp':>7}  start")
    for i, e in enumerate(entries[:n], 1):
        p = e.projection
        print(
            f"  {i:>3}  {p.name[:26]:<26} {p.primary_position:<4} {(p.team or '-'):<4} "
            f"{p.points:>7.1f} {e.vorp:>7.1f}  {'*' if e.is_starter else ''}"
        )


def _print_scoring_paths(provider: object) -> None:
    """Report how a vendor's universe was scored, when the adapter tracks it.

    Only the ESPN adapter has two paths (translated stat line vs the vendor's own
    projection), and a silent fallback is exactly the kind of thing that looks like data.
    """
    adapter = getattr(provider, "adapter", None)
    counts: dict[str, int] | None = getattr(adapter, "source_counts", None)
    if not counts:
        return
    ours = counts.get("stat_line", 0)
    print(f"  {getattr(adapter, 'pool_size', 0)} players served; {ours} scored by us from "
          f"translated stat lines.")
    print(f"  Vendor's own projection used for {counts.get('vendor_specialist', 0)} K/D-ST "
          f"(no translation exists) and {counts.get('vendor_untranslated', 0)} offensive "
          f"players (unprojected or return-only; all far below replacement).")


def cmd_vorp(args: argparse.Namespace) -> int:
    from .providers import build_consensus_provider

    cfg = _load(args.league)

    print(f"Pulling consensus projections for [{cfg.key}] {cfg.name} (season {cfg.season})...")
    with build_consensus_provider(cfg) as provider:
        players = provider.projections(cfg)
        _print_scoring_paths(provider)
    entries, levels = compute_vorp(players, cfg)
    starters = sum(1 for e in entries if e.is_starter)

    print(f"\nScored {len(players)} players. Starting demand = "
          f"{cfg.num_teams} x {len(cfg.starting_slots)} = "
          f"{cfg.num_teams * len(cfg.starting_slots)} slots ({starters} filled).\n")

    print("Replacement level per position (config-derived):")
    print(f"  {'pos':<5} {'starters':>9} {'repl_rank':>10} {'repl_pts':>9}")
    for pos in _order_positions(cfg.positions):
        lvl = levels[pos]
        print(f"  {pos:<5} {lvl.starters_used:>9} {lvl.replacement_rank:>10} {lvl.points:>9.1f}")

    print(f"\nTop {args.top} by VORP (overall):")
    _print_top(entries, args.top)

    per_pos = args.per_pos
    print(f"\nTop {per_pos} by VORP per position:")
    for pos in _order_positions(cfg.positions):
        at_pos = [e for e in entries if e.projection.primary_position == pos]
        print(f"\n {pos}:")
        _print_top(at_pos, per_pos)
    return 0


def _simulate_picks(board: DraftBoard, cfg: LeagueConfig, n: int) -> list[Pick]:
    from .draft.live import Pick, my_slot_on_clock

    teams = cfg.num_teams
    by_adp = sorted((e for e in board.entries if e.adp is not None), key=lambda e: e.adp or 0.0)
    picks: list[Pick] = []
    for pick_no in range(1, min(n, len(by_adp)) + 1):
        e = by_adp[pick_no - 1]
        rnd = (pick_no - 1) // teams + 1
        slot = my_slot_on_clock(pick_no, teams)
        assert slot is not None  # unbounded call: only pick_no < 1 yields None
        picks.append(Pick(pick_no, rnd, slot, e.player_id))
    return picks


def _render_live(v: LiveView, slot: int) -> None:
    print("\n" + "=" * 66)
    if v.on_the_clock is None:
        print(f"PICK #{v.current_pick}  -- DRAFT COMPLETE")
    else:
        print(f"PICK #{v.current_pick}  (slot {v.on_the_clock} on the clock)")
    if v.picks_until_me == 0:
        horizon = (f", then #{v.survival_horizon} "
                   f"({v.opponent_picks_until_horizon} rival picks later)"
                   if v.survival_horizon is not None else " -- your last pick")
        print(f"YOU (slot {slot}): >>> ON THE CLOCK <<<{horizon}")
    elif v.my_next_pick is not None:
        print(f"YOU (slot {slot}): next pick #{v.my_next_pick}  ({v.picks_until_me} away)")
    print(f"Your roster ({len(v.my_roster)}): {', '.join(v.my_roster) or '(none)'}")
    print(f"Unfilled starters: {', '.join(v.unfilled) or 'ALL FILLED'}")
    if v.runs or v.cliffs:
        print("\nALERTS:")
        for r in v.runs:
            print(f"  ! {r}")
        for c in v.cliffs:
            print(f"  ~ {c}")
    header = ("best available (all starters filled -- depth/upside)"
              if v.starters_complete else "best available that fills a need")
    print(f"\nON YOUR CLOCK -- {header}:")
    for cand in v.recommendations:
        e = cand.entry
        val = f"{e.value:+d}" if e.value is not None else "-"
        print(f"  {'GRAB' if cand.grab_now else 'wait':<4} {e.name[:22]:<22} {e.position:<3} "
              f"val {val:>4}  {' '.join(e.flags)}")
    print("\nBEST AVAILABLE (by league value):")
    for cand in v.best_available:
        e = cand.entry
        val = f"{e.value:+d}" if e.value is not None else "-"
        mark = "GRAB" if cand.grab_now else "    "
        need = "*" if cand.fills_need else " "
        print(f"  {mark} {need}{e.name[:22]:<22} {e.position:<3} proj {e.points:>5.0f}  "
              f"val {val:>4}  {' '.join(e.flags)}")


def cmd_live(args: argparse.Namespace) -> int:
    import time

    from .adapters.sleeper import SleeperAdapter
    from .draft import build_board
    from .draft.live import compute_view, parse_picks

    cfg = _load(args.league)
    # Refuse BEFORE building. This guard used to sit after the board build, so reaching for
    # `live` on an ESPN league printed "Building board...", spent minutes on it, and only
    # then said no -- which is the worst possible behaviour at 8:40 on draft night, when
    # this command is only ever reached for because something else already went wrong.
    if not args.simulate and cfg.platform.value != "sleeper":
        raise SystemExit(
            "`live` polls Sleeper directly and is Sleeper-only. League B's live sync runs "
            "in the cockpit: `audible serve --league espn_davis_drive`."
        )

    print(f"Building board for [{cfg.key}] {cfg.name} (value={cfg.value_metric})...")
    board = build_board(cfg)
    rounds = args.rounds

    adapter: SleeperAdapter | None = None
    draft_id = args.draft_id
    if not args.simulate:
        adapter = SleeperAdapter()
        draft_id = draft_id or str(adapter.get_league(cfg.league_id).get("draft_id"))
        settings = adapter.get_draft(draft_id).get("settings", {})
        rounds = int(settings.get("rounds", rounds))

        # Reconcile against the live draft room before showing a single number. A config that
        # disagrees with the room silently ruins the whole session.
        for slot, cfg_n, live_n in adapter.verify_structure(cfg):
            print(f"  !! ROSTER DRIFT {slot}: config={cfg_n} live={live_n} "
                  f"-- value numbers are derived from this and are WRONG until reconciled")
        live_teams = int(settings.get("teams", cfg.num_teams))
        if live_teams != cfg.num_teams:
            print(f"  !! TEAM COUNT DRIFT: config={cfg.num_teams} live={live_teams}")

    try:
        while True:
            if args.simulate:
                picks = _simulate_picks(board, cfg, args.simulate)
            else:
                assert adapter is not None and draft_id is not None
                picks = parse_picks(adapter.get_draft_picks(draft_id))
            view = compute_view(board, picks, args.slot, cfg, rounds)
            _render_live(view, args.slot)
            if not args.watch:
                break
            time.sleep(args.watch)
    finally:
        if adapter is not None:
            adapter.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    cfg = _load(args.league)
    serve(
        cfg, host=args.host, port=args.port, draft_id=args.draft_id,
        slot=args.slot, user_name=args.user,
    )
    return 0


def cmd_cheatsheet(args: argparse.Namespace) -> int:
    from .draft import build_board
    from .draft.cheatsheet import build_cheatsheet, render_csv, render_html
    from .snapshot import SNAPSHOTS_DIR, today_utc

    cfg = _load(args.league)
    date = args.date or today_utc()
    print(f"Building cheat sheet for [{cfg.key}] {cfg.name} (value={cfg.value_metric})...")
    board = build_board(cfg)
    cs = build_cheatsheet(board, cfg, date)

    out_dir = SNAPSHOTS_DIR.parent / "cheatsheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{cfg.key}_{date}.csv"
    html_path = out_dir / f"{cfg.key}_{date}.html"
    csv_path.write_text(render_csv(cs), encoding="utf-8")
    html_path.write_text(render_html(cs), encoding="utf-8")

    tiers = {pos: (tps[-1].tier if tps else 0) for pos, tps in cs.by_position.items()}
    drafted = [e for e in cs.overall if e.adp_rank is not None and e.adp_rank <= 200]
    targets = sum(1 for e in drafted if (e.value or 0) >= 12)
    tier_str = ", ".join(f"{p}={t}" for p, t in tiers.items())
    print(f"  {len(cs.overall)} players; tiers/pos: {tier_str}")
    print(f"  {targets} targets within ADP top-200 (of {len(drafted)} drafted-range players)")
    print(f"  CSV  -> {csv_path}")
    print(f"  HTML -> {html_path}")
    return 0


def cmd_crosswalk(args: argparse.Namespace) -> int:
    from .adapters.sleeper import SleeperAdapter
    from .crosswalk import Crosswalk

    cfg = _load(args.league)
    if cfg.platform.value != "sleeper":
        raise SystemExit("crosswalk currently supports Sleeper leagues only")

    print(f"Resolving [{cfg.key}] players to nflverse gsis_id...")
    with SleeperAdapter() as sleeper:
        lines = sleeper.raw_player_lines(cfg)
    report = Crosswalk.from_nflverse().resolve_all(lines)

    counts = report.source_counts()
    print(f"\n{len(report.resolved)} players  |  match rate {report.match_rate:.1%}")
    for src in ("catalog", "ff_playerids", "unmatched"):
        print(f"  {src:<13} {counts.get(src, 0)}")

    if report.unmatched:
        print(f"\nUnmatched ({len(report.unmatched)}) -- rookies / D-ST / id churn (sample):")
        for player in report.unmatched[: args.show_unmatched]:
            print(f"  {player.sleeper_id:<8} {player.primary_position:<4} {player.name}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    from .snapshot import (
        SNAPSHOTS_DIR,
        FantasyProsRankingsSource,
        SleeperProjectionsSource,
        SnapshotSource,
        run,
    )

    leagues = load_all_leagues()
    season = args.season or max(cfg.season for cfg in leagues.values())
    positions = sorted({p for cfg in leagues.values() for p in cfg.positions})

    sources: list[SnapshotSource] = []
    if "sleeper" in args.sources:
        sources.append(SleeperProjectionsSource(season, positions))
    if "rankings" in args.sources:
        sources.append(FantasyProsRankingsSource())

    print(f"Snapshotting {[s.name for s in sources]} (season {season}) ...")
    results = run(sources, date=args.date, force=args.force)
    for r in results:
        status = "skipped (exists)" if r.skipped else f"{r.rows} rows -> {r.path}"
        print(f"  {r.source:<22} {status}")
    print(f"\nArchive root: {SNAPSHOTS_DIR}")
    return 0


def cmd_anchoring(args: argparse.Namespace) -> int:
    from .adapters.espn import EspnAdapter
    from .analysis.anchoring import (
        DIVERGENCE_MIN,
        MIN_DIVERGENT,
        RANK_HORIZON,
        build_report,
    )

    cfg = _load(args.league)
    if cfg.platform.value != "espn":
        raise SystemExit("anchoring reads ESPN's per-season served ranks; ESPN leagues only")

    print(f"Opponent anchoring -- [{cfg.key}] {cfg.name}")
    with EspnAdapter() as espn:
        report = build_report(espn, cfg, me=args.me)

    print(f"  seasons: {', '.join(str(s) for s in report.seasons)}"
          + (f"  (excluded: {', '.join(str(s) for s in report.excluded_seasons)} "
             f"-- ESPN serves no ranks)" if report.excluded_seasons else ""))
    print(f"  {report.total_picks} picks, {report.coverage:.1%} usable "
          f"({report.unranked_picks} outside the board's dense range)")
    print(f"  ranks past {RANK_HORIZON:.0f} excluded: ESPN's tail runs to 2687 and is a "
          f"placeholder, not an ordering")
    print(f"  a pick counts as discriminating when the two boards differ by "
          f">= {DIVERGENCE_MIN:.0f} ranks; a seat needs {MIN_DIVERGENT} of them to be labelled")

    print(f"\n{'seat':<6} {'picks':>5} {'ranked':>7} {'disc':>5} "
          f"{'sp(STD)':>8} {'sp(PPR)':>8} {'mad(STD)':>9} {'mad(PPR)':>9} "
          f"{'edge':>7} {'±1.96se':>8}  reads like")
    for s in report.seats:
        print(f"{s.abbrev[:6]:<6} {s.picks:>5} {s.ranked_picks:>7} {s.divergent:>5} "
              f"{s.spearman_standard:>+8.3f} {s.spearman_ppr:>+8.3f} "
              f"{s.mad_standard:>9.1f} {s.mad_ppr:>9.1f} "
              f"{s.edge:>+7.1f} {1.96 * s.stderr:>8.1f}  {s.label}")

    print("\n  edge = mean(|PPR rank - pick|) - mean(|STANDARD rank - pick|) over "
          "discriminating picks.")
    print("  positive => the seat's choices track ESPN's own board; negative => a PPR board.")

    positive, n_seats, p = report.room_lean()
    print(f"\n  room lean: {positive}/{n_seats} seats toward ESPN's board "
          f"(sign test p = {p:.3f})")

    exploitable = report.exploitable()
    print("\nVERDICT")
    if exploitable:
        seats = ", ".join(f"{s.abbrev} ({s.edge:+.1f})" for s in exploitable)
        print(f"  {len(exploitable)} seat(s) read as PPR-anchored: {seats}")
        print("  These undervalue pure rushing backs -- a PPR board pays receiving backs for")
        print("  catches this league pays RBs nothing for. That is the archetype to take late.")
    else:
        print("  No seat resolves as PPR-anchored at 95%.")
        print("  On this room, the RB-reception split is NOT an exploitable ranking edge:")
        print("  ESPN's STANDARD board already prices the archetype correctly, and every")
        print("  opponent's behaviour is consistent with reading it.")
    unclassified = [s for s in report.seats if s.label == "unclassified"]
    if unclassified:
        thin = [s for s in unclassified if s.divergent < MIN_DIVERGENT]
        print(f"  {len(unclassified)} seat(s) unclassified"
              + (f" ({len(thin)} for want of discriminating picks)" if thin else "")
              + " -- reported as such rather than forced.")
    return 0


def cmd_rank_check(args: argparse.Namespace) -> int:
    from .analysis.rankdelta import (
        MATERIAL_MOVE,
        RANK_HORIZON,
        build_report,
        load_espn_projections,
    )

    cfg = _load(args.league)
    if cfg.platform.value != "espn":
        raise SystemExit("rank-check compares against ESPN's served ranks; ESPN leagues only")

    print(f"Rank delta vs ESPN's served STANDARD board -- [{cfg.key}] {cfg.name}")
    report = build_report(load_espn_projections(cfg), cfg, top_movers=args.movers)
    print(f"  {report.population} players compared "
          f"({report.excluded_beyond_horizon} past rank {RANK_HORIZON:.0f}, "
          f"{report.excluded_unranked} unranked)")
    print("  delta = ESPN rank - our rank; positive => WE rank him earlier")
    print("  both orderings dense-ranked over the same population\n")

    print(f"  {'tier':<9} {'n':>4} {'mean':>7} {'median':>7} {'mean|d|':>8} "
          f"{'moved':>6}  {'rec (up)':>9} {'rec (down)':>11}")
    for t in report.tiers:
        if not t.n:
            continue
        print(f"  {t.label:<9} {t.n:>4} {t.mean_delta:>+7.1f} {t.median_delta:>+7.1f} "
              f"{t.mean_abs_delta:>8.1f} {t.material:>6}  "
              f"{t.mean_receptions_up:>9.1f} {t.mean_receptions_down:>11.1f}")
    print(f"\n  'moved' = players at least {MATERIAL_MOVE} ranks from ESPN's placement.")
    print("  rec columns = mean projected receptions of those who moved up / down.")

    print("\n  mean delta by position:")
    for t in report.tiers:
        if t.by_position:
            cells = "  ".join(f"{p}{d:+.0f}" for p, d in sorted(t.by_position.items()))
            print(f"    {t.label:<9} {cells}")

    print("\nBiggest RISERS in ranks 25-120 (we rank earlier than ESPN):")
    print(f"  {'player':<24} {'pos':<4} {'espn':>5} {'ours':>5} {'delta':>6} {'rec':>6}")
    for m in report.risers:
        print(f"  {m.name[:24]:<24} {m.position:<4} {m.espn_rank:>5} {m.our_rank:>5} "
              f"{m.delta:>+6} {m.receptions:>6.1f}")
    print("\nBiggest FALLERS in ranks 25-120 (ESPN ranks them earlier):")
    print(f"  {'player':<24} {'pos':<4} {'espn':>5} {'ours':>5} {'delta':>6} {'rec':>6}")
    for m in report.fallers:
        print(f"  {m.name[:24]:<24} {m.position:<4} {m.espn_rank:>5} {m.our_rank:>5} "
              f"{m.delta:>+6} {m.receptions:>6.1f}")

    print("\n  Spearman(receptions, delta) WITHIN position -- the actual test of the")
    print("  reception hypothesis. Across positions it is confounded; inside one, if")
    print("  uncredited catches are what move players, this is strongly positive.")
    for t in report.tiers:
        if t.reception_corr:
            cells = "  ".join(
                f"{p} {c:+.2f}(n={n})" for p, (c, n) in sorted(t.reception_corr.items())
            )
            print(f"    {t.label:<9} {cells}")

    diverges = report.diverges()
    driven = report.reception_driven()
    print("\nVERDICT")
    if diverges and driven:
        moved = ", ".join(f"{p} |r|={c:.2f}" for p, c in sorted(driven.items()))
        print("  The boards DIVERGE sharply in the middle rounds, and part of that movement")
        print(f"  IS reception-driven, in the direction the scoring predicts: {moved}.")
        print("")
        print("  WR/TE are paid 0.5 a catch on our board and ESPN's ordering credits catches")
        print("  at every position, so high-volume receivers move UP for us and pass-catching")
        print("  backs -- paid 0.0 -- move DOWN. Both signs came out as predicted.")
        print("")
        print("  B1 says this room drafts ESPN's ordering. So the edge IS live, in rounds")
        print("  3-10, and it is WITHIN position, not across:")
        print("    * among WRs at a similar ESPN rank, take the high-reception possession")
        print("      receiver over the low-volume deep threat;")
        print("    * among RBs, fade the pass-catching back and prefer the pure rusher.")
        print("")
        print("  NOT established here: the whole-position moves (QB and TE rising as blocks)")
        print("  are VORP-vs-market structure, not receptions, and this gate says nothing")
        print("  about which of those two is right. Do not draft off those.")
    elif diverges:
        print("  The boards DIVERGE sharply in the middle rounds -- but NOT over receptions.")
        print("  The movement is POSITIONAL: whole positions shift together, and within a")
        print("  position catching more does not move you up in the direction the scoring")
        print("  predicts. That is VORP structure disagreeing with ESPN's market ordering.")
        print("  This gate does NOT establish who is right. Do not draft off it.")
    else:
        print("  The boards AGREE through the middle rounds too, not just at the top.")
        print("  Combined with B1 (all seven seats read as ESPN-anchored), the scoring")
        print("  split is NOT an exploitable ranking edge against this room at any tier.")
    return 0


def cmd_draft_quality(args: argparse.Namespace) -> int:
    from .adapters.espn import EspnAdapter
    from .analysis.draftquality import build_report

    cfg = _load(args.league)
    if cfg.platform.value != "espn":
        raise SystemExit("draft-quality reads ESPN season history; ESPN leagues only")

    print(f"Draft quality -- [{cfg.key}] {cfg.name}")
    with EspnAdapter() as espn:
        report = build_report(espn, cfg)

    print(f"  seasons: {', '.join(str(s) for s in report.seasons)}")
    print(f"  {report.total_picks} picks, {report.coverage:.1%} with a realized season total "
          f"({report.unscored_picks} unscored, counted not zeroed)")
    print("  points = sum of realized points of everyone the seat DRAFTED, that season's scoring")
    print("  ignores waivers, trades and start/sit -- it measures the draft, not the season\n")

    print("C1 -- per season (rank 1 = best draft)")
    for season in report.seasons:
        rows = sorted(
            (s for s in report.seat_seasons if s.season == season), key=lambda s: s.draft_rank
        )
        print(f"\n  {season}   {'seat':<6} {'pts':>8} {'n':>4}  {'draft#':>6} {'finish':>7} "
              f"{'W-L':>6} {'pts for':>8}")
        for s in rows:
            print(f"        {s.abbrev[:6]:<6} {s.points:>8.0f} {s.scored:>4}  {s.draft_rank:>6} "
                  f"{s.standing:>7} {f'{s.wins}-{s.losses}':>6} {s.points_for:>8.0f}")

    print("\nC1 -- across seasons (mean draft rank, lower is better)")
    print(f"  {'seat':<6} {'n':>3} {'mean':>6} {'sd':>6} {'best':>5} {'worst':>6} "
          f"{'mean finish':>12}")
    for c in report.careers:
        print(f"  {c.abbrev[:6]:<6} {c.seasons:>3} {c.mean_draft_rank:>6.2f} "
              f"{c.stdev_draft_rank:>6.2f} {c.best:>5} {c.worst:>6} {c.mean_standing:>12.2f}")

    print("\nC2 -- does drafting well predict finishing well?")
    print(f"  {'scope':<10} {'rho(draft, finish)':>20} {'rho(draft, points for)':>24} {'n':>5}")
    for scope in [str(s) for s in report.seasons] + ["pooled"]:
        st = report.corr_standing.get(scope)
        pt = report.corr_points.get(scope)
        if st is None or pt is None:
            continue
        print(f"  {scope:<10} {st[0]:>+20.3f} {pt[0]:>+24.3f} {st[1]:>5}")
    print("\n  Both are Spearman over ranks where 1 is best, so POSITIVE means drafting well")
    print("  goes with finishing well. Zero means the draft did not decide the season.")

    fin_mean, fin_hw, n_seasons = report.season_level("standing")
    pts_mean, pts_hw, _ = report.season_level("points")
    print("\n  The pooled row counts one season's evidence eight times: within a season the")
    print("  eight draft ranks are a permutation and so are the finishes, so the seats are")
    print("  not independent. Seasons are. Treating each season as ONE observation:")
    print(f"    rho(draft, finish)     = {fin_mean:+.3f}  95% CI "
          f"[{fin_mean - fin_hw:+.3f}, {fin_mean + fin_hw:+.3f}]  (n={n_seasons} seasons)")
    print(f"    rho(draft, points for) = {pts_mean:+.3f}  95% CI "
          f"[{pts_mean - pts_hw:+.3f}, {pts_mean + pts_hw:+.3f}]  (n={n_seasons} seasons)")

    print("\nWHAT IT SIZES")
    crosses_zero = (fin_mean - fin_hw) <= 0 <= (fin_mean + fin_hw)
    if crosses_zero:
        print(f"  Drafting well LOOKS like it goes with finishing well ({fin_mean:+.3f}), but")
        print("  with five seasons the interval crosses zero -- this cannot distinguish a real")
        print("  moderate relationship from none at all. The per-season numbers show why: they")
        print("  run from -0.17 to +0.98. One season carries the mean.")
        print("")
        print("  So this does NOT establish that draft edge decides seasons here, and it does")
        print("  not establish that it doesn't. It is underpowered, and five seasons of an")
        print("  eight-team league is all the data that exists. Widening the corpus (B3) is")
        print("  the only way to sharpen it, and that can run after the draft.")
    elif fin_mean > 0:
        print(f"  Drafting well goes with finishing well: {fin_mean:+.3f}, interval clear of")
        print("  zero. Draft edge is worth having in this league.")
    else:
        print(f"  Drafting well goes with finishing WORSE: {fin_mean:+.3f}, interval clear of")
        print("  zero. That is strange enough to audit before believing.")
    if pts_mean > fin_mean:
        print("")
        print(f"  Note the draft tracks POINTS ({pts_mean:+.3f}) more closely than it tracks")
        print(f"  STANDINGS ({fin_mean:+.3f}). A better draft scores more; converting that into")
        print("  wins runs through a schedule nobody controls.")
    return 0


def cmd_refresh_data(args: argparse.Namespace) -> int:
    """Pull every input the board needs and write it to disk.

    This is the only command that is *supposed* to depend on the network. Everything else
    reads what this leaves behind, which is what makes an offline board build possible --
    and draft night survivable when a third-party URL 404s at 8:35pm, as one already did.

    It refreshes by building each league's board, so the cache ends up holding exactly the
    sources `serve` will ask for, at exactly the seasons it will ask for them. A list of
    keys maintained by hand would drift from that the first time the board changed.
    """
    from .adapters import nflverse, sleeper
    from .adapters.cache import FrameCache
    from .adapters.sleeper import SleeperAdapter
    from .draft import build_board

    leagues = load_all_leagues()
    targets = [leagues[args.league]] if args.league else list(leagues.values())

    print("Refreshing the on-disk data cache (this is the network-dependent step)...")
    with SleeperAdapter() as adapter:
        catalog = adapter.get_players_catalog(force=True)
    print(f"  sleeper players catalog: {len(catalog)} players")

    sleeper.PROJECTIONS_REFRESH = True
    try:
        with nflverse.refreshing():
            for cfg in targets:
                board = build_board(cfg)
                print(f"  [{cfg.key}] board rebuilt: {len(board.entries)} players")
    finally:
        sleeper.PROJECTIONS_REFRESH = False

    entries = FrameCache().manifest()
    print(f"\n{len(entries)} nflverse source(s) on disk:")
    for key, entry in sorted(entries.items()):
        print(f"  {key:<28} {entry.rows:>8} rows  {entry.source}")
    print(f"\nCache root: {FrameCache().root.parent}")
    print("`serve` will now build a board from disk, with or without a network.")
    return 0


def _fmt_flags(flags: tuple[str, ...]) -> str:
    return " ".join(flags)


def cmd_draft(args: argparse.Namespace) -> int:
    from .draft import build_board
    from .draft.board import SLEEPER_SOURCED_CAVEAT

    cfg = _load(args.league)
    print(f"Building draft board for [{cfg.key}] {cfg.name}")
    print(f"  ranking = consensus -> league-exact VORP; value = {cfg.value_metric} vs ADP")
    print("  opportunity (opp+/opp-/riser/vac) is an OVERLAY tilt, not the ranking")
    if cfg.platform.value != "sleeper":
        print(SLEEPER_SOURCED_CAVEAT)
    board = build_board(cfg)

    models: dict[str, int] = {}
    for e in board.entries:
        models[e.model] = models.get(e.model, 0) + 1
    model_str = ", ".join(f"{k}={v}" for k, v in models.items())
    print(f"\n{len(board.entries)} players  |  models: {model_str}")

    hdr = (
        f"  {'#':>3} {'player':<24} {'pos':<4} {'tm':<3} "
        f"{'proj':>6} {'vorp':>6} {'adp':>6} {'val':>5}  notes"
    )
    print(f"\nTop {args.top} by VORP on consensus (value of record):")
    print(hdr)
    for e in board.entries[: args.top]:
        adp = f"{e.adp:.0f}" if e.adp is not None else "-"
        val = f"{e.value:+d}" if e.value is not None else "-"
        notes = (e.model if e.model != "consensus" else "") + " " + _fmt_flags(e.flags)
        print(
            f"  {e.vorp_rank:>3} {e.name[:24]:<24} {e.position:<4} {(e.team or '-'):<3} "
            f"{e.points:>6.1f} {e.vorp:>6.1f} {adp:>6} {val:>5}  {notes.strip()}"
        )

    ranked = [e for e in board.entries if e.value is not None and e.adp_rank is not None]
    in_market = [e for e in ranked if e.adp_rank is not None and e.adp_rank <= args.market]
    targets = sorted(in_market, key=lambda e: -(e.value or 0))
    fades = sorted(in_market, key=lambda e: (e.value or 0))
    print(f"\nBiggest TARGETS (market underpricing, ADP top {args.market}):")
    for e in targets[: args.movers]:
        print(
            f"  {e.name[:24]:<24} {e.position:<4} vorp#{e.vorp_rank:<3} "
            f"adp#{e.adp_rank:<3} value {e.value:+d}  {_fmt_flags(e.flags)}"
        )
    print(f"\nBiggest FADES (market overpricing, ADP top {args.market}):")
    for e in fades[: args.movers]:
        print(
            f"  {e.name[:24]:<24} {e.position:<4} vorp#{e.vorp_rank:<3} "
            f"adp#{e.adp_rank:<3} value {e.value:+d}  {_fmt_flags(e.flags)}"
        )
    return 0


def _mm(m: object) -> str:
    return f"sp={m.spearman:+.3f} mae={m.mae:5.0f} hit={m.hit_rate:.2f}"  # type: ignore[attr-defined]


def cmd_backtest(args: argparse.Namespace) -> int:
    from .backtest import run_fold

    cfg = _load(args.league)
    print(f"Backtest fold {args.prior}->{args.cur}  [{cfg.key}] {cfg.name}")
    fr = run_fold(cfg, args.prior, args.cur, market=args.market)

    print(f"\nPopulation: {fr.population} veterans (>= 6 prior games)")
    print(f"\nProjection vs actual {args.cur}  (baseline | consensus | [IDP model]):")
    for pos, mms in fr.per_position.items():
        print(f"  {pos:<4} n={mms[0].n:<4} " + " | ".join(_mm(m) for m in mms))
    if fr.overall_offense:
        o = fr.overall_offense
        print(f"  OFF  n={o[0].n:<4} {_mm(o[0])} | {_mm(o[1])}")

    idp = [p for p in ("DL", "LB", "DB") if p in fr.per_position]
    if idp:
        print("\nIDP gate (tackle model must beat BOTH baseline + consensus OOS to rank on it):")
        for pos in idp:
            by = {m.method: m for m in fr.per_position[pos]}
            if "model" not in by:
                continue
            mdl, base, cons = by["model"], by["baseline"], by["consensus"]
            clears = mdl.spearman > cons.spearman and mdl.spearman > base.spearman
            print(f"  {pos}: model {mdl.spearman:+.3f}  consensus {cons.spearman:+.3f}  "
                  f"baseline {base.spearman:+.3f}  -> {'MODEL' if clears else 'stay consensus'}")

    mt, mf, edge, nt, nf = fr.value_edge_scarcity
    vmt, vmf, vedge, vnt, vnf = fr.value_edge_vorp
    print(f"\nValue layer (on consensus; ADP top {args.market}; targets vs fades, mean actual):")
    print(f"  scarcity/VONA (§6): {mt:6.1f} (n={nt}) vs {mf:6.1f} (n={nf})  edge {edge:+.1f}")
    print(f"  raw VORP:           {vmt:6.1f} (n={vnt}) vs {vmf:6.1f} (n={vnf})  edge {vedge:+.1f}")
    print(f"  -> better value metric this fold: {'scarcity/VONA' if edge > vedge else 'raw VORP'}")

    m = fr.mobile_qb
    if int(m.get("n", 0)) >= 3:
        print(f"\nMobile QBs (>=300 prior rush yds, n={int(m['n'])}) -- consensus handling:")
        print(f"  mean actual={m['mean_actual']:.0f}  consensus={m['mean_consensus']:.0f}  "
              f"MAE={m['consensus_mae']:.0f} (sp {m['consensus_spearman']:+.2f})")

    print("\nGate: consensus is the projection of record (opportunity stays an overlay tilt);")
    print("      the value layer ships per league only where its targets beat fades OOS.")

    if not args.no_write:
        print(f"\nResults table -> {_write_backtest_results(fr, args.date)}")
    return 0


def cmd_idp_stickiness(args: argparse.Namespace) -> int:
    from .adapters.sleeper import SleeperAdapter
    from .backtest.idp import IDP_POSITIONS, METRICS, STICKY_METRICS, stickiness

    cfg = _load(args.league)
    if "LB" not in cfg.positions:
        raise SystemExit("idp-stickiness needs an IDP league (League A)")

    print(f"IDP thesis test -- year-over-year stickiness [{cfg.key}] {cfg.name}")
    print(f"  seasons {args.seasons} ({len(args.seasons) - 1} folds, pooled); "
          f"players >= {args.min_games} games & >= {args.min_snaps:.0f} snaps both years")
    with SleeperAdapter() as adapter:
        res = stickiness(adapter, args.seasons, cfg, args.min_games, args.min_snaps)

    cols = list(METRICS)
    print("\n  pos   " + "  ".join(f"{c:>11}" for c in cols))
    for pos in IDP_POSITIONS:
        if (pos, cols[0]) not in res:
            continue
        cells = [f"{res[(pos, c)][0]:+.2f}({res[(pos, c)][1]})" for c in cols]
        print(f"  {pos:<4}  " + "  ".join(f"{c:>11}" for c in cells))
    print("  (Spearman(prior, next); n in parens. sticky cols: " + ", ".join(STICKY_METRICS) + ")")

    print("\nVerdict (tackle stickiness vs pure-noise INT, per position):")
    for pos in IDP_POSITIONS:
        if (pos, "solo/gm") not in res:
            continue
        solo = res[(pos, "solo/gm")][0]
        intc = res[(pos, "int/gm")][0]
        sack = res[(pos, "sack/gm")][0]
        tier = "STRONG" if solo > 0.65 else "MODERATE" if solo > 0.45 else "WEAK"
        extra = ""
        if sack > 0.45:
            extra = f"  [NB sacks also sticky {sack:+.2f} -> project, don't regress]"
        print(f"  {pos}: tackles/gm {solo:+.2f}  vs INT noise {intc:+.2f}  -> {tier}{extra}")

    # LB is the anchor: highest-value IDP in tackle scoring and the most tackle-driven role.
    lb_solo = res[("LB", "solo/gm")][0] if ("LB", "solo/gm") in res else 0.0
    confirmed = lb_solo > 0.6
    msg = (
        "CONFIRMED -- LB tackle volume is highly sticky (the core edge); build the model"
        if confirmed else "NOT confirmed -- foundation too weak; reconsider before building"
    )
    print(f"\nTHESIS: {msg}")
    return 0


def _write_backtest_results(fr: object, date: str | None) -> object:
    import polars as pl

    from .backtest.harness import FoldResult
    from .snapshot import SNAPSHOTS_DIR, today_utc

    assert isinstance(fr, FoldResult)
    stamp = date or today_utc()
    rows: list[dict[str, object]] = []
    groups = list(fr.per_position.items()) + [("OFF", fr.overall_offense)]
    for scope, mms in groups:
        for m in mms:
            rows.append({
                "captured_date": stamp, "league": fr.league_key,
                "fold": f"{fr.prior_season}->{fr.cur_season}",
                "scope": scope, "method": m.method, "n": m.n,
                "spearman": m.spearman, "mae": m.mae, "rmse": m.rmse, "hit_rate": m.hit_rate,
            })
    fname = f"{fr.league_key}_{fr.prior_season}-{fr.cur_season}_{stamp}.parquet"
    path = SNAPSHOTS_DIR / "backtest" / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audible", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("configs", help="validate + summarise league configs").set_defaults(
        func=cmd_configs
    )

    vs = sub.add_parser("verify-scoring", help="compare a Sleeper config vs the live league")
    vs.add_argument("league")
    vs.set_defaults(func=cmd_verify_scoring)

    vp = sub.add_parser("vorp", help="compute replacement baselines + VORP")
    vp.add_argument("league")
    vp.add_argument("--top", type=int, default=25, help="top-N overall (default 25)")
    vp.add_argument("--per-pos", type=int, default=5, help="top-N per position (default 5)")
    vp.set_defaults(func=cmd_vorp)

    ic = sub.add_parser(
        "injury-coverage",
        help="roster/injury field coverage over the top N by value (reports, never ranks)",
    )
    ic.add_argument("league")
    ic.add_argument("--top", type=int, default=200, help="how many by value (default 200)")
    ic.set_defaults(func=cmd_injury_coverage)
    by = sub.add_parser(
        "byes", help="bye weeks for my roster, with same-position collisions (display only)"
    )
    by.add_argument("league")
    by.add_argument("--player", default=None,
                    help="comma-separated names to look up, e.g. 'Derrick Henry,James Cook'")
    by.set_defaults(func=cmd_byes)

    xw = sub.add_parser(
        "crosswalk", help="resolve players to nflverse gsis_id (needs nflverse extra)"
    )
    xw.add_argument("league")
    xw.add_argument("--show-unmatched", type=int, default=15, help="how many unmatched to list")
    xw.set_defaults(func=cmd_crosswalk)

    sn = sub.add_parser(
        "snapshot", help="capture consensus projections/rankings (needs nflverse extra)"
    )
    sn.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    sn.add_argument(
        "--season", type=int, default=None, help="NFL season (default: latest config season)"
    )
    sn.add_argument(
        "--sources", nargs="+", default=["sleeper", "rankings"],
        choices=["sleeper", "rankings"], help="which sources to capture",
    )
    sn.add_argument("--force", action="store_true", help="overwrite an existing same-date snapshot")
    sn.set_defaults(func=cmd_snapshot)

    lv = sub.add_parser("live", help="live draft decision surface (needs nflverse extra)")
    lv.add_argument("league")
    lv.add_argument("--slot", type=int, required=True, help="your draft slot (1..teams)")
    lv.add_argument("--draft-id", default=None, help="override (default: from the league)")
    lv.add_argument("--rounds", type=int, default=18, help="draft rounds (default 18 / from draft)")
    lv.add_argument("--watch", type=int, default=0, help="poll every N seconds (0 = one-shot)")
    lv.add_argument("--simulate", type=int, default=0, help="offline demo: simulate N ADP picks")
    lv.set_defaults(func=cmd_live)

    sv = sub.add_parser("serve", help="draft-day cockpit in the browser (needs nflverse extra)")
    sv.add_argument("--league", required=True, help="league key, e.g. sleeper_boyfun")
    sv.add_argument("--slot", type=int, default=None,
                    help="override your draft slot (default: resolved once the draft opens)")
    sv.add_argument("--draft-id", default=None, help="override (default: discovered each start)")
    sv.add_argument("--user", default=None, help="your Sleeper display name, for slot resolution")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8080)
    sv.set_defaults(func=cmd_serve)

    cs = sub.add_parser(
        "cheatsheet", help="printable pre-draft cheat sheet: CSV + HTML (needs nflverse extra)"
    )
    cs.add_argument("league")
    cs.add_argument("--date", default=None, help="date stamp (default today UTC)")
    cs.set_defaults(func=cmd_cheatsheet)

    dr = sub.add_parser(
        "draft", help="opportunity-adjusted draft board vs ADP (needs nflverse extra)"
    )
    dr.add_argument("league")
    dr.add_argument("--top", type=int, default=40, help="top-N by VORP to print (default 40)")
    dr.add_argument(
        "--market", type=int, default=150, help="ADP cutoff for targets/fades (default 150)"
    )
    dr.add_argument("--movers", type=int, default=15, help="how many targets/fades to show")
    dr.set_defaults(func=cmd_draft)

    an = sub.add_parser(
        "anchoring", help="which board is each opponent drafting off? (B1)"
    )
    an.add_argument("league")
    an.add_argument("--me", type=int, default=8,
                    help="my ESPN teamId, excluded from the table (default 8)")
    an.set_defaults(func=cmd_anchoring)

    dq = sub.add_parser(
        "draft-quality", help="who drafts well, and does it predict finishing (C1/C2)"
    )
    dq.add_argument("league")
    dq.set_defaults(func=cmd_draft_quality)

    rc = sub.add_parser(
        "rank-check", help="our ordering vs ESPN's served ranks, tier by tier (B-next)"
    )
    rc.add_argument("league")
    rc.add_argument("--movers", type=int, default=12, help="risers/fallers to list")
    rc.set_defaults(func=cmd_rank_check)

    rd = sub.add_parser(
        "refresh-data", help="pull every board input to disk so serve can run offline"
    )
    rd.add_argument("league", nargs="?", default=None, help="one league (default: all)")
    rd.set_defaults(func=cmd_refresh_data)

    bt = sub.add_parser("backtest", help="out-of-sample honesty gate (needs nflverse extra)")
    bt.add_argument("league")
    bt.add_argument("--prior", type=int, default=2024, help="prior season N (default 2024)")
    bt.add_argument("--cur", type=int, default=2025, help="outcome season N+1 (default 2025)")
    bt.add_argument("--market", type=int, default=150, help="ADP tier for the value test")
    bt.add_argument("--date", default=None, help="results-table date stamp (default today UTC)")
    bt.add_argument("--no-write", action="store_true", help="skip writing the results parquet")
    bt.set_defaults(func=cmd_backtest)

    st = sub.add_parser(
        "idp-stickiness", help="IDP thesis test: tackle stickiness (needs nflverse extra)"
    )
    st.add_argument("league")
    st.add_argument(
        "--seasons", type=int, nargs="+", default=[2021, 2022, 2023, 2024, 2025],
        help="seasons to pool consecutive folds over",
    )
    st.add_argument("--min-games", type=int, default=8, help="min games in both years")
    st.add_argument("--min-snaps", type=float, default=200.0, help="min defensive snaps both years")
    st.set_defaults(func=cmd_idp_stickiness)

    news = sub.add_parser("news", help="NFL news ingestion (display only; never ranks)")
    news_sub = news.add_subparsers(dest="news_command", required=True)

    np_ = news_sub.add_parser("probe", help="feed health; writes docs/feed-probe-<date>.md")
    np_.add_argument("--write", action="store_true", help="write the dated report to docs/")
    np_.set_defaults(func=cmd_news_probe)

    npo = news_sub.add_parser("poll", help="fetch, match, classify, store")
    npo.add_argument("--once", action="store_true",
                     help="accepted for symmetry; the CLI always polls once")
    npo.add_argument("--league", default="espn_davis_drive",
                     help="narrow ambiguous names to this league's board")
    npo.set_defaults(func=cmd_news_poll)

    nsh = news_sub.add_parser("show", help="recent items")
    nsh.add_argument("--player", default=None, help="full name to filter on")
    nsh.add_argument("--hours", type=float, default=48.0)
    nsh.add_argument("--min-severity", type=int, default=None, dest="min_severity")
    nsh.add_argument("--league", default="espn_davis_drive")
    nsh.set_defaults(func=cmd_news_show)

    nst = news_sub.add_parser("stats", help="counts by feed, match rate, event histogram")
    nst.set_defaults(func=cmd_news_stats)

    return parser


# --- news (additive; nothing here reads or writes a projection) -----------------------


def _news_index(args: argparse.Namespace):
    """Player index from the cached catalog, narrowed to a league roster when given."""
    from .news.entities import load_index

    roster = None
    if getattr(args, "league", None):
        from .draft.board import build_board

        cfg = load_all_leagues()[args.league]
        roster = {e.player_id for e in build_board(cfg).entries}
    return load_index(roster)


def cmd_news_probe(args: argparse.Namespace) -> int:
    """Fetch every registered feed and report what it actually serves."""
    import datetime

    from .adapters.feeds import load_feeds, probe_all

    report = probe_all(load_feeds(include_disabled=True))
    print("")
    print("Feed probe")
    print(f"  {'id':<19}{'HTTP':<6}{'parse':<13}{'items':<7}"
          f"{'newest_h':<10}{'etag':<6}{'lastmod':<8}content-type")
    for r in sorted(report.results, key=lambda r: r.feed_id):
        newest = f"{r.newest_age_h:.1f}" if r.newest_age_h is not None else "-"
        print(f"  {r.feed_id:<19}{str(r.status or r.error or '-')[:5]:<6}{r.parses:<13}"
              f"{r.items:<7}{newest:<10}{'yes' if r.etag else 'no':<6}"
              f"{'yes' if r.last_modified else 'no':<8}{r.content_type[:34]}")
    healthy = report.healthy
    print("")
    print(f"  healthy (parses, has items, newest < 24h): {len(healthy)}/{len(report.results)}")
    print(f"  G3 (>= 2 healthy feeds): {'PASS' if report.gate_g3() else 'FAIL'}")

    if args.write:
        out = Path("docs") / f"feed-probe-{datetime.date.today().isoformat()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# Feed probe - {datetime.date.today().isoformat()}",
            "",
            "Unconditional GET of every registered feed, including disabled ones.",
            "`enabled` in `config/feeds.toml` is set from this, never by hand.",
            "",
            "| feed | HTTP | parses | items | newest (h) | ETag | Last-Modified |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in sorted(report.results, key=lambda r: r.feed_id):
            newest = f"{r.newest_age_h:.1f}" if r.newest_age_h is not None else "-"
            lines.append(
                f"| `{r.feed_id}` | {r.status or r.error or '-'} | {r.parses} | "
                f"{r.items} | {newest} | {'yes' if r.etag else 'no'} | "
                f"{'yes' if r.last_modified else 'no'} |"
            )
        lines.append("")
        lines.append(f"**Healthy: {len(healthy)}/{len(report.results)}**. "
                     f"G3 (>= 2 healthy) {'PASS' if report.gate_g3() else 'FAIL'}.")
        lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"  wrote {out}")
    return 0 if report.gate_g3() else 1


def cmd_news_poll(args: argparse.Namespace) -> int:
    from .news.poll import poll_once
    from .news.store import NewsStore

    store = NewsStore()
    try:
        index = _news_index(args)
    except RuntimeError as exc:
        print(f"  [!] {exc}")
        index = None
    results = poll_once(store=store, index=index)
    total_new = sum(r.inserted for r in results)
    print("")
    print(f"  {'feed':<19}{'fetched':<9}{'new':<6}{'dupe':<6}{'matched':<9}error")
    for r in results:
        print(f"  {r.feed_id:<19}{r.fetched:<9}{r.inserted:<6}{r.skipped:<6}"
              f"{r.matched:<9}{r.error or ''}")
    print("")
    print(f"  {total_new} new item(s) stored at {store.path}")
    return 0


def cmd_news_show(args: argparse.Namespace) -> int:
    import time as _time

    from .news.store import NewsStore

    store = NewsStore()
    index = None
    player_id = None
    try:
        index = _news_index(args)
    except RuntimeError:
        index = None
    if args.player:
        if index is None:
            print("  no cached catalog; cannot resolve a name")
            return 1
        player_id = index.lookup_full(args.player)
        if player_id is None:
            print(f"  no unique player matched {args.player!r}")
            return 1
    items = store.recent(hours=args.hours, player_id=player_id,
                         min_severity=args.min_severity)
    if not items:
        print("  nothing in that window")
        return 0
    now = _time.time()
    for it in items:
        when = it.published_at or it.fetched_at
        age = (now - when) / 3600.0
        who = ""
        if it.player_id:
            who = f"  [{index.display_name(it.player_id) if index else it.player_id}]"
        print(f"  {age:>5.1f}h  {(it.event_type or '-'):<20}s{it.severity or 0}  "
              f"{it.title[:88]}{who}")
    print("")
    print(f"  {len(items)} item(s)")
    return 0


def cmd_news_stats(_args: argparse.Namespace) -> int:
    from .news.store import NewsStore

    s = NewsStore().stats()
    print("")
    print(f"  items {s['total']}  matched {s['matched']} "
          f"({100 * s['match_rate']:.1f}%)  db {s['db_bytes'] / 1e6:.2f} MB")
    if s["oldest"] and s["newest"]:
        span = (s["newest"] - s["oldest"]) / 3600.0
        print(f"  span {span:.1f}h of publication time")
    for label, counts in (("by feed", s["by_feed"]), ("by event", s["by_event"]),
                          ("by confidence", s["by_confidence"])):
        print("")
        print(f"  {label}:")
        for k, v in counts.items():
            print(f"     {k:<22}{v}")
    return 0


def cmd_injury_coverage(args: argparse.Namespace) -> int:
    """Measure roster/injury coverage over the top N by value. See docs/injury-coverage-gate.md.

    Reports, never ranks. The thresholds this is measured against were pre-registered in
    their own commit before the extraction existed.
    """
    from collections import Counter

    from .adapters.sleeper import SleeperAdapter
    from .draft import build_board

    cfg = _load(args.league)
    board = build_board(cfg)
    top = [e for e in board.entries][: args.top]
    ids = [e.player_id for e in top]
    by_id = {e.player_id: e for e in top}

    # Read straight off the cached catalog. There is deliberately NO adapter accessor for
    # these fields: this is a measurement tool, and an accessor would be a display-only API
    # for a field the measurement below says is not worth displaying. Phase 2 repoints this
    # at nflverse weekly injuries and ESPN's own injuryStatus, which is where signal lives.
    with SleeperAdapter() as sleeper:
        catalog = sleeper.get_players_catalog()
    fields = ("status", "injury_status", "injury_body_part", "injury_start_date")
    statuses: dict[str, dict[str, str | None]] = {}
    for pid in ids:
        entry = catalog.get(pid)
        if not isinstance(entry, dict):
            continue
        values = {f: (str(entry[f]) if entry.get(f) not in (None, "") else None)
                  for f in fields}
        # All-null is "no record", which is not the same as "Active". Team defences are the
        # real case -- Sleeper keys them by abbreviation and a defence cannot be on IR --
        # and collapsing the two would report health that was never observed.
        if any(v is not None for v in values.values()):
            statuses[pid] = values

    print("")
    print(f"Injury / roster coverage -- [{cfg.key}] {cfg.name}")
    print(f"  top {len(top)} by value; measured {_today()}")

    # G1: roster `status`, the field the chip is built on.
    with_status = [pid for pid in ids if statuses.get(pid, {}).get("status")]
    pct = 100.0 * len(with_status) / len(ids) if ids else 0.0
    print("")
    print(f"  G1  roster `status` non-null : {len(with_status)}/{len(ids)} = {pct:.1f}%"
          f"   (>= 95% required)  {'PASS' if pct >= 95.0 else 'FAIL'}")

    dist = Counter(statuses.get(pid, {}).get("status") or "(missing)" for pid in ids)
    print("")
    print("  status distribution:")
    for value, n in dist.most_common():
        print(f"     {value:<24}{n}")

    # G2: the negative control -- can this field ever disagree with itself?
    non_active = [pid for pid in ids
                  if statuses.get(pid, {}).get("status")
                  and statuses[pid]["status"] != "Active"]
    print("")
    print(f"  G2  non-Active players found : {len(non_active)}   (>= 3 across both leagues,"
          f" each hand-verified)")
    for pid in non_active:
        st, e = statuses[pid], by_id[pid]
        bits = [f"status={st['status']!r}"]
        for label, key in (("injury_status", "injury_status"),
                           ("body_part", "injury_body_part"),
                           ("since", "injury_start_date")):
            if st.get(key):
                bits.append(f"{label}={st[key]!r}")
        print(f"     {e.name:<26}{e.position:<5}{e.team or '--':<4}  " + "  ".join(bits))

    # G3: RECORDED, not gated. Preseason nulls are correct data -- see the gate doc.
    with_inj = [pid for pid in ids if statuses.get(pid, {}).get("injury_status")]
    null_rate = 100.0 * (len(ids) - len(with_inj)) / len(ids) if ids else 0.0
    print("")
    print(f"  G3  `injury_status` null-rate: {len(ids) - len(with_inj)}/{len(ids)} = "
          f"{null_rate:.1f}%   (RECORDED, not gated)")
    inj_dist = Counter(statuses[pid]["injury_status"] for pid in with_inj)
    for value, n in inj_dist.most_common():
        print(f"     {str(value):<24}{n}")
    if not with_inj:
        print("     (none -- expected before Week 1; official game-status designations")
        print("      come out of the weekly practice-report cycle. Re-measure from 2026-09-09.)")
    return 0 if pct >= 95.0 else 1


def _today() -> str:
    import datetime

    return datetime.date.today().isoformat()

def cmd_byes(args: argparse.Namespace) -> int:
    """Bye weeks for my roster, grouped, with same-position collisions flagged.

    Display only. Nothing here reads or writes a projection, and the derivation refuses to
    answer at all unless it passes its own consistency check -- a wrong bye is the kind of
    error someone plans a month of lineups around.
    """
    from .draft import build_board
    from .draft.board import DraftEntry
    from .draft.service import CockpitService
    from .server.state import bye_consistency

    cfg = _load(args.league)
    report = bye_consistency(cfg.season)

    print("")
    print(f"Bye weeks {cfg.season} -- derived from schedule absence")
    print(f"  B1 exactly 32 teams          : {report['teams']}  "
          f"{'PASS' if report['b1'] else 'FAIL'}")
    print(f"  B2 one bye per team          : "
          f"{'PASS' if report['b2'] else 'FAIL ' + str(report['multi_bye'])}")
    print(f"  B3 inside the plausible window: "
          f"{'PASS' if report['b3'] else 'FAIL ' + str(report['outside_window'])}")
    print(f"  B4 games == playing/2 each wk : "
          f"{'PASS' if report['b4'] else 'FAIL ' + str(report['week_mismatch'])}")
    on_bye = {w: n for w, n in report["per_week"].items() if n}
    print(f"  teams on bye by week          : {on_bye}")
    if not report["ok"]:
        print("")
        print("  Derivation failed its own check. Refusing to report byes.")
        return 1

    byes = report["byes"]
    board = build_board(cfg)
    by_id = {e.player_id: e for e in board.entries}
    service = CockpitService(cfg)
    service.board = board
    service.restore()
    mine = service.session.slot

    rostered = []
    for pick in service.session.effective_picks():
        if mine is not None and pick.draft_slot != mine:
            continue
        entry = by_id.get(pick.player_id)
        if entry is None:
            continue
        rostered.append(entry)

    print("")
    print(f"[{cfg.key}] {cfg.name} -- slot {mine}, {len(rostered)} rostered")
    if not rostered:
        print("  no saved roster for this league; nothing to group")
        return 0

    grouped: dict[int | None, list[DraftEntry]] = {}
    for entry in rostered:
        grouped.setdefault(byes.get(entry.team or ""), []).append(entry)

    for week in sorted(grouped, key=lambda w: (w is None, w or 0)):
        label = f"week {week}" if week is not None else "no bye derived"
        players = sorted(grouped[week], key=lambda e: (e.position, e.name))
        print("")
        print(f"  {label}  ({len(players)})")
        for e in players:
            print(f"     {e.name:<26}{e.position:<5}{e.team or '--'}")
        by_pos: dict[str, list[str]] = {}
        for e in players:
            by_pos.setdefault(e.position, []).append(e.name)
        for position, names in sorted(by_pos.items()):
            if len(names) > 1 and week is not None:
                print(f"     ** COLLISION: {len(names)} x {position} share week {week} -- "
                      + ", ".join(sorted(names)))

    if args.player:
        print("")
        wanted = [w.strip().lower() for w in args.player.split(",")]
        for name in wanted:
            hit = next((e for e in board.entries if e.name.lower() == name), None)
            if hit is None:
                print(f"  {name!r}: not on the board")
                continue
            print(f"  {hit.name:<26}{hit.position:<5}{hit.team or '--':<5}"
                  f"bye week {byes.get(hit.team or '', '?')}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    from .adapters.espn import EspnAuthError, EspnDataError

    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (EspnAuthError, EspnDataError) as exc:
        # Cookie expiry is routine and the fix is a two-minute copy-paste. A traceback
        # buries that; the message is the whole point.
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
