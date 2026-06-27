"""audible CLI -- Phase 0 surface.

  audible configs                      validate + summarise every league config
  audible verify-scoring <key>         compare a Sleeper config vs the live league
  audible vorp <key> [--top N]         compute per-position replacement + VORP (the milestone)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .config import LeagueConfig, load_all_leagues
from .value import VorpEntry, compute_vorp

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


def cmd_verify_scoring(args: argparse.Namespace) -> int:
    from .adapters.sleeper import SleeperAdapter

    cfg = _load(args.league)
    if cfg.platform.value != "sleeper":
        raise SystemExit("verify-scoring currently supports Sleeper leagues only")
    with SleeperAdapter() as sleeper:
        drift = sleeper.verify_scoring(cfg)
    if not drift:
        print(f"[{cfg.key}] config scoring is FAITHFUL to the live league "
              f"({len(cfg.scoring)} keys match).")
        return 0
    print(f"[{cfg.key}] SCORING DRIFT -- {len(drift)} key(s) differ (config vs live):")
    for key, cfg_val, live_val in drift:
        print(f"   {key:<18} config={cfg_val!s:<8} live={live_val!s}")
    return 1


def _print_top(entries: Sequence[VorpEntry], n: int) -> None:
    print(f"  {'#':>3}  {'player':<26} {'pos':<4} {'team':<4} {'proj':>7} {'vorp':>7}  start")
    for i, e in enumerate(entries[:n], 1):
        p = e.projection
        print(
            f"  {i:>3}  {p.name[:26]:<26} {p.primary_position:<4} {(p.team or '-'):<4} "
            f"{p.points:>7.1f} {e.vorp:>7.1f}  {'*' if e.is_starter else ''}"
        )


def cmd_vorp(args: argparse.Namespace) -> int:
    from .providers import build_consensus_provider

    cfg = _load(args.league)
    if cfg.platform.value != "sleeper":
        raise SystemExit("vorp currently supports Sleeper leagues only (ESPN adapter is Phase 1)")

    print(f"Pulling consensus projections for [{cfg.key}] {cfg.name} (season {cfg.season})...")
    with build_consensus_provider(cfg) as provider:
        players = provider.projections(cfg)
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


def _fmt_flags(flags: tuple[str, ...]) -> str:
    return " ".join(flags)


def cmd_draft(args: argparse.Namespace) -> int:
    from .draft import build_board

    cfg = _load(args.league)
    print(f"Building draft board for [{cfg.key}] {cfg.name}")
    print(f"  ranking = consensus -> league-exact VORP; value = {cfg.value_metric} vs ADP")
    print("  opportunity (opp+/opp-/riser/vac) is an OVERLAY tilt, not the ranking")
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
    print(f"\nProjection of record vs actual {args.cur}  (naive baseline | consensus):")
    for pos, mms in fr.per_position.items():
        print(f"  {pos:<4} n={mms[0].n:<4} {_mm(mms[0])} | {_mm(mms[1])}")
    if fr.overall_offense:
        o = fr.overall_offense
        print(f"  OFF  n={o[0].n:<4} {_mm(o[0])} | {_mm(o[1])}")

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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
