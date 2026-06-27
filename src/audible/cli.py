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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
